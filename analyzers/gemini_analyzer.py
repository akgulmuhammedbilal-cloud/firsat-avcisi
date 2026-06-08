"""AI karar motoru: Gemini implementasyonu + anahtar gerektirmeyen DryRun.

Gemini, zorunlu JSON çıktısı için response_mime_type=application/json ile çağrılır.
Parse/ağ hatasında güvenli tarafta kalınır: ilan reddedilir (yanlış pozitif yerine).
"""
from __future__ import annotations

import json
import logging
import re
import time

from analyzers import spec_validator
from analyzers.base_analyzer import (
    RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
    LLMAnalyzer,
    build_user_prompt,
)
from storage.models import AnalysisResult, RawDeal

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

_BOOL_KEYS = {"approved", "needs_manual_review"}
_INT_KEYS = {"confidence_score", "deal_score"}
_FLOAT_KEYS = {"estimated_normal_price"}


def _coerce(data: dict) -> AnalysisResult:
    """LLM'den gelen ham dict'i AnalysisResult'a güvenli biçimde dönüştürür."""
    result = AnalysisResult()
    for key, value in data.items():
        if not hasattr(result, key):
            continue
        if key in _BOOL_KEYS:
            value = bool(value) if not isinstance(value, str) else value.strip().lower() in ("true", "1", "evet", "yes")
        elif key in _INT_KEYS:
            try:
                value = int(round(float(value)))
            except (TypeError, ValueError):
                value = 0
        elif key in _FLOAT_KEYS:
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = None
        setattr(result, key, value)
    return result


def parse_llm_json(text: str) -> AnalysisResult:
    """LLM metnini (gerekirse code-fence temizleyerek) JSON'a çözer."""
    cleaned = _FENCE_RE.sub("", (text or "").strip())
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("JSON kök nesnesi bir obje değil")
    return _coerce(data)


class GeminiAnalyzer(LLMAnalyzer):
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash",
                 temperature: float = 0.1, timeout_seconds: int = 60) -> None:
        from google import genai  # lazily import; sadece gerçek modda gerekir
        from google.genai import types

        self._genai = genai
        self._types = types
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.timeout_ms = timeout_seconds * 1000

    # Geçici hatalar (yoğun talep / hız limiti) — yeniden denenebilir.
    _RETRYABLE = ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "500", "INTERNAL")
    _MAX_RETRIES = 3

    def _generate(self, deal: RawDeal):
        types = self._types
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=self.temperature,
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
            http_options=types.HttpOptions(timeout=self.timeout_ms),
        )
        last_exc: Exception | None = None
        for attempt in range(self._MAX_RETRIES):
            try:
                return self.client.models.generate_content(
                    model=self.model,
                    contents=build_user_prompt(deal),
                    config=config,
                )
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                if not any(code in msg for code in self._RETRYABLE):
                    raise
                last_exc = exc
                wait = 2 * (attempt + 1)  # 2s, 4s, 6s
                logger.info("Gemini geçici hata, %ds sonra yeniden (%d/%d): %s",
                            wait, attempt + 1, self._MAX_RETRIES, msg[:80])
                time.sleep(wait)
        raise last_exc  # type: ignore[misc]

    def analyze(self, deal: RawDeal) -> AnalysisResult:
        try:
            response = self._generate(deal)
            result = parse_llm_json(response.text)
        except Exception as exc:
            logger.warning("Gemini analiz hatası (%s): %s", deal.title[:60], exc)
            return AnalysisResult(
                approved=False, confidence_score=0,
                rejection_reason="AI analiz/parse hatası", reason="AI hatası",
                needs_manual_review=True,
            )
        result.needs_manual_review = spec_validator.needs_manual_review(result)
        return result


class DryRunAnalyzer(LLMAnalyzer):
    """API anahtarı olmadan uçtan uca test için kaba kural tabanlı analizör."""

    def __init__(self, reject_keywords: list[str] | None = None,
                 preferred_models: list[str] | None = None) -> None:
        self.reject_keywords = [k.lower() for k in (reject_keywords or [])]
        self.preferred_models = preferred_models or []

    def analyze(self, deal: RawDeal) -> AnalysisResult:
        text = deal.text_blob()
        lower = text.lower()
        gpu = spec_validator.detect_gpu(text) or "belirsiz"
        ram_gb = spec_validator.detect_ram_gb(text)
        ram = f"{ram_gb} GB" if ram_gb else "belirsiz"

        rejected_kw = next((k for k in self.reject_keywords if k in lower), None)
        gpu_ok = spec_validator.meets_min_gpu(text, "RTX 4060")
        model = next((m for m in self.preferred_models if m.lower() in lower), gpu)

        if rejected_kw:
            approved, reason = False, f"reddedilen anahtar kelime: {rejected_kw}"
        elif gpu_ok is False:
            approved, reason = False, "GPU minimum eşiğin altında"
        else:
            approved, reason = True, "dry-run: temel kriterler karşılanıyor"

        result = AnalysisResult(
            approved=approved,
            confidence_score=50,
            deal_score=70 if approved else 20,
            reason="[DRY-RUN] " + reason,
            detected_model=model,
            gpu=gpu,
            ram=ram,
            ram_upgradeability="belirsiz",
            case_quality="premium" if model in self.preferred_models else "belirsiz",
            display_quality="belirsiz",
            engineering_suitability="uygun" if approved else "uygun değil",
            gaming_suitability="iyi" if approved else "belirsiz",
            rejection_reason="" if approved else reason,
            estimated_normal_price=(deal.price * 1.25) if deal.price else None,
        )
        result.needs_manual_review = spec_validator.needs_manual_review(result)
        return result

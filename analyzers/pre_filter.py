"""Ucuz, kural tabanlı ön filtre.

Amaç: AI (Gemini) çağrısı yapmadan önce açıkça uygun olmayan ilanları elemek,
böylece API maliyetini düşürmek. Geçen ilanlar AI'a gönderilir.
"""
from __future__ import annotations

from dataclasses import dataclass

from analyzers import spec_validator
from storage.models import RawDeal

# Başlıkta bunlardan biri yoksa ilan büyük olasılıkla laptop değildir.
_LAPTOP_KEYWORDS = (
    "laptop", "notebook", "gaming", "workstation", "zbook", "legion",
    "zephyrus", "xps", "blade", "precision", "thinkpad", "ноут",
)

# Bu proje premium *Windows* laptop avcısıdır; aşağıdaki platformlar hedef
# dışıdır (RTX GPU yok, mühendislik yazılımı odaklı değil) → AI'a gönderilmez.
_NON_TARGET_KEYWORDS = (
    "macbook", "chromebook", "imac", "mac mini", "mac studio",
)


@dataclass
class PreFilterResult:
    passed: bool
    reason: str = ""


def pre_filter(deal: RawDeal, config: dict) -> PreFilterResult:
    """Tek bir ilanı ucuz kurallardan geçirir."""
    filters = config.get("filters", {})
    text = deal.text_blob()
    lower = text.lower()

    # 1) Laptop ile ilgili mi?
    if not any(kw in lower for kw in _LAPTOP_KEYWORDS):
        return PreFilterResult(False, "laptop anahtar kelimesi yok")

    # 1b) Hedef dışı platform (Windows olmayan / RTX'siz)
    for kw in _NON_TARGET_KEYWORDS:
        if kw in lower:
            return PreFilterResult(False, f"hedef dışı platform: {kw}")

    # 2) Otomatik ret anahtar kelimeleri
    for kw in config.get("reject_keywords", []):
        if kw.lower() in lower:
            return PreFilterResult(False, f"reddedilen anahtar kelime: {kw}")

    # 3) GPU eşiği — tespit edilebiliyorsa min altını ele
    min_gpu = filters.get("min_gpu", "RTX 4060")
    gpu_ok = spec_validator.meets_min_gpu(text, min_gpu)
    if gpu_ok is False:
        return PreFilterResult(False, f"GPU {min_gpu} altında")

    # 4) Fiyat aralığı (fiyat biliniyorsa)
    if deal.price is not None:
        min_price = filters.get("min_price")
        max_price = filters.get("max_price")
        if min_price is not None and deal.price < min_price:
            return PreFilterResult(False, f"fiyat çok düşük ({deal.price} €)")
        if max_price is not None and deal.price > max_price:
            return PreFilterResult(False, f"fiyat çok yüksek ({deal.price} €)")

    return PreFilterResult(True, "ön filtreyi geçti")

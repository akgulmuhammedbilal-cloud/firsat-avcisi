"""LLM analiz arayüzü, ortak sistem promptu ve JSON şeması.

AI sağlayıcısı pluggable'dır: GeminiAnalyzer ve DryRunAnalyzer bu arayüzü uygular.
İleride ClaudeAnalyzer da aynı arayüzle eklenebilir.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from storage.models import AnalysisResult, RawDeal

# AI'ın döndürmesi gereken JSON alanları (provider-agnostik şema tanımı).
# google-genai response_schema'sı bu alanlardan üretilir.
RESPONSE_FIELDS: dict[str, str] = {
    "approved": "boolean",
    "confidence_score": "integer",  # 0-100
    "deal_score": "integer",        # 0-100 (AI'ın kendi tahmini)
    "reason": "string",
    "detected_model": "string",
    "cpu": "string",
    "gpu": "string",
    "gpu_tgp_estimate": "string",
    "ram": "string",
    "ram_upgradeability": "string",  # yükseltilebilir | lehimli | belirsiz
    "storage": "string",
    "case_quality": "string",        # premium | orta | plastik | belirsiz
    "display_quality": "string",
    "engineering_suitability": "string",
    "gaming_suitability": "string",
    "rejection_reason": "string",
    "estimated_normal_price": "number",
}

# Zorunlu JSON çıktısı için Google (Gemini) formatında response_schema.
# RESPONSE_FIELDS'tan üretilir; estimated_normal_price dışındakiler zorunludur.
_GOOGLE_TYPE = {"string": "STRING", "integer": "INTEGER",
                "number": "NUMBER", "boolean": "BOOLEAN"}

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        key: {"type": _GOOGLE_TYPE[kind]} for key, kind in RESPONSE_FIELDS.items()
    },
    "required": [k for k in RESPONSE_FIELDS if k != "estimated_normal_price"],
    "property_ordering": list(RESPONSE_FIELDS.keys()),
}

SYSTEM_PROMPT = """\
Sen Almanya pazarındaki premium Windows laptop fırsatlarını değerlendiren uzman bir
satın alma asistanısın. Amacın "ucuz" laptopları değil; MacBook kalitesine yaklaşan,
güçlü GPU'lu, mühendislik yazılımlarını (SolidWorks, AutoCAD, ANSYS) kaldırabilen,
uzun ömürlü premium Windows laptopları yakalamak.

ZORUNLU KRİTERLER (karşılanmazsa approved=false):
- GPU: minimum RTX 4060
- RAM: minimum 32 GB VEYA kesin yükseltilebilir 16 GB
- Kasa: alüminyum/magnezyum/CNC metal/premium kompozit
- Fiyat: Almanya normal piyasa değerine göre GERÇEK indirim içermeli

OTOMATİK RET (fiyat ne olursa olsun approved=false):
- Asus TUF, HP Victus, Acer Nitro, MSI Thin/GF/Cyborg serileri
- Tamamen plastik giriş seviyesi gaming laptoplar
- RTX 4050 veya altı GPU
- 16 GB RAM olup yükseltilebilirliği belirsiz; 8 GB RAM
- Çok düşük TGP'li GPU; zayıf ekran (ör. %45 NTSC); aşırı kalın/ağır düşük kalite kasa

POZİTİF (premium aileler): ROG Zephyrus G14/G16, ROG Flow, Legion 7/Slim 7/Pro,
güçlü GPU'lu Yoga Pro, Dell XPS 15/16, Dell Precision, HP ZBook Studio/Fury,
Razer Blade, MSI Stealth/Creator, Schenker/XMG.

KURALLAR:
- SADECE JSON döndür, serbest metin yazma.
- Bilgi ilan metninde yoksa ilgili alana "belirsiz" yaz; UYDURMA.
- Kritik donanım belirsizse approved'ı temkinli ver ve rejection_reason'da belirt.
- reason ve rejection_reason Türkçe, kısa ve net olmalı.
- estimated_normal_price: bu modelin Almanya'daki tahmini normal fiyatı (sayı, EUR);
  bilmiyorsan ilan fiyatını kullan.
"""


def build_user_prompt(deal: RawDeal) -> str:
    price = f"{deal.price:.0f} €" if deal.price is not None else "belirtilmemiş"
    return (
        "Aşağıdaki ilanı değerlendir ve JSON döndür.\n\n"
        f"Başlık: {deal.title}\n"
        f"Fiyat: {price}\n"
        f"Kaynak: {deal.source}\n"
        f"Link: {deal.url}\n"
        f"Açıklama: {deal.description or '(yok)'}\n"
    )


class LLMAnalyzer(ABC):
    """Tüm AI karar motorlarının uyguladığı arayüz."""

    @abstractmethod
    def analyze(self, deal: RawDeal) -> AnalysisResult:
        raise NotImplementedError

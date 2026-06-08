"""Veri modelleri: ham ilan, AI analiz sonucu ve veritabanı kaydı."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class RawDeal:
    """Bir kaynaktan çekilen, henüz analiz edilmemiş ham ilan."""

    deal_id: str
    source: str
    title: str
    url: str
    description: str = ""
    price: Optional[float] = None
    currency: str = "EUR"
    merchant: Optional[str] = None
    raw_published_at: Optional[str] = None
    # İlan metninden ayrıştırılan GERÇEK referans (normal) fiyat ve indirim oranı.
    # "statt 1.799 €", "UVP", "−22%" gibi satıcı beyanlarından gelir; yoksa None.
    reference_price: Optional[float] = None
    discount_pct: Optional[float] = None

    def text_blob(self) -> str:
        """Ön filtre ve AI için birleşik metin (başlık + açıklama)."""
        return f"{self.title}\n{self.description}".strip()


@dataclass
class AnalysisResult:
    """AI karar motorunun (ya da dry-run analizörünün) JSON çıktısı."""

    approved: bool = False
    confidence_score: int = 0
    deal_score: int = 0  # AI'ın kendi skoru — sanity-check; nihai skor scoring.py'den gelir
    reason: str = ""
    detected_model: str = "belirsiz"
    cpu: str = "belirsiz"
    gpu: str = "belirsiz"
    gpu_tgp_estimate: str = "belirsiz"
    ram: str = "belirsiz"
    ram_upgradeability: str = "belirsiz"  # yükseltilebilir | lehimli | belirsiz
    storage: str = "belirsiz"
    case_quality: str = "belirsiz"  # premium | orta | plastik | belirsiz
    display_quality: str = "belirsiz"
    engineering_suitability: str = "belirsiz"
    gaming_suitability: str = "belirsiz"
    rejection_reason: str = ""
    estimated_normal_price: Optional[float] = None
    needs_manual_review: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DealRecord:
    """deals tablosundaki bir satır."""

    deal_id: str
    source: str
    title: str
    url: str
    price: Optional[float] = None
    detected_model: Optional[str] = None
    approved: bool = False
    deal_score: int = 0
    rejection_reason: str = ""
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    notified_at: Optional[str] = None
    analysis_json: Optional[str] = None

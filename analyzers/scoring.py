"""Fırsat skoru algoritması (0-100), deterministik.

AI alanları girdi olarak kullanılır; nihai skor burada hesaplanır (AI'ın kendi
deal_score'u yalnızca sanity-check olarak saklanır). Spec ağırlıkları:

    indirim 25 / GPU+TGP 20 / RAM+upgrade 15 / kasa 15 /
    ekran 10 / mühendislik 10 / marka 5  = 100
"""
from __future__ import annotations

from analyzers import spec_validator
from storage.models import AnalysisResult, RawDeal


def _discount_points(result: AnalysisResult, raw: RawDeal) -> int:
    """Gerçek indirim oranına göre 0-25 puan."""
    normal = result.estimated_normal_price
    price = raw.price
    if not normal or not price or normal <= 0 or price <= 0 or price >= normal:
        return 5  # indirim doğrulanamadı → düşük taban puan
    discount = (normal - price) / normal
    # %0 → 0p, %25+ → 25p (lineer, üst sınır)
    return min(25, round(discount * 100))


def _gpu_points(result: AnalysisResult) -> int:
    """GPU gücü/TGP — 0-20 puan."""
    rank = spec_validator.gpu_rank(spec_validator.detect_gpu(result.gpu))
    if rank is None:
        return 5
    if rank >= 80:        # 4080/4090/5080+
        base = 20
    elif rank >= 70:      # 4070 / 5070
        base = 17
    elif rank >= 60:      # 4060 / 5060
        base = 13
    else:                 # 4050 ve altı
        base = 4
    tgp = result.gpu_tgp_estimate.lower()
    if any(t in tgp for t in ("belirsiz", "")) and tgp.strip() in ("belirsiz", ""):
        base -= 2  # TGP doğrulanamadıysa hafif ceza
    return max(0, base)


def _ram_points(result: AnalysisResult) -> int:
    """RAM miktarı + yükseltilebilirlik — 0-15 puan."""
    ram_gb = spec_validator.detect_ram_gb(result.ram)
    upg = result.ram_upgradeability.lower()
    points = 0
    if ram_gb is None:
        points = 4
    elif ram_gb >= 64:
        points = 12
    elif ram_gb >= 32:
        points = 11
    elif ram_gb >= 16:
        points = 6
    else:
        points = 2
    if "yükseltilebilir" in upg:
        points += 3
    elif "lehim" in upg:
        points -= 1
    return max(0, min(15, points))


_CASE_POINTS = {"premium": 15, "orta": 8, "plastik": 1, "belirsiz": 5}


def _case_points(result: AnalysisResult) -> int:
    return _CASE_POINTS.get(result.case_quality.lower().strip(), 5)


def _display_points(result: AnalysisResult) -> int:
    """Ekran kalitesi — 0-10 puan, anahtar kelimelerle kaba değerlendirme."""
    d = result.display_quality.lower()
    if any(k in d for k in ("oled", "mini-led", "miniled")):
        return 10
    if any(k in d for k in ("120hz", "144hz", "165hz", "240hz", "qhd", "2k", "ips iyi", "yüksek")):
        return 8
    if "ips" in d:
        return 6
    if any(k in d for k in ("zayıf", "45% ntsc", "tn")):
        return 1
    return 5  # belirsiz


_SUIT_POINTS = {"uygun": 10, "kısmen": 6, "uygun değil": 1}


def _engineering_points(result: AnalysisResult) -> int:
    s = result.engineering_suitability.lower().strip()
    for key, pts in _SUIT_POINTS.items():
        if key in s:
            return pts
    return 5  # belirsiz


def _brand_points(result: AnalysisResult, preferred_models: list[str]) -> int:
    """Marka/model güvenilirliği — 0-5 puan."""
    model = result.detected_model.lower()
    if any(pm.lower() in model for pm in preferred_models):
        return 5
    return 2


def score(result: AnalysisResult, raw: RawDeal, preferred_models: list[str] | None = None) -> int:
    """Nihai fırsat skoru (0-100)."""
    preferred_models = preferred_models or []
    total = (
        _discount_points(result, raw)
        + _gpu_points(result)
        + _ram_points(result)
        + _case_points(result)
        + _display_points(result)
        + _engineering_points(result)
        + _brand_points(result, preferred_models)
    )
    return max(0, min(100, total))


def verdict(deal_score: int) -> str:
    """Skoru insan-okur karara çevirir (spec yorumları)."""
    if deal_score >= 90:
        return "Kaçırılmayacak premium fırsat"
    if deal_score >= 80:
        return "Çok güçlü fırsat"
    if deal_score >= 70:
        return "Alınabilir ama detaylı kontrol gerekli"
    if deal_score >= 60:
        return "Sınırda, manuel inceleme önerilir"
    return "Zayıf — bildirim eşiğinin altında"

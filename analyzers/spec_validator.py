"""Donanım doğrulama yardımcıları: GPU sınıfı, RAM yeterliliği, belirsizlik."""
from __future__ import annotations

import re

# RTX modellerini kaba bir "sıralama puanına" eşleriz; karşılaştırma için.
# Daha yüksek = daha güçlü. Sadece elemede sıralama amaçlı kullanılır.
_GPU_RANK: dict[str, int] = {
    "RTX 3050": 30,
    "RTX 4050": 40,
    "RTX 4060": 60,
    "RTX 4070": 70,
    "RTX 4080": 80,
    "RTX 4090": 90,
    "RTX 5060": 105,
    "RTX 5070": 110,
    "RTX 5080": 120,
    "RTX 5090": 130,
}

_GPU_RE = re.compile(r"RTX\s*([0-9]{4})", re.IGNORECASE)


def detect_gpu(text: str) -> str | None:
    """Metinden GPU modelini (ör. 'RTX 4070') tespit eder."""
    m = _GPU_RE.search(text or "")
    if not m:
        return None
    return f"RTX {m.group(1)}"


def gpu_rank(gpu: str | None) -> int | None:
    """Bir GPU adının sıralama puanı. Bilinmiyorsa None."""
    if not gpu:
        return None
    key = gpu.upper().replace("  ", " ").strip()
    return _GPU_RANK.get(key)


def meets_min_gpu(text: str, min_gpu: str) -> bool | None:
    """Metindeki GPU, min_gpu eşiğini karşılıyor mu?

    True = karşılıyor, False = altında, None = GPU tespit edilemedi (belirsiz).
    """
    detected = detect_gpu(text)
    detected_rank = gpu_rank(detected)
    min_rank = gpu_rank(min_gpu)
    if detected_rank is None or min_rank is None:
        return None
    return detected_rank >= min_rank


_RAM_RE = re.compile(r"([0-9]{1,3})\s*GB", re.IGNORECASE)


def detect_ram_gb(text: str) -> int | None:
    """Metindeki en büyük 'NN GB' değerini RAM adayı olarak döndürür.

    Not: SSD kapasitesi (512GB/1TB) ile karışmaması için yalnızca tipik RAM
    değerlerini (8..128) dikkate alırız.
    """
    candidates = [int(m.group(1)) for m in _RAM_RE.finditer(text or "")]
    ram_candidates = [c for c in candidates if c in (8, 12, 16, 24, 32, 48, 64, 96, 128)]
    return max(ram_candidates) if ram_candidates else None


def ram_is_sufficient(
    ram_gb: int | None,
    upgradeability: str,
    min_ram_gb: int,
    allow_16gb_if_upgradeable: bool,
) -> bool | None:
    """RAM kriteri karşılanıyor mu? None = belirsiz."""
    if ram_gb is None:
        return None
    if ram_gb >= min_ram_gb:
        return True
    if allow_16gb_if_upgradeable and ram_gb >= 16 and upgradeability == "yükseltilebilir":
        return True
    return False


_UNCERTAIN_VALUES = {"belirsiz", "", "unknown", "bilinmiyor", None}


def needs_manual_review(result) -> bool:
    """Kritik alanlar belirsizse manuel kontrol gerekir."""
    critical = [result.gpu, result.ram, result.case_quality]
    uncertain = sum(1 for v in critical if str(v).strip().lower() in _UNCERTAIN_VALUES)
    return uncertain >= 2 or result.gpu_tgp_estimate.strip().lower() in _UNCERTAIN_VALUES

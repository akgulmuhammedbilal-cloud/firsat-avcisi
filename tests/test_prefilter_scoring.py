"""Ön filtre, skor ve fiyat çıkarma için temel testler.

Çalıştırma:  python -m pytest -q   (veya)  python tests/test_prefilter_scoring.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analyzers.pre_filter import pre_filter
from analyzers.scoring import score
from analyzers.gemini_analyzer import DryRunAnalyzer
from sources.rss_source import extract_price, parse_prices
from sources.base import make_deal_id
from storage.models import RawDeal

CONFIG = {
    "filters": {"min_gpu": "RTX 4060", "min_ram_gb": 32,
                "allow_16gb_if_upgradeable": True, "min_price": 700, "max_price": 3000},
    "reject_keywords": ["Asus TUF", "HP Victus", "Acer Nitro", "RTX 4050", "8GB RAM"],
    "preferred_models": ["Legion Slim 7", "ROG Zephyrus", "XPS 16"],
}


def _deal(title, price=1500, desc=""):
    return RawDeal(deal_id=make_deal_id("test", title), source="test",
                   title=title, url="http://x", description=desc, price=price)


# --- ön filtre ---------------------------------------------------------------
def test_prefilter_rejects_nitro():
    r = pre_filter(_deal("Acer Nitro 5 Gaming Laptop RTX 4060"), CONFIG)
    assert not r.passed and "Acer Nitro" in r.reason


def test_prefilter_rejects_rtx4050():
    r = pre_filter(_deal("Some Gaming Laptop RTX 4050"), CONFIG)
    assert not r.passed


def test_prefilter_rejects_non_laptop():
    r = pre_filter(_deal("RTX 4070 Grafikkarte Desktop"), CONFIG)
    assert not r.passed and "laptop" in r.reason


def test_prefilter_rejects_low_gpu_passes_good():
    assert pre_filter(_deal("Lenovo Legion Slim 7 Gaming Laptop RTX 4070"), CONFIG).passed


def test_prefilter_price_bounds():
    assert not pre_filter(_deal("Legion Gaming Laptop RTX 4070", price=5000), CONFIG).passed
    assert not pre_filter(_deal("Legion Gaming Laptop RTX 4070", price=300), CONFIG).passed


# --- fiyat çıkarma -----------------------------------------------------------
def test_extract_price_german_format():
    assert extract_price("Jetzt für 1.399 €") == 1399.0
    assert extract_price("nur 1299€ statt mehr") == 1299.0
    assert extract_price("Preis EUR 999") == 999.0
    assert extract_price("kein preis hier") is None


# --- gerçek indirim ayrıştırma (statt / UVP / -%) ----------------------------
def test_parse_prices_statt():
    cur, ref, pct = parse_prices("Legion Slim 7 für 1.399 € statt 1.799 €")
    assert cur == 1399.0 and ref == 1799.0
    assert pct == round((1799 - 1399) / 1799 * 100, 1)


def test_parse_prices_uvp():
    cur, ref, pct = parse_prices("ROG Zephyrus 2.099€ (UVP 2.799€)")
    assert cur == 2099.0 and ref == 2799.0 and pct > 0


def test_parse_prices_explicit_pct():
    cur, ref, pct = parse_prices("Gaming Laptop 1499 € -22% Rabatt")
    assert cur == 1499.0 and pct == 22.0


def test_parse_prices_invalid_reference_dropped():
    # Referans güncelden küçükse geçersiz sayılmalı
    cur, ref, pct = parse_prices("Laptop 1500 € statt 999 €")
    assert ref is None


def test_real_discount_used_in_scoring():
    from analyzers.gemini_analyzer import DryRunAnalyzer
    deal = _deal("Lenovo Legion Slim 7 Gaming Laptop RTX 4070 32GB", price=1399)
    deal.reference_price = 1799.0
    deal.discount_pct = 22.0
    result = DryRunAnalyzer(CONFIG["reject_keywords"], CONFIG["preferred_models"]).analyze(deal)
    from analyzers.scoring import _discount_points
    assert _discount_points(result, deal) == 22  # gerçek %22 kullanılmalı


# --- skor + dry-run analizör -------------------------------------------------
def test_good_deal_scores_high_and_approved():
    deal = _deal("Lenovo Legion Slim 7 Gaming Laptop RTX 4070 32GB RAM 1TB SSD", price=1399)
    result = DryRunAnalyzer(CONFIG["reject_keywords"], CONFIG["preferred_models"]).analyze(deal)
    s = score(result, deal, CONFIG["preferred_models"])
    assert result.approved
    assert s >= 60  # güçlü ilan makul skor almalı


def test_bad_deal_rejected():
    deal = _deal("Acer Nitro RTX 4050 8GB RAM", price=899)
    result = DryRunAnalyzer(CONFIG["reject_keywords"], CONFIG["preferred_models"]).analyze(deal)
    assert not result.approved


# --- Apify kaynağı (mock) ----------------------------------------------------
def test_apify_source_maps_items():
    from unittest.mock import patch, Mock
    from sources.apify_source import ApifySource

    fake_items = [
        {"title": "Lenovo Legion Pro 7 RTX 4080", "url": "http://x/1", "price": 1899},
        {"title": "MSI Stealth 16 statt 2.499 €", "url": "http://x/2", "price": "1.999 €"},
        {"title": "", "url": "http://x/3", "price": 1000},  # başlıksız → atlanır
    ]
    resp = Mock(status_code=200)
    resp.raise_for_status = lambda: None
    resp.json = lambda: fake_items
    with patch("sources.apify_source.requests.get", return_value=resp):
        src = ApifySource("geizhals", token="t", apify_resource="acts/u~web-scraper")
        deals = src.fetch()
    assert len(deals) == 2
    assert deals[0].price == 1899.0
    assert deals[1].price == 1999.0 and deals[1].reference_price == 2499.0


def test_apify_source_handles_error():
    from unittest.mock import patch
    from sources.apify_source import ApifySource
    with patch("sources.apify_source.requests.get", side_effect=Exception("boom")):
        src = ApifySource("geizhals", token="t", apify_resource="acts/u~web-scraper")
        assert src.fetch() == []  # hata → boş liste, sistem durmaz


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    print(f"\n{('TÜM TESTLER GEÇTİ' if not failures else str(failures) + ' TEST BAŞARISIZ')}")
    sys.exit(1 if failures else 0)

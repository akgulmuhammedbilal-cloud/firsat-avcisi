"""Geriye dönük uyumluluk kalkanı.

MyDealz artık genel `RssSource` ile okunur (bkz. sources/rss_source.py).
Eski içe aktarmalar (`from sources.mydealz import MyDealzSource, extract_price`)
çalışmaya devam etsin diye bu modül korunur.
"""
from __future__ import annotations

from sources.rss_source import RssSource, extract_price, strip_html  # noqa: F401

# Geriye dönük uyumluluk için _strip_html alias'ı
_strip_html = strip_html


class MyDealzSource(RssSource):
    """Adı 'mydealz' olan RssSource (eski API)."""

    def __init__(self, feeds: list[str], request_timeout_seconds: int = 20) -> None:
        super().__init__("mydealz", feeds, request_timeout_seconds)

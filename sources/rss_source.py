"""Genel RSS fırsat kaynağı.

Herhangi bir RSS/Atom feed'ini (MyDealz, Preisjäger, mağaza feed'leri, kişisel
deal-alarm RSS'leri...) okur. Yeni bir RSS kaynağı eklemek için kod yazmaya gerek
yoktur; config'e ad + feed URL listesi eklemek yeterlidir.

Birçok site (MyDealz/Preisjäger dahil) tarayıcı benzeri bir User-Agent olmadan
HTTP 403 döndürür; bu yüzden istekleri gerçekçi bir User-Agent ile yaparız.
"""
from __future__ import annotations

import logging
import re

import feedparser
import requests

from sources.base import DealSource, RawDeal, make_deal_id

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# Fiyat kalıpları: "1.399 €", "1399€", "1.299,00 €", "EUR 1399", "999 EUR"
_PRICE_RE = re.compile(
    r"(?:€|EUR)\s*([0-9][0-9.\s]*[0-9](?:,[0-9]{2})?)"
    r"|([0-9][0-9.\s]*[0-9](?:,[0-9]{2})?)\s*(?:€|EUR)",
    re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")


def extract_price(text: str) -> float | None:
    """Metinden ilk makul fiyatı (EUR) çıkarır. Almanca biçimlendirme destekli."""
    if not text:
        return None
    for match in _PRICE_RE.finditer(text):
        raw = match.group(1) or match.group(2)
        if not raw:
            continue
        # Almanca format: binlik '.', ondalık ','. Boşlukları temizle.
        cleaned = raw.replace(" ", "").replace(".", "").replace(",", ".")
        try:
            value = float(cleaned)
        except ValueError:
            continue
        if 100 <= value <= 20000:  # mantıklı laptop fiyat aralığı
            return value
    return None


def strip_html(text: str) -> str:
    return _TAG_RE.sub(" ", text or "").replace("&nbsp;", " ").strip()


class RssSource(DealSource):
    """Ad + feed URL listesiyle çalışan genel RSS kaynağı."""

    def __init__(self, name: str, feeds: list[str],
                 request_timeout_seconds: int = 20) -> None:
        self.name = name
        self.feeds = feeds or []
        self.timeout = request_timeout_seconds
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": _USER_AGENT})

    def fetch(self) -> list[RawDeal]:
        deals: list[RawDeal] = []
        seen_ids: set[str] = set()
        for feed_url in self.feeds:
            try:
                deals.extend(self._fetch_one(feed_url, seen_ids))
            except Exception as exc:  # tek feed çökerse sistem durmasın
                logger.warning("[%s] feed çekilemedi (%s): %s", self.name, feed_url, exc)
        logger.info("[%s]: %d ilan çekildi", self.name, len(deals))
        return deals

    def _fetch_one(self, feed_url: str, seen_ids: set[str]) -> list[RawDeal]:
        # Yerel dosya yolu (test/offline) ya da http(s) feed'i destekle.
        if feed_url.startswith(("http://", "https://")):
            resp = self.session.get(feed_url, timeout=self.timeout)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
        else:
            parsed = feedparser.parse(feed_url)
        results: list[RawDeal] = []
        for entry in parsed.entries:
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue
            summary = entry.get("summary", "") or entry.get("description", "")
            identifier = entry.get("id") or link
            deal_id = make_deal_id(self.name, identifier)
            if deal_id in seen_ids:
                continue
            seen_ids.add(deal_id)
            price = extract_price(f"{title} {summary}")
            results.append(
                RawDeal(
                    deal_id=deal_id,
                    source=self.name,
                    title=title,
                    url=link,
                    description=strip_html(summary),
                    price=price,
                    raw_published_at=entry.get("published"),
                )
            )
        return results

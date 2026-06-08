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

# Referans (normal/eski) fiyat işaretleri: "statt 1.799 €", "UVP 1.999€", "ehem. ..."
# ÖNEMLİ: Referans fiyatın € işaretiyle bitişik olması ZORUNLU. Aksi halde "RTX 5070"
# gibi GPU model numaraları yanlışlıkla fiyat sanılıp sahte indirim üretir.
_PRICE_TOKEN = r"([0-9][0-9.\s]*[0-9](?:,[0-9]{2})?)"
_REF_KEYWORDS = (
    r"statt|uvp|ehem\.?|ehemals|empf\.?\s*vk|\bvk\b|idealo|regul[äa]r|bisher|"
    r"fr[üu]her|normalerweise|listenpreis"
)
_REF_RE = re.compile(
    r"(?:" + _REF_KEYWORDS + r")[^0-9]{0,12}"
    r"(?:€\s*" + _PRICE_TOKEN + r"|" + _PRICE_TOKEN + r"\s*(?:€|EUR))",
    re.IGNORECASE,
)
# Açıkça belirtilen indirim oranı: "-22%", "22% Rabatt", "minus 30 %"
_PCT_RE = re.compile(
    r"(?:-\s*|minus\s*)([0-9]{1,2})\s*%"
    r"|([0-9]{1,2})\s*%\s*(?:rabatt|reduziert|sparen|g[üu]nstiger|nachlass|off)",
    re.IGNORECASE,
)


def _to_float(raw: str | None, lo: float = 50, hi: float = 20000) -> float | None:
    """Almanca biçimli fiyat metnini float'a çevirir (binlik '.', ondalık ',')."""
    if not raw:
        return None
    cleaned = raw.replace(" ", "").replace(".", "").replace(",", ".")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if lo <= value <= hi else None


def extract_price(text: str) -> float | None:
    """Metinden ilk makul fiyatı (EUR) çıkarır. Almanca biçimlendirme destekli."""
    if not text:
        return None
    for match in _PRICE_RE.finditer(text):
        value = _to_float(match.group(1) or match.group(2), lo=100)
        if value is not None:
            return value
    return None


def parse_prices(text: str) -> tuple[float | None, float | None, float | None]:
    """(güncel_fiyat, referans_fiyat, indirim_yüzdesi) ayrıştırır.

    Referans fiyat ve indirim, ilan metnindeki satıcı beyanlarından (statt/UVP/-%)
    gelir; bulunamazsa None. İndirim yüzdesi açıkça yazılmışsa o, yoksa referans ve
    güncel fiyattan hesaplanır.
    """
    current = extract_price(text)

    reference = None
    ref_match = _REF_RE.search(text or "")
    if ref_match:
        reference = _to_float(ref_match.group(1) or ref_match.group(2))
    # Referans güncel fiyattan büyük olmalı; değilse geçersiz say.
    if reference is not None and current is not None and reference <= current:
        reference = None

    pct = None
    pct_match = _PCT_RE.search(text or "")
    if pct_match:
        raw_pct = pct_match.group(1) or pct_match.group(2)
        try:
            pct = float(raw_pct)
        except (TypeError, ValueError):
            pct = None
    # Açık yüzde yoksa referans + güncelden hesapla.
    if pct is None and reference and current and reference > current:
        pct = round((reference - current) / reference * 100, 1)

    return current, reference, pct


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
            blob = f"{title} {strip_html(summary)}"
            price, reference_price, discount_pct = parse_prices(blob)
            results.append(
                RawDeal(
                    deal_id=deal_id,
                    source=self.name,
                    title=title,
                    url=link,
                    description=strip_html(summary),
                    price=price,
                    reference_price=reference_price,
                    discount_pct=discount_pct,
                    raw_published_at=entry.get("published"),
                )
            )
        return results

"""Apify dataset fırsat kaynağı (type: apify).

Apify, proxy + headless tarayıcı ile bizim doğrudan erişemediğimiz siteleri
(Geizhals, idealo, Dell Outlet...) kazır. Maliyeti düşük tutmak için actor'ü
Apify'da ZAMANLI çalıştırırsın; biz yalnızca son BAŞARILI run'ın dataset'ini
API'den okuruz (okuma ucuzdur, her taramada yeni scrape tetiklemez).

Config örneği:
    geizhals:
      enabled: true
      type: apify
      apify_resource: "actor-tasks/XXXXXXXX"   # veya "acts/USERNAME~web-scraper"
      fields: { title: "title", url: "url", price: "price" }
      limit: 200

Token .env / GitHub secret: APIFY_TOKEN
"""
from __future__ import annotations

import logging

import requests

from sources.base import DealSource, RawDeal, make_deal_id
from sources.rss_source import extract_price, parse_prices

logger = logging.getLogger(__name__)

_API = "https://api.apify.com/v2/{resource}/runs/last/dataset/items"


def _coerce_price(value) -> float | None:
    """Apify item'ındaki fiyatı float'a çevirir (sayı ya da '1.399 €' metni)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if 50 <= float(value) <= 20000 else None
    return extract_price(str(value))


class ApifySource(DealSource):
    def __init__(self, name: str, token: str, apify_resource: str,
                 fields: dict | None = None, limit: int = 200,
                 request_timeout_seconds: int = 60) -> None:
        self.name = name
        self.token = token
        self.resource = apify_resource.strip("/")
        self.fields = fields or {}
        self.limit = limit
        self.timeout = request_timeout_seconds

    def fetch(self) -> list[RawDeal]:
        url = _API.format(resource=self.resource)
        params = {
            "token": self.token,
            "status": "SUCCEEDED",
            "clean": "true",
            "format": "json",
            "limit": self.limit,
        }
        try:
            resp = requests.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            items = resp.json()
        except Exception as exc:
            logger.warning("[%s] Apify dataset çekilemedi: %s", self.name, exc)
            return []
        if not isinstance(items, list):
            logger.warning("[%s] Apify beklenmeyen yanıt (liste değil)", self.name)
            return []

        f_title = self.fields.get("title", "title")
        f_url = self.fields.get("url", "url")
        f_price = self.fields.get("price", "price")

        deals: list[RawDeal] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get(f_title, "") or "").strip()
            link = str(item.get(f_url, "") or "").strip()
            if not title or not link:
                continue
            deal_id = make_deal_id(self.name, link)
            if deal_id in seen:
                continue
            seen.add(deal_id)

            price = _coerce_price(item.get(f_price))
            # Referans fiyat/indirim: gerçek fiyatı (price) bilerek başlıktan ayrıştır.
            _, ref, pct = parse_prices(title, current=price)
            ref = _coerce_price(item.get("reference_price")) or ref
            deals.append(
                RawDeal(
                    deal_id=deal_id,
                    source=self.name,
                    title=title,
                    url=link,
                    description=str(item.get("description", "") or ""),
                    price=price,
                    reference_price=ref,
                    discount_pct=pct,
                )
            )
        logger.info("[%s]: %d ilan çekildi (Apify)", self.name, len(deals))
        return deals

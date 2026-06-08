"""Ortak kaynak arayüzü. Tüm fırsat kaynakları DealSource'u uygular."""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod

from storage.models import RawDeal

__all__ = ["DealSource", "RawDeal", "make_deal_id"]


def make_deal_id(source: str, identifier: str) -> str:
    """Bir kaynak + tekil tanımlayıcıdan deterministik dedup anahtarı üretir."""
    digest = hashlib.sha1(f"{source}:{identifier}".encode("utf-8")).hexdigest()
    return f"{source}-{digest[:16]}"


class DealSource(ABC):
    """Tüm fırsat kaynaklarının uyması gereken arayüz."""

    name: str = "base"

    @abstractmethod
    def fetch(self) -> list[RawDeal]:
        """Kaynaktan güncel ilanları çeker. Hata durumunda boş liste döndürür."""
        raise NotImplementedError

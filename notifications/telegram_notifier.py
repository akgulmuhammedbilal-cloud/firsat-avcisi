"""Telegram bildirim sistemi.

Token/chat_id yoksa (ya da dry_run=True) mesaj gönderilmez; konsola basılır.
Böylece sistem anahtarsız da uçtan uca test edilebilir.
"""
from __future__ import annotations

import logging

import requests

from analyzers import scoring
from storage.models import AnalysisResult, RawDeal

logger = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot{token}/sendMessage"


def build_message(deal: RawDeal, result: AnalysisResult, deal_score: int) -> str:
    """Spec'teki sade, karar odaklı Telegram mesajını üretir (Markdown)."""
    price = f"{deal.price:.0f} €" if deal.price is not None else "belirtilmemiş"
    normal = (
        f"{result.estimated_normal_price:.0f} €"
        if result.estimated_normal_price else "belirsiz"
    )
    discount = "—"
    if result.estimated_normal_price and deal.price and result.estimated_normal_price > deal.price:
        pct = (result.estimated_normal_price - deal.price) / result.estimated_normal_price * 100
        discount = f"yaklaşık %{pct:.0f}"

    manual = "\n⚠️ *Manuel kontrol önerilir*" if result.needs_manual_review else ""

    return (
        "*Premium Laptop Fırsatı Bulundu*\n\n"
        f"*Model:* {result.detected_model}\n"
        f"*Fiyat:* {price}\n"
        f"*Tahmini Normal Fiyat:* {normal}\n"
        f"*İndirim:* {discount}\n"
        f"*Skor:* {deal_score}/100\n"
        f"*Karar:* {scoring.verdict(deal_score)}\n\n"
        "*Donanım:*\n"
        f"• CPU: {result.cpu}\n"
        f"• GPU: {result.gpu} (TGP: {result.gpu_tgp_estimate})\n"
        f"• RAM: {result.ram} ({result.ram_upgradeability})\n"
        f"• SSD: {result.storage}\n"
        f"• Kasa: {result.case_quality}\n"
        f"• Ekran: {result.display_quality}\n\n"
        f"*Neden?* {result.reason}\n"
        f"{manual}\n\n"
        f"[Deal linki]({deal.url})"
    )


class TelegramNotifier:
    def __init__(self, token: str | None, chat_id: str | None, dry_run: bool = False) -> None:
        self.token = token
        self.chat_id = chat_id
        self.dry_run = dry_run or not (token and chat_id)

    def send(self, deal: RawDeal, result: AnalysisResult, deal_score: int) -> bool:
        text = build_message(deal, result, deal_score)
        if self.dry_run:
            logger.info("[DRY-RUN] Telegram mesajı:\n%s\n", text)
            print("\n" + "=" * 60 + "\n" + text + "\n" + "=" * 60)
            return True
        try:
            resp = requests.post(
                _API.format(token=self.token),
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": False,
                },
                timeout=20,
            )
            resp.raise_for_status()
            return True
        except Exception as exc:
            logger.error("Telegram gönderim hatası: %s", exc)
            return False

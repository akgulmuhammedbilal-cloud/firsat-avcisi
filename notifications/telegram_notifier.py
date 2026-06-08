"""Telegram bildirim sistemi.

Token/chat_id yoksa (ya da dry_run=True) mesaj gönderilmez; konsola basılır.
Böylece sistem anahtarsız da uçtan uca test edilebilir.

Geri bildirim butonları: bildirimlere inline butonlar eklenir. GitHub Actions
sürekli dinleyemediği için buton basışları her tarama koşusunda getUpdates ile
toplanıp DB'ye kaydedilir (en geç ~20 dk gecikmeyle).
"""
from __future__ import annotations

import logging

import requests

from analyzers import scoring
from storage.models import AnalysisResult, RawDeal

logger = logging.getLogger(__name__)

_BASE = "https://api.telegram.org/bot{token}/{method}"

# callback_data formatı: "fb:<tür>:<deal_id>" (Telegram sınırı 64 bayt)
_FEEDBACK_LABELS = {
    "iyi": "👍 İyi",
    "gereksiz": "👎 Gereksiz",
    "pahali": "💰 Pahalı",
    "alindi": "📦 Alındım",
}


def _feedback_keyboard(deal_id: str) -> dict:
    row = [{"text": label, "callback_data": f"fb:{kind}:{deal_id}"}
           for kind, label in _FEEDBACK_LABELS.items()]
    # İki satıra böl (2'şer buton)
    return {"inline_keyboard": [row[:2], row[2:]]}


def build_message(deal: RawDeal, result: AnalysisResult, deal_score: int) -> str:
    """Spec'teki sade, karar odaklı Telegram mesajını üretir (Markdown)."""
    price = f"{deal.price:.0f} €" if deal.price is not None else "belirtilmemiş"

    # Gerçek (ilanda belirtilen) referans fiyat/indirim varsa onu göster; yoksa AI tahmini.
    if deal.reference_price:
        normal = f"{deal.reference_price:.0f} € *(ilanda)*"
    elif result.estimated_normal_price:
        normal = f"{result.estimated_normal_price:.0f} € *(AI tahmini)*"
    else:
        normal = "belirsiz"

    discount = "—"
    if deal.discount_pct:
        discount = f"%{deal.discount_pct:.0f} *(ilanda)*"
    elif result.estimated_normal_price and deal.price and result.estimated_normal_price > deal.price:
        pct = (result.estimated_normal_price - deal.price) / result.estimated_normal_price * 100
        discount = f"yaklaşık %{pct:.0f} *(AI tahmini)*"

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

    def _call(self, method: str, payload: dict, timeout: int = 20):
        resp = requests.post(_BASE.format(token=self.token, method=method),
                             json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def send(self, deal: RawDeal, result: AnalysisResult, deal_score: int) -> bool:
        text = build_message(deal, result, deal_score)
        if self.dry_run:
            logger.info("[DRY-RUN] Telegram mesajı:\n%s\n", text)
            print("\n" + "=" * 60 + "\n" + text + "\n" + "=" * 60)
            return True
        try:
            self._call("sendMessage", {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False,
                "reply_markup": _feedback_keyboard(deal.deal_id),
            })
            return True
        except Exception as exc:
            logger.error("Telegram gönderim hatası: %s", exc)
            return False

    def send_text(self, text: str) -> bool:
        """Düz metin/Markdown mesaj (günlük özet vb.)."""
        if self.dry_run:
            logger.info("[DRY-RUN] Telegram metni:\n%s\n", text)
            print("\n" + "=" * 60 + "\n" + text + "\n" + "=" * 60)
            return True
        try:
            self._call("sendMessage", {
                "chat_id": self.chat_id, "text": text,
                "parse_mode": "Markdown", "disable_web_page_preview": True,
            })
            return True
        except Exception as exc:
            logger.error("Telegram gönderim hatası: %s", exc)
            return False

    def poll_feedback(self, db) -> int:
        """Biriken buton basışlarını getUpdates ile çekip DB'ye kaydeder.

        Offset DB'de saklanır (meta tablosu), böylece koşular arası tekrar işlenmez.
        İşlenen geri bildirim sayısını döndürür.
        """
        if self.dry_run:
            return 0
        offset = db.get_meta("tg_update_offset")
        params = {"timeout": 0, "allowed_updates": ["callback_query"]}
        if offset:
            params["offset"] = int(offset)
        try:
            data = self._call("getUpdates", params, timeout=25)
        except Exception as exc:
            logger.warning("getUpdates hatası: %s", exc)
            return 0

        processed = 0
        max_update_id = None
        for upd in data.get("result", []):
            max_update_id = upd["update_id"]
            cq = upd.get("callback_query")
            if not cq:
                continue
            payload = cq.get("data", "")
            if payload.startswith("fb:"):
                _, _, rest = payload.partition("fb:")
                kind, _, deal_id = rest.partition(":")
                db.record_feedback(deal_id, kind)
                processed += 1
                title = db.deal_title(deal_id) or "ilan"
                label = _FEEDBACK_LABELS.get(kind, kind)
                # Kullanıcıya küçük onay (toast); eski callback'lerde sessizce geç.
                try:
                    self._call("answerCallbackQuery", {
                        "callback_query_id": cq["id"],
                        "text": f"Kaydedildi: {label}",
                    })
                except Exception:
                    pass
                logger.info("Geri bildirim: %s → %s (%s)", label, title[:40], deal_id)
        if max_update_id is not None:
            db.set_meta("tg_update_offset", str(max_update_id + 1))
        return processed

"""Ana scheduler ve orkestrasyon.

Akış (her tarama):
  1. Kaynaklardan ham ilanları çek
  2. DB dedup + ucuz ön filtre ile ele
  3. Geçenleri AI ile analiz et, skorla
  4. approved && skor >= eşik → Telegram bildirimi
  5. Tüm değerlendirilenleri (reddedilenler dahil) DB'ye yaz

Kullanım:
  python main.py --once            # tek tarama
  python main.py --once --dry-run  # anahtarsız uçtan uca test
  python main.py                   # sürekli (config'deki interval ile)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone

import yaml
from dotenv import load_dotenv

from analyzers import scoring
from analyzers.base_analyzer import LLMAnalyzer
from analyzers.gemini_analyzer import DryRunAnalyzer, GeminiAnalyzer
from analyzers.pre_filter import pre_filter
from notifications.telegram_notifier import TelegramNotifier
from sources.base import DealSource
from sources.rss_source import RssSource
from storage.database import Database

logger = logging.getLogger("firsat_avcisi")


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def build_sources(config: dict) -> list[DealSource]:
    """config.sources altındaki her etkin kaynağı kurar.

    Her kaynak adı bir blok: {enabled, type, feeds, ...}. type varsayılan "rss".
    Yeni bir RSS kaynağı eklemek için sadece config'e blok eklemek yeterlidir.
    """
    sources: list[DealSource] = []
    for name, cfg in config.get("sources", {}).items():
        if not cfg.get("enabled"):
            continue
        src_type = cfg.get("type", "rss")
        if src_type == "rss":
            sources.append(
                RssSource(
                    name=name,
                    feeds=cfg.get("feeds", []),
                    request_timeout_seconds=cfg.get("request_timeout_seconds", 20),
                )
            )
        else:
            logger.warning("Bilinmeyen kaynak tipi '%s' (kaynak: %s) — atlandı.",
                           src_type, name)
    return sources


def build_analyzer(config: dict, dry_run: bool) -> LLMAnalyzer:
    ai = config.get("ai", {})
    provider = ai.get("provider", "gemini")
    api_key = os.getenv("GEMINI_API_KEY")

    if dry_run or provider == "dryrun" or not api_key:
        if not dry_run and provider == "gemini" and not api_key:
            logger.warning("GEMINI_API_KEY yok → DryRunAnalyzer kullanılıyor.")
        return DryRunAnalyzer(
            reject_keywords=config.get("reject_keywords", []),
            preferred_models=config.get("preferred_models", []),
        )
    return GeminiAnalyzer(
        api_key=api_key,
        model=ai.get("model", "gemini-2.5-flash"),
        temperature=ai.get("temperature", 0.1),
        timeout_seconds=ai.get("timeout_seconds", 60),
    )


def run_once(config: dict, db: Database, sources: list[DealSource],
             analyzer: LLMAnalyzer, notifier: TelegramNotifier) -> None:
    filters = config.get("filters", {})
    preferred = config.get("preferred_models", [])
    min_score = filters.get("min_deal_score", 70)

    # Önce biriken Telegram buton geri bildirimlerini işle (getUpdates)
    fb = notifier.poll_feedback(db)
    if fb:
        logger.info("%d geri bildirim işlendi.", fb)

    stats = {"fetched": 0, "prefiltered": 0, "analyzed": 0, "notified": 0}

    for source in sources:
        for deal in source.fetch():
            stats["fetched"] += 1

            # 1) Dedup — daha önce görülmüşse atla
            if db.is_seen(deal.deal_id):
                logger.debug("Atlandı (görülmüş): %s", deal.title[:60])
                continue

            # 2) Ucuz ön filtre
            pf = pre_filter(deal, config)
            if not pf.passed:
                stats["prefiltered"] += 1
                logger.info("Ön filtre eledi [%s]: %s", pf.reason, deal.title[:60])
                db.upsert_deal(deal, approved=False, deal_score=0,
                               rejection_reason=f"ön filtre: {pf.reason}")
                continue

            # 3) AI analizi + skor
            stats["analyzed"] += 1
            result = analyzer.analyze(deal)
            deal_score = scoring.score(result, deal, preferred)
            result.deal_score = result.deal_score or deal_score

            should_notify = result.approved and deal_score >= min_score
            db.upsert_deal(
                deal,
                approved=result.approved,
                deal_score=deal_score,
                rejection_reason=result.rejection_reason,
                analysis=result,
            )
            logger.info(
                "Analiz: %s | approved=%s skor=%d/100 → %s",
                deal.title[:50], result.approved, deal_score,
                "BİLDİR" if should_notify else "geç",
            )

            # 4) Bildirim
            if should_notify:
                if notifier.send(deal, result, deal_score):
                    db.mark_notified(deal.deal_id)
                    stats["notified"] += 1

    logger.info(
        "Tarama bitti — çekilen=%d, ön-filtre-elenen=%d, AI-analiz=%d, bildirilen=%d",
        stats["fetched"], stats["prefiltered"], stats["analyzed"], stats["notified"],
    )


def run_digest(config: dict, db: Database, notifier: TelegramNotifier) -> None:
    """Belirlenen dönemdeki fırsatların Telegram'a kısa özetini gönderir."""
    from datetime import timedelta

    hours = config.get("digest", {}).get("period_hours", 24)
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    rows = db.deals_since(since)
    approved = [r for r in rows if r["approved"]]
    notified = [r for r in rows if r["notified_at"]]

    lines = [f"*📊 Günlük Özet* — son {hours} saat", ""]
    lines.append(f"Görülen ilan: *{len(rows)}* · Onaylanan: *{len(approved)}* · "
                 f"Bildirilen: *{len(notified)}*")
    if approved:
        lines += ["", "*En iyi fırsatlar:*"]
        for r in approved[:5]:
            price = f"{r['price']:.0f} €" if r["price"] is not None else "—"
            title = (r["title"] or "")[:45]
            lines.append(f"• {r['deal_score']}/100 · {price} · [{title}]({r['url']})")
    else:
        lines += ["", "Bu dönemde onaylanan fırsat yok."]
    notifier.send_text("\n".join(lines))
    logger.info("Günlük özet gönderildi (%d ilan).", len(rows))


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Premium Laptop Fırsat Avcısı")
    parser.add_argument("--once", action="store_true", help="Tek tarama yap ve çık")
    parser.add_argument("--digest", action="store_true",
                        help="Tarama yapma; sadece günlük özet gönder")
    parser.add_argument("--dry-run", action="store_true",
                        help="API anahtarı kullanmadan test (Gemini/Telegram mock)")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    # Windows konsolları sıklıkla cp1254/cp1252 kullanır; emoji ve Türkçe
    # karakterlerin çökme yapmaması için çıktıyı UTF-8'e ayarla.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    load_dotenv()
    config = load_config(args.config)

    db = Database(config.get("storage", {}).get("database_path", "deals.db"))
    notifier = TelegramNotifier(
        token=os.getenv("TELEGRAM_BOT_TOKEN"),
        chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        dry_run=args.dry_run,
    )

    # Özet modu: tarama/kaynak/analizör gerektirmez
    if args.digest:
        try:
            run_digest(config, db, notifier)
        finally:
            db.close()
        return

    sources = build_sources(config)
    analyzer = build_analyzer(config, args.dry_run)

    logger.info("Başlatıldı — %d kaynak, analizör=%s, telegram_dry_run=%s",
                len(sources), type(analyzer).__name__, notifier.dry_run)

    try:
        if args.once:
            run_once(config, db, sources, analyzer, notifier)
        else:
            interval = config.get("polling", {}).get("interval_seconds", 120)
            while True:
                run_once(config, db, sources, analyzer, notifier)
                logger.info("%d sn bekleniyor...", interval)
                time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("Durduruldu.")
    finally:
        db.close()


if __name__ == "__main__":
    main()

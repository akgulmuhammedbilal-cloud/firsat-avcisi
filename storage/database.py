"""SQLite kayıt sistemi: mükerrer kontrol, ilan kaydı ve analiz geçmişi."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from storage.models import AnalysisResult, RawDeal

_SCHEMA = """
CREATE TABLE IF NOT EXISTS deals (
    deal_id          TEXT PRIMARY KEY,
    source           TEXT NOT NULL,
    title            TEXT NOT NULL,
    url              TEXT NOT NULL,
    price            REAL,
    detected_model   TEXT,
    approved         INTEGER NOT NULL DEFAULT 0,
    deal_score       INTEGER NOT NULL DEFAULT 0,
    rejection_reason TEXT,
    analysis_json    TEXT,
    first_seen_at    TEXT NOT NULL,
    last_seen_at     TEXT NOT NULL,
    notified_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_deals_source ON deals(source);
CREATE INDEX IF NOT EXISTS idx_deals_score  ON deals(deal_score);

-- Telegram buton geri bildirimleri (Alındı/Gereksiz/Pahalı/İyi)
CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id    TEXT NOT NULL,
    feedback   TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_deal ON feedback(deal_id);

-- Genel anahtar/değer (ör. telegram getUpdates offset)
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """deals.db üzerinde dedup ve kayıt işlemleri."""

    def __init__(self, path: str = "deals.db") -> None:
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # --- dedup -----------------------------------------------------------
    def is_seen(self, deal_id: str) -> bool:
        """Bu ilan daha önce kaydedildi mi (analiz edilmiş/değerlendirilmiş)?"""
        cur = self.conn.execute(
            "SELECT 1 FROM deals WHERE deal_id = ?", (deal_id,)
        )
        return cur.fetchone() is not None

    def is_notified(self, deal_id: str) -> bool:
        cur = self.conn.execute(
            "SELECT notified_at FROM deals WHERE deal_id = ?", (deal_id,)
        )
        row = cur.fetchone()
        return bool(row and row["notified_at"])

    # --- kayıt -----------------------------------------------------------
    def upsert_deal(
        self,
        deal: RawDeal,
        approved: bool,
        deal_score: int,
        rejection_reason: str = "",
        analysis: Optional[AnalysisResult] = None,
    ) -> None:
        """İlanı ekle ya da varsa last_seen_at/skor alanlarını güncelle."""
        now = _now()
        detected_model = analysis.detected_model if analysis else None
        analysis_json = json.dumps(analysis.to_dict(), ensure_ascii=False) if analysis else None
        self.conn.execute(
            """
            INSERT INTO deals (
                deal_id, source, title, url, price, detected_model,
                approved, deal_score, rejection_reason, analysis_json,
                first_seen_at, last_seen_at, notified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(deal_id) DO UPDATE SET
                last_seen_at     = excluded.last_seen_at,
                price            = excluded.price,
                approved         = excluded.approved,
                deal_score       = excluded.deal_score,
                rejection_reason = excluded.rejection_reason,
                detected_model   = excluded.detected_model,
                analysis_json    = excluded.analysis_json
            """,
            (
                deal.deal_id, deal.source, deal.title, deal.url, deal.price,
                detected_model, int(approved), deal_score, rejection_reason,
                analysis_json, now, now,
            ),
        )
        self.conn.commit()

    def mark_notified(self, deal_id: str) -> None:
        self.conn.execute(
            "UPDATE deals SET notified_at = ? WHERE deal_id = ?", (_now(), deal_id)
        )
        self.conn.commit()

    # --- meta (anahtar/değer) --------------------------------------------
    def get_meta(self, key: str, default: str | None = None) -> str | None:
        cur = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()

    # --- geri bildirim ---------------------------------------------------
    def record_feedback(self, deal_id: str, feedback: str) -> None:
        self.conn.execute(
            "INSERT INTO feedback (deal_id, feedback, created_at) VALUES (?, ?, ?)",
            (deal_id, feedback, _now()),
        )
        self.conn.commit()

    def deal_title(self, deal_id: str) -> str | None:
        cur = self.conn.execute("SELECT title FROM deals WHERE deal_id = ?", (deal_id,))
        row = cur.fetchone()
        return row["title"] if row else None

    # --- günlük özet ------------------------------------------------------
    def deals_since(self, since_iso: str) -> list[sqlite3.Row]:
        """since_iso'dan beri ilk görülen ilanları skora göre döndürür."""
        cur = self.conn.execute(
            "SELECT title, url, price, deal_score, approved, notified_at "
            "FROM deals WHERE first_seen_at >= ? ORDER BY deal_score DESC",
            (since_iso,),
        )
        return cur.fetchall()

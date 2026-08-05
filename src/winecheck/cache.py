"""Cache auf Platte (sqlite).

Key = Quelle + normalisierter Name + Jahrgang, mit Zeitstempel. Getrennte
Gültigkeiten, weil sich die Daten unterschiedlich schnell ändern:

============================  ========
Bewertungen                   90 Tage
Preise                         1 Tag
``rating_not_readable``        30 Tage
``no_entry``                   30 Tage
``blocked``                    bis zum vermerkten Retry-Zeitpunkt
============================  ========

Die 30 Tage für Nicht-Treffer sind der Grund, warum ``diff.md`` neu aufgetauchte
Vivino-Bewertungen zeigen kann: der Eintrag verfällt, wird neu geprüft, und wenn dann
eine Note da ist, fällt das auf.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .names import normalized_name

TTL_RATING_DAYS = 90
TTL_PRICE_DAYS = 1
TTL_SOFT_MISS_DAYS = 30      # rating_not_readable, no_entry

#: Status-Werte, die nur kurz gecacht werden, weil Vivino-Einträge dazukommen.
SOFT_MISS_STATUSES = {"rating_not_readable", "no_entry", "too_few_ratings", "ambiguous"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ratings (
    source        TEXT NOT NULL,
    name_key      TEXT NOT NULL,
    vintage       TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT '',
    payload       TEXT NOT NULL,
    fetched_at    REAL NOT NULL,
    retry_after   TEXT,
    PRIMARY KEY (source, name_key, vintage)
);
CREATE TABLE IF NOT EXISTS offers (
    retailer      TEXT NOT NULL,
    name_key      TEXT NOT NULL,
    vintage       TEXT NOT NULL,
    payload       TEXT NOT NULL,
    fetched_at    REAL NOT NULL,
    PRIMARY KEY (retailer, name_key, vintage)
);
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    REAL NOT NULL,
    label         TEXT NOT NULL DEFAULT '',
    snapshot      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ratings_status ON ratings(status);
"""


def _key(name: str, vintage: int | None) -> tuple[str, str]:
    return normalized_name(name), str(vintage or "")


@dataclass
class Cache:
    path: Path
    conn: sqlite3.Connection

    @classmethod
    def open(cls, path: Path | str = "cache/winecheck.sqlite") -> Cache:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(p)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        conn.commit()
        return cls(path=p, conn=conn)

    def close(self) -> None:
        self.conn.close()

    # -- Bewertungen -------------------------------------------------------
    def get_rating(
        self,
        source: str,
        name: str,
        vintage: int | None,
        *,
        refresh: bool = False,
        retry_failed: bool = False,
    ) -> dict[str, Any] | None:
        if refresh:
            return None
        nk, vt = _key(name, vintage)
        row = self.conn.execute(
            "SELECT * FROM ratings WHERE source=? AND name_key=? AND vintage=?",
            (source, nk, vt),
        ).fetchone()
        if row is None:
            return None

        status = row["status"] or ""
        age_days = (time.time() - row["fetched_at"]) / 86400.0

        if status == "blocked":
            if retry_failed:
                return None
            # Blockaden bis zum vermerkten Retry-Zeitpunkt halten.
            retry_at = row["retry_after"]
            if retry_at and _in_past(retry_at):
                return None
            if age_days > 1:
                return None
        elif status in SOFT_MISS_STATUSES:
            if retry_failed or age_days > TTL_SOFT_MISS_DAYS:
                return None
        elif age_days > TTL_RATING_DAYS:
            return None

        return json.loads(row["payload"])

    def put_rating(
        self,
        source: str,
        name: str,
        vintage: int | None,
        payload: dict[str, Any],
        *,
        status: str = "",
        retry_after: str | None = None,
    ) -> None:
        nk, vt = _key(name, vintage)
        self.conn.execute(
            "INSERT INTO ratings (source, name_key, vintage, status, payload, fetched_at, retry_after) "
            "VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(source, name_key, vintage) DO UPDATE SET "
            "status=excluded.status, payload=excluded.payload, "
            "fetched_at=excluded.fetched_at, retry_after=excluded.retry_after",
            (source, nk, vt, status, json.dumps(payload, ensure_ascii=False), time.time(), retry_after),
        )
        self.conn.commit()

    # -- Angebote ----------------------------------------------------------
    def get_offer(self, retailer: str, name: str, vintage: int | None, *, refresh: bool = False):
        if refresh:
            return None
        nk, vt = _key(name, vintage)
        row = self.conn.execute(
            "SELECT * FROM offers WHERE retailer=? AND name_key=? AND vintage=?",
            (retailer, nk, vt),
        ).fetchone()
        if row is None:
            return None
        if (time.time() - row["fetched_at"]) / 86400.0 > TTL_PRICE_DAYS:
            return None
        return json.loads(row["payload"])

    def put_offer(self, retailer: str, name: str, vintage: int | None, payload: dict[str, Any]) -> None:
        nk, vt = _key(name, vintage)
        self.conn.execute(
            "INSERT INTO offers (retailer, name_key, vintage, payload, fetched_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(retailer, name_key, vintage) DO UPDATE SET "
            "payload=excluded.payload, fetched_at=excluded.fetched_at",
            (retailer, nk, vt, json.dumps(payload, ensure_ascii=False), time.time()),
        )
        self.conn.commit()

    def all_offers(self, *, max_age_days: float = TTL_PRICE_DAYS * 7) -> list[dict[str, Any]]:
        """Alle noch brauchbaren Angebote — Grundlage für ``rate`` und ``report``,
        damit die Schritte getrennt laufen können."""
        cutoff = time.time() - max_age_days * 86400
        rows = self.conn.execute(
            "SELECT payload FROM offers WHERE fetched_at >= ?", (cutoff,)
        ).fetchall()
        return [json.loads(r["payload"]) for r in rows]

    def clear_offers(self, retailer: str) -> None:
        self.conn.execute("DELETE FROM offers WHERE retailer=?", (retailer,))
        self.conn.commit()

    # -- Läufe (für diff.md) ----------------------------------------------
    def save_snapshot(self, snapshot: list[dict[str, Any]], label: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (started_at, label, snapshot) VALUES (?,?,?)",
            (time.time(), label, json.dumps(snapshot, ensure_ascii=False)),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def previous_snapshot(self, before_id: int | None = None) -> tuple[int | None, list[dict[str, Any]]]:
        """Letzter Lauf vor ``before_id`` — Basis für ``diff.md``."""
        if before_id is None:
            row = self.conn.execute(
                "SELECT id, snapshot FROM runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT id, snapshot FROM runs WHERE id < ? ORDER BY id DESC LIMIT 1", (before_id,)
            ).fetchone()
        if not row:
            return None, []
        return int(row["id"]), json.loads(row["snapshot"] or "[]")

    def stats(self) -> dict[str, int]:
        q = self.conn.execute
        return {
            "ratings": q("SELECT COUNT(*) c FROM ratings").fetchone()["c"],
            "offers": q("SELECT COUNT(*) c FROM offers").fetchone()["c"],
            "runs": q("SELECT COUNT(*) c FROM runs").fetchone()["c"],
            "blocked": q("SELECT COUNT(*) c FROM ratings WHERE status='blocked'").fetchone()["c"],
        }


def _in_past(timestamp: str) -> bool:
    try:
        t = time.mktime(time.strptime(timestamp, "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        return True
    return t <= time.time()

"""Cache auf Platte (sqlite).

Key = Quelle + normalisierter Name + Jahrgang, mit Zeitstempel. Getrennte
Gültigkeiten, weil sich die Daten unterschiedlich schnell ändern:

============================  ========
Bewertungen                   90 Tage
Preise                         7 Tage
``rating_not_readable``        30 Tage
``no_entry``                   30 Tage
``blocked``                    bis zum vermerkten Retry-Zeitpunkt, höchstens 7 Tage
============================  ========

Bei den Preisen stand hier „1 Tag", und das galt nirgends: der Wert kam nur in
``get_offer`` vor, und diese Methode hatte keinen einzigen Aufrufer. Wirksam ist
allein das Fenster von :meth:`Cache.all_offers`, also sieben Tage. Lieber die
tatsächliche Zahl als eine strengere, die nicht stimmt.

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

#: Wie lange ein Angebotspreis gilt. Hier stand ``TTL_PRICE_DAYS = 1``, benutzt wurde
#: aber ausschliesslich ``TTL_PRICE_DAYS * 7`` — die Eins war nie eine Frist, sondern
#: ein Faktor, und der Modulkopf hat sie als Frist dokumentiert. Jetzt steht die Zahl
#: da, die gilt.
TTL_PREIS_TAGE = 7
TTL_SOFT_MISS_DAYS = 30      # rating_not_readable, no_entry

#: Bewertungen ändern sich langsam, Preise nicht. Trägt ein Eintrag einen
#: Vivino-Marktpreis, wird er nach dieser Zeit neu geholt — sonst stünde im Report
#: monatelang ein alter Marktpreis und damit ein falsches Schnäppchen-Prozent.
TTL_MARKET_PRICE_DAYS = 30

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
    -- "source_key", nicht "retailer": hier steht der Schluessel des *Adapters*, nicht
    -- der Haendler. Fuer den Aggregator Aktionis ist es "aktionis", waehrend die
    -- Angebote darunter zu Coop, Denner, Otto's, Volg und SPAR gehoeren — der echte
    -- Haendler steht im Payload.
    --
    -- Die Spalte hiess "retailer" und hat genau dadurch eine falsche Auswertung
    -- erzeugt: eine Zaehlung je Haendler ueber diese Spalte ergab, fuenf Haendler
    -- seien auf null gefallen. Sie waren vollstaendig da, nur unter "aktionis".
    source_key    TEXT NOT NULL,
    name_key      TEXT NOT NULL,
    vintage       TEXT NOT NULL,
    payload       TEXT NOT NULL,
    fetched_at    REAL NOT NULL,
    PRIMARY KEY (source_key, name_key, vintage)
);
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    REAL NOT NULL,
    label         TEXT NOT NULL DEFAULT '',
    snapshot      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ratings_status ON ratings(status);
"""


#: Stand des Schemas. Wird als ``PRAGMA user_version`` in der Datei vermerkt.
#:
#: Vorher gab es keinen Ort, an dem ein Cache seinen Stand notiert: ``_SCHEMA``
#: arbeitet mit ``CREATE TABLE IF NOT EXISTS``, ``_migriere`` prüfte per Introspektion,
#: und ``user_version`` blieb auf 0. Ein Klon konnte damit nicht feststellen, dass sein
#: Cache älter ist als der Code — der Bruch zeigte sich erst als ``OperationalError``
#: zur Laufzeit, im Wochenlauf freitags um 07:00 ohne Beobachter.
#:
#: 1 = Ausgangsstand, 2 = ``offers.retailer`` heisst ``source_key``.
SCHEMA_VERSION = 2

#: Aufbewahrung der Lauf-Schnappschüsse.
#:
#: ``save_snapshot`` ersetzt nur den Lauf desselben Kalendertages; darüber hinaus wuchs
#: die Tabelle unbegrenzt. Gemessen: 2.67 MB je Lauf bei 2206 Weinen, 74 % der
#: 16.8-MB-Datei, nach einem Jahr Wochenläufen 157 MB. Das trifft jede Abfrage, die
#: die Spalte liest, und die Datei liegt zudem in einem synchronisierten Ordner.
#:
#: 26 statt 12: ``site --runs 12`` ist dokumentiert, und der älteste angezeigte Lauf
#: braucht einen Vorgänger für den Vergleich. Ein halbes Jahr Aktionswochen.
RUNS_AUFBEWAHRUNG = 26


def _key(name: str, vintage: int | None) -> tuple[str, str]:
    return normalized_name(name), str(vintage or "")


def _migriere(conn: sqlite3.Connection) -> None:
    """Bestehende Caches auf das aktuelle Schema bringen.

    Nur eine Wanderung bisher: die Spalte ``offers.retailer`` heisst ``source_key``,
    weil dort der Adapter-Schluessel steht und nicht der Haendler. Fuer den Aggregator
    Aktionis ist es "aktionis", waehrend die Angebote darunter zu Coop, Denner, Otto's,
    Volg und SPAR gehoeren.

    Der alte Name hat eine falsche Auswertung erzeugt: eine Zaehlung je Haendler ueber
    diese Spalte ergab, fuenf Haendler seien auf null gefallen — sie waren vollstaendig
    da, nur unter "aktionis" gebucht.

    Umbenennen statt neu aufbauen: der Cache ist regenerierbar, aber ein voller
    ``fetch`` kostet Anfragen bei siebzehn Quellen, und ein ``rate`` danach Stunden. Wer
    das Werkzeug aktualisiert, soll seinen Bestand behalten.
    """
    stand = conn.execute("PRAGMA user_version").fetchone()[0]
    if stand > SCHEMA_VERSION:
        raise RuntimeError(
            f"Der Cache trägt Schemastand {stand}, dieser Code kennt nur "
            f"{SCHEMA_VERSION}. Er stammt aus einer neueren Fassung des Werkzeugs — "
            f"erst aktualisieren, sonst gehen Felder verloren."
        )

    hat = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "offers" in hat:
        spalten = {r[1] for r in conn.execute("PRAGMA table_info(offers)")}
        if "retailer" in spalten and "source_key" not in spalten:
            conn.execute("ALTER TABLE offers RENAME COLUMN retailer TO source_key")

    # Den Stand vermerken. Ein leerer Cache bekommt ihn ebenso — er ist per
    # Konstruktion aktuell, und ohne Eintrag würde jede künftige Wanderung ihn für
    # veraltet halten.
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


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
        # Tabellen zuerst, Wanderungen danach. Vorher lief ``_migriere`` davor und
        # brauchte deshalb einen eigenen Existenzwächter; jeder künftige Schritt hätte
        # denselben gebraucht.
        conn.executescript(_SCHEMA)
        _migriere(conn)
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

        payload = json.loads(row["payload"])
        # Der Marktpreis veraltet schneller als die Bewertung.
        if payload.get("market_price") is not None and age_days > TTL_MARKET_PRICE_DAYS:
            return None
        return payload

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
    # ``get_offer`` stand hier: ein Einzelabruf mit einem Ein-Tage-Fenster. Er hatte
    # keinen Aufrufer, und sein TTL-Wert war damit die einzige Stelle, an der die im
    # Modulkopf dokumentierte Gültigkeit „Preise 1 Tag" auftauchte. Entfernt, statt die
    # Doku eine Grenze behaupten zu lassen, die nichts durchsetzt.

    def put_offer(self, source_key: str, name: str, vintage: int | None, payload: dict[str, Any]) -> None:
        nk, vt = _key(name, vintage)
        self.conn.execute(
            "INSERT INTO offers (source_key, name_key, vintage, payload, fetched_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(source_key, name_key, vintage) DO UPDATE SET "
            "payload=excluded.payload, fetched_at=excluded.fetched_at",
            (source_key, nk, vt, json.dumps(payload, ensure_ascii=False), time.time()),
        )
        self.conn.commit()

    def juengstes_angebot(self) -> float | None:
        """Zeitstempel des jüngsten Angebots, oder ``None`` bei leerer Tabelle.

        Gebraucht von ``report``, um einen abgebrochenen ``rate``-Lauf zu erkennen:
        ist der Bewertungsstand älter als die Angebote, die er bewerten soll, dann
        wurde nicht fertig bewertet.
        """
        row = self.conn.execute("SELECT MAX(fetched_at) AS m FROM offers").fetchone()
        return row["m"] if row and row["m"] is not None else None

    def all_offers(self, *, max_age_days: float = TTL_PREIS_TAGE) -> list[dict[str, Any]]:
        """Alle noch brauchbaren Angebote — Grundlage für ``rate`` und ``report``,
        damit die Schritte getrennt laufen können."""
        cutoff = time.time() - max_age_days * 86400
        rows = self.conn.execute(
            "SELECT payload FROM offers WHERE fetched_at >= ?", (cutoff,)
        ).fetchall()
        return [json.loads(r["payload"]) for r in rows]

    def clear_offers(self, source_key: str) -> None:
        self.conn.execute("DELETE FROM offers WHERE source_key=?", (source_key,))
        self.conn.commit()

    # -- Läufe (für diff.md) ----------------------------------------------
    def save_snapshot(self, snapshot: list[dict[str, Any]], label: str = "") -> int:
        """Lauf ablegen — höchstens einer pro Kalendertag.

        Ein Lauf soll eine Aktionswoche sein. Beim Entwickeln oder nach einem
        korrigierten Matcher baut man den Report am selben Tag mehrfach neu, und jeder
        Neubau legte bisher einen eigenen Lauf an: der Lauf-Filter der Webseite füllte
        sich mit zwölf Chips „6.8.2026", `diff.md` verglich gegen den eigenen Neubau
        von vor zehn Minuten (also gegen nichts), und die Seite wuchs mit jedem Lauf um
        rund 100 KB. Der jüngste Stand eines Tages ersetzt darum den älteren.
        """
        now = time.time()
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        for row in self.conn.execute("SELECT id, started_at FROM runs").fetchall():
            if time.strftime("%Y-%m-%d", time.localtime(float(row["started_at"]))) == today:
                self.conn.execute("DELETE FROM runs WHERE id=?", (int(row["id"]),))
        cur = self.conn.execute(
            "INSERT INTO runs (started_at, label, snapshot) VALUES (?,?,?)",
            (now, label, json.dumps(snapshot, ensure_ascii=False)),
        )
        # Aufbewahrungsgrenze: siehe RUNS_AUFBEWAHRUNG. Ohne sie wuchs die Tabelle
        # unbegrenzt, und sie ist der grösste Teil der Datei.
        self.conn.execute(
            "DELETE FROM runs WHERE id NOT IN "
            "(SELECT id FROM runs ORDER BY id DESC LIMIT ?)",
            (RUNS_AUFBEWAHRUNG,),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def previous_snapshot(self, before_id: int | None = None) -> tuple[int | None, list[dict[str, Any]]]:
        """Letzter Lauf vor ``before_id`` — Basis für ``diff.md``.

        Ohne ``before_id`` werden Läufe von *heute* übersprungen. Sonst vergleicht
        ``diff.md`` den Neubau gegen den eigenen Neubau von vor zehn Minuten und meldet
        pflichtschuldig „keine Änderungen" — der Bericht wäre formal richtig und
        praktisch wertlos. Interessant ist der Abstand zur letzten Aktionswoche.
        """
        if before_id is None:
            today = time.strftime("%Y-%m-%d", time.localtime())
            row = None
            for cand in self.conn.execute(
                "SELECT id, started_at, snapshot FROM runs ORDER BY id DESC"
            ).fetchall():
                stamp = time.strftime("%Y-%m-%d", time.localtime(float(cand["started_at"])))
                if stamp != today:
                    row = cand
                    break
        else:
            row = self.conn.execute(
                "SELECT id, snapshot FROM runs WHERE id < ? ORDER BY id DESC LIMIT 1", (before_id,)
            ).fetchone()
        if not row:
            return None, []
        return int(row["id"]), json.loads(row["snapshot"] or "[]")

    def all_runs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """Alle gespeicherten Läufe, neuester zuerst — Grundlage für die Webseite."""
        rows = self.conn.execute(
            "SELECT id, started_at, label, snapshot FROM runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for row in rows:
            try:
                wines = json.loads(row["snapshot"] or "[]")
            except json.JSONDecodeError:
                continue
            if not wines:
                continue
            out.append({
                "id": int(row["id"]),
                "started_at": float(row["started_at"]),
                "label": row["label"] or "",
                "wines": wines,
            })
        return out


    # -- Bewertungen aus- und einlesen -------------------------------------
    #
    # Der sqlite-Cache liegt nicht im Repo: binär, ändert sich bei jedem Lauf. Für den
    # GitHub-Wochenlauf braucht es die Bewertungen aber trotzdem — er holt frische
    # Preise, darf sie aber nicht mit einer leeren Bewertungsspalte veröffentlichen,
    # und selbst nachfragen kann er nicht, weil Vivino Rechenzentrums-IPs sperrt.
    # Darum ein schlanker, versionierbarer Auszug: nur die Bewertungen, als JSON.

    def export_ratings(self) -> list[dict[str, Any]]:
        """Alle Bewertungen als Liste — für die versionierte Datei."""
        out = []
        for row in self.conn.execute(
            "SELECT source, name_key, vintage, status, payload, fetched_at, retry_after "
            "FROM ratings ORDER BY source, name_key"
        ):
            out.append({k: row[k] for k in row.keys()})
        return out

    def import_ratings(self, rows: list[dict[str, Any]], *, overwrite: bool = False) -> int:
        """Bewertungen einspielen.

        Args:
            overwrite: Ohne dies bleiben vorhandene Einträge stehen — ein lokaler Lauf
                hat frischere Daten als die eingecheckte Datei und soll sie behalten.
        """
        n = 0
        for r in rows or []:
            if not overwrite:
                vorhanden = self.conn.execute(
                    "SELECT 1 FROM ratings WHERE source=? AND name_key=? AND vintage IS ?",
                    (r.get("source"), r.get("name_key"), r.get("vintage")),
                ).fetchone()
                if vorhanden:
                    continue
            self.conn.execute(
                "INSERT OR REPLACE INTO ratings "
                "(source, name_key, vintage, status, payload, fetched_at, retry_after) "
                "VALUES (?,?,?,?,?,?,?)",
                (r.get("source"), r.get("name_key"), r.get("vintage"), r.get("status"),
                 r.get("payload"), r.get("fetched_at"), r.get("retry_after")),
            )
            n += 1
        self.conn.commit()
        return n

    def verwerfe_ratings_ohne_feld(self, quelle: str, feld: str) -> int:
        """Löscht Bewertungen mit Treffer, denen ein Payload-Feld fehlt.

        Der Nachtrag-Modus. Wird ein Feld an der Antwort einer Bewertungsquelle
        ergänzt, tragen die bestehenden Cache-Einträge es nicht — und bisher gab es
        dafür nur ``rate --refresh``, also einen Volllauf über alles.

        Was das kostet, ist gemessen: 1567 Weine bei rund sechs Sekunden je Wein sind
        zweieinhalb Stunden. Als am 10.8.2026 ``region_name`` nachgezogen wurde, waren
        es zwei Läufe hintereinander, weil der erste noch mit dem alten Code lief —
        gut vier Stunden für ein Feld, das in derselben Antwort schon mitkam.

        Gelöscht wird nur, was einen Treffer hat: Einträge ohne Kandidaten können das
        Feld gar nicht tragen, und sie erneut abzufragen wäre die Arbeit, die
        ``--retry-failed`` macht.

        Rückgabe: Zahl der verworfenen Einträge. Der nächste ``rate``-Lauf fragt genau
        diese neu ab und lässt alles andere aus dem Cache stehen.
        """
        mit_treffer = ("exact", "wine_level", "too_few_ratings", "winery_level")
        rows = self.conn.execute(
            "SELECT rowid, payload, status FROM ratings WHERE source=?", (quelle,)
        ).fetchall()
        weg = []
        for r in rows:
            if (r["status"] or "") not in mit_treffer:
                continue
            try:
                payload = json.loads(r["payload"] or "{}")
            except json.JSONDecodeError:
                weg.append(r["rowid"])
                continue
            if not payload.get(feld):
                weg.append(r["rowid"])
        if weg:
            self.conn.executemany(
                "DELETE FROM ratings WHERE rowid=?", [(x,) for x in weg]
            )
            self.conn.commit()
        return len(weg)

    def verwerfe_ratings_mit_konfidenz(self, quelle: str, stufe: str) -> int:
        """Löscht Bewertungen einer bestimmten Konfidenzstufe.

        Geschwistermethode zu :meth:`verwerfe_ratings_ohne_feld`, für den anderen
        Anlass: nicht ein neues Feld, sondern eine geänderte **Entscheidungsregel**.

        Gebaut, als auffiel, dass die Kandidaten bei Punktgleichstand alphabetisch
        sortiert wurden und „fuzzy" damit vor „wine_level" gewann — „Rocca di
        Frassinello la Rocca" (CHF 37.50) trug die Note des Baffonero (rund CHF 200).
        Betroffen sein können nur Einträge, die als ``fuzzy`` endeten; alle anderen
        neu abzufragen wären zweieinhalb Stunden für nichts.

        Rückgabe: Zahl der verworfenen Einträge.
        """
        rows = self.conn.execute(
            "SELECT rowid, payload FROM ratings WHERE source=?", (quelle,)
        ).fetchall()
        weg = []
        for r in rows:
            try:
                payload = json.loads(r["payload"] or "{}")
            except json.JSONDecodeError:
                continue
            if (payload.get("match_confidence") or "") == stufe:
                weg.append(r["rowid"])
        if weg:
            self.conn.executemany("DELETE FROM ratings WHERE rowid=?", [(x,) for x in weg])
            self.conn.commit()
        return len(weg)

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

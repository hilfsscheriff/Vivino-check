"""Falstaff-Adapter — als Leitquelle fürs Ranking vorgesehen.

**Aktueller Zugangsstatus: blockiert.** Die gesamte Domain ``falstaff.com`` antwortet
auf Anfragen ohne Browser-Fingerprint mit HTTP 403 und der Cloudflare-Seite
"Attention Required" — Startseite, Wine-Guide und sogar die ``sitemap.xml``, die
``robots.txt`` selbst ankündigt. Das ist eine Firewall-Regel, keine JS-Challenge;
andere Header ändern nichts. ``falstaff.ch`` leitet per 301 auf ``falstaff.com``.

Laut Auftrag wird eine solche Schutzmassnahme bei einer öffentlichen Quelle **nicht
umgangen**. Der Adapter ist deshalb vollständig gebaut, meldet aber ``blocked`` mit
Retry-Zeitpunkt und schreibt das in den Cache. Sobald Zugang besteht — Abo,
API-Schlüssel, Freischaltung der IP —, greift er ohne Codeänderung.

Der Parser unten ist an der öffentlich dokumentierten Struktur der Falstaff-
Weinseiten orientiert und **nicht gegen echte Antworten verifiziert**, weil keine
abrufbar waren. Er ist bewusst so geschrieben, dass er im Zweifel nichts liefert
statt etwas zu erfinden.
"""

from __future__ import annotations

import re
import time
import urllib.parse

from selectolax.parser import HTMLParser

from ..fetching import Blocked, Fetcher
from ..matching import rank_candidates
from ..models import MatchConfidence, Rating
from ..names import tokenize

SEARCH_URL = "https://www.falstaff.com/de/suche?q={query}"
SCALE_MAX = 100.0

#: Falstaff punktet 0–100; alles darunter ist keine Falstaff-Note.
_RE_POINTS = re.compile(r"\b(\d{2,3})\s*(?:falstaff\s*)?punkte?\b", re.I)
_RE_POINTS_ATTR = re.compile(r"^\s*(\d{2,3})\s*$")


def build_query(name: str) -> str:
    return " ".join(tokenize(name)[:8]) or (name or "").strip()


def search_url(name: str) -> str:
    return SEARCH_URL.format(query=urllib.parse.quote_plus(build_query(name)))


class FalstaffAdapter:
    """Leitquelle fürs Ranking, solange erreichbar."""

    source = "falstaff"
    scale_max = SCALE_MAX

    def __init__(self, fetcher: Fetcher, *, cache=None):
        self.fetcher = fetcher
        self.cache = cache

    def lookup(
        self,
        name: str,
        vintage: int | None = None,
        *,
        refresh: bool = False,
        retry_failed: bool = False,
    ) -> Rating:
        """Liefert immer ein :class:`Rating` — mit ``value=None`` und Klartext-Notiz,
        wenn nichts zu holen war."""
        if self.cache is not None:
            cached = self.cache.get_rating(
                self.source, name, vintage, refresh=refresh, retry_failed=retry_failed
            )
            if cached:
                return _from_payload(cached)

        query = build_query(name)
        url = search_url(name)
        try:
            res = self.fetcher.get(url)
            rating = self._parse(res.text, name, vintage, url)
        except Blocked as exc:
            retry_at = exc.retry_after or time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + 86400)
            )
            rating = Rating(
                source=self.source,
                value=None,
                scale_max=SCALE_MAX,
                url=url,
                status="blocked",
                note=(
                    f"Falstaff nicht erreichbar ({exc.kind}) — Schutzmassnahme wird "
                    f"nicht umgangen, erneut ab {retry_at}"
                ),
            )
            if self.cache is not None:
                self.cache.put_rating(
                    self.source, name, vintage, _to_payload(rating),
                    status="blocked", retry_after=retry_at,
                )
            return rating

        if self.cache is not None:
            self.cache.put_rating(
                self.source, name, vintage, _to_payload(rating), status=rating.status
            )
        return rating

    # ------------------------------------------------------------------ Parser
    def _parse(self, html: str, name: str, vintage: int | None, url: str) -> Rating:
        """Trefferliste auswerten. Ungetestet — siehe Modul-Docstring."""
        tree = HTMLParser(html or "")
        candidates: list[tuple[str, int | None, float | None]] = []
        for node in tree.css("article, li, div.result, div.teaser, .wine-result"):
            text = re.sub(r"\s+", " ", node.text() or "").strip()
            if not text or len(text) > 400:
                continue
            title_node = node.css_first("a, h2, h3, .title")
            title = re.sub(r"\s+", " ", (title_node.text() if title_node else "")).strip()
            if not title:
                continue
            m = _RE_POINTS.search(text)
            points = float(m.group(1)) if m else None
            if points is not None and not (50 <= points <= 100):
                points = None
            year = None
            ym = re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", title)
            if ym:
                year = int(ym.group(1))
            candidates.append((title, year, points))

        if not candidates:
            return Rating(
                source=self.source,
                value=None,
                scale_max=SCALE_MAX,
                url=url,
                status="no_entry",
                note="kein Falstaff-Treffer für diesen Wein — Suche öffnen",
            )

        ranked, ambiguous = rank_candidates(
            name,
            [(t, y, p is not None) for t, y, p in candidates],
            retailer_vintage=vintage,
        )
        if not ranked:
            return Rating(
                source=self.source,
                value=None,
                scale_max=SCALE_MAX,
                url=url,
                status="no_entry",
                note=(
                    f"{len(candidates)} Falstaff-Treffer geprüft, keiner passt zum "
                    f"Wein — Suche öffnen"
                ),
            )
        if ambiguous:
            return Rating(
                source=self.source,
                value=None,
                scale_max=SCALE_MAX,
                url=url,
                status="ambiguous",
                note="mehrere Falstaff-Treffer gleich gut — nicht automatisch zugeordnet",
            )

        top = ranked[0]
        title, year, points = candidates[top.index]
        if points is None:
            return Rating(
                source=self.source,
                value=None,
                scale_max=SCALE_MAX,
                url=url,
                status="rating_not_readable",
                confidence=top.decision.confidence,
                source_name=title,
                note="Falstaff-Seite gefunden, Punktzahl nicht extrahierbar — Seite öffnen",
            )
        return Rating(
            source=self.source,
            value=points,
            scale_max=SCALE_MAX,
            count=None,
            confidence=top.decision.confidence,
            source_name=title,
            url=url,
            status=top.decision.confidence.value,
            note=f"{points:.0f} Falstaff-Punkte ({top.decision.reason})",
        )


def _to_payload(r: Rating) -> dict:
    return {
        "value": r.value,
        "scale_max": r.scale_max,
        "count": r.count,
        "confidence": r.confidence.value,
        "source_name": r.source_name,
        "url": r.url,
        "note": r.note,
        "status": r.status,
    }


def _from_payload(d: dict) -> Rating:
    return Rating(
        source="falstaff",
        value=d.get("value"),
        scale_max=d.get("scale_max") or SCALE_MAX,
        count=d.get("count"),
        confidence=MatchConfidence(d.get("confidence") or "none"),
        source_name=d.get("source_name"),
        url=d.get("url") or "",
        note=d.get("note") or "",
        status=d.get("status") or "",
    )

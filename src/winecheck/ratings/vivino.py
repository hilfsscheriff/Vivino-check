"""Vivino-Adapter — die Pflichtspalte.

Wird für **jeden** Wein aufgerufen, unabhängig davon, ob Falstaff schon einen Wert
geliefert hat. Kein "Abbruch beim ersten Treffer".

Warum der JSON-Endpunkt und nicht die Weinseite
-----------------------------------------------
Die Weinseiten-HTML von Vivino lädt die Note per JavaScript nach — deshalb existiert
der Status ``rating_not_readable``. Der Endpunkt ``/api/explore/explore`` liefert
dieselben Daten strukturiert und unterscheidet dabei sauber zwischen
Jahrgangsschnitt (``ratings_average``/``ratings_count``) und Weinschnitt
(``wine_ratings_average``/``wine_ratings_count``). Genau diese Unterscheidung braucht
die Statuslogik für ``exact`` gegen ``wine_level``. ``robots.txt`` verbietet
``/ajax/``, ``/prices/`` und ``/reviews/``; ``/api/`` und die Weinseiten sind erlaubt.

Wichtig für die Statuslogik: die Vivino-Suche ist auf Recall gebaut, nicht auf
Präzision. Eine Suche nach "Carmelin" liefert "Carmelo Rodero", eine Suche nach
"Col del Sol" liefert "Col Vetoraz". Ohne die Vetos aus :mod:`winecheck.matching`
würde das Tool also munter fremde Bewertungen zuordnen. Die Vetos sind hier
tragendes Element, nicht Feinschliff.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from ..fetching import Blocked, Fetcher
from ..matching import match_winery, rank_candidates
from ..models import (
    MatchConfidence,
    VivinoCandidate,
    VivinoResult,
    VivinoStatus,
    vivino_search_url,
)
from ..names import distinctive_tokens, tokenize

API_URL = "https://www.vivino.com/api/explore/explore"
WINE_URL = "https://www.vivino.com/de/{slug}/w/{wine_id}"
WINERY_URL = "https://www.vivino.com/de/wineries/{slug}"

#: Unter so vielen Bewertungen zeigt Vivino "not enough ratings".
MIN_RATINGS = 5

#: Alle Weintypen, damit unbewertete Weine nicht wegfiltert werden — die brauchen wir
#: für ``too_few_ratings``.
WINE_TYPE_IDS = (1, 2, 3, 4, 7, 24)

MAX_CANDIDATES_SHOWN = 3


@dataclass
class _Cand:
    """Ein Kandidat aus der API, auf das Nötige reduziert."""

    name: str
    wine_name: str
    winery: str
    url: str
    year: int | None
    vintage_avg: float | None
    vintage_count: int
    wine_avg: float | None
    wine_count: int

    @property
    def has_vintage_rating(self) -> bool:
        return self.vintage_count >= MIN_RATINGS and self.vintage_avg is not None


def build_query(name: str, vintage: int | None = None) -> str:
    """Suchbegriff aus der Händler-Bezeichnung.

    Volumen, Gebinde, rechtliche Bezeichnungen und Marketing fliegen raus; der
    Jahrgang bleibt weg, weil die API sonst schlechter greift. Der zurückgegebene
    String landet unverändert in ``vivino_query`` und in der Suchurl — damit sofort
    sichtbar ist, ob ein Nicht-Treffer an der Query oder am Wein lag.
    """
    tokens = tokenize(name)
    return " ".join(tokens[:10]) or (name or "").strip()


def _parse_candidates(payload: dict[str, Any]) -> list[_Cand]:
    ev = payload.get("explore_vintage") or {}
    out: list[_Cand] = []
    seen: set[tuple[int, int | None]] = set()
    for match in ev.get("matches") or []:
        v = match.get("vintage") or {}
        wine = v.get("wine") or {}
        stats = v.get("statistics") or {}
        winery = (wine.get("winery") or {}).get("name") or ""
        wine_id = wine.get("id")
        year_raw = v.get("year")
        try:
            year = int(year_raw) if year_raw not in (None, "", "N.V.") else None
        except (TypeError, ValueError):
            year = None
        if wine_id is None:
            continue
        key = (int(wine_id), year)
        if key in seen:
            continue
        seen.add(key)
        slug = wine.get("seo_name") or v.get("seo_name") or "wine"
        out.append(
            _Cand(
                name=v.get("name") or wine.get("name") or "",
                wine_name=wine.get("name") or "",
                winery=winery,
                url=WINE_URL.format(slug=slug, wine_id=wine_id),
                year=year,
                vintage_avg=_f(stats.get("ratings_average")),
                vintage_count=_i(stats.get("ratings_count")),
                wine_avg=_f(stats.get("wine_ratings_average")),
                wine_count=_i(stats.get("wine_ratings_count")),
            )
        )
    return out


def _f(v: object) -> float | None:
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _i(v: object) -> int:
    try:
        return int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def classify(
    retailer_name: str,
    retailer_vintage: int | None,
    query: str,
    candidates: list[_Cand],
) -> VivinoResult:
    """Ordnet API-Kandidaten einem :class:`VivinoStatus` zu.

    Reine Funktion ohne Netz — deshalb vollständig testbar. Liefert **immer** ein
    Ergebnis mit gesetzter URL: Weinseite falls gefunden, sonst die Suchurl.
    """
    if not candidates:
        return VivinoResult.miss(
            VivinoStatus.NO_ENTRY,
            query,
            "kein Eintrag gefunden — Suche öffnen",
        )

    ranked, ambiguous = rank_candidates(
        retailer_name,
        [(c.name, c.year, c.has_vintage_rating) for c in candidates],
        retailer_vintage=retailer_vintage,
    )

    # -- Kein Wein passt: Produzenten-Pfad, dann no_entry -------------------
    if not ranked:
        for c in candidates:
            if not c.winery:
                continue
            wd = match_winery(retailer_name, c.winery)
            if wd.matched:
                avg, count = (c.wine_avg, c.wine_count)
                if avg is not None and count >= MIN_RATINGS:
                    return VivinoResult(
                        status=VivinoStatus.WINERY_LEVEL,
                        query=query,
                        url=c.url,
                        note=(
                            f"nur Produzenten-Durchschnitt von '{c.winery}' "
                            f"({avg} aus {count} Bewertungen) — der Wein selbst ist nicht bewertet"
                        ),
                        rating=avg,
                        rating_count=count,
                        matched_name=c.winery,
                        match_confidence=MatchConfidence.WINERY_LEVEL.value,
                    )
                return VivinoResult(
                    status=VivinoStatus.TOO_FEW_RATINGS,
                    query=query,
                    url=c.url,
                    note=(
                        f"Produzent '{c.winery}' gefunden, aber "
                        f"{count if count else 'keine'} Bewertungen — Vivino zeigt keine Note"
                    ),
                    rating_count=count or None,
                    matched_name=c.winery,
                    match_confidence=MatchConfidence.WINERY_LEVEL.value,
                )

        best = max(candidates, key=lambda c: c.wine_count)
        return VivinoResult.miss(
            VivinoStatus.NO_ENTRY,
            query,
            (
                f"{len(candidates)} Kandidaten geprüft, keiner passt "
                f"(nächster: '{best.name}') — Suche öffnen"
            ),
        )

    # -- Mehrere gleich gute Kandidaten: nicht wählen, auflisten ------------
    if ambiguous:
        shown = [candidates[r.index] for r in ranked[:MAX_CANDIDATES_SHOWN]]
        return VivinoResult(
            status=VivinoStatus.AMBIGUOUS,
            query=query,
            url=shown[0].url,
            note=(
                f"{len(ranked)} Kandidaten praktisch gleich gut — nicht automatisch "
                f"zugeordnet, bitte selbst wählen"
            ),
            candidates=[
                VivinoCandidate(
                    name=c.name,
                    url=c.url,
                    rating=c.vintage_avg or c.wine_avg,
                    rating_count=c.vintage_count or c.wine_count,
                    vintage=c.year,
                    score=r.decision.score,
                )
                for c, r in zip(shown, ranked[:MAX_CANDIDATES_SHOWN])
            ],
        )

    top = ranked[0]
    c = candidates[top.index]
    decision = top.decision
    suffix = "" if decision.confidence is MatchConfidence.EXACT else f" [{decision.reason}]"

    # -- Jahrgangsgenaue Bewertung ----------------------------------------
    if c.has_vintage_rating and c.year is not None and c.year == retailer_vintage:
        return VivinoResult(
            status=VivinoStatus.EXACT,
            query=query,
            url=c.url,
            note=f"Jahrgang {c.year} mit {c.vintage_count} Bewertungen{suffix}",
            rating=c.vintage_avg,
            rating_count=c.vintage_count,
            matched_name=c.name,
            match_confidence=decision.confidence.value,
        )

    # -- Weinseite hat Bewertung, Jahrgang weicht ab -----------------------
    if c.wine_avg is not None and c.wine_count >= MIN_RATINGS:
        jahrgang = (
            f"Jahrgang {retailer_vintage} nicht separat bewertet"
            if retailer_vintage
            else "kein Jahrgang beim Händler angegeben"
        )
        return VivinoResult(
            status=VivinoStatus.WINE_LEVEL,
            query=query,
            url=c.url,
            note=f"Weinschnitt über alle Jahrgänge, {c.wine_count} Bewertungen — {jahrgang}{suffix}",
            rating=c.wine_avg,
            rating_count=c.wine_count,
            matched_name=c.wine_name or c.name,
            match_confidence=decision.confidence.value,
        )

    # -- Seite existiert, aber zu wenige Bewertungen -----------------------
    count = max(c.vintage_count, c.wine_count)
    return VivinoResult(
        status=VivinoStatus.TOO_FEW_RATINGS,
        query=query,
        url=c.url,
        note=(
            f"nur {count} Bewertungen — Vivino zeigt keine Note{suffix}"
            if count
            else f"Seite existiert, noch keine Bewertungen{suffix}"
        ),
        rating_count=count or None,
        matched_name=c.name,
        match_confidence=decision.confidence.value,
    )


class VivinoAdapter:
    """Fragt Vivino für jeden Wein ab und liefert nie ein leeres Ergebnis."""

    source = "vivino"
    scale_max = 5.0

    def __init__(self, fetcher: Fetcher, *, cache=None, min_ratings: int = MIN_RATINGS):
        self.fetcher = fetcher
        self.cache = cache
        self.min_ratings = min_ratings

    # -- Netz --------------------------------------------------------------
    def _search(self, query: str) -> list[_Cand]:
        params: list[tuple[str, object]] = [
            ("search_term", query),
            ("country_code", "CH"),
            ("language", "de"),
            ("per_page", "12"),
            ("min_rating", "1"),
        ]
        params += [("wine_type_ids[]", t) for t in WINE_TYPE_IDS]
        res = self.fetcher.get(API_URL, params=params, expect_json=True)
        if not res.ok:
            raise Blocked(f"Vivino API HTTP {res.status_code}", kind="http")
        try:
            payload = json.loads(res.text)
        except json.JSONDecodeError as exc:
            raise Blocked(f"Vivino API lieferte kein JSON: {exc}", kind="parse") from exc
        return _parse_candidates(payload)

    # -- Öffentliche API ---------------------------------------------------
    def lookup(
        self,
        name: str,
        vintage: int | None = None,
        *,
        refresh: bool = False,
        retry_failed: bool = False,
    ) -> VivinoResult:
        """Immer ein Ergebnis mit Status, Query und klickbarer URL."""
        query = build_query(name, vintage)

        if self.cache is not None:
            cached = self.cache.get_rating(
                self.source, name, vintage, refresh=refresh, retry_failed=retry_failed
            )
            if cached:
                return _from_payload(cached)

        try:
            candidates = self._search(query)
            result = classify(name, vintage, query, candidates)
            # Recall-Versuch, wenn die lange Query nichts fand. Gekürzt wird auf die
            # *unterscheidenden* Tokens, nicht positionell: "passio nero avola" wäre
            # zu 2/3 Rebsortenname und liefert ein Feld fremder Weine, das dann als
            # 'ambiguous' erscheint, obwohl gar nichts Passendes dabei ist.
            if result.status is VivinoStatus.NO_ENTRY:
                short = " ".join(distinctive_tokens(name)[:4])
                if short and short != query:
                    alt = classify(name, vintage, short, self._search(short))
                    if alt.status is not VivinoStatus.NO_ENTRY:
                        result = alt
        except Blocked as exc:
            result = VivinoResult.miss(
                VivinoStatus.BLOCKED,
                query,
                f"Vivino nicht erreichbar ({exc}) — erneut ab {exc.retry_after or 'später'}",
                retry_after=exc.retry_after,
            )

        result.checked_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        if self.cache is not None:
            self.cache.put_rating(
                self.source,
                name,
                vintage,
                _to_payload(result),
                status=result.status.value,
                retry_after=result.retry_after,
            )
        return result


def _to_payload(r: VivinoResult) -> dict[str, Any]:
    return {
        "status": r.status.value,
        "query": r.query,
        "url": r.url,
        "note": r.note,
        "rating": r.rating,
        "rating_count": r.rating_count,
        "matched_name": r.matched_name,
        "retry_after": r.retry_after,
        "checked_at": r.checked_at,
        "match_confidence": r.match_confidence,
        "candidates": [
            {
                "name": c.name,
                "url": c.url,
                "rating": c.rating,
                "rating_count": c.rating_count,
                "vintage": c.vintage,
                "score": c.score,
            }
            for c in r.candidates
        ],
    }


def _from_payload(d: dict[str, Any]) -> VivinoResult:
    return VivinoResult(
        status=VivinoStatus(d.get("status") or "no_entry"),
        query=d.get("query") or "",
        url=d.get("url") or "",
        note=d.get("note") or "",
        rating=d.get("rating"),
        rating_count=d.get("rating_count"),
        matched_name=d.get("matched_name"),
        retry_after=d.get("retry_after"),
        checked_at=d.get("checked_at"),
        match_confidence=d.get("match_confidence") or "",
        candidates=[
            VivinoCandidate(
                name=c.get("name") or "",
                url=c.get("url") or "",
                rating=c.get("rating"),
                rating_count=c.get("rating_count"),
                vintage=c.get("vintage"),
                score=c.get("score") or 0.0,
            )
            for c in d.get("candidates") or []
        ],
    )

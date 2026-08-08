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
import re
import time
import urllib.parse
from dataclasses import dataclass, field
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
from ..names import GRAPE_NAMES, VIVINO_TYPE_IDS, query_tokens, strip_accents, wine_style, distinctive_tokens, tokenize

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
class _Price:
    """Ein Händlerpreis aus der Vivino-Antwort, auf 75 cl normalisiert."""

    per_75cl: float
    raw: float
    basis: str
    url: str
    shop: str


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
    type_id: int | None = None
    prices: list[_Price] = field(default_factory=list)

    @property
    def has_vintage_rating(self) -> bool:
        return self.vintage_count >= MIN_RATINGS and self.vintage_avg is not None

    def market_price(self, exclude_hosts: set[str]) -> tuple[_Price | None, str]:
        """Günstigster Preis, der **nicht** vom Vergleichshändler selbst stammt.

        Ohne diese Filterung wäre der Vergleich zirkulär: Mövenpick ist
        Vivino-Partnerhändler (``merchant_id`` 450), und für Mövenpick-Weine nennt
        Vivino genau den Mövenpick-Preis. Château Plince CHF 65 gegen CHF 65 wären
        dann 0 % Ersparnis — und alle Weine anderer Händler sähen dadurch besser aus.
        """
        if not self.prices:
            return None, "Vivino nennt keinen Händlerpreis für die Schweiz"
        usable = [p for p in self.prices if not _host_matches(p.url, exclude_hosts)]
        if not usable:
            shops = ", ".join(sorted({p.shop for p in self.prices if p.shop})) or "demselben Shop"
            return None, (
                f"einziger Vivino-Preis stammt von {shops} — derselbe Händler, "
                f"kein unabhängiger Vergleich möglich"
            )
        # Schweizer Shops zuerst: verglichen wird mit dem *Schweizer* Detailhandel.
        # Ausländische Sammler- und Anlageplattformen (cultwinesintl.com,
        # wineuponatime.com) führen Preise, die ein Vielfaches des Ladenpreises
        # betragen — als Marktpreis genommen ergäbe das ein Fantasie-Schnäppchen.
        swiss = [p for p in usable if p.shop.endswith(".ch")]
        pool = swiss or usable
        best = min(pool, key=lambda p: p.per_75cl)

        note = f"Marktpreis von {best.shop or 'Vivino-Händler'}"
        skipped = len(self.prices) - len(usable)
        if skipped:
            note += f", {skipped} Preis(e) des eigenen Händlers übersprungen"
        if not swiss:
            note += " — kein Schweizer Shop, Vergleich mit Vorsicht"
        return best, note


#: Wie viele Kandidaten je Abfrage geholt werden.
#:
#: Vivino sortiert die Trefferliste nach **Bewertung**, nicht nach Namensähnlichkeit.
#: Der gesuchte Wein steht darum oft nicht vorne, sondern hinter den berühmten Weinen
#: derselben Herkunft. Beispiel aus dem Livebetrieb: „Chivite Navarra Colección 125"
#: (rot) stand hinter dem Blanco und der Vendimia Tardía desselben Hauses — mit zwölf
#: Kandidaten fiel er unter den Tisch, mit mehr nicht.
PER_PAGE = 24


def build_query(name: str, vintage: int | None = None) -> str:
    """Suchbegriff aus der Händler-Bezeichnung.

    Volumen, Gebinde, rechtliche Bezeichnungen und Marketing fliegen raus; der
    Jahrgang bleibt weg, weil die API sonst schlechter greift. Der zurückgegebene
    String landet unverändert in ``vivino_query`` und in der Suchurl — damit sofort
    sichtbar ist, ob ein Nicht-Treffer an der Query oder am Wein lag.

    Diese lange Fassung behält Herkunft und Land und ist damit die **zweite** Wahl:
    siehe :meth:`Vivino.lookup`, wo zuerst mit den unterscheidenden Tokens gesucht wird.
    """
    tokens = tokenize(name)
    return " ".join(tokens[:10]) or (name or "").strip()


def _display_name(c: _Cand) -> str:
    """Fundname so, dass ein Mensch ihn wiedererkennt.

    Vivino trennt Weingut und Wein: „Cune Imperial Rioja Reserva" heisst dort Weingut
    „Imperial", Wein „Rioja Reserva". Gaben wir nur den Weinnamen aus, stand in der
    Spalte „Rioja Reserva" — eine Gattungsbezeichnung, die wie ein Fehltreffer
    aussieht, obwohl der Treffer stimmte. Wer das prüft, verwirft einen richtigen
    Match; ich bin selbst darauf hereingefallen.
    """
    wein = (c.wine_name or c.name or "").strip()
    haus = (c.winery or "").strip()
    if haus and haus.lower() not in wein.lower():
        return f"{haus} {wein}".strip()
    return wein


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
                type_id=_i(wine.get("type_id")) or None,
                prices=_parse_prices(match),
            )
        )
    return out


def _parse_prices(match: dict[str, Any]) -> list[_Price]:
    """Händlerpreise auf CHF pro 75 cl normalisieren.

    Nur CHF wird übernommen — umgerechnet wird nichts, ein Wechselkurs wäre eine
    weitere Fehlerquelle. ``bottle_quantity`` ist die Zahl der Flaschen im Angebot,
    ``bottle_type.volume_ml`` das Volumen je Flasche.
    """
    raw = match.get("prices")
    if not isinstance(raw, list) or not raw:
        single = match.get("price")
        raw = [single] if isinstance(single, dict) else []

    out: list[_Price] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        currency = ((entry.get("currency") or {}).get("code") or "").upper()
        amount = _f(entry.get("amount"))
        if currency != "CHF" or amount is None:
            continue
        bottles = _i(entry.get("bottle_quantity")) or 1
        volume = _i((entry.get("bottle_type") or {}).get("volume_ml")) or 750
        if bottles <= 0 or volume <= 0:
            continue
        per_75cl = round(amount / bottles * (750 / volume), 2)
        url = str(entry.get("url") or "")
        basis_parts = []
        if bottles > 1:
            basis_parts.append(f"{bottles} Flaschen")
        if volume != 750:
            basis_parts.append(f"{volume/10:g} cl")
        out.append(
            _Price(
                per_75cl=per_75cl,
                raw=amount,
                basis=", ".join(basis_parts) or "pro Flasche",
                url=url,
                shop=_shop_name(url),
            )
        )
    return out


def _shop_name(url: str) -> str:
    host = urllib.parse.urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _host_matches(url: str, hosts: set[str]) -> bool:
    """Gehört die Preis-URL zu einem der ausgeschlossenen Händler?"""
    host = _shop_name(url)
    if not host:
        return False
    return any(host == h or host.endswith("." + h) or h.endswith("." + host) for h in hosts if h)


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


#: Rebsorte hinter einem Artikel — „Il Grigio", „La Rosa", „Le Merle". Dann ist sie
#: Bestandteil eines Eigennamens, nicht die Sorte des Weins.
_RE_EIGENNAME_SORTE = re.compile(
    r"\b(?:il|lo|la|le|los|las|les|el|der|die|das)\s+("
    + "|".join(sorted(GRAPE_NAMES, key=len, reverse=True))
    + r")\b"
)


#: Farben, die einander ausschliessen. Schaum- und Süsswein bleiben draussen: ein
#: „Prosecco" kann als Schaumwein *und* weiss geführt sein, das ist kein Widerspruch.
_FARBEN = {"rot", "weiss", "rose"}


def _farbkonflikt(retailer_name: str, type_id: int | None) -> bool:
    """Widerspricht Vivinos Weintyp der Farbe, die der Händlername nennt?

    Die verlässlichste Farbprüfung, die zu haben ist: ``type_id`` kommt aus Vivinos
    Weindatenbank, nicht aus einer Namensanalyse. Der Händlername wiederum verrät die
    Farbe oft nur über die **Rebsorte** — und genau daran scheiterte die bisherige
    Prüfung, die Farbwörter gegen Farbwörter hielt: „Vermentino San Felice Toscana IGT"
    für CHF 11.50 bekam die 4.2 eines „San Felice Campogiovanni **Brunello di
    Montalcino**". Beide Namen tragen kein Farbwort, Vermentino ist aber eine weisse
    Sorte und Brunello ein Roter.
    """
    if type_id is None:
        return False
    quelle = VIVINO_TYPE_IDS.get(type_id)
    if quelle not in _FARBEN:
        return False
    # Steht die Rebsorte hinter einem Artikel, ist sie ein Eigenname und keine
    # Sortenangabe: „Chianti Classico Riserva **Il Grigio** da San Felice" ist ein
    # Roter, obwohl „Grigio" nach Pinot Grigio aussieht. Solche Namen sind als
    # Farbquelle unbrauchbar — dann lieber nicht sperren.
    if _RE_EIGENNAME_SORTE.search(strip_accents(retailer_name.lower())):
        return False
    haendler = wine_style(retailer_name, None)
    if haendler not in _FARBEN:
        return False
    return haendler != quelle


def classify(
    retailer_name: str,
    retailer_vintage: int | None,
    query: str,
    candidates: list[_Cand],
    *,
    exclude_hosts: set[str] | None = None,
) -> VivinoResult:
    """Ordnet API-Kandidaten einem :class:`VivinoStatus` zu.

    Reine Funktion ohne Netz — deshalb vollständig testbar. Liefert **immer** ein
    Ergebnis mit gesetzter URL: Weinseite falls gefunden, sonst die Suchurl.

    Args:
        exclude_hosts: Domains der Händler, mit denen verglichen wird. Preise von
            dort werden beim Marktpreis übersprungen, sonst ist der Vergleich
            zirkulär.
    """
    hosts = exclude_hosts or set()
    # Kandidaten mit widersprechender Farbe fliegen raus, bevor überhaupt verglichen
    # wird — ein Roter kann die Note eines Weissen nicht tragen, wie ähnlich der Name
    # auch sei.
    candidates = [c for c in candidates if not _farbkonflikt(retailer_name, c.type_id)]
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
    price, price_note = c.market_price(hosts)
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
            **_price_fields(price, price_note),
            wine_type_id=c.type_id,
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
            matched_name=_display_name(c),
            match_confidence=decision.confidence.value,
            **_price_fields(price, price_note),
            wine_type_id=c.type_id,
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
        **_price_fields(price, price_note),
    )


#: Das Trinkfenster steckt als JSON im HTML der Weinseite. Zweimal codiert: einmal
#: roh, einmal HTML-entitätenweise (``&quot;``). Gesucht wird die rohe Fassung; sie
#: ist auf jeder geprüften Seite vorhanden.
_RE_TRINKFENSTER = re.compile(
    r'drinking_window"\s*:\s*\{\s*"start_year"\s*:\s*(null|\d{4})\s*,'
    r'\s*"end_year"\s*:\s*(null|\d{4})'
)


def _jahr(rohwert: str) -> int | None:
    return None if rohwert == "null" else int(rohwert)


class VivinoAdapter:
    """Fragt Vivino für jeden Wein ab und liefert nie ein leeres Ergebnis."""

    source = "vivino"
    scale_max = 5.0

    def __init__(self, fetcher: Fetcher, *, cache=None, min_ratings: int = MIN_RATINGS):
        self.fetcher = fetcher
        self.cache = cache
        self.min_ratings = min_ratings

    # -- Netz --------------------------------------------------------------
    def _search(self, query: str, *, order_by: str | None = None) -> list[_Cand]:
        params: list[tuple[str, object]] = [
            ("search_term", query),
            ("country_code", "CH"),
            ("language", "de"),
            ("per_page", str(PER_PAGE)),
            ("min_rating", "1"),
        ]
        if order_by:
            params += [("order_by", order_by), ("order", "desc")]
        params += [("wine_type_ids[]", t) for t in WINE_TYPE_IDS]
        res = self.fetcher.get(API_URL, params=params, expect_json=True)
        if not res.ok:
            raise Blocked(f"Vivino API HTTP {res.status_code}", kind="http")
        try:
            payload = json.loads(res.text)
        except json.JSONDecodeError as exc:
            raise Blocked(f"Vivino API lieferte kein JSON: {exc}", kind="parse") from exc
        return _parse_candidates(payload)

    def _trinkfenster(self, url: str, vintage: int | None) -> tuple[int | None, int | None]:
        """Holt das Trinkfenster von der Weinseite.

        Der Jahrgangsparameter ist zwingend: ohne ihn liefert Vivino
        ``start_year: null, end_year: null``, und die Angabe sieht aus, als gäbe es
        sie nicht. Mit ihm steht sie da — und zwar je Jahrgang verschieden, was sie
        erst brauchbar macht (Château Lafleur 2011 → 2014–2026, 2020 → 2023–2035).

        Ein Fehlschlag ist kein Grund, die ganze Bewertung zu verlieren: dann bleibt
        das Fenster eben leer.
        """
        if not vintage or "/w/" not in url:
            return None, None
        trenner = "&" if "?" in url else "?"
        try:
            res = self.fetcher.get(f"{url.split('#')[0]}{trenner}year={vintage}")
        except Exception:
            return None, None
        if not res.ok:
            return None, None
        m = _RE_TRINKFENSTER.search(res.text)
        if not m:
            return None, None
        return _jahr(m.group(1)), _jahr(m.group(2))

    # -- Öffentliche API ---------------------------------------------------

    #: Rangfolge der Status für die Auswahl zwischen zwei Abfragen. Höher ist besser.
    #: ``winery_level`` steht bewusst unter ``ambiguous``: eine Liste von drei
    #: Kandidaten, aus der ein Mensch wählen kann, sagt mehr als ein
    #: Produzenten-Durchschnitt, der so tut, als wäre er die Note dieses Weins.
    _RANK = {
        VivinoStatus.EXACT: 6,
        VivinoStatus.WINE_LEVEL: 5,
        VivinoStatus.AMBIGUOUS: 4,
        VivinoStatus.WINERY_LEVEL: 3,
        VivinoStatus.TOO_FEW_RATINGS: 2,
        VivinoStatus.RATING_NOT_READABLE: 2,
        VivinoStatus.NO_ENTRY: 1,
    }

    def _best_of(self, name, vintage, long_query, exclude_hosts):
        """Mehrere Suchbegriffe probieren und das beste Ergebnis behalten.

        Die **kurze** Abfrage kommt zuerst, und das ist der ganze Punkt. Vivino
        sortiert nach Bewertung, nicht nach Namensähnlichkeit — eine Abfrage, die mit
        der Appellation beginnt, liefert darum die berühmtesten Weine der Herkunft
        statt den gesuchten. Gemessen an echten Fällen:

        ==========================================  =======  ==========================
        Abfrage                                     Treffer  erster Kandidat
        ==========================================  =======  ==========================
        ``ribera duero protos roble spanien``            13  Protos 27 Ribera del Duero
        ``protos roble``                                  2  **Protos Roble 2024**
        ``ribera duero protos crianza spanien``          45  Protos 27 Ribera del Duero
        ``protos crianza``                                3  **Protos Crianza 2020**
        ==========================================  =======  ==========================

        Vorher lief die kurze Abfrage nur bei ``no_entry``. Beide Protos-Weine
        bekamen aber einen *falschen, aber akzeptierten* Treffer auf „Protos 27 Ribera
        del Duero" (4.2 aus 43'583 Bewertungen) — und damit kam der bessere Versuch nie
        zum Zug. Ein Fehltreffer verhinderte den Treffer.

        Die kurze Abfrage ist nicht immer besser: „Rioja Reserva Las Flores" schrumpft
        auf ``flores`` und liefert 247 fremde Weine. Davor schützen die Sperren in
        :mod:`~winecheck.matching` — was sie ablehnen, wird ``no_entry``, und dann
        greift die lange Abfrage. Deshalb *beide* versuchen und das bessere nehmen,
        statt sich auf eine Strategie festzulegen.
        """
        short = " ".join(query_tokens(name)[:4])
        # Dritter Versuch, nach Bewertungs*anzahl* sortiert. Grund: die Standard-
        # sortierung nach Note begräbt bei grossen Häusern genau die Weine, die man
        # im Regal findet. „Faiveley" liefert 207 Treffer, angeführt von
        # Bâtard-Montrachet und Mazis-Chambertin Grand Cru — der schlichte
        # Gevrey-Chambertin steht weit hinten. Nach Bewertungsanzahl sortiert steht er
        # vorne, weil ihn viele Leute trinken und die Grand Crus fast niemand.
        queries: list[tuple[str, str | None]] = [(short, None), (long_query, None)]
        if short:
            queries.append((short, "ratings_count"))

        best = None
        gesehen: set[tuple[str, str | None]] = set()
        for q, order in queries:
            if not q or (q, order) in gesehen:
                continue
            gesehen.add((q, order))
            res = classify(name, vintage, q, self._search(q, order_by=order),
                           exclude_hosts=exclude_hosts)
            if best is None or self._RANK[res.status] > self._RANK[best.status]:
                best = res
            # Besser als ein Jahrgangstreffer wird es nicht — weitere Anfragen wären
            # nur Last für Vivino.
            if best.status is VivinoStatus.EXACT:
                break
        return best

    def lookup(
        self,
        name: str,
        vintage: int | None = None,
        *,
        refresh: bool = False,
        retry_failed: bool = False,
        exclude_hosts: set[str] | None = None,
    ) -> VivinoResult:
        """Immer ein Ergebnis mit Status, Query und klickbarer URL."""
        query = build_query(name, vintage)

        if self.cache is not None:
            cached = self.cache.get_rating(
                self.source, name, vintage, refresh=refresh, retry_failed=retry_failed
            )
            if cached:
                result = _from_payload(cached)
                # Nachziehen statt neu suchen. Ältere Cache-Einträge stammen aus der
                # Zeit vor dem Trinkfenster; sie sind deswegen nicht schlecht. Wer
                # hier den ganzen Eintrag verwürfe, suchte 1391 Weine neu — Stunden
                # Arbeit für eine Angabe, die eine einzige Anfrage kostet.
                #
                # Unterschieden wird an ``drink_checked``, nicht an den Jahreszahlen:
                # sonst wäre "geprüft, aber Vivino führt keines" nicht von "noch nie
                # geprüft" zu trennen, und der Abruf liefe jede Woche neu.
                if not cached.get("drink_checked") and result.rating is not None \
                        and "/w/" in result.url:
                    result.drink_from, result.drink_until = self._trinkfenster(
                        result.url, vintage
                    )
                    self.cache.put_rating(
                        self.source, name, vintage, _to_payload(result),
                        status=result.status.value, retry_after=result.retry_after,
                    )
                return result

        try:
            result = self._best_of(name, vintage, query, exclude_hosts)
        except Blocked as exc:
            result = VivinoResult.miss(
                VivinoStatus.BLOCKED,
                query,
                f"Vivino nicht erreichbar ({exc}) — erneut ab {exc.retry_after or 'später'}",
                retry_after=exc.retry_after,
            )

        # Nur bei einem echten Weinfund: eine Suchurl hat keine Weinseite, und ein
        # Produzenten-Mittelwert hat kein Trinkfenster.
        if result.rating is not None and "/w/" in result.url:
            result.drink_from, result.drink_until = self._trinkfenster(result.url, vintage)

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


def _price_fields(price: _Price | None, note: str) -> dict[str, Any]:
    """Marktpreis-Felder für :class:`VivinoResult`."""
    if price is None:
        return {"market_price_note": note}
    return {
        "market_price": price.per_75cl,
        "market_price_raw": price.raw,
        "market_price_basis": price.basis,
        "market_price_url": price.url,
        "market_price_shop": price.shop,
        "market_price_note": note,
    }


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
        "market_price": r.market_price,
        "market_price_raw": r.market_price_raw,
        "market_price_basis": r.market_price_basis,
        "market_price_url": r.market_price_url,
        "market_price_shop": r.market_price_shop,
        "market_price_note": r.market_price_note,
        "wine_type_id": r.wine_type_id,
        "drink_from": r.drink_from,
        "drink_until": r.drink_until,
        # Merker, dass nachgeschaut wurde. Ohne ihn liefe der Abruf bei jedem Wein
        # ohne Trinkfenster jede Woche erneut.
        "drink_checked": True,
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
        market_price=d.get("market_price"),
        market_price_raw=d.get("market_price_raw"),
        market_price_basis=d.get("market_price_basis") or "",
        market_price_url=d.get("market_price_url") or "",
        market_price_shop=d.get("market_price_shop") or "",
        market_price_note=d.get("market_price_note") or "",
        wine_type_id=d.get("wine_type_id"),
        drink_from=d.get("drink_from"),
        drink_until=d.get("drink_until"),
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

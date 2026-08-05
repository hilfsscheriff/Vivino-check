"""Datenmodell.

Zwei Grundsätze, die sich durch alle Felder ziehen:

1. Eine Bewertung wird nie geraten. Kein Treffer heisst ``rating is None`` plus Status
   plus Klartext-Notiz.
2. Die Vivino-Felder sind nie leer. Auch ein Nicht-Treffer liefert Status, Query und
   eine klickbare URL (Weinseite falls gefunden, sonst die Vivino-Suche mit der Query).
"""

from __future__ import annotations

import enum
import urllib.parse
from dataclasses import dataclass, field, asdict
from typing import Any


# --------------------------------------------------------------------------- Vivino

class VivinoStatus(str, enum.Enum):
    """Warum die Vivino-Spalte so aussieht, wie sie aussieht.

    Reihenfolge = absteigende Aussagekraft. ``rank()`` nutzt das für die Auswahl des
    besten Kandidaten; die Report-Legende zieht die Texte aus ``LABELS``.
    """

    EXACT = "exact"                          # Bewertung für den exakten Jahrgang
    WINE_LEVEL = "wine_level"                # Weinseite hat Bewertung, Jahrgang weicht ab
    WINERY_LEVEL = "winery_level"            # nur Produzenten-Durchschnitt, schwach
    TOO_FEW_RATINGS = "too_few_ratings"      # Seite existiert, "not enough ratings"
    RATING_NOT_READABLE = "rating_not_readable"  # Seite existiert, Note per JS, nicht extrahierbar
    AMBIGUOUS = "ambiguous"                  # mehrere Kandidaten über der Schwelle
    NO_ENTRY = "no_entry"                    # kein passender Eintrag -> Suchurl
    BLOCKED = "blocked"                      # Cloudflare / Rate-Limit, Retry vermerkt

    def rank(self) -> int:
        return _VIVINO_RANK[self]


_VIVINO_RANK = {
    VivinoStatus.EXACT: 0,
    VivinoStatus.WINE_LEVEL: 1,
    VivinoStatus.WINERY_LEVEL: 2,
    VivinoStatus.TOO_FEW_RATINGS: 3,
    VivinoStatus.RATING_NOT_READABLE: 4,
    VivinoStatus.AMBIGUOUS: 5,
    VivinoStatus.NO_ENTRY: 6,
    VivinoStatus.BLOCKED: 7,
}

#: Kurztexte für die Vivino-Spalte im PDF. Kein leeres Feld, kein Gedankenstrich.
VIVINO_LABELS: dict[VivinoStatus, str] = {
    VivinoStatus.EXACT: "Jahrgang bewertet",
    VivinoStatus.WINE_LEVEL: "Wein bewertet, and. Jahrgang",
    VivinoStatus.WINERY_LEVEL: "nur Produzenten-Ø",
    VivinoStatus.TOO_FEW_RATINGS: "zu wenige Bewertungen",
    VivinoStatus.RATING_NOT_READABLE: "Note nicht lesbar — Seite öffnen",
    VivinoStatus.AMBIGUOUS: "mehrere Kandidaten",
    VivinoStatus.NO_ENTRY: "kein Eintrag — Suche öffnen",
    VivinoStatus.BLOCKED: "blockiert — später erneut",
}

VIVINO_SEARCH_BASE = "https://www.vivino.com/de/explore?search_term="


def vivino_search_url(query: str) -> str:
    """Die Suchurl, die auch bei ``no_entry`` ausgegeben wird — damit selbst klickbar ist,
    ob die Query schlecht war oder der Wein wirklich fehlt."""
    return VIVINO_SEARCH_BASE + urllib.parse.quote_plus(query or "")


@dataclass
class VivinoCandidate:
    """Ein Kandidat. Bei ``ambiguous`` werden bis zu drei davon ausgegeben statt geraten."""

    name: str
    url: str
    rating: float | None = None
    rating_count: int | None = None
    vintage: int | None = None
    score: float = 0.0


@dataclass
class VivinoResult:
    """Pflichtspalte. Wird für jeden Wein gesetzt, unabhängig von Falstaff."""

    status: VivinoStatus
    query: str
    url: str
    note: str
    rating: float | None = None
    rating_count: int | None = None
    matched_name: str | None = None
    candidates: list[VivinoCandidate] = field(default_factory=list)
    retry_after: str | None = None          # nur bei BLOCKED
    checked_at: str | None = None
    #: Sicherheit der *Namens*-Zuordnung — orthogonal zum Status, der die
    #: Jahrgangsgenauigkeit der Bewertung beschreibt. Ein ``exact``-Status auf einem
    #: ``fuzzy``-Namensmatch heisst: Jahrgang stimmt, Wein bitte prüfen.
    match_confidence: str = ""

    def __post_init__(self) -> None:
        # Harte Zusicherung: die URL ist niemals leer. Ohne Weinseite die Suche.
        if not self.url:
            self.url = vivino_search_url(self.query)
        if not self.note:
            self.note = VIVINO_LABELS.get(self.status, self.status.value)

    @property
    def has_rating(self) -> bool:
        return self.rating is not None

    @classmethod
    def miss(
        cls,
        status: VivinoStatus,
        query: str,
        note: str,
        *,
        url: str | None = None,
        retry_after: str | None = None,
    ) -> VivinoResult:
        """Nicht-Treffer bauen, ohne die URL-Regel jedes Mal neu zu buchstabieren."""
        return cls(
            status=status,
            query=query,
            url=url or vivino_search_url(query),
            note=note,
            retry_after=retry_after,
        )


# --------------------------------------------------------------------------- Matching

class MatchConfidence(str, enum.Enum):
    EXACT = "exact"              # Name + Jahrgang sicher
    WINE_LEVEL = "wine_level"    # Wein sicher, Jahrgang abweichend
    FUZZY = "fuzzy"              # ähnlich genug; Quell-Bezeichnung wird mitgegeben
    WINERY_LEVEL = "winery_level"
    NONE = "none"                # unter der Schwelle -> gar nicht matchen


@dataclass
class MatchDecision:
    """Ergebnis der Namens-Prüfung. ``reason`` ist bewusst menschenlesbar — bei einem
    abgelehnten Match will man wissen, *warum* (z.B. "Classico nur in einem Namen")."""

    matched: bool
    confidence: MatchConfidence
    score: float
    reason: str
    source_name: str | None = None
    vintage_match: bool | None = None

    @property
    def needs_source_name(self) -> bool:
        """Ab ``fuzzy`` immer die gefundene Quell-Bezeichnung mit ausgeben."""
        return self.confidence in (MatchConfidence.FUZZY, MatchConfidence.WINERY_LEVEL)


# --------------------------------------------------------------------------- Preise

class PriceConfidence(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"      # Gebindegrösse unsicher -> NICHT ins Ranking


class DiscountPlausibility(str, enum.Enum):
    OK = "ok"
    QUESTIONABLE = "questionable"   # >45% auf Eigenmarke
    UNKNOWN = "unknown"


@dataclass
class NormalizedPrice:
    """Führt Rohwert und normalisierten Wert parallel — im Report steht der
    normalisierte Preis, der Rohwert als Klammerzusatz, damit man am Regal vergleichen
    kann."""

    price_per_bottle_incl_vat: float | None
    price_raw: float | None
    price_raw_basis: str
    confidence: PriceConfidence
    bottle_ml: int | None = None
    units: int | None = None
    vat_added: bool = False
    note: str = ""

    @property
    def usable_for_ranking(self) -> bool:
        """Ein falsch umgerechneter Literpreis erzeugt einen Scheinsieger — das ist
        schlimmer als eine Lücke."""
        return self.price_per_bottle_incl_vat is not None and self.confidence is not PriceConfidence.LOW


# --------------------------------------------------------------------------- Angebote

@dataclass
class Offer:
    """Ein Aktionsangebot bei genau einem Händler."""

    retailer: str
    name: str
    url: str = ""
    vintage: int | None = None
    producer: str | None = None
    region: str | None = None
    country: str | None = None
    price_per_bottle_incl_vat: float | None = None
    price_raw: float | None = None
    price_raw_basis: str = ""
    price_confidence: PriceConfidence = PriceConfidence.HIGH
    reference_price: float | None = None
    discount_percent: float | None = None
    discount_plausibility: DiscountPlausibility = DiscountPlausibility.UNKNOWN
    is_private_label: bool = False
    bottle_ml: int | None = None
    units: int | None = None
    article_no: str | None = None
    fetched_at: str | None = None
    source_note: str = ""

    def apply_price(self, p: NormalizedPrice) -> None:
        self.price_per_bottle_incl_vat = p.price_per_bottle_incl_vat
        self.price_raw = p.price_raw
        self.price_raw_basis = p.price_raw_basis
        self.price_confidence = p.confidence
        self.bottle_ml = p.bottle_ml
        self.units = p.units
        if p.note:
            self.source_note = (self.source_note + " " + p.note).strip()


@dataclass
class RetailerPrice:
    """Derselbe Wein bei einem weiteren Händler — Kernfeature des Vergleichs."""

    retailer: str
    price_per_bottle_incl_vat: float | None
    price_raw: float | None
    price_raw_basis: str
    url: str
    price_confidence: PriceConfidence
    discount_percent: float | None = None
    discount_plausibility: DiscountPlausibility = DiscountPlausibility.UNKNOWN


@dataclass
class Rating:
    """Eine externe Bewertung. ``value is None`` ist ein legitimes, informatives Ergebnis."""

    source: str
    value: float | None
    scale_max: float
    count: int | None = None
    confidence: MatchConfidence = MatchConfidence.NONE
    source_name: str | None = None
    url: str = ""
    note: str = ""
    status: str = ""

    @property
    def normalized(self) -> float | None:
        """Auf 0..1, damit Skalen vergleichbar werden. Die Herkunft wird im Report
        immer angezeigt — nie zwei Skalen im selben Sortierschlüssel ohne Quellenangabe."""
        if self.value is None:
            return None
        return round(self.value / self.scale_max, 4)


@dataclass
class WineRow:
    """Eine Zeile im Output: ein Wein, ggf. mehrere Händlerpreise, Bewertungen, Score."""

    name: str
    vintage: int | None
    dedup_key: str
    offers: list[Offer] = field(default_factory=list)
    prices: list[RetailerPrice] = field(default_factory=list)
    falstaff: Rating | None = None
    vivino: VivinoResult | None = None
    winesearcher: Rating | None = None
    value_score: float | None = None
    price_band: str = ""
    rank_source: str = ""            # welche Skala den Sortierschlüssel gestellt hat
    is_private_label: bool = False

    # -- Preis -------------------------------------------------------------
    @property
    def best_price(self) -> float | None:
        vals = [p.price_per_bottle_incl_vat for p in self.prices
                if p.price_per_bottle_incl_vat is not None
                and p.price_confidence is not PriceConfidence.LOW]
        return min(vals) if vals else None

    @property
    def cheapest_retailer(self) -> str:
        best = self.best_price
        if best is None:
            return ""
        for p in self.prices:
            if p.price_per_bottle_incl_vat == best:
                return p.retailer
        return ""

    @property
    def retailer_count(self) -> int:
        return len({p.retailer for p in self.prices})

    # -- Bewertung ---------------------------------------------------------
    @property
    def has_any_rating(self) -> bool:
        if self.falstaff and self.falstaff.value is not None:
            return True
        if self.vivino and self.vivino.has_rating:
            return True
        if self.winesearcher and self.winesearcher.value is not None:
            return True
        return False

    def ranking_rating(self) -> tuple[float | None, str]:
        """Ranking läuft über Falstaff, wo vorhanden, mit Vivino als Zweitwert.
        Gibt (normalisierter Wert, Quellenname) zurück — die Quelle wird immer
        mitgeführt, damit im Report nie unklar ist, welche Skala gewonnen hat."""
        if self.falstaff and self.falstaff.value is not None:
            return self.falstaff.normalized, "Falstaff"
        if self.vivino and self.vivino.rating is not None:
            return round(self.vivino.rating / 5.0, 4), "Vivino"
        if self.winesearcher and self.winesearcher.value is not None:
            return self.winesearcher.normalized, "Wine-Searcher"
        return None, ""

    def no_rating_reason(self) -> str:
        """Begründung für die Tabelle 'ohne Bewertung'."""
        bits = []
        if self.falstaff and self.falstaff.note:
            bits.append(f"Falstaff: {self.falstaff.note}")
        elif not self.falstaff:
            bits.append("Falstaff: nicht abgefragt")
        if self.vivino:
            bits.append(f"Vivino: {self.vivino.note}")
        return " · ".join(bits) or "keine Fremdbewertung verfügbar"

    def to_flat(self) -> dict[str, Any]:
        """Flache Zeile für results.csv — alle Felder roh, inkl. aller Vivino-Felder."""
        v = self.vivino
        rating_norm, rank_src = self.ranking_rating()
        row: dict[str, Any] = {
            "name": self.name,
            "vintage": self.vintage or "",
            "dedup_key": self.dedup_key,
            "is_private_label": self.is_private_label,
            "price_per_bottle_incl_vat": _fmt_num(self.best_price),
            "cheapest_retailer": self.cheapest_retailer,
            "retailer_count": self.retailer_count,
            "price_band": self.price_band,
            "value_score": _fmt_num(self.value_score),
            "rank_rating_normalized": _fmt_num(rating_norm),
            "rank_source": rank_src or self.rank_source,
            "falstaff_points": _fmt_num(self.falstaff.value) if self.falstaff else "",
            "falstaff_confidence": self.falstaff.confidence.value if self.falstaff else "",
            "falstaff_source_name": (self.falstaff.source_name or "") if self.falstaff else "",
            "falstaff_url": self.falstaff.url if self.falstaff else "",
            "falstaff_note": self.falstaff.note if self.falstaff else "",
            # -- Pflichtspalte, nie leer ------------------------------------
            "vivino_status": v.status.value if v else VivinoStatus.NO_ENTRY.value,
            "vivino_rating": _fmt_num(v.rating) if v else "",
            "vivino_rating_count": (v.rating_count if v and v.rating_count is not None else ""),
            "vivino_matched_name": (v.matched_name or "") if v else "",
            "vivino_url": v.url if v else vivino_search_url(self.name),
            "vivino_query": v.query if v else self.name,
            "vivino_note": v.note if v else "nicht abgefragt",
            "vivino_match_confidence": (v.match_confidence or "") if v else "",
            "vivino_candidates": " | ".join(f"{c.name} <{c.url}>" for c in v.candidates) if v else "",
            "vivino_retry_after": (v.retry_after or "") if v else "",
            "winesearcher_value": _fmt_num(self.winesearcher.value) if self.winesearcher else "",
            "winesearcher_note": self.winesearcher.note if self.winesearcher else "",
        }
        # Preisvergleich über Händler: je Händler eine Spalte.
        for p in sorted(self.prices, key=lambda x: x.retailer):
            row[f"price_{p.retailer}"] = _fmt_num(p.price_per_bottle_incl_vat)
            row[f"price_raw_{p.retailer}"] = (
                f"{_fmt_num(p.price_raw)} ({p.price_raw_basis})" if p.price_raw is not None else ""
            )
            row[f"discount_{p.retailer}"] = _fmt_num(p.discount_percent)
            row[f"discount_plausibility_{p.retailer}"] = p.discount_plausibility.value
            row[f"url_{p.retailer}"] = p.url
        return row


def _fmt_num(v: float | None) -> str:
    if v is None:
        return ""
    return f"{v:.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def as_dict(obj: Any) -> dict[str, Any]:
    return asdict(obj)

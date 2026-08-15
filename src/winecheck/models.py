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

    # -- Marktpreis --------------------------------------------------------
    #: Vivino nennt im selben Aufruf Händlerpreise für die Schweiz. Auf CHF pro
    #: 75 cl normalisiert ist das ein *unabhängiger* Referenzpreis — deutlich
    #: belastbarer als das "statt X" des Händlers, das bei Eigenmarken teils
    #: konstruiert ist.
    market_price: float | None = None
    market_price_raw: float | None = None
    market_price_basis: str = ""
    market_price_url: str = ""
    market_price_shop: str = ""
    #: Warum kein Marktpreis vorliegt — z.B. weil der einzige Preis vom selben
    #: Händler stammt, mit dem verglichen werden soll.
    market_price_note: str = ""
    #: Vivinos ``wine.type_id`` — verlässlicher als jede Namensanalyse für die Sorte.
    wine_type_id: int | None = None

    # -- Machart und Herkunft ---------------------------------------------
    #: ``wine.style.name``, etwa „Bolgheri Italien". Vivinos eigene Stil-Schublade.
    style_name: str = ""
    #: ``wine.region.country.name``. Nur 585 von 1564 Weinen tragen ein Land aus dem
    #: Händlernamen; Vivino nennt es in derselben Antwort mit, in der auch die Note
    #: steht — derselbe Weg wie bei der Farbe über ``wine_type_id``.
    country: str = ""
    #: ``wine.region.name``. Bei den meisten Weinen die Appellation, bei den untersten
    #: Herkunftsstufen aber die **Denomination** selbst: „Vino d'Italia", „Vin de
    #: France". Genau das trägt Stufe 1d des Stil-Typs — siehe
    #: :func:`winecheck.stiltyp.einordnen`.
    region_name: str = ""
    #: ``wine.taste.structure`` — Süsse, Tannin, Säure und Intensität auf einer Skala
    #: von 1 bis 5, dazu ``user_structure_count``. Das ist eine Messung **an diesem
    #: Wein**, nicht an seiner Gattung, und trägt darum den Stil-Typ.
    taste: dict[str, float] = field(default_factory=dict)
    #: ``wine.style.baseline_structure`` — dieselben Achsen als Normalwert des Stils.
    #: Rückfall, wenn dieser Wein zu wenige Nutzerurteile hat.
    style_baseline: dict[str, float] = field(default_factory=dict)

    # -- Trinkfenster ------------------------------------------------------
    #: Vivino nennt auf der Weinseite ein Trinkfenster, aber **nur mit
    #: Jahrgangsparameter** (``/w/1099307?year=2011`` → 2014–2026). Ohne ihn sind
    #: die Felder leer; daran ist die Angabe bei einer früheren Prüfung durchgerutscht.
    #:
    #: Anders als die Vinum-Tabelle gilt sie je Wein und Jahrgang statt je Region
    #: und Farbe. Sie ersetzt Vinum nicht, sondern steht daneben: Vinum ist
    #: redaktionell geprüft, Vivino ist feiner, und wo sie sich widersprechen, soll
    #: man das sehen.
    drink_from: int | None = None
    drink_until: int | None = None

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

#: Anzeigenamen der Kritiker und die Reihenfolge, in der sie das Ranking treiben
#: dürfen, wenn Falstaff fehlt. Alle auf der 100-Punkte-Skala.
CRITIC_LABELS: dict[str, str] = {
    "falstaff": "Falstaff",
    "parker": "Parker",
    "suckling": "James Suckling",
    "galloni": "Vinous/Galloni",
    "decanter": "Decanter",
    "spectator": "Wine Spectator",
    "vinum": "Vinum",
    "dunnuck": "Jeb Dunnuck",
    "atkin": "Tim Atkin",
    "penin": "Guía Peñín",
    "gambero": "Gambero Rosso",
    "bibenda": "Bibenda",
    "veronelli": "Veronelli",
    "gaultmillau": "Gault&Millau",
}

#: Vorrang, wenn mehrere Kritiker eine Note haben. Falstaff steht nicht drin — der
#: läuft über ``WineRow.falstaff`` und hat ohnehin Vorrang.
CRITIC_PRIORITY = (
    "parker", "suckling", "galloni", "decanter", "spectator", "vinum",
    "dunnuck", "atkin", "penin", "gambero", "bibenda", "veronelli",
)


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
    #: Anteil der unterscheidenden Wörter des Händlernamens, die im Kandidaten
    #: vorkommen. Wurde immer schon berechnet, blieb aber in der Prüfung liegen —
    #: und damit fehlte der Auswahl ihr wichtigstes Merkmal. Siehe
    #: :func:`winecheck.matching.rank_candidates`.
    coverage: float = 0.0

    @property
    def needs_source_name(self) -> bool:
        """Ab ``fuzzy`` immer die gefundene Quell-Bezeichnung mit ausgeben."""
        return self.confidence in (MatchConfidence.FUZZY, MatchConfidence.WINERY_LEVEL)


# --------------------------------------------------------------------------- Preise

class PriceConfidence(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"      # Gebindegrösse unsicher -> NICHT ins Ranking


#: Ersparnis über dieser Schwelle gegen den Vivino-Marktpreis gilt als fragwürdig.
#: Höher als die 45 % bei Eigenmarken-Rabatten, weil eine echte 50%-Aktion gegen
#: einen fremden Marktpreis durchaus 60 % ergeben kann — jenseits davon steckt aber
#: meist ein einzelner Preiseintrag eines Sammler- oder Anlageshops dahinter.
#: Steht hier und nicht in prices.py, weil prices.py dieses Modul importiert.
QUESTIONABLE_BARGAIN = 65.0


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
    #: Kritikerpunkte, die der *Händler* selbst ausweist ("Falstaff 92/100").
    #: Der Ersatz für den blockierten Falstaff-Zugang — die Note hängt am exakten
    #: Produkt, ist aber vom Händler berichtet und nicht bei der Quelle verifiziert.
    critic_scores: dict[str, float] = field(default_factory=dict)

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
    #: Wie viele Flaschen man abnehmen muss. ``None`` oder 1 heisst Einzelflasche.
    #:
    #: Der Preis je Flasche ist bei einer Kiste richtig gerechnet und vergleichbar — was
    #: fehlte, war die Verpflichtung. Gemeldet am Pio Cesare Barolo 2016: CHF 45.47 stand
    #: da, kaufen kann man ihn nur als Sechserkiste zu CHF 272.82. Wer den Einzelpreis
    #: sucht, findet ihn nicht und hält die Zeile für falsch.
    units: int | None = None

    @property
    def gesamtpreis(self) -> float | None:
        """Was tatsächlich zu zahlen ist. Bei der Einzelflasche derselbe Betrag."""
        if self.price_per_bottle_incl_vat is None:
            return None
        return self.price_per_bottle_incl_vat * (self.units or 1)


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
    #: Trinkreife aus der Vinum-Jahrgangstabelle, sofern Region und Jahrgang
    #: eindeutig zuzuordnen waren. Typ ist ``winecheck.trinkreife.Match``; als
    #: ``Any`` gehalten, damit models.py nicht von trinkreife.py abhängt.
    maturity: Any | None = None
    #: Weitere Kritikernoten, die Händler ausweisen: ``{"suckling": (94.0, "moevenpick")}``.
    #: Nur informativ — sie treiben das Ranking nicht, Leitquelle bleibt Falstaff.
    critics: dict[str, tuple[float, str]] = field(default_factory=dict)
    winesearcher: Rating | None = None
    #: Die alte Kennzahl: Rangposition innerhalb der Preisklasse, 0 bis 100. Sie steht
    #: weiterhin in der CSV, treibt aber seit dem 12.8.2026 **keinen** Sortierschlüssel
    #: mehr — global sortiert besetzte sie die ersten 25 Plätze mit 19 Weinen über CHF 80
    #: und liess die Klasse unter CHF 10 ganz aus. Siehe Spec §6.
    value_score: float | None = None
    #: Dieselbe Frage, tragfähige Rechnung: der Rest der Note über dem Preisniveau, nach
    #: ``(typ, sorte)`` gruppiert. Sie treibt die Rangfolge in PDF, CSV und ``diff.md``
    #: und ist die Zahl, die die Webseite in der Standardansicht zeigt — identisch, mit
    #: einem Test, der beide Kanäle gegeneinander hält.
    #:
    #: Über **beide** Warenwelten gerechnet, wie ``valueScoreAll`` auf der Seite. Wer
    #: innerhalb einer Welt vergleicht, nimmt :attr:`wert_score_welt`.
    wert_score: float | None = None
    #: Dieselbe Zahl, aber nur gegen die eigene Warenwelt — Schweizer Handel oder
    #: Vivino-Marktplatz. Entspricht ``valueScore`` auf der Seite.
    #:
    #: Sie wird gebraucht, sobald eine Liste **eine** Welt zeigt. Über beide Welten
    #: gerechnet gewinnt sonst fast durchgehend der Marktplatz: er trägt 640 der 924
    #: rankbaren Weine, weil seine Noten von Vivino selbst kommen und keinen
    #: Namensabgleich brauchen. Ohne diese zweite Zahl standen in der
    #: Preis-Leistungs-Liste des PDF 15 von 20 Weinen, die man in der Schweiz nicht
    #: kaufen kann — in zwei Preisklassen alle vier.
    wert_score_welt: float | None = None
    price_band: str = ""
    #: Welche Skala die Note für „Beste Bewertung" gestellt hat — Falstaff, ein Kritiker
    #: oder Vivino. **Nicht** die Quelle der Preis-Leistungs-Rangfolge: die läuft
    #: ausschliesslich über Vivino, weil die Regression auf dieser Skala kalibriert ist.
    rank_source: str = ""
    is_private_label: bool = False
    #: Zwischenspeicher für :attr:`stil`. Die Einordnung liest mehrere Felder und
    #: wird je Zeile mehrfach abgefragt.
    _stil: Any | None = field(default=None, repr=False, compare=False)

    @property
    def stil(self):
        """Stil-Typ: die Machart, nicht die Qualität. Siehe :mod:`winecheck.stiltyp`.

        Bewusst hier und nicht als Rechenschritt in ``aggregate``: die Einordnung
        hängt nur an Feldern, die die Zeile ohnehin trägt, und kann darum nicht
        veralten. ``sorte`` ist aus demselben Grund eine Eigenschaft.
        """
        if self._stil is None:
            from .stiltyp import Struktur, einordnen

            v = self.vivino
            self._stil = einordnen(
                self.name,
                datenblatt=" ".join(o.source_note or "" for o in self.offers),
                struktur=Struktur.aus_vivino(v.taste) if v else None,
                baseline=Struktur.aus_vivino(v.style_baseline) if v else None,
                stil_name=v.style_name if v else "",
                denomination=v.region_name if v else "",
                jahrgang=self.vintage,
            )
        return self._stil

    @property
    def herkunft(self) -> str:
        """Herkunftsland. Der Händlername nennt es selten, Vivino fast immer."""
        return (self.vivino.country if self.vivino else "") or ""

    @property
    def region(self) -> str:
        """Anbauregion als Schlüssel, ``""`` wenn unbekannt.

        Vivinos ``region_name`` ist zu fein, um damit zu rechnen: 298 verschiedene
        Namen auf 1347 Weine, Bordeaux allein in sieben Appellationen zersplittert.
        :mod:`winecheck.region` fasst zusammen, was preislich zusammengehört, und
        lässt getrennt, was es nicht tut — Barolo bleibt neben Langhe stehen.
        """
        from .region import zuordnen

        return zuordnen(self.vivino.region_name if self.vivino else "")

    @property
    def region_label(self) -> str:
        from .region import label

        return label(self.region)

    @property
    def region_spanne(self) -> str:
        """Das übliche Preisniveau der Region als Text, z.B. „12–30".

        **Gesetzte** Zahl, nicht gemessen — sie steht zur Einordnung daneben und geht
        nicht in die Preis-Leistungs-Rechnung ein. Begründung im Kopf von
        :mod:`winecheck.region`.
        """
        from .region import spanne

        s = spanne(self.region)
        return f"{s[0]:.0f}–{s[1]:.0f}" if s else ""

    @property
    def style(self) -> str:
        """Sorte: rot, weiss, rose, schaumwein, suesswein oder unbekannt.

        Vivinos ``type_id`` hat Vorrang, weil er aus der Weindatenbank kommt; sonst
        wird der Name ausgewertet.
        """
        from .names import wine_style

        type_id = self.vivino.wine_type_id if self.vivino else None
        return wine_style(self.name, type_id)

    @property
    def style_label(self) -> str:
        from .names import STYLE_LABELS

        return STYLE_LABELS.get(self.style, self.style)

    # -- Schnäppchen gegen den Marktpreis ----------------------------------
    @property
    def market_price(self) -> float | None:
        """Unabhängiger Marktpreis pro 75 cl, sofern Vivino einen nennt."""
        return self.vivino.market_price if self.vivino else None

    @property
    def bargain_percent(self) -> float | None:
        """Um wie viel Prozent liegt der Aktionspreis unter dem Marktpreis.

        Je höher, desto besser das Schnäppchen. ``None``, wenn kein unabhängiger
        Marktpreis vorliegt oder der Aktionspreis nicht verlässlich ist — geschätzt
        wird hier nichts. Negative Werte bleiben stehen: ein Angebot *über* dem
        Marktpreis ist eine Information, kein Fehler.
        """
        market = self.market_price
        price = self.best_price
        if market is None or price is None or market <= 0:
            return None
        if not any(p.price_confidence is not PriceConfidence.LOW for p in self.prices):
            return None
        # Bei unbestätigter Namenszuordnung gibt es keine Ersparnis auszuweisen.
        #
        # Der Marktpreis stammt von *dem* Wein, den Vivino gefunden hat. Ist die
        # Zuordnung nur ``fuzzy``, kann das ein anderer sein — und dann vergleicht
        # die Prozentzahl zwei verschiedene Weine. „Juan Gil Monastrell" für
        # CHF 8.90 landete auf „Juan Gil Bruto" und wies damit 85 % Ersparnis gegen
        # dessen Marktpreis von CHF 58 aus. Das ist kein Schnäppchen, das ist ein
        # Rechenfehler mit Ausrufezeichen.
        #
        # Die *Note* darf bleiben: sie ist als unbestätigt gekennzeichnet, und wer
        # sie sieht, kann dem Link folgen und selbst urteilen. Eine Prozentzahl
        # dagegen liest sich wie eine Tatsache, und niemand rechnet ihr nach.
        if self.vivino is not None and self.vivino.match_confidence == "fuzzy":
            return None
        return round((market - price) / market * 100, 1)

    @property
    def bargain_plausibility(self) -> DiscountPlausibility:
        """Ist das Schnäppchen glaubwürdig?

        Analog zur Rabatt-Prüfung bei Eigenmarken: ein Nachlass jenseits von
        :data:`~winecheck.prices.QUESTIONABLE_BARGAIN` gegen den Marktpreis kommt
        selten von einer echten Aktion und häufig von einem einzelnen fremden
        Preiseintrag. Beim ersten Lauf stand ein Bourgogne für CHF 13.95 gegen
        CHF 80.86 einer Wein-Anlageplattform — 83 % "Ersparnis", die es nicht gibt.
        Auch ein Marktpreis ohne Schweizer Shop gilt als fragwürdig.
        """
        pct = self.bargain_percent
        if pct is None:
            return DiscountPlausibility.UNKNOWN
        v = self.vivino
        foreign = bool(v and "kein Schweizer Shop" in (v.market_price_note or ""))
        if pct > QUESTIONABLE_BARGAIN or foreign:
            return DiscountPlausibility.QUESTIONABLE
        return DiscountPlausibility.OK

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
        """Ob irgendeine Fremdbewertung vorliegt.

        Muss dieselben Quellen kennen wie :meth:`ranking_rating`, sonst widerspricht sich
        der Bericht. Genau das tat er: ``critics`` fehlte hier, und damit standen 41 Weine
        mit einer Parker-93 oder Suckling-95 unter „Ohne Fremdbewertung" — und trugen in
        derselben CSV einen Preis-Leistungs-Wert, den ``ranking_rating`` aus genau dieser
        Note gebildet hatte.
        """
        if self.falstaff and self.falstaff.value is not None:
            return True
        if self.vivino and self.vivino.has_rating:
            return True
        if self.critics:
            return True
        if self.winesearcher and self.winesearcher.value is not None:
            return True
        return False

    #: Nur diese Konfidenzstufen dürfen das Ranking treiben. Ein ``fuzzy``-Match ist
    #: nicht falsch, aber unbestätigt — er wird angezeigt, mit Quell-Bezeichnung, und
    #: kann von Hand übernommen werden. Er sortiert aber keine Rangliste.
    RANKING_CONFIDENCES = (MatchConfidence.EXACT, MatchConfidence.WINE_LEVEL)

    def ranking_rating(self) -> tuple[float | None, str]:
        """Ranking läuft über Falstaff, wo vorhanden, mit Vivino als Zweitwert.

        Gibt ``(normalisierter Wert, Quellenname)`` zurück — die Quelle wird immer
        mitgeführt, damit im Report nie unklar ist, welche Skala gewonnen hat.

        Nicht ins Ranking kommen:

        * ``winery_level`` — ein Produzenten-Durchschnitt ist nicht die Note *dieses*
          Weins. "Piccini" hat 4.2 aus 752 Bewertungen; das sagt über den Chianti
          Classico Riserva von Piccini nichts Belastbares.
        * ``fuzzy`` — Namenszuordnung unbestätigt. So hing "Montagne Vin Rouge"
          (Fasswein, CHF 1.21) an "Marsannay 'La Montagne' Rouge" (Burgunder, 4.0).

        Beides bleibt im Report sichtbar, nur eben nicht im Sortierschlüssel.
        """
        if (
            self.falstaff
            and self.falstaff.value is not None
            and self.falstaff.confidence in self.RANKING_CONFIDENCES
        ):
            return self.falstaff.normalized, "Falstaff"
        # Weitere 100-Punkte-Kritiker, die der Händler am Produkt ausweist. Sie kommen
        # vor Vivino, weil die Note am *exakten* Produkt hängt — kein Namens-Matching,
        # kein Fehlzuordnungsrisiko — während ein Vivino-Treffer über Namensähnlichkeit
        # zustande kommt. Die Quelle steht immer in ``rank_source``.
        critic = self.best_critic()
        if critic is not None:
            key, value, _who = critic
            return round(value / 100.0, 4), CRITIC_LABELS.get(key, key.capitalize())
        if self.vivino and self.vivino.rating is not None and self._vivino_is_rankable():
            return round(self.vivino.rating / 5.0, 4), "Vivino"
        if self.winesearcher and self.winesearcher.value is not None:
            return self.winesearcher.normalized, "Wine-Searcher"
        return None, ""

    def best_critic(self) -> tuple[str, float, str] | None:
        """Beste verfügbare Kritikernote ausser Falstaff.

        Returns:
            ``(Schlüssel, Punkte, Händler)`` oder None. Die Reihenfolge folgt
            :data:`CRITIC_PRIORITY`, nicht der Höhe der Note — sonst gewinnt immer der
            freundlichste Kritiker, und das wäre eine Auswahl nach Wunschergebnis.
        """
        for key in CRITIC_PRIORITY:
            entry = self.critics.get(key)
            if entry is not None:
                value, who = entry
                return key, value, who
        return None

    def _vivino_is_rankable(self) -> bool:
        v = self.vivino
        if v is None:
            return False
        if v.status not in (VivinoStatus.EXACT, VivinoStatus.WINE_LEVEL):
            return False
        # Leere Konfidenz kommt aus älteren Cache-Einträgen — dann nicht ranken.
        return v.match_confidence in ("exact", "wine_level")

    def chart_rating(self) -> float | None:
        """Note für die Diagramm-Achse — ausschliesslich Vivino, in 1–5.

        Absichtlich *nicht* :meth:`ranking_rating`: dort mischen Falstaff (0–100) und
        Vivino (1–5) über eine 0–1-Normalisierung auf eine Achse, und zwei
        Bewertungsgrundlagen in einem Streudiagramm sind nicht vergleichbar — ein
        Falstaff-92 und ein Vivino-4.6 liegen dann nebeneinander, ohne dass die Punkte
        dasselbe bedeuten. Für die Rangliste bleibt Falstaff die Leitquelle; hier zählt
        nur die eine Skala, die für alle 400 Weine dieselbe ist.

        ``winery_level`` fällt raus: ein Produzenten-Mittelwert ist keine Note für
        diesen Wein und hat auf der Achse nichts zu suchen. ``fuzzy``-Matches kommen
        mit — sie betreffen 59 von 128 Weinen, und sie zu verschweigen halbiert das
        Diagramm — aber :meth:`chart_confirmed` markiert sie als unbestätigt, damit
        sie gezeichnet nicht wie bestätigte aussehen.
        """
        v = self.vivino
        if v is None or v.rating is None:
            return None
        if v.status not in (VivinoStatus.EXACT, VivinoStatus.WINE_LEVEL):
            return None
        return v.rating

    def chart_confirmed(self) -> bool:
        """Ob der Punkt auf einem bestätigten Match sitzt.

        Trennt die Darstellung von der Datenlage: ein ``fuzzy``-Match ist eine
        plausible, aber ungeprüfte Zuordnung. Gefüllt gezeichnet würde er dasselbe
        behaupten wie ein exakter Treffer.
        """
        return self._vivino_is_rankable()

    def wert_rankable(self) -> bool:
        """Ob dieser Wein eine Preis-Leistungs-Rangliste anführen darf.

        Dasselbe Verhältnis wie :meth:`chart_confirmed` zu :meth:`chart_rating`: die
        Zahl zu *rechnen* ist eine andere Frage als sie zu *sortieren*. In die
        Regression darf ein unbestätigter Treffer, sonst dünnen die Gruppen aus. An
        die Spitze einer Liste darf er nicht.

        Verlangt wird ein ranking-taugliches Vivino-Ergebnis. Ohne diese Sperre führte
        die Liste „Gran Castillo Cabernet Sauvignon" für CHF 6.00 mit einer 4.3 an, die
        dem *Produzenten* gehört — dazu fünf weitere Produzenten-Mittelwerte und zwei
        unbestätigte Zuordnungen unter den ersten 25.

        Der zweite Schadensfall — eine unsichere Gebindegrösse, die über einen falsch
        umgerechneten Literpreis einen Scheinsieger erzeugt — braucht hier **keine**
        eigene Prüfung: :attr:`best_price` lässt ``PriceConfidence.LOW`` gar nicht
        durch, und ohne Preis entsteht kein :attr:`wert_score`. Eine Prüfung, die nie
        greift, gehört nicht in eine Sicherheitsregel: sie liest sich wie ein Schutz
        und verdeckt, wo der Schutz wirklich sitzt.

        Der Wein bleibt im Bericht sichtbar — nur eben nicht im Sortierschlüssel.
        """
        return self.wert_score is not None and self._vivino_is_rankable()

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
            "wert_score": _fmt_num(self.wert_score),
            "wert_score_welt": _fmt_num(self.wert_score_welt),
            "bargain_percent": _fmt_num(self.bargain_percent),
            "bargain_plausibility": self.bargain_plausibility.value,
            "vivino_market_price": _fmt_num(v.market_price) if v else "",
            "vivino_market_price_raw": _fmt_num(v.market_price_raw) if v else "",
            "vivino_market_price_basis": (v.market_price_basis or "") if v else "",
            "vivino_market_price_shop": (v.market_price_shop or "") if v else "",
            "vivino_market_price_url": (v.market_price_url or "") if v else "",
            "vivino_market_price_note": (v.market_price_note or "") if v else "",
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
            "sorte": self.style_label,
            "sorte_key": self.style,
            # Stil-Typ: die Machart. Ohne Begründung kein Typ — die Signale stehen
            # als Klartext daneben und werden in der Anzeige gezeigt.
            "typ": self.stil.label,
            "typ_key": self.stil.typ,
            "typ_stufe": self.stil.stufe or "",
            "typ_signale": " · ".join(self.stil.signale),
            "typ_score": _fmt_num(self.stil.score),
            "herkunft": self.herkunft,
            "region": self.region_label,
            "region_key": self.region,
            # Gesetzt, nicht gemessen — siehe winecheck.region. Steht zur Einordnung
            # daneben und geht nicht in die Preis-Leistungs-Zahl ein.
            "region_preisspanne": self.region_spanne,
            "trinkreife": self.maturity.short if self.maturity else "",
            "trinkreife_text": self.maturity.text if self.maturity else "",
            "trinkreife_code": self.maturity.code if self.maturity else "",
            "trinkreife_region": self.maturity.region_label if self.maturity else "",
            # Vivinos Trinkfenster für genau diesen Wein und Jahrgang, und ob es der
            # Vinum-Tabelle widerspricht. Beide Quellen behalten ihre Stimme.
            "trinkfenster_vivino": self.maturity.fenster if self.maturity else "",
            "trinkreife_widerspruch": self.maturity.widerspruch if self.maturity else "",
            "trinkreife_weinart": self.maturity.wine_type if self.maturity else "",
            "jahrgang_qualitaet": (self.maturity.quality or "") if self.maturity else "",
            "falstaff_reported_by": (self.falstaff.source_name or "") if self.falstaff else "",
            "critics": " · ".join(
                f"{k} {v:.0f}/100 ({who})" for k, (v, who) in sorted(self.critics.items())
            ),
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
            # Abnahmemenge und Gesamtbetrag. Leer bei der Einzelflasche — dort sagt der
            # Preis je Flasche alles, und eine 1 wäre nur Rauschen in der Tabelle.
            row[f"units_{p.retailer}"] = str(p.units) if (p.units or 1) > 1 else ""
            row[f"total_{p.retailer}"] = (
                _fmt_num(p.gesamtpreis) if (p.units or 1) > 1 else ""
            )
        return row


def _fmt_num(v: float | None) -> str:
    if v is None:
        return ""
    return f"{v:.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def as_dict(obj: Any) -> dict[str, Any]:
    return asdict(obj)

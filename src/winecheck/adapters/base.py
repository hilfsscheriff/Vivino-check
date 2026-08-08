"""Gemeinsame Grundlage aller Händler-Adapter."""

from __future__ import annotations

import re
import time
import urllib.parse
from dataclasses import dataclass, field
from functools import lru_cache

from ..config import SourceConfig
from ..fetching import Blocked, Fetcher
from ..models import Offer, PriceConfidence
from ..names import extract_vintage, looks_like_private_label
from ..prices import discount_percent, normalize_price, rate_discount

#: Wörter, an denen ein Wein von anderen Sortimenten unterschieden wird.
WINE_HINTS = (
    # Plurale müssen einzeln dastehen: geprüft wird auf Wortgrenzen, damit
    # "Schweinskoteletts" nicht als Wein durchgeht — dann trifft "vin" aber auch
    # "Vins" nicht. Aligro benennt seine Warengruppen französisch im Plural
    # ("Vins rouges étrangers"), womit die verlässlichste Weinkennung wirkungslos war.
    "wein", "weine", "vin", "vins", "vino", "vini", "wine", "wines",
    "rotwein", "weisswein", "rosé", "rose",
    "schaumwein", "champagne", "prosecco", "crémant", "cremant", "sekt", "cava",
    "merlot", "chardonnay", "pinot", "cabernet", "syrah", "riesling", "chasselas",
    "fendant", "dôle", "dole", "amarone", "valpolicella", "chianti", "rioja",
    "bordeaux", "bourgogne", "barolo", "primitivo", "sangiovese", "aoc", "docg",
    "doc", "igt", "igp",
)

#: Sortimente, die trotz Wein-Stichwort nicht gemeint sind.
#:
#: Alkoholfreies steht hier aus zwei Gründen: es ist für einen Wein-Preisvergleich
#: nicht gemeint, und es unterliegt in der Schweiz dem **reduzierten** MwSt-Satz von
#: 2.6 % statt dem Normalsatz von 8.1 %, mit dem hier gerechnet wird. Ein
#: alkoholfreier Schaumwein bekäme sonst einen um 5.4 % zu hohen Preis.
NOT_WINE = (
    "weinessig", "essig", "weinbrand", "glas", "gläser", "glaeser", "korkenzieher",
    "kühler", "kuehler", "karaffe", "dekanter", "traubensaft", "weinstein",
    "sauerkraut", "weingummi", "senf", "bratwurst", "fondue", "weinbergschnecke",
    "alkoholfrei", "alkoholfreier", "alkoholfreie", "alkoholfreies",
    "entalkoholisiert", "entalkoholisierter", "sans alcool", "senza alcol",
    "rimuss", "alkoholarm",
)

#: Zubehör, das fast immer als **zusammengesetztes** Wort auftritt: „Weinglas",
#: „Rotweingläser", „Flaschenöffner". Für diese Wörter wird nur die *Endung*
#: geprüft, nicht die ganze Wortgrenze.
#:
#: ``NOT_WINE`` verlangt links wie rechts eine Wortgrenze — richtig für „Essig",
#: aber wirkungslos bei „Weinglas": vor dem g steht ein Buchstabe. Ein Weinglas kam
#: dadurch als Wein durch, denn „wein" steckt ja drin. Aufgefallen ist das erst mit
#: ``wine_only``: dort fehlt die zweite Hürde, die vorher zufällig manches abfing.
NOT_WINE_SUFFIX = (
    "glas", "gläser", "glaeser", "karaffe", "karaffen", "kelch", "kelche",
    "öffner", "oeffner", "zieher", "kühler", "kuehler", "ständer", "staender",
)

#: Wörter, die auf ``NOT_WINE_SUFFIX`` enden und trotzdem Wein bezeichnen.
#:
#: „Mehrwegglas" ist die Pfandflasche, nicht das Trinkglas. Vier Weine der
#: Zürcher Genossenschaft heissen so („Zürcher Cuvée weiss AOC, Mehrwegglas,
#: 50 cl") und wären mit der Endungsregel stillschweigend verschwunden. Sie werden
#: vor der Prüfung aus dem Text genommen.
NOT_WINE_SUFFIX_AUSNAHMEN = (
    "mehrwegglas", "mehrweggläser", "einwegglas", "pfandglas", "depotglas",
)

_RE_PRICE = re.compile(r"(\d{1,4}(?:['’]\d{3})*(?:[.,]\d{1,2})?)")

#: Kritiker, deren Punkte Händler mit ausweisen. Schlüssel ist der interne Name,
#: der Wert die Schreibvarianten im Händler-HTML.
#:
#: Das ist der Ersatz für den blockierten Falstaff-Zugang: Mövenpick schreibt
#: "Falstaff 92/100" in die Produktkachel. Die Note hängt damit am *exakten* Produkt
#: — kein Namens-Matching, kein Fehlzuordnungsrisiko. Sie ist aber vom Händler
#: berichtet und nicht bei Falstaff verifiziert; die Herkunft steht deshalb im Report.
CRITIC_ALIASES: dict[str, tuple[str, ...]] = {
    "falstaff": ("falstaff",),
    "parker": ("parker", "robert parker", "wine advocate"),
    "suckling": ("james suckling", "suckling"),
    "decanter": ("decanter",),
    "vinum": ("vinum",),
    "spectator": ("wine spectator", "spectator"),
    "gaultmillau": ("gault&millau", "gault millau", "gaultmillau"),
    "penin": ("guía peñín", "guia penin", "peñín", "penin"),
    "atkin": ("tim atkin", "atkin"),
    "dunnuck": ("jeb dunnuck", "dunnuck"),
    "galloni": ("antonio galloni", "vinous", "galloni"),
    # Bekannter Kritiker, aber Mövenpick führt ihn als "Veronelli 3/100" — Sterne,
    # nicht Punkte. Steht hier, damit die *Skalen*-Prüfung greift und nicht die
    # Namensprüfung: die Begründung im Report soll stimmen.
    "veronelli": ("veronelli",),
    "gambero": ("gambero rosso", "gambero"),
    "bibenda": ("bibenda",),
}

#: Plausible Spanne für eine 100-Punkte-Note. Alles darunter ist eine andere Skala:
#: Mövenpick schreibt z.B. "Veronelli 3/100", das sind Sterne und keine Punkte.
CRITIC_MIN, CRITIC_MAX = 50.0, 100.0

_RE_CRITIC = re.compile(
    r"([A-Za-zÀ-ÿ&.\s']{3,28}?)\s*(\d{1,3}(?:[.,]\d)?)\s*/\s*100", re.U
)


def parse_critic_scores(*texts: str) -> tuple[dict[str, float], list[str]]:
    """Zieht Kritikerpunkte aus Händlertexten wie ``"Falstaff 92/100"``.

    Returns:
        ``(Punkte je Kritiker, verworfene Angaben)``. Verworfen wird, was nicht in die
        100-Punkte-Spanne passt oder keinem bekannten Kritiker zuzuordnen ist — lieber
        eine Lücke als eine Note auf der falschen Skala.
    """
    scores: dict[str, float] = {}
    rejected: list[str] = []
    for text in texts:
        for raw_name, raw_value in _RE_CRITIC.findall(text or ""):
            label = " ".join(raw_name.split()).strip(" .&'").lower()
            try:
                value = float(raw_value.replace(",", "."))
            except ValueError:
                continue
            key = next(
                (k for k, aliases in CRITIC_ALIASES.items()
                 if any(label.endswith(a) or label == a for a in aliases)),
                None,
            )
            if key is None:
                rejected.append(f"{raw_name.strip()} {raw_value}/100 (unbekannter Kritiker)")
                continue
            if not (CRITIC_MIN <= value <= CRITIC_MAX):
                rejected.append(f"{raw_name.strip()} {raw_value}/100 (andere Skala)")
                continue
            # Bei Mehrfachnennung die höhere Note behalten — Händler führen
            # gelegentlich mehrere Jahrgänge derselben Quelle auf.
            scores[key] = max(scores.get(key, 0.0), value)
    return scores, rejected


def looks_like_wine(*texts: str) -> bool:
    """Grobe Vorfilterung für Läden mit gemischtem Sortiment.

    Auf Wortgrenzen geprüft, nicht als Teilstring: "Sch**wein**skoteletts" und
    "Sch**wein**sfleisch" enthalten "wein", sind aber kein Wein. Genau daran sind in
    der ersten Fassung Cervelas und Grillbrutzler durchgerutscht.
    """
    if kein_wein(*texts):
        return False
    hay = " ".join(t for t in texts if t).lower()
    return any(_word_re(hint).search(hay) for hint in WINE_HINTS)


def kein_wein(*texts: str) -> bool:
    """Ist das ausdrücklich **kein** Wein — Zubehör, Essig, Alkoholfreies?

    Die Umkehrung von :func:`looks_like_wine` ohne dessen zweite Hälfte: es wird
    nicht verlangt, dass ein Weinwort vorkommt. Für reine Weinhändler ist genau das
    richtig, denn dort trägt ein guter Teil der Weine gar keines im Namen — "Aalto
    2023", "689 Six Eight Nine Napa Valley", "4 kilos Tinto". Bei Schubi fielen so
    fünf von zwölf Aktionen heraus, alles unstrittige Weine.

    Der Schutz bleibt: Gläser, Karaffen und Essig fliegen weiterhin raus, und
    Alkoholfreies ebenfalls — das ist hier nicht gemeint und unterliegt zudem dem
    reduzierten MwSt-Satz von 2.6 % statt den 8.1 %, mit denen gerechnet wird.
    """
    hay = " ".join(t for t in texts if t).lower()
    if any(_word_re(bad).search(hay) for bad in NOT_WINE):
        return True
    for ausnahme in NOT_WINE_SUFFIX_AUSNAHMEN:
        hay = hay.replace(ausnahme, " ")
    return any(_endung_re(bad).search(hay) for bad in NOT_WINE_SUFFIX)


@lru_cache(maxsize=512)
def _word_re(word: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-zäöüéèàç]){re.escape(word)}(?![a-zäöüéèàç])")


@lru_cache(maxsize=512)
def _endung_re(word: str) -> re.Pattern[str]:
    """Wie :func:`_word_re`, aber ohne Grenze nach links — für Wortendungen.

    Damit trifft „glas" auch in „Wein**glas**", nicht nur alleinstehend.
    """
    return re.compile(rf"{re.escape(word)}(?![a-zäöüéèàç])")


def absolute_url(href: str, page_url: str) -> str:
    """Macht einen Händler-Link absolut.

    Viele Shops schreiben ihre Produktlinks relativ (``/edizione-bianco_21164700``).
    Unverändert übernommen landen sie im Bericht und auf der Webseite — und dort
    löst der Browser sie gegen **deren** Adresse auf. Aus einem Wein bei Wine-Outlet
    wurde so ``hilfsscheriff.github.io/edizione-bianco_21164700``: ein toter Link.

    Ist ``href`` bereits absolut, bleibt er unangetastet.
    """
    if not href:
        return ""
    return urllib.parse.urljoin(page_url, href)


def parse_price(text: str | None) -> float | None:
    """Zieht einen CHF-Betrag aus Text wie ``"statt 4.50"`` oder ``"CHF 12'950.00"``."""
    if not text:
        return None
    m = _RE_PRICE.search(str(text))
    if not m:
        return None
    raw = m.group(1).replace("'", "").replace("’", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


@dataclass
class FetchReport:
    """Was ein Adapter-Lauf ergeben hat — auch wenn er nichts ergeben hat.

    Wird im Report und in ``diff.md`` ausgewiesen, damit eine blockierte Quelle nicht
    stillschweigend als "keine Aktionen" durchgeht.
    """

    retailer: str
    status: str = "ok"              # ok | blocked | empty | error | skipped
    offers: list[Offer] = field(default_factory=list)
    message: str = ""
    resolved_url: str = ""
    url_note: str = ""
    retry_after: str | None = None

    @property
    def count(self) -> int:
        return len(self.offers)


class RetailerAdapter:
    """Basisklasse. Unterklassen implementieren :meth:`parse`."""

    def __init__(self, cfg: SourceConfig, fetcher: Fetcher):
        self.cfg = cfg
        self.fetcher = fetcher

    def ist_wein(self, *texts: str) -> bool:
        """Vorfilterung, passend zum Sortiment des Ladens.

        Bei gemischtem Sortiment muss ein Weinwort vorkommen; bei einem reinen
        Weinhändler (``wine_only: true`` in der YAML) genügt es, dass nichts
        ausdrücklich dagegen spricht. Siehe :func:`kein_wein`.
        """
        if self.cfg.wine_only:
            return not kein_wein(*texts)
        return looks_like_wine(*texts)

    # -- von Unterklassen zu implementieren -------------------------------
    def parse(self, html: str, url: str) -> list[Offer]:
        raise NotImplementedError

    def urls(self) -> list[str]:
        return list(self.cfg.urls)

    # -- gemeinsamer Ablauf -----------------------------------------------
    def fetch(self) -> FetchReport:
        """Holt alle konfigurierten Seiten, löst veraltete Deep-Links auf und meldet
        das Ergebnis — ohne bei einer Blockade den ganzen Lauf zu killen."""
        report = FetchReport(retailer=self.cfg.key)
        if not self.cfg.urls and not self.cfg.shop_root:
            report.status = "skipped"
            report.message = "keine URL konfiguriert"
            return report

        url, note = self.fetcher.resolve_url(
            self.urls(), self.cfg.shop_root, self.cfg.promo_keywords or ["aktion"]
        )
        report.url_note = note
        if not url:
            report.status = "error"
            report.message = f"keine erreichbare Aktionsseite ({note})"
            return report
        report.resolved_url = url

        offers: list[Offer] = []
        seen: set[str] = set()
        for candidate in _dedupe([url, *self.urls()]):
            if candidate in seen:
                continue
            seen.add(candidate)
            try:
                res = self.fetcher.get(candidate)
            except Blocked as exc:
                if not offers:
                    report.status = "blocked"
                    report.message = str(exc)
                    report.retry_after = exc.retry_after
                    return report
                continue
            if not res.ok:
                continue
            try:
                offers.extend(self.parse(res.text, str(res.url)))
            except Exception as exc:  # noqa: BLE001 — ein defektes Layout darf nicht alles reissen
                report.message = _join(report.message, f"Parse-Fehler auf {candidate}: {exc}")

        report.offers = _dedupe_offers(offers)
        if not report.offers:
            report.status = "empty"
            report.message = _join(
                report.message, "Seite erreichbar, aber keine Wein-Positionen erkannt"
            )
        return report

    # -- Hilfen für Unterklassen ------------------------------------------
    def make_offer(
        self,
        *,
        name: str,
        url: str = "",
        price_text: str | float | None = None,
        reference_text: str | float | None = None,
        gebinde_text: str = "",
        article_no: str | None = None,
        vintage: int | None = None,
        source_note: str = "",
        price_basis: str | None = None,
        vat_included: bool | None = None,
        critic_text: str = "",
    ) -> Offer:
        """Baut ein :class:`Offer` mit normalisiertem Preis, Rabatt und
        Eigenmarken-Kennzeichnung.

        Args:
            price_basis: Überschreibt die Einstellung des Händlers. Nötig z.B. beim
                Prodega-Prospekt, wo über dem Preis die Bezugsgrösse angeschrieben ist
                ("75 cl", "kg") — der Preis gilt dort pro Flasche, nicht pro Karton,
                auch wenn darunter das Gebinde "15 × 50 cl" steht.
        """
        amount = price_text if isinstance(price_text, (int, float)) else parse_price(price_text)
        reference = (
            reference_text
            if isinstance(reference_text, (int, float))
            else parse_price(reference_text)
        )
        vat = self.cfg.vat_included if vat_included is None else vat_included
        basis = " ".join(x for x in (gebinde_text, name) if x)
        if not vat and "mwst" not in basis.lower():
            basis += ", exkl. MwSt"

        norm = normalize_price(
            amount,
            basis,
            price_basis=price_basis or self.cfg.price_basis,
            default_vat_included=vat,
        )
        private = looks_like_private_label(name, self.cfg.private_label_brands)

        # Rabatt immer auf den *normalisierten* Aktionspreis bezogen, aber rein
        # informativ — gerankt wird nie über den Rabatt.
        ref_norm = None
        if reference is not None and amount and amount > 0 and norm.price_per_bottle_incl_vat:
            ref_norm = reference * (norm.price_per_bottle_incl_vat / amount)
        pct = discount_percent(norm.price_per_bottle_incl_vat, ref_norm)

        offer = Offer(
            retailer=self.cfg.key,
            name=name.strip(),
            url=url,
            vintage=vintage if vintage is not None else extract_vintage(f"{name} {gebinde_text}"),
            reference_price=round(ref_norm, 2) if ref_norm else None,
            discount_percent=pct,
            discount_plausibility=rate_discount(pct, private),
            is_private_label=private,
            article_no=article_no,
            fetched_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            source_note=source_note,
        )
        if critic_text:
            scores, rejected = parse_critic_scores(critic_text)
            offer.critic_scores = scores
            if rejected:
                offer.source_note = _join(
                    offer.source_note, "verworfene Notenangaben: " + "; ".join(rejected[:3])
                )
        offer.apply_price(norm)
        return offer


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    return [x for x in items if x and not (x in seen or seen.add(x))]


def _dedupe_offers(offers: list[Offer]) -> list[Offer]:
    """Ein Wein kann auf einer Seite mehrfach stehen (Teaser + Liste)."""
    best: dict[tuple[str, int | None], Offer] = {}
    for o in offers:
        key = (o.name.lower().strip(), o.vintage)
        prev = best.get(key)
        if prev is None:
            best[key] = o
            continue
        # Den mit dem verlässlicheren Preis behalten.
        if prev.price_confidence is PriceConfidence.LOW and o.price_confidence is not PriceConfidence.LOW:
            best[key] = o
        elif (o.price_per_bottle_incl_vat or 1e9) < (prev.price_per_bottle_incl_vat or 1e9):
            best[key] = o
    return list(best.values())


def _join(a: str, b: str) -> str:
    return "; ".join(x for x in (a, b) if x)

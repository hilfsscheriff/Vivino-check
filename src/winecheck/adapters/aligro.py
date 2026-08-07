"""Aligro — Abholmarkt, Aktionen aus eingebettetem JSON.

Aligro ist als Ersatz für TopCC dazugekommen: gleicher Kanal (Abholmarkt mit Karte),
neun Weinkategorien, rund 230 Aktionspositionen. TopCC selbst geht nicht, weil dessen
Prospekte auf ``files.cdn.ipaper.io`` liegen und deren robots.txt ``Disallow: /`` für
alle Agenten setzt.

Wie die Daten hereinkommen
--------------------------
Die Kategorieseite rendert die Kacheln clientseitig, liefert die Daten aber vollständig
mit: in einem Vue-Attribut ``pagination="…"`` steckt HTML-entity-kodiertes JSON mit
allen Artikeln. Kein Browser nötig, kein Nachladen — ein GET je Kategorie.

``?limit=192`` hebt die Seitengrösse von 48 auf alles. Der Parameter überlebt allerdings
**keine Weiterleitung**: ruft man den französischen Slug auf, leitet Aligro auf den
deutschen um und verliert die Abfrage. Darum wird der Slug einmal ohne Parameter
aufgelöst und dann gezielt geholt.

Die Preisfalle
--------------
Aligro zeigt je nach Kundentyp etwas völlig anderes an. Derselbe Wein:

===============  ==========================  ===========================
Kundentyp        Anzeige                     Bedeutung
===============  ==========================  ===========================
Privatkunde      ``103.- / 6 Flaschen → 83.-``  Kartonpreis, **inkl.** MwSt
Gastroprofi      ``15.88 / Flasche → 12.80``   Flaschenpreis, **exkl.** MwSt
===============  ==========================  ===========================

Gegenprobe: 83 ÷ 6 = 13.83 und 12.80 × 1.081 = 13.84 — dieselbe Flasche.

Statt eine dieser Ansichten zu lesen, nimmt der Adapter die Zahlenfelder direkt:
``discountPriceTTC`` ist der Aktionspreis **inklusive MwSt für das ganze Gebinde**,
``quantityUnit.number`` die Flaschenzahl darin. Der Quotient ist der Flaschenpreis.
Damit hängt nichts an Textauslegung, an einem Cookie oder an der Frage, welcher
Kundentyp gerade gilt — die drei Stellen, an denen so eine Rechnung sonst kippt.

``unitPrice`` wäre bequemer, ist aber **exklusive** MwSt (26.83 ÷ 6 = 4.47 bei einem
TTC-Preis von 29.00) und damit genau die Zahl, die man versehentlich für den Endpreis
hält.
"""

from __future__ import annotations

import html as _html
import json
import re
from typing import Any

from ..fetching import Blocked
from ..models import Offer, PriceConfidence
from .base import FetchReport, RetailerAdapter, looks_like_wine

#: Kategorien unter „Weine, Schaumweine". Die Nummer führt, der Slug ist nur Beiwerk —
#: Aligro leitet von jedem Slug auf den richtigen um. 1718 fehlt bewusst: alkoholfreier
#: Wein ist kein Wein und trägt ausserdem den reduzierten MwSt-Satz von 2.6 %.
CATEGORY_IDS = (1710, 1711, 1712, 1713, 1714, 1715, 1716, 1717)

#: Ausgeschlossen, mit Begründung fürs Protokoll.
SKIPPED_CATEGORIES = {1718: "alkoholfreier Wein und Schaumwein — kein Wein, anderer MwSt-Satz"}

BASE = "https://www.aligro.ch/de/aktionen"

#: Das JSON hängt in diesem Attribut. Die Mindestlänge hält kurze Attribute fern, die
#: zufällig auch „pagination" heissen könnten.
_RE_PAYLOAD = re.compile(r'pagination="((?:&quot;|[^"]){200,})"')


def _text(item: dict[str, Any], *keys: str) -> str:
    """Feld aus den Übersetzungen holen — Deutsch, sonst Französisch.

    Aligro pflegt viele Artikel nur französisch (``translations.de`` ist dann ``null``).
    Ein französischer Name ist kein Problem: der Matcher kennt die Betriebsformen und
    Rechtsbegriffe beider Sprachen.
    """
    tr = item.get("translations") or {}
    for lang in ("de", "fr"):
        block = tr.get(lang) or {}
        for k in keys:
            v = block.get(k)
            if v:
                return str(v).strip()
    return ""


def _name(item: dict[str, Any]) -> str:
    """Lesbarer Name aus Werbetext, Zusatz, Marke und Volumen.

    ``description`` allein ist oft abgekürzter Kassentext ("Valdepeñas P.Negra Reserva
    DO 2019 75 cl"). Werbetext plus Zusatzbezeichnung liest sich besser und enthält
    Jahrgang und Herkunft, was dem Matcher hilft.
    """
    parts = [
        _text(item, "advertisingText"),
        _text(item, "additionalDesignation"),
    ]
    brand = _text(item, "brand")
    if brand and not any(brand.lower() in p.lower() for p in parts if p):
        parts.append(brand)
    name = " ".join(p for p in parts if p).strip()
    if not name:
        name = _text(item, "description")
    volume = item.get("packagingLabel") or _text(item, "weightVolume")
    if volume and volume.lower() not in name.lower():
        name = f"{name}, {volume}".strip(", ")
    return name



def _category(item: dict[str, Any]) -> str:
    """Warengruppe, z.B. „Vins rouges étrangers".

    Sie steckt unter ``article.articleGroup.translations`` und **nicht** in den
    Übersetzungen des Artikels selbst. Das ist die verlässlichste Weinkennung, die
    Aligro hergibt: viele Namen tragen kein einziges Wort, das nach Wein aussieht
    („Amarone della Valpolicella Classico Zeni DOCG"), die Warengruppe schon.
    """
    group = (item.get("article") or {}).get("articleGroup") or {}
    tr = group.get("translations") or {}
    for lang in ("de", "fr"):
        w = (tr.get(lang) or {}).get("wording")
        if w:
            return str(w).strip()
    return ""

def _bottles(item: dict[str, Any]) -> int | None:
    """Flaschen im Gebinde.

    ``quantityUnit.number`` ist die verlässliche Angabe (``{"code": "Z06", "number": 6}``).
    Fehlt sie, wird nicht geraten — ein falsch geteilter Preis ist schlimmer als eine
    Lücke, und genau dafür gibt es ``price_confidence``.
    """
    unit = item.get("quantityUnit") or {}
    n = unit.get("number")
    if isinstance(n, int) and n > 0:
        return n
    # Einzelflasche ohne Gebindeangabe: quantityUnitBase sagt "BT".
    base = (item.get("quantityUnitBase") or {}).get("code")
    if base == "BT" and not unit:
        return 1
    return None


class AligroAdapter(RetailerAdapter):
    key = "aligro"

    def __init__(self, cfg, fetcher):
        super().__init__(cfg, fetcher)
        self.uncertain: list[str] = []

    def fetch(self) -> FetchReport:
        report = FetchReport(retailer=self.cfg.key)
        offers: list[Offer] = []
        seen: set[str] = set()
        notes: list[str] = []

        for cid in CATEGORY_IDS:
            try:
                url, payload = self._category(cid)
            except Blocked as exc:
                report.status = "blocked"
                report.message = str(exc)
                return report
            except Exception as exc:  # noqa: BLE001 — eine Kategorie darf den Lauf nicht kippen
                notes.append(f"Kategorie {cid}: {exc}")
                continue
            if payload is None:
                notes.append(f"Kategorie {cid}: keine Daten im HTML")
                continue
            report.resolved_url = report.resolved_url or url
            for item in payload.get("items") or []:
                offer = self._offer(item)
                if offer is None:
                    continue
                # Derselbe Artikel steht in Über- und Unterkategorie.
                sku = str(item.get("sKU") or offer.name)
                if sku in seen:
                    continue
                seen.add(sku)
                offers.append(offer)

        report.offers = offers
        if not offers:
            report.status = "empty"
            report.message = "; ".join(notes) or "keine Aktionspositionen gefunden"
            return report
        for cid, why in SKIPPED_CATEGORIES.items():
            notes.append(f"Kategorie {cid} übersprungen: {why}")
        report.message = "; ".join(notes)
        return report

    # ---------------------------------------------------------------- intern
    def _category(self, cid: int) -> tuple[str, dict[str, Any] | None]:
        """Slug auflösen, dann mit ``limit`` holen.

        Zwei Anfragen, weil ``?limit=192`` eine Weiterleitung nicht überlebt: der
        französische Slug leitet auf den deutschen um und die Abfrage geht dabei
        verloren — man bekommt stillschweigend nur die ersten 48 Positionen.
        """
        first = self.fetcher.get(f"{BASE}/{cid}-x")
        slug = str(first.url).rstrip("/").split("/")[-1].split("?")[0]
        url = f"{BASE}/{slug}"
        page = self.fetcher.get(url, params={"limit": 192})
        return url, self._payload(page.text)

    @staticmethod
    def _payload(html_text: str) -> dict[str, Any] | None:
        m = _RE_PAYLOAD.search(html_text)
        if not m:
            return None
        try:
            return json.loads(_html.unescape(m.group(1)))
        except json.JSONDecodeError:
            return None

    def _offer(self, item: dict[str, Any]) -> Offer | None:
        name = _name(item)
        if not name:
            return None
        category = _category(item)
        if not looks_like_wine(name, f"{category} {item.get('packagingLabel') or ''}"):
            return None

        price = item.get("mainArticleDetailPrice") or {}
        gross = price.get("discountPriceTTC")
        regular = price.get("salesPriceTTC")
        if gross is None:
            return None

        bottles = _bottles(item)
        url = ((item.get("href") or {}).get("self")) or ""
        article = str((item.get("article") or {}).get("articleNumber") or "") or None

        if bottles is None:
            # Ohne Flaschenzahl kein Flaschenpreis. Der Wein wird trotzdem geführt,
            # aber mit niedriger Konfidenz — und damit aus dem Ranking heraus.
            self.uncertain.append(f"{name}: Gebinde nicht erkannt, Preis gilt fürs Gebinde")
            offer = self.make_offer(
                name=name, url=url, article_no=article,
                price_text=gross, reference_text=regular,
                gebinde_text=item.get("packagingLabelPro") or "",
                vat_included=True, price_basis="pack",
                source_note="Gebindegrösse unbekannt",
            )
            offer.price_confidence = PriceConfidence.LOW
            return offer

        # Der eigentliche Punkt des Adapters: Flaschenpreis aus Zahlenfeldern, nicht
        # aus Anzeigetext. discountPriceTTC gilt fürs Gebinde und ist inkl. MwSt.
        per_bottle = round(gross / bottles, 2)
        per_bottle_regular = round(regular / bottles, 2) if regular else None
        gebinde = item.get("quantityLabelForFullPrice") or item.get("packagingLabelPro") or ""

        offer = self.make_offer(
            name=name, url=url, article_no=article,
            price_text=per_bottle, reference_text=per_bottle_regular,
            gebinde_text=item.get("packagingLabel") or "",
            vat_included=True, price_basis="bottle",
            source_note=(
                f"{gebinde}, Gebindepreis CHF {gross:.2f} inkl. MwSt "
                f"durch {bottles} geteilt" if bottles > 1 else "Einzelflasche"
            ),
        )
        offer.units = bottles
        return offer

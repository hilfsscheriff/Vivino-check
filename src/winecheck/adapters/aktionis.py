"""Aktionis-Adapter — Aggregator, liefert mehrere Händler auf einmal.

Aktionis sammelt Aktionen der Schweizer Detailhändler ein und stellt sie
serverseitig gerendert bereit. Damit kommen Quellen ins Werkzeug, die direkt nicht
einlesbar sind (Coop, Migros, Lidl) oder für die es keinen eigenen Adapter gibt
(Otto's, SPAR, Volg).

Eine Karte sieht so aus:

.. code-block:: html

    <div class="card dealtype-deal" data-upox-id="1551796">
      <a href="/deals/…" title="Mehr Infos über Blauer Zweigelt, Mundart (2022) …">
        <div class="card-merchant"><img alt="Coop"></div>
        <div class="card-price">
          <span class="price-new">3.95</span>
          <span class="price-old">7.95</span>
          <span class="price-discount">50%</span>
        </div>
        <div class="card-image"><img alt="Blauer Zweigelt, Mundart (2022) – Rotwein,
             Österreich (0.75l)"></div>
        <span class="card-date">16.07.2026 - 12.08.2026</span>

Der vollständige Weinname steht im ``alt`` des Produktbildes; die Überschrift
``h3.card-title`` ist per ``text-truncate`` gekürzt und taugt nicht zum Matchen.

**Die Daten sind aus zweiter Hand.** Ein Preis, der bei Aktionis falsch steht, steht
danach auch im Report. Die Deal-URL wird deshalb als Angebots-URL mitgeführt, damit
jede Zeile bis zur Quelle zurückverfolgbar bleibt.

``robots.txt`` erlaubt ``/q/`` und ``/deals/`` ausdrücklich; gesperrt sind
``/admin``, ``/login``, ``/profile``, ``*.pdf``, ``/dealtarget/`` und ``/app`` — die
werden nicht angefasst.
"""

from __future__ import annotations

import re
from datetime import date

from selectolax.parser import HTMLParser, Node

from ..models import Offer
from ..names import strip_accents
from .base import RetailerAdapter, kein_wein, looks_like_wine, parse_price

BASE = "https://www.aktionis.ch"

#: Höchstens so viele Seiten pro Lauf. Bei 48 Karten je Seite deckt das ~380
#: Angebote ab; mehr Wein führt Aktionis in dieser Kategorie nicht.
MAX_PAGES = 8

#: Logo-Beschriftung bei Aktionis -> Händlerschlüssel im Werkzeug. Filialformate
#: laufen auf denselben Schlüssel: "Coop Megastore" ist preislich Coop.
MERCHANT_KEYS = {
    "coop": "coop",
    "coop megastore": "coop",
    "coop bau+hobby": "coop",
    "denner": "denner",
    "denner express": "denner",
    "migros": "migros",
    "migrolino": "migros",
    "otto's": "ottos",
    "ottos": "ottos",
    "lidl": "lidl",
    "aldi": "aldi",
    "aldi suisse": "aldi",
    "spar": "spar",
    "volg": "volg",
    "landi": "landi",
    "globus": "globus",
    "manor": "manor",
}

_RE_INFO_PREFIX = re.compile(r"^\s*Mehr\s+Infos\s+über\s+", re.I)
_RE_WS = re.compile(r"\s+")


def _ist_weinrubrik(url: str) -> bool:
    """Steht diese Seite schon fest in der Weinrubrik des Aggregators?

    Auf ``/q/Wein`` hat Aktionis die Vorauswahl getroffen. Ein zweites Mal ein
    Weinwort im Produktnamen zu verlangen kostet dort nur Weine, die nach ihrem Gut
    heissen statt nach ihrer Rebsorte: „Alma de Luzon", „Opi Fantini Riserva",
    „Mont-sur-Rolle les Etourneaux", „Edizione Tre Autoctoni Bianco" — allesamt
    Weine, allesamt bisher verworfen.

    Warum das an der Adresse hängt und nicht an ``wine_only`` in der YAML: der
    Ausschlussfilter allein hält Coca-Cola, Pouletschnitzel und Vollmilch **nicht**
    zurück — nachgemessen. Sollte ``/q/Wein`` je wegbrechen und der Lauf auf eine
    allgemeine Aktionsseite ausweichen, käme mit einem pauschalen ``wine_only`` der
    halbe Lebensmittelladen herein. Seitenweise entschieden, kann das nicht passieren.
    """
    return "/q/wein" in (url or "").lower()


class AktionisAdapter(RetailerAdapter):
    key = "aktionis"

    def urls(self) -> list[str]:
        """Seite 1 ist ``/q/Wein``, weiter geht es über ``?page=N``.

        ``?p=`` und ``?offset=`` werden von Aktionis ignoriert und liefern still
        wieder Seite 1 — nur ``page`` zählt.
        """
        out: list[str] = []
        for base in self.cfg.urls:
            out.append(base)
            sep = "&" if "?" in base else "?"
            for page in range(2, MAX_PAGES + 1):
                out.append(f"{base}{sep}page={page}")
        return out

    def parse(self, html: str, url: str) -> list[Offer]:
        tree = HTMLParser(html)
        offers: list[Offer] = []
        # Auf der Weinrubrik hat der Aggregator die Vorauswahl schon getroffen.
        vorgefiltert = _ist_weinrubrik(url)
        abgelaufen = 0
        for card in tree.css("div.card.dealtype-deal"):
            if _ist_abgelaufen(card):
                abgelaufen += 1
                continue
            offer = self._parse_card(card, vorgefiltert=vorgefiltert)
            if offer is not None:
                offers.append(offer)
        if abgelaufen:
            self.melde_luecke(f"{abgelaufen} Karten mit abgelaufener Aktion übersprungen")
        return offers

    def _parse_card(self, card: Node, *, vorgefiltert: bool = False) -> Offer | None:
        name = _full_name(card)
        if not name:
            return None
        # Auf ``/q/Wein`` genügt es, dass nichts gegen Wein spricht; sonst muss ein
        # Weinwort vorkommen. Siehe :func:`_ist_weinrubrik`.
        if kein_wein(name) if vorgefiltert else not looks_like_wine(name):
            return None

        merchant = _merchant(card)
        if merchant is None:
            # Ohne Händler ist das Angebot für den Vergleich wertlos — dann lieber
            # weglassen als einem falschen Laden zuschreiben.
            return None

        price_new = _price(card, "span.price-new")
        if price_new is None:
            return None
        price_old = _price(card, "span.price-old")

        link = card.css_first("a[href]")
        href = link.attributes.get("href") if link else ""
        offer = self.make_offer(
            name=name,
            url=f"{BASE}{href}" if href and href.startswith("/") else (href or ""),
            price_text=price_new,
            reference_text=price_old,
            # Gebinde und Volumen stehen **nicht** zuverlässig im Titel. Die Karte
            # führt sie in der Metazeile: „Italien, Apulien, 2025, 6 x 75 cl". Vorher
            # ging nur der Titel hier hinein, und ein Sechserpaket galt als eine
            # Flasche — „A Mano Primitivo" stand mit CHF 39.90 statt CHF 6.65 im
            # Report, Faktor sechs. Der ganze Kartentext ist die verlässliche Quelle.
            gebinde_text=f"{name} {_card_meta(card)}",
            article_no=card.attributes.get("data-upox-id"),
            source_note=_validity(card),
            # Aus dem Text ableiten: "6x 75cl" ist ein Kartonpreis, "(0.75l)" nicht.
            # Explizit gesetzt, damit der Adapter nicht am YAML-Standard hängt.
            price_basis="auto",
        )
        # Der Händler ist das eigentliche Ziel, nicht der Aggregator.
        offer.retailer = merchant
        return offer



def _card_meta(card: Node) -> str:
    """Metazeile der Karte — Herkunft, Jahrgang und **Gebinde**.

    Steht als eigener Textknoten unter dem Titel: „Italien, Apulien, 2025, 6 x 75 cl".
    Fällt die erwartete Klasse weg, liefert der ganze Kartentext denselben Dienst; er
    enthält zusätzlich Preise, was der Gebinde-Erkennung nicht schadet.
    """
    for sel in ("p.card-meta", "div.card-meta", "p.card-description", "div.card-content"):
        n = card.css_first(sel)
        if n:
            t = " ".join(n.text().split())
            if t:
                return t
    return " ".join(card.text().split())


def _full_name(card: Node) -> str:
    """Vollständiger Name aus dem Bild-``alt``, sonst aus dem Link-``title``.

    ``h3.card-title`` ist gekürzt ("… Österreich...") und würde beim Matching
    Bestandteile verlieren.
    """
    img = card.css_first("div.card-image img")
    alt = (img.attributes.get("alt") or "") if img else ""
    if alt.strip():
        return _clean(alt)

    link = card.css_first("a[title]")
    title = (link.attributes.get("title") or "") if link else ""
    title = _RE_INFO_PREFIX.sub("", title)
    if title.strip():
        return _clean(title)

    head = card.css_first("h3.card-title")
    return _clean(head.text()) if head else ""


def _merchant(card: Node) -> str | None:
    img = card.css_first("div.card-merchant img")
    label = _clean((img.attributes.get("alt") or "") if img else "")
    if not label:
        return None
    key = MERCHANT_KEYS.get(label.lower())
    if key:
        return key
    # Unbekanntes Logo: aus dem Namen einen Schlüssel bilden, statt das Angebot
    # wegzuwerfen. Es erscheint dann unter genau dieser Bezeichnung im Report.
    # Akzente zuerst auflösen, sonst fällt "Händler" zu "hndler" zusammen.
    slug = re.sub(r"[^a-z0-9]+", "", strip_accents(label.lower()))
    return slug or None


def _price(card: Node, selector: str) -> float | None:
    node = card.css_first(selector)
    return parse_price(_clean(node.text())) if node else None


#: Das Ende der Gültigkeit aus ``"20.08.2026 - 26.08.2026"`` oder ``"bis 26.08.2026"``.
_RE_BIS = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})\s*$")


def _ist_abgelaufen(card: Node, heute: date | None = None) -> bool:
    """Läuft die Aktion dieser Karte schon nicht mehr?

    Das Datum stand bisher nur in der Notiz (:func:`_validity`) und filterte nichts.
    Ein Aggregator, der eine beendete Aktion noch listet, hätte sie damit in den
    Bericht getragen — mit einem Preis, den es an der Kasse nicht mehr gibt. Das ist
    die falsche Zahl, die dieses Projekt vermeidet.

    Nur das **Ende** wird geprüft, nicht der Beginn: eine Aktion, die morgen anfängt,
    ist eine gültige Auskunft, eine gestern beendete nicht. Ohne lesbares Datum wird
    nicht ausgeschlossen — ein fehlendes Feld darf keinen Wein kosten.
    """
    node = card.css_first("span.card-date")
    if node is None:
        return False
    m = _RE_BIS.search(_clean(node.text()))
    if not m:
        return False
    try:
        ende = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return False
    return ende < (heute or date.today())


def _validity(card: Node) -> str:
    node = card.css_first("span.card-date")
    text = _clean(node.text()) if node else ""
    return f"Aktionis, gültig {text}" if text else "Aktionis"


def _clean(text: str | None) -> str:
    return _RE_WS.sub(" ", (text or "")).strip()

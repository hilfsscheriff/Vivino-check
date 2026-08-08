"""Shopware-Weinhändler — ein Adapter für mehrere Läden.

Shopware ist bei Schweizer Weinhändlern verbreitet, und die Produktkacheln sehen
überall gleich aus: ``div.product-box`` mit ``.product-name``, ``.product-description``
und ``.product-price``. Was sich unterscheidet, sind die Kategorie-Adressen — und die
stehen in ``sources/retailers.yaml``. Ein neuer Shopware-Laden braucht damit keinen
Code, nur einen Eintrag.

Bedient aktuell Selection Schwander und Caratello.

Nur Reduziertes
---------------
Diese Läden führen Vollsortimente von hunderten Weinen. Übernommen wird **nur, was
einen Streichpreis trägt** (``CHF 13.90 statt CHF 15.40``). Ohne diese Grenze
überschwemmten ein paar hundert regulär bepreiste Weine den Bericht, und aus einem
Aktionsvergleich würde ein Weinkatalog.

Mengenrabatte sind keine Aktion
-------------------------------
Schwander schreibt daneben „Mengenrabatt 3% ab 24 Flaschen; 5% ab 60 …". Das ist ein
Staffelpreis für Grossabnehmer, kein Aktionspreis, und wird bewusst ignoriert: der
Vergleich soll zeigen, was eine einzelne Flasche heute kostet.

Zur robots.txt
--------------
Caratello verbietet ``*/?`` — also **alle** Adressen mit Query-String. Kategorien
werden darum nur über ihren Pfad geholt, ohne Sortier- oder Seitenparameter. Der
Fetcher prüft robots.txt ohnehin je Domain; die Kategorien in der YAML sind so
gewählt, dass sie erlaubt sind.
"""

from __future__ import annotations

import re

from selectolax.parser import HTMLParser, Node

from ..models import Offer
from ..names import tokenize
from .base import RetailerAdapter, looks_like_wine, parse_price

#: „CHF 13.90 statt CHF 15.40" — der zweite Preis ist der reguläre.
_RE_STATT = re.compile(r"statt\s*(?:CHF|Fr\.?)?\s*([\d'’.,]+)", re.I)
_RE_PREIS = re.compile(r"(?:CHF|Fr\.?)\s*([\d'’.,]+)")

#: Jahrgang im Namen oder in der Adresse: „…-talliya-2018-…"
_RE_JAHRGANG = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")


def _text(node: Node | None) -> str:
    return " ".join(node.text().split()) if node is not None else ""



def _enthalten(name: str, produzent: str) -> bool:
    """Steckt der Produzentenname schon im Weinnamen?

    Verglichen werden Wörter, nicht Zeichenfolgen: „Bodegas Murua" gilt als enthalten,
    wenn „Murua" im Namen steht — „Bodegas" ist eine Betriebsform und zählt nicht.
    """
    woerter = {w for w in tokenize(produzent) if len(w) > 2}
    im_namen = set(tokenize(name))
    return bool(woerter) and woerter <= im_namen


class ShopwareAdapter(RetailerAdapter):
    """Generisch — die Läden unterscheiden sich nur über ``urls`` in der YAML."""

    key = "shopware"

    def parse(self, html: str, url: str) -> list[Offer]:
        tree = HTMLParser(html)
        offers: list[Offer] = []
        for box in tree.css("div.product-box"):
            offer = self._parse_box(box)
            if offer is not None:
                offers.append(offer)
        return offers

    def _parse_box(self, box: Node) -> Offer | None:
        name = _text(box.css_first(".product-name"))
        if not name:
            return None
        # Die Beschreibung trägt bei diesen Läden den Produzenten („Château Barka").
        # Für Vivino ist der das wichtigste Wort, im Namen steht er nicht.
        produzent = _text(box.css_first(".product-description"))
        # Nur anhängen, wenn er nicht schon drinsteht: „Murua Rioja Reserva Especial"
        # plus „Bodegas Murua" ergab die Abfrage „murua especial murua", und ein
        # doppeltes Wort hilft der Suche nicht.
        if produzent and not _enthalten(name, produzent):
            voll = f"{name} {produzent}".strip()
        else:
            voll = name

        # Nicht jeder Laden nutzt .product-price; Caratello schreibt die Preise ohne
        # eigene Klasse in die Kachel. Der Kacheltext als Rückfall kostet nichts.
        kachel_text = _text(box)
        preis_text = _text(box.css_first(".product-price")) or kachel_text
        if not preis_text:
            return None

        # Ohne Streichpreis ist es kein Aktionsangebot, sondern Regalware.
        m_statt = _RE_STATT.search(preis_text)
        if not m_statt:
            return None
        referenz = parse_price(m_statt.group(1))
        if referenz is None:
            return None

        # Die Reihenfolge ist nicht verlässlich: Schwander schreibt „CHF 13.90 statt
        # CHF 15.40", Caratello „statt CHF 215.00 CHF 189.00". Wer den ersten Preis
        # nimmt, erwischt beim zweiten Laden den alten. Der Aktionspreis ist immer der
        # niedrigste — das gilt in beiden Schreibweisen.
        betraege = [p for p in (parse_price(x) for x in _RE_PREIS.findall(preis_text)) if p]
        betraege = [p for p in betraege if p < referenz]
        if not betraege:
            # Kein echter Abschlag — lieber weglassen als einen Rabatt von 0 % oder
            # gar einen negativen auszuweisen.
            return None
        aktuell = min(betraege)

        link = box.css_first("a.product-name") or box.css_first("a[href]")
        href = link.attributes.get("href", "") if link else ""

        if not looks_like_wine(voll, href):
            return None

        jahr = _RE_JAHRGANG.search(f"{voll} {href}")
        return self.make_offer(
            name=voll,
            url=href,
            price_text=aktuell,
            reference_text=referenz,
            # Der Kacheltext, nicht der Name: Caratello schreibt das Volumen daneben
            # („… 2016 , 150 cl"), im Namen steht es bei keiner der 70 Positionen.
            # Ohne diese Angabe geht eine Magnum als 75-cl-Flasche durch und landet
            # zum halben Literpreis in der Rangliste.
            gebinde_text=f"{voll} {kachel_text}",
            vintage=int(jahr.group(1)) if jahr else None,
            vat_included=True,
            price_basis="bottle",
        )

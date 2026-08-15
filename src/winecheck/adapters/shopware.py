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
from .base import RetailerAdapter, parse_price

#: „CHF 13.90 statt CHF 15.40" — der zweite Preis ist der reguläre.
_RE_STATT = re.compile(r"statt\s*(?:CHF|Fr\.?)?\s*([\d'’.,]+)", re.I)

#: Shopware schreibt für Screenreader hin, wie viel die Seite zeigt: „Es werden 24
#: von 74 Produkten angezeigt." Das ist die ehrlichste Quelle für den eigenen
#: Deckungsgrad, und sie steht in jedem Theme.
_RE_ANGEZEIGT = re.compile(r"(\d+)\s+von\s+(\d+)\s+Produkten", re.I)


def _angezeigt_von(html: str) -> tuple[int, int]:
    """(sichtbar, insgesamt) — (0, 0), wenn die Seite nichts dazu sagt."""
    m = _RE_ANGEZEIGT.search(html or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)
#: Währung vorn („CHF 13.90") wie hinten („6,50 CHF*"). Shopware 6 stellt sie in
#: der Standardausgabe nach, ältere Themes davor.
_RE_PREIS = re.compile(r"(?:(?:CHF|Fr\.?)\s*([\d'’.,]+)|([\d'’.,]+)\s*(?:CHF|Fr\.?))")

#: Ab wie vielen Wörtern ein Beschreibungsfeld als Fliesstext gilt und nicht mehr
#: als Produzentenname. Vino Vintana füllt dasselbe Feld mit Werbetext („Aus Italien
#: stammt dieser Rosé Spumante DOC der Casa Vinicola Caldirola, einem …"), Schwander
#: und Caratello mit „Bodegas Murua". Angehängt wird nur der Name; der Werbetext
#: würde die Vivino-Abfrage unbrauchbar machen.
_PRODUZENT_MAX_WOERTER = 6

#: Jahrgang im Namen oder in der Adresse: „…-talliya-2018-…"
_RE_JAHRGANG = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")


def _text(node: Node | None) -> str:
    return " ".join(node.text().split()) if node is not None else ""



def _preise(text: str) -> list[float]:
    """Alle CHF-Beträge eines Textes, gleich ob die Währung vor oder hinter steht."""
    aus = []
    for vorn, hinten in _RE_PREIS.findall(text):
        p = parse_price(vorn or hinten)
        if p is not None:
            aus.append(p)
    return aus


def _ist_produzentenname(text: str) -> bool:
    """Sieht das Beschreibungsfeld nach einem Namen aus — oder nach Werbetext?

    Zwei Merkmale unterscheiden sie zuverlässig: die Länge und der Satzpunkt.
    Ein Produzent heisst „Bodegas Murua", ein Werbetext hört nicht auf.
    """
    if not text or "." in text:
        return False
    return len(text.split()) <= _PRODUZENT_MAX_WOERTER


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

        gezeigt, gesamt = _angezeigt_von(html)
        if gesamt > gezeigt > 0:
            self.melde_luecke(
                f"Seite 1 von {-(-gesamt // gezeigt)}: {gezeigt} von {gesamt} Produkten "
                f"sichtbar — robots.txt verbietet Query-Strings, also kein Blättern"
            )
        return offers

    @staticmethod
    def _gebinde(box: Node, voll: str, kachel_text: str) -> str:
        """Der Text, aus dem die Flaschengrösse gelesen wird.

        Steht sie in einem eigenen Feld (``span.price-unit-content``, „0.75 Liter"),
        wird **nur** dieses genommen. Der ganze Kacheltext taugt dort nicht: daneben
        steht der Referenzpreis „(10,00 CHF* / 1 Liter)", und die Normalisierung fand
        dann zwei Volumen — 750 ml und 1000 ml. Uneindeutig heisst
        ``price_confidence = low``, und damit fiel jeder Wein dieses Ladens aus der
        Rangliste, obwohl seine Grösse sauber angeschrieben war.

        Ohne eigenes Feld bleibt der Kacheltext: Caratello schreibt das Volumen frei
        daneben („… 2016 , 150 cl"), und im Namen steht es bei keiner der 70
        Positionen. Ohne diese Angabe ginge eine Magnum als 75-cl-Flasche durch und
        landete zum halben Literpreis in der Rangliste.
        """
        einheit = _text(box.css_first(".price-unit-content"))
        return f"{einheit} {voll}".strip() if einheit else f"{voll} {kachel_text}"

    def _parse_box(self, box: Node) -> Offer | None:
        name = _text(box.css_first(".product-name"))
        if not name:
            return None
        # Die Beschreibung trägt bei manchen Läden den Produzenten („Château Barka").
        # Für Vivino ist der das wichtigste Wort, im Namen steht er nicht. Bei anderen
        # steht dort Werbeprosa — die muss draussen bleiben, sonst sucht Vivino nach
        # einem halben Absatz.
        produzent = _text(box.css_first(".product-description"))
        if not _ist_produzentenname(produzent):
            produzent = ""
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

        # Ohne Streichpreis ist es kein Aktionsangebot, sondern Regalware. Zwei
        # Schreibweisen: als Wort („statt CHF 15.40") oder als eigenes Element
        # (``span.list-price``, Shopware-6-Standard, ganz ohne „statt").
        m_statt = _RE_STATT.search(preis_text)
        if m_statt:
            referenz = parse_price(m_statt.group(1))
        else:
            liste = _preise(_text(box.css_first(".list-price-price"))
                            or _text(box.css_first(".list-price")))
            referenz = liste[0] if liste else None
        if referenz is None:
            return None

        # Die Reihenfolge ist nicht verlässlich: Schwander schreibt „CHF 13.90 statt
        # CHF 15.40", Caratello „statt CHF 215.00 CHF 189.00". Wer den ersten Preis
        # nimmt, erwischt beim zweiten Laden den alten. Der Aktionspreis ist immer der
        # niedrigste — das gilt in beiden Schreibweisen.
        betraege = [p for p in _preise(preis_text) if p < referenz]
        if not betraege:
            # Kein echter Abschlag — lieber weglassen als einen Rabatt von 0 % oder
            # gar einen negativen auszuweisen.
            return None
        aktuell = min(betraege)

        link = box.css_first("a.product-name") or box.css_first("a[href]")
        href = link.attributes.get("href", "") if link else ""

        if not self.ist_wein(voll, href):
            return None

        # Der **letzte** Jahrgang im Text, nicht der erste. Diese Läden hängen den
        # Jahrgang hinten an; steht vorne eine Jahreszahl, gehört sie zum Namen:
        # „Since 1974 Prosecco Superiore … Millesimato Dry 2025" ist ein 2025er, und
        # mit dem ersten Treffer wäre daraus ein einundfünfzig Jahre alter Prosecco
        # geworden — mit entsprechend absurder Trinkreife.
        jahre = _RE_JAHRGANG.findall(f"{voll} {href}")
        return self.make_offer(
            name=voll,
            url=href,
            price_text=aktuell,
            reference_text=referenz,
            gebinde_text=self._gebinde(box, voll, kachel_text),
            vintage=int(jahre[-1]) if jahre else None,
            vat_included=True,
            price_basis="bottle",
        )

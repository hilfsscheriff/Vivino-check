"""Volg — kleiner eigener Weinshop, bisher nur über den Aggregator gesehen.

Volg stand als ``adapter: none``, ``status: via_aktionis`` im Verzeichnis: die
Angebote sollten über Aktionis hereinkommen. Diese Woche kam dort genau **eine**
Position an, während ``volg.ch/weinshop/`` neun führte — der Aggregator nimmt
offenbar nicht alles mit. Der Vermerk „kommt über Aktionis" war damit keine falsche
Aussage, aber eine, auf die man sich nicht verlassen kann.

Der Laden schreibt alles an, was gebraucht wird:

.. code-block:: html

    <div class="c-product">
      <h3 class="c-product__title">G Cuvée Rosé Prestige<p>Schweiz 2025</p></h3>
      <div class="c-product__description">
        <strong>Bestelleinheit:</strong> Karton à 6 Flaschen (75cl)
        nur CHF 63.00 statt CHF 87.00
      </div>
      <div class="c-product__price">
        <span class="c-product__price-main">10.50</span>
        <span class="u-text-nowrap">statt 14.50 / Flasche</span>

Der Karton ist eine Falle, und zwar in beide Richtungen
-------------------------------------------------------
In der Beschreibung stehen **Kartonpreise** (63.00 statt 87.00), im Preisblock
daneben die **Flasche** (10.50 statt 14.50). Beides sind echte Zahlen desselben
Angebots — sie unterscheiden sich um den Faktor 6.

Darum zwei Festlegungen, die zusammengehören: gelesen wird ausschliesslich der
Preisblock, und ``price_basis`` steht fest auf ``bottle``. Käme der ganze
Kacheltext in die Gebinde-Erkennung, fände sie „Karton à 6 Flaschen", teilte den
ohnehin schon richtigen Flaschenpreis noch einmal durch sechs, und Volg stünde mit
CHF 1.75 an der Spitze jeder Rangliste. Ein Scheinsieger entsteht hier nicht durch
einen zu hohen, sondern durch einen zu niedrigen Preis.

Die Flaschengrösse kommt aus dem ``(75cl)`` derselben Zeile — die einzige Angabe
daraus, die gebraucht wird.

Kein Blätterwerk
----------------
Die Seite führt neun Weine und hat keinen Pager. Das ist der ganze Aktionsbestand
dieses Ladens, nicht ein Ausschnitt davon.
"""

from __future__ import annotations

import re

from selectolax.parser import HTMLParser, Node

from ..models import Offer
from .base import RetailerAdapter, absolute_url, parse_price

#: „statt 14.50 / Flasche" — der Referenzpreis je Flasche, nicht je Karton.
_RE_STATT = re.compile(r"statt\s*(?:CHF\s*)?([\d'’.,]+)", re.I)

#: „(75cl)", „(50 cl)" — die Grösse aus der Bestelleinheit-Zeile.
_RE_GROESSE = re.compile(r"\((\d+)\s*(cl|ml|l)\)", re.I)

#: Vierstellige Jahreszahl im Herkunftszusatz („Schweiz 2025").
_RE_JAHR = re.compile(r"\b(19[5-9]\d|20[0-3]\d)\b")


def _sauber(node: Node | None) -> str:
    return " ".join(node.text().split()) if node is not None else ""


class VolgAdapter(RetailerAdapter):
    key = "volg"

    def parse(self, html: str, url: str) -> list[Offer]:
        tree = HTMLParser(html)
        offers: list[Offer] = []
        for box in tree.css("div.c-product"):
            offer = self._parse_box(box, url)
            if offer is not None:
                offers.append(offer)
        return offers

    def _parse_box(self, box: Node, seiten_url: str = "https://www.volg.ch/weinshop/") -> Offer | None:
        titel = box.css_first("h3.c-product__title")
        if titel is None:
            return None

        # Der Herkunftszusatz steht als <p> im Titel: "Schweiz 2025". Er trägt den
        # Jahrgang, gehört aber nicht in den Namen — "G Cuvée Prestige Schweiz 2024"
        # als Suchbegriff verwässert den Vivino-Abgleich.
        zusatz_node = titel.css_first("p")
        zusatz = _sauber(zusatz_node)
        voll = _sauber(titel)
        name = voll[: -len(zusatz)].strip() if zusatz and voll.endswith(zusatz) else voll
        if not name or not self.ist_wein(name, zusatz):
            return None

        preis = parse_price(_sauber(box.css_first("span.c-product__price-main")))
        if preis is None:
            return None

        # Nur der Preisblock, nie die Beschreibung: dort stehen Kartonpreise.
        block = _sauber(box.css_first("div.c-product__price"))
        m = _RE_STATT.search(block)
        referenz = parse_price(m.group(1)) if m else None
        # Ohne Streichpreis ist es Regalware — dieselbe Grenze wie bei allen Läden.
        if referenz is None or referenz <= preis:
            return None

        jahr = _RE_JAHR.search(zusatz)
        link = box.css_first("a[href]")
        return self.make_offer(
            name=name,
            url=absolute_url(link.attributes.get("href") if link else "", seiten_url),
            price_text=preis,
            reference_text=referenz,
            gebinde_text=_groesse(box),
            vintage=int(jahr.group(1)) if jahr else None,
            # Fest: der gelesene Preis ist bereits der Flaschenpreis. Siehe Modulkopf.
            price_basis="bottle",
        )


def _groesse(box: Node) -> str:
    """Nur die Flaschengrösse aus der Bestelleinheit-Zeile, nicht die ganze Zeile.

    „Karton à 6 Flaschen (75cl)" ergibt „75 cl". Die Kartonangabe bleibt bewusst
    draussen — der gelesene Preis gilt schon je Flasche.
    """
    text = _sauber(box.css_first("div.c-product__description"))
    m = _RE_GROESSE.search(text)
    return f"{m.group(1)} {m.group(2).lower()}" if m else ""

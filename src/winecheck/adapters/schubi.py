"""Schubi Weine — die sauberste Aktionsquelle im Bestand.

Der Laden schreibt alles an, was dieser Vergleich braucht, und zwar in eigenen
Feldern statt in einem Fliesstext: Name, Jahrgang, Produzent, Flaschengrösse,
Aktionspreis, Streichpreis und den Mehrwertsteuersatz. Es muss nichts geraten
werden.

Die Klassennamen führen in die Irre
-----------------------------------
``productdetail__price-norm`` trägt den **Aktions**preis, ``product__price-action``
den **Streich**preis („statt CHF 39.00"). Das ist genau andersherum, als die Namen
vermuten lassen. Verlassen wird sich darum nicht auf sie, sondern auf die Beträge:
der Aktionspreis ist der kleinere. Bleibt richtig, auch wenn der Laden die
Klassennamen irgendwann geraderückt.

Nur Reduziertes
---------------
Es zählt, was einen Streichpreis trägt. Die Aktionsseite führt zwar ausschliesslich
Aktionen, aber die Regel ist dieselbe wie bei allen anderen Läden: ohne
Referenzpreis lässt sich Aktion nicht von Regalware unterscheiden.

Umfang — und ein Irrtum, der ein Jahr lang im Docstring stand
--------------------------------------------------------------
Hier stand: „Die Seite zeigt zwölf Weine, und dabei bleibt es — ``?p=2``,
``?limit=all`` und ``?product_list_limit=36`` liefern alle dieselben zwölf. Ein
Blätterwerk zu bauen wäre also nutzlos."

Der Befund stimmte, der Schluss nicht. Alle drei Parameter sind Magento-Namen, und
dieser Laden blättert nicht mit Magento, sondern mit ``?shop_recpage=``. Drei
erfolglose Versuche mit dem falschen Schlüssel wurden als Beweis gelesen, dass die
Tür zu ist.

Nachgemessen: Seite 1 und Seite 2 tragen zwölf beziehungsweise elf Weine mit **null**
Überschneidung, der Pager nennt 59 Seiten, der Seitenkopf 702 Produkte. Es waren also
rund 690 Aktionen unsichtbar — bei der Quelle, die im Kopf dieser Datei als „die
sauberste im Bestand" gelobt wird.

Wie viele Seiten es sind, sagt der Pager selbst (``a.pagingbullet-list__pagingbullet``
mit ``data-page``). Eine feste Zahl stünde hier nur, bis das Sortiment wächst.
"""

from __future__ import annotations

import re

from selectolax.parser import HTMLParser, Node

from ..fetching import Blocked
from ..models import Offer
from ..names import tokenize
from .base import RetailerAdapter, absolute_url, parse_price

#: „CHF 28.50", „CHF 1'250.00"
_RE_PREIS = re.compile(r"(?:CHF|Fr\.?)\s*([\d'’.,]+)", re.I)

#: Notdeckel, falls der Pager unlesbar wird. Der Laden zählt derzeit 59 Seiten;
#: reichlich Luft nach oben ist billiger als ein stiller Abschnitt.
MAX_SEITEN = 120


def _text(node: Node | None) -> str:
    return " ".join(node.text().split()) if node is not None else ""


def _enthalten(name: str, produzent: str) -> bool:
    """Steckt der Produzent schon im Weinnamen?

    Wortweise verglichen: „Bodegas Binigrau" gilt als enthalten, wenn „Binigrau" im
    Namen steht — „Bodegas" ist eine Betriebsform und trägt zur Unterscheidung
    nichts bei. Ohne diese Prüfung stünde in der Vivino-Abfrage „binigrau …
    binigrau", und ein doppeltes Wort hilft der Suche nicht.
    """
    woerter = {w for w in tokenize(produzent) if len(w) > 2}
    return bool(woerter) and woerter <= set(tokenize(name))


class SchubiAdapter(RetailerAdapter):
    key = "schubi"

    def __init__(self, cfg, fetcher):
        super().__init__(cfg, fetcher)
        self._letzte: dict[str, int] = {}

    def urls(self) -> list[str]:
        """Grundseiten plus Blätterung über ``?shop_recpage=``.

        Die ``robots.txt`` des Hauses sperrt einzig ``/admin/`` — Query-Strings sind
        nicht ausgenommen, dieser Weg ist also erlaubt.
        """
        return [u for base in self.cfg.urls for u in self._seiten(base)]

    def _seiten(self, base: str) -> list[str]:
        letzte = self._letzte_seite(base)
        return [base, *(f"{base}?shop_recpage={p}" for p in range(2, letzte + 1))]

    def _letzte_seite(self, base: str) -> int:
        """Höchste Seitenzahl aus dem Pager.

        Gemerkt, weil :meth:`RetailerAdapter.fetch` die Liste zweimal anfordert und
        die erste Seite sonst doppelt geholt würde.

        Ist der Pager unlesbar, gilt :data:`MAX_SEITEN` statt einer kleinen Zahl. Der
        Fehler kostet dann Anfragen für Seiten, die es nicht gibt; deren Angebote sind
        Dubletten und fallen weg. Andersherum wäre er teurer — genau andersherum lag
        er ja bisher, und niemand hat die fehlenden 690 Weine vermisst.
        """
        if base in self._letzte:
            return self._letzte[base]

        letzte = MAX_SEITEN
        try:
            res = self.fetcher.get(base)
        except Blocked:
            letzte = 1                      # blockiert ist blockiert, nicht 60 Versuche
        else:
            if res.ok:
                seiten = [
                    int(roh)
                    for a in HTMLParser(res.text).css("a.pagingbullet-list__pagingbullet")
                    if (roh := a.attributes.get("data-page") or "").isdigit()
                ]
                if seiten:
                    letzte = min(max(seiten), MAX_SEITEN)
        self._letzte[base] = letzte
        return letzte

    def parse(self, html: str, url: str) -> list[Offer]:
        tree = HTMLParser(html)
        offers: list[Offer] = []
        for box in tree.css("div.productoverview__item"):
            offer = self._parse_box(box, url)
            if offer is not None:
                offers.append(offer)
        return offers

    def _parse_box(self, box: Node, seiten_url: str = "https://www.schubiweine.ch/") -> Offer | None:
        titel = box.css_first("a.product__title")
        name = _text(titel)
        if not name:
            return None

        # Der Produzent steht separat und ist für Vivino das wichtigste Wort —
        # im Titel fehlt er bei den meisten Positionen.
        produzent = _text(box.css_first(".product__producer"))
        voll = name if not produzent or _enthalten(name, produzent) else f"{name} {produzent}"

        preis_text = _text(box.css_first(".product__price"))
        if "statt" not in preis_text.lower():
            return None
        betraege = [p for p in (parse_price(x) for x in _RE_PREIS.findall(preis_text)) if p]
        if len(betraege) < 2:
            return None
        aktuell, referenz = min(betraege), max(betraege)
        if aktuell >= referenz:
            return None

        # Schubi verlinkt relativ ("/b-binigrau-…-a10145.html"). Unverändert
        # übernommen löst der Browser den Link gegen die Adresse der *Berichtsseite*
        # auf und landet auf github.io statt beim Händler.
        href = absolute_url(titel.attributes.get("href", "") if titel else "", seiten_url)
        if not self.ist_wein(voll, href):
            return None

        # Die Flaschengrösse hat ein eigenes Feld („75 cl", „150 cl"). Ohne sie ginge
        # eine Magnum als normale Flasche durch und landete zum halben Literpreis
        # in der Rangliste.
        gebinde = _text(box.css_first(".product__bottle-size"))

        jahr = _text(box.css_first(".product__vintage"))
        return self.make_offer(
            name=voll,
            url=href,
            price_text=aktuell,
            reference_text=referenz,
            gebinde_text=f"{gebinde} {voll}".strip(),
            vintage=int(jahr) if jahr.isdigit() else None,
            # Steht wörtlich in jeder Kachel: „inkl. 8.1% MwSt."
            vat_included=True,
            price_basis="bottle",
        )

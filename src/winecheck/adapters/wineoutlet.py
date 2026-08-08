"""Wine-Outlet — Restposten mit angeschriebenem Literpreis.

Die Besonderheit dieses Ladens: er rechnet den Literpreis selbst aus und schreibt
ihn daneben („CHF 17.70 / 75 cl **(CHF 33.73 / L.)**"). Damit lässt sich die eigene
Umrechnung gegenprüfen, statt ihr vertrauen zu müssen — siehe
:meth:`WineOutletAdapter._gegenprobe`. Weicht sie ab, gilt der Gebindetext als
unklar und der Wein fällt aus der Rangliste, statt mit einem falschen Literpreis
einen Scheinsieger zu erzeugen.

Nur Reduziertes
---------------
Trotz des Namens ist nicht jede Position herabgesetzt: von zwölf Kacheln trugen
zehn ein „statt". Übernommen wird nur, was einen Streichpreis hat — sonst wäre der
Rabatt eine Behauptung ohne Bezugsgrösse.

Der Produzent steckt im Beschreibungstext
-----------------------------------------
``a.product-desc-section`` enthält Produzent **und** drei Geschmacksadjektive in
einem Feld: „Bodegas Príncipe de Viana Stoffig - aromatisch - harmonisch". Getrennt
wird am ersten „ - ", und vom vorderen Teil fällt das letzte Wort weg — das ist das
erste Adjektiv, das ohne Trenner am Produzenten klebt. Bleiben „Bodegas Príncipe de
Viana", „Fantini", „DonnaChiara". Ohne diesen Schnitt landete „Stoffig" in der
Vivino-Abfrage.

Umfang
------
``?limit=48`` liefert die volle Liste; ``?page=`` und ``?p=`` ändern nichts.
"""

from __future__ import annotations

import re

from selectolax.parser import HTMLParser, Node

from ..models import Offer
from ..names import tokenize
from .base import RetailerAdapter, absolute_url, parse_price

_RE_PREIS = re.compile(r"(?:CHF|Fr\.?)\s*([\d'’.,]+)", re.I)
#: „(CHF 33.73 / L.)" — der vom Laden gerechnete Literpreis.
_RE_LITERPREIS = re.compile(r"\(\s*(?:CHF|Fr\.?)\s*([\d'’.,]+)\s*/\s*L", re.I)
#: „/ 75 cl", „/ 150 cl", „/ 1.5 L"
_RE_GEBINDE = re.compile(r"/\s*(\d+(?:[.,]\d+)?)\s*(cl|dl|l|ml)\b", re.I)

#: Wie weit der eigene Literpreis vom angeschriebenen abweichen darf. Zwei Prozent
#: decken Rundung ab; alles darüber heisst, dass die Gebindeangabe anders gemeint
#: war als gelesen.
_TOLERANZ = 0.02


def _text(node: Node | None) -> str:
    return " ".join(node.text().split()) if node is not None else ""


def _produzent(desc: str) -> str:
    """Zieht den Produzenten aus „<Produzent> <Adjektiv> - <Adjektiv> - <Adjektiv>"."""
    if " - " not in desc:
        return ""
    kopf = desc.split(" - ")[0].split()
    # Mit nur einem Wort im Kopf wäre nach dem Abschneiden nichts mehr übrig —
    # dann lieber gar keinen Produzenten als einen leeren.
    return " ".join(kopf[:-1]) if len(kopf) > 1 else ""


def _enthalten(name: str, produzent: str) -> bool:
    woerter = {w for w in tokenize(produzent) if len(w) > 2}
    return bool(woerter) and woerter <= set(tokenize(name))


class WineOutletAdapter(RetailerAdapter):
    key = "wineoutlet"

    def parse(self, html: str, url: str) -> list[Offer]:
        tree = HTMLParser(html)
        offers: list[Offer] = []
        for box in tree.css("article.product-elem"):
            offer = self._parse_box(box, url)
            if offer is not None:
                offers.append(offer)
        return offers

    @staticmethod
    def _gegenprobe(preise: tuple[float, ...], gebinde: str, angeschrieben: float | None) -> bool:
        """Bestätigt der angeschriebene Literpreis die gelesene Flaschengrösse?

        Geprüft wird gegen Aktions- **und** Streichpreis, denn der Laden rechnet
        seinen Literpreis bei reduzierter Ware aus dem *Streich*preis:
        „CHF 9.60 / 75 cl statt CHF 17.45 (CHF 23.27 / L.)" — 23.27 ist 17.45 / 0.75,
        nicht 9.60 / 0.75. Nur gegen den Aktionspreis geprüft schlug die Kontrolle
        bei jedem reduzierten Wein an und warf die Gebindeangabe weg, die sie
        eigentlich bestätigen sollte.

        Geprüft wird die Flaschengrösse, nicht der Preis: passt einer der beiden
        Beträge, ist die Grösse richtig gelesen. Ohne angeschriebenen Literpreis
        wird nicht widersprochen — die Prüfung soll Fehler finden, nicht Weine ohne
        Zusatzangabe aussortieren.
        """
        if angeschrieben is None:
            return True
        m = _RE_GEBINDE.search(gebinde)
        if not m:
            return True
        menge = float(m.group(1).replace(",", "."))
        liter = {"cl": menge / 100, "dl": menge / 10, "ml": menge / 1000, "l": menge}[
            m.group(2).lower()
        ]
        if liter <= 0:
            return False
        return any(
            abs(p / liter - angeschrieben) <= angeschrieben * _TOLERANZ for p in preise
        )

    def _parse_box(self, box: Node, seiten_url: str = "https://www.wine-outlet.ch/") -> Offer | None:
        name = _text(box.css_first(".product-name"))
        if not name:
            return None

        produzent = _produzent(_text(box.css_first("a.product-desc-section")))
        voll = name if not produzent or _enthalten(name, produzent) else f"{name} {produzent}"

        preis_roh = _text(box.css_first(".product-price"))
        aktuell = parse_price(_RE_PREIS.search(preis_roh).group(1)) if _RE_PREIS.search(preis_roh) else None
        statt_roh = _text(box.css_first(".product-instead-price"))
        referenz = parse_price(_RE_PREIS.search(statt_roh).group(1)) if _RE_PREIS.search(statt_roh) else None
        if aktuell is None or referenz is None or aktuell >= referenz:
            return None

        # Wine-Outlet verlinkt relativ ("/edizione-bianco_21164700"). Unverändert
        # übernommen löst der Browser den Link gegen die Adresse der *Berichtsseite*
        # auf: aus dem Wein wurde hilfsscheriff.github.io/edizione-bianco_21164700.
        link = box.css_first("a[href]")
        href = absolute_url(link.attributes.get("href", "") if link else "", seiten_url)
        if not self.ist_wein(voll, href):
            return None

        # „CHF 17.70 / 75 cl" trägt Preis und Flaschengrösse im selben Feld.
        gebinde = preis_roh
        liter_roh = _RE_LITERPREIS.search(_text(box.css_first(".product-liter-price")))
        angeschrieben = parse_price(liter_roh.group(1)) if liter_roh else None
        if not self._gegenprobe((aktuell, referenz), gebinde, angeschrieben):
            # Die eigene Lesart des Gebindes widerspricht dem Laden. Der Gebindetext
            # wird verworfen; ohne ihn stuft die Preisnormalisierung den Wein als
            # unsicher ein und nimmt ihn aus der Rangliste.
            gebinde = ""

        jahr = _text(box.css_first(".product-year"))
        return self.make_offer(
            name=voll,
            url=href,
            price_text=aktuell,
            reference_text=referenz,
            gebinde_text=f"{gebinde} {voll}".strip(),
            vintage=int(jahr) if jahr.isdigit() else None,
            # Der Laden schreibt es an den Preis: title="Preis inkl. Mwst. / zzgl. Versand"
            vat_included=True,
            price_basis="bottle",
        )

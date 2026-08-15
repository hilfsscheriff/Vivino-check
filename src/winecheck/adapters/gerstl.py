"""Gerstl Weinselektionen — die Aktionen liegen als JSON in der Seite.

Gerstl läuft auf Angular und legt seinen Zustand als ``<script id="ng-state">``
in die Seite. Darin steht jede Position vollständig ausgezeichnet: Produzent,
Weinname, Appellation, Jahrgang, Preis, Streichpreis, Flaschengrösse, Gebinde,
Land und Region. Das ist die verlässlichere Quelle als das HTML darum herum — die
Kacheln tragen ausschliesslich Tailwind-Hilfsklassen (``w-full grid
grid-cols-[100px_1fr] xs:grid-cols-…``), die sich beim nächsten Feinschliff des
Layouts ändern, ohne dass am Inhalt etwas anders wäre.

Welcher Preis gilt
------------------
Das Feld ``prices`` legt die ganze Staffel offen::

    {"ws": 9.6, "hr": 13.4, "hR2": 11.3, "ek": 5.10, "pr": 14.9}

Genommen wird ``price``, und das entspricht ``pr`` — dem Privatkundenpreis.
``ws`` und ``hr`` sind Handels- und Gastronomiekonditionen, ``ek`` ist Gerstls
eigener Einkauf. Wer davon einen nähme, stellte einen Preis in die Rangliste, den
niemand bezahlen kann.

Diese Staffel beweist nebenbei, dass der Preis **pro Flasche** gilt und nicht pro
Gebinde: bei einem Karton zu sechs entspräche ``ek`` einem Einkauf von 85 Rappen
je Flasche Prosecco. Die AGB bestätigen es wörtlich — „Preise verstehen sich pro
75cl-Flasche, inkl. Mehrwertsteuer".

Sechserkarton
-------------
``packaging.quantity`` ist bei allen Positionen 6: Gerstl verkauft nicht einzeln.
Der Preis je Flasche stimmt trotzdem, aber der Einstieg kostet das Sechsfache.
Das steht als Hinweis am Händlereintrag, damit im Bericht niemand mit CHF 14.90
rechnet und an der Kasse CHF 89.40 sieht.

Zur robots.txt
--------------
Gerstl verbietet ``*?p=*`` und ``*&p=*`` — also die Blätterparameter. Die
Aktionsseite wird darum ohne Parameter geholt; sie führt alle Aktionen auf einer
Seite.
"""

from __future__ import annotations

import html as _html
import json
import re
from typing import Any, Iterator

from ..models import Offer
from .base import RetailerAdapter

#: Der Angular-Zustand. HTML-entitätencodiert, muss vor dem Parsen entschärft werden.
_RE_STATE = re.compile(
    r'<script[^>]*id="ng-state"[^>]*>(.*?)</script>', re.S | re.I
)

#: Woran ein Produktobjekt im Zustandsbaum erkannt wird. Der Baum enthält daneben
#: Filterdefinitionen, Navigationsknoten und Bannertexte; ein Objekt mit *beiden*
#: Feldern ist zuverlässig eine Position.
_PFLICHTFELDER = ("oldPrice", "packaging")


def _produkte(knoten: Any) -> Iterator[dict]:
    """Läuft den Zustandsbaum ab und gibt jedes Produktobjekt zurück."""
    if isinstance(knoten, dict):
        if all(f in knoten for f in _PFLICHTFELDER):
            yield knoten
        for wert in knoten.values():
            yield from _produkte(wert)
    elif isinstance(knoten, list):
        for wert in knoten:
            yield from _produkte(wert)


def _gesamtzahl(knoten: Any) -> int:
    """Wie viele Aktionen der Laden insgesamt führt.

    Angular legt neben die 15 ausgelieferten Produkte die Gesamtzahl: ein ``count``
    direkt neben dem ``data``-Array. Auf ``/aktionen/c`` steht dort 1307, im Fliesstext
    bestätigt durch „1 - 15 von 1307 Produkte".

    Die Zahl wird nur zum Melden gebraucht — geholt werden die übrigen nicht, das
    verböte die ``robots.txt``. Aber ein Lauf, der 15 von 1307 liest und „ok" meldet,
    behauptet etwas Falsches über seine Vollständigkeit.
    """
    gefunden = 0
    if isinstance(knoten, dict):
        if isinstance(knoten.get("count"), int) and isinstance(knoten.get("data"), list):
            gefunden = knoten["count"]
        for wert in knoten.values():
            gefunden = max(gefunden, _gesamtzahl(wert))
    elif isinstance(knoten, list):
        for wert in knoten:
            gefunden = max(gefunden, _gesamtzahl(wert))
    return gefunden


def _name(p: dict) -> str:
    """Baut den Namen so, wie der Laden ihn selbst anzeigt.

    ``title1`` ist der Produzent, ``title2`` die Appellation, ``title3`` der
    Weinname. Die Kachel zeigt „<title3> <title1>" — „L'Homme-Cheval Domaine
    Léandre-Chevalier". Bei drei der fünfzehn Positionen ist ``title3`` leer
    (Château du Retout, Château Brisson); dort tritt die Appellation an seine
    Stelle, sonst bliebe nur der Produzentenname stehen und zwei Jahrgänge
    desselben Guts wären nicht zu unterscheiden.
    """
    produzent = (p.get("title1") or "").strip()
    appellation = (p.get("title2") or "").strip()
    wein = (p.get("title3") or "").strip()
    teile = [wein, produzent] if wein else [produzent, appellation]
    return " ".join(t for t in teile if t)


class GerstlAdapter(RetailerAdapter):
    key = "gerstl"

    def parse(self, html: str, url: str) -> list[Offer]:
        m = _RE_STATE.search(html)
        if not m:
            return []
        try:
            zustand = json.loads(_html.unescape(m.group(1)))
        except json.JSONDecodeError:
            return []

        offers: list[Offer] = []
        gesehen: set[str] = set()
        for p in _produkte(zustand):
            # Derselbe Wein steht im Zustandsbaum mehrfach (Liste, Vorschau,
            # Empfehlungen). Die SKU trägt den Jahrgang, zwei Jahrgänge desselben
            # Guts bleiben damit getrennt.
            sku = str(p.get("sku") or p.get("id") or "")
            if sku and sku in gesehen:
                continue
            offer = self._offer(p)
            if offer is not None:
                gesehen.add(sku)
                offers.append(offer)

        gesamt = _gesamtzahl(zustand)
        if gesamt > len(gesehen):
            self.melde_luecke(
                f"{len(gesehen)} von {gesamt} Aktionen gelesen — "
                f"robots.txt verbietet *?p=*, mehr ist ohne Blättern nicht zu holen"
            )
        return offers

    def _offer(self, p: dict) -> Offer | None:
        name = _name(p)
        if not name:
            return None

        preis, referenz = p.get("price"), p.get("oldPrice")
        if not isinstance(preis, (int, float)) or not isinstance(referenz, (int, float)):
            return None
        # Ohne echten Abschlag ist es keine Aktion, sondern Regalware.
        if not preis or referenz <= preis:
            return None

        slug = (p.get("slug") or "").strip()
        href = f"https://www.gerstl.ch/{slug}/p" if slug else ""
        if not self.ist_wein(name, href):
            return None

        # Die Flaschengrösse steht als Zahl in Zentilitern („value": 75). Ohne sie
        # ginge eine Magnum als 75-cl-Flasche durch und landete zum halben
        # Literpreis in der Rangliste.
        groesse = (p.get("size") or {}).get("name") or ""

        jahr = (p.get("year") or {}).get("name") if isinstance(p.get("year"), dict) else None
        return self.make_offer(
            name=name,
            url=href,
            price_text=float(preis),
            reference_text=float(referenz),
            gebinde_text=f"{groesse} {name}".strip(),
            article_no=str(p.get("sku") or "") or None,
            vintage=int(jahr) if jahr and str(jahr).isdigit() else None,
            # AGB: „Preise verstehen sich pro 75cl-Flasche, inkl. Mehrwertsteuer".
            vat_included=True,
            # Der Preis gilt je Flasche, auch wenn nur im Sechserkarton verkauft wird.
            price_basis="bottle",
        )

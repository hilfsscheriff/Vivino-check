"""Adapter für die Neos-Shops von DIVO und Alloboissons.

Beide Läden laufen auf derselben Plattform — ``GabWeb.Shop``, erkennbar an den
Skriptpfaden ``_Resources/Static/Packages/GabWeb.Shop/`` — und werden deshalb von
**einem** Adapter bedient, so wie ``shopware`` mehrere Händler trägt. Der Adapter
heisst darum nach der Plattform und nicht nach dem ersten Laden, für den er
gebaut wurde.

Die Aktionsseite ``/de/sortiment.html?promotions=true`` liefert jede Kachel als
vollständiges JSON im Alpine-Attribut ``x-data="product({…})"``:

.. code-block:: json

    {"id": "91967 75 2024", "name": "Anthoinette 2024",
     "description": "Bordeaux Blanc AOC", "extraDescription": "Château Castera",
     "conditioningDescription": "Flasche 75 cl",
     "packagingDescription": "Karton 6x75 cl",
     "packaging": {"unit": 43618, "main": 43617},
     "price": {"43618": "15.20", "43617": "91.20"},
     "promotion": {"percent": 10, "regularPrice": {"43618": "16.90"}},
     "gAData": {"items": [{"item_category": "Flaschenweine"}]}}

Damit steht alles in einer Abfrage: Preis, Referenzpreis, Gebinde, Flaschengrösse,
Produzent und Warengruppe. Kein Browser, keine Detailseite, kein Ratespiel. Beide
Shops weisen unter der Liste "Die Preise sind in CHF und inkl. MwSt." aus — geprüft,
nicht angenommen, denn ein Grossist mit Netto-Preisen ergäbe 8.1 % zu tiefe Werte.

Warengruppe statt Wortfilter
----------------------------
DIVO führt nur Wein, Alloboissons alle Getränke — zwölf Weine neben Bier, Evian und
Eistee. Der Wortfilter (:func:`looks_like_wine`) taugt dort für keine der beiden
Richtungen: "Féchy Bertrand de Mestral", "Gamaret-Garanoir" und "Charme Spumante"
tragen kein Weinwort und wären verschwunden, während "Boxer old spéciale" und
"Coors" mangels Gegenwort als Wein durchgekommen wären.

Entschieden wird darum über die Warengruppe, die die Plattform selbst führt
(``gAData.items[0].item_category`` — dieselben Werte, mit denen ihr eigener Filter
``filters[categories1][]`` arbeitet). Nur bei einer *unbekannten* Gruppe entscheidet
der Wortfilter: so kommt "Assyrtiko 2024" herein, das DIVO intern unter "Absent de
la liste" führt und dessen "Laconia IGP" die Weinprüfung besteht. Eine unbekannte
Gruppe muss sich also ausweisen, statt ungeprüft zu gelten.

Preis: was tatsächlich zu zahlen ist
------------------------------------
Die Kachel nennt Flaschen- **und** Kartonpreis. Welcher gilt, hängt vom Laden ab und
steht im Produkt: DIVO verkauft einzelne Flaschen (``isSellableByUnit: true``),
Alloboissons ausschliesslich Kartons. Gelesen wird der Preis des Gebindes, das man
wirklich kaufen kann, mitsamt dem dazu passenden Gebindetext. Sonst stünde im
Bericht ein Zahlbetrag von CHF 14.50 für einen Wein, den es nur zu sechst für
CHF 87.00 gibt — genau die Sorte Scheingenauigkeit, die der Zahlbetrag seit
:attr:`Offer.gesamtpreis` vermeiden soll.
"""

from __future__ import annotations

import html as html_entities
import json
import re

from ..models import Offer
from .base import RetailerAdapter, kein_wein, looks_like_wine

#: Warengruppen (``categories1``), die Wein führen.
WEIN_GRUPPEN = frozenset({"flaschenweine", "vins en bouteille", "offenweine", "vins ouverts"})

#: Warengruppen, die ausdrücklich kein Wein sind.
#:
#: Vollständig aus dem Filter der beiden Shops übernommen. Die französischen
#: Schreibweisen stehen mit dabei, weil die Plattform mehrsprachig ist und eine
#: umbenannte Gruppe hier nicht stillschweigend zu Wein werden soll — sie fällt dann
#: in den Wortfilter, nicht durch.
NICHT_WEIN_GRUPPEN = frozenset({
    "biere und mostgetränke", "bières et cidres", "bières et boissons au moût",
    "alkoholfreie getränke", "boissons sans alcool",
    "spirituosen", "spiritueux",
    "verschiedenes", "divers",
})

#: Untergruppen (``categories2``), die trotz Weingruppe nicht gemeint sind.
#:
#: Der Degustationskarton ist die Probe aufs Exempel: DIVO führt ihn unter
#: "Flaschenweine", er heisst "Zwischenstopp am Mittelmeer", kostet CHF 98 und ist
#: eine gemischte Kiste ohne eigene Flaschengrösse. Über die Warengruppe allein käme
#: er als Wein in die Rangliste. "Ohne Alkohol" fliegt aus zwei Gründen: hier nicht
#: gemeint, und in der Schweiz mit 2.6 % statt 8.1 % MwSt belastet.
NICHT_WEIN_UNTERGRUPPEN = frozenset({
    "degustationkarton", "degustationskarton", "carton de dégustation",
    "ohne alkohol", "sans alcool",
})

#: Die Produktkachel. Im ausgelieferten HTML steht kein einziges echtes
#: Anführungszeichen innerhalb des Attributs — alles ist als ``&quot;`` kodiert.
#: Darum genügt ``[^"]*``, und ein Klammernzähler ist nicht nötig.
_RE_KACHEL = re.compile(r'x-data="product\((\{[^"]*\})\)"')

#: Vorlage für den Produktlink. Die Seite baut ihn per JavaScript:
#: ``el.href = productDetailUri.replace("0", product.id)``.
_RE_LINKVORLAGE = re.compile(r'productDetailUri\((?:&quot;|["\'])([^&"\']+)')

_RE_JAHR = re.compile(r"(?:19|20)\d\d")


class GabWebAdapter(RetailerAdapter):
    key = "gabweb"

    def parse(self, html: str, url: str) -> list[Offer]:
        vorlage = self._linkvorlage(html)
        offers: list[Offer] = []
        kacheln = defekt = 0

        for treffer in _RE_KACHEL.finditer(html):
            kacheln += 1
            try:
                produkt = json.loads(html_entities.unescape(treffer.group(1)))
            except ValueError:
                defekt += 1
                continue
            if not isinstance(produkt, dict):
                defekt += 1
                continue
            if not self._ist_wein(produkt):
                continue
            angebot = self._angebot(produkt, vorlage, url)
            if angebot is not None:
                offers.append(angebot)

        # Eine Kachel, die sich nicht lesen lässt, ist eine Lücke und kein "ok":
        # ohne diese Meldung sähe ein halb geparster Lauf aus wie ein vollständiger.
        if defekt:
            self.melde_luecke(f"{defekt} von {kacheln} Produktkacheln nicht lesbar")
        return offers

    # -- Auswahl ----------------------------------------------------------
    def _ist_wein(self, produkt: dict) -> bool:
        """Wein oder nicht — zuerst nach der Warengruppe des Shops, dann nach Wort."""
        gruppe, untergruppe = _warengruppen(produkt)
        texte = (
            str(produkt.get("name") or ""),
            str(produkt.get("description") or ""),
            str(produkt.get("extraDescription") or ""),
        )
        if untergruppe in NICHT_WEIN_UNTERGRUPPEN:
            return False
        if gruppe in NICHT_WEIN_GRUPPEN:
            return False
        if gruppe in WEIN_GRUPPEN:
            # Auch in der Weingruppe liegt Zubehör und Alkoholfreies.
            return not kein_wein(*texte)
        return looks_like_wine(*texte)

    # -- eine Kachel in ein Angebot -----------------------------------------
    def _angebot(self, produkt: dict, vorlage: str, seite: str) -> Offer | None:
        if not produkt.get("isSellable", True):
            return None
        if produkt.get("isTemporarilyUnavailable"):
            return None

        # Ohne Flaschengrösse ist nichts auf 75 cl umzurechnen. Der
        # Degustationskarton steht mit ``capacity: 0`` da; die Untergruppe fängt ihn
        # schon ab, aber die Grösse ist die allgemeinere Prüfung.
        kapazitaet = (produkt.get("conditioningDetail") or {}).get("capacity")
        if not isinstance(kapazitaet, (int, float)) or kapazitaet <= 0:
            return None

        pack = produkt.get("packaging") or {}
        details = produkt.get("packagingDetails") or {}
        flasche, karton = str(pack.get("unit")), str(pack.get("main"))

        einzeln = bool(produkt.get("isSellableByUnit")) and bool(
            (details.get(flasche) or {}).get("isSellable", True)
        )
        if einzeln:
            schluessel = flasche
            gebinde = str(produkt.get("conditioningDescription") or "")
            basis = "bottle"
        else:
            schluessel = karton
            gebinde = str(produkt.get("packagingDescription") or "")
            basis = "pack"

        betrag = _betrag((produkt.get("price") or {}).get(schluessel))
        if betrag is None:
            return None
        referenz = _betrag(
            ((produkt.get("promotion") or {}).get("regularPrice") or {}).get(schluessel)
        )
        if referenz is None:
            # DIVO führt beides, Alloboissons nur ``promotion.regularPrice``.
            referenz = _betrag((produkt.get("insteadOfPrice") or {}).get(schluessel))

        artikel = str(produkt.get("id") or "")
        hinweise = []
        if not einzeln:
            menge = (details.get(karton) or {}).get("quantity")
            hinweise.append(f"nur im Karton{f' à {menge}' if menge else ''}")
        if produkt.get("hasDeliveryDelay"):
            hinweise.append("Lieferverzögerung")

        return self.make_offer(
            name=_anzeigename(produkt),
            url=_produktlink(vorlage, artikel, seite),
            price_text=betrag,
            reference_text=referenz,
            gebinde_text=gebinde,
            article_no=artikel or None,
            vintage=_jahrgang(artikel),
            price_basis=basis,
            source_note="; ".join(hinweise),
        )

    def _linkvorlage(self, html: str) -> str:
        m = _RE_LINKVORLAGE.search(html)
        if not m:
            # Lieber ohne Link als mit einem geratenen: ein toter Produktlink ist
            # im Bericht schlimmer als keiner (siehe Flaschenpost).
            self.melde_luecke("Vorlage für den Produktlink nicht gefunden")
            return ""
        return html_entities.unescape(m.group(1))


def _warengruppen(produkt: dict) -> tuple[str, str]:
    """``(Warengruppe, Untergruppe)`` aus den Analytics-Daten der Kachel, klein."""
    posten = ((produkt.get("gAData") or {}).get("items") or [{}])[0]
    if not isinstance(posten, dict):
        return "", ""
    return (
        str(posten.get("item_category") or "").strip().lower(),
        str(posten.get("item_category2") or "").strip().lower(),
    )


def _anzeigename(produkt: dict) -> str:
    """Name, Produzent und Appellation zu einem Suchnamen.

    "Anthoinette 2024" allein ist bei Vivino hoffnungslos; mit "Château Castera"
    und "Bordeaux Blanc AOC" ist der Wein eindeutig. Die Appellation trägt zudem die
    Region, nach der die Preis-Leistungs-Rechnung gruppiert. Doppelt genannt wird
    nichts: bei Alloboissons steht der Produzent schon in der ``description``
    ("Ticino DOC - Delea").
    """
    teile = [str(produkt.get("name") or "").strip()]
    for zusatz in (produkt.get("extraDescription"), produkt.get("description")):
        text = str(zusatz or "").strip()
        if text and text.lower() not in " ".join(teile).lower():
            teile.append(text)
    return " ".join(t for t in teile if t)


def _jahrgang(artikel: str) -> int | None:
    """Der Jahrgang aus der Artikelnummer ``"91967 75 2024"``.

    Strukturierte Angabe statt Namensauslese — und sie fehlt sauber, wo kein
    Jahrgang existiert ("98811 75" für einen Champagner ohne Jahr). Der dritte Teil
    muss eine Jahreszahl sein: der Degustationskarton "93959 2026 08" endet auf "08"
    und liefert damit nichts.
    """
    teile = artikel.split()
    if len(teile) >= 3 and _RE_JAHR.fullmatch(teile[2]):
        return int(teile[2])
    return None


def _produktlink(vorlage: str, artikel: str, seite: str) -> str:
    """Baut den Produktlink wie das Shop-JavaScript: erste "0" durch die ID ersetzt.

    Die ID enthält Leerzeichen ("91967 75 2024"); im Browser werden sie zu ``%20``.
    Ohne diese Kodierung wäre der Link im Bericht unbrauchbar.
    """
    if not vorlage or not artikel:
        return ""
    from urllib.parse import quote, urljoin

    pfad = vorlage.replace("0", quote(artikel), 1)
    return urljoin(seite, pfad)


def _betrag(wert: object) -> float | None:
    """Preise stehen als Zeichenkette in der Kachel ("15.20")."""
    if wert is None or isinstance(wert, bool):
        return None
    try:
        betrag = float(str(wert).replace("'", "").replace(",", "."))
    except ValueError:
        return None
    return betrag if betrag > 0 else None

"""Mövenpick-Adapter.

Serverseitig gerendertes Magento mit eigenem Theme. Ein Produkt steckt in
``div.cs-product-tile``:

* ``a.product-item-link`` — Name und URL
* ``div.price-box`` — "Sonderpreis CHF 48.00 / Regulärer Preis CHF 59.00"
* ``.cs-product-tile__attribute`` — Jahrgang, Region, Gebinde

``robots.txt`` verbietet Query-Strings (``Disallow: /*?*``) mit Ausnahme von ``p=``
und ``page=`` — Paginierung läuft deshalb über ``?p=``, Suchqueries gibt es nicht.
"""

from __future__ import annotations

import re
import urllib.parse

from selectolax.parser import HTMLParser, Node

from ..fetching import Blocked
from ..models import Offer
from ..names import PACKAGING_NOISE, PRODUCER_WORDS, tokenize
from .base import RetailerAdapter, looks_like_wine, parse_price

#: Notbremse für die Paginierung, **nicht** die erwartete Seitenzahl — die steht im
#: Pager und wird von dort gelesen (:meth:`MoevenpickAdapter._letzte_seite`). Greift
#: nur, wenn sich das Markup ändert oder eine unsinnig grosse Zahl liefert.
MAX_PAGES = 40

_RE_SPECIAL = re.compile(r"sonderpreis", re.I)
_RE_REGULAR = re.compile(r"regul[äa]rer\s+preis|statt", re.I)
_RE_VINTAGE_ATTR = re.compile(r"\b(19[5-9]\d|20[0-3]\d)\b")


class MoevenpickAdapter(RetailerAdapter):
    key = "moevenpick"

    def __init__(self, cfg, fetcher):
        super().__init__(cfg, fetcher)
        self._letzte: dict[str, int] = {}

    def urls(self) -> list[str]:
        """Grundseiten plus Paginierung über den erlaubten ``?p=``-Parameter.

        Wie viele Seiten es gibt, sagt Magento selbst — vorher stand hier ein fester
        Deckel von vier Seiten. Der war der Grund, dass „Fallet Dart Champagne Brut
        Cuvée de Réserve" (CHF 28.80 statt 36.00) nie im Report auftauchte: der Wein
        steht auf Seite 7, und von 511 Angeboten sahen wir 96.

        Zu bemerken war das nicht: ein zu grosses ``p`` beantwortet Magento nicht mit
        404, sondern klemmt stillschweigend auf die erste Seite zurück. Ein Deckel
        schneidet also lautlos ab — und ein höherer wäre nur ein späterer Deckel, weil
        das Sortiment jede Woche anders gross ist.
        """
        return [u for base in self.cfg.urls for u in self._seiten(base)]

    def _seiten(self, base: str) -> list[str]:
        letzte = self._letzte_seite(base)
        return [base, *(f"{base}?p={p}" for p in range(2, letzte + 1))]

    def _letzte_seite(self, base: str) -> int:
        """Letzte Seitenzahl aus dem Pager (``<input data-role="pager" max="22">``).

        Das Ergebnis wird gemerkt, weil :meth:`RetailerAdapter.fetch` die URL-Liste
        zweimal anfordert und die erste Seite sonst dreimal geholt würde.

        Ist der Pager nicht lesbar, gilt :data:`MAX_PAGES` statt einer kleinen Zahl.
        Der Fehler kostet dann Anfragen für Seiten, die es nicht gibt — die doppelten
        Angebote fallen in der Dedup-Stufe weg. Andersherum wäre er teurer: fehlende
        Weine sieht im Report niemand.
        """
        if base in self._letzte:
            return self._letzte[base]

        letzte = MAX_PAGES
        try:
            res = self.fetcher.get(base)
        except Blocked:
            letzte = 1                      # blockiert ist blockiert, nicht 40 Versuche
        else:
            if res.ok:
                pager = HTMLParser(res.text).css_first('input[data-role="pager"]')
                roh = (pager.attributes.get("max") or "") if pager else ""
                if roh.isdigit():
                    letzte = min(int(roh), MAX_PAGES)
        self._letzte[base] = letzte
        return letzte

    def parse(self, html: str, url: str) -> list[Offer]:
        tree = HTMLParser(html)
        offers: list[Offer] = []
        for tile in tree.css("div.cs-product-tile"):
            offer = self._parse_tile(tile)
            if offer is not None:
                offers.append(offer)
        return offers

    def _parse_tile(self, tile: Node) -> Offer | None:
        link = tile.css_first("a.product-item-link")
        if link is None:
            return None
        name = _clean(link.text())
        if not name:
            return None

        href = link.attributes.get("href") or ""
        attrs_text = " ".join(
            _clean(n.text()) for n in tile.css(".cs-product-tile__attribute")
        )
        # Kritikerpunkte: Mövenpick weist sie selbst aus ("Falstaff 92/100"). Das ist
        # der Ersatz für den blockierten Falstaff-Zugang — 12 von 24 Kacheln tragen
        # eine oder mehrere Noten.
        critic_text = " · ".join(
            _clean(n.text()) for n in tile.css(".cs-product-tile__attributes-item-value")
        )
        # Ohne Wein-Indiz überspringen — Mövenpick verkauft auch Zubehör und Spirituosen.
        if not looks_like_wine(name, attrs_text) and not _RE_VINTAGE_ATTR.search(attrs_text):
            return None

        special, regular = _prices(tile)
        if special is None:
            return None

        vintage_match = _RE_VINTAGE_ATTR.search(f"{name} {attrs_text}")
        # Produzent aus der Adresse anhängen — er fehlt im Namen und ist das Wort, das
        # die Vivino-Suche trägt.
        producer = producer_from_url(name, href)
        if producer:
            # In Klammern: so trägt der Name den Produzenten für die Vivino-Suche,
            # ohne dass er beim Namensvergleich als fehlender Bestandteil zählt.
            name = f"{name} ({producer})"
        # Jahrgangs-Sets tragen ihre Flaschenzahl nur in der Adresse.
        flaschen = bottles_from_url(href)
        gebinde = attrs_text
        if flaschen:
            gebinde = f"{attrs_text} Karton {flaschen} x 75 cl"
        return self.make_offer(
            name=name,
            url=href,
            price_text=special,
            reference_text=regular,
            gebinde_text=gebinde,
            vintage=int(vintage_match.group(1)) if vintage_match else None,
            source_note=_clean(attrs_text)[:160],
            critic_text=critic_text,
        )



#: Wörter, die im URL-Slug neben dem Produzenten stehen und keiner sind.
_SLUG_NOISE = frozenset({"bio", "set", "anniversary", "edition", "geschenk", "magnum",
                         "doppelmagnum", "holzkiste", "originalholzkiste"})


def producer_from_url(name: str, url: str) -> str:
    """Produzent aus dem URL-Slug, den Mövenpick im Namen weglässt.

    Mövenpick benennt seine Weine nach Herkunft und Lage — „Côtes du Roussillon
    Villages AOC 2020 Les Dentelles" — und stellt den Produzenten nur in die Adresse:
    ``…-aoc-domaine-thunevin-calvet.html``. Für Vivino ist genau das das wichtigste
    Wort: die Suche sortiert nach Bewertung, nicht nach Namensähnlichkeit, und ohne
    Produzent findet man den berühmtesten Wein der Appellation statt den gesuchten.
    Bei „Les Dentelles" fand die Suche über den Weinnamen allein fünf fremde Weine,
    die Suche über „Thunevin-Calvet" den richtigen.

    Der Trick ist einfach: der Slug ist Name **plus** Produzent. Was im Slug steht und
    im Namen fehlt, ist der Produzent.

    Returns:
        Leerstring, wenn nichts Belastbares übrig bleibt — dann bleibt der Name, wie
        er ist. Geraten wird nicht.
    """
    if not url:
        return ""
    slug = urllib.parse.urlparse(url).path.rsplit("/", 1)[-1]
    slug = re.sub(r"\.html?$", "", slug).replace("-", " ")
    in_name = set(tokenize(name))
    extra = [
        t for t in tokenize(slug)
        if t not in in_name
        and t not in PRODUCER_WORDS      # "domaine", "chateau" — Betriebsform, kein Name
        and t not in PACKAGING_NOISE
        and t not in _SLUG_NOISE
        and not t.isdigit()
        and len(t) > 2
    ]
    return " ".join(extra[:3]).title()


#: Jahrgangs-Sets in der Adresse: „…-anniversary-set-2x2013-2x2016-2x2018-…".
#: Die Zahl vor dem x ist die Flaschenzahl je Jahrgang, die Summe das Gebinde.
_RE_SET = re.compile(r"(\d{1,2})\s*x\s*(19|20)\d{2}\b", re.I)


def bottles_from_url(url: str) -> int | None:
    """Flaschenzahl eines Jahrgangs-Sets aus der Adresse.

    Mövenpick verkauft Sammlungen als eine Position: „Anniversary Set 2x2013 2x2016
    2x2018" sind sechs Flaschen zu CHF 290 — also CHF 48.33 je Flasche, nicht 290.
    Im Namen steht davon nichts, und ohne Volumenangabe nimmt die Preisrechnung eine
    einzelne 75-cl-Flasche an. Der Fehler ist der Faktor sechs, und er trifft immer
    die teuersten Positionen, weil nur dort Sets verkauft werden.
    """
    treffer = _RE_SET.findall(url or "")
    if not treffer:
        return None
    n = sum(int(a) for a, _ in treffer)
    return n if 1 < n <= 24 else None

def _prices(tile: Node) -> tuple[float | None, float | None]:
    """Sonderpreis und regulären Preis auseinanderhalten.

    Steht nur ein Preis da, ist das der Aktionspreis und es gibt keinen Referenzwert —
    dann bleibt der Rabatt leer statt geschätzt zu werden.
    """
    box = tile.css_first("div.price-box") or tile
    special = regular = None

    for node in box.css("span.price, span.price-wrapper, .special-price, .old-price"):
        text = _clean(node.text())
        value = parse_price(text)
        if value is None:
            continue
        context = _clean((node.parent.text() if node.parent else "") + " " + text)
        classes = " ".join(
            filter(None, [node.attributes.get("class"), (node.parent.attributes.get("class") if node.parent else "")])
        )
        if "old-price" in classes or _RE_REGULAR.search(context):
            regular = regular or value
        elif "special-price" in classes or _RE_SPECIAL.search(context):
            special = special or value
        elif special is None:
            special = value

    if special is None or regular is None:
        # Fallback über den reinen Text der Preisbox: "Sonderpreis CHF 48.00
        # Regulärer Preis CHF 59.00"
        text = _clean(box.text())
        numbers = [parse_price(x) for x in re.findall(r"CHF\s*[\d'’.,]+", text)]
        numbers = [n for n in numbers if n]
        if _RE_SPECIAL.search(text) and len(numbers) >= 2:
            special, regular = numbers[0], numbers[1]
        elif numbers:
            special = special or numbers[0]

    # Ein "regulärer Preis" unter dem Aktionspreis ist keiner.
    if special is not None and regular is not None and regular <= special:
        regular = None
    return special, regular


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()

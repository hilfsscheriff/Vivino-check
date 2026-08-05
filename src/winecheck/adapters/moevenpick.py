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

from selectolax.parser import HTMLParser, Node

from ..models import Offer
from .base import RetailerAdapter, looks_like_wine, parse_price

#: Mövenpick zeigt 24 Kacheln pro Seite; mehr als das holen wir pro Lauf nicht,
#: damit das Rate-Limit von 1 Anfrage / 2 s nicht zur Endlosschleife wird.
MAX_PAGES = 4

_RE_SPECIAL = re.compile(r"sonderpreis", re.I)
_RE_REGULAR = re.compile(r"regul[äa]rer\s+preis|statt", re.I)
_RE_VINTAGE_ATTR = re.compile(r"\b(19[5-9]\d|20[0-3]\d)\b")


class MoevenpickAdapter(RetailerAdapter):
    key = "moevenpick"

    def urls(self) -> list[str]:
        """Grundseiten plus Paginierung über den erlaubten ``?p=``-Parameter."""
        out: list[str] = []
        for base in self.cfg.urls:
            out.append(base)
            for page in range(2, MAX_PAGES + 1):
                out.append(f"{base}?p={page}")
        return out

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
        # Ohne Wein-Indiz überspringen — Mövenpick verkauft auch Zubehör und Spirituosen.
        if not looks_like_wine(name, attrs_text) and not _RE_VINTAGE_ATTR.search(attrs_text):
            return None

        special, regular = _prices(tile)
        if special is None:
            return None

        vintage_match = _RE_VINTAGE_ATTR.search(f"{name} {attrs_text}")
        return self.make_offer(
            name=name,
            url=href,
            price_text=special,
            reference_text=regular,
            gebinde_text=attrs_text,
            vintage=int(vintage_match.group(1)) if vintage_match else None,
            source_note=_clean(attrs_text)[:160],
        )


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

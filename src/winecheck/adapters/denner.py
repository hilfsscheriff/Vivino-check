"""Denner-Adapter.

Denner ist eine Nuxt-3-Anwendung. Die Aktionsprodukte stehen serverseitig im
``__NUXT_DATA__``-Payload — kein Browser nötig. Ein Produkt sieht dort so aus:

.. code-block:: json

    {"sku": "296633f2-…", "price": 2.95, "itemType": "PRODUCT",
     "attributeInfo": [{"attributeName": "name", "vals": [{"value": "Kirschen"}]},
                       {"attributeName": "insteadPriceText", "vals": [{"value": "statt 4.50"}]},
                       …]}

Der CMS-Endpunkt ``/api/headless/content`` liefert dagegen nur Seitenstruktur ohne
Preise; die eigentliche Produktliste kommt im SSR-Payload. Deshalb wird das HTML
geparst und nicht der API-Endpunkt aufgerufen.
"""

from __future__ import annotations

from ..models import Offer
from ..nuxt import NuxtPayload, flatten_attribute_info
from .base import RetailerAdapter, looks_like_wine

#: Kategorie-Labels, die Denner für Wein verwendet.
WINE_CATEGORIES = ("wein", "weine", "schaumwein", "champagne", "spirituosen")


class DennerAdapter(RetailerAdapter):
    key = "denner"

    def parse(self, html: str, url: str) -> list[Offer]:
        payload = NuxtPayload.from_html(html)
        if payload is None:
            return []

        offers: list[Offer] = []
        for raw in payload.find_dicts(required_keys={"sku", "attributeInfo"}):
            product = payload.deref(raw)
            if not isinstance(product, dict):
                continue
            if product.get("itemType") not in (None, "PRODUCT"):
                continue
            attrs = flatten_attribute_info(product)
            name = _text(attrs.get("name"))
            if not name:
                continue

            subline = _text(attrs.get("nameSubline"))
            categories = " ".join(attrs.get("category__labels") or [])
            # Wein erkennen: entweder über die Kategorie oder über den Namen selbst.
            in_wine_category = any(c in categories.lower() for c in WINE_CATEGORIES)
            if not (in_wine_category or looks_like_wine(name, subline)):
                continue
            # Weinspezifisches Attribut als zusätzlicher Beleg.
            if not in_wine_category and "Geschmacksprofil" not in attrs and not looks_like_wine(name, subline):
                continue

            price = attrs.get("priceFormatted") or attrs.get("price") or product.get("price")
            item_url = _text(attrs.get("itemUrl"))
            offers.append(
                self.make_offer(
                    name=name,
                    url=_absolute(item_url),
                    price_text=_text(price),
                    reference_text=_text(attrs.get("insteadPriceText")),
                    # Die Gebindegrösse steht in der Subline ("75 cl", "6 × 75 cl").
                    gebinde_text=subline,
                    article_no=_text(attrs.get("pimcoreId")) or product.get("sku"),
                    source_note=_promo_note(attrs),
                )
            )
        return offers


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return str(value.get("value") or value.get("label") or "")
    if isinstance(value, list):
        return _text(value[0]) if value else ""
    return str(value)


def _absolute(path: str) -> str:
    if not path:
        return ""
    if path.startswith("http"):
        return path
    return "https://www.denner.ch" + (path if path.startswith("/") else "/" + path)


def _promo_note(attrs: dict[str, object]) -> str:
    bits = []
    label = _text(attrs.get("promotionLabel"))
    if label:
        bits.append(label)
    pub = _text(attrs.get("product_publication__labels") or attrs.get("product_publication"))
    if pub:
        bits.append(pub)
    return "; ".join(bits)

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

Kein Filter auf ``itemType``
---------------------------
Früher liess der Adapter nur ``itemType == "PRODUCT"`` durch. Denner hat die
Weinshop-Kacheln inzwischen auf ``CONTENT_3`` umgestellt — damit fiel die gesamte
Seite ``/de/weinshop/wein-aktionen`` durch, 21 Weine, wochenlang unbemerkt, weil der
Lauf brav "ok" meldete: die zwei Positionen von der allgemeinen Aktionsseite genügten,
damit nichts nach Fehler aussah.

Der Wert wird darum nicht nachgepflegt, sondern gar nicht mehr gelesen. Er ist eine
Marketing-Bezeichnung, die Denner jederzeit umbenennen kann, und er hat hier nie
etwas aussortiert: die Auswahl trägt ``find_dicts({"sku", "attributeInfo"})``, und
was Wein ist, entscheidet der Weinfilter darunter. Ein fest verdrahtetes
``"CONTENT_3"`` würde beim nächsten Umbenennen genauso platzen.
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
        gesehen: set[str] = set()
        for raw in payload.find_dicts(required_keys={"sku", "attributeInfo"}):
            product = payload.deref(raw)
            if not isinstance(product, dict):
                continue
            # Jede Kachel steht zweimal im Payload — 42 Objekte für 21 Weine.
            sku = str(product.get("sku") or "")
            if sku and sku in gesehen:
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
            if sku:
                gesehen.add(sku)
            offers.append(
                self.make_offer(
                    name=name,
                    url=_absolute(item_url),
                    price_text=_text(price),
                    reference_text=_text(attrs.get("insteadPriceText")),
                    gebinde_text=_gebinde(attrs) or subline,
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


def _gebinde(attrs: dict[str, object]) -> str:
    """Gebinde aus den harten Feldern statt aus der Anzeigezeile.

    Denner schreibt auf der Aktionsseite den **Kartonpreis** an (29.70) und die
    Flasche nur klein darunter ("Flasche: 4.95 statt 9.95"). Welcher der beiden
    Preise gemeint ist, entscheidet sich am Gebinde — und genau dort war der Fehler:
    ``nameSubline`` lautet hier "Italien, 75 cl" und verschweigt den Faktor 6, den
    dasselbe Objekt in ``box_item_count`` mitliefert. Auf ``/de/aktionen`` steht bei
    demselben Wein "…, 6 x 75 cl". Die Anzeigezeile ist also seitenabhängig, die
    beiden Zahlenfelder sind es nicht.

    Ohne diese Korrektur käme jeder Denner-Wein zum sechsfachen Preis in die Liste —
    ein Scheinsieger mit umgekehrtem Vorzeichen, und schlimmer als eine Lücke.
    """
    karton = _text(attrs.get("box_item_count")).strip()
    groesse = _text(attrs.get("content_size_text")).strip()
    if not groesse:
        return ""
    if karton and karton not in ("", "0", "1"):
        return f"{karton} × {groesse}"
    return groesse


def _promo_note(attrs: dict[str, object]) -> str:
    bits = []
    label = _text(attrs.get("promotionLabel"))
    if label:
        bits.append(label)
    pub = _text(attrs.get("product_publication__labels") or attrs.get("product_publication"))
    if pub:
        bits.append(pub)
    return "; ".join(bits)

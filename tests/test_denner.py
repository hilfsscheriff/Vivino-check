"""Denner — zwei Fehler, die sich gegenseitig gedeckt haben.

Der Adapter liess nur ``itemType == "PRODUCT"`` durch. Denner hat die Weinshop-
Kacheln auf ``CONTENT_3`` umgestellt, womit die gesamte Seite durchfiel: 21 Weine,
wochenlang unbemerkt, weil der Lauf "ok" meldete — die zwei Positionen von der
allgemeinen Aktionsseite genügten, damit nichts nach Fehler aussah.

Und hätte man nur das Gate geöffnet, wären alle 21 zum **sechsfachen Preis** in die
Liste gekommen: Denner schreibt auf dieser Seite den Kartonpreis an, und
``nameSubline`` verschweigt den Faktor 6, den dasselbe Objekt in ``box_item_count``
mitliefert.
"""

import json

import pytest

from winecheck.adapters.denner import DennerAdapter
from winecheck.config import SourceConfig


@pytest.fixture
def adapter():
    # price_basis "auto" wie in sources/retailers.yaml: erst damit teilt die
    # Normalisierung den Kartonpreis überhaupt auf die Flasche herunter.
    cfg = SourceConfig(key="denner", name="Denner", adapter="denner",
                       domain="denner.ch", vat_included=True, price_basis="auto")
    return DennerAdapter(cfg, fetcher=None)


def _attr(name, wert):
    return {"attributeName": name, "vals": [{"value": wert}]}


def _kategorie(*labels):
    """Mehrwertiges Attribut — daran erkennt der Adapter den Wein.

    Der Name allein reicht nicht: "Leopardo Spumante Extra Dry" enthält kein Wort,
    das der Weinfilter kennt. Denner liefert die Warenart in der Kategorie mit.
    """
    return {"attributeName": "category",
            "vals": [{"value": x, "label": x} for x in labels]}


def _html(*produkte):
    """Baut das Minimum, das NuxtPayload.from_html erwartet."""
    return (
        '<html><body><script id="__NUXT_DATA__" type="application/json">'
        + json.dumps(list(produkte))
        + "</script></body></html>"
    )


def _produkt(*, sku="a1", item_type="CONTENT_3", name="Leopardo Spumante Extra Dry",
             subline="Italien, 75 cl", preis="29.70", statt="statt 59.70",
             karton="6", groesse="75 cl"):
    attrs = [
        _kategorie("Getränke", "Wein/Champagner", "Schaumwein", "Italien"),
        _attr("name", name),
        _attr("nameSubline", subline),
        _attr("priceFormatted", preis),
        _attr("insteadPriceText", statt),
        _attr("itemUrl", "/de/produkte/leopardo-spumante"),
    ]
    if karton:
        attrs.append(_attr("box_item_count", karton))
    if groesse:
        attrs.append(_attr("content_size_text", groesse))
    return {"sku": sku, "itemType": item_type, "attributeInfo": attrs}


# -- Das itemType-Gate -----------------------------------------------------
def test_content_kachel_wird_gelesen(adapter):
    """CONTENT_3 statt PRODUCT — daran ist die ganze Weinshop-Seite gescheitert.

    Der Wert wird nicht nachgepflegt, sondern gar nicht mehr gelesen: er ist eine
    Marketing-Bezeichnung, die Denner jederzeit umbenennt, und er hat nie etwas
    aussortiert.
    """
    offers = adapter.parse(_html(_produkt(item_type="CONTENT_3")), "https://www.denner.ch/x")
    assert len(offers) == 1


def test_beliebiger_neuer_itemtype_faellt_nicht_durch(adapter):
    """Beim nächsten Umbenennen soll nicht wieder alles verschwinden."""
    offers = adapter.parse(_html(_produkt(item_type="CONTENT_9")), "https://www.denner.ch/x")
    assert len(offers) == 1


# -- Die Kartonfalle -------------------------------------------------------
def test_kartonpreis_wird_auf_die_flasche_geteilt(adapter):
    """29.70 ist der Karton, 4.95 die Flasche — Denners eigene Zeile lautet
    "Flasche: 4.95 statt 9.95".

    Ohne diese Rechnung stünde jeder Denner-Wein sechsfach zu teuer in der Liste.
    """
    o = adapter.parse(_html(_produkt()), "https://www.denner.ch/x")[0]
    assert o.price_per_bottle_incl_vat == 4.95


def test_gebinde_kommt_aus_den_zahlenfeldern_nicht_aus_der_anzeigezeile(adapter):
    """Die Anzeigezeile ist seitenabhängig, die Zahlenfelder sind es nicht.

    Auf /de/weinshop/wein-aktionen lautet nameSubline "Italien, 75 cl" und
    verschweigt den Faktor 6; auf /de/aktionen steht bei demselben Wein
    "…, 6 x 75 cl". box_item_count trägt beide Male die 6.
    """
    o = adapter.parse(_html(_produkt(subline="Italien, 75 cl")), "https://www.denner.ch/x")[0]
    assert o.price_per_bottle_incl_vat == 4.95


def test_einzelflasche_wird_nicht_geteilt(adapter):
    """box_item_count = 1 ist kein Karton — sonst würde hier durch 1 geteilt und
    die Grössenangabe ginge trotzdem verloren."""
    o = adapter.parse(
        _html(_produkt(karton="1", preis="9.95", statt="statt 12.95")),
        "https://www.denner.ch/x",
    )[0]
    assert o.price_per_bottle_incl_vat == 9.95


def test_ohne_zahlenfelder_gilt_weiter_die_subline(adapter):
    """Rückfall für Seiten, die box_item_count nicht mitliefern."""
    o = adapter.parse(
        _html(_produkt(karton="", groesse="", subline="Italien, 6 x 75 cl")),
        "https://www.denner.ch/x",
    )[0]
    assert o.price_per_bottle_incl_vat == 4.95


# -- Die doppelten Kacheln -------------------------------------------------
def test_jede_kachel_zaehlt_einmal(adapter):
    """Der Payload führt jede Kachel zweimal — 42 Objekte für 21 Weine."""
    offers = adapter.parse(_html(_produkt(sku="a1"), _produkt(sku="a1")), "https://www.denner.ch/x")
    assert len(offers) == 1

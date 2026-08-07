"""Shopware-Weinhändler — ein Adapter, zwei Läden, zwei Fallen.

Selection Schwander und Caratello nutzen dasselbe Shopsystem, schreiben Preise aber
verschieden an. Beide Eigenheiten haben beim Bauen zugeschlagen.
"""

import pytest
from selectolax.parser import HTMLParser

from winecheck.adapters.shopware import ShopwareAdapter


class _Cfg:
    key = "schwander"
    vat_included = True
    price_basis = "bottle"
    private_label_brands: list[str] = []


@pytest.fixture
def adapter():
    return ShopwareAdapter(_Cfg(), fetcher=None)


def _box(html):
    return HTMLParser(f'<div class="product-box">{html}</div>').css_first("div.product-box")


def test_schwander_order_current_then_statt(adapter):
    o = adapter._parse_box(_box(
        '<a class="product-name" href="https://x/barolo-2019">Barolo Bricco Visette</a>'
        '<div class="product-description">Attilio Ghisolfi</div>'
        '<div class="product-price">CHF 39.80 statt CHF 45.00</div>'
    ))
    assert o is not None
    assert o.price_per_bottle_incl_vat == pytest.approx(39.80)
    assert o.reference_price == pytest.approx(45.00)
    assert "Attilio Ghisolfi" in o.name, "der Produzent steht in der Beschreibung, nicht im Namen"


def test_caratello_order_statt_then_current(adapter):
    """Caratello dreht die Reihenfolge: „statt CHF 215.00 CHF 189.00". Wer den ersten
    Preis nimmt, verkauft den alten als Aktionspreis."""
    o = adapter._parse_box(_box(
        '<a class="product-name" href="https://x/w">Arte Langhe Rosso DOC 2022</a>'
        ' statt CHF 39.50 CHF 32.50 Flasche'
    ))
    assert o is not None
    assert o.price_per_bottle_incl_vat == pytest.approx(32.50)
    assert o.reference_price == pytest.approx(39.50)


def test_volume_from_the_tile_not_the_name(adapter):
    """Caratello schreibt das Volumen neben den Namen, nicht hinein — bei keiner der
    70 Positionen stand es im Namen. Ohne diese Angabe geht eine Magnum als
    75-cl-Flasche durch und landet zum halben Literpreis in der Rangliste."""
    o = adapter._parse_box(_box(
        '<a class="product-name" href="https://x/w">Azelia Barolo Cerretta</a>'
        ' , 150 cl statt CHF 200.00 CHF 164.00'
    ))
    assert o is not None
    assert o.price_per_bottle_incl_vat == pytest.approx(82.0, abs=0.05)


def test_full_price_items_are_skipped(adapter):
    """Vollsortimenter führen hunderte Weine. Ohne Streichpreis ist es Regalware und
    gehört nicht in einen Aktionsvergleich."""
    assert adapter._parse_box(_box(
        '<a class="product-name" href="https://x/w">Irgendein Barolo</a>'
        '<div class="product-price">CHF 39.80</div>'
    )) is None


def test_no_discount_is_not_a_discount(adapter):
    """Gleicher oder höherer Preis als der Streichpreis: kein Abschlag, also raus —
    lieber weglassen als 0 % oder einen negativen Rabatt ausweisen."""
    assert adapter._parse_box(_box(
        '<a class="product-name" href="https://x/w">Barolo</a>'
        '<div class="product-price">CHF 45.00 statt CHF 45.00</div>'
    )) is None

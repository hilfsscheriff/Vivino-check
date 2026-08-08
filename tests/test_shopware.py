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
    #: Schwander und Caratello führen nicht nur Wein — die Vorfilterung verlangt
    #: hier weiterhin ein Weinwort im Namen. Vino Vintana steht auf ``true``.
    wine_only = False


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


# --------------------------------------------------------------- Vino Vintana
# Derselbe Adapter, drittes Shopware-Kleid: Streichpreis als eigenes Element statt
# als Wort "statt", Währung hinter der Zahl, Beschreibungsfeld voller Werbetext.
class _CfgVintana(_Cfg):
    key = "vinovintana"
    wine_only = True


@pytest.fixture
def vintana():
    return ShopwareAdapter(_CfgVintana(), fetcher=None)


_VINTANA_PREIS = (
    '<div class="product-price-info">'
    '  <span class="product-price with-list-price">6,50 CHF*'
    '    <span class="list-price"><span class="list-price-price">7,50 CHF*</span>'
    '    <span class="list-price-percentage">(13.33%)</span></span>'
    '  </span>'
    '  <p class="product-price-unit">Inhalt: <span class="price-unit-content">0.75 Liter</span>'
    '  <span class="price-unit-reference">(10,00 CHF* / 1 Liter)</span></p>'
    '</div>'
)


def test_streichpreis_aus_list_price_ohne_das_wort_statt(vintana):
    """Shopware 6 schreibt den Referenzpreis in ein eigenes Element.

    Der Adapter suchte nur nach "statt" und fand bei diesem Laden null Angebote.
    """
    o = vintana._parse_box(_box(
        '<div class="product-name">La Bollina Monferrato Beneficio DOC 2024 - 0.75l</div>'
        + _VINTANA_PREIS
    ))
    assert o.price_raw == 6.50
    assert o.reference_price == 7.50


def test_werbetext_wird_nicht_an_den_namen_gehaengt(vintana):
    """Dasselbe Feld trägt hier Prosa statt des Produzenten.

    Angehängt ergäbe das eine Vivino-Abfrage über einen halben Absatz.
    """
    o = vintana._parse_box(_box(
        '<div class="product-name">Tramin Pinot Grigio DOC 2025 - 0.75l</div>'
        '<div class="product-description">Aus Italien stammt dieser Wein der Casa '
        'Vinicola Caldirola, einem traditionsreichen Haus mit langer Geschichte.</div>'
        + _VINTANA_PREIS
    ))
    assert o.name == "Tramin Pinot Grigio DOC 2025 - 0.75l"


def test_kurzer_produzent_wird_weiterhin_angehaengt(vintana):
    """Die Unterscheidung darf Schwander nicht kaputt machen."""
    o = vintana._parse_box(_box(
        '<div class="product-name">Murua Rioja Reserva 2017</div>'
        '<div class="product-description">Bodegas Murua</div>'
        + _VINTANA_PREIS
    ))
    assert o.name == "Murua Rioja Reserva 2017"


def test_volumen_aus_dem_eigenen_feld_nicht_aus_der_kachel(vintana):
    """Der Kacheltext nennt zwei Volumen: 0.75 Liter und "(10,00 CHF* / 1 Liter)".

    Uneindeutig heisst price_confidence=low — damit fiel jeder Wein dieses Ladens
    aus der Rangliste, obwohl seine Grösse sauber angeschrieben war.
    """
    o = vintana._parse_box(_box(
        '<div class="product-name">Tramin Pinot Grigio DOC 2025 - 0.75l</div>' + _VINTANA_PREIS
    ))
    assert o.bottle_ml == 750
    assert o.price_confidence.value == "high"


def test_letzter_jahrgang_gewinnt(vintana):
    """"Since 1974" ist ein Markenname, kein Jahrgang.

    Mit dem ersten Treffer wurde aus einem 2025er ein einundfünfzig Jahre alter
    Prosecco — mit entsprechend absurder Trinkreife.
    """
    o = vintana._parse_box(_box(
        '<div class="product-name">Since 1974 Prosecco Superiore Conegliano '
        'Valdobbiadene DOCG Millesimato Dry 2025 - 0.75l</div>' + _VINTANA_PREIS
    ))
    assert o.vintage == 2025

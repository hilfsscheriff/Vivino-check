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


# -- Die vorangestellte Anbauregion ----------------------------------------
def test_die_region_verlaesst_den_namen():
    """Caratello stellt jedem Wein seine Region voran — für Vivino ist das Gift.

    Aus "Toscana Montepulciano – Avignonesi IL Marzocco Cortona DOC/bc" wurde die
    Abfrage "toscana montepulciano avignonesi marzocco cortona bc", und die beiden
    Ortsnamen zogen die Suche auf "Avignonesi 50 & 50" — einen anderen Wein
    desselben Guts, rot statt weiss, CHF 94 statt CHF 28.60. Weil der Fehltreffer
    ein Roter ist, stand der Chardonnay bei uns als Rotwein in der Liste.
    """
    from winecheck.adapters.shopware import _ohne_herkunft
    name, region = _ohne_herkunft("Toscana Montepulciano – Avignonesi IL Marzocco Cortona DOC/bc")
    assert name == "Avignonesi IL Marzocco Cortona DOC/bc"
    assert region == "Toscana Montepulciano"


def test_ohne_gedankenstrich_bleibt_alles_stehen():
    from winecheck.adapters.shopware import _ohne_herkunft
    assert _ohne_herkunft("Vietti Barolo Brunate DOCG") == ("Vietti Barolo Brunate DOCG", "")


def test_ein_langer_vorderteil_ist_keine_region():
    """Vier Wörter sind die Grenze. Was länger ist, ist kein Ortsname."""
    from winecheck.adapters.shopware import _ohne_herkunft
    lang = "Ein sehr langer Name mit Gedankenstrich – Rosso Toscana IGT"
    assert _ohne_herkunft(lang) == (lang, "")


def test_ein_kurzer_hinterteil_wird_nicht_abgetrennt():
    """Die Regel darf nie den Weinnamen wegwerfen und die Warengruppe behalten.

    Das ist kein theoretischer Fall: "Café de Paris Ice – Schaumwein, Frankreich
    (0.75l)" würde bei einer allgemeinen Fassung zu "Schaumwein, Frankreich". Dieser
    Wein kommt über einen anderen Adapter herein, aber die Regel muss auch hier
    standhalten.
    """
    from winecheck.adapters.shopware import _ohne_herkunft
    assert _ohne_herkunft("Château X – Rosso IGT") == ("Château X – Rosso IGT", "")


def test_das_bio_kuerzel_faellt_weg():
    """"/bc" ist Caratellos Bio-Vermerk, kein Namensbestandteil — als "bc" landete
    er bisher im Suchbegriff."""
    from winecheck.adapters.shopware import _RE_BIOCODE
    assert _RE_BIOCODE.sub("", "Avignonesi IL Marzocco Cortona DOC/bc") == "Avignonesi IL Marzocco Cortona DOC"
    assert _RE_BIOCODE.sub("", "Rosso Toscana IGT/b") == "Rosso Toscana IGT"
    assert _RE_BIOCODE.sub("", "Barolo DOCG") == "Barolo DOCG"

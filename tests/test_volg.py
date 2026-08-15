"""Volg — der Karton ist hier eine Falle nach unten.

In der Beschreibung stehen Kartonpreise (63.00 statt 87.00), im Preisblock daneben
die Flasche (10.50 statt 14.50). Beides sind echte Zahlen desselben Angebots, und
sie unterscheiden sich um den Faktor 6.

Käme der ganze Kacheltext in die Gebinde-Erkennung, fände sie „Karton à 6 Flaschen",
teilte den ohnehin richtigen Flaschenpreis noch einmal durch sechs, und Volg stünde
mit CHF 1.75 an der Spitze jeder Rangliste.
"""

import pytest

from winecheck.adapters.volg import VolgAdapter
from winecheck.config import SourceConfig


@pytest.fixture
def adapter():
    cfg = SourceConfig(key="volg", name="Volg", adapter="volg", domain="volg.ch",
                       vat_included=True, price_basis="bottle", wine_only=True)
    return VolgAdapter(cfg, fetcher=None)


def _kachel(*, name="G Cuvée Rosé Prestige", zusatz="Schweiz 2025",
            flasche="10.50", statt="statt 14.50 / Flasche",
            beschreibung="<strong>Bestelleinheit:</strong> Karton à 6 Flaschen (75cl) "
                         "nur CHF 63.00 statt CHF 87.00",
            href="/weinshop/detail/?tx_kochwine_wineshow%5Bwine%5D=461"):
    return (
        '<html><body><div class="c-product">'
        f'<a href="{href}"><h3 class="c-product__title">{name}'
        + (f"<p>{zusatz}</p>" if zusatz else "")
        + "</h3></a>"
        f'<div class="c-product__meta"><div class="c-product__description">{beschreibung}</div>'
        f'<div class="c-product__price"><span class="c-product__price-main">{flasche}</span>'
        f'<span class="u-text-nowrap">{statt}</span></div></div>'
        "</div></body></html>"
    )


def _eins(adapter, html):
    offers = adapter.parse(html, "https://www.volg.ch/weinshop/")
    assert len(offers) == 1
    return offers[0]


# -- Die Kartonfalle -------------------------------------------------------
def test_der_flaschenpreis_wird_nicht_noch_einmal_geteilt(adapter):
    """10.50 ist bereits die Flasche. 63.00 wäre der Karton, 1.75 wäre Unsinn."""
    o = _eins(adapter, _kachel())
    assert o.price_per_bottle_incl_vat == 10.50


def test_der_streichpreis_kommt_aus_dem_preisblock_nicht_aus_der_beschreibung(adapter):
    """In der Beschreibung steht "statt CHF 87.00" — das ist der Karton.

    Würde der genommen, wiese Volg 88 % Ersparnis aus statt 28 %.
    """
    o = _eins(adapter, _kachel())
    assert o.reference_price == 14.50


def test_die_groesse_kommt_ohne_den_kartonfaktor(adapter):
    """Aus "Karton à 6 Flaschen (75cl)" wird "75 cl" — die 6 bleibt draussen."""
    o = _eins(adapter, _kachel())
    assert o.bottle_ml == 750
    assert o.price_confidence.value == "high"


# -- Name und Jahrgang -----------------------------------------------------
def test_die_herkunft_bleibt_aus_dem_namen(adapter):
    """Der Zusatz "Schweiz 2025" steht als <p> im Titel und trägt den Jahrgang.

    Im Namen hätte er nichts verloren: "G Cuvée Prestige Schweiz 2024" als
    Suchbegriff verwässert den Vivino-Abgleich.
    """
    o = _eins(adapter, _kachel())
    assert o.name == "G Cuvée Rosé Prestige"
    assert o.vintage == 2025


def test_ohne_jahrgang_wird_keiner_geraten(adapter):
    o = _eins(adapter, _kachel(zusatz="Schweiz"))
    assert o.vintage is None


# -- Die Grenze zur Regalware ----------------------------------------------
def test_ohne_streichpreis_kein_angebot(adapter):
    """Dieselbe Grenze wie bei allen Läden: ohne Referenzpreis lässt sich Aktion
    nicht von Sortiment unterscheiden."""
    assert adapter.parse(_kachel(statt=""), "https://www.volg.ch/weinshop/") == []


def test_kein_abschlag_kein_angebot(adapter):
    assert adapter.parse(
        _kachel(flasche="14.50", statt="statt 14.50 / Flasche"),
        "https://www.volg.ch/weinshop/",
    ) == []


# -- Die Adresse -----------------------------------------------------------
def test_die_adresse_wird_absolut(adapter):
    """Volg verlinkt relativ; unverändert übernommen löst der Browser gegen die
    Adresse der Berichtsseite auf — daraus wurden bei anderen Läden tote Links."""
    o = _eins(adapter, _kachel())
    assert o.url.startswith("https://www.volg.ch/weinshop/detail/")

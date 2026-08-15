"""Flaschenpost — gelesen über die öffentliche Produkt-API statt über die Webseite.

Die Webseite liegt hinter Cloudflare. Die API ist es nicht, und das wurde geprüft
statt angenommen: dieselbe Anfrage mit ehrlichem Projekt-User-Agent, ganz ohne
User-Agent und als Chrome lieferte dreimal byteidentisch dieselbe Antwort.
"""

import pytest

from winecheck.adapters.flaschenpost import FlaschenpostAdapter, _de
from winecheck.config import SourceConfig


@pytest.fixture
def adapter():
    cfg = SourceConfig(key="flaschenpost", name="Flaschenpost", adapter="flaschenpost",
                       domain="flaschenpost.ch", wine_only=True)
    return FlaschenpostAdapter(cfg, fetcher=None)


def _produkt(*, aktion=1050, referenz=1395, liter=14.0, groesse=7500,
             name="Negromaro Salento IGP", produzent="Poggio Marù"):
    preis = {"initialPrice": {"amount": referenz, "currency": "CHF"}}
    if aktion is not None:
        preis["discountPrice"] = {"amount": aktion, "currency": "CHF"}
    if liter is not None:
        preis["literPrice"] = {"amount": liter, "currency": "CHF"}
    return {
        "name": {"de-CH": name, "fr-CH": "…"},
        "productTypeName": "wines",
        "masterVariant": {
            "sku": "1203292",
            "url": "negromaro-salento-igp_poggio-maru?_size=7500",
            "price": preis,
            "attributes": {
                "producer": {"key": "abc", "label": produzent},
                "bottleSize": groesse,
                "salesUnit": 1,
            },
        },
    }


# -- Die drei Formen der Sprachfelder --------------------------------------
def test_deutsche_texte_aus_drei_verschiedenen_formen():
    """Die Schnittstelle mischt flache Sprach-Maps, label-Maps und label-Strings."""
    assert _de({"de-CH": "Merlot", "en": "Merlot"}) == "Merlot"
    assert _de({"key": "0", "label": {"de-CH": "Keine", "en": "None"}}) == "Keine"
    assert _de({"key": "abc", "label": "Poggio Marù"}) == "Poggio Marù"
    assert _de(None) == ""


# -- Aktion gegen Regalware ------------------------------------------------
def test_wein_mit_streichpreis_wird_uebernommen(adapter):
    o = adapter._offer(_produkt())
    assert o.price_per_bottle_incl_vat == 10.50
    assert o.reference_price == 13.95
    assert o.bottle_ml == 750
    assert o.price_confidence.value == "high"


def test_ohne_aktionspreis_kein_angebot(adapter):
    """Ohne discountPrice ist es Sortiment, keine Aktion — das ist die Grenze,
    an der sich in diesem Projekt beides scheidet."""
    assert adapter._offer(_produkt(aktion=None)) is None


def test_kein_abschlag_kein_angebot(adapter):
    """Gleicher oder höherer Preis als der Streichpreis: lieber weglassen als
    einen Rabatt von 0 % oder einen negativen auszuweisen."""
    assert adapter._offer(_produkt(aktion=1395, referenz=1395)) is None
    assert adapter._offer(_produkt(aktion=1500, referenz=1395)) is None


# -- Die Gegenprobe über den Literpreis ------------------------------------
def test_literpreis_bestaetigt_die_flaschengroesse(adapter):
    """10.50 CHF ÷ 14.00 CHF/Liter ergibt exakt 0.750 Liter."""
    o = adapter._offer(_produkt(aktion=1050, liter=14.0, groesse=7500))
    assert o.bottle_ml == 750


def test_widerspruechlicher_literpreis_verwirft_die_groesse(adapter):
    """Passt der Literpreis nicht zur Grösse, ist eine der beiden Angaben falsch.

    Dann wird verworfen statt geraten: ein falsch umgerechneter Literpreis erzeugt
    einen Scheinsieger in der Rangliste.
    """
    o = adapter._offer(_produkt(aktion=1050, liter=99.0, groesse=7500))
    assert o.price_confidence.value != "high"


def test_ohne_literpreis_wird_nicht_widersprochen(adapter):
    """Die Prüfung soll Fehler finden, nicht Weine ohne Zusatzangabe aussortieren."""
    o = adapter._offer(_produkt(liter=None))
    assert o.bottle_ml == 750


def test_magnum_wird_erkannt(adapter):
    """bottleSize kommt in Zehntel-Millilitern: 15000 sind 1.5 Liter."""
    o = adapter._offer(_produkt(aktion=6000, referenz=9000, liter=40.0, groesse=15000))
    assert o.bottle_ml == 1500
    assert o.price_per_bottle_incl_vat == 30.00


# -- Name und Produzent ----------------------------------------------------
def test_produzent_wird_angehaengt(adapter):
    """Für Vivino ist der Produzent das wichtigste Wort und steht nie im Namen."""
    o = adapter._offer(_produkt())
    assert o.name == "Negromaro Salento IGP Poggio Marù"


def test_ohne_jahrgang_wird_keiner_geraten(adapter):
    """Die Schnittstelle nennt den Jahrgang nirgends — weder als Attribut, noch in
    der Adresse, noch im Namen. Die Varianten unterscheiden sich zwar in SKU und
    Preis, bleiben aber unbeschriftet. Lieber die Lücke als eine erfundene Zahl.
    """
    o = adapter._offer(_produkt())
    assert o.vintage is None


def test_die_adresse_wird_absolut(adapter):
    o = adapter._offer(_produkt())
    assert o.url.startswith("https://www.flaschenpost.ch/negromaro")

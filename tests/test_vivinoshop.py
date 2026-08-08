"""Vivinos eigene Aktionen — die Quelle, die ihre Note mitbringt.

Zwei Dinge müssen stimmen: die Preisbasis (nur die 0,75-l-Flasche) und die
Trennung von den Schweizer Händlern.
"""

import pytest

from winecheck.adapters.vivinoshop import VivinoShopAdapter, _name
from winecheck.config import SourceConfig
from winecheck.report.site import _add_value_scores


@pytest.fixture
def adapter():
    cfg = SourceConfig(key="vivinoshop", name="Vivino Aktionen",
                       adapter="vivinoshop", domain="vivino.com", wine_only=True)
    return VivinoShopAdapter(cfg, fetcher=None)


def _treffer(*, betrag=10.0, vorher=20.0, flasche=1, note=4.2, jahr=2020):
    return {
        "vintage": {
            "id": 111, "year": jahr,
            "wine": {"id": 222, "name": "Rioja Reserva", "type_id": 1,
                     "winery": {"name": "Imperial"}},
            "statistics": {"ratings_average": note, "ratings_count": 900},
        },
        "price": {"id": 333, "amount": betrag, "discounted_from": vorher,
                  "bottle_type": {"id": flasche, "name": "Flasche (0,75 l)"},
                  "sku": "VI-1-CS"},
    }


def test_weingut_kommt_vor_den_weinnamen():
    """Vivino trennt Weingut und Wein; nur der Weinname ergäbe "Rioja Reserva"."""
    assert _name(_treffer()) == "Imperial Rioja Reserva"


def test_normale_flasche_wird_uebernommen(adapter):
    o = adapter._offer(_treffer())
    assert o.price_per_bottle_incl_vat == 10.0
    assert o.reference_price == 20.0
    assert o.bottle_ml == 750
    assert o.price_confidence.value == "high"


@pytest.mark.parametrize("flasche", [2, 3, 5])
def test_andere_gebinde_werden_uebersprungen(adapter, flasche):
    """Magnum, Halbflasche, Karton: die Antwort sagt nicht, wie viele Flaschen
    darin stecken. Ein geratener Literpreis erzeugt einen Scheinsieger."""
    assert adapter._offer(_treffer(flasche=flasche)) is None


def test_ohne_abschlag_kein_angebot(adapter):
    assert adapter._offer(_treffer(betrag=20.0, vorher=20.0)) is None
    assert adapter._offer(_treffer(betrag=25.0, vorher=20.0)) is None


def test_note_wird_zum_saeen_gesammelt(adapter):
    adapter._offer(_treffer(note=4.4))
    assert adapter.bewertungen == [{
        "name": "Imperial Rioja Reserva", "vintage": 2020, "wine_id": 222,
        "rating": 4.4, "rating_count": 900,
        "url": "https://www.vivino.com/w/222",
        # Die Farbe muss mit. Ohne sie fielen 400 Weine auf "unbekannt" zurück,
        # weil Namen wie "Astrale Special Edition" kein Farbwort enthalten.
        "wine_type_id": 1,
    }]


# -- Trennung der beiden Warenwelten ---------------------------------------
def _wein(preis, note, **kw):
    return {"price": preis, "rating": note, "ratingCount": 500, **kw}


def test_wein_in_beiden_welten_wird_im_schweizer_niveau_gerechnet():
    """"10 Vendemmie Tenuta Ulisse" verkaufen Schubi und Vivino.

    Mit einem Entweder-oder-Kennzeichen verschwand er aus der Schweizer Ansicht,
    obwohl er dort zu kaufen ist.
    """
    beide = _wein(30.0, 4.4, marketplace=True, swiss=True)
    wines = [_wein(10.0 + i, 3.5 + i * 0.05, swiss=True) for i in range(14)] + [beide]
    _add_value_scores(wines)
    # Er wurde gerechnet, also lag er in einer Gruppe — und zwar in der Schweizer,
    # denn die Marktplatz-Gruppe wäre mit einem einzigen Wein zu klein gewesen.
    assert "valueScore" in beide


def test_die_beiden_gruppen_werden_nicht_vermischt():
    """Getrennte Regressionen: der Marktplatz liefert aus dem Ausland, der
    Schweizer Handel nicht. Eine gemeinsame Kurve machte den systematischen
    Preisunterschied zu einer Aussage über die einzelnen Weine."""
    handel = [_wein(10.0 + i, 3.5, swiss=True) for i in range(14)]
    markt = [_wein(100.0 + i, 4.5, marketplace=True) for i in range(14)]
    _add_value_scores(handel + markt)
    # Innerhalb jeder Gruppe sind alle Noten gleich, also liegt niemand über der
    # Erwartung. Gemeinsam gerechnet stünden die teuren Marktplatzweine weit oben.
    assert all(abs(w.get("valueScore", 0)) < 0.2 for w in handel + markt)

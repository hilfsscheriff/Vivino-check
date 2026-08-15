"""Flaschenpost — die Quelle, die sauber aussah und keine gültige Aktion enthielt.

Die Schnittstelle ist offen und gut strukturiert. Sie führt aber ausschliesslich
ausgelistete Ware: über 6000 geprüfte Produkte war keines ``published``, keines
``active``, keines lieferbar, und alle 20 stichprobenweise geöffneten Produktseiten
antworteten mit 404 (Gegenprobe mit einem lebenden Wein des Ladens: 200).

Diese Tests halten beides fest — dass der Lesecode stimmt, und dass er trotzdem
nichts ausliefert, solange die Quelle tot ist.
"""

import json

import pytest

from winecheck.adapters.flaschenpost import (
    PRO_SEITE,
    PROBE_SEITEN,
    FlaschenpostAdapter,
    _de,
)
from winecheck.config import SourceConfig


@pytest.fixture
def adapter():
    cfg = SourceConfig(key="flaschenpost", name="Flaschenpost", adapter="flaschenpost",
                       domain="flaschenpost.ch", wine_only=True)
    return FlaschenpostAdapter(cfg, fetcher=None)


def _produkt(*, aktion=1050, referenz=1395, liter=14.0, groesse=7500,
             name="Negromaro Salento IGP", produzent="Poggio Marù",
             published=True, active=True):
    preis = {"initialPrice": {"amount": referenz, "currency": "CHF"}}
    if aktion is not None:
        preis["discountPrice"] = {"amount": aktion, "currency": "CHF"}
    if liter is not None:
        preis["literPrice"] = {"amount": liter, "currency": "CHF"}
    return {
        "name": {"de-CH": name, "fr-CH": "…"},
        "slug": {"de-CH": "negromaro-salento-igp_poggio-maru"},
        "productTypeName": "wines",
        "masterVariant": {
            "sku": "1203292",
            "url": "negromaro-salento-igp_poggio-maru?_size=7500",
            "published": published,
            "active": active,
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


# -- Die Adresse -----------------------------------------------------------
def test_die_adresse_traegt_sprachpraefix_und_keinen_query_string(adapter):
    """Zwei Fehler in einer Adresse, beide am lebenden Laden nachgemessen.

    Das url-Feld der Schnittstelle liefert ``<slug>?_size=7500``. Ohne ``/de/``
    antwortet die Webseite mit 404; und ``_size`` trägt dort die interne
    Zehntel-Milliliter-Zahl, wo die Seite Milliliter erwartet.

    Gegenprobe an einem Wein, den der Laden aktuell führt: ``/de/<slug>`` liefert
    200, ``/<slug>`` und ``/<slug>?_size=750`` liefern 404.
    """
    o = adapter._offer(_produkt())
    assert o.url == "https://www.flaschenpost.ch/de/negromaro-salento-igp_poggio-maru"
    assert "?" not in o.url


# -- Ausgelistete Ware -----------------------------------------------------
def test_unpubliziertes_produkt_wird_uebersprungen(adapter):
    """Die Prüfung, die von Anfang an gefehlt hat.

    Ohne sie kamen 477 Positionen in den Bestand, deren Seiten allesamt 404
    lieferten und deren "Aktionspreise" aus der Vergangenheit stammten. Ein
    Phantomangebot mit totem Link ist schlechter als eine Lücke.
    """
    assert adapter._offer(_produkt(published=False)) is None
    assert adapter._offer(_produkt(active=False)) is None
    assert adapter._offer(_produkt(published=False, active=False)) is None


class _StubFetcher:
    """Liefert immer dieselbe Seite — genug, um den Abbruch zu prüfen."""

    def __init__(self, produkte):
        self.payload = json.dumps({"results": produkte})
        self.aufrufe = 0

    def get(self, url, params=None, expect_json=False):
        self.aufrufe += 1
        return type("Res", (), {"ok": True, "status_code": 200, "text": self.payload})()


def test_tote_quelle_meldet_blockiert_statt_leer(adapter):
    """"Leer" hiesse: diese Woche keine Aktionen. Das wäre eine andere Aussage.

    Die Quelle ist nicht aktionsfrei, sie ist unbrauchbar — und das gehört so in der
    Übersicht zu stehen, neben Coop und Migros, statt als unauffällige Null.
    """
    adapter.fetcher = _StubFetcher([_produkt(published=False, active=False)] * 5)
    bericht = adapter.fetch()
    assert bericht.status == "blocked"
    assert "ausgelistete" in bericht.message
    assert not bericht.offers


def test_der_abbruch_kommt_frueh(adapter):
    """Nach PROBE_SEITEN ist Schluss — nicht nach 65.

    Sechs Sekunden Nachprüfen pro Woche sind der Preis dafür, dass die Quelle sich
    von selbst wieder füllt, falls der Laden den Pfad je auf lebendes Sortiment
    umstellt. Zwei Minuten wären es nicht wert.
    """
    # Volle Seiten, sonst endet die Blätterung schon nach der ersten und der
    # Abbruch, um den es hier geht, käme gar nicht zum Zug.
    fetcher = _StubFetcher([_produkt(published=False, active=False)] * PRO_SEITE)
    adapter.fetcher = fetcher
    adapter.fetch()
    assert fetcher.aufrufe == PROBE_SEITEN


def test_lebende_ware_kaeme_durch(adapter):
    """Der Lesecode bleibt scharf: sobald ein Produkt publiziert ist, greift er.

    Sonst wäre nicht unterscheidbar, ob die Quelle tot ist oder der Adapter kaputt.
    """
    fetcher = _StubFetcher([_produkt(), _produkt(published=False)])
    adapter.fetcher = fetcher
    bericht = adapter.fetch()
    assert bericht.status == "ok"
    assert len(bericht.offers) == 1
    assert bericht.offers[0].price_per_bottle_incl_vat == 10.50

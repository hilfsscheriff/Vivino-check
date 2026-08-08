"""Schubi Weine — zwei Fallen, die beim Bauen zugeschlagen haben.

Erstens die irreführenden Klassennamen: ``productdetail__price-norm`` trägt den
Aktionspreis, ``product__price-action`` den Streichpreis. Zweitens die
Weinerkennung, die bei einem reinen Weinhändler fünf von zwölf Aktionen wegwarf.
"""

import pytest
from selectolax.parser import HTMLParser

from winecheck.adapters.schubi import SchubiAdapter


class _Cfg:
    key = "schubi"
    vat_included = True
    price_basis = "bottle"
    private_label_brands: list[str] = []
    wine_only = True


@pytest.fixture
def adapter():
    return SchubiAdapter(_Cfg(), fetcher=None)


def _kachel(inhalt: str):
    return HTMLParser(
        f'<div class="productoverview__item">{inhalt}</div>'
    ).css_first("div.productoverview__item")


def _preisblock(aktuell: str, statt: str) -> str:
    return (
        f'<div class="product__price">'
        f'<span class="productdetail__price-norm">CHF {aktuell}</span>'
        f'<span class="product__price-action">statt CHF {statt}</span>'
        f'</div>'
    )


def test_aktionspreis_ist_der_kleinere_betrag(adapter):
    """Nicht der Klasse vertrauen, sondern dem Betrag.

    ``price-norm`` klingt nach Normalpreis, trägt aber die Aktion. Gelesen wird
    darum min/max — das bleibt richtig, auch wenn der Laden die Namen geraderückt.
    """
    o = adapter._parse_box(_kachel(
        '<a class="product__title" href="/aagne-2025.html">Aagne Pinot Noir AOC 2025</a>'
        '<span class="product__vintage">2025</span>'
        '<div class="product__producer">Weingut Aagne</div>'
        '<span class="product__bottle-size">75 cl</span>'
        + _preisblock("28.50", "39.00")
    ))
    assert o.price_raw == 28.50
    assert o.reference_price == 39.00


def test_produzent_wird_angehaengt(adapter):
    """Für Vivino ist der Produzent das wichtigste Wort; im Titel fehlt er oft."""
    o = adapter._parse_box(_kachel(
        '<a class="product__title" href="/aalto.html">Aalto 2023</a>'
        '<div class="product__producer">Bodegas Aalto</div>'
        '<span class="product__bottle-size">75 cl</span>'
        + _preisblock("49.00", "59.00")
    ))
    # "Aalto" steckt schon im Namen — nur "Bodegas" käme dazu, und das unterscheidet
    # nichts. Der Name bleibt darum unverändert.
    assert o.name == "Aalto 2023"


def test_fremder_produzent_kommt_dazu(adapter):
    o = adapter._parse_box(_kachel(
        '<a class="product__title" href="/x.html">Il Bruciato Bolgheri DOC 2022</a>'
        '<div class="product__producer">Tenuta Guado al Tasso</div>'
        '<span class="product__bottle-size">75 cl</span>'
        + _preisblock("22.50", "29.00")
    ))
    assert o.name == "Il Bruciato Bolgheri DOC 2022 Tenuta Guado al Tasso"


def test_wein_ohne_weinwort_bleibt_drin(adapter):
    """Der Grund für ``wine_only``.

    "Aalto 2023" enthält kein einziges Weinwort. Die allgemeine Vorfilterung warf
    ihn samt vier weiteren Aktionen weg — bei einem Laden, der ausschliesslich Wein
    verkauft.
    """
    o = adapter._parse_box(_kachel(
        '<a class="product__title" href="/aalto.html">Aalto 2023</a>'
        '<div class="product__producer">Bodegas Aalto</div>'
        '<span class="product__bottle-size">75 cl</span>'
        + _preisblock("49.00", "59.00")
    ))
    assert o is not None


def test_kein_wein_fliegt_trotzdem_raus(adapter):
    """``wine_only`` hebt den Schutz nicht auf, es dreht nur die Beweislast um."""
    for name in ("Riedel Weinglas 2er-Set", "Alkoholfreier Sekt Alternative"):
        o = adapter._parse_box(_kachel(
            f'<a class="product__title" href="/x.html">{name}</a>'
            '<span class="product__bottle-size">75 cl</span>'
            + _preisblock("19.00", "29.00")
        ))
        assert o is None, name


def test_magnum_wird_erkannt(adapter):
    """Ohne die Flaschengrösse landete eine 150-cl-Flasche zum halben Literpreis
    in der Rangliste."""
    o = adapter._parse_box(_kachel(
        '<a class="product__title" href="/x.html">Barolo DOCG 2019 Magnum</a>'
        '<div class="product__producer">Marchesi</div>'
        '<span class="product__bottle-size">150 cl</span>'
        + _preisblock("120.00", "150.00")
    ))
    assert o.bottle_ml == 1500
    assert o.price_per_bottle_incl_vat == 60.00


def test_ohne_streichpreis_kein_angebot(adapter):
    o = adapter._parse_box(_kachel(
        '<a class="product__title" href="/x.html">Chianti DOCG 2022</a>'
        '<span class="product__bottle-size">75 cl</span>'
        '<div class="product__price">'
        '<span class="productdetail__price-norm">CHF 18.50</span></div>'
    ))
    assert o is None


def test_mehrwegglas_ist_kein_trinkglas():
    """Die Pfandflasche darf nicht als Zubehör durchgehen.

    Vier Weine der Zürcher Genossenschaft heissen "…, Mehrwegglas, 50 cl". Die
    Endungsregel gegen "Weinglas" hätte sie stillschweigend entfernt.
    """
    from winecheck.adapters.base import kein_wein

    assert not kein_wein("Zürcher Cuvée weiss AOC, Mehrwegglas, 50 cl")
    assert not kein_wein("Herbstgold Rosé VdP Mehrwegglas, 50 cl")
    assert kein_wein("Riedel Weinglas 2er-Set")
    assert kein_wein("Rotweingläser 6er-Pack")

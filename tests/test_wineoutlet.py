"""Wine-Outlet — der Laden rechnet den Literpreis selbst, aber anders als erwartet.

Die Gegenprobe gegen den angeschriebenen Literpreis ist die Besonderheit dieses
Adapters. Sie war in der ersten Fassung falsch herum gedacht und warf bei *jedem*
reduzierten Wein die Gebindeangabe weg, die sie bestätigen sollte.
"""

import pytest
from selectolax.parser import HTMLParser

from winecheck.adapters.wineoutlet import WineOutletAdapter, _produzent


class _Cfg:
    key = "wineoutlet"
    vat_included = True
    price_basis = "bottle"
    private_label_brands: list[str] = []
    wine_only = True


@pytest.fixture
def adapter():
    return WineOutletAdapter(_Cfg(), fetcher=None)


def _kachel(name, desc, preis, statt=None, liter=None, jahr=None):
    teile = [f'<a class="product-name-section" href="/x_1"><div class="product-name">{name}</div></a>']
    if jahr:
        teile.append(f'<div class="product-year">{jahr}</div>')
    teile.append(f'<a class="product-desc-section">{desc}</a>')
    teile.append(f'<div class="product-price">{preis}</div>')
    if statt:
        teile.append(f'<div class="product-instead-price">statt CHF {statt}</div>')
    if liter:
        teile.append(f'<div class="product-liter-price">(CHF {liter} / L.)</div>')
    return HTMLParser(
        f'<article class="product-elem">{"".join(teile)}</article>'
    ).css_first("article.product-elem")


# -- Produzent aus dem Beschreibungsfeld -----------------------------------
@pytest.mark.parametrize(
    "desc, erwartet",
    [
        ("Bodegas Príncipe de Viana Stoffig - aromatisch - harmonisch", "Bodegas Príncipe de Viana"),
        ("Fantini Einmalig - intensiv - stoffig", "Fantini"),
        ("DonnaChiara Harmonisch - eigenständig - vielschichtig", "DonnaChiara"),
        # Ohne Trenner ist das Muster nicht erkennbar — dann lieber nichts.
        ("Irgendein Fliesstext ohne Trenner", ""),
        # Ein einzelnes Wort vor dem Trenner wäre nach dem Abschneiden leer.
        ("Kräftig - würzig - lang", ""),
    ],
)
def test_produzent_ohne_geschmacksadjektiv(desc, erwartet):
    """Das erste Adjektiv klebt ohne Trenner am Produzenten und muss weg.

    Ungefiltert landete "Stoffig" in der Vivino-Abfrage.
    """
    assert _produzent(desc) == erwartet


# -- Die Gegenprobe --------------------------------------------------------
def test_literpreis_bestaetigt_gebinde_ueber_den_streichpreis(adapter):
    """Der Laden rechnet den Literpreis aus dem **Streich**preis.

    "CHF 9.60 / 75 cl statt CHF 17.45 (CHF 23.27 / L.)" — 23.27 ist 17.45/0.75,
    nicht 9.60/0.75. Wer nur gegen den Aktionspreis prüft, findet überall einen
    Widerspruch und verwirft die richtige Gebindeangabe.
    """
    o = adapter._parse_box(_kachel(
        "Falanghina Beneventano IGP", "DonnaChiara Harmonisch - eigenständig - vielschichtig",
        "CHF 9.60 / 75 cl", statt="17.45", liter="23.27", jahr="2020",
    ))
    assert o.bottle_ml == 750
    assert o.price_confidence.value == "high"
    assert o.price_per_bottle_incl_vat == 9.60


def test_magnum_wird_auf_75cl_umgerechnet(adapter):
    o = adapter._parse_box(_kachel(
        "Marquês de Borba Reserva Alentejo DOC", "J. Portugal Ramos Kräftig - dicht - lang",
        "CHF 69.25 / 150 cl", statt="138.50", liter="92.33", jahr="2008",
    ))
    assert o.bottle_ml == 1500
    assert o.price_per_bottle_incl_vat == 34.63


def test_widerspruechlicher_literpreis_verwirft_das_gebinde(adapter):
    """Passt der Literpreis zu keinem der beiden Beträge, ist die Grösse unklar.

    Dann wird die Angabe verworfen statt geraten: ein falsch umgerechneter
    Literpreis erzeugt einen Scheinsieger.
    """
    o = adapter._parse_box(_kachel(
        "Irgendein Wein DOC", "Weingut X Kräftig - würzig - lang",
        "CHF 10.00 / 75 cl", statt="20.00", liter="99.99",
    ))
    assert o.price_confidence.value != "high"


def test_ohne_literpreis_wird_nicht_widersprochen(adapter):
    """Die Prüfung soll Fehler finden, nicht Weine ohne Zusatzangabe aussortieren."""
    o = adapter._parse_box(_kachel(
        "Chianti Classico DOCG", "Weingut Y Kräftig - würzig - lang",
        "CHF 14.00 / 75 cl", statt="20.00",
    ))
    assert o.bottle_ml == 750
    assert o.price_confidence.value == "high"


def test_ohne_streichpreis_kein_angebot(adapter):
    """Trotz des Namens ist nicht jede Position im Outlet herabgesetzt."""
    o = adapter._parse_box(_kachel(
        "Edición Blanca Navarra DO", "Bodegas Príncipe de Viana Stoffig - aromatisch - harmonisch",
        "CHF 14.30 / 75 cl", liter="19.07", jahr="2019",
    ))
    assert o is None


def test_relativer_link_wird_absolut(adapter):
    """44 tote Links, weil "/edizione-bianco_21164700" so übernommen wurde.

    Auf der Berichtsseite löste der Browser sie gegen deren eigene Adresse auf.
    """
    o = adapter._parse_box(
        _kachel("Chianti Classico DOCG", "Weingut Y Kräftig - würzig - lang",
                "CHF 14.00 / 75 cl", statt="20.00"),
        "https://www.wine-outlet.ch/shop/alle-produkte?limit=48",
    )
    assert o.url == "https://www.wine-outlet.ch/x_1"

"""Der Zahlbetrag bei Gebinden — die Zahl, die den Kaufentscheid trägt.

``RetailerPrice.gesamtpreis`` rechnete ``price_per_bottle_incl_vat * units``. Der linke
Faktor ist aber der auf 750 ml **normierte** Preis. Bei Flaschen, die nicht 75 cl
haben, war das Produkt nicht der Kassenbetrag — und der Fehler ging in beide
Richtungen:

    6 × 37.5 cl   ausgewiesen 228.00, zu zahlen 114.00
    6 × 50 cl     ausgewiesen  38.28, zu zahlen  25.50
    6 × 70 cl     ausgewiesen  57.54, zu zahlen  53.70
    6 × 100 cl    ausgewiesen  14.88, zu zahlen  19.80   ← zu niedrig

Der letzte Fall ist der schlimmere: ein zu niedrig ausgewiesener Zahlbetrag lockt zu
einem Kauf, der teurer ist als angeschrieben.

Der bisherige Test konnte den Fehler nicht sehen: tests/test_vivinoshop.py setzte
``price_per_bottle_incl_vat=45.47, price_raw=45.47`` — genau den 75-cl-Fall, in dem
beide Faktoren zusammenfallen.
"""

import pytest

from winecheck.models import RetailerPrice
from winecheck.prices import normalize_price


def _preis(roh, text, *, units_danach=None):
    n = normalize_price(roh, text)
    return RetailerPrice(
        retailer="x", price_per_bottle_incl_vat=n.price_per_bottle_incl_vat,
        price_raw=n.price_raw, price_raw_basis=n.price_raw_basis, url="",
        price_confidence=n.confidence,
        units=units_danach if units_danach is not None else n.units,
        roh_ist_gebinde=n.roh_ist_gebinde, vat_added=n.vat_added,
    )


@pytest.mark.parametrize("roh,text,soll", [
    (114.00, "Karton 6, 37.5 cl, inkl. MwSt", 114.00),
    (25.50,  "Karton 6, 50 cl, inkl. MwSt",    25.50),
    (53.70,  "Karton 6, 70 cl, inkl. MwSt",    53.70),
    (19.80,  "Karton 6, 100 cl, inkl. MwSt",   19.80),
    (290.00, "Karton 6, inkl. MwSt",          290.00),
])
def test_der_kartonpreis_bleibt_der_kartonpreis(roh, text, soll):
    """Ist der Rohpreis der Kartonpreis, ist er auch der Zahlbetrag — unabhaengig von
    der Flaschengroesse."""
    assert _preis(roh, text).gesamtpreis == pytest.approx(soll, abs=0.01)


def test_einzelflasche_bleibt_der_flaschenpreis():
    assert _preis(18.90, "75 cl, inkl. MwSt").gesamtpreis == pytest.approx(18.90, abs=0.01)


def test_preis_je_flasche_mit_abnahmezwang_wird_hochgerechnet():
    """Der Fall Vivino-Marktplatz und Aligro: der Preis gilt je Flasche, abzunehmen
    ist ein Sechserpack. Beide Adapter setzen ``units`` erst NACH dem Normalisieren —
    darum traegt das Modell ein Merkmal (`roh_ist_gebinde`) und keinen fertigen
    Betrag, der dann veraltet waere.

    Gemeldet am Pio Cesare Barolo 2016: CHF 45.47 stand da, zu zahlen sind 272.82.
    """
    p = _preis(45.47, "75 cl, inkl. MwSt", units_danach=6)
    assert p.gesamtpreis == pytest.approx(272.82, abs=0.01)


def test_ohne_mwst_angeschrieben_wird_sie_ergaenzt():
    """Prodega schreibt exkl. an. Der Zahlbetrag muss die Steuer tragen, sonst ist er
    an der Kasse zu tief."""
    p = _preis(100.00, "Karton 6, exkl. MwSt")
    assert p.vat_added
    assert p.gesamtpreis == pytest.approx(108.10, abs=0.01)


def test_der_alte_weg_bleibt_als_rueckfall():
    """Eintraege aus aelteren Laeufen tragen die neuen Felder nicht. Dort ist die alte
    Rechnung die beste verfuegbare — und bei 75 cl, der Mehrheit, ist sie richtig."""
    p = RetailerPrice(retailer="x", price_per_bottle_incl_vat=9.59, price_raw=None,
                      price_raw_basis="", url="",
                      price_confidence=__import__("winecheck.models", fromlist=["x"]).PriceConfidence.HIGH,
                      units=6)
    assert p.gesamtpreis == pytest.approx(57.54, abs=0.01)

"""Anbauregionen — Zusammenfassen ohne zu vermischen.

Vivino nennt 298 verschiedene Regionsnamen für 1347 Weine. Bordeaux zerfällt darin
in sieben Appellationen, jede zu dünn zum Rechnen. Die Tabelle fasst zusammen, was
preislich zusammengehört — und lässt getrennt, was es nicht tut.
"""

import pytest

from winecheck.region import REGIONEN, label, spanne, zuordnen


# -- Zusammenfassen --------------------------------------------------------
def test_bordeaux_appellationen_landen_zusammen():
    """Saint-Émilion 23, Pomerol 19, Pauillac 7, Margaux 7 … einzeln zu dünn.

    Ohne diese Tabelle gäbe es für Bordeaux nichts zu rechnen.
    """
    assert zuordnen("Saint-Émilion Grand Cru") == "bordeaux_rechts"
    assert zuordnen("Pomerol") == "bordeaux_rechts"
    assert zuordnen("Pauillac") == "medoc_cru"
    assert zuordnen("Margaux") == "medoc_cru"


def test_akzente_stoeren_nicht():
    """Vivino schreibt „Saint-Émilion", die Tabelle „saint-emilion"."""
    assert zuordnen("Saint-Émilion") == zuordnen("Saint-Emilion") == "bordeaux_rechts"


def test_der_laengste_alias_gewinnt():
    """"valpolicella" steckt auch in "amarone della valpolicella".

    Amarone kostet das Dreifache. Wer hier den ersten Treffer nähme, legte 16 Amarone
    auf die Valpolicella-Kurve — und ein Amarone für CHF 30 sähe dann teuer aus statt
    normal.
    """
    assert zuordnen("Amarone della Valpolicella Classico") == "amarone"
    assert zuordnen("Valpolicella Ripasso") == "valpolicella"


def test_teiltreffer_in_laengeren_namen():
    """Nicht jede Schreibweise steht in der Tabelle — „Bolgheri Sassicaia DOC" nicht,
    „bolgheri" schon."""
    assert zuordnen("Bolgheri Sassicaia DOC") == "bolgheri"


# -- Nicht vermischen ------------------------------------------------------
def test_barolo_bleibt_neben_langhe_stehen():
    """Beides Piemont, und der Unterschied ist der Punkt: Barolo 35–95, Langhe 11–30.

    Zusammengefasst wäre die Region kein Preisniveau mehr, sondern ein Mittelwert
    aus zwei verschiedenen Welten.
    """
    assert zuordnen("Barolo") == "barolo"
    assert zuordnen("Langhe") == "piemont"
    assert spanne("barolo")[0] > spanne("piemont")[1]


def test_brunello_ist_nicht_toscana():
    assert zuordnen("Brunello di Montalcino") == "brunello"
    assert zuordnen("Toscana") == "toscana"
    assert spanne("brunello")[0] > spanne("toscana")[0]


# -- Nichts erfinden -------------------------------------------------------
def test_unbekanntes_bleibt_unbekannt():
    """„Schaumwein" ist keine Region, sondern eine Machart — Vivino führt das Feld
    gelegentlich so. Geraten wird nichts; der Wein fällt in der Rechnung auf die
    nächstgröbere Ebene zurück."""
    assert zuordnen("Schaumwein") == ""
    assert zuordnen("") == ""
    assert zuordnen("Irgendwo am Meer") == ""


def test_kein_alias_gehoert_zwei_regionen():
    """Sonst entschiede die Reihenfolge der Tabelle über die Zuordnung.

    Die Prüfung läuft beim Import und wirft; dieser Test hält fest, dass es sie gibt
    — und schlägt fehl, sobald jemand sie entfernt.
    """
    gesehen: dict[str, str] = {}
    for r in REGIONEN:
        for a in (r.label, *r.aliase):
            k = a.lower()
            assert gesehen.setdefault(k, r.key) == r.key, f"'{a}' doppelt vergeben"


# -- Die Preisspannen ------------------------------------------------------
def test_jede_region_hat_eine_plausible_spanne():
    for r in REGIONEN:
        assert 0 < r.von < r.bis, f"{r.key}: {r.von}–{r.bis}"
        assert r.bis / r.von <= 5, f"{r.key}: Spanne zu weit, sie ordnet nichts mehr ein"


def test_die_spanne_ist_nur_zur_anzeige_da():
    """Sie ist **gesetzt, nicht gemessen** — wie PREIS_GEWICHT und sonst nichts.

    Darum darf sie in keine Kennzahl einfliessen. Dieser Test kann das nicht
    erzwingen; er hält die Absicht fest, damit sie beim nächsten Umbau nicht
    unbemerkt verlorengeht. Die Rechnung selbst prüft test_wert_region.
    """
    assert spanne("bordeaux") == (12, 30)
    assert label("bordeaux") == "Bordeaux"
    assert spanne("gibtsnicht") is None

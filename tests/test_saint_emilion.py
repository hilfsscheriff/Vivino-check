"""In Saint-Émilion ist „Grand Cru" die Herkunft, in Burgund die Stufe.

Gemeldet an einem Wein für CHF 400: „St-Emilion Château Pavie AOC 2016" stand mit dem
Produzenten-Durchschnitt 4.5 da und dem Vermerk, der Wein selbst sei nicht bewertet.
Bei Vivino trägt der Jahrgang 2016 eine eigene 4.6 aus 466 Bewertungen.

Abgelehnt hatten ihn drei Regeln, alle wegen derselben Wörter: Vivino nennt den Wein
„Château Pavie Saint-Émilion Grand Cru (Premier Grand Cru Classé)", der Händler nur
„St-Emilion Château Pavie AOC". „Grand", „Cru", „Premier" und „Classé" sind hier aber
Appellation und Klassifikation — in Saint-Émilion heisst die Herkunft so. Die dritte
Regel meldete darum einen Scheinunterschied: die Quelle bringe „Classé" zusätzlich mit,
obwohl beide Namen dasselbe sagen.

In Burgund muss die Regel scharf bleiben: dort trennen „Grand Cru" und „Premier Cru"
wirklich verschiedene Weine desselben Guts. Die Ausnahme hängt darum an der Herkunft,
nicht an den Wörtern. Gemessen an allen 2789 gespeicherten Namenspaaren kostet sie
keinen einzigen Treffer und löst alle vier betroffenen Weine.
"""

import pytest

from winecheck.matching import match_wine


@pytest.mark.parametrize("haendler,quelle,jahr", [
    # Händlername nennt nur das Gut — die Quelle nichts darüber hinaus.
    ("St-Emilion Château Pavie AOC 2016 75 cl",
     "Château Pavie Saint-Émilion Grand Cru (Premier Grand Cru Classé)", 2016),
    ("N 3 Angelus St-Emilion AOC 2018",
     "Château Angelus Saint-Émilion Grand Cru (Premier Grand Cru Classé)", 2018),
    # Händlername mit eigenem Namensbestandteil.
    ("Saint-Emilion Château La Croix de Montlabert AOC 2019",
     "Château La Croix de Montlabert Saint-Émilion Grand Cru", 2019),
    ("St-Emilion Château Vieux Clos AOC 2018",
     "Château Vieux Clos St. Emilion Saint-Émilion Grand Cru", 2018),
])
def test_die_appellation_sperrt_den_richtigen_wein_nicht_mehr(haendler, quelle, jahr):
    d = match_wine(haendler, quelle, retailer_vintage=jahr, source_vintage=jahr,
                   source_has_vintage_rating=True)
    assert d.matched, d.reason


@pytest.mark.parametrize("haendler,quelle", [
    # Burgund: die Stufe trennt zwei Weine desselben Guts, in beiden Richtungen.
    ("Chambolle-Musigny 2019 Domaine X",
     "Chambolle-Musigny Premier Cru Les Amoureuses Domaine X"),
    ("Gevrey-Chambertin Grand Cru 2019 Faiveley", "Gevrey-Chambertin Faiveley"),
])
def test_in_burgund_bleibt_die_stufe_entscheidend(haendler, quelle):
    d = match_wine(haendler, quelle, retailer_vintage=2019, source_vintage=2019,
                   source_has_vintage_rating=True)
    assert not d.matched, d.reason


def test_der_zweitwein_desselben_guts_bleibt_getrennt():
    """Was den Pavie schützt, ist nicht die Stufenregel, sondern der Wein selbst.

    Das Haus führt „Esprit de Pavie" — und zwar als Bordeaux AOC, nicht als
    Saint-Émilion. Ein Händler, der „St-Emilion Château Pavie" schreibt, kann diesen
    Wein nicht meinen, und der Abgleich sieht das an den Namen, nicht an einer Regel
    über Qualitätsstufen. Darum darf die Ausnahme oben so weit gehen, wie sie geht.
    """
    d = match_wine("St-Emilion Château Pavie AOC 2018",
                   "Château Pavie Esprit de Pavie Bordeaux",
                   retailer_vintage=2018, source_vintage=2018,
                   source_has_vintage_rating=True)
    assert not d.matched, d.reason


def test_ein_einzelnes_haeufiges_wort_traegt_weiterhin_zu_wenig():
    """Die Regel gegen zu dünne Händlernamen bleibt ausserhalb dieser Herkunft ganz.

    „Montagne Vin Rouge" ist ein Fassweinname; er hing einmal an einem Burgunder
    „Marsannay 'La Montagne' Rouge" mit 382 Bewertungen.
    """
    d = match_wine("Montagne Vin Rouge", "Marsannay La Montagne Rouge")
    assert not d.matched, d.reason

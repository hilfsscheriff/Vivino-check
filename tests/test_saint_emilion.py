"""In Saint-Émilion ist „Grand Cru" die Herkunft, in Burgund die Stufe.

Gemeldet an einem Wein für CHF 400: „St-Emilion Château Pavie AOC 2016" stand mit dem
Produzenten-Durchschnitt 4.5 da und dem Vermerk, der Wein selbst sei nicht bewertet.
Bei Vivino trägt der Jahrgang 2016 eine eigene 4.6 aus 466 Bewertungen.

Abgelehnt hatten ihn zwei Regeln, beide wegen derselben Wörter: Vivino nennt den Wein
„Château Pavie Saint-Émilion Grand Cru (Premier Grand Cru Classé)", der Händler nur
„St-Emilion Château Pavie AOC". „Grand", „Cru", „Premier" und „Classé" sind hier aber
Appellation und Klassifikation — in Saint-Émilion heisst die Herkunft so.

In Burgund muss die Regel scharf bleiben: dort trennen „Grand Cru" und „Premier Cru"
wirklich verschiedene Weine desselben Guts. Die Ausnahme hängt darum an der Herkunft,
nicht an den Wörtern. Gemessen an allen 2643 bestätigten Zuordnungen kostet sie
keinen einzigen Treffer.
"""

import pytest

from winecheck.matching import match_wine


@pytest.mark.parametrize("haendler,quelle,jahr", [
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


def test_ein_produzentenname_allein_genuegt_weiterhin_nicht():
    """Die Ausnahme öffnet die Tür nicht für Namen ohne eigenen Bestandteil.

    „St-Emilion Château Pavie AOC" nennt nur das Gut. Château Pavie führt aber auch
    „Arômes de Pavie" — aus dem Namen allein ist nicht entscheidbar, welcher gemeint
    ist, und die Regel gegen produzentenreine Treffer bleibt richtig. Dieser Wein
    braucht darum eine geprüfte Zuordnung, keine schwächere Regel.
    """
    d = match_wine("St-Emilion Château Pavie AOC 2016 75 cl",
                   "Château Pavie Saint-Émilion Grand Cru (Premier Grand Cru Classé)",
                   retailer_vintage=2016, source_vintage=2016,
                   source_has_vintage_rating=True)
    assert not d.matched
    assert "unspezifisch" in d.reason

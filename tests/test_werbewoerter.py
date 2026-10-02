"""Ein Jubiläumswort ist kein Markenname — auch wenn es zehn Buchstaben hat.

Gemeldet am 02.10.2026: Denners „Centenario Merlot del Ticino DOC 2021" stand für
CHF 11.95 als „gut und günstig" auf der Seite, mit Vivino 4.3 und „−78 % gegen Markt".
Die Note gehörte zur „Matasci Cent Cuvée del Centenario", der Jubiläumscuvée eines
anderen Hauses für CHF 54.80 — daher auch die −78 %.

Der Händler nennt keinen Produzenten. Sein einziges Namenswort war „centenario", und
das hat genau die Länge, ab der ein einzelnes Wort als starker Markenname gilt. Damit
übersprang es die Regel gegen zu dünne Händlernamen, obwohl die Quelle mit „Matasci"
einen Produzenten mitbrachte, den der Händler gar nicht nennt. Länge war hier ein
schlechter Ersatz für Eigenart: viele Häuser nennen eine Sondercuvée so.
"""

import pytest

from winecheck.matching import match_wine
from winecheck.names import WERBEWOERTER, is_distinctive


@pytest.mark.parametrize("wort", ["centenario", "anniversario", "centenaire", "jubilaeum"])
def test_das_wort_traegt_keine_identitaet(wort):
    assert wort in WERBEWOERTER
    assert not is_distinctive(wort)


def test_der_gemeldete_fall():
    d = match_wine("Centenario Merlot del Ticino DOC", "Matasci Cent Cuvée del Centenario Merlot",
                   retailer_vintage=2021)
    assert not d.matched, d.reason


def test_mit_produzent_bleibt_der_treffer():
    """Die Sperre trifft nur Namen, die ausser dem Werbewort nichts Eigenes haben."""
    for haendler, quelle in [
        ("San Marzano 62 Anniversario Primitivo di Manduria",
         "San Marzano 62 Anniversario Primitivo di Manduria"),
        ("Domaine Lafage Centenaire Côtes du Roussillon Blanc",
         "Domaine Lafage Centenaire Côtes du Roussillon Blanc"),
        ("Alceño 150 Aniversario Monastrell", "Alceño 150 Aniversario Monastrell"),
    ]:
        d = match_wine(haendler, quelle)
        assert d.matched, f"{haendler}: {d.reason}"


def test_das_wort_bleibt_in_der_suche():
    """Es verschwindet nicht aus dem Namen — anders als Verpackungsrauschen. Wer
    „Matasci Centenario" sucht, soll den Wein finden; nur als alleiniger Anker taugt
    das Wort nicht."""
    from winecheck.names import PACKAGING_NOISE, normalized_name

    assert "centenario" not in PACKAGING_NOISE
    assert "centenario" in normalized_name("Centenario Merlot del Ticino DOC")

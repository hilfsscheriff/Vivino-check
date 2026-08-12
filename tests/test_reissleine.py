"""Die Reissleine gegen still leer gelieferte Stände.

Die beiden Schwellen gab es schon, aber ausschliesslich in
``.github/workflows/weekly.yml``. Veröffentlicht wird aber über den lokalen Weg —
rate, ratings-export, report, site, git push —, und der hatte keine. Eine
Schemaänderung bei einer Bewertungsquelle hätte die versionierte Austauschdatei mit
Leerwerten überschrieben, ohne dass etwas fehlschlägt.
"""

import pytest

from winecheck.aggregate import (
    MIN_BEWERTET_ANTEIL,
    Unplausibel,
    pruefe_plausibilitaet,
)
from winecheck.models import VivinoResult, VivinoStatus, WineRow


def _zeile(status=VivinoStatus.EXACT, note=4.2):
    return WineRow(
        name="Irgendein Wein", vintage=None, dedup_key="k",
        vivino=VivinoResult(status=status, query="q", url="u", note="n", rating=note),
    )


def test_ein_guter_stand_geht_durch():
    pruefe_plausibilitaet([_zeile() for _ in range(100)], 100)


def test_halbierte_trefferquote_bricht_ab():
    """Der Fall, den eine Schemaänderung erzeugt: die Quelle antwortet mit 200 und
    liefert nichts, statt zu blocken."""
    rows = [_zeile() for _ in range(40)] + [
        _zeile(VivinoStatus.NO_ENTRY, None) for _ in range(60)
    ]
    with pytest.raises(Unplausibel, match="still leer"):
        pruefe_plausibilitaet(rows, 100)


def test_gesperrte_quelle_bricht_ab():
    """Das eindeutige Signal. Beim ersten CI-Lauf waren es 465 von 478."""
    rows = [_zeile(VivinoStatus.BLOCKED, None) for _ in range(30)] + [
        _zeile() for _ in range(70)
    ]
    with pytest.raises(Unplausibel, match="blockiert"):
        pruefe_plausibilitaet(rows, 100)


def test_ohne_vergleichsstand_greift_nur_die_blockadepruefung():
    """Beim ersten Lauf gibt es keinen Vorstand — dann darf die Quote nichts sperren."""
    pruefe_plausibilitaet([_zeile() for _ in range(5)], None)


def test_kleiner_vorstand_sperrt_nicht():
    """Unter der Vergleichsbasis ist der Quotenvergleich Zufall."""
    pruefe_plausibilitaet([_zeile()], 5)


def test_leerer_bestand_bricht_ab():
    with pytest.raises(Unplausibel, match="Keine Weine"):
        pruefe_plausibilitaet([], 100)


def test_ein_sortimentswechsel_darf_druecken():
    """Gegenprobe: die Grenze liegt bei zwei Dritteln, damit ein legitimer
    Aktionswechsel nicht als Ausfall gilt."""
    knapp = int(100 * MIN_BEWERTET_ANTEIL) + 1
    rows = [_zeile() for _ in range(knapp)] + [
        _zeile(VivinoStatus.NO_ENTRY, None) for _ in range(100 - knapp)
    ]
    pruefe_plausibilitaet(rows, 100)


def test_der_workflow_nutzt_dieselben_konstanten():
    """Die Schwellen dürfen nicht wieder auseinanderlaufen: der Workflow importiert
    sie, statt 0.2 und 0.66 erneut hinzuschreiben."""
    from pathlib import Path

    yml = Path(__file__).resolve().parents[1] / ".github/workflows/weekly.yml"
    text = yml.read_text(encoding="utf-8")
    assert "from winecheck.aggregate import" in text
    assert "MAX_BLOCKIERT_ANTEIL" in text and "MIN_BEWERTET_ANTEIL" in text
    # Die alten, fest verdrahteten Zahlen sind weg.
    assert "* 0.2" not in text and "* 0.66" not in text

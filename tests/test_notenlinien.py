"""Eine Notenlinie muss auf einer Note liegen, die es gibt.

Vivino gibt seine Noten in Zehnteln aus — von 1682 Werten im Bestand liegt kein
einziger dazwischen. Die Leiter der Achsenabstände begann trotzdem bei 0.05, mit einer
Begründung von mir, die ein Fehlschluss war: „Vivino weist Noten in Zehnteln aus; die
Leiter beginnt darum bei 0.05."

Die Folge sah man erst bei enger Auswahl. Blieben nach dem Filtern nur Noten von 4.2
bis 4.3, zog das Diagramm Linien auf 4.15, 4.25 und 4.35 — drei von sieben, auf denen
nie ein Punkt liegen kann. Es sah feiner aufgelöst aus, als die Daten hergeben, und
liess die Punkte wie zufällig zwischen den Linien wirken. Gemeldet mit „0.05er
Schritte in den Noten gibt es nicht, das nervt mich".
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ASSETS = Path(__file__).resolve().parents[1] / "src" / "winecheck" / "report" / "assets"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node nicht vorhanden")


def _linien(spannen: list[tuple[float, float]]) -> list[list[float]]:
    js = (ASSETS / "app.js").read_text(encoding="utf-8")
    start = js.index("const NOTENSTUFEN")
    ende = js.index("/* ------", start)
    programm = js[start:ende] + f"""
console.log(JSON.stringify({json.dumps(spannen)}.map(([a, b]) => notenlinien(a, b))));
"""
    lauf = subprocess.run(["node", "-e", programm], capture_output=True, text=True, timeout=60)
    assert lauf.returncode == 0, lauf.stderr
    return json.loads(lauf.stdout)


@needs_node
@pytest.mark.parametrize("y0,y1", [
    (4.15, 4.35), (4.1, 4.4), (4.2, 4.3), (3.2, 4.7), (1.0, 5.0),
    (4.05, 4.15), (3.95, 4.05), (4.0, 4.2), (2.5, 3.1),
])
def test_jede_linie_liegt_auf_einem_zehntel(y0, y1):
    """Die eigentliche Zusicherung — unabhängig davon, welcher Abstand gewählt wird."""
    (linien,) = _linien([(y0, y1)])
    assert linien, f"keine Linie für {y0}–{y1}"
    for v in linien:
        assert abs(v * 10 - round(v * 10)) < 1e-9, f"{v} liegt zwischen zwei Noten"


@needs_node
def test_die_enge_auswahl_bekommt_keine_halben_zehntel():
    """Der gemeldete Fall: nur Noten von 4.2 bis 4.3 in der Auswahl."""
    (linien,) = _linien([(4.15, 4.35)])
    assert linien == [4.2, 4.3]
    assert 4.25 not in linien


@needs_node
def test_die_linien_bleiben_in_der_spanne_und_sind_geordnet():
    for (y0, y1), linien in zip([(4.1, 4.4), (3.2, 4.7)], _linien([(4.1, 4.4), (3.2, 4.7)])):
        assert linien == sorted(linien)
        assert y0 - 1e-9 <= linien[0] and linien[-1] <= y1 + 1e-9


@needs_node
def test_nie_mehr_als_sieben_linien():
    """Sonst wird die Achse zur Leiter und das Diagramm unlesbar."""
    for linien in _linien([(1.0, 5.0), (3.0, 4.8), (4.0, 4.9), (2.0, 5.0)]):
        assert len(linien) <= 7, linien


def test_die_leiter_kennt_keinen_halben_zehntel_schritt():
    js = (ASSETS / "app.js").read_text(encoding="utf-8")
    zeile = re.search(r"const NOTENSTUFEN = \[(.*?)\];", js).group(1)
    stufen = [float(x) for x in zeile.split(",")]
    assert min(stufen) >= 0.1, f"Schritt {min(stufen)} liegt unter der Auflösung der Daten"
    for s in stufen:
        assert abs(s * 10 - round(s * 10)) < 1e-9, s
    # 0.25 gehört ebenfalls nicht dazu: eine Linie auf 4.25 stünde als «4.3» an.
    assert 0.25 not in stufen

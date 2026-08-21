"""Die Detailzeilen der Liste müssen einen Wein ohne Fremdbewertung überleben.

``detailRows`` wird aus zwei Richtungen gerufen: das Diagramm zeigt nur bewertete
Weine, die Tabelle alle. Der erste Zugriff war ``p.rating.toFixed(1)`` ohne Prüfung —
und riss bei einem Wein ohne Note die ganze Darstellung mitten im Neuzeichnen.

Das Ergebnis war heimtückisch: der Zähler über der Liste stand schon auf der neuen
Auswahl, die Tabelle noch auf der alten. Es sah aus, als filtere die Seite falsch.
Gemeldet wurde es als „mit Filter DIVO, das wirkt falsch" — und genau dort trat es
auf, weil DIVOs Weine grösstenteils keinen Vivino-Eintrag haben und der Laden nur
sichtbar wird, wenn man die voreingestellte Notengrenze von 4.2 aufhebt. Unter der
Vorauswahl trägt jeder gezeigte Wein eine Note; darum blieb der Fehler verdeckt.

Geprüft wird darum das Verhalten und nicht der Quelltext: die Funktion wird mit node
ausgeführt, mit einem Wein ohne Note, einem mit Note und einem, für den es nur einen
Produzenten-Durchschnitt gibt.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ASSETS = Path(__file__).resolve().parents[1] / "src" / "winecheck" / "report" / "assets"

#: Die Umgebung, die ``detailRows`` erwartet — knapp gehalten, damit der Test die
#: Funktion prüft und nicht ihre Nachbarschaft.
STUMMEL = """
const esc = s => String(s ?? "");
const chf = v => (v == null || v === 0) ? "—" : "CHF " + Number(v).toFixed(2);
const valueOf = () => null, valueText = () => "", valueBezug = () => "";
const gebindeText = () => "";
const D = { retailers: [{ key: "divo", name: "DIVO" }] };
"""


def _detailzeilen() -> dict[str, str]:
    js = (ASSETS / "app.js").read_text(encoding="utf-8")
    start = js.index("function detailRows(")
    ende = js.index("\nfunction table(", start)
    programm = STUMMEL + js[start:ende] + """
const ohne = { name: "Arvad Blanc 2024", price: 11.4, cheapest: "divo", styleLabel: "Weisswein" };
const mit = { name: "Anthoinette 2024", price: 15.2, cheapest: "divo", rating: 4.0, ratingCount: 236 };
const winery = { name: "Irgendwas", price: 9.0, cheapest: "divo", wineryRating: 3.8 };
console.log(JSON.stringify({ ohne: detailRows(ohne), mit: detailRows(mit),
                             winery: detailRows(winery) }));
"""
    lauf = subprocess.run(["node", "-e", programm], capture_output=True, text=True, timeout=60)
    assert lauf.returncode == 0, lauf.stderr
    return json.loads(lauf.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node nicht vorhanden")
def test_ein_wein_ohne_note_sprengt_die_details_nicht():
    zeilen = _detailzeilen()["ohne"]
    assert "keine Fremdbewertung verfügbar" in zeilen
    # Und der Rest der Auskunft steht trotzdem da — der Wein ist ja nicht wertlos.
    assert "Weisswein" in zeilen and "CHF 11.40" in zeilen


@pytest.mark.skipif(shutil.which("node") is None, reason="node nicht vorhanden")
def test_mit_note_steht_die_note_da():
    assert "4.0/5 (236)" in _detailzeilen()["mit"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node nicht vorhanden")
def test_nur_produzenten_durchschnitt_wird_als_solcher_ausgewiesen():
    """Ein Produzenten-Mittel ist keine Note für *diesen* Wein und muss so dastehen."""
    zeilen = _detailzeilen()["winery"]
    assert "Produzenten-Ø 3.8/5" in zeilen

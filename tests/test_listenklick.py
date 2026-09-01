"""Der Klick in die Liste bedeutet auf dem Handy etwas anderes als am Desktop.

Gemeldet, nachdem der Klick auf einen Punkt im Diagramm ein Fenster mit allen Weinen
dieser Stelle bekam: „auf dem handy habe ich die grafik nicht, wenn da auf ein link
geklickt wird soll es zum shop gehen, aber die tabelle auf dem desktop, da soll das
verhalten anderst sein".

Das ist sachlich begründet und nicht bloss Geschmack. Auf dem Handy ist die Liste
alles, was es gibt — das Diagramm ist per CSS ausgeblendet. Wer dort auf einen Link
tippt, steht meist im Laden und will sofort in den Shop. Am Desktop steht das
Diagramm daneben, man vergleicht, und ein Klick, der ungefragt eine Händlerseite
öffnet, reisst aus dem Vergleich heraus.

Geprüft wird die Entscheidungsregel selbst, mit node und ohne Browser.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ASSETS = Path(__file__).resolve().parents[1] / "src" / "winecheck" / "report" / "assets"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node nicht vorhanden")


def _entscheide(faelle: list[dict]) -> list[str]:
    js = (ASSETS / "app.js").read_text(encoding="utf-8")
    start = js.index("function listenklick(")
    ende = js.index("\n/* Die Liste, wie sie gerade gerendert ist", start)
    programm = js[start:ende] + f"""
console.log(JSON.stringify({json.dumps(faelle)}.map(listenklick)));
"""
    lauf = subprocess.run(["node", "-e", programm], capture_output=True, text=True, timeout=60)
    assert lauf.returncode == 0, lauf.stderr
    return json.loads(lauf.stdout)


@needs_node
def test_auf_dem_handy_bleibt_der_link_ein_link():
    (navigieren, daneben) = _entscheide([
        {"handy": True, "aufLink": True, "modifiziert": False, "auswahl": False},
        {"handy": True, "aufLink": False, "modifiziert": False, "auswahl": False},
    ])
    assert navigieren == "navigieren"
    # Ein Tipp neben den Link öffnet nichts: die Kartenansicht hat schon den
    # Details-Knopf, und ein Fenster über der ganzen Fläche wäre eine zweite,
    # widersprechende Bedienung.
    assert daneben == "nichts"


@needs_node
def test_am_desktop_zeigt_der_klick_zuerst_die_angaben():
    (auf_link, daneben) = _entscheide([
        {"handy": False, "aufLink": True, "modifiziert": False, "auswahl": False},
        {"handy": False, "aufLink": False, "modifiziert": False, "auswahl": False},
    ])
    assert auf_link == "fenster"
    assert daneben == "fenster"


@needs_node
def test_der_bewusste_klick_in_einen_neuen_tab_funktioniert_weiter():
    """Was die Umstellung kostet, ist genau ein einfacher Klick — nicht mehr.

    Mittelklick, Cmd/Ctrl-Klick und Shift-Klick navigieren weiterhin. Ohne diese
    Ausnahme wäre „Link in neuem Tab öffnen" am Desktop verloren, und das ist genau
    die Bedienung, mit der man mehrere Angebote nebeneinander legt.
    """
    ergebnis = _entscheide([
        {"handy": False, "aufLink": True, "modifiziert": True, "auswahl": False},
    ])
    assert ergebnis == ["navigieren"]


@needs_node
def test_eine_textauswahl_oeffnet_kein_fenster():
    """Wer einen Weinnamen markiert, um ihn zu kopieren, klickt dabei in die Zeile."""
    ergebnis = _entscheide([
        {"handy": False, "aufLink": False, "modifiziert": False, "auswahl": True},
    ])
    assert ergebnis == ["nichts"]


def test_der_bruchpunkt_steht_nur_im_css():
    """Die Zahl 720 darf nicht ein zweites Mal in JavaScript stehen.

    Zwei Zahlen, die auseinanderlaufen können, wären schlimmer als eine indirekte
    Abfrage: JavaScript liest die Ansicht darum über die CSS-Eigenschaft
    ``--ansicht``, die der Media-Query setzt.
    """
    css = (ASSETS / "app.css").read_text(encoding="utf-8")
    js = (ASSETS / "app.js").read_text(encoding="utf-8")
    # Genau ein Breiten-Media-Query, und er setzt die Ansicht.
    breiten = re.findall(r"@media\s*\(\s*(?:max|min)-width[^)]*\)", css)
    assert breiten == ["@media (max-width: 720px)"], breiten
    assert "--ansicht: desktop;" in css and "--ansicht: handy;" in css
    # Und in app.js kommt die Zahl nirgends vor, auch nicht im Kommentar: eine
    # zweite Stelle, die auseinanderlaufen kann, faengt mit der Prosa an.
    assert "--ansicht" in js
    assert not re.search(r"\b720\b", js), "der Bruchpunkt gehoert nur ins CSS"

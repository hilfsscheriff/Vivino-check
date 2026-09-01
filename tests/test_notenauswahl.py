"""Die Notenschwelle in Zehnteln — dort, wo die Entscheidungen fallen.

Die Auswahl bot alle, 3.5, 3.8, 4.0, 4.2, 4.5. Der Sprung von 4.2 auf 4.5 überging
387 Weine, und genau in diesem Band liegt das obere Drittel des Bestands: gemessen am
Lauf vom 28.08.2026 stehen hinter „ab 4.0" 1007 Weine, hinter 4.3 noch 231, hinter
4.6 noch 10.

Unter 4.0 bleibt es grob: dort sind es tausende Weine, und wer so filtert, sucht keine
Feinheit, sondern eine Untergrenze.
"""

import re
from pathlib import Path

QUELLE = Path(__file__).resolve().parents[1] / "src" / "winecheck" / "report" / "site.py"

#: Die Leiter, wie sie sein soll. Wert und Beschriftung getrennt, weil „4.0" den Wert
#: „4" trägt — das Zurücksetzen vergleicht über ``String(4)``.
ERWARTET = [("", "alle"), ("3.5", "3.5"), ("3.8", "3.8"), ("4", "4.0"),
            ("4.1", "4.1"), ("4.2", "4.2"), ("4.3", "4.3"), ("4.4", "4.4"),
            ("4.5", "4.5"), ("4.6", "4.6")]


def _auswahl() -> list[tuple[str, str]]:
    t = QUELLE.read_text(encoding="utf-8")
    block = t[t.index('<select id="fMinRating">'):]
    block = block[:block.index("</select>")]
    return re.findall(r'<option value="([^"]*)">([^<]+)</option>', block)


def test_die_leiter_geht_in_zehnteln_von_4_0_bis_4_6():
    assert _auswahl() == ERWARTET


def test_der_wert_von_4_0_bleibt_vier():
    """Sonst findet das Zurücksetzen die Stufe nicht wieder: es setzt den Wert über
    ``String(STANDARD_NOTE)``, und aus 4.0 wird dort „4"."""
    werte = dict((b, w) for w, b in _auswahl())
    assert werte["4.0"] == "4"


def test_4_2_bleibt_die_voreinstellung():
    """Die Voreinstellung ist eine Aussage über den Bestand — ab 4.2 beginnt das obere
    Drittel — und sie soll sich nicht mit einer feineren Leiter verschieben."""
    js = (QUELLE.parent / "assets" / "app.js").read_text(encoding="utf-8")
    m = re.search(r"const STANDARD_NOTE = ([\d.]+)", js)
    assert m and m.group(1) == "4.2"
    assert ("4.2", "4.2") in _auswahl()

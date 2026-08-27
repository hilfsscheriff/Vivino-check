"""„Filter zurücksetzen" muss jede Filtergruppe zurücksetzen.

Gemeldet: der Knopf liess die Typ-Auswahl stehen. „Weich & modern" und „Ausgewogen"
blieben gewählt, die Zeile darüber zählte weiter „3 aktiv" — es sah wie ein defekter
Knopf aus, und es war einer: ``S.typ`` stand nicht im Zurücksetzen.

Geprüft wird darum nicht der eine Fall, sondern die Vollständigkeit: jedes Feld des
Filterzustands muss im Zurücksetz-Block vorkommen. Ausnahmen brauchen einen Namen und
eine Begründung, sonst fällt die nächste vergessene Gruppe genauso durch.
"""

import re
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "src" / "winecheck" / "report" / "assets"

#: Felder, die das Zurücksetzen bewusst nicht anfasst.
#:
#: ``run`` ist die Wahl des Laufs, nicht ein Filter über den Bestand — wer einen
#: früheren Lauf ansieht, will ihn beim Aufräumen der Filter nicht verlieren.
BEWUSST_AUSSEN = {"run"}


def _quelltext() -> str:
    return (ASSETS / "app.js").read_text(encoding="utf-8")


def _zustandsfelder(js: str) -> set[str]:
    start = js.index("const S = {")
    block = js[start:js.index("\nconst esc", start)]
    return set(re.findall(r"(?:^|\{|\s)([a-zA-Z][a-zA-Z0-9_]*)\s*:", block))


def _zuruecksetz_block(js: str) -> str:
    start = js.index('document.getElementById("reset").addEventListener')
    return js[start:js.index("\n});", start)]


def test_jede_filtergruppe_wird_zurueckgesetzt():
    js = _quelltext()
    felder = _zustandsfelder(js) - BEWUSST_AUSSEN
    block = _zuruecksetz_block(js)
    fehlen = {f for f in felder if not re.search(rf"\bS\.{re.escape(f)}\b", block)}
    assert not fehlen, f"vom Zurücksetzen nicht angefasst: {sorted(fehlen)}"


def test_der_typ_steht_ausdruecklich_drin():
    """Der gemeldete Fall, als eigener Test — damit er beim Umbauen nicht wegfällt."""
    assert "S.typ.clear()" in _zuruecksetz_block(_quelltext())


def test_die_ausnahme_ist_wirklich_eine_ausnahme():
    """``run`` darf nicht heimlich verschwinden: steht es plötzlich im Block, ist die
    Begründung oben veraltet."""
    assert not re.search(r"\bS\.run\b", _zuruecksetz_block(_quelltext()))

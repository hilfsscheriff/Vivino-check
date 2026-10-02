"""Der Preisverlauf gehört neben den Preis von heute.

Gefragt am 02.10.2026 an der „Tenuta Ulisse Limited Edition 10 Vendemmie", die für
CHF 30.90 als Vivino-Aktion auf der Seite stand: „wie war die Preisentwicklung?" Die
Antwort lag seit dem 1.9. in der Preisreihe und stand nirgends auf der Seite. Anfang
September hatte derselbe Wein CHF 23.95 gekostet — die Aktion von heute war 29 %
teurer als die von damals, und das schreibt kein Händler an.

Geprüft werden beide Hälften: die Verdichtung der Reihe in Python und ihre Auskunft
im Browser, mit node und ohne Netz.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from winecheck.report.site import _reihenschluessel, preisverlauf_je_wein

ASSETS = Path(__file__).resolve().parents[1] / "src" / "winecheck" / "report" / "assets"

TAGE = ["2026-09-01", "2026-09-04", "2026-09-09", "2026-09-11", "2026-09-14",
        "2026-09-18", "2026-09-21", "2026-09-22", "2026-09-25", "2026-10-02"]


def _b(datum, preis, haendler="vivinoshop", name="tenuta ulisse limited edition 10 vendemmie"):
    return {"datum": datum, "name_key": name, "vintage": "", "haendler": haendler,
            "preis_75cl": preis}


#: Der echte Verlauf bei Vivino, wie er in der Reihe steht.
ULISSE_VIVINO = ([_b(t, 23.95) for t in TAGE[:4]] + [_b(TAGE[4], 34.00)]
                 + [_b(TAGE[9], 30.90)])


def test_nur_die_wechselpunkte_werden_gespeichert():
    """Ein Preis, der stillsteht, kostet einen Eintrag — die Seite trägt
    zweieinhalbtausend Weine."""
    v = preisverlauf_je_wein(ULISSE_VIVINO, TAGE)
    laeufe = v[_reihenschluessel("tenuta ulisse limited edition 10 vendemmie", "")]["vivinoshop"]
    assert laeufe == [[0, 2395], [4, 3400], [5, None], [9, 3090]]


def test_eine_luecke_bleibt_eine_luecke():
    """``None`` heisst „nicht im Angebot" — vom 18.9. bis 25.9. stand der Wein bei
    Vivino nicht in den Aktionen. Das darf keine Linie überdecken."""
    v = preisverlauf_je_wein(ULISSE_VIVINO, TAGE)
    laeufe = next(iter(v.values()))["vivinoshop"]
    assert [5, None] in laeufe


def test_die_wortfolge_trennt_keinen_wein():
    """Schubi führte denselben Wein eine Woche lang mit umgestellten Wörtern. Im
    Verlauf stand dafür eine Woche „nicht im Angebot", die es nie gab."""
    reihe = ([_b(t, 35.90, "schubi") for t in TAGE[:5]]
             + [_b(t, 35.90, "schubi", "10 vendemmie limited edition tenuta ulisse")
                for t in TAGE[5:9]]
             + [_b(TAGE[9], 35.90, "schubi")])
    v = preisverlauf_je_wein(reihe, TAGE)
    assert len(v) == 1, "beide Schreibweisen muessen zu einem Wein gehoeren"
    assert next(iter(v.values()))["schubi"] == [[0, 3590]]


def test_vor_der_ersten_beobachtung_steht_nichts():
    """Ein Wein, der erst am 14.9. auftaucht, war vorher nicht gesehen — nicht
    „nicht im Angebot"."""
    v = preisverlauf_je_wein([_b(TAGE[4], 19.50), _b(TAGE[9], 19.50)], TAGE)
    laeufe = next(iter(v.values()))["vivinoshop"]
    assert laeufe[0][0] == 4


# ------------------------------------------------------------------ im Browser

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node nicht vorhanden")


def _js(ausdruck: str):
    js = (ASSETS / "app.js").read_text(encoding="utf-8")
    start = js.index("function tagKurz(")
    ende = js.index("\nfunction preisverlaufZeile(", start)
    programm = ('const chf = v => "CHF " + Number(v).toFixed(2);\n'
                + js[start:ende] + f"\nconsole.log(JSON.stringify({ausdruck}));")
    lauf = subprocess.run(["node", "-e", programm], capture_output=True, text=True, timeout=60)
    assert lauf.returncode == 0, lauf.stderr
    return json.loads(lauf.stdout)


@needs_node
def test_der_gemeldete_fall_sagt_was_er_sagen_soll():
    tage = json.dumps(TAGE)
    text = _js(f"preisverlaufText(preisverlaufAuskunft([[0,2395],[4,3400],[5,null],[9,3090]], "
               f"{tage}), {tage})")
    assert "jetzt CHF 30.90" in text
    assert "Tief CHF 23.95 am 1.9.–11.9." in text
    assert "+29 %" in text
    assert "zeitweise nicht im Angebot" in text


@needs_node
def test_ein_stiller_preis_sagt_unveraendert():
    tage = json.dumps(TAGE)
    text = _js(f"preisverlaufText(preisverlaufAuskunft([[0,3590]], {tage}), {tage})")
    assert text == "unverändert CHF 35.90 seit 1.9."


@needs_node
def test_das_tief_von_heute_wird_als_solches_genannt():
    tage = json.dumps(TAGE)
    text = _js(f"preisverlaufText(preisverlaufAuskunft([[0,2800],[6,2400]], {tage}), {tage})")
    assert text.startswith("jetzt CHF 24.00")
    assert "das Tief seit 1.9." in text


@needs_node
def test_das_datum_ist_schweizerisch():
    assert _js('[tagKurz("2026-09-01"), tagKurz("2026-10-02")]') == ["1.9.", "2.10."]

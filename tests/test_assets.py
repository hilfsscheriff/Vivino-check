"""Die Anzeigeschicht liegt in Dateien und ist damit prüfbar.

Sie lag in einem Python-String: 1208 von 1860 Zeilen `site.py`, davon 32
JavaScript-Funktionen. Kein Werkzeug kam daran — kein Syntaxfehler fiel auf, keine
Formatierung griff, und `pytest --cov` meldete für die Datei 97 %, gemessen an 172
Python-Anweisungen. Die Zahl sagte über die Anzeige nichts und las sich, als sagte sie
alles.

Die Auslieferung als *eine* HTML-Datei bleibt — sie ist der Grund, dass die Seite
offline und ohne Drittanbieter funktioniert. Nur die Quellen liegen getrennt.
"""

import json
import re
import shutil
import subprocess

import pytest

from winecheck.report.site import _ASSETS, _SHORT_KEYS, _asset, _wine_from_snapshot, build


@pytest.fixture
def doc(tmp_path):
    """Die gebaute Seite als Text. Bewusst eigenstaendig statt aus test_site.py
    geliehen — dieser Test prueft die Vorlage, nicht die Anzeige."""

    def _build():
        wein = _wine_from_snapshot({
            "dedup_key": "k", "name": "Pomerol AOC 2007 Château Lafleur",
            "vintage": "2007", "best_price": 42.0, "vivino_rating": 4.4,
            "vivino_status": "exact", "vivino_rating_count": 900,
            "retailers": ["coop"], "cheapest_retailer": "coop",
        })
        pfad = build([{"id": "r1", "label": "6.8.2026", "date": "2026-08-06",
                       "wines": [wein]}], tmp_path / "index.html")
        assert pfad is not None
        return pfad.read_text(encoding="utf-8")

    return _build


def test_die_dateien_liegen_getrennt_und_sind_nicht_leer():
    assert (_ASSETS / "app.css").is_file()
    assert (_ASSETS / "app.js").is_file()
    assert len(_asset("app.css")) > 5_000
    assert len(_asset("app.js")) > 20_000


@pytest.mark.skipif(shutil.which("node") is None, reason="node nicht vorhanden")
def test_das_javascript_ist_syntaktisch_gueltig():
    """Der eigentliche Gewinn der Trennung. Im String war das nicht prüfbar; ein
    Tippfehler fiel erst im Browser auf, und nur wenn jemand hinsah."""
    r = subprocess.run(["node", "--check", str(_ASSETS / "app.js")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_die_geschweiften_klammern_im_css_gehen_auf():
    """Kein Ersatz für einen CSS-Parser, aber es fängt den häufigsten Schaden beim
    Bearbeiten eines langen Blocks."""
    css = _asset("app.css")
    assert css.count("{") == css.count("}")


def test_kein_platzhalter_bleibt_im_dokument_stehen(doc):
    """Die Vorlage füllt sieben Platzhalter. Bleibt einer stehen, steht er sichtbar auf
    der Seite — und die Datei sähe nicht kaputt aus, sondern nur seltsam."""
    text = doc()
    offen = re.findall(r"__[A-Z_]+__", text)
    assert not offen, f"nicht ersetzt: {sorted(set(offen))}"


def test_die_schluesselabbildung_wird_erzeugt_und_nicht_gepflegt():
    """Sie stand zweimal da, je Richtung einmal, und ein fehlendes Paar hat einen
    Ausfall gekostet: ``w.swiss`` war im Browser immer undefiniert, und der
    Quellenfilter zeigte in jeder Einzelstellung null von 1391 Weinen."""
    js = _asset("app.js")
    assert "const KEYS = __KEYS__;" in js
    # Keine handgeschriebene zweite Tabelle mehr.
    assert 'n:"name"' not in js and 'mp:"marketplace"' not in js


def test_die_erzeugte_abbildung_ist_die_umkehrung(doc):
    roh = re.search(r"const KEYS = (\{.*?\});", doc(), re.S)
    assert roh
    assert json.loads(roh.group(1)) == {k: v for v, k in _SHORT_KEYS.items()}

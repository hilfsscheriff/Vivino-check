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


# ------------------------------------------- Barrierefreiheit, aus dem UX-Review

def test_jede_farbe_der_seite_wird_auf_kontrast_geprueft():
    """Die eigentliche Ursache des Kontrastfehlers: nicht die Rechnung, ihr Umfang.

    ``--typ1`` bis ``--typ4`` standen als 12-px-Text in jeder Tabellenzeile und waren im
    Prüfer nicht aufgeführt — ``check_tokens()`` meldete «keine Beanstandung», während
    drei der vier 4.5:1 verfehlten. Dieser Test hält den Umfang fest: was im CSS als
    Farbe verwendet wird, muss geprüft sein.
    """
    from winecheck.report.site import _TOKEN_CONTRAST

    css = _asset("app.css")
    benutzt = set(re.findall(r"var\((--[a-z0-9-]+)", css))
    # Nicht-Farben und der Grund selbst bleiben aussen vor.
    keine_farbe = {"--fs-page-title", "--fs-title", "--fs-body", "--fs-body-sm",
                   "--fs-label", "--serif", "--sans", "--mono", "--control-h", "--ctl"}
    # ``--bg`` ist der Grund, gegen den geprüft wird; ``--chip`` ist durchsichtig;
    # ``--line`` trennt rein dekorativ, tragende Ränder nehmen ``--line-strong``.
    absichtlich_ohne = {"--bg", "--chip", "--line", "--panel"}
    offen = benutzt - keine_farbe - absichtlich_ohne - set(_TOKEN_CONTRAST["hell"][1])
    assert not offen, f"als Farbe verwendet, aber nicht im Kontrastprüfer: {sorted(offen)}"


def test_die_typ_pillen_nehmen_den_textton():
    """Rand aus dem Grafikton (3:1 genügt), Text aus dem Textton (4.5:1 nötig).

    Ohne die Trennung trug „Weich & modern" 3.42:1 als 12-px-Versalien.
    """
    css = _asset("app.css")
    for typ, ton in ((("fruchtsuess"), "typ1"), ("weich_modern", "typ2"),
                     ("ausgewogen", "typ3"), ("straff_herb", "typ4")):
        regel = re.search(rf"\.pill\.t-{typ} \{{([^}}]*)\}}", css)
        assert regel, typ
        assert f"color:var(--{ton}tx)" in regel.group(1), f"{typ} nimmt den Grafikton als Text"
        assert f"border-color:var(--{ton})" in regel.group(1)


def test_der_spaltenkopf_nennt_den_sortierzustand():
    """Vorher trug der Knopf ein festes ``aria-label``, das den Zustand nicht nannte und
    als zugänglicher Name den Pfeil im Text *überschrieb*: gehört wurde „Nach
    Preis-Leistung sortieren" und damit nichts über die gezeigte Reihenfolge."""
    js = _asset("app.js")
    # Nur die erzeugte Auszeichnung prüfen, nicht die Datei: die Begründung im Kommentar
    # zitiert das alte Label und würde jede Suche über die ganze Datei täuschen.
    kopf = re.search(r"const head = COLS\.map\(.*?\}\)\.join\(\"\"\);", js, re.S)
    assert kopf, "Kopfzeile der Tabelle nicht gefunden"
    kopf = kopf.group(0)
    assert 'aria-sort="${richtung}"' in kopf
    assert 'scope="col"' in kopf
    assert "aria-label" not in kopf, "ein festes Label verdeckt den Zustand"
    # Der Pfeil ist Dekoration derselben Aussage und darf nicht doppelt gelesen werden.
    assert 'aria-hidden="true"' in kopf


def test_der_fokus_ueberlebt_den_neuaufbau_der_tabelle():
    """Gemessen: nach Sortieren und nach „Weitere anzeigen" lag der Fokus auf ``BODY``.

    Bei 1473 Weinen und 50 je Seite wird der Knopf bis zu 29 Mal gedrückt, und jedes Mal
    begann der Weg wieder am Dokumentanfang über 159 fokussierbare Elemente.
    """
    js = _asset("app.js")
    assert "function fokusMerken" in js and "function fokusZurueck" in js
    # Gemerkt wird vor dem Ersetzen, zurückgegeben danach.
    tabelle = js[js.index("function table(list)"):]
    assert tabelle.index("fokusMerken(box)") < tabelle.index("box.innerHTML")
    assert tabelle.index("box.innerHTML") < tabelle.index("fokusZurueck(box, merk)")


def test_die_sticky_leiste_verdeckt_den_fokus_nicht():
    """``scroll-padding-top`` fehlte. Gemessen: ein oben ausgerichtetes Element lag bei
    top 0, die Unterkante der deckenden Leiste bei 117 px — vollständig verdeckt."""
    css = _asset("app.css")
    m = re.search(r"scroll-padding-top:([\d.]+)rem", css)
    assert m, "ohne scroll-padding-top kann die sticky Leiste den Fokus verdecken"
    assert float(m.group(1)) * 16 >= 117, "muss die gemessene Leistenhöhe abdecken"


def test_die_grundschrift_skaliert_mit():
    """``font:16px`` hielt den Fliesstext fest, während alle Rollen darüber in ``rem``
    mitskalierten — reine Textvergrösserung wirkte damit nur zur Hälfte."""
    css = _asset("app.css")
    assert re.search(r"body \{[^}]*font:1rem/", css, re.S)


def test_die_bedienzeile_kann_sich_verkleinern():
    """Der Grund für das waagrechte Scrollen bei 320 px und vergrösserter Schrift: ein
    Flex-Element darf sich nicht unter seinen Inhalt verkleinern, und die längste
    Sortier-Option setzte damit eine Mindestbreite von 415 px."""
    css = _asset("app.css")
    regel = re.search(r"\.controls label \{([^}]*)\}", css)
    assert regel
    assert "min-width:0" in regel.group(1)
    assert "white-space:nowrap" not in regel.group(1)
    auswahl = re.search(r"\.controls select \{([^}]*)\}", css, re.S)
    assert "width:100%" in auswahl.group(1)


def test_zuruecksetzen_loest_jedes_kaestchen():
    """Der Zurücksetzen-Knopf pflegt seine Kästchen von Hand, und beim Ergänzen des
    fünften ist genau das passiert: der Zustand war zurückgesetzt, das Häkchen blieb
    stehen. Sichtbar hiess das „nur neu" bei voller Liste.

    Der Test hält die Liste beisammen: jedes Kästchen der Feinauswahl muss im
    Zurücksetzen vorkommen.
    """
    js = _asset("app.js")
    vorlage = re.search(
        r'getElementById\("reset"\)\.addEventListener\("click".*?\n\}\);', js, re.S)
    assert vorlage, "Zurücksetzen-Knopf nicht gefunden"
    zuruecksetzen = vorlage.group(0)

    # Die Kästchen aus der Vorlage lesen, nicht aus dem Verhalten: gefragt ist, was auf
    # der Seite ankreuzbar ist. Auswahlfelder gehen einen anderen Weg (``syncSort``).
    from pathlib import Path

    vorlage_py = (Path(__file__).resolve().parents[1]
                  / "src/winecheck/report/site.py").read_text(encoding="utf-8")
    kaestchen = set(re.findall(r'type="checkbox" id="(f[A-Z]\w*)"', vorlage_py))
    assert len(kaestchen) >= 4, f"zu wenige gefunden: {kaestchen}"
    fehlen = {k for k in kaestchen
              if f'getElementById("{k}").checked = false' not in zuruecksetzen}
    assert not fehlen, f"vom Zurücksetzen nicht erfasst: {sorted(fehlen)}"


def test_neu_bekommt_keine_eigene_farbe():
    """Farbe hat auf dieser Seite drei Aufgaben — Akzent, Urteil, Gold — und „seit
    letzter Woche dabei" ist keine davon. Die Kennzeichnung arbeitet mit Gewicht im
    vorhandenen Grauwert; auffindbar wird sie über das Kästchen."""
    css = _asset("app.css")
    regel = re.search(r"\.pill\.neu \{([^}]*)\}", css)
    assert regel, "die Kennzeichnung fehlt"
    assert "var(--ink)" in regel.group(1)
    for verboten in ("--accent", "--gold", "--good", "--bad", "--typ"):
        assert verboten not in regel.group(1), f"{verboten} erfindet eine vierte Farbaufgabe"


def test_ohne_vorlauf_wird_nichts_als_neu_gezeigt():
    """Beim ersten Lauf ist kein Wein neu, sondern alle sind es. Ein Kästchen, das dann
    jeden Wein zeigt, behauptet eine Auskunft, die es nicht hat."""
    js = _asset("app.js")
    assert "currentRun().hasPrev" in js
    assert 'getElementById("fNeuBox").hidden = !hatVorlauf' in js
    # Eine gesetzte Auswahl muss mitfallen, sonst filtert ein verborgenes Kästchen.
    assert "if (!hatVorlauf && S.onlyNeu)" in js


def test_lange_woerter_duerfen_umbrechen():
    """Vier Ursachen, eine Regel. «Châteauneuf-du-Pape» ist bei 200 % Textgrösse 403 px
    breit, «Weinaktionen» in der Überschrift 317 px — jedes einzelne mehr als ein
    320-px-Fenster, und jedes hätte den Balken für sich allein erzeugt."""
    css = _asset("app.css")
    assert re.search(r"body \{[^}]*overflow-wrap:break-word", css, re.S)


def test_die_kartenansicht_ist_kein_tabellenkasten_mehr():
    """``tr`` und ``td`` waren dort längst Blöcke, ``table`` nicht — und der
    Tabellenkasten hielt eine Mindestbreite aus dem Inhalt seiner Zellen, die sich bei
    vergrösserter Schrift nicht unterschreiten liess."""
    css = _asset("app.css")
    mobil = re.search(r"@media \(max-width: 720px\) \{(.*?)\n  \}", css, re.S)
    assert mobil, "der Handy-Block wurde nicht gefunden"
    mobil = mobil.group(1)
    assert re.search(r"\btable \{[^}]*display:block", mobil)
    # Spaltenname und Wert stehen dort auf einer Zeile; sie muss brechen dürfen.
    zahlen = re.search(r"\.num, \.pl \{([^}]*)\}", mobil)
    assert zahlen and "white-space:normal" in zahlen.group(1)


def test_die_zahlenspalten_bleiben_in_der_tabelle_zusammen():
    """Die Gegenprobe zur vorherigen Regel: in der echten Tabelle muss ``nowrap``
    bleiben, sonst bricht «CHF 23.95» mitten in der Spalte."""
    css = _asset("app.css")
    ohne_mobil = css[:css.index("@media (max-width: 720px)")]
    for wahl in (r"\.num \{([^}]*)\}", r"\.pl \{([^}]*)\}"):
        regel = re.search(wahl, ohne_mobil)
        assert regel, wahl
        assert "white-space:nowrap" in regel.group(1)

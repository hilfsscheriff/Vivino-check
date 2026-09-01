"""Ein Punkt im Diagramm ist nicht immer ein Wein — der Klick muss alle zeigen.

Bei gleichem Preis und gleicher Note liegen die Weine in den *Daten* aufeinander, nicht
bloss optisch; ein kleinerer Punktradius hilft darum nichts. Der Tooltip nannte die
verdeckten immerhin, aber nur mit Namen und Preis, ohne Adresse und auf vier begrenzt.
Gemeldet als „ich will auch den anderen Wein sehen können und dann anklicken für den
Shop".

Geprüft wird das Verhalten und nicht der Quelltext: ``punktInhalt`` wird mit node
ausgeführt, mit zwei Weinen an derselben Stelle — einer mit Note und Shop-Adresse,
einer ohne Fremdbewertung.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ASSETS = Path(__file__).resolve().parents[1] / "src" / "winecheck" / "report" / "assets"

#: Die Umgebung, die ``punktInhalt`` erwartet — knapp gehalten, damit der Test die
#: Funktion prüft und nicht ihre Nachbarschaft.
STUMMEL = """
const esc = s => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;");
const chf = v => (v == null || v === 0) ? "—" : "CHF " + Number(v).toFixed(2);
const valueOf = w => w.value ?? null, valueText = () => "", valueBezug = () => "";
const gebindeText = w => w.gebinde || "";
const vintageSuffix = w => w.vintage ? " " + w.vintage : "";
const istGut = w => (w.rating ?? 0) >= 4.2 && w.price > 0 && w.price <= 20;
const D = { retailers: [{ key: "coop", name: "Coop", domain: "coop.ch" },
                        { key: "divo", name: "DIVO", domain: "divo.ch" }] };
"""

MIT_NOTE = {
    "name": "Puglia IGT Primitivo Negroamaro Elettra Giordano",
    "vintage": "2024", "price": 9.95, "rating": 4.3, "ratingCount": 4374,
    "cheapest": "coop", "url": "https://www.coop.ch/de/p/1016195006",
    "vivinoUrl": "https://www.vivino.com/w/1234", "value": 0.32,
}
OHNE_NOTE = {
    "name": "Cantina Sava Ritardatario Primitivo di Manduria",
    "price": 9.95, "cheapest": "divo", "url": "https://www.divo.ch/wein/4711",
    "vivinoUrl": "https://www.vivino.com/de/explore?search_term=sava",
}


def _inhalt(weine: list[dict]) -> dict:
    js = (ASSETS / "app.js").read_text(encoding="utf-8")
    # Ab ``shopName``: ``punktInhalt`` beschriftet den Shop-Link damit, und die
    # Funktion steht im Quelltext oberhalb von ``detailRows``.
    start = js.index("function shopName(")
    ende = js.index("\nfunction punktZeigen(", start)
    programm = STUMMEL + js[start:ende] + f"""
const weine = {json.dumps(weine)};
const r = punktInhalt(weine);
console.log(JSON.stringify(r));
"""
    lauf = subprocess.run(["node", "-e", programm], capture_output=True, text=True, timeout=60)
    assert lauf.returncode == 0, lauf.stderr
    return json.loads(lauf.stdout)


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node nicht vorhanden")


@needs_node
def test_beide_weine_stehen_mit_beiden_adressen_da():
    r = _inhalt([MIT_NOTE, OHNE_NOTE])
    assert "2 Weine" in r["titel"]
    # Beide Weine, nicht nur der angeklickte.
    assert "Elettra Giordano" in r["html"] and "Ritardatario" in r["html"]
    # Und beide mit ihrer Shop-Adresse — das war der Punkt der Meldung.
    assert 'href="https://www.coop.ch/de/p/1016195006"' in r["html"]
    assert 'href="https://www.divo.ch/wein/4711"' in r["html"]
    assert r["html"].count("Zum Shop") == 2
    # Der Händlername steht am Link, damit man vor dem Klick weiss, wohin es geht.
    assert "Coop" in r["html"] and "DIVO" in r["html"]


@needs_node
def test_der_vivino_link_verspricht_keine_note_die_es_nicht_gibt():
    r = _inhalt([MIT_NOTE, OHNE_NOTE])
    assert "Bei Vivino: 4.3/5" in r["html"]
    assert "Bei Vivino nachsehen" in r["html"]


@needs_node
def test_ein_einzelner_wein_oeffnet_dieselbe_liste():
    """Auch bei einem Wein: ein Klick, der manchmal eine Liste zeigt und manchmal
    ungefragt den Shop öffnet, wäre nicht vorhersehbar."""
    r = _inhalt([MIT_NOTE])
    assert r["titel"] == "Wein an dieser Stelle"
    assert "Zum Shop" in r["html"] and "Elettra" in r["html"]


@needs_node
def test_fehlt_die_shop_adresse_steht_das_da_statt_eines_toten_links():
    ohne_url = {**OHNE_NOTE}
    del ohne_url["url"]
    r = _inhalt([ohne_url])
    assert "keine Adresse hinterlegt" in r["html"]
    assert "Zum Shop" not in r["html"]

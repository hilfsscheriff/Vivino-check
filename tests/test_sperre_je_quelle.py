"""Die Seitensperre fragt je Quelle, ob sie zusammengebrochen ist — nicht nach der Summe.

Vorher verglich sie nur die Gesamtzahl mit der zuletzt ausgelieferten Seite. Das war in
beide Richtungen falsch:

* Am 28.08.2026 lieferte Mövenpick 29 statt 301 Positionen, mit Status „ok" und ohne
  Meldung. Die Summe sank um 7 %, die Seite ging mit rund 270 fehlenden Weinen hinaus.
* Am 09.10.2026 hielt sie einen Lauf an, an dem alles stimmte: 2295 gegen 2717, weil
  Aligros grosse Aktionswoche vorbei war und Aktionis um 07:00 die neue Woche noch
  nicht eingestellt hatte.

Die Zahlen unten sind die gemessenen der gespeicherten Läufe.
"""

import json
import sqlite3

import pytest

from winecheck.cli import _einbrueche


def lauf(**quellen) -> dict:
    """Ein Lauf mit so vielen Weinen je Quelle; ein Wein gehört einer Quelle."""
    weine = [{"retailers": [q]} for q, n in quellen.items() for _ in range(n)]
    return {"wines": weine}


#: Die fünf Läufe vor dem 21.09., auf die grossen Quellen verkürzt.
VOR_21_09 = [
    lauf(vivinoshop=714, schubi=682, aligro=198, moevenpick=255, coop=150),
    lauf(vivinoshop=742, schubi=683, aligro=198, moevenpick=244, coop=247),
    lauf(vivinoshop=750, schubi=682, aligro=263, moevenpick=248, coop=265),
    lauf(vivinoshop=726, schubi=678, aligro=263, moevenpick=252, coop=150),
    lauf(vivinoshop=690, schubi=680, aligro=266, moevenpick=245, coop=227),
]


def test_eine_quelle_auf_null_wird_beim_namen_genannt():
    """21.09.: Aligro lehnte limit=192 ab und lieferte 0."""
    neu = lauf(vivinoshop=699, schubi=682, aligro=0, moevenpick=229, coop=187)
    befund = _einbrueche([neu, *VOR_21_09])
    assert any(b.startswith("aligro 0 statt üblich") for b in befund), befund


def test_der_stille_ausfall_vom_28_08_waere_aufgefallen():
    """Mövenpick 29 statt rund 300, Status „ok" — die alte Regel liess das durch."""
    vorher = [lauf(vivinoshop=700, schubi=674, aligro=295, moevenpick=m, coop=151)
              for m in (304, 304, 301, 290, 300)]
    neu = lauf(vivinoshop=699, schubi=674, aligro=295, moevenpick=29, coop=286)
    befund = _einbrueche([neu, *vorher])
    assert any(b.startswith("moevenpick 29") for b in befund), befund


def test_drei_quellen_per_dns_auf_null():
    """11.09. früh: der Rechner schlief während des Laufs wieder ein."""
    neu = lauf(vivinoshop=0, schubi=682, aligro=263, moevenpick=248, coop=0)
    befund = _einbrueche([neu, *VOR_21_09])
    namen = {b.split()[0] for b in befund}
    assert {"vivinoshop", "coop"} <= namen, befund


def test_eine_kleinere_woche_geht_durch():
    """09.10.: Aligro halbiert, Aktionis bei einem Drittel — echt, nicht kaputt."""
    vorher = [
        lauf(vivinoshop=714, schubi=682, aligro=198, moevenpick=255, coop=150),
        lauf(vivinoshop=699, schubi=682, aligro=0, moevenpick=229, coop=187),
        lauf(vivinoshop=711, schubi=682, aligro=520, moevenpick=229, coop=187),
        lauf(vivinoshop=729, schubi=684, aligro=520, moevenpick=246, coop=195),
        lauf(vivinoshop=720, schubi=693, aligro=511, moevenpick=233, coop=168),
    ]
    neu = lauf(vivinoshop=708, schubi=695, aligro=262, moevenpick=231, coop=98)
    assert _einbrueche([neu, *vorher]) == []


def test_eine_kleine_quelle_zaehlt_nicht():
    """Alloboissons hatte eine Woche nur Getränke ohne Wein in Aktion: 15 → 0 ist
    eine Woche, kein Ausfall."""
    vorher = [lauf(schubi=680, alloboissons=15) for _ in range(5)]
    assert _einbrueche([lauf(schubi=680, alloboissons=0), *vorher]) == []


def test_ohne_geschichte_keine_aussage():
    """Zwei Läufe sind kein Normalwert — dann gilt die Sperre über die ausgelieferte
    Seite, nicht diese."""
    assert _einbrueche([lauf(schubi=0), lauf(schubi=680)]) == []


def test_viele_kleine_verluste_zugleich_fallen_auf():
    """Keine Quelle bricht ein, aber alle verlieren ein Drittel: die grobe Sicherung
    über die Summe."""
    vorher = [lauf(a=300, b=300, c=300, d=300) for _ in range(5)]
    befund = _einbrueche([lauf(a=200, b=200, c=200, d=200), *vorher])
    assert any(b.startswith("insgesamt") for b in befund), befund


def test_der_median_ist_robust_gegen_einen_ausreisser():
    """Ein früherer Ausfall im Fenster verschiebt den Massstab nicht."""
    vorher = [lauf(aligro=263), lauf(aligro=0), lauf(aligro=266), lauf(aligro=263),
              lauf(aligro=198)]
    assert _einbrueche([lauf(aligro=250), *vorher]) == []


# ------------------------------------------------- stammt die Seite von hier?

def test_die_weinzahl_eines_laufs(tmp_path):
    from winecheck.cache import Cache

    c = Cache.open(tmp_path / "c.sqlite")
    c.save_snapshot([{"name": "a"}, {"name": "b"}, {"name": "c"}], label="report")
    lid = c.conn.execute("SELECT max(id) FROM runs").fetchone()[0]
    assert c.weinzahl_des_laufs(lid) == 3
    assert c.weinzahl_des_laufs(lid + 99) is None, "unbekannter Lauf"
    assert c.weinzahl_des_laufs("kein-lauf") is None
    c.close()

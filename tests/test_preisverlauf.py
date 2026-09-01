"""Die Preisreihe — damit „was kostete dieser Wein im Juli" beantwortbar bleibt.

Gefragt wurde, ob die Preise gespeichert werden. Sie wurden es, aber nur als
Nebenwirkung: die Lauf-Schnappschüsse tragen ``prices: {Händler: Preis}``, und sie
verfallen mit ``RUNS_AUFBEWAHRUNG`` nach 26 Lauftagen. Dazu liegen sie im lokalen
Cache, der nicht im Git steht — ein verlorener Rechner nimmt die Reihe mit.

Diese Tabelle ist die Antwort darauf: eine Zeile je Tag, Wein und Händler, ohne
Aufbewahrungsgrenze, mit einem versionierten CSV-Export als Gedächtnis.
"""

import csv
import json
import time
from pathlib import Path

import pytest

from winecheck.cache import Cache
from winecheck.models import PriceConfidence, RetailerPrice, WineRow


@pytest.fixture
def cache(tmp_path):
    c = Cache.open(tmp_path / "test.sqlite")
    yield c
    c.close()


#: Der Wein der Vorgaben. Der Schlüssel wird **gerechnet**, nicht geschrieben: von
#: Hand notiert stand hier „barolo docg produttori", während der Code
#: „barolo produttori barolo" erzeugt — und der Test verglich damit zwei Weine, die es
#: nie gab. Derselbe Schlüssel wie im Bewertungs-Cache, damit Preise und Noten
#: zusammenzuführen sind.
NAME = "Barolo DOCG Produttori del Barolo"


def _beobachtung(**kw):
    from winecheck.names import normalized_name
    grund = dict(name_key=normalized_name(NAME), vintage="2019", haendler="schubi",
                 preis_75cl=29.90, rohpreis=179.40, units=6, flaschen_ml=750,
                 sicherheit="high", name=NAME)
    grund.update(kw)
    return grund


# -- Speichern und Lesen ---------------------------------------------------
def test_eine_beobachtung_kommt_zurueck_wie_sie_hineinging(cache):
    cache.preise_schreiben("2026-08-07", [_beobachtung()])
    reihe = cache.preisverlauf()
    assert len(reihe) == 1
    b = reihe[0]
    assert b["datum"] == "2026-08-07" and b["haendler"] == "schubi"
    assert b["preis_75cl"] == 29.90 and b["rohpreis"] == 179.40
    assert b["units"] == 6 and b["flaschen_ml"] == 750 and b["sicherheit"] == "high"


def test_zwei_laeufe_am_selben_tag_sind_eine_beobachtung(cache):
    """Der Tag ist die Einheit, nicht der Lauf — wie bei ``save_snapshot``.

    Sonst trüge die Reihe an Entwicklungstagen ein Dutzend Punkte für denselben Preis
    und an Ruhetagen keinen.
    """
    cache.preise_schreiben("2026-08-07", [_beobachtung(preis_75cl=29.90)])
    cache.preise_schreiben("2026-08-07", [_beobachtung(preis_75cl=27.50)])
    reihe = cache.preisverlauf()
    assert len(reihe) == 1 and reihe[0]["preis_75cl"] == 27.50


def test_derselbe_wein_bei_zwei_haendlern_sind_zwei_beobachtungen(cache):
    cache.preise_schreiben("2026-08-07", [
        _beobachtung(haendler="schubi", preis_75cl=29.90),
        _beobachtung(haendler="coop", preis_75cl=24.95),
    ])
    assert {b["haendler"] for b in cache.preisverlauf()} == {"schubi", "coop"}


def test_die_reihe_wird_nicht_aufgeraeumt(cache):
    """Ausdrücklich ohne Aufbewahrungsgrenze — 40 Tage über der Lauf-Grenze von 26."""
    for tag in range(1, 41):
        cache.preise_schreiben(f"2026-07-{tag:02d}" if tag <= 31 else f"2026-08-{tag-31:02d}",
                               [_beobachtung(preis_75cl=20 + tag * 0.1)])
    assert len(cache.preis_tage()) == 40


def test_nach_wein_und_seit_datum_abfragbar(cache):
    from winecheck.names import normalized_name
    cache.preise_schreiben("2026-07-01", [_beobachtung(preis_75cl=31.0)])
    cache.preise_schreiben("2026-08-01", [_beobachtung(preis_75cl=29.0)])
    cache.preise_schreiben("2026-08-01", [_beobachtung(name_key="anderer wein",
                                                      preis_75cl=12.0)])
    assert len(cache.preisverlauf(normalized_name(NAME))) == 2
    assert len(cache.preisverlauf(seit="2026-08-01")) == 2
    assert len(cache.preisverlauf(normalized_name(NAME), seit="2026-08-01")) == 1


# -- Aus den Berichtszeilen ------------------------------------------------
def _zeile(name="Barolo DOCG Produttori del Barolo", vintage=2019, preise=None):
    from winecheck.names import dedup_key
    row = WineRow(name=name, vintage=vintage, dedup_key=dedup_key(name, vintage))
    for r, (norm, roh, units) in (preise or {"schubi": (29.90, 179.40, 6)}).items():
        row.prices.append(RetailerPrice(
            retailer=r, price_per_bottle_incl_vat=norm, price_raw=roh,
            price_raw_basis="Karton 6", url="", price_confidence=PriceConfidence.HIGH,
            units=units, bottle_ml=750))
    return row


def test_aus_einer_berichtszeile_wird_je_haendler_eine_beobachtung():
    from winecheck.cli import _preis_beobachtungen
    zeile = _zeile(preise={"schubi": (29.90, 179.40, 6), "coop": (24.95, 24.95, 1)})
    aus = _preis_beobachtungen([zeile])
    assert {b["haendler"] for b in aus} == {"schubi", "coop"}
    schubi = next(b for b in aus if b["haendler"] == "schubi")
    assert schubi["preis_75cl"] == 29.90 and schubi["rohpreis"] == 179.40
    assert schubi["units"] == 6 and schubi["flaschen_ml"] == 750
    assert schubi["name"] == "Barolo DOCG Produttori del Barolo"


def test_ein_angebot_ohne_betrag_ist_keine_beobachtung():
    """Sonst trägt die Reihe Punkte, die keinen Preis kennen — und eine Kurve, die
    dort auf Null fällt, wäre eine Falschaussage."""
    from winecheck.cli import _preis_beobachtungen
    assert _preis_beobachtungen([_zeile(preise={"schubi": (None, None, None)})]) == []


def test_der_klartextname_wird_mitgeschrieben():
    """Eine Reihe aus normalisierten Schlüsseln ist in einem Jahr nicht mehr lesbar."""
    from winecheck.cli import _preis_beobachtungen
    aus = _preis_beobachtungen([_zeile()])
    assert aus[0]["name"] and aus[0]["name_key"] != aus[0]["name"]


# -- Der versionierte Export ----------------------------------------------
def _export(tmp_path, cache_pfad):
    from typer.testing import CliRunner

    from winecheck.cli import app
    ziel = tmp_path / "preisverlauf.csv"
    ergebnis = CliRunner().invoke(app, ["preise-export", "--out", str(ziel),
                                        "--cache", str(cache_pfad)])
    assert ergebnis.exit_code == 0, ergebnis.output
    return ziel, ergebnis.output


def test_der_export_schreibt_die_reihe(tmp_path):
    c = Cache.open(tmp_path / "t.sqlite")
    c.preise_schreiben("2026-08-07", [_beobachtung()])
    c.close()
    ziel, ausgabe = _export(tmp_path, tmp_path / "t.sqlite")
    zeilen = list(csv.DictReader(ziel.open(encoding="utf-8"), delimiter=";"))
    assert len(zeilen) == 1
    assert zeilen[0]["datum"] == "2026-08-07" and zeilen[0]["preis_75cl"] == "29.9"
    assert "1 Beobachtungen" in ausgabe


def test_der_export_verliert_nichts_aus_der_datei(tmp_path):
    """Die härtere Regel als beim Notenexport: geschrieben wird die Vereinigung.

    Eine Beobachtung von gestern kann nicht besser werden — sie darf also auch nicht
    verschwinden, wenn der Cache neu aufgebaut wurde. Ohne diese Regel nimmt ein
    frischer Cache der Reihe ihre Geschichte, und zwar unwiederbringlich, weil die
    Datei die einzige versionierte Fassung ist.
    """
    ziel = tmp_path / "preisverlauf.csv"
    ziel.write_text(
        "datum;name_key;vintage;haendler;preis_75cl;rohpreis;units;flaschen_ml;sicherheit;name\n"
        "2026-07-01;alter wein;2018;coop;11.9;11.9;1;750;high;Alter Wein\n",
        encoding="utf-8")
    c = Cache.open(tmp_path / "t.sqlite")
    c.preise_schreiben("2026-08-07", [_beobachtung()])
    c.close()
    from typer.testing import CliRunner

    from winecheck.cli import app
    e = CliRunner().invoke(app, ["preise-export", "--out", str(ziel),
                                 "--cache", str(tmp_path / "t.sqlite")])
    assert e.exit_code == 0, e.output
    zeilen = list(csv.DictReader(ziel.open(encoding="utf-8"), delimiter=";"))
    assert len(zeilen) == 2
    from winecheck.names import normalized_name
    assert {z["name_key"] for z in zeilen} == {"alter wein", normalized_name(NAME)}


# -- Rückfüllen aus den Schnappschüssen -----------------------------------
def test_das_rueckfuellen_holt_die_preise_aus_den_schnappschuessen(tmp_path):
    """Die Schnappschüsse tragen die Geschichte schon — sie verfällt nur."""
    c = Cache.open(tmp_path / "t.sqlite")
    c.save_snapshot([{"name": "Barolo DOCG Produttori del Barolo", "vintage": 2019,
                      "prices": {"schubi": 31.50, "coop": 28.00}, "units": 6}],
                    label="report")
    c.close()
    from typer.testing import CliRunner

    from winecheck.cli import app
    e = CliRunner().invoke(app, ["preise-nachfuellen", "--cache", str(tmp_path / "t.sqlite")])
    assert e.exit_code == 0, e.output
    c = Cache.open(tmp_path / "t.sqlite")
    reihe = c.preisverlauf()
    c.close()
    assert {b["haendler"] for b in reihe} == {"schubi", "coop"}
    assert {b["preis_75cl"] for b in reihe} == {31.50, 28.00}
    # Aus dem Schnappschuss gibt es keinen Rohpreis — leer heisst hier "unbekannt".
    assert all(b["rohpreis"] is None for b in reihe)


def test_das_rueckfuellen_ueberschreibt_den_genaueren_eintrag_nicht(tmp_path):
    """Der laufende Weg kennt Rohpreis, Gebinde und Flaschengrösse, der Schnappschuss
    nur den normierten Preis. Wo beides existiert, gewinnt der genauere."""
    c = Cache.open(tmp_path / "t.sqlite")
    heute = time.strftime("%Y-%m-%d")
    c.preise_schreiben(heute, [_beobachtung(preis_75cl=29.90)])
    c.save_snapshot([{"name": "Barolo DOCG Produttori del Barolo", "vintage": 2019,
                      "prices": {"schubi": 99.99}, "units": 6}], label="report")
    c.close()
    from typer.testing import CliRunner

    from winecheck.cli import app
    e = CliRunner().invoke(app, ["preise-nachfuellen", "--cache", str(tmp_path / "t.sqlite")])
    assert e.exit_code == 0, e.output
    c = Cache.open(tmp_path / "t.sqlite")
    reihe = c.preisverlauf()
    c.close()
    assert len(reihe) == 1
    assert reihe[0]["preis_75cl"] == 29.90, "der Schnappschuss hat den genaueren Eintrag verdrängt"
    assert reihe[0]["rohpreis"] == 179.40

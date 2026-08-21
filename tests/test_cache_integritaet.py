"""Die Wege, die Bestand vernichten oder sichern — vorher ungetestet.

Aus der Datenintegritätsprüfung: von ``import_ratings``, ``export_ratings``, der
Reissleine des Exports, ``clear_offers``, ``verwerfe_ratings_mit_konfidenz`` und der
Schemawanderung hatte keiner einen Test. Die beiden folgenschwersten Befunde des
Bereichs — der Export, der die Sicherung kürzt, und die Löschung, die zu wenig löscht
— wären beide von einem einzigen kleinen Test erwischt worden.
"""

import json
import time

import pytest

from winecheck.cache import RUNS_AUFBEWAHRUNG, SCHEMA_VERSION, Cache


@pytest.fixture
def cache(tmp_path):
    c = Cache.open(tmp_path / "t.sqlite")
    yield c
    c.close()


def _note(c, name, *, status="exact", note=4.2, vintage=2022):
    c.put_rating("vivino", name, vintage, {"rating": note, "match_confidence": status},
                 status=status)


# -- Schemastand -----------------------------------------------------------
def test_ein_neuer_cache_traegt_den_schemastand(cache):
    """Ohne Eintrag könnte kein Klon feststellen, dass sein Cache älter ist als der
    Code — der Bruch zeigte sich erst als OperationalError zur Laufzeit."""
    assert cache.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_ein_neuerer_cache_wird_abgelehnt(tmp_path):
    """Der Klon-Fall: eine Datei aus einer neueren Fassung des Werkzeugs darf nicht
    stillschweigend mit altem Code geöffnet werden."""
    p = tmp_path / "neu.sqlite"
    c = Cache.open(p)
    c.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 5}")
    c.conn.commit()
    c.close()
    with pytest.raises(RuntimeError, match="Schemastand"):
        Cache.open(p)


# -- Sicherung: Export und Import -----------------------------------------
def test_export_und_import_sind_feldtreu_und_wiederholbar(cache, tmp_path):
    _note(cache, "Barolo Testwein")
    cache.put_rating("vivino", "Ohne Treffer", None, {"rating": None}, status="no_entry")
    cache.put_rating("vivino", "Gesperrt", 2021, {"rating": None},
                     status="blocked", retry_after="2030-01-01T00:00:00")
    satz = cache.export_ratings()
    assert len(satz) == 3

    ziel = Cache.open(tmp_path / "ziel.sqlite")
    try:
        assert ziel.import_ratings(satz) == 3
        # Zweimal einspielen darf nichts verdoppeln und nichts verlieren.
        ziel.import_ratings(satz)
        wieder = ziel.export_ratings()
        assert len(wieder) == 3
        def schluessel(s):
            return {(r["source"], r["name_key"], r["vintage"]) for r in s}
        assert schluessel(wieder) == schluessel(satz)
        gesperrt = next(r for r in wieder if r["status"] == "blocked")
        assert gesperrt["retry_after"] == "2030-01-01T00:00:00"
    finally:
        ziel.close()


def test_import_laesst_vorhandene_stehen(cache, tmp_path):
    """Ohne --overwrite ist der Import ein Auffüllen, kein Ersetzen — sonst nimmt ein
    älterer Austauschstand dem lokalen Lauf seine frischeren Noten."""
    _note(cache, "Barolo Testwein", note=4.4)
    fremd = [{"source": "vivino", "name_key": "barolo testwein", "vintage": "2022",
              "status": "exact", "payload": json.dumps({"rating": 3.0}),
              "fetched_at": time.time(), "retry_after": None}]
    cache.import_ratings(fremd)
    assert cache.get_rating("vivino", "Barolo Testwein", 2022)["rating"] == 4.4
    cache.import_ratings(fremd, overwrite=True)
    assert cache.get_rating("vivino", "Barolo Testwein", 2022)["rating"] == 3.0


# -- Löschwege -------------------------------------------------------------
def test_neubeurteilung_trifft_genau_eine_stufe(cache):
    _note(cache, "Sicher", status="exact")
    _note(cache, "Unsicher", status="fuzzy")
    _note(cache, "Weinebene", status="wine_level")
    assert cache.verwerfe_ratings_mit_konfidenz("vivino", "fuzzy") == 1
    verbleibend = {r["name_key"] for r in cache.export_ratings()}
    assert "unsicher" not in verbleibend
    assert len(verbleibend) == 2


def test_angebote_loeschen_trifft_nur_den_genannten_schluessel(cache):
    cache.put_offer("aktionis", "Wein A", 2022, {"retailer": "coop"})
    cache.put_offer("denner", "Wein B", 2022, {"retailer": "denner"})
    cache.clear_offers("aktionis")
    uebrig = {o.get("retailer") for o in cache.all_offers()}
    assert uebrig == {"denner"}


# -- Aufbewahrung ----------------------------------------------------------
def test_die_lauf_historie_waechst_nicht_unbegrenzt(cache):
    """2.67 MB je Lauf, 74 % der Datei, nach einem Jahr 157 MB — und die Datei liegt
    in einem synchronisierten Ordner."""
    for i in range(RUNS_AUFBEWAHRUNG + 8):
        cache.conn.execute(
            "INSERT INTO runs (started_at, label, snapshot) VALUES (?,?,?)",
            (time.time() - i * 86400, "test", "[]"),
        )
    cache.conn.commit()
    cache.save_snapshot([{"name": "x"}])
    n = cache.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    assert n <= RUNS_AUFBEWAHRUNG


def test_das_juengste_angebot_wird_gemeldet(cache):
    """Grundlage dafuer, dass report einen abgebrochenen rate-Lauf erkennt."""
    assert cache.juengstes_angebot() is None
    cache.put_offer("denner", "Wein", 2022, {"retailer": "denner"})
    assert cache.juengstes_angebot() is not None

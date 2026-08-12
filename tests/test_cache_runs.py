"""Ein Lauf soll eine Aktionswoche sein, kein Neubau.

Regression aus der Webseite: der Lauf-Filter zeigte dreizehn Chips, alle mit dem
Datum „6.8.2026". Es waren dreizehn Neubauten desselben Tages — jedes ``report`` legte
einen eigenen Lauf an. Drei Folgen, alle unerwünscht:

* Der Filter, der Aktionswochen unterscheiden soll, unterschied nichts.
* ``diff.md`` verglich gegen den Neubau von vor zehn Minuten und meldete korrekt
  „keine Änderungen" — formal richtig, praktisch wertlos.
* Die eingebettete Seite wuchs pro Lauf um rund 100 KB auf 1.4 MB.
"""

import time

from winecheck.cache import Cache


def _snap(name: str) -> list[dict]:
    return [{"dedup_key": name, "name": name, "best_price": 9.95}]


def test_same_day_rebuild_replaces_instead_of_appending(tmp_path):
    c = Cache.open(tmp_path / "c.sqlite")
    c.save_snapshot(_snap("erster Bau"), label="report")
    c.save_snapshot(_snap("zweiter Bau"), label="report")
    c.save_snapshot(_snap("dritter Bau"), label="report")

    runs = c.all_runs()
    assert len(runs) == 1, "drei Neubauten am selben Tag sind ein Lauf"
    assert runs[0]["wines"][0]["name"] == "dritter Bau", "der jüngste Stand gilt"
    c.close()


def test_runs_from_different_days_are_kept(tmp_path):
    """Die eigentliche Funktion darf dabei nicht verloren gehen."""
    c = Cache.open(tmp_path / "c.sqlite")
    c.save_snapshot(_snap("letzte Woche"), label="report")
    # Direkt in die Tabelle zurückdatieren — die öffentliche API stempelt auf jetzt.
    c.conn.execute("UPDATE runs SET started_at=?", (time.time() - 8 * 86400,))
    c.conn.commit()
    c.save_snapshot(_snap("diese Woche"), label="report")

    runs = c.all_runs()
    assert len(runs) == 2
    assert runs[0]["wines"][0]["name"] == "diese Woche", "neuester Lauf zuerst"
    c.close()


def test_diff_compares_against_the_previous_week_not_todays_rebuild(tmp_path):
    """``previous_snapshot`` überspringt heutige Läufe. Sonst ist der Vergleichsstand
    der eigene Neubau, und ``diff.md`` bleibt dauerhaft leer."""
    c = Cache.open(tmp_path / "c.sqlite")
    c.save_snapshot(_snap("letzte Woche"), label="report")
    c.conn.execute("UPDATE runs SET started_at=?", (time.time() - 8 * 86400,))
    c.conn.commit()
    c.save_snapshot(_snap("heute vormittag"), label="report")

    _id, prev = c.previous_snapshot()
    assert prev, "es gibt einen Vergleichsstand"
    assert prev[0]["name"] == "letzte Woche"
    c.close()


def test_first_run_has_no_comparison(tmp_path):
    c = Cache.open(tmp_path / "c.sqlite")
    c.save_snapshot(_snap("heute"), label="report")
    _id, prev = c.previous_snapshot()
    assert prev == [], "der erste Lauf vergleicht gegen nichts, nicht gegen sich selbst"
    c.close()


def test_nachtrag_verwirft_nur_treffer_ohne_das_feld(tmp_path):
    """Der Nachtrag-Modus. Kommt ein Feld aus der Vivino-Antwort dazu, tragen die
    bestehenden Einträge es nicht — und bisher half nur ``--refresh``, ein Volllauf
    über alles. Gemessen sind das 1567 Weine bei rund sechs Sekunden, also
    zweieinhalb Stunden.

    Verworfen wird nur, was einen Treffer hat: Einträge ohne Kandidaten können das
    Feld gar nicht tragen, und sie erneut abzufragen ist die Arbeit von
    ``--retry-failed``."""
    from winecheck.cache import Cache

    c = Cache.open(tmp_path / "c.sqlite")
    c.put_rating("vivino", "Mit Feld", 2022, {"status": "exact", "region_name": "Rioja"},
                 status="exact")
    c.put_rating("vivino", "Ohne Feld", 2022, {"status": "exact"}, status="exact")
    c.put_rating("vivino", "Leeres Feld", 2022, {"status": "exact", "region_name": ""},
                 status="exact")
    c.put_rating("vivino", "Kein Treffer", 2022, {"status": "no_entry"}, status="no_entry")
    c.put_rating("vivino", "Gesperrt", 2022, {"status": "blocked"}, status="blocked")

    n = c.verwerfe_ratings_ohne_feld("vivino", "region_name")
    assert n == 2, "genau 'Ohne Feld' und 'Leeres Feld'"

    uebrig = {r["name_key"] for r in c.conn.execute("SELECT name_key FROM ratings")}
    assert any("mit feld" in k for k in uebrig)
    assert any("kein treffer" in k for k in uebrig), "no_entry bleibt — dafür ist --retry-failed da"
    assert any("gesperrt" in k for k in uebrig)
    assert not any("ohne feld" in k for k in uebrig)
    c.close()


def test_nachtrag_ohne_luecke_verwirft_nichts(tmp_path):
    from winecheck.cache import Cache

    c = Cache.open(tmp_path / "c.sqlite")
    c.put_rating("vivino", "A", 2022, {"status": "exact", "taste": {"sweetness": 2.0}},
                 status="exact")
    assert c.verwerfe_ratings_ohne_feld("vivino", "taste") == 0
    c.close()


def test_die_spalte_heisst_wie_ihr_inhalt(tmp_path):
    """``offers.source_key`` trägt den Schlüssel des *Adapters*, nicht den Händler. Für
    den Aggregator Aktionis ist es „aktionis", während die Angebote darunter zu Coop,
    Denner, Otto's, Volg und SPAR gehören — der echte Händler steht im Payload.

    Die Spalte hiess „retailer" und hat dadurch eine falsche Auswertung erzeugt: eine
    Zählung je Händler über diese Spalte ergab, fünf Händler seien auf null gefallen.
    Sie waren vollständig da, nur unter „aktionis" gebucht."""
    from winecheck.cache import Cache

    c = Cache.open(tmp_path / "c.sqlite")
    spalten = {r[1] for r in c.conn.execute("PRAGMA table_info(offers)")}
    assert "source_key" in spalten
    assert "retailer" not in spalten, "der irreführende Name ist weg"
    c.close()


def test_ein_alter_cache_wird_umbenannt_und_behaelt_seine_angebote(tmp_path):
    """Umbenennen statt neu aufbauen: der Cache ist regenerierbar, aber ein voller
    ``fetch`` kostet Anfragen bei siebzehn Quellen und ein ``rate`` danach Stunden."""
    import json
    import sqlite3
    import time

    from winecheck.cache import Cache

    p = tmp_path / "alt.sqlite"
    alt = sqlite3.connect(p)
    alt.executescript(
        "CREATE TABLE offers (retailer TEXT NOT NULL, name_key TEXT NOT NULL, "
        "vintage TEXT NOT NULL, payload TEXT NOT NULL, fetched_at REAL NOT NULL, "
        "PRIMARY KEY (retailer, name_key, vintage));"
    )
    alt.execute("INSERT INTO offers VALUES (?,?,?,?,?)",
                ("aktionis", "ein wein", "2022",
                 json.dumps({"retailer": "coop", "name": "Ein Wein"}), time.time()))
    alt.commit()
    alt.close()

    c = Cache.open(p)
    spalten = {r[1] for r in c.conn.execute("PRAGMA table_info(offers)")}
    assert "source_key" in spalten and "retailer" not in spalten
    rows = list(c.conn.execute("SELECT source_key, payload FROM offers"))
    assert len(rows) == 1
    assert rows[0]["source_key"] == "aktionis"
    # Der echte Händler bleibt im Payload — genau die Unterscheidung, um die es geht.
    assert json.loads(rows[0]["payload"])["retailer"] == "coop"
    c.close()

    # Zweimal öffnen darf nicht scheitern.
    c2 = Cache.open(p)
    assert len(list(c2.conn.execute("SELECT 1 FROM offers"))) == 1
    c2.close()

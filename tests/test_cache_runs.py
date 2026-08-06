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

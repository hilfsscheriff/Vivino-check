"""Ein alter Bewertungsstand darf nicht als frisch durchgehen.

``report`` bricht ab, wenn ``state/rated.json`` älter ist als die Angebote im Cache:
dann ist ``rate`` abgebrochen, und ohne den Abbruch stünden die Preise des Vorlaufs
unter dem heutigen Datum auf der Seite.

Die Prüfung hatte ein Loch. Die alte Fassung von rated.json ist eine nackte Liste
ohne Kopf, und für sie gab ``_rated_stand`` ``None`` zurück — womit die Prüfung sich
selbst übersprang. Am 01.09.2026 hat das zugeschlagen: ``report`` mit ``--cache`` auf
den Publisher-Klon gerichtet, aufgerufen aus einem Klon, dessen rated.json vom
21.08. stammte und noch das alte Format hatte. ``save_snapshot`` behält höchstens
einen Lauf pro Kalendertag — der Lauf des Wochenlaufs war damit weg und durch einen
aus elf Tage alten Bewertungen ersetzt.
"""

import json
import time

from winecheck.cli import _rated_stand


def test_der_zeitpunkt_kommt_aus_dem_kopf(tmp_path):
    p = tmp_path / "rated.json"
    p.write_text(json.dumps({"geschrieben_am": 1788269757.0, "weine": 3, "zeilen": []}),
                 encoding="utf-8")
    assert _rated_stand(p) == 1788269757.0


def test_ohne_kopf_zaehlt_die_aenderungszeit(tmp_path):
    """Das Loch: hier stand früher ``None``, und die Prüfung schaltete sich damit ab."""
    p = tmp_path / "rated.json"
    p.write_text(json.dumps([{"name": "Irgendein Wein"}]), encoding="utf-8")
    import os

    vor_elf_tagen = time.time() - 11 * 86400
    os.utime(p, (vor_elf_tagen, vor_elf_tagen))
    stand = _rated_stand(p)
    assert stand is not None, "eine Datei ohne Kopf darf die Pruefung nicht abschalten"
    assert abs(stand - vor_elf_tagen) < 2


def test_ohne_datei_kein_zeitpunkt(tmp_path):
    assert _rated_stand(tmp_path / "fehlt.json") is None


def test_ein_kopf_ohne_zeitstempel_faellt_ebenfalls_zurueck(tmp_path):
    """Auch ein halber Kopf darf die Pruefung nicht aushebeln."""
    p = tmp_path / "rated.json"
    p.write_text(json.dumps({"zeilen": []}), encoding="utf-8")
    assert _rated_stand(p) is not None

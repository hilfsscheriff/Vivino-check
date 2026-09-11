"""Der Wochenlauf darf nicht auf einem schlafenden Rechner halb arbeiten.

Am 11.09.2026 schlief der Mac um 07:00. launchd holte den Termin beim nächsten
Wartungs-Aufwachen um 07:11:11 nach — und 45 Sekunden später ging der Rechner wieder
schlafen. Der Lauf arbeitete in Schüben weiter: die Abrufphase brauchte 73 statt 7
Minuten, und mitten darin fielen vivinoshop, aktionis und prodega mit „nodename nor
servname provided" aus, dem Fehler einer gescheiterten Namensauflösung. Fünf Quellen
antworteten normal, drei nicht.

Die Reissleine hat die Veröffentlichung zu Recht gestoppt — 810 bewertete Weine
gegenüber 1575 in der Vorwoche. Aufgefallen ist es aber nur, weil die drei Ausfälle
zufällig die grössten Quellen waren. Zwei Dinge fehlten davor: ein Rechner, der wach
bleibt, und eine Prüfung, ob überhaupt ein Netz da ist, **bevor** etwas geholt wird.

Geprüft wird hier das Verhalten des Skripts, in einer eigenen Kopie und ohne Netz.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SKRIPT = Path(__file__).resolve().parents[1] / "scripts" / "wochenlauf.sh"


@pytest.fixture
def kopie(tmp_path: Path) -> Path:
    """Das Skript in einem eigenen Verzeichnis — es leitet sein Projekt aus dem
    eigenen Pfad ab, arbeitet also vollständig in der Kopie."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "state").mkdir()
    ziel = tmp_path / "scripts" / "wochenlauf.sh"
    shutil.copy2(SKRIPT, ziel)
    return ziel


def _lauf(kopie: Path, **umgebung) -> subprocess.CompletedProcess:
    env = {**os.environ, "WINECHECK_NETZ_WARTEN": "0", **umgebung}
    return subprocess.run(["bash", str(kopie)], capture_output=True, text=True,
                          timeout=120, env=env)


def test_ohne_namensaufloesung_wird_nichts_geholt(kopie):
    """Der Kern: lieber gar kein Lauf als ein halber.

    Ein halb gelesener Lauf ist schlimmer als keiner, weil er aussieht wie ein
    Ergebnis — und der alte Stand auf der Seite bleibt stehen, statt von einer
    Teilmenge überschrieben zu werden.
    """
    r = _lauf(kopie, WINECHECK_NETZ_PROBE="kein.echter.name.invalid")
    assert r.returncode == 1, r.stdout
    assert "ABBRUCH" in r.stdout and "keine Namensaufloesung" in r.stdout
    # Und zwar, bevor irgendetwas geholt oder zurückgesetzt wurde.
    assert "Aktionen holen" not in r.stdout
    assert "git reset" not in r.stdout


def test_der_abbruch_kommt_vor_dem_harten_zuruecksetzen(kopie):
    """``git reset --hard`` steht im Skript nach der Netzwache — sonst verwürfe ein
    Lauf ohne Netz die gebaute Seite des letzten."""
    text = SKRIPT.read_text(encoding="utf-8")
    assert text.index("netz_da()") < text.index("git reset --hard")
    assert text.index("keine Namensaufloesung") < text.index("git reset --hard")


def test_der_rechner_wird_wachgehalten(kopie):
    """Ohne Zusicherung schlief der Mac 45 Sekunden nach dem Start wieder ein.

    ``-w $$`` bindet sie an diesen Prozess: sie verschwindet mit dem Lauf und bleibt
    nicht als Dauerzustand zurück. ``-s`` fehlt mit Absicht — es wirkt nur am
    Netzteil, und der Lauf vom 11.09. lief auf Batterie.
    """
    text = SKRIPT.read_text(encoding="utf-8")
    assert "caffeinate -i -w $$ &" in text
    assert "caffeinate -i -s" not in text
    # Und es passiert wirklich, nicht nur im Kommentar.
    r = _lauf(kopie, WINECHECK_NETZ_PROBE="kein.echter.name.invalid")
    assert "Wachhalten aktiv" in r.stdout


def test_die_sperre_wird_auch_beim_abbruch_freigegeben(kopie):
    """Sonst bliebe nach einem Lauf ohne Netz jede weitere Woche gesperrt."""
    r = _lauf(kopie, WINECHECK_NETZ_PROBE="kein.echter.name.invalid")
    assert r.returncode == 1
    assert not (kopie.parent.parent / "state" / ".lauf.lock").exists()

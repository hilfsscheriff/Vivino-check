"""Eine gebaute Seite darf keine bessere ersetzen.

``docs/index.html`` ist ein Bauartefakt im Git, damit GitHub Pages es ausliefert.
Jeder Klon kann es aus **seinem** Cache neu schreiben, und wer zuletzt pusht,
gewinnt. Zwei Klone gibt es hier: das Arbeitsverzeichnis und ~/winecheck, aus dem
der Wochenlauf läuft — mit getrennten Caches.

Am 21.08.2026 stand ein Commit bereit, der die veröffentlichte Seite von 2531 auf
2206 Weine zurückgesetzt hätte. Aufgefallen ist das beim Nachsehen, nicht durch
eine Prüfung.
"""

from pathlib import Path

from winecheck.cli import SEITE_MIN_ANTEIL, _seiten_kennung


def _seite(tmp_path: Path, lauf: str, weine: int) -> Path:
    p = tmp_path / "index.html"
    p.write_text(
        f"<!doctype html>\n<!-- winecheck lauf={lauf} weine={weine} -->\n"
        "<html><body>…</body></html>",
        encoding="utf-8",
    )
    return p


def test_die_kennung_wird_gelesen(tmp_path):
    assert _seiten_kennung(_seite(tmp_path, "42", 2531)) == ("42", 2531)


def test_ohne_datei_keine_kennung(tmp_path):
    assert _seiten_kennung(tmp_path / "gibtsnicht.html") is None


def test_eine_seite_ohne_kennung_blockiert_nichts(tmp_path):
    """Ältere Seiten tragen keine — dann darf die Sperre nicht zuschlagen, sonst
    liesse sich nach dem Umbau nichts mehr bauen."""
    p = tmp_path / "index.html"
    p.write_text("<!doctype html><html><body>alt</body></html>", encoding="utf-8")
    assert _seiten_kennung(p) is None


def test_nur_der_kopf_wird_gelesen(tmp_path):
    """Die Seite ist 1.6 MB gross. Die Kennung steht darum vorn, und die Prüfung
    liest 4 KB statt alles."""
    p = tmp_path / "index.html"
    p.write_text(
        "<!doctype html>\n<!-- winecheck lauf=7 weine=99 -->\n" + "x" * 2_000_000,
        encoding="utf-8",
    )
    assert _seiten_kennung(p) == ("7", 99)


def test_die_schwelle_haette_den_fall_vom_21_08_erwischt():
    """2206 gegen 2531 sind 87 % — unter der Schwelle, also Abbruch."""
    assert 2206 < 2531 * SEITE_MIN_ANTEIL


def test_die_schwelle_laesst_normale_schwankung_durch():
    """Eine Quelle, die eine Woche ausfällt, kostet selten mehr als ein Zehntel.
    Wer die Sperre zu eng zieht, kann irgendwann nichts mehr bauen."""
    assert 2400 > 2531 * SEITE_MIN_ANTEIL

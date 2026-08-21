"""Geprüfte Zuordnungen — für Weine, die Vivinos Suche nicht hergibt.

Der Anlass: „Rocca di Frassinello la Rocca" (CHF 37.50). Vivino führt den Wein
unter /w/14033263 mit ratings_count 0. Der Eintrag ist über keinen automatischen
Weg erreichbar — die Such-API gibt ihn unter keiner Schreibweise aus, und die
Weingutseite listet ihn nicht (27 Weine, keiner davon).

Ohne Eintragung bekam der Wein die Note des gleichnamigen Hauptweins, davor die
des Spitzenweins „Baffonero" für rund CHF 200.
"""

from pathlib import Path

import pytest

from winecheck.zuordnung import finde, laden


def _datei(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "z.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_der_eintrag_wird_gefunden(tmp_path):
    t = laden(_datei(tmp_path, """
version: 1
zuordnungen:
  - name: Rocca di Frassinello la Rocca Maremma Toscana DOC
    ohne_note: true
    url: https://www.vivino.com/de/x/w/14033263
    geprueft_am: "2026-08-21"
    grund: ratings_count 0
"""))
    e = finde("Rocca di Frassinello la Rocca Maremma Toscana DOC", t)
    assert e is not None and e.ohne_note and "14033263" in e.url


def test_die_schreibweise_ist_gleichgueltig(tmp_path):
    """Geschluesselt wird ueber denselben normalisierten Namen wie im Cache — sonst
    trifft ein Eintrag den Wein nur bei genau einer Schreibweise."""
    t = laden(_datei(tmp_path, """
version: 1
zuordnungen:
  - name: Rocca di Frassinello la Rocca Maremma Toscana DOC
    ohne_note: true
    url: u
    geprueft_am: "2026-08-21"
    grund: g
"""))
    assert finde("rocca di frassinello LA ROCCA maremma toscana doc", t) is not None
    assert finde("Rocca di Frassinello le Sughere Maremma Toscana DOC", t) is None


def test_ohne_datei_leere_tabelle(tmp_path):
    assert laden(tmp_path / "gibtsnicht.yaml") == {}


def test_ein_eintrag_ohne_namen_wird_uebersprungen(tmp_path):
    t = laden(_datei(tmp_path, """
version: 1
zuordnungen:
  - url: u
    ohne_note: true
"""))
    assert t == {}


def test_die_echte_datei_ist_lesbar_und_belegt():
    """Jeder Eintrag muss Adresse und Pruefdatum tragen — eine Behauptung ohne Beleg
    hat hier nichts zu suchen.

    Die Liste darf leer sein, und sie ist es: der erste Eintrag war falsch. Er
    stuetzte sich auf einen Namensgleichstand mit einem Vivino-Dublettenstummel und
    entfernte damit eine richtige Note. Die Begruendung steht als Warnung in der YAML.
    """
    t = laden()
    for e in t.values():
        assert e.url.startswith("https://www.vivino.com/"), e.name
        assert e.geprueft_am, e.name
        assert e.grund, e.name


def test_der_eintrag_schlaegt_die_suche():
    """Er steht ueber Cache und Suche. Ohne diesen Vorrang bliebe eine Note vom
    falschen Wein dauerhaft stehen, weil der Cache sie festhaelt."""
    import inspect
    from winecheck.ratings.vivino import VivinoAdapter
    quelle = inspect.getsource(VivinoAdapter.lookup)
    vor_cache = quelle.index("_zuordnung(name)") < quelle.index("self.cache.get_rating")
    assert vor_cache, "die Zuordnung muss vor dem Cache geprueft werden"


def test_ein_namensgleichstand_allein_rechtfertigt_keinen_eintrag():
    """Die Regel, an der ich gescheitert bin — als Text festgehalten, damit sie beim
    naechsten Eintrag gelesen wird.

    Vivino enthaelt Dubletten: von Nutzern angelegte Stummel, die wie der gesuchte
    Wein heissen, aber keine Bewertungen, einen einzigen Jahrgang und lueckenhafte
    Angaben tragen. "la Rocca" wurde auf so einen Stummel eingetragen (/w/14033263,
    nur Sangiovese, 0 Bewertungen) und verlor dadurch die richtige Note 4.2 von
    /w/11745 — derselben Cuvée aus Cabernet Sauvignon, Merlot und Sangiovese mit
    4663 Bewertungen.
    """
    from pathlib import Path
    text = Path("sources/vivino-zuordnung.yaml").read_text(encoding="utf-8")
    assert "Substanz" in text, "die Regel muss in der Datei stehen"
    assert "14033263" in text and "11745" in text, "der Anlassfall muss belegt bleiben"
    modul = Path("src/winecheck/zuordnung.py").read_text(encoding="utf-8")
    assert "Dubletten" in modul

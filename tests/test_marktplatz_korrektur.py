"""Wenn Vivino selbst den falschen Wein an ein Angebot hängt.

Der Marktplatz-Adapter übernimmt Note und Weinname **ohne Namensabgleich** — die
Zuordnung kommt von Vivino, und das ist sonst die verlässlichste Auskunft im ganzen
Werkzeug: kein Suchen, kein Raten, keine Verwechslungsgefahr. Genau darum greift
keine der vier Sicherungen des Abgleichs, wenn sie falsch ist.

Gefunden am 22.08.2026, gemeldet mit einem Scan: Vivinos Schnittstelle liefert den
Wein „Secret Spot Tinto" (4.3 aus 448 Bewertungen) mit einem Gerstl-Link, der den
„Vale do Lacrau Reserva 2022" desselben Hauses verkauft — 13'017 Bewertungen unter
eigenem Eintrag. Zwei verschiedene Weine, ein Datensatz.

Eine Stichprobe von zwölf weiteren Marktplatz-Angeboten war fehlerfrei. Es ist also
ein Ausreisser, kein Muster — aber einer, den nur eine geprüfte Gegenauskunft heilt.
"""

from pathlib import Path

import pytest
import yaml

from winecheck.zuordnung import marktplatz_laden

DATEI = Path(__file__).resolve().parents[1] / "sources" / "vivino-zuordnung.yaml"


def test_die_korrektur_ist_geladen_und_belegt():
    tabelle = marktplatz_laden(DATEI)
    assert tabelle, "keine Marktplatz-Korrektur geladen"
    for url, e in tabelle.items():
        assert url.startswith("http"), url
        assert e.name and e.geprueft_am, e
        # Ein Eintrag ohne Begründung ist eine Behauptung. Die Datei verlangt Substanz.
        assert len(e.grund) > 120, f"{e.name}: Begründung zu knapp"


def test_der_belegte_fall_traegt_seine_substanz():
    """Die Begründung muss nachprüfbar sein: Traubensatz, Produzent, beide Adressen."""
    e = marktplatz_laden(DATEI)[
        "https://www.gerstl.ch/2022-secret-spot-wines-doc-douro-prt-265715-2022/p"]
    assert e.name == "Vale do Lacrau Reserva"
    for beleg in ("Touriga Franca", "Tempranillo", "Secret Spot Wines",
                  "w/6467422", "w/1368855"):
        assert beleg in e.grund, f"{beleg!r} fehlt in der Begründung"


def test_kein_eintrag_ohne_adresse_oder_name():
    """Halbe Einträge werden übergangen statt halb angewandt."""
    import tempfile
    roh = {"marktplatz": [{"url": "https://x/y"}, {"name": "Nur ein Name"},
                          {"url": "https://a/b", "name": "Gültig", "grund": "x",
                           "geprueft_am": "2026-08-22"}]}
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        yaml.safe_dump(roh, f)
        pfad = Path(f.name)
    tabelle = marktplatz_laden(pfad)
    assert list(tabelle) == ["https://a/b"]


def test_der_adapter_verwirft_die_mitgelieferte_note():
    """Der Kern: die falsche Note darf nicht in den Bewertungs-Cache gesät werden."""
    from winecheck.adapters.vivinoshop import VivinoShopAdapter
    from winecheck.config import SourceConfig

    cfg = SourceConfig(key="vivinoshop", name="Vivino Aktionen", adapter="vivinoshop",
                       domain="vivino.com", vat_included=True)
    a = VivinoShopAdapter(cfg, fetcher=None)
    treffer = {
        "price": {"amount": 18.8, "discounted_from": 25.0, "bottle_type": {"id": 1},
                  "url": "https://www.gerstl.ch/2022-secret-spot-wines-doc-douro-"
                         "prt-265715-2022/p"},
        "vintage": {"year": 2022, "id": 1,
                    "statistics": {"ratings_average": 4.3, "ratings_count": 448},
                    "wine": {"id": 1368855, "name": "Tinto",
                             "winery": {"name": "Secret Spot"}}},
    }
    offer = a._offer(treffer)
    assert offer is not None
    assert offer.name == "Vale do Lacrau Reserva"
    assert a.bewertungen == [], "die falsche Note wurde gesät"
    assert any("verworfen" in h for h in a._hinweise), a._hinweise


def test_ohne_korrektur_bleibt_die_note_erhalten():
    """Der Normalfall darf nicht leiden — zwölf von zwölf Stichproben waren richtig."""
    from winecheck.adapters.vivinoshop import VivinoShopAdapter
    from winecheck.config import SourceConfig

    cfg = SourceConfig(key="vivinoshop", name="Vivino Aktionen", adapter="vivinoshop",
                       domain="vivino.com", vat_included=True)
    a = VivinoShopAdapter(cfg, fetcher=None)
    treffer = {
        "price": {"amount": 24.9, "discounted_from": 32.0, "bottle_type": {"id": 1},
                  "url": "https://www.bignens.ch/irgendein-wein"},
        "vintage": {"year": 2021, "id": 2,
                    "statistics": {"ratings_average": 4.1, "ratings_count": 900},
                    "wine": {"id": 999, "name": "Pommard",
                             "winery": {"name": "Louis Latour"}}},
    }
    offer = a._offer(treffer)
    assert offer is not None and offer.name == "Louis Latour Pommard"
    assert len(a.bewertungen) == 1 and a.bewertungen[0]["rating"] == 4.1

"""„Blockiert" muss eine Messung von heute sein, kein Zitat aus der Registry.

Coop, Migros und TopCC stehen mit ``enabled: false`` in der Registry, und der Lauf
trug ihre Sperrmeldung bisher in den Report, **ohne dass je eine Anfrage hinausging**.
Die Übersicht sagte damit jede Woche dasselbe, mit einem Prüfdatum vom August. Hätte
Coop seinen DataDome abgeschaltet oder TopCC seine robots.txt gelockert, wäre es nie
aufgefallen.

Der Fühler stellt eine gewöhnliche Anfrage und hält fest, was zurückkommt. Beobachten
ist nicht umgehen: kommt eine Challenge, bleibt es dabei. Und fällt eine Sperre, wird
die Quelle **nicht** von selbst eingeschaltet — neues Crawling zu beginnen ist eine
Entscheidung, die dem Menschen gehört. Die Meldung sagt es dafür deutlich.
"""

import pytest

from winecheck.cli import _sperre_pruefen
from winecheck.config import SourceConfig
from winecheck.fetching import Blocked


class _Netz:
    """Ein Fetcher-Ersatz, der eine bestimmte Antwort gibt und die Ziele mitschreibt."""

    def __init__(self, *, antwort=None, fehler=None, robots=True):
        self.antwort, self.fehler, self.robots = antwort, fehler, robots
        self.geholt: list[str] = []
        self.robots_gefragt: list[str] = []

    def get(self, url, **kw):
        self.geholt.append(url)
        if self.fehler:
            raise self.fehler
        return self.antwort

    def robots_allows(self, url):
        self.robots_gefragt.append(url)
        if isinstance(self.robots, Exception):
            raise self.robots
        return self.robots


def _antwort(status=200):
    return type("Res", (), {"ok": status == 200, "status_code": status, "text": ""})()


def cfg(**kw) -> SourceConfig:
    grund = {"key": "coop", "name": "Coop", "blocked_by": "datadome",
             "fuehler_url": "https://www.coop.ch/de/weine/aktionen/c/SPECIAL_OFFERS_WINE",
             "verified_at": "2026-08-05"}
    return SourceConfig(**{**grund, **kw})


def test_die_challenge_bleibt_eine_challenge():
    netz = _Netz(fehler=Blocked("datadome-Challenge — nicht umgangen", kind="datadome"))
    steht, meldung = _sperre_pruefen(netz, cfg())
    assert steht is True
    assert "datadome" in meldung
    # Genau eine Anfrage, an das benannte Ziel.
    assert netz.geholt == [cfg().fuehler_url]


def test_eine_gefallene_sperre_wird_laut_gemeldet():
    """Der Fall, für den der Fühler gebaut ist."""
    netz = _Netz(antwort=_antwort(200))
    steht, meldung = _sperre_pruefen(netz, cfg())
    assert steht is False
    assert "HTTP 200" in meldung
    assert "einschalten" in meldung, "die Meldung muss zum Handeln auffordern"


def test_die_quelle_schaltet_sich_nicht_selbst_ein():
    """Auch bei HTTP 200 bleibt der Status blockiert.

    Mit dem Crawlen einer Quelle zu beginnen, die der Besitzer abgeschaltet hat, wäre
    eine Entscheidung über sein Verhalten gegenüber einem fremden Server. Der Fühler
    meldet, er handelt nicht.
    """
    import inspect

    from winecheck import cli

    quelle = inspect.getsource(cli.fetch)
    stelle = quelle[quelle.index("_sperre_pruefen"):]
    assert 'status="blocked"' in stelle[:600], "der Bericht muss blockiert bleiben"
    assert "cfg.enabled = True" not in quelle and "enabled=True" not in stelle[:600]


def test_bei_robots_wird_nichts_abgerufen():
    """Nur die robots.txt auswerten — sie zu lesen ist immer erlaubt, und der Inhalt
    dahinter geht uns nichts an, solange sie ihn verbietet."""
    netz = _Netz(robots=False)
    steht, meldung = _sperre_pruefen(
        netz, cfg(key="topcc", blocked_by="robots",
                  fuehler_url="https://files.cdn.ipaper.io/"))
    assert steht is True
    assert "robots.txt verbietet" in meldung
    assert netz.geholt == [], "bei einer robots-Sperre wird nichts geholt"
    assert netz.robots_gefragt == ["https://files.cdn.ipaper.io/"]


def test_eine_gelockerte_robots_faellt_auf():
    netz = _Netz(robots=True)
    steht, meldung = _sperre_pruefen(
        netz, cfg(key="topcc", blocked_by="robots",
                  fuehler_url="https://files.cdn.ipaper.io/"))
    assert steht is False and "erlaubt" in meldung


def test_das_fuehlerziel_ist_nicht_die_hauptseite():
    """TopCCs Sperre liegt auf einem fremden CDN, nicht auf topcc.ch.

    Ohne eigenes Ziel führe der Fühler auf ``shop_root``, bekäme dort HTTP 200 und
    meldete eine gefallene Sperre, die es nie gab. Darum steht das Ziel in der
    Registry — und dort steht es auch wirklich.
    """
    from winecheck.config import load_registry

    topcc = load_registry().retailers["topcc"]
    assert topcc.fuehler_url and "ipaper" in topcc.fuehler_url
    assert topcc.fuehler_url != topcc.shop_root


def test_ein_kaputter_fuehler_kippt_keinen_lauf():
    """Ein Netzfehler ist keine Auskunft über die Sperre — und kein Grund, den
    Wochenlauf abzubrechen."""
    netz = _Netz(fehler=RuntimeError("DNS weg"))
    steht, meldung = _sperre_pruefen(netz, cfg())
    assert steht is True
    assert "nicht erreichbar" in meldung


def test_ohne_ziel_wird_nichts_behauptet():
    netz = _Netz(antwort=_antwort(200))
    steht, meldung = _sperre_pruefen(netz, cfg(fuehler_url="", urls=[], shop_root=""))
    assert steht is True
    assert "kein Fühler hinterlegt" in meldung
    assert netz.geholt == []


@pytest.mark.parametrize("key", ["coop", "migros", "topcc"])
def test_jede_gesperrte_quelle_hat_ein_ziel(key):
    """Sonst wäre der Fühler für sie stumm, und das fiele nicht auf."""
    from winecheck.config import load_registry

    c = load_registry().retailers[key]
    assert c.status == "blocked" and not c.enabled
    assert c.fuehler_url or c.urls or c.shop_root, f"{key} hat kein Fühlerziel"

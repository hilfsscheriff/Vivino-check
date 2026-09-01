"""Ein Zuordnungseintrag *mit* Note muss auch wirken.

Die Liste in ``sources/vivino-zuordnung.yaml`` ist für Weine gedacht, deren richtigen
Vivino-Eintrag kein automatischer Weg findet: die Suche gibt ihn nicht aus, die
Weingutseite listet ihn nicht. Umgesetzt war davon aber nur der Sonderfall „Vivino
führt den Wein ohne verwertbare Note" — ein Eintrag, der eine Adresse *mit* Note
nannte, wurde gelesen und stillschweigend übergangen.

Aufgefallen am 01.09.2026 am Pintia Toro: für ihn wurde ein Eintrag angelegt und
geprüft, und der Wein blieb danach ``no_entry``, obwohl /w/77172 für den Jahrgang 2020
eine 4.5 aus 2111 Bewertungen trägt. Der Eintrag war damit wirkungslos, und die
Begründung im Commit behauptete etwas, das nicht stimmte.

Geprüft wird gegen eine nachgebaute Weinseite in der Form, die Vivino ausliefert —
kein Netz.
"""

import json
from dataclasses import dataclass

import pytest

from winecheck.fetching import Blocked
from winecheck.models import VivinoStatus
from winecheck.ratings.vivino import (
    VivinoAdapter,
    _fenster_aus_seite,
    _kandidaten_aus_seite,
)
from winecheck.zuordnung import Eintrag


def weinseite(*, jahr=2020, jahrgang_note=4.5, jahrgang_zahl=2111,
              wein_note=4.4, wein_zahl=79085, fenster=(2023, 2028)) -> str:
    """Eine Weinseite in Vivinos Form: ``wine`` und ``vintage`` nebeneinander.

    Genau darin unterscheidet sie sich von der Suchantwort, in der der Wein
    *innerhalb* des Jahrgangs steht — und genau das muss die Auswertung angleichen.
    """
    roh = {
        "wine": {
            "id": 77172, "name": "Toro", "seo_name": "toro", "type_id": 1,
            "winery": {"name": "Pintia", "seo_name": "pintia"},
            "region": {"name": "Toro", "country": {"name": "Spanien"}},
            "style": {"name": "Toro Rot Spanien"},
            "statistics": {"ratings_average": wein_note, "ratings_count": wein_zahl},
        },
        "vintage": {
            "id": 162989737, "year": jahr, "name": f"Pintia Toro {jahr}",
            "statistics": {"ratings_average": jahrgang_note,
                           "ratings_count": jahrgang_zahl},
        },
    }
    fenster_json = ('"drinking_window":{"start_year":%s,"end_year":%s}'
                    % (fenster[0] or "null", fenster[1] or "null"))
    # Ohne Leerzeichen serialisiert, und das ist keine Kosmetik: die Auswertung
    # findet die Objekte über die Marke ``{"wine":{"id":``. Schriebe Vivino sein JSON
    # eines Tages formatiert, fände sie nichts mehr — dann meldet der Zuordnungsweg
    # „Seite nicht auswertbar" mit der Adresse und erfindet keine Note. Genau so soll
    # es sich verhalten, darum steht die Empfindlichkeit hier als Test-Voraussetzung.
    return ("<!doctype html><html><body><div data-props='"
            + json.dumps(roh, separators=(",", ":")) + "'></div><script>{"
            + fenster_json + "}</script></body></html>")


EINTRAG = Eintrag(
    name="Toro Pintia Parker 94, DO 2020 Vega Sicilia",
    url="https://www.vivino.com/de/w/77172",
    grund="substanzgeprüft",
    geprueft_am="2026-09-01",
)


@dataclass
class Antwort:
    text: str
    status_code: int = 200

    @property
    def ok(self) -> bool:
        return self.status_code == 200


class Netz:
    """Ein Fetcher, der immer dieselbe Seite liefert und die Abrufe mitschreibt."""

    def __init__(self, seite: str = "", status: int = 200, blockiert: bool = False):
        self.seite, self.status, self.blockiert = seite, status, blockiert
        self.gerufen: list[str] = []

    def get(self, url, **kw):
        self.gerufen.append(url)
        if self.blockiert:
            raise Blocked("429", kind="http", retry_after="2026-09-02")
        return Antwort(self.seite, self.status)


@pytest.fixture
def adapter(monkeypatch):
    """Der echte Adapter, aber mit genau diesem einen Zuordnungseintrag."""
    import winecheck.ratings.vivino as v

    monkeypatch.setattr(v, "_ZUORDNUNG", {"toro pintia vega sicilia": EINTRAG})

    def bauen(netz):
        return VivinoAdapter(fetcher=netz, cache=None)

    return bauen


def test_der_eintrag_liefert_die_jahrgangsnote(adapter):
    netz = Netz(weinseite())
    r = adapter(netz).lookup(EINTRAG.name, 2020)
    assert r.status is VivinoStatus.EXACT
    assert r.rating == 4.5 and r.rating_count == 2111
    assert r.matched_name == "Pintia Toro 2020"
    assert "/w/77172" in r.url
    # Die Herkunft der Auskunft gehört in die Bemerkung — sie landet im Cache und
    # ist damit später noch nachvollziehbar.
    assert "geprüfte Zuordnung vom 2026-09-01" in r.note


def test_der_jahrgang_steht_an_der_adresse(adapter):
    """Ohne ``?year=`` liefert Vivino keine Jahrgangsstatistik — dasselbe Problem wie
    beim Trinkfenster, wo es schon einmal aufgefallen ist."""
    netz = Netz(weinseite())
    adapter(netz).lookup(EINTRAG.name, 2020)
    assert netz.gerufen == ["https://www.vivino.com/de/w/77172?year=2020"]


def test_das_trinkfenster_kostet_keinen_zweiten_abruf(adapter):
    """Es steht in derselben Antwort wie die Note."""
    netz = Netz(weinseite(fenster=(2023, 2028)))
    r = adapter(netz).lookup(EINTRAG.name, 2020)
    assert (r.drink_from, r.drink_until) == (2023, 2028)
    assert len(netz.gerufen) == 1


def test_ohne_jahrgangsnote_faellt_es_auf_die_weinebene(adapter):
    """Der Händlerjahrgang ist nicht bewertet: dann die Note des Weins, klar benannt —
    nicht die Jahrgangsnote eines anderen Jahrgangs."""
    netz = Netz(weinseite(jahr=2018, jahrgang_zahl=2, jahrgang_note=None))
    r = adapter(netz).lookup(EINTRAG.name, 2020)
    assert r.status is VivinoStatus.WINE_LEVEL
    assert r.rating == 4.4 and r.rating_count == 79085


def test_eine_unlesbare_seite_erfindet_keine_note(adapter):
    netz = Netz("", status=503)
    r = adapter(netz).lookup(EINTRAG.name, 2020)
    assert r.status is VivinoStatus.NO_ENTRY
    assert r.rating is None
    # Die Adresse gehört in die Meldung, sonst ist der Eintrag nicht nachprüfbar.
    assert EINTRAG.url in r.note


def test_eine_ratenbegrenzung_wird_als_solche_gemeldet(adapter):
    """Sonst sähe sie wie „kein Eintrag" aus und der Wein käme nie wieder dran.

    Anders als bei der Weingutseite darf ``Blocked`` hier nicht geschluckt werden:
    dort ist der Abruf ein Zusatzversuch nach einer Suche, hier ist er der einzige Weg
    zur Auskunft.
    """
    r = adapter(Netz(blockiert=True)).lookup(EINTRAG.name, 2020)
    assert r.status is VivinoStatus.BLOCKED
    assert r.retry_after == "2026-09-02"


def test_der_eintrag_schlaegt_einen_falschen_cache_eintrag(adapter, monkeypatch):
    """Ein Eintrag entsteht, weil der automatische Weg danebenlag — und dieses
    Ergebnis liegt im Cache. Würde der Cache zuerst gelesen, bliebe die falsche Note
    dauerhaft stehen."""
    gelesen = []

    class Cache:
        def get_rating(self, *a, **kw):
            gelesen.append(a)
            return {"status": "no_entry", "url": "https://www.vivino.com/de/explore"}

        def put_rating(self, *a, **kw):
            pass

    netz = Netz(weinseite())
    ad = VivinoAdapter(fetcher=netz, cache=Cache())
    r = ad.lookup(EINTRAG.name, 2020)
    assert not gelesen, "der Cache darf bei einer geprüften Zuordnung nicht befragt werden"
    assert r.rating == 4.5


def test_die_auswertung_ist_rein():
    """Beide Auswertungen laufen ohne Netz — damit sind sie vollständig prüfbar."""
    seite = weinseite()
    kandidaten = _kandidaten_aus_seite(seite)
    assert len(kandidaten) == 1
    c = kandidaten[0]
    assert (c.year, c.vintage_avg, c.vintage_count) == (2020, 4.5, 2111)
    assert (c.wine_avg, c.wine_count) == (4.4, 79085)
    assert _fenster_aus_seite(seite) == (2023, 2028)
    # Und auf einem leeren oder fremden Text sagt sie nichts, statt zu raten.
    assert _kandidaten_aus_seite("") == []
    assert _fenster_aus_seite("<html>nichts</html>") == (None, None)

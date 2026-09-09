"""Der lebende Index von Flaschenpost — erreichbar ist er nicht, lesbar schon.

``/api/search`` ist der Aufruf, den der Shop selbst macht: 377 rabattierte
Produktgruppen von 20'753 im Sortiment, publiziert, mit lebenden Adressen und — anders
als bei ``/api/products`` — **mit Jahrgang**. Für einen ehrlichen Client antwortet er
mit HTTP 403 und ``cf-mitigated: challenge``; dasselbe gilt für ``/aktionen`` und sogar
für die Sitemap, auf die die robots.txt verweist. Umgangen wird das nicht.

Der Lesecode steht trotzdem da, damit die Aktionen von selbst kommen, falls die
Challenge je fällt. Damit er dann nicht raten muss, ist er hier gegen **echte
aufgezeichnete Antworten** geprüft: 114 Antworten einer Untersuchung vom 09.09.2026,
reduziert auf die Felder, die die Aufzählung braucht, plus vier vollständige
Produktobjekte für die Feldabbildung.

Die wichtigste Zusicherung ist nicht, dass etwas gefunden wird, sondern dass eine
**Teilmenge nie durchgeht**: die Suche gibt höchstens zwölf Treffer heraus, und eine
stillschweigend halbe Aufzählung sähe auf der Seite vollständig aus.
"""

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from winecheck.adapters.flaschenpost import (
    AKTIONS_FACETTE,
    FlaschenpostAdapter,
    _blaetter,
    _rappen,
    _such_payload,
    _teilpreis,
)
from winecheck.config import SourceConfig
from winecheck.fetching import Blocked

VORLAGEN = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def aufgezeichnet() -> dict:
    with gzip.open(VORLAGEN / "flaschenpost-suche.json.gz", "rt", encoding="utf-8") as f:
        return json.load(f)


def _replay(aufgezeichnet: dict):
    """Eine Suche, die aus den aufgezeichneten Antworten liest.

    Der Schlüssel ist der Hash der Anfrage. Damit prüft der Replay nicht nur das
    Ergebnis, sondern jeden Schritt: teilt die Aufzählung anders als damals, fragt sie
    nach einer Antwort, die es nicht gibt — und der Test sagt genau das.
    """
    import hashlib

    gerufen: list[dict] = []

    def suche(payload: dict) -> dict:
        gerufen.append(payload)
        h = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        satz = aufgezeichnet.get(h)
        if satz is None:
            raise AssertionError(
                "Anfrage nicht aufgezeichnet — die Aufteilung weicht von der "
                f"gepruefen ab: {json.dumps(payload, ensure_ascii=False)}"
            )
        # Die Vorlage haelt Facetten als Abbildung; die echte Antwort ist eine Liste.
        # Zurueckgebaut, damit der Lesecode an der echten Form haengt.
        return {
            "resultsNumber": satz["resultsNumber"],
            "products": satz["products"],
            "facets": [
                {"facetName": name, "values": f["values"], "stats": f["stats"]}
                for name, f in satz["facets"].items()
            ],
        }

    return suche, gerufen


def test_die_aufzaehlung_findet_alles(aufgezeichnet):
    """Vollständig heisst: so viele Produktgruppen wie der Server selbst meldet."""
    suche, gerufen = _replay(aufgezeichnet)
    treffer = _blaetter(suche, _such_payload(AKTIONS_FACETTE))
    assert len(treffer) == 393, "393 SKU standen im aufgezeichneten Lauf"
    gruppen = {p["productID"] for p in treffer.values()}
    assert len(gruppen) == 377, "377 Produktgruppen meldet die Suche als Trefferzahl"
    # 114 Anfragen kostete das damals. Mehr waere eine Verschlechterung, die niemand
    # bemerkt haette.
    assert len(gerufen) <= 114, f"{len(gerufen)} Anfragen statt 114"


def test_eine_teilmenge_geht_nicht_durch():
    """Die Wache, um die es geht. Der Server meldet 20 Treffer, liefert 12 und bietet
    keine Facette zum Teilen — dann bricht die Aufzählung ab, statt 12 zu melden."""
    def suche(payload):
        return {"resultsNumber": 20,
                "products": [{"sku": str(i), "productID": str(i)} for i in range(12)],
                "facets": []}

    with pytest.raises(Blocked) as fehler:
        _blaetter(suche, _such_payload(AKTIONS_FACETTE))
    assert "Antwortform verändert" in str(fehler.value)


def test_ein_unteilbarer_preispunkt_bricht_ab():
    """Ein einzelner Preis mit mehr Treffern als das Fenster, und keine Facette mit
    mehr als einem Wert: auch das ist ein Abbruch und keine Teilmenge."""
    def suche(payload):
        return {
            "resultsNumber": 30,
            "products": [{"sku": str(i), "productID": str(i)} for i in range(12)],
            "facets": [
                {"facetName": "activePrice",
                 "values": [["19.95", 30]], "stats": {"min": 19.95, "max": 19.95}},
                {"facetName": "country", "values": [["Schweiz", 30]], "stats": {}},
            ],
        }

    with pytest.raises(Blocked) as fehler:
        _blaetter(suche, _such_payload(AKTIONS_FACETTE))
    assert "nicht weiter teilbar" in str(fehler.value)


def test_rappen_rechnet_ohne_fliesskomma_fehler():
    """``19.95 * 100`` ergibt in Fliesskomma 1994.9999… — und ``int()`` daraus 1994."""
    assert _rappen("19.95") == 1995
    assert _rappen(19.95) == 1995
    assert _rappen("7014.95") == 701495


def test_der_teilpunkt_bleibt_im_bereich():
    werte = [("10.00", 5), ("20.00", 5), ("30.00", 90)]
    mitte = _teilpreis(werte, 1000, 3000)
    assert 1000 <= mitte < 3000
    # Ohne brauchbare Werte die geometrische Mitte, statt einer Ausnahme.
    assert _teilpreis([], 1000, 3000) == 2000


# ---------------------------------------------------------------- Feldabbildung

@pytest.fixture(scope="module")
def treffer() -> list[dict]:
    return json.loads((VORLAGEN / "flaschenpost-treffer.json").read_text(encoding="utf-8"))


@pytest.fixture
def adapter() -> FlaschenpostAdapter:
    cfg = SourceConfig(key="flaschenpost", name="Flaschenpost", adapter="flaschenpost",
                       domain="flaschenpost.ch", wine_only=True)
    return FlaschenpostAdapter(cfg, fetcher=None)


def test_der_jahrgang_kommt_mit(adapter, treffer):
    """Der Gewinn gegenüber ``/api/products``: dort gibt es keinen Jahrgang, und ohne
    ihn fehlt die Trinkreife und der Vivino-Treffer bleibt auf Weinebene."""
    angebote = [adapter._aus_suchtreffer(p) for p in treffer]
    angebote = [a for a in angebote if a]
    assert angebote, "aus vier echten Treffern muss mindestens einer ein Angebot sein"
    assert all(a.vintage for a in angebote), [a.name for a in angebote if not a.vintage]


def test_das_gebinde_steht_als_zahl_da(adapter, treffer):
    """``packageSize`` sagt die kleinste Abnahme — geraten wird nichts.

    Der Sechserpack im Bestand ist der Fall, für den die Seite "nur 6er-Gebinde"
    anschreibt; ohne die Zahl stufte die Normalisierung den Preis als unsicher ein und
    nahm den Wein aus der Rangliste.
    """
    nach_sku = {}
    for p in treffer:
        a = adapter._aus_suchtreffer(p)
        if a:
            nach_sku[str(p["sku"])] = a
    sechser = nach_sku.get("1214202")
    assert sechser is not None and sechser.units == 6, "1214202 ist ein Sechserpack"
    dreier = nach_sku.get("1186311")
    assert dreier is not None and dreier.units == 3 and dreier.bottle_ml == 1500


def test_die_adresse_traegt_das_sprachpraefix(adapter, treffer):
    """Ohne ``/de/`` antwortet die Webseite mit 404 — nachgemessen an einem lebenden
    Wein, und der Grund, weshalb 477 Adressen einmal ins Leere führten."""
    angebot = adapter._aus_suchtreffer(treffer[0])
    assert angebot is not None
    assert angebot.url.startswith("https://www.flaschenpost.ch/de/")
    assert "?" not in angebot.url, "der Query-String der Schnittstelle gehoert nicht dazu"


def test_der_preis_kommt_aus_rappen(adapter, treffer):
    angebot = adapter._aus_suchtreffer(treffer[0])
    roh = treffer[0]["price"]
    assert angebot.price_raw == pytest.approx(roh["discountPrice"]["amount"] / 100)
    assert angebot.reference_price == pytest.approx(roh["initialPrice"]["amount"] / 100)
    assert angebot.reference_price > angebot.price_raw


@pytest.mark.parametrize("rabatt,soll", [
    ({"isActive": True}, True),
    ({"isActive": False}, False),
    ({"isActive": True, "validUntil": "2026-01-01T00:00:00.000Z"}, False),
    ({"isActive": True, "validFrom": "2099-01-01T00:00:00.000Z"}, False),
    ({"isActive": True, "validFrom": "2026-09-01T00:00:00.000Z",
      "validUntil": "2026-09-30T00:00:00.000Z"}, True),
    # Unlesbares Datum widerspricht nicht: ``isActive`` ist die Aussage des Shops.
    ({"isActive": True, "validUntil": "irgendwann"}, True),
])
def test_nur_was_heute_gilt(rabatt, soll):
    jetzt = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
    assert FlaschenpostAdapter._rabatt_gilt(rabatt, jetzt) is soll

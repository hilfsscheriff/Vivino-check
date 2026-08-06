"""Kritikernoten, die der Händler selbst ausweist.

Falstaff ist auf ``.com``, ``.at`` und ``.de`` vollständig per Cloudflare gesperrt und
hat keine API-Subdomain — direkter Zugang gibt es nur per Umgehung, und die bleibt aus.
Mövenpick schreibt die Punkte aber selbst ins Produkt: ``Falstaff 92/100``.

Der Vorteil gegenüber einer eigenen Falstaff-Abfrage ist grundsätzlich: die Note hängt
am **exakten** Produkt, also kein Namens-Matching und damit kein Fehlzuordnungsrisiko.
Der Nachteil steht in jeder Zeile — vom Händler berichtet, nicht bei Falstaff geprüft.
"""

import pytest

from winecheck.adapters.base import parse_critic_scores
from winecheck.aggregate import merge_offers
from winecheck.models import MatchConfidence, Offer


# ------------------------------------------------------------------ Parser

def test_reads_falstaff_points():
    scores, rejected = parse_critic_scores("Falstaff 92/100")
    assert scores == {"falstaff": 92.0}
    assert rejected == []


def test_reads_several_critics_from_one_tile():
    scores, _ = parse_critic_scores(
        "James Suckling 94/100 · Falstaff 92/100 · Parker 95/100 · Decanter 94/100"
    )
    assert scores == {"suckling": 94.0, "falstaff": 92.0, "parker": 95.0, "decanter": 94.0}


@pytest.mark.parametrize(
    "text,key",
    [
        ("Robert Parker 95/100", "parker"),
        ("Wine Advocate 93/100", "parker"),
        ("James Suckling 97/100", "suckling"),
        ("Wine Spectator 90/100", "spectator"),
        ("Guía Peñín 93/100", "penin"),
        ("Tim Atkin 93/100", "atkin"),
        ("Jeb Dunnuck 91/100", "dunnuck"),
        ("Gault&Millau 17/100", None),   # andere Skala, s. u.
    ],
)
def test_critic_aliases(text, key):
    scores, _ = parse_critic_scores(text)
    if key is None:
        assert scores == {}
    else:
        assert key in scores


def test_other_scales_are_rejected_not_converted():
    """Mövenpick schreibt "Veronelli 3/100" — das sind Sterne, keine Punkte. Eine Note
    auf der falschen Skala wäre schlimmer als eine Lücke."""
    scores, rejected = parse_critic_scores("Veronelli 3/100")
    assert scores == {}
    assert rejected and "andere Skala" in rejected[0]


def test_unknown_critic_is_rejected_with_a_reason():
    scores, rejected = parse_critic_scores("Irgendwer 95/100")
    assert scores == {}
    assert rejected and "unbekannter Kritiker" in rejected[0]


def test_higher_score_wins_on_duplicate_mentions():
    """Händler führen gelegentlich mehrere Jahrgänge derselben Quelle auf."""
    scores, _ = parse_critic_scores("Falstaff 91/100", "Falstaff 94/100")
    assert scores == {"falstaff": 94.0}


def test_text_without_scores_is_harmless():
    assert parse_critic_scores("Toskana, 75 cl, Sangiovese") == ({}, [])
    assert parse_critic_scores("") == ({}, [])


# ------------------------------------------------- Aggregation zur Leitquelle

def _offer(retailer, name, critics, price=25.0):
    return Offer(
        retailer=retailer, name=name, vintage=2023,
        price_per_bottle_incl_vat=price, price_raw=price,
        price_raw_basis="pro Flasche, inkl. MwSt",
        critic_scores=critics,
    )


def test_falstaff_from_the_retailer_becomes_the_leitquelle():
    row = merge_offers([
        _offer("moevenpick", "Rosso Bolgheri DOC 2023 Il Seggio",
               {"falstaff": 92.0, "suckling": 94.0}),
    ])[0]
    assert row.falstaff is not None
    assert row.falstaff.value == 92.0
    assert row.falstaff.scale_max == 100.0
    # Kein Namens-Matching nötig: die Note hängt am Produkt.
    assert row.falstaff.confidence is MatchConfidence.EXACT
    # Und sie treibt damit das Ranking.
    value, source = row.ranking_rating()
    assert source == "Falstaff"
    assert value == pytest.approx(0.92)


def test_provenance_is_always_stated():
    row = merge_offers([_offer("moevenpick", "Wein", {"falstaff": 92.0})])[0]
    assert row.falstaff.source_name == "laut moevenpick"
    assert row.falstaff.status == "retailer_reported"
    assert "nicht bei Falstaff verifiziert" in row.falstaff.note


def test_other_critics_rank_when_falstaff_is_missing():
    """Fehlt Falstaff, springen die anderen 100-Punkte-Kritiker ein. Sie kommen vor
    Vivino, weil die Note am exakten Produkt hängt statt an einer Namensähnlichkeit —
    und die Quelle steht immer in ``rank_source``."""
    row = merge_offers([
        _offer("moevenpick", "Wein", {"suckling": 94.0, "decanter": 96.0}),
    ])[0]
    assert row.critics == {"suckling": (94.0, "moevenpick"), "decanter": (96.0, "moevenpick")}
    assert row.falstaff is None
    value, source = row.ranking_rating()
    assert value == pytest.approx(0.94)
    assert source == "James Suckling"


def test_critic_order_follows_priority_not_the_friendliest_score():
    """Sonst gewinnt immer der Kritiker mit der höchsten Note, und das wäre eine
    Auswahl nach Wunschergebnis."""
    row = merge_offers([
        _offer("moevenpick", "Wein", {"parker": 90.0, "decanter": 99.0}),
    ])[0]
    _value, source = row.ranking_rating()
    assert source == "Parker"


def test_falstaff_still_outranks_the_other_critics():
    row = merge_offers([
        _offer("moevenpick", "Wein", {"falstaff": 88.0, "parker": 97.0}),
    ])[0]
    _value, source = row.ranking_rating()
    assert source == "Falstaff"


def test_named_critic_outranks_a_vivino_match():
    """Die Kritikernote hängt am Produkt, der Vivino-Treffer an einem Namensvergleich."""
    from winecheck.models import VivinoResult, VivinoStatus

    row = merge_offers([_offer("moevenpick", "Wein", {"suckling": 94.0})])[0]
    row.vivino = VivinoResult(
        status=VivinoStatus.EXACT, query="wein", url="https://www.vivino.com/de/x/w/1",
        note="ok", rating=4.8, rating_count=500, match_confidence="exact",
    )
    _value, source = row.ranking_rating()
    assert source == "James Suckling"


def test_vivino_still_ranks_when_no_critic_is_known():
    from winecheck.models import VivinoResult, VivinoStatus

    row = merge_offers([_offer("prodega", "Wein ohne Noten", {})])[0]
    row.vivino = VivinoResult(
        status=VivinoStatus.EXACT, query="wein", url="https://www.vivino.com/de/x/w/1",
        note="ok", rating=4.0, rating_count=100, match_confidence="exact",
    )
    _value, source = row.ranking_rating()
    assert source == "Vivino"


def test_conflicting_retailer_scores_are_reported_not_averaged():
    row = merge_offers([
        _offer("moevenpick", "Barolo DOCG 2019 Tortoniano", {"falstaff": 92.0}),
        _offer("coop", "Barolo DOCG 2019 Tortoniano", {"falstaff": 95.0}, price=29.0),
    ])[0]
    assert row.falstaff.value == 95.0
    assert "widersprechen sich" in row.falstaff.note
    assert "92" in row.falstaff.note and "95" in row.falstaff.note


def test_row_without_critic_scores_keeps_falstaff_empty():
    row = merge_offers([_offer("prodega", "Wein ohne Noten", {})])[0]
    assert row.falstaff is None
    assert row.critics == {}


def test_critics_reach_the_csv():
    from winecheck.report.csv_out import LEAD_COLUMNS

    row = merge_offers([
        _offer("moevenpick", "Wein", {"falstaff": 92.0, "suckling": 94.0}),
    ])[0]
    flat = row.to_flat()
    assert flat["falstaff_points"] == "92"
    assert flat["falstaff_reported_by"] == "laut moevenpick"
    assert "suckling 94/100 (moevenpick)" in flat["critics"]
    for col in ("falstaff_reported_by", "critics"):
        assert col in LEAD_COLUMNS


def test_offer_critic_scores_survive_the_cache_roundtrip():
    from winecheck.cli import _offer_from_payload, _offer_payload

    original = _offer("moevenpick", "Wein", {"falstaff": 92.0})
    restored = _offer_from_payload(_offer_payload(original))
    assert restored.critic_scores == {"falstaff": 92.0}

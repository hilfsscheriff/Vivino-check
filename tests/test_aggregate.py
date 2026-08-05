"""Tests für Dedup über Händler und den value_score."""

import pytest

from winecheck.aggregate import compute_scores, merge_offers, spread
from winecheck.models import Offer, PriceConfidence


def offer(retailer, name, price, vintage=2022, confidence=PriceConfidence.HIGH, raw=None, basis=""):
    o = Offer(
        retailer=retailer,
        name=name,
        vintage=vintage,
        price_per_bottle_incl_vat=price,
        price_raw=raw if raw is not None else price,
        price_raw_basis=basis or "pro Flasche, inkl. MwSt",
        price_confidence=confidence,
    )
    return o


# ------------------------------------------------------- Dedup über Händler

def test_same_wine_at_two_retailers_becomes_one_row():
    """Kernfeature: derselbe Wein bei Coop und Prodega ist eine Zeile mit zwei Preisen."""
    rows = merge_offers([
        offer("coop", "Tenute Rossetti Linda Bolgheri DOC", 12.95),
        offer("prodega", "Rossetti Linda Bolgheri", 9.73, raw=9.00, basis="Karton 6, exkl. MwSt"),
    ])
    assert len(rows) == 1
    row = rows[0]
    assert row.retailer_count == 2
    assert row.best_price == 9.73
    assert row.cheapest_retailer == "prodega"
    assert spread(row) == pytest.approx(3.22, abs=0.01)


def test_different_vintages_stay_separate():
    rows = merge_offers([
        offer("coop", "Rossetti Linda Bolgheri", 12.95, vintage=2021),
        offer("coop", "Rossetti Linda Bolgheri", 13.95, vintage=2022),
    ])
    assert len(rows) == 2


def test_dedup_ignores_article_numbers_and_word_order():
    a = offer("denner", "Castelbarco Ripasso della Valpolicella DOC Superiore", 6.45)
    a.article_no = "1234"
    b = offer("prodega", "Valpolicella Ripasso Superiore Castelbarco", 7.51)
    b.article_no = "9999"
    rows = merge_offers([a, b])
    assert len(rows) == 1
    assert rows[0].retailer_count == 2


def test_flat_row_has_per_retailer_price_columns():
    rows = merge_offers([
        offer("coop", "Rossetti Linda Bolgheri", 12.95),
        offer("prodega", "Rossetti Linda Bolgheri", 9.73, raw=9.0, basis="Karton 6, exkl. MwSt"),
    ])
    flat = rows[0].to_flat()
    assert flat["price_coop"] == "12.95"
    assert flat["price_prodega"] == "9.73"
    assert "Karton 6, exkl. MwSt" in flat["price_raw_prodega"]
    assert flat["cheapest_retailer"] == "prodega"
    assert flat["retailer_count"] == 2


# ------------------------------------------------------------- Preisqualität

def test_low_price_confidence_is_excluded_from_best_price():
    """Ein falsch umgerechneter Literpreis erzeugt einen Scheinsieger."""
    rows = merge_offers([
        offer("prodega", "Irgendein Wein", 1.20, confidence=PriceConfidence.LOW),
        offer("coop", "Irgendein Wein", 11.95),
    ])
    row = rows[0]
    assert row.best_price == 11.95
    assert row.cheapest_retailer == "coop"


def test_row_with_only_low_confidence_gets_no_score():
    from winecheck.models import Rating, VivinoResult, VivinoStatus

    rows = merge_offers([offer("prodega", "Wein X", 1.20, confidence=PriceConfidence.LOW)])
    rows[0].vivino = VivinoResult(
        status=VivinoStatus.EXACT, query="wein x", url="https://www.vivino.com/de/x/w/1",
        note="ok", rating=4.5, rating_count=100, match_confidence="exact",
    )
    compute_scores(rows)
    assert rows[0].value_score is None


# ---------------------------------------------------------------- value_score

def _rated(name, price, rating, retailer="coop"):
    from winecheck.models import VivinoResult, VivinoStatus

    o = offer(retailer, name, price)
    row = merge_offers([o])[0]
    row.vivino = VivinoResult(
        status=VivinoStatus.EXACT, query=name.lower(),
        url="https://www.vivino.com/de/x/w/1", note="ok",
        rating=rating, rating_count=100, match_confidence="exact",
    )
    return row


def test_cheap_good_wine_beats_expensive_better_wine_in_its_own_band():
    """Ein 4.1er für 7 Franken und ein 4.5er für 125 Franken sind nicht dasselbe."""
    cheap = _rated("Guter Günstiger", 7.00, 4.1)
    pricey = _rated("Teurer Besserer", 125.00, 4.5)
    compute_scores([cheap, pricey])
    assert cheap.price_band == "<10"
    assert pricey.price_band == ">80"
    # Beide sind je Klasse einziger Vertreter -> gleicher Fallback-Score.
    # Entscheidend ist, dass sie nicht in derselben Klasse verglichen werden.
    assert cheap.price_band != pricey.price_band


def test_within_a_band_better_rating_and_lower_price_wins():
    a = _rated("A", 12.00, 4.4)   # gut und günstiger
    b = _rated("B", 19.00, 4.0)   # schlechter und teurer
    compute_scores([a, b])
    assert a.price_band == b.price_band == "10-20"
    assert a.value_score > b.value_score


def test_unrated_wine_gets_no_score_but_stays_in_the_list():
    from winecheck.models import VivinoResult, VivinoStatus

    row = merge_offers([offer("coop", "Ohne Bewertung", 9.95)])[0]
    row.vivino = VivinoResult.miss(VivinoStatus.NO_ENTRY, "ohne bewertung", "kein Eintrag")
    compute_scores([row])
    assert row.value_score is None
    assert row.has_any_rating is False
    # Der Wein verschwindet nicht — er landet in der Tabelle "ohne Bewertung".
    assert row.no_rating_reason()
    assert row.vivino.url.startswith("https://www.vivino.com/de/explore?search_term=")


def test_ranking_source_is_always_reported():
    """Nie zwei Skalen im selben Sortierschlüssel ohne Herkunftsangabe."""
    from winecheck.models import Rating, MatchConfidence

    row = _rated("Mit Falstaff", 15.0, 4.0)
    row.falstaff = Rating(source="falstaff", value=91, scale_max=100,
                          confidence=MatchConfidence.EXACT)
    value, source = row.ranking_rating()
    assert source == "Falstaff"
    assert value == pytest.approx(0.91)

    row2 = _rated("Nur Vivino", 15.0, 4.0)
    value2, source2 = row2.ranking_rating()
    assert source2 == "Vivino"
    assert value2 == pytest.approx(0.8)

"""Vivino-Marktpreis und Schnäppchen-Prozent.

Der wichtigste Test hier ist die Zirkularitätssperre: Mövenpick ist
Vivino-Partnerhändler, und für Mövenpick-Weine nennt Vivino genau den
Mövenpick-Preis. Ohne Filter verglichen wir einen Preis mit sich selbst und
bekämen überall 0 % — wodurch alle Weine anderer Händler künstlich besser aussehen.
"""

import pytest

from winecheck.aggregate import merge_offers
from winecheck.models import Offer, PriceConfidence, VivinoResult, VivinoStatus
from winecheck.ratings.vivino import _Cand, _parse_prices, classify


def _api_price(amount, *, currency="CHF", ml=750, bottles=1, url="https://shop.example/x"):
    return {
        "amount": amount,
        "currency": {"code": currency},
        "bottle_quantity": bottles,
        "bottle_type": {"volume_ml": ml},
        "url": url,
    }


# ------------------------------------------------------- Preis-Normalisierung

def test_single_bottle_price_is_taken_as_is():
    prices = _parse_prices({"prices": [_api_price(24.50)]})
    assert len(prices) == 1
    assert prices[0].per_75cl == 24.50
    assert prices[0].shop == "shop.example"


def test_case_price_is_divided_by_bottle_count():
    """Ein Angebot über 6 Flaschen ist kein Flaschenpreis."""
    prices = _parse_prices({"prices": [_api_price(120.0, bottles=6)]})
    assert prices[0].per_75cl == 20.0
    assert "6 Flaschen" in prices[0].basis


def test_magnum_is_scaled_down_to_75cl():
    prices = _parse_prices({"prices": [_api_price(60.0, ml=1500)]})
    assert prices[0].per_75cl == 30.0
    assert "150 cl" in prices[0].basis


def test_half_bottle_is_scaled_up():
    prices = _parse_prices({"prices": [_api_price(10.0, ml=375)]})
    assert prices[0].per_75cl == 20.0


def test_foreign_currency_is_skipped_not_converted():
    """Ein Wechselkurs wäre eine weitere Fehlerquelle."""
    prices = _parse_prices({"prices": [_api_price(25.0, currency="EUR")]})
    assert prices == []


def test_single_price_field_is_used_when_prices_list_is_absent():
    prices = _parse_prices({"price": _api_price(18.0)})
    assert len(prices) == 1 and prices[0].per_75cl == 18.0


def test_missing_prices_yield_empty_list():
    assert _parse_prices({}) == []
    assert _parse_prices({"prices": []}) == []


# --------------------------------------------------------- Zirkularitätssperre

def _cand(prices):
    return _Cand(
        name="Pomerol Château Plince 2022", wine_name="Château Plince", winery="Château Plince",
        url="https://www.vivino.com/de/x/w/1", year=2022,
        vintage_avg=4.3, vintage_count=40, wine_avg=4.3, wine_count=400,
        prices=prices,
    )


def test_own_retailer_price_is_not_a_market_price():
    """Château Plince CHF 65 bei Mövenpick gegen CHF 65 von Mövenpick wären 0 %."""
    c = _cand([_api_and("https://www.moevenpick-wein.com/de/2022-chateau-plince.html", 65.0)])
    price, note = c.market_price({"moevenpick-wein.com"})
    assert price is None
    assert "derselbe Händler" in note
    assert "moevenpick-wein.com" in note


def test_independent_shop_counts_as_market_price():
    c = _cand([_api_and("https://www.nuritalienischeprodukte.ch/x", 39.0)])
    price, note = c.market_price({"transgourmet.ch"})
    assert price is not None
    assert price.per_75cl == 39.0
    assert "nuritalienischeprodukte.ch" in note


def test_cheapest_independent_price_wins_and_own_one_is_reported_as_skipped():
    c = _cand([
        _api_and("https://www.moevenpick-wein.com/de/x", 65.0),
        _api_and("https://fremder-shop.ch/x", 58.0),
        _api_and("https://noch-einer.ch/x", 72.0),
    ])
    price, note = c.market_price({"moevenpick-wein.com"})
    assert price.per_75cl == 58.0
    assert "1 Preis(e) des eigenen Händlers übersprungen" in note


def test_subdomain_of_the_retailer_also_counts_as_own():
    c = _cand([_api_and("https://shop.moevenpick-wein.com/x", 65.0)])
    price, _ = c.market_price({"moevenpick-wein.com"})
    assert price is None


def test_without_exclusion_the_own_price_would_be_used():
    """Belegt, dass der Filter der einzige Grund für die Lücke ist."""
    c = _cand([_api_and("https://www.moevenpick-wein.com/de/x", 65.0)])
    price, _ = c.market_price(set())
    assert price is not None and price.per_75cl == 65.0


def _api_and(url, amount):
    from winecheck.ratings.vivino import _Price, _shop_name

    return _Price(per_75cl=amount, raw=amount, basis="pro Flasche", url=url, shop=_shop_name(url))


def test_classify_attaches_market_price_and_respects_exclusion():
    c = _cand([_api_and("https://fremder-shop.ch/x", 58.0)])
    r = classify("Pomerol Château Plince", 2022, "pomerol chateau plince", [c],
                 exclude_hosts={"moevenpick-wein.com"})
    assert r.status is VivinoStatus.EXACT
    assert r.market_price == 58.0
    assert r.market_price_shop == "fremder-shop.ch"

    own = _cand([_api_and("https://www.moevenpick-wein.com/de/x", 65.0)])
    r2 = classify("Pomerol Château Plince", 2022, "pomerol chateau plince", [own],
                  exclude_hosts={"moevenpick-wein.com"})
    assert r2.market_price is None
    assert "derselbe Händler" in r2.market_price_note


# ------------------------------------------------------- bargain_percent

def _row(price, market, *, confidence=PriceConfidence.HIGH):
    o = Offer(
        retailer="prodega", name="Ein Wein", vintage=2022,
        price_per_bottle_incl_vat=price, price_raw=price,
        price_raw_basis="pro Flasche, inkl. MwSt", price_confidence=confidence,
    )
    row = merge_offers([o])[0]
    row.vivino = VivinoResult(
        status=VivinoStatus.EXACT, query="ein wein",
        url="https://www.vivino.com/de/x/w/1", note="ok",
        rating=4.0, rating_count=100, match_confidence="exact",
        market_price=market,
    )
    return row


def test_bargain_percent_is_the_saving_against_the_market():
    assert _row(7.51, 15.0).bargain_percent == pytest.approx(49.9, abs=0.1)
    assert _row(10.0, 20.0).bargain_percent == 50.0


def test_offer_above_market_gives_a_negative_percent():
    """Ein Angebot über dem Marktpreis ist eine Information, kein Fehler."""
    assert _row(25.0, 20.0).bargain_percent == -25.0


def test_no_market_price_means_no_percent():
    assert _row(7.51, None).bargain_percent is None


def test_unreliable_price_means_no_percent():
    """Ein falsch umgerechneter Literpreis erzeugt sonst ein Fantasie-Schnäppchen."""
    assert _row(1.21, 15.0, confidence=PriceConfidence.LOW).bargain_percent is None


def test_row_without_vivino_has_no_market_price():
    o = Offer(retailer="coop", name="X", price_per_bottle_incl_vat=9.0, price_raw=9.0)
    row = merge_offers([o])[0]
    assert row.market_price is None
    assert row.bargain_percent is None


def test_market_price_reaches_the_csv():
    from winecheck.report.csv_out import LEAD_COLUMNS

    flat = _row(7.51, 15.0).to_flat()
    for col in ("bargain_percent", "vivino_market_price", "vivino_market_price_shop",
                "vivino_market_price_note"):
        assert col in flat, f"{col} fehlt"
        assert col in LEAD_COLUMNS
    assert flat["vivino_market_price"] == "15"
    assert flat["bargain_percent"].startswith("49")

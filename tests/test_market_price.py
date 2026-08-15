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


# ------------------------------------------- Schweizer Shops und Plausibilität

def test_swiss_shop_is_preferred_over_a_cheaper_foreign_one():
    """Verglichen wird mit dem *Schweizer* Detailhandel. Ausländische Sammler- und
    Anlageplattformen führen Preise, die ein Vielfaches des Ladenpreises betragen."""
    c = _cand([
        _api_and("https://cultwinesintl.com/x", 80.86),
        _api_and("https://www.chezgrisoni.ch/x", 24.90),
    ])
    price, note = c.market_price(set())
    assert price.shop == "chezgrisoni.ch"
    assert "kein Schweizer Shop" not in note


def test_swiss_preference_wins_even_when_the_foreign_price_is_lower():
    c = _cand([
        _api_and("https://auslandshop.com/x", 12.00),
        _api_and("https://www.chezgrisoni.ch/x", 24.90),
    ])
    price, _ = c.market_price(set())
    assert price.shop == "chezgrisoni.ch"


def test_foreign_only_price_is_used_but_flagged():
    """Lieber ein Vergleich mit Vorbehalt als keiner — aber der Vorbehalt steht dran."""
    c = _cand([_api_and("https://cultwinesintl.com/x", 80.86)])
    price, note = c.market_price(set())
    assert price is not None
    assert "kein Schweizer Shop" in note


def _row_with_note(price, market, note):
    from winecheck.models import VivinoResult, VivinoStatus

    o = Offer(retailer="coop", name="Ein Wein", vintage=2022,
              price_per_bottle_incl_vat=price, price_raw=price,
              price_raw_basis="pro Flasche, inkl. MwSt")
    row = merge_offers([o])[0]
    row.vivino = VivinoResult(
        status=VivinoStatus.EXACT, query="q", url="https://www.vivino.com/de/x/w/1",
        note="ok", rating=4.0, rating_count=100, match_confidence="exact",
        market_price=market, market_price_note=note,
    )
    return row


def test_huge_bargain_is_flagged_as_questionable():
    """Der Bourgogne für CHF 13.95 gegen CHF 80.86 einer Anlageplattform — 83 %
    'Ersparnis', die es nicht gibt."""
    from winecheck.models import DiscountPlausibility

    row = _row_with_note(13.95, 80.86, "Marktpreis von cultwinesintl.com")
    assert row.bargain_percent > 80
    assert row.bargain_plausibility is DiscountPlausibility.QUESTIONABLE


def test_foreign_market_price_is_questionable_even_at_moderate_percent():
    from winecheck.models import DiscountPlausibility

    row = _row_with_note(20.0, 30.0, "Marktpreis von x.com — kein Schweizer Shop, "
                                     "Vergleich mit Vorsicht")
    assert row.bargain_percent == pytest.approx(33.3, abs=0.1)
    assert row.bargain_plausibility is DiscountPlausibility.QUESTIONABLE


def test_normal_bargain_from_a_swiss_shop_is_plausible():
    from winecheck.models import DiscountPlausibility

    row = _row_with_note(5.95, 14.30, "Marktpreis von chezgrisoni.ch")
    assert row.bargain_percent == pytest.approx(58.4, abs=0.1)
    assert row.bargain_plausibility is DiscountPlausibility.OK


def test_plausibility_is_unknown_without_a_percent():
    from winecheck.models import DiscountPlausibility

    row = _row_with_note(9.0, None, "kein Preis")
    assert row.bargain_plausibility is DiscountPlausibility.UNKNOWN


def test_plausibility_reaches_the_csv():
    flat = _row_with_note(13.95, 80.86, "Marktpreis von cultwinesintl.com").to_flat()
    assert flat["bargain_plausibility"] == "questionable"


# -- Der Marktpreis darf nicht vom eigenen Shop stammen ---------------------
def test_marktpreis_vom_eigenen_shop_zaehlt_nicht():
    """Sonst vergleicht sich der Preis mit sich selbst.

    Der Vivino-Marktplatz ist der Fall, an dem es auffiel: er steht als vivino.com im
    Verzeichnis, verlinkt aber auf den Shop, der tatsaechlich liefert. Die
    Ausschlussliste beim Abruf kannte nur die eingetragene Domain, und so nannte
    Vivino genau den Preis wieder, der schon in der Zeile stand — 289 Weine, die
    meisten mit "gegen Markt 0 %".
    """
    from winecheck.models import Offer, VivinoResult, VivinoStatus
    from winecheck.aggregate import merge_offers

    o = Offer(retailer="vivinoshop", name="Provins Valais Clos Corbassières",
              vintage=2016, price_per_bottle_incl_vat=26.70, price_raw=26.70,
              price_raw_basis="inkl. MwSt",
              url="https://www.bignens.ch/single-product/clos-corbassieres-valais-aoc-x/")
    row = merge_offers([o])[0]
    row.vivino = VivinoResult(
        status=VivinoStatus.EXACT, query="q",
        url="https://www.vivino.com/de/clos-corbassieres/w/1761842", note="n",
        rating=4.3, rating_count=293, match_confidence="exact",
        matched_name="Provins Valais Clos Corbassières 2016",
        market_price=26.70,
        market_price_url="http://www.bignens.ch/single-product/clos-corbassieres-valais-aoc-x/",
    )
    assert row.market_price is None, "derselbe Shop ist kein unabhaengiger Vergleich"
    assert row.bargain_percent is None


def test_marktpreis_von_einem_anderen_shop_zaehlt():
    """Gegenprobe — sonst waere die Regel ein Rueckschritt."""
    from winecheck.models import Offer, VivinoResult, VivinoStatus
    from winecheck.aggregate import merge_offers

    o = Offer(retailer="vivinoshop", name="Provins Valais Clos Corbassières",
              vintage=2016, price_per_bottle_incl_vat=20.00, price_raw=20.00,
              price_raw_basis="inkl. MwSt",
              url="https://www.bignens.ch/single-product/x/")
    row = merge_offers([o])[0]
    row.vivino = VivinoResult(
        status=VivinoStatus.EXACT, query="q", url="https://www.vivino.com/de/x/w/1",
        note="n", rating=4.3, rating_count=293, match_confidence="exact",
        matched_name="Provins Valais Clos Corbassières 2016",
        market_price=26.70, market_price_url="https://www.vinotheque.ch/x/",
    )
    assert row.market_price == 26.70
    assert row.bargain_percent is not None and row.bargain_percent > 0

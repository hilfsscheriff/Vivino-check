"""Tests der Preisnormalisierung — CHF pro 75 cl inkl. MwSt, 8.1 % Normalsatz."""

import pytest

from winecheck.models import DiscountPlausibility, PriceConfidence
from winecheck.prices import (
    VAT_ALCOHOL,
    discount_percent,
    normalize_price,
    parse_gebinde,
    price_band,
    rate_discount,
)


def test_vat_rate_is_normalsatz_not_lebensmittelsatz():
    """Alkohol = 8.1 %. Der reduzierte Satz von 2.6 % wäre der klassische Fehler."""
    assert VAT_ALCOHOL == 0.081


def test_prodega_karton_exkl_mwst():
    """Die Vorgabe aus dem Auftrag: Karton 6 × 75 cl, CHF 41.70 exkl. MwSt -> CHF 7.51."""
    p = normalize_price(41.70, "Karton 6 × 75 cl, exkl. MwSt", price_basis="pack")
    assert p.price_per_bottle_incl_vat == 7.51
    assert p.price_raw == 41.70
    assert p.vat_added is True
    assert p.units == 6
    assert p.bottle_ml == 750
    assert p.usable_for_ranking
    assert "exkl. MwSt" in p.price_raw_basis
    assert "Karton 6" in p.price_raw_basis


def test_auto_basis_detects_carton_price():
    """Ohne explizites price_basis muss 'Karton 6 ×' als Kartonpreis erkannt werden."""
    p = normalize_price(41.70, "Karton 6 × 75 cl, exkl. MwSt")
    assert p.price_per_bottle_incl_vat == 7.51


def test_retail_bottle_price_incl_vat_unchanged():
    """Coop/Denner: inkl. MwSt pro Flasche — darf nicht angefasst werden."""
    p = normalize_price(9.95, "75 cl, inkl. MwSt")
    assert p.price_per_bottle_incl_vat == 9.95
    assert p.vat_added is False
    assert p.confidence is PriceConfidence.HIGH


def test_50cl_is_scaled_up_to_75cl():
    p = normalize_price(10.00, "50 cl, inkl. MwSt")
    assert p.price_per_bottle_incl_vat == 15.00
    assert p.bottle_ml == 500
    assert p.confidence is PriceConfidence.MEDIUM


def test_magnum_is_scaled_down():
    p = normalize_price(30.00, "Magnum 150 cl, inkl. MwSt")
    assert p.price_per_bottle_incl_vat == 15.00
    assert p.bottle_ml == 1500


def test_bag_in_box_3l():
    p = normalize_price(19.90, "Bag-in-Box 3 l, inkl. MwSt")
    assert p.price_per_bottle_incl_vat == pytest.approx(4.98, abs=0.01)
    assert "Bag-in-Box" in p.note


def test_carton_without_count_is_low_confidence_and_excluded():
    """Der gefährliche Fall: Kartonpreis ohne Stückzahl. Kein Ranking."""
    p = normalize_price(41.70, "Karton, exkl. MwSt")
    assert p.confidence is PriceConfidence.LOW
    assert p.usable_for_ranking is False
    assert "Stückzahl" in p.note


def test_bag_in_box_without_volume_is_low_confidence():
    p = normalize_price(19.90, "Bag-in-Box, exkl. MwSt")
    assert p.confidence is PriceConfidence.LOW
    assert p.usable_for_ranking is False


def test_12er_karton():
    """12 × 75 cl, CHF 108.00 exkl. -> 9.00 exkl. -> 9.73 inkl."""
    p = normalize_price(108.00, "Karton 12 × 75 cl exkl. MwSt", price_basis="pack")
    assert p.price_per_bottle_incl_vat == 9.73
    assert p.units == 12


def test_pro_flasche_beats_pack_hint():
    """Steht 'pro Flasche' dabei, ist der Preis pro Flasche — auch wenn ein 6er-Gebinde
    erwähnt wird."""
    p = normalize_price(6.95, "6er Karton, Preis pro Flasche, exkl. MwSt")
    assert p.price_per_bottle_incl_vat == 7.51


def test_missing_vat_note_defaults_per_retailer_setting():
    """Prodega-Adapter setzt default_vat_included=False; das muss greifen, wenn im Text
    kein Hinweis steht."""
    p = normalize_price(6.95, "6 × 75 cl", price_basis="bottle", default_vat_included=False)
    assert p.price_per_bottle_incl_vat == 7.51
    assert "exkl. angenommen" in p.note


def test_no_price_yields_low_confidence():
    p = normalize_price(None, "Karton 6")
    assert p.price_per_bottle_incl_vat is None
    assert p.usable_for_ranking is False


@pytest.mark.parametrize(
    "text,units,ml",
    [
        ("6 x 75 cl", 6, 750),
        ("12 × 0.75 l", 12, 750),
        ("6er Pack", 6, 750),
        ("Karton à 12", 12, 750),
        ("6 Flaschen 75cl", 6, 750),
        ("100 cl", None, 1000),
        ("Harass 6 × 50 cl", 6, 500),
    ],
)
def test_parse_gebinde_variants(text, units, ml):
    u, m, _note, certain = parse_gebinde(text)
    assert (u, m) == (units, ml)
    assert certain is True


def test_price_bands():
    assert price_band(7.0) == "<10"
    assert price_band(9.99) == "<10"
    assert price_band(10.0) == "10-20"
    assert price_band(39.9) == "20-40"
    assert price_band(80.0) == ">80"
    assert price_band(125.0) == ">80"
    assert price_band(None) == ""


def test_discount_percent_and_plausibility():
    assert discount_percent(6.25, 12.50) == 50.0
    # Eigenmarke mit 50 % -> fragwürdig, weil Referenzpreise dort konstruiert sein können.
    assert rate_discount(50.0, is_private_label=True) is DiscountPlausibility.QUESTIONABLE
    # Markenwein mit 50 % -> plausibel, nur informativ.
    assert rate_discount(50.0, is_private_label=False) is DiscountPlausibility.OK
    assert rate_discount(20.0, is_private_label=True) is DiscountPlausibility.OK
    assert rate_discount(None, is_private_label=True) is DiscountPlausibility.UNKNOWN


def test_discount_ignores_nonsense_reference():
    assert discount_percent(12.50, 12.50) is None
    assert discount_percent(15.0, 12.50) is None
    assert discount_percent(6.25, None) is None

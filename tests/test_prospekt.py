"""Tests des Prospekt-PDF-Parsers.

Der Parser arbeitet über Koordinaten, nicht über ``extract_text()`` — im Rasterlayout
liest zeilenweises Extrahieren quer über alle vier Spalten und mischt die Produkte
durcheinander. Getestet wird hier die Zellenlogik, die aus den rekonstruierten Zeilen
Preis, Bezugsgrösse und Name zieht.
"""

import pytest

from winecheck.adapters.prospekt_pdf import Cell


def cell(above, below, article="628059", page=24):
    return Cell(article_no=article, lines_above=above, lines_below=below, page=page)


def test_reads_price_unit_and_reference():
    """Aufbau im Prodega-Prospekt: Rabatt, Bezugsgrösse, Preis, 'statt' — darüber."""
    c = cell(
        ["-22%", "75 cl", "6.95", "statt 8.95"],
        ["Marques de Riscal", "Verdejo", "Rueda DO", "Spanien", "Rueda"],
    )
    assert c.unit == "75 cl"
    assert c.price == 6.95
    assert c.reference == 8.95
    assert "Marques de Riscal" in c.name
    assert "Verdejo" in c.name


def test_country_and_region_lines_are_dropped_from_the_name():
    """Land und Region verwässern das Namens-Matching: sie fügen auf Händlerseite
    Tokens hinzu, die die Bewertungsquelle nicht kennt, und senken die Abdeckung."""
    c = cell(
        ["AKTION", "75 cl", "17.90"],
        ["Roncaia Riserva", "Ticino DOC", "Vinattieri", "Schweiz", "Tessin"],
    )
    assert "Schweiz" not in c.name
    assert "Tessin" not in c.name
    assert "Roncaia" in c.name


def test_footer_date_range_is_not_part_of_the_name():
    """Der Gültigkeitszeitraum steht in der Fusszeile und rutschte in der ersten
    Fassung in die Weinnamen."""
    c = cell(
        ["-24%", "1000 cl", "14.95"],
        ["Montagne Vin Rouge", "Europa/Drittländer", "3.8.–8.8.2026"],
    )
    assert "3.8." not in c.name
    assert "2026" not in c.name
    assert "Montagne Vin Rouge" in c.name


def test_nearest_price_above_wins():
    """Der Block über dem eigenen Preisblock gehört zum vorherigen Produkt."""
    c = cell(
        ["75 cl", "99.00", "statt 120.00",      # Vorgängerprodukt
         "-22%", "75 cl", "6.95", "statt 8.95"],  # eigener Block, näher an der Art.-Nr.
        ["Marques de Riscal", "Verdejo"],
    )
    assert c.price == 6.95
    assert c.reference == 8.95


def test_pack_is_kept_separate_from_the_unit():
    """Der Preis gilt pro Bezugsgrösse (50 cl), nicht pro Karton (15 × 50 cl)."""
    c = cell(
        ["-17%", "50 cl", "3.50", "statt 4.25"],
        ["Trait d`Union", "Rosé de Gamay", "Romand", "Schweiz", "Waadt", "15 x 50 cl"],
    )
    assert c.unit == "50 cl"
    assert c.pack == "15 x 50 cl"
    assert c.price == 3.50


def test_missing_price_yields_none_rather_than_a_guess():
    c = cell(["AKTION", "75 cl"], ["Irgendein Wein", "Toskana"])
    assert c.price is None
    assert c.unit == "75 cl"


def test_missing_unit_yields_empty_string():
    c = cell(["AKTION", "12.90"], ["Irgendein Wein"])
    assert c.unit == ""
    assert c.price == 12.90


def test_noise_lines_are_ignored_in_the_name():
    c = cell(
        ["75 cl", "9.95"],
        ["Piccini Chianti Classico", "IMMER GÜNSTIG ABHOLEN", "Italien", "Toskana",
         "Preisänderungen und Mengenbeschränkungen vorbehalten"],
    )
    assert c.name == "Piccini Chianti Classico"


# ------------------------------------------------- Normalisierung der Zelle

@pytest.mark.parametrize(
    "unit,price,expected",
    [
        # exkl. MwSt -> inkl. 8.1 %, und auf 75 cl umgerechnet
        ("75 cl", 6.95, 7.51),
        ("50 cl", 3.50, 5.68),
        ("70 cl", 8.90, 10.31),
        ("100 cl", 1.60, 1.30),
    ],
)
def test_cell_price_normalizes_to_75cl_incl_vat(unit, price, expected):
    from winecheck.prices import normalize_price

    norm = normalize_price(price, f"{unit}, exkl. MwSt", price_basis="bottle",
                           default_vat_included=False)
    assert norm.price_per_bottle_incl_vat == pytest.approx(expected, abs=0.01)

"""Trinkreife aus der Vinum-Jahrgangstabelle.

Keine erreichbare Quelle führt Trinkreife als Datenfeld — Vivino hat sie nicht,
Prodega nennt sie nirgends, Falstaff ist gesperrt. Die Vinum-Jahrgangstabelle, die
Mövenpick als PDF veröffentlicht, ist ein Text-PDF; OCR ist nicht nötig. Weinart und
Jahrgangsqualität stecken allerdings in der Grafik und werden über Farben gelesen.
"""

import pytest

from winecheck.trinkreife import (
    MATURITY,
    MATURITY_SHORT,
    REGION_TOKENS,
    Entry,
    Table,
    display_region,
    guess_wine_type,
    load,
)


@pytest.fixture(scope="module")
def table():
    t = Table.load()
    if not t.entries:
        pytest.skip("sources/trinkreife.yaml fehlt — 'wine-check trinkreife' ausführen")
    return t


# --------------------------------------------------------------- Tabellendaten

def test_table_has_both_wine_types(table):
    types = {e.wine_type for e in table.entries}
    assert "rot" in types and "weiss" in types
    assert "unbekannt" not in types, "jede Zeile braucht eine Weinart"


@pytest.mark.parametrize(
    "region_part,expected",
    [
        # Weinarten, deren Farbe zweifelsfrei ist — Kontrolle der Glas-Erkennung.
        ("Amarone", "rot"),
        ("Sfursat", "rot"),
        ("Montepulciano", "rot"),
        ("Vintage Port", "rot"),
        ("Barolo", "rot"),
        ("Sauternes", "weiss"),
        ("Chablis", "weiss"),
        ("Rueda", "weiss"),
        ("Champagner", "weiss"),
        ("Mosel", "weiss"),
    ],
)
def test_wine_type_from_glass_colour(table, region_part, expected):
    """Die Weinart steckt in der Farbe des Weinglases, nicht im Text. Eine Annahme
    über die Zeilenreihenfolge wäre falsch gewesen: bei Burgenland steht Rot zuerst."""
    hits = [e for e in table.entries if region_part.lower() in e.region.lower()]
    assert hits, f"{region_part} nicht in der Tabelle"
    assert all(e.wine_type == expected for e in hits)


def test_empty_cells_become_too_old_not_missing(table):
    """Leere Zellen heissen "hätte man besser schon getrunken". Im Text fehlen sie,
    nur über die x-Position ist erkennbar, welcher Jahrgang gemeint ist."""
    baden = [e for e in table.entries if e.region == "Baden"]
    assert baden
    codes = baden[0].maturity
    assert len(codes) >= 16, "alle Jahrgangsspalten müssen belegt sein"
    assert "-" in codes.values()


def test_every_code_has_a_legend_entry(table):
    for e in table.entries:
        for code in e.maturity.values():
            assert code in MATURITY, f"unbekannter Code {code!r}"
            assert code in MATURITY_SHORT


def test_vintage_quality_is_read_from_the_cell_background(table):
    qualities = {q for e in table.entries for q in e.quality.values()}
    assert qualities <= {"exzellent", "gut bis sehr gut", "mittelmässig"}
    assert qualities, "keine Jahrgangsqualität erkannt"


def test_no_legend_rows_leaked_into_the_data(table):
    """Die PDF-Legende enthält selbst die Buchstaben g, k und m."""
    for e in table.entries:
        low = e.region.lower()
        assert "zenit" not in low
        assert "jahrgang bietet" not in low
        assert "*)" not in e.region, "Fussnotenmarker muss entfernt sein"


def test_region_tokens_reference_existing_rows(table):
    regions = {e.region for e in table.entries}
    unknown = [r for r in REGION_TOKENS if r not in regions]
    assert not unknown, f"REGION_TOKENS verweist auf unbekannte Zeilen: {unknown}"


# ------------------------------------------------------------- Weinart raten

@pytest.mark.parametrize(
    "name,expected",
    [
        # Ausdrückliche Farbangabe schlägt die Rebsorte.
        ("Ticino DOC Bianco di Merlot Roccolo – Weisswein", "weiss"),
        ("Ticino DOC Merlot Roccolo – Rotwein", "rot"),
        ("Rosso Bolgheri DOC Il Seggio", "rot"),
        # Nur Rebsorte, kein Farbwort.
        ("Cabernet Sauvignon California Anthony's Hope", "rot"),
        ("Valais AOC Petite Arvine Terrasses du Rhône", "weiss"),
        # Rosé bekommt einen eigenen Wert, weil die Tabelle keine Rosé-Zeilen führt.
        ("Céline Rosé Côtes de Provence AOC", "rose"),
        # Nichts Eindeutiges.
        ("Bordeaux AOC Château Sainte-Marie", "unbekannt"),
    ],
)
def test_guess_wine_type(name, expected):
    assert guess_wine_type(name) == expected


# ------------------------------------------------------------------- Zuordnung

@pytest.mark.parametrize(
    "name,vintage,region_contains",
    [
        ("Valais AOC Humagne Rouge Terrasses du Rhône", 2023, "Wallis"),
        ("Ticino DOC Merlot Roccolo – Rotwein", 2023, "Tessin"),
        ("Barolo DOCG Riserva Tortoniano", 2019, "Barolo"),
        ("Brunello di Montalcino DOCG Eredi Fuligni", 2021, "Montalcino"),
        ("Château Saint-Paul Cru Bourgeois Haut-Médoc", 2021, "Médoc"),
        ("Châteauneuf-du-Pape AOC Domaine du Vieux Lazaret", 2021, "Süd"),
        ("Ribera del Duero DO Tempranillo Roble", 2023, "Ribera"),
    ],
)
def test_region_is_matched(table, name, vintage, region_contains):
    m = table.lookup(name, vintage)
    assert m is not None, f"keine Zuordnung für {name!r}"
    assert region_contains.lower() in m.region.lower()


@pytest.mark.parametrize(
    "name,vintage",
    [
        # "oc" steckt in "DOCa" — das hatte einen Rioja ins Languedoc befördert.
        ("Rioja DOCa Gran Reserva Las Flores – Rotwein", 2016),
        # "bern" steckt in "Cabernet" — das hatte einen Kalifornier in die
        # Deutschschweiz befördert.
        ("Cabernet Sauvignon California Anthony's Hope", 2022),
        # "cote" steckt in "Côtes-du-Rhône" — das hatte ihn in die Waadt befördert.
        ("Côtes-du-Rhône AOC La Renjardière – Rotwein", 2023),
    ],
)
def test_tokens_match_on_word_boundaries(table, name, vintage):
    """Teilstring-Matching hatte drei Weine in völlig fremde Regionen einsortiert."""
    m = table.lookup(name, vintage)
    assert m is not None
    for wrong in ("Languedoc", "Deutschschweiz", "Waadt"):
        if wrong.lower() not in name.lower():
            assert wrong.lower() not in m.region.lower(), f"{name!r} -> {m.region}"


def test_most_specific_region_wins(table):
    """"Rioja Gran Reserva" gehört in die Reserva-Zeile, nicht in die Crianza-Zeile."""
    m = table.lookup("Rioja DOCa Gran Reserva Las Flores – Rotwein", 2016)
    assert m is not None
    assert "Reserva" in m.region


def test_no_vintage_means_no_answer(table):
    assert table.lookup("Barolo DOCG Riserva", None) is None


def test_unknown_region_means_no_answer(table):
    assert table.lookup("Irgendein Wein ohne Herkunft", 2022) is None


def test_rose_gets_no_answer_because_the_table_has_no_rose_rows(table):
    """Sonst bekäme ein Rosé die Reife des Rotweins derselben Region."""
    assert table.lookup("Céline Rosé Côtes de Provence AOC", 2024) is None


def test_white_wine_gets_no_red_row(table):
    """Tessin führt nur eine Rotwein-Zeile; ein weisser Ticino darf sie nicht erben."""
    assert table.lookup("Ticino DOC Bianco di Merlot Roccolo – Weisswein", 2025) is None


def test_match_carries_reason_and_quality(table):
    m = table.lookup("Valais AOC Humagne Rouge Terrasses du Rhône", 2022)
    assert m is not None
    assert m.short in MATURITY_SHORT.values()
    assert m.text == MATURITY[m.code]
    assert str(m.vintage) in m.note
    assert m.region_label in m.note


def test_display_region_expands_continuation_rows():
    """Fortsetzungszeilen tragen ihren Elternnamen im PDF nicht mit."""
    assert display_region("Süd") == "Rhône Süd"
    assert display_region("Sauternes").startswith("Bordeaux")
    assert display_region("Wallis") == "Wallis"


# ------------------------------------------------------------------ Anbindung

def test_maturity_reaches_the_row_and_the_csv():
    from winecheck.aggregate import attach_maturity, merge_offers
    from winecheck.models import Offer
    from winecheck.report.csv_out import LEAD_COLUMNS

    o = Offer(
        retailer="coop", name="Ticino DOC Merlot Roccolo – Rotwein", vintage=2023,
        price_per_bottle_incl_vat=9.95, price_raw=9.95,
        price_raw_basis="pro Flasche, inkl. MwSt",
    )
    row = attach_maturity(merge_offers([o]))[0]
    assert row.maturity is not None
    flat = row.to_flat()
    assert flat["trinkreife"] in MATURITY_SHORT.values()
    assert flat["trinkreife_region"] == "Tessin"
    for col in ("trinkreife", "trinkreife_text", "jahrgang_qualitaet",
                "trinkreife_region", "trinkreife_weinart", "trinkreife_code"):
        assert col in flat and col in LEAD_COLUMNS


def test_row_without_region_keeps_maturity_empty():
    from winecheck.aggregate import attach_maturity, merge_offers
    from winecheck.models import Offer

    o = Offer(retailer="coop", name="Wein ohne Herkunft", vintage=2022,
              price_per_bottle_incl_vat=9.0, price_raw=9.0)
    row = attach_maturity(merge_offers([o]))[0]
    assert row.maturity is None
    assert row.to_flat()["trinkreife"] == ""


def test_yaml_records_its_source():
    import yaml
    from winecheck.trinkreife import DEFAULT_PATH

    if not DEFAULT_PATH.exists():
        pytest.skip("sources/trinkreife.yaml fehlt")
    data = yaml.safe_load(DEFAULT_PATH.read_text(encoding="utf-8"))
    src = data["source"]
    assert "vinum" in src["name"].lower()
    assert src["pdf"].endswith(".pdf")
    assert src["fetched_at"]
    assert data["legend"]

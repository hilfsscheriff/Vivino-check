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


# ------------------------------- Land gehört nicht zur Identität (Regression)

def test_same_wine_at_two_retailers_merges_despite_the_country_token():
    """Coop und Aligro führen denselben Wein, nur nennt Coop das Land.

    „Ribera del Duero DO Protos Roble (2024) – Rotwein, Spanien" gegen „Ribera del
    Duero Roble Protos DO 2024, 75 cl": ein Token Unterschied, und der Wein stand
    zweimal im Report — CHF 9.75 bei Coop, CHF 9.67 bei Aligro — statt einmal mit
    beiden Preisen. Der Händlervergleich ist der Zweck des Werkzeugs.
    """
    from winecheck.names import dedup_key

    a = dedup_key("Ribera del Duero DO Protos Roble (2024) – Rotwein, Spanien (75cl)", 2024)
    b = dedup_key("Ribera del Duero Roble Protos DO 2024, 75 cl", 2024)
    assert a == b, f"{a!r} != {b!r}"


def test_generic_wines_keep_their_country():
    """Ohne diese Bedingung fielen „Cabernet Sauvignon, Chile" und „Cabernet
    Sauvignon, Australien" zu einer Zeile zusammen — zwei verschiedene Weine, deren
    Preise zu einem Phantomwert verschmelzen."""
    from winecheck.names import dedup_key

    assert dedup_key("Cabernet Sauvignon, Chile", 2022) != dedup_key(
        "Cabernet Sauvignon, Australien", 2022
    )


def test_two_offers_of_the_same_wine_become_one_row_with_both_prices():
    o1 = Offer(retailer="coop", name="Ribera del Duero DO Protos Roble (2024) – Rotwein, Spanien",
               vintage=2024, price_per_bottle_incl_vat=9.75, price_raw=9.75,
               price_raw_basis="inkl. MwSt")
    o2 = Offer(retailer="aligro", name="Ribera del Duero Roble Protos DO 2024, 75 cl",
               vintage=2024, price_per_bottle_incl_vat=9.67, price_raw=9.67,
               price_raw_basis="inkl. MwSt")
    rows = merge_offers([o1, o2])
    assert len(rows) == 1, "derselbe Wein bei zwei Händlern ist eine Zeile"
    assert rows[0].retailer_count == 2
    assert rows[0].best_price == pytest.approx(9.67)
    assert rows[0].cheapest_retailer == "aligro"


def test_one_vivino_wine_belongs_to_one_wine():
    """Fünf Weine von Rocca di Frassinello — il Frassinello, la Fillirea, la Guardia,
    la Rocca, la Uni — bekamen alle die 4.2 aus 4'655 Bewertungen des Sammeleintrags
    „Rocca di Frassinello Maremma Toscana". Vier davon sind falsch, und man sieht es
    der einzelnen Zeile nicht an; erst der Vergleich über alle Zeilen verrät es."""
    from winecheck.aggregate import resolve_shared_ratings
    from winecheck.models import VivinoResult, VivinoStatus

    def zeile(name, konfidenz):
        o = Offer(retailer="x", name=name, vintage=2024, price_per_bottle_incl_vat=15.0,
                  price_raw=15.0, price_raw_basis="inkl. MwSt")
        r = merge_offers([o])[0]
        r.vivino = VivinoResult(
            status=VivinoStatus.WINE_LEVEL, query="q",
            url="https://www.vivino.com/de/rocca/w/11745", note="n",
            rating=4.2, rating_count=4655, match_confidence=konfidenz,
            matched_name="Rocca di Frassinello Maremma Toscana",
        )
        return r

    a = zeile("Rocca di Frassinello la Guardia Maremma Toscana", "fuzzy")
    b = zeile("Rocca di Frassinello Maremma Toscana", "exact")
    resolve_shared_ratings([a, b])
    assert b.vivino.rating == 4.2, "der beste Treffer behält die Note"
    assert a.vivino.rating is None, "der schwächere verliert sie"
    assert "anderen Wein" in a.vivino.note


def test_different_vintages_of_one_wine_keep_their_rating():
    """Gegenprobe: „Legaris Crianza" 2020, 2021 und 2022 teilen sich zu Recht die
    Weinseite. Unterschieden wird an den unterscheidenden Wörtern — sind sie gleich,
    ist es derselbe Wein in anderem Jahr."""
    from winecheck.aggregate import resolve_shared_ratings
    from winecheck.models import VivinoResult, VivinoStatus

    zeilen = []
    for jahr in (2020, 2021, 2022):
        o = Offer(retailer="x", name=f"Ribera del Duero DO Crianza Legaris ({jahr})",
                  vintage=jahr, price_per_bottle_incl_vat=15.0, price_raw=15.0,
                  price_raw_basis="inkl. MwSt")
        r = merge_offers([o])[0]
        r.vivino = VivinoResult(
            status=VivinoStatus.WINE_LEVEL, query="q",
            url="https://www.vivino.com/de/legaris/w/80084", note="n",
            rating=3.9, rating_count=17387, match_confidence="wine_level",
            matched_name="Legaris Ribera del Duero Crianza",
        )
        zeilen.append(r)
    resolve_shared_ratings(zeilen)
    assert all(r.vivino.rating == 3.9 for r in zeilen), "alle drei Jahrgänge behalten die Note"


# -- Zwei Weine, ein Vivino-Eintrag ----------------------------------------
def test_den_eintrag_bekommt_der_wein_ohne_fremdes_wort():
    """Wer ein Wort mitbringt, das der Eintrag nicht kennt, hat den schwaecheren
    Anspruch.

    Fortsetzung des Falls oben, eine Stufe feiner. "la Rocca" und "il Frassinello
    Merlot" beanspruchten beide den gleichnamigen Hauptwein, beide als wine_level.
    Ueber die *unterscheidenden* Woerter sind sie nicht zu trennen: nach Abzug von
    Region und Rebsorte bleibt bei beiden nur der Gutsname, der Guetewert ist
    identisch. Der Eintrag ging deshalb an den, der zufaellig vorne stand — und das
    war der Merlot.

    Ueber *alle* Woerter geht es: "la Rocca" traegt keines, das der Eintrag nicht
    nennt, "il Frassinello Merlot" traegt "merlot".
    """
    from winecheck.aggregate import resolve_shared_ratings
    from winecheck.models import VivinoResult, VivinoStatus

    def zeile(name):
        o = Offer(retailer="x", name=name, vintage=2022, price_per_bottle_incl_vat=37.5,
                  price_raw=37.5, price_raw_basis="inkl. MwSt")
        r = merge_offers([o])[0]
        r.vivino = VivinoResult(
            status=VivinoStatus.WINE_LEVEL, query="q",
            url="https://www.vivino.com/de/maremma-toscana/w/11745", note="n",
            rating=4.2, rating_count=4658, match_confidence="wine_level",
            matched_name="Rocca di Frassinello Maremma Toscana",
        )
        return r

    merlot = zeile("Rocca di Frassinello il Frassinello Merlot Maremma Toscana DOC")
    rocca = zeile("Rocca di Frassinello la Rocca Maremma Toscana DOC")
    # Der Merlot steht zuerst — vorher gewann allein diese Reihenfolge.
    resolve_shared_ratings([merlot, rocca])
    assert rocca.vivino.rating == 4.2, "der Wein ohne fremdes Wort behaelt die Note"
    assert merlot.vivino.rating is None
    assert "anderen Wein" in merlot.vivino.note

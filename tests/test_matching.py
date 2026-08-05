"""Tests der Matching-Logik gegen echte Beispielpaare.

Die Zeilen 3 und 5 aus dem Auftrag sind die wichtigen: "Classico" und "Il Bruciato"
sind andere Weine, nicht Schreibvarianten.
"""

import pytest

from winecheck.matching import match_wine, match_winery, rank_candidates
from winecheck.models import MatchConfidence
from winecheck.names import dedup_key, extract_vintage, normalized_name, tokenize


# --------------------------------------------------------------- Treffer

def test_passio_settesoli_matches_despite_reordering_and_extra_producer():
    """Zeile 1: Produzentenpräfix 'Settesoli' und umgestellte Wortfolge."""
    d = match_wine(
        "Passìo Nero d'Avola/Perricone Sicilia DOC da uve leggermente appassite",
        "Settesoli Passìo Nero d'Avola - Perricone Da Uve Leggermente Appassite",
    )
    assert d.matched, d.reason
    assert d.confidence in (MatchConfidence.WINE_LEVEL, MatchConfidence.EXACT, MatchConfidence.FUZZY)


def test_anima_negra_matches_and_is_exact_for_matching_vintage():
    """Zeile 2: Akzent (ÀN/2 vs AN/2) und Jahrgang 2022 -> exact."""
    d = match_wine(
        "Anima Negra ÀN/2 IGP Illes Balears 2022",
        "Ànima Negra AN/2",
        source_vintage=2022,
        source_has_vintage_rating=True,
    )
    assert d.matched, d.reason
    assert d.confidence is MatchConfidence.EXACT
    assert d.vintage_match is True


def test_anima_negra_without_vintage_rating_is_wine_level():
    d = match_wine("Anima Negra ÀN/2 IGP Illes Balears 2022", "Ànima Negra AN/2")
    assert d.matched
    assert d.confidence is MatchConfidence.WINE_LEVEL


def test_rossetti_matches_despite_betriebsform():
    """Zeile 4: 'Tenute' ist eine Betriebsform, kein Namensbestandteil."""
    d = match_wine("Tenute Rossetti Linda Bolgheri DOC", "Rossetti Linda Bolgheri")
    assert d.matched, d.reason
    assert d.confidence in (MatchConfidence.WINE_LEVEL, MatchConfidence.EXACT)


@pytest.mark.parametrize(
    "retailer,source",
    [
        # 'Rosso' ist hier Teil des Appellationsnamens, keine Stilangabe.
        ("Masi Campofiorin Rosso del Veronese IGT", "Masi Campofiorin"),
        ("Villa Antinori Toscana IGT rosso", "Marchesi Antinori Villa Antinori Rosso Toscana"),
        ("Argiano Rosso di Montalcino DOC", "Argiano Rosso di Montalcino"),
        # 'Blanc' ist Bestandteil des Rebsortennamens.
        ("Chenin Blanc Western Cape", "Chenin Blanc Western Cape"),
        ("Ken Forrester Chenin Blanc", "Ken Forrester Chenin Blanc"),
        # Farbe fehlt einseitig -> irrelevant.
        ("Zaccagnini Montepulciano d'Abruzzo DOC", "Cantina Zaccagnini Montepulciano d'Abruzzo"),
        ("Fontanafredda Barolo DOCG 2018", "Fontanafredda Barolo"),
    ],
)
def test_colour_absence_does_not_block_match(retailer, source):
    """Farbtokens dürfen einseitig fehlen. Sonst fallen die häufigsten italienischen
    Appellationen (Rosso del Veronese, Rosso di Montalcino) alle durchs Raster."""
    d = match_wine(retailer, source)
    assert d.matched, f"{retailer!r} vs {source!r} wurde fälschlich abgelehnt: {d.reason}"


def test_colour_conflict_does_block_match():
    """Widersprüchliche Farbe ist ein anderes Produkt."""
    d = match_wine("Bardolino Chiaretto Bianco", "Bardolino Chiaretto Rosso")
    assert not d.matched
    assert "Farbe" in d.reason


def test_rose_is_still_a_hard_veto():
    """Ein Rosé ist nicht der Rotwein desselben Hauses — 'Rosé' steht anders als
    'Rosso' praktisch nie in einem Appellationsnamen."""
    d = match_wine("Gerard Bertrand Cote des Roses Rosé", "Gerard Bertrand Cote des Roses")
    assert not d.matched
    assert "Rose" in d.reason


# --------------------------------------------------------------- Nicht-Treffer

def test_castelbarco_classico_is_a_different_wine():
    """Zeile 3 — der wichtige Test. 'Classico' ist eine andere Lage, keine Variante."""
    d = match_wine(
        "Castelbarco Ripasso della Valpolicella DOC Superiore",
        "Castelbarco Valpolicella Ripasso Classico Superiore",
    )
    assert not d.matched, f"darf nicht matchen, matchte mit {d.score}: {d.reason}"
    assert d.confidence is MatchConfidence.NONE
    assert "Classico" in d.reason
    # Die Quell-Bezeichnung wird trotzdem mitgegeben, damit die Ablehnung prüfbar ist.
    assert d.source_name == "Castelbarco Valpolicella Ripasso Classico Superiore"


def test_guado_al_tasso_second_wine_is_not_the_grand_vin():
    """Zeile 5 — der zweite wichtige Test. 'Il Bruciato' ist der Zweitwein."""
    d = match_wine(
        "Guado al Tasso Bolgheri DOC Superiore",
        "Antinori Tenuta Guado al Tasso Il Bruciato Bolgheri",
    )
    assert not d.matched, f"darf nicht matchen, matchte mit {d.score}: {d.reason}"
    assert d.confidence is MatchConfidence.NONE


def test_second_wine_blocked_even_without_qualifier_difference():
    """Auch ohne 'Superiore' auf Händlerseite darf der Zweitwein nicht durchgehen —
    hier greift die Positionsregel (Cuvée-Name vor der Betriebsform)."""
    d = match_wine("Guado al Tasso Bolgheri", "Antinori Tenuta Guado al Tasso Il Bruciato Bolgheri")
    assert not d.matched, d.reason


def test_product_line_matches_but_only_as_fuzzy():
    """Gegenstück zum Zweitwein: 'Les Grands Dignitaires' ist die Produktlinie von
    Provins, der Wein ist derselbe. Das darf matchen — aber nur als ``fuzzy``, mit
    ausgegebener Quell-Bezeichnung, weil es lexikalisch nicht von einem Zweitwein zu
    unterscheiden ist."""
    d = match_wine(
        "Domherrenwein Fendant du Valais AOC",
        "Provins Valais Les Grands Dignitaires Domherrenwein Fendant",
    )
    assert d.matched, d.reason
    assert d.confidence is MatchConfidence.FUZZY
    assert d.needs_source_name
    assert d.source_name == "Provins Valais Les Grands Dignitaires Domherrenwein Fendant"
    assert "Dignitaires" in d.reason or "Grands" in d.reason


@pytest.mark.parametrize(
    "retailer,source,marker",
    [
        ("Chianti Colli Senesi", "Chianti Colli Senesi Riserva", "Riserva"),
        ("Rioja Reserva", "Rioja", "Reserva"),
        ("Barolo Bussia", "Barolo Cannubi", None),
        ("Prosecco Brut", "Prosecco Extra Dry", None),
        ("Château Margaux", "Pavillon Rouge du Château Margaux", None),
    ],
)
def test_qualifier_and_foreign_token_vetos(retailer, source, marker):
    d = match_wine(retailer, source)
    assert not d.matched, f"{retailer!r} vs {source!r} matchte fälschlich: {d.reason}"
    if marker:
        assert marker in d.reason


@pytest.mark.parametrize(
    "retailer,source",
    [
        ("Château Margaux", "Pavillon Rouge du Château Margaux"),
        ("Château Lafite Rothschild", "Carruades de Lafite Rothschild"),
        ("Château Latour Pauillac", "Les Forts de Latour"),
        ("Château Cos d'Estournel", "Les Pagodes de Cos"),
    ],
)
def test_french_second_wines_are_rejected(retailer, source):
    """Zweitweine nach französischem Muster: der Cuvée-Name steht *vor* dem Gut, nicht
    dahinter. Das darf nicht als Produzentenpräfix durchgehen."""
    d = match_wine(retailer, source)
    assert not d.matched, f"{retailer!r} vs {source!r} matchte fälschlich: {d.reason}"


@pytest.mark.parametrize(
    "retailer,source",
    [
        # Führendes Wort ohne Betriebsform beim Händler = Produzent, erlaubt.
        ("Passìo Nero d'Avola Perricone Sicilia DOC", "Settesoli Passìo Nero d'Avola Perricone"),
        ("Château Ste Michelle Chardonnay", "Chateau Ste Michelle Chardonnay"),
        ("Fattoria Le Pupille Saffredi Maremma", "Fattoria Le Pupille Saffredi"),
        ("Domaine Weinbach Riesling", "Domaine Weinbach Riesling"),
    ],
)
def test_producer_prefix_is_still_allowed(retailer, source):
    d = match_wine(retailer, source)
    assert d.matched, f"{retailer!r} vs {source!r} wurde fälschlich abgelehnt: {d.reason}"


@pytest.mark.parametrize(
    "retailer,source",
    [
        # Beide Namen bestehen nur aus Rebsorte/Farbe -> kein Produzentenbezug.
        ("Heldenrosé Rosé de Gamay", "Perdono Rosé di Gamay"),
        # Nur Region und Qualitätsstufe gemeinsam.
        ("Castelbarco Valpolicella Ripasso Superiore", "Valpolicella Ripasso Superiore"),
        ("Denner Merlot del Ticino", "Merlot del Ticino"),
        # Appellation ohne Produzent ist kein Wein, sondern eine Gattung.
        ("Rosso di Montalcino DOC", "Rosso di Montalcino"),
    ],
)
def test_generic_tokens_alone_are_not_a_match(retailer, source):
    """Rebsorte, Region, Farbe und Qualitätsstufe kommen in hunderten Weinen vor.
    Ohne einen Anker aus Produzent, Marke oder Lage gibt es keine Bewertung — sonst
    erbt eine Denner-Eigenmarke die Note eines fremden Produzenten."""
    d = match_wine(retailer, source)
    assert not d.matched, f"{retailer!r} vs {source!r} matchte fälschlich: {d.reason}"
    assert "generische" in d.reason or "zu wenig" in d.reason


def test_unrelated_wines_do_not_match():
    d = match_wine("Denner Carmelin Blanc", "Château d'Yquem Sauternes")
    assert not d.matched
    assert d.confidence is MatchConfidence.NONE


# --------------------------------------------------------------- Winery-Pfad

def test_winery_level_match_for_col_del_sol():
    """Zeile 6: Der Wein ist nicht bewertet, der Produzent existiert. Der schwache
    Pfad muss greifen, damit die Vivino-Spalte einen Link liefern kann."""
    d = match_winery("Col del Sol Brut Prosecco Superiore Valdobbiadene", "Col del Sol")
    assert d.matched, d.reason
    assert d.confidence is MatchConfidence.WINERY_LEVEL


def test_winery_level_rejects_unrelated_producer():
    d = match_winery("Col del Sol Brut Prosecco Valdobbiadene", "Cantina Zaccagnini")
    assert not d.matched


# --------------------------------------------------------------- Ambiguität

def test_ambiguous_when_two_different_wines_score_equally():
    hits, ambiguous = rank_candidates(
        "Rossetti Linda Bolgheri",
        [("Rossetti Linda Bolgheri", None, False), ("Rossetti Linda Bolgheri", 2021, True)],
    )
    # Gleicher Wein in zwei Jahrgängen ist NICHT uneindeutig.
    assert not ambiguous
    assert len(hits) == 2


def test_rank_candidates_drops_vetoed_entries():
    hits, _ = rank_candidates(
        "Guado al Tasso Bolgheri Superiore",
        [
            ("Antinori Tenuta Guado al Tasso Il Bruciato Bolgheri", 2022, True),
            ("Guado al Tasso Bolgheri Superiore", 2022, True),
        ],
    )
    assert len(hits) == 1
    assert hits[0].decision.source_name == "Guado al Tasso Bolgheri Superiore"


# --------------------------------------------------------------- Normalisierung

def test_vintage_extraction_ignores_volume():
    assert extract_vintage("Barolo 2019 75 cl") == 2019
    assert extract_vintage("Bag-in-Box 3 l 750 ml") is None
    assert extract_vintage("Anima Negra ÀN/2 IGP Illes Balears 2022") == 2022


def test_tokenize_strips_noise_keeps_identity():
    toks = tokenize("Passìo Nero d'Avola/Perricone Sicilia DOC 75 cl 2022")
    assert "passio" in toks
    assert "perricone" in toks
    assert "doc" not in toks
    assert "cl" not in toks
    assert "2022" not in toks


def test_normalized_name_is_stable_across_spelling_variants():
    assert normalized_name("Ànima Negra AN/2") == normalized_name("Anima Negra ÀN/2")


def test_dedup_key_ignores_word_order_but_not_vintage():
    """Dedup über normalisierten Namen + Jahrgang — derselbe Wein bei Coop und Prodega
    muss auf denselben Key fallen."""
    a = dedup_key("Tenute Rossetti Linda Bolgheri DOC", 2021)
    b = dedup_key("Rossetti Linda Bolgheri", 2021)
    assert a == b
    assert dedup_key("Rossetti Linda Bolgheri", 2022) != a

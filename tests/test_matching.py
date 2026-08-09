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
    assert any(w in d.reason for w in ("generische", "zu wenig", "unterscheidendes Wort")), d.reason


def test_bulk_wine_does_not_inherit_a_burgundy_rating():
    """Regression aus dem ersten Live-Lauf: "Montagne Vin Rouge" (Prodega-Fasswein,
    CHF 1.21/75cl) hing an "Marsannay 'La Montagne' Rouge" (Burgunder, 4.0 aus 382
    Bewertungen). Nach Abzug von "Vin" und "Rouge" bleibt ein einziges, häufiges Wort —
    zu wenig Identität, und die Quelle nennt zusätzlich den Produzenten."""
    for retailer in (
        "Montagne Vin Rouge",
        "Montagne Vin Rouge PET",          # "PET" ist Verpackung, kein Namensbestandteil
        "Montagne Vin Rouge Europa/Drittländer",
    ):
        d = match_wine(retailer, "Marsannay 'La Montagne' Rouge")
        assert not d.matched, f"{retailer!r} matchte fälschlich: {d.reason}"


def test_short_name_still_matches_when_source_adds_nothing():
    """Gegenprobe: sind beide Namen gleich spezifisch, gibt es nichts zu verwechseln."""
    for retailer, source in [
        ("Argiano Rosso di Montalcino DOC", "Argiano Rosso di Montalcino"),
        ("Domaine Weinbach Riesling", "Domaine Weinbach Riesling"),
    ]:
        d = match_wine(retailer, source)
        assert d.matched, f"{retailer!r} wurde fälschlich abgelehnt: {d.reason}"


def test_long_brand_name_carries_a_match_on_its_own():
    """"Domherrenwein" ist lang und kollidiert kaum — ein einzelnes solches Wort
    genügt, anders als "Montagne"."""
    d = match_wine(
        "Domherrenwein Fendant du Valais AOC",
        "Provins Valais Les Grands Dignitaires Domherrenwein Fendant",
    )
    assert d.matched, d.reason


def test_parent_company_prefix_is_not_a_second_wine():
    """Regression: "Il Bruciato Bolgheri DOC Tenuta Guado al Tasso" ist derselbe Wein
    wie "Antinori Tenuta Guado al Tasso Il Bruciato Bolgheri" — "Antinori" ist das
    Haus, nicht eine andere Cuvée. Der Händlername ist hier spezifisch genug und
    vollständig abgedeckt, anders als bei "Château Margaux"."""
    d = match_wine(
        "Il Bruciato Bolgheri DOC Tenuta Guado al Tasso",
        "Antinori Tenuta Guado al Tasso Il Bruciato Bolgheri",
    )
    assert d.matched, f"wurde fälschlich abgelehnt: {d.reason}"
    # Die Gegenrichtung bleibt ein Nicht-Treffer.
    reverse = match_wine(
        "Guado al Tasso Bolgheri DOC Superiore",
        "Antinori Tenuta Guado al Tasso Il Bruciato Bolgheri",
    )
    assert not reverse.matched, reverse.reason


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


def test_second_label_does_not_inherit_the_grand_vin_producer_average():
    """Regression aus der Webseite: "Bordeaux AC Mouton Cadet Baron Ph de Rothschild"
    für CHF 9.95 bekam über den Produzenten-Pfad die 4.6 von Château Mouton Rothschild
    aus 92'093 Bewertungen — einem Premier Grand Cru Classé. "Cadet" ist genau der
    Unterschied zwischen der Zweitmarke und dem Erstwein."""
    d = match_winery(
        "Bordeaux AC Mouton Cadet Baron Ph de Rothschild (2023) – Rotwein, Frankreich",
        "Château Mouton Rothschild",
    )
    assert not d.matched, d.reason
    assert "Cadet" in d.reason


def test_generic_extras_still_allow_the_producer_average():
    """Gegenprobe: Schaumwein-Dosage und Herkunft sind keine eigene Linie. Sonst
    verliert der schwache Pfad seinen Zweck."""
    d = match_winery("Col del Sol Brut Prosecco Superiore Valdobbiadene", "Col del Sol")
    assert d.matched, d.reason

    d2 = match_winery("Piccini Chianti Classico Riserva DOCG", "Piccini")
    assert d2.matched, "Region und Qualitätsstufe sind generisch, kein eigener Linienname"


# ------------------------------------------- Farbe aus dem Rohtext (Regression)

def test_rotwein_in_the_retailer_name_blocks_a_white_source():
    """„Rotwein" steht in LEGAL_DESIGNATIONS und fliegt aus den Tokens — für die
    Suchabfrage richtig, für die Farbprüfung fatal.

    Der Händler schreibt die Farbe fast immer genau so an („… – Rotwein, Spanien").
    Ohne diesen Griff auf den Rohtext fehlt sie einseitig, einseitiges Fehlen ist
    erlaubt, und der rote „Chivite Coleccion 125" bekam die 4.2 des Blanco.
    """
    d = match_wine(
        "Navarra DO Chivite Coleccion 125 (2017) – Rotwein, Spanien (75cl)",
        "Chivite Navarra Coleccion 125 Blanco 2023",
    )
    assert not d.matched, d.reason
    assert "Farbe" in d.reason


@pytest.mark.parametrize("retailer,source", [
    # Farbe nur auf einer Seite, kein Widerspruch — muss weiter durchgehen.
    ("Ribera del Duero DO Protos Roble (2024) – Rotwein, Spanien", "Protos Roble 2024"),
    ("Fontanafredda Barolo DOCG 2018 – Rotwein, Italien", "Fontanafredda Barolo"),
    ("Rueda DO Verdejo Legaris – Weisswein, Spanien", "Legaris Rueda Verdejo"),
])
def test_compound_colour_does_not_block_when_there_is_no_conflict(retailer, source):
    d = match_wine(retailer, source)
    assert d.matched, f"{retailer!r} wurde fälschlich abgelehnt: {d.reason}"


def test_colour_from_text_reads_compound_words():
    from winecheck.names import colour_from_text
    assert colour_from_text("… – Rotwein, Spanien") == "rot"
    assert colour_from_text("Chardonnay – Weisswein") == "weiss"
    assert colour_from_text("Gamay – Roséwein, Schweiz") == "rose"
    assert colour_from_text("Barolo DOCG") is None


# ---------------------------------------- Beiwörter gegen Identitätsbestandteile

#: Händlernamen tragen Region, Land, Farbe und Flaschengrösse mit, Vivino nennt nur
#: den Wein. Diese Beiwörter drückten Score und Abdeckung und liessen damit richtige
#: Treffer als „unbestätigt" durchgehen — bei 39 % der bewerteten Weine. Für die
#: Konfidenz zählt darum zusätzlich der Vergleich nur der unterscheidenden Teile.
@pytest.mark.parametrize("retailer,source,vintage", [
    # Der Fall aus dem Auftrag: Vivino-ID stimmte, Markierung trotzdem „unsicher".
    ("Mendoza 2021 Chardonnay Alta Angelica Zapata",
     "Catena Zapata Angélica Zapata Chardonnay Alta 2021", 2021),
    ("Rioja DOCa Crianza Bodegas Izadi (2022) – Rotwein, Spanien (0.75l)",
     "Izadi Crianza 2022", 2022),
    ("Valais AOC Cornalin Fleur du Rhône (2024) – Rotwein, Schweiz (0.75l)",
     "Fleur du Rhône Cornalin 2024", 2024),
    ("Ribera del Duero DO Protos Roble (2024) – Rotwein, Spanien (0.75l)",
     "Protos Roble 2024", 2024),
    ("Valais AOC Dôle des Monts Maison Gilliard (2023) – Rotwein, Schweiz",
     "Maison Gilliard Dôle des Monts 2023", 2023),
])
def test_side_words_no_longer_make_a_correct_match_uncertain(retailer, source, vintage):
    d = match_wine(retailer, source, retailer_vintage=vintage, source_vintage=vintage,
                   source_has_vintage_rating=True)
    assert d.matched, d.reason
    assert d.confidence is not MatchConfidence.FUZZY, (
        f"nur Region/Land/Farbe weichen ab, trotzdem unsicher: {d.reason}"
    )


@pytest.mark.parametrize("retailer,source,vintage,missing", [
    # Vivino nennt den Produzenten nicht — dann bleibt es unsicher, auch wenn der
    # Rest wörtlich passt. Genau diese Fälle soll die Markierung erwischen.
    #
    # „Caves des Coteaux" ist der harte Fall: ``caves`` ist ein Betriebswort und
    # ``coteaux`` eine Appellation, nach den Tokens bleibt vom Produzenten nichts
    # übrig. Erkannt wird er nur über die Betriebsphrase.
    ("Neuchâtel AOC Oeil de Perdrix Rosé Caves des Coteaux (2025)",
     "Oeil de Perdrix Rosé", 2025, "Coteaux"),
    ("Ribera del Duero DO Pàramos Legaris (2022) – Rotwein, Spanien (0.75l)",
     "Páramos", 2022, "Legaris"),
])
def test_missing_producer_stays_uncertain(retailer, source, vintage, missing):
    d = match_wine(retailer, source, retailer_vintage=vintage, source_vintage=vintage,
                   source_has_vintage_rating=True)
    assert d.confidence is MatchConfidence.FUZZY, (
        f"Produzent {missing!r} fehlt in der Quelle, Treffer trotzdem bestätigt: {d.reason}"
    )
    assert missing in d.reason, (
        f"Die Begründung soll das fehlende Wort nennen, steht aber nicht drin: {d.reason}"
    )


def test_reason_names_the_missing_word():
    """Ohne den fehlenden Bestandteil ist „ähnlich" nicht nachprüfbar."""
    d = match_wine("Zeni Bardolino DOC Classico Superiore", "Bardolino Classico")
    if d.confidence is MatchConfidence.FUZZY:
        assert "nennt" in d.reason and "nicht" in d.reason


def test_generic_source_entry_is_still_rejected():
    """Die Lockerung darf generische Vivino-Einträge nicht durchlassen."""
    for retailer, source in [
        ("Rioja Imperial Cune Reserva DOCa (2020) – Rotwein, Spanien", "Rioja Reserva"),
        ("Rueda DO Verdejo Marqués de Riscal 6x 75cl (2024)", "Verdejo"),
        ("Malanser Steinadler Pinot Noir (2024) – Rotwein, Schweiz", "Pinot Noir"),
    ]:
        d = match_wine(retailer, source, source_has_vintage_rating=True)
        assert d.confidence is MatchConfidence.NONE, (
            f"generischer Eintrag {source!r} wurde angenommen: {d.reason}"
        )


def test_producer_phrase_guard_catches_a_winery_named_after_its_appellation():
    """Direkt am Schutz, nicht am Gesamtergebnis.

    „Caves des Coteaux": ``caves`` ist ein Betriebswort und fliegt beim
    Tokenisieren; gilt ``coteaux`` als Appellation, bleibt vom Produzenten nichts
    übrig und der Identitätsvergleich sieht ihn als vollständig gedeckt. Ob das
    passiert, hängt am handgepflegten Vokabular — der Schutz greift unabhängig davon.
    """
    from winecheck.matching import _uncovered_producer_words, prepare
    retailer = prepare("Neuchâtel AOC Oeil de Perdrix Rosé Caves des Coteaux (2025)")
    assert _uncovered_producer_words(retailer, prepare("Oeil de Perdrix Rosé")), \
        "ungedeckter Betriebsname wurde nicht erkannt"
    # Nennt die Quelle den Betrieb, greift der Schutz nicht.
    assert _uncovered_producer_words(
        prepare("Rioja DOCa Crianza Bodegas Izadi (2022)"), prepare("Izadi Crianza 2022")
    ) == []
    # Ohne Betriebswort im Händlernamen ist nichts zu prüfen.
    assert _uncovered_producer_words(
        prepare("Mendoza 2021 Chardonnay Alta Angelica Zapata"),
        prepare("Catena Zapata Angélica Zapata Chardonnay Alta 2021"),
    ) == []


# ------------------------- Zwei Weine, zwei Produzenten (Regression 7.8.2026)

def test_a_different_producer_is_a_different_wine():
    """„Gevrey-Chambertin **Faiveley**" bekam die 4.3 von „**Regnard**
    Gevrey-Chambertin Rouge". Die Appellation ist identisch, der Produzent nicht.
    Gemeinsame Wörter gibt es genug, darum reichte die Ankerregel nicht — beide Seiten
    tragen zusätzlich einen eigenen Namen, und das sind zwei verschiedene Weine."""
    d = match_wine("Gevrey-Chambertin Faiveley 2022, 75 cl", "Regnard Gevrey-Chambertin Rouge")
    assert not d.matched, d.reason
    assert "Faiveley" in d.reason and "Regnard" in d.reason


def test_same_producer_still_matches():
    """Gegenprobe: einseitige Zusätze bleiben erlaubt."""
    assert match_wine("Gevrey-Chambertin Faiveley 2022", "Faiveley Gevrey-Chambertin").matched


def test_a_source_without_any_distinctive_word_cannot_be_this_wine():
    """„Rioja Imperial Cune Reserva" gegen einen Eintrag namens schlicht „Rioja
    Reserva": Score 100, weil nach Abzug von Herkunft und Qualitätsstufe auf beiden
    Seiten fast nichts übrig blieb. Ein Fundname ohne jedes unterscheidende Wort ist
    ein Sammeleintrag und kann per Konstruktion nicht dieser Wein sein."""
    d = match_wine("Rioja Imperial Cune Reserva DOCa (2020) – Rotwein, Spanien", "Rioja Reserva")
    assert not d.matched, d.reason
    assert "unterscheidendes Wort" in d.reason


@pytest.mark.parametrize("source", [
    "Cune (CVNE) Crianza",
    "Cune (CVNE) Rosado",
])
def test_parenthetical_alias_is_not_an_extra_name(source):
    """Vivino führt Produzenten mit Zweitnamen in Klammern. „CVNE" galt als
    zusätzlicher Namensbestandteil, der dem Händlernamen fehlt — und liess damit
    richtige Treffer durchfallen."""
    retailer = ("Rioja DOCa Crianza Cune (2022) – Rotwein, Spanien" if "Crianza" in source
                else "Rioja DOCa Rosado Cune 6x 75cl (2025) – Roséwein, Spanien")
    assert match_wine(retailer, source).matched


def test_long_parentheses_are_kept():
    """Nur Zweitnamen fliegen raus. „(Magnum 1.5 Liter Flasche)" ist kein Alias."""
    from winecheck.names import strip_alias
    assert strip_alias("Barolo (Magnum 1.5 Liter Flasche)") == "Barolo (Magnum 1.5 Liter Flasche)"
    assert "CVNE" not in strip_alias("Cune (CVNE) Crianza")


def test_region_words_do_not_count_against_coverage():
    """„Insoglio del Cinghiale **Toscana** IGP Tenuta di Biserno" gegen „Biserno
    **Campo di Sasso** Insoglio del Cinghiale": alle drei unterscheidenden Wörter des
    Händlers stecken in der Quelle, es fehlte nur „Toscana". Über alle Tokens gerechnet
    waren das 75 % Abdeckung — unter der Schwelle, und der Wein fiel als
    Zweitwein-Verdacht durch. „Campo di Sasso" ist Bisernos zweites Gut, kein anderer
    Wein.

    Händlernamen tragen Region, Land und Farbe mit, Vivino nennt sie oft nicht. Jedes
    solche Wort drückte die Abdeckung und damit einen richtigen Treffer."""
    d = match_wine(
        "Insoglio del Cinghiale Toscana IGP Tenuta di Biserno, 75 cl",
        "Biserno Campo di Sasso Insoglio del Cinghiale 2020",
    )
    assert d.matched, d.reason


def test_a_missing_producer_still_caps_the_confidence():
    """Gegenprobe zur Abdeckungsänderung. Bei kurzen Namen steigt die Abdeckung über
    unterscheidende Wörter schnell über die Schwelle — „Oeil de Perdrix Rosé Caves des
    Coteaux" gegen ein blosses „Oeil de Perdrix Rosé" käme sonst auf ``exact``, obwohl
    der Produzent fehlt und diesen Rosé-Typ viele Neuenburger Häuser keltern."""
    d = match_wine(
        "Neuchâtel AOC Oeil de Perdrix Rosé Caves des Coteaux (2025)",
        "Oeil de Perdrix Rosé",
        retailer_vintage=2025, source_vintage=2025, source_has_vintage_rating=True,
    )
    assert d.confidence is MatchConfidence.FUZZY, d.reason


@pytest.mark.parametrize("retailer,source,marker", [
    ("Navarra DO Chivite Coleccion 125 (2017) – Rotwein, Spanien",
     "Chivite Navarra Vendimia Tardia Coleccion 125", "Vendimia"),
    ("La Porte de Novembre VdP Suisse Maison Gilliard",
     "Maison Gilliard Porte de Novembre Ice", "Ice"),
])
def test_sweet_wine_markers_are_a_different_wine(retailer, source, marker):
    """„Passito", „Recioto" und „Eiswein" standen schon in den Qualitätsstufen, die
    fremdsprachigen Entsprechungen nicht — und daran fiel es auf: ein roter „Chivite
    Coleccion 125" bekam die Note des gleichnamigen **Vendimia Tardía**, eines
    Spätlese-Süssweins desselben Hauses.

    Diese Wörter stehen nie zufällig da: wer sie auf einer Seite liest und auf der
    anderen nicht, hat zwei verschiedene Weine vor sich."""
    d = match_wine(retailer, source)
    assert not d.matched, d.reason
    assert marker in d.reason


def test_a_real_late_harvest_still_matches():
    """Gegenprobe: steht die Angabe auf beiden Seiten, ist es derselbe Wein."""
    assert match_wine(
        "Navarra DO Chivite Coleccion 125 Vendimia Tardia",
        "Chivite Navarra Vendimia Tardia Coleccion 125",
    ).matched


def test_our_own_producer_hint_does_not_count_against_the_match():
    """Mövenpick nennt den Produzenten nur in der Adresse; wir hängen ihn an. Stand er
    ohne Klammern im Namen, rechnete der Matcher **uns** an, was wir selbst ergänzt
    hatten: „Douro DOC 2023 Quinta do Vale Meão, Olazabal Filhos" gegen „Quinta do Vale
    Meão Douro 2023" wurde `fuzzy`, weil die Quelle „Olazabal Filhos" nicht nennt — den
    Firmennamen, den Vivino gar nicht führt. In Klammern trägt der Name den Produzenten
    für die Suche, ohne den Vergleich zu stören."""
    d = match_wine(
        "Douro DOC 2023 Quinta do Vale Meão (Olazabal Filhos)",
        "Quinta do Vale Meão Douro 2023",
        retailer_vintage=2023, source_vintage=2023, source_has_vintage_rating=True,
    )
    assert d.confidence is MatchConfidence.EXACT, d.reason


def test_the_query_still_sees_the_producer_in_parentheses():
    """Gegenprobe: für die Suche ist der Produzent das wichtigste Wort und muss bleiben."""
    from winecheck.names import query_tokens
    assert "olazabal" in query_tokens("Douro DOC 2023 Quinta do Vale Meão (Olazabal Filhos)")


def test_a_critic_score_in_the_name_is_not_part_of_the_name():
    """„Châteauneuf-du-Pape Vieux Télégraphe **Parker 95**" — Vivino kennt keine
    Kritikernote im Weinnamen, also galt „Parker" als fehlender Bestandteil und stufte
    einen Volltreffer auf „unbestätigt"."""
    d = match_wine(
        "Châteauneuf-du-Pape Vieux Télégraphe Parker 95, AOC 2023, 75 cl",
        "Domaine du Vieux Télégraphe Châteauneuf-du-Pape (La Crau) 2023",
        retailer_vintage=2023, source_vintage=2023, source_has_vintage_rating=True,
    )
    assert d.confidence is MatchConfidence.EXACT, d.reason


def test_a_winery_named_parker_survives():
    """Entfernt wird nur, wenn eine Zahl folgt — sonst verschwände das Weingut Parker
    in Coonawarra."""
    from winecheck.names import distinctive_tokens
    assert "parker" in distinctive_tokens("Parker Coonawarra Estate Terra Rossa")
    assert "parker" not in distinctive_tokens("Vieux Télégraphe Parker 95")


def test_a_higher_tier_is_a_different_wine():
    """„Murua Rioja Reserva **Especial**" für CHF 17.90 bekam die Note der schlichten
    „Murua Reserva" — zwei Weine desselben Guts, eine Ausbaustufe auseinander.
    „Selezione" stand schon in den Qualitätsstufen, die spanischen Entsprechungen
    nicht."""
    d = match_wine("Murua Rioja Reserva Especial Bodegas Murua", "Murua Murua Reserva 2017")
    assert not d.matched, d.reason
    assert "Especial" in d.reason


def test_the_plain_reserva_still_matches_its_own_entry():
    assert match_wine("Rioja Reserva Bodegas Murua", "Murua Murua Reserva 2017").matched


@pytest.mark.xfail(reason="bekannte Lücke, siehe Kommentar über _foreign_token_analysis")
def test_selbst_ergaenzter_produzent_darf_nicht_gegen_den_treffer_zaehlen():
    """Mövenpick nennt den Produzenten nur in der Adresse; der Adapter hängt ihn in
    Klammern an. Für die Suche ist das nötig, für den Vergleich wird er gestrichen —
    und dann trägt Vivino zwei Wörter, die unser Name scheinbar nicht kennt.

    Der Treffer stimmt nachweislich: Vivino führt "Poggio Al Tesoro Livrone 2023"
    mit Note 4.0.
    """
    from winecheck.matching import rank_candidates

    ranked, _ = rank_candidates(
        "Toscana IGT 2023 Livrone (Poggio Tesoro)",
        [("Poggio Al Tesoro Livrone", 2023, True)],
        retailer_vintage=2023,
    )
    assert ranked, "der gefundene und richtige Kandidat wird verworfen"

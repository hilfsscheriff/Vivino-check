"""Tests der Vivino-Statuslogik.

``classify`` ist eine reine Funktion — die Statuslogik lässt sich damit vollständig
ohne Netz prüfen. Der Live-Test steht in ``test_vivino_live.py`` und läuft nur mit
``WINECHECK_LIVE=1``.

Zentrale Zusicherung in jedem Test: ``vivino_url`` ist niemals leer, auch beim
Nicht-Treffer. Kein leeres Feld, kein Gedankenstrich.
"""

import pytest

from winecheck.models import VivinoStatus
from winecheck.ratings.vivino import _Cand, build_query, classify


def cand(
    name,
    *,
    year=None,
    v_avg=None,
    v_count=0,
    w_avg=None,
    w_count=0,
    winery="",
    wine_name="",
    url="https://www.vivino.com/de/slug/w/123",
):
    return _Cand(
        name=name,
        wine_name=wine_name or name,
        winery=winery,
        url=url,
        year=year,
        vintage_avg=v_avg,
        vintage_count=v_count,
        wine_avg=w_avg,
        wine_count=w_count,
    )


# ------------------------------------------------------------ Pflichtspalte

def test_no_entry_still_yields_search_url_and_query():
    """Zeile 7 der Fixtures: Noirillon existiert nicht. Trotzdem Suchurl ausgeben,
    damit selbst klickbar ist, ob die Query schlecht war oder der Wein fehlt."""
    r = classify("Noirillon Assemblage de cépages rouges AOC Vaud", 2023, "noirillon assemblage", [])
    assert r.status is VivinoStatus.NO_ENTRY
    assert r.url.startswith("https://www.vivino.com/de/explore?search_term=")
    assert "noirillon" in r.url.lower()
    assert r.query == "noirillon assemblage"
    assert r.rating is None
    assert r.note  # nie leer


def test_no_entry_when_all_candidates_are_vetoed():
    """Die Vivino-Suche ist auf Recall gebaut: 'Carmelin' liefert 'Carmelo Rodero'.
    Das darf keine Bewertung ergeben."""
    r = classify(
        "Carmelin Vin de Pays Romand",
        2022,
        "carmelin vin de pays romand",
        [
            cand("Carmelo Rodero Raza 2021", year=2021, v_avg=4.2, v_count=443, w_avg=4.1, w_count=784),
            cand("Carmelo Rodero Reserva 2021", year=2021, v_avg=4.3, v_count=52, w_avg=4.4, w_count=7598),
        ],
    )
    assert r.status is VivinoStatus.NO_ENTRY
    assert r.rating is None
    assert "Kandidaten geprüft" in r.note
    assert r.url.startswith("https://www.vivino.com/de/explore?search_term=")


def test_every_status_has_a_nonempty_url_and_note():
    """Harte Anforderung: nie ein leeres Feld."""
    results = [
        classify("Irgendwas", None, "irgendwas", []),
        classify(
            "Provins Les Grands Dignitaires Domherrenwein Fendant",
            2023,
            "q",
            [cand("Provins Les Grands Dignitaires Domherrenwein Fendant 2023",
                  year=2023, v_avg=3.6, v_count=42, w_avg=3.4, w_count=1136)],
        ),
    ]
    for r in results:
        assert r.url
        assert r.note
        assert r.query


# ------------------------------------------------------------ exact / wine_level

def test_exact_for_matching_vintage():
    """Domherrenwein Fendant: Jahrgang 2023 mit 42 Bewertungen."""
    r = classify(
        "Domherrenwein Fendant du Valais AOC",
        2023,
        "domherrenwein fendant valais",
        [cand("Provins Valais Les Grands Dignitaires Domherrenwein Fendant 2023",
              year=2023, v_avg=3.6, v_count=42, w_avg=3.4, w_count=1136,
              winery="Provins Valais")],
    )
    assert r.status is VivinoStatus.EXACT
    assert r.rating == 3.6
    assert r.rating_count == 42
    assert "2023" in r.note
    assert r.url.endswith("/w/123")
    assert r.matched_name


def test_wine_level_when_vintage_differs():
    """Jahrgang weicht ab -> Weinschnitt, klar als solcher benannt."""
    r = classify(
        "Domherrenwein Fendant du Valais AOC",
        2021,
        "domherrenwein fendant valais",
        [cand("Provins Valais Les Grands Dignitaires Domherrenwein Fendant 2023",
              year=2023, v_avg=3.6, v_count=42, w_avg=3.4, w_count=1136)],
    )
    assert r.status is VivinoStatus.WINE_LEVEL
    assert r.rating == 3.4
    assert r.rating_count == 1136
    assert "Weinschnitt" in r.note


def test_wine_level_when_retailer_has_no_vintage():
    r = classify(
        "Domherrenwein Fendant du Valais AOC",
        None,
        "domherrenwein fendant valais",
        [cand("Provins Valais Les Grands Dignitaires Domherrenwein Fendant 2023",
              year=2023, v_avg=3.6, v_count=42, w_avg=3.4, w_count=1136)],
    )
    assert r.status is VivinoStatus.WINE_LEVEL
    assert r.rating == 3.4


# ------------------------------------------------------------ too_few_ratings

def test_too_few_ratings_keeps_the_link():
    """Zeile 6 der Fixtures: Seite existiert, Vivino zeigt keine Note. Der Link ist
    hier mehr wert als eine Zahl."""
    r = classify(
        "Col del Sol Brut Prosecco Superiore Valdobbiadene",
        2023,
        "col del sol brut prosecco superiore valdobbiadene",
        [cand("Col del Sol Brut Prosecco Superiore Valdobbiadene 2023",
              year=2023, v_avg=None, v_count=4, w_avg=None, w_count=4,
              url="https://www.vivino.com/de/col-del-sol/w/999")],
    )
    assert r.status is VivinoStatus.TOO_FEW_RATINGS
    assert r.rating is None
    assert r.rating_count == 4
    assert "nur 4 Bewertungen" in r.note
    assert r.url == "https://www.vivino.com/de/col-del-sol/w/999"


def test_zero_ratings_is_too_few_not_no_entry():
    r = classify(
        "Venvole Vully Rouge Assemblage",
        2022,
        "venvole vully rouge assemblage",
        [cand("Venvole Vully Rouge Assemblage 2022", year=2022, v_count=0, w_count=0)],
    )
    assert r.status is VivinoStatus.TOO_FEW_RATINGS
    assert r.rating is None
    assert r.url.endswith("/w/123")


# ------------------------------------------------------------ winery_level

def test_winery_level_when_only_producer_matches():
    r = classify(
        "Col del Sol Brut Prosecco Superiore Valdobbiadene",
        2023,
        "col del sol",
        [cand("Col del Sol Cartizze Dry 2022", year=2022, w_avg=3.8, w_count=210,
              winery="Col del Sol", url="https://www.vivino.com/de/cartizze/w/777")],
    )
    assert r.status in (VivinoStatus.WINERY_LEVEL, VivinoStatus.WINE_LEVEL)
    assert r.url == "https://www.vivino.com/de/cartizze/w/777"
    assert r.rating is not None


def test_winery_level_marks_rating_as_weak():
    """Der Wein selbst passt nicht (Cartizze ist eine andere Lage), nur der Produzent."""
    r = classify(
        "Col del Sol Prosecco Frizzante",
        2023,
        "col del sol prosecco frizzante",
        [cand("Col del Sol Valdobbiadene Cartizze Superiore 2022", year=2022,
              w_avg=3.8, w_count=210, winery="Col del Sol")],
    )
    assert r.status in (VivinoStatus.WINERY_LEVEL, VivinoStatus.TOO_FEW_RATINGS,
                        VivinoStatus.NO_ENTRY)
    assert r.url
    if r.status is VivinoStatus.WINERY_LEVEL:
        assert "Produzenten-Durchschnitt" in r.note


# ------------------------------------------------------------ ambiguous

def test_ambiguous_lists_up_to_three_candidates_instead_of_choosing():
    r = classify(
        "Rossetti Linda Bolgheri",
        None,
        "rossetti linda bolgheri",
        [
            cand("Rossetti Linda Bolgheri Bianco", year=2022, w_avg=3.9, w_count=120,
                 url="https://www.vivino.com/de/a/w/1"),
            cand("Rossetti Linda Bolgheri Rosso", year=2022, w_avg=4.1, w_count=140,
                 url="https://www.vivino.com/de/b/w/2"),
        ],
    )
    # Weiss gegen Rot ist ein Farbwiderspruch, beide werden abgelehnt -> kein Raten.
    assert r.status in (VivinoStatus.AMBIGUOUS, VivinoStatus.NO_ENTRY)
    assert r.url
    if r.status is VivinoStatus.AMBIGUOUS:
        assert 2 <= len(r.candidates) <= 3
        assert all(c.url for c in r.candidates)
        assert r.rating is None, "bei Uneindeutigkeit wird keine Note gewählt"


def test_same_wine_two_vintages_is_not_ambiguous():
    r = classify(
        "Rossetti Linda Bolgheri",
        2021,
        "rossetti linda bolgheri",
        [
            cand("Rossetti Linda Bolgheri 2021", year=2021, v_avg=4.0, v_count=60,
                 w_avg=4.0, w_count=300),
            cand("Rossetti Linda Bolgheri 2020", year=2020, v_avg=3.9, v_count=55,
                 w_avg=4.0, w_count=300),
        ],
    )
    assert r.status is VivinoStatus.EXACT
    assert r.rating == 4.0


# ------------------------------------------------------------ Query-Bau

def test_build_query_strips_noise():
    q = build_query("Passìo Nero d'Avola/Perricone Sicilia DOC 6 × 75 cl Aktion 2022", 2022)
    assert "doc" not in q.split()
    assert "cl" not in q.split()
    assert "2022" not in q
    assert "aktion" not in q
    assert "passio" in q


def test_build_query_never_empty():
    assert build_query("DOC 75 cl") != ""


@pytest.mark.parametrize("status", list(VivinoStatus))
def test_all_statuses_have_a_german_label(status):
    from winecheck.models import VIVINO_LABELS

    assert status in VIVINO_LABELS
    assert VIVINO_LABELS[status]


# --------------------------------- Reihenfolge der Suchbegriffe (Regression)

def test_short_query_is_tried_before_the_long_one():
    """Die kurze Abfrage muss zuerst laufen, nicht erst bei no_entry.

    Vivino sortiert nach Bewertung, nicht nach Namensähnlichkeit. „ribera duero protos
    roble spanien" liefert 13 Treffer, angeführt von „Protos 27 Ribera del Duero"
    (4.2 aus 43'583 Bewertungen) — einem anderen Wein. „protos roble" liefert zwei,
    beide richtig.

    Vorher lief die kurze Abfrage nur, wenn die lange *nichts* fand. Beide
    Protos-Weine bekamen aber einen falschen, aber akzeptierten Treffer — ein
    Fehltreffer verhinderte so den Treffer.
    """
    from winecheck.names import distinctive_tokens
    from winecheck.ratings.vivino import build_query

    name = "Ribera del Duero DO Protos Roble (2024) – Rotwein, Spanien (75cl)"
    lang = build_query(name)
    kurz = " ".join(distinctive_tokens(name)[:4])

    assert "ribera" in lang and "spanien" in lang, "die lange Abfrage trägt Herkunft und Land"
    assert kurz == "protos roble", f"die kurze Abfrage ist der Kern des Namens, war {kurz!r}"
    assert "ribera" not in kurz and "spanien" not in kurz


def test_rank_prefers_a_real_match_over_a_producer_average():
    """Bei zwei Abfragen gewinnt das aussagekräftigere Ergebnis. Ein Produzenten-Ø
    steht unter einer Kandidatenliste: aus drei Vorschlägen kann ein Mensch wählen,
    ein Durchschnitt tut nur so, als wäre er die Note dieses Weins."""
    from winecheck.models import VivinoStatus
    from winecheck.ratings.vivino import VivinoAdapter

    r = VivinoAdapter._RANK
    assert r[VivinoStatus.EXACT] > r[VivinoStatus.WINE_LEVEL] > r[VivinoStatus.AMBIGUOUS]
    assert r[VivinoStatus.AMBIGUOUS] > r[VivinoStatus.WINERY_LEVEL]
    assert r[VivinoStatus.WINERY_LEVEL] > r[VivinoStatus.NO_ENTRY]


# ------------------------- Farbe über Vivinos Weintyp (Regression 8.8.2026)

@pytest.mark.parametrize("name,type_id,konflikt", [
    # Ein weisser Vermentino bekam die 4.2 eines Brunello di Montalcino für CHF 11.50.
    # Beide Namen tragen kein Farbwort — die Farbe steckt nur in der Rebsorte.
    ("Vermentino San Felice Toscana IGT 2025, 75 cl", 1, True),
    ("Toscana Colli Aretini – Il Borro Chardonnay", 1, True),
    ("Roncaia Merlot Bianco Ticino DOC", 1, True),
    ("Pinot Grigio delle Venezie", 1, True),
    # Passt zusammen: kein Konflikt.
    ("Vermentino San Felice Toscana IGT 2025, 75 cl", 2, False),
    # Schaumwein ist keine Farbe — ein Prosecco darf weiss *und* Schaumwein sein.
    ("Chardonnay Reserve", 3, False),
    # Ohne Farbhinweis im Namen wird nicht gesperrt.
    ("Barolo DOCG Fontanafredda", 1, False),
])
def test_vivino_wine_type_beats_a_missing_colour_word(name, type_id, konflikt):
    from winecheck.ratings.vivino import _farbkonflikt
    assert _farbkonflikt(name, type_id) is konflikt


def test_a_grape_after_an_article_is_a_proper_name():
    """„Chianti Classico Riserva **Il Grigio** da San Felice" ist ein Roter — „Grigio"
    gehört zum Weinnamen, nicht zur Sorte. Die erste Fassung der Farbprüfung nahm ihm
    seine korrekte Note weg; solche Namen taugen nicht als Farbquelle."""
    from winecheck.ratings.vivino import _farbkonflikt
    assert _farbkonflikt("Chianti Classico Riserva Il Grigio da San Felice", 1) is False

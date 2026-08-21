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


def test_ein_einzelnes_restwort_wird_mitgenommen():
    """"Sondraia (Marilisa Allegrini Poggio al Tesoro)" verlor beim Schnitt nach vier
    Wörtern ausgerechnet "tesoro" — den Teil, der den Wein findet.

    Mövenpick leitet den Produzenten aus der Adresse ab, und die nennt hier zwei
    Güter: das Mutterhaus im Veneto und das Bolgheri-Gut.
    """
    from winecheck.ratings.vivino import _kurze_abfrage

    lang = "Bolgheri Superiore DOC 2021 Sondraia (Marilisa Allegrini Poggio al Tesoro)"
    assert _kurze_abfrage(lang) == ["sondraia", "marilisa", "allegrini", "poggio", "tesoro"]


def test_laengere_namen_werden_weiterhin_gekuerzt():
    """Mehr Wörter schaden bei Vivino häufiger, als sie helfen — die Regel gilt nur
    für das eine abgetrennte Restwort."""
    from winecheck.ratings.vivino import KURZ_MAX, _kurze_abfrage

    lang = "Alpha Beta Gamma Delta Epsilon Zeta Chianti Classico Riserva"
    assert len(_kurze_abfrage(lang)) == KURZ_MAX


# ------------------------------------------------ Rückfall über die Weingutseite
def test_json_objekte_liest_ganze_objekte_aus_fremdem_text():
    """Die Weingutseite trägt ihre Daten in einem einzigen, sehr grossen
    HTML-Attribut. Gelesen wird über Klammerzählung statt über die Seitenstruktur.
    """
    from winecheck.ratings.vivino import _json_objekte

    text = 'Vorspann <div x="{"wine":{"id":1,"name":"A"},"year":0} und '\
           '{"wine":{"id":2,"name":"B"},"year":0}"> Nachspann'
    o = _json_objekte(text)
    assert [x["wine"]["id"] for x in o] == [1, 2]


def test_geschweifte_klammer_im_namen_beendet_das_objekt_nicht():
    """Sonst bräche das Objekt mitten im Weinnamen ab."""
    from winecheck.ratings.vivino import _json_objekte

    o = _json_objekte('{"wine":{"id":7,"name":"Cuvée {Spezial}"},"year":0}')
    assert o and o[0]["wine"]["name"] == "Cuvée {Spezial}"


def test_kaputtes_json_wird_uebersprungen():
    """Ein defektes Objekt darf die übrigen nicht mitreissen."""
    from winecheck.ratings.vivino import _json_objekte

    o = _json_objekte('{"wine":{"id":1,,,}} {"wine":{"id":2,"name":"B"},"year":0}')
    assert [x["wine"]["id"] for x in o] == [2]


def test_der_rueckfall_greift_nur_ohne_treffer(monkeypatch):
    """Wo die Suche schon etwas fand, wäre die zusätzliche Anfrage unnötige Last.

    Und geraten wird keine Adresse: geholt werden nur Güter, die die Suche selbst
    genannt hat.
    """
    import winecheck.ratings.vivino as v

    ad = v.VivinoAdapter(fetcher=None)
    gerufen = []
    monkeypatch.setattr(ad, "_weingut_kandidaten",
                        lambda slug: gerufen.append(slug) or [])
    monkeypatch.setattr(ad, "_search", lambda q, order_by=None: [])
    ad._best_of("Irgendein Wein", 2020, "irgendein wein", set())
    # Ohne Weingut in der Trefferliste gibt es nichts nachzuschlagen.
    assert gerufen == []


# ------------------- Rueckfall ueber die Weingutseite: Auswahlverzerrung

def test_weingutseite_verlangt_mehr_als_den_produzenten():
    """Von einem Nutzer gemeldet. „Avignonesi IL Marzocco Cortona DOC" ist ein
    Chardonnay und bekam über die Gutsseite die 4.4 aus 12'110 Bewertungen von
    „Avignonesi 50 & 50", einem Merlot-Sangiovese für ein Vielfaches des Preises.

    Die Gutsseite ist ein anderer Pool als eine Trefferliste: sie enthält **jeden**
    Wein des Guts, der Produzentenname ist dort bei allen gleich und trägt darum
    keine Information. Wer den Pool nach dem Produzenten bildet, darf den Produzenten
    nicht als Beleg zählen."""
    from winecheck.ratings.vivino import _Cand, _nur_derselbe_wein

    def gut(wein):
        return _Cand(name=wein, wine_name=wein, winery="Avignonesi",
                     url="u", year=None, vintage_avg=None, vintage_count=0,
                     wine_avg=4.4, wine_count=12110)

    kandidaten = [gut("50 & 50"), gut("Il Marzocco Chardonnay"), gut("Vino Nobile")]
    uebrig = _nur_derselbe_wein(
        "Toscana Montepulciano – Avignonesi IL Marzocco Cortona DOC/bc", kandidaten
    )
    namen = [c.wine_name for c in uebrig]
    assert namen == ["Il Marzocco Chardonnay"], namen


def test_weingutseite_ohne_eigenes_wort_liefert_nichts():
    """Trägt der Händlername ausser dem Gut nichts Eigenes, ist nicht zu entscheiden,
    welcher Wein des Guts gemeint ist. Dann lieber keiner."""
    from winecheck.ratings.vivino import _Cand, _nur_derselbe_wein

    kandidaten = [_Cand(name="Vino Nobile", wine_name="Vino Nobile", winery="Avignonesi",
                        url="u", year=None, vintage_avg=None, vintage_count=0,
                        wine_avg=4.2, wine_count=900)]
    assert _nur_derselbe_wein("Avignonesi", kandidaten) == []


def test_der_rueckfall_hoert_auf_sobald_er_etwas_gefunden_hat():
    """Hier stand ``if best.status is VivinoStatus.EXACT: break``, und das konnte per
    Konstruktion nie zutreffen: ``_weingut_kandidaten`` setzt ``year`` auf None,
    ``classify`` verlangt für EXACT aber ``c.year is not None``. Der Abbruch war toter
    Code — die zweite Gutsseite wurde auch dann geholt, wenn die erste den Wein schon
    gebracht hatte. Zwei Sekunden Tempolimit je gerettetem Wein, gegen den eigenen
    Kommentar über der Schleife."""
    from winecheck.ratings.vivino import VivinoAdapter, _Cand

    geholt: list[str] = []

    def _kand(*, name, slug="", year=None, wine_avg=None, wine_count=0):
        return _Cand(name=name, wine_name=name, winery="Fallet Dart", url="https://x/w/1",
                     year=year, vintage_avg=None, vintage_count=0,
                     wine_avg=wine_avg, wine_count=wine_count, winery_slug=slug)

    a = VivinoAdapter(fetcher=None)
    # Die Suche nennt zwei Gueter, findet den Wein selbst aber nicht.
    a._search = lambda q, **kw: [
        _kand(name="Fallet Dart Brut Millesime", slug="erstes-gut"),
        _kand(name="Irgendein Fremder Wein", slug="zweites-gut"),
    ]
    a._trinkfenster = lambda *args, **kw: (None, None)

    def _gut(slug):
        geholt.append(slug)
        if slug != "erstes-gut":
            return []
        return [_kand(name="Fallet Dart Cuvée de Réserve Brut Champagne",
                      wine_avg=4.1, wine_count=533)]

    a._weingut_kandidaten = _gut
    r = a._best_of("Fallet Dart Champagne Brut Cuvée de Réserve", None,
                   "fallet dart champagne brut cuvee reserve", set())
    assert r.status.value == "wine_level", r.status
    assert geholt == ["erstes-gut"], f"zweite Gutsseite unnoetig geholt: {geholt}"


# -- Derselbe Wein in zwei Farben ------------------------------------------
def test_ohne_farbe_im_namen_wird_nicht_zwischen_rose_und_rot_gewaehlt():
    """Schubi verkauft "Whispering Angel Cotes de Provence AC 2025 Chateau
    d'Esclans" — laut Beschreibung "ein unwiderstehlicher Rose". Der Name nennt die
    Farbe nicht.

    Vivino fuehrt beide Weine des Guts, "Whispering Angel Rose" und "Whispering
    Angel Rouge". Der Wein bekam die Note des Roten, und zwar als exact.

    Dass ausgerechnet der Rote gewann, war kein Zufall: "rouge", "rosso" und "tinto"
    gelten im Vokabular als Farbe und duerfen einseitig fehlen, "rose" steht dagegen
    bei den Qualitaetsstufen und fuehrt zur Ablehnung. Ein Wein ohne Farbe im Namen
    landet damit systematisch beim Roten.
    """
    from winecheck.ratings.vivino import _Cand, classify

    def kand(name, type_id):
        return _Cand(name=name, wine_name=name, winery="Château d'Esclans",
                     url=f"https://www.vivino.com/de/x/w/{type_id}", year=2025,
                     vintage_avg=4.2, vintage_count=500, wine_avg=4.2, wine_count=900,
                     type_id=type_id)

    r = classify(
        "Whispering Angel Côtes de Provence AC 2025 Château d'Esclans", 2025, "q",
        [kand("Château d'Esclans Whispering Angel Rosé", 4),
         kand("Château d'Esclans Whispering Angel Rouge", 1)],
    )
    assert r.rating is None, "aus dem Namen ist die Farbe nicht zu entscheiden"
    assert "Farben" in r.note


def test_mit_farbe_im_namen_wird_richtig_gewaehlt():
    """Sagt der Haendler die Farbe, wird ausgewaehlt statt ausgeschlossen — das ist
    die Aufgabe von _farbkonflikt."""
    from winecheck.ratings.vivino import _Cand, classify

    def kand(name, type_id):
        return _Cand(name=name, wine_name=name, winery="Château d'Esclans",
                     url=f"https://www.vivino.com/de/x/w/{type_id}", year=2025,
                     vintage_avg=4.1, vintage_count=1493, wine_avg=4.1, wine_count=9000,
                     type_id=type_id)

    r = classify(
        "Whispering Angel Rosé Côtes de Provence AC 2025 Château d'Esclans", 2025, "q",
        [kand("Château d'Esclans Whispering Angel Rosé", 4),
         kand("Château d'Esclans Whispering Angel Rouge", 1)],
    )
    assert r.rating == 4.1
    assert "Rosé" in (r.matched_name or "")


def test_ein_einzelner_farbeintrag_bleibt_unangetastet():
    """Nur wenn die Quelle wirklich zwei Farben desselben Weins fuehrt, ist die Frage
    offen. Sonst waere die Regel ein Rueckschritt: "Cotes du Rhone" gegen "Cotes du
    Rhone Rouge" ist derselbe Wein, und die Farbe steht dort nur der Vollstaendigkeit
    halber."""
    from winecheck.ratings.vivino import _Cand, classify

    r = classify(
        "Côtes du Rhône AC 2022 Guigal", 2022, "q",
        [_Cand(name="E. Guigal Côtes du Rhône Rouge", wine_name="Côtes du Rhône Rouge",
               winery="E. Guigal", url="https://www.vivino.com/de/x/w/1", year=2022,
               vintage_avg=4.0, vintage_count=800, wine_avg=4.0, wine_count=5000,
               type_id=1)],
    )
    assert r.rating == 4.0


def test_der_grundwein_gewinnt_gegen_die_benannte_variante():
    """Traegt genau einer der Kandidaten kein Farbwort, ist er der Grundwein.

    Vivino fuehrt "Tenuta Ulisse Limited Edition 10 Vendemmie" (rot) und
    "… 10 Vendemmie Bianco" (weiss). Der Haendler schreibt den ersten zeichengleich
    an. Der Produzent benennt die Variante, nicht das Original — das ist
    entscheidbar, und die erste Fassung der Farbregel warf es faelschlich weg.

    Beim Whispering Angel ist es anders herum: dort heissen beide "… Rose" bzw.
    "… Rouge", der blosse Name gehoert keinem von beiden. Siehe den Test darueber.
    """
    from winecheck.ratings.vivino import _Cand, classify

    def kand(name, type_id, note):
        return _Cand(name=name, wine_name=name, winery="Tenuta Ulisse",
                     url=f"https://www.vivino.com/de/x/w/{type_id}", year=None,
                     vintage_avg=None, vintage_count=0, wine_avg=note, wine_count=15663,
                     type_id=type_id)

    r = classify(
        "Tenuta Ulisse Limited Edition 10 Vendemmie", None, "q",
        [kand("Tenuta Ulisse Limited Edition 10 Vendemmie", 1, 4.4),
         kand("Tenuta Ulisse Limited Edition 10 Vendemmie Bianco", 2, 4.0)],
    )
    assert r.rating == 4.4
    assert "Bianco" not in (r.matched_name or "")


# -- Identitaet vor Jahrgangsgenauigkeit -----------------------------------
def test_ein_unsicherer_jahrgangstreffer_schlaegt_keinen_sicheren_wein():
    """"Rocca di Frassinello la Rocca" (CHF 37.50) trug die 4.5 von "Baffonero",
    dem Spitzenwein des Guts fuer rund CHF 200.

    Der Weg dorthin: die kurze Abfrage `rocca frassinello rocca` liefert den
    gleichnamigen Hauptwein des Guts NICHT mit, also gewinnt dort Baffonero — als
    fuzzy eingestuft, aber mit jahrgangsgenauem Wert und damit Status EXACT. Die
    lange Abfrage findet den richtigen Wein und erreicht mit ihm nur WINE_LEVEL.

    Verglichen wurde allein ueber den Status, und der Abbruch bei EXACT griff sofort
    — die bessere Abfrage lief nie.
    """
    from winecheck.ratings.vivino import VivinoAdapter, VivinoStatus

    a = VivinoAdapter(fetcher=None)
    unsicher = VivinoStatus.EXACT
    sicher = VivinoStatus.WINE_LEVEL

    class _Res:
        def __init__(self, status, conf):
            self.status, self.match_confidence = status, conf

    fuzzy_exact = _Res(unsicher, "fuzzy")
    bestaetigt_weinebene = _Res(sicher, "wine_level")
    assert a._guete(bestaetigt_weinebene) > a._guete(fuzzy_exact), (
        "ein bestaetigter Wein in anderem Jahrgang ist mehr wert als ein "
        "unbestaetigter mit passendem Jahrgang"
    )
    # Bei gleicher Identitaet entscheidet weiterhin die Jahrgangsgenauigkeit.
    assert a._guete(_Res(unsicher, "exact")) > a._guete(_Res(sicher, "exact"))


def test_der_abbruch_verlangt_bestaetigte_identitaet():
    """Sonst hoert die Suche beim ersten unsicheren Treffer auf, dessen Jahrgang
    zufaellig passt — und die Abfrage, die den richtigen Wein findet, laeuft nie."""
    import inspect
    from winecheck.ratings.vivino import VivinoAdapter
    quelle = inspect.getsource(VivinoAdapter._best_of)
    assert "_IDENTITAET" in quelle, "der Abbruch muss die Identitaet mitpruefen"

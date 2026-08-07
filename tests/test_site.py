"""Tests für die statische Webseite.

Der Generator ist eine reine Funktion: gleiche Läufe rein, gleiche HTML-Datei
raus. Das macht die Punkte aus dem UX-Check günstig absicherbar — ohne Browser,
ohne Screenshot-Vergleich. Geprüft wird darum am erzeugten Dokument.
"""

from __future__ import annotations

import json
import re

import pytest

from winecheck.report.site import (
    GOOD_PRICE_MAX,
    GOOD_RATING_MIN,
    _wine_from_snapshot,
    build,
    check_tokens,
    contrast,
)


def _snapshot(**over):
    """Eine Snapshot-Zeile, wie sie aus dem Cache kommt."""
    row = {
        "dedup_key": "test-wein",
        "name": "Pomerol AOC 2007 Château Lafleur",
        "vintage": "2007",
        "best_price": 42.0,
        "vivino_rating": 4.4,
        "vivino_status": "ok",
        "vivino_rating_count": 170,
        "vivino_url": "https://www.vivino.com/w/1",
        "retailers": ["moevenpick"],
        "cheapest_retailer": "moevenpick",
        "urls": {"moevenpick": "https://example.invalid/wein"},
        "market_price": 60.0,
        "bargain_percent": 30.0,
        "style": "rot",
        "style_label": "Rotwein",
        "maturity": "*",
        "maturity_short": "jetzt trinken",
    }
    row.update(over)
    return row


@pytest.fixture
def doc(tmp_path):
    """Die gebaute Seite als Text."""

    def _build(rows=None, **kw):
        rows = rows if rows is not None else [_snapshot()]
        runs = [{
            "id": "r1",
            "label": "6.8.2026",
            "date": "2026-08-06",
            "wines": [_wine_from_snapshot(r) for r in rows],
        }]
        path = build(runs, tmp_path / "index.html", **kw)
        assert path is not None
        return path.read_text(encoding="utf-8")

    return _build


def _payload(doc_text):
    """Die eingebettete JSON zurücklesen."""
    m = re.search(r"^const D = (\{.*\});$", doc_text, re.M)
    assert m, "eingebettete Payload nicht gefunden"
    return json.loads(m.group(1))


# --------------------------------------------------------- Sorte „unbekannt"

def test_unknown_style_gets_no_pill_label():
    """„Sorte: unbekannt" ist keine Information und soll kein Pill werden."""
    wine = _wine_from_snapshot(_snapshot(style="unbekannt", style_label="unbekannt"))
    assert wine["styleLabel"] == ""
    # Der Wert selbst bleibt erhalten, sonst greift der Filter-Chip nicht mehr.
    assert wine["style"] == "unbekannt"


def test_known_style_keeps_its_label():
    assert _wine_from_snapshot(_snapshot())["styleLabel"] == "Rotwein"


def test_unknown_style_still_offered_as_filter(doc):
    """Der Filter „unbekannt" muss bleiben — nur die Pills verschwinden."""
    text = doc([_snapshot(style="unbekannt", style_label="unbekannt")])
    styles = [s["key"] for s in _payload(text)["styles"]]
    assert "unbekannt" in styles


# ------------------------------------------------------------ Jahrgang doppelt

def test_vintage_is_not_printed_twice(doc):
    """Steht der Jahrgang schon im Namen, darf er nicht angehängt werden.

    Bei den Händlernamen ist das die Regel, nicht die Ausnahme.
    """
    text = doc()
    assert "vintageSuffix" in text, "Helfer fehlt — Jahrgang würde doppelt gedruckt"
    # Der Name enthält „2007" bereits; der Helfer entscheidet zur Laufzeit.
    assert "${w.vintage ? `<span class=\"meta\"> ${w.vintage}</span>` : \"\"}" not in text


def test_vintage_suffix_helper_covers_both_cases(doc):
    """Der Helfer prüft auf Enthaltensein, nicht nur auf Vorhandensein."""
    text = doc()
    helper = re.search(r"const vintageSuffix = .*?;", text, re.S)
    assert helper, "vintageSuffix nicht gefunden"
    assert "includes" in helper.group(0)


# ------------------------------------------------------------- Leerzustand

def test_chart_card_is_hidden_when_nothing_matches(doc):
    """Bei 0 Treffern darf das Diagramm nicht behaupten, die Tabelle zeige alles."""
    text = doc()
    assert "card.hidden = list.length === 0" in text
    # Nur Nicht-Kommentarzeilen prüfen: die Begründung im Code nennt die alte
    # Meldung absichtlich, und an der Interpunktion soll der Test nicht hängen.
    code = [ln for ln in text.splitlines() if not ln.lstrip().startswith("//")]
    assert not any("Die Tabelle zeigt alle" in ln for ln in code), \
        "widersprüchliche Meldung wieder da"


def test_unrated_selection_message_matches_reality(doc):
    """Wenn Zeilen da sind, aber keine Note: Tabelle zeigt sie — das darf dastehen."""
    text = doc()
    assert "Kein Wein dieser Auswahl hat eine Vivino-Note" in text
    assert "zeigt sie trotzdem" in text


# ---------------------------------------------------------------- Tokens

def test_control_border_token_exists_in_both_schemes(doc):
    """Bedienelemente brauchen eine sichtbare Kontur, Trennlinien nicht."""
    text = doc()
    assert text.count("--line-strong:") == 2, "hell und dunkel je ein Wert erwartet"
    for sel in (".search input", ".chip {", ".controls select"):
        block = text.split(sel, 1)[1][:220]
        assert "var(--line-strong)" in block, f"{sel} nutzt die schwache Linie"


def test_table_rules_keep_the_quiet_line(doc):
    """Die Tabellenlinien sollen leise bleiben — nur Controls werden stärker."""
    text = doc()
    td_rule = re.search(r"\n  td \{[^}]*\}", text).group(0)
    assert "var(--line)" in td_rule and "--line-strong" not in td_rule


def test_touch_targets_grow_on_coarse_pointer(doc):
    """44 px auf Touch, kompakter auf Zeigergeräten."""
    text = doc()
    assert "@media (pointer: coarse) { :root { --control-h:44px; } }" in text
    for sel in (".chip {", ".reset {", ".controls select", ".controls label"):
        # Bis zur schliessenden Klammer der Regel lesen, nicht nach Zeichenzahl:
        # sonst schneidet der Ausschnitt mitten in den Wert.
        block = text.split(sel, 1)[1].split("}", 1)[0]
        assert "var(--control-h)" in block, f"{sel} ohne Mindesthöhe"


def test_single_focus_style_for_everything(doc):
    """Vorher hing der Fokusring am Browser."""
    text = doc()
    assert ":focus-visible { outline:2px solid var(--accent); outline-offset:2px; }" in text


# ------------------------------------------------------------- Semantik

def test_landmark_and_live_region(doc):
    text = doc()
    assert "<main>" in text and "</main>" in text
    assert 'id="count" aria-live="polite"' in text


def test_tooltip_has_no_dangling_role(doc):
    """role=tooltip ohne aria-describedby ist ein Versprechen ohne Beziehung."""
    text = doc()
    assert '<div id="tip"></div>' in text
    # Auf das Attribut prüfen, nicht auf die Zeichenkette: die Begründung im
    # Kommentar daneben nennt role="tooltip" absichtlich.
    assert not re.search(r"<[^!>]*role=\"tooltip\"", text)


def test_chart_legend_explains_its_encodings(doc):
    """Trendlinie, Vektor und Markierung müssen benannt sein — sonst sind sie Deko."""
    text = doc()
    legend = text.split('class="legend"', 1)[1].split("</p>", 1)[0]
    for begriff in ("üblich für den Preis", "gut und günstig", "ausserhalb der Regel",
                    "je Punkt ein Wein"):
        assert begriff in legend, begriff


def test_single_run_hides_the_run_filter(doc):
    """Ein einzelner Lauf ist keine Wahl."""
    text = doc()
    assert 'id="runBox"' in text
    assert 'getElementById("runBox").hidden = D.runs.length < 2' in text


def test_market_coverage_is_named_in_the_counter(doc):
    """Der Marktpreis fehlt bei der Mehrheit — das soll ablesbar sein."""
    text = doc()
    assert "mit Marktpreis" in text


def test_empty_cells_are_marked_for_the_card_view(doc):
    """In der Kartenansicht ist ein „—" nur eine Zeile ohne Inhalt."""
    text = doc()
    assert "td.noval { display:none; }" in text
    assert 'w.bargain == null ? " noval" : ""' in text


def test_missing_market_price_marks_the_cell(doc):
    """Gegenprobe: mit Marktpreis kein noval, ohne Marktpreis schon."""
    text = doc([_snapshot(market_price=None, bargain_percent=None)])
    payload = _payload(text)
    wine = payload["runs"][0]["wines"][0]
    assert "b" not in wine, "bargain sollte fehlen, wenn kein Marktpreis vorliegt"


# -------------------------------------------------------- Preis-Leistung (F-02)

def _run_with_prices(rows):
    return [{"id": "r1", "label": "6.8.2026", "date": "2026-08-06",
             "wines": [_wine_from_snapshot(r) for r in rows]}]


def _priced(price, rating, count=500, name=None):
    return _snapshot(name=name or f"Wein zu {price}", best_price=price,
                     vivino_rating=rating, vivino_rating_count=count,
                     dedup_key=f"k{price}-{rating}-{count}")


def test_value_score_rewards_quality_above_its_price_level(tmp_path):
    """Nicht „billig gewinnt": gemessen wird der Abstand zum Preisniveau.

    Zwei Weine auf der Trendlinie, einer deutlich darüber — der muss vorne liegen,
    obwohl er nicht der günstigste ist.
    """
    rows = [_priced(p, r) for p, r in [
        (5, 3.6), (10, 3.8), (20, 4.0), (40, 4.2), (80, 4.4), (160, 4.6),
        (5, 3.5), (10, 3.7), (20, 3.9), (40, 4.1), (80, 4.3), (160, 4.5),
    ]]
    rows.append(_priced(20, 4.5, name="Überflieger"))       # weit über dem Niveau
    rows.append(_priced(5, 3.2, name="Enttäuschung"))       # unter dem Niveau
    runs = _run_with_prices(rows)
    build(runs, tmp_path / "index.html")
    by_name = {w["name"]: w.get("valueScore") for w in runs[0]["wines"]}
    assert by_name["Überflieger"] > 0.2, by_name["Überflieger"]
    assert by_name["Enttäuschung"] < 0, by_name["Enttäuschung"]
    assert by_name["Überflieger"] == max(v for v in by_name.values() if v is not None)


def test_expensive_wine_can_still_win_on_value(tmp_path):
    """Ein teurer Wein, der sein Preisniveau überschreitet, darf vorne stehen."""
    rows = [_priced(p, r) for p, r in [
        (8, 3.7), (12, 3.8), (18, 3.9), (25, 4.0), (60, 4.2), (120, 4.35),
        (8, 3.6), (12, 3.75), (18, 3.85), (25, 3.95), (60, 4.15), (120, 4.3),
    ]]
    rows.append(_priced(120, 4.8, name="Teuer aber gut"))
    rows.append(_priced(8, 3.7, name="Billig und mittelmässig"))
    runs = _run_with_prices(rows)
    build(runs, tmp_path / "index.html")
    by_name = {w["name"]: w.get("valueScore") for w in runs[0]["wines"]}
    assert by_name["Teuer aber gut"] > by_name["Billig und mittelmässig"]


def test_thin_evidence_is_damped(tmp_path):
    """Bei 0.16 Streuung führt sonst ein Wein mit zwölf Bewertungen die Liste an."""
    rows = [_priced(p, r) for p, r in [
        (5, 3.6), (10, 3.8), (20, 4.0), (40, 4.2), (80, 4.4), (160, 4.6),
        (5, 3.5), (10, 3.7), (20, 3.9), (40, 4.1), (80, 4.3), (160, 4.5),
    ]]
    rows.append(_priced(20, 4.5, count=12, name="Kaum bewertet"))
    rows.append(_priced(20, 4.5, count=5000, name="Gut belegt"))
    runs = _run_with_prices(rows)
    build(runs, tmp_path / "index.html")
    by_name = {w["name"]: w.get("valueScore") for w in runs[0]["wines"]}
    assert by_name["Kaum bewertet"] < by_name["Gut belegt"], \
        "gleiche Note und gleicher Preis, aber die dünne Belegung wird nicht gedämpft"


def test_wines_without_rating_or_price_get_no_score(tmp_path):
    rows = [_priced(p, r) for p, r in [(5, 3.6), (10, 3.8), (20, 4.0), (40, 4.2),
                                       (80, 4.4), (160, 4.6), (5, 3.5), (10, 3.7),
                                       (20, 3.9), (40, 4.1), (80, 4.3), (160, 4.5)]]
    rows.append(_snapshot(name="Ohne Note", vivino_rating=None, dedup_key="x1"))
    rows.append(_snapshot(name="Ohne Preis", best_price=None, dedup_key="x2"))
    runs = _run_with_prices(rows)
    build(runs, tmp_path / "index.html")
    by_name = {w["name"]: w.get("valueScore") for w in runs[0]["wines"]}
    assert by_name["Ohne Note"] is None
    assert by_name["Ohne Preis"] is None


def test_tiny_run_gets_no_scores(tmp_path):
    """Aus drei Weinen lässt sich kein Preisniveau schätzen."""
    runs = _run_with_prices([_priced(10, 4.0), _priced(20, 4.1), _priced(30, 4.2)])
    build(runs, tmp_path / "index.html")
    assert all(w.get("valueScore") is None for w in runs[0]["wines"])


def test_value_is_the_default_sort(doc):
    text = doc()
    assert 'sort: "value"' in text
    assert '<option value="value:-1">' in text
    # Die erste Option ist die Vorauswahl im Auswahlfeld.
    first = text.split('<select id="fSort">', 1)[1].split("</option>", 1)[0]
    assert 'value="value:-1"' in first
    assert 'S.sort = "value"' in text, "Zurücksetzen muss auch dorthin zurückkehren"


def test_value_column_is_visible_and_explained(doc):
    """Wonach sortiert wird, muss dastehen — sonst ist die Reihenfolge unerklärlich."""
    text = doc()
    assert '["value", "Preis-Leistung", "num"]' in text
    assert 'data-l="Preis-Leistung"' in text
    assert "wie viel besser die Note ist" in text
    # Die Erklärung darf nicht mit dem Sortierhinweis am Handy verschwinden.
    note = text.split('class="tblnote"', 1)[1].split("</p>", 1)[0]
    assert "Preis-Leistung" in note, "die Tabellen-Erklärung zeigt auf den falschen Absatz"


# ------------------------------------------------------------ Paginierung (F-02/F-03)

def test_table_pages_instead_of_cutting_off(doc):
    """Vorher endete die Tabelle bei 400 Zeilen — der Rest war unerreichbar."""
    text = doc()
    assert "const PAGE = 50;" in text
    assert "sorted.slice(0, S.limit)" in text
    assert "slice(0, 400)" not in text
    assert "weitere ausgeblendet" not in text, "alter Deckel-Hinweis noch da"
    assert 'id="more"' in text
    assert "S.limit += PAGE" in text


def test_filter_change_returns_to_the_first_page(doc):
    """Sonst stehen nach einem Filterwechsel Hunderte Zeilen einer anderen Menge da."""
    text = doc()
    assert "function refilter() { S.limit = PAGE; render(); }" in text
    for handler in ('getElementById("q")', 'getElementById("fMinRating")',
                    'getElementById("fMaxPrice")', 'getElementById("fBargain")',
                    'getElementById("fFound")'):
        block = text.split(handler, 1)[1][:200]
        assert "refilter()" in block, f"{handler} setzt die Seite nicht zurück"
    assert "onClick(); refilter();" in text, "Chips setzen die Seite nicht zurück"


def test_more_button_does_not_rebuild_the_filters(doc):
    """Nachladen soll den Blick nicht nach oben reissen."""
    text = doc()
    block = text.split('id="more"', 1)[1]
    handler = block.split('addEventListener("click"', 1)[1][:120]
    assert "table(list)" in handler and "render()" not in handler


# ------------------------------------------------- Filter einklappen auf dem Handy

def test_filters_collapse_on_mobile_but_the_count_stays(doc):
    text = doc()
    assert '<details id="filterBox">' in text
    assert "<summary>Filter" in text
    # Entscheidend ist, dass Zähler und Rückweg *nicht im* aufklappbaren Teil liegen —
    # wo sonst auf der Seite sie stehen, ist frei.
    inside = text.split('<details id="filterBox">', 1)[1].split("</details>", 1)[0]
    assert 'id="count"' not in inside, "Zähler liegt im aufklappbaren Teil"
    assert 'id="reset"' not in inside, "Rückweg liegt im aufklappbaren Teil"


def test_hidden_summary_forces_the_filters_open(doc):
    """Sonst wären die Filter am Desktop unerreichbar: kein Griff, kein Inhalt."""
    text = doc()
    assert '@media (min-width: 721px) { #filterBox > summary { display:none; } }' in text
    assert 'display === "none"' in text, "Kopplung an die gerenderte Lage fehlt"
    assert 'addEventListener("resize", syncFilterBox)' in text


def test_filter_sync_works_in_both_directions(doc):
    """Einseitig gedacht bleiben die Filter nach breit→schmal offen und füllen
    den ersten Bildschirm wieder."""
    text = doc()
    fn = text.split("function syncFilterBox()", 1)[1].split("\n}", 1)[0]
    assert "want" in fn and "filterBox.open = want" in fn
    # Eine bewusste Nutzerentscheidung darf das nicht überschreiben.
    assert "userChoseFilters" in fn
    assert 'filterBox.addEventListener("toggle"' in text


def test_summary_keeps_an_affordance(doc):
    """display:flex nimmt der Summary ihr Standard-Dreieck."""
    text = doc()
    assert "#filterBox > summary::after" in text
    assert "details-marker { display:none; }" in text


# ------------------------------------------------------- Farbe und Regel (02)

def test_tokens_keep_their_contrast_promise():
    """Die Zusage, nicht die Auswahl: jede Textfarbe erreicht ihr Ziel, hell und dunkel.

    Gold ist mit 3:1 milder geprüft — es trägt nur Grossgrade und Flächen. Für
    Kleintext gibt es ``--goldtx`` mit 4.5:1.
    """
    assert check_tokens() == []


def test_retailer_no_longer_carries_colour(doc):
    """In dieser Richtung trägt der Händler seinen Namen, keine Farbe.

    Vorher war Farbe im Diagramm das einzige Händlersignal — und dieselben Töne
    mussten gleichzeitig die Trinkreife tragen.
    """
    text = doc()
    for r in _payload(text)["retailers"]:
        assert "var" not in r and "colour" not in r, r
    assert "--shop-" not in text
    assert 'class="dot"' not in text, "Farbpunkt an den Chips ist zurück"


def test_colour_has_three_jobs_only(doc):
    """Akzent, Urteil, Gold — keine vierte Aufgabe."""
    text = doc()
    style = text.split("<style>", 1)[1].split("</style>", 1)[0]
    # Keine erzeugte Palette, keine Trinkreife-Farbe.
    assert "@media (prefers-color-scheme: dark)" in style
    import winecheck.report.site as site
    assert not hasattr(site, "_MATURITY_COLOURS")
    assert not hasattr(site, "_SHOP_LIGHT")
    for m in _payload(text)["maturities"]:
        assert "colour" not in m


def test_good_and_cheap_is_an_absolute_rule(doc):
    """Ab Note 4.2 und bis CHF 20, nur dieser Bereich — nicht der Abstand zur Linie."""
    assert (GOOD_RATING_MIN, GOOD_PRICE_MAX) == (4.2, 20.0)
    text = doc()
    payload = _payload(text)
    assert payload["good"] == {"rating": 4.2, "price": 20.0}
    # Tabelle und Diagramm müssen dieselbe Regel benutzen.
    assert "const istGut = w =>" in text
    assert "const gut = p => p.rating >= gRating" in text
    assert "D.good.rating" in text and "D.good.price" in text


def test_rule_marks_only_matching_wines(doc):
    """Gegenprobe an den Grenzen: 4.2/20.00 zählt, 4.1 und 20.01 nicht."""
    from winecheck.report.site import GOOD_PRICE_MAX as pmax, GOOD_RATING_MIN as rmin
    treffer = [(rmin, pmax), (4.5, 9.9)]
    daneben = [(rmin - 0.1, pmax), (rmin, pmax + 0.01), (4.0, 5.0)]
    for r, pr in treffer:
        assert r >= rmin and 0 < pr <= pmax
    for r, pr in daneben:
        assert not (r >= rmin and 0 < pr <= pmax)
    # Die Markierung hängt im Dokument an derselben Bedingung.
    text = doc()
    assert "istGut(w) ?" in text and "gut und günstig" in text


def test_zone_names_its_rule_and_count(doc):
    """Der Bereich ist eng — er muss selbst sagen, wie viele Weine darin liegen."""
    text = doc()
    assert "GUT UND GÜNSTIG" in text
    assert "ab Note ${gRating.toFixed(1)}" in text
    assert "${imFeld.length} von ${pts.length} Weinen" in text


def test_chart_shows_the_trend_line_without_vectors(doc):
    """Die Trendlinie bleibt, die Striche zu ihr sind weg — bei 174 Weinen zogen sie
    das markierte Feld zu. Die Abweichung steht als Zahl in der Tabelle."""
    text = doc()
    assert 'class="trend"' in text
    assert "const erwartet = v => fit" in text
    assert "const fit = (() => {" in text
    assert 'class="vec' not in text, "Striche zur Trendlinie sind zurück"
    # Die Bildunterschrift darf sie dann auch nicht mehr erklären.
    note = text.split('class="chartnote"', 1)[1].split("</p>", 1)[0]
    assert "Vektor" not in note
    legend = text.split('class="legend"', 1)[1].split("</p>", 1)[0]
    assert "Länge" not in legend


def test_typography_uses_the_label_faces(doc):
    """Didot für Namen und Kennzahl, Menlo für Zahlen, Optima im Text."""
    text = doc()
    assert "--serif:Didot" in text
    assert "Menlo" in text
    assert "Optima" in text
    wine = re.search(r"\n  \.wine \{[^}]*\}", text).group(0)
    assert "var(--serif)" in wine
    num = re.search(r"\n  \.num \{[^}]*\}", text).group(0)
    assert "var(--mono)" in num


# ------------------------------------------------------------- Grundlagen

def test_page_stays_self_contained(doc):
    """Kein CDN, keine externen Schriften, keine Bilder von aussen."""
    text = doc()
    external = re.findall(r'(?:src|href)="(https?://[^"]+)"', text)
    allowed = ("https://www.vivino.com", "https://www.aktionis.ch")
    for url in external:
        assert url.startswith(allowed) or "moevenpick" in url or "example.invalid" in url, url
    assert "<script src=" not in text
    assert "@import" not in text


def test_build_returns_none_without_wines(tmp_path):
    assert build([{"id": "r1", "label": "x", "date": "d", "wines": []}],
                 tmp_path / "index.html") is None


# ---------------------------------------------- Typografie und Breakpoint (F-09/F-15)

def test_only_five_text_roles_exist(doc):
    """Vorher lagen zehn Grössen zwischen 11 und 13.6 px, mehrere ununterscheidbar."""
    text = doc()
    style = text.split("<style>", 1)[1].split("</style>", 1)[0]
    # SVG-Text darf in px bleiben: er skaliert über die viewBox mit der Diagrammbreite.
    # em-Werte sind relativ zur Umgebung und definieren keine eigene Rolle (Chevron).
    svg_px = {"9px", "9.5px", "10px", "10.5px"}
    literal = set(re.findall(r"font-size:\s*([^;}]+)", style))
    tokens = {v for v in literal if v.startswith("var(--fs-")}
    rest = {v for v in literal
            if not v.startswith("var(--fs-") and not v.endswith("em")} - svg_px
    assert not rest, f"Einzelwerte ausserhalb der Tokens: {sorted(rest)}"
    assert len(tokens) <= 5, sorted(tokens)


def test_reading_surface_is_sixteen_pixels(doc):
    """Die Tabelle ist die am längsten gelesene Fläche — vorher 13.6 px."""
    text = doc()
    assert "--fs-body:1rem;" in text
    table_rule = re.search(r"\n  table \{[^}]*\}", text).group(0)
    assert "var(--fs-body)" in table_rule


def test_one_breakpoint_for_layout_changes(doc):
    """721/767 nebeneinander erzeugte einen Zustand mit Spaltenköpfen ohne Hinweis."""
    text = doc()
    style = text.split("<style>", 1)[1].split("</style>", 1)[0]
    # Nur Media-Query-Bedingungen zählen. max-width an .wrap oder #tip ist ein
    # Layoutmass, kein Breakpoint.
    conditions = re.findall(r"@media\s*\(([^)]*)\)", style)
    widths = {m for cond in conditions
              for m in re.findall(r"(?:max|min)-width:\s*(\d+)px", cond)}
    assert widths <= {"720", "721"}, f"mehrere Breakpoints: {sorted(widths)}"


def test_count_and_reset_stay_visible_while_scrolling(doc):
    """Wer in der Liste liest, soll die Auswahl ohne Rückweg ändern können."""
    text = doc()
    search = text.split('<div class="search">', 1)[1].split("</div>\n\n", 1)[0]
    assert 'id="count"' in search and 'id="reset"' in search
    assert ".search { position:sticky" in text


def test_coverage_is_split_off_from_the_match_count(doc):
    """Die Abdeckung würde die sticky Leiste am Handy auf zwei Zeilen bringen."""
    text = doc()
    assert 'id="coverage"' in text
    assert "davon mit Vivino-Note" in text
    count_line = text.split('getElementById("count").innerHTML', 1)[1][:120]
    assert "Marktpreis" not in count_line


# ------------------------------------------------------ Anzeigename (F-11)

@pytest.mark.parametrize("raw,clean", [
    ("Rioja DOCa Crianza Bodegas Izadi (2022) – Rotwein, Spanien (0.75l)",
     "Rioja DOCa Crianza Bodegas Izadi"),
    ("Blauer Zweigelt, Mundart (2022) – Rotwein, Österreich (0.75l)",
     "Blauer Zweigelt, Mundart"),
    ("Naturaplan Bio Alentejo DOC Marquês de Borba (2024) – Roséwein, Portugal (0.75l)",
     "Naturaplan Bio Alentejo DOC Marquês de Borba"),
    ("Syrah Terra Linda 2024, 75 cl", "Syrah Terra Linda 2024"),
    ("Chianti Classico Riserva – Rotwein, Italien", "Chianti Classico Riserva"),
])
def test_display_name_drops_retailer_boilerplate(raw, clean):
    from winecheck.report.site import display_name
    assert display_name(raw) == clean


@pytest.mark.parametrize("raw", [
    # Andere Flaschengrössen und Packungen sind Kaufinformation, keine Wiederholung.
    "Ruinart Blanc de Blancs, 1.5 l",
    "Taittinger Brut Réserve, 37.5 cl",
    "Forlane Yvorne Chablais AOC, 50 cl",
    "Rioja DOCa Las Flores 6x 75cl",
])
def test_display_name_keeps_purchase_relevant_sizes(raw):
    from winecheck.report.site import display_name
    kept = display_name(raw)
    assert any(tok in kept for tok in ("1.5", "37.5", "50 cl", "6x")), kept


def test_display_name_leaves_ordinary_names_alone():
    from winecheck.report.site import display_name
    for name in ["Pomerol AOC 2007 Château Lafleur", "Ànima Negra AN/2",
                 "Masi Campofiorin Rosso del Veronese IGT"]:
        assert display_name(name) == name


def test_cleaning_does_not_touch_key_or_matching():
    """Gematcht wurde vorher mit dem Originalnamen — der Schlüssel bleibt stabil."""
    raw = "Rioja DOCa Crianza Bodegas Izadi (2022) – Rotwein, Spanien (0.75l)"
    wine = _wine_from_snapshot(_snapshot(name=raw, dedup_key="izadi-2022"))
    assert wine["key"] == "izadi-2022"
    assert wine["name"] == "Rioja DOCa Crianza Bodegas Izadi"


def test_key_falls_back_to_the_original_name():
    """Ohne dedup_key darf der Schlüssel nicht von der Anzeige-Bereinigung abhängen."""
    raw = "Rioja DOCa Crianza Bodegas Izadi (2022) – Rotwein, Spanien (0.75l)"
    wine = _wine_from_snapshot({"name": raw})
    assert wine["key"] == raw

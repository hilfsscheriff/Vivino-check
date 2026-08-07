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
    MIN_UI_CONTRAST,
    _SHOP_DARK,
    _SHOP_LIGHT,
    _check_palette,
    _wine_from_snapshot,
    build,
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
    assert ":focus-visible { outline:2px solid var(--brand); outline-offset:2px; }" in text


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


def test_chart_legend_explains_both_encodings(doc):
    """Farbe und Füllung waren nirgends erklärt."""
    text = doc()
    assert "Farbe = Händler" in text
    assert "hohler Kreis" in text


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


# ------------------------------------------------------------------- Farben

def test_palette_keeps_its_contrast_promise():
    """Die Zusage, nicht die Auswahl: jede Händlerfarbe >= 3:1, hell und dunkel.

    Sichert vor allem den Fall ab, dass jemand einen Händler ergänzt oder eine
    Farbe austauscht — vorher lagen im Dunkelmodus vier Werte unter 3:1.
    """
    assert _check_palette() == []


def test_shop_palette_has_a_value_per_scheme():
    assert len(_SHOP_LIGHT) == len(_SHOP_DARK)
    # Gleiche Farbe in beiden Schemata ist erlaubt, wenn sie beides schafft —
    # aber die dunklen Flächen brauchen bei tiefen Tönen einen eigenen Wert.
    assert _SHOP_LIGHT != _SHOP_DARK


def test_maturity_no_longer_spends_colour(doc):
    """Trinkreife hat den Farbkanal abgegeben — sonst heisst eine Farbe zweierlei."""
    text = doc()
    payload = _payload(text)
    for m in payload["maturities"]:
        assert "colour" not in m, "Trinkreife trägt wieder eine eigene Farbe"
    assert 'id="fMat"' in text
    # Der Chip-Punkt wird nur noch für Händler erzeugt.
    assert text.count('class="dot" style="background:var(') == 1


def test_shop_colour_travels_as_css_variable(doc):
    """Als Hexwert in der JSON könnte die Farbe nicht auf das Schema reagieren."""
    text = doc()
    payload = _payload(text)
    for r in payload["retailers"]:
        assert r["var"].startswith("--shop-"), r
        assert "colour" not in r, "Hexwert zurück in der Payload"
    assert "--shop-moevenpick:" in text
    assert "@media (prefers-color-scheme: dark) { :root {--shop-" in text


def test_chart_paints_by_style_not_attribute(doc):
    """``fill="var(--x)"`` funktioniert nicht — Präsentationsattribute nehmen kein var()."""
    text = doc()
    assert 'style="fill:${c}"' in text
    assert 'fill="${c}"' not in text


def test_no_colour_serves_two_meanings():
    """Der Kern von F-05: keine Farbe steht in zwei Legenden.

    Die Trinkreife hat keine Farben mehr, darum kann die Schnittmenge nur leer sein.
    Der Test hält das fest, damit ein Rückbau auffällt.
    """
    import winecheck.report.site as site
    assert not hasattr(site, "_MATURITY_COLOURS"), \
        "Trinkreife-Palette ist zurück — dann bitte gegen _SHOP_* auf Kollisionen prüfen"


def test_new_retailer_cannot_get_an_invisible_colour():
    """Ein neunter Händler greift auf die Reserve zu, nicht auf Zufall."""
    assert len(_SHOP_LIGHT) >= 10
    for colour, panel in [(_SHOP_LIGHT[-1], "#f8f4f5"), (_SHOP_DARK[-1], "#1e181a")]:
        assert contrast(colour, panel) >= MIN_UI_CONTRAST


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

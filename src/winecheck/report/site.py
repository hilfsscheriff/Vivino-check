"""Statische Webseite für GitHub Pages.

Eine einzige HTML-Datei mit **allen Daten inline**: kein CDN, keine externen
Schriften, keine Bilder von aussen. Das hat drei Gründe:

* Sie funktioniert per Doppelklick, in OneDrive und auf Pages gleichermassen.
* Sie funktioniert unterwegs ohne Netz, sobald sie einmal geladen ist — genau dann,
  wenn man am Tisch sitzt und schlechten Empfang hat.
* Besucher lösen keine Anfragen an Dritte aus. Wer die Seite mit Freunden teilt,
  verschickt nicht deren IP-Adressen an ein CDN.

Achse und Filter
----------------
Die y-Achse zeigt **nur die Vivino-Note in ihrer eigenen Skala 1–5**. Falstaff- und
andere Kritikerpunkte stehen im Tooltip und in der Tabelle, aber nicht auf der Achse:
zwei Bewertungsgrundlagen auf einer Achse sind nicht vergleichbar, auch normalisiert
nicht. Weine ohne Vivino-Note erscheinen darum nicht im Diagramm, wohl aber in der
Tabelle.

Gefiltert wird kombinierbar nach Lauf, Trinkreife, Sorte und Händler, dazu ein
Suchfeld über Name und Produzent.
"""

from __future__ import annotations

import html
import json
import math
import re
import time
from pathlib import Path
from typing import Any

from ..names import STYLE_LABELS
from ..trinkreife import MATURITY, MATURITY_SHORT, SOURCE_NAME, SOURCE_PAGE
from .formatting import chf, datetime_ch

#: Reihenfolge der Trinkreife-Filter: von „jetzt" nach „später".
MATURITY_FILTER_ORDER = ("*", "k", "m", "g", "-")

#: Händlerfarben, hell und dunkel. Die Farbe ist im Diagramm das **einzige**
#: Händlersignal — sie muss darum in beiden Farbschemata sichtbar und untereinander
#: unterscheidbar sein. Beides war vorher nicht der Fall: vier Werte lagen im
#: Dunkelmodus unter 3:1 gegen die Kartenfläche, und dieselben vier Werte standen
#: gleichzeitig für eine Trinkreife (Grün hiess „Mövenpick" *und* „jetzt trinken").
#:
#: Die Trinkreife hat den Farbkanal darum abgegeben: ihre Farbe wurde an genau einer
#: Stelle getragen — dem Punkt in ihrem eigenen Filter-Chip, direkt neben der
#: Beschriftung, die dasselbe schon sagte. Damit steht das ganze Hue-Rad den
#: Händlern zur Verfügung; der geringste Paarabstand der ersten acht Farben steigt
#: von ΔE 30 auf 42, und jeder Wert erreicht >= 3:1 gegen seine Fläche.
#:
#: Reihenfolge = alphabetische Händlerliste. Die letzten zwei sind Reserve für neue
#: Händler; ``_check_palette`` sichert die Zusage ab, damit ein neunter Händler nicht
#: still eine unsichtbare Farbe bekommt.
_SHOP_LIGHT = [
    "#6b1030", "#2f9d2f", "#2525a7", "#258da7", "#a77a25",
    "#283167", "#a72594", "#286741", "#a73f25", "#674428",
]
_SHOP_DARK = [
    "#c41d58", "#2f9d2f", "#5454d9", "#258da7", "#a77a25",
    "#4f5ebb", "#b4289f", "#2c7248", "#af4227", "#8c5c36",
]

#: Flächen, auf denen die Punkte und Chip-Punkte liegen — Bezug für den Kontrast.
_PANEL_LIGHT, _PANEL_DARK = "#f8f4f5", "#1e181a"


#: Ab so vielen Vivino-Bewertungen zählt die Abweichung vom Preisniveau voll. Darunter
#: wird sie anteilig gedämpft: bei einer Streuung von rund 0.16 Notenpunkten führt sonst
#: ein Wein mit zwölf Bewertungen die Liste an, weil er zufällig gut wegkam.
VALUE_RATING_ANCHOR = 50

#: So viele Weine braucht ein Lauf, damit sich ein Preisniveau schätzen lässt.
VALUE_MIN_SAMPLE = 12


def _add_value_scores(wines: list[dict[str, Any]]) -> None:
    """Trägt in jeden Wein ein, wie weit seine Note über dem Preisniveau liegt.

    „Gut und günstig" ist die Frage, für die es die Seite gibt — im Diagramm ist es
    „oben links". Als Zahl: die Regression der Note auf ``log10(Preis)`` über den Lauf,
    und der Rest je Wein. Damit heisst der Wert „so viel besser als üblich für dieses
    Geld" und nicht „billig". Ein Ruinart für CHF 89.50 kann so vor einem mittelmässigen
    Wein für CHF 8 liegen.

    Der Preis geht logarithmisch ein, weil die Note es auch tut: über die Läufe bringt
    eine Verzehnfachung des Preises knapp einen halben Notenpunkt. Linear gerechnet
    würde die Spanne von CHF 4.60 bis 590 die ganze Rangfolge von den teuren Weinen
    her bestimmen.

    Gerechnet wird über den ganzen Lauf, nicht über die gefilterte Auswahl: sonst
    änderte ein Wein seinen Rang, je nachdem was sonst angezeigt wird.
    """
    sample = [
        w for w in wines
        if w.get("rating") is not None and (w.get("price") or 0) > 0
    ]
    if len(sample) < VALUE_MIN_SAMPLE:
        return
    xs = [math.log10(w["price"]) for w in sample]
    ys = [w["rating"] for w in sample]
    n = len(xs)
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    spread = sum((x - mean_x) ** 2 for x in xs)
    if spread <= 0:                       # alle zum selben Preis
        return
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / spread
    intercept = mean_y - slope * mean_x
    for w in sample:
        expected = intercept + slope * math.log10(w["price"])
        count = w.get("ratingCount") or 0
        damping = count / (count + VALUE_RATING_ANCHOR)
        w["valueScore"] = (w["rating"] - expected) * damping


#: Farbwörter, wie die Händler sie an den Namen hängen.
_COLOUR_WORD = r"(?:Rot|Weiss|Weiß|Ros[ée]|Schaum|Süss|Suess|Dessert)wein"

#: Die Standardflasche. Der Preis ist darauf normiert, im Namen sagt sie nichts.
#: Andere Grössen bleiben stehen: eine Magnum oder eine Halbflasche ist eine andere
#: Kaufentscheidung, ebenso der Sechserpack.
_STD_VOLUME = r"(?:0[.,]75\s*l|75\s*cl)"

_NAME_NOISE = [
    # „– Rotwein, Schweiz (0.75l)" am Ende
    re.compile(rf"\s*[–—-]\s*{_COLOUR_WORD}\s*,\s*[^,(]+?\s*\(\s*{_STD_VOLUME}\s*\)\s*$", re.I),
    # dasselbe ohne Volumen
    re.compile(rf"\s*[–—-]\s*{_COLOUR_WORD}\s*,\s*[^,(]+?\s*$", re.I),
    # nur das Farbwort, mit oder ohne folgende Klammer
    re.compile(rf"\s*[–—-]\s*{_COLOUR_WORD}\s*(?=\(|$)", re.I),
    # Standardgrösse am Ende, mit und ohne Klammer
    re.compile(rf",?\s*\(?\s*{_STD_VOLUME}\s*\)?\s*$", re.I),
    # Jahrgang in Klammern — er wird einheitlich angehängt, siehe ``vintageSuffix``
    re.compile(r"\s*\((?:19|20)\d{2}\)"),
]


def display_name(name: str) -> str:
    """Den Anzeigenamen von Händler-Beiwerk befreien.

    Die Namen kommen aus den Shops und tragen alles mit: „Rioja DOCa Crianza Bodegas
    Izadi (2022) – Rotwein, Spanien (0.75l)". Farbe steht daneben als Pill, das Land
    trägt nichts, 0.75 l ist die Bezugsgrösse des Preises, und der Jahrgang wird
    ohnehin einheitlich angehängt. Beim Überfliegen einer Liste ist der Name das
    Ankerelement — vierfach redundanter Text macht daraus mehrere Umbrüche.

    Was bleibt: Magnum, Halbflasche und Sechserpack. Das sind andere Käufe, keine
    Wiederholungen.
    """
    out = name or ""
    for pattern in _NAME_NOISE:
        out = pattern.sub("", out)
    return re.sub(r"\s{2,}", " ", out).strip(" ,;–—-")


def _css_ident(key: str) -> str:
    """Händlerschlüssel in einen CSS-taugliches Bezeichnerteil überführen."""
    return re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")


def _relative_luminance(colour: str) -> float:
    raw = colour.lstrip("#")
    parts = [int(raw[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in parts]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    """Kontrastverhältnis zweier Farben nach WCAG."""
    high, low = sorted((_relative_luminance(a), _relative_luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


#: Nicht-Text-Kontrast für Flächen und Umrisse (WCAG 2.2 SC 1.4.11).
MIN_UI_CONTRAST = 3.0


def _check_palette() -> list[str]:
    """Prüft die Zusage der Palette. Leere Liste heisst: alles gut.

    Läuft im Test, nicht im Build — eine kaputte Farbe soll auffallen, bevor sie
    ausgeliefert wird, aber den Seitenbau nicht anhalten.
    """
    problems = []
    if len(_SHOP_LIGHT) != len(_SHOP_DARK):
        problems.append("hell und dunkel haben unterschiedlich viele Farben")
    for scheme, palette, panel in (
        ("hell", _SHOP_LIGHT, _PANEL_LIGHT), ("dunkel", _SHOP_DARK, _PANEL_DARK),
    ):
        for colour in palette:
            got = contrast(colour, panel)
            if got < MIN_UI_CONTRAST:
                problems.append(
                    f"{colour} erreicht {scheme} nur {got:.2f}:1 gegen {panel}"
                )
    return problems


def _wine_from_snapshot(d: dict[str, Any]) -> dict[str, Any]:
    """Eine Snapshot-Zeile in die Form bringen, die die Seite braucht.

    Ältere Läufe kennen Sorte und Trinkreife nicht — dann bleiben die Felder leer,
    statt geraten zu werden.
    """
    urls = d.get("urls") or {}
    cheapest = d.get("cheapest_retailer") or ""
    style = d.get("style") or ""
    # Ein Pill "unbekannt" kostet dieselbe Aufmerksamkeit wie "jetzt trinken" und
    # sagt nichts. Nur die Anzeige entfällt: ``style`` bleibt gesetzt, damit der
    # Filter-Chip "unbekannt" weiter greift — dessen Beschriftung kommt aus
    # STYLE_LABELS, nicht von hier.
    style_label = "" if style == "unbekannt" else (
        d.get("style_label") or STYLE_LABELS.get(style, "")
    )
    return {
        "key": d.get("dedup_key") or d.get("name") or "",
        # Nur die Anzeige wird bereinigt. Gematcht und dedupliziert wurde vorher mit
        # dem Originalnamen, und der Schlüssel bleibt der Originalschlüssel.
        "name": display_name(d.get("name") or ""),
        "vintage": d.get("vintage") or "",
        "price": d.get("best_price"),
        # Ein Produzenten-Durchschnitt ist nicht die Note *dieses* Weins und darf
        # darum nicht auf die Achse. Mouton Cadet für CHF 9.95 hätte sonst die 4.6
        # von Château Mouton Rothschild.
        "rating": (
            d.get("vivino_rating")
            if d.get("vivino_status") not in ("winery_level",)
            else None
        ),
        "wineryOnly": d.get("vivino_status") == "winery_level",
        "wineryRating": d.get("vivino_rating") if d.get("vivino_status") == "winery_level" else None,
        # 1 = der Namensabgleich ist unbestätigt (fuzzy). Nur gesetzt, wenn wir es
        # positiv wissen: Läufe von vor dieser Änderung haben das Feld nicht, und
        # "Feld fehlt" darf nicht als "unbestätigt" durchgehen.
        "fuzzy": 1 if d.get("vivino_match_confidence") == "fuzzy" else None,
        "matchedName": d.get("vivino_matched_name") or "",
        "ratingCount": d.get("vivino_rating_count"),
        "vivinoStatus": d.get("vivino_status") or "",
        "vivinoUrl": d.get("vivino_url") or "",
        "retailers": d.get("retailers") or ([cheapest] if cheapest else []),
        "cheapest": cheapest,
        "url": urls.get(cheapest) or next(iter(urls.values()), ""),
        "market": d.get("market_price"),
        "bargain": d.get("bargain_percent"),
        "style": style,
        "styleLabel": style_label,
        "maturity": d.get("maturity") or "",
        "maturityShort": d.get("maturity_short") or "",
        "maturityRegion": d.get("maturity_region") or "",
        "vintageQuality": d.get("vintage_quality") or "",
        "falstaff": d.get("falstaff_points"),
        "rankSource": d.get("rank_source") or "",
    }


#: Kurze Schlüssel in der eingebetteten JSON. Bei 400 Weinen und mehreren Läufen
#: macht die Umbenennung rund ein Drittel der Dateigrösse aus — und die Seite soll
#: auch über Mobilfunk schnell laden. Die Zuordnung steht direkt daneben im JS.
_SHORT_KEYS = {
    "name": "n", "vintage": "y", "price": "p", "rating": "r", "ratingCount": "rc",
    "vivinoUrl": "vu", "retailers": "rs", "cheapest": "c", "url": "u",
    "market": "m", "bargain": "b", "style": "s", "styleLabel": "sl",
    "maturity": "t", "maturityShort": "ts", "maturityRegion": "tr",
    "vintageQuality": "q", "falstaff": "f", "key": "k",
    "wineryRating": "wr", "fuzzy": "fz", "matchedName": "mn",
    "valueScore": "vs",
}


def _compact(wine: dict[str, Any]) -> dict[str, Any]:
    """Leere Felder weglassen, Zahlen runden, Schlüssel kürzen."""
    out: dict[str, Any] = {}
    for long, short in _SHORT_KEYS.items():
        value = wine.get(long)
        if value is None or value == "" or value == []:
            continue
        if isinstance(value, float):
            value = round(value, 2)
        out[short] = value
    # Die Händlerliste ist meist identisch mit dem günstigsten Händler.
    if out.get("rs") == [out.get("c")]:
        out.pop("rs", None)
    return out


def build(
    runs: list[dict[str, Any]],
    path: Path | str,
    *,
    retailer_info: dict[str, dict] | None = None,
    title: str = "Schweizer Weinaktionen",
) -> Path | None:
    """Baut die Seite.

    Args:
        runs: Liste aus ``{"id", "label", "date", "wines": [...]}``, neuester zuerst.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    runs = [r for r in runs if r.get("wines")]
    if not runs:
        return None

    # Je Lauf gerechnet: jeder hat sein eigenes Preisniveau.
    for run in runs:
        _add_value_scores(run["wines"])

    info = retailer_info or {}
    retailers = sorted({r for run in runs for w in run["wines"] for r in w["retailers"]})
    # Die Farbe steht als CSS-Variable im Dokument, nicht als Hexwert in der JSON:
    # nur so kann sie im Dunkelmodus einen anderen Wert haben. Der Name der Variable
    # geht in die Payload, den Wert setzt das Stylesheet.
    light = {r: _SHOP_LIGHT[i % len(_SHOP_LIGHT)] for i, r in enumerate(retailers)}
    dark = {r: _SHOP_DARK[i % len(_SHOP_DARK)] for i, r in enumerate(retailers)}
    var = {r: f"--shop-{_css_ident(r) or f'n{i}'}" for i, r in enumerate(retailers)}
    colour_css = (
        ":root {"
        + "".join(f"{var[r]}:{light[r]};" for r in retailers)
        + "}\n  @media (prefers-color-scheme: dark) { :root {"
        + "".join(f"{var[r]}:{dark[r]};" for r in retailers)
        + "} }"
    )
    names = {r: (info.get(r) or {}).get("name") or r for r in retailers}
    channels = {r: (info.get(r) or {}).get("channel") or "" for r in retailers}

    styles = [s for s in STYLE_LABELS if any(
        w["style"] == s for run in runs for w in run["wines"]
    )]
    maturities = [m for m in MATURITY_FILTER_ORDER if any(
        w["maturity"] == m for run in runs for w in run["wines"]
    )]

    payload = {
        "runs": [
            {"id": r["id"], "label": r["label"],
             "wines": [_compact(w) for w in r["wines"]]}
            for r in runs
        ],
        "retailers": [
            {"key": r, "name": names[r], "var": var[r], "channel": channels[r]}
            for r in retailers
        ],
        "styles": [{"key": s, "label": STYLE_LABELS[s]} for s in styles],
        # Ohne Farbe: die Trinkreife hat den Farbkanal an die Händler abgegeben.
        # Die Reihenfolge der Chips („jetzt" nach „später") trägt die Abstufung,
        # die Beschriftung den Wert.
        "maturities": [
            {"key": m, "label": MATURITY_SHORT[m], "text": MATURITY[m]}
            for m in maturities
        ],
        "generated": datetime_ch(),
    }

    doc = _TEMPLATE.replace("__COLOURCSS__", colour_css)
    doc = doc.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))
    doc = doc.replace("__TITLE__", html.escape(title))
    doc = doc.replace("__SOURCE_NAME__", html.escape(SOURCE_NAME))
    doc = doc.replace("__SOURCE_PAGE__", html.escape(SOURCE_PAGE))
    doc = doc.replace("__STAMP__", html.escape(datetime_ch()))
    p.write_text(doc, encoding="utf-8")
    return p


_TEMPLATE = r"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<meta name="description" content="Aktuelle Weinaktionen der Schweizer Händler mit Vivino-Bewertung, Trinkreife und Marktpreisvergleich.">
<title>__TITLE__</title>
<style>
  :root {
    --ink:#241f20; --muted:#5f5658; --line:#e2dadd; --brand:#6b1030;
    --bg:#fffdfd; --panel:#f8f4f5; --chip:#efe8ea; --accent:#6b1030;
    /* Zwei Linienstärken nach Zweck: --line trennt (Tabellenzeilen, Kartenrand)
       und darf leise sein, --line-strong umrandet Bedienelemente und muss sich
       vom Hintergrund abheben — sonst liest sich ein Chip als Beschriftung
       statt als Schalter. Gemessen >= 3:1 gegen Seitenhintergrund, Karte und
       Chipfläche — der jeweils hellste Wert, der das noch schafft. */
    --line-strong:#918085;
    /* Mindesthöhe für Bedienelemente. Auf Zeigergeräten kompakt, auf Touch
       44 px — dort entscheidet die Treffgenauigkeit, hier die Dichte. */
    --control-h:36px;
    /* Fünf Textrollen statt dreizehn Einzelwerte. Vorher lagen zwischen 11 und
       13.6 px zehn Grössen, mehrere weniger als 0.5 px auseinander — nicht zu
       sehen, aber dreifach zu pflegen. Gleichzeitig teilten verschiedene Rollen
       dieselbe Grösse (.sub und .reset, .count und td), die Hierarchie war also
       zugleich zu fein und zu grob. Der Lesetext liegt jetzt auf 16 px statt
       13.6 px: die Tabelle ist die am längsten gelesene Fläche der Seite. */
    --fs-page-title:1.5rem;   /* h1 */
    --fs-title:1.125rem;      /* Kartentitel */
    --fs-body:1rem;           /* Tabelle, Suchfeld, Tooltip */
    --fs-body-sm:.875rem;     /* Metatext, Chips, Zähler, Footer, Hinweise */
    --fs-label:.75rem;        /* Legenden, Spaltenköpfe, Pills — uppercase/600 */
    --lh-tight:1.25;
  }
  @media (prefers-color-scheme: dark) {
    :root { --ink:#eee8ea; --muted:#a89fa2; --line:#393134; --brand:#eaa6bd;
            --bg:#151113; --panel:#1e181a; --chip:#2a2225; --accent:#eaa6bd;
            --line-strong:#7b6f73; }
  }
  @media (pointer: coarse) { :root { --control-h:44px; } }
  /* Händlerfarben, je Schema ein Wert — im Generator erzeugt. */
  __COLOURCSS__
  * { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  /* Ein Fokusstil für alles Bedienbare — vorher hing das Aussehen am Browser. */
  :focus-visible { outline:2px solid var(--brand); outline-offset:2px; }
  html { -webkit-text-size-adjust:100%; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
         padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left); }
  .wrap { max-width:1180px; margin:0 auto; padding:16px 14px 48px; }
  h1 { font-size:var(--fs-page-title); margin:0 0 2px; color:var(--brand); letter-spacing:-.01em; }
  .sub { color:var(--muted); font-size:var(--fs-body-sm); margin:0 0 14px; }
  /* ---- Suche und Filter ---- */
  .search { position:sticky; top:0; z-index:5; background:var(--bg);
            padding:8px 0 8px; margin-bottom:2px;
            border-bottom:1px solid var(--line); }
  .search .bar { margin:8px 0 0; }
  .search input { width:100%; font-size:var(--fs-body); padding:11px 13px; border-radius:11px;
                  border:1px solid var(--line-strong); background:var(--panel); color:var(--ink); }
  .search input::placeholder { color:var(--muted); }
  fieldset { border:0; margin:0 0 10px; padding:0; }
  legend { font-size:var(--fs-label); text-transform:uppercase; letter-spacing:.06em;
           color:var(--muted); margin-bottom:5px; padding:0; }
  .chips { display:flex; flex-wrap:wrap; gap:6px; }
  .chip { display:inline-flex; align-items:center; gap:6px; border:1px solid var(--line-strong);
          background:var(--chip); color:inherit; font:inherit; font-size:var(--fs-body-sm);
          padding:7px 11px; border-radius:999px; cursor:pointer;
          min-height:var(--control-h); }
  .chip[aria-pressed="true"] { background:var(--accent); color:var(--bg);
                               border-color:var(--accent); font-weight:600; }
  .chip .dot { width:9px; height:9px; border-radius:50%; flex:0 0 auto; }
  .chip .n { color:var(--muted); font-variant-numeric:tabular-nums; font-size:var(--fs-label); }
  .chip[aria-pressed="true"] .n { color:var(--bg); opacity:.8; }
  .bar { display:flex; align-items:center; justify-content:space-between; gap:12px;
         flex-wrap:wrap; margin:6px 0 12px; }
  .count { font-size:var(--fs-body-sm); color:var(--muted); }
  .count b { color:var(--ink); }
  .reset { background:none; border:0; color:var(--brand); font:inherit;
           font-size:var(--fs-body-sm); cursor:pointer; padding:6px 0; text-decoration:underline;
           min-height:var(--control-h); }
  /* ---- Diagramm ---- */
  .card { border:1px solid var(--line); border-radius:14px; background:var(--panel);
          padding:12px; margin-bottom:16px; }
  .card h2 { font-size:var(--fs-title); margin:0 0 8px; color:var(--brand); }
  svg { width:100%; height:auto; display:block; overflow:visible; touch-action:manipulation; }
  .grid { stroke:var(--line); stroke-dasharray:2 3; }
  .axis { stroke:var(--line); stroke-width:1.2; }
  .tick { fill:var(--muted); font-size:11px; }
  .alabel { fill:var(--muted); font-size:12px; }
  .hint { fill:var(--brand); font-size:11px; }
  /* fill-opacity statt voller Deckung: übereinanderliegende Punkte werden dunkler
     statt sich zu verdecken. Der Umriss in Kartenfarbe trennt sie zusätzlich. */
  .pt { stroke:var(--panel); stroke-width:1.2; cursor:pointer; fill-opacity:.82;
        transition:opacity .12s; }
  .pt:hover, .pt:focus-visible { fill-opacity:1; stroke:var(--ink); stroke-width:1.6; }
  .pt.off { display:none; }
  .empty { color:var(--muted); font-size:var(--fs-body-sm); padding:22px 4px; text-align:center; }
  /* ---- Tabelle als Karten auf dem Handy ---- */
  table { width:100%; border-collapse:collapse; font-size:var(--fs-body); }
  th { text-align:left; font-size:var(--fs-label); text-transform:uppercase; letter-spacing:.05em;
       color:var(--muted); font-weight:600; padding:6px 8px; border-bottom:1px solid var(--line); }
  td { padding:9px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
  tr:last-child td { border-bottom:0; }
  a { color:#1a4f8a; }
  @media (prefers-color-scheme: dark) { a { color:#8fb8e8; } }
  .wine { font-weight:600; }
  .meta { color:var(--muted); font-size:var(--fs-body-sm); }
  .num { font-variant-numeric:tabular-nums; white-space:nowrap; }
  .good { color:#2e7d32; font-weight:650; }
  .bad { color:#c62828; }
  .warn { color:var(--brand); }
  .matched { color:var(--muted); font-size:.78em; }
  /* Alle Filter in einer Karte, damit sofort sichtbar ist, was zusammen wirkt.
     Vorher lagen Chips oben und Feinauswahl unten bei der Tabelle — wer die Note
     einschränken wollte, musste am Diagramm vorbeiscrollen und wieder zurück. */
  .filters { padding:14px 16px 10px; margin-bottom:14px; }
  .filters fieldset + fieldset { margin-top:11px; }
  /* display:flex nimmt der Summary ihr Standard-Dreieck — ohne Ersatz sieht man
     nicht, dass sich das aufklappen lässt. */
  #filterBox > summary { font-size:var(--fs-body-sm); color:var(--brand); cursor:pointer;
                         display:flex; align-items:center; gap:7px;
                         min-height:var(--control-h); font-weight:600;
                         list-style:none; }
  #filterBox > summary::-webkit-details-marker { display:none; }
  #filterBox > summary::after { content:"▾"; margin-left:auto; font-size:.9em;
                                transition:transform .15s; }
  #filterBox[open] > summary::after { transform:rotate(180deg); }
  #filterBox > summary .n { color:var(--muted); font-weight:400; }
  .coverage { font-size:var(--fs-body-sm); color:var(--muted); margin:11px 0 0;
              padding-top:10px; border-top:1px solid var(--line); }
  #filterBox[open] > summary { margin-bottom:4px; }
  /* Am Desktop ist Platz — dort sind die Filter immer offen und der Aufklapper
     wäre nur ein zusätzlicher Klick. */
  @media (min-width: 721px) { #filterBox > summary { display:none; } }
  .filters .fine { border-top:1px solid var(--line); padding-top:11px; margin-top:13px; }
  .controls { display:flex; flex-wrap:wrap; gap:9px 14px; align-items:center;
              font-size:var(--fs-body-sm); color:var(--muted); }
  .controls label { display:flex; gap:6px; align-items:center; white-space:nowrap;
                    min-height:var(--control-h); }
  .controls select { font:inherit; color:var(--ink); background:var(--bg);
                     border:1px solid var(--line-strong); border-radius:8px;
                     padding:5px 7px; max-width:100%; min-height:var(--control-h); }
  .controls .cb { cursor:pointer; }
  .controls input[type=checkbox] { accent-color:var(--brand); width:20px; height:20px;
                                   flex:0 0 auto; }
  /* Erklärt die Standardsortierung — muss auf jeder Breite lesbar bleiben. */
  .tblnote { font-size:var(--fs-body-sm); color:var(--muted); margin:0 0 10px; }
  /* Nur der Hinweis auf die Spaltenköpfe ist am Handy falsch: dort ist thead weg. */
  .colhint { font-size:var(--fs-body-sm); color:var(--muted); }
  .more { margin:12px 0 0; text-align:center; }
  .more button { font:inherit; font-size:var(--fs-body-sm); color:var(--brand); cursor:pointer;
                 background:var(--bg); border:1px solid var(--line-strong);
                 border-radius:999px; padding:9px 18px; min-height:var(--control-h); }
  .more button:hover { border-color:var(--brand); }
  .more .meta { display:block; margin-top:6px; }
  /* Farbe und Füllung sind die beiden Kodierungen im Diagramm. Ohne diese Zeile
     ist die Händlerfarbe nur über die Filter-Chips zu erraten und der hohle
     Kreis gar nicht zu deuten. Anders als .colhint auch unter 767 px sichtbar:
     das Diagramm selbst verschwindet erst bei 720 px. */
  .legend { font-size:var(--fs-body-sm); color:var(--muted); margin:0 0 8px; }
  .legend .ring { display:inline-block; width:9px; height:9px; border-radius:50%;
                  border:1.8px solid var(--muted); vertical-align:baseline; }
  /* Auf dem Handy ist thead ausgeblendet — dort ist der Hinweis schlicht falsch.
     Derselbe Breakpoint wie fuer Kartenansicht und Diagramm: 720 px. */
  @media (max-width: 720px) {
    .colhint { display:none; }
    .controls { gap:8px 10px; }
    .controls label { font-size:var(--fs-body-sm); }
  }
  th .sortbtn { font:inherit; color:inherit; background:none; border:0; padding:0;
                cursor:pointer; letter-spacing:inherit; text-transform:inherit; }
  th .sortbtn:hover { color:var(--brand); }
  th.sorted { color:var(--brand); }
  th.num .sortbtn { width:100%; text-align:right; }
  @media (prefers-color-scheme: dark){ .good{color:#7cc47f} .bad{color:#ef9a9a} }
  .pill { display:inline-block; font-size:var(--fs-label); font-weight:600; padding:2px 7px; border-radius:999px;
          background:var(--chip); color:var(--muted); }
  @media (max-width:720px) {
    thead { display:none; }
    tr { display:block; border-bottom:1px solid var(--line); padding:10px 2px; }
    td { display:block; border:0; padding:2px 0; }
    td[data-l]::before { content:attr(data-l) " "; color:var(--muted); font-size:var(--fs-label); }
    /* In der Tabelle hält ein "—" die Spalte ausgerichtet. In der Kartenansicht
       gibt es keine Spalte mehr — dort ist es nur eine Zeile ohne Inhalt, und
       beim Marktpreis betrifft das die Mehrheit der Weine. */
    td.noval { display:none; }
    .chart { display:none; }
  }
  #tip { position:fixed; z-index:20; pointer-events:none; opacity:0; transition:opacity .1s;
         max-width:300px; background:var(--panel); border:1px solid var(--line);
         border-radius:10px; padding:9px 11px; font-size:var(--fs-body-sm); line-height:1.45;
         box-shadow:0 8px 26px rgba(0,0,0,.18); }
  #tip.on { opacity:1; }
  #tip .n { font-weight:650; display:block; margin-bottom:3px; }
  #tip .r { display:flex; justify-content:space-between; gap:12px; }
  #tip .k { color:var(--muted); }
  #tip .also { margin-top:7px; padding-top:6px; border-top:1px solid var(--line); }
  #tip .also b { display:block; margin-bottom:3px; }
  #tip { max-width:320px; }
  footer { color:var(--muted); font-size:var(--fs-body-sm); border-top:1px solid var(--line);
           padding-top:12px; margin-top:8px; }
  footer p { margin:.4em 0; }
</style>
</head>
<body>
<div class="wrap">
  <h1>__TITLE__</h1>
  <p class="sub">Stand __STAMP__ · Preise auf CHF pro 75 cl inkl. MwSt normalisiert (8.1 %)</p>

  <!-- Suchfeld, Treffermenge und Rückweg bleiben beim Scrollen stehen: wer in der
       Liste liest und die Auswahl ändern will, soll nicht nach oben zurück müssen.
       Die Abdeckungsangaben stehen bewusst *nicht* hier — sie sind Nachschlagewerte
       und würden die Leiste am Handy auf zwei Zeilen bringen. -->
  <div class="search">
    <input id="q" type="search" placeholder="Wein, Produzent, Region oder Sorte suchen …"
           autocomplete="off" autocapitalize="none" spellcheck="false"
           aria-label="Weine durchsuchen">
    <div class="bar">
      <span class="count" id="count" aria-live="polite"></span>
      <button class="reset" id="reset" type="button">Filter zurücksetzen</button>
    </div>
  </div>

  <main>
  <div class="card filters">
    <!-- Eingeklappt auf dem Handy: sonst füllt das Formular den ersten Bildschirm und
         der erste Wein steht unter 1200 px. Der Zähler bleibt draussen und damit
         immer sichtbar. <details> statt eigener Logik — Tastatur und Screenreader
         kommen gratis mit. -->
    <details id="filterBox">
    <summary>Filter <span class="n" id="filterCount"></span></summary>
    <fieldset id="runBox"><legend>Lauf</legend><div class="chips" id="fRun"></div></fieldset>
    <fieldset><legend>Trinkreife</legend><div class="chips" id="fMat"></div></fieldset>
    <fieldset><legend>Sorte</legend><div class="chips" id="fStyle"></div></fieldset>
    <fieldset><legend>Händler</legend><div class="chips" id="fShop"></div></fieldset>

    <fieldset class="fine">
      <legend>Feinauswahl</legend>
      <div class="controls">
        <label>Note ab
          <select id="fMinRating">
            <option value="">alle</option>
            <option value="3.5">3.5</option>
            <option value="3.8">3.8</option>
            <option value="4">4.0</option>
            <option value="4.2">4.2</option>
            <option value="4.5">4.5</option>
          </select>
        </label>
        <label>Preis bis
          <select id="fMaxPrice">
            <option value="">alle</option>
            <option value="10">CHF 10</option>
            <option value="20">CHF 20</option>
            <option value="40">CHF 40</option>
            <option value="80">CHF 80</option>
          </select>
        </label>
        <label>Sortieren
          <select id="fSort">
            <option value="value:-1">Preis-Leistung, beste zuerst</option>
            <option value="rating:-1">Note, beste zuerst</option>
            <option value="price:1">Preis, günstigste zuerst</option>
            <option value="price:-1">Preis, teuerste zuerst</option>
            <option value="bargain:-1">Ersparnis, grösste zuerst</option>
            <option value="name:1">Name A–Z</option>
            <option value="shop:1">Händler A–Z</option>
          </select>
        </label>
        <label class="cb" title="Nur Weine mit bestätigtem Namensabgleich — ohne unsichere Treffer, ohne Produzenten-Mittelwerte, ohne Weine ohne Eintrag"><input type="checkbox" id="fFound"> nur bei Vivino gefunden</label>
        <label class="cb"><input type="checkbox" id="fBargain"> nur unter Marktpreis</label>
      </div>
    </fieldset>
    </details>
    <p class="coverage" id="coverage"></p>
  </div>

  <div class="card chart">
    <h2>Vivino-Bewertung gegen Preis</h2>
    <p class="legend">Farbe = Händler · <span class="ring"></span> hohler Kreis =
       Vivino-Treffer unsicher, die Note kann zu einem anderen Wein gehören</p>
    <div id="chart"></div>
  </div>

  <div class="card">
    <h2 id="tblTitle">Weine</h2>
    <p class="tblnote"><b>Preis-Leistung</b> = wie viel besser die Note ist als bei
       Weinen zum gleichen Preis. ±0.00 = im Schnitt. Wenig bewertete Weine werden
       gedämpft.<span class="colhint"> · Spaltentitel antippen sortiert, nochmal
       antippen kehrt um</span></p>
    <div id="table"></div>
  </div>
  </main>

  <footer>
    <p><b>Bewertungen</b> von <a href="https://www.vivino.com" target="_blank" rel="noopener">Vivino</a>.
       Die Achse zeigt ausschliesslich die Vivino-Note in ihrer eigenen Skala 1–5 —
       Falstaff- und andere Kritikerpunkte stehen in der Tabelle, aber nicht auf der
       Achse: zwei Bewertungsgrundlagen auf einer Achse sind nicht vergleichbar.</p>
    <p><b>Trinkreife</b> aus der <a href="__SOURCE_PAGE__" target="_blank" rel="noopener">__SOURCE_NAME__</a>.
       Sie gilt für Region und Weinart, nicht für die einzelne Flasche.</p>
    <p><b>Preise</b> von den genannten Händlern, teils über den Aggregator
       <a href="https://www.aktionis.ch" target="_blank" rel="noopener">Aktionis</a> und damit aus zweiter
       Hand. <b>Marktpreise</b> von Vivino-Partnerhändlern, nie vom eigenen Händler.
       Alles ohne Gewähr — vor dem Kauf beim Händler prüfen.</p>
    <p>Diese Seite lädt nichts von Dritten. Sie funktioniert offline, sobald sie
       einmal geladen ist.</p>
  </footer>
</div>
<!-- Kein role="tooltip": der Kasten hängt an keinem aria-describedby und wäre für
     assistive Technik ein Versprechen ohne Beziehung. Die Tabelle ist die
     zugängliche Entsprechung zum Diagramm. -->
<div id="tip"></div>

<script>
const D = __PAYLOAD__;
/* Kurzschlüssel aus der eingebetteten JSON zurückbenennen — sie halten die Datei
   klein, der Code arbeitet aber mit lesbaren Namen. */
const KEYS = { n:"name", y:"vintage", p:"price", r:"rating", rc:"ratingCount",
  vu:"vivinoUrl", rs:"retailers", c:"cheapest", u:"url", m:"market", b:"bargain",
  s:"style", sl:"styleLabel", t:"maturity", ts:"maturityShort", tr:"maturityRegion",
  q:"vintageQuality", f:"falstaff", k:"key", wr:"wineryRating",
                   fz:"fuzzy", mn:"matchedName", vs:"valueScore" };
D.runs.forEach(run => {
  run.wines = run.wines.map(w => {
    const o = { retailers: [], name: "", style: "", maturity: "", styleLabel: "",
                maturityShort: "", cheapest: "", url: "", vivinoUrl: "", vintage: "" };
    for (const [short, long] of Object.entries(KEYS)) {
      if (short in w) o[long] = w[short];
    }
    if (!o.retailers.length && o.cheapest) o.retailers = [o.cheapest];
    return o;
  });
});
/* So viele Zeilen auf einmal. Vorher standen 400 fest im Dokument: bei 623 Weinen
   waren 223 nur über „Filter verfeinern" erreichbar, und die Tabelle allein trug
   über 800 Tabstopps. */
const PAGE = 50;
const S = { run: D.runs[0].id, mat: new Set(), style: new Set(), shop: new Set(), q: "",
            /* Standard ist Preis-Leistung: „welche Flasche lohnt sich" ist die Frage,
               für die es die Seite gibt. Nach Note allein eröffnete die Liste mit den
               teuersten Flaschen. */
            sort: "value", dir: -1, minRating: null, maxPrice: null, onlyBargain: false,
            onlyFound: false, limit: PAGE };
const esc = s => String(s ?? "").replace(/[&<>"']/g, c =>
  ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
const chf = v => v == null ? "" : "CHF " + Number(v).toFixed(2)
  .replace(/\B(?=(\d{3})+(?!\d))/, "'");
/* Die Händlernamen tragen den Jahrgang meist schon in sich ("Pomerol AOC 2007
   Château Lafleur"). Ihn dann noch anzuhängen, druckt ihn zweimal — bei den
   allermeisten Weinen. Nur anhängen, wenn er im Namen fehlt. */
const vintageSuffix = w => (w.vintage && !String(w.name).includes(String(w.vintage)))
  ? " " + w.vintage : "";
/* Der Wert, nach dem standardmässig sortiert wird, muss auch dastehen — sonst ist die
   Reihenfolge nicht nachvollziehbar. 0 heisst „genau im Preisniveau". */
const valueText = w => {
  if (w.valueScore == null) return '<span class="meta">—</span>';
  const v = w.valueScore;
  const cls = v > 0.05 ? "good" : v < -0.05 ? "bad" : "meta";
  return `<span class="${cls}">${v > 0 ? "+" : v < 0 ? "−" : "±"}`
    + Math.abs(v).toFixed(2) + "</span>";
};

function currentRun() { return D.runs.find(r => r.id === S.run) || D.runs[0]; }

function visible() {
  const q = S.q.trim().toLowerCase();
  return currentRun().wines.filter(w => {
    if (S.mat.size && !S.mat.has(w.maturity || "?")) return false;
    if (S.style.size && !S.style.has(w.style || "?")) return false;
    if (S.shop.size && !w.retailers.some(r => S.shop.has(r))) return false;
    // Der bei Vivino gefundene Name gehört in die Suche. Händler benennen Weine oft
    // ohne den Produzenten: Mövenpick führt „Mendoza 2021 Chardonnay Alta Angelica
    // Zapata", Vivino „Catena Zapata Angélica Zapata Chardonnay Alta". Wer nach
    // „Catena" sucht — dem Namen, unter dem das Weingut bekannt ist — fand nichts,
    // obwohl der Wein zugeordnet war.
    if (q) {
      const heu = (w.name + " " + (w.maturityRegion || "") + " " + (w.matchedName || "")
                   + " " + (w.styleLabel || "")).toLowerCase();
      if (!heu.includes(q)) return false;
    }
    // Spaltenfilter greifen hier, nicht erst in der Tabelle: sonst zeigen Diagramm,
    // Zähler und Tabelle drei verschiedene Mengen, und man weiss nicht, welche gilt.
    if (S.minRating != null && !(w.rating != null && w.rating >= S.minRating)) return false;
    if (S.maxPrice != null && !(w.price != null && w.price <= S.maxPrice)) return false;
    if (S.onlyBargain && !(w.bargain != null && w.bargain > 0)) return false;
    // "Bei Vivino gefunden" heisst: bestätigter Namensabgleich. Nicht dabei sind
    // fuzzy-Treffer (Name passt nur ungefähr), Produzenten-Mittelwerte und die
    // Weine ohne Eintrag. Das sind genau die gefüllten Punkte im Diagramm.
    if (S.onlyFound && !(w.rating != null && !w.fuzzy)) return false;
    return true;
  });
}

/* ---------------------------------------------------------------- Diagramm */
function chart(list) {
  const pts = list.filter(w => w.rating != null && w.price > 0);
  const box = document.getElementById("chart");
  const card = document.querySelector(".chart");
  // Passt kein Wein zur Auswahl, hat das Diagramm nichts zu sagen — dann ganz weg.
  // Vorher stand hier "Die Tabelle zeigt alle", während die Tabelle leer war.
  // Der Leerzustand gehört an eine Stelle, nicht an zwei widersprechende.
  card.hidden = list.length === 0;
  if (list.length === 0) return;
  if (pts.length < 2) {
    box.innerHTML = '<p class="empty">' +
      (pts.length ? "Nur ein Wein mit Vivino-Note — siehe Tabelle."
                  : "Kein Wein dieser Auswahl hat eine Vivino-Note. Die Tabelle "
                    + "zeigt sie trotzdem, mit Preis und Händler.") +
      "</p>";
    return;
  }
  const W = 900, H = 460, L = 52, R = 16, T = 30, B = 46;
  const pw = W - L - R, ph = H - T - B;
  const xs = pts.map(p => Math.log10(p.price));
  const x0 = Math.min(...xs) - .05, x1 = Math.max(...xs) + .05;
  const ys = pts.map(p => p.rating);
  const y0 = Math.max(1, Math.min(...ys) - .1), y1 = Math.min(5, Math.max(...ys) + .1);
  const sx = v => L + (Math.log10(v) - x0) / (x1 - x0 || 1) * pw;
  const sy = v => T + (1 - (v - y0) / (y1 - y0 || 1)) * ph;

  let g = "";
  for (const v of [3,5,7,10,15,20,30,50,75,100,150,200,300,500,800]) {
    if (Math.log10(v) < x0 || Math.log10(v) > x1) continue;
    g += `<line class="grid" x1="${sx(v)}" y1="${T}" x2="${sx(v)}" y2="${T+ph}"/>`
       + `<text class="tick" x="${sx(v)}" y="${T+ph+17}" text-anchor="middle">${v}</text>`;
  }
  for (let i = 0; i <= 4; i++) {
    const v = y0 + i * (y1 - y0) / 4;
    g += `<line class="grid" x1="${L}" y1="${sy(v)}" x2="${L+pw}" y2="${sy(v)}"/>`
       + `<text class="tick" x="${L-7}" y="${sy(v)+4}" text-anchor="end">${v.toFixed(1)}</text>`;
  }
  /* Im dichten Bereich (CHF 5–20, Note 3.9–4.2) lagen bei 127 Punkten 24 ganz oder
     teilweise hinter anderen — deren Tooltip war unerreichbar. Kleinerer Radius und
     Teiltransparenz machen Häufungen als dunklere Fläche lesbar, statt sie zu
     verdecken; der Umriss trennt die Punkte weiter voneinander. */
  const shopVar = Object.fromEntries(D.retailers.map(r => [r.key, r.var]));
  // Unbestätigte Namensabgleiche werden hohl gezeichnet. Farbe immer per style, nie
  // als Präsentationsattribut: fill="..." nimmt kein var(), und die Regel
  // .pt { stroke: ... } würde ein stroke-Attribut überstimmen.
  const circles = pts.map((p, i) => {
    const c = `var(${shopVar[p.cheapest] || "--brand"})`;
    const paint = p.fuzzy
      ? `style="fill:none;stroke:${c};stroke-width:1.8"`
      : `style="fill:${c}"`;
    return `<circle class="pt" data-i="${i}" cx="${sx(p.price).toFixed(1)}"`
      + ` cy="${sy(p.rating).toFixed(1)}" r="5" ${paint}/>`;
  }).join("");

  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img"
      aria-label="Vivino-Bewertung gegen Preis, ${pts.length} Weine">
    ${g}
    <line class="axis" x1="${L}" y1="${T+ph}" x2="${L}" y2="${T}"/>
    <line class="axis" x1="${L}" y1="${T+ph}" x2="${L+pw}" y2="${T+ph}"/>
    <text class="alabel" x="${L+pw/2}" y="${H-8}" text-anchor="middle">Preis pro 75 cl inkl. MwSt (CHF, logarithmisch)</text>
    <text class="alabel" transform="rotate(-90 14 ${T+ph/2})" x="14" y="${T+ph/2}" text-anchor="middle">Vivino-Bewertung (1–5)</text>
    <text class="hint" x="${L}" y="${T-10}">oben links = gut und günstig</text>
    <g id="pts">${circles}</g></svg>`;

  const tip = document.getElementById("tip"), host = box.querySelector("#pts");
  /* Gerenderte Lage je Punkt, um Häufungen zu finden. Ein kleinerer Radius löst das
     Problem nicht — die Punkte liegen in den Daten aufeinander, nicht bloss optisch.
     Erreichbar werden die verdeckten nur, wenn der Tooltip sie mitnennt. */
  const at = pts.map(p => ({ x: +sx(p.price).toFixed(1), y: +sy(p.rating).toFixed(1) }));
  const clusterOf = i => pts
    .map((_, j) => j)
    .filter(j => Math.abs(at[j].x - at[i].x) <= 5 && Math.abs(at[j].y - at[i].y) <= 5);
  const show = (el, ev) => {
    const i = +el.dataset.i, p = pts[i]; if (!p) return;
    const row = (k, v) => `<div class="r"><span class="k">${k}</span><span>${v}</span></div>`;
    const cluster = clusterOf(i).filter(j => j !== i);
    let h = `<span class="n">${esc(p.name)}${vintageSuffix(p)}</span>`;
    h += row("Vivino", p.rating.toFixed(1) + "/5" + (p.ratingCount ? ` (${p.ratingCount})` : ""));
    if (p.fuzzy) h += row("Achtung", `<span class="warn">Namensabgleich unbestätigt`
      + (p.matchedName ? ` — gefunden: „${esc(p.matchedName)}"` : "") + `</span>`);
    if (p.styleLabel) h += row("Sorte", esc(p.styleLabel));
    if (p.maturityShort) h += row("Trinkreife", "<b>" + esc(p.maturityShort) + "</b>");
    if (p.valueScore != null) h += row("Preis-Leistung", valueText(p));
    h += row("Preis/75cl", chf(p.price));
    h += row("Händler", esc((D.retailers.find(r => r.key === p.cheapest) || {}).name || p.cheapest));
    if (p.bargain != null) {
      const c = p.bargain > 0 ? "good" : "bad";
      h += row("gegen Markt", `<span class="${c}">${p.bargain > 0 ? "−" : "+"}`
        + Math.abs(p.bargain).toFixed(0) + "%</span>");
    }
    if (p.falstaff != null) h += row("Falstaff", p.falstaff.toFixed(0) + "/100");
    // Verdeckte Nachbarn benennen, sonst weiss man nicht, dass sie da sind.
    if (cluster.length) {
      h += `<div class="also"><b>${cluster.length} weitere${cluster.length === 1 ? "r" : ""}`
        + ` Wein${cluster.length === 1 ? "" : "e"} an dieser Stelle</b>`
        + cluster.slice(0, 4).map(j => {
            const o = pts[j];
            return `<div class="r"><span>${esc(o.name).slice(0, 38)}</span>`
              + `<span class="k">${o.rating.toFixed(1)} · ${chf(o.price)}</span></div>`;
          }).join("")
        + (cluster.length > 4
            ? `<div class="k">… und ${cluster.length - 4} weitere — in der Tabelle</div>`
            : "")
        + `</div>`;
    }
    tip.innerHTML = h; tip.classList.add("on"); place(ev);
  };
  const place = ev => {
    const m = 14, w = tip.offsetWidth, h = tip.offsetHeight;
    let x = ev.clientX + m, y = ev.clientY + m;
    if (x + w > innerWidth - 8) x = ev.clientX - w - m;
    if (y + h > innerHeight - 8) y = ev.clientY - h - m;
    tip.style.left = Math.max(8, x) + "px"; tip.style.top = Math.max(8, y) + "px";
  };
  host.addEventListener("mouseover", e => { if (e.target.classList.contains("pt")) show(e.target, e); });
  host.addEventListener("mousemove", e => { if (tip.classList.contains("on")) place(e); });
  host.addEventListener("mouseout", () => tip.classList.remove("on"));
  /* Auf Touch gibt es kein Hover. Zwischen 721 und 900 px ist das Diagramm sichtbar
     — dort waren die Tooltips bisher unerreichbar, weil nur Maus-Ereignisse hingen.
     Erstes Antippen zeigt den Wein, zweites Antippen öffnet ihn. */
  let armed = null;
  host.addEventListener("click", e => {
    if (!e.target.classList.contains("pt")) return;
    const p = pts[+e.target.dataset.i];
    const touch = !matchMedia("(hover: hover)").matches;
    if (touch && armed !== e.target) {
      armed = e.target;
      show(e.target, e.touches ? e.touches[0] : e);
      return;
    }
    armed = null;
    const href = p && (p.url || p.vivinoUrl);
    if (href) window.open(href, "_blank", "noopener");
  });
  // Tippen daneben schliesst den Tooltip wieder.
  addEventListener("pointerdown", e => {
    if (!e.target.classList || !e.target.classList.contains("pt")) {
      armed = null; tip.classList.remove("on");
    }
  }, { passive: true });
}


/* Grob prüfen, ob Händler- und Fundname dasselbe sagen — dann ist die Zeile nur
   Wiederholung. Verglichen werden die Wörter, nicht die Zeichenfolge. */
function sameWine(a, b) {
  const w = t => new Set(String(t || "").toLowerCase()
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9 ]+/g, " ").split(/\s+/).filter(x => x.length > 2));
  const A = w(a), B = w(b);
  if (!A.size || !B.size) return false;
  let n = 0; B.forEach(x => { if (A.has(x)) n++; });
  return n === B.size;
}
/* ----------------------------------------------------------------- Tabelle */
function table(list) {
  const box = document.getElementById("table");
  if (!list.length) { box.innerHTML = '<p class="empty">Kein Wein passt zu dieser Auswahl.</p>'; return; }
  const shopName = k => (D.retailers.find(r => r.key === k) || {}).name || k;
  // Leere Werte sortieren immer nach unten, in beiden Richtungen. Ein Wein ohne Note
  // ist keine 0 — er würde sonst bei aufsteigender Sortierung die Liste anführen.
  const KEYS = {
    name:    w => (w.name || "").toLowerCase(),
    rating:  w => w.rating,
    price:   w => w.price,
    shop:    w => shopName(w.cheapest).toLowerCase(),
    bargain: w => w.bargain,
    value:   w => w.valueScore,
  };
  const key = KEYS[S.sort] || KEYS.value;
  const sorted = list.slice().sort((a, b) => {
    const x = key(a), y = key(b);
    const xe = x == null || x === "", ye = y == null || y === "";
    if (xe && ye) return 0;
    if (xe) return 1;
    if (ye) return -1;
    if (typeof x === "string") return S.dir * x.localeCompare(y, "de");
    return S.dir * (x - y);
  });
  const rows = sorted.slice(0, S.limit).map(w => {
    const vivino = w.rating != null
      ? `<a href="${esc(w.vivinoUrl)}" target="_blank" rel="noopener">${w.rating.toFixed(1)}/5</a>`
        + (w.ratingCount ? ` <span class="meta">(${w.ratingCount})</span>` : "")
        + (w.fuzzy ? ` <span class="warn" title="Namensabgleich unbestätigt">?</span>` : "")
        // Den gefundenen Namen ausschreiben, wenn er vom Händlernamen abweicht.
        // Ein Tooltip genügt dafür nicht: auf dem Handy gibt es kein Hover, und ohne
        // den Namen ist nicht nachprüfbar, welcher Vivino-Wein gemeint ist — genau
        // die Frage, die man bei einem "?" als Erstes hat.
        + (w.matchedName && !sameWine(w.name, w.matchedName)
            ? `<br><span class="matched">→ ${esc(w.matchedName)}</span>` : "")
      : w.wineryRating != null
        ? `<a href="${esc(w.vivinoUrl)}" target="_blank" rel="noopener" class="meta">nur Produzenten-Ø `
          + w.wineryRating.toFixed(1) + "/5</a>"
        : `<a href="${esc(w.vivinoUrl)}" target="_blank" rel="noopener" class="meta">keine Note</a>`;
    const bargain = w.bargain == null ? '<span class="meta">—</span>'
      : `<span class="${w.bargain > 0 ? "good" : "bad"}">${w.bargain > 0 ? "−" : "+"}`
        + Math.abs(w.bargain).toFixed(0) + "%</span>";
    const shop = w.url ? `<a href="${esc(w.url)}" target="_blank" rel="noopener">${esc(shopName(w.cheapest))}</a>`
                       : esc(shopName(w.cheapest));
    const vs = vintageSuffix(w);
    return `<tr>
      <td data-l="Wein"><span class="wine">${esc(w.name)}</span>
        ${vs ? `<span class="meta">${vs}</span>` : ""}
        ${w.styleLabel ? `<br><span class="pill">${esc(w.styleLabel)}</span>` : ""}
        ${w.maturityShort ? ` <span class="pill">${esc(w.maturityShort)}</span>` : ""}</td>
      <td data-l="Preis-Leistung" class="num${w.valueScore == null ? " noval" : ""}">${valueText(w)}</td>
      <td data-l="Vivino">${vivino}</td>
      <td data-l="Preis/75cl" class="num">${chf(w.price)}</td>
      <td data-l="Wo kaufen">${shop}</td>
      <td data-l="gegen Markt" class="num${w.bargain == null ? " noval" : ""}">${bargain}</td>
    </tr>`;
  }).join("");
  const COLS = [
    ["name", "Wein", ""], ["value", "Preis-Leistung", "num"], ["rating", "Vivino", ""],
    ["price", "Preis/75cl", "num"], ["shop", "Wo kaufen", ""],
    ["bargain", "gegen Markt", "num"],
  ];
  const head = COLS.map(([k, label, cls]) => {
    const on = S.sort === k;
    const arrow = on ? (S.dir < 0 ? " ▾" : " ▴") : "";
    return `<th class="${cls}${on ? " sorted" : ""}"><button type="button" class="sortbtn"`
      + ` data-col="${k}" aria-label="Nach ${esc(label)} sortieren">${esc(label)}${arrow}</button></th>`;
  }).join("");
  const rest = sorted.length - S.limit;
  box.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table>`
    + (rest > 0
        ? `<p class="more"><button type="button" id="more">Weitere ${Math.min(rest, PAGE)} anzeigen</button>`
          + `<span class="meta"> ${S.limit} von ${sorted.length} angezeigt</span></p>`
        : sorted.length > PAGE
          ? `<p class="more"><span class="meta">Alle ${sorted.length} angezeigt</span></p>`
          : "");
  const more = box.querySelector("#more");
  // Nur nachladen, nicht neu filtern: der Blick soll nicht nach oben springen.
  if (more) more.addEventListener("click", () => { S.limit += PAGE; table(list); });

  box.querySelectorAll(".sortbtn").forEach(b => b.addEventListener("click", () => {
    const col = b.dataset.col;
    // Gleiche Spalte nochmal = Richtung wechseln. Neue Spalte startet in der
    // Richtung, die man dort erwartet: Text A→Z, Zahlen gross→klein.
    if (S.sort === col) S.dir = -S.dir;
    else { S.sort = col; S.dir = (col === "name" || col === "shop") ? 1 : -1; }
    syncSort();
    render();
  }));
}

/* ------------------------------------------------------------------ Filter */
/* Ändert sich die Auswahl, beginnt die Liste wieder bei der ersten Seite — sonst
   stehen nach einem Filterwechsel mehrere Hundert Zeilen einer anderen Menge da. */
function refilter() { S.limit = PAGE; render(); }

function chip(label, pressed, onClick, extra = "") {
  const b = document.createElement("button");
  b.type = "button"; b.className = "chip"; b.setAttribute("aria-pressed", String(pressed));
  b.innerHTML = extra + esc(label);
  b.addEventListener("click", () => { onClick(); refilter(); });
  return b;
}

function buildFilters() {
  const run = document.getElementById("fRun"); run.innerHTML = "";
  // Ein einzelner Lauf ist keine Wahl. Die Gruppe kostet sonst Legende plus
  // Chipzeile auf dem knappsten Platz der Seite — dem ersten Handy-Bildschirm.
  // Das Datum steht ohnehin schon in der Stand-Zeile darüber.
  document.getElementById("runBox").hidden = D.runs.length < 2;
  D.runs.forEach(r => run.append(chip(
    r.label, S.run === r.id, () => { S.run = r.id; },
    `<span class="n">${r.wines.length}</span>&nbsp;`)));

  const toggle = (set, key) => () => set.has(key) ? set.delete(key) : set.add(key);
  const mat = document.getElementById("fMat"); mat.innerHTML = "";
  // Kein Farbpunkt: die Beschriftung sagt dasselbe, und dieselbe Farbe stand vorher
  // im Diagramm für einen Händler.
  D.maturities.forEach(m => mat.append(chip(
    m.label, S.mat.has(m.key), toggle(S.mat, m.key))));
  mat.append(chip("keine Angabe", S.mat.has("?"), toggle(S.mat, "?")));

  const st = document.getElementById("fStyle"); st.innerHTML = "";
  D.styles.forEach(s => st.append(chip(s.label, S.style.has(s.key), toggle(S.style, s.key))));

  const sh = document.getElementById("fShop"); sh.innerHTML = "";
  D.retailers.forEach(r => sh.append(chip(
    r.name, S.shop.has(r.key), toggle(S.shop, r.key),
    `<span class="dot" style="background:var(${r.var})"></span>`)));
}

/* Am Desktop ist der Aufklapper ausgeblendet — dort muss <details> offen sein, sonst
   wäre der Inhalt unerreichbar: kein Griff zum Öffnen, kein Inhalt.
   Geprüft wird die gerenderte Lage der Summary, nicht die Media Query. Die Regel gilt
   dann auch, wenn der Breitenwechsel anders kommt als über ein `change`-Ereignis —
   Fenster ziehen, Drehen, Zoomen. */
const filterBox = document.getElementById("filterBox");
/* Zweiseitig: schmal wird eingeklappt, breit aufgeklappt. Einseitig gedacht bleiben
   die Filter nach einem Wechsel von breit zu schmal offen — Drehen, Fenster ziehen —
   und füllen den ersten Bildschirm wieder. Wer selbst geklickt hat, behält seine
   Wahl; die Ausnahme ist der Desktop, wo der Griff fehlt und offen sein muss. */
let userChoseFilters = false, programmatic = false;
/* Am Klick festgemacht, nicht am `toggle`-Ereignis: das feuert asynchron, und ein
   unmittelbar folgender Resize würde die Wahl sonst wieder überschreiben. */
filterBox.querySelector("summary").addEventListener("click", () => {
  userChoseFilters = true;
});
filterBox.addEventListener("toggle", () => { if (!programmatic) userChoseFilters = true; });
function syncFilterBox() {
  const hidden = getComputedStyle(filterBox.querySelector("summary")).display === "none";
  const want = hidden ? true : (userChoseFilters ? filterBox.open : false);
  if (filterBox.open !== want) {
    programmatic = true; filterBox.open = want; programmatic = false;
  }
}
addEventListener("resize", syncFilterBox);
syncFilterBox();

function activeFilterCount() {
  return S.mat.size + S.style.size + S.shop.size
    + (S.q.trim() ? 1 : 0) + (S.minRating != null ? 1 : 0) + (S.maxPrice != null ? 1 : 0)
    + (S.onlyBargain ? 1 : 0) + (S.onlyFound ? 1 : 0);
}

function render() {
  buildFilters();
  const active = activeFilterCount();
  document.getElementById("filterCount").textContent =
    active ? `· ${active} aktiv` : "· keine aktiv";
  syncFilterBox();
  const list = visible(), total = currentRun().wines.length;
  const rated = list.filter(w => w.rating != null).length;
  // Der Marktpreis fehlt bei der Mehrheit der Weine. Wer nach Ersparnis sortiert,
  // soll wissen, wie viele Weine dazu überhaupt eine Angabe haben — sonst liest
  // sich die Spalte voller "—" wie ein Fehler statt wie eine Lücke in den Daten.
  const priced = list.filter(w => w.bargain != null).length;
  // Treffermenge in die sticky Leiste, Abdeckung darunter: das eine ändert sich mit
  // jedem Klick, das andere ist zum Nachschlagen.
  document.getElementById("count").innerHTML =
    `<b>${list.length}</b> von ${total} Weinen`;
  document.getElementById("coverage").textContent =
    `${rated} davon mit Vivino-Note · ${priced} mit Marktpreis`;
  document.getElementById("tblTitle").textContent =
    list.length === total ? "Alle Weine" : "Gefilterte Weine";
  chart(list); table(list);
}

document.getElementById("q").addEventListener("input", e => { S.q = e.target.value; refilter(); });
const numOrNull = v => v === "" ? null : Number(v);
/* Kopfzeile und Auswahlfeld sind zwei Wege zur selben Sortierung. Nach einem Klick auf
   die Kopfzeile muss das Feld nachziehen, sonst zeigt es etwas anderes an als gilt. */
function syncSort() {
  const el = document.getElementById("fSort");
  const wanted = `${S.sort}:${S.dir}`;
  el.value = [...el.options].some(o => o.value === wanted) ? wanted : "";
}
document.getElementById("fSort").addEventListener("change", e => {
  const [col, dir] = e.target.value.split(":");
  S.sort = col; S.dir = Number(dir); render();
});
document.getElementById("fMinRating").addEventListener("change", e => {
  S.minRating = numOrNull(e.target.value); refilter();
});
document.getElementById("fMaxPrice").addEventListener("change", e => {
  S.maxPrice = numOrNull(e.target.value); refilter();
});
document.getElementById("fBargain").addEventListener("change", e => {
  S.onlyBargain = e.target.checked; refilter();
});
document.getElementById("fFound").addEventListener("change", e => {
  S.onlyFound = e.target.checked; refilter();
});
document.getElementById("reset").addEventListener("click", () => {
  S.mat.clear(); S.style.clear(); S.shop.clear(); S.q = "";
  S.minRating = null; S.maxPrice = null; S.onlyBargain = false; S.onlyFound = false;
  S.sort = "value"; S.dir = -1; S.limit = PAGE;
  document.getElementById("q").value = "";
  document.getElementById("fMinRating").value = "";
  document.getElementById("fMaxPrice").value = "";
  document.getElementById("fBargain").checked = false;
  document.getElementById("fFound").checked = false;
  syncSort();
  render();
});
render();
</script>
</body>
</html>
"""

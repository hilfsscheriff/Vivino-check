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

#: „Gut und günstig" ist eine feste Regel, kein Abstand zur Trendlinie: ab dieser
#: Note und bis zu diesem Preis. Nur dieser Bereich. Absolut zu rechnen ist der
#: schärfere Filter — „besser als üblich fürs Geld" trifft auch eine mittelmässige
#: Flasche für CHF 8.
GOOD_RATING_MIN = 4.2
GOOD_PRICE_MAX = 20.0

#: Flächen, gegen die Farben geprüft werden (hell, dunkel).
_GROUND_LIGHT, _GROUND_DARK = "#faf9f7", "#141114"

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


#: Textfarben der Etikette-Richtung, je Schema, mit ihrem Zweck. Grossgrade dürfen
#: bei 3:1 liegen (WCAG-Schwelle für grosse Schrift), Kleintext braucht 4.5:1.
_TOKEN_CONTRAST = {
    "hell": (_GROUND_LIGHT, {
        "--ink": ("#1a1719", 4.5), "--muted": ("#6b6668", 4.5),
        "--faint": ("#78716d", 4.5), "--accent": ("#6d1834", 4.5),
        "--goldtx": ("#8a6a3d", 4.5), "--gold": ("#9a7b4f", 3.0),
        "--good": ("#2e7d32", 4.5), "--bad": ("#c62828", 4.5),
        "--line-strong": ("#8f8a86", 3.0),
    }),
    "dunkel": (_GROUND_DARK, {
        "--ink": ("#f0ebec", 4.5), "--muted": ("#a49da0", 4.5),
        "--faint": ("#8b8488", 4.5), "--accent": ("#e0879f", 4.5),
        "--goldtx": ("#d4b587", 4.5), "--gold": ("#c9a877", 3.0),
        "--good": ("#7cc47f", 4.5), "--bad": ("#ef9a9a", 4.5),
        "--line-strong": ("#6f6a6e", 3.0),
    }),
}


def check_tokens() -> list[str]:
    """Prüft die Farbzusage der Seite. Leere Liste heisst: alles gut.

    Läuft im Test, nicht im Build — eine zu blasse Farbe soll auffallen, bevor sie
    ausgeliefert wird, aber den Seitenbau nicht anhalten. Gold ist mit 3:1 bewusst
    milder geprüft: es trägt nur Grossgrade und Flächen, für Kleintext gibt es
    ``--goldtx``.
    """
    problems = []
    for scheme, (ground, tokens) in _TOKEN_CONTRAST.items():
        for name, (value, target) in tokens.items():
            got = contrast(value, ground)
            if got < target:
                problems.append(
                    f"{scheme}: {name} ({value}) erreicht {got:.2f}:1, "
                    f"gefordert {target}:1 gegen {ground}"
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
    # Kein Farbwert je Händler mehr: in dieser Richtung trägt der Händler keine
    # Farbe, sondern seinen Namen. Farbe bleibt für Akzent, Urteil und Gold.
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
            {"key": r, "name": names[r], "channel": channels[r]}
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
        "good": {"rating": GOOD_RATING_MIN, "price": GOOD_PRICE_MAX},
        "generated": datetime_ch(),
    }

    doc = _TEMPLATE.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))
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
    /* ---------------------------------------------------------------- Etikette
       Nach der Weinetikette gebaut: gestochener Serif, Linien statt Kästen, viel
       Ruhe, eine tiefe Farbe. Gold trägt den Wert — die Kennzahl, das markierte
       Feld — und sonst nichts.

       Farbe hat drei Aufgaben und keine vierte: Akzent (bedienbar), Urteil
       (gut/schwach), Gold (Wert). Der Händler bekommt keine Farbe mehr: er stand
       nur im Diagramm als Punktfarbe, und dieselben Töne mussten dort gleichzeitig
       die Trinkreife tragen. Jetzt steht sein Name im Tooltip und in der Tabelle.

       Alle Textwerte gegen beide Gründe auf >= 4.5:1 geprüft, Grossgrade auf 3:1,
       Ränder von Bedienelementen auf 3:1. */
    --ink:#1a1719; --muted:#6b6668; --faint:#78716d;
    --line:#e2dedc; --line-strong:#8f8a86;
    --bg:#faf9f7; --panel:#f4f2ef; --chip:transparent;
    --brand:#6d1834; --accent:#6d1834;
    /* Gold erreicht auf dem hellen Grund nur 3.75:1 — es trägt darum ausschliesslich
       Grossgrade und Flächen. Kleintext in Gold nimmt --goldtx mit 4.74:1. */
    --gold:#9a7b4f; --goldtx:#8a6a3d;
    --good:#2e7d32; --bad:#c62828;
    /* Didot ist die Etikettenschrift, Optima der humanistische Begleiter, Menlo
       hält die Zahlenspalten. Nichts wird geladen: die Seite bleibt ohne
       Drittanbieter, und jede Stufe hat einen breit vorhandenen Ersatz. */
    --serif:Didot, "Didot LT STD", "Hoefler Text", Garamond, "Times New Roman", serif;
    --sans:Optima, Candara, "Gill Sans", "Gill Sans MT", "Trebuchet MS", "Segoe UI", sans-serif;
    --mono:Menlo, "SF Mono", Consolas, monospace;
    /* Mindesthöhe für Bedienelemente. Auf Zeigergeräten kompakt, auf Touch 44 px —
       dort entscheidet die Treffgenauigkeit, hier die Dichte. */
    --control-h:36px;
    /* Fünf Textrollen. Der Lesetext liegt auf 16 px: die Tabelle ist die am
       längsten gelesene Fläche der Seite. */
    --fs-page-title:2rem;     /* h1, Didot */
    --fs-title:1.25rem;       /* Abschnittstitel, Didot */
    --fs-body:1rem;           /* Tabelle, Suchfeld, Tooltip */
    --fs-body-sm:.875rem;     /* Metatext, Chips, Zähler, Footer, Hinweise */
    --fs-label:.75rem;        /* Legenden, Spaltenköpfe, Pills — gesperrte Versalien */
  }
  @media (prefers-color-scheme: dark) {
    :root { --ink:#f0ebec; --muted:#a49da0; --faint:#8b8488;
            --line:#2b262a; --line-strong:#6f6a6e;
            --bg:#141114; --panel:#1c181c; --chip:transparent;
            --brand:#e0879f; --accent:#e0879f;
            --gold:#c9a877; --goldtx:#d4b587;
            --good:#7cc47f; --bad:#ef9a9a; }
  }
  @media (pointer: coarse) { :root { --control-h:44px; } }
  * { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  /* Ein Fokusstil für alles Bedienbare — vorher hing das Aussehen am Browser. */
  :focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
  html { -webkit-text-size-adjust:100%; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:16px/1.55 var(--sans);
         padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left); }
  .wrap { max-width:1080px; margin:0 auto; padding:26px 18px 56px; }
  h1 { font-family:var(--serif); font-size:var(--fs-page-title); font-weight:400;
       margin:6px 0 0; letter-spacing:-.01em; line-height:1.05; }
  .sub { color:var(--muted); font-size:var(--fs-body-sm); margin:9px 0 0; }
  /* Die Haarlinie unter dem Kopf ist das Etikettenmotiv: getrennt wird mit Linien,
     nicht mit Flächen. */
  .rule { height:1px; background:var(--ink); opacity:.8; margin:15px 0 0; }
  /* ---- Suche und Filter ---------------------------------------------------- */
  /* Suchfeld, Treffermenge und Rückweg bleiben stehen: wer in der Liste liest und
     die Auswahl ändern will, soll nicht nach oben zurück müssen. */
  .search { position:sticky; top:0; z-index:5; background:var(--bg);
            padding:12px 0 10px; border-bottom:1px solid var(--line); }
  .search input { width:100%; font:400 var(--fs-title)/1.35 var(--serif);
                  padding:5px 0 8px; background:transparent; color:var(--ink);
                  border:0; border-bottom:1px solid var(--ctl, var(--line-strong)); }
  .search input::placeholder { color:var(--faint); font-family:var(--serif); }
  .search input:focus { outline:0; border-bottom:2px solid var(--accent); padding-bottom:7px; }
  .search .bar { margin:9px 0 0; }
  .bar { display:flex; align-items:baseline; justify-content:space-between; gap:14px;
         flex-wrap:wrap; }
  .count { font-size:var(--fs-body-sm); color:var(--muted); }
  .count b { color:var(--ink); font-family:var(--mono); font-weight:600;
             font-variant-numeric:tabular-nums; }
  .reset { background:none; border:0; color:var(--accent); font:inherit;
           font-size:var(--fs-body-sm); cursor:pointer; padding:6px 0;
           text-decoration:underline; min-height:var(--control-h); }
  fieldset { border:0; margin:0; padding:0; }
  fieldset + fieldset { margin-top:15px; }
  legend { font-size:var(--fs-label); text-transform:uppercase; letter-spacing:.2em;
           color:var(--faint); margin-bottom:8px; padding:0; }
  .chips { display:flex; flex-wrap:wrap; gap:7px; }
  /* Pillen behalten ihren Umriss: sie sind schaltbar, dort ist der Rahmen
     Information und keine Dekoration. */
  .chip { display:inline-flex; align-items:center; gap:7px;
          border:1px solid var(--line-strong); background:var(--chip); color:var(--muted);
          font:inherit; font-size:var(--fs-body-sm); padding:8px 14px; border-radius:999px;
          cursor:pointer; min-height:var(--control-h); }
  .chip[aria-pressed="true"] { background:var(--accent); border-color:var(--accent);
                               color:var(--bg); font-weight:600; }
  .chip .n { color:var(--faint); font-family:var(--mono); font-size:var(--fs-label);
             font-variant-numeric:tabular-nums; }
  .chip[aria-pressed="true"] .n { color:var(--bg); opacity:.85; }
  /* Kein eigener Oberstrich: die sticky Leiste darüber hat schon einen, sonst
     stehen zwei Linien mit einer leeren Lücke dazwischen. */
  .filters { padding:16px 0 0; margin-top:0; border-top:0; }
  #filterBox > summary { font-size:var(--fs-label); letter-spacing:.16em;
                         text-transform:uppercase; color:var(--accent); cursor:pointer;
                         display:flex; align-items:center; gap:9px;
                         min-height:var(--control-h); list-style:none; }
  #filterBox > summary::-webkit-details-marker { display:none; }
  #filterBox > summary::after { content:"▾"; margin-left:auto; font-size:1.1em;
                                transition:transform .15s; }
  #filterBox[open] > summary::after { transform:rotate(180deg); }
  #filterBox > summary .n { color:var(--faint); letter-spacing:0; text-transform:none;
                            font-size:var(--fs-body-sm); }
  #filterBox[open] > summary { margin-bottom:10px; }
  /* Am Desktop ist Platz — dort sind die Filter immer offen und der Aufklapper
     wäre nur ein zusätzlicher Klick. */
  @media (min-width: 721px) { #filterBox > summary { display:none; } }
  .fine { border-top:1px solid var(--line); padding-top:15px; margin-top:16px; }
  .controls { display:flex; flex-wrap:wrap; gap:14px 26px; align-items:flex-end;
              font-size:var(--fs-body-sm); color:var(--muted); }
  /* Auswahlfelder sind unterstrichen, nicht umkastet — Etiketten arbeiten mit Linien. */
  .controls label { display:flex; flex-direction:column; gap:5px; white-space:nowrap;
                    min-height:var(--control-h); }
  .controls label > span { font-size:var(--fs-label); letter-spacing:.2em;
                           text-transform:uppercase; color:var(--faint); }
  .controls select { font:400 var(--fs-body)/1 var(--serif); color:var(--ink);
                     background:transparent; border:0;
                     border-bottom:1px solid var(--line-strong);
                     padding:4px 16px 6px 0; min-height:var(--control-h); cursor:pointer;
                     appearance:none; max-width:100%; }
  .controls .cb { flex-direction:row; align-items:center; gap:9px; cursor:pointer; }
  .controls input[type=checkbox] { accent-color:var(--accent); width:19px; height:19px;
                                   flex:0 0 auto; }
  .coverage { font-size:var(--fs-body-sm); color:var(--faint); margin:15px 0 0;
              padding-top:12px; border-top:1px solid var(--line); }
  /* ---- Abschnitte: Haarlinie statt Karte --------------------------------- */
  .card { border:0; border-radius:0; background:transparent; padding:24px 0 0;
          margin:22px 0 0; border-top:1px solid var(--ink); }
  .card h2 { font-family:var(--serif); font-size:var(--fs-title); font-weight:400;
             margin:0 0 4px; letter-spacing:-.005em; }
  /* ---- Diagramm ---------------------------------------------------------- */
  svg { width:100%; height:auto; display:block; overflow:visible;
        touch-action:manipulation; }
  .grid { stroke:var(--line); }
  .axis { stroke:var(--line); stroke-width:1; }
  .tick { fill:var(--faint); font-size:10px; font-family:var(--sans); }
  .alabel { fill:var(--faint); font-size:10px; font-family:var(--sans); }
  /* Der Vektor zeigt die Abweichung vom Preisniveau, der Punkt sitzt an seiner
     Spitze. Im markierten Feld ist er gefüllt und golden, sonst hohl und leise. */
  /* Die Trendlinie muss so aussehen wie ihr Symbol in der Legende — sonst sagen
     Diagramm und Legende Unterschiedliches. */
  .trend { stroke:var(--muted); stroke-width:1.1; opacity:.55; }
  .vec { stroke:var(--muted); stroke-width:1; opacity:.5; }
  .vec.good { stroke:var(--gold); stroke-width:1.5; opacity:.95; }
  .pt { fill:none; stroke:var(--muted); stroke-width:1.1; opacity:.55;
        cursor:pointer; }
  .pt.good { fill:var(--gold); stroke:var(--gold); opacity:.95; }
  .pt:hover, .pt:focus-visible { stroke:var(--ink); stroke-width:1.8; opacity:1; }
  .zone { fill:var(--gold); fill-opacity:.14; }
  .zone-edge { fill:none; stroke:var(--gold); stroke-width:1.3; stroke-dasharray:5 3; }
  .zone-t { fill:var(--goldtx); font-family:var(--sans); font-size:9.5px;
            font-weight:600; letter-spacing:1.6px; }
  .zone-s { fill:var(--goldtx); font-family:var(--sans); font-size:9px; opacity:.9; }
  .lead { fill:none; stroke:var(--goldtx); stroke-width:.9; }
  .lead-t { fill:var(--ink); font-family:var(--sans); font-size:10.5px; }
  .legend { font-size:var(--fs-body-sm); color:var(--muted); margin:8px 0 12px;
            display:flex; flex-wrap:wrap; gap:8px 22px; }
  .legend span { display:flex; align-items:center; gap:7px; }
  .legend svg { flex:0 0 auto; width:auto; }
  .empty { color:var(--muted); font-size:var(--fs-body-sm); padding:24px 2px;
           text-align:center; }
  /* ---- Tabelle: Linien, Serif für Namen, Mono für Zahlen ----------------- */
  table { width:100%; border-collapse:collapse; font-size:var(--fs-body); }
  th { text-align:left; font-size:var(--fs-label); text-transform:uppercase;
       letter-spacing:.18em; color:var(--faint); font-weight:400; padding:0 9px 9px;
       border-bottom:1px solid var(--ink); background:transparent; }
  td { padding:13px 9px; border-bottom:1px solid var(--line); vertical-align:baseline;
       background:transparent; }
  tr:last-child td { border-bottom:0; }
  a { color:var(--accent); }
  .wine { font-family:var(--serif); font-size:1.28em; line-height:1.25; }
  .meta { color:var(--faint); font-size:var(--fs-body-sm); }
  .num { font-family:var(--mono); font-variant-numeric:tabular-nums; white-space:nowrap;
         text-align:right; font-size:.92em; }
  /* Die Kennzahl ist der Anker der Seite: Didot, gross, gold. */
  .pl { font-family:var(--serif); font-size:1.55em; line-height:1; color:var(--gold);
        text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
  .pl.neg { color:var(--muted); }
  .good { color:var(--good); font-weight:600; }
  .bad { color:var(--bad); }
  .warn { color:var(--accent); }
  .matched { color:var(--faint); font-size:.78em; }
  /* Sorte und Trinkreife als gesperrte Versalien, nicht als gefüllte Pillen —
     Flächen gehören in dieser Richtung nicht ins Bild. */
  .pill { display:inline-block; font-size:var(--fs-label); letter-spacing:.14em;
          text-transform:uppercase; color:var(--faint); }
  .pill + .pill::before { content:"·"; margin:0 6px 0 2px; opacity:.6; }
  /* Die Markierung sagt, dass ein Wein die Regel erfüllt. Sie steht bei den Fakten,
     nicht in der Zahlenspalte: dort bräche sie auf drei Zeilen. */
  .marker { display:inline-flex; align-items:center; gap:5px; font-size:var(--fs-label);
            letter-spacing:.13em; text-transform:uppercase; color:var(--goldtx);
            border:1px solid var(--gold); border-radius:999px; padding:4px 9px;
            margin-top:7px; }
  th .sortbtn { font:inherit; color:inherit; background:none; border:0; padding:0;
                cursor:pointer; letter-spacing:inherit; text-transform:inherit; }
  th .sortbtn:hover { color:var(--accent); }
  th.sorted { color:var(--ink); }
  th.num .sortbtn { width:100%; text-align:right; }
  .tblnote { font-size:var(--fs-body-sm); color:var(--muted); margin:0 0 14px; }
  .chartnote { font-size:var(--fs-body-sm); color:var(--muted); margin:0 0 10px;
               max-width:78ch; }
  .colhint { font-size:var(--fs-body-sm); color:var(--faint); }
  .more { margin:16px 0 0; text-align:center; }
  .more button { font:inherit; font-size:var(--fs-body-sm); color:var(--accent);
                 cursor:pointer; background:transparent;
                 border:1px solid var(--line-strong); border-radius:999px;
                 padding:9px 20px; min-height:var(--control-h); }
  .more button:hover { border-color:var(--accent); }
  .more .meta { display:block; margin-top:7px; }
  /* Auf dem Handy ist thead ausgeblendet — dort ist der Hinweis schlicht falsch.
     Derselbe Breakpoint wie für Kartenansicht und Diagramm: 720 px. */
  @media (max-width: 720px) {
    .colhint { display:none; }
    h1 { font-size:1.6rem; }
    .wrap { padding:20px 15px 44px; }
    thead { display:none; }
    tr { display:block; border-bottom:1px solid var(--line); padding:14px 0; }
    td { display:block; border:0; padding:2px 0; text-align:left; }
    td[data-l]::before { content:attr(data-l) " "; color:var(--faint);
                         font-size:var(--fs-label); letter-spacing:.1em;
                         text-transform:uppercase; }
    /* In der Tabelle hält ein "—" die Spalte ausgerichtet. In der Kartenansicht
       gibt es keine Spalte mehr — dort ist es nur eine Zeile ohne Inhalt, und
       beim Marktpreis betrifft das die Mehrheit der Weine. */
    td.noval { display:none; }
    .num, .pl { text-align:left; }
    .pl { font-size:1.7em; }
    /* Das Diagramm braucht Breite, die es hier nicht hat. Die Liste ist auf dieser
       Breite die vollständigere Ansicht. */
    .chart { display:none; }
  }
  #tip { position:fixed; z-index:20; pointer-events:none; opacity:0;
         transition:opacity .1s; max-width:320px; background:var(--bg);
         border:1px solid var(--line-strong); border-radius:2px; padding:12px 14px;
         font-size:var(--fs-body-sm); line-height:1.45;
         box-shadow:0 10px 30px rgba(0,0,0,.16); }
  #tip.on { opacity:1; }
  #tip .n { font-family:var(--serif); font-size:1.15em; display:block;
            margin-bottom:7px; line-height:1.25; }
  #tip .r { display:flex; justify-content:space-between; gap:14px; }
  #tip .k { color:var(--faint); }
  #tip .also { margin-top:9px; padding-top:7px; border-top:1px solid var(--line); }
  #tip .also b { display:block; margin-bottom:4px; font-weight:600; }
  footer { color:var(--faint); font-size:var(--fs-body-sm);
           border-top:1px solid var(--line); padding-top:16px; margin-top:32px; }
  footer p { margin:.5em 0; }
  @media (prefers-reduced-motion: reduce) { * { transition:none !important; } }
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
    <p class="chartnote">Die Linie ist die Note, die für diesen Preis üblich ist. Jeder
       Vektor zeigt, wie weit ein Wein davon abweicht — nach oben mehr Note fürs Geld,
       nach unten weniger. Getrennt davon markiert ist die feste Regel für
       <b>gut und günstig</b>: ab Note 4.2 und bis CHF 20.</p>
    <p class="legend">
      <span><svg width="26" height="12" aria-hidden="true"><line x1="1" y1="6" x2="25" y2="6"
        stroke="var(--muted)" stroke-width="1.1" opacity=".55"/></svg> üblich für den Preis</span>
      <span><svg width="16" height="20" aria-hidden="true"><line x1="8" y1="17" x2="8" y2="6"
        stroke="var(--gold)" stroke-width="1.5"/><circle cx="8" cy="5" r="4"
        fill="var(--gold)"/></svg> gut und günstig</span>
      <span><svg width="16" height="20" aria-hidden="true"><line x1="8" y1="3" x2="8" y2="14"
        stroke="var(--muted)" stroke-width="1" opacity=".5"/><circle cx="8" cy="15" r="4"
        fill="none" stroke="var(--muted)" stroke-width="1.1" opacity=".55"/></svg>
        ausserhalb der Regel</span>
      <span>Länge = Abweichung in Notenpunkten</span></p>
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
/* Für die Etiketten im Diagramm: die ersten Wörter genügen, der Tooltip hat den Rest. */
const kurz = n => { const w = String(n).split(" ");
  return w.slice(0, 3).join(" ") + (w.length > 3 ? "…" : ""); };
/* Dieselbe Regel wie im Diagramm: ab Note 4.2 und bis CHF 20, nur dieser Bereich. */
const istGut = w => w.rating != null && w.rating >= D.good.rating
  && w.price > 0 && w.price <= D.good.price;
const vintageSuffix = w => (w.vintage && !String(w.name).includes(String(w.vintage)))
  ? " " + w.vintage : "";
/* Der Wert, nach dem standardmässig sortiert wird, muss auch dastehen — sonst ist die
   Reihenfolge nicht nachvollziehbar. 0 heisst „genau im Preisniveau". */
const valueText = w => {
  if (w.valueScore == null) return '<span class="meta">—</span>';
  const v = w.valueScore;
  return (v > 0 ? "+" : v < 0 ? "−" : "±") + Math.abs(v).toFixed(2);
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
  /* Trendlinie: die Note, die man für diesen Preis üblicherweise bekommt. Aus dem
     Lauf geschätzt, nicht geraten — dieselbe Regression, aus der der
     Preis-Leistungs-Wert kommt. */
  const fit = (() => {
    const lx = pts.map(p => Math.log10(p.price)), ly = pts.map(p => p.rating);
    const n = lx.length, mx = lx.reduce((s, v) => s + v, 0) / n,
          my = ly.reduce((s, v) => s + v, 0) / n;
    const sxx = lx.reduce((s, x) => s + (x - mx) ** 2, 0);
    if (!sxx) return null;
    const bb = lx.reduce((s, x, i) => s + (x - mx) * (ly[i] - my), 0) / sxx;
    return { a: my - bb * mx, b: bb };
  })();
  const erwartet = v => fit ? fit.a + fit.b * Math.log10(v) : null;

  /* Das markierte Feld ist eine feste Regel: ab Note 4.2 und bis CHF 20, nur dieser
     Bereich. Als Rechteck, weil die Regel absolut ist — nicht als Fläche über der
     Trendlinie: „besser als üblich fürs Geld" trifft auch eine mittelmässige Flasche
     für CHF 8. Die Regel ist eng; ist das Feld leer, sagt es das selbst. */
  const gRating = D.good.rating, gPrice = D.good.price;
  const gut = p => p.rating >= gRating && p.price > 0 && p.price <= gPrice;
  const imFeld = pts.filter(gut);
  const zx = Math.min(L + pw, Math.max(L, sx(gPrice)));
  const zy = Math.min(T + ph, Math.max(T, sy(gRating)));
  const zone = (zx > L + 4 && zy > T + 4)
    ? `<rect class="zone" x="${L}" y="${T}" width="${(zx - L).toFixed(1)}" height="${(zy - T).toFixed(1)}"/>`
      + `<path class="zone-edge" d="M ${L} ${zy.toFixed(1)} L ${zx.toFixed(1)} ${zy.toFixed(1)} L ${zx.toFixed(1)} ${T}"/>`
      + `<text class="zone-t" x="${L + 8}" y="${T + 16}">GUT UND GÜNSTIG</text>`
      + `<text class="zone-s" x="${L + 8}" y="${T + 29}">ab Note ${gRating.toFixed(1)} · bis CHF ${gPrice.toFixed(0)}</text>`
      + `<text class="zone-s" x="${L + 8}" y="${(zy - 9).toFixed(1)}">${imFeld.length} von ${pts.length} Weinen</text>`
    : "";

  const trend = fit
    ? `<line class="trend" x1="${sx(Math.pow(10, x0)).toFixed(1)}" y1="${sy(erwartet(Math.pow(10, x0))).toFixed(1)}"`
      + ` x2="${sx(Math.pow(10, x1)).toFixed(1)}" y2="${sy(erwartet(Math.pow(10, x1))).toFixed(1)}"/>`
    : "";

  /* Je Wein ein Vektor von der Trendlinie zu seinem Punkt: Richtung = mehr oder
     weniger Note fürs Geld, Länge = wie viel. Der Punkt sitzt an der Spitze. Weine im
     markierten Feld sind gefüllt und golden, alle anderen hohl und leise — die
     Kennung hängt damit nicht an der Farbe allein, das Feld ist beschriftet. */
  const circles = pts.map((p, i) => {
    const x = sx(p.price).toFixed(1), yP = sy(p.rating).toFixed(1);
    const yE = fit ? sy(erwartet(p.price)).toFixed(1) : yP;
    const cls = gut(p) ? " good" : "";
    return `<line class="vec${cls}" x1="${x}" y1="${yE}" x2="${x}" y2="${yP}"/>`
      + `<circle class="pt${cls}" data-i="${i}" cx="${x}" cy="${yP}" r="4"/>`;
  }).join("");

  /* Benannt werden die Weine, die die Regel erfüllen — sie sind der Punkt der
     Markierung. Die Etiketten sitzen rechts der Zonenkante, damit sie deren
     Beschriftung nicht überschreiben, und gestaffelt gegen sich selbst. */
  const labels = imFeld.slice(0, 4).map((p, i) => {
    const ax = sx(p.price), ay = sy(p.rating);
    const tx = zx + 20, ty = T + 26 + i * 16;
    return `<path class="lead" d="M ${(ax + 5).toFixed(1)} ${ay.toFixed(1)} L ${(zx + 9).toFixed(1)} ${ty.toFixed(1)} L ${tx.toFixed(1)} ${ty.toFixed(1)}"/>`
      + `<text class="lead-t" x="${(tx + 3).toFixed(1)}" y="${(ty + 3.5).toFixed(1)}">${esc(kurz(p.name))}`
      + ` <tspan fill="var(--goldtx)">${p.rating.toFixed(1)} · ${chf(p.price)}</tspan></text>`;
  }).join("");

  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img"
      aria-label="Vivino-Note gegen Preis, ${pts.length} Weine. Eine Trendlinie zeigt die Note, die für diesen Preis üblich ist; je Wein zeigt ein Vektor die Abweichung davon. Markiert ist der Bereich ab Note ${gRating.toFixed(1)} bis CHF ${gPrice.toFixed(0)}: ${imFeld.length} von ${pts.length} Weinen.">
    ${zone}${g}
    <line class="axis" x1="${L}" y1="${T+ph}" x2="${L}" y2="${T}"/>
    <line class="axis" x1="${L}" y1="${T+ph}" x2="${L+pw}" y2="${T+ph}"/>
    <text class="alabel" x="${L+pw/2}" y="${H-8}" text-anchor="middle">Preis pro 75 cl inkl. MwSt (CHF, logarithmisch)</text>
    <text class="alabel" transform="rotate(-90 14 ${T+ph/2})" x="14" y="${T+ph/2}" text-anchor="middle">Vivino-Note (1–5)</text>
    ${trend}<g id="pts">${circles}</g>${labels}</svg>`;

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
        ${w.styleLabel || w.maturityShort ? "<br>" : ""}
        ${w.styleLabel ? `<span class="pill">${esc(w.styleLabel)}</span>` : ""}
        ${w.maturityShort ? `<span class="pill">${esc(w.maturityShort)}</span>` : ""}
        ${istGut(w) ? `<br><span class="marker">◆ gut und günstig</span>` : ""}</td>
      <td data-l="Preis-Leistung" class="pl${w.valueScore == null ? " noval" : ""}${
        (w.valueScore ?? 0) < 0 ? " neg" : ""}">${valueText(w)}</td>
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
  // Ohne Farbpunkt: der Händler trägt hier keine Farbe, nur seinen Namen.
  D.retailers.forEach(r => sh.append(chip(
    r.name, S.shop.has(r.key), toggle(S.shop, r.key))));
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

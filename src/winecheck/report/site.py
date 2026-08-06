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
import time
from pathlib import Path
from typing import Any

from ..names import STYLE_LABELS
from ..trinkreife import MATURITY, MATURITY_SHORT, SOURCE_NAME, SOURCE_PAGE
from .formatting import chf, datetime_ch

#: Reihenfolge der Trinkreife-Filter: von „jetzt" nach „später".
MATURITY_FILTER_ORDER = ("*", "k", "m", "g", "-")

_PALETTE = [
    "#6b1030", "#1a4f8a", "#2e7d32", "#ef6c00", "#6a1b9a",
    "#00838f", "#c62828", "#4e342e", "#37474f", "#9e9d24",
]

_MATURITY_COLOURS = {
    "*": "#2e7d32", "k": "#00838f", "m": "#ef6c00", "g": "#1a4f8a", "-": "#8a8a8a",
}


def _wine_from_snapshot(d: dict[str, Any]) -> dict[str, Any]:
    """Eine Snapshot-Zeile in die Form bringen, die die Seite braucht.

    Ältere Läufe kennen Sorte und Trinkreife nicht — dann bleiben die Felder leer,
    statt geraten zu werden.
    """
    urls = d.get("urls") or {}
    cheapest = d.get("cheapest_retailer") or ""
    return {
        "key": d.get("dedup_key") or d.get("name") or "",
        "name": d.get("name") or "",
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
        "style": d.get("style") or "",
        "styleLabel": d.get("style_label") or STYLE_LABELS.get(d.get("style") or "", ""),
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

    info = retailer_info or {}
    retailers = sorted({r for run in runs for w in run["wines"] for r in w["retailers"]})
    colour = {r: _PALETTE[i % len(_PALETTE)] for i, r in enumerate(retailers)}
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
            {"key": r, "name": names[r], "colour": colour[r], "channel": channels[r]}
            for r in retailers
        ],
        "styles": [{"key": s, "label": STYLE_LABELS[s]} for s in styles],
        "maturities": [
            {"key": m, "label": MATURITY_SHORT[m], "text": MATURITY[m],
             "colour": _MATURITY_COLOURS.get(m, "#5a5a5a")}
            for m in maturities
        ],
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
    --ink:#241f20; --muted:#5f5658; --line:#e2dadd; --brand:#6b1030;
    --bg:#fffdfd; --panel:#f8f4f5; --chip:#efe8ea; --accent:#6b1030;
  }
  @media (prefers-color-scheme: dark) {
    :root { --ink:#eee8ea; --muted:#a89fa2; --line:#393134; --brand:#eaa6bd;
            --bg:#151113; --panel:#1e181a; --chip:#2a2225; --accent:#eaa6bd; }
  }
  * { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  html { -webkit-text-size-adjust:100%; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
         padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left); }
  .wrap { max-width:1180px; margin:0 auto; padding:16px 14px 48px; }
  h1 { font-size:1.35rem; margin:0 0 2px; color:var(--brand); letter-spacing:-.01em; }
  .sub { color:var(--muted); font-size:.82rem; margin:0 0 14px; }
  /* ---- Suche und Filter ---- */
  .search { position:sticky; top:0; z-index:5; background:var(--bg);
            padding:8px 0 10px; margin-bottom:2px; }
  .search input { width:100%; font-size:1rem; padding:11px 13px; border-radius:11px;
                  border:1px solid var(--line); background:var(--panel); color:var(--ink); }
  .search input::placeholder { color:var(--muted); }
  fieldset { border:0; margin:0 0 10px; padding:0; }
  legend { font-size:.72rem; text-transform:uppercase; letter-spacing:.06em;
           color:var(--muted); margin-bottom:5px; padding:0; }
  .chips { display:flex; flex-wrap:wrap; gap:6px; }
  .chip { display:inline-flex; align-items:center; gap:6px; border:1px solid var(--line);
          background:var(--chip); color:inherit; font:inherit; font-size:.8rem;
          padding:7px 11px; border-radius:999px; cursor:pointer; min-height:36px; }
  .chip[aria-pressed="true"] { background:var(--accent); color:var(--bg);
                               border-color:var(--accent); font-weight:600; }
  .chip .dot { width:9px; height:9px; border-radius:50%; flex:0 0 auto; }
  .chip .n { color:var(--muted); font-variant-numeric:tabular-nums; font-size:.74rem; }
  .chip[aria-pressed="true"] .n { color:var(--bg); opacity:.8; }
  .bar { display:flex; align-items:center; justify-content:space-between; gap:12px;
         flex-wrap:wrap; margin:6px 0 12px; }
  .count { font-size:.85rem; color:var(--muted); }
  .count b { color:var(--ink); }
  .reset { background:none; border:0; color:var(--brand); font:inherit;
           font-size:.82rem; cursor:pointer; padding:6px 0; text-decoration:underline; }
  /* ---- Diagramm ---- */
  .card { border:1px solid var(--line); border-radius:14px; background:var(--panel);
          padding:12px; margin-bottom:16px; }
  .card h2 { font-size:.95rem; margin:0 0 8px; color:var(--brand); }
  svg { width:100%; height:auto; display:block; overflow:visible; touch-action:manipulation; }
  .grid { stroke:var(--line); stroke-dasharray:2 3; }
  .axis { stroke:var(--line); stroke-width:1.2; }
  .tick { fill:var(--muted); font-size:11px; }
  .alabel { fill:var(--muted); font-size:12px; }
  .hint { fill:var(--brand); font-size:11px; }
  .pt { stroke:var(--panel); stroke-width:1.3; cursor:pointer; transition:opacity .12s; }
  .pt.off { display:none; }
  .empty { color:var(--muted); font-size:.85rem; padding:22px 4px; text-align:center; }
  /* ---- Tabelle als Karten auf dem Handy ---- */
  table { width:100%; border-collapse:collapse; font-size:.85rem; }
  th { text-align:left; font-size:.72rem; text-transform:uppercase; letter-spacing:.05em;
       color:var(--muted); font-weight:600; padding:6px 8px; border-bottom:1px solid var(--line); }
  td { padding:9px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
  tr:last-child td { border-bottom:0; }
  a { color:#1a4f8a; }
  @media (prefers-color-scheme: dark) { a { color:#8fb8e8; } }
  .wine { font-weight:600; }
  .meta { color:var(--muted); font-size:.76rem; }
  .num { font-variant-numeric:tabular-nums; white-space:nowrap; }
  .good { color:#2e7d32; font-weight:650; }
  .bad { color:#c62828; }
  .warn { color:var(--brand); }
  .colfilter { display:flex; flex-wrap:wrap; gap:10px 16px; align-items:center;
               margin:0 0 12px; font-size:13px; color:var(--muted); }
  .colfilter label { display:flex; gap:6px; align-items:center; }
  .colfilter select { font:inherit; color:var(--ink); background:var(--bg);
                      border:1px solid var(--line); border-radius:7px; padding:4px 6px; }
  .colfilter .cb { cursor:pointer; }
  .colhint { margin-left:auto; font-size:12px; opacity:.75; }
  @media (max-width: 767px) { .colhint { display:none; } }
  th .sortbtn { font:inherit; color:inherit; background:none; border:0; padding:0;
                cursor:pointer; letter-spacing:inherit; text-transform:inherit; }
  th .sortbtn:hover { color:var(--brand); }
  th.sorted { color:var(--brand); }
  th.num .sortbtn { width:100%; text-align:right; }
  @media (prefers-color-scheme: dark){ .good{color:#7cc47f} .bad{color:#ef9a9a} }
  .pill { display:inline-block; font-size:.7rem; padding:2px 7px; border-radius:999px;
          background:var(--chip); color:var(--muted); }
  @media (max-width:720px) {
    thead { display:none; }
    tr { display:block; border-bottom:1px solid var(--line); padding:10px 2px; }
    td { display:block; border:0; padding:2px 0; }
    td[data-l]::before { content:attr(data-l) " "; color:var(--muted); font-size:.74rem; }
    .chart { display:none; }
  }
  #tip { position:fixed; z-index:20; pointer-events:none; opacity:0; transition:opacity .1s;
         max-width:300px; background:var(--panel); border:1px solid var(--line);
         border-radius:10px; padding:9px 11px; font-size:.8rem; line-height:1.45;
         box-shadow:0 8px 26px rgba(0,0,0,.18); }
  #tip.on { opacity:1; }
  #tip .n { font-weight:650; display:block; margin-bottom:3px; }
  #tip .r { display:flex; justify-content:space-between; gap:12px; }
  #tip .k { color:var(--muted); }
  footer { color:var(--muted); font-size:.76rem; border-top:1px solid var(--line);
           padding-top:12px; margin-top:8px; }
  footer p { margin:.4em 0; }
</style>
</head>
<body>
<div class="wrap">
  <h1>__TITLE__</h1>
  <p class="sub">Stand __STAMP__ · Preise auf CHF pro 75 cl inkl. MwSt normalisiert (8.1 %)</p>

  <div class="search">
    <input id="q" type="search" placeholder="Wein, Produzent oder Region suchen …"
           autocomplete="off" autocapitalize="none" spellcheck="false"
           aria-label="Weine durchsuchen">
  </div>

  <fieldset><legend>Lauf</legend><div class="chips" id="fRun"></div></fieldset>
  <fieldset><legend>Trinkreife</legend><div class="chips" id="fMat"></div></fieldset>
  <fieldset><legend>Sorte</legend><div class="chips" id="fStyle"></div></fieldset>
  <fieldset><legend>Händler</legend><div class="chips" id="fShop"></div></fieldset>

  <div class="bar">
    <span class="count" id="count"></span>
    <button class="reset" id="reset" type="button">Filter zurücksetzen</button>
  </div>

  <div class="card chart">
    <h2>Vivino-Bewertung gegen Preis</h2>
    <div id="chart"></div>
  </div>

  <div class="card">
    <h2 id="tblTitle">Weine</h2>
    <div class="colfilter">
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
      <label class="cb" title="Nur Weine mit bestätigtem Namensabgleich — ohne unsichere Treffer, ohne Produzenten-Mittelwerte, ohne Weine ohne Eintrag"><input type="checkbox" id="fFound"> nur bei Vivino gefunden</label>
      <label class="cb"><input type="checkbox" id="fBargain"> nur unter Marktpreis</label>
      <label>Sortieren
        <select id="fSort">
          <option value="rating:-1">Note, beste zuerst</option>
          <option value="price:1">Preis, günstigste zuerst</option>
          <option value="price:-1">Preis, teuerste zuerst</option>
          <option value="bargain:-1">Ersparnis, grösste zuerst</option>
          <option value="name:1">Name A–Z</option>
          <option value="shop:1">Händler A–Z</option>
        </select>
      </label>
      <span class="colhint">Spaltentitel antippen sortiert auch · nochmal antippen kehrt um</span>
    </div>
    <div id="table"></div>
  </div>

  <footer>
    <p><b>Bewertungen</b> von <a href="https://www.vivino.com" rel="noopener">Vivino</a>.
       Die Achse zeigt ausschliesslich die Vivino-Note in ihrer eigenen Skala 1–5 —
       Falstaff- und andere Kritikerpunkte stehen in der Tabelle, aber nicht auf der
       Achse: zwei Bewertungsgrundlagen auf einer Achse sind nicht vergleichbar.</p>
    <p><b>Trinkreife</b> aus der <a href="__SOURCE_PAGE__" rel="noopener">__SOURCE_NAME__</a>.
       Sie gilt für Region und Weinart, nicht für die einzelne Flasche.</p>
    <p><b>Preise</b> von den genannten Händlern, teils über den Aggregator
       <a href="https://www.aktionis.ch" rel="noopener">Aktionis</a> und damit aus zweiter
       Hand. <b>Marktpreise</b> von Vivino-Partnerhändlern, nie vom eigenen Händler.
       Alles ohne Gewähr — vor dem Kauf beim Händler prüfen.</p>
    <p>Diese Seite lädt nichts von Dritten. Sie funktioniert offline, sobald sie
       einmal geladen ist.</p>
  </footer>
</div>
<div id="tip" role="tooltip"></div>

<script>
const D = __PAYLOAD__;
/* Kurzschlüssel aus der eingebetteten JSON zurückbenennen — sie halten die Datei
   klein, der Code arbeitet aber mit lesbaren Namen. */
const KEYS = { n:"name", y:"vintage", p:"price", r:"rating", rc:"ratingCount",
  vu:"vivinoUrl", rs:"retailers", c:"cheapest", u:"url", m:"market", b:"bargain",
  s:"style", sl:"styleLabel", t:"maturity", ts:"maturityShort", tr:"maturityRegion",
  q:"vintageQuality", f:"falstaff", k:"key", wr:"wineryRating",
                   fz:"fuzzy", mn:"matchedName" };
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
const S = { run: D.runs[0].id, mat: new Set(), style: new Set(), shop: new Set(), q: "",
            sort: "rating", dir: -1, minRating: null, maxPrice: null, onlyBargain: false,
            onlyFound: false };
const esc = s => String(s ?? "").replace(/[&<>"']/g, c =>
  ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
const chf = v => v == null ? "" : "CHF " + Number(v).toFixed(2)
  .replace(/\B(?=(\d{3})+(?!\d))/, "'");

function currentRun() { return D.runs.find(r => r.id === S.run) || D.runs[0]; }

function visible() {
  const q = S.q.trim().toLowerCase();
  return currentRun().wines.filter(w => {
    if (S.mat.size && !S.mat.has(w.maturity || "?")) return false;
    if (S.style.size && !S.style.has(w.style || "?")) return false;
    if (S.shop.size && !w.retailers.some(r => S.shop.has(r))) return false;
    if (q && !(w.name + " " + (w.maturityRegion || "")).toLowerCase().includes(q)) return false;
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
  if (pts.length < 2) {
    box.innerHTML = '<p class="empty">' +
      (pts.length ? "Nur ein Wein mit Vivino-Note — siehe Tabelle."
                  : "Kein Wein mit Vivino-Note in dieser Auswahl. Die Tabelle zeigt alle.") +
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
  const shopColour = Object.fromEntries(D.retailers.map(r => [r.key, r.colour]));
  // Unbestätigte Namensabgleiche werden hohl gezeichnet. Inline-style, weil die
  // Regel .pt { stroke: ... } ein stroke-Attribut überstimmen würde.
  const circles = pts.map((p, i) => {
    const c = shopColour[p.cheapest] || "#6b1030";
    const paint = p.fuzzy
      ? `style="fill:none;stroke:${c};stroke-width:1.8"`
      : `fill="${c}"`;
    return `<circle class="pt" data-i="${i}" cx="${sx(p.price).toFixed(1)}"`
      + ` cy="${sy(p.rating).toFixed(1)}" r="6" ${paint}/>`;
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
  const show = (el, ev) => {
    const p = pts[+el.dataset.i]; if (!p) return;
    const row = (k, v) => `<div class="r"><span class="k">${k}</span><span>${v}</span></div>`;
    let h = `<span class="n">${esc(p.name)}${p.vintage ? " " + p.vintage : ""}</span>`;
    h += row("Vivino", p.rating.toFixed(1) + "/5" + (p.ratingCount ? ` (${p.ratingCount})` : ""));
    if (p.fuzzy) h += row("Achtung", `<span class="warn">Namensabgleich unbestätigt`
      + (p.matchedName ? ` — gefunden: „${esc(p.matchedName)}"` : "") + `</span>`);
    if (p.styleLabel) h += row("Sorte", esc(p.styleLabel));
    if (p.maturityShort) h += row("Trinkreife", "<b>" + esc(p.maturityShort) + "</b>");
    h += row("Preis/75cl", chf(p.price));
    h += row("Händler", esc((D.retailers.find(r => r.key === p.cheapest) || {}).name || p.cheapest));
    if (p.bargain != null) {
      const c = p.bargain > 0 ? "good" : "bad";
      h += row("gegen Markt", `<span class="${c}">${p.bargain > 0 ? "−" : "+"}`
        + Math.abs(p.bargain).toFixed(0) + "%</span>");
    }
    if (p.falstaff != null) h += row("Falstaff", p.falstaff.toFixed(0) + "/100");
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
  host.addEventListener("click", e => {
    if (!e.target.classList.contains("pt")) return;
    const p = pts[+e.target.dataset.i], href = p && (p.url || p.vivinoUrl);
    if (href) window.open(href, "_blank", "noopener");
  });
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
  };
  const key = KEYS[S.sort] || KEYS.rating;
  const sorted = list.slice().sort((a, b) => {
    const x = key(a), y = key(b);
    const xe = x == null || x === "", ye = y == null || y === "";
    if (xe && ye) return 0;
    if (xe) return 1;
    if (ye) return -1;
    if (typeof x === "string") return S.dir * x.localeCompare(y, "de");
    return S.dir * (x - y);
  });
  const rows = sorted.slice(0, 400).map(w => {
    const vivino = w.rating != null
      ? `<a href="${esc(w.vivinoUrl)}" rel="noopener">${w.rating.toFixed(1)}/5</a>`
        + (w.ratingCount ? ` <span class="meta">(${w.ratingCount})</span>` : "")
        + (w.fuzzy ? ` <span class="warn" title="Namensabgleich unbestätigt`
            + (w.matchedName ? `, gefunden: ${esc(w.matchedName)}` : "") + `">?</span>` : "")
      : w.wineryRating != null
        ? `<a href="${esc(w.vivinoUrl)}" rel="noopener" class="meta">nur Produzenten-Ø `
          + w.wineryRating.toFixed(1) + "/5</a>"
        : `<a href="${esc(w.vivinoUrl)}" rel="noopener" class="meta">keine Note</a>`;
    const bargain = w.bargain == null ? '<span class="meta">—</span>'
      : `<span class="${w.bargain > 0 ? "good" : "bad"}">${w.bargain > 0 ? "−" : "+"}`
        + Math.abs(w.bargain).toFixed(0) + "%</span>";
    const shop = w.url ? `<a href="${esc(w.url)}" rel="noopener">${esc(shopName(w.cheapest))}</a>`
                       : esc(shopName(w.cheapest));
    return `<tr>
      <td data-l="Wein"><span class="wine">${esc(w.name)}</span>
        ${w.vintage ? `<span class="meta"> ${w.vintage}</span>` : ""}
        ${w.styleLabel ? `<br><span class="pill">${esc(w.styleLabel)}</span>` : ""}
        ${w.maturityShort ? ` <span class="pill">${esc(w.maturityShort)}</span>` : ""}</td>
      <td data-l="Vivino">${vivino}</td>
      <td data-l="Preis/75cl" class="num">${chf(w.price)}</td>
      <td data-l="Wo kaufen">${shop}</td>
      <td data-l="gegen Markt" class="num">${bargain}</td>
    </tr>`;
  }).join("");
  const COLS = [
    ["name", "Wein", ""], ["rating", "Vivino", ""], ["price", "Preis/75cl", "num"],
    ["shop", "Wo kaufen", ""], ["bargain", "gegen Markt", "num"],
  ];
  const head = COLS.map(([k, label, cls]) => {
    const on = S.sort === k;
    const arrow = on ? (S.dir < 0 ? " ▾" : " ▴") : "";
    return `<th class="${cls}${on ? " sorted" : ""}"><button type="button" class="sortbtn"`
      + ` data-col="${k}" aria-label="Nach ${esc(label)} sortieren">${esc(label)}${arrow}</button></th>`;
  }).join("");
  box.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table>`
    + (sorted.length > 400 ? `<p class="empty">${sorted.length - 400} weitere ausgeblendet — Filter verfeinern.</p>` : "");

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
function chip(label, pressed, onClick, extra = "") {
  const b = document.createElement("button");
  b.type = "button"; b.className = "chip"; b.setAttribute("aria-pressed", String(pressed));
  b.innerHTML = extra + esc(label);
  b.addEventListener("click", () => { onClick(); render(); });
  return b;
}

function buildFilters() {
  const run = document.getElementById("fRun"); run.innerHTML = "";
  D.runs.forEach(r => run.append(chip(
    r.label, S.run === r.id, () => { S.run = r.id; },
    `<span class="n">${r.wines.length}</span>&nbsp;`)));

  const toggle = (set, key) => () => set.has(key) ? set.delete(key) : set.add(key);
  const mat = document.getElementById("fMat"); mat.innerHTML = "";
  D.maturities.forEach(m => mat.append(chip(
    m.label, S.mat.has(m.key), toggle(S.mat, m.key),
    `<span class="dot" style="background:${m.colour}"></span>`)));
  mat.append(chip("keine Angabe", S.mat.has("?"), toggle(S.mat, "?")));

  const st = document.getElementById("fStyle"); st.innerHTML = "";
  D.styles.forEach(s => st.append(chip(s.label, S.style.has(s.key), toggle(S.style, s.key))));

  const sh = document.getElementById("fShop"); sh.innerHTML = "";
  D.retailers.forEach(r => sh.append(chip(
    r.name, S.shop.has(r.key), toggle(S.shop, r.key),
    `<span class="dot" style="background:${r.colour}"></span>`)));
}

function render() {
  buildFilters();
  const list = visible(), total = currentRun().wines.length;
  const rated = list.filter(w => w.rating != null).length;
  document.getElementById("count").innerHTML =
    `<b>${list.length}</b> von ${total} Weinen · ${rated} mit Vivino-Note`;
  document.getElementById("tblTitle").textContent =
    list.length === total ? "Alle Weine" : "Gefilterte Weine";
  chart(list); table(list);
}

document.getElementById("q").addEventListener("input", e => { S.q = e.target.value; render(); });
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
  S.minRating = numOrNull(e.target.value); render();
});
document.getElementById("fMaxPrice").addEventListener("change", e => {
  S.maxPrice = numOrNull(e.target.value); render();
});
document.getElementById("fBargain").addEventListener("change", e => {
  S.onlyBargain = e.target.checked; render();
});
document.getElementById("fFound").addEventListener("change", e => {
  S.onlyFound = e.target.checked; render();
});
document.getElementById("reset").addEventListener("click", () => {
  S.mat.clear(); S.style.clear(); S.shop.clear(); S.q = "";
  S.minRating = null; S.maxPrice = null; S.onlyBargain = false; S.onlyFound = false;
  S.sort = "rating"; S.dir = -1;
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

"""scatter.html — dasselbe Streudiagramm, aber mit Mouseover.

``scatter.png`` bleibt für PDF und Druck; hier kommt die interaktive Fassung dazu.
Beim Überfahren eines Punktes erscheinen Weinname und Vivino-Bewertung, dazu Preis,
Händler und die Ersparnis gegenüber dem Marktpreis. Ein Klick öffnet die Händlerseite.

Bewusst **selbstenthaltend**: Inline-SVG plus Vanilla-JS, keine CDN-Abhängigkeit. Die
Datei liegt in OneDrive und muss auch offline und ohne Buildschritt funktionieren.
"""

from __future__ import annotations

import html
import json
import math
from pathlib import Path

from ..models import PriceConfidence, WineRow
from .formatting import chf, datetime_ch

#: Zeichenfläche in SVG-Nutzerkoordinaten. Das SVG skaliert per viewBox mit.
WIDTH, HEIGHT = 1180, 660
PAD_LEFT, PAD_RIGHT, PAD_TOP, PAD_BOTTOM = 70, 210, 46, 62

_PALETTE = [
    "#6b1030", "#1a4f8a", "#2e7d32", "#ef6c00", "#6a1b9a",
    "#00838f", "#c62828", "#4e342e", "#37474f", "#9e9d24",
]


def _points(rows: list[WineRow]) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        rating, source = row.ranking_rating()
        price = row.best_price
        if rating is None or price is None or price <= 0:
            continue
        if all(p.price_confidence is PriceConfidence.LOW for p in row.prices):
            continue
        v = row.vivino
        cheapest = next(
            (p for p in row.prices if p.price_per_bottle_incl_vat == price), None
        )
        out.append({
            "name": row.name,
            "vintage": row.vintage or "",
            "price": price,
            "priceText": chf(price),
            "rating": rating,
            "source": source,
            "vivino": (
                f"{v.rating:.1f}/5 aus {v.rating_count} Bewertungen"
                if v and v.rating is not None and v.rating_count
                else (f"{v.rating:.1f}/5" if v and v.rating is not None else "keine Note")
            ),
            "vivinoUrl": v.url if v else "",
            "retailer": row.cheapest_retailer or "unbekannt",
            "url": (cheapest.url if cheapest else "") or "",
            "market": chf(v.market_price) if v and v.market_price is not None else "",
            "bargain": row.bargain_percent,
            "band": row.price_band,
            "reife": row.maturity.short if row.maturity else "",
            "reifeText": row.maturity.text if row.maturity else "",
            "reifeRegion": (
                f"{row.maturity.region_label} {row.maturity.wine_type}" if row.maturity else ""
            ),
            "jahrgang": (row.maturity.quality or "") if row.maturity else "",
            "retailers": sorted({p.retailer for p in row.prices}),
        })
    return out


def write_interactive(
    rows: list[WineRow],
    path: Path | str,
    *,
    retailer_info: dict[str, dict] | None = None,
) -> Path | None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    points = _points(rows)
    if not points:
        return None

    info = retailer_info or {}
    retailers = sorted({pt["retailer"] for pt in points})
    colour = {r: _PALETTE[i % len(_PALETTE)] for i, r in enumerate(retailers)}
    for pt in points:
        pt["colour"] = colour[pt["retailer"]]
        pt["retailerName"] = (info.get(pt["retailer"]) or {}).get("name") or pt["retailer"]
        pt["channel"] = (info.get(pt["retailer"]) or {}).get("channel") or ""

    prices = [pt["price"] for pt in points]
    ratings = [pt["rating"] for pt in points]
    x_min, x_max = min(prices), max(prices)
    y_min, y_max = min(ratings), max(ratings)
    # Etwas Luft, damit Punkte nicht am Rand kleben.
    lx_min, lx_max = math.log10(x_min) - 0.06, math.log10(x_max) + 0.06
    y_lo, y_hi = max(0.0, y_min - 0.02), min(1.0, y_max + 0.02)

    plot_w = WIDTH - PAD_LEFT - PAD_RIGHT
    plot_h = HEIGHT - PAD_TOP - PAD_BOTTOM

    def sx(price: float) -> float:
        return PAD_LEFT + (math.log10(price) - lx_min) / (lx_max - lx_min) * plot_w

    def sy(rating: float) -> float:
        return PAD_TOP + (1 - (rating - y_lo) / (y_hi - y_lo or 1)) * plot_h

    for pt in points:
        pt["cx"] = round(sx(pt["price"]), 1)
        pt["cy"] = round(sy(pt["rating"]), 1)

    # Achsen: x-Ticks als runde CHF-Werte innerhalb der Spanne.
    x_ticks = [v for v in (1, 2, 3, 5, 7, 10, 15, 20, 30, 50, 75, 100, 150, 200, 300, 500, 800)
               if x_min * 0.95 <= v <= x_max * 1.05]
    y_ticks = [round(y_lo + i * (y_hi - y_lo) / 5, 3) for i in range(6)]

    grid = []
    for v in x_ticks:
        x = round(sx(v), 1)
        grid.append(f'<line class="grid" x1="{x}" y1="{PAD_TOP}" x2="{x}" y2="{PAD_TOP + plot_h}"/>')
        grid.append(
            f'<text class="tick" x="{x}" y="{PAD_TOP + plot_h + 18}" text-anchor="middle">{v}</text>'
        )
    for v in y_ticks:
        y = round(sy(v), 1)
        grid.append(f'<line class="grid" x1="{PAD_LEFT}" y1="{y}" x2="{PAD_LEFT + plot_w}" y2="{y}"/>')
        grid.append(
            f'<text class="tick" x="{PAD_LEFT - 8}" y="{y + 3.5}" text-anchor="end">{v:.2f}</text>'
        )

    circles = "".join(
        f'<circle class="pt" data-i="{i}" cx="{pt["cx"]}" cy="{pt["cy"]}" r="6" '
        f'fill="{pt["colour"]}" data-retailer="{html.escape(pt["retailer"])}"/>'
        for i, pt in enumerate(points)
    )

    legend_rows = "".join(
        f'<li><button class="legend-item" data-retailer="{html.escape(r)}" aria-pressed="true">'
        f'<span class="dot" style="background:{colour[r]}"></span>'
        f'<span class="legend-label">{html.escape((info.get(r) or {}).get("name") or r)}</span>'
        f'<span class="legend-count">{sum(1 for pt in points if pt["retailer"] == r)}</span>'
        f"</button></li>"
        for r in retailers
    )

    payload = json.dumps(points, ensure_ascii=False)
    doc = _TEMPLATE.format(
        stamp=html.escape(datetime_ch()),
        count=len(points),
        width=WIDTH,
        height=HEIGHT,
        pad_left=PAD_LEFT,
        plot_w=plot_w,
        plot_h=plot_h,
        axis_y=PAD_TOP + plot_h,
        pad_top=PAD_TOP,
        plot_right=PAD_LEFT + plot_w,
        y_label_y=PAD_TOP + plot_h / 2,
        hint_y=PAD_TOP - 12,
        x_label_x=PAD_LEFT + plot_w / 2,
        x_label_y=HEIGHT - 14,
        grid="".join(grid),
        circles=circles,
        legend=legend_rows,
        legend_x=PAD_LEFT + plot_w + 26,
        payload=payload,
    )
    p.write_text(doc, encoding="utf-8")
    return p


_TEMPLATE = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>wine-check — Preis gegen Bewertung</title>
<style>
  :root {{
    --ink: #24201f; --muted: #5a5a5a; --line: #ded7d9;
    --brand: #6b1030; --bg: #ffffff; --panel: #faf7f8;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --ink: #ece7e8; --muted: #a9a2a4; --line: #3a3335;
             --brand: #e8a3ba; --bg: #171416; --panel: #201b1d; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 20px; background: var(--bg); color: var(--ink);
         font: 14px/1.5 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
  h1 {{ font-size: 19px; margin: 0 0 2px; color: var(--brand); }}
  .sub {{ color: var(--muted); font-size: 12.5px; margin: 0 0 14px; }}
  .wrap {{ position: relative; max-width: 1240px; }}
  svg {{ width: 100%; height: auto; display: block; overflow: visible; }}
  .grid {{ stroke: var(--line); stroke-width: 1; stroke-dasharray: 2 3; }}
  .axis {{ stroke: var(--line); stroke-width: 1.2; }}
  .tick {{ fill: var(--muted); font-size: 11px; }}
  .axis-label {{ fill: var(--muted); font-size: 12px; }}
  .hint {{ fill: var(--brand); font-size: 12px; }}
  .pt {{ stroke: var(--bg); stroke-width: 1.4; cursor: pointer;
        transition: r .09s ease, opacity .12s ease; }}
  .pt:hover {{ r: 9; }}
  .pt.dim {{ opacity: .08; pointer-events: none; }}
  .pt.on {{ r: 9.5; stroke: var(--ink); stroke-width: 2; }}
  ul.legend {{ list-style: none; margin: 0; padding: 0; position: absolute;
              right: 0; top: 58px; width: 186px; }}
  .legend-item {{ display: flex; align-items: center; gap: 8px; width: 100%;
                 background: none; border: 0; padding: 4px 6px; border-radius: 6px;
                 color: inherit; font: inherit; font-size: 12.5px; cursor: pointer; }}
  .legend-item:hover {{ background: var(--panel); }}
  .legend-item[aria-pressed="false"] {{ opacity: .38; }}
  .dot {{ width: 11px; height: 11px; border-radius: 50%; flex: 0 0 auto;
         margin-right: 2px; }}
  .legend-label {{ flex: 1 1 auto; text-align: left; }}
  .legend-count {{ color: var(--muted); font-variant-numeric: tabular-nums; }}
  #tip {{ position: fixed; z-index: 10; pointer-events: none; opacity: 0;
         transition: opacity .1s ease; max-width: 330px;
         background: var(--panel); color: var(--ink);
         border: 1px solid var(--line); border-radius: 9px;
         padding: 9px 11px; box-shadow: 0 6px 22px rgba(0,0,0,.17);
         font-size: 12.5px; line-height: 1.45; }}
  #tip.on {{ opacity: 1; }}
  #tip .n {{ font-weight: 650; display: block; margin-bottom: 4px; }}
  #tip .r {{ display: flex; justify-content: space-between; gap: 14px; }}
  #tip .k {{ color: var(--muted); }}
  #tip .good {{ color: #2e7d32; font-weight: 650; }}
  #tip .bad {{ color: #c62828; font-weight: 650; }}
  @media (prefers-color-scheme: dark) {{
    #tip .good {{ color: #7bc47f; }} #tip .bad {{ color: #ef9a9a; }}
  }}
  #tip .go {{ color: var(--muted); font-size: 11.5px; margin-top: 5px;
             border-top: 1px solid var(--line); padding-top: 5px; }}
  .foot {{ color: var(--muted); font-size: 11.5px; margin-top: 12px; max-width: 900px; }}
</style>
</head>
<body>
<h1>Preis gegen Bewertung</h1>
<p class="sub">Stand {stamp} · {count} Weine mit Preis und Bewertung · Punkt anfahren für
Details, Klick öffnet die Händlerseite · Händler in der Legende zum Ausblenden</p>

<div class="wrap">
  <svg viewBox="0 0 {width} {height}" role="img" aria-label="Streudiagramm Preis gegen Bewertung">
    {grid}
    <line class="axis" x1="{pad_left}" y1="{axis_y}" x2="{pad_left}" y2="{pad_top}"/>
    <line class="axis" x1="{pad_left}" y1="{axis_y}" x2="{plot_right}" y2="{axis_y}"/>
    <text class="axis-label" x="{x_label_x}" y="{x_label_y}" text-anchor="middle">
      Preis pro 75 cl inkl. MwSt (CHF, logarithmisch)
    </text>
    <!-- Gedreht an der Achse, sonst kollidiert die Beschriftung mit dem Hinweis. -->
    <text class="axis-label" transform="rotate(-90 18 {y_label_y})" x="18" y="{y_label_y}"
          text-anchor="middle">Normalisierte Bewertung (0–1)</text>
    <text class="hint" x="{pad_left}" y="{hint_y}">oben links = gut und günstig</text>
    <g id="pts">{circles}</g>
  </svg>
  <ul class="legend">{legend}</ul>
</div>

<div id="tip" role="tooltip"></div>

<p class="foot">Die Bewertung ist auf 0–1 normalisiert, damit sich Falstaff (0–100) und
Vivino (1–5) vergleichen lassen; die Quelle steht je Punkt im Tooltip. Der Marktpreis
stammt von einem Vivino-Händler und ausdrücklich nicht vom eigenen Händler — sonst
verglichen wir einen Preis mit sich selbst.</p>

<script>
const DATA = {payload};
const tip = document.getElementById("tip");
const pts = document.getElementById("pts");
const hidden = new Set();

function row(k, v) {{
  return '<div class="r"><span class="k">' + k + '</span><span>' + v + "</span></div>";
}}

function show(el, evt) {{
  const d = DATA[+el.dataset.i];
  if (!d) return;
  let h = '<span class="n">' + esc(d.name) + (d.vintage ? " " + d.vintage : "") + "</span>";
  h += row("Vivino", esc(d.vivino));
  if (d.source && d.source !== "Vivino") h += row("Ranking über", esc(d.source));
  if (d.reife) {{
    h += row("Trinkreife", '<b>' + esc(d.reife) + "</b>");
  }}
  if (d.jahrgang) h += row("Jahrgang", esc(d.jahrgang));
  h += row("Preis/75cl", esc(d.priceText));
  h += row("Händler", esc(d.retailerName) + (d.retailers.length > 1
        ? " (+" + (d.retailers.length - 1) + ")" : ""));
  if (d.channel) h += row("Kauf", esc(d.channel));
  if (d.market) {{
    if (d.bargain === null || d.bargain === undefined) {{
      h += row("Marktpreis", esc(d.market));
    }} else {{
      const cls = d.bargain > 0 ? "good" : "bad";
      const sign = d.bargain > 0 ? "\\u2212" : "+";
      h += row("gegen Markt", '<span class="' + cls + '">' + sign
           + Math.abs(d.bargain).toFixed(0) + " %</span> von " + esc(d.market));
    }}
  }}
  h += '<div class="go">' + (d.url ? "Klick: Händlerseite öffnen" : "keine Händler-URL") + "</div>";
  tip.innerHTML = h;
  tip.classList.add("on");
  place(evt);
  el.classList.add("on");
}}

function place(evt) {{
  const m = 14, w = tip.offsetWidth, h = tip.offsetHeight;
  let x = evt.clientX + m, y = evt.clientY + m;
  if (x + w > innerWidth - 8) x = evt.clientX - w - m;
  if (y + h > innerHeight - 8) y = evt.clientY - h - m;
  tip.style.left = Math.max(8, x) + "px";
  tip.style.top = Math.max(8, y) + "px";
}}

function hide() {{
  tip.classList.remove("on");
  pts.querySelectorAll(".pt.on").forEach(function (e) {{ e.classList.remove("on"); }});
}}

const esc = function (s) {{
  return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {{
    return {{ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }}[c];
  }});
}};

pts.addEventListener("mouseover", function (e) {{
  if (e.target.classList.contains("pt")) show(e.target, e);
}});
pts.addEventListener("mousemove", function (e) {{
  if (tip.classList.contains("on")) place(e);
}});
pts.addEventListener("mouseout", function (e) {{
  if (e.target.classList.contains("pt")) hide();
}});
pts.addEventListener("click", function (e) {{
  if (!e.target.classList.contains("pt")) return;
  const d = DATA[+e.target.dataset.i];
  const href = d && (d.url || d.vivinoUrl);
  if (href) window.open(href, "_blank", "noopener");
}});

// Tastaturzugang: Punkte per Tab erreichbar machen wäre bei 200 Punkten mühsam —
// stattdessen filtert die Legende, und die Tabellen im PDF bleiben die Volltextsicht.
document.querySelectorAll(".legend-item").forEach(function (btn) {{
  btn.addEventListener("click", function () {{
    const key = btn.dataset.retailer;
    if (hidden.has(key)) {{ hidden.delete(key); }} else {{ hidden.add(key); }}
    btn.setAttribute("aria-pressed", hidden.has(key) ? "false" : "true");
    pts.querySelectorAll(".pt").forEach(function (c) {{
      c.classList.toggle("dim", hidden.has(c.dataset.retailer));
    }});
    hide();
  }});
}});
</script>
</body>
</html>
"""

"""scatter.png — Preis/75 cl (x, logarithmisch) gegen normalisierte Bewertung (y).

Nach Händler gefärbt. Ausreisser oben links — gut und günstig — werden beschriftet,
denn das ist die Ecke, um die es beim ganzen Werkzeug geht.
"""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from ..models import PriceConfidence, WineRow  # noqa: E402
from .formatting import date, truncate  # noqa: E402

#: Wie viele Ausreisser beschriftet werden.
LABEL_COUNT = 8

#: Mindestabstand zwischen zwei Beschriftungen. Der x-Wert ist grosszügig, weil der
#: Text nach rechts über seinen Ankerpunkt hinausragt — mit 0.16 Dekaden überschrieben
#: sich die Namen in der dicht besetzten Ecke unten links noch.
LABEL_MIN_DX = 0.5
LABEL_MIN_DY = 0.015

_PALETTE = [
    "#6b1030", "#1a4f8a", "#2e7d32", "#ef6c00", "#6a1b9a",
    "#00838f", "#c62828", "#4e342e", "#37474f", "#9e9d24",
]


def write_scatter(rows: list[WineRow], path: Path | str) -> Path | None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    points: list[tuple[float, float, str, str]] = []
    for row in rows:
        rating, source = row.ranking_rating()
        price = row.best_price
        if rating is None or price is None or price <= 0:
            continue
        if all(x.price_confidence is PriceConfidence.LOW for x in row.prices):
            continue
        points.append((price, rating, row.cheapest_retailer or "unbekannt", row.name))

    if not points:
        return None

    retailers = sorted({r for _, _, r, _ in points})
    colour = {r: _PALETTE[i % len(_PALETTE)] for i, r in enumerate(retailers)}

    fig, ax = plt.subplots(figsize=(11, 7), dpi=150)
    for retailer in retailers:
        xs = [x for x, _, r, _ in points if r == retailer]
        ys = [y for _, y, r, _ in points if r == retailer]
        ax.scatter(xs, ys, s=46, alpha=0.82, label=retailer,
                   color=colour[retailer], edgecolors="white", linewidths=0.6)

    # Ausreisser oben links: hohe Bewertung, tiefer Preis. Beschriftet wird nur, was
    # sich nicht überlappt — mehrere Weine teilen oft dieselbe gerundete Note, und
    # übereinandergedruckte Namen sind unbrauchbar.
    ranked = sorted(points, key=lambda t: -(t[1] / (t[0] ** 0.5)))
    placed: list[tuple[float, float]] = []
    for x, y, _r, name in ranked:
        if len(placed) >= LABEL_COUNT:
            break
        lx = math.log10(x)
        if any(abs(lx - px) < LABEL_MIN_DX and abs(y - py) < LABEL_MIN_DY
               for px, py in placed):
            continue
        placed.append((lx, y))
        ax.annotate(
            truncate(name, 26),
            (x, y),
            textcoords="offset points",
            xytext=(8, 4),
            fontsize=7.2,
            color="#333333",
        )

    ax.set_xscale("log")
    ax.set_xlabel("Preis pro 75 cl inkl. MwSt (CHF, logarithmisch)")
    ax.set_ylabel("Normalisierte Bewertung (0–1)")
    ax.set_title(f"Preis gegen Bewertung — Stand {date()}")
    ax.grid(True, which="both", linestyle=":", linewidth=0.5, alpha=0.6)
    ax.set_axisbelow(True)
    ax.legend(title="Günstigster Händler", fontsize=8, title_fontsize=8,
              loc="lower right", framealpha=0.9)
    ax.text(
        0.01, 0.985,
        "oben links = gut und günstig",
        transform=ax.transAxes, fontsize=8, color="#6b1030", va="top",
    )
    # Hinweis auf gemischte Skalen: Falstaff 0–100 und Vivino 1–5 sind beide auf
    # 0–1 normalisiert; die Herkunft steht in results.csv je Zeile.
    sources = sorted({s for r in rows if (s := r.ranking_rating()[1])})
    if len(sources) > 1:
        ax.text(
            0.01, 0.945,
            "Bewertungsquellen gemischt: " + ", ".join(sources) + " (Herkunft je Zeile in results.csv)",
            transform=ax.transAxes, fontsize=7, color="#5a5a5a", va="top",
        )

    fig.tight_layout()
    fig.savefig(p)
    plt.close(fig)
    return p

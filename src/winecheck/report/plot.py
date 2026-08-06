"""scatter.png — Preis/75 cl (x, logarithmisch) gegen Vivino-Bewertung (y).

Nach Händler gefärbt. Ausreisser oben links — gut und günstig — werden beschriftet,
denn das ist die Ecke, um die es beim ganzen Werkzeug geht.

Die y-Achse zeigt **nur Vivino**, nicht die Ranglisten-Note. Falstaff auf 0–100 und
Vivino auf 1–5 lassen sich normalisieren, aber nicht vergleichen: nebeneinander
liegende Punkte hätten dann verschiedene Bedeutung. Für die Rangliste bleibt Falstaff
die Leitquelle, hier zählt die eine Skala, die alle Weine teilen.
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
#: Auf der Vivino-Skala 1–5. Viele Weine teilen dieselbe gerundete Zehntelnote, darum
#: ist knapp unter einem Zehntel der richtige Abstand.
LABEL_MIN_DY = 0.075

_PALETTE = [
    "#6b1030", "#1a4f8a", "#2e7d32", "#ef6c00", "#6a1b9a",
    "#00838f", "#c62828", "#4e342e", "#37474f", "#9e9d24",
]


def write_scatter(rows: list[WineRow], path: Path | str) -> Path | None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    points: list[tuple[float, float, str, str, bool]] = []
    for row in rows:
        rating = row.chart_rating()
        price = row.best_price
        if rating is None or price is None or price <= 0:
            continue
        if all(x.price_confidence is PriceConfidence.LOW for x in row.prices):
            continue
        points.append((
            price, rating, row.cheapest_retailer or "unbekannt", row.name,
            row.chart_confirmed(),
        ))

    if not points:
        return None

    retailers = sorted({r for _x, _y, r, _n, _ok in points})
    colour = {r: _PALETTE[i % len(_PALETTE)] for i, r in enumerate(retailers)}

    fig, ax = plt.subplots(figsize=(11, 7), dpi=150)
    for retailer in retailers:
        # Bestätigte Treffer gefüllt, fuzzy hohl. Sonst behauptet ein ungeprüfter
        # Namensabgleich dieselbe Sicherheit wie ein exakter.
        sure = [(x, y) for x, y, r, _n, ok in points if r == retailer and ok]
        maybe = [(x, y) for x, y, r, _n, ok in points if r == retailer and not ok]
        if sure:
            ax.scatter([x for x, _ in sure], [y for _, y in sure],
                       s=46, alpha=0.82, label=retailer,
                       color=colour[retailer], edgecolors="white", linewidths=0.6)
        if maybe:
            ax.scatter([x for x, _ in maybe], [y for _, y in maybe],
                       s=42, alpha=0.9, label=retailer if not sure else None,
                       facecolors="none", edgecolors=colour[retailer], linewidths=1.3)

    # Ausreisser oben links: hohe Bewertung, tiefer Preis. Beschriftet wird nur, was
    # sich nicht überlappt — mehrere Weine teilen oft dieselbe gerundete Note, und
    # übereinandergedruckte Namen sind unbrauchbar.
    # Nur bestätigte Treffer werden beschriftet — der Name neben einem Punkt liest sich
    # als Empfehlung, und die soll nicht auf einem ungeprüften Match stehen.
    ranked = sorted((p for p in points if p[4]), key=lambda t: -(t[1] / (t[0] ** 0.5)))
    placed: list[tuple[float, float]] = []
    for x, y, _r, name, _ok in ranked:
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
    ax.set_ylabel("Vivino-Bewertung (1–5)")
    ax.set_title(f"Preis gegen Vivino-Bewertung — Stand {date()}")
    ax.grid(True, which="both", linestyle=":", linewidth=0.5, alpha=0.6)
    ax.set_axisbelow(True)
    ax.legend(title="Günstigster Händler", fontsize=8, title_fontsize=8,
              loc="lower right", framealpha=0.9)
    ax.text(
        0.01, 0.985,
        "oben links = gut und günstig",
        transform=ax.transAxes, fontsize=8, color="#6b1030", va="top",
    )
    # Wie viele Weine die Achse nicht erreichen, muss dastehen: sonst liest sich ein
    # dünn besetztes Diagramm als "wenig Auswahl" statt als "wenig Bewertungen".
    missing = len(rows) - len(points)
    fuzzy = sum(1 for p in points if not p[4])
    note = "Achse nur Vivino (1–5)."
    if fuzzy:
        note += f" Hohle Punkte ({fuzzy}) sitzen auf einem unbestätigten Namensabgleich."
    if missing > 0:
        note += (f" {missing} von {len(rows)} Weinen ohne Vivino-Note — Gründe je "
                 f"Zeile in results.csv.")
    ax.text(
        0.01, 0.945, note,
        transform=ax.transAxes, fontsize=7, color="#5a5a5a", va="top",
    )

    fig.tight_layout()
    fig.savefig(p)
    plt.close(fig)
    return p

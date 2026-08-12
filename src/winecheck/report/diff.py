"""diff.md — Änderungen gegenüber dem letzten Lauf.

Bei wöchentlichem Betrieb ist das der Teil, der tatsächlich gelesen wird. Vier
Abschnitte:

1. neue Aktionen
2. ausgelaufene Aktionen
3. Preisänderungen
4. **neu aufgetauchte Vivino-Bewertungen** für Weine, die vorher keine hatten

Punkt 4 ist der Grund, warum Nicht-Treffer nur 30 Tage gecacht werden: der Eintrag
verfällt, wird neu geprüft, und wenn dann eine Note da ist, fällt es hier auf.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..names import land as _land
from ..models import VIVINO_LABELS, VivinoStatus, WineRow
from .formatting import ch, chf, datetime_ch

#: Preisänderungen darunter sind Rundungsrauschen.
MIN_PRICE_DELTA = 0.05


def snapshot(rows: list[WineRow]) -> list[dict[str, Any]]:
    """Zustand für den Vergleich beim nächsten Lauf."""
    out = []
    for r in rows:
        out.append({
            "dedup_key": r.dedup_key,
            "name": r.name,
            "vintage": r.vintage,
            "best_price": r.best_price,
            "retailers": sorted({p.retailer for p in r.prices}),
            "prices": {
                p.retailer: p.price_per_bottle_incl_vat
                for p in r.prices
                if p.price_per_bottle_incl_vat is not None
            },
            "vivino_status": r.vivino.status.value if r.vivino else "",
            "vivino_rating": r.vivino.rating if r.vivino else None,
            "market_price": r.market_price,
            "bargain_percent": r.bargain_percent,
            "vivino_url": r.vivino.url if r.vivino else "",
            "vivino_rating_count": r.vivino.rating_count if r.vivino else None,
            # Der Match-Grad muss mit, sonst kann die Webseite einen fuzzy-Treffer
            # nicht von einem exakten unterscheiden und stellt beide gleich dar.
            "vivino_match_confidence": (r.vivino.match_confidence if r.vivino else ""),
            "vivino_matched_name": (r.vivino.matched_name if r.vivino else ""),
            "falstaff_points": r.falstaff.value if r.falstaff else None,
            # Für die Webseite: Sorte, Trinkreife, Kaufquelle. Ältere Läufe haben
            # diese Felder nicht — der Seitenbau muss ohne sie auskommen.
            "style": r.style,
            "style_label": r.style_label,
            # Stil-Typ: die Machart. Ordinale Achse von fruchtsuess nach straff_herb,
            # siehe winecheck.stiltyp. Die Signale fahren mit, weil die Seite keinen
            # Typ ohne Begruendung anzeigen darf.
            "typ": r.stil.typ,
            "typ_label": r.stil.label,
            "typ_stufe": r.stil.stufe,
            "typ_signale": r.stil.signale,
            "maturity": r.maturity.code if r.maturity else "",
            "maturity_short": r.maturity.short if r.maturity else "",
            "maturity_region": r.maturity.region_label if r.maturity else "",
            # Herkunftsland fuer den Filter. Zuerst Vivino: es nennt das Land in
            # derselben Antwort, in der auch die Note steht, und kennt es fuer jeden
            # Wein, den es ueberhaupt fuehrt. Aus dem Namen liess es sich nur bei 585
            # von 1564 Weinen lesen. Danach der Name, danach die Vinum-Region; ohne
            # alle drei bleibt es leer statt geraten.
            "country": r.herkunft or _land(r.name, r.maturity.region_label if r.maturity else ""),
            # Vivinos Trinkfenster für genau diesen Wein und Jahrgang, und ob es der
            # Vinum-Tabelle widerspricht. Beide Quellen behalten ihre Stimme.
            "maturity_window": r.maturity.fenster if r.maturity else "",
            "maturity_conflict": r.maturity.widerspruch if r.maturity else "",
            "vintage_quality": (r.maturity.quality or "") if r.maturity else "",
            "cheapest_retailer": r.cheapest_retailer,
            "urls": {p.retailer: p.url for p in r.prices if p.url},
            "value_score": r.value_score,
            "wert_score": r.wert_score,
            "price_band": r.price_band,
            "rank_source": r.rank_source,
        })
    return out


def write_diff(
    rows: list[WineRow],
    previous: list[dict[str, Any]],
    path: Path | str,
    *,
    source_reports: list | None = None,
) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    current = {r.dedup_key: r for r in rows}
    prev = {d["dedup_key"]: d for d in previous or []}

    new_keys = [k for k in current if k not in prev]
    gone_keys = [k for k in prev if k not in current]
    common = [k for k in current if k in prev]

    lines: list[str] = [
        "# Änderungen seit dem letzten Lauf",
        "",
        f"Stand {datetime_ch()}",
        "",
    ]

    if not previous:
        lines += [
            "Erster Lauf — es gibt noch keinen Vergleichsstand. Ab dem nächsten Lauf "
            "stehen hier neue und ausgelaufene Aktionen, Preisänderungen und neu "
            "aufgetauchte Vivino-Bewertungen.",
            "",
        ]

    if source_reports:
        problems = [r for r in source_reports if r.status not in ("ok",)]
        if problems:
            lines += ["## Quellen mit Problemen", ""]
            for rep in problems:
                lines.append(f"- **{ch(rep.retailer)}** — `{rep.status}`: {ch(rep.message[:220])}")
            lines.append("")

    # -- 1. Neue Aktionen -------------------------------------------------
    lines += [f"## Neue Aktionen ({len(new_keys)})", ""]
    if new_keys:
        # Dieselbe Rangfolge wie im PDF. Weine ohne rankbare Zahl kommen zuletzt, nicht
        # in die Mitte: -1e9, weil die Skala um null liegt und eine 0 der Wert eines
        # durchschnittlichen Weins ist, nicht die Abwesenheit eines Werts.
        for key in sorted(
            new_keys,
            key=lambda k: -(current[k].wert_score if current[k].wert_rankable() else -1e9),
        ):
            row = current[key]
            lines.append(f"- {_describe(row)}")
    else:
        lines.append("_keine_")
    lines.append("")

    # -- 2. Ausgelaufen ---------------------------------------------------
    lines += [f"## Ausgelaufene Aktionen ({len(gone_keys)})", ""]
    if gone_keys:
        for key in gone_keys:
            d = prev[key]
            price = chf(d.get("best_price"))
            retailers = ", ".join(d.get("retailers") or [])
            lines.append(
                f"- {_label(d.get('name') or '', d.get('vintage'))}"
                + (f" — war {price}" if price else "")
                + (f" bei {ch(retailers)}" if retailers else "")
            )
    else:
        lines.append("_keine_")
    lines.append("")

    # -- 3. Preisänderungen ----------------------------------------------
    changes: list[tuple[float, str]] = []
    for key in common:
        row, old = current[key], prev[key]
        new_price, old_price = row.best_price, old.get("best_price")
        if new_price is None or old_price is None:
            continue
        delta = round(new_price - old_price, 2)
        if abs(delta) < MIN_PRICE_DELTA:
            continue
        arrow = "▼" if delta < 0 else "▲"
        pct = (delta / old_price * 100) if old_price else 0
        changes.append((
            delta,
            f"- {arrow} {_label(row.name, row.vintage)}"
            + f" — {chf(old_price)} → **{chf(new_price)}** ({pct:+.0f} %)"
            + f", günstigster Händler {ch(row.cheapest_retailer)}",
        ))
    lines += [f"## Preisänderungen ({len(changes)})", ""]
    if changes:
        for _delta, text in sorted(changes, key=lambda t: t[0]):
            lines.append(text)
    else:
        lines.append("_keine_")
    lines.append("")

    # -- 4. Neu aufgetauchte Vivino-Bewertungen ---------------------------
    appeared: list[str] = []
    for key in common:
        row, old = current[key], prev[key]
        if row.vivino is None or row.vivino.rating is None:
            continue
        if old.get("vivino_rating") is not None:
            continue
        old_status = old.get("vivino_status") or "unbekannt"
        appeared.append(
            f"- {_label(row.name, row.vintage)}"
            + f" — vorher `{old_status}`, jetzt **{row.vivino.rating:.1f}/5**"
            + (f" aus {row.vivino.rating_count} Bewertungen" if row.vivino.rating_count else "")
            + f" · [Vivino]({row.vivino.url})"
        )
    lines += [f"## Neu aufgetauchte Vivino-Bewertungen ({len(appeared)})", ""]
    if appeared:
        lines += appeared
    else:
        lines.append("_keine — Nicht-Treffer werden 30 Tage gecacht und danach neu geprüft_")
    lines.append("")

    # -- Bonus: Status-Wechsel bei Vivino ohne Note -----------------------
    status_changes: list[str] = []
    for key in common:
        row, old = current[key], prev[key]
        if row.vivino is None:
            continue
        new_status = row.vivino.status.value
        old_status = old.get("vivino_status") or ""
        if old_status and new_status != old_status and row.vivino.rating is None:
            status_changes.append(
                f"- {ch(row.name)} — Vivino `{old_status}` → `{new_status}` "
                f"({ch(VIVINO_LABELS.get(row.vivino.status, ''))}) · [öffnen]({row.vivino.url})"
            )
    if status_changes:
        lines += [f"## Vivino-Statuswechsel ohne Note ({len(status_changes)})", ""]
        lines += status_changes
        lines.append("")

    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _label(name: str, vintage: int | None) -> str:
    """Name mit Jahrgang — aber nur, wenn er nicht schon drinsteht. Mövenpick führt
    den Jahrgang mitten im Namen ("Valais AOC 2023 Cuvée de l'Orpailleur")."""
    text = ch(name or "")
    if vintage and str(vintage) not in text:
        text = f"{text} {vintage}"
    return text


def _describe(row: WineRow) -> str:
    text = _label(row.name, row.vintage)
    price = chf(row.best_price)
    if price:
        text += f" — **{price}**/75cl"
    if row.cheapest_retailer:
        text += f" bei {ch(row.cheapest_retailer)}"
    if row.retailer_count > 1:
        text += f" (bei {row.retailer_count} Händlern)"
    if row.falstaff and row.falstaff.value is not None:
        text += f", Falstaff {row.falstaff.value:.0f}"
    if row.vivino:
        if row.vivino.rating is not None:
            text += f", Vivino {row.vivino.rating:.1f}/5"
        else:
            text += f", Vivino: {ch(VIVINO_LABELS.get(row.vivino.status, ''))}"
        text += f" ([Link]({row.vivino.url}))"
    pct = row.bargain_percent
    if pct is not None and pct > 0:
        text += f" · **{pct:.0f} % unter Marktpreis**"
    if row.wert_rankable():
        text += f" · P/L {row.wert_score:+.2f}"
    return text

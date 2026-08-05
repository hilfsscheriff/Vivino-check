"""report.pdf — Ranglisten, Vivino als eigene verlinkte Spalte, Legende.

Die Vivino-Spalte ist nie leer. Steht keine Note zur Verfügung, steht dort der
Status-Text ("nur 4 Bewertungen", "kein Eintrag — Suche öffnen") und der ist verlinkt:
auf die Weinseite, wenn es eine gibt, sonst auf die Vivino-Suche mit der verwendeten
Query. Kein leeres Feld, kein Gedankenstrich.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..models import VIVINO_LABELS, PriceConfidence, VivinoStatus, WineRow
from ..prices import PRICE_BANDS
from .formatting import ch, chf, datetime_ch, rating_text, truncate

TOP_N = 10

#: Wie viele Weine je Preisklasse in der Preis-Leistungs-Rangliste stehen.
PER_BAND = 4

_BRAND = colors.HexColor("#6b1030")
_GREY = colors.HexColor("#5a5a5a")
_LIGHT = colors.HexColor("#f4f1f2")
_LINK = colors.HexColor("#1a4f8a")


def _styles():
    ss = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle("h1", parent=ss["Heading1"], fontSize=17, textColor=_BRAND,
                             spaceAfter=2 * mm),
        "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12, textColor=_BRAND,
                             spaceBefore=5 * mm, spaceAfter=2 * mm),
        "body": ParagraphStyle("body", parent=ss["BodyText"], fontSize=8.5, leading=11),
        "small": ParagraphStyle("small", parent=ss["BodyText"], fontSize=7.5, leading=9.5,
                                textColor=_GREY),
        "cell": ParagraphStyle("cell", parent=ss["BodyText"], fontSize=7.5, leading=9.5,
                               alignment=TA_LEFT),
        "cell_link": ParagraphStyle("cell_link", parent=ss["BodyText"], fontSize=7.5,
                                    leading=9.5, textColor=_LINK),
        "band": ParagraphStyle("band", parent=ss["Heading3"], fontSize=9.5,
                               textColor=_GREY, spaceBefore=3.5 * mm, spaceAfter=1.5 * mm),
    }


def _vivino_cell(row: WineRow, style) -> Paragraph:
    """Die Pflichtspalte. Immer gefüllt, immer verlinkt."""
    v = row.vivino
    if v is None:
        return Paragraph(ch("nicht abgefragt"), style)
    if v.rating is not None:
        label = rating_text(v.rating, 5.0, v.rating_count)
        if v.status is not VivinoStatus.EXACT:
            label += f" · {VIVINO_LABELS[v.status]}"
    else:
        label = VIVINO_LABELS.get(v.status, v.status.value)
        if v.status is VivinoStatus.TOO_FEW_RATINGS and v.rating_count:
            label = f"nur {v.rating_count} Bewertungen"
    text = f'<a href="{_esc(v.url)}">{ch(label)}</a>'
    if v.status is VivinoStatus.AMBIGUOUS and v.candidates:
        extras = " ".join(
            f'<br/><a href="{_esc(c.url)}">{ch(truncate(c.name, 34))}</a>'
            for c in v.candidates[:3]
        )
        text += extras
    return Paragraph(text, style)


def _falstaff_cell(row: WineRow, style) -> Paragraph:
    f = row.falstaff
    if f is None:
        return Paragraph(ch("nicht abgefragt"), style)
    if f.value is not None:
        label = rating_text(f.value, f.scale_max)
        if f.confidence.value not in ("exact", "wine_level"):
            label += f" ({f.confidence.value})"
    else:
        label = {"blocked": "blockiert", "no_entry": "kein Eintrag",
                 "ambiguous": "mehrere Treffer",
                 "rating_not_readable": "Note nicht lesbar"}.get(f.status, f.status or "keine Note")
    if f.url:
        return Paragraph(f'<a href="{_esc(f.url)}">{ch(label)}</a>', style)
    return Paragraph(ch(label), style)


def _price_cell(row: WineRow, style) -> Paragraph:
    """Normalisierter Preis, Rohwert als Klammerzusatz — damit am Regal vergleichbar."""
    best = row.best_price
    if best is None:
        return Paragraph(ch("kein verlässlicher Preis"), style)
    text = chf(best)
    cheapest = next(
        (p for p in row.prices if p.price_per_bottle_incl_vat == best), None
    )
    if cheapest and cheapest.price_raw is not None and cheapest.price_raw != best:
        text += f"<br/><font size=6.5>({chf(cheapest.price_raw)} {ch(cheapest.price_raw_basis)})</font>"
    return Paragraph(text, style)


def _retailer_cell(row: WineRow, style) -> Paragraph:
    best = row.best_price
    parts = []
    for p in sorted(row.prices, key=lambda x: x.price_per_bottle_incl_vat or 9e9):
        if p.price_per_bottle_incl_vat is None:
            continue
        mark = "<b>" if p.price_per_bottle_incl_vat == best else ""
        end = "</b>" if mark else ""
        flag = " !" if p.discount_plausibility.value == "questionable" else ""
        parts.append(f"{mark}{ch(p.retailer)} {chf(p.price_per_bottle_incl_vat, prefix='')}{flag}{end}")
    return Paragraph("<br/>".join(parts) or ch("—"), style)


def _table(data: list[list], widths: list[float]) -> Table:
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), _BRAND),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 7.5),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _LIGHT]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d8d2d4")),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ])
    )
    return t


def _ranking_table(rows: list[WineRow], st: dict) -> Table:
    header = ["Wein", "Jg.", "Preis/75cl", "Günstigster Händler", "Falstaff", "Vivino", "Konfidenz"]
    data = [header]
    for row in rows:
        conf = row.vivino.match_confidence if row.vivino else ""
        if row.falstaff and row.falstaff.value is not None:
            conf = row.falstaff.confidence.value
        low = any(p.price_confidence is PriceConfidence.LOW for p in row.prices)
        data.append([
            Paragraph(ch(truncate(row.name, 60)), st["cell"]),
            Paragraph(str(row.vintage or ""), st["cell"]),
            _price_cell(row, st["cell"]),
            _retailer_cell(row, st["cell"]),
            _falstaff_cell(row, st["cell_link"]),
            _vivino_cell(row, st["cell_link"]),
            Paragraph(ch(conf or "—") + (" · Preis unsicher" if low else ""), st["cell"]),
        ])
    return _table(data, [72 * mm, 10 * mm, 25 * mm, 34 * mm, 24 * mm, 42 * mm, 24 * mm])


def _unrated_table(rows: list[WineRow], st: dict) -> Table:
    header = ["Wein", "Jg.", "Preis/75cl", "Händler", "Warum keine Bewertung", "Vivino-Link"]
    data = [header]
    for row in rows:
        data.append([
            Paragraph(ch(truncate(row.name, 58)), st["cell"]),
            Paragraph(str(row.vintage or ""), st["cell"]),
            _price_cell(row, st["cell"]),
            Paragraph(ch(", ".join(sorted({p.retailer for p in row.prices}))), st["cell"]),
            Paragraph(ch(truncate(row.no_rating_reason(), 150)), st["cell"]),
            _vivino_cell(row, st["cell_link"]),
        ])
    return _table(data, [66 * mm, 10 * mm, 24 * mm, 24 * mm, 76 * mm, 31 * mm])


def _legend(st: dict) -> list:
    out = [Paragraph(ch("Legende Vivino-Status"), st["h2"])]
    rows = [["Status", "Bedeutung"]]
    explain = {
        VivinoStatus.EXACT: "Bewertung für den exakten Jahrgang.",
        VivinoStatus.WINE_LEVEL: "Weinseite hat eine Bewertung, der Jahrgang weicht ab.",
        VivinoStatus.WINERY_LEVEL: "Nur Produzenten-Durchschnitt — schwach, Wein selbst unbewertet.",
        VivinoStatus.TOO_FEW_RATINGS: "Seite existiert, Vivino zeigt wegen zu weniger Bewertungen keine Note.",
        VivinoStatus.RATING_NOT_READABLE: "Seite existiert, die Note wird per JavaScript nachgeladen. Link öffnen.",
        VivinoStatus.AMBIGUOUS: "Mehrere Kandidaten gleich gut — es wird keiner gewählt, bis zu drei sind verlinkt.",
        VivinoStatus.NO_ENTRY: "Kein passender Eintrag. Der Link führt auf die Vivino-Suche mit der verwendeten Query.",
        VivinoStatus.BLOCKED: "Cloudflare oder Rate-Limit. Retry-Zeitpunkt steht in results.csv.",
    }
    for status, text in explain.items():
        rows.append([
            Paragraph(f"<b>{status.value}</b><br/>{ch(VIVINO_LABELS[status])}", st["cell"]),
            Paragraph(ch(text), st["cell"]),
        ])
    out.append(_table(rows, [45 * mm, 186 * mm]))

    out.append(Paragraph(ch("Legende Match-Konfidenz"), st["h2"]))
    conf = [["Stufe", "Bedeutung"]]
    for stufe, text in {
        "exact": "Name und Jahrgang bestätigt.",
        "wine_level": "Wein bestätigt, kein jahrgangsspezifischer Wert.",
        "fuzzy": "Ähnlich genug, aber nicht sicher — die gefundene Quell-Bezeichnung steht in results.csv, bitte prüfen.",
        "winery_level": "Nur der Produzent stimmt.",
    }.items():
        conf.append([Paragraph(f"<b>{stufe}</b>", st["cell"]), Paragraph(ch(text), st["cell"])])
    out.append(_table(conf, [45 * mm, 186 * mm]))
    return out


def write_pdf(
    rows: list[WineRow],
    path: Path | str,
    *,
    source_reports: list | None = None,
    uncertain: list[str] | None = None,
) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    st = _styles()
    doc = SimpleDocTemplate(
        str(p),
        pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
        title="wine-check Report",
        author="wine-check",
    )

    rated = [r for r in rows if r.has_any_rating]
    unrated = [r for r in rows if not r.has_any_rating]

    best_rating = sorted(
        rated, key=lambda r: -(r.ranking_rating()[0] or 0)
    )[:TOP_N]
    best_value = sorted(
        [r for r in rated if r.value_score is not None],
        key=lambda r: -(r.value_score or 0),
    )[:TOP_N]

    story: list = [
        Paragraph(ch("wine-check — Aktionen der Schweizer Weinhändler"), st["h1"]),
        Paragraph(
            ch(
                f"Stand {datetime_ch()} · {len(rows)} Weine · {len(rated)} mit Fremdbewertung · "
                f"{len(unrated)} ohne · Preise normalisiert auf CHF pro 75 cl inkl. MwSt (8.1 %)"
            ),
            st["small"],
        ),
        Spacer(1, 3 * mm),
    ]

    if source_reports:
        story.append(Paragraph(ch("Quellen in diesem Lauf"), st["h2"]))
        data = [["Händler", "Status", "Positionen", "Bemerkung"]]
        for rep in source_reports:
            data.append([
                Paragraph(ch(rep.retailer), st["cell"]),
                Paragraph(ch(rep.status), st["cell"]),
                Paragraph(str(rep.count), st["cell"]),
                Paragraph(ch(truncate(rep.message, 190)), st["cell"]),
            ])
        story.append(_table(data, [28 * mm, 20 * mm, 20 * mm, 163 * mm]))

    if best_rating:
        story.append(Paragraph(ch(f"Beste Bewertung (Top {len(best_rating)})"), st["h2"]))
        story.append(
            Paragraph(
                ch("Sortiert nach normalisierter Bewertung. Die Quelle steht je Zeile — "
                   "Falstaff und Vivino werden nie im selben Sortierschlüssel vermischt."),
                st["small"],
            )
        )
        story.append(_ranking_table(best_rating, st))

    if best_value:
        story.append(Paragraph(ch("Bestes Preis-Leistungs-Verhältnis"), st["h2"]))
        story.append(
            Paragraph(
                ch("Bewertung relativ zum Aktionspreis, verglichen **innerhalb** der "
                   "Preisklasse — und darum auch klassenweise ausgegeben. Ein globaler "
                   "Rang wäre irreführend: er würde klassenrelative Werte über Klassen "
                   "hinweg vergleichen und damit systematisch die teuren Weine nach oben "
                   "spülen. Die günstigen Klassen stehen zuerst. Gerechnet wird immer auf "
                   "den Aktionspreis, nie auf den Rabatt; ein ! markiert einen "
                   "fragwürdigen Referenzpreis bei einer Eigenmarke."),
                st["small"],
            )
        )
        for label, _lo, _hi in PRICE_BANDS:
            members = [r for r in best_value if r.price_band == label]
            if not members:
                continue
            top = sorted(members, key=lambda r: -(r.value_score or 0))[:PER_BAND]
            story.append(
                KeepTogether([
                    Paragraph(
                        ch(f"Preisklasse {label} CHF — {len(members)} Weine, "
                           f"beste {len(top)}"),
                        st["band"],
                    ),
                    _ranking_table(top, st),
                ])
            )

    cross = [r for r in rows if r.retailer_count > 1]
    if cross:
        story.append(Paragraph(ch(f"Bei mehreren Händlern in Aktion ({len(cross)})"), st["h2"]))
        story.append(
            Paragraph(ch("Hier zeigt sich, ob sich der Weg zum Abholgrosshandel lohnt."), st["small"])
        )
        story.append(_ranking_table(cross[:TOP_N], st))

    if unrated:
        story.append(PageBreak())
        story.append(Paragraph(ch(f"Ohne Fremdbewertung ({len(unrated)})"), st["h2"]))
        story.append(
            Paragraph(
                ch("Ein ehrliches „keine Fremdbewertung verfügbar\" ist wertvoller als eine "
                   "plausible Zahl. Jede Zeile nennt den Grund und behält den Vivino-Link."),
                st["small"],
            )
        )
        story.append(_unrated_table(unrated, st))

    if uncertain:
        story.append(Paragraph(ch(f"Unsichere Prospekt-Positionen ({len(uncertain)})"), st["h2"]))
        story.append(
            Paragraph(
                ch("Aus dem Prospekt-PDF erkannt, aber ohne verlässliche Bezugsgrösse oder "
                   "ohne Preis — zur manuellen Ergänzung, absichtlich nicht im Ranking."),
                st["small"],
            )
        )
        for item in uncertain[:40]:
            story.append(Paragraph("• " + ch(truncate(item, 200)), st["small"]))

    story.append(PageBreak())
    story.extend(_legend(st))
    story.append(Spacer(1, 4 * mm))
    story.append(
        Paragraph(
            ch("Preis-Leistung wird immer auf den Aktionspreis gerechnet. Referenzpreise bei "
               "Eigenmarken sind teils konstruiert; Rabatte über 45 % auf Eigenmarken sind in "
               "results.csv als discount_plausibility = questionable markiert und hier mit ! "
               "gekennzeichnet."),
            st["small"],
        )
    )

    doc.build(story)
    return p


def _esc(url: str) -> str:
    return (url or "").replace("&", "&amp;").replace('"', "%22").replace("<", "%3C")

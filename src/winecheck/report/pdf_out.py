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

from ..models import (
    VIVINO_LABELS,
    DiscountPlausibility,
    PriceConfidence,
    VivinoStatus,
    WineRow,
)
from ..prices import MARKTPLATZ_QUELLEN, PRICE_BANDS
from .formatting import ch, chf, datetime_ch, rating_text, truncate

TOP_N = 10

#: Wie viele Weine in der Preis-Leistungs-Rangliste des Schweizer Handels stehen.
#:
#: Eine Liste über alle Preisklassen, nicht fünf klassenweise. Möglich wurde das erst
#: durch den Wechsel des Sortierschlüssels: die alte Kennzahl war eine Rangposition
#: *innerhalb* der Klasse und über Klassen hinweg schlicht nicht vergleichbar — global
#: sortiert besetzten die teuren Weine 19 der ersten 25 Plätze, und die Klasse unter
#: CHF 10 fiel ganz heraus. In :attr:`WineRow.wert_score_welt` ist der Preis
#: herausgerechnet.
#:
#: Die Klumpung verschwindet damit nicht ganz, sie kippt: die Spitze füllt die Klassen mit
#: 14/4/2/0/0, weil der gesetzte Preisfaktor über dem gemessenen liegt und günstige Weine
#: darum begünstigt. Das ist die gewollte Haltung der Kennzahl („gut und günstig"), aber
#: sie lässt die teuren Klassen leer — darum stehen unter dieser Liste weiterhin die
#: besten je Preisklasse. Beide Ansichten, nicht eine.
#:
#: 20 statt der vorherigen fünf mal vier: dieselbe Menge Weine, eine Reihenfolge.
TOP_VALUE = 20

#: Wie viele Marktplatzweine ihre eigene Liste bekommen.
#:
#: Kürzer als die des Schweizer Handels, obwohl der Marktplatz mit 640 von 924 rankbaren
#: Weinen die grössere Hälfte stellt. Das ist Absicht und folgt dem Titel des Berichts:
#: es geht um die Aktionen der Schweizer Weinhändler, und was aus dem Ausland geliefert
#: wird, ist die Beilage. Vollständig steht der Marktplatz trotzdem hinten in der Liste
#: aller bewerteten Weine.
TOP_MARKTPLATZ = 10

#: Wie viele Weine je Preisklasse unter der Liste des Schweizer Handels stehen.
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
    # Die Verpflichtung gehört zum Preis. Ohne sie stand CHF 45.47 da und gemeint war
    # eine Sechserkiste zu CHF 272.82 — der Preis je Flasche stimmt, kaufen kann man ihn
    # so nicht. 7 Prozent der Marktplatzangebote sind Kisten.
    if cheapest and (cheapest.units or 1) > 1:
        text += (f"<br/><font size=6.5><b>nur {cheapest.units}er-Gebinde</b>, "
                 f"zusammen {chf(cheapest.gesamtpreis)}</font>")
    return Paragraph(text, style)


def _retailer_cell(row: WineRow, style, info: dict[str, dict] | None = None) -> Paragraph:
    """Wo der Wein zu kaufen ist.

    Lesbarer Händlername statt Schlüssel, verlinkt auf die Produktseite, und der
    Verkaufskanal darunter — bei Prodega ist die Kundenkarte nötig, das ändert die
    Antwort auf "lohnt sich das".
    """
    best = row.best_price
    info = info or {}
    parts = []
    for p in sorted(row.prices, key=lambda x: x.price_per_bottle_incl_vat or 9e9):
        if p.price_per_bottle_incl_vat is None:
            continue
        meta = info.get(p.retailer) or {}
        label = ch(meta.get("name") or p.retailer)
        price = chf(p.price_per_bottle_incl_vat, prefix="")
        flag = " !" if p.discount_plausibility.value == "questionable" else ""
        text = f"{label} {price}{flag}"
        if p.url:
            text = f'<a href="{_esc(p.url)}">{text}</a>'
        if p.price_per_bottle_incl_vat == best:
            text = f"<b>{text}</b>"
        channel = ch(meta.get("channel") or "")
        if channel:
            text += f'<br/><font size=6.2 color="#5a5a5a">{channel}</font>'
        parts.append(text)
    return Paragraph("<br/>".join(parts) or ch("kein Händler"), style)


#: Farben der Trinkreife-Stufen. Grün heisst jetzt geniessen, blau noch warten,
#: orange bald austrinken, grau vorbei.
_MATURITY_COLOURS = {
    "*": "#2e7d32", "k": "#00838f", "m": "#ef6c00", "g": "#1a4f8a", "-": "#8a8a8a",
}


def _maturity_cell(row: WineRow, style) -> Paragraph:
    """Trinkreife laut Vinum-Jahrgangstabelle, plus Jahrgangsqualität."""
    m = row.maturity
    if m is None:
        return Paragraph('<font size=6.2 color="#8a8a8a">keine Angabe</font>', style)
    colour = _MATURITY_COLOURS.get(m.code, "#5a5a5a")
    text = f'<b><font color="{colour}">{ch(m.short)}</font></b>'
    if m.quality:
        text += f'<br/><font size=6.2 color="#5a5a5a">Jg. {ch(m.quality)}</font>'
    return Paragraph(text, style)


def _market_cell(row: WineRow, style) -> Paragraph:
    """Vivino-Marktpreis und die Ersparnis darauf.

    Der Marktpreis stammt bewusst nicht vom eigenen Händler — sonst verglichen wir
    einen Preis mit sich selbst. Liegt kein unabhängiger Preis vor, steht hier die
    Begründung statt einer 0.
    """
    v = row.vivino
    if v is None or v.market_price is None:
        note = (v.market_price_note if v else "") or "kein Marktpreis"
        return Paragraph(f'<font size=6.5>{ch(truncate(note, 90))}</font>', style)

    pct = row.bargain_percent
    text = chf(v.market_price)
    if v.market_price_shop:
        shop = ch(v.market_price_shop)
        text += f'<br/><font size=6.2 color="#5a5a5a">{shop}</font>'
    if pct is not None:
        questionable = row.bargain_plausibility is DiscountPlausibility.QUESTIONABLE
        colour = "#8a6d1f" if questionable else ("#2e7d32" if pct > 0 else "#c62828")
        sign = "−" if pct > 0 else "+"
        text = (
            f'<b><font color="{colour}">{sign}{abs(pct):.0f} %{" !" if questionable else ""}</font></b><br/>'
            f'<font size=6.5>gegen {text}</font>'
        )
    if v.market_price_url:
        text = f'<a href="{_esc(v.market_price_url)}">{text}</a>'
    return Paragraph(text, style)


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


#: Was in der Spalte P/L steht — im Bericht selbst, weil das Papier keinen Mauszeiger hat.
#:
#: Die Übersetzung in Prozent ist der Kern: ohne sie ist „+0.10" eine Rangnummer mit
#: Komma. Auf der Webseite steht sie unter der Tabelle; hier musste sie nachgetragen
#: werden.
#:
#: „Notenpunkte" stand hier zuerst und war unwahr. Der Rest wird auf der *wirksamen* Note
#: gerechnet — Seltenheit eingemischt — und danach mit der Dämpfung nach Bewertungszahl
#: multipliziert. Gemessen: wirksam(4.6) liegt 0.22 über 4.6, wirksam(4.1) 0.04 darunter,
#: und 156 rankbare Weine tragen unter 60 Bewertungen und damit eine Dämpfung bis 0.33.
#: Zwei Weine mit gleicher Note und gleichem Preis können darum verschieden dastehen.
_PL_ERKLAERUNG = (
    "Die Spalte P/L sagt, wie viel besser ein Wein bewertet ist, als sein Preis "
    "üblicherweise kauft — verglichen mit Weinen derselben <b>Machart</b>, nicht bloss "
    "derselben Preisklasse. Null heisst „so gut, wie dieses Geld üblicherweise kauft\", "
    "nicht „mittelmässig\". Als Preis gelesen: <b>0.10 entspricht rund 40 % "
    "Preisunterschied</b> bei gleicher Note, 0.25 rund 130 %. Dieser Umrechnungsfaktor "
    "ist gesetzt und nicht gemessen — gemessen wäre er halb so gross, was getreu "
    "beschreibt, wie der Markt bepreist, aber als Kaufempfehlung nichts taugt. "
    "Der Preis ist in der Zahl herausgerechnet, darum lassen sich die Preisklassen "
    "vergleichen: eine 4.4 für CHF 24 kann eine 4.1 für CHF 7 schlagen und umgekehrt. "
    "Wenig bewertete Weine werden gedämpft, damit ein Glückstreffer aus zwölf Stimmen die "
    "Liste nicht anführt — dieselbe Note zum gleichen Preis kann darum verschieden "
    "dastehen. <b>Abstände unter etwa 0.03 sind kein Rangunterschied</b>, sondern die "
    "Unsicherheit des Modells; die Reihenfolge innerhalb einer solchen Gruppe bedeutet "
    "nichts. Gerechnet wird immer auf den Aktionspreis, nie auf den Rabatt; ein ! "
    "markiert einen fragwürdigen Referenzpreis bei einer Eigenmarke."
)


def _schweizer_handel(row: WineRow) -> bool:
    """Ob der Wein bei einem Schweizer Händler zu kaufen ist.

    Ein Wein in beiden Welten zählt zum Schweizer Handel — dort ist er zu kaufen, und die
    Lieferung aus dem Ausland ist dann nur eine zweite Möglichkeit.
    """
    return any(p.retailer not in MARKTPLATZ_QUELLEN for p in row.prices)


def _wert_text(row: WineRow) -> str:
    """Die Preis-Leistungs-Zahl mit Vorzeichen, oder ein Strich.

    Das Vorzeichen ist die Aussage: null heisst „so gut, wie dieser Preis üblicherweise
    kauft". Ohne Vorzeichen liest sich eine 0.31 wie eine Note.

    Ein Strich steht dort, wo die Zahl bewusst fehlt — kein Vivino-Treffer, den man
    ranken darf, oder ein unsicherer Preis. Eine 0 hinzuschreiben wäre eine Behauptung.

    Immer :attr:`WineRow.wert_score_welt`, nie die Zahl über beide Warenwelten. Damit gilt
    im ganzen Bericht eine Regel — P/L vergleicht einen Wein mit seiner eigenen Welt —
    und der Leser muss sich nicht je Abschnitt fragen, gegen was gerechnet wurde. Die Zahl
    über beide Welten steht in ``results.csv`` und ist die, welche die Webseite in der
    Standardansicht zeigt.
    """
    if not row.wert_rankable() or row.wert_score_welt is None:
        return "—"
    return f"{row.wert_score_welt:+.2f}"


def _ranking_table(
    rows: list[WineRow],
    st: dict,
    *,
    info: dict[str, dict] | None = None,
    show_falstaff: bool = False,
    show_value: bool = False,
) -> Table:
    """Die Rangliste.

    Die Falstaff-Spalte erscheint nur, wenn Falstaff überhaupt Werte geliefert hat —
    solange die Quelle blockiert ist, wäre es eine Spalte voll "nicht abgefragt", und
    die Breite fehlt für Kaufquelle und Marktpreis.

    ``show_value`` blendet die Preis-Leistungs-Zahl ein. Wo nach ihr sortiert wird,
    gehört sie hin: eine Liste mit dem Titel „Bestes Preis-Leistungs-Verhältnis", die
    ihr Kriterium nicht zeigt, lässt sich nicht nachprüfen. Auf dem Papier gibt es
    keinen Mauszeiger, mit dem man nachsehen könnte.
    """
    header = ["Wein", "Jg.", "Reife", "Preis/75cl", "Wo kaufen"]
    widths = [50 * mm, 9 * mm, 17 * mm, 22 * mm, 37 * mm]
    if show_value:
        header.append("P/L")
        widths.append(13 * mm)
        widths[0] -= 13 * mm
    if show_falstaff:
        header.append("Falstaff")
        widths.append(20 * mm)
    header += ["Vivino", "Marktpreis", "Konfidenz"]
    widths += [36 * mm, 26 * mm, 18 * mm]

    data = [header]
    for row in rows:
        conf = row.vivino.match_confidence if row.vivino else ""
        if row.falstaff and row.falstaff.value is not None:
            conf = row.falstaff.confidence.value
        low = any(p.price_confidence is PriceConfidence.LOW for p in row.prices)
        cells = [
            Paragraph(ch(truncate(row.name, 48)), st["cell"]),
            Paragraph(str(row.vintage or ""), st["cell"]),
            _maturity_cell(row, st["cell"]),
            _price_cell(row, st["cell"]),
            _retailer_cell(row, st["cell"], info),
        ]
        if show_value:
            cells.append(Paragraph(_wert_text(row), st["cell"]))
        if show_falstaff:
            cells.append(_falstaff_cell(row, st["cell_link"]))
        cells += [
            _vivino_cell(row, st["cell_link"]),
            _market_cell(row, st["cell_link"]),
            Paragraph(ch(conf or "—") + (" · Preis unsicher" if low else ""), st["cell"]),
        ]
        data.append(cells)
    return _table(data, widths)


def _unrated_table(rows: list[WineRow], st: dict, info: dict[str, dict] | None = None) -> Table:
    header = ["Wein", "Jg.", "Reife", "Preis/75cl", "Wo kaufen", "Warum keine Bewertung", "Vivino-Link"]
    data = [header]
    for row in rows:
        data.append([
            Paragraph(ch(truncate(row.name, 52)), st["cell"]),
            Paragraph(str(row.vintage or ""), st["cell"]),
            _maturity_cell(row, st["cell"]),
            _price_cell(row, st["cell"]),
            _retailer_cell(row, st["cell"], info),
            Paragraph(ch(truncate(row.no_rating_reason(), 130)), st["cell"]),
            _vivino_cell(row, st["cell_link"]),
        ])
    return _table(data, [54 * mm, 9 * mm, 17 * mm, 22 * mm, 34 * mm, 58 * mm, 41 * mm])


def _legend(st: dict) -> list:
    # Die P/L-Spalte steht auch in der vollständigen Liste hinter dem Seitenumbruch, wo
    # der erklärende Absatz Seiten entfernt ist. Wer dort zu seiner Preisklasse springt,
    # sieht „+0.31" und „—" ohne jeden Anhalt.
    out = [Paragraph(ch("Legende Preis-Leistung (Spalte P/L)"), st["h2"])]
    out.append(Paragraph(ch(_PL_ERKLAERUNG), st["small"]))
    out.append(
        Paragraph(
            ch("Ein <b>Strich</b> heisst, dass der Wein keine Rangfolge tragen kann: seine "
               "Note stammt von einem Kritiker und nicht von Vivino, die Vivino-Zuordnung "
               "ist über den Namen nur vermutet, oder sie trifft bloss den Produzenten "
               "statt diesen Wein. Der Wein steht trotzdem vollständig im Bericht — eine "
               "0 hinzuschreiben wäre eine Behauptung."),
            st["small"],
        )
    )
    out.append(Spacer(1, 3 * mm))

    out.append(Paragraph(ch("Legende Vivino-Status"), st["h2"]))
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

    out.append(Paragraph(ch("Legende Trinkreife"), st["h2"]))
    out.append(
        Paragraph(
            ch("Quelle: Vinum-Jahrgangstabelle, von Mövenpick als PDF veröffentlicht. "
               "Die Auskunft gilt für Region und Weinart, nicht für die einzelne Flasche. "
               "Wo Region oder Jahrgang nicht eindeutig zuzuordnen waren, steht "
               "„keine Angabe\" — eine falsche Region liefert eine falsche Empfehlung."),
            st["small"],
        )
    )
    reife = [["Stufe", "Bedeutung"]]
    from ..trinkreife import MATURITY, MATURITY_SHORT
    for code, text in MATURITY.items():
        reife.append([
            Paragraph(f'<b><font color="{_MATURITY_COLOURS.get(code, "#5a5a5a")}">'
                      f'{ch(MATURITY_SHORT[code])}</font></b>', st["cell"]),
            Paragraph(ch(text), st["cell"]),
        ])
    out.append(_table(reife, [45 * mm, 186 * mm]))

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
    retailer_info: dict[str, dict] | None = None,
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

    info = retailer_info or {}
    show_falstaff = any(r.falstaff and r.falstaff.value is not None for r in rows)
    rated = [r for r in rows if r.has_any_rating]
    unrated = [r for r in rows if not r.has_any_rating]

    best_rating = sorted(
        rated, key=lambda r: -(r.ranking_rating()[0] or 0)
    )[:TOP_N]
    scored = [r for r in rated if r.wert_rankable()]

    story: list = [
        Paragraph(ch("wine-check — Aktionen der Schweizer Weinhändler"), st["h1"]),
        Paragraph(
            ch(
                f"Stand {datetime_ch()} · {len(rows)} Weine · {len(rated)} mit Fremdbewertung · "
                f"{len(unrated)} ohne · Preise normalisiert auf CHF pro 75 cl inkl. MwSt (8.1 %) · "
                f"die Ranglisten sind Auszüge, die vollständigen Listen stehen hinten"
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
        story.append(_ranking_table(best_rating, st, info=info, show_falstaff=show_falstaff))

    # -- Schnäppchen gegen den Marktpreis ---------------------------------
    # Fragwürdige Schnäppchen nach hinten: sie stehen weiterhin drin, führen die
    # Liste aber nicht an. Sonst gewinnt ein einzelner Preis einer Anlageplattform.
    bargains = sorted(
        [r for r in rows if r.bargain_percent is not None and r.bargain_percent > 0],
        key=lambda r: (
            r.bargain_plausibility is DiscountPlausibility.QUESTIONABLE,
            -(r.bargain_percent or 0),
        ),
    )
    if bargains:
        story.append(Paragraph(ch(f"Grösste Schnäppchen ({len(bargains)} mit Marktpreis)"), st["h2"]))
        story.append(
            Paragraph(
                ch("Aktionspreis gegen den Vivino-Marktpreis, je mehr Prozent darunter, desto "
                   "besser. Der Marktpreis ist ein Händlerpreis von Vivino und stammt "
                   "ausdrücklich <b>nicht</b> vom eigenen Händler — sonst verglichen wir einen "
                   "Preis mit sich selbst. Das ist der belastbarere Vergleich als das „statt X\" "
                   "des Händlers, das bei Eigenmarken teils konstruiert ist. Ist kein "
                   "unabhängiger Preis verfügbar, steht in der Spalte die Begründung statt "
                   "einer 0."),
                st["small"],
            )
        )
        story.append(_ranking_table(bargains[:TOP_N], st, info=info, show_falstaff=show_falstaff))

    if scored:
        # Getrennt nach Warenwelt, und der Schweizer Handel zuerst.
        #
        # Ohne die Trennung besetzte der Vivino-Marktplatz 15 der ersten 20 Plätze und in
        # zwei Preisklassen alle vier. Nicht aus einem Fehler der Rechnung: er trägt 640
        # der 924 rankbaren Weine, weil seine Noten von Vivino selbst kommen und keinen
        # Namensabgleich brauchen, während Händlerweine öfter durch die Eignungsprüfung
        # fallen. Aber ein Heft mit dem Titel „Aktionen der Schweizer Weinhändler", dessen
        # Empfehlungen man in der Schweiz nicht kaufen kann, verfehlt seinen Zweck.
        #
        # Jede Welt wird gegen ihr eigenes Preisniveau gerechnet — der Marktplatz liefert
        # aus dem Ausland — und darum steht in der Spalte wert_score_welt, nicht
        # wert_score. Über beide Welten gelegt machte eine Erwartungskurve den
        # systematischen Preisunterschied zu einer Aussage über die einzelnen Weine.
        story.append(Paragraph(ch("Bestes Preis-Leistungs-Verhältnis"), st["h2"]))
        story.append(Paragraph(ch(_PL_ERKLAERUNG), st["small"]))
        for titel, gruppe, laenge in (
            ("Schweizer Handel", [r for r in scored if _schweizer_handel(r)], TOP_VALUE),
            ("Vivino-Marktplatz — Lieferung aus dem Ausland",
             [r for r in scored if not _schweizer_handel(r)], TOP_MARKTPLATZ),
        ):
            gruppe = [r for r in gruppe if r.wert_score_welt is not None]
            if not gruppe:
                continue
            besten = sorted(gruppe, key=lambda r: -(r.wert_score_welt or 0))[:laenge]
            story.append(Paragraph(ch(f"{titel} — {len(gruppe)} Weine, beste {len(besten)}"),
                                   st["band"]))
            story.append(_ranking_table(
                besten, st, info=info, show_falstaff=show_falstaff, show_value=True
            ))

        # Und dieselbe Frage noch einmal je Preisklasse, für den Schweizer Handel.
        #
        # Die Rangfolge beantwortet „welcher Wein ist sein Geld am meisten wert" — aber
        # niemand kauft so. Wer 60 Franken ausgeben will, hat von vierzehn Empfehlungen
        # unter CHF 10 nichts, und genau das kam heraus: die globale Spitze füllte die
        # Klassen mit 14/4/2/0/0, die beiden teuren Klassen kamen gar nicht vor. Das war
        # derselbe Verlust wie mit der alten Kennzahl, nur am anderen Ende der Skala.
        #
        # Vertretbar ist die Aufteilung erst mit dieser Kennzahl. Eine klassenrelative
        # Zahl klassenweise auszugeben war eine Notlösung — man konnte die Klassen nicht
        # vergleichen. Hier bedeutet +0.30 in jeder Klasse dasselbe, und die Aufteilung
        # ist nur noch eine Ansicht auf dieselbe Zahl.
        ch_scored = [r for r in scored
                     if _schweizer_handel(r) and r.wert_score_welt is not None]
        if ch_scored:
            story.append(Spacer(1, 2 * mm))
            story.append(
                Paragraph(
                    ch("Schweizer Handel nach Budget aufgeteilt — für wen die Preisklasse "
                       "zuerst feststeht. Dieselben Werte wie oben; sie sind über die "
                       "Klassen hinweg vergleichbar."),
                    st["small"],
                )
            )
            for label, _lo, _hi in PRICE_BANDS:
                members = [r for r in ch_scored if r.price_band == label]
                if not members:
                    continue
                besten = sorted(members, key=lambda r: -(r.wert_score_welt or 0))[:PER_BAND]
                story.append(
                    KeepTogether([
                        Paragraph(
                            ch(f"Preisklasse {label} CHF — {len(members)} Weine, "
                               f"beste {len(besten)}"),
                            st["band"],
                        ),
                        _ranking_table(
                            besten, st, info=info, show_falstaff=show_falstaff, show_value=True
                        ),
                    ])
                )

        # Wer nicht in der Liste steht, und warum. Der Satz zählte anfangs nur die Weine
        # mit Kritikernote — 27 von 117 — und behauptete damit eine Vollständigkeit, die
        # er nicht hatte: die 90 Weine mit unbestätigter oder produzentenweiter
        # Vivino-Zuordnung haben gar keine ranking_rating und fielen durch den Filter.
        fehlen = [r for r in rated if not r.wert_rankable()]
        if fehlen:
            kritiker = sum(1 for r in fehlen if r.ranking_rating()[0] is not None)
            story.append(
                Paragraph(
                    ch(f"Nicht in diesen Listen: {len(fehlen)} bewertete Weine. Davon "
                       f"{kritiker} mit einer Kritikernote statt einer Vivino-Note — eine "
                       "Parker-95 und eine Vivino-4.3 liegen auf verschiedenen Skalen, und "
                       "die Rechnung ist auf der Vivino-Skala kalibriert. Die übrigen "
                       f"{len(fehlen) - kritiker} tragen einen Vivino-Treffer, der nicht "
                       "ranken darf: Namenszuordnung unbestätigt oder nur ein "
                       "Produzenten-Durchschnitt. Alle stehen in „Beste Bewertung\" und in "
                       "der vollständigen Liste hinten — nur nicht in einer Rangfolge, die "
                       "sie nicht tragen können."),
                    st["small"],
                )
            )

    cross = [r for r in rows if r.retailer_count > 1]
    if cross:
        story.append(Paragraph(ch(f"Bei mehreren Händlern in Aktion ({len(cross)})"), st["h2"]))
        story.append(
            Paragraph(ch("Hier zeigt sich, ob sich der Weg zum Abholgrosshandel lohnt."), st["small"])
        )
        story.append(_ranking_table(cross[:TOP_N], st, info=info, show_falstaff=show_falstaff))

    # -- Vollständige Liste der bewerteten Weine --------------------------
    # Ohne diesen Abschnitt fällt jeder bewertete Wein aus dem PDF, der in keiner
    # Top-Liste steht — und das war die Mehrheit. Der Châteauneuf-du-Pape von Prodega
    # lag auf Platz 21 von 68 nach Bewertung, 6 von 25 in seiner Preisklasse und 20
    # von 61 bei den Schnäppchen: überall knapp hinter dem Schnitt und damit unsichtbar,
    # obwohl er in results.csv und im Streudiagramm steht.
    if rated:
        story.append(PageBreak())
        story.append(Paragraph(ch(f"Alle bewerteten Weine ({len(rated)})"), st["h2"]))
        story.append(
            Paragraph(
                ch("Die Ranglisten oben sind Auszüge. Hier stehen alle bewerteten Weine "
                   "vollständig — nach Warenwelt, darin nach Preisklasse und darin nach "
                   "Preis-Leistung. Auch dieser Teil ist nach Warenwelt getrennt, weil "
                   "P/L im ganzen Bericht dasselbe bedeuten muss: den Vergleich mit der "
                   "eigenen Welt. Ein Strich heisst, dass der Wein keine Rangfolge tragen "
                   "kann — die Gründe stehen oben."),
                st["small"],
            )
        )

        # Weine ohne Preis-Leistungs-Zahl nach hinten, nicht heraus: sie stehen in der
        # Klasse weiterhin vollständig, führen sie aber nicht an. ``None`` als -1e9 statt
        # als -1 — die neue Skala liegt um null, und -1 wäre ein gültiger, sehr
        # schlechter Wert gewesen. Damit hätte ein Wein ohne Zahl vor einem mit einer
        # schlechten gestanden.
        def _nach_wert(r: WineRow):
            wert = r.wert_score_welt if r.wert_rankable() else None
            return (-(wert if wert is not None else -1e9), r.best_price or 9e9)

        for welt, gruppe in (
            ("Schweizer Handel", [r for r in rated if _schweizer_handel(r)]),
            ("Vivino-Marktplatz", [r for r in rated if not _schweizer_handel(r)]),
        ):
            if not gruppe:
                continue
            story.append(Paragraph(ch(f"{welt} — {len(gruppe)} Weine"), st["h2"]))
            for label, _lo, _hi in PRICE_BANDS:
                members = sorted((r for r in gruppe if r.price_band == label), key=_nach_wert)
                if not members:
                    continue
                story.append(
                    Paragraph(ch(f"Preisklasse {label} CHF — {len(members)} Weine"), st["band"])
                )
                story.append(_ranking_table(
                    members, st, info=info, show_falstaff=show_falstaff, show_value=True
                ))
            rest = sorted((r for r in gruppe if not r.price_band), key=_nach_wert)
            if rest:
                story.append(Paragraph(ch(f"Ohne Preisklasse — {len(rest)} Weine"), st["band"]))
                story.append(_ranking_table(
                    rest, st, info=info, show_falstaff=show_falstaff, show_value=True
                ))

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
        story.append(_unrated_table(unrated, st, info))

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

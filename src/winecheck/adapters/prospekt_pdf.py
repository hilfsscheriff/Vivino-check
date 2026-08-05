"""Prospekt-PDFs lesen (Prodega, und vorbereitet für Aldi/Lidl).

Prospekte sind Rasterlayouts, keine Tabellen. ``extract_text()`` liest zeilenweise
über alle Spalten hinweg und mischt die Produkte dadurch durcheinander:

.. code-block:: text

    -22% -25% AKTION -22%          <- vier Spalten, eine Zeile
    75 cl 75 cl 75 cl 75 cl
    6.95 5.95 17.50 9.95

Deshalb wird hier über **Koordinaten** gearbeitet: jede ``Art.-Nr.`` ist ein Anker,
um den herum die Zelle rekonstruiert wird. Oberhalb des Ankers stehen Rabatt,
Bezugsgrösse und Preis, unterhalb Produzent, Bezeichnung, Appellation, Land, Region.

Was sich nicht sicher zuordnen lässt, wird nicht geraten, sondern als unsichere
Position mit ``price_confidence = low`` zurückgegeben — die landet im Report in der
Liste zur manuellen Ergänzung, statt einen Scheinsieger zu erzeugen.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import pdfplumber

from ..models import Offer
from .base import RetailerAdapter, looks_like_wine, parse_price

_RE_ART = re.compile(r"Art\.-?Nr\.?\s*(\d{4,8})", re.I)
_RE_UNIT = re.compile(r"^(\d+(?:[.,]\d+)?\s*(?:cl|ml|dl|l|lt)|kg|g|st(?:ü|u)ck|stk|liter)$", re.I)
_RE_PRICE = re.compile(r"^\d{1,4}[.,]\d{2}$")
_RE_STATT = re.compile(r"statt\s*([\d.,]+)", re.I)
_RE_DISCOUNT = re.compile(r"^-\d{1,2}\s*%$")
_RE_PACK = re.compile(r"\b\d{1,3}\s*[x×]\s*\d+(?:[.,]\d+)?\s*(?:cl|ml|dl|l|g|kg)\b", re.I)

#: Zeilen, die zur Seitengestaltung gehören und nicht zum Produkt. Der
#: Gültigkeitszeitraum ("3.8.–8.8.2026") steht in der Fusszeile und rutschte in der
#: ersten Fassung in die Weinnamen.
_NOISE = re.compile(
    r"immer g(ü|u)nstig|abholen|preis(ä|a)nderungen|mengenbeschr|vorbehalten|"
    r"alle aktionen|internet|prodega\.ch|transgourmet|aktionen$|dauertief|"
    r"exklusive mwst|inklusive vrg|^aktion$|^neu$|"
    r"\d{1,2}\.\d{1,2}\.\s*[–-]\s*\d{1,2}\.\d{1,2}\.",
    re.I,
)

#: Länder- und Regionenzeilen. Der Prospekt führt sie als eigene Zeilen unter dem
#: Namen. Sie tragen nichts zur Wein-Identität bei und verschlechtern die Abdeckung
#: beim Namens-Matching, weil sie auf Händlerseite Tokens hinzufügen, die die Quelle
#: nicht kennt.
_GEO_LINE = re.compile(
    r"^(schweiz|deutschland|frankreich|italien|spanien|portugal|(ö|oe)sterreich|"
    r"griechenland|ungarn|chile|argentinien|australien|neuseeland|s(ü|u)dafrika|"
    r"usa|kalifornien|europa|drittl(ä|a)nder|europa/drittl(ä|a)nder|"
    r"wallis|waadt|tessin|graub(ü|u)nden|z(ü|u)rich|aargau|schaffhausen|thurgau|"
    r"neuenburg|genf|bern|dreiseenland|b(ü|u)ndner\s+herrschaft|"
    r"venetien|toskana|piemont|apulien|sizilien|sardinien|umbrien|abruzzen|"
    r"lombardei|friaul|s(ü|u)dtirol|latium|kampanien|kalabrien|marken|"
    r"champagne|burgund|bordeaux|elsass|languedoc|provence|rhone|rh(ô|o)ne|loire|"
    r"beaujolais|jura|savoyen|korsika|"
    r"rioja|ribera del duero|katalonien|navarra|rueda|priorat|kastilien|"
    r"alentejo|douro|dao|vinho verde|mosel|rheingau|pfalz|baden|franken|"
    r"burgenland|steiermark|nieder(ö|o)sterreich|wachau)$",
    re.I,
)


@dataclass
class Cell:
    """Eine rekonstruierte Produktzelle."""

    article_no: str
    lines_above: list[str] = field(default_factory=list)
    lines_below: list[str] = field(default_factory=list)
    page: int = 0

    # -- abgeleitete Werte -------------------------------------------------
    # ``lines_above`` ist von oben nach unten sortiert. Gesucht ist jeweils die
    # *nächstgelegene* Angabe über der Artikelnummer, darum rückwärts iterieren:
    # im Prospekt steht der Preisblock rund 180 pt über der Artikelnummer, und der
    # darüberliegende Block gehört schon zum vorherigen Produkt.
    @property
    def unit(self) -> str:
        """Bezugsgrösse über dem Preis — ``75 cl``, ``kg``, ``Stück``."""
        for line in reversed(self.lines_above):
            if _RE_UNIT.match(line.strip()):
                return line.strip()
        return ""

    @property
    def price(self) -> float | None:
        for line in reversed(self.lines_above):
            if _RE_PRICE.match(line.strip()):
                return parse_price(line)
        return None

    @property
    def reference(self) -> float | None:
        for line in reversed(self.lines_above):
            m = _RE_STATT.search(line)
            if m:
                return parse_price(m.group(1))
        for line in self.lines_below:
            m = _RE_STATT.search(line)
            if m:
                return parse_price(m.group(1))
        return None

    @property
    def pack(self) -> str:
        for line in self.lines_below + self.lines_above:
            m = _RE_PACK.search(line)
            if m:
                return m.group(0)
        return ""

    @property
    def name(self) -> str:
        """Produzent und Bezeichnung. Land- und Regionzeilen bleiben draussen, weil
        sie das Namens-Matching verwässern."""
        parts = [
            line.strip()
            for line in self.lines_below
            if line.strip()
            and not _NOISE.search(line)
            and not _GEO_LINE.match(line.strip())
            and not _RE_PACK.fullmatch(line.strip())
            and not _RE_STATT.search(line)
            and not _RE_UNIT.match(line.strip())
            and not _RE_PRICE.match(line.strip())
            and not _RE_DISCOUNT.match(line.strip())
            and not line.strip().isdigit()
        ]
        return " ".join(parts)


#: Vertikaler Suchbereich über der Artikelnummer. Im Prodega-Prospekt liegt der
#: Preisblock (Rabatt, Bezugsgrösse, Preis, "statt") rund 180 pt darüber; mit den
#: ursprünglich angesetzten 75 pt fand der Parser die Namen, aber keine Preise.
ABOVE_WINDOW = 200.0

#: Darunter stehen Produzent, Bezeichnung, Appellation, Land, Region.
BELOW_WINDOW = 95.0


def _column_bounds(centers: list[float], page_width: float) -> list[tuple[float, float]]:
    """Spaltengrenzen mittig zwischen den Ankerpositionen."""
    if not centers:
        return [(0.0, page_width)]
    out: list[tuple[float, float]] = []
    for i, c in enumerate(centers):
        lo = 0.0 if i == 0 else (centers[i - 1] + c) / 2
        hi = page_width if i == len(centers) - 1 else (c + centers[i + 1]) / 2
        out.append((lo, hi))
    return out


def _bounds_for(bounds: list[tuple[float, float]], x: float) -> tuple[float, float]:
    for lo, hi in bounds:
        if lo <= x < hi:
            return lo, hi
    return bounds[-1]


def _cluster(values: list[float], tolerance: float) -> list[float]:
    """Gruppiert Koordinaten zu Spalten-/Zeilenmitten."""
    out: list[float] = []
    for v in sorted(values):
        if not out or v - out[-1] > tolerance:
            out.append(v)
        else:
            out[-1] = (out[-1] + v) / 2
    return out


def extract_cells(pdf_bytes: bytes, *, only_pages: list[int] | None = None) -> list[Cell]:
    """Rekonstruiert Produktzellen aus einem Prospekt-PDF."""
    cells: list[Cell] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            if only_pages and page_no not in only_pages:
                continue
            words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
            if not words:
                continue
            text = page.extract_text() or ""
            anchors = list(_RE_ART.finditer(text))
            if not anchors:
                continue

            # Spaltenmitten aus den x-Positionen der "Art.-Nr."-Wörter ableiten.
            art_words = [w for w in words if w["text"].lower().startswith("art")]
            columns = _cluster([w["x0"] for w in art_words], tolerance=60.0)
            if not columns:
                columns = _cluster([w["x0"] for w in words], tolerance=80.0)

            # Spaltengrenzen mittig zwischen den Ankern — der Preis sitzt gegenüber
            # der Artikelnummer um ein paar Punkte eingerückt und darf nicht in die
            # Nachbarspalte fallen.
            bounds = _column_bounds(columns, page.width)

            for aw in art_words:
                # Artikelnummer: das Wort direkt rechts vom Anker.
                same_line = [
                    w for w in words
                    if abs(w["top"] - aw["top"]) < 4 and w["x0"] > aw["x0"] and w["x0"] - aw["x0"] < 90
                ]
                digits = next((w["text"] for w in sorted(same_line, key=lambda w: w["x0"])
                               if re.fullmatch(r"\d{4,8}", w["text"])), "")
                if not digits:
                    continue

                lo, hi = _bounds_for(bounds, aw["x0"])
                in_col = [w for w in words if lo <= w["x0"] < hi]
                # Der Preisblock steht rund 180 pt über der Artikelnummer, die
                # Bezeichnung unmittelbar darunter.
                above = [w for w in in_col if aw["top"] - ABOVE_WINDOW < w["top"] < aw["top"] - 4]
                below = [w for w in in_col if aw["top"] + 4 < w["top"] < aw["top"] + BELOW_WINDOW]
                cells.append(
                    Cell(
                        article_no=digits,
                        lines_above=_to_lines(above),
                        lines_below=_to_lines(below),
                        page=page_no,
                    )
                )
    return cells


def _to_lines(words: list[dict]) -> list[str]:
    """Wörter nach y-Position zu Zeilen zusammensetzen."""
    if not words:
        return []
    rows: dict[float, list[dict]] = {}
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        key = next((k for k in rows if abs(k - w["top"]) < 4), None)
        rows.setdefault(key if key is not None else w["top"], []).append(w)
    lines = []
    for top in sorted(rows):
        line = " ".join(w["text"] for w in sorted(rows[top], key=lambda w: w["x0"]))
        lines.append(line.strip())
    return lines


class ProspektPdfMixin:
    """Gemeinsame Logik für Adapter, die ein Prospekt-PDF auswerten."""

    def offers_from_pdf(self, pdf_bytes: bytes, source_url: str) -> tuple[list[Offer], list[str]]:
        """Returns:
            ``(Angebote, unsichere Positionen)``. Die unsicheren Positionen bekommt
            der Report als Liste zur manuellen Ergänzung.
        """
        offers: list[Offer] = []
        uncertain: list[str] = []
        for cell in extract_cells(pdf_bytes):
            name = cell.name
            if not name or not looks_like_wine(name, cell.unit):
                continue
            price = cell.price
            unit = cell.unit
            # Ohne Bezugsgrösse oder Preis wird nicht gerechnet.
            if price is None or not unit:
                uncertain.append(
                    f"Art. {cell.article_no} (S. {cell.page}): {name[:70]} — "
                    f"{'kein Preis erkannt' if price is None else 'keine Bezugsgrösse'}"
                )
                continue
            # Gewichts-/Stückpreise sind keine Flaschenpreise.
            if re.match(r"^(kg|g|st)", unit, re.I):
                uncertain.append(
                    f"Art. {cell.article_no} (S. {cell.page}): {name[:70]} — "
                    f"Preis pro '{unit}', nicht pro Flasche"
                )
                continue

            offer = self.make_offer(  # type: ignore[attr-defined]
                name=name,
                url=source_url,
                price_text=price,
                reference_text=cell.reference,
                # Die Bezugsgrösse über dem Preis bestimmt die Umrechnung; das
                # Gebinde darunter wird nur als Notiz mitgeführt.
                gebinde_text=unit,
                article_no=cell.article_no,
                source_note=f"Prospekt S. {cell.page}"
                + (f", Gebinde {cell.pack}" if cell.pack else ""),
                price_basis="bottle",
                vat_included=False,
            )
            offers.append(offer)
        return offers, uncertain

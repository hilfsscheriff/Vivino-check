"""Preisnormalisierung auf CHF pro 75 cl inkl. MwSt.

Zwei Fehlerquellen, die hier bewusst adressiert werden:

* **MwSt-Satz.** Alkoholische Getränke unterliegen in der Schweiz dem *Normalsatz*
  von 8.1 %, nicht dem reduzierten Lebensmittelsatz von 2.6 %. Das ist der häufigste
  Rechenfehler beim Vergleich Grosshandel gegen Detailhandel.
* **Gebinde.** Prodega quotiert exkl. MwSt und meist pro Karton, Coop und Denner
  inkl. MwSt pro Flasche. Ist die Gebindegrösse nicht sicher erkennbar, wird
  ``price_confidence = low`` gesetzt und der Wein fliegt aus dem Ranking. Ein falsch
  umgerechneter Literpreis erzeugt einen Scheinsieger, und das ist schlimmer als eine
  Lücke.
"""

from __future__ import annotations

import re

from .models import (
    QUESTIONABLE_BARGAIN,
    DiscountPlausibility,
    NormalizedPrice,
    PriceConfidence,
)

#: Normalsatz für alkoholische Getränke (nicht der reduzierte Lebensmittelsatz).
VAT_ALCOHOL = 0.081

#: Referenzgebinde, auf das alles normalisiert wird.
REFERENCE_ML = 750

#: Rabatt über dieser Schwelle auf einer Eigenmarke gilt als konstruiert.
QUESTIONABLE_DISCOUNT = 45.0

#: Re-Export, damit die Schwelle bei den anderen Preiskonstanten auffindbar bleibt.
#: Definiert ist sie in models.py — prices.py importiert models, nicht umgekehrt.
__all__ = ["QUESTIONABLE_BARGAIN"]

_NAMED_VOLUMES = {
    "piccolo": 200,
    "halbflasche": 375,
    "demi": 375,
    "magnum": 1500,
    "doppelmagnum": 3000,
    "jeroboam": 3000,
}

# "6 x 75 cl", "12 × 0.75 l", "6*75cl"
_RE_PACK_X_VOL = re.compile(
    r"(?<!\d)(\d{1,3})\s*[x×*]\s*(\d+(?:[.,]\d+)?)\s*(cl|ml|dl|l|lt|liter)\b", re.I
)
# "6er", "12er-Pack", "6 Flaschen", "Karton 6", "Karton à 12", "Harass 6"
_RE_PACK_ONLY = re.compile(
    r"(?:(?<!\d)(\d{1,3})\s*er\b"
    r"|(?<!\d)(\d{1,3})\s*(?:fl(?:aschen)?|bouteilles?)\b"
    r"|(?:karton|harass|kiste|box|caisse|tray|gebinde|pack)\s*(?:à|a|von|of)?\s*(\d{1,3})(?!\s*(?:cl|ml|dl|l)\b))",
    re.I,
)
_RE_VOLUME = re.compile(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(cl|ml|dl|l|lt|liter)\b", re.I)
_RE_CARTON_WORD = re.compile(r"karton|harass|kiste|caisse|gebinde|tray|\bpack\b", re.I)
_RE_PER_BOTTLE = re.compile(r"pro\s*flasche|je\s*flasche|/\s*fl\b|par\s*bouteille|st(?:ü|u)ck", re.I)
_RE_EXCL_VAT = re.compile(r"exkl?\.?\s*(?:mwst|vat|tva|ust)|ohne\s*mwst|net(?:to)?\b|ht\b", re.I)
_RE_INCL_VAT = re.compile(r"inkl?\.?\s*(?:mwst|vat|tva|ust)|brutto|ttc\b", re.I)
_RE_BAG_IN_BOX = re.compile(r"bag[\s-]?in[\s-]?box|\bbib\b|beutel|tetra|pouch", re.I)


def _to_ml(value: float, unit: str) -> int | None:
    u = unit.lower()
    if u == "ml":
        ml = value
    elif u == "cl":
        ml = value * 10
    elif u == "dl":
        ml = value * 100
    elif u in ("l", "lt", "liter"):
        ml = value * 1000
    else:
        return None
    ml_int = int(round(ml))
    # Unplausible Werte lieber verwerfen als falsch rechnen.
    if not (100 <= ml_int <= 20000):
        return None
    return ml_int


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def parse_gebinde(text: str) -> tuple[int | None, int | None, str, bool]:
    """Erkennt (Anzahl Flaschen, Flaschenvolumen in ml, Notiz, sicher?).

    ``sicher`` ist False, sobald etwas mehrdeutig bleibt — dann wird der Wein nicht
    gerankt, statt eine Zahl zu erfinden.
    """
    t = text or ""
    notes: list[str] = []
    units: int | None = None
    ml: int | None = None
    certain = True

    m = _RE_PACK_X_VOL.search(t)
    if m:
        units = int(m.group(1))
        ml = _to_ml(_num(m.group(2)), m.group(3))
        if ml is None:
            certain = False
            notes.append("Volumen unplausibel")
    else:
        mp = _RE_PACK_ONLY.search(t)
        if mp:
            units = int(next(g for g in mp.groups() if g))
        # Volumen separat suchen; mehrere abweichende Angaben -> unsicher.
        vols = {v for v in (_to_ml(_num(a), b) for a, b in _RE_VOLUME.findall(t)) if v}
        for word, wml in _NAMED_VOLUMES.items():
            if re.search(rf"\b{word}\b", t, re.I):
                vols.add(wml)
        if len(vols) == 1:
            ml = vols.pop()
        elif len(vols) > 1:
            # Häufiger Fall: "6 x 75 cl (4.5 l)" — die kleinste plausible Flaschengrösse
            # ist meist die Flasche, aber sicher ist das nicht.
            certain = False
            ml = min(vols)
            notes.append(f"mehrere Volumenangaben {sorted(vols)}")

    if _RE_BAG_IN_BOX.search(t):
        notes.append("Bag-in-Box/Beutel — Vergleich mit Flasche nur bedingt sinnvoll")
        if ml is None:
            certain = False
            notes.append("BiB ohne Volumenangabe")

    # Der gefährliche Fall: Kartonpreis, aber die Stückzahl steht nicht dabei.
    if units is None and _RE_CARTON_WORD.search(t):
        certain = False
        notes.append("Karton erkannt, Stückzahl fehlt")

    if ml is None:
        if certain and units is not None:
            # Pack erkannt, Volumen nicht genannt: 75 cl ist bei Wein der Normalfall,
            # aber es bleibt eine Annahme -> medium, nicht high.
            ml = REFERENCE_ML
            notes.append("Volumen nicht genannt, 75 cl angenommen")
        elif certain:
            ml = REFERENCE_ML
            notes.append("Volumen nicht genannt, 75 cl angenommen")

    return units, ml, "; ".join(notes), certain


def normalize_price(
    amount: float | None,
    basis_text: str = "",
    *,
    vat_included: bool | None = None,
    price_basis: str = "auto",
    default_vat_included: bool = True,
) -> NormalizedPrice:
    """Rechnet einen Rohpreis auf CHF pro 75 cl inkl. MwSt um.

    Args:
        amount: Rohpreis wie beim Händler angeschrieben.
        basis_text: Text, der Gebinde und MwSt-Hinweis enthält, z.B.
            ``"Karton 6 × 75 cl, exkl. MwSt"``.
        vat_included: Überschreibt die Erkennung aus dem Text.
        price_basis: ``"bottle"``, ``"pack"`` oder ``"auto"``. Bei ``auto`` gilt ein
            Preis als Kartonpreis, wenn ein Gebinde erkannt wurde und nicht
            ausdrücklich "pro Flasche" dabeisteht.
    """
    text = basis_text or ""
    if amount is None:
        return NormalizedPrice(
            price_per_bottle_incl_vat=None,
            price_raw=None,
            price_raw_basis=text,
            confidence=PriceConfidence.LOW,
            note="kein Preis erkannt",
        )

    units, ml, note, certain = parse_gebinde(text)

    # MwSt bestimmen.
    if vat_included is None:
        if _RE_EXCL_VAT.search(text):
            vat_included = False
        elif _RE_INCL_VAT.search(text):
            vat_included = True
        else:
            vat_included = default_vat_included
            if not default_vat_included:
                note = _join(note, "MwSt-Status nicht angeschrieben, exkl. angenommen")

    # Bezugsgrösse des Preises bestimmen.
    if price_basis == "auto":
        if _RE_PER_BOTTLE.search(text):
            effective_units = 1
        elif units and units > 1:
            effective_units = units
        else:
            effective_units = 1
    elif price_basis == "pack":
        effective_units = units or 1
        if units is None:
            certain = False
            note = _join(note, "Kartonpreis, aber Stückzahl unbekannt")
    else:
        effective_units = 1

    per_bottle_raw = amount / effective_units
    per_reference = per_bottle_raw * (REFERENCE_ML / (ml or REFERENCE_ML))
    vat_added = False
    if not vat_included:
        per_reference *= 1 + VAT_ALCOHOL
        vat_added = True

    value = round(per_reference + 1e-9, 2)

    if not certain:
        confidence = PriceConfidence.LOW
    elif ml == REFERENCE_ML and "angenommen" not in note:
        confidence = PriceConfidence.HIGH
    else:
        confidence = PriceConfidence.MEDIUM

    basis_desc = _describe_basis(units, ml, vat_included, text)
    return NormalizedPrice(
        price_per_bottle_incl_vat=value,
        price_raw=amount,
        price_raw_basis=basis_desc,
        confidence=confidence,
        bottle_ml=ml,
        units=units,
        vat_added=vat_added,
        note=note,
    )


def _describe_basis(units: int | None, ml: int | None, vat_included: bool, text: str) -> str:
    """Kurztext für die Klammer im Report, z.B. 'Karton 6, exkl. MwSt'."""
    parts: list[str] = []
    if units and units > 1:
        parts.append(f"Karton {units}")
    if ml and ml != REFERENCE_ML:
        parts.append(f"{ml/10:g} cl")
    parts.append("inkl. MwSt" if vat_included else "exkl. MwSt")
    desc = ", ".join(parts)
    return desc or (text.strip() or "pro Flasche, inkl. MwSt")


def _join(a: str, b: str) -> str:
    return "; ".join(x for x in (a, b) if x)


def discount_percent(price: float | None, reference: float | None) -> float | None:
    if not price or not reference or reference <= 0 or price >= reference:
        return None
    return round((1 - price / reference) * 100, 1)


def rate_discount(pct: float | None, is_private_label: bool) -> DiscountPlausibility:
    """Preis-Leistung wird immer auf den Aktionspreis gerechnet, nie auf den Rabatt.
    Der Rabatt ist rein informativ — und bei Eigenmarken über 45 % markiert, weil
    Referenzpreise dort teils konstruiert sind."""
    if pct is None:
        return DiscountPlausibility.UNKNOWN
    if is_private_label and pct > QUESTIONABLE_DISCOUNT:
        return DiscountPlausibility.QUESTIONABLE
    return DiscountPlausibility.OK


PRICE_BANDS: list[tuple[str, float, float]] = [
    ("<10", 0.0, 10.0),
    ("10-20", 10.0, 20.0),
    ("20-40", 20.0, 40.0),
    ("40-80", 40.0, 80.0),
    (">80", 80.0, float("inf")),
]


def price_band(price: float | None) -> str:
    """Preisklasse für den value_score. Ein 4.1er für 7 Franken und ein 4.5er für
    125 Franken sind nicht dasselbe — verglichen wird innerhalb der Klasse."""
    if price is None:
        return ""
    for label, lo, hi in PRICE_BANDS:
        if lo <= price < hi:
            return label
    return ">80"

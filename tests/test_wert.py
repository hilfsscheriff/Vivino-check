"""Preis-Leistung — die Kennzahl hat einen Besitzer.

Sie hatte zwei, und beide hiessen dem Nutzer gegenüber „Preis-Leistung":
``aggregate.compute_scores`` setzte eine Rangposition innerhalb der Preisklasse und
trieb damit die PDF-Rangliste, die Regression in ``report/site`` setzte den
Regressionsrest nach ``(typ, sorte)`` und trieb nur die Webseite.

Teuer wurde das, als Spec §6 die Gruppierung auf den Stil-Typ umstellte: umgesetzt
wurde es nur in der Seite, und das PDF rankte weiter nach der Verzerrung, die §6
beheben sollte.
"""

import pytest

from winecheck.aggregate import compute_scores
from winecheck.models import (
    Offer,
    PriceConfidence,
    RetailerPrice,
    VivinoResult,
    VivinoStatus,
    WineRow,
)
from winecheck.wert import _je_typ, _wirksame_note


def _wein(preis, note, typ="ausgewogen", sorte="rot", anzahl=500):
    return {"price": preis, "rating": note, "ratingCount": anzahl, "typ": typ, "style": sorte}


def test_die_rechnung_liegt_nur_noch_in_wert():
    """Regressionssperre gegen den Rückfall: ``report/site`` darf die Formel nicht
    erneut enthalten, sondern muss sie importieren."""
    from pathlib import Path

    quelle = (Path(__file__).resolve().parents[1]
              / "src/winecheck/report/site.py").read_text(encoding="utf-8")
    assert "from ..wert import" in quelle
    # Die Formel selbst — der gedämpfte Rest gegen die gesetzte Steigung — steht dort
    # nicht mehr.
    assert "PREIS_GEWICHT * (math.log10" not in quelle
    assert "def _value_scores_einer_gruppe" not in quelle


def test_der_durchschnittswein_liegt_bei_null():
    """Die Zahl heisst „besser oder schlechter als üblich für dieses Geld". Wer genau
    auf der Kurve liegt, muss null bekommen — sonst bedeutet das Vorzeichen nichts."""
    wines = [_wein(10 * 1.5 ** i, 4.0) for i in range(20)]
    _je_typ(wines, "valueScore", None)
    mitte = sum(w["valueScore"] for w in wines) / len(wines)
    assert abs(mitte) < 1e-9, mitte


def test_wenig_bewertete_weine_werden_gedaempft():
    """Eine 4.6 aus zwölf Bewertungen ist keine 4.6 aus zwölftausend."""
    viele = _wein(10.0, 4.6, anzahl=12000)
    wenige = _wein(10.0, 4.6, anzahl=12)
    wines = [viele, wenige] + [_wein(8 + i, 4.0) for i in range(20)]
    _je_typ(wines, "valueScore", None)
    assert viele["valueScore"] > wenige["valueScore"] > 0


def _zeile(preis, note, anzahl=500, typ_name="Irgendein Wein"):
    row = WineRow(
        name=typ_name, vintage=2022, dedup_key=f"{typ_name}-{preis}",
        offers=[Offer(retailer="coop", name=typ_name)],
        prices=[RetailerPrice(retailer="coop", price_per_bottle_incl_vat=preis,
                              price_raw=preis, price_raw_basis="", url="",
                              price_confidence=PriceConfidence.HIGH)],
        vivino=VivinoResult(status=VivinoStatus.EXACT, query="q", url="u", note="n",
                            rating=note, rating_count=anzahl,
                            match_confidence="exact"),
    )
    return row


def test_aggregate_fuehrt_beide_kennzahlen_in_derselben_zeile():
    """Der Kern des Befunds: vorher trug eine Zeile nur die eine Zahl, und die andere
    lag in einem anderen Ausgabekanal. Vergleichen konnte man sie nicht."""
    rows = [_zeile(8 + i, 3.8 + (i % 5) * 0.1, typ_name=f"Wein {i}") for i in range(30)]
    compute_scores(rows)
    mit_beiden = [r for r in rows if r.value_score is not None and r.wert_score is not None]
    assert len(mit_beiden) >= 25, "beide Zahlen müssen an derselben Zeile hängen"
    # Sie sind bewusst verschieden — verschiedene Skalen, verschiedene Gruppierung.
    assert any(abs(r.value_score) > 1 for r in mit_beiden), "value_score ist 0..100"
    assert all(abs(r.wert_score) < 3 for r in mit_beiden), "wert_score ist ein Rest um null"


def test_die_alte_kennzahl_treibt_weiter_die_rangliste():
    """Spec §6 verlangt Parallelbetrieb, „bis die Verteilung geprüft ist". Die
    PDF-Rangfolge umzustellen ist eine Produktentscheidung und darf hier nicht
    stillschweigend passieren."""
    from pathlib import Path

    pdf = (Path(__file__).resolve().parents[1]
           / "src/winecheck/report/pdf_out.py").read_text(encoding="utf-8")
    assert "value_score" in pdf
    assert "wert_score" not in pdf, "die Umstellung gehört bewusst entschieden"


def test_die_csv_zeigt_beide():
    from winecheck.report.csv_out import LEAD_COLUMNS

    assert "value_score" in LEAD_COLUMNS and "wert_score" in LEAD_COLUMNS

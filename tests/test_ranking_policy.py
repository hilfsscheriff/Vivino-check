"""Welche Bewertungen das Ranking treiben dürfen — und welche nur angezeigt werden.

Beides sind Regressionen aus dem ersten Live-Lauf:

* Ein **Produzenten-Durchschnitt** ist nicht die Note dieses Weins. "Piccini" hat
  4.2 aus 752 Bewertungen; über den Chianti Classico Riserva von Piccini sagt das
  nichts Belastbares. Er stand damit auf Platz 3 der Preis-Leistungs-Liste.
* Ein **fuzzy**-Match ist unbestätigt. So kam der Fasswein "Montagne Vin Rouge" mit
  der Note eines Burgunders in die Rangliste.

Beides bleibt im Report sichtbar — nur eben nicht im Sortierschlüssel.
"""

import pytest

from winecheck.aggregate import compute_scores, merge_offers
from winecheck.models import MatchConfidence, Offer, Rating, VivinoResult, VivinoStatus


def _row(name="Ein Wein", price=9.95, **vivino_kwargs):
    o = Offer(
        retailer="prodega", name=name, vintage=2022,
        price_per_bottle_incl_vat=price, price_raw=price,
        price_raw_basis="pro Flasche, inkl. MwSt",
    )
    row = merge_offers([o])[0]
    row.vivino = VivinoResult(**vivino_kwargs) if vivino_kwargs else None
    return row


def _vivino(status, *, rating, confidence, count=100):
    return {
        "status": status, "query": "q", "url": "https://www.vivino.com/de/x/w/1",
        "note": "n", "rating": rating, "rating_count": count,
        "match_confidence": confidence,
    }


# ------------------------------------------------------------- darf ranken

@pytest.mark.parametrize("status", [VivinoStatus.EXACT, VivinoStatus.WINE_LEVEL])
@pytest.mark.parametrize("confidence", ["exact", "wine_level"])
def test_confirmed_matches_drive_the_ranking(status, confidence):
    row = _row(**_vivino(status, rating=4.2, confidence=confidence))
    value, source = row.ranking_rating()
    assert value == pytest.approx(0.84)
    assert source == "Vivino"
    compute_scores([row])
    assert row.value_score is not None


# ---------------------------------------------------------- darf nicht ranken

def test_winery_level_is_shown_but_not_ranked():
    """Piccini: Produzenten-Durchschnitt 4.2 — sichtbar, aber kein Sortierwert."""
    row = _row(
        "Piccini Chianti Classico Riserva DOCG", 8.59,
        **_vivino(VivinoStatus.WINERY_LEVEL, rating=4.2, confidence="winery_level", count=752),
    )
    value, source = row.ranking_rating()
    assert value is None
    assert source == ""
    compute_scores([row])
    assert row.value_score is None
    # Sichtbar bleibt es: Note, Status und Link stehen weiterhin in der Zeile.
    assert row.vivino.rating == 4.2
    assert row.vivino.url
    assert row.has_any_rating is True


def test_fuzzy_match_is_shown_but_not_ranked():
    """Montagne Vin Rouge: unbestätigte Namenszuordnung — kein Sortierwert."""
    row = _row(
        "Montagne Vin Rouge", 1.21,
        **_vivino(VivinoStatus.WINE_LEVEL, rating=4.0, confidence="fuzzy", count=382),
    )
    assert row.ranking_rating() == (None, "")
    compute_scores([row])
    assert row.value_score is None
    assert row.vivino.rating == 4.0


def test_falstaff_fuzzy_is_also_excluded_from_ranking():
    row = _row()
    row.falstaff = Rating(
        source="falstaff", value=91, scale_max=100, confidence=MatchConfidence.FUZZY,
        source_name="Irgendein anderer Wein",
    )
    assert row.ranking_rating() == (None, "")


def test_falstaff_confirmed_beats_vivino_as_leitquelle():
    row = _row(**_vivino(VivinoStatus.EXACT, rating=4.0, confidence="exact"))
    row.falstaff = Rating(
        source="falstaff", value=89, scale_max=100, confidence=MatchConfidence.EXACT,
    )
    value, source = row.ranking_rating()
    assert source == "Falstaff", "Falstaff ist Leitquelle, wo vorhanden"
    assert value == pytest.approx(0.89)


def test_missing_match_confidence_from_old_cache_does_not_rank():
    """Alte Cache-Einträge ohne Konfidenz werden nicht stillschweigend gerankt."""
    row = _row(**_vivino(VivinoStatus.EXACT, rating=4.5, confidence=""))
    assert row.ranking_rating() == (None, "")


# ------------------------------------------------------- Diagramm-Achse

def test_chart_axis_uses_vivino_only_never_falstaff():
    """Auf einer Achse darf nur eine Bewertungsgrundlage stehen. Ein Falstaff-92 und
    ein Vivino-4.6 sehen normalisiert gleich hoch aus, bedeuten aber Verschiedenes —
    das Diagramm würde eine Vergleichbarkeit behaupten, die es nicht gibt. Für die
    Rangliste bleibt Falstaff Leitquelle, dort steht die Herkunft je Zeile."""
    row = _row(**_vivino(VivinoStatus.EXACT, rating=4.2, confidence="exact", count=900))
    row.falstaff = Rating(
        source="falstaff", value=95.0, scale_max=100.0,
        confidence=MatchConfidence.EXACT,
    )
    # Ranking folgt Falstaff …
    assert row.ranking_rating()[1] == "Falstaff"
    # … die Achse trotzdem Vivino, in der Original-Skala 1–5.
    assert row.chart_rating() == 4.2


def test_chart_axis_drops_winery_averages():
    """Der Produzenten-Mittelwert ist keine Note für diesen Wein. Auf der Achse würde
    er wie eine wirken."""
    row = _row(**_vivino(
        VivinoStatus.WINERY_LEVEL, rating=4.6, confidence="winery_level", count=92093,
    ))
    assert row.chart_rating() is None


def test_chart_axis_drops_wines_without_vivino():
    """Ohne Vivino-Note kein Punkt — statt einer geschätzten Position."""
    assert _row().chart_rating() is None
    assert _row(**_vivino(
        VivinoStatus.NO_ENTRY, rating=None, confidence="none",
    )).chart_rating() is None

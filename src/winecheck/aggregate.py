"""Dedup über Händler und ``value_score``.

Dedup ist das Kernfeature: derselbe Wein bei Coop und Prodega wird **eine** Zeile mit
zwei Preisen — nur so ist zu sehen, ob sich die Karte lohnt. Der Schlüssel ist der
normalisierte Name plus Jahrgang, nicht die Artikelnummer: Artikelnummern sind
händlerspezifisch und taugen für den Vergleich nicht.

Der ``value_score`` vergleicht **innerhalb der Preisklasse**. Ein 4.1er für 7 Franken
und ein 4.5er für 125 Franken sind nicht dasselbe — der günstige soll gewinnen.
Gerechnet wird immer auf den Aktionspreis, nie auf den Rabatt.
"""

from __future__ import annotations

from collections import defaultdict

from .models import Offer, PriceConfidence, RetailerPrice, WineRow
from .names import dedup_key, normalized_name
from .prices import PRICE_BANDS, price_band


def merge_offers(offers: list[Offer]) -> list[WineRow]:
    """Fasst Angebote verschiedener Händler zum selben Wein zusammen."""
    groups: dict[str, list[Offer]] = defaultdict(list)
    for o in offers:
        groups[dedup_key(o.name, o.vintage)].append(o)

    rows: list[WineRow] = []
    for key, group in groups.items():
        # Den ausführlichsten Namen als Anzeigenamen nehmen — er trägt am meisten
        # Information für die Bewertungssuche.
        display = max(group, key=lambda o: len(normalized_name(o.name)))
        row = WineRow(
            name=display.name,
            vintage=display.vintage,
            dedup_key=key,
            offers=list(group),
            is_private_label=any(o.is_private_label for o in group),
        )
        for o in group:
            row.prices.append(
                RetailerPrice(
                    retailer=o.retailer,
                    price_per_bottle_incl_vat=o.price_per_bottle_incl_vat,
                    price_raw=o.price_raw,
                    price_raw_basis=o.price_raw_basis,
                    url=o.url,
                    price_confidence=o.price_confidence,
                    discount_percent=o.discount_percent,
                    discount_plausibility=o.discount_plausibility,
                )
            )
        row.price_band = price_band(row.best_price)
        rows.append(row)
    return rows


def compute_scores(rows: list[WineRow]) -> list[WineRow]:
    """Setzt ``value_score`` je Preisklasse.

    Innerhalb einer Klasse wird die normalisierte Bewertung gegen den Preis gestellt:
    der Score steigt mit der Bewertung und fällt mit dem Preis, jeweils relativ zu den
    anderen Weinen derselben Klasse. Weine ohne Bewertung oder ohne verlässlichen
    Preis bekommen keinen Score — geraten wird nichts.
    """
    by_band: dict[str, list[WineRow]] = defaultdict(list)
    for row in rows:
        rating, source = row.ranking_rating()
        row.rank_source = source
        price = row.best_price
        if rating is None or price is None or price <= 0:
            row.value_score = None
            continue
        if not any(
            p.price_confidence is not PriceConfidence.LOW for p in row.prices
        ):
            # Gebindegrösse unsicher -> nicht ins Ranking. Ein falsch umgerechneter
            # Literpreis erzeugt einen Scheinsieger.
            row.value_score = None
            continue
        by_band[row.price_band].append(row)

    for band, members in by_band.items():
        prices = [r.best_price for r in members if r.best_price]
        ratings = [r.ranking_rating()[0] for r in members]
        ratings = [x for x in ratings if x is not None]
        if not prices or not ratings:
            continue
        p_lo, p_hi = min(prices), max(prices)
        r_lo, r_hi = min(ratings), max(ratings)
        for row in members:
            rating, _ = row.ranking_rating()
            price = row.best_price
            if rating is None or price is None:
                continue
            # Position innerhalb der Klasse, 0..1. Bei nur einem Wein je Klasse oder
            # identischen Werten fällt der Term auf 0.5 zurück.
            r_pos = (rating - r_lo) / (r_hi - r_lo) if r_hi > r_lo else 0.5
            p_pos = (price - p_lo) / (p_hi - p_lo) if p_hi > p_lo else 0.5
            # Bewertung zählt doppelt: ein guter Wein soll einen billigen schlechten
            # nicht automatisch verlieren.
            row.value_score = round(100 * (2 * r_pos + (1 - p_pos)) / 3, 1)
    return rows


def band_summary(rows: list[WineRow]) -> list[tuple[str, int, int]]:
    """``(Preisklasse, Anzahl, davon mit Bewertung)`` — für den Report."""
    out = []
    for label, _lo, _hi in PRICE_BANDS:
        members = [r for r in rows if r.price_band == label]
        rated = [r for r in members if r.has_any_rating]
        out.append((label, len(members), len(rated)))
    return out


def cross_retailer_rows(rows: list[WineRow]) -> list[WineRow]:
    """Weine, die bei mehr als einem Händler in Aktion sind — der eigentliche
    Grund für den händlerübergreifenden Vergleich."""
    return sorted(
        (r for r in rows if r.retailer_count > 1),
        key=lambda r: -(_spread(r) or 0),
    )


def _spread(row: WineRow) -> float | None:
    """Preisspanne zwischen dem teuersten und günstigsten Händler."""
    vals = [
        p.price_per_bottle_incl_vat
        for p in row.prices
        if p.price_per_bottle_incl_vat is not None
        and p.price_confidence is not PriceConfidence.LOW
    ]
    if len(vals) < 2:
        return None
    return round(max(vals) - min(vals), 2)


def spread(row: WineRow) -> float | None:
    return _spread(row)

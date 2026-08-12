"""results.csv — alle Felder roh, inkl. Händlerpreise und aller Vivino-Felder."""

from __future__ import annotations

import csv
from pathlib import Path

from ..models import WineRow

#: Feste Spaltenreihenfolge vorne, damit die Datei zwischen Läufen vergleichbar
#: bleibt. Die Vivino-Felder stehen zusammen und vollständig.
LEAD_COLUMNS = [
    "name",
    "vintage",
    "price_per_bottle_incl_vat",
    "cheapest_retailer",
    "retailer_count",
    "price_band",
    # Drei Preis-Leistungs-Spalten, und jede beantwortet eine andere Frage. Damit nicht
    # wieder zwei Zahlen unter einem Namen stehen, hier festgehalten, welche wo gilt:
    #
    #   value_score       alte Kennzahl, Rangposition in der Preisklasse, 0..100.
    #                     Treibt seit dem 12.8.2026 keine Rangfolge mehr, steht nur noch
    #                     zum Vergleich da.
    #   wert_score        Rest der Note über dem Preisniveau, über **beide** Warenwelten
    #                     gerechnet. Das ist die Zahl, welche die Webseite in der
    #                     Standardansicht zeigt.
    #   wert_score_welt   dieselbe Rechnung, aber nur gegen die eigene Warenwelt
    #                     (Schweizer Handel oder Vivino-Marktplatz). Das ist die Zahl in
    #                     der Spalte P/L des PDF und die, nach der es sortiert.
    "value_score",
    "wert_score",
    "wert_score_welt",
    "sorte",
    "trinkreife",
    "trinkreife_text",
    "jahrgang_qualitaet",
    "trinkreife_region",
    "trinkreife_weinart",
    "trinkreife_code",
    "bargain_percent",
    "bargain_plausibility",
    "vivino_market_price",
    "vivino_market_price_shop",
    "vivino_market_price_raw",
    "vivino_market_price_basis",
    "vivino_market_price_url",
    "vivino_market_price_note",
    "rank_source",
    "rank_rating_normalized",
    "falstaff_points",
    "falstaff_confidence",
    "falstaff_source_name",
    "falstaff_note",
    "falstaff_url",
    "falstaff_reported_by",
    "critics",
    "vivino_status",
    "vivino_rating",
    "vivino_rating_count",
    "vivino_matched_name",
    "vivino_match_confidence",
    "vivino_note",
    "vivino_query",
    "vivino_url",
    "vivino_candidates",
    "vivino_retry_after",
    "winesearcher_value",
    "winesearcher_note",
    "is_private_label",
    "dedup_key",
]


def write_csv(rows: list[WineRow], path: Path | str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    flat = [r.to_flat() for r in rows]

    extra = sorted({k for row in flat for k in row} - set(LEAD_COLUMNS))
    fieldnames = [*LEAD_COLUMNS, *extra]

    with p.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        for row in flat:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    return p

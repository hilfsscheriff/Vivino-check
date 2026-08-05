"""Tests für Formatierung und Ausgabedateien.

Schwerpunkt: die Vivino-Spalte ist auch im Report nie leer, und die Schweizer
Konventionen stimmen (ss statt ß, CHF 9.95, Datum 5.8.2026).
"""

import csv
import time

import pytest

from winecheck.aggregate import compute_scores, merge_offers
from winecheck.models import (
    MatchConfidence,
    Offer,
    Rating,
    VivinoCandidate,
    VivinoResult,
    VivinoStatus,
)
from winecheck.report.csv_out import LEAD_COLUMNS, write_csv
from winecheck.report.diff import snapshot, write_diff
from winecheck.report.formatting import ch, chf, date, rating_text
from winecheck.report.pdf_out import write_pdf
from winecheck.report.plot import write_scatter


# ------------------------------------------------------------- Formatierung

def test_swiss_sharp_s_becomes_ss():
    assert ch("Grösse") == "Grösse"
    assert ch("Größe") == "Grösse"
    assert ch("Straße") == "Strasse"


def test_chf_formatting():
    assert chf(9.95) == "CHF 9.95"
    assert chf(7.5) == "CHF 7.50"
    assert chf(1250) == "CHF 1'250.00"
    assert chf(None) == ""


def test_date_has_no_leading_zeros():
    t = time.mktime(time.strptime("2026-08-05", "%Y-%m-%d"))
    assert date(t) == "5.8.2026"


def test_rating_text_uses_scale():
    assert rating_text(3.6, 5.0, 42) == "3.6/5 (42)"
    assert rating_text(89, 100) == "89/100"
    assert rating_text(None, 5.0) == ""


# ------------------------------------------------------------------- Fixtures

def _row(name, price, *, vivino, falstaff=None, retailer="denner", vintage=2022):
    o = Offer(
        retailer=retailer, name=name, vintage=vintage,
        price_per_bottle_incl_vat=price, price_raw=price,
        price_raw_basis="pro Flasche, inkl. MwSt",
        url=f"https://example.test/{name[:8]}",
    )
    row = merge_offers([o])[0]
    row.vivino = vivino
    row.falstaff = falstaff
    return row


@pytest.fixture
def rows():
    hit = _row(
        "Provins Domherrenwein Fendant du Valais AOC", 9.95,
        vivino=VivinoResult(
            status=VivinoStatus.EXACT, query="domherrenwein fendant valais",
            url="https://www.vivino.com/de/domherrenwein/w/2076752",
            note="Jahrgang 2022 mit 42 Bewertungen", rating=3.6, rating_count=42,
            matched_name="Provins Les Grands Dignitaires Domherrenwein Fendant",
            match_confidence="exact",
        ),
    )
    miss = _row(
        "Noirillon Assemblage de cépages rouges AOC Vaud", 6.25,
        vivino=VivinoResult.miss(
            VivinoStatus.NO_ENTRY, "noirillon assemblage cepages rouges vaud",
            "kein Eintrag gefunden — Suche öffnen",
        ),
    )
    few = _row(
        "Col del Sol Brut Prosecco Superiore Valdobbiadene", 12.90,
        vivino=VivinoResult(
            status=VivinoStatus.TOO_FEW_RATINGS, query="col del sol",
            url="https://www.vivino.com/de/col-del-sol/w/999",
            note="nur 4 Bewertungen", rating_count=4,
        ),
    )
    ambiguous = _row(
        "Rossetti Linda Bolgheri DOC", 15.50,
        vivino=VivinoResult(
            status=VivinoStatus.AMBIGUOUS, query="rossetti linda bolgheri",
            url="https://www.vivino.com/de/a/w/1", note="mehrere Kandidaten",
            candidates=[
                VivinoCandidate(name="Rossetti Linda Bianco", url="https://www.vivino.com/de/a/w/1"),
                VivinoCandidate(name="Rossetti Linda Rosso", url="https://www.vivino.com/de/b/w/2"),
            ],
        ),
    )
    blocked = _row(
        "Castelbarco Ripasso Valpolicella Superiore", 6.45,
        vivino=VivinoResult.miss(
            VivinoStatus.BLOCKED, "castelbarco ripasso", "blockiert",
            retry_after="2026-08-06T10:00:00",
        ),
        falstaff=Rating(
            source="falstaff", value=None, scale_max=100, status="blocked",
            note="Falstaff nicht erreichbar", url="https://www.falstaff.com/de/suche?q=castelbarco",
        ),
    )
    return compute_scores([hit, miss, few, ambiguous, blocked])


# -------------------------------------------------------------------- CSV

def test_csv_contains_all_vivino_fields_and_never_blank_url(tmp_path, rows):
    path = write_csv(rows, tmp_path / "results.csv")
    with path.open(encoding="utf-8-sig") as fh:
        data = list(csv.DictReader(fh, delimiter=";"))

    assert len(data) == len(rows)
    for col in ("vivino_status", "vivino_url", "vivino_query", "vivino_note",
                "vivino_rating", "vivino_rating_count", "vivino_matched_name"):
        assert col in data[0], f"{col} fehlt in results.csv"

    for record in data:
        assert record["vivino_status"], "vivino_status darf nie leer sein"
        assert record["vivino_url"].startswith("https://www.vivino.com/"), record["vivino_url"]
        assert record["vivino_query"], "vivino_query darf nie leer sein"
        assert record["vivino_note"], "vivino_note darf nie leer sein"


def test_csv_lead_columns_are_stable(tmp_path, rows):
    path = write_csv(rows, tmp_path / "results.csv")
    header = path.read_text(encoding="utf-8-sig").splitlines()[0].split(";")
    assert header[: len(LEAD_COLUMNS)] == LEAD_COLUMNS


def test_csv_records_retry_after_for_blocked(tmp_path, rows):
    path = write_csv(rows, tmp_path / "results.csv")
    with path.open(encoding="utf-8-sig") as fh:
        data = list(csv.DictReader(fh, delimiter=";"))
    blocked = [r for r in data if r["vivino_status"] == "blocked"]
    assert blocked and blocked[0]["vivino_retry_after"] == "2026-08-06T10:00:00"


# -------------------------------------------------------------------- PDF

def test_pdf_is_written_and_nonempty(tmp_path, rows):
    path = write_pdf(rows, tmp_path / "report.pdf")
    assert path.exists()
    assert path.stat().st_size > 4000
    assert path.read_bytes().startswith(b"%PDF")


def test_pdf_survives_rows_without_any_rating(tmp_path):
    row = _row(
        "Nur Preis, keine Bewertung", 8.50,
        vivino=VivinoResult.miss(VivinoStatus.NO_ENTRY, "nur preis", "kein Eintrag"),
    )
    path = write_pdf(compute_scores([row]), tmp_path / "r.pdf")
    assert path.exists()


def test_pdf_with_empty_input_still_produces_a_file(tmp_path):
    path = write_pdf([], tmp_path / "empty.pdf")
    assert path.exists()


# ------------------------------------------------------------------- Plot

def test_scatter_written_when_ratings_exist(tmp_path, rows):
    path = write_scatter(rows, tmp_path / "scatter.png")
    assert path is not None and path.exists()
    assert path.stat().st_size > 5000


def test_scatter_skipped_without_ratings(tmp_path):
    row = _row(
        "Ohne alles", 9.0,
        vivino=VivinoResult.miss(VivinoStatus.NO_ENTRY, "ohne alles", "kein Eintrag"),
    )
    assert write_scatter([row], tmp_path / "s.png") is None


# ------------------------------------------------------------------- diff

def test_diff_first_run_mentions_missing_baseline(tmp_path, rows):
    path = write_diff(rows, [], tmp_path / "diff.md")
    text = path.read_text(encoding="utf-8")
    assert "Erster Lauf" in text
    assert "Neue Aktionen" in text


def test_diff_reports_new_expired_and_price_changes(tmp_path, rows):
    before = snapshot(rows)
    # Preis eines Weins senken, einen entfernen, einen neuen ergänzen.
    changed = compute_scores([
        _row("Provins Domherrenwein Fendant du Valais AOC", 7.95,
             vivino=VivinoResult(
                 status=VivinoStatus.EXACT, query="q",
                 url="https://www.vivino.com/de/x/w/1", note="ok",
                 rating=3.6, rating_count=42, match_confidence="exact")),
        _row("Ganz neuer Wein", 11.0,
             vivino=VivinoResult(
                 status=VivinoStatus.EXACT, query="neu",
                 url="https://www.vivino.com/de/n/w/2", note="ok",
                 rating=4.2, rating_count=80, match_confidence="exact")),
    ])
    path = write_diff(changed, before, tmp_path / "diff.md")
    text = path.read_text(encoding="utf-8")
    assert "Ganz neuer Wein" in text
    assert "Noirillon" in text          # ausgelaufen
    assert "CHF 9.95" in text and "CHF 7.95" in text   # Preisänderung
    assert "▼" in text


def test_diff_highlights_newly_appeared_vivino_ratings(tmp_path):
    """Der Abschnitt, um den es beim wöchentlichen Betrieb geht."""
    before_row = _row(
        "Heldenrosé Rosé de Gamay", 6.25,
        vivino=VivinoResult.miss(VivinoStatus.NO_ENTRY, "heldenrose rose gamay", "kein Eintrag"),
    )
    before = snapshot(compute_scores([before_row]))

    after_row = _row(
        "Heldenrosé Rosé de Gamay", 6.25,
        vivino=VivinoResult(
            status=VivinoStatus.EXACT, query="heldenrose rose gamay",
            url="https://www.vivino.com/de/heldenrose/w/4242",
            note="Jahrgang 2022 mit 7 Bewertungen", rating=3.4, rating_count=7,
            match_confidence="exact",
        ),
    )
    path = write_diff(compute_scores([after_row]), before, tmp_path / "diff.md")
    text = path.read_text(encoding="utf-8")
    assert "Neu aufgetauchte Vivino-Bewertungen (1)" in text
    assert "vorher `no_entry`" in text
    assert "3.4/5" in text
    assert "https://www.vivino.com/de/heldenrose/w/4242" in text

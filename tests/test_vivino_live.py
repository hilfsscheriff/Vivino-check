"""Live-Test gegen Vivino. Läuft nur mit ``WINECHECK_LIVE=1``.

Prüft nicht die Noten selbst (die ändern sich), sondern die harte Zusicherung der
Pflichtspalte: jeder Wein bekommt einen Status, eine Query und eine klickbare URL.
"""

from __future__ import annotations

import os

import pytest

from winecheck.fetching import Fetcher
from winecheck.models import VivinoStatus
from winecheck.ratings.vivino import VivinoAdapter

pytestmark = pytest.mark.skipif(
    os.getenv("WINECHECK_LIVE") != "1",
    reason="Netzwerktest — mit WINECHECK_LIVE=1 aktivieren",
)

FIXTURES = [
    ("Domherrenwein Fendant du Valais AOC", 2023),
    ("Passìo Nero d'Avola/Perricone Sicilia DOC da uve leggermente appassite", 2022),
    ("Anima Negra ÀN/2 IGP Illes Balears", 2022),
    ("Noirillon Assemblage de cépages rouges AOC Vaud", 2023),
    ("Carmelin Vin de Pays Romand", 2022),
]


@pytest.fixture(scope="module")
def adapter():
    with Fetcher(rate_limit_seconds=2.2) as f:
        yield VivinoAdapter(f)


@pytest.mark.parametrize("name,vintage", FIXTURES)
def test_pflichtspalte_is_never_empty(adapter, name, vintage):
    r = adapter.lookup(name, vintage)
    assert isinstance(r.status, VivinoStatus)
    assert r.url.startswith("https://www.vivino.com/"), r.url
    assert r.query, "vivino_query muss gesetzt sein"
    assert r.note, "vivino_note muss gesetzt sein"
    # Keine Bewertung ohne Status, kein Status ohne Erklärung.
    if r.rating is None:
        assert r.status is not VivinoStatus.EXACT
    else:
        assert r.rating_count is not None


def test_known_hit_has_a_rating(adapter):
    """Domherrenwein Fendant ist auf Vivino vorhanden — über die API auffindbar,
    auch wenn die Website-Suche ihn nicht zeigt."""
    r = adapter.lookup("Domherrenwein Fendant du Valais AOC", 2023)
    assert r.status in (
        VivinoStatus.EXACT,
        VivinoStatus.WINE_LEVEL,
        VivinoStatus.TOO_FEW_RATINGS,
    ), f"{r.status} / {r.note}"
    assert "/w/" in r.url


def test_known_miss_yields_search_url(adapter):
    """Eine Denner-Eigenmarke ohne Vivino-Eintrag muss die Suchurl liefern."""
    r = adapter.lookup("Noirillon Assemblage de cépages rouges AOC Vaud", 2023)
    if r.status is VivinoStatus.NO_ENTRY:
        assert "explore?search_term=" in r.url
        assert r.rating is None

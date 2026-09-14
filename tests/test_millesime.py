"""Im Champagne ist „Millésimé" ein eigener Wein, kein Etikett für die Jahreszahl.

Gemeldet am 14.09.2026 an einer Karte: „Champagne AOC Laurent-Perrier, brut,
Frankreich" für CHF 25.55 bei Coop, mit der Note 4.2 aus 14 135 Bewertungen — und
darunter, klein, der gefundene Name: „Laurent-Perrier Brut **Millésimé** Champagne".
Das ist ein anderer Wein. Sein Marktpreis von CHF 81.66 erzeugte obendrein die
Auszeichnung „−69 % gegen Markt", also genau das Signal, das zum Kauf verleitet.

Derselbe Wein steht bei Prodega und Schubi korrekt als „La Cuvée Brut" mit 4.1 aus
64 489 Bewertungen — der Fehler betraf nur die Aktionis-Position.

Die Ursache war eine Entscheidung von mir, schriftlich festgehalten und falsch: beim
Aufräumen von „vintage" blieb „millesime" im Verpackungsrauschen stehen, mit der
Begründung, es bezeichne nie ein Produkt. Damit verschwand das Wort schon beim
Normalisieren, und keine Regel konnte es mehr beanstanden. Die italienische Form
„millesimato" galt die ganze Zeit als unterscheidend.
"""

import pytest

from winecheck.matching import match_wine
from winecheck.names import DISCRIMINATING, PACKAGING_NOISE, STIL_IN_ABFRAGE, normalized_name


def test_das_wort_ueberlebt_das_normalisieren():
    """Ohne das ist jede Regel darüber wirkungslos — sie sieht das Wort gar nicht."""
    assert "millesime" in normalized_name("Laurent-Perrier Brut Millésimé Champagne")
    assert "millesime" in DISCRIMINATING
    assert "millesime" not in PACKAGING_NOISE


def test_es_bleibt_in_der_suchabfrage():
    """Sonst fiele es aus der Abfrage, die Suche fände den Brut ohne Jahrgang — und
    der würde als anderer Wein abgelehnt. Ergebnis: keine Note statt der richtigen."""
    assert "millesime" in STIL_IN_ABFRAGE


@pytest.mark.parametrize("haendler,quelle", [
    # Der gemeldete Fall.
    ("Champagne AOC Laurent-Perrier, brut, Frankreich",
     "Laurent-Perrier Brut Millésimé Champagne"),
    # Derselbe Fehler, im selben Bestand gefunden.
    ("Charles Heidsieck Champagne Brut", "Charles Heidsieck Brut Millésimé 2018"),
])
def test_der_jahrgangschampagner_erbt_die_note_nicht(haendler, quelle):
    d = match_wine(haendler, quelle)
    assert not d.matched, d.reason


def test_umgekehrt_ebenso():
    """Auch wenn der Händler den Millésimé führt und die Quelle den einfachen Brut —
    die Regel muss in beide Richtungen sperren."""
    d = match_wine("Champagne Laurent-Perrier Brut Millésimé 2015",
                   "Laurent-Perrier La Cuvée Brut Champagne")
    assert not d.matched, d.reason


def test_zwei_millesime_finden_sich_weiterhin():
    d = match_wine("Prosecco Rosé Millesimato Brut Villa Sandi",
                   "Villa Sandi Il Fresco Rosé Millesimato Prosecco")
    assert d.matched, d.reason


def test_der_richtige_wein_bleibt_erreichbar():
    """Was der Händler wirklich meint, ist der Brut ohne Jahrgang. Er darf durch die
    Änderung nicht mit verloren gehen — wenn auch mit Vorbehalt, weil die Quelle
    einen eigenen Namensbestandteil mitbringt."""
    d = match_wine("Champagne AOC Laurent-Perrier, brut, Frankreich",
                   "Laurent-Perrier La Cuvée Brut Champagne")
    assert d.matched, d.reason

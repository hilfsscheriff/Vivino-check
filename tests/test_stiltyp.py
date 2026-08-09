"""Stil-Typ: die Einordnung nach Machart.

Die Fixtures stammen aus der Spec (§8) und aus echten Datensätzen. Stufe 1 hat dort
kein Spielraum — „Alle Fixtures der Stufe 1 werden exakt getroffen."
"""

import pytest

from winecheck.stiltyp import (
    MIN_KEYWORD_TREFFER,
    MIN_STRUKTUR_URTEILE,
    TYPEN,
    UNBEKANNT,
    Struktur,
    einordnen,
    tabelle,
    typ_aus_score,
)


# ------------------------------------------------- Stufe 1: gesicherte Signale

@pytest.mark.parametrize("name,beleg", [
    ("Santi Nobile Cento X Cento Appassimento Primitivo", "appassimento"),
    ("Amarone della Valpolicella Classico DOCG", "amarone"),
    ("Valpolicella Ripasso Superiore DOC", "ripasso"),
    ("Recioto di Soave Classico", "recioto"),
    ("Vin Santo del Chianti", "vin santo"),
    ("Vinsanto Toscano", "vinsanto"),
])
def test_suesse_token_im_namen_entscheidet_sofort(name, beleg):
    """Fixture 1 der Spec. Kein Händler schreibt „Appassimento" versehentlich hin —
    steht das Wort da, ist der Fall entschieden und keine spätere Stufe darf ihn
    umdrehen."""
    e = einordnen(name)
    assert e.typ == "fruchtsuess", e.signale
    assert e.stufe == 1
    assert any(beleg in s.lower() for s in e.signale), e.signale


@pytest.mark.parametrize("name", ["Barista Pinotage", "Apothic Red Blend California"])
def test_stilmarke_entscheidet_sofort(name):
    """Fixtures 13 und 14. Diese Marken tragen ihr Profil im Namen, ohne es zu nennen."""
    e = einordnen(name)
    assert e.typ == "fruchtsuess"
    assert e.stufe == 1
    assert any("stilmarke" in s.lower() for s in e.signale), e.signale


def test_restzucker_aus_dem_datenblatt_entscheidet():
    """Fixture 3: Tenuta Ulisse Amaranta, 7 g/l Restzucker im Händlerdatenblatt.

    Heute liefert kein Händler solche Werte (siehe Modulkopf von stiltyp.py). Der Test
    hält die Regel fest, damit sie am Tag stimmt, an dem eines mitkommt."""
    e = einordnen(
        "Tenuta Ulisse Amaranta Montepulciano d'Abruzzo",
        datenblatt="Alkohol 14,0 % vol, Restzucker 7 g/l, Gesamtsäure 5,2 g/l",
    )
    assert e.typ == "fruchtsuess"
    assert e.stufe == 1
    assert any("7.0 g/l" in s for s in e.signale), e.signale


def test_durchgegoren_und_saeurebetont_ist_straff():
    e = einordnen("Irgendein Weisser", datenblatt="Restzucker 1,2 g/l, Gesamtsäure 6,8 g/l")
    assert e.typ == "straff_herb"
    assert e.stufe == 1


def test_hoher_alkohol_allein_genuegt():
    """15 % erreicht ein Rotwein nur über sehr reife oder angetrocknete Trauben."""
    assert einordnen("Roter", datenblatt="Alkohol 15,0 % vol").typ == "fruchtsuess"
    assert einordnen("Roter", datenblatt="Alkohol 13,5 % vol").typ == UNBEKANNT


@pytest.mark.parametrize("name", ["Riesling Spätlese Mosel", "Riesling Spaetlese Mosel"])
def test_beide_umlautschreibweisen_treffen(name):
    """Händler schreiben „Spätlese" und „Spaetlese". ``strip_accents`` allein macht aus
    dem einen „spatlese" und aus dem anderen „spaetlese" — dieträfen sich nie."""
    assert einordnen(name).typ == "fruchtsuess"


@pytest.mark.parametrize("name", [
    "Grundwein rund um den See",      # "rund" steckt in "Grundwein"
    "Dulcedo Nero d'Avola",           # "dulce" steckt in "Dulcedo"
    "Passitea Bianco",                # "passito" ist nicht "Passitea"
])
def test_wortgrenzen_verhindern_falsche_treffer(name):
    """Ohne Wortgrenzen fände „dulce" auch in „Dulcedo" statt. Ein falscher Typ ist
    schlimmer als keiner: er verschiebt eine Kennzahl, ohne dass es auffällt."""
    assert einordnen(name).typ == UNBEKANNT, einordnen(name).signale


# ------------------------------------------------- Stufe 2: Vivino-Struktur

def test_gemessene_struktur_schlaegt_die_stiltabelle():
    """Die Struktur ist am einzelnen Wein gemessen, die Tabelle gilt für eine Gattung.
    Ein Appassimento-Primitivo und ein trockener Primitivo tragen denselben Stil."""
    e = einordnen(
        "Irgendein Primitivo",
        struktur=Struktur(suesse=3.4, tannin=2.6, saeure=2.7, urteile=280),
        stil_name="Southern Italy Primitivo",
    )
    assert e.stufe == 2
    assert e.typ == "fruchtsuess"
    assert "Geschmacksstruktur" in e.signale[0]
    assert e.score is not None


def test_straffe_struktur_wird_als_straff_erkannt():
    e = einordnen(
        "Irgendein Nebbiolo",
        struktur=Struktur(suesse=1.4, tannin=4.6, saeure=3.9, urteile=900),
    )
    assert e.typ == "straff_herb", (e.score, e.signale)


def test_zu_wenige_urteile_zaehlen_nicht():
    """4.0 Süsse aus drei Urteilen und aus dreihundert sind zwei verschiedene
    Aussagen. Unter der Schwelle fällt die Kaskade eine Stufe tiefer."""
    e = einordnen(
        "Irgendein Wein",
        struktur=Struktur(suesse=4.2, tannin=2.0, saeure=2.0, urteile=MIN_STRUKTUR_URTEILE - 1),
        stil_name="Barolo",
    )
    assert e.typ == "straff_herb"          # aus der Stiltabelle, nicht aus der Struktur
    assert "Vivino-Stil" in e.signale[0]


def test_baseline_greift_vor_der_tabelle():
    """Der Normalwert des Stils kommt von Vivino, unsere Tabelle von Hand. Was
    gerechnet ist, schlägt was gepflegt ist."""
    e = einordnen(
        "Irgendein Bolgheri",
        baseline=Struktur(suesse=1.0, tannin=4.5, saeure=3.5),
        stil_name="Tuscan Red",
    )
    assert e.stufe == 2
    assert e.typ == "straff_herb"
    assert "Normalwert" in e.signale[0]


def test_stiltabelle_als_letzter_vivino_weg():
    e = einordnen("Irgendein Sangiovese", stil_name="Brunello di Montalcino")
    assert e.typ == "straff_herb"
    assert e.stufe == 2


def test_unbekannter_stil_liefert_keinen_typ():
    """Was nicht in der Tabelle steht, wird nicht geraten — es wird protokolliert und
    wächst über die Läufe hinein."""
    assert einordnen("Wein", stil_name="Irgendein Stil, den niemand kennt").typ == UNBEKANNT


# ------------------------------------------------- Stufe 3: Notiz

def test_notiz_unter_drei_treffern_sagt_nichts():
    """Zwei Wörter in einem Werbetext sind keine Beschreibung eines Weins."""
    e = einordnen("Wein", notiz="Samtig und rund im Abgang.")
    assert e.typ == UNBEKANNT


def test_notiz_mit_genug_treffern_schaetzt_und_markiert_sich_als_schaetzung():
    e = einordnen("Wein", notiz="Vanille, Kakao und Karamell, samtig und opulent.")
    assert e.typ == "fruchtsuess"
    assert e.stufe == 3
    assert e.unsicher, "Stufe 3 muss sich als Schätzung ausweisen"


def test_straffe_notiz():
    e = einordnen("Wein", notiz="Herb, mineralisch, mit Gerbstoff und straffer Säure.")
    assert e.typ == "straff_herb"
    assert e.stufe == 3


def test_die_erste_stufe_entscheidet_und_spaetere_ueberschreiben_nicht():
    """Sonst hinge das Ergebnis daran, in welcher Reihenfolge Daten nachgeliefert
    werden, und dieselbe Zeile hiesse von Lauf zu Lauf anders."""
    e = einordnen(
        "Primitivo Appassimento",                       # Stufe 1 -> fruchtsuess
        struktur=Struktur(suesse=1.2, tannin=4.8, saeure=4.0, urteile=500),  # Stufe 2 -> straff
        notiz="Herb, mineralisch, Gerbstoff, straff.",  # Stufe 3 -> straff
    )
    assert e.typ == "fruchtsuess"
    assert e.stufe == 1


# ------------------------------------------------- Zusicherungen der Spec

def test_kein_typ_ohne_begruendung():
    """Akzeptanzkriterium 3 der Spec: kein Wein erhält einen Typ ohne mindestens einen
    Eintrag in den Signalen."""
    faelle = [
        einordnen("Primitivo Appassimento"),
        einordnen("Apothic Red"),
        einordnen("Wein", struktur=Struktur(suesse=2.0, tannin=3.0, saeure=3.0, urteile=99)),
        einordnen("Wein", baseline=Struktur(suesse=1.0), stil_name="Tuscan Red"),
        einordnen("Wein", stil_name="Barolo"),
        einordnen("Wein", notiz="Vanille, Kakao, Karamell, samtig."),
    ]
    for e in faelle:
        assert e.typ in TYPEN, e
        assert e.signale, f"{e.typ} ohne Signal"


def test_die_achse_ist_geordnet():
    """Die Reihenfolge ist Teil der Bedeutung — Filter und Farbverlauf richten sich
    danach, und ein Nachbar-Tausch wäre inhaltlich falsch."""
    assert TYPEN == ("fruchtsuess", "weich_modern", "ausgewogen", "straff_herb")
    assert typ_aus_score(1.0) == "fruchtsuess"
    assert typ_aus_score(0.25) == "weich_modern"
    assert typ_aus_score(0.0) == "ausgewogen"
    assert typ_aus_score(-1.0) == "straff_herb"


def test_unbekannt_ist_kein_punkt_auf_der_achse():
    """Es ist das Eingeständnis, keinen zu kennen — und darf darum nicht mitgefiltert
    oder mitgefärbt werden wie die vier echten Werte."""
    assert UNBEKANNT not in TYPEN


def test_die_gepflegten_listen_sind_lesbar_und_gefuellt():
    t = tabelle()
    assert len(t.suesse_tokens) >= 30
    assert len(t.stilmarken) >= 10
    assert len(t.stil_tabelle) >= 15
    assert len(t.opulent) >= 30 and len(t.straff) >= 30
    assert all(v in TYPEN for v in t.stil_tabelle.values()), "Tabelle nennt einen unbekannten Typ"
    # „Kirsche" allein ist neutral (Spec §5) — nur die Sauerkirsche gehört nach B.
    assert "kirsche" not in t.opulent and "kirsche" not in t.straff
    assert "sauerkirsche" in t.straff
    # Marketingfloskeln nie einlesen.
    for floskel in ("genuss", "charakter", "eleganz"):
        assert floskel not in t.opulent and floskel not in t.straff


def test_min_keyword_treffer_ist_dokumentiert():
    assert MIN_KEYWORD_TREFFER == 3

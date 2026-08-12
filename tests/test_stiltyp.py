"""Stil-Typ: die Einordnung nach Machart.

Die Fixtures stammen aus der Spec (§8) und aus echten Datensätzen. Stufe 1 hat dort
kein Spielraum — „Alle Fixtures der Stufe 1 werden exakt getroffen."
"""

import pytest

from winecheck.stiltyp import (
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


# ------------------------------------------------- Reihenfolge der Kaskade

def test_die_erste_stufe_entscheidet_und_spaetere_ueberschreiben_nicht():
    """Sonst hinge das Ergebnis daran, in welcher Reihenfolge Daten nachgeliefert
    werden, und dieselbe Zeile hiesse von Lauf zu Lauf anders."""
    e = einordnen(
        "Primitivo Appassimento",                       # Stufe 1 -> fruchtsuess
        struktur=Struktur(suesse=1.2, tannin=4.8, saeure=4.0, urteile=500),  # Stufe 2 -> straff
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
    assert all(v in TYPEN for v in t.stil_tabelle.values()), "Tabelle nennt einen unbekannten Typ"


def test_die_keyword_listen_sind_weg():
    """Stufe 3 ist am 12.8.2026 gestrichen. Mit ihr fallen die beiden Keyword-Listen —
    88 Zeilen gepflegte Wörter, die nie gelesen wurden: ``einordnen`` bekam von keinem
    Produktionsaufrufer eine Notiz, nur von Tests.

    Der Test hält das fest, damit die Listen nicht aus Gewohnheit zurückkehren, ohne
    dass etwas sie füttert."""
    t = tabelle()
    assert not hasattr(t, "opulent") and not hasattr(t, "straff")


# ------------------------------- Stufe 1d: Denomination ohne Herkunft (v1.1)

def test_gran_sasso_tre_autoctoni_ergibt_fruchtsuess():
    """Der Fall, an dem die Lücke aufgefallen ist. Vor diesem Patch: ``unbekannt``.

    „Gran Sasso Tre Autoctoni N.V." von Farnese — Nerello Mascalese, Montepulciano und
    Primitivo aus drei Regionen, 14.5 %, kein Jahrgang, CHF 9.95, Vivino 4.2 aus 970
    Bewertungen. Sensorisch eindeutig fruchtsüss, und jede andere Achse der Kaskade
    lief leer: kein Süsse-Token im Namen, „Vino d'Italia" ist keine Region, „Cuvée"
    ist keine Sorte, und die Händlernotiz („reich, dicht, kräftig") traf kein
    Keyword."""
    e = einordnen("Gran Sasso Tre Autoctoni N.V.", denomination="Vino d'Italia",
                  jahrgang=None, stil_name="Italian Red")
    assert e.typ == "fruchtsuess", e.signale
    assert e.stufe == 1
    assert "Denomination ohne Herkunft" in e.signale[0]
    assert "jahrgangslos" in e.signale[0]


@pytest.mark.parametrize("denom", [
    "Vino d'Italia", "Vino da Tavola", "Vin de France", "Vin de Table",
    "Deutscher Wein", "Vino de España", "Wine of Chile", "Wine of Argentina",
    "South Eastern Australia", "European Union Table Wine",
])
def test_jede_denomination_ohne_herkunft_greift(denom):
    """Diese Stufen existieren ausschliesslich, um regionenübergreifend verschneiden zu
    dürfen. Wer sie wählt, verzichtet freiwillig auf eine Herkunft, die er haben
    könnte — eine Absichtserklärung über die Machart, kein Nebensignal."""
    e = einordnen("Irgendein Wein", denomination=denom, jahrgang=None)
    assert e.typ == "fruchtsuess", (denom, e)
    assert e.stufe == 1


def test_denomination_mit_jahrgang_bleibt_die_schwaechere_aussage():
    """Ohne das zweite Zeichen — kein Jahrgang, N.V. oder eine gebaute Sorte — ist die
    Denomination allein nur ein Indiz: rund gebaut, aber nicht zwingend süss."""
    e = einordnen("Irgendein Wein", denomination="Vin de France", jahrgang=2022)
    assert e.typ == "weich_modern"
    assert e.stufe == 2


def test_cuvee_als_sorte_genuegt_auch_mit_jahrgang():
    e = einordnen("Irgendein Verschnitt", denomination="Vino d'Italia", jahrgang=2021,
                  stil_name="Italian Red Blend")
    assert e.typ == "fruchtsuess"
    assert e.stufe == 1
    assert "Sorte" in e.signale[0]


def test_eine_echte_appellation_loest_1d_nicht_aus():
    """Gegenprobe: „Bolgheri Superiore" ist eine Herkunft und keine Absichtserklärung."""
    assert einordnen("Wein", denomination="Bolgheri Superiore", jahrgang=None).typ == UNBEKANNT
    assert einordnen("Wein", denomination="Vino Nobile di Montepulciano").typ == UNBEKANNT


def test_gemessener_wert_schlaegt_die_absichtserklaerung():
    """1d steht als letzte Regel in Stufe 1. Ein Restzuckerwert ist eine Tatsache über
    den Wein im Glas, die Denomination eine Absicht des Abfüllers."""
    e = einordnen("Irgendein Wein", denomination="Vin de France", jahrgang=None,
                  datenblatt="Restzucker 1,0 g/l, Gesamtsäure 6,5 g/l")
    assert e.typ == "straff_herb", e.signale


def test_keine_denomination_ohne_herkunft_bleibt_unbekannt():
    """Akzeptanzkriterium der Version 1.1: Weine mit einer Denomination ohne Herkunft
    dürfen nie ``unbekannt`` ergeben."""
    from winecheck.stiltyp import tabelle as _tab

    for d in _tab().denominationen:
        for jg in (None, 2022):
            e = einordnen("Irgendein Wein", denomination=d, jahrgang=jg)
            assert e.typ != UNBEKANNT, (d, jg)
            assert e.signale



# --------------------------------------------- Kalibrierung an echten Daten

def test_die_normalwerte_sind_gemessen_und_zentrieren_die_achse():
    """Die Schwellen der Spec (+0.4 / +0.1 / −0.1) setzen eine zentrierte Achse voraus.
    Ein geschätzter Normalfall lieferte die nicht: 33 von 39 Weinen landeten auf
    ``straff_herb``, weil Süsse zu hoch und Säure zu tief angesetzt waren und alle
    Fehler in dieselbe Richtung drückten.

    Die Werte sind jetzt die Mediane über 839 Weine des Bestands. Ein Wein, der genau
    dort liegt, muss ``ausgewogen`` ergeben — sonst ist die Achse wieder verschoben."""
    from winecheck.stiltyp import NORMAL_SAEURE, NORMAL_SUESSE, NORMAL_TANNIN

    e = einordnen("Durchschnittswein", struktur=Struktur(
        suesse=NORMAL_SUESSE, tannin=NORMAL_TANNIN, saeure=NORMAL_SAEURE, urteile=500))
    assert e.typ == "ausgewogen", (e.score, e.signale)
    assert abs(e.score) < 1e-9


@pytest.mark.parametrize("suesse,tannin,saeure,erwartet", [
    # Barolo-Profil: wenig Süsse, viel Tannin und Säure.
    (1.4, 4.3, 4.1, "straff_herb"),
    # Amarone-Profil: deutlich süsser, weiches Tannin.
    (3.2, 2.9, 2.8, "fruchtsuess"),
])
def test_bekannte_machart_wird_richtig_eingeordnet(suesse, tannin, saeure, erwartet):
    """Gegenprobe der Kalibrierung an echten Profilen. Im Bestand ergeben alle 20
    Barolo und 27 von 28 Brunello ``straff_herb``, alle 17 Amarone, 9 Appassimento,
    7 Ripasso und 26 Primitivo ``fruchtsuess``."""
    e = einordnen("Wein", struktur=Struktur(suesse=suesse, tannin=tannin,
                                            saeure=saeure, urteile=500))
    assert e.typ == erwartet, (e.score, e.signale)

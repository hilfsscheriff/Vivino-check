

# ---------------------------------------------------------------- Champagner
# Von den 85 Schaumweinen im Bestand sind 39 Champagner. Gegenüber einem Prosecco
# ist das eine andere Kaufentscheidung — andere Preisklasse, andere Herkunft.

def test_champagner_ist_eine_eigene_sorte():
    from winecheck.names import wine_style

    assert wine_style("Champagne Brut Réserve Deutz") == "champagner"
    assert wine_style("Ruinart Blanc de Blancs") == "champagner"
    assert wine_style("Dom Pérignon 2013") == "champagner"


def test_anderer_schaumwein_bleibt_schaumwein():
    """Crémant, Cava und Franciacorta entstehen nach derselben Methode, dürfen sich
    aber nicht Champagner nennen. Wer hier filtert, meint die Appellation."""
    from winecheck.names import wine_style

    for name in ("Prosecco Superiore DOCG", "Cava Brut Nature",
                 "Crémant d'Alsace Brut", "Franciacorta DOCG Satèn"):
        assert wine_style(name) == "schaumwein", name


def test_vivino_kennt_champagner_nicht_als_eigene_art():
    """Dort ist alles type_id 3 "Sparkling". Ohne Verfeinerung über den Namen
    landeten ausgerechnet die sicher zugeordneten Champagner in der Sammelkachel."""
    from winecheck.names import wine_style

    assert wine_style("Ruinart Blanc de Blancs", 3) == "champagner"
    assert wine_style("Prosecco Superiore DOCG", 3) == "schaumwein"
    # Die Farbe aus Vivino bleibt unangetastet.
    assert wine_style("Barolo DOCG", 1) == "rot"


def test_haeuser_mit_mehrdeutigem_namen_sind_nicht_dabei():
    """Mumm Napa und Roederer Estate machen Schaumwein, aber keinen Champagner.

    Ein falscher Treffer wäre hier schlimmer als ein fehlender — die Kachel soll
    halten, was sie verspricht.
    """
    from winecheck.names import wine_style

    # Ohne Schaumwein-Wort im Namen bleiben sie "unbekannt" — das ist bestehendes
    # Verhalten. Wichtig ist hier nur: nicht "champagner".
    assert wine_style("Mumm Napa Brut Prestige") != "champagner"
    assert wine_style("Roederer Estate Brut Anderson Valley") != "champagner"
    # Auch mit Vivinos Schaumwein-Kennung dürfen sie nicht umkippen.
    assert wine_style("Mumm Napa Brut Prestige", 3) == "schaumwein"
    assert wine_style("Roederer Estate Brut Anderson Valley", 3) == "schaumwein"
    assert wine_style("Louis Roederer Collection 244") == "champagner"


# ------------------------------------------------------------------- Herkunftsland
def test_land_aus_dem_namen():
    """Manche Händler schreiben das Land an — dann gilt es."""
    from winecheck.names import land

    assert land("Amarone Classico, Italien") == "Italien"
    assert land("Rioja Reserva, Spanien") == "Spanien"


def test_land_aus_der_vinum_region():
    """Der Normalfall: kaum ein Händler schreibt „Frankreich" an einen Bordeaux."""
    from winecheck.names import land

    assert land("Château Lafleur Pomerol", "Bordeaux St-Émilion/Pomerol/Fronsac") == "Frankreich"
    assert land("Chianti Classico Riserva", "Toskana -Chianti Classico") == "Italien"
    assert land("Dôle Blanche", "Wallis") == "Schweiz"


def test_der_name_hat_vorrang_vor_der_region():
    """Der Name beschreibt den Wein selbst; die Region kommt aus einer Zuordnung,
    die schiefgehen kann."""
    from winecheck.names import land

    assert land("Merlot Ticino, Schweiz", "Toskana -Chianti Classico") == "Schweiz"


def test_ohne_hinweis_bleibt_das_land_leer():
    """Ein geratenes Land wäre schlimmer als eine Lücke: wer nach „Italien" filtert,
    will keine Portugiesen sehen."""
    from winecheck.names import land

    assert land("Irgendein Wein ohne Herkunft") == ""

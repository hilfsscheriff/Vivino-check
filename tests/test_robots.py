"""robots.txt mit Wildcards.

Das ist die eine Stelle, an der eine Lücke nicht Daten kostet, sondern eine Zusage
bricht: dieses Projekt sagt in jeder Quellenbeschreibung, dass es robots.txt
respektiert und keinen Schutz umgeht. Wenn der Prüfer Regeln übersieht, ist die
Aussage falsch, ohne dass es jemandem auffällt.

Genau das war der Fall. ``urllib.robotparser`` kennt keine Wildcards und vergleicht
mit ``startswith`` — ``Disallow: /*brands=*`` galt damit als Regel über Pfade, die
wörtlich so beginnen, also über keinen einzigen.
"""

from winecheck.fetching import Robots


def _r(text: str, ua: str = "WeinCheck/1.0") -> Robots:
    return Robots.parse(text, ua)


# ------------------------------------------------- Die gefundene Lücke

def test_stern_in_der_mitte_wird_beachtet():
    """Der Kern des Fehlers. Mit ``urllib.robotparser`` war dieser Pfad erlaubt."""
    r = _r("User-agent: *\nDisallow: /*brands=*")
    assert not r.allows("https://x/de/catalog.data?brands=121")
    assert r.allows("https://x/de/catalog.data?a=true")


def test_query_verbot_greift():
    """``web.transgourmet.ch`` verbietet ``searchTerm``. Der Prodega-Adapter fragte
    trotzdem damit ab — nicht aus Absicht, sondern weil der Prüfer schwieg."""
    r = _r("User-agent: *\nDisallow: /*?searchTerm=*")
    assert not r.allows("https://x/de/prodega-easy/catalog.data?searchTerm=wein&a=true")
    assert r.allows("https://x/de/prodega-easy/catalog.data?a=true&page=3")


def test_moevenpick_muster():
    """Mövenpick verbietet alle Query-Strings und erlaubt nur ``p`` und ``page``.
    Diese Entscheidung stand im Projekt von Hand fest; jetzt erzwingt sie der Prüfer.
    """
    r = _r("User-agent: *\nDisallow: /*?*\nAllow: *?p=*\nAllow: *?page=*")
    assert r.allows("https://x/de/aktuelle-angebote.html")
    assert r.allows("https://x/de/aktuelle-angebote.html?p=7")
    assert not r.allows("https://x/de/aktuelle-angebote.html?mpw_has_special_price=1")


# ------------------------------------------------- Vorrang der Regeln

def test_die_laengere_regel_gewinnt():
    """Google-Semantik: nicht die Reihenfolge entscheidet, sondern die Länge des
    Musters. Sonst hinge das Urteil daran, wie ein Shop seine Datei sortiert."""
    r = _r("User-agent: *\nDisallow: /shop/\nAllow: /shop/katalog/")
    assert not r.allows("https://x/shop/warenkorb")
    assert r.allows("https://x/shop/katalog/wein")


def test_bei_gleicher_laenge_gewinnt_allow():
    r = _r("User-agent: *\nDisallow: /a/b\nAllow: /a/b")
    assert r.allows("https://x/a/b")


def test_ohne_passende_regel_ist_alles_erlaubt():
    r = _r("User-agent: *\nDisallow: /intern/")
    assert r.allows("https://x/de/katalog")


def test_leeres_disallow_erlaubt_alles():
    """``Disallow:`` ohne Wert heisst ausdrücklich „keine Einschränkung" und darf
    nicht als Sperre des Wurzelpfads gelesen werden."""
    r = _r("User-agent: *\nDisallow:")
    assert r.allows("https://x/irgendwas")


# ------------------------------------------------- Anker und Gruppen

def test_dollar_ankert_am_ende():
    r = _r("User-agent: *\nDisallow: /*.pdf$")
    assert not r.allows("https://x/prospekt.pdf")
    assert r.allows("https://x/prospekt.pdf.html")


def test_benannter_block_schlaegt_den_sternblock():
    """Shops sperren einzelne Bots hart aus. Diese Sperren dürfen uns nicht treffen —
    und unsere eigene, falls sie dasteht, muss gelten."""
    text = ("User-agent: *\nDisallow:\n\n"
            "User-agent: AhrefsBot\nDisallow: /\n\n"
            "User-agent: weincheck\nDisallow: /gesperrt/")
    r = _r(text, "WeinCheck/1.0")
    assert r.allows("https://x/katalog")
    assert not r.allows("https://x/gesperrt/seite")


def test_fremde_bot_sperren_treffen_uns_nicht():
    text = "User-agent: *\nDisallow:\n\nUser-agent: AhrefsBot\nDisallow: /"
    r = _r(text, "WeinCheck/1.0")
    assert r.allows("https://x/irgendwas")


def test_mehrere_agenten_teilen_einen_block():
    """Aufeinanderfolgende ``User-agent``-Zeilen gehören zur selben Gruppe."""
    text = "User-agent: foo\nUser-agent: weincheck\nDisallow: /nein/"
    r = _r(text, "WeinCheck/1.0")
    assert not r.allows("https://x/nein/da")


def test_kommentare_und_leerzeilen_stoeren_nicht():
    r = _r("# Kopf\nUser-agent: *   # wir alle\n\nDisallow: /intern/ # nicht hierher")
    assert not r.allows("https://x/intern/x")
    assert r.allows("https://x/extern/x")

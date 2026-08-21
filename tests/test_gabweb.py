"""DIVO und Alloboissons — dieselbe Plattform, zwei entgegengesetzte Fallen.

Bei DIVO liegt zwischen 21 Weinen ein Degustationskarton: er steht in der
Warengruppe „Flaschenweine", heisst „Zwischenstopp am Mittelmeer", kostet CHF 98 und
hat keine Flaschengrösse. Über den Namen ist er nicht zu erkennen — über die
Warengruppe der Plattform und die fehlende Kapazität schon.

Bei Alloboissons liegen zwölf Weine zwischen Bier, Evian und Eistee, und der
Wortfilter versagt in **beide** Richtungen: „Féchy", „Gamaret-Garanoir" und „Charme
Spumante" tragen kein Weinwort, „Boxer old spéciale" und „Coors" tragen kein
Gegenwort. Entschieden wird darum über die Warengruppe des Shops.

Und der Preis: Alloboissons verkauft keine einzelnen Flaschen. Der Kacheltext nennt
CHF 14.50 je Flasche, zu zahlen sind CHF 87.00 für sechs. Steht im Bericht der
Flaschenbetrag als Zahlbetrag, ist er um den Faktor sechs falsch.
"""

import html as html_entities
import json

import pytest

from winecheck.adapters.gabweb import GabWebAdapter
from winecheck.config import SourceConfig
from winecheck.models import PriceConfidence

SEITE = "https://www.divo.ch/de/sortiment.html?promotions=true"


def _cfg(key="divo", wine_only=True):
    return SourceConfig(key=key, name=key, adapter="gabweb", domain=f"{key}.ch",
                        vat_included=True, price_basis="bottle", wine_only=wine_only)


@pytest.fixture
def adapter():
    return GabWebAdapter(_cfg(), fetcher=None)


@pytest.fixture
def allo():
    return GabWebAdapter(_cfg("alloboissons", wine_only=False), fetcher=None)


def _produkt(
    *,
    id="91967 75 2024",
    name="Anthoinette 2024",
    description="Bordeaux Blanc AOC",
    extra="Château Castera",
    gruppe="Flaschenweine",
    untergruppe=None,
    kapazitaet=75,
    einzeln=True,
    menge=6,
    flasche="15.20",
    karton="91.20",
    regular_flasche="16.90",
    regular_karton="101.40",
    instead=None,
    verkaeuflich=True,
    nicht_lieferbar=False,
    verzoegerung=False,
):
    posten = {"item_id": id, "item_name": name, "item_category": gruppe}
    if untergruppe:
        posten["item_category2"] = untergruppe
    p = {
        "id": id,
        "name": name,
        "description": description,
        "extraDescription": extra,
        "isSellable": verkaeuflich,
        "isTemporarilyUnavailable": nicht_lieferbar,
        "isSellableByUnit": einzeln,
        "hasDeliveryDelay": verzoegerung,
        "conditioningDetail": {"name": "Flasche", "capacity": kapazitaet},
        "conditioningDescription": f"Flasche {kapazitaet} cl",
        "packagingDescription": f"Karton {menge}x{kapazitaet} cl",
        "packaging": {"unit": 43618, "main": 43617},
        "packagingDetails": {
            "43618": {"id": 43618, "label": {"singular": "Flasche"}, "quantity": 1,
                      "isSellable": einzeln},
            "43617": {"id": 43617, "label": {"singular": "Karton"}, "quantity": menge,
                      "isSellable": True},
        },
        "price": {"43618": flasche, "43617": karton},
        "promotion": {"percent": 10,
                      "regularPrice": {"43618": regular_flasche, "43617": regular_karton}},
        "gAData": {"currency": "CHF", "items": [posten]},
    }
    if instead:
        p["insteadOfPrice"] = instead
    return p


def _seite(*produkte, vorlage="/de/sortiment/artikel-0.html"):
    """Baut die Aktionsseite so, wie der Shop sie ausliefert: JSON in HTML-Entities."""
    kacheln = "".join(
        f'<div x-data="product({html_entities.escape(json.dumps(p, ensure_ascii=False))})">'
        f"<article>{p['name']}</article></div>"
        for p in produkte
    )
    return (f'<html><body><div x-data="productDetailUri(&quot;{vorlage}&quot;)">'
            f"{kacheln}</div></body></html>")


def _eins(adapter, *produkte):
    offers = adapter.parse(_seite(*produkte), SEITE)
    assert len(offers) == 1, [o.name for o in offers]
    return offers[0]


# -- Der Degustationskarton -------------------------------------------------
def test_der_degustationskarton_ist_kein_wein(adapter):
    """CHF 98, Warengruppe „Flaschenweine", keine Flaschengrösse — und kein Wein.

    Käme er durch, stünde eine gemischte Kiste als teuerster „Wein" in der Liste,
    ohne Fremdbewertung und mit einem Preis, der sich auf nichts bezieht.
    """
    karton = _produkt(id="93959 2026 08", name="Zwischenstopp am Mittelmeer",
                      description="Degustationskarton", extra="August 2026",
                      untergruppe="Degustationkarton", kapazitaet=0, menge=1)
    assert adapter.parse(_seite(karton), SEITE) == []


def test_ohne_flaschengroesse_kein_angebot(adapter):
    """Die allgemeinere Prüfung: ohne Kapazität ist nichts auf 75 cl umzurechnen.

    Sie greift auch dann, wenn die Untergruppe einmal anders heisst — die
    Plattform ist mehrsprachig und benennt ihre Gruppen um.
    """
    assert adapter.parse(_seite(_produkt(kapazitaet=0)), SEITE) == []


# -- Warengruppe statt Wortfilter ------------------------------------------
def test_bier_und_eistee_fallen_ueber_die_warengruppe_heraus(allo):
    """„Boxer old spéciale" und „Nestea Lemon" tragen kein Gegenwort im Namen."""
    bier = _produkt(id="64030", name="Boxer old spéciale vp", description="", extra="",
                    gruppe="Biere und Mostgetränke", kapazitaet=25, einzeln=False)
    eistee = _produkt(id="16056", name="Nestea Lemon 4x6-pk", description="", extra="",
                      gruppe="Alkoholfreie Getränke", kapazitaet=50, einzeln=False)
    assert allo.parse(_seite(bier, eistee), SEITE) == []


def test_wein_ohne_weinwort_bleibt_drin(allo):
    """„Féchy" ist eine Waadtländer Appellation und kein Weinwort.

    Der Wortfilter hätte diesen Wein weggeworfen — hier entscheidet die Gruppe.
    """
    wein = _produkt(id="91488 75 2024", name="Féchy Bertrand de Mestral La Côte AOC 2024",
                    description="", extra="Uvavins cave de la côte", einzeln=False)
    o = _eins(allo, wein)
    assert o.vintage == 2024


def test_unbekannte_gruppe_muss_sich_ausweisen(adapter):
    """DIVO führt „Assyrtiko 2024" intern unter „Absent de la liste".

    Eine unbekannte Gruppe gilt nicht ungeprüft als Wein: „Laconia IGP" besteht die
    Weinprüfung, ein Korkenzieher in derselben Gruppe nicht.
    """
    wein = _produkt(id="91626 75 2024", name="Assyrtiko 2024", description="Laconia IGP",
                    extra="Monemvasia Winery", gruppe="Absent de la liste")
    zubehoer = _produkt(id="70001", name="Korkenzieher Classic", description="", extra="",
                        gruppe="Absent de la liste")
    offers = adapter.parse(_seite(wein, zubehoer), SEITE)
    assert [o.vintage for o in offers] == [2024]


def test_alkoholfreier_wein_bleibt_draussen(adapter):
    """Untergruppe „Ohne Alkohol": hier nicht gemeint — und mit 2.6 % statt 8.1 % MwSt.

    Mit dem Alkoholsatz gerechnet stünde er 5.4 % zu teuer da.
    """
    assert adapter.parse(_seite(_produkt(untergruppe="Ohne Alkohol")), SEITE) == []


# -- Preis: was tatsächlich zu zahlen ist ----------------------------------
def test_bei_kartonzwang_zaehlt_der_kartonpreis(allo):
    """Alloboissons verkauft keine einzelnen Flaschen.

    Der Vergleichspreis bleibt die Flasche (14.50), der Zahlbetrag ist der Karton
    (87.00). Stünde 14.50 als Zahlbetrag da, wäre er um den Faktor sechs falsch.
    """
    o = _eins(allo, _produkt(id="92332 75 2023", name="Mòmò Merlot 2023",
                             description="Ticino DOC - Delea", extra="",
                             einzeln=False, flasche="14.50", karton="87.00",
                             regular_flasche="18.00", regular_karton="108.00"))
    assert o.price_per_bottle_incl_vat == 14.50
    assert o.price_raw == 87.00
    assert o.roh_ist_gebinde is True
    assert o.units == 6
    assert "nur im Karton à 6" in o.source_note


def test_bei_einzelverkauf_zaehlt_die_flasche(adapter):
    """DIVO verkauft einzeln — dann ist der Zahlbetrag der Flaschenpreis."""
    o = _eins(adapter, _produkt())
    assert o.price_per_bottle_incl_vat == 15.20
    assert o.price_raw == 15.20
    assert o.roh_ist_gebinde is False
    assert "Karton" not in o.source_note


def test_der_streichpreis_liegt_auf_derselben_bezugsgroesse(allo):
    """Karton gegen Karton: 87.00 zu 108.00 sind 19 %, nicht 84 % gegen die Flasche."""
    o = _eins(allo, _produkt(einzeln=False, flasche="14.50", karton="87.00",
                             regular_flasche="18.00", regular_karton="108.00"))
    assert o.reference_price == 18.00
    assert o.discount_percent is not None and 19.0 <= o.discount_percent <= 19.5


def test_referenzpreis_auch_ohne_insteadofprice(allo):
    """Alloboissons führt nur ``promotion.regularPrice``, DIVO beides."""
    o = _eins(allo, _produkt(einzeln=False))
    assert o.reference_price is not None


def test_halbe_flasche_wird_hochgerechnet_der_zahlbetrag_nicht(adapter):
    """37.5 cl für CHF 25.90 sind 51.80 je 75 cl — zu zahlen bleiben 25.90."""
    o = _eins(adapter, _produkt(id="91930 38 2012", name="Monemvasia Malvasia Vin Liastos 2012",
                                kapazitaet=37.5, flasche="25.90", regular_flasche="29.10"))
    assert o.price_per_bottle_incl_vat == 51.80
    assert o.price_raw == 25.90
    assert o.bottle_ml == 375
    assert o.price_confidence is PriceConfidence.MEDIUM


def test_nicht_lieferbares_wird_nicht_angeboten(adapter):
    """Ein Wein, den man nicht bestellen kann, ist keine Aktion."""
    assert adapter.parse(_seite(_produkt(nicht_lieferbar=True)), SEITE) == []
    assert adapter.parse(_seite(_produkt(verkaeuflich=False)), SEITE) == []


def test_lieferverzoegerung_steht_in_der_notiz(adapter):
    o = _eins(adapter, _produkt(verzoegerung=True))
    assert "Lieferverzögerung" in o.source_note


# -- Name, Jahrgang, Link --------------------------------------------------
def test_produzent_und_appellation_kommen_in_den_namen(adapter):
    """„Anthoinette 2024" allein ist bei Vivino nicht zu finden.

    Die Appellation trägt zudem die Region, nach der die Preis-Leistungs-Rechnung
    gruppiert.
    """
    o = _eins(adapter, _produkt())
    assert o.name == "Anthoinette 2024 Château Castera Bordeaux Blanc AOC"


def test_eine_bereits_enthaltene_angabe_wird_nicht_wiederholt(allo):
    """Doppelt genannt wird nichts, was schon im Namen steht.

    Geprüft wird ganze Angabe gegen ganze Angabe, nicht Wort gegen Wort. Wortweises
    Entdoppeln wäre schlimmer als das Problem: aus dem Produzenten "Monemvasia
    Winery" hinter dem Wein "Monemvasia 2025" würde ein nacktes "Winery". Ein
    einzelnes doppeltes Wort am Namensende kostet dagegen nichts — die Weinsuche
    vergleicht Wortmengen und ist reihenfolgeunabhängig.
    """
    o = _eins(allo, _produkt(id="92332 75 2023", name="Mòmò Merlot Ticino DOC 2023",
                             description="Ticino DOC", extra="Delea", einzeln=False))
    assert o.name == "Mòmò Merlot Ticino DOC 2023 Delea"


def test_der_produzent_bleibt_ganz(adapter):
    """"Monemvasia Winery" hinter "Monemvasia 2025" — der Name bleibt lesbar."""
    o = _eins(adapter, _produkt(id="91627 75 2025", name="Monemvasia 2025",
                                description="Laconia IGP", extra="Monemvasia Winery"))
    assert o.name == "Monemvasia 2025 Monemvasia Winery Laconia IGP"


def test_jahrgang_kommt_aus_der_artikelnummer(adapter):
    """„91967 75 2024" — strukturiert statt aus dem Namen geraten."""
    o = _eins(adapter, _produkt(id="91967 75 2024", name="Anthoinette"))
    assert o.vintage == 2024


def test_ohne_jahrgang_bleibt_die_luecke(adapter):
    """„98811 75" ist ein Champagner ohne Jahrgang — dann steht dort nichts."""
    o = _eins(adapter, _produkt(id="98811 75", name="Champagne Bernard Remy Rosé Brut",
                                description="Champagne AOC", extra="Bernard Remy"))
    assert o.vintage is None


def test_der_produktlink_wird_wie_im_shop_gebaut(adapter):
    """Das Shop-Skript ersetzt die erste „0" der Vorlage durch die Artikelnummer.

    Die enthält Leerzeichen; unkodiert wäre der Link im Bericht unbrauchbar — die
    Lehre aus den toten Flaschenpost-Links.
    """
    o = _eins(adapter, _produkt())
    assert o.url == "https://www.divo.ch/de/sortiment/artikel-91967%2075%202024.html"


def test_ohne_linkvorlage_lieber_kein_link(adapter):
    """Ein geratener Produktlink ist schlimmer als keiner — und wird gemeldet."""
    html = _seite(_produkt()).replace('x-data="productDetailUri(&quot;'
                                      '/de/sortiment/artikel-0.html&quot;)"', "")
    offers = adapter.parse(html, SEITE)
    assert len(offers) == 1 and offers[0].url == ""
    assert any("Produktlink" in h for h in adapter._hinweise)


# -- Eine defekte Kachel ist eine Lücke, kein „ok" -------------------------
def test_unlesbare_kachel_wird_gemeldet(adapter):
    """Sonst sähe ein halb geparster Lauf aus wie ein vollständiger.

    Genau so blieb Denners umbenanntes Kachel-Etikett wochenlang unbemerkt: der
    Lauf meldete brav „ok".
    """
    html = _seite(_produkt()).replace("<div x-data=\"product(", "<div x-data=\"product({&quot;id&quot;:)", 1)
    offers = adapter.parse(html, SEITE)
    assert offers == []
    assert any("nicht lesbar" in h for h in adapter._hinweise)

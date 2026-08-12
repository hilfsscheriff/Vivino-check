"""Vivinos eigene Aktionen — die Quelle, die ihre Note mitbringt.

Zwei Dinge müssen stimmen: die Preisbasis (nur die 0,75-l-Flasche) und die
Trennung von den Schweizer Händlern.
"""

import pytest

from winecheck.adapters.vivinoshop import VivinoShopAdapter, _name
from winecheck.config import SourceConfig
from winecheck.report.site import _add_value_scores


@pytest.fixture
def adapter():
    cfg = SourceConfig(key="vivinoshop", name="Vivino Aktionen",
                       adapter="vivinoshop", domain="vivino.com", wine_only=True)
    return VivinoShopAdapter(cfg, fetcher=None)


def _treffer(*, betrag=10.0, vorher=20.0, flasche=1, note=4.2, jahr=2020, url=None,
             bottle_quantity=None):
    preis = {"id": 333, "amount": betrag, "discounted_from": vorher,
             "bottle_type": {"id": flasche, "name": "Flasche (0,75 l)"},
             "sku": "VI-1-CS"}
    if url is not None:
        preis["url"] = url
    if bottle_quantity is not None:
        preis["bottle_quantity"] = bottle_quantity
    return {
        "vintage": {
            "id": 111, "year": jahr,
            "wine": {"id": 222, "name": "Rioja Reserva", "type_id": 1,
                     "winery": {"name": "Imperial"}},
            "statistics": {"ratings_average": note, "ratings_count": 900},
        },
        "price": preis,
    }


def test_weingut_kommt_vor_den_weinnamen():
    """Vivino trennt Weingut und Wein; nur der Weinname ergäbe "Rioja Reserva"."""
    assert _name(_treffer()) == "Imperial Rioja Reserva"


def test_normale_flasche_wird_uebernommen(adapter):
    o = adapter._offer(_treffer())
    assert o.price_per_bottle_incl_vat == 10.0
    assert o.reference_price == 20.0
    assert o.bottle_ml == 750
    assert o.price_confidence.value == "high"


@pytest.mark.parametrize("flasche", [2, 3, 5])
def test_andere_gebinde_werden_uebersprungen(adapter, flasche):
    """Magnum, Halbflasche, Karton: die Antwort sagt nicht, wie viele Flaschen
    darin stecken. Ein geratener Literpreis erzeugt einen Scheinsieger."""
    assert adapter._offer(_treffer(flasche=flasche)) is None


def test_ohne_abschlag_kein_angebot(adapter):
    assert adapter._offer(_treffer(betrag=20.0, vorher=20.0)) is None
    assert adapter._offer(_treffer(betrag=25.0, vorher=20.0)) is None


def test_note_wird_zum_saeen_gesammelt(adapter):
    adapter._offer(_treffer(note=4.4))
    assert adapter.bewertungen == [{
        "name": "Imperial Rioja Reserva", "vintage": 2020, "wine_id": 222,
        "rating": 4.4, "rating_count": 900,
        "url": "https://www.vivino.com/w/222",
        # Die Farbe muss mit. Ohne sie fielen 400 Weine auf "unbekannt" zurück,
        # weil Namen wie "Astrale Special Edition" kein Farbwort enthalten.
        "wine_type_id": 1,
        # Machart und Herkunft ebenso — ohne sie blieben ausgerechnet diese Weine
        # ohne Stil-Typ, siehe den Test darunter.
        "style_name": "", "country": "", "region_name": "",
        "taste": {}, "style_baseline": {},
    }]


def test_die_saat_traegt_machart_und_herkunft(adapter):
    """Für diese Weine fragt ``rate`` bei Vivino gar nicht mehr nach — die Antwort kam
    mit dem Angebot. Genau deshalb muss die Saat alles mitbringen, was der Stil-Typ
    braucht: sonst bleiben ausgerechnet die Weine mit der verlässlichsten Note ohne
    Typ. Gemessen waren es 703 von 1452."""
    t = _treffer()
    t["vintage"]["wine"]["style"] = {
        "name": "Rioja Red", "baseline_structure": {"sweetness": 1.5, "tannin": 3.5},
    }
    t["vintage"]["wine"]["region"] = {"name": "Rioja", "country": {"name": "Spanien"}}
    t["vintage"]["wine"]["taste"] = {"structure": {
        "sweetness": 2.1, "tannin": 3.4, "acidity": 3.2, "user_structure_count": 640,
    }}
    adapter._offer(t)
    b = adapter.bewertungen[0]
    assert b["style_name"] == "Rioja Red"
    assert b["country"] == "Spanien"
    assert b["region_name"] == "Rioja"
    assert b["taste"] == {"sweetness": 2.1, "tannin": 3.4, "acidity": 3.2, "count": 640.0}
    assert b["style_baseline"] == {"sweetness": 1.5, "tannin": 3.5}


def test_der_gesaete_eintrag_traegt_die_felder_in_den_cache(adapter):
    """Gegenprobe eine Schicht tiefer: was gesammelt wurde, muss auch im Cache landen,
    sonst hilft es dem Typ nichts."""
    t = _treffer()
    t["vintage"]["wine"]["region"] = {"name": "Vino d'Italia", "country": {"name": "Italien"}}
    adapter._offer(t)

    class _Cache:
        def __init__(self):
            self.eintraege = []

        def put_rating(self, quelle, name, jahrgang, payload, status=""):
            self.eintraege.append(payload)

    cache = _Cache()
    assert adapter.saee_bewertungen(cache) == 1
    d = cache.eintraege[0]
    assert d["region_name"] == "Vino d'Italia"
    assert d["country"] == "Italien"


# -- Trennung der beiden Warenwelten ---------------------------------------
def _wein(preis, note, **kw):
    return {"price": preis, "rating": note, "ratingCount": 500, **kw}


def test_wein_in_beiden_welten_wird_im_schweizer_niveau_gerechnet():
    """"10 Vendemmie Tenuta Ulisse" verkaufen Schubi und Vivino.

    Mit einem Entweder-oder-Kennzeichen verschwand er aus der Schweizer Ansicht,
    obwohl er dort zu kaufen ist.
    """
    beide = _wein(30.0, 4.4, marketplace=True, swiss=True)
    wines = [_wein(10.0 + i, 3.5 + i * 0.05, swiss=True) for i in range(14)] + [beide]
    _add_value_scores(wines)
    # Er wurde gerechnet, also lag er in einer Gruppe — und zwar in der Schweizer,
    # denn die Marktplatz-Gruppe wäre mit einem einzigen Wein zu klein gewesen.
    assert "valueScore" in beide


def test_die_beiden_gruppen_werden_nicht_vermischt():
    """Getrennte Regressionen: der Marktplatz liefert aus dem Ausland, der
    Schweizer Handel nicht. Eine gemeinsame Kurve machte den systematischen
    Preisunterschied zu einer Aussage über die einzelnen Weine."""
    handel = [_wein(10.0 + i, 3.5, swiss=True) for i in range(14)]
    markt = [_wein(100.0 + i, 4.5, marketplace=True) for i in range(14)]
    _add_value_scores(handel + markt)
    # Innerhalb jeder Gruppe sind alle Noten gleich, also liegt niemand über der
    # Erwartung. Gemeinsam gerechnet stünden die teuren Marktplatzweine weit oben.
    assert all(abs(w.get("valueScore", 0)) < 0.2 for w in handel + markt)


def test_der_verweis_fuehrt_an_das_angebot(adapter):
    """Von einem Nutzer gemeldet: „preis finde ich nicht".

    Der Verweis führte auf die *Weinseite*, nachgebaut als ``/w/<id>?year=<jahr>``. Am
    Pio Cesare Barolo 2016 geprüft, Angebot CHF 45.47: die Seite lieferte die Daten des
    **2018er** zu CHF 84.03 von einem anderen Händler. Der genannte Preis stand nirgends,
    und ein Preis, den man nicht nachsehen kann, ist keiner.

    Die Antwort gibt die Adresse mit — bei ``type: vc`` die Produktseite des Händlers, bei
    ``type: xdo`` eine jahrgangsgenaue ``/wines/<id>``-Adresse. Sie wird genommen, nicht
    nachgebaut.
    """
    o = adapter._offer(_treffer(url="https://www.gerstl.ch/2019-irgendwas-esp-1"))
    assert o.url == "https://www.gerstl.ch/2019-irgendwas-esp-1", o.url


def test_unverschluesselte_adressen_werden_angehoben(adapter):
    """``http`` kommt in der Antwort vor. Unverändert übernommen verlinkt die Seite
    unverschlüsselt."""
    o = adapter._offer(_treffer(url="http://www.vivino.com/wines/91068564"))
    assert o.url == "https://www.vivino.com/wines/91068564", o.url


def test_ohne_adresse_faellt_es_auf_die_weinseite_mit_jahrgang_zurueck(adapter):
    """Der Rückfall, und warum er den Jahrgang trägt: von einem Nutzer gemeldet zu „The
    Standish The Relic Shiraz-Viognier" — unser Angebot ist der 2019er zu CHF 53.78 statt
    95.92, die Weinseite eröffnete mit dem 2021er zu CHF 99.50 ohne Abschlag. Der Rabatt
    stimmte, er galt für eine andere Flasche. Besser als kein Verweis, schlechter als die
    Adresse aus der Antwort."""
    o = adapter._offer(_treffer(jahr=2019))
    assert o.url == "https://www.vivino.com/w/222?year=2019", o.url


def test_die_weinadresse_der_saat_bleibt_ohne_jahrgang(adapter):
    """Gegenprobe: der Saat-Eintrag identifiziert den *Wein*, und seine Note gilt oft
    über alle Jahrgänge. Ein Jahrgang in dieser Adresse wäre eine Behauptung, die die
    Note nicht deckt — und die Händleradresse des Angebots erst recht nicht."""
    adapter._offer(_treffer(jahr=2019, url="https://www.gerstl.ch/irgendwas"))
    assert adapter.bewertungen[0]["url"] == "https://www.vivino.com/w/222"


def test_ohne_jahrgang_bleibt_die_adresse_wie_sie_war(adapter):
    o = adapter._offer(_treffer(jahr=None))
    assert o.url == "https://www.vivino.com/w/222", o.url


def test_die_saat_traegt_dieselben_felder_wie_der_suchweg(adapter):
    """Es gab zwei Wege, wie ein Ergebnis in den Cache kommt, und der zweite baute
    seine Feldliste von Hand nach. Als Machart und Herkunft dazukamen, bekam der
    reguläre Weg sie und dieser nicht — 703 von 1452 Weinen blieben ohne Stil-Typ,
    ausgerechnet die mit der verlässlichsten Note.

    Dieser Test ist die Regressionssperre: beide Pfade müssen dieselbe Feldmenge
    schreiben. Ein künftiges Feld kann damit nur noch an einer Stelle vergessen
    werden."""
    from winecheck.models import VivinoResult, VivinoStatus
    from winecheck.ratings.vivino import _to_payload, saat_payload

    regulaer = set(_to_payload(VivinoResult(
        status=VivinoStatus.EXACT, query="q", url="u", note="n")))
    saat = set(saat_payload(VivinoResult(
        status=VivinoStatus.EXACT, query="q", url="u", note="n")))
    assert saat == regulaer, f"nur in einem Pfad: {saat ^ regulaer}"


def test_die_saat_laesst_das_trinkfenster_offen(adapter):
    """``_to_payload`` setzt ``drink_checked``, weil der reguläre Weg das Fenster im
    selben Durchgang holt. Diese Weine haben es nicht — ``rate`` zieht es nach, und
    zwar genau dann, wenn der Marker fehlt. Stünde er hier, verlören 645 Weine still
    ihr Trinkfenster."""
    from winecheck.models import VivinoResult, VivinoStatus
    from winecheck.ratings.vivino import saat_payload

    d = saat_payload(VivinoResult(status=VivinoStatus.EXACT, query="q", url="u", note="n"))
    assert d["drink_checked"] is False


def test_die_saat_schreibt_machart_und_herkunft(adapter):
    """Der konkrete Anlassfall: die Felder müssen bis in den Cache-Payload kommen."""
    class _Cache:
        def __init__(self):
            self.geschrieben = []

        def put_rating(self, quelle, name, jahrgang, payload, *, status):
            self.geschrieben.append(payload)

    m = _treffer()
    m["vintage"]["wine"]["style"] = {"name": "Rioja Rot", "baseline_structure":
                                     {"sweetness": 1.0, "tannin": 3.0, "acidity": 3.0}}
    m["vintage"]["wine"]["region"] = {"name": "Rioja", "country": {"name": "Spanien"}}
    m["vintage"]["wine"]["taste"] = {"structure": {"sweetness": 2.0, "tannin": 3.0,
                                                   "acidity": 3.0, "user_structure_count": 90}}
    adapter._offer(m)
    c = _Cache()
    adapter.saee_bewertungen(c)
    assert len(c.geschrieben) == 1
    p = c.geschrieben[0]
    assert p["style_name"] == "Rioja Rot"
    assert p["country"] == "Spanien"
    assert p["region_name"] == "Rioja"
    assert p["taste"]["sweetness"] == 2.0
    assert p["style_baseline"]["tannin"] == 3.0


# ------------------------------------------- Gebinde, aus einer Nutzermeldung

def test_die_kiste_wird_als_kiste_ausgewiesen(adapter):
    """Gemeldet mit den Worten „preis finde ich nicht".

    Der Pio Cesare Barolo 2016 stand mit CHF 45.47 im Bericht. Zu kaufen ist er bei
    vinpark.ch nur als Sechserkiste zu CHF 272.82 — die Adresse sagt es selbst
    („6x75cl"). Vivino nennt die Zahl in ``bottle_quantity``; geprüft wurde nur, dass es
    eine 0,75-l-Flasche ist, und das ist sie ja: sechsmal.

    Der Preis je Flasche bleibt, er ist richtig gerechnet und vergleichbar. Die
    Bedingung kommt dazu.
    """
    o = adapter._offer(_treffer(betrag=45.47, vorher=50.52, bottle_quantity=6))
    assert o.price_per_bottle_incl_vat == 45.47, "der Flaschenpreis bleibt unverändert"
    assert o.units == 6
    assert "6er-Gebinde" in o.source_note
    assert "272.82" in o.source_note, o.source_note


def test_die_einzelflasche_traegt_keine_gebindeangabe(adapter):
    """Eine 1 wäre nur Rauschen: bei der Einzelflasche sagt der Flaschenpreis alles."""
    o = adapter._offer(_treffer(bottle_quantity=1))
    assert o.units is None
    assert o.source_note == ""


def test_der_gesamtpreis_wird_ausgerechnet():
    """Die Zahl, die der Nutzer sucht: was tatsächlich abzubuchen ist."""
    from winecheck.models import PriceConfidence, RetailerPrice

    def preis(units):
        return RetailerPrice(retailer="vivinoshop", price_per_bottle_incl_vat=45.47,
                             price_raw=45.47, price_raw_basis="inkl. MwSt", url="",
                             price_confidence=PriceConfidence.HIGH, units=units)

    assert preis(6).gesamtpreis == pytest.approx(272.82)
    assert preis(None).gesamtpreis == pytest.approx(45.47), "Einzelflasche: derselbe Betrag"


def test_die_gebindeangabe_kommt_bis_in_die_zeile():
    """Die Kette von der Antwort bis zur Anzeige. Sie ist mir einmal in der Mitte
    gerissen: der Cache trug die Adresse schon und das Gebinde noch nicht."""
    from winecheck.aggregate import merge_offers
    from winecheck.models import Offer, PriceConfidence

    o = Offer(retailer="vivinoshop", name="Pio Cesare Barolo", vintage=2016,
              price_per_bottle_incl_vat=45.47, price_raw=45.47,
              price_raw_basis="inkl. MwSt", price_confidence=PriceConfidence.HIGH,
              units=6, bottle_ml=750)
    row = merge_offers([o])[0]
    assert row.prices[0].units == 6
    assert row.prices[0].gesamtpreis == pytest.approx(272.82)
    # Und in der CSV, je Händler.
    flach = row.to_flat()
    assert flach["units_vivinoshop"] == "6"
    assert flach["total_vivinoshop"] == "272.82"


def test_der_preis_nennt_seine_herkunft(adapter):
    """Vivino ist hier Vermittler, nicht Verkäufer. Der Betrag stammt aus seinen
    Angebotsdaten und wird nicht beim Verkäufer nachgeprüft.

    Vom Nutzer gemeldet und an der Quelle bestätigt: Pio Cesare Barolo 2016 stand mit
    CHF 45.47 in Vivinos Daten, vinpark.ch verlangt CHF 57.65 — 21 % mehr, und kein
    veralteter Cache. Stichprobe über 12 Händlerangebote: bei 4 stand Vivinos Betrag
    nicht auf der Verkäuferseite.

    Bewusst nicht über ``PriceConfidence``: das Feld trägt die Sicherheit der
    Gebindegrösse, und zwei Bedeutungen in einem Feld waren hier schon einmal teuer.
    """
    o = adapter._offer(_treffer())
    assert "Preis laut Vivino" in o.price_raw_basis, o.price_raw_basis
    assert o.price_confidence.value == "high", "die Gebindegrösse bleibt sicher"


def test_die_preisherkunft_steht_im_pdf_und_im_tooltip():
    """Sie stand zuerst nur im ``price_raw_basis`` — und der wird im PDF nur gedruckt,
    wenn Roh- und Normalpreis auseinandergehen. Beim Marktplatz sind sie gleich, also
    erschien der Hinweis nirgends: ausgerechnet bei der Quelle, für die er gemacht ist.
    """
    from pathlib import Path

    wurzel = Path(__file__).resolve().parents[1]
    pdf = (wurzel / "src/winecheck/report/pdf_out.py").read_text(encoding="utf-8")
    assert "cheapest.retailer in MARKTPLATZ_QUELLEN" in pdf
    assert "nicht beim Verkäufer geprüft" in pdf
    js = (wurzel / "src/winecheck/report/assets/app.js").read_text(encoding="utf-8")
    assert 'row("Preisquelle"' in js

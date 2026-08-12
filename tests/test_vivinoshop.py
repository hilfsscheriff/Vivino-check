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


def _treffer(*, betrag=10.0, vorher=20.0, flasche=1, note=4.2, jahr=2020):
    return {
        "vintage": {
            "id": 111, "year": jahr,
            "wine": {"id": 222, "name": "Rioja Reserva", "type_id": 1,
                     "winery": {"name": "Imperial"}},
            "statistics": {"ratings_average": note, "ratings_count": 900},
        },
        "price": {"id": 333, "amount": betrag, "discounted_from": vorher,
                  "bottle_type": {"id": flasche, "name": "Flasche (0,75 l)"},
                  "sku": "VI-1-CS"},
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


def test_die_angebotsadresse_traegt_den_jahrgang(adapter):
    """Von einem Nutzer gemeldet. Unser Angebot zu „The Standish The Relic
    Shiraz-Viognier" ist der 2019er zu CHF 53.78 statt 95.92; die Weinseite eröffnete
    mit dem 2021er zu CHF 99.50 ohne Abschlag. Der Rabatt stimmte — er galt für eine
    andere Flasche. Ohne ``?year=`` zeigt Vivino den Jahrgang, den es gerade für den
    passendsten hält, und der Klick widerlegt scheinbar die eigene Zeile."""
    o = adapter._offer(_treffer(jahr=2019))
    assert o.url == "https://www.vivino.com/w/222?year=2019", o.url


def test_die_weinadresse_der_saat_bleibt_ohne_jahrgang(adapter):
    """Gegenprobe: der Saat-Eintrag identifiziert den *Wein*, und seine Note gilt oft
    über alle Jahrgänge. Ein Jahrgang in dieser Adresse wäre eine Behauptung, die die
    Note nicht deckt."""
    adapter._offer(_treffer(jahr=2019))
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

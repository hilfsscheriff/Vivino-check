"""Eine beendete Aktion darf nicht in den Bericht.

Aktionis schreibt die Gültigkeit in die Karte (``<span class="card-date">20.08.2026 -
26.08.2026</span>``). Der Adapter las sie, machte daraus aber nur eine Notiz und
filterte nichts. Listet der Aggregator eine beendete Aktion weiter — und er listet
sie mitunter —, trug sie einen Preis in den Bericht, den es an der Kasse nicht mehr
gibt.

Geprüft wird nur das **Ende**: eine Aktion, die morgen beginnt, ist eine gültige
Auskunft. Und ohne lesbares Datum wird nichts ausgeschlossen — ein fehlendes Feld
darf keinen Wein kosten.
"""

from datetime import date

import pytest
from selectolax.parser import HTMLParser

from winecheck.adapters.aktionis import AktionisAdapter, _ist_abgelaufen
from winecheck.config import SourceConfig

HEUTE = date(2026, 8, 21)


def _karte(datum: str | None) -> "object":
    inneres = f'<span class="card-date">{datum}</span>' if datum is not None else ""
    html = (
        '<div class="card dealtype-deal">'
        '<a href="/deals/irgendein-wein"><div class="card-merchant"><img alt="Coop"></div>'
        '<div class="card-price"><span class="price-new">9.95</span>'
        '<span class="price-old">14.95</span></div>'
        '<div class="card-image"><img alt="Barolo DOCG 2020 – Rotwein, Italien (0.75l)"></div>'
        f"{inneres}</a></div>"
    )
    return HTMLParser(html).css_first("div.card.dealtype-deal")


@pytest.mark.parametrize("datum,erwartet", [
    ("20.08.2026 - 26.08.2026", False),   # läuft noch
    ("13.08.2026 - 21.08.2026", False),   # endet heute — heute gilt sie
    ("06.08.2026 - 20.08.2026", True),    # gestern beendet
    ("01.07.2026 - 15.07.2026", True),    # lange vorbei
    ("25.08.2026 - 31.08.2026", False),   # beginnt erst
    ("bis 26.08.2026", False),
    ("bis 19.08.2026", True),
    ("", False),                          # kein Datum: nicht ausschliessen
    (None, False),                        # kein Feld: nicht ausschliessen
    ("Datum unklar", False),
    ("32.13.2026 - 40.99.2026", False),   # unlesbar: nicht ausschliessen
])
def test_nur_beendete_aktionen_fallen_heraus(datum, erwartet):
    assert _ist_abgelaufen(_karte(datum), heute=HEUTE) is erwartet


def test_der_adapter_meldet_die_uebersprungenen():
    """Stillschweigend weglassen wäre so schlecht wie mitnehmen.

    Ein Lauf, der die Hälfte des Sortiments als abgelaufen verwirft, muss das
    ausweisen — sonst sieht er aus wie ein vollständiger.
    """
    cfg = SourceConfig(key="aktionis", name="Aktionis", adapter="aktionis",
                       domain="aktionis.ch", vat_included=True)
    a = AktionisAdapter(cfg, fetcher=None)
    karten = "".join(
        '<div class="card dealtype-deal">'
        f'<a href="/deals/wein-{i}"><div class="card-merchant"><img alt="Coop"></div>'
        '<div class="card-price"><span class="price-new">9.95</span></div>'
        f'<div class="card-image"><img alt="Barolo DOCG 20{20 + i} – Rotwein, Italien (0.75l)"></div>'
        f'<span class="card-date">01.08.2026 - {datum}</span></a></div>'
        for i, datum in enumerate(("26.08.2026", "20.08.2026", "19.08.2026"))
    )
    offers = a.parse(f"<html><body>{karten}</body></html>", "https://www.aktionis.ch/q/Wein")
    assert len(offers) == 1, [o.name for o in offers]
    assert any("abgelaufener Aktion" in h for h in a._hinweise), a._hinweise


# -- Das Kaufziel ----------------------------------------------------------
def _adapter_mit_seiten() -> AktionisAdapter:
    cfg = SourceConfig(key="aktionis", name="Aktionis", adapter="aktionis",
                       domain="aktionis.ch", vat_included=True)
    a = AktionisAdapter(cfg, fetcher=None)
    a.haendler_seiten = {"coop": {
        "standard": "https://www.coop.ch/de/weine/aktionen/c/SPECIAL_OFFERS_WINE",
        "weisswein": "https://www.coop.ch/de/weine/aktionen/aktionen-weisswein/c/X",
        "champagner": "https://www.coop.ch/de/weine/aktionen/aktionen-champagner/c/Y",
    }}
    return a


def _mit_namen(name: str, haendler: str = "Coop"):
    html = (
        '<div class="card dealtype-deal" data-upox-id="123">'
        f'<a href="/deals/irgendein-wein-47"><div class="card-merchant"><img alt="{haendler}"></div>'
        '<div class="card-price"><span class="price-new">9.95</span></div>'
        f'<div class="card-image"><img alt="{name}"></div>'
        '<span class="card-date">20.08.2026 - 26.08.2026</span></a></div>'
    )
    return f"<html><body>{html}</body></html>"


def test_der_link_engt_die_aktionsliste_auf_diesen_wein_ein():
    """Gemeldet: „coop zeigt nur dahin und nicht auf die effektive Aktion".

    Coop läuft auf SAP Hybris, und dort ist der erste Abschnitt von ``q`` die
    Freitextsuche. Am Laden nachgesehen: „costasera masi" ergibt die zwei Jahrgänge
    des Amarone Costasera, „brigaldara cavolo" genau einen Wein.
    """
    a = _adapter_mit_seiten()
    o = a.parse(_mit_namen("Amarone della Valpolicella DOC Costasera Masi (2020) – "
                           "Rotwein, Italien (0.75l)"),
                "https://www.aktionis.ch/q/Wein")[0]
    assert o.url == ("https://www.coop.ch/de/weine/aktionen/c/SPECIAL_OFFERS_WINE"
                     "?q=costasera%20masi%3Arelevance%3AspecialOfferFacet%3Atrue")


def test_vorhandene_parameter_der_haendlerseite_bleiben():
    """``sort`` und ``pageSize`` sind Teil der Adresse und dürfen nicht verschwinden."""
    from winecheck.adapters.aktionis import _mit_suchtext
    aus = _mit_suchtext(
        "https://www.coop.ch/de/x/c/Y?q=:relevance:specialOfferFacet:true&sort=relevance&pageSize=58",
        "costasera masi")
    assert aus.endswith("&sort=relevance&pageSize=58")
    assert "q=costasera%20masi%3Arelevance%3AspecialOfferFacet%3Atrue" in aus


def test_ohne_unterscheidende_woerter_bleibt_die_liste():
    """Ein Name ohne eigene Wörter darf keine leere Suche erzeugen — dann ist die
    Liste die bessere Auskunft."""
    from winecheck.adapters.aktionis import _suchtext
    assert _suchtext("– Rotwein, Italien (0.75l)") == ""
    a = _adapter_mit_seiten()
    assert a._kaufziel("coop", "– Rotwein, Italien (0.75l)").endswith("SPECIAL_OFFERS_WINE")


def test_der_link_zeigt_auf_die_aktionsseite_des_haendlers():
    """Aktionis' Deal-Seiten sind binnen Stunden tot — 9 von 11 gemessen.

    Der Link muss auf eine Adresse zeigen, die bleibt. Der Preis stammt weiterhin
    von Aktionis, und das steht in der Notiz.
    """
    a = _adapter_mit_seiten()
    o = a.parse(_mit_namen("Barolo DOCG 2020 – Rotwein, Italien (0.75l)"),
                "https://www.aktionis.ch/q/Wein")[0]
    assert o.url.startswith("https://www.coop.ch/de/weine/aktionen/c/SPECIAL_OFFERS_WINE")
    assert "Aktionis" in o.source_note


def test_die_farbe_fuehrt_zur_genaueren_seite_wenn_nichts_zu_suchen_ist():
    """Ohne unterscheidende Wörter bleibt nur die Liste — dann die farbrichtige.

    Mit Suchtext ist die Farbseite überflüssig: die Suche isoliert den Wein, und die
    allgemeine Aktionsseite ist die am Laden geprüfte Kombination.
    """
    a = _adapter_mit_seiten()
    assert a._kaufziel("coop", "– Weisswein, Frankreich (0.75l)").endswith("aktionen-weisswein/c/X")


def test_ohne_bekannte_aktionsseite_bleibt_der_deal_link():
    """Für Händler ohne eigene Adresse ist die Deal-Seite immer noch die beste — sie
    ist am Tag des Laufs richtig, und eine schlechtere Auskunft wäre keine."""
    a = _adapter_mit_seiten()
    o = a.parse(_mit_namen("Rioja DOCa 2021 – Rotwein, Spanien (0.75l)", haendler="Otto's"),
                "https://www.aktionis.ch/q/Wein")[0]
    assert o.url.startswith("https://www.aktionis.ch/deals/")

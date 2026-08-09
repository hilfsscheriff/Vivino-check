"""Aktionis-Karten, turbo-stream-Decoder und Prodega-Easy-Artikel."""

import pytest
from selectolax.parser import HTMLParser

from winecheck.config import SourceConfig
from winecheck.turbostream import TurboStream


# ----------------------------------------------------------------- turbo-stream

def test_turbostream_resolves_key_and_value_indices():
    """``{"_1": 2}`` heisst ``{liste[1]: liste[2]}`` — anders als bei devalue sind
    hier auch die Schlüssel Indizes."""
    ts = TurboStream([{"_1": 2}, "searchTerm", "wein"])
    assert ts.resolve(0) == {"searchTerm": "wein"}


def test_turbostream_resolves_nested_lists():
    ts = TurboStream([{"_1": 2}, "ids", [3, 4], 7, 9])
    assert ts.resolve(0) == {"ids": [7, 9]}


def test_turbostream_treats_negative_indices_as_missing():
    ts = TurboStream([{"_1": -7}, "brand"])
    assert ts.resolve(0) == {"brand": None}


def test_turbostream_survives_cycles():
    ts = TurboStream([{"_1": 0}, "self"])
    assert ts.resolve(0) == {"self": None}


def test_turbostream_finds_objects_by_required_keys():
    array = [
        {"_1": 2, "_3": 4},   # 0: Artikel
        "articleNumber", "673110",
        "price", 5.9,
        {"_1": 6},            # 5: anderer Artikel, ohne price
        "999",
    ]
    ts = TurboStream(array)
    found = ts.objects_with("articleNumber", "price")
    assert found == [{"articleNumber": "673110", "price": 5.9}]


def test_turbostream_returns_nothing_for_unknown_keys():
    ts = TurboStream([{"_1": 2}, "a", "b"])
    assert ts.objects_with("gibtsnicht") == []


def test_turbostream_rejects_non_list_payload():
    assert TurboStream.parse('{"a": 1}') is None
    assert TurboStream.parse("kein json") is None


# ------------------------------------------------------------------- Aktionis

CARD = """
<div data-upox-id="1551796" class="card dealtype-deal"><div class="card-wrapper">
 <a href="/deals/blauer-zweigelt-mundart-2022" target="_top"
    title="Mehr Infos über Blauer Zweigelt, Mundart (2022) – Rotwein, Österreich (0.75l)">
  <div class="card-merchant"><img src="x.webp" alt="{merchant}"></div>
  <div class="card-price">
    <span class="price-new">{new}</span>
    <span class="price-old">{old}</span>
    <span class="price-discount" title="Rabatt">50%</span>
  </div>
  <div class="card-image"><img alt="{name}" width="220"></div>
  <div class="card-content"><h3 class="card-title text-truncate">{name_trunc}</h3>
   <div class="card-content-info"><span class="card-date">16.07.2026 - 12.08.2026</span></div>
  </div>
 </a></div></div>
"""


def _card(*, merchant="Coop", new="3.95", old="7.95",
          name="Blauer Zweigelt, Mundart (2022) – Rotwein, Österreich (0.75l)"):
    html = CARD.format(merchant=merchant, new=new, old=old, name=name,
                       name_trunc=name[:40] + "...")
    return HTMLParser(html).css_first("div.card.dealtype-deal")


@pytest.fixture
def adapter():
    from winecheck.adapters.aktionis import AktionisAdapter

    cfg = SourceConfig(key="aktionis", name="Aktionis", domain="aktionis.ch")
    return AktionisAdapter(cfg, fetcher=None)  # type: ignore[arg-type]


def test_full_name_comes_from_the_image_alt_not_the_truncated_heading(adapter):
    """``h3.card-title`` ist per ``text-truncate`` gekürzt und würde beim Matching
    Bestandteile verlieren."""
    offer = adapter._parse_card(_card())
    assert offer is not None
    assert offer.name.endswith("(0.75l)")
    assert "..." not in offer.name


def test_offer_is_attributed_to_the_real_retailer(adapter):
    assert adapter._parse_card(_card(merchant="Coop")).retailer == "coop"
    assert adapter._parse_card(_card(merchant="Denner")).retailer == "denner"
    assert adapter._parse_card(_card(merchant="OTTO'S")).retailer == "ottos"
    # Filialformate laufen auf denselben Schlüssel.
    assert adapter._parse_card(_card(merchant="Coop Megastore")).retailer == "coop"


def test_unknown_logo_becomes_a_slug_instead_of_being_dropped(adapter):
    offer = adapter._parse_card(_card(merchant="Neuer Händler AG"))
    assert offer is not None
    assert offer.retailer == "neuerhandlerag"


def test_price_reference_and_vintage_are_read(adapter):
    offer = adapter._parse_card(_card(new="3.95", old="7.95"))
    assert offer.price_per_bottle_incl_vat == 3.95
    assert offer.vintage == 2022
    assert offer.discount_percent == pytest.approx(50.3, abs=0.5)


def test_pack_in_the_name_is_divided_to_a_bottle_price(adapter):
    """"6x 75cl" bei CHF 19.80 ist ein Kartonpreis, nicht der Flaschenpreis."""
    offer = adapter._parse_card(_card(
        new="19.80", old="39.90",
        name="Valdepeñas DO Tempranillo Pata Negra Oro 6x 75cl (2022) – Rotwein, Spanien",
    ))
    assert offer.price_per_bottle_incl_vat == pytest.approx(3.30, abs=0.01)


def test_validity_period_is_kept_as_a_note(adapter):
    offer = adapter._parse_card(_card())
    assert "16.07.2026" in offer.source_note
    assert "Aktionis" in offer.source_note


def test_deal_url_is_absolute_so_the_source_stays_traceable(adapter):
    offer = adapter._parse_card(_card())
    assert offer.url.startswith("https://www.aktionis.ch/deals/")


def test_non_wine_cards_are_skipped(adapter):
    assert adapter._parse_card(_card(name="Weinessig Aceto Balsamico 50 cl")) is None
    assert adapter._parse_card(_card(name="Rotwein-Gläser 6er-Set")) is None


def test_card_without_price_is_skipped(adapter):
    html = CARD.format(merchant="Coop", new="", old="", name="Merlot Ticino DOC 75cl",
                       name_trunc="Merlot")
    html = html.replace('<span class="price-new"></span>', "")
    assert adapter._parse_card(HTMLParser(html).css_first("div.card.dealtype-deal")) is None


def test_pagination_uses_page_parameter(adapter):
    """``?p=`` und ``?offset=`` werden von Aktionis ignoriert und liefern still
    wieder Seite 1 — nur ``page`` zählt."""
    adapter.cfg.urls = ["https://www.aktionis.ch/q/Wein"]
    urls = adapter.urls()
    assert urls[0] == "https://www.aktionis.ch/q/Wein"
    assert "?page=2" in urls[1]
    assert all("?p=" not in u or "?page=" in u for u in urls)


# --------------------------------------------------- Weinart als Namensbestandteil

def test_wine_type_words_are_not_identity():
    """Aktionis schreibt "… – Rotwein, Österreich"; ohne diese Regel wäre "rotwein"
    ein eigenständiger Namensbestandteil."""
    from winecheck.names import tokenize

    toks = tokenize("Blauer Zweigelt, Mundart – Rotwein, Österreich")
    assert "rotwein" not in toks
    assert "zweigelt" in toks


def test_two_wines_do_not_match_on_wine_type_alone():
    from winecheck.matching import match_wine

    d = match_wine("Irgendwas – Rotwein, Österreich", "Anderes – Rotwein, Österreich")
    assert not d.matched


# ------------------------------------------------------------- Alkoholfreies

@pytest.mark.parametrize(
    "name",
    [
        "Rimuss Rosato Sparkling, dry, alkoholfrei – Schaumwein",
        "Alkoholfreier Riesling 75 cl",
        "Entalkoholisierter Merlot, 0.0 %",
        "Vin mousseux sans alcool 75 cl",
    ],
)
def test_alcohol_free_is_not_wine(name):
    """Doppelt falsch: kein Wein für den Preisvergleich, und alkoholfreie Getränke
    unterliegen dem reduzierten MwSt-Satz von 2.6 % statt den 8.1 %, mit denen hier
    gerechnet wird — der Preis wäre um 5.4 % zu hoch."""
    from winecheck.adapters.base import looks_like_wine

    assert not looks_like_wine(name)


def test_real_wine_still_passes():
    from winecheck.adapters.base import looks_like_wine

    assert looks_like_wine("Casalforte Ripasso della Valpolicella DOC, 75 cl")
    assert looks_like_wine("Blauer Zweigelt, Mundart (2022) – Rotwein, Österreich (0.75l)")


# ----------------------------- Produzent aus der Mövenpick-URL (Regression)

def test_producer_is_recovered_from_the_moevenpick_url():
    """Mövenpick benennt Weine nach Herkunft und Lage und stellt den Produzenten nur
    in die Adresse. Für Vivino ist er das wichtigste Wort — die Suche sortiert nach
    Bewertung, nicht nach Namensähnlichkeit, und ohne Produzent findet man den
    berühmtesten Wein der Appellation statt den gesuchten.

    Der Slug ist Name **plus** Produzent; was im Slug steht und im Namen fehlt, ist
    der Produzent. Das brachte 22 zusätzliche exakte Treffer.
    """
    from winecheck.adapters.moevenpick import producer_from_url

    assert producer_from_url(
        "Côtes du Roussillon Villages AOC 2020 Les Dentelles",
        "https://www.moevenpick-wein.com/de/2020-les-dentelles-cotes-du-roussillon-"
        "villages-aoc-domaine-thunevin-calvet.html",
    ) == "Thunevin Calvet"

    assert producer_from_url(
        "Aconcagua Costa DO 2023 Chardonnay Las Pizarras",
        "https://www.moevenpick-wein.com/de/2023-chardonnay-las-pizarras-aconcagua-"
        "costa-do-vina-errazuriz.html",
    ) == "Vina Errazuriz"


def test_packaging_words_are_not_mistaken_for_a_producer():
    """„anniversary set 2x 2x 2x poliziano" stand so im Slug — nur „Poliziano" ist
    der Produzent."""
    from winecheck.adapters.moevenpick import producer_from_url

    assert producer_from_url(
        "Asinone Vino Nobile di Montepulciano DOCG",
        "https://www.moevenpick-wein.com/de/asinone-vino-nobile-anniversary-set-2x-"
        "2x-2x-poliziano.html",
    ) == "Poliziano"


def test_no_producer_is_better_than_a_guess():
    """Bleibt nach dem Filtern nichts Belastbares übrig, wird der Name nicht angefasst."""
    from winecheck.adapters.moevenpick import producer_from_url

    assert producer_from_url(
        "Bianco del Ticino DOC 2024 Castello di Morcote",
        "https://x/de/2024-bianco-del-ticino-doc-castello-di-morcote-bio.html",
    ) == ""
    assert producer_from_url("Irgendein Wein", "") == ""


# ------------------------------- Mehrflaschen-Gebinde (Regression 7.8.2026)

def test_vintage_set_bottle_count_comes_from_the_url():
    """Mövenpick verkauft Sammlungen als eine Position: „Anniversary Set 2x2013
    2x2016 2x2018" sind sechs Flaschen zu CHF 290 — also CHF 48.33 je Flasche.
    Im Namen steht davon nichts, und ohne Volumenangabe nimmt die Preisrechnung eine
    einzelne Flasche an. Der Fehler ist Faktor sechs und trifft immer die teuersten
    Positionen, weil nur dort Sets verkauft werden."""
    from winecheck.adapters.moevenpick import bottles_from_url

    assert bottles_from_url(
        "https://www.moevenpick-wein.com/de/vino-nobile-di-montepulciano-docg-asinone-"
        "anniversary-set-2x2013-2x2016-2x2018-azienda-agricola-poliziano.html"
    ) == 6
    assert bottles_from_url("https://x/de/3x2019-barolo-set.html") == 3
    # Ein gewöhnlicher Wein hat kein Set-Muster.
    assert bottles_from_url(
        "https://x/de/2020-les-dentelles-cotes-du-roussillon-aoc-thunevin-calvet.html"
    ) is None
    assert bottles_from_url("") is None


def test_aktionis_reads_the_pack_size_from_the_card_meta_line():
    """Die Gebindeangabe steht nicht im Titel, sondern in der Metazeile der Karte:
    „Italien, Apulien, 2025, 6 x 75 cl". Vorher ging nur der Titel in die
    Preisrechnung, und ein Sechserpaket galt als eine Flasche — „A Mano Primitivo"
    stand mit CHF 39.90 statt CHF 6.65 im Report."""
    from winecheck.prices import normalize_price

    r = normalize_price(39.90, "A Mano Primitivo di Puglia IGT Italien, Apulien, 2025, 6 x 75 cl")
    assert r.price_per_bottle_incl_vat == pytest.approx(6.65, abs=0.02)
    assert "6" in r.price_raw_basis


def test_a_single_bottle_listing_is_not_divided():
    """Gegenprobe: ohne Gebindeangabe bleibt der Preis, wie er ist."""
    from winecheck.prices import normalize_price

    r = normalize_price(39.90, "A Mano Primitivo di Puglia IGT Italien, Apulien, 2025, 75 cl")
    assert r.price_per_bottle_incl_vat == pytest.approx(39.90, abs=0.02)


# ------------------------- Mövenpick-Paginierung (Regression 9.8.2026)

class _MoevenpickCfg:
    key = "moevenpick"
    vat_included = True
    price_basis = "bottle"
    private_label_brands: list[str] = []
    wine_only = True
    urls = ["https://mp.test/de/aktuelle-angebote.html"]
    shop_root = "https://mp.test/de/"
    promo_keywords = ["angebote"]


class _PagerFetcher:
    """Antwortet wie Magento: die letzte Seitenzahl steht im Pager."""

    def __init__(self, letzte: int | None):
        self.letzte = letzte
        self.geholt: list[str] = []

    def get(self, url, **kw):
        self.geholt.append(url)
        pager = (
            f'<input type="number" min="1" max="{self.letzte}" data-role="pager">'
            if self.letzte is not None else "<p>kein Pager</p>"
        )
        return type("R", (), {"ok": True, "text": pager, "url": url, "status_code": 200})()


def test_moevenpick_blaettert_bis_zur_letzten_seite():
    """„Fallet Dart Champagne Brut Cuvée de Réserve" (CHF 28.80 statt 36.00) fehlte im
    Report, weil hier ein fester Deckel von vier Seiten stand — der Wein steht auf
    Seite 7, und von 511 Angeboten sahen wir 96.

    Bemerken liess sich das nicht: ein zu grosses ``p`` beantwortet Magento nicht mit
    404, sondern klemmt auf die erste Seite zurück. Wie weit es geht, sagt der Shop
    selbst im Pager."""
    from winecheck.adapters.moevenpick import MoevenpickAdapter

    f = _PagerFetcher(letzte=22)
    urls = MoevenpickAdapter(_MoevenpickCfg(), f).urls()
    assert len(urls) == 22
    assert urls[0] == "https://mp.test/de/aktuelle-angebote.html"
    assert urls[-1] == "https://mp.test/de/aktuelle-angebote.html?p=22"
    # Die Seitenzahl wird gemerkt: fetch() fragt die URL-Liste zweimal ab.
    assert len(f.geholt) == 1


def test_ohne_lesbaren_pager_wird_grosszuegig_geblaettert():
    """Der Ausfall darf nicht in Richtung „zu wenig" gehen: ein unlesbarer Pager
    kostet Anfragen für Seiten, die es nicht gibt, und deren doppelte Angebote fallen
    in der Dedup-Stufe weg. Fehlende Weine sieht dagegen niemand."""
    from winecheck.adapters.moevenpick import MAX_PAGES, MoevenpickAdapter

    urls = MoevenpickAdapter(_MoevenpickCfg(), _PagerFetcher(letzte=None)).urls()
    assert len(urls) == MAX_PAGES


def test_die_seitenzahl_des_shops_ist_nach_oben_begrenzt():
    """Eine unsinnig grosse Zahl im Markup darf keinen Dauerlauf auslösen."""
    from winecheck.adapters.moevenpick import MAX_PAGES, MoevenpickAdapter

    urls = MoevenpickAdapter(_MoevenpickCfg(), _PagerFetcher(letzte=9999)).urls()
    assert len(urls) == MAX_PAGES

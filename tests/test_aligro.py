"""Aligro — der Kartonpreis ist die ganze Schwierigkeit.

Aligro zeigt je nach Kundentyp etwas anderes an. Derselbe Wein, am 7.8.2026 gemessen:

* **Privatkunde**: ``103.- / 6 Flaschen → 83.-`` — Kartonpreis, inkl. MwSt
* **Gastroprofi**: ``15.88 / Flasche → 12.80`` — Flaschenpreis, exkl. MwSt

83 ÷ 6 = 13.83 und 12.80 × 1.081 = 13.84 — dieselbe Flasche, zwei Darstellungen. Wer
eine davon ungeprüft übernimmt, liegt entweder um den Faktor 6 oder um 8.1 % daneben.
Der Adapter liest darum keine Anzeige, sondern die Zahlenfelder.
"""

import pytest

from winecheck.adapters.aligro import AligroAdapter, _bottles, _category, _name


def _item(**over):
    """Ein Artikel in der Form, die Aligro im ``pagination``-Attribut liefert."""
    base = {
        "sKU": "451848-Z06",
        "quantityUnit": {"code": "Z06", "number": 6},
        "quantityUnitBase": {"code": "BT"},
        "article": {"articleNumber": 451848, "articleGroup": {
            "code": 1711, "translations": {"fr": {"wording": "Vins rouges étrangers"}}}},
        "packagingLabel": "75 cl",
        "packagingLabelPro": "75 cl, 6 x",
        "quantityLabelForFullPrice": "6 x 75 cl",
        "href": {"self": "https://www.aligro.ch/produits/451848-Z06/x"},
        "translations": {"fr": {
            "description": "Valdepeñas P.Negra Reserva DO 2019 75 cl",
            "advertisingText": "Valdepeñas Reserva",
            "additionalDesignation": "DO 2019",
            "brand": "Pata Negra",
            "weightVolume": "75 cl",
        }},
        "mainArticleDetailPrice": {
            "salesPriceTTC": 56.0, "salesPriceHT": 51.8,
            "discountPriceTTC": 29.0, "discountPriceHT": 26.83,
            "unitPrice": 4.47,
        },
    }
    base.update(over)
    return base


class _Cfg:
    key = "aligro"
    vat_included = True
    price_basis = "bottle"
    private_label_brands: list[str] = []


@pytest.fixture
def adapter():
    return AligroAdapter(_Cfg(), fetcher=None)


def test_carton_price_is_divided_by_the_bottle_count(adapter):
    """``discountPriceTTC`` gilt fürs Gebinde, nicht für die Flasche.

    Ungeteilt stünde dieser Wein mit CHF 29.00 statt CHF 4.83 in der Liste — ein
    Sechsfaches, das ihn aus seiner Preisklasse und damit aus jedem sinnvollen
    Vergleich wirft.
    """
    o = adapter._offer(_item())
    assert o is not None
    assert o.price_per_bottle_incl_vat == pytest.approx(4.83, abs=0.01)
    assert o.units == 6


def test_reference_price_is_divided_too(adapter):
    """Sonst wäre der Rabatt aus zwei verschiedenen Bezugsgrössen gerechnet."""
    o = adapter._offer(_item())
    assert o.reference_price == pytest.approx(9.33, abs=0.02)


def test_unit_price_field_is_not_used(adapter):
    """``unitPrice`` ist der bequemste und der falsche Wert.

    Er ist der Flaschenpreis **exklusive** MwSt (26.83 ÷ 6 = 4.47) und sieht dem
    richtigen Endpreis von 4.83 nahe genug, um unbemerkt durchzugehen.
    """
    o = adapter._offer(_item())
    assert o.price_per_bottle_incl_vat != pytest.approx(4.47, abs=0.01)


def test_single_bottle_is_not_divided(adapter):
    o = adapter._offer(_item(
        quantityUnit={"code": "BT", "number": 1},
        mainArticleDetailPrice={"salesPriceTTC": 24.0, "discountPriceTTC": 19.0},
    ))
    assert o.price_per_bottle_incl_vat == pytest.approx(19.0, abs=0.01)


def test_unknown_pack_size_lowers_confidence_instead_of_guessing(adapter):
    """Ohne Flaschenzahl wird nicht geteilt und nicht geraten.

    Der Wein bleibt sichtbar, fällt aber über ``price_confidence = low`` aus dem
    Ranking — ein falsch geteilter Preis erzeugt einen Scheinsieger, eine Lücke nicht.
    """
    from winecheck.models import PriceConfidence

    o = adapter._offer(_item(quantityUnit={}, quantityUnitBase={"code": "XX"}))
    assert o is not None
    assert o.price_confidence is PriceConfidence.LOW
    assert adapter.uncertain, "der Fall muss im Protokoll auftauchen"


def test_bottle_count_reads_the_number_field():
    assert _bottles({"quantityUnit": {"code": "Z06", "number": 6}}) == 6
    assert _bottles({"quantityUnit": {}, "quantityUnitBase": {"code": "BT"}}) == 1
    assert _bottles({"quantityUnit": {}, "quantityUnitBase": {"code": "XX"}}) is None


def test_name_uses_the_readable_fields():
    """``description`` ist Kassentext. Werbetext plus Zusatz liest sich besser und
    trägt Jahrgang und Herkunft, die der Matcher braucht."""
    n = _name(_item())
    assert "Valdepeñas Reserva" in n
    assert "75 cl" in n


def test_french_only_translations_are_accepted():
    """Aligro pflegt viele Artikel nur französisch — ``translations.de`` ist dann
    ``null``. Ein französischer Name ist kein Hindernis, der Matcher kennt beide
    Sprachen."""
    n = _name(_item(translations={"de": None, "fr": {
        "advertisingText": "Côtes du Rhône", "additionalDesignation": "AOC 2022",
        "weightVolume": "75 cl",
    }}))
    assert "Côtes du Rhône" in n


def test_category_comes_from_the_article_group():
    """Die Warengruppe steckt unter ``article.articleGroup``, nicht in den
    Artikel-Übersetzungen. Ohne sie fällt die Weinerkennung auf den Namen zurück —
    und „Amarone della Valpolicella Classico Zeni DOCG" enthält kein Wort, das nach
    Wein aussieht."""
    assert _category(_item()) == "Vins rouges étrangers"
    assert _category({"article": {}}) == ""

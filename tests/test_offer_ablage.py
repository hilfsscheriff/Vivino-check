"""Was im Modell steht, muss auch im Cache landen.

Die Ablage in ``_offer_payload`` ist eine von Hand geführte Feldliste, und genau das
war die Falle: ``roh_ist_gebinde`` und ``vat_added`` kamen ins Modell, aber nicht in
die Liste. Die Zahlbetrags-Rechnung wirkte damit nur im Speicher — über den Cache,
also im Bericht und auf der Webseite, fiel sie auf den alten Rückfall zurück und wies
für einen Wein, den es nur im Sechserkarton zu CHF 87.00 gibt, CHF 522.00 aus.

Aufgefallen ist das erst an der neuen Quelle Alloboissons, die ausschliesslich Kartons
verkauft. Bei allen anderen Händlern meint der Rohpreis die Flasche; dort ist der alte
Rückfall zufällig richtig, und der Fehler wäre unbemerkt geblieben.
"""

import dataclasses
import re
from pathlib import Path

from winecheck.cli import _offer_from_payload, _offer_payload
from winecheck.models import DiscountPlausibility, Offer, PriceConfidence


def test_jedes_feld_des_modells_wird_gespeichert():
    """Der Wächter gegen die nächste Erweiterung, die die Liste vergisst."""
    quelle = Path(__file__).resolve().parents[1] / "src" / "winecheck" / "cli.py"
    text = quelle.read_text(encoding="utf-8")
    ausschnitt = text[text.index("def _offer_payload"):text.index("def _offer_from_payload")]
    gespeichert = set(re.findall(r'"([a-z_]+)":', ausschnitt))
    fehlt = {f.name for f in dataclasses.fields(Offer)} - gespeichert
    assert not fehlt, f"nicht im Cache gespeichert: {sorted(fehlt)}"


def _vollstaendig() -> Offer:
    """Ein Angebot mit *jedem* Feld belegt — sonst prüft der Rundlauf nichts."""
    return Offer(
        retailer="alloboissons",
        name="Mòmò Merlot colline del Mendrisiotto 2023",
        url="https://www.alloboissons.ch/de/sortiment/artikel-92332%2075%202023.html",
        vintage=2023,
        producer="Delea",
        region="Ticino",
        country="Schweiz",
        price_per_bottle_incl_vat=14.50,
        price_raw=87.00,
        price_raw_basis="Karton 6, inkl. MwSt",
        price_confidence=PriceConfidence.HIGH,
        reference_price=18.00,
        discount_percent=19.4,
        discount_plausibility=DiscountPlausibility.OK,
        is_private_label=False,
        bottle_ml=750,
        units=6,
        roh_ist_gebinde=True,
        vat_added=False,
        article_no="92332 75 2023",
        fetched_at="2026-08-21T16:00:00",
        source_note="nur im Karton à 6",
        critic_scores={"falstaff": 90.0},
    )


def test_der_rundlauf_durch_den_cache_verliert_nichts():
    zurueck = _offer_from_payload(_offer_payload(_vollstaendig()))
    assert dataclasses.asdict(zurueck) == dataclasses.asdict(_vollstaendig())


def test_der_zahlbetrag_ueberlebt_den_cache():
    """Der Kartonpreis darf nach dem Rundlauf nicht noch einmal mal sechs gerechnet werden."""
    from winecheck.models import RetailerPrice

    o = _offer_from_payload(_offer_payload(_vollstaendig()))
    p = RetailerPrice(
        retailer=o.retailer, price_per_bottle_incl_vat=o.price_per_bottle_incl_vat,
        price_raw=o.price_raw, price_raw_basis=o.price_raw_basis, url=o.url,
        price_confidence=o.price_confidence, units=o.units,
        roh_ist_gebinde=o.roh_ist_gebinde, vat_added=o.vat_added,
    )
    assert p.gesamtpreis == 87.00


def test_alte_eintraege_ohne_die_neuen_felder_bleiben_lesbar():
    """Ein Cache aus einer früheren Fassung darf nicht platzen.

    Dort fehlen die Felder; ``False`` ist der bisherige Stand und für Flaschenpreise
    — die grosse Mehrheit — die richtige Annahme.
    """
    alt = _offer_payload(_vollstaendig())
    for feld in ("roh_ist_gebinde", "vat_added", "producer", "region", "country"):
        alt.pop(feld)
    o = _offer_from_payload(alt)
    assert o.roh_ist_gebinde is False and o.vat_added is False
    assert o.name.startswith("Mòmò")

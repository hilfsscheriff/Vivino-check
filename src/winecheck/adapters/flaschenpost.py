"""Flaschenpost — der grösste Schweizer Onlinehändler, über seine Produkt-API.

Die Webseite selbst liegt hinter einer Cloudflare-Challenge und war darum lange als
``blocked`` eingetragen. Die Produkt-API ist es nicht:

    GET /api/products?limit=500&page=1   →  HTTP 200, application/json

Warum das keine Umgehung ist
----------------------------
Geprüft, nicht angenommen. Dieselbe Anfrage wurde dreimal gestellt — mit dem
ehrlichen Projekt-User-Agent samt Kontaktadresse, ganz ohne User-Agent, und als
Chrome. Alle drei Male dieselbe Antwort, **byteidentisch** (25'871 B). Es gibt auf
diesem Pfad keine Bot-Erkennung, die getäuscht würde: die Schnittstelle antwortet
jedem, auch einem Crawler, der sich als solcher zu erkennen gibt.

Die ``robots.txt`` des Hauses sperrt ``/checkout``, ``/cart``, ``/account`` und
``/404`` — ``/api/`` steht ausdrücklich nicht darin. Das ist die maschinenlesbare
Aussage des Betreibers über automatisierten Zugriff, und sie erlaubt diesen Pfad.

Ehrlich dazugesagt: ``/api/products`` ist der **einzige** offene API-Pfad.
``/api/categories``, ``/api/search``, ``/api/facets`` und ``/api/config`` liefern
alle die Challenge. Dieser eine Pfad ist also eine Ausnahme in ihrer Konfiguration.
Sollte Flaschenpost ihn schliessen, wird der Adapter ``blocked`` melden — und dann
bleibt er blockiert, so wie Coop und Migros.

Was die Antwort hergibt
-----------------------
Sauberer als jede andere Quelle im Bestand — nichts muss aus Fliesstext geraten
werden::

    "price": {
      "initialPrice":  {"amount": 1395},   Streichpreis in Rappen
      "discountPrice": {"amount": 1050},   Aktionspreis, fehlt bei Regalware
      "literPrice":    {"amount": 14.00}   erlaubt die Gegenprobe
    }

Dazu ``producer``, ``bottleSize``, ``salesUnit``, ``region``, ``grapes``.

Die Blätterung hat eine Decke
-----------------------------
``page`` ist der Blätterparameter — ``offset``, ``from``, ``start`` und ``skip``
werden stillschweigend ignoriert und liefern immer dieselbe Seite. Bei
``limit=500`` endet die Blätterung bei Offset 32'000, also nach 65 Seiten; Seite 66
liefert nichts mehr. Von den gemeldeten 53'421 Produkten sind damit rund 61 %
erreichbar.

Die Reihenfolge ist dabei nicht stabil: ein Probedurchgang fand 640 rabattierte
Positionen, darunter 164 Dubletten — Produkte wandern zwischen den Seiten, während
man blättert. Entdoppelt wird über die SKU. Umgekehrt heisst das auch, dass einzelne
Weine bei einem Durchgang durchrutschen können; über die Wochen gleicht sich das aus.

Kein Jahrgang
-------------
Die Schnittstelle nennt ihn nirgends — weder als Attribut, noch in der Adresse, noch
im Namen. Ein Wein hat mehrere ``variants`` mit verschiedenen SKU und Preisen, die
mit grosser Wahrscheinlichkeit Jahrgänge sind, aber unbeschriftet bleiben.

Das kostet drei Dinge, und sie stehen hier, damit niemand sie später für Fehler hält:
die **Trinkreife** entfällt (die Vinum-Tabelle rechnet je Jahrgang), der
Vivino-Treffer erreicht bestenfalls ``wine_level`` statt ``exact``, und beim
Zusammenführen über die Händler steht ein Flaschenpost-Wein neben demselben Wein
eines anderen Ladens, statt mit ihm zu verschmelzen. Lieber diese Lücke als ein
geratener Jahrgang.
"""

from __future__ import annotations

import json
from typing import Any

from ..fetching import Blocked
from ..models import Offer
from .base import FetchReport, RetailerAdapter

API_URL = "https://www.flaschenpost.ch/api/products"
BASIS_URL = "https://www.flaschenpost.ch/"

#: 500 ist das Maximum, das die Schnittstelle beantwortet — bei 1000 kommt nichts
#: Verwertbares zurück.
PRO_SEITE = 500

#: Die Blätterung endet bei Offset 32'000. Eine Seite mehr als nötig kostet zwei
#: Sekunden und fängt ab, falls die Decke einmal höher liegt.
MAX_SEITEN = 66

#: ``bottleSize`` kommt als Ganzzahl in Zehntel-Millilitern: 7500 sind 750 ml.
#: Bestätigt über den mitgelieferten Literpreis — 10.50 CHF ÷ 14.00 CHF/l ergibt
#: exakt 0.750 l.
GROESSE_TEILER = 10

#: Wie weit der eigene Literpreis vom angeschriebenen abweichen darf. Zwei Prozent
#: decken Rundung ab; alles darüber heisst, dass die Grössenangabe anders gemeint
#: war als gelesen.
TOLERANZ = 0.02


def _de(wert: Any) -> str:
    """Holt den deutschen Text aus den verschachtelten Sprachfeldern.

    Die Schnittstelle mischt drei Formen: eine flache Sprach-Map
    (``{"de-CH": "…"}``), ein Objekt mit ``label`` als Sprach-Map, und ein Objekt
    mit ``label`` als einfachem String (so kommt der Produzent).
    """
    if isinstance(wert, dict):
        if "de-CH" in wert:
            return str(wert["de-CH"]).strip()
        label = wert.get("label")
        if isinstance(label, dict):
            return str(label.get("de-CH") or "").strip()
        if label is not None:
            return str(label).strip()
        return ""
    return str(wert or "").strip()


class FlaschenpostAdapter(RetailerAdapter):
    """Spricht JSON statt HTML — darum eigener Ablauf statt ``parse``."""

    key = "flaschenpost"

    def _seite(self, seite: int) -> list[dict]:
        res = self.fetcher.get(
            API_URL,
            params=[("limit", str(PRO_SEITE)), ("page", str(seite))],
            expect_json=True,
        )
        if not res.ok:
            raise Blocked(f"Flaschenpost API HTTP {res.status_code}", kind="http")
        try:
            payload = json.loads(res.text)
        except json.JSONDecodeError as exc:
            raise Blocked(f"Flaschenpost API lieferte kein JSON: {exc}", kind="parse") from exc
        return [x for x in (payload.get("results") or []) if isinstance(x, dict)]

    @staticmethod
    def _gegenprobe(preis: float, ml: int | None, literpreis: float | None) -> bool:
        """Bestätigt der angeschriebene Literpreis die gelesene Flaschengrösse?

        Ohne Literpreis wird nicht widersprochen — die Prüfung soll Fehler finden,
        nicht Weine ohne Zusatzangabe aussortieren.
        """
        if not literpreis or not ml:
            return True
        liter = ml / 1000
        if liter <= 0:
            return False
        return abs(preis / liter - literpreis) <= literpreis * TOLERANZ

    def _offer(self, produkt: dict) -> Offer | None:
        mv = produkt.get("masterVariant") or {}
        preise = mv.get("price") or {}
        attr = mv.get("attributes") or {}

        # Ohne Aktionspreis ist es Regalware. Das ist die Grenze, an der sich in
        # diesem Projekt Aktion von Sortiment scheidet.
        aktion = (preise.get("discountPrice") or {}).get("amount")
        referenz = (preise.get("initialPrice") or {}).get("amount")
        if not isinstance(aktion, (int, float)) or not aktion:
            return None
        if not isinstance(referenz, (int, float)) or referenz <= aktion:
            return None
        # Beträge kommen in Rappen.
        aktion, referenz = aktion / 100, referenz / 100

        name = _de(produkt.get("name")) or _de(attr.get("name"))
        if not name:
            return None
        produzent = _de(attr.get("producer"))
        # Der Produzent ist für Vivino das wichtigste Wort und steht nie im Namen.
        voll = f"{name} {produzent}".strip() if produzent else name

        if not self.ist_wein(voll):
            return None

        groesse = attr.get("bottleSize")
        ml = int(groesse) // GROESSE_TEILER if isinstance(groesse, (int, float)) else None
        literpreis = (preise.get("literPrice") or {}).get("amount")
        if not self._gegenprobe(aktion, ml, literpreis):
            # Die eigene Lesart widerspricht dem Händler. Ohne Gebindetext stuft
            # die Normalisierung den Wein als unsicher ein und nimmt ihn aus der
            # Rangliste — besser als ein falscher Literpreis.
            ml = None

        # Nur der Slug, ohne Query-String. Das ``url``-Feld der Schnittstelle hängt
        # ``?_size=7500&_packaging=…&_sku=…`` an — und ``_size`` trägt dort dieselbe
        # interne Zehntel-Milliliter-Zahl wie ``bottleSize``. Die Webseite erwartet
        # an dieser Stelle Milliliter: mit ``_size=7500`` antwortet sie „Die
        # angeforderte Seite existiert nicht", mit dem blossen Slug findet sie den
        # Wein. Ungeprüft übernommen waren damit alle 477 Links tot.
        pfad = str(mv.get("url") or "").lstrip("/").split("?")[0]
        return self.make_offer(
            name=voll,
            url=f"{BASIS_URL}{pfad}" if pfad else BASIS_URL,
            price_text=aktion,
            reference_text=referenz,
            gebinde_text=f"{ml} ml" if ml else "",
            article_no=str(mv.get("sku") or "") or None,
            # Kein Jahrgang in der Antwort — siehe Modulkopf. Geraten wird keiner.
            vintage=None,
            vat_included=True,
            price_basis="bottle",
        )

    def parse(self, html: str, url: str) -> list[Offer]:
        """Nur der Vollständigkeit halber — diese Quelle liefert kein HTML."""
        return []

    def fetch(self) -> FetchReport:
        offers: list[Offer] = []
        gesehen: set[str] = set()
        seiten = 0
        try:
            for seite in range(1, MAX_SEITEN + 1):
                treffer = self._seite(seite)
                if not treffer:
                    break
                seiten += 1
                for produkt in treffer:
                    # Entdoppeln über die SKU: die Reihenfolge der Schnittstelle ist
                    # nicht stabil, ein Probedurchgang fand 640 Positionen mit 164
                    # Dubletten.
                    sku = str((produkt.get("masterVariant") or {}).get("sku") or "")
                    if sku and sku in gesehen:
                        continue
                    offer = self._offer(produkt)
                    if offer is not None:
                        gesehen.add(sku)
                        offers.append(offer)
                if len(treffer) < PRO_SEITE:
                    break
        except Blocked as exc:
            if not offers:
                # Gleich die erste Seite verweigert: das ist eine echte Sperre.
                return FetchReport(retailer=self.cfg.key, status="blocked", message=str(exc))
            # Ein Fehler *nach* gelesenen Seiten ist das erwartete Ende, kein
            # Zwischenfall: jenseits von Offset 32'000 antwortet die Schnittstelle
            # mit HTTP 400. Das als "abgebrochen" zu melden liesse jeden Lauf wie
            # einen halben Fehlschlag aussehen, obwohl er vollständig ist.
            grund = (
                "Ende der Blätterung erreicht"
                if seiten >= MAX_SEITEN - 1 or "400" in str(exc)
                else f"vorzeitig beendet ({exc})"
            )
            return FetchReport(
                retailer=self.cfg.key,
                status="ok",
                offers=offers,
                message=f"{seiten} Seiten gelesen, {grund}; ohne Jahrgang",
            )

        return FetchReport(
            retailer=self.cfg.key,
            status="ok" if offers else "empty",
            offers=offers,
            message=(
                f"{seiten} Seiten gelesen; ohne Jahrgang, den die Schnittstelle nicht nennt"
            ),
        )

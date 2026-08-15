"""Flaschenpost — offene Produkt-API, die nur ausgelistete Ware führt.

Ergebnis vorweg: **diese Quelle liefert keine gültigen Aktionen.** Der Adapter
bleibt bestehen und prüft das bei jedem Lauf nach, aber er meldet ``blocked``,
solange sich daran nichts ändert. Wer nur wissen will, warum Flaschenpost fehlt,
kann nach dem nächsten Abschnitt aufhören zu lesen.

Was schiefging
--------------
Die Schnittstelle antwortet bereitwillig und sieht sauber aus — Preise, Produzent,
Region, Literpreis, alles in Feldern statt in Fliesstext. 477 rabattierte Positionen
kamen daraus in den Bestand. Erst als ein einzelner Link angeklickt wurde, kam
heraus, dass keine davon existiert.

Die Nachprüfung, Schritt für Schritt:

* 20 Adressen aus der Schnittstelle im Browser geöffnet — **20 mal HTTP 404**,
  „Die angeforderte Seite wurde entweder verschoben, existiert nicht …".
* Gegenprobe mit einem Wein von der Kategorieseite des Ladens
  (``mauro-tinto-cosecha_bodegas-mauro``) — **HTTP 200**. Die Prüfmethode taugt
  also, die Adressen taugen nicht.
* Dann der Blick auf die Felder, die vorher niemand gelesen hatte::

      "published": false,  "active": false,  "stock": {"isAvailable": false}

* Über **6000 geprüfte Produkte: kein einziges** publiziert, aktiv oder lieferbar.
  Auch nicht mit ``?published=true``, ``?active=true``, ``?inStock=true`` und drei
  weiteren Filterversuchen — die Schnittstelle kennt schlicht nichts anderes.

``/api/products`` ist demnach keine Ladenschnittstelle, sondern eine Projektion auf
ausgelistetes Sortiment: alte Jahrgänge, ausverkaufte Posten, zurückgezogene Artikel.
Die „Aktionspreise" darin sind historisch. 477 Phantomangebote mit toten Links und
Preisen von gestern sind schlechter als eine Lücke — genau der Fall, für den in
diesem Projekt die Regel gilt, lieber nichts zu zeigen als etwas Plausibles.

Zwei falsche Fährten, damit sie niemand erneut verfolgt
-------------------------------------------------------
1. Das ``url``-Feld hängt ``?_size=7500`` an, während die Webseite an dieser Stelle
   Milliliter erwartet (``?_size=750``). Das sah nach der Ursache aus und war
   keine: mit korrigierter Grösse antwortet die Seite genauso mit 404.
2. Die echten Adressen tragen ein Sprachpräfix (``/de/<slug>``), das der
   Schnittstelle fehlt. Auch das behebt nichts — ``/de/`` plus Slug ist für einen
   lebenden Wein gültig, für die 6000 aus der Schnittstelle nicht.

Beide Beobachtungen stimmen. Beide erklären den Fehler nicht. Der Grund liegt eine
Ebene tiefer, und wer nur an der Adresse schraubt, findet ihn nicht.

Warum der Zugriff selbst in Ordnung war
---------------------------------------
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

Was der Adapter jetzt tut
-------------------------
Er liest ein paar Seiten, verlangt von jedem Produkt ``published`` **und** ``active``
und meldet ``blocked``, wenn er nach ``PROBE_SEITEN`` nichts Publiziertes gefunden
hat. Das kostet wenige Sekunden pro Woche und hat einen Zweck: sollte Flaschenpost
den Pfad je auf lebendes Sortiment umstellen, füllt sich die Quelle von selbst
wieder. Bis dahin steht in der Übersicht ehrlich „blockiert" statt einer Zahl.

Der übrige Lesecode bleibt erhalten und ist geprüft — Preise in Rappen, Streichpreis,
Literpreis als Gegenprobe, ``bottleSize`` in Zehntel-Millilitern. Er wartet nur auf
Daten, die es wert sind.

Zwei Dinge, die weiterhin gelten
--------------------------------
Die Blätterung endet bei Offset 32'000 (65 Seiten à 500), und die Reihenfolge ist
nicht stabil: Produkte wandern zwischen den Seiten, entdoppelt wird über die SKU.

Einen **Jahrgang** nennt die Schnittstelle nirgends. Sollte sie je brauchbar werden,
kostet das die Trinkreife (die Vinum-Tabelle rechnet je Jahrgang), begrenzt den
Vivino-Treffer auf ``wine_level``, und verhindert das Verschmelzen mit demselben Wein
bei anderen Händlern. Lieber diese Lücke als ein geratener Jahrgang.
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

#: Nach so vielen Seiten ohne ein einziges publiziertes Produkt gilt die Quelle als
#: tot. Drei Seiten sind 1500 Produkte — bei einem Bestand, in dem 6000 geprüfte
#: Stück ausnahmslos ausgelistet waren, reicht das für ein Urteil und kostet den
#: Wochenlauf sechs Sekunden statt zwei Minuten.
PROBE_SEITEN = 3

#: Sprachpräfix der Produktseiten. Die Schnittstelle liefert den Slug ohne, die
#: Webseite antwortet ohne ihn mit 404 — nachgemessen an einem Wein, den der Laden
#: aktuell führt.
SPRACHE = "de"


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

    @staticmethod
    def _lebt(mv: dict) -> bool:
        """Steht das Produkt im Laden, oder ist es ausgelistet?

        Die Prüfung, die von Anfang an gefehlt hat. Ohne sie kamen 477 Positionen in
        den Bestand, deren Seiten allesamt 404 lieferten und deren „Aktionspreise"
        aus der Vergangenheit stammten — siehe Modulkopf.
        """
        return bool(mv.get("published")) and bool(mv.get("active"))

    def _offer(self, produkt: dict) -> Offer | None:
        mv = produkt.get("masterVariant") or {}
        if not self._lebt(mv):
            return None
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

        # Sprachpräfix davor, Query-String weg. Das ``url``-Feld der Schnittstelle
        # liefert ``<slug>?_size=7500&_packaging=…`` — ohne ``/de/`` antwortet die
        # Webseite mit 404, und ``_size`` trägt dort die interne Zehntel-Milliliter-
        # Zahl, wo die Seite Milliliter erwartet. Beides ist hier korrigiert. Dass
        # die Adressen trotzdem ins Leere führten, lag an etwas anderem — an
        # ``_lebt``, das es damals nicht gab.
        slug = _de(produkt.get("slug")) or str(mv.get("url") or "").lstrip("/").split("?")[0]
        return self.make_offer(
            name=voll,
            url=f"{BASIS_URL}{SPRACHE}/{slug}" if slug else BASIS_URL,
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

    #: Meldung bei toter Quelle. Steht hier statt inline, weil der Test sie prüft.
    AUSGELISTET = (
        "Schnittstelle führt nur ausgelistete Ware "
        "(kein Produkt published/active, Produktseiten liefern 404)"
    )

    def fetch(self) -> FetchReport:
        offers: list[Offer] = []
        gesehen: set[str] = set()
        seiten = 0
        lebend = 0
        try:
            for seite in range(1, MAX_SEITEN + 1):
                treffer = self._seite(seite)
                if not treffer:
                    break
                seiten += 1
                lebend += sum(1 for p in treffer if self._lebt(p.get("masterVariant") or {}))
                # Früh abbrechen, wenn die Quelle tot ist. Sie ist es seit dem
                # ersten Blick — aber geprüft wird sie weiter, damit sie sich von
                # selbst wieder füllt, falls der Laden den Pfad umstellt.
                if seiten >= PROBE_SEITEN and lebend == 0:
                    return FetchReport(
                        retailer=self.cfg.key,
                        status="blocked",
                        message=f"{self.AUSGELISTET}; {seiten} Seiten geprüft",
                    )
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

        if lebend == 0:
            # Deckt den Fall ab, dass die Schnittstelle weniger als PROBE_SEITEN
            # Seiten hergibt: auch dann ist eine Quelle ohne ein einziges lebendes
            # Produkt blockiert und nicht bloss "leer".
            return FetchReport(
                retailer=self.cfg.key,
                status="blocked",
                message=f"{self.AUSGELISTET}; {seiten} Seiten geprüft",
            )

        return FetchReport(
            retailer=self.cfg.key,
            status="ok" if offers else "empty",
            offers=offers,
            message=(
                f"{seiten} Seiten gelesen; ohne Jahrgang, den die Schnittstelle nicht nennt"
            ),
        )

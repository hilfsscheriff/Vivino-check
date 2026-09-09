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

Was seither dazugekommen ist (09.09.2026)
-----------------------------------------
Eine fremde Untersuchung — sie liegt im Ordner „flaschenpost api" — hat aufgeschrieben,
was hinter ``POST /api/search`` steht, dem Aufruf, den die Webseite selbst macht:
**377 rabattierte Produktgruppen** von 20'753 im Sortiment, publiziert, mit lebenden
Adressen und **mit Jahrgang**. Das ist genau das, was hier fehlt.

Erreichbar ist es nicht. Nachgemessen mit unserem eigenen Client, ehrlicher
User-Agent, keine Tarnung:

===============================  ==========================================
``POST /api/search``             403, ``cf-mitigated: challenge``
``GET /aktionen``                403, Challenge
``GET /letzte-flaschen``         403, Challenge
``GET /tropfen-der-woche``       403, Challenge
``GET /sitemaps/sitemap_index``  403, Challenge — obwohl robots.txt darauf verweist
``GET /api/products``            200 — die ausgelistete Projektion, unbrauchbar
===============================  ==========================================

Die Untersuchung kam durch, weil sie mit ``curl_cffi impersonate="chrome"`` den
TLS-Fingerabdruck eines Browsers nachbaut. Das ist keine Kopfzeile, die man höflich
mitschickt, sondern das Unterlaufen der Bot-Erkennung — dieselbe Klasse Eingriff, die
dieses Projekt bei Coops DataDome ablehnt. Sie wird hier nicht gemacht, und damit ist
Flaschenpost eine blockierte Quelle wie Coop und Migros.

Der **Lesecode** dafür steht trotzdem da, gegen die aufgezeichneten Antworten jener
Untersuchung geprüft (siehe ``tests/test_flaschenpost_suche.py``): fällt die Challenge
— sei es, dass Flaschenpost sie lockert, sei es, dass wir eine Freischaltung
bekommen —, liefert der nächste Lauf die Aktionen von selbst. Bis dahin kostet der
Versuch eine Anfrage pro Woche und macht aus „blockiert" eine Messung von heute statt
eines Zitats aus der Konfiguration.

Was der Adapter jetzt tut
-------------------------
Zuerst den lebenden Index versuchen. Kommt die Challenge, wird der Grund vermerkt und
der offene Pfad gelesen: ein paar Seiten, von jedem Produkt ``published`` **und**
``active`` verlangt, und ``blocked`` gemeldet, wenn nach ``PROBE_SEITEN`` nichts
Publiziertes dabei war. Das kostet wenige Sekunden pro Woche und hat einen Zweck: sollte Flaschenpost
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
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from ..fetching import Blocked
from ..models import Offer
from .base import FetchReport, RetailerAdapter

API_URL = "https://www.flaschenpost.ch/api/products"
BASIS_URL = "https://www.flaschenpost.ch/"

#: Der Aufruf, den die Webseite selbst macht — der **lebende** Index.
#:
#: Am 09.09.2026 dazugekommen, aus einer Untersuchung, die im Ordner „flaschenpost
#: api" liegt. Sie hat gefunden, was hinter dieser Route steht: 377 rabattierte
#: Produktgruppen von 20'753 im Sortiment, mit ``isPublished: true``, lebenden
#: Adressen — und, anders als bei ``/api/products``, **mit Jahrgang**.
#:
#: Erreichbar ist sie für uns nicht. Der Pfad antwortet einem ehrlichen Client mit
#: HTTP 403 und ``cf-mitigated: challenge``; dasselbe gilt für ``/aktionen``,
#: ``/letzte-flaschen``, ``/tropfen-der-woche`` und sogar für die Sitemap, auf die
#: die robots.txt selbst verweist. Die Untersuchung kam durch, weil sie mit
#: ``curl_cffi impersonate="chrome"`` den TLS-Fingerabdruck eines Browsers nachbaut
#: — also genau die Umgehung, die dieses Projekt nicht macht, hier so wenig wie bei
#: Coops DataDome.
#:
#: Warum der Lesecode trotzdem hier steht: fällt die Challenge — sei es, weil
#: Flaschenpost sie lockert, sei es weil wir eine Freischaltung erhalten —, liefert
#: der nächste Lauf die Aktionen von selbst. Bis dahin kostet der Versuch **eine**
#: Anfrage pro Woche und macht aus „blockiert" eine Messung von heute statt eines
#: Zitats aus der Konfiguration.
SUCH_URL = "https://www.flaschenpost.ch/api/search"

#: Die Suche deckelt bei zwölf Treffern und ignoriert jede Blätterung: Seitenparameter,
#: ``perPage=100``, URL-Pagination und Algolia-Stil kamen in der Untersuchung alle vier
#: mit ``page=0, perPage=12`` zurück. Vollständig wird die Menge darum nur über eine
#: Aufteilung der Abfrage — siehe :func:`_blaetter`.
SUCH_PRO_SEITE = 12

#: Facetten, nach denen weitergeteilt wird, wenn ein einzelner Preispunkt für sich
#: schon mehr als zwölf Treffer hat. Reihenfolge ist Absicht: Land teilt am
#: gröbsten, Produzent am feinsten.
TEIL_FACETTEN = (
    "country",
    "attributes.wineType.label",
    "attributes.bottleSizeFormatted",
    "attributes.producer.label",
)

#: ``literPrice.amount`` ist **Rappen pro Deziliter**, nicht pro Liter. Gemessen an
#: allen 670 prüfbaren Produkten der Untersuchung: der selbst gerechnete Rappen-Preis
#: pro Liter war ausnahmslos genau das Zehnfache dieses Feldes, Minimum wie Maximum
#: 10.000. Der Franken-Literpreis ist also ``amount / 10``.
LITERPREIS_TEILER = 10

#: Auf dieser Route steht ``bottleSize`` in **Millilitern** (750), auf
#: ``/api/products`` in Zehntel-Millilitern (7500). Dieselbe Feldbezeichnung, zwei
#: Einheiten — darum hier ohne :data:`GROESSE_TEILER`.

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


def _such_payload(
    facetten: list[dict[str, list[str]]],
    numerisch: list[dict[str, list[str]]] | None = None,
) -> dict[str, Any]:
    """Die Anfrageform, die das Frontend des Shops selbst sendet.

    Alle fünf Felder werden immer mitgeschickt. Welche der Server weglassen lässt,
    ist nicht ermittelt — und ausprobieren hiesse, die Quelle mit Anfragen zu
    beschäftigen, die niemand braucht.
    """
    return {
        "query": "",
        "locale": "de-CH",
        "facetFilters": list(facetten),
        "numericFilters": list(numerisch or []),
        "filters": [],
    }


#: Der Einstieg: alles, was der Shop als rabattiert führt.
AKTIONS_FACETTE: list[dict[str, list[str]]] = [{"attributes.isDiscounted": ["true"]}]


def _rappen(wert: object) -> int:
    """Frankenbetrag als ganze Rappen.

    Über ``Decimal`` und nicht über ``float``: ``19.95 * 100`` ergibt in Fliesskomma
    1994.9999999999998, und ``int()`` macht daraus 1994. Ein Rappen daneben verschiebt
    eine Bereichsgrenze und kann einen Wein aus der Aufzählung fallen lassen.
    """
    return int(Decimal(str(wert)) * 100)


def _facette(daten: dict[str, Any], name: str) -> dict[str, Any] | None:
    for f in daten.get("facets") or []:
        if isinstance(f, dict) and f.get("facetName") == name:
            return f
    return None


def _facettenwerte(facette: dict[str, Any]) -> list[tuple[str, int]]:
    """``[(Wert, Trefferzahl)]`` — die Antwort liefert Objekte, die Testvorlage Paare."""
    aus = []
    for v in facette.get("values") or []:
        if isinstance(v, dict):
            aus.append((str(v.get("value")), int(v.get("hitCount") or 0)))
        elif isinstance(v, (list, tuple)) and len(v) == 2:
            aus.append((str(v[0]), int(v[1])))
    return aus


def _teilpreis(werte: list[tuple[str, int]], lo: int, hi: int) -> int:
    """Der Preis, an dem sich die Trefferzahl etwa halbiert — in Rappen.

    Eine Heuristik, und sie muss eine bleiben: die Preis-Facette gibt höchstens
    **100** Werte zurück. Über einen weiten Bereich ist die Summe der Trefferzahlen
    darum unvollständig, und der Teilungspunkt sitzt nur ungefähr in der Mitte. Das
    ist unschädlich, weil nicht die Teilung die Vollständigkeit sichert, sondern die
    Abstimmung in :func:`_blaetter`: passt die Summe der Blätter nicht zur
    Trefferzahl, bricht die Aufzählung ab, statt eine Teilmenge zu liefern.

    Ohne brauchbare Facettenwerte bleibt die geometrische Mitte des Bereichs.
    """
    preise = sorted((_rappen(v), h) for v, h in werte if lo <= _rappen(v) <= hi)
    gesamt = sum(h for _, h in preise)
    mitte = (lo + hi) // 2
    summe = 0
    for preis, treffer in preise:
        summe += treffer
        if gesamt and summe >= gesamt / 2:
            mitte = min(hi - 1, preis)
            break
    return max(lo, mitte)


def _blaetter(
    suche: Callable[[dict[str, Any]], dict[str, Any]],
    payload: dict[str, Any],
    lo: int | None = None,
    hi: int | None = None,
    benutzt: tuple[str, ...] = (),
) -> dict[str, dict[str, Any]]:
    """Alle Produkte einer Abfrage, geschlüsselt über die SKU.

    Die Suche gibt höchstens zwölf Treffer heraus und lässt sich nicht blättern.
    Vollständig wird die Menge nur, indem die **Abfrage** verkleinert wird, bis jede
    Teilabfrage in ein Zwölferfenster passt: zuerst über den Preisbereich
    (Binärteilung am Median der Trefferzahlen), und wenn ein einzelner Preispunkt für
    sich schon zu viele Treffer hat, über eine weitere Facette.

    Das Verfahren stammt aus der Untersuchung im Ordner „flaschenpost api"; es ist
    dort mit 114 Anfragen auf 393 SKUs gekommen und in dieser Fassung gegen deren
    aufgezeichnete Antworten nachgeprüft.

    **Die Wache ist der eigentliche Punkt.** Nach jedem Teilbaum wird gezählt, ob so
    viele Produktgruppen zusammengekommen sind, wie der Server für diese Abfrage
    gemeldet hat. Fehlt eine, bricht die Aufzählung ab. Eine Teilmenge wäre hier das
    Schlimmste: die Seite zeigte dann zwölf Flaschenpost-Angebote und sähe vollständig
    aus.

    Gezählt wird über ``productID`` und nicht über die SKU. Die Trefferzahl des
    Servers meint Produktgruppen; eine Gruppe kann mehrere SKUs tragen (Jahrgänge,
    Flaschengrössen). Die Vorlage dieses Verfahrens verglich SKUs gegen Gruppen — das
    geht in dieselbe Richtung und ist darum nie aufgefallen, kann eine Lücke aber
    verdecken, sobald eine Gruppe mehrere SKUs mitbringt.
    """
    daten = suche(payload)
    anzahl = int(daten.get("resultsNumber") or 0)
    treffer = [p for p in (daten.get("products") or []) if isinstance(p, dict)]
    gefunden = {str(p.get("sku")): p for p in treffer if p.get("sku")}
    if anzahl <= len(treffer):
        return gefunden

    preisfacette = _facette(daten, "activePrice")
    if preisfacette is None:
        raise Blocked(
            f"Flaschenpost-Suche ohne Preis-Facette bei {anzahl} Treffern — "
            f"Antwortform verändert",
            kind="parse",
        )
    if lo is None or hi is None:
        stats = preisfacette.get("stats") or {}
        if "min" not in stats or "max" not in stats:
            raise Blocked("Flaschenpost-Suche ohne Preisspanne — Antwortform verändert",
                          kind="parse")
        lo, hi = _rappen(stats["min"]), _rappen(stats["max"])

    if lo < hi:
        mitte = _teilpreis(_facettenwerte(preisfacette), lo, hi)
        for a, b in ((lo, mitte), (mitte + 1, hi)):
            kind_payload = {
                **payload,
                "numericFilters": [{"activePrice": [f"{a / 100:.2f} TO {b / 100:.2f}"]}],
            }
            gefunden |= _blaetter(suche, kind_payload, a, b, benutzt)
    else:
        teiler = None
        for name in TEIL_FACETTEN:
            f = _facette(daten, name)
            if name not in benutzt and f and len(_facettenwerte(f)) > 1:
                teiler = (name, f)
                break
        if teiler is None:
            raise Blocked(
                f"Preispunkt {lo / 100:.2f} mit {anzahl} Treffern nicht weiter "
                f"teilbar — die Aufzählung bliebe unvollständig",
                kind="parse",
            )
        name, f = teiler
        for wert, _ in _facettenwerte(f):
            kind_payload = {
                **payload,
                "facetFilters": [*payload["facetFilters"], {name: [wert]}],
            }
            gefunden |= _blaetter(suche, kind_payload, lo, hi, (*benutzt, name))

    gruppen = {str(p.get("productID") or p.get("sku")) for p in gefunden.values()}
    if len(gruppen) < anzahl:
        raise Blocked(
            f"Aufzählung unvollständig: {len(gruppen)} von {anzahl} Produktgruppen — "
            f"lieber keine Flaschenpost-Aktionen als ein Teil davon",
            kind="parse",
        )
    return gefunden


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

    # -- Der lebende Index, wenn er je erreichbar ist -----------------------

    def _suche(self, payload: dict[str, Any]) -> dict[str, Any]:
        res = self.fetcher.post_json(SUCH_URL, payload=payload)
        if not res.ok:
            raise Blocked(f"Flaschenpost-Suche HTTP {res.status_code}", kind="http")
        try:
            daten = json.loads(res.text)
        except json.JSONDecodeError as exc:
            raise Blocked(f"Flaschenpost-Suche lieferte kein JSON: {exc}", kind="parse") from exc
        if not isinstance(daten, dict) or "resultsNumber" not in daten:
            raise Blocked("Flaschenpost-Suche ohne 'resultsNumber' — Antwortform verändert",
                          kind="parse")
        return daten

    @staticmethod
    def _rabatt_gilt(rabatt: dict[str, Any], jetzt: datetime | None = None) -> bool:
        """Gilt dieser Aktionspreis **heute**?

        Die Antwort trägt ``validFrom`` und ``validUntil``, und das ist mehr, als die
        meisten Quellen hergeben — hier steht die Gültigkeit im Feld statt im
        Fliesstext. Genutzt wird sie auch: 185 abgelaufene Aktionen bei Aktionis waren
        der Anlass, das überall zu prüfen, wo ein Datum dasteht.

        Fehlt ein Datum, wird nicht widersprochen. ``isActive`` ist die Aussage des
        Shops und zählt zuerst.
        """
        if not rabatt.get("isActive"):
            return False
        jetzt = jetzt or datetime.now(timezone.utc)
        for feld, vergleich in (("validFrom", True), ("validUntil", False)):
            roh = rabatt.get(feld)
            if not roh:
                continue
            try:
                grenze = datetime.fromisoformat(str(roh).replace("Z", "+00:00"))
            except ValueError:
                continue
            if vergleich and grenze > jetzt:
                return False
            if not vergleich and grenze < jetzt:
                return False
        return True

    def _aus_suchtreffer(self, produkt: dict[str, Any]) -> Offer | None:
        """Ein Suchtreffer als Angebot — oder ``None``, wenn er keines ist."""
        attr = produkt.get("attributes") or {}
        preise = produkt.get("price") or {}
        lager = produkt.get("stock") or {}
        rabatt = preise.get("discountPrice") or {}

        # Dieselbe Grenze wie auf dem anderen Pfad: ohne gültigen Aktionspreis ist es
        # Regalware. Dazu hier, was ``/api/products`` nicht hergab — der Shop sagt
        # selbst, ob der Artikel publiziert und lieferbar ist.
        if not attr.get("isPublished") or not lager.get("isAvailable"):
            return None
        if not self._rabatt_gilt(rabatt):
            return None
        aktion, referenz = rabatt.get("amount"), (preise.get("initialPrice") or {}).get("amount")
        if not isinstance(aktion, (int, float)) or not aktion:
            return None
        if not isinstance(referenz, (int, float)) or referenz <= aktion:
            return None
        aktion, referenz = aktion / 100, referenz / 100

        name = _de(produkt.get("name")) or _de(attr.get("displayName")) or _de(attr.get("name"))
        if not name:
            return None
        produzent = _de(attr.get("producer"))
        voll = f"{name} {produzent}".strip() if produzent else name
        if not self.ist_wein(voll):
            return None

        groesse = attr.get("bottleSize")
        ml = int(groesse) if isinstance(groesse, (int, float)) and groesse else None
        literpreis = (preise.get("literPrice") or {}).get("amount")
        chf_pro_liter = literpreis / LITERPREIS_TEILER if literpreis else None
        if not self._gegenprobe(aktion, ml, chf_pro_liter):
            ml = None

        # Das Gebinde steht als Zahl da und muss nicht aus Text geraten werden.
        # ``packageSize`` ist die kleinste Abnahme; bei 6 kostet die Flasche den
        # genannten Preis, zu haben ist sie nur im Sechserpack.
        gebinde = lager.get("packageSize")
        einheiten = int(gebinde) if isinstance(gebinde, (int, float)) and gebinde > 1 else 1
        if ml and einheiten > 1:
            gebinde_text = f"{einheiten} × {ml} ml"
        elif ml:
            gebinde_text = f"{ml} ml"
        else:
            gebinde_text = ""

        # Der Jahrgang, den der andere Pfad nicht kennt. Damit trägt der Wein
        # Trinkreife und kann jahrgangsgenau bei Vivino treffen statt nur auf
        # Weinebene.
        jahr = attr.get("vintage") or attr.get("year")
        try:
            jahrgang = int(jahr) if jahr else None
        except (TypeError, ValueError):
            jahrgang = None

        slug = str(produkt.get("url") or "").lstrip("/").split("?")[0]
        return self.make_offer(
            name=voll,
            url=f"{BASIS_URL}{SPRACHE}/{slug}" if slug else BASIS_URL,
            price_text=aktion,
            reference_text=referenz,
            gebinde_text=gebinde_text,
            article_no=str(produkt.get("sku") or "") or None,
            vintage=jahrgang,
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
        """Erst der lebende Index, dann der offene Pfad.

        Die Reihenfolge ist die Rangfolge der Auskunft: ``/api/search`` führt das
        Sortiment, das im Laden steht, ``/api/products`` das ausgelistete. Der erste
        Versuch kostet eine Anfrage und macht aus „blockiert" eine Messung von heute.
        """
        try:
            treffer = _blaetter(self._suche, _such_payload(AKTIONS_FACETTE))
        except Blocked as exc:
            # Kein Umgehen. Der Grund wird mitgeschrieben, damit in der Übersicht
            # steht, *warum* die Quelle fehlt, und damit auffällt, wenn er sich
            # ändert.
            such_grund = str(exc)
        else:
            offers = [o for p in treffer.values() if (o := self._aus_suchtreffer(p))]
            return FetchReport(
                retailer=self.cfg.key,
                status="ok" if offers else "empty",
                message=(
                    f"{len(offers)} Aktionen aus dem lebenden Index "
                    f"({len(treffer)} SKU geprüft)"
                ),
                offers=offers,
            )

        bericht = self._aus_produkten()
        bericht.message = f"{such_grund}; {bericht.message}"
        return bericht

    def _aus_produkten(self) -> FetchReport:
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

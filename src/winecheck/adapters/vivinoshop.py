"""Vivinos eigene Aktionen — die einzige Quelle, die ihre Note mitbringt.

Vivino ist in diesem Projekt die Bewertungsquelle. Es ist daneben aber auch ein
Marktplatz, und derselbe ``/api/explore/explore``-Aufruf, der die Noten liefert,
gibt mit ``discount_prices=true`` die reduzierten Weine für die Schweiz aus.

Was das besonders macht
-----------------------
Bei jedem anderen Händler steht am Anfang ein Namensabgleich: aus „Ribera del Duero
DO Protos Roble 2024" muss erst der Vivino-Eintrag gefunden werden, und das gelingt
in rund vier von zehn Fällen. Hier entfällt dieser Schritt — die Antwort enthält die
Wein-ID, die Note und die Zahl der Bewertungen. Keine Suche, keine Fehlzuordnung,
keine Lücke.

Genau daraus folgt aber auch, dass diese Weine im Bericht **getrennt** ausgewiesen
werden. Sie hätten sonst in jeder Rangliste die Nase vorn, nicht weil sie besser
wären, sondern weil bei den Schweizer Händlern die Hälfte der Weine mangels
auffindbarer Note gar nicht erst antritt.

Preisbasis
----------
Der Markt wird auf ``ch``/``CHF`` festgelegt, und die Antwort bestätigt das im Feld
``market``. Jeder Preis trägt seinen ``bottle_type``; übernommen wird nur, was als
``Flasche (0,75 l)`` ausgewiesen ist. Andere Gebinde — Magnum, Sechserkarton —
werden übersprungen statt umgerechnet: die Angabe, wie viele Flaschen in einem
Karton stecken, steht in dieser Antwort nicht, und ein geratener Literpreis erzeugt
einen Scheinsieger.

Keine Umgehung
--------------
Es ist dieselbe öffentliche Schnittstelle, die dieses Projekt für die Bewertungen
ohnehin abfragt, mit demselben Tempolimit von einer Anfrage pro zwei Sekunden. Es
wird kein Schutzmechanismus umgangen und keine Anmeldung benötigt.
"""

from __future__ import annotations

import json
import time
from typing import Any, Iterator

from ..fetching import Blocked
from ..models import Offer
from ..ratings.vivino import API_URL, PER_PAGE, _struktur
from .base import FetchReport, RetailerAdapter

#: Die Farben, die dieses Projekt führt — dieselben wie bei der Bewertungsabfrage.
#: Ohne Angabe liefert die Schnittstelle auch Sake und Bier.
WEINFARBEN = (1, 2, 3, 4, 7, 24)

#: Nur die normale Flasche. ``bottle_type.id`` 1 ist „Flasche (0,75 l)"; alles
#: andere ist Magnum, Halbflasche oder Karton, und wie viele Flaschen darin
#: stecken, sagt diese Antwort nicht.
FLASCHE_075 = 1

#: Wie viele Seiten je Farbe höchstens geholt werden. Bei 24 Treffern je Seite sind
#: das 480 Weine pro Farbe — mehr als die Schnittstelle für die Schweiz überhaupt
#: reduziert führt (484 Rotweine beim Bauen). Die Grenze ist eine Reissleine gegen
#: eine Endlosschleife, keine inhaltliche Beschränkung.
MAX_SEITEN = 20


def _preis(m: dict) -> dict | None:
    p = m.get("price")
    return p if isinstance(p, dict) else None


def _name(m: dict) -> str:
    """Weingut und Wein zusammen — so, wie ein Mensch den Wein wiedererkennt.

    Vivino trennt beides: „Cune Imperial Rioja Reserva" heisst dort Weingut
    „Imperial", Wein „Rioja Reserva". Nur der Weinname ergäbe „Rioja Reserva", eine
    Gattungsbezeichnung.
    """
    wein = ((m.get("vintage") or {}).get("wine") or {})
    name = (wein.get("name") or "").strip()
    haus = ((wein.get("winery") or {}).get("name") or "").strip()
    if haus and haus.lower() not in name.lower():
        return f"{haus} {name}".strip()
    return name


class VivinoShopAdapter(RetailerAdapter):
    """Erbt Preisnormalisierung und Eigenmarken-Prüfung, ersetzt aber den Ablauf.

    Der gemeinsame Ablauf der Basisklasse holt HTML-Seiten und reicht sie an
    ``parse``. Diese Quelle spricht JSON und wird geblättert, bis die Schnittstelle
    nichts mehr liefert — darum ist ``fetch`` überschrieben und ``parse`` leer.
    """

    key = "vivinoshop"

    def __init__(self, cfg, fetcher):
        super().__init__(cfg, fetcher)
        #: Was hier gesammelt wird, kann ``rate`` ohne eine einzige Netzabfrage in
        #: den Bewertungs-Cache legen: (Name, Jahrgang, Wein-ID, Note, Anzahl).
        self.bewertungen: list[dict[str, Any]] = []

    # -- Netz --------------------------------------------------------------
    def _seite(self, farbe: int, seite: int) -> list[dict]:
        params: list[tuple[str, object]] = [
            ("country_code", "CH"),
            ("currency_code", "CHF"),
            ("language", "de"),
            ("discount_prices", "true"),
            ("order_by", "discount_percent"),
            ("order", "desc"),
            ("min_rating", "1"),
            ("per_page", str(PER_PAGE)),
            ("page", str(seite)),
            ("wine_type_ids[]", farbe),
        ]
        res = self.fetcher.get(API_URL, params=params, expect_json=True)
        if not res.ok:
            raise Blocked(f"Vivino API HTTP {res.status_code}", kind="http")
        try:
            payload = json.loads(res.text)
        except json.JSONDecodeError as exc:
            raise Blocked(f"Vivino API lieferte kein JSON: {exc}", kind="parse") from exc
        ev = payload.get("explore_vintage") or {}
        return [m for m in (ev.get("matches") or []) if isinstance(m, dict)]

    def _alle(self) -> Iterator[dict]:
        for farbe in WEINFARBEN:
            for seite in range(1, MAX_SEITEN + 1):
                treffer = self._seite(farbe, seite)
                if not treffer:
                    break
                yield from treffer
                if len(treffer) < PER_PAGE:
                    break

    # -- Umsetzung ---------------------------------------------------------
    def _offer(self, m: dict) -> Offer | None:
        p = _preis(m)
        if not p:
            return None
        betrag, vorher = p.get("amount"), p.get("discounted_from")
        if not isinstance(betrag, (int, float)) or not betrag:
            return None
        if not isinstance(vorher, (int, float)) or vorher <= betrag:
            return None

        # Nur die 0,75-l-Flasche. Andere Gebinde nennen ihre Stückzahl nicht.
        flasche = (p.get("bottle_type") or {}).get("id")
        if flasche != FLASCHE_075:
            return None

        name = _name(m)
        if not name:
            return None

        v = m.get("vintage") or {}
        wein = v.get("wine") or {}
        stat = v.get("statistics") or {}
        jahr = v.get("year")
        jahrgang = int(jahr) if isinstance(jahr, int) or (isinstance(jahr, str) and jahr.isdigit()) else None

        wein_id = wein.get("id")
        # Der Jahrgang gehört in die Adresse. Ohne ihn zeigt Vivino den Jahrgang, den
        # es gerade für den passendsten hält, und das ist selten der, für den unser
        # Angebot gilt. Gemeldet an „The Standish The Relic Shiraz-Viognier": unser
        # Angebot ist der 2019er zu CHF 53.78 statt 95.92, die Seite eröffnete mit
        # dem 2021er zu CHF 99.50 ohne Abschlag. Wer draufklickt, hält den Rabatt für
        # erfunden — dabei stimmt er, nur für eine andere Flasche.
        #
        # Derselbe Parameter, den auch das Trinkfenster braucht (siehe
        # ``VivinoAdapter._trinkfenster``): ohne ``?year=`` antwortet Vivino
        # jahrgangslos.
        wein_url = f"https://www.vivino.com/w/{wein_id}" if wein_id else (p.get("url") or "")
        # Die Angebotsadresse trägt den Jahrgang, die Weinadresse nicht: der Saat-Eintrag
        # unten identifiziert den *Wein* und seine Note gilt oft über alle Jahrgänge.
        url = f"{wein_url}?year={jahrgang}" if wein_id and jahrgang else wein_url

        note = stat.get("ratings_average")
        anzahl = stat.get("ratings_count")
        if isinstance(note, (int, float)) and wein_id:
            self.bewertungen.append({
                "name": name, "vintage": jahrgang, "wine_id": wein_id,
                "rating": float(note), "rating_count": anzahl, "url": wein_url,
                # Die Farbe. Sie kommt aus Vivinos Weindatenbank und ist damit
                # verlässlicher als jede Namensanalyse — ohne sie fielen 400 Weine
                # auf "unbekannt" zurück, weil Namen wie "Astrale Special Edition"
                # oder "The Guv'nor" kein Farbwort enthalten.
                "wine_type_id": wein.get("type_id"),
                # Machart und Herkunft. Sie stehen in derselben Antwort wie die Note
                # und kosten keine Anfrage. Ohne sie bekämen ausgerechnet die Weine
                # keinen Stil-Typ, deren Note am verlässlichsten ist: für sie fragt
                # ``rate`` bei Vivino gar nicht mehr nach, weil die Antwort schon
                # feststeht — und griff damit auch die Struktur nie ab. Über 700 von
                # 1450 Weinen blieben so ohne Typ.
                "style_name": (wein.get("style") or {}).get("name") or "",
                "country": (((wein.get("region") or {}).get("country") or {}).get("name") or ""),
                "region_name": (wein.get("region") or {}).get("name") or "",
                "taste": _struktur((wein.get("taste") or {}).get("structure")),
                "style_baseline": _struktur((wein.get("style") or {}).get("baseline_structure")),
            })

        return self.make_offer(
            name=name,
            url=url,
            price_text=float(betrag),
            reference_text=float(vorher),
            # Nur die Grösse, ohne den Namen. Sie steht oben schon fest
            # (``bottle_type.id == 1``), und der Name kann sie nur noch
            # durcheinanderbringen: „Moët & Chandon Ice Impérial (Demi-Sec)" wurde
            # über das „Demi" als halbe Flasche gelesen, womit die Normalisierung
            # zwei Volumen fand und den Wein als unsicher aus der Rangliste warf.
            gebinde_text="75 cl",
            article_no=str(p.get("sku") or "") or None,
            vintage=jahrgang,
            vat_included=True,
            price_basis="bottle",
        )

    def parse(self, html: str, url: str) -> list[Offer]:
        """Nur der Vollständigkeit halber — diese Quelle liefert kein HTML."""
        return []

    def fetch(self):
        offers: list[Offer] = []
        gesehen: set[str] = set()
        try:
            for m in self._alle():
                # Ein Wein steht in mehreren Farbabfragen nie doppelt, wohl aber
                # mehrfach innerhalb einer Farbe, wenn zwei Händler ihn führen.
                # Behalten wird der erste — die Antwort ist nach Rabatt sortiert.
                p = _preis(m) or {}
                schluessel = str(p.get("id") or ((m.get("vintage") or {}).get("id") or ""))
                if schluessel and schluessel in gesehen:
                    continue
                offer = self._offer(m)
                if offer is not None:
                    gesehen.add(schluessel)
                    offers.append(offer)
        except Blocked as exc:
            return FetchReport(retailer=self.cfg.key, status="blocked", message=str(exc))

        return FetchReport(
            retailer=self.cfg.key,
            status="ok" if offers else "empty",
            offers=offers,
            message=f"{len(self.bewertungen)} Noten kamen mit — kein Namensabgleich nötig",
        )

    # -- Noten weiterreichen ------------------------------------------------
    def saee_bewertungen(self, cache) -> int:
        """Legt die mitgelieferten Noten so im Cache ab, dass ``rate`` sie findet.

        ``rate`` fragt für jeden Wein bei Vivino nach und schaut vorher in den
        Cache. Für diese Weine steht die Antwort schon fest — sie kam mit dem
        Angebot. Wird sie unter demselben Schlüssel abgelegt, den die Suche
        verwenden würde, spart das nicht nur einige hundert Abfragen: es schliesst
        auch aus, dass die Suche einen *anderen* Wein findet als den, der hier
        tatsächlich verkauft wird.

        Der Status ist ``exact``, und das ist keine Schönfärberei: die Wein-ID kam
        von Vivino selbst, es wurde nichts zugeordnet.

        Gibt die Zahl der geschriebenen Noten zurück.
        """
        geschrieben = 0
        for b in self.bewertungen:
            cache.put_rating(
                "vivino",
                b["name"],
                b["vintage"],
                {
                    "status": "exact",
                    "query": b["name"],
                    "url": b["url"],
                    "note": "Note kam mit dem Angebot — kein Namensabgleich nötig",
                    "rating": b["rating"],
                    "rating_count": b["rating_count"],
                    "matched_name": b["name"],
                    "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "match_confidence": "exact",
                    "wine_type_id": b.get("wine_type_id"),
                    "style_name": b.get("style_name") or "",
                    "country": b.get("country") or "",
                    "region_name": b.get("region_name") or "",
                    "taste": b.get("taste") or {},
                    "style_baseline": b.get("style_baseline") or {},
                    # Kein Marktpreis: er käme von Vivino und würde mit einem
                    # Vivino-Preis verglichen. Der Vergleich wäre zirkulär, und
                    # die Schnäppchen-Spalte bliebe eine Aussage über sich selbst.
                    "market_price_note": "entfällt — Angebot und Marktpreis stammen beide von Vivino",
                    "candidates": [],
                },
                status="exact",
            )
            geschrieben += 1
        return geschrieben

"""Prodega / Transgourmet — der aufwendigste Adapter.

Drei Wege, in dieser Reihenfolge:

1. **Prodega Easy, öffentlicher JSON-Katalog.** ``web.transgourmet.ch`` liefert unter
   ``/de/prodega-easy/catalog.data`` die Katalogdaten als turbo-stream-JSON —
   **ohne Login**, ``isAuthenticated: false``. Mit ``hwg=3`` (Warengruppe Getränke),
   ``searchTerm=wein`` und ``a=true`` (nur Aktionen) sind das rund 85 Weinpositionen
   mit Artikelnummer, Bezeichnung inkl. Volumen, Aktions- und Normalpreis sowie
   Gültigkeitszeitraum. Das ist die Hauptquelle.

   Wichtig für die Preisrechnung: ``unitText`` sagt, worauf sich ``price`` bezieht
   (``Fl`` = pro Flasche), ``sellUnit`` nur, wie verkauft wird (``Kt`` = Karton).
   ``pricePerSellUnit`` geteilt durch ``price`` ergibt die Flaschenzahl im Karton.
   Alle Preise sind exkl. MwSt.

2. **Wochenprospekt als PDF, öffentlich.** ``transgourmet.ch/de/aktionen`` verlinkt die
   Aktionsbroschüre der Woche unter ``www-static.transgourmet.ch``. Sie sagt selbst:
   *"Alle Angebote exklusive MwSt und inklusive VRG"*. Wird nur noch als **Rückfall**
   gelesen, wenn der Easy-Katalog nichts liefert: der Rasterparser ist heuristisch,
   das JSON ist es nicht.

3. **Webkatalog hinter Login.** Nur für marktspezifische Preise nötig. Zugangsdaten
   kommen aus ``PRODEGA_USER``/``PRODEGA_PASS`` oder als Session-Cookie aus
   ``PRODEGA_COOKIE`` — nie aus dem Code, nie aus dem Repo. Ungetestet.

Zur robots.txt: ``transgourmet.ch`` verbietet Crawlern ``/login``, ``/user/login`` und
``/search/``. Die Regeln greifen als Pfad-Präfix und damit nicht auf die
sprachpräfixierte Variante ``/de/user/login``. ``web.transgourmet.ch`` ist eine eigene
Domain mit eigener robots.txt, die der Fetcher separat prüft.

Zu ``easy.prodega.ch``: leitet mit Cookie-Check auf ``web.transgourmet.ch`` weiter und
ist als Einstieg unbrauchbar — der Katalogpfad dort funktioniert aber direkt.
"""

from __future__ import annotations

import re
import urllib.parse

from selectolax.parser import HTMLParser

from ..fetching import Blocked
from ..models import Offer, PriceConfidence
from .base import FetchReport, RetailerAdapter, looks_like_wine, parse_price
from ..turbostream import TurboStream
from .prospekt_pdf import ProspektPdfMixin

PROMO_PAGE = "https://www.transgourmet.ch/de/aktionen"
LOGIN_PAGE = "https://www.transgourmet.ch/de/user/login"
WINE_CATEGORY = "https://www.transgourmet.ch/de/sortiment/wein"

#: Prodega Easy, JSON-Katalog. ``a=true`` filtert auf Aktionen — ohne ihn käme das
#: ganze Sortiment mit 23'175 Artikeln.
EASY_CATALOG = "https://web.transgourmet.ch/de/prodega-easy/catalog.data"
EASY_PAGE = "https://web.transgourmet.ch/de/prodega-easy/catalog"

#: Hier stand ``{"searchTerm": "wein", "hwg": "3", "a": "true"}``, und daran waren
#: zwei Dinge falsch. Beides am 10.8.2026 gemessen:
#:
#: * ``searchTerm`` **verbietet die robots.txt** der Domain (``Disallow:
#:   /*?searchTerm=*``). Dass der Adapter trotzdem damit abfragte, lag an einer Lücke
#:   im Prüfer — Pythons ``robotparser`` kennt keine Wildcards und liess die Regel
#:   fallen. Siehe :class:`winecheck.fetching.Robots`.
#: * ``hwg=3`` filterte nichts. Die Facette heisst ``hwgs``, und der Katalog nimmt sie
#:   nur über einen POST an; als Query-Parameter wird sie ignoriert. Die Antwort war
#:   jedes Mal der volle Aktionsbestand, nur eben über ``searchTerm`` eingeengt.
#:
#: Statt zu suchen und zu filtern holen wir jetzt **alle** Aktionsseiten und
#: entscheiden selbst, was Wein ist. Das ist erlaubt, vollständig und nutzt die
#: Weinerkennung, die dieses Projekt für jeden anderen Händler ohnehin hat: über die
#: Suche kamen 35 Weine, über die Warengruppe zählt Prodega selbst 47.
EASY_PARAMS = {"a": "true"}

#: pageSize ist serverseitig auf 100 festgelegt und lässt sich nicht erhöhen. Bei
#: rund 1'300 Aktionen sind das vierzehn Seiten; die Grenze ist die Absicherung,
#: falls der Bestand wächst, und kostet bei zwei Sekunden Abstand eine halbe Minute.
EASY_MAX_PAGES = 20

#: Die Wochenbroschüre heisst "kwNN-...-aktionen-d.pdf". Andere PDFs auf der Seite
#: sind Kataloge und Marktberichte ohne Aktionspreise.
_RE_PROMO_PDF = re.compile(r"kw\d{1,2}[^\"']*aktion[^\"']*\.pdf", re.I)
_RE_ANY_PDF = re.compile(r"https://[^\"']+\.pdf", re.I)


class ProdegaAdapter(ProspektPdfMixin, RetailerAdapter):
    key = "prodega"

    def __init__(self, cfg, fetcher):
        super().__init__(cfg, fetcher)
        self.uncertain: list[str] = []
        self.logged_in = False

    # ------------------------------------------------------------------ Login
    def login(self) -> tuple[bool, str]:
        """Meldet sich an, falls Zugangsdaten vorliegen.

        Returns:
            ``(erfolgreich, Klartextnotiz)``. Ohne Zugangsdaten ist das kein Fehler —
            der Prospekt-Weg funktioniert auch ohne.
        """
        user, password, cookie = self.cfg.credentials()

        if cookie:
            self.fetcher.set_cookie_header(cookie, domain=".transgourmet.ch")
            self.logged_in = True
            return True, "Session-Cookie aus PRODEGA_COOKIE übernommen"

        if not (user and password):
            return False, (
                "keine Zugangsdaten gesetzt (PRODEGA_USER/PRODEGA_PASS oder "
                "PRODEGA_COOKIE in .env) — nur öffentlicher Wochenprospekt gelesen"
            )

        try:
            page = self.fetcher.get(LOGIN_PAGE)
        except Blocked as exc:
            return False, f"Login-Seite nicht erreichbar: {exc}"

        form = _login_form(page.text)
        if form is None:
            return False, "Login-Formular nicht gefunden (Layout geändert?)"

        # Drupal verlangt die versteckten Felder unverändert zurück.
        data = {**form, "name": user, "pass": password}
        try:
            res = self.fetcher.post(LOGIN_PAGE, data=data)
        except Blocked as exc:
            return False, f"Login abgelehnt: {exc}"

        body = res.text.lower()
        ok = res.ok and ("abmelden" in body or "logout" in body or "mein konto" in body)
        if not ok and "nicht erkannt" in body or "unrecognized" in body:
            return False, "Login fehlgeschlagen — Benutzername oder Passwort abgelehnt"
        self.logged_in = ok
        return ok, "angemeldet" if ok else "Login-Status unklar, fahre öffentlich fort"

    # ------------------------------------------------------- Weg 1: Easy-JSON
    def _fetch_easy(self) -> tuple[list[Offer], str]:
        """Aktionen aus dem öffentlichen Prodega-Easy-Katalog."""
        offers: list[Offer] = []
        pages = 0
        geprueft = 0
        for page in range(EASY_MAX_PAGES):
            params = {**EASY_PARAMS, "page": str(page)}
            try:
                res = self.fetcher.get(EASY_CATALOG, params=params, expect_json=True)
            except Blocked as exc:
                return offers, f"Easy-Katalog blockiert auf Seite {page}: {exc}"
            stream = TurboStream.parse(res.text)
            if stream is None:
                return offers, f"Easy-Katalog lieferte kein turbo-stream-JSON (Seite {page})"
            articles = _easy_articles(stream)
            if not articles:
                break
            pages += 1
            geprueft += len(articles)
            for art in articles:
                offer = self._offer_from_easy(art)
                if offer is not None:
                    offers.append(offer)

        note = (f"Easy-Katalog: {len(offers)} Weinaktionen aus {geprueft} Aktionen "
                f"auf {pages} Seite(n)")
        return offers, note

    def _offer_from_easy(self, art: dict) -> Offer | None:
        """Ein Artikel aus dem Easy-Katalog.

        ``price`` bezieht sich auf ``unitText``: bei ``Fl`` ist es der Flaschenpreis,
        exkl. MwSt. Steht dort etwas anderes, wird die Bezugsgrösse nicht geraten —
        dann fliegt die Position mit ``price_confidence = low`` aus dem Ranking.
        """
        name = _clean(art.get("description"))
        if not name or not looks_like_wine(name):
            return None
        price = _num(art.get("price")) or _num(art.get("actionPrice"))
        if price is None:
            return None
        reference = _num(art.get("normalPrice")) or _num(art.get("oldPrice"))

        unit = _clean(art.get("unitText"))
        per_bottle = unit.lower() in ("fl", "flasche", "bouteille", "st", "stk")
        gebinde = name  # trägt das Volumen, z.B. "Sensuale Primitivo …, 75 cl"
        if not per_bottle:
            gebinde = f"{name} {unit}".strip()

        offer = self.make_offer(
            name=name,
            url=_easy_item_url(art),
            price_text=price,
            reference_text=reference,
            gebinde_text=gebinde,
            article_no=_clean(art.get("articleNumber")) or None,
            source_note=_easy_note(art),
            price_basis="bottle" if per_bottle else "auto",
            vat_included=False,
        )
        if not per_bottle:
            offer.price_confidence = PriceConfidence.LOW
            offer.source_note = _join(
                offer.source_note,
                f"Bezugsgrösse '{unit}' nicht als Flasche erkannt — nicht im Ranking",
            )
        return offer

    # ------------------------------------------------------------------ Ablauf
    def fetch(self) -> FetchReport:
        report = FetchReport(retailer=self.cfg.key)
        notes: list[str] = []

        ok, login_note = self.login()
        notes.append(login_note)

        # -- Weg 1: öffentlicher Easy-Katalog (JSON) -----------------------
        easy_offers, easy_note = self._fetch_easy()
        report.offers.extend(easy_offers)
        notes.append(easy_note)
        report.resolved_url = EASY_PAGE

        # -- Weg 2: Wochenprospekt, nur als Rückfall -----------------------
        if not easy_offers:
            pdf_url = ""
            try:
                promo = self.fetcher.get(PROMO_PAGE)
                pdf_url = _find_promo_pdf(promo.text)
            except Blocked as exc:
                notes.append(f"Aktionsseite blockiert: {exc}")

            if pdf_url:
                try:
                    pdf = self.fetcher.get(pdf_url)
                    offers, uncertain = self.offers_from_pdf(pdf.content_bytes, pdf_url)
                    report.offers.extend(offers)
                    self.uncertain.extend(uncertain)
                    report.resolved_url = pdf_url
                    notes.append(
                        f"Rückfall Wochenprospekt {pdf_url.rsplit('/', 1)[-1]}: "
                        f"{len(offers)} Weinpositionen"
                        + (f", {len(uncertain)} unsicher" if uncertain else "")
                    )
                except Blocked as exc:
                    notes.append(f"Prospekt-PDF nicht ladbar: {exc}")
                except Exception as exc:  # noqa: BLE001
                    notes.append(f"Prospekt-PDF nicht lesbar: {exc}")
            else:
                notes.append("kein Wochenprospekt-PDF auf der Aktionsseite gefunden")

        # -- Weg 2: Webkatalog, nur mit Login ------------------------------
        if self.logged_in:
            try:
                cat = self.fetcher.get(_market_url(WINE_CATEGORY, self.cfg.market))
                found = self._parse_catalog(cat.text, str(cat.url))
                report.offers.extend(found)
                notes.append(f"Webkatalog: {len(found)} Positionen")
            except Blocked as exc:
                notes.append(f"Webkatalog blockiert: {exc}")
        else:
            notes.append("Webkatalog übersprungen (nicht angemeldet)")

        report.message = "; ".join(n for n in notes if n)
        if not report.offers:
            report.status = "empty"
        return report

    # ------------------------------------------------------------------ Katalog
    def _parse_catalog(self, html: str, url: str) -> list[Offer]:
        """Webkatalog-Parser.

        Ungetestet: ohne gültige Zugangsdaten war der eingeloggte Katalog nicht
        erreichbar. Bewusst tolerant geschrieben und liefert im Zweifel nichts,
        statt falsche Preise zu erzeugen.
        """
        tree = HTMLParser(html)
        offers: list[Offer] = []
        for tile in tree.css("[class*=product], [class*=article], li[class*=item]"):
            name_node = tile.css_first("a[href], h2, h3, .title, [class*=name]")
            if name_node is None:
                continue
            name = re.sub(r"\s+", " ", name_node.text() or "").strip()
            if not name or not looks_like_wine(name):
                continue
            text = re.sub(r"\s+", " ", tile.text() or "")
            price = parse_price(text)
            if price is None:
                continue
            href = name_node.attributes.get("href") or ""
            offers.append(
                self.make_offer(
                    name=name,
                    url=urllib.parse.urljoin(url, href),
                    price_text=price,
                    gebinde_text=text,
                    source_note="Webkatalog (eingeloggt)",
                )
            )
        return offers


def _login_form(html: str) -> dict[str, str] | None:
    """Versteckte Drupal-Felder aus dem Login-Formular ziehen."""
    tree = HTMLParser(html)
    for form in tree.css("form"):
        inputs = form.css("input")
        if not any(i.attributes.get("type") == "password" for i in inputs):
            continue
        data: dict[str, str] = {}
        for i in inputs:
            name = i.attributes.get("name")
            if not name:
                continue
            if i.attributes.get("type") in ("text", "password"):
                continue
            data[name] = i.attributes.get("value") or ""
        data.setdefault("form_id", "user_login_form")
        data.setdefault("op", "Anmelden")
        return data
    return None


_RE_YEAR_MONTH = re.compile(r"/(\d{4})-(\d{2})/")
_RE_KW = re.compile(r"kw(\d{1,2})", re.I)


def _promo_sort_key(url: str) -> tuple[int, int, int]:
    """Sortierschlüssel (Jahr, Monat, Kalenderwoche).

    Bewusst nicht lexikografisch: ``kw10`` sortiert als Text vor ``kw9``, und im
    selben Monat können beide vorkommen. Der Pfad trägt beides —
    ``/public/2026-08/kw33-agh-aktionen-d.pdf``.
    """
    ym = _RE_YEAR_MONTH.search(url)
    kw = _RE_KW.search(url)
    return (
        int(ym.group(1)) if ym else 0,
        int(ym.group(2)) if ym else 0,
        int(kw.group(1)) if kw else 0,
    )


def _find_promo_pdf(html: str) -> str:
    """Die Aktionsbroschüre der aktuellen Woche heraussuchen."""
    promo = [u for u in _RE_ANY_PDF.findall(html or "") if _RE_PROMO_PDF.search(u)]
    if not promo:
        return ""
    return max(promo, key=_promo_sort_key)


def _market_url(url: str, market: str | None) -> str:
    """Sortiment ist marktspezifisch — Markt als Parameter anhängen, falls gesetzt."""
    if not market:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}market={urllib.parse.quote(market)}"


# --------------------------------------------------------------- Easy-Katalog

def _easy_articles(stream: TurboStream) -> list[dict]:
    """Die Artikelliste aus der Suchantwort. Sub-Artikel (``zzArticles``) bleiben
    draussen — das sind Gebindevarianten desselben Artikels."""
    best: list[dict] = []
    for obj in stream.objects_with("articles"):
        arts = obj.get("articles")
        if isinstance(arts, list) and len(arts) > len(best):
            best = [a for a in arts if isinstance(a, dict) and a.get("articleNumber")]
    return best


def _easy_item_url(art: dict) -> str:
    """Suchlink auf den Artikel — Prodega Easy hat keine stabile Detail-URL pro
    Artikelnummer, die ohne Session funktioniert."""
    number = _clean(art.get("articleNumber"))
    if not number:
        return EASY_PAGE
    return f"{EASY_PAGE}?searchTerm={urllib.parse.quote(number)}&hwg=3"


def _easy_note(art: dict) -> str:
    bits = ["Prodega Easy"]
    frm, to = _clean(art.get("actionValidFrom"))[:10], _clean(art.get("actionValidTo"))[:10]
    if frm and to:
        bits.append(f"Aktion {_de_date(frm)}\u2013{_de_date(to)}")
    sell = _clean(art.get("sellUnit"))
    unit = _clean(art.get("unitText"))
    per_unit = _num(art.get("pricePerSellUnit"))
    price = _num(art.get("price"))
    if sell and unit and per_unit and price:
        # pricePerSellUnit / price ergibt die Stueckzahl im Verkaufsgebinde.
        count = round(per_unit / price) if price else 0
        if count > 1:
            bits.append(f"Verkauf per {sell} = {count} \u00d7 {unit}")
    return "; ".join(bits)


def _de_date(iso: str) -> str:
    try:
        y, m, d = iso.split("-")
        return f"{int(d)}.{int(m)}.{y}"
    except ValueError:
        return iso


def _num(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _clean(value: object) -> str:
    if value is None or isinstance(value, (dict, list, bool)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _join(a: str, b: str) -> str:
    return "; ".join(x for x in (a, b) if x)

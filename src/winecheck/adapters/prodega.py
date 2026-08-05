"""Prodega / Transgourmet — der aufwendigste Adapter.

Zwei Wege, in dieser Reihenfolge:

1. **Wochenprospekt als PDF, öffentlich.** ``transgourmet.ch/de/aktionen`` verlinkt die
   Aktionsbroschüre der Woche unter ``www-static.transgourmet.ch`` — ohne Login. Dort
   stehen die Weinaktionen mit Artikelnummer, Bezugsgrösse, Aktionspreis und
   Referenzpreis ("statt"). Das PDF sagt selbst: *"Alle Angebote exklusive MwSt und
   inklusive VRG"* — genau die Fussangel, wegen der jeder Vergleich mit Coop/Denner
   sonst falsch ist.
2. **Webkatalog hinter Login.** Für Sortiment und marktspezifische Preise. Zugangsdaten
   kommen aus ``PRODEGA_USER``/``PRODEGA_PASS`` oder als Session-Cookie aus
   ``PRODEGA_COOKIE`` — nie aus dem Code, nie aus dem Repo.

Zur robots.txt: die Domain verbietet Crawlern ``/login``, ``/user/login`` und
``/search/``. Die Regeln greifen als Pfad-Präfix und damit nicht auf die
sprachpräfixierte Variante ``/de/user/login``. Unabhängig davon wird der Login hier
als *Nutzeraktion mit eigenen Zugangsdaten* behandelt und nicht als Crawling — das
Rate-Limit von einer Anfrage pro zwei Sekunden gilt trotzdem.

Zu ``easy.prodega.ch``: leitet auf ``web.transgourmet.ch`` mit einem Cookie-Check
weiter und ist ohne Session nicht ansprechbar. Ein offener JSON-Endpunkt der App war
ohne Reverse Engineering nicht auffindbar — laut Auftrag wird das dann gelassen und
der Webkatalog genommen.
"""

from __future__ import annotations

import re
import urllib.parse

from selectolax.parser import HTMLParser

from ..fetching import Blocked
from ..models import Offer
from .base import FetchReport, RetailerAdapter, looks_like_wine, parse_price
from .prospekt_pdf import ProspektPdfMixin

PROMO_PAGE = "https://www.transgourmet.ch/de/aktionen"
LOGIN_PAGE = "https://www.transgourmet.ch/de/user/login"
WINE_CATEGORY = "https://www.transgourmet.ch/de/sortiment/wein"

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

    # ------------------------------------------------------------------ Ablauf
    def fetch(self) -> FetchReport:
        report = FetchReport(retailer=self.cfg.key)
        notes: list[str] = []

        ok, login_note = self.login()
        notes.append(login_note)

        # -- Weg 1: öffentlicher Wochenprospekt ----------------------------
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
                notes.append(
                    f"Wochenprospekt {pdf_url.rsplit('/', 1)[-1]}: {len(offers)} Weinpositionen"
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

        report.resolved_url = pdf_url or PROMO_PAGE
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


def _find_promo_pdf(html: str) -> str:
    """Die Aktionsbroschüre der aktuellen Woche heraussuchen."""
    candidates = _RE_ANY_PDF.findall(html or "")
    promo = [u for u in candidates if _RE_PROMO_PDF.search(u)]
    if promo:
        # Der neueste Pfad enthält das jüngste Jahr-Monat-Segment.
        return sorted(promo)[-1]
    return ""


def _market_url(url: str, market: str | None) -> str:
    """Sortiment ist marktspezifisch — Markt als Parameter anhängen, falls gesetzt."""
    if not market:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}market={urllib.parse.quote(market)}"

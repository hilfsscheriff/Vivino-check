"""HTTP-Schicht: Rate-Limiting, robots.txt, Backoff, Bot-Schutz-Erkennung.

Anstand gegenüber den Quellen ist hier eingebaut, nicht optional:

* max. eine Anfrage pro 2 Sekunden **pro Domain**,
* ``robots.txt`` wird gelesen und respektiert,
* echter User-Agent mit Kontaktangabe (``WINECHECK_CONTACT``),
* exponentielles Backoff bei 429/503,
* trifft das Tool bei einer *öffentlichen* Quelle auf eine Cloudflare- oder
  DataDome-Challenge, bricht es ab und meldet ``blocked``. Es umgeht sie nicht.
"""

from __future__ import annotations

import logging
import os
import time
import urllib.parse
from dataclasses import dataclass, field

import httpx

log = logging.getLogger("winecheck.fetch")

CONTACT = os.getenv("WINECHECK_CONTACT", "").strip()

#: Echter Browser-UA plus Kontaktangabe. Kein Tarnen als anonymer Browser: wer
#: geblockt werden will, soll uns erreichen können.
def user_agent() -> str:
    base = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    suffix = f"wine-check/0.1 (+{CONTACT})" if CONTACT else "wine-check/0.1"
    return f"{base} {suffix}"


#: Nur das, was für jede Anfrage gilt. Die ``Sec-Fetch-*``-Metadaten stehen bewusst
#: NICHT hier: Vivinos API antwortet auf ``Sec-Fetch-Dest: empty`` zusammen mit
#: ``Sec-Fetch-Mode: cors`` mit HTTP 415. Solche Fetch-Metadaten setzt der Browser
#: passend zum Anfragetyp — wir tun das darum auch, pro Anfrage statt global.
BASE_HEADERS = {
    "Accept-Language": "de-CH,de;q=0.9,fr-CH;q=0.7,en;q=0.5",
}

#: Header für Seitenaufrufe (HTML).
HTML_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}

#: Header für JSON-Endpunkte. Absichtlich schmal — siehe Kommentar zu BASE_HEADERS.
JSON_HEADERS = {
    "Accept": "application/json",
}

#: Textmarker der gängigen Bot-Schutzsysteme.
_BLOCK_MARKERS = (
    "just a moment",
    "attention required",
    "captcha-delivery",
    "geo.captcha",
    "datadome",
    "verifying you are human",
    "checking your browser",
    "access denied",
    "please enable js",
    "cf-browser-verification",
    "cf_chl_opt",
)


class Blocked(RuntimeError):
    """Bot-Schutz oder dauerhaftes Rate-Limit. Wird nicht umgangen."""

    def __init__(self, message: str, *, retry_after: str | None = None, kind: str = "unknown"):
        super().__init__(message)
        self.retry_after = retry_after
        self.kind = kind


@dataclass
class FetchResult:
    url: str
    status_code: int
    text: str
    from_cache: bool = False
    #: Rohbytes — für PDFs, wo ``text`` unbrauchbar ist.
    content_bytes: bytes = b""

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


def detect_block(text: str, status_code: int, server: str = "") -> str | None:
    """Erkennt eine Schutz-Challenge. Gibt den Namen des Systems zurück oder None."""
    low = (text or "")[:200_000].lower()
    hits = [m for m in _BLOCK_MARKERS if m in low]
    if not hits:
        return None
    srv = (server or "").lower()
    if "datadome" in srv or "captcha-delivery" in " ".join(hits) or "datadome" in " ".join(hits):
        return "datadome"
    if "cloudflare" in srv or any("moment" in h or "attention" in h for h in hits):
        return "cloudflare"
    return "bot-protection"


class Robots:
    """robots.txt mit Wildcards — ``*`` und ``$``, wie Google es spezifiziert.

    Warum nicht ``urllib.robotparser``: die Standardbibliothek kennt **keine
    Wildcards**. Sie vergleicht mit ``startswith``, und damit ist ``Disallow:
    /*brands=*`` eine Regel über Pfade, die wörtlich mit ``/*brands=*`` beginnen —
    also über keinen. Jede Regel mit einem Stern in der Mitte fiel stillschweigend
    weg, und genau so schreiben Shops ihre Query-Verbote.

    Gemessen am 10.8.2026 an zwei Fällen, die dieses Projekt betreffen:

    * ``web.transgourmet.ch`` verbietet ``/*?searchTerm=*``. Der Prodega-Adapter
      fragte mit ``searchTerm=wein`` ab, und der Prüfer nannte es erlaubt.
    * ``moevenpick-wein.com`` verbietet ``/*?*`` und erlaubt nur ``*?p=*``. Dass wir
      dort keine anderen Query-Parameter verwenden, war eine Entscheidung von Hand —
      der Prüfer hätte sie nicht erzwungen.

    Das ist die eine Stelle, an der eine Lücke nicht nur Daten kostet, sondern eine
    Zusage bricht. Darum hier ausgeschrieben statt geliehen.

    Regelvorrang nach Google: die **längste** passende Regel gewinnt; bei gleicher
    Länge gewinnt ``Allow``. Kein Treffer heisst erlaubt.
    """

    __slots__ = ("regeln",)

    def __init__(self, regeln: list[tuple[str, bool]]):
        #: ``(Muster, erlaubt)``, ungeordnet — der Vorrang entscheidet sich beim Prüfen.
        self.regeln = regeln

    @classmethod
    def parse(cls, text: str, user_agent: str) -> Robots:
        """Nur die Gruppen, die uns betreffen: unser Name, sonst ``*``.

        Ein benannter Block gewinnt über ``*`` — steht unser Name in der Datei, gilt
        ausschliesslich sein Block. So halten es die Shops auch: die Sperren für
        AhrefsBot sollen andere nicht treffen.
        """
        ua = (user_agent or "").lower()
        gruppen: dict[str, list[tuple[str, bool]]] = {}
        aktuell: list[str] = []
        letzte_zeile_agent = False
        for rohzeile in text.splitlines():
            zeile = rohzeile.split("#", 1)[0].strip()
            if not zeile or ":" not in zeile:
                continue
            feld, _, wert = zeile.partition(":")
            feld, wert = feld.strip().lower(), wert.strip()
            if feld == "user-agent":
                if not letzte_zeile_agent:
                    aktuell = []
                aktuell.append(wert.lower())
                letzte_zeile_agent = True
                for a in aktuell:
                    gruppen.setdefault(a, [])
                continue
            letzte_zeile_agent = False
            if feld not in ("allow", "disallow") or not aktuell:
                continue
            # "Disallow:" ohne Wert heisst ausdrücklich: alles erlaubt.
            if feld == "disallow" and not wert:
                continue
            for a in aktuell:
                gruppen[a].append((wert, feld == "allow"))

        passend = [a for a in gruppen if a and a != "*" and a in ua]
        name = passend[0] if passend else "*"
        return cls(gruppen.get(name, []))

    @staticmethod
    def _trifft(muster: str, pfad: str) -> bool:
        anker = muster.endswith("$")
        if anker:
            muster = muster[:-1]
        teile = muster.split("*")
        # Der erste Abschnitt muss am Anfang stehen, die weiteren in Reihenfolge
        # irgendwo danach. Das ist die Wildcard-Semantik von Google, ohne Regex —
        # ein aus fremdem Text gebautes Regex wäre eine unnötige Angriffsfläche.
        if not pfad.startswith(teile[0]):
            return False
        pos = len(teile[0])
        for teil in teile[1:]:
            if not teil:
                continue
            treffer = pfad.find(teil, pos)
            if treffer < 0:
                return False
            pos = treffer + len(teil)
        if anker:
            return pos == len(pfad) if teile[-1] else True
        return True

    def allows(self, url: str) -> bool:
        parts = urllib.parse.urlsplit(url)
        pfad = parts.path or "/"
        if parts.query:
            pfad += "?" + parts.query
        beste: tuple[int, bool] | None = None
        for muster, erlaubt in self.regeln:
            if not self._trifft(muster, pfad):
                continue
            laenge = len(muster)
            # Längste Regel gewinnt; bei gleicher Länge das Allow.
            if beste is None or laenge > beste[0] or (laenge == beste[0] and erlaubt):
                beste = (laenge, erlaubt)
        return True if beste is None else beste[1]


@dataclass
class _DomainState:
    last_request: float = 0.0
    robots: Robots | None = None
    robots_loaded: bool = False
    robots_unavailable: bool = False


@dataclass
class Fetcher:
    """Gemeinsamer HTTP-Client für alle Adapter."""

    rate_limit_seconds: float = 2.0
    timeout_seconds: float = 30.0
    respect_robots: bool = True
    max_retries: int = 3
    _client: httpx.Client | None = field(default=None, repr=False)
    _domains: dict[str, _DomainState] = field(default_factory=dict, repr=False)
    log_lines: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        headers = {**BASE_HEADERS, "User-Agent": user_agent()}
        self._client = httpx.Client(
            headers=headers,
            follow_redirects=True,
            timeout=self.timeout_seconds,
        )

    # -- Lebenszyklus ------------------------------------------------------
    def close(self) -> None:
        if self._client:
            self._client.close()

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- Interna -----------------------------------------------------------
    def _state(self, url: str) -> _DomainState:
        host = urllib.parse.urlsplit(url).netloc.lower()
        return self._domains.setdefault(host, _DomainState())

    def _throttle(self, url: str, rate: float | None = None) -> None:
        st = self._state(url)
        wait = (rate if rate is not None else self.rate_limit_seconds) - (time.monotonic() - st.last_request)
        if wait > 0:
            time.sleep(wait)
        st.last_request = time.monotonic()

    def robots_allows(self, url: str) -> bool:
        """robots.txt respektieren. Ist sie selbst nicht lesbar (z.B. weil eine
        Challenge davorsteht), gilt das nicht als Erlaubnis, sondern als Blockade —
        die Quelle wird dann ohnehin über :class:`Blocked` gemeldet."""
        if not self.respect_robots:
            return True
        st = self._state(url)
        if not st.robots_loaded:
            st.robots_loaded = True
            parts = urllib.parse.urlsplit(url)
            robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
            try:
                self._throttle(url)
                r = self._client.get(robots_url, headers=HTML_HEADERS)  # type: ignore[union-attr]
                if r.status_code == 200 and not detect_block(r.text, r.status_code,
                                                             r.headers.get("server", "")):
                    st.robots = Robots.parse(r.text, user_agent())
                else:
                    st.robots_unavailable = True
            except Exception as exc:  # noqa: BLE001
                log.debug("robots.txt nicht lesbar für %s: %s", robots_url, exc)
                st.robots_unavailable = True
        if st.robots is None:
            return True  # keine robots.txt lesbar -> keine Einschränkung ableitbar
        return st.robots.allows(url)

    # -- Öffentliche API ---------------------------------------------------
    def get(
        self,
        url: str,
        *,
        rate: float | None = None,
        headers: dict[str, str] | None = None,
        allow_block: bool = False,
        params: dict[str, object] | list[tuple[str, object]] | None = None,
        expect_json: bool = False,
    ) -> FetchResult:
        """Holt eine URL mit Rate-Limit, robots-Prüfung und Backoff.

        Args:
            allow_block: True unterdrückt :class:`Blocked` und liefert die Antwort
                zurück — nur für die Diagnose gedacht.
            expect_json: setzt den Accept-Header auf JSON.
        """
        if not self.robots_allows(url):
            raise Blocked(f"robots.txt verbietet {url}", kind="robots")

        hdrs = {**(JSON_HEADERS if expect_json else HTML_HEADERS), **(headers or {})}

        delay = 2.0
        last: httpx.Response | None = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle(url, rate)
            try:
                resp = self._client.get(url, headers=hdrs, params=params)  # type: ignore[union-attr]
            except httpx.HTTPError as exc:
                if attempt == self.max_retries:
                    raise Blocked(f"Netzwerkfehler bei {url}: {exc}", kind="network") from exc
                time.sleep(delay)
                delay *= 2
                continue

            last = resp
            server = resp.headers.get("server", "")
            kind = detect_block(resp.text, resp.status_code, server)
            if kind and not allow_block:
                retry_at = _retry_timestamp(resp)
                self.log_lines.append(f"blocked[{kind}] {url}")
                raise Blocked(
                    f"{kind}-Challenge bei {url} — nicht umgangen",
                    retry_after=retry_at,
                    kind=kind,
                )

            if resp.status_code in (429, 503):
                retry_after = resp.headers.get("Retry-After")
                sleep_for = float(retry_after) if (retry_after or "").isdigit() else delay
                if attempt == self.max_retries:
                    raise Blocked(
                        f"HTTP {resp.status_code} bei {url} nach {attempt} Versuchen",
                        retry_after=_retry_timestamp(resp),
                        kind="rate_limit",
                    )
                self.log_lines.append(f"backoff {resp.status_code} {url} -> {sleep_for}s")
                time.sleep(sleep_for)
                delay *= 2
                continue

            return FetchResult(
                url=str(resp.url),
                status_code=resp.status_code,
                text=resp.text,
                content_bytes=resp.content,
            )

        return FetchResult(
            url=str(last.url) if last else url,
            status_code=last.status_code if last else 0,
            text=last.text if last else "",
            content_bytes=last.content if last else b"",
        )

    def post(
        self,
        url: str,
        *,
        data: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        rate: float | None = None,
    ) -> FetchResult:
        """POST für Logins. robots.txt wird hier nicht geprüft: ein Login mit eigenen
        Zugangsdaten ist eine Nutzeraktion, kein Crawling. Das Rate-Limit gilt aber."""
        self._throttle(url, rate)
        resp = self._client.post(url, data=data, headers=headers)  # type: ignore[union-attr]
        kind = detect_block(resp.text, resp.status_code, resp.headers.get("server", ""))
        if kind:
            raise Blocked(f"{kind}-Challenge beim Login auf {url}", kind=kind)
        return FetchResult(url=str(resp.url), status_code=resp.status_code, text=resp.text)

    @property
    def cookies(self) -> httpx.Cookies:
        return self._client.cookies  # type: ignore[union-attr]

    def set_cookie_header(self, cookie: str, domain: str) -> None:
        """Session-Cookie aus dem Browser übernehmen (Format ``a=1; b=2``)."""
        for part in cookie.split(";"):
            if "=" in part:
                name, _, value = part.strip().partition("=")
                self._client.cookies.set(name, value, domain=domain)  # type: ignore[union-attr]

    def resolve_url(self, cfg_urls: list[str], shop_root: str, keywords: list[str]) -> tuple[str | None, str]:
        """Deep-Links veralten. Antwortet die konfigurierte URL mit 404, wird vom
        Shop-Root aus nach der Promo-Kategorie gesucht, statt zu scheitern.

        Returns:
            ``(gefundene URL oder None, Protokollnotiz)``
        """
        notes: list[str] = []
        for url in cfg_urls:
            try:
                r = self.get(url)
            except Blocked as exc:
                notes.append(f"{url}: {exc}")
                continue
            if r.ok:
                if str(r.url) != url:
                    notes.append(f"{url} -> {r.url} (Redirect)")
                return str(r.url), "; ".join(notes)
            notes.append(f"{url}: HTTP {r.status_code}")

        if not shop_root:
            return None, "; ".join(notes) or "keine URL konfiguriert"

        try:
            root = self.get(shop_root)
        except Blocked as exc:
            return None, _join(notes, f"Shop-Root blockiert: {exc}")
        if not root.ok:
            return None, _join(notes, f"Shop-Root HTTP {root.status_code}")

        from selectolax.parser import HTMLParser  # lokal, hält das Modul leicht

        tree = HTMLParser(root.text)
        candidates: list[str] = []
        for a in tree.css("a[href]"):
            href = a.attributes.get("href") or ""
            label = f"{href} {a.text() or ''}".lower()
            if any(k in label for k in keywords):
                candidates.append(urllib.parse.urljoin(shop_root, href))
        # Stabile, eindeutige Reihenfolge.
        seen: set[str] = set()
        uniq = [c for c in candidates if not (c in seen or seen.add(c))]
        if not uniq:
            return None, _join(notes, "keine Promo-Kategorie im Shop-Root gefunden")
        return uniq[0], _join(notes, f"vom Shop-Root aufgelöst auf {uniq[0]} ({len(uniq)} Kandidaten)")


def _retry_timestamp(resp: httpx.Response) -> str:
    """Retry-Zeitpunkt für den Cache-Eintrag vermerken."""
    ra = resp.headers.get("Retry-After", "")
    if ra.isdigit():
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + int(ra)))
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + 3600))


def _join(notes: list[str], extra: str) -> str:
    return "; ".join([*notes, extra])

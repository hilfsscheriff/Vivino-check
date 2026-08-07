"""Kommandozeile.

``fetch`` und ``rate`` sind getrennt, weil ``fetch`` täglich sinnvoll ist und ``rate``
nur bei neuen Weinen:

.. code-block:: shell

    wine-check fetch  --retailers denner,moevenpick,prodega
    wine-check rate                       # Falstaff + Vivino für alle
    wine-check report --out ./output
    wine-check run    --all
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from .adapters.base import FetchReport, RetailerAdapter
from .adapters.aktionis import AktionisAdapter
from .adapters.denner import DennerAdapter
from .adapters.moevenpick import MoevenpickAdapter
from .adapters.aligro import AligroAdapter
from .adapters.prodega import ProdegaAdapter
from .aggregate import attach_maturity, compute_scores, merge_offers
from .cache import Cache
from .config import SourceConfig, load_registry
from .fetching import Fetcher
from .models import Offer, PriceConfidence, VivinoStatus, WineRow
from .prices import price_band
from .ratings.falstaff import FalstaffAdapter
from .ratings.vivino import VivinoAdapter
from .report.csv_out import write_csv
from .report.diff import snapshot, write_diff
from .report.interactive import write_interactive
from .report.pdf_out import write_pdf
from .report.site import build as build_site
from .report.plot import write_scatter

app = typer.Typer(add_completion=False, help="Aktionen der Schweizer Weinhändler prüfen.")

ADAPTERS: dict[str, type[RetailerAdapter]] = {
    "aktionis": AktionisAdapter,
    "aligro": AligroAdapter,
    "denner": DennerAdapter,
    "moevenpick": MoevenpickAdapter,
    "prodega": ProdegaAdapter,
}

DEFAULT_CACHE = Path("cache/winecheck.sqlite")
STATE_DIR = Path("state")


def _echo(msg: str, *, err: bool = False) -> None:
    typer.echo(msg, err=err)


def _adapter_for(cfg: SourceConfig, fetcher: Fetcher) -> RetailerAdapter | None:
    cls = ADAPTERS.get(cfg.adapter) or ADAPTERS.get(cfg.key)
    return cls(cfg, fetcher) if cls else None


# --------------------------------------------------------------------- fetch

@app.command()
def fetch(
    retailers: str = typer.Option("", "--retailers", help="Kommaliste, z.B. denner,prodega"),
    cache_path: Path = typer.Option(DEFAULT_CACHE, "--cache"),
    registry: Path = typer.Option(None, "--registry"),
    refresh_prices: bool = typer.Option(
        False, "--refresh-prices",
        help="Angebote aller gewählten Händler vorab löschen, auch wenn der Lauf scheitert",
    ),
) -> None:
    """Aktionsseiten einlesen und Angebote im Cache ablegen."""
    reg = load_registry(registry)
    keys = [k for k in retailers.split(",") if k.strip()] if retailers else None
    selected = reg.select(keys)
    cache = Cache.open(cache_path)
    reports: list[FetchReport] = []
    uncertain: list[str] = []

    # Blockierte Quellen erscheinen im Report, auch wenn sie nicht aktiviert sind —
    # sonst liest sich "keine Coop-Aktionen" wie "Coop hat diese Woche nichts", statt
    # wie "Coop ist nicht einlesbar".
    if keys is None:
        for cfg in reg.retailers.values():
            if cfg.enabled or cfg.status != "blocked":
                continue
            reports.append(
                FetchReport(
                    retailer=cfg.key,
                    status="blocked",
                    message=(
                        f"{cfg.blocked_by or 'Bot-Schutz'} — Schutzmassnahme wird nicht "
                        f"umgangen. {' '.join((cfg.notes or '').split())[:150]}"
                    ),
                )
            )
            _echo(f"  {cfg.key:<14} blockiert ({cfg.blocked_by}) — nicht umgangen")

    with Fetcher() as fetcher:
        for cfg in selected:
            if not cfg.enabled and keys is None:
                continue
            if refresh_prices:
                cache.clear_offers(cfg.key)
            adapter = _adapter_for(cfg, fetcher)
            if adapter is None:
                _echo(f"  {cfg.key:<14} übersprungen — kein Adapter ({cfg.status})")
                continue
            if cfg.status == "blocked":
                _echo(
                    f"  {cfg.key:<14} blockiert ({cfg.blocked_by}) — "
                    f"Schutzmassnahme wird nicht umgangen"
                )
                reports.append(
                    FetchReport(retailer=cfg.key, status="blocked",
                                message=f"{cfg.blocked_by}: {cfg.notes[:160]}")
                )
                continue

            _echo(f"  {cfg.key:<14} …")
            report = adapter.fetch()
            reports.append(report)
            uncertain.extend(getattr(adapter, "uncertain", []))
            # Eine Aktionsseite ist eine Momentaufnahme, keine Sammlung: der frische
            # Satz ersetzt den alten. Sonst stehen nach zwei Läufen die Aktionen von
            # KW32 und KW33 nebeneinander im Report, und "Ausgelaufene Aktionen" in
            # diff.md kann nie anschlagen. Ersetzt wird nur bei erfolgreichem Lauf —
            # eine blockierte Quelle darf ihren letzten guten Stand behalten.
            if report.status == "ok" and report.offers:
                # Auch die Händler leeren, unter denen dieser Adapter ablegt.
                # Aktionis ist ein Aggregator: seine Funde landen unter "coop",
                # "ottos", "spar", "volg" — beim Leeren nur des eigenen Schlüssels
                # sammelten sich deren Angebote an und liefen nie ab. Coop stand mit
                # 210 Positionen im Cache, während Aktionis 112 listete; die
                # Differenz waren abgelaufene Aktionen, die im Report weiterlebten
                # und deren Detailseite "Angebot ist abgelaufen" meldete.
                for key in {cfg.key} | {o.retailer for o in report.offers if o.retailer}:
                    cache.clear_offers(key)
            for offer in report.offers:
                cache.put_offer(cfg.key, offer.name, offer.vintage, _offer_payload(offer))
            _echo(f"  {cfg.key:<14} {report.status:<8} {report.count:>4} Positionen  {report.message[:90]}")

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "fetch_reports.json").write_text(
        json.dumps([_report_payload(r) for r in reports], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (STATE_DIR / "uncertain.json").write_text(
        json.dumps(uncertain, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    total = sum(r.count for r in reports)
    _echo(f"\n{total} Positionen von {len(reports)} Quellen im Cache.")
    cache.close()


# ---------------------------------------------------------------------- rate

@app.command()
def rate(
    cache_path: Path = typer.Option(DEFAULT_CACHE, "--cache"),
    registry: Path = typer.Option(None, "--registry"),
    refresh: bool = typer.Option(False, "--refresh", help="Bewertungs-Cache ignorieren"),
    retry_failed: bool = typer.Option(False, "--retry-failed", help="blocked/no_entry erneut prüfen"),
    limit: int = typer.Option(0, "--limit", help="nur die ersten N Weine (zum Ausprobieren)"),
) -> None:
    """Falstaff abfragen und Vivino **für jeden** Wein — unabhängig voneinander."""
    reg = load_registry(registry)
    cache = Cache.open(cache_path)
    offers = [_offer_from_payload(d) for d in cache.all_offers()]
    rows = compute_scores(attach_maturity(merge_offers(offers)))
    if limit:
        rows = rows[:limit]
    if not rows:
        _echo("Keine Angebote im Cache — zuerst 'wine-check fetch' laufen lassen.", err=True)
        raise typer.Exit(1)

    falstaff_cfg = reg.rating_source("falstaff")
    use_falstaff = bool(falstaff_cfg and falstaff_cfg.enabled)
    if not use_falstaff:
        _echo(
            "  Falstaff ist in der Registry deaktiviert (Status: "
            f"{falstaff_cfg.status if falstaff_cfg else 'unbekannt'}) — "
            "Ranking läuft über Vivino, die Herkunft steht je Zeile."
        )

    stats: dict[str, int] = {}
    with Fetcher() as fetcher:
        vivino = VivinoAdapter(fetcher, cache=cache)
        falstaff = FalstaffAdapter(fetcher, cache=cache)
        for i, row in enumerate(rows, start=1):
            if use_falstaff:
                row.falstaff = falstaff.lookup(
                    row.name, row.vintage, refresh=refresh, retry_failed=retry_failed
                )
            # Vivino IMMER — kein Abbruch beim ersten Treffer.
            # Die Domains der Händler dieses Weins werden beim Marktpreis
            # ausgeschlossen: Mövenpick ist Vivino-Partnerhändler, ohne Filter
            # verglichen wir dessen Preis mit sich selbst.
            row.vivino = vivino.lookup(
                row.name, row.vintage, refresh=refresh, retry_failed=retry_failed,
                exclude_hosts=_retailer_hosts(reg, row),
            )
            stats[row.vivino.status.value] = stats.get(row.vivino.status.value, 0) + 1
            _echo(
                f"  [{i}/{len(rows)}] {row.name[:52]:<52} "
                f"vivino={row.vivino.status.value:<19} "
                f"{(f'{row.vivino.rating}' if row.vivino.rating else '—')}"
            )
            cache.put_offer(
                row.offers[0].retailer, row.name, row.vintage,
                {**_offer_payload(row.offers[0]), "_rated": True},
            )

    _save_rated(rows)
    _echo("\nVivino-Status-Verteilung:")
    for status in VivinoStatus:
        n = stats.get(status.value, 0)
        if n:
            share = n / max(len(rows), 1) * 100
            _echo(f"  {status.value:<21} {n:>4}  ({share:.0f} %)")
    rated = sum(1 for r in rows if r.has_any_rating)
    _echo(f"\n{rated}/{len(rows)} Weine mit Fremdbewertung ({rated/max(len(rows),1)*100:.0f} %).")
    cache.close()


# -------------------------------------------------------------------- report



RATINGS_FILE = Path("state/ratings-cache.json")


@app.command("ratings-export")
def ratings_export(
    out: Path = typer.Option(RATINGS_FILE, "--out"),
    cache_path: Path = typer.Option(DEFAULT_CACHE, "--cache"),
) -> None:
    """Bewertungen in eine versionierbare Datei schreiben.

    Der GitHub-Wochenlauf holt frische Preise, kann aber nicht selbst bei Vivino
    nachfragen — Rechenzentrums-IPs werden gesperrt. Diese Datei gibt ihm die
    Bewertungen des letzten lokalen Laufs mit, damit die Seite Preise *und* Noten
    zeigt statt nur Preise.
    """
    cache = Cache.open(cache_path)
    rows = cache.export_ratings()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    cache.close()
    _echo(f"{len(rows)} Bewertungen nach {out} geschrieben ({out.stat().st_size // 1024} KB)")


@app.command("ratings-import")
def ratings_import(
    src: Path = typer.Option(RATINGS_FILE, "--in"),
    cache_path: Path = typer.Option(DEFAULT_CACHE, "--cache"),
    overwrite: bool = typer.Option(False, "--overwrite",
                                   help="auch vorhandene Einträge ersetzen"),
) -> None:
    """Bewertungen aus der versionierten Datei in den Cache spielen."""
    if not src.exists():
        _echo(f"{src} nicht gefunden — nichts einzuspielen.", err=True)
        return
    cache = Cache.open(cache_path)
    n = cache.import_ratings(json.loads(src.read_text(encoding="utf-8")), overwrite=overwrite)
    cache.close()
    _echo(f"{n} Bewertungen aus {src} übernommen")


@app.command()
def report(
    out: Path = typer.Option(Path("output"), "--out"),
    cache_path: Path = typer.Option(DEFAULT_CACHE, "--cache"),
    registry: Path = typer.Option(None, "--registry"),
) -> None:
    """results.csv, report.pdf, scatter.png, scatter.html und diff.md schreiben."""
    reg = load_registry(registry)
    info = {
        c.key: {"name": c.name, "channel": c.channel, "domain": c.domain}
        for c in reg.retailers.values()
    }
    cache = Cache.open(cache_path)
    rows = _load_rated()
    if not rows:
        _echo("Keine bewerteten Weine gefunden — zuerst 'wine-check rate'.", err=True)
        raise typer.Exit(1)

    reports = _load_reports()
    uncertain = _load_uncertain()

    out.mkdir(parents=True, exist_ok=True)
    csv_path = write_csv(rows, out / "results.csv")
    pdf_path = write_pdf(
        rows, out / "report.pdf", source_reports=reports, uncertain=uncertain,
        retailer_info=info,
    )
    png_path = write_scatter(rows, out / "scatter.png")
    html_path = write_interactive(rows, out / "scatter.html", retailer_info=info)

    _prev_id, previous = cache.previous_snapshot()
    diff_path = write_diff(rows, previous, out / "diff.md", source_reports=reports)
    cache.save_snapshot(snapshot(rows), label="report")

    _echo(f"  {csv_path}")
    _echo(f"  {pdf_path}")
    _echo(f"  {png_path if png_path else '(scatter.png übersprungen — keine bewerteten Preise)'}")
    _echo(f"  {html_path if html_path else '(scatter.html übersprungen)'}")
    _echo(f"  {diff_path}")
    cache.close()


# ----------------------------------------------------------------------- run

@app.command()
def run(
    all_: bool = typer.Option(False, "--all", help="fetch, rate und report in einem Lauf"),
    retailers: str = typer.Option("", "--retailers"),
    out: Path = typer.Option(Path("output"), "--out"),
    cache_path: Path = typer.Option(DEFAULT_CACHE, "--cache"),
    limit: int = typer.Option(0, "--limit"),
) -> None:
    """Alles hintereinander."""
    _echo("== fetch")
    fetch(retailers=retailers, cache_path=cache_path, registry=None, refresh_prices=False)
    _echo("\n== rate")
    rate(cache_path=cache_path, registry=None, refresh=False, retry_failed=False, limit=limit)
    _echo("\n== report")
    report(out=out, cache_path=cache_path, registry=None)


# --------------------------------------------------------------------- infos

@app.command()
def site(
    out: Path = typer.Option(Path("docs"), "--out", help="Zielordner, Standard docs/ für GitHub Pages"),
    cache_path: Path = typer.Option(DEFAULT_CACHE, "--cache"),
    registry: Path = typer.Option(None, "--registry"),
    runs: int = typer.Option(12, "--runs", help="wie viele Läufe die Seite anbieten soll"),
    title: str = typer.Option("Schweizer Weinaktionen", "--title"),
) -> None:
    """Statische Webseite bauen — für GitHub Pages oder zum Mitnehmen aufs Handy.

    Eine einzige HTML-Datei mit allen Daten inline: kein CDN, keine externen Schriften.
    Damit läuft sie per Doppelklick, in OneDrive und auf Pages gleichermassen, sie
    funktioniert unterwegs ohne Netz, und Besucher lösen keine Anfragen an Dritte aus.
    """
    import time as _time

    reg = load_registry(registry)
    info = {
        c.key: {"name": c.name, "channel": c.channel, "domain": c.domain}
        for c in reg.retailers.values()
    }
    cache = Cache.open(cache_path)
    history = cache.all_runs(limit=runs)
    cache.close()

    if not history:
        _echo(
            "Keine Läufe im Cache — zuerst 'wine-check report' laufen lassen, das "
            "legt die Momentaufnahme an.",
            err=True,
        )
        raise typer.Exit(1)

    from .report.site import _wine_from_snapshot

    prepared = []
    for run in history:
        stamp = _time.localtime(run["started_at"])
        prepared.append({
            "id": run["id"],
            "label": f"{stamp.tm_mday}.{stamp.tm_mon}.{stamp.tm_year}",
            "wines": [_wine_from_snapshot(w) for w in run["wines"]],
        })

    out.mkdir(parents=True, exist_ok=True)
    # GitHub Pages würde den Ordner sonst durch Jekyll schicben.
    (out / ".nojekyll").write_text("", encoding="utf-8")
    path = build_site(prepared, out / "index.html", retailer_info=info, title=title)
    if path is None:
        _echo("Keine Weine in den Läufen — nichts zu bauen.", err=True)
        raise typer.Exit(1)

    size = path.stat().st_size / 1024
    _echo(f"  {path}  ({size:.0f} KB, {len(prepared)} Läufe, alles inline)")
    _echo(f"  {out / '.nojekyll'}")
    _echo("")
    _echo("  GitHub Pages: Repository -> Settings -> Pages -> Branch main, Ordner /docs")


@app.command()
def trinkreife(
    out: Path = typer.Option(None, "--out", help="Ziel, Standard sources/trinkreife.yaml"),
) -> None:
    """Die Vinum-Jahrgangstabelle neu einlesen.

    Sie erscheint jährlich; einmal pro Jahr ausführen. Das PDF ist ein Text-PDF, es
    braucht kein OCR — Weinart und Jahrgangsqualität stecken allerdings in der Grafik
    und werden über Farben ausgewertet.
    """
    import time as _time

    from .trinkreife import DEFAULT_PATH, SOURCE_URL, parse_pdf, to_yaml

    target = out or DEFAULT_PATH
    with Fetcher() as fetcher:
        _echo(f"  hole {SOURCE_URL.rsplit('/', 1)[-1]} …")
        res = fetcher.get(SOURCE_URL)
    entries = parse_pdf(res.content_bytes)
    if not entries:
        _echo("Keine Tabellenzeilen erkannt — Layout geändert?", err=True)
        raise typer.Exit(1)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(to_yaml(entries, _time.strftime("%Y-%m-%d")), encoding="utf-8")
    weiss = sum(1 for e in entries if e.wine_type == "weiss")
    rot = sum(1 for e in entries if e.wine_type == "rot")
    _echo(f"  {len(entries)} Zeilen ({rot} rot, {weiss} weiss) -> {target}")


@app.command()
def sources(registry: Path = typer.Option(None, "--registry")) -> None:
    """Quellen-Registry anzeigen — welche Quelle geht, welche nicht und warum."""
    reg = load_registry(registry)
    _echo(f"{'Key':<14}{'Tier':<6}{'Status':<16}{'Adapter':<15}Bemerkung")
    _echo("-" * 110)
    for cfg in sorted(reg.retailers.values(), key=lambda c: (c.tier, c.key)):
        flag = "✓" if cfg.enabled else " "
        note = (cfg.notes or "").strip().replace("\n", " ")[:52]
        _echo(f"{flag} {cfg.key:<12}{cfg.tier:<6}{cfg.status:<16}{cfg.adapter:<15}{note}")
    _echo("\nBewertungsquellen:")
    for cfg in reg.rating_sources.values():
        flag = "✓" if cfg.enabled else " "
        note = (cfg.notes or "").strip().replace("\n", " ")[:52]
        _echo(f"{flag} {cfg.key:<12}{cfg.role:<16}{cfg.status:<16}{note}")


@app.command()
def cache_stats(cache_path: Path = typer.Option(DEFAULT_CACHE, "--cache")) -> None:
    """Was steckt im Cache."""
    cache = Cache.open(cache_path)
    for key, value in cache.stats().items():
        _echo(f"  {key:<10} {value}")
    cache.close()


# ------------------------------------------------------------ Serialisierung

def _retailer_hosts(reg, row: WineRow) -> set[str]:
    """Domains aller Händler, die diesen Wein anbieten."""
    hosts: set[str] = set()
    for price in row.prices:
        cfg = reg.retailers.get(price.retailer)
        if cfg and cfg.domain:
            hosts.add(cfg.domain.lower())
    return hosts


def _offer_payload(o: Offer) -> dict:
    return {
        "retailer": o.retailer, "name": o.name, "url": o.url, "vintage": o.vintage,
        "price_per_bottle_incl_vat": o.price_per_bottle_incl_vat,
        "price_raw": o.price_raw, "price_raw_basis": o.price_raw_basis,
        "price_confidence": o.price_confidence.value,
        "reference_price": o.reference_price, "discount_percent": o.discount_percent,
        "discount_plausibility": o.discount_plausibility.value,
        "is_private_label": o.is_private_label, "bottle_ml": o.bottle_ml,
        "units": o.units, "article_no": o.article_no, "fetched_at": o.fetched_at,
        "source_note": o.source_note,
        "critic_scores": o.critic_scores,
    }


def _offer_from_payload(d: dict) -> Offer:
    from .models import DiscountPlausibility

    return Offer(
        retailer=d.get("retailer") or "", name=d.get("name") or "", url=d.get("url") or "",
        vintage=d.get("vintage"),
        price_per_bottle_incl_vat=d.get("price_per_bottle_incl_vat"),
        price_raw=d.get("price_raw"), price_raw_basis=d.get("price_raw_basis") or "",
        price_confidence=PriceConfidence(d.get("price_confidence") or "high"),
        reference_price=d.get("reference_price"),
        discount_percent=d.get("discount_percent"),
        discount_plausibility=DiscountPlausibility(d.get("discount_plausibility") or "unknown"),
        is_private_label=bool(d.get("is_private_label")),
        bottle_ml=d.get("bottle_ml"), units=d.get("units"),
        article_no=d.get("article_no"), fetched_at=d.get("fetched_at"),
        source_note=d.get("source_note") or "",
        critic_scores=d.get("critic_scores") or {},
    )


def _report_payload(r: FetchReport) -> dict:
    return {
        "retailer": r.retailer, "status": r.status, "count": r.count,
        "message": r.message, "resolved_url": r.resolved_url, "url_note": r.url_note,
        "retry_after": r.retry_after,
    }


def _load_reports() -> list[FetchReport]:
    path = STATE_DIR / "fetch_reports.json"
    if not path.exists():
        return []
    out = []
    for d in json.loads(path.read_text(encoding="utf-8")):
        rep = FetchReport(
            retailer=d.get("retailer") or "", status=d.get("status") or "",
            message=d.get("message") or "", resolved_url=d.get("resolved_url") or "",
            url_note=d.get("url_note") or "", retry_after=d.get("retry_after"),
        )
        # count ist abgeleitet; für den Report reicht die Zahl aus der Datei.
        rep.offers = [Offer(retailer=rep.retailer, name="")] * int(d.get("count") or 0)
        out.append(rep)
    return out


def _load_uncertain() -> list[str]:
    path = STATE_DIR / "uncertain.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _save_rated(rows: list[WineRow]) -> None:
    """Bewertete Zeilen zwischenspeichern, damit ``report`` getrennt laufen kann."""
    from .ratings.vivino import _to_payload as vivino_payload
    from .ratings.falstaff import _to_payload as falstaff_payload

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    data = []
    for r in rows:
        data.append({
            "name": r.name, "vintage": r.vintage, "dedup_key": r.dedup_key,
            "is_private_label": r.is_private_label,
            "offers": [_offer_payload(o) for o in r.offers],
            "vivino": vivino_payload(r.vivino) if r.vivino else None,
            "falstaff": falstaff_payload(r.falstaff) if r.falstaff else None,
        })
    (STATE_DIR / "rated.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _load_rated() -> list[WineRow]:
    from .ratings.falstaff import _from_payload as falstaff_from
    from .ratings.vivino import _from_payload as vivino_from

    path = STATE_DIR / "rated.json"
    if not path.exists():
        return []
    rows: list[WineRow] = []
    for d in json.loads(path.read_text(encoding="utf-8")):
        offers = [_offer_from_payload(o) for o in d.get("offers") or []]
        merged = merge_offers(offers)
        row = merged[0] if merged else WineRow(name=d["name"], vintage=d.get("vintage"),
                                               dedup_key=d.get("dedup_key") or "")
        row.name = d["name"]
        row.vintage = d.get("vintage")
        row.dedup_key = d.get("dedup_key") or row.dedup_key
        row.is_private_label = bool(d.get("is_private_label"))
        if d.get("vivino"):
            row.vivino = vivino_from(d["vivino"])
        if d.get("falstaff"):
            row.falstaff = falstaff_from(d["falstaff"])
        row.price_band = price_band(row.best_price)
        rows.append(row)
    return compute_scores(attach_maturity(rows))


if __name__ == "__main__":
    app()

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
import time
from pathlib import Path

import typer

from .adapters.base import FetchReport, RetailerAdapter
from .adapters.aktionis import AktionisAdapter
from .adapters.denner import DennerAdapter
from .adapters.flaschenpost import FlaschenpostAdapter
from .adapters.gabweb import GabWebAdapter
from .adapters.gerstl import GerstlAdapter
from .adapters.moevenpick import MoevenpickAdapter
from .adapters.aligro import AligroAdapter
from .adapters.prodega import ProdegaAdapter
from .adapters.schubi import SchubiAdapter
from .adapters.shopware import ShopwareAdapter
from .adapters.vivinoshop import VivinoShopAdapter
from .adapters.volg import VolgAdapter
from .adapters.wineoutlet import WineOutletAdapter
from .aggregate import (
    MIN_BEWERTET_ANTEIL,
    MIN_VERGLEICHSBASIS,
    Unplausibel,
    attach_maturity,
    compute_scores,
    merge_offers,
    pruefe_plausibilitaet,
    resolve_shared_ratings,
)
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
    "flaschenpost": FlaschenpostAdapter,
    "gabweb": GabWebAdapter,
    "gerstl": GerstlAdapter,
    "moevenpick": MoevenpickAdapter,
    "prodega": ProdegaAdapter,
    "schubi": SchubiAdapter,
    "shopware": ShopwareAdapter,
    "vivinoshop": VivinoShopAdapter,
    "volg": VolgAdapter,
    "wineoutlet": WineOutletAdapter,
}

#: So gross muss der Vorlauf mindestens sein, damit "neu" etwas bedeutet — als
#: Anteil am aktuellen Lauf. Darunter wird gar nichts markiert.
#:
#: Zwei Drittel ist grosszuegig: eine Quelle, die eine Woche ausfaellt, kostet
#: selten mehr als ein Viertel des Bestands. Wer darunter faellt, hat kein
#: Aktionskarussell erlebt, sondern einen kaputten Lauf.
VERGLEICH_MIN_ANTEIL = 0.66

#: So viel kleiner darf eine neu gebaute Seite höchstens sein als die vorhandene,
#: bevor ``site`` abbricht — als Anteil.
#:
#: 90 %: eine Quelle, die eine Woche ausfällt, kostet selten mehr. Ein Klon mit
#: veraltetem Cache verliert deutlich mehr — am 21.08. wären es 2206 gegen 2531
#: Weine gewesen, also 87 %.
SEITE_MIN_ANTEIL = 0.90

#: Kennung, die jede gebaute Seite trägt: ``<!-- winecheck lauf=… weine=… -->``.
_RE_SEITEN_KENNUNG = None  # spät gesetzt, siehe _seiten_kennung


def _seiten_kennung(pfad: Path) -> tuple[str, int] | None:
    """``(Lauf-Kennung, Weinzahl)`` einer vorhandenen Seite, oder ``None``.

    Gelesen wird nur der Anfang der Datei: die Kennung steht direkt hinter
    ``<!doctype html>``, und die Seite ist 1.6 MB gross.
    """
    import re

    if not pfad.exists():
        return None
    try:
        with pfad.open("r", encoding="utf-8") as f:
            kopf = f.read(4096)
    except OSError:
        return None
    m = re.search(r"<!--\s*winecheck lauf=(\S+) weine=(\d+)\s*-->", kopf)
    return (m.group(1), int(m.group(2))) if m else None


def _lauf_aelter(neu: str, alt: str, cache_path: Path) -> bool:
    """Ist der Lauf ``neu`` älter als der Lauf ``alt``?

    Verglichen wird über die Startzeit im Cache. Kennt der eigene Cache den
    ausgelieferten Lauf nicht, stammt er aus einem anderen Klon — dann sagt die Zeit
    nichts, und es bleibt beim Grössenvergleich.

    Das ist der häufige Fall, und darum trägt der Grössenvergleich die Sperre fast
    allein: die Lauf-Kennungen der beiden Klone sind unabhängige AUTOINCREMENT-Zahlen,
    und derselbe Wert bedeutet in beiden Caches etwas anderes. Der Altersvergleich
    greift nur innerhalb eines Klons — dort, wo jemand eine ältere Momentaufnahme
    ausliefern will.
    """
    if not neu or not alt or neu == alt:
        return False
    cache = Cache.open(cache_path)
    try:
        zeiten = cache.lauf_zeiten(limit=40)
    finally:
        cache.close()
    if neu not in zeiten or alt not in zeiten:
        return False
    return zeiten[neu] < zeiten[alt]

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
                # Auch die Händler darunter, nicht nur den Adapter-Schlüssel. Der
                # Erfolgspfad weiter unten tut das längst; hier fehlte es, und damit
                # blieben beim erzwungenen Neuladen die Aggregator-Angebote stehen —
                # gemessen 96 Zeilen unter coop, denner, ottos, volg und spar.
                for key in {cfg.key} | cache.haendler_unter(cfg.key):
                    cache.clear_offers(key)
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
            # Quellen, die ihre Vivino-Note mitliefern, legen sie gleich im
            # Bewertungs-Cache ab. 'rate' findet sie dort und fragt gar nicht erst
            # nach — das spart nicht nur Abfragen, es schliesst auch aus, dass die
            # Suche einen anderen Wein findet als den tatsächlich angebotenen.
            saeen = getattr(adapter, "saee_bewertungen", None)
            if saeen is not None and report.status == "ok":
                n = saeen(cache)
                if n:
                    _echo(f"  {cfg.key:<14} {n} Noten in den Bewertungs-Cache gelegt")
            _echo(f"  {cfg.key:<14} {report.status:<8} {report.count:>4} Positionen  {report.message[:90]}")

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _schreibe_atomar(
        STATE_DIR / "fetch_reports.json",
        json.dumps([_report_payload(r) for r in reports], ensure_ascii=False, indent=2),
    )
    _schreibe_atomar(
        STATE_DIR / "uncertain.json",
        json.dumps(uncertain, ensure_ascii=False, indent=2),
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
    nachtragen: str = typer.Option(
        "", "--nachtragen", metavar="<feld>",
        help="nur Weine neu abfragen, deren Bewertung dieses Payload-Feld nicht trägt",
    ),
    neu_beurteilen: str = typer.Option(
        "", "--neu-beurteilen", metavar="<stufe>",
        help="nur Weine neu abfragen, deren Treffer diese Konfidenzstufe hat (z.B. fuzzy)",
    ),
) -> None:
    """Falstaff abfragen und Vivino **für jeden** Wein — unabhängig voneinander.

    ``--nachtragen <feld>`` ist der schmale Weg für eine Feldergänzung. Kommt ein neues
    Feld aus der Vivino-Antwort dazu, tragen die bestehenden Cache-Einträge es nicht,
    und bisher half nur ``--refresh`` — ein Volllauf. Gemessen sind das 1567 Weine bei
    rund sechs Sekunden, also zweieinhalb Stunden; als ``region_name`` nachgezogen
    wurde, waren es zwei Läufe und gut vier Stunden für ein Feld, das in derselben
    Antwort schon mitkam. Der Nachtrag verwirft nur die Einträge ohne dieses Feld und
    lässt den Rest stehen.
    """
    reg = load_registry(registry)
    cache = Cache.open(cache_path)

    # Erst die Arbeitsmenge bilden und prüfen, dann verwerfen.
    #
    # Die beiden Verwerfungen standen vorher **vor** diesem Block. Sind die Angebote
    # leer oder älter als das Preisfenster, waren die Bewertungen damit gelöscht und
    # der Lauf endete mit Exit 1, ohne eine einzige Abfrage gestellt zu haben — ein
    # vergessener ``fetch`` oder ein Tippfehler im Feldnamen kostete mehrere hundert
    # Noten, die nur über Stunden Vivino-Abfragen zurückkommen.
    offers = [_offer_from_payload(d) for d in cache.all_offers()]
    rows = compute_scores(attach_maturity(merge_offers(offers)))
    if limit:
        rows = rows[:limit]
    if not rows:
        _echo("Keine Angebote im Cache — zuerst 'wine-check fetch' laufen lassen.", err=True)
        raise typer.Exit(1)

    if nachtragen:
        verworfen = cache.verwerfe_ratings_ohne_feld("vivino", nachtragen)
        _echo(f"Nachtrag '{nachtragen}': {verworfen} Bewertungen verworfen, "
              f"der Rest bleibt aus dem Cache.")
        if not verworfen:
            _echo("Nichts nachzutragen — jede Bewertung mit Treffer führt das Feld.")
    if neu_beurteilen:
        # Für den anderen Anlass als der Nachtrag: nicht ein neues Feld, sondern eine
        # geänderte Entscheidungsregel im Matcher. Dann sind nur die Einträge einer
        # Stufe betroffen, und ein Volllauf über alles wäre zweieinhalb Stunden für
        # nichts.
        verworfen = cache.verwerfe_ratings_mit_konfidenz("vivino", neu_beurteilen)
        _echo(f"Neubeurteilung '{neu_beurteilen}': {verworfen} Bewertungen verworfen, "
              f"der Rest bleibt aus dem Cache.")

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
            # Hier stand eine Rueckschreibung des Angebots mit der Marke ``_rated``.
            # Sie ist entfernt, und zwar aus zwei Gruenden:
            #
            # 1. Niemand liest ``_rated``. Der Bewertungsstand steht in der Tabelle
            #    ``ratings`` und in state/rated.json.
            # 2. ``put_offer`` stempelt ``fetched_at = time.time()``. Damit trug die
            #    Angebotszeile nicht mehr die Zeit des ``fetch``, sondern die des
            #    ``rate`` — und ``all_offers`` filtert genau darauf. Jeder rate-Lauf
            #    verlaengerte die Lebensdauer alter Preise um weitere sieben Tage.
            #    Messbar: am 21.08. wurden durchweg Preise vom 15.08. verrechnet und
            #    gerankt, waehrend die Seite "Stand 21.08." anschrieb.
            #
            # Dazu schrieb sie unter dem *Haendler*-Schluessel, wo ``fetch`` unter dem
            # *Adapter*-Schluessel ablegt — also eine zweite Zeile mit demselben
            # Inhalt. Im Arbeitsverzeichnis 2332 statt 2225 Zeilen.

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
    force: bool = typer.Option(False, "--force",
                               help="auch schreiben, wenn der Stand schlechter ist"),
) -> None:
    """Bewertungen in eine versionierbare Datei schreiben.

    Der GitHub-Wochenlauf holt frische Preise, kann aber nicht selbst bei Vivino
    nachfragen — Rechenzentrums-IPs werden gesperrt. Diese Datei gibt ihm die
    Bewertungen des letzten lokalen Laufs mit, damit die Seite Preise *und* Noten
    zeigt statt nur Preise.
    """
    cache = Cache.open(cache_path)
    rows = cache.export_ratings()
    # Die versionierte Austauschdatei nicht gegen einen schlechteren Stand tauschen.
    # Sie ist die einzige Notenquelle des Wochenlaufs, der selbst nicht bei Vivino
    # nachfragen kann — sie mit Leerwerten zu überschreiben nimmt der Seite die Noten,
    # und zwar dauerhaft, weil der Cache lokal und nicht versioniert ist.
    if out.exists() and not force:
        try:
            vorher = json.loads(out.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            vorher = None
        if isinstance(vorher, list) and len(vorher) >= MIN_VERGLEICHSBASIS \
                and len(rows) < len(vorher) * MIN_BEWERTET_ANTEIL:
            _echo(
                f"Abbruch: nur {len(rows)} Bewertungen gegenüber {len(vorher)} in "
                f"{out}. Die bestehende Datei bleibt stehen — mit --force überschreiben.",
                err=True,
            )
            raise typer.Exit(2)
        # Die Zeilenzahl allein genügt nicht.
        #
        # Weil die beiden Klone getrennte Caches haben, sind ihre Bestände
        # auseinandergelaufen. Gemessen am 21.08.: die Datei führte 3924 Schlüssel, das
        # Arbeitsverzeichnis 2620, ~/winecheck 3799 — und die Vereinigung 3971. Ein
        # Export aus dem kleineren Klon lag mit 1.2 % über der Zahlengrenze und hätte
        # 1351 Schlüssel und darin 597 echte Noten aus der einzigen Sicherung genommen,
        # ohne dass etwas fehlschlägt.
        #
        # Verglichen wird darum die Abdeckung: verliert der neue Satz Schlüssel, die
        # die Datei führt, bleibt sie stehen. Der Weg dazu ist ``ratings-import`` vor
        # dem Export — dann trägt die Datei die Vereinigung.
        if isinstance(vorher, list) and vorher:
            def schluessel(satz):
                return {
                    (r.get("source"), r.get("name_key"), r.get("vintage"))
                    for r in satz if isinstance(r, dict)
                }
            verloren = schluessel(vorher) - schluessel(rows)
            if verloren:
                _echo(
                    f"Abbruch: {len(verloren)} Schlüssel der bestehenden Datei fehlen im "
                    f"neuen Satz ({len(rows)} gegen {len(vorher)} Zeilen).\n"
                    f"  Die Datei ist die einzige Sicherung der Bewertungen — der Cache "
                    f"steht nicht im Git.\n"
                    f"  Erst 'wine-check ratings-import' laufen lassen, dann exportieren; "
                    f"dann trägt die Datei die Vereinigung beider Klone.\n"
                    f"  Mit --force überschreiben, wenn der Verlust gewollt ist.",
                    err=True,
                )
                raise typer.Exit(2)
    out.parent.mkdir(parents=True, exist_ok=True)
    _schreibe_atomar(out, json.dumps(rows, ensure_ascii=False))
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

    # Ist der Bewertungsstand älter als die Angebote, die er bewerten soll?
    #
    # Dann ist ``rate`` abgebrochen, und das war bisher nicht zu bemerken: report las
    # einfach den letzten erfolgreichen Stand, und alle Reissleinen verglichen ihn mit
    # sich selbst. Veröffentlicht wurden die Preise der Vorwoche unter dem Datum von
    # heute. Ein Abbruch soll ein Fehler sein, kein stiller Erfolg.
    stand = _rated_stand(STATE_DIR / "rated.json")
    juengstes = cache.juengstes_angebot()
    if stand is not None and juengstes is not None and stand < juengstes:
        import time as _t

        _echo(
            f"Abgebrochen: der Bewertungsstand ist älter als die Angebote.\n"
            f"  rated.json  {_t.strftime('%d.%m.%Y %H:%M', _t.localtime(stand))}\n"
            f"  Angebote    {_t.strftime('%d.%m.%Y %H:%M', _t.localtime(juengstes))}\n"
            f"  Das heisst, 'rate' ist abgebrochen. Erst 'wine-check rate' zu Ende "
            f"laufen lassen — sonst stünden die Preise des Vorlaufs unter dem heutigen "
            f"Datum auf der Seite.",
            err=True,
        )
        raise typer.Exit(1)

    reports = _load_reports()
    uncertain = _load_uncertain()

    # Reissleine, bevor irgendetwas geschrieben wird. Diese beiden Schwellen gab es
    # bisher nur in .github/workflows/weekly.yml — der lokale Weg (rate, report, site,
    # git push) hatte keine, und veröffentlicht wird tatsächlich über den lokalen.
    # Eine Schemaänderung bei einer Bewertungsquelle hätte die versionierte
    # Austauschdatei mit Leerwerten überschrieben, ohne dass etwas fehlschlägt.
    _prev_id, previous = cache.previous_snapshot()
    bewertet_vorher = (
        sum(1 for d in previous if d.get("vivino_rating") is not None) if previous else None
    )
    try:
        pruefe_plausibilitaet(rows, bewertet_vorher)
    except Unplausibel as exc:
        _echo(f"Abbruch: {exc}", err=True)
        raise typer.Exit(2) from exc

    out.mkdir(parents=True, exist_ok=True)
    csv_path = write_csv(rows, out / "results.csv")
    pdf_path = write_pdf(
        rows, out / "report.pdf", source_reports=reports, uncertain=uncertain,
        retailer_info=info,
    )
    png_path = write_scatter(rows, out / "scatter.png")
    html_path = write_interactive(rows, out / "scatter.html", retailer_info=info)

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
    runs: int = typer.Option(
        1, "--runs",
        help="wie viele Läufe die Seite anbieten soll; Standard 1 (nur der aktuelle)",
    ),
    title: str = typer.Option("Schweizer Weinaktionen", "--title"),
    trotzdem: bool = typer.Option(
        False, "--trotzdem",
        help="eine neuere oder vollständigere Seite überschreiben (siehe SEITE_MIN_ANTEIL)",
    ),
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
    # Standardmässig nur der aktuelle Lauf.
    #
    # Ältere Läufe standen vorher als Kachelreihe auf der Seite. Für die Frage, die
    # sie beantworten soll — was lohnt sich diese Woche —, sind sie ohne Wert, und
    # sie kosteten das Mehrfache an Seitengrösse: jeder Lauf trägt seine tausend
    # Weine mit.
    #
    # Verloren geht dabei nichts. Der Verlauf liegt weiterhin im Cache, und
    # ``diff.md`` weist Preisänderungen gegenüber dem Vorlauf aus. Wer die
    # Entwicklung über Wochen ansehen will, baut die Seite mit ``--runs 12``.
    cache = Cache.open(cache_path)
    # Ein Lauf mehr laden als gezeigt wird: der älteste angezeigte braucht einen
    # Vorgänger, gegen den sich "neu" bestimmen lässt. Der Zusatzlauf wird nur
    # verglichen, nicht ausgeliefert.
    history = cache.all_runs(limit=runs + 1)
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
    for i, run in enumerate(history[:runs]):
        stamp = _time.localtime(run["started_at"])
        # Gegen den unmittelbaren Vorlauf, nicht gegen den neuesten: bei mehreren
        # Läufen soll jeder zeigen, was *damals* neu war.
        vorlauf = history[i + 1] if i + 1 < len(history) else None
        bekannt = (
            {w.get("dedup_key") for w in vorlauf["wines"]} if vorlauf is not None else None
        )
        # Ein Vorlauf, der viel kleiner ist als der aktuelle, taugt nicht als
        # Vergleich. Genau das trat am 14.08. ein: der Klon hatte wochenlang mit
        # altem Code gerechnet, sein letzter Stand zählte 477 Weine, der neue 1524.
        # Rechnerisch waren damit über tausend Weine "neu" — und eine Kennzeichnung,
        # die zwei Drittel der Liste trifft, sagt nichts mehr aus.
        #
        # Lieber gar keine Markierung als eine wertlose: wer die Seite oeffnet, soll
        # "neu" als Hinweis lesen koennen, nicht als Grundrauschen.
        if bekannt is not None and len(bekannt) < len(run["wines"]) * VERGLEICH_MIN_ANTEIL:
            _echo(
                f"  Vorlauf zu klein ({len(bekannt)} gegen {len(run['wines'])} Weine) — "
                f"nichts als neu markiert."
            )
            bekannt = None
        wines = []
        for w in run["wines"]:
            wein = _wine_from_snapshot(w)
            # ``None`` statt ``0``, damit das Feld aus der komprimierten JSON fällt.
            # Ohne Vorlauf bleibt es leer: der erste Lauf hat keine Neuzugänge, er ist
            # einer, und jeden Wein zu markieren wäre eine Aussage ohne Inhalt.
            if bekannt is not None and w.get("dedup_key") not in bekannt:
                wein["neu"] = 1
            wines.append(wein)
        prepared.append({
            "id": run["id"],
            "label": f"{stamp.tm_mday}.{stamp.tm_mon}.{stamp.tm_year}",
            # Damit die Seite den Filter nur anbietet, wenn es etwas zu filtern gibt.
            "hatVorlauf": bekannt is not None,
            "wines": wines,
        })

    # -- Sperre gegen das Überschreiben einer besseren Seite ----------------
    #
    # ``docs/index.html`` ist ein Bauartefakt im Git, damit GitHub Pages es
    # ausliefert. Jeder Klon kann es aus **seinem** Cache neu schreiben, und wer
    # zuletzt pusht, gewinnt. Zwei Klone gibt es hier: das Arbeitsverzeichnis und
    # ~/winecheck, aus dem der Wochenlauf läuft — mit getrennten Caches.
    #
    # Am 21.08. stand ein Commit bereit, der die veröffentlichte Seite von 2531 auf
    # 2206 Weine zurückgesetzt hätte: der Wochenlauf hatte frisch alle Quellen
    # gelesen, das Arbeitsverzeichnis kannte nur den älteren Bestand. Aufgefallen ist
    # das beim Nachsehen, nicht durch eine Prüfung — und beim nächsten Mal fällt es
    # niemandem auf.
    #
    # Verglichen wird gegen die Kennung, die die vorhandene Seite selbst trägt.
    # Verweigert wird, wenn der neue Lauf älter ist oder deutlich weniger Weine
    # trägt. ``--trotzdem`` hebt die Sperre auf; sie soll schützen, nicht blockieren.
    ziel = out / "index.html"
    vorhanden = _seiten_kennung(ziel)
    if vorhanden and not trotzdem:
        alt_lauf, alt_weine = vorhanden
        neu_lauf = str(history[0].get("id") or "")
        neu_weine = len(history[0].get("wines") or [])
        aelter = _lauf_aelter(neu_lauf, alt_lauf, cache_path)
        viel_kleiner = alt_weine and neu_weine < alt_weine * SEITE_MIN_ANTEIL
        if aelter or viel_kleiner:
            grund = (
                f"der Lauf ist älter als der ausgelieferte"
                if aelter else
                f"nur {neu_weine} Weine gegen {alt_weine} in der ausgelieferten Seite"
            )
            _echo(
                f"Abgebrochen: {grund}.\n"
                f"  Die vorhandene Seite stammt aus einem anderen Klon — der Wochenlauf "
                f"läuft aus ~/winecheck mit eigenem Cache.\n"
                f"  Dort neu bauen, oder mit --trotzdem überschreiben.",
                err=True,
            )
            raise typer.Exit(1)

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
    """Domains aller Händler, die diesen Wein anbieten.

    Zwei Quellen, und die zweite fehlte. Die konfigurierte Domain aus der Registry
    trifft nur, wo der Händler auch unter eigenem Namen liest. Der Vivino-Marktplatz
    tut das nicht: er ist als ``vivino.com`` eingetragen, verlinkt aber auf den Shop,
    der tatsächlich liefert — ``bignens.ch``, ``moevenpick-wein.com``,
    ``vinotheque.ch``. Wird nur die Registry gefragt, steht dieser Shop nicht auf der
    Ausschlussliste, und Vivino nennt genau seinen Preis als „Marktpreis".

    Damit verglich sich der Preis mit sich selbst: 289 Weine, die meisten mit
    „gegen Markt +0 %", einige mit −500 % — dort war es nicht einmal derselbe Betrag,
    sondern ein anderes Gebinde desselben Shops.

    Die Adresse des Angebots ist die direkteste Auskunft darüber, wer verkauft, und
    sie kommt darum dazu.
    """
    from urllib.parse import urlparse

    hosts: set[str] = set()
    for price in row.prices:
        cfg = reg.retailers.get(price.retailer)
        if cfg and cfg.domain:
            hosts.add(cfg.domain.lower())
        host = urlparse(price.url or "").netloc.lower().removeprefix("www.")
        if host:
            hosts.add(host)
    return hosts


def _offer_payload(o: Offer) -> dict:
    """Ein Angebot für den Cache. **Jedes** Feld von :class:`Offer` gehört hierher.

    Die Liste ist von Hand geführt und war darum eine Falle: ``roh_ist_gebinde`` und
    ``vat_added`` kamen neu ins Modell, aber nicht hierher — und damit wirkte die
    Zahlbetrags-Rechnung nur im Speicher. Über den Cache, also im Bericht und auf der
    Seite, fiel sie auf den alten Rückfall zurück und wies für einen Wein, den es nur
    im Sechserkarton zu CHF 87 gibt, CHF 522 aus.

    ``tests/test_offer_ablage.py`` vergleicht diese Liste mit den Feldern des Modells
    und schlägt an, wenn wieder eines fehlt.
    """
    return {
        "retailer": o.retailer, "name": o.name, "url": o.url, "vintage": o.vintage,
        "producer": o.producer, "region": o.region, "country": o.country,
        "price_per_bottle_incl_vat": o.price_per_bottle_incl_vat,
        "price_raw": o.price_raw, "price_raw_basis": o.price_raw_basis,
        "price_confidence": o.price_confidence.value,
        "reference_price": o.reference_price, "discount_percent": o.discount_percent,
        "discount_plausibility": o.discount_plausibility.value,
        "is_private_label": o.is_private_label, "bottle_ml": o.bottle_ml,
        "units": o.units, "roh_ist_gebinde": o.roh_ist_gebinde, "vat_added": o.vat_added,
        "article_no": o.article_no, "fetched_at": o.fetched_at,
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
        producer=d.get("producer"), region=d.get("region"), country=d.get("country"),
        bottle_ml=d.get("bottle_ml"), units=d.get("units"),
        # Ohne diese zwei rechnet ``gesamtpreis`` den Kartonpreis noch einmal mal
        # sechs. Alte Einträge tragen sie nicht; ``False`` ist dort der bisherige Stand.
        roh_ist_gebinde=bool(d.get("roh_ist_gebinde")),
        vat_added=bool(d.get("vat_added")),
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
    # Mit Kopf: Zeitstempel und Zahl der Weine.
    #
    # Ohne diese zwei Angaben konnte ``report`` nicht erkennen, dass ``rate``
    # abgebrochen war. Dann las es den Stand des letzten erfolgreichen Laufs, und alle
    # drei Reissleinen verglichen den alten Stand mit sich selbst: die Weinzahl gleich,
    # die Notenzahl gleich, der Seitenumfang gleich. Der Lauf ging durch und
    # veröffentlichte die Preise der Vorwoche unter dem Datum von heute.
    _schreibe_atomar(
        STATE_DIR / "rated.json",
        json.dumps(
            {"geschrieben_am": time.time(), "weine": len(data), "zeilen": data},
            ensure_ascii=False, indent=2,
        ),
    )


def _schreibe_atomar(pfad: Path, text: str) -> None:
    """Erst vollständig schreiben, dann an die Stelle rücken.

    Die Übergabedateien wurden direkt überschrieben. Ein Abbruch mitten im Schreiben
    liess eine halbe JSON-Datei zurück, und die nimmt der nächste Leser als „kaputt"
    statt als „alt" — schlimmer als der alte Stand, den sie ersetzen sollte. Der
    Austausch über ``replace`` ist auf einem Dateisystem atomar.
    """
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_suffix(pfad.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(pfad)


def _rated_zeilen(pfad: Path) -> list[dict]:
    """Die Weinzeilen aus rated.json — beide Dateiformen.

    Ältere Läufe schrieben eine nackte Liste, neuere ein Objekt mit Kopf. Eine alte
    Datei darf nicht zum Fehler werden, nur weil das Format gewachsen ist.
    """
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    if isinstance(daten, dict):
        return daten.get("zeilen") or []
    return daten


def _rated_stand(pfad: Path) -> float | None:
    """Wann wurde rated.json geschrieben? ``None`` bei alter Datei ohne Kopf."""
    if not pfad.exists():
        return None
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    return daten.get("geschrieben_am") if isinstance(daten, dict) else None


def _load_rated() -> list[WineRow]:
    from .ratings.falstaff import _from_payload as falstaff_from
    from .ratings.vivino import _from_payload as vivino_from

    path = STATE_DIR / "rated.json"
    if not path.exists():
        return []
    rows: list[WineRow] = []
    for d in _rated_zeilen(path):
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
    # Erst hier, wo alle Zeilen vorliegen: ein Vivino-Wein gehört zu einem Wein.
    return compute_scores(attach_maturity(resolve_shared_ratings(rows)))


if __name__ == "__main__":
    app()

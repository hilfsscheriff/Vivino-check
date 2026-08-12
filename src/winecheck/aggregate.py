"""Dedup über Händler und ``value_score``.

Dedup ist das Kernfeature: derselbe Wein bei Coop und Prodega wird **eine** Zeile mit
zwei Preisen — nur so ist zu sehen, ob sich die Karte lohnt. Der Schlüssel ist der
normalisierte Name plus Jahrgang, nicht die Artikelnummer: Artikelnummern sind
händlerspezifisch und taugen für den Vergleich nicht.

Der ``value_score`` vergleicht **innerhalb der Preisklasse**. Ein 4.1er für 7 Franken
und ein 4.5er für 125 Franken sind nicht dasselbe — der günstige soll gewinnen.
Gerechnet wird immer auf den Aktionspreis, nie auf den Rabatt.
"""

from __future__ import annotations

from datetime import date

from collections import defaultdict

from .models import (
    MatchConfidence,
    Offer,
    PriceConfidence,
    Rating,
    RetailerPrice,
    VivinoStatus,
    WineRow,
)
from .names import dedup_key, distinctive_tokens, normalized_name, tokenize
from .prices import PRICE_BANDS, price_band


def merge_offers(offers: list[Offer]) -> list[WineRow]:
    """Fasst Angebote verschiedener Händler zum selben Wein zusammen."""
    groups: dict[str, list[Offer]] = defaultdict(list)
    for o in offers:
        groups[dedup_key(o.name, o.vintage)].append(o)

    rows: list[WineRow] = []
    for key, group in groups.items():
        # Den ausführlichsten Namen als Anzeigenamen nehmen — er trägt am meisten
        # Information für die Bewertungssuche.
        display = max(group, key=lambda o: len(normalized_name(o.name)))
        row = WineRow(
            name=display.name,
            vintage=display.vintage,
            dedup_key=key,
            offers=list(group),
            is_private_label=any(o.is_private_label for o in group),
        )
        # Je Händler genau ein Preis. Ein Wein kann denselben Händler mehrfach
        # liefern — Denner wird direkt *und* über Aktionis gelesen, und ein Shop
        # führt dieselbe Flasche manchmal in zwei Gebinden. Behalten wird der
        # verlässlichste, bei gleicher Verlässlichkeit der günstigste.
        by_retailer: dict[str, Offer] = {}
        for o in group:
            prev = by_retailer.get(o.retailer)
            if prev is None or _better_price(o, prev):
                by_retailer[o.retailer] = o

        for o in by_retailer.values():
            row.prices.append(
                RetailerPrice(
                    retailer=o.retailer,
                    price_per_bottle_incl_vat=o.price_per_bottle_incl_vat,
                    price_raw=o.price_raw,
                    price_raw_basis=o.price_raw_basis,
                    url=o.url,
                    price_confidence=o.price_confidence,
                    discount_percent=o.discount_percent,
                    discount_plausibility=o.discount_plausibility,
                )
            )
        _attach_critic_scores(row, group)
        row.price_band = price_band(row.best_price)
        rows.append(row)
    return rows


def _attach_critic_scores(row: WineRow, offers: list[Offer]) -> None:
    """Vom Händler ausgewiesene Kritikernoten übernehmen.

    Das ist der Ersatz für den blockierten Falstaff-Zugang. Der Vorteil gegenüber
    einer eigenen Falstaff-Abfrage: die Note hängt am *exakten* Produkt, es gibt kein
    Namens-Matching und damit kein Fehlzuordnungsrisiko — die Konfidenz ist per
    Konstruktion ``exact``.

    Der Nachteil steht in jeder Zeile: die Note ist vom Händler berichtet und nicht
    bei der Quelle verifiziert. ``falstaff_reported_by`` nennt den Händler, im Report
    steht "laut <Händler>".
    """
    collected: dict[str, list[tuple[float, str]]] = {}
    for offer in offers:
        for critic, value in (offer.critic_scores or {}).items():
            collected.setdefault(critic, []).append((value, offer.retailer))
    if not collected:
        return

    for critic, entries in collected.items():
        value, who = max(entries, key=lambda e: e[0])
        row.critics[critic] = (value, who)

    falstaff = collected.get("falstaff")
    if not falstaff:
        return
    value, who = max(falstaff, key=lambda e: e[0])
    # Widersprechen sich zwei Händler, steht das in der Notiz statt still gemittelt.
    spread = {round(v, 1) for v, _ in falstaff}
    conflict = (
        f" — Händler widersprechen sich: {', '.join(f'{v:.0f}' for v in sorted(spread))}"
        if len(spread) > 1
        else ""
    )
    row.falstaff = Rating(
        source="falstaff",
        value=value,
        scale_max=100.0,
        confidence=MatchConfidence.EXACT,
        source_name=f"laut {who}",
        status="retailer_reported",
        note=(
            f"{value:.0f} Falstaff-Punkte, von {who} am Produkt ausgewiesen "
            f"(nicht bei Falstaff verifiziert — Domain blockiert){conflict}"
        ),
    )


def _better_price(candidate: Offer, current: Offer) -> bool:
    """Verlässlichkeit zuerst, dann der günstigere Preis."""
    rank = {PriceConfidence.HIGH: 0, PriceConfidence.MEDIUM: 1, PriceConfidence.LOW: 2}
    c_rank = rank.get(candidate.price_confidence, 3)
    p_rank = rank.get(current.price_confidence, 3)
    if c_rank != p_rank:
        return c_rank < p_rank
    return (candidate.price_per_bottle_incl_vat or 9e9) < (current.price_per_bottle_incl_vat or 9e9)


def attach_maturity(rows: list[WineRow], table=None) -> list[WineRow]:
    """Trinkreife aus der Vinum-Jahrgangstabelle anhängen.

    Wo Region oder Jahrgang nicht eindeutig zuzuordnen sind, bleibt das Feld leer —
    eine falsche Region liefert eine falsche Empfehlung, und die wäre schlimmer als
    eine Lücke.
    """
    from .trinkreife import Table

    tbl = table if table is not None else Table.load()
    if not tbl.entries:
        return rows
    from .trinkreife import Match, fenster_code

    heute = date.today().year
    for row in rows:
        # Der bei Vivino gefundene Name geht zusätzlich ein — aber nur dort, wo die
        # Tabelle nach dem *Stil* fragt, nicht bei der Regionssuche. Er trägt oft
        # die Rebsorte, die der Händler weglässt.
        stil_name = (row.vivino.matched_name if row.vivino else "") or ""
        match = tbl.lookup(row.name, row.vintage, stil_name=stil_name)

        von = row.vivino.drink_from if row.vivino else None
        bis = row.vivino.drink_until if row.vivino else None

        if match is not None:
            # Vinum bleibt führend. Vivinos Fenster wird mitgeführt, damit ein
            # Widerspruch sichtbar wird, statt dass eine der beiden Quellen
            # stillschweigend gewinnt.
            match.vivino_von, match.vivino_bis = von, bis
        elif fenster_code(von, bis, heute):
            # Die Tabelle schweigt — meist, weil die Region nicht zu erkennen war
            # oder sie das Gebiet nicht führt. Dann trägt Vivino die Auskunft
            # allein: sie gilt für genau diesen Wein und diesen Jahrgang und ist
            # damit spezifischer als alles, was die Regionstabelle geliefert hätte.
            match = Match(
                code=fenster_code(von, bis, heute),
                region="",
                wine_type="unbekannt",
                vintage=row.vintage or 0,
                vivino_von=von,
                vivino_bis=bis,
                quelle="vivino",
            )
        row.maturity = match
    return rows



#: Rangfolge für die Frage, welcher Wein einen umstrittenen Vivino-Eintrag behalten darf.
_CONF_RANG = {"exact": 4, "wine_level": 3, "fuzzy": 2, "winery_level": 1, "": 0, "none": 0}


def resolve_shared_ratings(rows: list[WineRow]) -> list[WineRow]:
    """Ein Vivino-Wein gehört zu **einem** Wein.

    Tragen mehrere *verschiedene* Händlerweine denselben Vivino-Eintrag, kann höchstens
    einer davon stimmen. Aufgefallen an „Rocca di Frassinello": fünf Weine des Guts —
    il Frassinello, la Fillirea, la Guardia, la Rocca, la Uni — bekamen alle die 4.2 aus
    4'655 Bewertungen des Sammeleintrags „Rocca di Frassinello Maremma Toscana". Vier
    davon sind falsch, und man sieht es der einzelnen Zeile nicht an; erst der Vergleich
    über alle Zeilen verrät es.

    Verschiedene **Jahrgänge** desselben Weins sind dagegen in Ordnung und müssen
    bleiben: „Legaris Crianza" 2020, 2021 und 2022 teilen sich zu Recht die Weinseite.
    Unterschieden wird darum an den *unterscheidenden* Wörtern — sind sie gleich, ist es
    derselbe Wein in anderem Jahr; unterscheiden sie sich, sind es andere Weine.

    Der beste Treffer behält die Note. Die übrigen verlieren sie und bekommen eine
    Begründung, die den Gewinner nennt — eine Lücke mit Erklärung ist brauchbarer als
    eine Zahl, die zu einem anderen Wein gehört.
    """
    nach_wein: dict[str, list[WineRow]] = {}
    for row in rows:
        v = row.vivino
        if v is None or v.rating is None or not v.url or "/w/" not in v.url:
            continue
        wein_id = v.url.split("/w/")[-1].split("?")[0].split("/")[0]
        nach_wein.setdefault(wein_id, []).append(row)

    for gruppe in nach_wein.values():
        if len(gruppe) < 2:
            continue
        # Verglichen wird über **alle** Identitätswörter, nicht nur die
        # unterscheidenden. Der Jahrgang ist ohnehin schon heraus, „Legaris Crianza"
        # 2020/2021/2022 ergeben also dieselbe Menge. Qualitätsstufen dagegen müssen
        # zählen: „Porte de Novembre" und „Porte de Novembre **Ice**" sind zwei Weine,
        # und weil „Ice" als Süssweinmerkmal gilt, fiele es aus den unterscheidenden
        # Wörtern heraus — die drei Zeilen sähen identisch aus und blieben alle stehen.
        signaturen = {frozenset(tokenize(r.name)) for r in gruppe}
        if len(signaturen) < 2:
            continue

        def guete(r: WineRow) -> tuple[int, int]:
            v = r.vivino
            konf = _CONF_RANG.get((v.match_confidence or "") if v else "", 0)
            # Bei gleichem Rang gewinnt, wessen Name im Fundnamen am besten aufgeht.
            eigen = set(distinctive_tokens(r.name))
            gefunden = set(distinctive_tokens((v.matched_name or "") if v else ""))
            return (konf, len(eigen & gefunden) - len(eigen - gefunden))

        sieger = max(gruppe, key=guete)
        for row in gruppe:
            if row is sieger or row.vivino is None:
                continue
            v = row.vivino
            v.rating = None
            v.rating_count = None
            v.status = VivinoStatus.NO_ENTRY
            v.match_confidence = "none"
            v.note = (
                f"Eintrag '{v.matched_name}' gehört zu einem anderen Wein dieses "
                f"Produzenten ({sieger.name[:44]}) — hier keine eigene Bewertung "
                f"gefunden. Suche öffnen"
            )
            v.matched_name = ""
    return rows


def compute_scores(rows: list[WineRow]) -> list[WineRow]:
    """Setzt ``value_score`` je Preisklasse.

    Innerhalb einer Klasse wird die normalisierte Bewertung gegen den Preis gestellt:
    der Score steigt mit der Bewertung und fällt mit dem Preis, jeweils relativ zu den
    anderen Weinen derselben Klasse. Weine ohne Bewertung oder ohne verlässlichen
    Preis bekommen keinen Score — geraten wird nichts.
    """
    by_band: dict[str, list[WineRow]] = defaultdict(list)
    for row in rows:
        rating, source = row.ranking_rating()
        row.rank_source = source
        price = row.best_price
        # Gebindegrösse unsicher -> keine Zahl. Ein falsch umgerechneter Literpreis
        # erzeugt einen Scheinsieger. Die Regel steht nicht hier, sondern in
        # :attr:`WineRow.best_price`, das ``PriceConfidence.LOW`` gar nicht als Preis
        # gelten lässt — ``price is None`` oben fängt sie also schon.
        #
        # Hier stand dieselbe Prüfung ein zweites Mal, ausdrücklich als Ranking-Veto
        # kommentiert. Am ganzen Bestand fing sie **null** Zeilen. Das ist die
        # unangenehmste Sorte toter Code: er liest sich wie ein Schutz, und wer
        # ``best_price`` später lockert, verlässt sich auf ihn.
        if rating is None or price is None or price <= 0:
            row.value_score = None
            continue
        by_band[row.price_band].append(row)

    for band, members in by_band.items():
        prices = [r.best_price for r in members if r.best_price]
        ratings = [r.ranking_rating()[0] for r in members]
        ratings = [x for x in ratings if x is not None]
        if not prices or not ratings:
            continue
        p_lo, p_hi = min(prices), max(prices)
        r_lo, r_hi = min(ratings), max(ratings)
        for row in members:
            rating, _ = row.ranking_rating()
            price = row.best_price
            if rating is None or price is None:
                continue
            # Position innerhalb der Klasse, 0..1. Bei nur einem Wein je Klasse oder
            # identischen Werten fällt der Term auf 0.5 zurück.
            r_pos = (rating - r_lo) / (r_hi - r_lo) if r_hi > r_lo else 0.5
            p_pos = (price - p_lo) / (p_hi - p_lo) if p_hi > p_lo else 0.5
            # Bewertung zählt doppelt: ein guter Wein soll einen billigen schlechten
            # nicht automatisch verlieren.
            row.value_score = round(100 * (2 * r_pos + (1 - p_pos)) / 3, 1)

    # Dieselbe Frage, andere Rechnung — und zwar die, welche die Webseite zeigt.
    #
    # Vorher gab es beide Kennzahlen auch schon, aber in getrennten Ausgabekanälen:
    # das PDF rankte nach ``value_score`` (Rangposition in der Preisklasse), die Seite
    # zeigte den Regressionsrest nach ``(typ, sorte)``, und beide hiessen dem Nutzer
    # gegenüber „Preis-Leistung". Als Spec §6 die Gruppierung auf den Stil-Typ
    # umstellte, landete das nur in der Seite — die PDF-Rangliste blieb bei der
    # unkorrigierten Rechnung, also bei genau der Verzerrung, die §6 beheben sollte.
    #
    # Jetzt stehen beide in derselben Zeile. Angezeigt und geranked wird weiterhin
    # ``value_score``: §6 verlangt ausdrücklich Parallelbetrieb, „bis die Verteilung
    # geprüft ist", und die PDF-Rangfolge umzustellen ist eine Produktentscheidung,
    # keine Aufräumarbeit. Wer sie treffen will, tauscht in pdf_out.py und diff.py den
    # Sortierschlüssel — die Zahl liegt bereit.
    _wert_scores(rows)
    return rows


def _wert_scores(rows: list[WineRow]) -> None:
    """Trägt :attr:`WineRow.wert_score` aus :mod:`winecheck.wert` ein.

    Übersetzt die Wein-Zeilen in die Form, die das Wertmodul erwartet — dasselbe
    Vokabular, das die Seite verwendet — und schreibt das Ergebnis zurück. Ein
    Zwischenschritt statt eines zweiten Rechenwegs: die Formel gibt es nur einmal.

    Die Note kommt aus :meth:`WineRow.chart_rating` und nicht aus ``vivino.rating``.
    Das ist die Hausregel für „eine Vivino-Note auf einer Skala, die sich vergleichen
    lässt": sie schliesst ``winery_level`` aus, weil ein Produzenten-Mittelwert nicht
    die Note dieses Weins ist. Die Seite tut dasselbe, nur an anderer Stelle. Vorher
    stand hier ``vivino.rating`` — damit trugen 22 Weine eine CSV-Zahl, die die Seite
    zu Recht nicht zeigt, und die 22 verschoben zusätzlich jeden Gruppenmittelwert
    und damit *jede* Zahl der Spalte gegenüber der Seite.

    ``fuzzy`` bleibt drin, und das ist Absicht: die Zuordnung ist plausibel, nur
    unbestätigt, und sie herauszunehmen würde die Gruppen ausdünnen. Ins Ranking
    darf ein solcher Wein trotzdem nicht — dafür gibt es
    :meth:`WineRow.wert_rankable`, genau wie :meth:`chart_confirmed` neben
    :meth:`chart_rating` steht.

    Gerechnet wird über :func:`winecheck.wert._add_value_scores` — dieselbe Funktion, die
    die Seite aufruft, statt eines eigenen Aufrufs von ``_je_typ``. Damit fällt auch die
    Trennung von Schweizer Handel und Marktplatz mit an, und zwar unvermeidlich: sie
    steckt in der Funktion. Vorher fehlte sie hier, und das kostete den Bericht seinen
    Zweck — 15 der 20 empfohlenen Weine waren nur beim Vivino-Marktplatz zu kaufen,
    in zwei Preisklassen sogar alle vier. Ein Heft mit dem Titel „Aktionen der Schweizer
    Weinhändler", dessen Empfehlungen man in der Schweiz nicht kaufen kann.
    """
    from .prices import MARKTPLATZ_QUELLEN
    from .wert import _add_value_scores

    tragbar = [r for r in rows if r.chart_rating() is not None and (r.best_price or 0) > 0]
    if not tragbar:
        return
    dicts = []
    for r in tragbar:
        haendler = {p.retailer for p in r.prices}
        dicts.append({
            "rating": r.chart_rating(),
            "ratingCount": r.vivino.rating_count or 0,
            "price": r.best_price,
            # Roh weitergeben. Ob ``unbekannt`` eine eigene Gruppe bildet, entscheidet
            # das Wertmodul für alle Aufrufer gleich — siehe wert._typ_gruppe.
            "typ": r.stil.typ,
            "style": r.style,
            # Zwei Kennzeichen, kein Entweder-oder: ein Wein kann in beiden Welten
            # stehen, und dann zählt er zum Schweizer Handel — dort ist er zu kaufen.
            "marketplace": bool(haendler & MARKTPLATZ_QUELLEN),
            "swiss": bool(haendler - MARKTPLATZ_QUELLEN),
        })
    _add_value_scores(dicts)
    for row, d in zip(tragbar, dicts):
        alle = d.get("valueScoreAll")
        welt = d.get("valueScore")
        row.wert_score = round(alle, 3) if alle is not None else None
        row.wert_score_welt = round(welt, 3) if welt is not None else None


def band_summary(rows: list[WineRow]) -> list[tuple[str, int, int]]:
    """``(Preisklasse, Anzahl, davon mit Bewertung)`` — für den Report."""
    out = []
    for label, _lo, _hi in PRICE_BANDS:
        members = [r for r in rows if r.price_band == label]
        rated = [r for r in members if r.has_any_rating]
        out.append((label, len(members), len(rated)))
    return out


def cross_retailer_rows(rows: list[WineRow]) -> list[WineRow]:
    """Weine, die bei mehr als einem Händler in Aktion sind — der eigentliche
    Grund für den händlerübergreifenden Vergleich."""
    return sorted(
        (r for r in rows if r.retailer_count > 1),
        key=lambda r: -(_spread(r) or 0),
    )


def _spread(row: WineRow) -> float | None:
    """Preisspanne zwischen dem teuersten und günstigsten Händler."""
    vals = [
        p.price_per_bottle_incl_vat
        for p in row.prices
        if p.price_per_bottle_incl_vat is not None
        and p.price_confidence is not PriceConfidence.LOW
    ]
    if len(vals) < 2:
        return None
    return round(max(vals) - min(vals), 2)


def spread(row: WineRow) -> float | None:
    return _spread(row)


# --------------------------------------------------------------- Reissleine

#: Ab so vielen blockierten Weinen ist eine Bewertungsquelle dichtgemacht, nicht das
#: Sortiment gewechselt. Beim ersten CI-Lauf waren es 465 von 478.
MAX_BLOCKIERT_ANTEIL = 0.20

#: So viel der bisher ausgelieferten Bewertungen muss ein neuer Stand mindestens
#: erreichen. Ein Sortimentswechsel drückt die Trefferquote legitim, ein stiller
#: Ausfall halbiert sie.
MIN_BEWERTET_ANTEIL = 0.66

#: Unter so wenigen bisher ausgelieferten Bewertungen ist der Vergleich sinnlos —
#: beim ersten Lauf gibt es keinen Vorstand.
MIN_VERGLEICHSBASIS = 20


class Unplausibel(RuntimeError):
    """Der neue Stand ist so viel schlechter als der alte, dass er nicht taugt.

    Warum das hier steht und nicht nur im Workflow: die beiden Schwellen gab es schon,
    aber ausschliesslich in ``.github/workflows/weekly.yml``. Der lokale Weg — rate,
    ratings-export, report, site, git push — hatte keine, und über den wird tatsächlich
    veröffentlicht. Eine Schemaänderung bei Vivino während eines lokalen Nachtlaufs
    hätte die versionierte Austauschdatei mit Leerwerten überschrieben und eine Seite
    ohne Noten publiziert, ohne dass etwas fehlschlägt.

    Eine Regel für beide Wege, an einer Stelle gepflegt.
    """


def pruefe_plausibilitaet(rows: list[WineRow], bewertet_vorher: int | None = None) -> None:
    """Wirft :class:`Unplausibel`, wenn der Stand nicht ausgeliefert werden darf.

    Zwei Prüfungen, beide aus dem Wochenlauf übernommen:

    * **Blockade.** Sind über :data:`MAX_BLOCKIERT_ANTEIL` der Weine als ``blocked``
      gemeldet, hat eine Quelle dichtgemacht. Das ist das eindeutige Signal — ein
      Sortimentswechsel erzeugt kein Sperrmuster.
    * **Stiller Einbruch.** Fällt die Zahl bewerteter Weine unter
      :data:`MIN_BEWERTET_ANTEIL` des bisher ausgelieferten Stands, liefert eine Quelle
      leer statt zu blocken. Das ist der Fall, den eine Schemaänderung erzeugt.

    Args:
        bewertet_vorher: Zahl der Bewertungen im bisher ausgelieferten Stand. ``None``
            heisst „kein Vergleichsstand" — dann greift nur die Blockadeprüfung.
    """
    if not rows:
        raise Unplausibel("Keine Weine im Bestand — es gibt nichts auszuliefern.")

    blockiert = sum(
        1 for r in rows if r.vivino is not None and r.vivino.status is VivinoStatus.BLOCKED
    )
    if blockiert > len(rows) * MAX_BLOCKIERT_ANTEIL:
        raise Unplausibel(
            f"{blockiert} von {len(rows)} Weinen blockiert "
            f"(Grenze {MAX_BLOCKIERT_ANTEIL:.0%}) — eine Bewertungsquelle hat "
            f"dichtgemacht. Der alte Stand bleibt stehen."
        )

    bewertet = sum(1 for r in rows if r.vivino is not None and r.vivino.has_rating)
    if (
        bewertet_vorher is not None
        and bewertet_vorher >= MIN_VERGLEICHSBASIS
        and bewertet < bewertet_vorher * MIN_BEWERTET_ANTEIL
    ):
        raise Unplausibel(
            f"nur {bewertet} bewertete Weine gegenüber {bewertet_vorher} bisher "
            f"(Grenze {MIN_BEWERTET_ANTEIL:.0%}) — eine Quelle liefert still leer. "
            f"Der alte Stand bleibt stehen."
        )

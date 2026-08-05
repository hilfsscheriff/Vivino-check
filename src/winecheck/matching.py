"""Namens-Matching zwischen Händler-Bezeichnung und Quell-Bezeichnung.

Das ist der schwierige Teil, nicht das Scraping. Der Matcher arbeitet in drei Schritten:

1. **Normalisieren** (:mod:`winecheck.names`) — Akzente, Jahrgang, Volumen, Gebinde,
   rechtliche Bezeichnungen und Betriebsformen raus.
2. **Vetos** — zwei Regeln, die einen Match unabhängig vom Ähnlichkeitswert verhindern:

   * *Qualitätsstufen-Veto*: Steht ``Classico``, ``Riserva``, ``Superiore``, ``Brut``
     … auf genau einer Seite, ist es ein anderer Wein.
   * *Fremd-Token-Veto*: Trägt die Quell-Bezeichnung nach dem ersten gemeinsamen Token
     noch ein eigenständiges Wort, das der Händlername nicht kennt, ist es ein anderer
     Wein — typisch der Zweitwein (``Il Bruciato``). Fremdwörter *vor* dem ersten
     gemeinsamen Token sind erlaubt, das ist der Produzentenpräfix (``Settesoli``).
3. **Ähnlichkeit** — erst danach entscheidet ``rapidfuzz`` über die Konfidenz.

Die Reihenfolge ist der Punkt: ein hoher Ähnlichkeitswert darf ein Veto nicht
überstimmen. Sonst empfiehlt das Tool einen 13-Franken-Wein mit der Bewertung eines
130-Franken-Weins.
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from .models import MatchConfidence, MatchDecision
from .names import (
    COLOUR_TOKENS,
    DISCRIMINATING,
    GRAPE_NAMES,
    PRODUCER_WORDS,
    REGION_HINTS,
    colour_group,
    discriminating_tokens,
    extract_vintage,
    is_distinctive,
    tokenize,
    tokenize_keep_producer,
)

#: Unter diesem Ähnlichkeitswert wird gar nicht gematcht.
MIN_SCORE = 84.0

#: Ab hier gilt der Name als sicher; darunter (aber über MIN_SCORE) ist es ``fuzzy``.
STRONG_SCORE = 93.0

#: Anteil der Händler-Tokens, den die Quelle erklären muss, damit der Match stark ist.
STRONG_COVERAGE = 0.66

#: Liegen die zwei besten Kandidaten näher zusammen als das, ist die Lage uneindeutig.
AMBIGUITY_MARGIN = 4.0

#: So viele Zusatzwörter darf die Quelle bei vollständiger Abdeckung führen, bevor
#: der Match kippt (Produktlinien wie "Les Grands Dignitaires" haben zwei).
MAX_TOLERATED_EXTRA = 2


@dataclass
class _Prepared:
    raw: str
    tokens: list[str]
    token_set: set[str]
    vintage: int | None
    seq: list[str]           # inkl. Betriebsformen, für die Zweitwein-Erkennung

    @property
    def joined(self) -> str:
        return " ".join(self.tokens)


def prepare(name: str, vintage: int | None = None) -> _Prepared:
    toks = tokenize(name)
    return _Prepared(
        raw=name,
        tokens=toks,
        token_set=set(toks),
        vintage=vintage if vintage is not None else extract_vintage(name),
        seq=tokenize_keep_producer(name),
    )


def _similarity(a: _Prepared, b: _Prepared) -> float:
    """Beste von drei Metriken. ``token_set_ratio`` verzeiht Wortreihenfolge und
    Teilmengen, ``token_sort_ratio`` bestraft fehlende Wörter stärker, ``WRatio``
    fängt Tippfehler."""
    if not a.tokens or not b.tokens:
        return 0.0
    return max(
        fuzz.token_set_ratio(a.joined, b.joined),
        fuzz.token_sort_ratio(a.joined, b.joined),
        fuzz.WRatio(a.joined, b.joined),
    )


def _qualifier_veto(retailer: _Prepared, source: _Prepared) -> str | None:
    """Qualitätsstufen müssen auf beiden Seiten gleich sein."""
    r_q = discriminating_tokens(retailer.tokens)
    s_q = discriminating_tokens(source.tokens)
    only_source = s_q - r_q
    only_retailer = r_q - s_q
    if only_source:
        return f"{_pretty(only_source)} nur in der Quell-Bezeichnung — anderer Wein"
    if only_retailer:
        return f"{_pretty(only_retailer)} nur in der Händler-Bezeichnung — anderer Wein"
    return None


def _colour_veto(retailer: _Prepared, source: _Prepared) -> str | None:
    """Farbe kippt den Match nur im Widerspruch.

    Fehlt die Farbe auf einer Seite, ist das belanglos — "Rosso del Veronese" gegen
    "Campofiorin" meint denselben Wein. Stehen aber auf beiden Seiten Farben und sie
    widersprechen sich, ist es ein anderes Produkt.
    """
    r_c = {g for g in (colour_group(t) for t in retailer.tokens) if g}
    s_c = {g for g in (colour_group(t) for t in source.tokens) if g}
    if r_c and s_c and not (r_c & s_c):
        return f"Farbe widersprüchlich ({'/'.join(sorted(r_c))} vs. {'/'.join(sorted(s_c))})"
    return None


def _foreign_token_analysis(
    retailer: _Prepared, source: _Prepared, coverage: float
) -> tuple[str | None, list[str]]:
    """Eigenständige Fremdwörter in der Quelle nach dem ersten gemeinsamen Token.

    Hier liegt die unangenehmste Stelle des ganzen Matchers, weil zwei Fälle
    **lexikalisch nicht unterscheidbar** sind:

    * ``Provins Valais Les Grands Dignitaires Domherrenwein Fendant`` — "Les Grands
      Dignitaires" ist die Produktlinie von Provins, der Wein ist derselbe.
    * ``Antinori Tenuta Guado al Tasso Il Bruciato Bolgheri`` — "Il Bruciato" ist der
      Zweitwein, ein anderer Wein.

    Beide Male trägt die Quelle Zusatzwörter, die der Händlername nicht kennt. Statt
    zu raten, entscheidet die **Abdeckung**:

    * Deckt die Quelle den Händlernamen *vollständig* ab und sind es höchstens zwei
      Zusatzwörter, gilt der Match — aber nur als ``fuzzy``, mit ausgegebener
      Quell-Bezeichnung. Genau dafür ist die Konfidenzstufe da.
    * Fehlt dagegen ein Bestandteil des Händlernamens in der Quelle, ist es ein
      anderer Wein: Veto.

    Die Zweitwein-Fälle nach französischem Muster fangen zusätzlich die beiden
    positionsbasierten Regeln ab.

    Returns:
        ``(Veto-Grund oder None, tolerierte Zusatzwörter)``
    """
    first_hit = next(
        (i for i, tok in enumerate(source.tokens) if tok in retailer.token_set), None
    )
    if first_hit is None:
        return None, []
    suspects = [
        tok
        for tok in source.tokens[first_hit:]
        if tok not in retailer.token_set
        and tok not in REGION_HINTS
        and tok not in COLOUR_TOKENS
        and len(tok) > 2
        and not tok.isdigit()
    ]
    if not suspects:
        return None, []

    fully_covered = coverage >= 1.0 - 1e-9
    specific_enough = len(retailer.token_set) >= 3
    if fully_covered and specific_enough and len(suspects) <= MAX_TOLERATED_EXTRA:
        return None, suspects

    return (
        f"{_pretty(set(suspects))} steht nur in der Quell-Bezeichnung, während dem "
        f"Händlernamen Bestandteile fehlen (Abdeckung {coverage:.0%}) — eigener Wein "
        f"(z.B. Zweitwein oder andere Cuvée)"
    ), []


def _leading_cuvee_veto(retailer: _Prepared, source: _Prepared) -> str | None:
    """Zweitwein nach französischem Muster: ``<Cuvée> du Château <Gut>``.

    Steht in der Quell-Bezeichnung ein unbekanntes Wort *vor* der Betriebsform
    (``Château``, ``Domaine``, ``Tenuta``), ist das kein Produzentenpräfix, sondern ein
    eigener Cuvée-Name: ``Pavillon Rouge du Château Margaux`` ist nicht
    ``Château Margaux``, ``Les Forts de Latour`` ist nicht ``Château Latour``.

    Umgekehrt ist ``Settesoli Passìo …`` unbedenklich — dort steht überhaupt keine
    Betriebsform, das führende Wort *ist* der Produzent.
    """
    first_producer = next((i for i, t in enumerate(source.seq) if t in PRODUCER_WORDS), None)
    if first_producer is None or first_producer == 0:
        return None
    leading = [
        t
        for t in source.seq[:first_producer]
        if t not in PRODUCER_WORDS
        and t not in retailer.token_set
        and t not in REGION_HINTS
        and t not in COLOUR_TOKENS
        and len(t) > 2
    ]
    if leading:
        return (
            f"{_pretty(set(leading))} steht vor der Betriebsform in der Quell-Bezeichnung "
            f"— eigener Cuvée-Name (Zweitwein-Muster)"
        )
    return None


def _cuvee_before_producer_name_veto(retailer: _Prepared, source: _Prepared) -> str | None:
    """Spiegelbild von :func:`_leading_cuvee_veto`, wenn die Betriebsform beim *Händler*
    steht statt in der Quelle.

    ``Château Lafite Rothschild`` sagt: der Produzent heisst "Lafite Rothschild".
    Wenn die Quelle davor noch ein eigenes Wort führt — ``Carruades de Lafite
    Rothschild`` —, ist das ein Cuvée-Name und damit ein anderer Wein.

    Fehlt beim Händler die Betriebsform (``Passìo Nero d'Avola …``), greift die Regel
    nicht: dann *ist* das führende Wort der Quelle der Produzent (``Settesoli``).
    """
    idx = next((i for i, t in enumerate(retailer.seq) if t in PRODUCER_WORDS), None)
    if idx is None:
        return None
    producer_name = [t for t in retailer.seq[idx + 1:] if t not in PRODUCER_WORDS]
    if not producer_name:
        return None
    anchor = producer_name[0]
    pos = next((i for i, t in enumerate(source.seq) if t == anchor), None)
    if pos is None or pos == 0:
        return None
    leading = [
        t
        for t in source.seq[:pos]
        if t not in PRODUCER_WORDS
        and t not in retailer.token_set
        and t not in REGION_HINTS
        and t not in COLOUR_TOKENS
        and len(t) > 2
    ]
    if leading:
        return (
            f"{_pretty(set(leading))} steht in der Quelle vor dem Produzentennamen "
            f"'{anchor.capitalize()}' — eigener Cuvée-Name (Zweitwein-Muster)"
        )
    return None


def _pretty(tokens: set[str]) -> str:
    return ", ".join(f"'{t.capitalize()}'" for t in sorted(tokens))


#: Siehe :func:`winecheck.names.is_distinctive` — dort steht die Begründung.
_is_distinctive = is_distinctive


def match_wine(
    retailer_name: str,
    source_name: str,
    *,
    retailer_vintage: int | None = None,
    source_vintage: int | None = None,
    source_has_vintage_rating: bool = False,
) -> MatchDecision:
    """Prüft, ob Händler- und Quell-Bezeichnung denselben Wein meinen.

    Args:
        source_has_vintage_rating: True, wenn die Quelle eine jahrgangsspezifische
            Bewertung liefert. Nur dann kann das Ergebnis ``exact`` werden.
    """
    r = prepare(retailer_name, retailer_vintage)
    s = prepare(source_name, source_vintage)

    if not r.tokens or not s.tokens:
        return MatchDecision(
            matched=False,
            confidence=MatchConfidence.NONE,
            score=0.0,
            reason="Name nach Normalisierung leer",
            source_name=source_name,
        )

    score = _similarity(r, s)
    shared = r.token_set & s.token_set
    coverage = len(shared) / len(r.token_set) if r.token_set else 0.0

    foreign_veto, tolerated_extras = _foreign_token_analysis(r, s, coverage)

    # -- Vetos zuerst. Ein hoher Score darf sie nicht überstimmen. ------------
    vetos = (
        _qualifier_veto(r, s),
        _colour_veto(r, s),
        foreign_veto,
        _leading_cuvee_veto(r, s),
        _cuvee_before_producer_name_veto(r, s),
    )
    for veto in vetos:
        if veto:
            return MatchDecision(
                matched=False,
                confidence=MatchConfidence.NONE,
                score=score,
                reason=veto,
                source_name=source_name,
            )

    # -- Anker: mindestens ein *unterscheidendes* gemeinsames Token ----------
    # Rebsorte, Region, Farbe und Qualitätsstufe sind generisch. "Heldenrosé Rosé de
    # Gamay" und "Perdono Rosé di Gamay" teilen Farbe und Rebsorte und sind trotzdem
    # zwei verschiedene Weine; "Castelbarco Valpolicella Ripasso Superiore" darf nicht
    # an einem anonymen "Valpolicella Ripasso Superiore" hängen bleiben. Ohne einen
    # Anker aus Produzent, Marke oder Lagenname gibt es keinen Match.
    anchors = [t for t in shared if _is_distinctive(t)]
    strong_shared = anchors
    if not anchors:
        return MatchDecision(
            matched=False,
            confidence=MatchConfidence.NONE,
            score=score,
            reason=(
                "gemeinsam sind nur generische Bestandteile "
                f"({_pretty(shared) or 'keine'}) — kein Produzenten- oder Markenbezug"
            ),
            source_name=source_name,
        )
    if len(shared) < 2 and not any(len(t) >= 6 for t in shared):
        return MatchDecision(
            matched=False,
            confidence=MatchConfidence.NONE,
            score=score,
            reason="zu wenig gemeinsame Namensbestandteile",
            source_name=source_name,
        )

    if score < MIN_SCORE:
        return MatchDecision(
            matched=False,
            confidence=MatchConfidence.NONE,
            score=score,
            reason=f"Ähnlichkeit {score:.0f} unter Schwelle {MIN_SCORE:.0f}",
            source_name=source_name,
        )

    # -- Konfidenz -----------------------------------------------------------
    is_strong = (
        score >= STRONG_SCORE
        and coverage >= STRONG_COVERAGE
        and bool(strong_shared)
        and not tolerated_extras  # Zusatzwörter in der Quelle -> nie "sicher"
    )
    vintage_match: bool | None
    if r.vintage is not None and s.vintage is not None:
        vintage_match = r.vintage == s.vintage
    else:
        vintage_match = None

    if tolerated_extras:
        conf = MatchConfidence.FUZZY
        reason = (
            f"Quelle führt zusätzlich {_pretty(set(tolerated_extras))} — Händlername "
            f"vollständig abgedeckt, aber Quell-Bezeichnung prüfen "
            f"(Produktlinie oder eigener Wein?)"
        )
    elif not is_strong:
        conf = MatchConfidence.FUZZY
        reason = f"ähnlich (Score {score:.0f}, Abdeckung {coverage:.0%})"
    elif vintage_match and source_has_vintage_rating:
        conf = MatchConfidence.EXACT
        reason = f"Name und Jahrgang {r.vintage} bestätigt"
    elif vintage_match is False:
        conf = MatchConfidence.WINE_LEVEL
        reason = f"Wein bestätigt, Jahrgang weicht ab ({r.vintage} vs. {s.vintage})"
    else:
        conf = MatchConfidence.WINE_LEVEL
        reason = "Wein bestätigt, kein jahrgangsspezifischer Wert"

    return MatchDecision(
        matched=True,
        confidence=conf,
        score=score,
        reason=reason,
        source_name=source_name,
        vintage_match=vintage_match,
    )


def match_winery(retailer_name: str, winery_name: str) -> MatchDecision:
    """Schwacher Pfad: nur der Produzent stimmt.

    Bewusst ohne Qualitätsstufen-Veto — ein Produzentenname enthält keine
    Qualitätsstufe, und ``Col del Sol Brut Prosecco Superiore`` soll den Produzenten
    ``Col del Sol`` finden dürfen, auch wenn der Wein selbst nicht bewertet ist.
    """
    r = prepare(retailer_name)
    w = prepare(winery_name)
    if not r.tokens or not w.tokens:
        return MatchDecision(False, MatchConfidence.NONE, 0.0, "Name leer", winery_name)

    covered = sum(1 for tok in w.token_set if tok in r.token_set)
    ratio = covered / len(w.token_set)
    score = max(fuzz.partial_ratio(w.joined, r.joined), ratio * 100)
    if ratio >= 0.6 and score >= MIN_SCORE:
        return MatchDecision(
            matched=True,
            confidence=MatchConfidence.WINERY_LEVEL,
            score=score,
            reason=f"nur Produzent '{winery_name}' erkannt, Wein selbst nicht bewertet",
            source_name=winery_name,
        )
    return MatchDecision(
        matched=False,
        confidence=MatchConfidence.NONE,
        score=score,
        reason="Produzent nicht erkannt",
        source_name=winery_name,
    )


@dataclass
class Ranked:
    index: int
    decision: MatchDecision


def rank_candidates(
    retailer_name: str,
    candidates: list[tuple[str, int | None, bool]],
    *,
    retailer_vintage: int | None = None,
) -> tuple[list[Ranked], bool]:
    """Bewertet alle Kandidaten einer Quelle.

    Args:
        candidates: ``(name, vintage, has_vintage_rating)`` je Kandidat.

    Returns:
        ``(sortierte Treffer, ambiguous)``. ``ambiguous`` ist True, wenn zwei
        unterschiedliche Kandidaten praktisch gleich gut passen — dann wird nicht
        gewählt, sondern es werden bis zu drei zur Auswahl ausgegeben.
    """
    hits: list[Ranked] = []
    for i, (name, vintage, has_vr) in enumerate(candidates):
        d = match_wine(
            retailer_name,
            name,
            retailer_vintage=retailer_vintage,
            source_vintage=vintage,
            source_has_vintage_rating=has_vr,
        )
        if d.matched:
            hits.append(Ranked(i, d))

    hits.sort(key=lambda h: (-h.decision.score, h.decision.confidence.value))
    ambiguous = False
    if len(hits) >= 2:
        top, second = hits[0].decision, hits[1].decision
        # Gleicher Wein in mehreren Jahrgängen ist nicht uneindeutig.
        same_wine = _similarity(prepare(top.source_name or ""), prepare(second.source_name or "")) >= 95
        if not same_wine and (top.score - second.score) < AMBIGUITY_MARGIN:
            ambiguous = True
    return hits, ambiguous

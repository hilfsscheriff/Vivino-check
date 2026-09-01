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
    colour_from_text,
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

#: So viele eigenständige Namensbestandteile braucht der Händlername mindestens.
MIN_IDENTITY_TOKENS = 2

#: Ein einzelnes Wort genügt, wenn es lang genug ist, um kaum zu kollidieren
#: ("Domherrenwein" ja, "Montagne" nein).
STRONG_TOKEN_LENGTH = 10

#: Ab so vielen eigenständigen Bestandteilen im Händlernamen gilt ein Treffer, bei dem
#: die Quelle einen Konzern- oder Gutsnamen davorstellt, als ``fuzzy`` statt als
#: Zweitwein-Veto — siehe :func:`_leading_cuvee_veto`.
SPECIFIC_ENOUGH_FOR_PARENT_NAME = 3


@dataclass
class _Prepared:
    raw: str
    tokens: list[str]
    token_set: set[str]
    vintage: int | None
    seq: list[str]           # inkl. Betriebsformen, für die Zweitwein-Erkennung
    alias_tokens: set[str]   # nur aus der Klammer, siehe :attr:`known`

    @property
    def joined(self) -> str:
        return " ".join(self.tokens)

    @property
    def known(self) -> set[str]:
        """Alle Wörter, die dieser Name **kennt** — die eigenen und die der Klammer.

        Der Unterschied zu :attr:`token_set` ist die ganze Asymmetrie des
        Klammer-Zusatzes, und beide Richtungen sind nötig:

        * Was Mövenpick nur in der Adresse führt, hängen wir in Klammern an
          („Toscana IGT 2023 Livrone **(Poggio Tesoro)**"). Von der Quelle *verlangen*
          dürfen wir es nicht — sonst rechnen wir ihr als fehlend an, was wir selbst
          ergänzt haben. Dafür ist :attr:`token_set` da, das die Klammer nicht kennt:
          Abdeckung, Anker und Identitätsvergleich laufen weiter darüber.
        * Umgekehrt ist der Produzent aber sehr wohl ein Wort, das wir kennen. Steht er
          in der Quelle, ist er kein *fremdes* Wort. Vor dieser Unterscheidung fiel
          „Poggio Al Tesoro Livrone" durch: nach dem Streichen blieb uns „livrone",
          Vivino trug „poggio tesoro livrone" — zwei Wörter, die unser Name scheinbar
          nicht kannte, und der richtige Treffer galt als anderer Wein.

        Faustregel für jede Stelle unten: fragt sie „kennt der Händler dieses Wort der
        Quelle?", dann :attr:`known`. Fragt sie „nennt die Quelle dieses Wort des
        Händlers?", dann :attr:`token_set`.
        """
        return self.token_set | self.alias_tokens

    @property
    def joined_known(self) -> str:
        return " ".join(self.tokens + sorted(self.alias_tokens))


def prepare(name: str, vintage: int | None = None) -> _Prepared:
    toks = tokenize(name)
    return _Prepared(
        raw=name,
        tokens=toks,
        token_set=set(toks),
        vintage=vintage if vintage is not None else extract_vintage(name),
        seq=tokenize_keep_producer(name),
        alias_tokens=set(tokenize(name, keep_alias=True)) - set(toks),
    )


def _ratios(a: str, b: str) -> float:
    """Beste von drei Metriken. ``token_set_ratio`` verzeiht Wortreihenfolge und
    Teilmengen, ``token_sort_ratio`` bestraft fehlende Wörter stärker, ``WRatio``
    fängt Tippfehler."""
    return max(
        fuzz.token_set_ratio(a, b),
        fuzz.token_sort_ratio(a, b),
        fuzz.WRatio(a, b),
    )


def _similarity(a: _Prepared, b: _Prepared) -> float:
    """Ähnlichkeit der beiden Namen, die Klammer als zweite Lesart.

    Ohne sie verglich sich „livrone" mit „poggio tesoro livrone" — Score 64, unter
    jeder Schwelle, obwohl wir den Produzenten kennen und nur nicht mitgezählt haben.
    Bewusst als *Maximum* über beide Lesarten und nicht als Ersatz: die selbst
    ergänzten Wörter dürfen einen Treffer stützen, aber nie einen kosten, wenn die
    Quelle den Produzenten gar nicht führt.
    """
    if not a.tokens or not b.tokens:
        return 0.0
    score = _ratios(a.joined, b.joined)
    if a.alias_tokens:
        score = max(score, _ratios(a.joined_known, b.joined))
    return score


#: Die Standard-Dosage. Praktisch jeder Champagner und Schaumwein ist Brut; Vivino
#: schreibt es aus, Händler oft nicht. Einseitig fehlendes "Brut" ist darum keine
#: Unterscheidung — „Ruinart Blanc de Blancs" gegen „Ruinart Blanc de Blancs **Brut**
#: Champagne" hatte Score 100 und fiel trotzdem durch. Ein *Widerspruch* zählt weiter:
#: steht auf einer Seite "Demi-Sec" oder "Extra Dry", ist es ein anderer Wein, denn
#: diese Angaben schreibt niemand versehentlich weg.
_DEFAULT_DOSAGE = frozenset({"brut"})


#: „Vintage" wird **nicht** nachsichtig behandelt, in keiner Richtung.
#:
#: Hier stand eine Ausnahme: steht „Vintage" nur beim Händler und führt die Quelle
#: einen Jahrgang, sollte nicht gesperrt werden. Gedacht war sie für „Vintage Brut
#: 2015 Champagne Blanc de Blancs (Pol Roger)" gegen „Pol Roger Blanc de Blancs
#: Champagne 2015" — dort beschreibt das Wort wirklich nur den Jahrgang, und zwei
#: solche Champagner verloren ihre 4.3.
#:
#: Sie riss aber genau den Fehler wieder auf, gegen den die Sperre gebaut wurde, nur
#: spiegelbildlich: „Kopke Vintage Porto 2016" gegen „Kopke Porto 2016" wurde zum
#: exakten Treffer, ebenso Warre's, Quinta do Noval, Taylor's und „Piper-Heidsieck
#: Vintage Brut 2012" gegen den Standard-Brut. Ein deklarierter Vintage-Port kostet
#: ein Mehrfaches seines jahrgangslosen Geschwisters — er darf dessen Note nicht
#: erben.
#:
#: Paarweise ist der Unterschied nicht zu erkennen: „Pol Roger Blanc de Blancs
#: Champagne 2015" und „Kopke Porto 2016" haben dieselbe Bauform (Wein plus Jahr).
#: Was sie trennt, ist Weltwissen — dass Pol Rogers Blanc de Blancs nur als
#: Jahrgangswein existiert. Solange das nicht im Namen steht, gilt die Regel des
#: Projekts: zwei Lücken sind billiger als eine falsche Note.


#: In Saint-Émilion ist „Grand Cru" die **Appellation**, nicht die Stufe darüber.
#:
#: „Saint-Émilion Grand Cru" ist der Name der Herkunft, und „Premier Grand Cru Classé"
#: die Klassifikation, die Vivino in Klammern anhängt. Händler lassen beides weg:
#: Aligro schreibt „St-Emilion Château Pavie AOC 2016", Vivino „Château Pavie
#: Saint-Émilion Grand Cru (Premier Grand Cru Classé)". Die Stufenregel sah darin drei
#: einseitige Wörter und lehnte den richtigen Wein ab — der CHF 400 teure Pavie stand
#: mit dem Produzenten-Durchschnitt 4.5 da, während seine eigene 4.6 aus 466
#: Bewertungen bei Vivino steht.
#:
#: In Burgund bleibt die Regel scharf, und das ist der Punkt: dort trennen „Grand Cru"
#: und „Premier Cru" tatsächlich verschiedene Weine desselben Guts. Die Ausnahme hängt
#: darum an der Herkunft und nicht an den Wörtern. Gemessen an allen gespeicherten
#: Zuordnungen betrifft sie vier Weine, alle in Saint-Émilion, und keinen einzigen
#: Cru-Fall anderswo.
_EMILION = frozenset({"emilion"})
_EMILION_STUFEN = frozenset({"grand", "cru", "premier", "classe", "classé"})


def _qualifier_veto(retailer: _Prepared, source: _Prepared) -> str | None:
    """Qualitätsstufen müssen auf beiden Seiten gleich sein."""
    r_q = discriminating_tokens(retailer.tokens)
    s_q = discriminating_tokens(source.tokens)
    if (retailer.token_set | source.token_set) & _EMILION:
        r_q = r_q - _EMILION_STUFEN
        s_q = s_q - _EMILION_STUFEN
    only_source = s_q - r_q
    only_retailer = r_q - s_q
    # Die Standard-Dosage darf einseitig fehlen — aber nur, wenn die andere Seite
    # keine abweichende Dosage nennt.
    andere_dosage = (r_q | s_q) & {"sec", "demi", "extra", "dolce", "doux"}
    if not andere_dosage:
        only_source -= _DEFAULT_DOSAGE
        only_retailer -= _DEFAULT_DOSAGE
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
    # "Rotwein"/"Weisswein" sind Rechtsbegriffe und darum keine Tokens mehr. Für die
    # Suchabfrage ist das richtig, hier wäre es ein Verlust: der Händler schreibt die
    # Farbe fast immer genau so an.
    for prep, bucket in ((retailer, r_c), (source, s_c)):
        if not bucket:
            g = colour_from_text(prep.raw)
            if g:
                bucket.add(g)
    if r_c and s_c and not (r_c & s_c):
        return f"Farbe widersprüchlich ({'/'.join(sorted(r_c))} vs. {'/'.join(sorted(s_c))})"
    return None



def _distinctive_anchor_veto(retailer: _Prepared, source: _Prepared) -> str | None:
    """Zwei Weine brauchen mindestens ein gemeinsames unterscheidendes Wort.

    „Rioja Imperial Cune Reserva" bekam die 4.2 aus 36'233 Bewertungen von einem
    Eintrag namens schlicht **„Rioja Reserva"** — Score 100, weil nach Abzug von
    Herkunft und Qualitätsstufe auf beiden Seiten fast dasselbe übrig blieb. Nur trägt
    der Fundname überhaupt kein unterscheidendes Wort: er kann per Konstruktion nicht
    dieser bestimmte Wein sein, sondern ist ein Sammeleintrag.
    """
    r_dist = {t for t in retailer.token_set if is_distinctive(t)}
    s_dist = {t for t in source.token_set if is_distinctive(t)}
    if r_dist and not (r_dist & s_dist):
        return (
            f"kein gemeinsames unterscheidendes Wort — {_pretty(r_dist)} fehlt in der "
            f"Quelle" + (f", die {_pretty(s_dist)} führt" if s_dist else ", die keines führt")
        )
    return None


def _rival_producer_veto(retailer: _Prepared, source: _Prepared) -> str | None:
    """Beide Seiten tragen ein eigenes unterscheidendes Wort, das die andere nicht kennt.

    „Gevrey-Chambertin **Faiveley**" gegen „**Regnard** Gevrey-Chambertin Rouge": die
    Appellation ist identisch, der Produzent ein anderer. Gemeinsame Wörter gibt es
    genug (gevrey, chambertin), darum greift die Ankerregel oben nicht — und der Score
    lag bei 86.

    Einseitige Zusätze bleiben erlaubt und werden anderswo behandelt: fehlt der
    Produzent nur in der Quelle, ist das die bekannte Unsicherheit (``fuzzy``); trägt
    nur die Quelle Zusätze, entscheidet die Abdeckung. Erst wenn **beide** Seiten
    etwas Eigenes mitbringen, sind es zwei verschiedene Weine.

    „Eigenes" der Quelle ist der Produzent aus unserer Klammer aber gerade nicht — er
    steht auf beiden Seiten, nur auf unserer in einem Feld, das nicht der Name ist.
    Ohne :attr:`_Prepared.known` traf es sonst auch den *richtigen* Kandidaten: bei
    „Bicento 53 Red Passion (Nativ)" führt der Händlername ein paar Appellationswörter
    mit, die Vivino nicht nennt, und schon galten beide Seiten als eigenständig.
    """
    r_only = {t for t in retailer.token_set - source.token_set if is_distinctive(t)}
    s_only = {t for t in source.token_set - retailer.known if is_distinctive(t)}
    if r_only and s_only:
        return (
            f"beide Seiten führen eigene Namen — {_pretty(r_only)} beim Händler, "
            f"{_pretty(s_only)} in der Quelle"
        )
    return None



def _prestige_prefix_veto(retailer: _Prepared, source: _Prepared) -> str | None:
    """Ein zusätzliches Wort **vor** dem Produzentennamen macht einen anderen Wein.

    „Ruinart Blanc de Blancs" gegen „**Dom** Ruinart Blanc de Blancs": derselbe Name,
    ein Wort davor — und ein Vielfaches des Preises. Champagne führt diese Bauform
    reihenweise (Dom Ruinart, Dom Pérignon, Cuvée Sir Winston Churchill), Bordeaux
    ebenso (Château Mouton Rothschild gegen Mouton Cadet).

    Die Abdeckung hilft hier nicht: der Händlername ist *vollständig* in der Quelle
    enthalten, die Ähnlichkeit entsprechend hoch. Genau darum braucht es die
    Positionsregel — nicht was fehlt entscheidet, sondern wo das Zusätzliche steht.
    """
    r_seq, s_seq = retailer.tokens, source.tokens
    if not r_seq or not s_seq or len(s_seq) <= len(r_seq):
        return None
    erstes_r = r_seq[0]
    if erstes_r not in s_seq:
        return None
    pos = s_seq.index(erstes_r)
    # Genau **ein** Wort davor. Mehr ist keine Prestige-Cuvée, sondern der Produzent
    # mit seiner Produktlinie: „Provins Valais Les Grands Dignitaires Domherrenwein"
    # meint denselben Wein wie „Domherrenwein" und darf als ``fuzzy`` durchgehen.
    # Diese beiden Bauformen sind lexikalisch nur an der Länge zu unterscheiden.
    if pos != 1:
        return None
    davor = [t for t in s_seq[:pos] if is_distinctive(t) and t not in retailer.known]
    if davor:
        return (
            f"{_pretty(set(davor))} steht in der Quelle **vor** '{erstes_r.title()}' — "
            f"das ist eine eigene, meist deutlich teurere Cuvée"
        )
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

    Gefragt wird hier durchweg „kennt der Händler dieses Wort?", darum
    :attr:`_Prepared.known` und nicht ``token_set`` — siehe die Begründung dort. Das
    wirkt in beide Richtungen: der selbst ergänzte Produzent zählt nicht mehr als
    fremd, aber er verschiebt auch den ersten Treffer nach vorn, und damit fällt der
    Rest der Quell-Bezeichnung erst recht unter diese Prüfung.

    Returns:
        ``(Veto-Grund oder None, tolerierte Zusatzwörter)``
    """
    first_hit = next(
        (i for i, tok in enumerate(source.tokens) if tok in retailer.known), None
    )
    if first_hit is None:
        return None, []
    # In Saint-Émilion sind „Grand Cru" und „Premier Grand Cru Classé" Herkunft und
    # Klassifikation, nicht ein eigener Wein — dieselbe Ausnahme wie in
    # :func:`_qualifier_veto`, siehe die Begründung dort. Beide Regeln nehmen
    # Regionswörter aus; für diese gilt es nur unter dieser Herkunft.
    emilion = bool((retailer.token_set | source.token_set) & _EMILION)
    suspects = [
        tok
        for tok in source.tokens[first_hit:]
        if tok not in retailer.known
        and tok not in REGION_HINTS
        and tok not in COLOUR_TOKENS
        and not (emilion and tok in _EMILION_STUFEN)
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
        and t not in retailer.known
        and t not in REGION_HINTS
        and t not in COLOUR_TOKENS
        and len(t) > 2
    ]
    if not leading or _looks_like_parent_company(retailer, source):
        return None

    return (
        f"{_pretty(set(leading))} steht vor der Betriebsform in der Quell-Bezeichnung "
        f"— eigener Cuvée-Name (Zweitwein-Muster)"
    )


def _looks_like_parent_company(retailer: _Prepared, source: _Prepared) -> bool:
    """Ist das führende Fremdwort der Quelle eher Konzern- als Cuvée-Name?

    ``Il Bruciato Bolgheri DOC Tenuta Guado al Tasso`` gegen ``Antinori Tenuta Guado
    al Tasso Il Bruciato Bolgheri`` ist derselbe Wein — "Antinori" ist bloss das Haus.
    ``Château Margaux`` gegen ``Pavillon Rouge du Château Margaux`` ist es nicht.

    Der Unterschied ist die Spezifität des Händlernamens: im ersten Fall nennt er vier
    eigenständige Bestandteile (Bruciato, Guado, Tasso, …) und wird von der Quelle
    vollständig abgedeckt, im zweiten einen einzigen. Wer den Cuvée-Namen schon selbst
    führt, bekommt nicht den falschen Wein zugeordnet.
    """
    covered = all(t in source.token_set for t in retailer.token_set)
    identity = [t for t in retailer.token_set if is_distinctive(t)]
    return covered and len(identity) >= SPECIFIC_ENOUGH_FOR_PARENT_NAME


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
        and t not in retailer.known
        and t not in REGION_HINTS
        and t not in COLOUR_TOKENS
        and len(t) > 2
    ]
    if leading and not _looks_like_parent_company(retailer, source):
        return (
            f"{_pretty(set(leading))} steht in der Quelle vor dem Produzentennamen "
            f"'{anchor.capitalize()}' — eigener Cuvée-Name (Zweitwein-Muster)"
        )
    return None


def _uncovered_producer_words(retailer: _Prepared, source: _Prepared) -> list[str]:
    """Nennt die Quelle den Betrieb, den der Händlername angibt?

    Heisst ein Weingut nach einer Lage — „Caves des Coteaux", „Cave de la Côte" —,
    dann verschwindet es aus den Tokens: ``caves`` ist ein Betriebswort und fliegt
    beim Tokenisieren, ``coteaux`` steht als Appellation in ``REGION_HINTS`` und gilt
    darum nicht als unterscheidend. Über Vokabular allein ist so ein Produzent nicht
    von der Lage zu trennen.

    Darum hier über ``seq``, das die Betriebswörter behält: Trägt der Händlername ein
    Betriebswort, muss mindestens eines der Wörter danach auch in der Quelle stehen.
    Sonst bleibt der Treffer unsicher — „Oeil de Perdrix Rosé" ist eben nicht
    „Oeil de Perdrix Rosé **von Caves des Coteaux**".

    Rückgabe: die ungedeckten Wörter des Betriebsnamens. Leere Liste heisst „gedeckt"
    — auch dann, wenn der Händlername gar kein Betriebswort trägt.
    """
    positions = [i for i, tok in enumerate(retailer.seq) if tok in PRODUCER_WORDS]
    if not positions:
        return []
    known = set(source.seq) | source.token_set
    missing: list[str] = []
    for start in positions:
        following = [
            tok for tok in retailer.seq[start + 1:]
            if tok not in PRODUCER_WORDS and len(tok) > 2
        ]
        # Nichts hinter dem Betriebswort ("… Weingut") lässt sich nicht prüfen.
        if not following:
            continue
        if any(tok in known for tok in following):
            return []
        missing.extend(tok for tok in following if tok not in known)
    return missing


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
    # Abdeckung über die **unterscheidenden** Wörter. Händlernamen tragen Region,
    # Land und Farbe mit, Vivino nennt sie oft nicht — jedes solche Wort drückte die
    # Abdeckung und liess einen richtigen Treffer als Zweitwein-Verdacht durchfallen.
    #
    # „Insoglio del Cinghiale Toscana IGP Tenuta di Biserno" gegen „Biserno Campo di
    # Sasso Insoglio del Cinghiale": alle drei unterscheidenden Wörter des Händlers
    # stecken in der Quelle, es fehlte nur „Toscana" — 75 % statt 100 %, und der Wein
    # fiel durch. „Campo di Sasso" ist Bisernos zweites Gut, kein anderer Wein.
    r_dist = {t for t in r.token_set if is_distinctive(t)}
    if r_dist:
        coverage = len(shared & r_dist) / len(r_dist)
    else:
        coverage = len(shared) / len(r.token_set) if r.token_set else 0.0

    foreign_veto, tolerated_extras = _foreign_token_analysis(r, s, coverage)

    # -- Vetos zuerst. Ein hoher Score darf sie nicht überstimmen. ------------
    vetos = (
        _qualifier_veto(r, s),
        _colour_veto(r, s),
        _distinctive_anchor_veto(r, s),
        _rival_producer_veto(r, s),
        _prestige_prefix_veto(r, s),
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

    # -- Händlername zu unspezifisch? --------------------------------------
    # "Montagne Vin Rouge" ist ein Fassweinname: nach Abzug von "Vin" (rechtliche
    # Bezeichnung) und "Rouge" (Farbe) bleibt ein einziges, dazu noch häufiges Wort.
    # Damit liess sich der Wein an "Marsannay 'La Montagne' Rouge" hängen — ein
    # Burgunder mit 382 Bewertungen. Ein einzelnes kurzes Wort trägt zu wenig
    # Identität; ein langer Markenname wie "Domherrenwein" dagegen kollidiert kaum.
    #
    # Ob die Quelle „reicher" ist, entscheidet sich an ``known``: „Toscana IGT 2023
    # Livrone (Poggio Tesoro)" bringt für sich genommen nur ein einziges
    # unterscheidendes Wort mit, und Vivinos „Poggio Al Tesoro Livrone" sah damit aus
    # wie ein Eintrag mit zwei zusätzlichen Namensbestandteilen. Es sind aber genau
    # die Wörter, die wir selbst angehängt haben — die Quelle bringt nichts mit, was
    # wir nicht schon wüssten.
    # Unter der Herkunft Saint-Émilion tragen „Grand Cru" und „Premier Grand Cru
    # Classé" auf keiner der beiden Seiten Identität — sie sind Appellation und
    # Klassifikation, siehe die Begründung bei :data:`_EMILION`. Ohne diesen Abzug
    # feuert die Regel auf einen Scheinunterschied: „St-Emilion Château Pavie AOC"
    # und „Château Pavie Saint-Émilion Grand Cru (Premier Grand Cru Classé)" sagen
    # dasselbe, und die Quelle brachte doch angeblich „Classé" zusätzlich mit.
    stufen = _EMILION_STUFEN if (r.token_set | s.token_set) & _EMILION else frozenset()
    r_identity = [t for t in r.token_set if is_distinctive(t) and t not in stufen]
    s_identity = [t for t in s.token_set if is_distinctive(t) and t not in stufen]
    unexplained_source = [t for t in s_identity if t not in r.known]
    if (
        len(r_identity) < MIN_IDENTITY_TOKENS
        and unexplained_source                      # nur wenn die Quelle reicher ist
        and not any(len(t) >= STRONG_TOKEN_LENGTH for t in anchors)
    ):
        # "Argiano Rosso di Montalcino" gegen denselben Namen ist unproblematisch —
        # da gibt es nichts zu verwechseln. Kritisch ist erst, wenn die Quelle einen
        # eigenen Namensbestandteil mitbringt, den der Händler nicht nennt.
        return MatchDecision(
            matched=False,
            confidence=MatchConfidence.NONE,
            score=score,
            reason=(
                "Händlername zu unspezifisch ("
                + (
                    f"nur {_pretty(set(r_identity))}"
                    if r_identity
                    else "kein eigenständiger Namensbestandteil"
                )
                + f"), Quelle nennt zusätzlich {_pretty(set(unexplained_source))}"
                " — nicht eindeutig zuordenbar"
            ),
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
    # Händlernamen tragen Region, Land, Farbe und Flaschengrösse mit: Mövenpick
    # führt „Mendoza 2021 Chardonnay Alta Angelica Zapata", Coop „Rioja DOCa
    # Crianza Bodegas Izadi (2022) – Rotwein, Spanien (0.75l)". Vivino nennt nur
    # den Wein. Diese Beiwörter drückten Score und Abdeckung und liessen damit
    # *richtige* Treffer als „unbestätigt" durchgehen — bei 39 % der bewerteten
    # Weine. Für die Konfidenz zählt darum zusätzlich der Vergleich, der nur die
    # unterscheidenden Bestandteile ansieht.
    #
    # Bewusst nur die Konfidenz, nicht die Match-Entscheidung: welcher Kandidat
    # gewinnt, bleibt unverändert. Und ``identity_complete`` verlangt *jeden*
    # unterscheidenden Bestandteil — fehlt der Produzent („Oeil de Perdrix Rosé"
    # ohne „Caves des Coteaux", „Bardolino Classico" ohne „Zeni"), bleibt es fuzzy.
    r_identity_tokens = [t for t in r.tokens if is_distinctive(t)]
    s_identity_tokens = [t for t in s.tokens if is_distinctive(t)]
    identity_complete = bool(r_identity_tokens) and not (
        set(r_identity_tokens) - set(s_identity_tokens)
    )
    if r_identity_tokens and s_identity_tokens:
        r_id_joined, s_id_joined = " ".join(r_identity_tokens), " ".join(s_identity_tokens)
        identity_score = max(
            fuzz.token_set_ratio(r_id_joined, s_id_joined),
            fuzz.token_sort_ratio(r_id_joined, s_id_joined),
        )
    else:
        identity_score = 0.0

    # Auch der Weg über den ganzen Namen verlangt, dass kein unterscheidendes Wort
    # des Händlers fehlt. Seit die Abdeckung nur noch unterscheidende Wörter zählt,
    # steigt sie bei kurzen Namen schnell über die Schwelle — „Oeil de Perdrix Rosé
    # Caves des Coteaux" gegen ein blosses „Oeil de Perdrix Rosé" käme sonst auf
    # exact, obwohl der Produzent fehlt und diesen Rosé-Typ viele Häuser keltern.
    whole_name_strong = (
        score >= STRONG_SCORE and coverage >= STRONG_COVERAGE and identity_complete
    )
    # Die unterscheidenden Bestandteile stimmen vollständig und auch für sich
    # genommen deutlich — Beiwörter dürfen das nicht mehr verhindern.
    missing_producer = _uncovered_producer_words(r, s)
    identity_strong = (
        identity_complete
        and identity_score >= STRONG_SCORE
        and not missing_producer
    )
    is_strong = (
        (whole_name_strong or identity_strong)
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
        base = f"ähnlich (Score {score:.0f}, Abdeckung {coverage:.0%})"
        missing = set(r_identity_tokens) - set(s_identity_tokens)
        if missing:
            reason = f"{base}, Quelle nennt {_pretty(missing)} nicht"
        elif missing_producer:
            reason = f"{base}, Quelle nennt den Betrieb {_pretty(set(missing_producer))} nicht"
        else:
            reason = base
    elif vintage_match and source_has_vintage_rating:
        conf = MatchConfidence.EXACT
        reason = (
            f"Name und Jahrgang {r.vintage} bestätigt"
            if whole_name_strong
            else f"Jahrgang {r.vintage} und alle unterscheidenden Bestandteile "
                 f"bestätigt (Beiwörter wie Region oder Farbe weichen ab)"
        )
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
        coverage=coverage,
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

    # Trägt der Händlername über den Produzenten hinaus ein eigenständiges Wort, dann
    # benennt es eine bestimmte Linie und der Produzenten-Durchschnitt gilt dafür
    # nicht. "Mouton Cadet" von Baron Philippe de Rothschild bekam so die 4.6 von
    # Château Mouton Rothschild — CHF 9.95 mit der Note eines Premier Grand Cru.
    # Generische Zusätze sind unschädlich: "Col del Sol Brut Prosecco Superiore
    # Valdobbiadene" ist gegenüber dem Produzenten "Col del Sol" nur um Schaumwein-
    # Dosage und Herkunft erweitert.
    extras = [t for t in r.token_set if t not in w.token_set and is_distinctive(t)]
    if extras:
        return MatchDecision(
            matched=False,
            confidence=MatchConfidence.NONE,
            score=score,
            reason=(
                f"Produzent '{winery_name}' erkannt, aber {_pretty(set(extras))} benennt "
                f"eine bestimmte Linie — der Produzenten-Durchschnitt gilt dafür nicht"
            ),
            source_name=winery_name,
        )

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


#: Rangfolge der Konfidenzstufen, wie sie in :class:`MatchConfidence` deklariert
#: sind: sicher vor unsicher. Kleiner ist besser.
_KONFIDENZ_RANG = {stufe: i for i, stufe in enumerate(MatchConfidence)}


def _konfidenz_rang(stufe: MatchConfidence) -> int:
    """Wie vertrauenswürdig ist diese Stufe? Kleiner ist besser.

    Klingt nach einer Formalität, war aber ein handfester Fehler: sortiert wurde
    vorher nach ``confidence.value``, also alphabetisch über den Text der Stufe. Und
    alphabetisch steht „fuzzy" vor „wine_level".

    Bei gleichem Ähnlichkeitswert entschied damit der Anfangsbuchstabe. Genau so
    verlor „Rocca di Frassinello la Rocca" (CHF 37.50) gegen „Rocca di Frassinello
    Baffonero" (rund CHF 200): beide Kandidaten erreichten exakt 100 Punkte, der
    richtige Wein war als ``wine_level`` eingestuft, der falsche als ``fuzzy`` — und
    ``f`` kommt vor ``w``. Der Wein bekam die Note 4.5 des Spitzenweins.

    ``fuzzy`` heisst „ähnlich genug, aber die Quelle trägt Wörter, die der Händler
    nicht nennt" — also *vielleicht ein anderer Wein*. ``wine_level`` heisst „dieser
    Wein, nur ein anderer Jahrgang". Das zweite ist die sicherere Aussage und gehört
    nach vorn. Die Deklarationsreihenfolge im Modell sagt das seit jeher; nur gelesen
    hat sie hier niemand.
    """
    return _KONFIDENZ_RANG.get(stufe, len(_KONFIDENZ_RANG))


def _sortierung(d: MatchDecision) -> tuple[float, float, int]:
    """Sortierschlüssel unter den passenden Kandidaten. Kleiner ist besser.

    **Abdeckung vor Ähnlichkeit**, und das ist der Kern. Der Ähnlichkeitswert kommt
    von ``token_set_ratio``, und der belohnt eine Teilmenge mit der vollen Punktzahl:
    ein Kandidat, der ein unterscheidendes Wort des Händlers einfach *weglässt*,
    bekommt 100.

    Gemessen an einem echten Fall — Händler: „Rioja DOC **Calados** del Puntido 2015
    Viñedos de Paganos"::

        Viñedos de Páganos El Puntido ....................  Score 100.0, Abdeckung 80 %
        Viñedos de Páganos Calados del Puntido Tempranillo   Score  91.2, Abdeckung 100 %

    Der richtige Wein verlor, weil er das Wort „Tempranillo" mitbringt; der falsche
    gewann, weil ihm „Calados" fehlt — und Fehlendes kostet bei diesem Mass nichts.
    Das sind zwei verschiedene Weine desselben Guts, El Puntido mit 12'065
    Bewertungen der weit bekanntere. Genau so wandert eine Note zum falschen Wein.

    Die Abdeckung misst das Umgekehrte: welcher Anteil der unterscheidenden Wörter
    *des Händlers* im Kandidaten vorkommt. Sie wurde immer schon berechnet und für die
    Vetos benutzt, nur nicht für die Auswahl.

    Dann erst die Ähnlichkeit, und zuletzt die Konfidenzstufe in ihrer deklarierten
    Reihenfolge — siehe :func:`_konfidenz_rang`.
    """
    return (-round(d.coverage, 3), -d.score, _konfidenz_rang(d.confidence))


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

    # Abdeckung zuerst, dann Ähnlichkeit, dann Sicherheit — siehe :func:`_sortierung`.
    hits.sort(key=lambda h: _sortierung(h.decision))
    ambiguous = False
    if len(hits) >= 2:
        top, second = hits[0].decision, hits[1].decision
        # Gleicher Wein in mehreren Jahrgängen ist nicht uneindeutig.
        same_wine = _similarity(prepare(top.source_name or ""), prepare(second.source_name or "")) >= 95
        if not same_wine and (top.score - second.score) < AMBIGUITY_MARGIN:
            ambiguous = True
    return hits, ambiguous

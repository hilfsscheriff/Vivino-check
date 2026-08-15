"""Preis-Leistung — was „lohnt sich" heisst, an genau einer Stelle.

Warum dieses Modul existiert
----------------------------
Die Kennzahl hatte zwei Besitzer, und beide hiessen dem Nutzer gegenüber
„Preis-Leistung":

* :func:`winecheck.aggregate.compute_scores` setzt ``WineRow.value_score`` — eine
  Rangposition innerhalb der Preisklasse, Skala 0 bis 100. Sie treibt die
  **PDF-Rangliste**, die CSV-Spalte und die Reihenfolge in ``diff.md``.
* die Regression hier setzt ``valueScore`` — den Rest der Note über dem Preisniveau,
  Skala etwa ±0.5, gruppiert nach ``(typ, sorte)``. Sie treibt **nur die Webseite**.

Das wurde teuer, als Spec §6 verlangte, die Gruppierung von der Sorte auf den Stil-Typ
umzustellen: umgesetzt wurde es hier, und die PDF-Rangliste blieb bei der
unkorrigierten Rechnung — also bei genau der Verzerrung, die die Spec beheben sollte.
Derselbe Wein trug damit zwei „Preis-Leistung"-Werte, je nach Ausgabekanal.

Die Rechnung liegt jetzt hier, und beide Kanäle holen sie von hier. Was sie *anzeigen*,
bleibt vorerst getrennt: Spec §6 verlangt ausdrücklich Parallelbetrieb, „bis die
Verteilung geprüft ist". Der Unterschied zur alten Zahl steht darum in der CSV
nebeneinander, statt still ersetzt zu werden — siehe
:func:`winecheck.aggregate.compute_scores`.

Was die Zahl bedeutet
---------------------
„Gut und günstig" ist die Frage, für die es die Seite gibt — im Diagramm ist es „oben
links". Als Zahl: die Note gegen das für diesen Preis übliche Niveau, und der Rest je
Wein. Der Wert heisst damit „so viel besser als üblich für dieses Geld" und nicht
„billig". Ein Ruinart für CHF 89.50 kann so vor einem mittelmässigen Wein für CHF 8
liegen.
"""

from __future__ import annotations

import math
import statistics
from typing import Any

from .stiltyp import UNBEKANNT


#: So viele Weine braucht ein Lauf, damit sich ein Preisniveau schätzen lässt.
VALUE_MIN_SAMPLE = 12

#: Wie stark der Preis gegen die Note zählt. **Gesetzt, nicht gemessen** — das ist
#: der einzige Wert im ganzen Bericht, der nicht aus Daten stammt.
#:
#: Übersetzt heisst er: ein Wein mit 0.1 Vivino-Punkten mehr darf rund 40 % teurer
#: sein und gilt noch als gleich gut (10^(0.1/0.70) ≈ 1.39).
#:
#: Gemessen ergäbe sich 0.34 über alle Weine, 0.48 bei den Champagnern — dort wäre
#: ein Zehntelpunkt fast den **doppelten** Preis wert. Das beschreibt getreu, wie
#: der Markt bepreist, taugt aber nicht als Kaufempfehlung: die Ursache liegt bei
#: Vivino, dessen Noten sich zwischen 3.5 und 4.6 drängen, während die Preise um das
#: Hundertfache streuen. Ein Zehntelpunkt ist dort viel, und die Regression rechnet
#: ihn entsprechend teuer.
#:
#: 0.70 statt der Kippstelle 0.55, an der zwei konkrete Champagner exakt gleichauf
#: lägen: ein Wert direkt am Umschlagpunkt ist zufällig gewählt, dieser lässt Luft.
#: Ein wirklich besserer Wein verteidigt damit weiterhin seine Preisklasse.
#:
#: Wer den Bericht liest, muss das wissen — auf der Seite steht es unter der
#: Tabelle. Eine gesetzte Zahl als gemessene auszugeben wäre das Schlimmste von
#: beidem.
PREIS_GEWICHT = 0.70

#: Ab so vielen Vivino-Bewertungen zählt die Abweichung vom Preisniveau voll. Darunter
#: wird sie anteilig gedämpft: bei einer Streuung von rund 0.16 Notenpunkten führt sonst
#: ein Wein mit zwölf Bewertungen die Liste an, weil er zufällig gut wegkam.
VALUE_RATING_ANCHOR = 50

#: Wie stark die **Seltenheit** einer Note zählt, von 0 (gar nicht) bis 1 (allein).
#:
#: Vivino-Noten sind keine gleichmässige Skala. Im Bestand tragen 218 Weine eine 4.1
#: und nur 26 eine 4.5 — ein Zehntelpunkt am oberen Ende bedeutet also etwas ganz
#: anderes als in der Mitte. Linear gerechnet zählen beide gleich, und dann führt ein
#: 4.1er für CHF 6.50 die Liste an, obwohl 4.1 die häufigste Note überhaupt ist.
#:
#: Die Gegenrechnung wäre, allein die Seltenheit zu nehmen. Das schiesst über: der
#: Sprung von 4.4 auf 4.5 wird dabei so gross, dass der Preis daneben nicht mehr ins
#: Gewicht fällt — bei den Champagnern besetzten dann wieder die Flaschen für CHF 70
#: bis 90 die Spitze allein, und zwar bei jedem Preisgewicht.
#:
#: 0.5 ist die Mitte, und sie trifft, was gemeint ist: ein 4.1er für sechs Franken
#: bleibt gut platziert, führt die Liste aber nicht mehr an.
SELTENHEIT_ANTEIL = 0.5

def _wirksame_note(wines: list[dict[str, Any]]):
    """Baut die Umrechnung Note → wirksame Note für diesen Lauf.

    Die Seltenheit einer Note wird als ``-log10(Anteil der Weine, die so gut oder
    besser sind)`` gemessen — je exklusiver, desto grösser. Sie wird auf die
    Notenskala zurückgerechnet (gleicher Mittelwert, gleiche Streuung) und dann mit
    der rohen Note gemischt.

    Der Umweg über die Notenskala ist Absicht: die Zahl behält damit ihre Einheit,
    und die Aussage „0.1 Punkte rechtfertigen 40 % Aufpreis" gilt weiter. Rechnete
    man in Seltenheitseinheiten, stünde in der Spalte eine Zahl, die niemand mehr
    einordnen kann.

    Gemessen wird über den **ganzen** Lauf, nicht je Sorte: eine 4.5 ist selten,
    unabhängig davon, ob sie an einem Rotwein oder einem Champagner hängt.

    „Der ganze Lauf" heisst: dieselbe Menge, die auch in die Regression eingeht — Note
    *und* brauchbarer Preis. Der Preisfilter steht hier und nicht bei den Aufrufern,
    weil er genau dort auseinanderlief: die Seite übergab alle Weine, ``aggregate`` nur
    die mit Preis. Eine einzige zusätzliche Note verschiebt die Seltenheitskurve, und
    damit stand für jeden Wein eine andere Zahl in der CSV als auf der Seite. Wer die
    Menge bestimmen darf, muss eine Stelle sein.
    """
    # Auf ein Zehntel runden, bevor gezählt wird. Vivino liefert die Note als float32,
    # und damit sind 4.2 und 4.199999809265137 zwei verschiedene Zahlen. Der Vergleich
    # ``x >= r - 1e-9`` zählte sie als getrennte Notenstufen, und eine Stufe, die es nur
    # in der Zahlendarstellung gibt, macht eine Note seltener als sie ist: bis zu 0.083
    # wirksame Note geschenkt, nach der Preisformel rund 31 Prozent Preisvorteil.
    #
    # Ein Zehntel ist die Auflösung, in der Vivino Noten überhaupt ausweist — gerundet
    # wird also auf das, was die Quelle meint.
    noten = sorted(
        round(w["rating"], 1) for w in wines
        if w.get("rating") is not None and (w.get("price") or 0) > 0
    )
    n = len(noten)
    if n < VALUE_MIN_SAMPLE:
        return lambda r: r

    def seltenheit(r: float) -> float:
        r = round(r, 1)
        # bisect wäre schneller, aber n liegt bei rund tausend und die Funktion
        # läuft einmal je Wein — Klarheit geht hier vor.
        besser = sum(1 for x in noten if x >= r - 1e-9)
        return -math.log10(max(besser, 1) / n)

    roh = [seltenheit(r) for r in noten]
    streuung_note = statistics.pstdev(noten)
    streuung_roh = statistics.pstdev(roh)
    if streuung_roh <= 0 or streuung_note <= 0:
        return lambda r: r
    faktor = streuung_note / streuung_roh
    mitte_note = statistics.mean(noten)
    mitte_roh = statistics.mean(roh)

    def wirksam(r: float) -> float:
        auf_notenskala = mitte_note + (seltenheit(r) - mitte_roh) * faktor
        return (1 - SELTENHEIT_ANTEIL) * r + SELTENHEIT_ANTEIL * auf_notenskala

    return wirksam


def _add_value_scores(wines: list[dict[str, Any]]) -> None:
    """Rechnet je Quellenart getrennt — Schweizer Handel und Marktplatz.

    Beide Gruppen haben ein eigenes Preisniveau: der Marktplatz liefert aus dem
    Ausland, der Schweizer Handel nicht. Eine gemeinsame Regression legte über
    beide dieselbe Erwartungskurve und machte den systematischen Preisunterschied
    zu einer Aussage über die einzelnen Weine.
    """
    # Ein Wein, den auch ein Schweizer Händler führt, wird im Schweizer Preisniveau
    # gerechnet — dort ist er zu kaufen. Rein im Marktplatz geführte Weine bilden
    # die zweite Gruppe.
    # Einmal je Lauf über *alle* Weine: eine 4.5 ist selten, gleich an welcher
    # Sorte sie hängt.
    note = _wirksame_note(wines)

    marktplatz = [w for w in wines if w.get("marketplace") and not w.get("swiss")]
    handel = [w for w in wines if w.get("swiss") or not w.get("marketplace")]
    for gruppe in (handel, marktplatz):
        if gruppe:
            _je_typ(gruppe, "valueScore", note)

    # Zusätzlich eine Zahl über beide Welten hinweg. Sie wird gebraucht, sobald die
    # Seite Handel und Marktplatz gemeinsam zeigt — das ist die Standardansicht.
    # Ohne sie stünden in einer Liste zwei Zahlen nebeneinander, die aus getrennten
    # Regressionen stammen und schlicht nicht dasselbe messen: eine 0.3 aus der
    # Marktplatz-Gruppe hiesse "gut für einen Marktplatzwein", eine 0.3 aus dem
    # Handel "gut für einen Schweizer Ladenwein". Sortiert man danach, vergleicht
    # man Äpfel mit Birnen.
    _je_typ(wines, "valueScoreAll", note)


def _typ_gruppe(w: dict[str, Any]) -> str:
    """Der Gruppenschlüssel eines Weins. ``""`` heisst „kein Typ".

    ``unbekannt`` ist kein Typ, sondern das Eingeständnis, keinen zu kennen — die
    Unterscheidung gehört hierher und nicht in die Aufrufer. Genau daran ist sie
    nämlich auseinandergelaufen: die Seite gibt den Rohwert ``"unbekannt"`` weiter,
    :func:`winecheck.aggregate._wert_scores` bildete ihn vorher selbst auf ``""`` ab.
    Damit rechnete die Seite für 521 Weine eine eigene Kurve, die CSV für dieselben
    Weine die globale — 295 von 1010 Zahlen wichen ab, bis zu 0.132 auf einer Skala
    von rund ±0.5. Wieder zwei Zahlen unter einem Namen, nur eine Ebene tiefer.

    Die globale Kurve ist die richtige, und der Grund steht in :func:`_je_typ`: aus
    dem Fehlen einer Information keine Erwartung ableiten.
    """
    typ = w.get("typ") or ""
    return "" if typ == UNBEKANNT else typ


def _je_typ(wines: list[dict[str, Any]], feld: str, note) -> None:
    """Eine eigene Kurve je Stil-Typ, mit Rückfall über Sorte auf die ganze Gruppe.

    Vorher lief der Schnitt über die **Sorte** — Rotwein, Weisswein, Champagner. Der
    Grund dafür gilt weiter: Champagner hat ein anderes Preisniveau als Rotwein,
    Median CHF 43 gegen 23. Aber innerhalb von „Rotwein" steckt die grössere
    Verzerrung: Vivino-Noten sind Publikumsmittelwerte, und die fruchtsüsse Machart
    erreicht dort verlässlich 4.2 bis 4.4, während straffe Weine polarisieren. Wer
    einen Appassimento-Primitivo gegen einen Brunello normalisiert, weil beide
    „Rotwein" sind, misst die Machart und nicht den Wein.

    Der Typ ist der stärkere Schnitt und darum der erste. Die Sorte bleibt als
    zweite Ebene: sie trennt weiter, was sich preislich nicht vergleichen lässt.

    Drei Ebenen, jede mit derselben Mindestfallzahl:

    1. ``(typ, sorte)`` — der genaueste Schnitt, wo die Fallzahl ihn trägt.
    2. ``typ`` allein — wenn eine Sorte innerhalb eines Typs zu dünn besetzt ist.
    3. die ganze Gruppe — für alles Übrige, inklusive der Weine ohne Typ.

    Weine ohne Typ landen bewusst in Ebene 3 statt in einer eigenen Gruppe: „kein
    Typ" ist keine Machart, und eine Kurve darüber hiesse, aus dem Fehlen einer
    Information eine Erwartung abzuleiten.

    Gezählt wird, was in die Regression eingeht — Weine ohne Note oder ohne Preis
    tragen nichts bei und dürfen eine Gruppe nicht gross erscheinen lassen.
    """
    def brauchbar(gruppe: list[dict[str, Any]]) -> int:
        return sum(
            1 for w in gruppe if w.get("rating") is not None and (w.get("price") or 0) > 0
        )

    def teilen(gruppe: list[dict[str, Any]], schluessel) -> dict[Any, list[dict[str, Any]]]:
        out: dict[Any, list[dict[str, Any]]] = {}
        for w in gruppe:
            out.setdefault(schluessel(w), []).append(w)
        return out

    rest: list[dict[str, Any]] = []
    for typ, mit_typ in teilen(wines, _typ_gruppe).items():
        if not typ:
            rest.extend(mit_typ)                      # ohne Typ: globale Kurve
            continue
        if brauchbar(mit_typ) < VALUE_MIN_SAMPLE:
            rest.extend(mit_typ)
            continue
        # Erst die gröbere Ebene für alle, dann die feinere für die Zellen, die sie
        # tragen. Die Reihenfolge ist der Trick: jeder Wein bekommt am Ende den
        # feinsten Wert, den seine Fallzahl hergibt, und keiner bleibt leer. Die
        # Bezugsmenge einer zu dünnen Zelle ist dabei der **ganze** Typ, nicht die
        # Sammlung der übrigen dünnen Zellen — drei Weisse gegen vier Rosés gerechnet
        # wäre keine Erwartung, sondern ein Zufall.
        _nach_sorte(mit_typ, feld, note, brauchbar, teilen)
    if rest:
        # Der Resttopf bekommt dieselbe zweite Ebene. Das fehlte, und es war der teuerste
        # Fehler dieser Rechnung: 38 Champagner mit einem Medianpreis von CHF 42.42 lagen
        # mit 30 Schaumweinen zu CHF 10.86 auf einer Kurve. Wer einen Champagner gegen
        # Prosecco normalisiert, weil man von beiden die Machart nicht kennt, misst den
        # Preisunterschied zweier Kategorien und nennt ihn Preis-Leistung.
        #
        # Messbar an der Spitze: Weine ohne Stil-Typ stellten 8.5 % der rankbaren Menge
        # und 32 % der ersten 25 Plätze — ausgerechnet die eine Gruppe ohne
        # Typkorrektur beherrschte die Liste, deren Rechtfertigung die Typkorrektur ist.
        #
        # Die Sorte trennt hier weiter, was sich preislich nicht vergleichen lässt — genau
        # der Grund, aus dem sie innerhalb der Typen die zweite Ebene ist. „Kein Typ"
        # bleibt dabei kein Typ: eine gemeinsame Kurve über alle typlosen Weine gibt es
        # weiterhin, sie wird nur dort verfeinert, wo eine Sorte die Fallzahl trägt.
        _nach_sorte(rest, feld, note, brauchbar, teilen)


def _nach_sorte(gruppe, feld, note, brauchbar, teilen) -> None:
    """Erst die gröbere Ebene für alle, dann die feinere für die Zellen, die sie tragen.

    Die Reihenfolge ist der Trick: jeder Wein bekommt am Ende den feinsten Wert, den seine
    Fallzahl hergibt, und keiner bleibt leer. Die Bezugsmenge einer zu dünnen Zelle ist
    dabei die **ganze** übergeordnete Gruppe, nicht die Sammlung der übrigen dünnen Zellen
    — drei Weisse gegen vier Rosés gerechnet wäre keine Erwartung, sondern ein Zufall.
    """
    _value_scores_einer_gruppe(gruppe, feld=feld, note=note)
    for sorte_gruppe in teilen(gruppe, lambda w: w.get("style") or "?").values():
        if brauchbar(sorte_gruppe) >= VALUE_MIN_SAMPLE:
            _value_scores_einer_gruppe(sorte_gruppe, feld=feld, note=note)
            _nach_region(sorte_gruppe, feld, note, brauchbar, teilen)


def _nach_region(gruppe, feld, note, brauchbar, teilen) -> None:
    """Vierte und feinste Ebene: die Anbauregion.

    „Ein Bordeaux für CHF 10 ist viel besser als ein Primitivo für CHF 10." Das
    stimmt, und die Rechnung wusste es nicht — sie verglich einen Wein mit allen
    anderen seiner Machart und Sorte, ohne zu fragen, was seine Herkunft
    normalerweise kostet. Ein günstiger Primitivo ist gewöhnlich, ein günstiger
    Bordeaux ist ein Fund.

    Eine eigene Ebene braucht es dafür, weil die Region etwas anderes trennt als Typ
    und Sorte. Zwei kräftige Rotweine können dieselbe Machart und dieselbe Farbe
    haben und trotzdem in ganz verschiedenen Preiswelten leben.

    **Gemessen, nicht gesetzt.** Der Schwerpunkt jeder Region kommt aus dem Lauf
    selbst — ``mean_x`` in :func:`_value_scores_einer_gruppe` ist genau das übliche
    Preisniveau dieser Herkunft, und der Rest je Wein sagt, wie weit er darüber oder
    darunter liegt. Die Preisspannen in :mod:`winecheck.region` sind Erfahrungswerte
    und dienen der Anzeige; in diese Zahl gehen sie **nicht** ein. Eine gesetzte Zahl
    still in eine Kennzahl zu rechnen wäre genau das, was dieses Projekt sonst
    ablehnt.

    Regionen ohne genug Weine im Lauf bekommen keine eigene Kurve und behalten den
    Wert der Sorten-Ebene — dieselbe Mechanik wie überall darüber. Weine ohne
    erkannte Region ebenso: aus dem Fehlen einer Information wird keine Erwartung
    abgeleitet.
    """
    for region_gruppe in teilen(gruppe, lambda w: w.get("region") or "").items():
        key, wines = region_gruppe
        if key and brauchbar(wines) >= VALUE_MIN_SAMPLE:
            _value_scores_einer_gruppe(wines, feld=feld, note=note)


def _value_scores_einer_gruppe(
    wines: list[dict[str, Any]], *, feld: str = "valueScore", note=None
) -> None:
    """Trägt in jeden Wein ein, wie weit seine Note über dem Preisniveau liegt.

    „Gut und günstig" ist die Frage, für die es die Seite gibt — im Diagramm ist es
    „oben links". Als Zahl: die Regression der Note auf ``log10(Preis)`` über den Lauf,
    und der Rest je Wein. Damit heisst der Wert „so viel besser als üblich für dieses
    Geld" und nicht „billig". Ein Ruinart für CHF 89.50 kann so vor einem mittelmässigen
    Wein für CHF 8 liegen.

    Der Preis geht logarithmisch ein, weil die Note es auch tut: über die Läufe bringt
    eine Verzehnfachung des Preises knapp einen halben Notenpunkt. Linear gerechnet
    würde die Spanne von CHF 4.60 bis 590 die ganze Rangfolge von den teuren Weinen
    her bestimmen.

    Gerechnet wird über den ganzen Lauf, nicht über die gefilterte Auswahl: sonst
    änderte ein Wein seinen Rang, je nachdem was sonst angezeigt wird.
    """
    sample = [
        w for w in wines
        if w.get("rating") is not None and (w.get("price") or 0) > 0
    ]
    if len(sample) < VALUE_MIN_SAMPLE:
        return
    xs = [math.log10(w["price"]) for w in sample]
    wirksam = note or (lambda r: r)
    ys = [wirksam(w["rating"]) for w in sample]
    n = len(xs)
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    spread = sum((x - mean_x) ** 2 for x in xs)
    if spread <= 0:
        # Alle zum selben Preis. Die Sicherung ist **kein** Schutz gegen eine Division
        # durch null: die Steigung wird gesetzt und nicht geschätzt, ``spread`` geht in die
        # Rechnung darunter gar nicht ein. Sie bleibt, weil eine Gruppe ohne
        # Preisunterschied auch keine Preis-Leistungs-Aussage trägt — jeder Wein bekäme
        # allein aus seiner Note eine Zahl, und die Spalte hiesse dann „Note", nicht
        # „Preis-Leistung". Wer die gesetzte Steigung je durch eine geschätzte ersetzt,
        # braucht die Zeile dann wirklich.
        return
    # Die Steigung wird **gesetzt**, nicht gemessen — siehe PREIS_GEWICHT. Der
    # Schwerpunkt der Wolke bleibt gemessen: die Gerade läuft weiterhin durch
    # (mean_x, mean_y), womit der Durchschnittswein einer Sorte bei null liegt und
    # die Zahl weiterhin "besser oder schlechter als üblich" heisst.
    for w in sample:
        expected = mean_y + PREIS_GEWICHT * (math.log10(w["price"]) - mean_x)
        count = w.get("ratingCount") or 0
        damping = count / (count + VALUE_RATING_ANCHOR)
        w[feld] = (wirksam(w["rating"]) - expected) * damping


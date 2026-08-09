"""Statische Webseite für GitHub Pages.

Eine einzige HTML-Datei mit **allen Daten inline**: kein CDN, keine externen
Schriften, keine Bilder von aussen. Das hat drei Gründe:

* Sie funktioniert per Doppelklick, in OneDrive und auf Pages gleichermassen.
* Sie funktioniert unterwegs ohne Netz, sobald sie einmal geladen ist — genau dann,
  wenn man am Tisch sitzt und schlechten Empfang hat.
* Besucher lösen keine Anfragen an Dritte aus. Wer die Seite mit Freunden teilt,
  verschickt nicht deren IP-Adressen an ein CDN.

Achse und Filter
----------------
Die y-Achse zeigt **nur die Vivino-Note in ihrer eigenen Skala 1–5**. Falstaff- und
andere Kritikerpunkte stehen im Tooltip und in der Tabelle, aber nicht auf der Achse:
zwei Bewertungsgrundlagen auf einer Achse sind nicht vergleichbar, auch normalisiert
nicht. Weine ohne Vivino-Note erscheinen darum nicht im Diagramm, wohl aber in der
Tabelle.

Gefiltert wird kombinierbar nach Lauf, Trinkreife, Sorte und Händler, dazu ein
Suchfeld über Name und Produzent.
"""

from __future__ import annotations

import html
import json
import math
import statistics
from collections import Counter
import re
import time
from pathlib import Path
from typing import Any

from ..names import STYLE_LABELS
from ..trinkreife import MATURITY, MATURITY_SHORT, SOURCE_NAME, SOURCE_PAGE
from .logo import SVG_MARK, schreibe_icons
from .formatting import chf, datetime_ch

#: Reihenfolge der Trinkreife-Filter: von „jetzt" nach „später".
MATURITY_FILTER_ORDER = ("*", "k", "m", "g", "-")

#: „Gut und günstig" ist eine feste Regel, kein Abstand zur Trendlinie: ab dieser
#: Note und bis zu diesem Preis. Nur dieser Bereich. Absolut zu rechnen ist der
#: schärfere Filter — „besser als üblich fürs Geld" trifft auch eine mittelmässige
#: Flasche für CHF 8.
#:
#: Note 4.3, nicht 4.2: eine 4.2 tragen 148 Weine im Bestand, eine 4.3 nur noch 71.
#: Wenn die Auszeichnung etwas heissen soll, muss sie selten genug sein — bei 4.2
#: bekäme sie fast jeder zweite günstige Wein, und dann sagt sie nichts mehr.
GOOD_RATING_MIN = 4.3
GOOD_PRICE_MAX = 20.0

#: Flächen, gegen die Farben geprüft werden (hell, dunkel).
_GROUND_LIGHT, _GROUND_DARK = "#faf9f7", "#141114"

#: Ab so vielen Vivino-Bewertungen zählt die Abweichung vom Preisniveau voll. Darunter
#: wird sie anteilig gedämpft: bei einer Streuung von rund 0.16 Notenpunkten führt sonst
#: ein Wein mit zwölf Bewertungen die Liste an, weil er zufällig gut wegkam.
VALUE_RATING_ANCHOR = 50

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
    """
    noten = sorted(w["rating"] for w in wines if w.get("rating") is not None)
    n = len(noten)
    if n < VALUE_MIN_SAMPLE:
        return lambda r: r

    def seltenheit(r: float) -> float:
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


#: Quellen, deren Weine ihre Bewertung mitbringen statt sie über einen
#: Namensabgleich zu finden. Aktuell nur Vivinos eigener Marktplatz.
#:
#: Diese Weine werden getrennt gerechnet und angezeigt. Der Grund ist kein
#: Misstrauen gegen die Quelle, im Gegenteil: ihre Noten sind die verlässlichsten
#: im ganzen Bestand. Aber bei den Schweizer Händlern tritt nur rund die Hälfte der
#: Weine überhaupt an — die andere Hälfte findet bei Vivino keinen Eintrag. In einer
#: gemeinsamen Rangliste gewänne der Marktplatz jeden Platz, ohne dass daraus etwas
#: über die Weine folgte.
MARKTPLATZ_QUELLEN = frozenset({"vivinoshop"})

#: Rebsorten, die sich auf der Seite gezielt ausblenden lassen.
#:
#: Anlass war Primitivo: 23 der 168 Weine in der Standardansicht sind welcher, und
#: sie besetzen die ersten fünf Plätze der Preis-Leistungs-Rangliste. Das ist kein
#: Rechenfehler — süsslich ausgebaute Appassimento-Weine werden auf Vivino von
#: vielen Gelegenheitstrinkern hoch bewertet und sind günstig. Wer sie nicht mag,
#: sortiert an ihnen vorbei, und dafür gibt es jetzt einen Schalter.
#:
#: Bewusst nur die Sorte selbst, nicht ihre Synonyme: Primitivo und Zinfandel sind
#: botanisch dieselbe Rebe, ein kalifornischer Zinfandel schmeckt aber anders als
#: ein apulischer Appassimento. Wer „Primitivo" ausblendet, meint nicht zwingend
#: auch die sechs Zinfandel im Bestand.
#:
#: Ein weiterer Eintrag hier genügt, damit auf der Seite ein Kästchen mehr steht.
AUSBLENDBARE_SORTEN: dict[str, tuple[str, str]] = {
    "primitivo": ("Primitivo", r"primitivo"),
}

#: Auf Wortgrenzen geprüft, damit ein Produzentenname wie „Primitivoli" nicht
#: mitgenommen wird.
_SORTEN_RE = {
    key: re.compile(rf"(?<![a-zäöüéèàç]){muster}(?![a-zäöüéèàç])", re.I)
    for key, (_, muster) in AUSBLENDBARE_SORTEN.items()
}


def _sorten(wine: dict[str, Any]) -> list[str]:
    """Welche der ausblendbaren Rebsorten stehen in diesem Wein?

    Gesucht wird im Händlernamen **und** im bei Vivino gefundenen Namen: Händler
    lassen die Sorte oft weg. „Santi Nobile Cento X Cento" heisst bei Vivino
    „… Appassimento Primitivo", und nur über den zweiten Namen ist er zu erkennen.
    """
    heu = f"{wine.get('name') or ''} {wine.get('matchedName') or ''}"
    return [key for key, rx in _SORTEN_RE.items() if rx.search(heu)]


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
            _je_sorte(gruppe, "valueScore", note)

    # Zusätzlich eine Zahl über beide Welten hinweg. Sie wird gebraucht, sobald die
    # Seite Handel und Marktplatz gemeinsam zeigt — das ist die Standardansicht.
    # Ohne sie stünden in einer Liste zwei Zahlen nebeneinander, die aus getrennten
    # Regressionen stammen und schlicht nicht dasselbe messen: eine 0.3 aus der
    # Marktplatz-Gruppe hiesse "gut für einen Marktplatzwein", eine 0.3 aus dem
    # Handel "gut für einen Schweizer Ladenwein". Sortiert man danach, vergleicht
    # man Äpfel mit Birnen.
    _je_sorte(wines, "valueScoreAll", note)


def _je_sorte(wines: list[dict[str, Any]], feld: str, note) -> None:
    """Eine eigene Kurve je Sorte, mit Rückfall auf die ganze Gruppe.

    Champagner hat ein anderes Preisniveau als Rotwein — Median CHF 43 gegen 23 im
    selben Lauf. An der gemeinsamen Kurve gemessen sagt die Zahl bei jedem
    Champagner mehr über seine Warengruppe aus als über den einzelnen Wein.

    Die Sorte ist dafür der richtige Schnitt, die *Auswahl* wäre es nicht: sie ist
    eine Eigenschaft des Weins und kein Zustand der Seite. Ein Wein behält damit
    seinen Rang, gleich was sonst angezeigt wird — anders als bei einer Rechnung
    über die gerade gefilterte Menge.

    Sorten mit zu wenigen Weinen bekommen die Kurve der ganzen Gruppe. Süsswein
    zählt 13 Positionen, Schaumwein 27; aus einer Handvoll Punkten eine eigene
    Erwartung abzuleiten wäre genauer aussehende, aber schlechtere Auskunft. Sie
    bleiben damit gerechnet, statt ohne Zahl dazustehen.
    """
    nach_sorte: dict[str, list[dict[str, Any]]] = {}
    for w in wines:
        nach_sorte.setdefault(w.get("style") or "?", []).append(w)

    rest: list[dict[str, Any]] = []
    for gruppe in nach_sorte.values():
        # Gezählt wird, was überhaupt in die Regression eingeht — Weine ohne Note
        # oder ohne Preis tragen nichts bei und dürfen die Gruppe nicht gross
        # erscheinen lassen.
        brauchbar = sum(
            1 for w in gruppe if w.get("rating") is not None and (w.get("price") or 0) > 0
        )
        if brauchbar >= VALUE_MIN_SAMPLE:
            _value_scores_einer_gruppe(gruppe, feld=feld, note=note)
        else:
            rest.extend(gruppe)
    if rest:
        _value_scores_einer_gruppe(rest, feld=feld, note=note)


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
    if spread <= 0:                       # alle zum selben Preis
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


#: Farbwörter, wie die Händler sie an den Namen hängen.
_COLOUR_WORD = r"(?:Rot|Weiss|Weiß|Ros[ée]|Schaum|Süss|Suess|Dessert)wein"

#: Die Standardflasche. Der Preis ist darauf normiert, im Namen sagt sie nichts.
#: Andere Grössen bleiben stehen: eine Magnum oder eine Halbflasche ist eine andere
#: Kaufentscheidung, ebenso der Sechserpack.
_STD_VOLUME = r"(?:0[.,]75\s*l|75\s*cl)"

_NAME_NOISE = [
    # „– Rotwein, Schweiz (0.75l)" am Ende
    re.compile(rf"\s*[–—-]\s*{_COLOUR_WORD}\s*,\s*[^,(]+?\s*\(\s*{_STD_VOLUME}\s*\)\s*$", re.I),
    # dasselbe ohne Volumen
    re.compile(rf"\s*[–—-]\s*{_COLOUR_WORD}\s*,\s*[^,(]+?\s*$", re.I),
    # nur das Farbwort, mit oder ohne folgende Klammer
    re.compile(rf"\s*[–—-]\s*{_COLOUR_WORD}\s*(?=\(|$)", re.I),
    # Standardgrösse am Ende, mit und ohne Klammer
    re.compile(rf",?\s*\(?\s*{_STD_VOLUME}\s*\)?\s*$", re.I),
    # Jahrgang in Klammern — er wird einheitlich angehängt, siehe ``vintageSuffix``
    re.compile(r"\s*\((?:19|20)\d{2}\)"),
]


def display_name(name: str) -> str:
    """Den Anzeigenamen von Händler-Beiwerk befreien.

    Die Namen kommen aus den Shops und tragen alles mit: „Rioja DOCa Crianza Bodegas
    Izadi (2022) – Rotwein, Spanien (0.75l)". Farbe steht daneben als Pill, das Land
    trägt nichts, 0.75 l ist die Bezugsgrösse des Preises, und der Jahrgang wird
    ohnehin einheitlich angehängt. Beim Überfliegen einer Liste ist der Name das
    Ankerelement — vierfach redundanter Text macht daraus mehrere Umbrüche.

    Was bleibt: Magnum, Halbflasche und Sechserpack. Das sind andere Käufe, keine
    Wiederholungen.
    """
    out = name or ""
    for pattern in _NAME_NOISE:
        out = pattern.sub("", out)
    return re.sub(r"\s{2,}", " ", out).strip(" ,;–—-")


def _relative_luminance(colour: str) -> float:
    raw = colour.lstrip("#")
    parts = [int(raw[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in parts]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    """Kontrastverhältnis zweier Farben nach WCAG."""
    high, low = sorted((_relative_luminance(a), _relative_luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


#: Nicht-Text-Kontrast für Flächen und Umrisse (WCAG 2.2 SC 1.4.11).
MIN_UI_CONTRAST = 3.0


#: Textfarben der Etikette-Richtung, je Schema, mit ihrem Zweck. Grossgrade dürfen
#: bei 3:1 liegen (WCAG-Schwelle für grosse Schrift), Kleintext braucht 4.5:1.
_TOKEN_CONTRAST = {
    "hell": (_GROUND_LIGHT, {
        "--ink": ("#1a1719", 4.5), "--muted": ("#6b6668", 4.5),
        "--faint": ("#78716d", 4.5), "--accent": ("#6d1834", 4.5),
        "--goldtx": ("#8a6a3d", 4.5), "--gold": ("#9a7b4f", 3.0),
        "--good": ("#2e7d32", 4.5), "--bad": ("#c62828", 4.5),
        "--line-strong": ("#8f8a86", 3.0),
    }),
    "dunkel": (_GROUND_DARK, {
        "--ink": ("#f0ebec", 4.5), "--muted": ("#a49da0", 4.5),
        "--faint": ("#8b8488", 4.5), "--accent": ("#e0879f", 4.5),
        "--goldtx": ("#d4b587", 4.5), "--gold": ("#c9a877", 3.0),
        "--good": ("#7cc47f", 4.5), "--bad": ("#ef9a9a", 4.5),
        "--line-strong": ("#6f6a6e", 3.0),
    }),
}


def check_tokens() -> list[str]:
    """Prüft die Farbzusage der Seite. Leere Liste heisst: alles gut.

    Läuft im Test, nicht im Build — eine zu blasse Farbe soll auffallen, bevor sie
    ausgeliefert wird, aber den Seitenbau nicht anhalten. Gold ist mit 3:1 bewusst
    milder geprüft: es trägt nur Grossgrade und Flächen, für Kleintext gibt es
    ``--goldtx``.
    """
    problems = []
    for scheme, (ground, tokens) in _TOKEN_CONTRAST.items():
        for name, (value, target) in tokens.items():
            got = contrast(value, ground)
            if got < target:
                problems.append(
                    f"{scheme}: {name} ({value}) erreicht {got:.2f}:1, "
                    f"gefordert {target}:1 gegen {ground}"
                )
    return problems


def _wine_from_snapshot(d: dict[str, Any]) -> dict[str, Any]:
    """Eine Snapshot-Zeile in die Form bringen, die die Seite braucht.

    Ältere Läufe kennen Sorte und Trinkreife nicht — dann bleiben die Felder leer,
    statt geraten zu werden.
    """
    urls = d.get("urls") or {}
    cheapest = d.get("cheapest_retailer") or ""
    style = d.get("style") or ""
    # Ein Pill "unbekannt" kostet dieselbe Aufmerksamkeit wie "jetzt trinken" und
    # sagt nichts. Nur die Anzeige entfällt: ``style`` bleibt gesetzt, damit der
    # Filter-Chip "unbekannt" weiter greift — dessen Beschriftung kommt aus
    # STYLE_LABELS, nicht von hier.
    style_label = "" if style == "unbekannt" else (
        d.get("style_label") or STYLE_LABELS.get(style, "")
    )
    return {
        "key": d.get("dedup_key") or d.get("name") or "",
        # Nur die Anzeige wird bereinigt. Gematcht und dedupliziert wurde vorher mit
        # dem Originalnamen, und der Schlüssel bleibt der Originalschlüssel.
        "name": display_name(d.get("name") or ""),
        "vintage": d.get("vintage") or "",
        "price": d.get("best_price"),
        # Ein Produzenten-Durchschnitt ist nicht die Note *dieses* Weins und darf
        # darum nicht auf die Achse. Mouton Cadet für CHF 9.95 hätte sonst die 4.6
        # von Château Mouton Rothschild.
        "rating": (
            d.get("vivino_rating")
            if d.get("vivino_status") not in ("winery_level",)
            else None
        ),
        "wineryOnly": d.get("vivino_status") == "winery_level",
        "wineryRating": d.get("vivino_rating") if d.get("vivino_status") == "winery_level" else None,
        # 1 = der Namensabgleich ist unbestätigt (fuzzy). Nur gesetzt, wenn wir es
        # positiv wissen: Läufe von vor dieser Änderung haben das Feld nicht, und
        # "Feld fehlt" darf nicht als "unbestätigt" durchgehen.
        "fuzzy": 1 if d.get("vivino_match_confidence") == "fuzzy" else None,
        "matchedName": d.get("vivino_matched_name") or "",
        "ratingCount": d.get("vivino_rating_count"),
        "vivinoStatus": d.get("vivino_status") or "",
        "vivinoUrl": d.get("vivino_url") or "",
        "retailers": d.get("retailers") or ([cheapest] if cheapest else []),
        "cheapest": cheapest,
        "url": urls.get(cheapest) or next(iter(urls.values()), ""),
        "market": d.get("market_price"),
        "bargain": d.get("bargain_percent"),
        "style": style,
        "styleLabel": style_label,
        "maturity": d.get("maturity") or "",
        "maturityShort": d.get("maturity_short") or "",
        "maturityRegion": d.get("maturity_region") or "",
        "country": d.get("country") or "",
        # Vivinos Trinkfenster für genau diesen Wein und Jahrgang, und ob es der
        # Vinum-Tabelle widerspricht. Beide Quellen behalten ihre Stimme.
        "drinkWindow": d.get("maturity_window") or "",
        "maturityConflict": d.get("maturity_conflict") or "",
        "vintageQuality": d.get("vintage_quality") or "",
        "falstaff": d.get("falstaff_points"),
        "rankSource": d.get("rank_source") or "",
    }


#: Kurze Schlüssel in der eingebetteten JSON. Bei 400 Weinen und mehreren Läufen
#: macht die Umbenennung rund ein Drittel der Dateigrösse aus — und die Seite soll
#: auch über Mobilfunk schnell laden. Die Zuordnung steht direkt daneben im JS.
_SHORT_KEYS = {
    "name": "n", "vintage": "y", "price": "p", "rating": "r", "ratingCount": "rc",
    "vivinoUrl": "vu", "retailers": "rs", "cheapest": "c", "url": "u",
    "market": "m", "bargain": "b", "style": "s", "styleLabel": "sl",
    "maturity": "t", "maturityShort": "ts", "maturityRegion": "tr",
    "drinkWindow": "dw", "maturityConflict": "mc", "country": "co",
    "vintageQuality": "q", "falstaff": "f", "key": "k",
    "wineryRating": "wr", "fuzzy": "fz", "matchedName": "mn",
    # Zwei Preis-Leistungs-Zahlen: „vs" gilt innerhalb einer Warenwelt, „vsa" über
    # beide hinweg. Welche angezeigt wird, entscheidet der Quellenfilter.
    "valueScore": "vs",
    "valueScoreAll": "vsa",
    # Kennzeichnung der Quellenart — siehe MARKTPLATZ_QUELLEN.
    "marketplace": "mp",
    "swiss": "ch",
    # Ausblendbare Rebsorten, siehe AUSBLENDBARE_SORTEN.
    "grapes": "g",
}


def _compact(wine: dict[str, Any]) -> dict[str, Any]:
    """Leere Felder weglassen, Zahlen runden, Schlüssel kürzen."""
    out: dict[str, Any] = {}
    for long, short in _SHORT_KEYS.items():
        value = wine.get(long)
        if value is None or value == "" or value == []:
            continue
        if isinstance(value, float):
            value = round(value, 2)
        out[short] = value
    # Die Händlerliste ist meist identisch mit dem günstigsten Händler.
    if out.get("rs") == [out.get("c")]:
        out.pop("rs", None)
    return out


def build(
    runs: list[dict[str, Any]],
    path: Path | str,
    *,
    retailer_info: dict[str, dict] | None = None,
    title: str = "Schweizer Weinaktionen",
) -> Path | None:
    """Baut die Seite.

    Args:
        runs: Liste aus ``{"id", "label", "date", "wines": [...]}``, neuester zuerst.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    runs = [r for r in runs if r.get("wines")]
    if not runs:
        return None

    # Jeder Wein weiss, aus welcher Art Quelle er kommt. Muss vor der Bewertung
    # stehen: die Preis-Leistungs-Zahl wird je Gruppe getrennt gerechnet.
    for run in runs:
        for w in run["wines"]:
            haendler = set(w.get("retailers") or [])
            # Zwei getrennte Kennzeichen, kein Entweder-oder: ein Wein kann in
            # beiden Welten stehen. "10 Vendemmie Tenuta Ulisse" verkaufen Schubi
            # *und* Vivino. Mit einem einzigen Kennzeichen verschwand er aus der
            # Schweizer Ansicht, obwohl er dort zu kaufen ist.
            w["marketplace"] = bool(haendler & MARKTPLATZ_QUELLEN)
            w["swiss"] = bool(haendler - MARKTPLATZ_QUELLEN)
            w["grapes"] = _sorten(w)

    # Je Lauf gerechnet: jeder hat sein eigenes Preisniveau.
    for run in runs:
        _add_value_scores(run["wines"])

    info = retailer_info or {}
    retailers = sorted({r for run in runs for w in run["wines"] for r in w["retailers"]})
    # Kein Farbwert je Händler mehr: in dieser Richtung trägt der Händler keine
    # Farbe, sondern seinen Namen. Farbe bleibt für Akzent, Urteil und Gold.
    names = {r: (info.get(r) or {}).get("name") or r for r in retailers}
    channels = {r: (info.get(r) or {}).get("channel") or "" for r in retailers}

    styles = [s for s in STYLE_LABELS if any(
        w["style"] == s for run in runs for w in run["wines"]
    )]
    maturities = [m for m in MATURITY_FILTER_ORDER if any(
        w["maturity"] == m for run in runs for w in run["wines"]
    )]

    payload = {
        "runs": [
            {"id": r["id"], "label": r["label"],
             "wines": [_compact(w) for w in r["wines"]]}
            for r in runs
        ],
        "retailers": [
            {"key": r, "name": names[r], "channel": channels[r]}
            for r in retailers
        ],
        "styles": [{"key": s, "label": STYLE_LABELS[s]} for s in styles],
        # Nach Häufigkeit sortiert, nicht alphabetisch: Italien und Frankreich
        # stellen den Grossteil, und wer filtert, greift meist dorthin.
        #
        # Ohne Zahl im Namen — die Kachel zählt selbst, und zwar die *aktuelle*
        # Auswahl. Eine feste Zahl daneben widerspräche ihr, sobald ein anderer
        # Filter gesetzt ist.
        "countries": [
            {"key": k}
            for k, _n in Counter(
                w.get("country") for run in runs for w in run["wines"] if w.get("country")
            ).most_common()
        ],
        # Ein Kästchen je Rebsorte, die im Bestand tatsächlich vorkommt. Ein
        # Schalter, der nichts ausblendet, wäre nur Ballast.
        "grapeFilters": [
            {"key": k, "label": AUSBLENDBARE_SORTEN[k][0],
             "count": sum(1 for run in runs for w in run["wines"] if k in (w.get("grapes") or []))}
            for k in AUSBLENDBARE_SORTEN
            if any(k in (w.get("grapes") or []) for run in runs for w in run["wines"])
        ],
        # Ohne Farbe: die Trinkreife hat den Farbkanal an die Händler abgegeben.
        # Die Reihenfolge der Chips („jetzt" nach „später") trägt die Abstufung,
        # die Beschriftung den Wert.
        "maturities": [
            {"key": m, "label": MATURITY_SHORT[m], "text": MATURITY[m]}
            for m in maturities
        ],
        "good": {"rating": GOOD_RATING_MIN, "price": GOOD_PRICE_MAX},
        "generated": datetime_ch(),
    }

    doc = _TEMPLATE.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))
    doc = doc.replace("__TITLE__", html.escape(title))
    doc = doc.replace("__SOURCE_NAME__", html.escape(SOURCE_NAME))
    doc = doc.replace("__SOURCE_PAGE__", html.escape(SOURCE_PAGE))
    doc = doc.replace("__STAMP__", html.escape(datetime_ch()))
    doc = doc.replace("__MARK__", SVG_MARK)
    p.write_text(doc, encoding="utf-8")

    # Die Rasterfassung des Zeichens muss neben der Seite liegen: iOS lädt für den
    # Startbildschirm ausschliesslich PNG. Fehlt sie, zeigt das Telefon wieder ein
    # graues Feld mit dem ersten Buchstaben des Titels.
    schreibe_icons(p.parent)
    return p


_TEMPLATE = r"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<meta name="description" content="Aktuelle Weinaktionen der Schweizer Händler mit Vivino-Bewertung, Trinkreife und Marktpreisvergleich.">
<title>__TITLE__</title>
<!-- Startbildschirm. Ohne apple-touch-icon setzt iOS ein graues Feld mit dem ersten
     Buchstaben des Titels — daher liegt neben dieser Seite ein PNG; SVG nimmt iOS
     dafür nicht an. Der Kurzname muss kurz sein: unter dem Symbol ist nach rund
     zwölf Zeichen Schluss, „Schweizer Weinaktionen" wurde zu „SchweizerWeina…". -->
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<link rel="icon" type="image/png" sizes="512x512" href="icon-512.png">
<meta name="apple-mobile-web-app-title" content="Weincheck">
<meta name="application-name" content="Weincheck">
<!-- Zwei Werte, damit die Systemleiste auf dem Telefon zum Seitengrund passt. -->
<meta name="theme-color" content="#faf9f7" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#141114" media="(prefers-color-scheme: dark)">
<style>
  :root {
    /* ---------------------------------------------------------------- Etikette
       Nach der Weinetikette gebaut: gestochener Serif, Linien statt Kästen, viel
       Ruhe, eine tiefe Farbe. Gold trägt den Wert — die Kennzahl, das markierte
       Feld — und sonst nichts.

       Farbe hat drei Aufgaben und keine vierte: Akzent (bedienbar), Urteil
       (gut/schwach), Gold (Wert). Der Händler bekommt keine Farbe mehr: er stand
       nur im Diagramm als Punktfarbe, und dieselben Töne mussten dort gleichzeitig
       die Trinkreife tragen. Jetzt steht sein Name im Tooltip und in der Tabelle.

       Alle Textwerte gegen beide Gründe auf >= 4.5:1 geprüft, Grossgrade auf 3:1,
       Ränder von Bedienelementen auf 3:1. */
    --ink:#1a1719; --muted:#6b6668; --faint:#78716d;
    --line:#e2dedc; --line-strong:#8f8a86;
    --bg:#faf9f7; --panel:#f4f2ef; --chip:transparent;
    --brand:#6d1834; --accent:#6d1834;
    /* Gold erreicht auf dem hellen Grund nur 3.75:1 — es trägt darum ausschliesslich
       Grossgrade und Flächen. Kleintext in Gold nimmt --goldtx mit 4.74:1. */
    --gold:#9a7b4f; --goldtx:#8a6a3d;
    --good:#2e7d32; --bad:#c62828;
    /* Didot ist die Etikettenschrift, Optima der humanistische Begleiter, Menlo
       hält die Zahlenspalten. Nichts wird geladen: die Seite bleibt ohne
       Drittanbieter, und jede Stufe hat einen breit vorhandenen Ersatz. */
    --serif:Didot, "Didot LT STD", "Hoefler Text", Garamond, "Times New Roman", serif;
    --sans:Optima, Candara, "Gill Sans", "Gill Sans MT", "Trebuchet MS", "Segoe UI", sans-serif;
    --mono:Menlo, "SF Mono", Consolas, monospace;
    /* Mindesthöhe für Bedienelemente. Auf Zeigergeräten kompakt, auf Touch 44 px —
       dort entscheidet die Treffgenauigkeit, hier die Dichte. */
    --control-h:36px;
    /* Fünf Textrollen. Der Lesetext liegt auf 16 px: die Tabelle ist die am
       längsten gelesene Fläche der Seite. */
    --fs-page-title:2rem;     /* h1, Didot */
    --fs-title:1.25rem;       /* Abschnittstitel, Didot */
    --fs-body:1rem;           /* Tabelle, Suchfeld, Tooltip */
    --fs-body-sm:.875rem;     /* Metatext, Chips, Zähler, Footer, Hinweise */
    --fs-label:.75rem;        /* Legenden, Spaltenköpfe, Pills — gesperrte Versalien */
  }
  @media (prefers-color-scheme: dark) {
    :root { --ink:#f0ebec; --muted:#a49da0; --faint:#8b8488;
            --line:#2b262a; --line-strong:#6f6a6e;
            --bg:#141114; --panel:#1c181c; --chip:transparent;
            --brand:#e0879f; --accent:#e0879f;
            --gold:#c9a877; --goldtx:#d4b587;
            --good:#7cc47f; --bad:#ef9a9a; }
  }
  @media (pointer: coarse) { :root { --control-h:44px; } }
  * { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  /* Ein Fokusstil für alles Bedienbare — vorher hing das Aussehen am Browser. */
  :focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
  html { -webkit-text-size-adjust:100%; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:16px/1.55 var(--sans);
         padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left); }
  .wrap { max-width:1080px; margin:0 auto; padding:26px 18px 56px; }
  h1 { font-family:var(--serif); font-size:var(--fs-page-title); font-weight:400;
       margin:6px 0 0; letter-spacing:-.01em; line-height:1.05; }
  .sub { color:var(--muted); font-size:var(--fs-body-sm); margin:9px 0 0; }
  /* Zeichen und Titel stehen nebeneinander; das Zeichen richtet sich an der
     Versalhöhe aus, nicht am Kastenrand — sonst hängt es unter der Zeile. */
  .head { display:flex; align-items:center; gap:16px; }
  .head > div { min-width:0; }
  .mark { flex:none; width:56px; height:56px; display:block; }
  /* Die Haarlinie unter dem Kopf ist das Etikettenmotiv: getrennt wird mit Linien,
     nicht mit Flächen. */
  .rule { height:1px; background:var(--ink); opacity:.8; margin:15px 0 0; }
  /* ---- Suche und Filter ---------------------------------------------------- */
  /* Suchfeld, Treffermenge und Rückweg bleiben stehen: wer in der Liste liest und
     die Auswahl ändern will, soll nicht nach oben zurück müssen. */
  .search { position:sticky; top:0; z-index:5; background:var(--bg);
            padding:12px 0 10px; border-bottom:1px solid var(--line); }
  .search input { width:100%; font:400 var(--fs-title)/1.35 var(--serif);
                  padding:5px 0 8px; background:transparent; color:var(--ink);
                  border:0; border-bottom:1px solid var(--ctl, var(--line-strong)); }
  .search input::placeholder { color:var(--faint); font-family:var(--serif); }
  .search input:focus { outline:0; border-bottom:2px solid var(--accent); padding-bottom:7px; }
  .search .bar { margin:9px 0 0; }
  .bar { display:flex; align-items:baseline; justify-content:space-between; gap:14px;
         flex-wrap:wrap; }
  .count { font-size:var(--fs-body-sm); color:var(--muted); }
  .count b { color:var(--ink); font-family:var(--mono); font-weight:600;
             font-variant-numeric:tabular-nums; }
  .reset { background:none; border:0; color:var(--accent); font:inherit;
           font-size:var(--fs-body-sm); cursor:pointer; padding:6px 0;
           text-decoration:underline; min-height:var(--control-h); }
  fieldset { border:0; margin:0; padding:0; }
  fieldset + fieldset { margin-top:15px; }
  legend { font-size:var(--fs-label); text-transform:uppercase; letter-spacing:.2em;
           color:var(--faint); margin-bottom:8px; padding:0; }
  .chips { display:flex; flex-wrap:wrap; gap:7px; }
  /* Pillen behalten ihren Umriss: sie sind schaltbar, dort ist der Rahmen
     Information und keine Dekoration. */
  .chip { display:inline-flex; align-items:center; gap:7px;
          border:1px solid var(--line-strong); background:var(--chip); color:var(--muted);
          font:inherit; font-size:var(--fs-body-sm); padding:8px 14px; border-radius:999px;
          cursor:pointer; min-height:var(--control-h); }
  .chip[aria-pressed="true"] { background:var(--accent); border-color:var(--accent);
                               color:var(--bg); font-weight:600; }
  .chip .n { color:var(--faint); font-family:var(--mono); font-size:var(--fs-label);
             font-variant-numeric:tabular-nums; }
  .chip[aria-pressed="true"] .n { color:var(--bg); opacity:.85; }
  /* Kein eigener Oberstrich: die sticky Leiste darüber hat schon einen, sonst
     stehen zwei Linien mit einer leeren Lücke dazwischen. */
  .filters { padding:16px 0 0; margin-top:0; border-top:0; }
  #filterBox > summary { font-size:var(--fs-label); letter-spacing:.16em;
                         text-transform:uppercase; color:var(--accent); cursor:pointer;
                         display:flex; align-items:center; gap:9px;
                         min-height:var(--control-h); list-style:none; }
  #filterBox > summary::-webkit-details-marker { display:none; }
  #filterBox > summary::after { content:"▾"; margin-left:auto; font-size:1.1em;
                                transition:transform .15s; }
  #filterBox[open] > summary::after { transform:rotate(180deg); }
  #filterBox > summary .n { color:var(--faint); letter-spacing:0; text-transform:none;
                            font-size:var(--fs-body-sm); }
  #filterBox[open] > summary { margin-bottom:10px; }
  /* Am Desktop ist Platz — dort sind die Filter immer offen und der Aufklapper
     wäre nur ein zusätzlicher Klick. */
  @media (min-width: 721px) { #filterBox > summary { display:none; } }
  .fine { border-top:1px solid var(--line); padding-top:15px; margin-top:16px; }
  .controls { display:flex; flex-wrap:wrap; gap:14px 26px; align-items:flex-end;
              font-size:var(--fs-body-sm); color:var(--muted); }
  /* Auswahlfelder sind unterstrichen, nicht umkastet — Etiketten arbeiten mit Linien. */
  .controls label { display:flex; flex-direction:column; gap:5px; white-space:nowrap;
                    min-height:var(--control-h); }
  .controls label > span { font-size:var(--fs-label); letter-spacing:.2em;
                           text-transform:uppercase; color:var(--faint); }
  .controls select { font:400 var(--fs-body)/1 var(--serif); color:var(--ink);
                     background:transparent; border:0;
                     border-bottom:1px solid var(--line-strong);
                     padding:4px 16px 6px 0; min-height:var(--control-h); cursor:pointer;
                     appearance:none; max-width:100%; }
  .controls .cb { flex-direction:row; align-items:center; gap:9px; cursor:pointer; }
  .controls input[type=checkbox] { accent-color:var(--accent); width:19px; height:19px;
                                   flex:0 0 auto; }
  .coverage { font-size:var(--fs-body-sm); color:var(--faint); margin:15px 0 0;
              padding-top:12px; border-top:1px solid var(--line); }
  /* ---- Abschnitte: Haarlinie statt Karte --------------------------------- */
  .card { border:0; border-radius:0; background:transparent; padding:24px 0 0;
          margin:22px 0 0; border-top:1px solid var(--ink); }
  .card h2 { font-family:var(--serif); font-size:var(--fs-title); font-weight:400;
             margin:0 0 4px; letter-spacing:-.005em; }
  /* ---- Diagramm ---------------------------------------------------------- */
  svg { width:100%; height:auto; display:block; overflow:visible;
        touch-action:manipulation; }
  .grid { stroke:var(--line); }
  .axis { stroke:var(--line); stroke-width:1; }
  .tick { fill:var(--faint); font-size:10px; font-family:var(--sans); }
  .alabel { fill:var(--faint); font-size:10px; font-family:var(--sans); }
  /* Der Vektor zeigt die Abweichung vom Preisniveau, der Punkt sitzt an seiner
     Spitze. Im markierten Feld ist er gefüllt und golden, sonst hohl und leise. */
  /* Die Trendlinie muss so aussehen wie ihr Symbol in der Legende — sonst sagen
     Diagramm und Legende Unterschiedliches. */
  .trend { stroke:var(--muted); stroke-width:1.1; opacity:.55; }
  /* Der Trefferkreis liegt unsichtbar vor dem Punkt und nimmt die Ereignisse.
     pointer-events:all trifft auch ohne Füllung. */
  .hit { fill:transparent; stroke:none; pointer-events:all; cursor:pointer; }
  .pt { fill:none; stroke:var(--muted); stroke-width:1.1; opacity:.55;
        pointer-events:none; }
  .pt.good { fill:var(--gold); stroke:var(--gold); opacity:.95; }
  /* Der sichtbare Punkt reagiert über seinen Trefferkreis — er ist dessen
     unmittelbarer Nachbar. */
  .hit:hover + .pt { stroke:var(--ink); stroke-width:1.8; opacity:1; }
  .zone { fill:var(--gold); fill-opacity:.14; }
  .zone-edge { fill:none; stroke:var(--gold); stroke-width:1.3; stroke-dasharray:5 3; }
  .zone-t { fill:var(--goldtx); font-family:var(--sans); font-size:9.5px;
            font-weight:600; letter-spacing:1.6px; }
  .zone-s { fill:var(--goldtx); font-family:var(--sans); font-size:9px; opacity:.9; }
  .lead { fill:none; stroke:var(--goldtx); stroke-width:.9; }
  .lead-t { fill:var(--ink); font-family:var(--sans); font-size:10.5px; }
  .legend { font-size:var(--fs-body-sm); color:var(--muted); margin:8px 0 12px;
            display:flex; flex-wrap:wrap; gap:8px 22px; }
  .legend span { display:flex; align-items:center; gap:7px; }
  .legend svg { flex:0 0 auto; width:auto; }
  .empty { color:var(--muted); font-size:var(--fs-body-sm); padding:24px 2px;
           text-align:center; }
  /* ---- Tabelle: Linien, Serif für Namen, Mono für Zahlen ----------------- */
  table { width:100%; border-collapse:collapse; font-size:var(--fs-body); }
  th { text-align:left; font-size:var(--fs-label); text-transform:uppercase;
       letter-spacing:.18em; color:var(--faint); font-weight:400; padding:0 9px 9px;
       border-bottom:1px solid var(--ink); background:transparent; }
  td { padding:13px 9px; border-bottom:1px solid var(--line); vertical-align:baseline;
       background:transparent; }
  tr:last-child td { border-bottom:0; }
  a { color:var(--accent); }
  .wine { font-family:var(--serif); font-size:1.28em; line-height:1.25; }
  .meta { color:var(--faint); font-size:var(--fs-body-sm); }
  .num { font-family:var(--mono); font-variant-numeric:tabular-nums; white-space:nowrap;
         text-align:right; font-size:.92em; }
  /* Die Kennzahl ist der Anker der Seite: Didot, gross, gold. */
  .pl { font-family:var(--serif); font-size:1.55em; line-height:1; color:var(--gold);
        text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
  .pl.neg { color:var(--muted); }
  .good { color:var(--good); font-weight:600; }
  .bad { color:var(--bad); }
  .warn { color:var(--accent); }
  .matched { color:var(--faint); font-size:.78em; }
  /* Sorte und Trinkreife als gesperrte Versalien, nicht als gefüllte Pillen —
     Flächen gehören in dieser Richtung nicht ins Bild. */
  .pill { display:inline-block; font-size:var(--fs-label); letter-spacing:.14em;
          text-transform:uppercase; color:var(--faint); }
  .pill + .pill::before { content:"·"; margin:0 6px 0 2px; opacity:.6; }
  /* Die Markierung sagt, dass ein Wein die Regel erfüllt. Sie steht bei den Fakten,
     nicht in der Zahlenspalte: dort bräche sie auf drei Zeilen. */
  .marker { display:inline-flex; align-items:center; gap:5px; font-size:var(--fs-label);
            letter-spacing:.13em; text-transform:uppercase; color:var(--goldtx);
            border:1px solid var(--gold); border-radius:999px; padding:4px 9px;
            margin-top:7px; }
  th .sortbtn { font:inherit; color:inherit; background:none; border:0; padding:0;
                cursor:pointer; letter-spacing:inherit; text-transform:inherit; }
  th .sortbtn:hover { color:var(--accent); }
  th.sorted { color:var(--ink); }
  th.num .sortbtn { width:100%; text-align:right; }
  .tblnote { font-size:var(--fs-body-sm); color:var(--muted); margin:0 0 14px; }
  .chartnote { font-size:var(--fs-body-sm); color:var(--muted); margin:0 0 10px;
               max-width:78ch; }
  .colhint { font-size:var(--fs-body-sm); color:var(--faint); }
  .more { margin:16px 0 0; text-align:center; }
  .more button { font:inherit; font-size:var(--fs-body-sm); color:var(--accent);
                 cursor:pointer; background:transparent;
                 border:1px solid var(--line-strong); border-radius:999px;
                 padding:9px 20px; min-height:var(--control-h); }
  .more button:hover { border-color:var(--accent); }
  .more .meta { display:block; margin-top:7px; }
  /* Auf dem Handy ist thead ausgeblendet — dort ist der Hinweis schlicht falsch.
     Derselbe Breakpoint wie für Kartenansicht und Diagramm: 720 px. */
  @media (max-width: 720px) {
    .colhint { display:none; }
    h1 { font-size:1.6rem; }
    .wrap { padding:20px 15px 44px; }
    thead { display:none; }
    tr { display:block; border-bottom:1px solid var(--line); padding:14px 0; }
    td { display:block; border:0; padding:2px 0; text-align:left; }
    td[data-l]::before { content:attr(data-l) " "; color:var(--faint);
                         font-size:var(--fs-label); letter-spacing:.1em;
                         text-transform:uppercase; }
    /* In der Tabelle hält ein "—" die Spalte ausgerichtet. In der Kartenansicht
       gibt es keine Spalte mehr — dort ist es nur eine Zeile ohne Inhalt, und
       beim Marktpreis betrifft das die Mehrheit der Weine. */
    td.noval { display:none; }
    .num, .pl { text-align:left; }
    .pl { font-size:1.7em; }
    /* Das Diagramm braucht Breite, die es hier nicht hat. Die Liste ist auf dieser
       Breite die vollständigere Ansicht. */
    .chart { display:none; }
  }
  #tip { position:fixed; z-index:20; pointer-events:none; opacity:0;
         transition:opacity .1s; max-width:320px; background:var(--bg);
         border:1px solid var(--line-strong); border-radius:2px; padding:12px 14px;
         font-size:var(--fs-body-sm); line-height:1.45;
         box-shadow:0 10px 30px rgba(0,0,0,.16); }
  #tip.on { opacity:1; }
  #tip .n { font-family:var(--serif); font-size:1.15em; display:block;
            margin-bottom:7px; line-height:1.25; }
  #tip .r { display:flex; justify-content:space-between; gap:14px; }
  #tip .k { color:var(--faint); }
  #tip .also { margin-top:9px; padding-top:7px; border-top:1px solid var(--line); }
  #tip .also b { display:block; margin-bottom:4px; font-weight:600; }
  footer { color:var(--faint); font-size:var(--fs-body-sm);
           border-top:1px solid var(--line); padding-top:16px; margin-top:32px; }
  footer p { margin:.5em 0; }
  @media (prefers-reduced-motion: reduce) { * { transition:none !important; } }
</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    __MARK__
    <div>
      <h1>__TITLE__</h1>
      <p class="sub">Stand __STAMP__ · Preise auf CHF pro 75 cl inkl. MwSt normalisiert (8.1 %)</p>
    </div>
  </div>

  <!-- Suchfeld, Treffermenge und Rückweg bleiben beim Scrollen stehen: wer in der
       Liste liest und die Auswahl ändern will, soll nicht nach oben zurück müssen.
       Die Abdeckungsangaben stehen bewusst *nicht* hier — sie sind Nachschlagewerte
       und würden die Leiste am Handy auf zwei Zeilen bringen. -->
  <div class="search">
    <input id="q" type="search" placeholder="Wein, Produzent, Region oder Sorte suchen …"
           autocomplete="off" autocapitalize="none" spellcheck="false"
           aria-label="Weine durchsuchen">
    <div class="bar">
      <span class="count" id="count" aria-live="polite"></span>
      <button class="reset" id="reset" type="button">Filter zurücksetzen</button>
    </div>
  </div>

  <main>
  <div class="card filters">
    <!-- Eingeklappt auf dem Handy: sonst füllt das Formular den ersten Bildschirm und
         der erste Wein steht unter 1200 px. Der Zähler bleibt draussen und damit
         immer sichtbar. <details> statt eigener Logik — Tastatur und Screenreader
         kommen gratis mit. -->
    <details id="filterBox">
    <summary>Filter <span class="n" id="filterCount"></span></summary>
    <fieldset id="runBox"><legend>Lauf</legend><div class="chips" id="fRun"></div></fieldset>
    <!-- Die Quellenart trennt zwei Warenwelten, die nicht in dieselbe Rangliste
         gehören: der Schweizer Handel, bei dem rund die Hälfte der Weine keine
         auffindbare Note hat, und Vivinos Marktplatz, wo jeder Wein seine Note
         mitbringt. Gemischt gewänne der Marktplatz jeden Platz, ohne dass daraus
         etwas über die Weine folgte. Vorgewählt ist der Schweizer Handel. -->
    <fieldset><legend>Quelle</legend><div class="chips" id="fSrc"></div></fieldset>
    <fieldset><legend>Trinkreife</legend><div class="chips" id="fMat"></div></fieldset>
    <fieldset><legend>Sorte</legend><div class="chips" id="fStyle"></div></fieldset>
    <!-- Nur Länder, die im Bestand vorkommen, und nur solche mit erkanntem Land.
         Wo weder Name noch Vinum-Region eines nennen, bleibt der Wein ohne — und
         taucht dann in keinem Länderfilter auf, statt unter einem geratenen. -->
    <fieldset><legend>Land</legend><div class="chips" id="fLand"></div></fieldset>
    <fieldset><legend>Händler</legend><div class="chips" id="fShop"></div></fieldset>

    <fieldset class="fine">
      <legend>Feinauswahl</legend>
      <div class="controls">
        <label>Note ab
          <select id="fMinRating">
            <option value="">alle</option>
            <option value="3.5">3.5</option>
            <option value="3.8">3.8</option>
            <option value="4">4.0</option>
            <option value="4.2">4.2</option>
            <option value="4.5">4.5</option>
          </select>
        </label>
        <label>Preis bis
          <select id="fMaxPrice">
            <option value="">alle</option>
            <option value="10">CHF 10</option>
            <option value="20">CHF 20</option>
            <option value="40">CHF 40</option>
            <option value="50">CHF 50</option>
            <option value="80">CHF 80</option>
          </select>
        </label>
        <label>Sortieren
          <select id="fSort">
            <option value="value:-1">Preis-Leistung, beste zuerst</option>
            <option value="rating:-1">Note, beste zuerst</option>
            <option value="price:1">Preis, günstigste zuerst</option>
            <option value="price:-1">Preis, teuerste zuerst</option>
            <option value="bargain:-1">Ersparnis, grösste zuerst</option>
            <option value="name:1">Name A–Z</option>
            <option value="shop:1">Händler A–Z</option>
          </select>
        </label>
        <label class="cb" title="Nur Weine mit bestätigtem Namensabgleich — ohne unsichere Treffer, ohne Produzenten-Mittelwerte, ohne Weine ohne Eintrag"><input type="checkbox" id="fFound"> nur bei Vivino gefunden</label>
        <label class="cb"><input type="checkbox" id="fBargain"> nur unter Marktpreis</label>
        <!-- Nicht dasselbe wie der Quellen-Chip "Schweizer Handel": der zeigt jeden
             Wein, den ein Schweizer Laden führt — auch wenn Vivino ihn billiger hat
             und darum in der Kaufspalte steht. Dieses Kästchen entfernt genau die
             Zeilen, deren Kauflink zu Vivino führt. -->
        <label class="cb" title="Blendet Weine aus, deren angezeigtes Angebot von Vivino stammt"><input type="checkbox" id="fNoVivino"> ohne Vivino-Shop</label>
        <!-- Je ausblendbarer Rebsorte ein Kästchen; gebaut aus D.grapeFilters. -->
        <span id="fGrapes"></span>
      </div>
    </fieldset>
    </details>
    <p class="coverage" id="coverage"></p>
  </div>

  <div class="card chart">
    <h2>Vivino-Bewertung gegen Preis</h2>
    <p class="chartnote">Die Linie ist die Note, die für diesen Preis üblich ist. Wer
       darüber liegt, gibt weniger für dieselbe Note — wie viel genau, steht in der
       Spalte <b>Preis-Leistung</b>. Getrennt davon markiert ist die feste Regel für
       <b>gut und günstig</b>: ab Note 4.2 und bis CHF 20.</p>
    <p class="legend">
      <span><svg width="26" height="12" aria-hidden="true"><line x1="1" y1="6" x2="25" y2="6"
        stroke="var(--muted)" stroke-width="1.1" opacity=".55"/></svg> üblich für den Preis</span>
      <span><svg width="14" height="12" aria-hidden="true"><circle cx="7" cy="6" r="4"
        fill="var(--gold)"/></svg> gut und günstig</span>
      <span><svg width="14" height="12" aria-hidden="true"><circle cx="7" cy="6" r="4"
        fill="none" stroke="var(--muted)" stroke-width="1.1" opacity=".55"/></svg>
        ausserhalb der Regel</span>
      <span>je Punkt ein Wein</span></p>
    <div id="chart"></div>
  </div>

  <div class="card">
    <h2 id="tblTitle">Weine</h2>
    <!-- Die Herkunft der Zahl gehört sichtbar dazu: das Preisniveau ist gemessen,
         die Gewichtung ist gesetzt. Wer danach kauft, soll wissen, welcher Teil
         Beobachtung ist und welcher Entscheidung. -->
    <p class="tblnote"><b>Preis-Leistung</b> = wie viel besser die Note ist als bei
       Weinen derselben Sorte zum gleichen Preis. ±0.00 = im Schnitt. Wenig bewertete
       Weine werden gedämpft. Der Preis ist dabei bewusst stärker gewichtet, als die
       Daten hergeben: <b>0.1 Notenpunkte rechtfertigen rund 40 % Aufpreis</b>
       (gemessen wären es fast 100 %). Und eine seltene Note zählt mehr: 218 Weine
       tragen eine 4.1, nur 26 eine 4.5 — ein Zehntel am oberen Ende wiegt
       schwerer als eines in der Mitte.<span class="colhint"> · Spaltentitel antippen
       sortiert, nochmal antippen kehrt um</span></p>
    <div id="table"></div>
  </div>
  </main>

  <footer>
    <p><b>Bewertungen</b> von <a href="https://www.vivino.com" target="_blank" rel="noopener">Vivino</a>.
       Die Achse zeigt ausschliesslich die Vivino-Note in ihrer eigenen Skala 1–5 —
       Falstaff- und andere Kritikerpunkte stehen in der Tabelle, aber nicht auf der
       Achse: zwei Bewertungsgrundlagen auf einer Achse sind nicht vergleichbar.</p>
    <p><b>Trinkreife</b> aus der <a href="__SOURCE_PAGE__" target="_blank" rel="noopener">__SOURCE_NAME__</a>.
       Sie gilt für Region und Weinart, nicht für die einzelne Flasche.</p>
    <p><b>Preise</b> von den genannten Händlern, teils über den Aggregator
       <a href="https://www.aktionis.ch" target="_blank" rel="noopener">Aktionis</a> und damit aus zweiter
       Hand. <b>Marktpreise</b> von Vivino-Partnerhändlern, nie vom eigenen Händler.
       Alles ohne Gewähr — vor dem Kauf beim Händler prüfen.</p>
    <p>Diese Seite lädt nichts von Dritten. Sie funktioniert offline, sobald sie
       einmal geladen ist.</p>
  </footer>
</div>
<!-- Kein role="tooltip": der Kasten hängt an keinem aria-describedby und wäre für
     assistive Technik ein Versprechen ohne Beziehung. Die Tabelle ist die
     zugängliche Entsprechung zum Diagramm. -->
<div id="tip"></div>

<script>
const D = __PAYLOAD__;
/* Kurzschlüssel aus der eingebetteten JSON zurückbenennen — sie halten die Datei
   klein, der Code arbeitet aber mit lesbaren Namen. */
const KEYS = { n:"name", y:"vintage", p:"price", r:"rating", rc:"ratingCount",
  vu:"vivinoUrl", rs:"retailers", c:"cheapest", u:"url", m:"market", b:"bargain",
  s:"style", sl:"styleLabel", t:"maturity", ts:"maturityShort", tr:"maturityRegion",
  dw:"drinkWindow", mc:"maturityConflict", co:"country",
  q:"vintageQuality", f:"falstaff", k:"key", wr:"wineryRating",
  fz:"fuzzy", mn:"matchedName", vs:"valueScore", vsa:"valueScoreAll", g:"grapes",
  /* Die Quellenart. Fehlten diese beiden, war w.swiss im Browser immer undefiniert
     und der Quellenfilter zeigte in jeder Einzelstellung null Weine — nur "alle"
     funktionierte, weil es keine der beiden Bedingungen prüft. */
  mp:"marketplace", ch:"swiss" };
D.runs.forEach(run => {
  run.wines = run.wines.map(w => {
    const o = { retailers: [], name: "", style: "", maturity: "", styleLabel: "",
                maturityShort: "", cheapest: "", url: "", vivinoUrl: "", vintage: "" };
    for (const [short, long] of Object.entries(KEYS)) {
      if (short in w) o[long] = w[short];
    }
    if (!o.retailers.length && o.cheapest) o.retailers = [o.cheapest];
    return o;
  });
});
/* So viele Zeilen auf einmal. Vorher standen 400 fest im Dokument: bei 623 Weinen
   waren 223 nur über „Filter verfeinern" erreichbar, und die Tabelle allein trug
   über 800 Tabstopps. */
const PAGE = 50;
/* Rotwein ist vorgewählt — er macht den grössten Teil des Sortiments aus, und wer
   etwas anderes sucht, klickt einmal. Ohne Vorauswahl beginnt jeder Besuch mit einer
   Liste, in der Schaumwein, Süsswein und „unbekannt" dazwischenliegen. Ein Klick auf
   „Rotwein" hebt die Vorauswahl wieder auf. */
const STANDARD_SORTE = "rot";
/* "alle" = beide Welten, "ch" = nur Schweizer Handel, "mp" = nur Vivino-Marktplatz.
   Vorgewählt sind beide: der Marktplatz liefert in die Schweiz und gehört damit zur
   Auswahl. Damit die gemeinsame Liste vergleichbar bleibt, wird in dieser Ansicht
   die über beide Welten gerechnete Preis-Leistungs-Zahl verwendet — siehe
   valueOf(). */
const STANDARD_QUELLE = "alle";
/* Die Standardauswahl beantwortet die häufigste Frage: ein guter Rotwein für den
   Alltag. Ohne Grenzen eröffnet die Liste mit Flaschen zu dreihundert Franken und
   mit Weinen, die niemand bewertet hat. Ein Klick hebt jede dieser Grenzen auf.

   Note ab 4.2, nicht ab 4.0: eine 4.1 ist die häufigste Note im Bestand und damit
   glattes Mittelfeld. Ab 4.2 beginnt das obere Drittel — das ist die Schwelle, ab
   der sich das Hinschauen lohnt. */
const STANDARD_NOTE = 4.2;
const STANDARD_PREIS = 50;
const S = { run: D.runs[0].id, mat: new Set(), style: new Set([STANDARD_SORTE]),
            shop: new Set(), land: new Set(), src: STANDARD_QUELLE, q: "",
            /* Standard ist Preis-Leistung: „welche Flasche lohnt sich" ist die Frage,
               für die es die Seite gibt. Nach Note allein eröffnete die Liste mit den
               teuersten Flaschen. */
            sort: "value", dir: -1, minRating: STANDARD_NOTE, maxPrice: STANDARD_PREIS,
            onlyBargain: false, hideGrapes: new Set(), noVivino: false,
            onlyFound: false, limit: PAGE };
const esc = s => String(s ?? "").replace(/[&<>"']/g, c =>
  ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
/* Null ist kein Preis. Weine, deren Preisbasis unsicher blieb, kommen ohne Betrag
   in den Bericht — als "CHF 0.00" gedruckt las sich das wie ein Gratisangebot.
   Ein Strich sagt, was gemeint ist: hier steht keine belastbare Zahl. */
const chf = v => (v == null || v === 0) ? "—" : "CHF " + Number(v).toFixed(2)
  .replace(/\B(?=(\d{3})+(?!\d))/, "'");
/* Die Händlernamen tragen den Jahrgang meist schon in sich ("Pomerol AOC 2007
   Château Lafleur"). Ihn dann noch anzuhängen, druckt ihn zweimal — bei den
   allermeisten Weinen. Nur anhängen, wenn er im Namen fehlt. */
/* Für die Etiketten im Diagramm: die ersten Wörter genügen, der Tooltip hat den Rest. */
const kurz = n => { const w = String(n).split(" ");
  return w.slice(0, 3).join(" ") + (w.length > 3 ? "…" : ""); };
/* Dieselbe Regel wie im Diagramm: ab Note 4.2 und bis CHF 20, nur dieser Bereich. */
const istGut = w => w.rating != null && w.rating >= D.good.rating
  && w.price > 0 && w.price <= D.good.price;
const vintageSuffix = w => (w.vintage && !String(w.name).includes(String(w.vintage)))
  ? " " + w.vintage : "";
/* Der Wert, nach dem standardmässig sortiert wird, muss auch dastehen — sonst ist die
   Reihenfolge nicht nachvollziehbar. 0 heisst „genau im Preisniveau". */
/* Zwei Preis-Leistungs-Zahlen liegen bereit: eine je Warenwelt, eine über beide.
   Zeigt die Seite nur eine Welt, gilt deren eigene — sie misst "gut für einen
   Schweizer Ladenwein" bzw. "gut für einen Marktplatzwein". Stehen beide Welten in
   derselben Liste, muss die gemeinsame gelten, sonst würden zwei Zahlen sortiert,
   die nicht dasselbe messen. */
const valueOf = w => (S.src === "alle" ? w.valueScoreAll : w.valueScore);
const valueText = w => {
  if (valueOf(w) == null) return '<span class="meta">—</span>';
  const v = valueOf(w);
  return (v > 0 ? "+" : v < 0 ? "−" : "±") + Math.abs(v).toFixed(2);
};

function currentRun() { return D.runs.find(r => r.id === S.run) || D.runs[0]; }

/* ``ausser`` blendet **eine** Filtergruppe aus. Gebraucht wird das, um zu zählen,
   was eine Kachel dieser Gruppe brächte: für die Frage „wie viele Rotweine gäbe es"
   darf die Sortenauswahl selbst nicht mitzählen, sonst käme bei jeder nicht
   gewählten Sorte null heraus und die ganze Reihe verschwände nach dem ersten
   Klick. Alle anderen Filter zählen sehr wohl — genau das macht die Zahl nützlich. */
function visible(ausser) {
  const q = S.q.trim().toLowerCase();
  return currentRun().wines.filter(w => {
    if (ausser !== "mat" && S.mat.size && !S.mat.has(w.maturity || "?")) return false;
    if (ausser !== "style" && S.style.size && !S.style.has(w.style || "?")) return false;
    /* Die beiden Warenwelten werden nie gemeinsam gezeigt: ihre Preis-Leistungs-
       Zahlen stammen aus getrennten Regressionen und sind untereinander nicht
       vergleichbar. */
    if (ausser !== "src" && S.src === "ch" && !w.swiss) return false;
    if (ausser !== "src" && S.src === "mp" && !w.marketplace) return false;
    if (ausser !== "shop" && S.shop.size && !w.retailers.some(r => S.shop.has(r))) return false;
    if (ausser !== "land" && S.land.size && !S.land.has(w.country || "")) return false;
    // Der bei Vivino gefundene Name gehört in die Suche. Händler benennen Weine oft
    // ohne den Produzenten: Mövenpick führt „Mendoza 2021 Chardonnay Alta Angelica
    // Zapata", Vivino „Catena Zapata Angélica Zapata Chardonnay Alta". Wer nach
    // „Catena" sucht — dem Namen, unter dem das Weingut bekannt ist — fand nichts,
    // obwohl der Wein zugeordnet war.
    if (q) {
      const heu = (w.name + " " + (w.maturityRegion || "") + " " + (w.matchedName || "")
                   + " " + (w.styleLabel || "")).toLowerCase();
      if (!heu.includes(q)) return false;
    }
    // Spaltenfilter greifen hier, nicht erst in der Tabelle: sonst zeigen Diagramm,
    // Zähler und Tabelle drei verschiedene Mengen, und man weiss nicht, welche gilt.
    if (S.minRating != null && !(w.rating != null && w.rating >= S.minRating)) return false;
    if (S.maxPrice != null && !(w.price != null && w.price <= S.maxPrice)) return false;
    if (S.onlyBargain && !(w.bargain != null && w.bargain > 0)) return false;
    if (S.hideGrapes.size && (w.grapes || []).some(g => S.hideGrapes.has(g))) return false;
    if (S.noVivino && w.cheapest === "vivinoshop") return false;
    // "Bei Vivino gefunden" heisst: bestätigter Namensabgleich. Nicht dabei sind
    // fuzzy-Treffer (Name passt nur ungefähr), Produzenten-Mittelwerte und die
    // Weine ohne Eintrag. Das sind genau die gefüllten Punkte im Diagramm.
    if (S.onlyFound && !(w.rating != null && !w.fuzzy)) return false;
    return true;
  });
}

/* ---------------------------------------------------------------- Diagramm */
function chart(list) {
  const pts = list.filter(w => w.rating != null && w.price > 0);
  const box = document.getElementById("chart");
  const card = document.querySelector(".chart");
  // Passt kein Wein zur Auswahl, hat das Diagramm nichts zu sagen — dann ganz weg.
  // Vorher stand hier "Die Tabelle zeigt alle", während die Tabelle leer war.
  // Der Leerzustand gehört an eine Stelle, nicht an zwei widersprechende.
  card.hidden = list.length === 0;
  if (list.length === 0) return;
  if (pts.length < 2) {
    box.innerHTML = '<p class="empty">' +
      (pts.length ? "Nur ein Wein mit Vivino-Note — siehe Tabelle."
                  : "Kein Wein dieser Auswahl hat eine Vivino-Note. Die Tabelle "
                    + "zeigt sie trotzdem, mit Preis und Händler.") +
      "</p>";
    return;
  }
  const W = 900, H = 460, L = 52, R = 16, T = 30, B = 46;
  const pw = W - L - R, ph = H - T - B;
  const xs = pts.map(p => Math.log10(p.price));
  const x0 = Math.min(...xs) - .05, x1 = Math.max(...xs) + .05;
  const ys = pts.map(p => p.rating);
  const y0 = Math.max(1, Math.min(...ys) - .1), y1 = Math.min(5, Math.max(...ys) + .1);
  const sx = v => L + (Math.log10(v) - x0) / (x1 - x0 || 1) * pw;
  const sy = v => T + (1 - (v - y0) / (y1 - y0 || 1)) * ph;

  let g = "";
  for (const v of [3,5,7,10,15,20,30,50,75,100,150,200,300,500,800]) {
    if (Math.log10(v) < x0 || Math.log10(v) > x1) continue;
    g += `<line class="grid" x1="${sx(v)}" y1="${T}" x2="${sx(v)}" y2="${T+ph}"/>`
       + `<text class="tick" x="${sx(v)}" y="${T+ph+17}" text-anchor="middle">${v}</text>`;
  }
  for (let i = 0; i <= 4; i++) {
    const v = y0 + i * (y1 - y0) / 4;
    g += `<line class="grid" x1="${L}" y1="${sy(v)}" x2="${L+pw}" y2="${sy(v)}"/>`
       + `<text class="tick" x="${L-7}" y="${sy(v)+4}" text-anchor="end">${v.toFixed(1)}</text>`;
  }
  /* Trendlinie: die Note, die man für diesen Preis üblicherweise bekommt. Aus dem
     Lauf geschätzt, nicht geraten — dieselbe Regression, aus der der
     Preis-Leistungs-Wert kommt. */
  const fit = (() => {
    const lx = pts.map(p => Math.log10(p.price)), ly = pts.map(p => p.rating);
    const n = lx.length, mx = lx.reduce((s, v) => s + v, 0) / n,
          my = ly.reduce((s, v) => s + v, 0) / n;
    const sxx = lx.reduce((s, x) => s + (x - mx) ** 2, 0);
    if (!sxx) return null;
    const bb = lx.reduce((s, x, i) => s + (x - mx) * (ly[i] - my), 0) / sxx;
    return { a: my - bb * mx, b: bb };
  })();
  const erwartet = v => fit ? fit.a + fit.b * Math.log10(v) : null;

  /* Das markierte Feld ist eine feste Regel: ab Note 4.2 und bis CHF 20, nur dieser
     Bereich. Als Rechteck, weil die Regel absolut ist — nicht als Fläche über der
     Trendlinie: „besser als üblich fürs Geld" trifft auch eine mittelmässige Flasche
     für CHF 8. Die Regel ist eng; ist das Feld leer, sagt es das selbst. */
  const gRating = D.good.rating, gPrice = D.good.price;
  const gut = p => p.rating >= gRating && p.price > 0 && p.price <= gPrice;
  const imFeld = pts.filter(gut);
  const zx = Math.min(L + pw, Math.max(L, sx(gPrice)));
  const zy = Math.min(T + ph, Math.max(T, sy(gRating)));
  const zone = (zx > L + 4 && zy > T + 4)
    ? `<rect class="zone" x="${L}" y="${T}" width="${(zx - L).toFixed(1)}" height="${(zy - T).toFixed(1)}"/>`
      + `<path class="zone-edge" d="M ${L} ${zy.toFixed(1)} L ${zx.toFixed(1)} ${zy.toFixed(1)} L ${zx.toFixed(1)} ${T}"/>`
      + `<text class="zone-t" x="${L + 8}" y="${T + 16}">GUT UND GÜNSTIG</text>`
      + `<text class="zone-s" x="${L + 8}" y="${T + 29}">ab Note ${gRating.toFixed(1)} · bis CHF ${gPrice.toFixed(0)}</text>`
      + `<text class="zone-s" x="${L + 8}" y="${(zy - 9).toFixed(1)}">${imFeld.length} von ${pts.length} Weinen</text>`
    : "";

  const trend = fit
    ? `<line class="trend" x1="${sx(Math.pow(10, x0)).toFixed(1)}" y1="${sy(erwartet(Math.pow(10, x0))).toFixed(1)}"`
      + ` x2="${sx(Math.pow(10, x1)).toFixed(1)}" y2="${sy(erwartet(Math.pow(10, x1))).toFixed(1)}"/>`
    : "";

  /* Nur der Punkt. Die Striche zur Trendlinie standen bei 174 Weinen so dicht, dass
     sie das Feld zugezogen haben — die Abweichung liest man am Abstand zur Linie
     ohnehin ab, und als Zahl steht sie in der Tabelle. Weine im markierten Feld sind
     gefüllt und golden, alle anderen hohl und leise; die Kennung hängt nicht an der
     Farbe allein, das Feld ist beschriftet. */
  const circles = pts.map((p, i) => {
    const cls = gut(p) ? " good" : "";
    const x = sx(p.price).toFixed(1), y = sy(p.rating).toFixed(1);
    /* Ein unsichtbarer Trefferkreis vor jedem Punkt. Zwei Gründe: hohle Punkte haben
       `fill:none`, und damit ist ihre Fläche in SVG nicht anklickbar — es reagierte
       nur die 1 px dünne Kontur. Und mit r=10 ist das Ziel auch mit dem Finger
       oder einer unruhigen Hand erreichbar. */
    return `<circle class="hit" data-i="${i}" cx="${x}" cy="${y}" r="10"/>`
      + `<circle class="pt${cls}" cx="${x}" cy="${y}" r="4"/>`;
  }).join("");

  /* Benannt werden die Weine, die die Regel erfüllen — sie sind der Punkt der
     Markierung. Die Etiketten sitzen rechts der Zonenkante, damit sie deren
     Beschriftung nicht überschreiben, und gestaffelt gegen sich selbst. */
  const labels = imFeld.slice(0, 4).map((p, i) => {
    const ax = sx(p.price), ay = sy(p.rating);
    const tx = zx + 20, ty = T + 26 + i * 16;
    return `<path class="lead" d="M ${(ax + 5).toFixed(1)} ${ay.toFixed(1)} L ${(zx + 9).toFixed(1)} ${ty.toFixed(1)} L ${tx.toFixed(1)} ${ty.toFixed(1)}"/>`
      + `<text class="lead-t" x="${(tx + 3).toFixed(1)}" y="${(ty + 3.5).toFixed(1)}">${esc(kurz(p.name))}`
      + ` <tspan fill="var(--goldtx)">${p.rating.toFixed(1)} · ${chf(p.price)}</tspan></text>`;
  }).join("");

  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img"
      aria-label="Vivino-Note gegen Preis, ${pts.length} Weine. Eine Trendlinie zeigt die Note, die für diesen Preis üblich ist. Markiert ist der Bereich ab Note ${gRating.toFixed(1)} bis CHF ${gPrice.toFixed(0)}: ${imFeld.length} von ${pts.length} Weinen.">
    ${zone}${g}
    <line class="axis" x1="${L}" y1="${T+ph}" x2="${L}" y2="${T}"/>
    <line class="axis" x1="${L}" y1="${T+ph}" x2="${L+pw}" y2="${T+ph}"/>
    <text class="alabel" x="${L+pw/2}" y="${H-8}" text-anchor="middle">Preis pro 75 cl inkl. MwSt (CHF, logarithmisch)</text>
    <text class="alabel" transform="rotate(-90 14 ${T+ph/2})" x="14" y="${T+ph/2}" text-anchor="middle">Vivino-Note (1–5)</text>
    ${trend}<g id="pts">${circles}</g>${labels}</svg>`;

  const tip = document.getElementById("tip"), host = box.querySelector("#pts");
  /* Gerenderte Lage je Punkt, um Häufungen zu finden. Ein kleinerer Radius löst das
     Problem nicht — die Punkte liegen in den Daten aufeinander, nicht bloss optisch.
     Erreichbar werden die verdeckten nur, wenn der Tooltip sie mitnennt. */
  const at = pts.map(p => ({ x: +sx(p.price).toFixed(1), y: +sy(p.rating).toFixed(1) }));
  const clusterOf = i => pts
    .map((_, j) => j)
    .filter(j => Math.abs(at[j].x - at[i].x) <= 5 && Math.abs(at[j].y - at[i].y) <= 5);
  const show = (el, ev) => {
    const i = +el.dataset.i, p = pts[i]; if (!p) return;
    const row = (k, v) => `<div class="r"><span class="k">${k}</span><span>${v}</span></div>`;
    const cluster = clusterOf(i).filter(j => j !== i);
    let h = `<span class="n">${esc(p.name)}${vintageSuffix(p)}</span>`;
    h += row("Vivino", p.rating.toFixed(1) + "/5" + (p.ratingCount ? ` (${p.ratingCount})` : ""));
    if (p.fuzzy) h += row("Achtung", `<span class="warn">Namensabgleich unbestätigt`
      + (p.matchedName ? ` — gefunden: „${esc(p.matchedName)}"` : "") + `</span>`);
    if (p.styleLabel) h += row("Sorte", esc(p.styleLabel));
    if (p.maturityShort) {
      /* Woher die Auskunft stammt, gehört daneben — sonst liest sich die Vinum-Zeile
         wie eine Aussage über genau diesen Wein, obwohl sie für eine ganze Region
         gilt. Vivinos Fenster ist jahrgangsgenau und steht in Klammern dahinter. */
      let m = "<b>" + esc(p.maturityShort) + "</b>";
      if (p.drinkWindow) m += ` <span class="meta">Vivino ${esc(p.drinkWindow)}</span>`;
      h += row("Trinkreife", m);
      if (p.maturityRegion) h += row("Grundlage", `<span class="meta">${esc(p.maturityRegion)}</span>`);
      /* Sind sich die beiden Quellen uneinig, steht das da. Beide behalten ihre
         Stimme; wer es liest, entscheidet selbst. Das ist mehr wert, als wenn eine
         von beiden stillschweigend gewinnt. */
      if (p.maturityConflict) h += row("uneinig", `<span class="warn">${esc(p.maturityConflict)}</span>`);
    }
    if (valueOf(p) != null) h += row("Preis-Leistung", valueText(p));
    h += row("Preis/75cl", chf(p.price));
    h += row("Händler", esc((D.retailers.find(r => r.key === p.cheapest) || {}).name || p.cheapest));
    if (p.bargain != null) {
      const c = p.bargain > 0 ? "good" : "bad";
      h += row("gegen Markt", `<span class="${c}">${p.bargain > 0 ? "−" : "+"}`
        + Math.abs(p.bargain).toFixed(0) + "%</span>");
    }
    if (p.falstaff != null) h += row("Falstaff", p.falstaff.toFixed(0) + "/100");
    // Verdeckte Nachbarn benennen, sonst weiss man nicht, dass sie da sind.
    if (cluster.length) {
      h += `<div class="also"><b>${cluster.length} weitere${cluster.length === 1 ? "r" : ""}`
        + ` Wein${cluster.length === 1 ? "" : "e"} an dieser Stelle</b>`
        + cluster.slice(0, 4).map(j => {
            const o = pts[j];
            return `<div class="r"><span>${esc(o.name).slice(0, 38)}</span>`
              + `<span class="k">${o.rating.toFixed(1)} · ${chf(o.price)}</span></div>`;
          }).join("")
        + (cluster.length > 4
            ? `<div class="k">… und ${cluster.length - 4} weitere — in der Tabelle</div>`
            : "")
        + `</div>`;
    }
    tip.innerHTML = h; tip.classList.add("on"); place(ev);
  };
  const place = ev => {
    const m = 14, w = tip.offsetWidth, h = tip.offsetHeight;
    let x = ev.clientX + m, y = ev.clientY + m;
    if (x + w > innerWidth - 8) x = ev.clientX - w - m;
    if (y + h > innerHeight - 8) y = ev.clientY - h - m;
    tip.style.left = Math.max(8, x) + "px"; tip.style.top = Math.max(8, y) + "px";
  };
  /* Über data-i statt über die Klasse: so greift es am Trefferkreis wie am Punkt. */
  const treffer = e => e.target.closest && e.target.closest("[data-i]");
  host.addEventListener("mouseover", e => { const el = treffer(e); if (el) show(el, e); });
  host.addEventListener("mousemove", e => { if (tip.classList.contains("on")) place(e); });
  host.addEventListener("mouseout", () => tip.classList.remove("on"));
  /* Auf Touch gibt es kein Hover. Zwischen 721 und 900 px ist das Diagramm sichtbar
     — dort waren die Tooltips bisher unerreichbar, weil nur Maus-Ereignisse hingen.
     Erstes Antippen zeigt den Wein, zweites Antippen öffnet ihn. */
  let armed = null;
  host.addEventListener("click", e => {
    const el = treffer(e); if (!el) return;
    const p = pts[+el.dataset.i];
    const touch = !matchMedia("(hover: hover)").matches;
    if (touch && armed !== el) {
      armed = el;
      show(el, e.touches ? e.touches[0] : e);
      return;
    }
    armed = null;
    const href = p && (p.url || p.vivinoUrl);
    if (href) window.open(href, "_blank", "noopener");
  });
  // Tippen daneben schliesst den Tooltip wieder.
  addEventListener("pointerdown", e => {
    if (!treffer(e)) {
      armed = null; tip.classList.remove("on");
    }
  }, { passive: true });
}


/* Grob prüfen, ob Händler- und Fundname dasselbe sagen — dann ist die Zeile nur
   Wiederholung. Verglichen werden die Wörter, nicht die Zeichenfolge. */
function sameWine(a, b) {
  const w = t => new Set(String(t || "").toLowerCase()
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9 ]+/g, " ").split(/\s+/).filter(x => x.length > 2));
  const A = w(a), B = w(b);
  if (!A.size || !B.size) return false;
  let n = 0; B.forEach(x => { if (A.has(x)) n++; });
  return n === B.size;
}
/* ----------------------------------------------------------------- Tabelle */
function table(list) {
  const box = document.getElementById("table");
  if (!list.length) { box.innerHTML = '<p class="empty">Kein Wein passt zu dieser Auswahl.</p>'; return; }
  const shopName = k => (D.retailers.find(r => r.key === k) || {}).name || k;
  // Leere Werte sortieren immer nach unten, in beiden Richtungen. Ein Wein ohne Note
  // ist keine 0 — er würde sonst bei aufsteigender Sortierung die Liste anführen.
  const KEYS = {
    name:    w => (w.name || "").toLowerCase(),
    rating:  w => w.rating,
    price:   w => w.price,
    shop:    w => shopName(w.cheapest).toLowerCase(),
    bargain: w => w.bargain,
    value:   w => valueOf(w),
  };
  const key = KEYS[S.sort] || KEYS.value;
  const sorted = list.slice().sort((a, b) => {
    const x = key(a), y = key(b);
    const xe = x == null || x === "", ye = y == null || y === "";
    if (xe && ye) return 0;
    if (xe) return 1;
    if (ye) return -1;
    if (typeof x === "string") return S.dir * x.localeCompare(y, "de");
    return S.dir * (x - y);
  });
  const rows = sorted.slice(0, S.limit).map(w => {
    const vivino = w.rating != null
      ? `<a href="${esc(w.vivinoUrl)}" target="_blank" rel="noopener">${w.rating.toFixed(1)}/5</a>`
        + (w.ratingCount ? ` <span class="meta">(${w.ratingCount})</span>` : "")
        + (w.fuzzy ? ` <span class="warn" title="Namensabgleich unbestätigt">?</span>` : "")
        // Den gefundenen Namen ausschreiben, wenn er vom Händlernamen abweicht.
        // Ein Tooltip genügt dafür nicht: auf dem Handy gibt es kein Hover, und ohne
        // den Namen ist nicht nachprüfbar, welcher Vivino-Wein gemeint ist — genau
        // die Frage, die man bei einem "?" als Erstes hat.
        + (w.matchedName && !sameWine(w.name, w.matchedName)
            ? `<br><span class="matched">→ ${esc(w.matchedName)}</span>` : "")
      : w.wineryRating != null
        ? `<a href="${esc(w.vivinoUrl)}" target="_blank" rel="noopener" class="meta">nur Produzenten-Ø `
          + w.wineryRating.toFixed(1) + "/5</a>"
        : `<a href="${esc(w.vivinoUrl)}" target="_blank" rel="noopener" class="meta">keine Note</a>`;
    const bargain = w.bargain == null ? '<span class="meta">—</span>'
      : `<span class="${w.bargain > 0 ? "good" : "bad"}">${w.bargain > 0 ? "−" : "+"}`
        + Math.abs(w.bargain).toFixed(0) + "%</span>";
    const shop = w.url ? `<a href="${esc(w.url)}" target="_blank" rel="noopener">${esc(shopName(w.cheapest))}</a>`
                       : esc(shopName(w.cheapest));
    const vs = vintageSuffix(w);
    return `<tr>
      <td data-l="Wein"><span class="wine">${esc(w.name)}</span>
        ${vs ? `<span class="meta">${vs}</span>` : ""}
        ${w.styleLabel || w.maturityShort ? "<br>" : ""}
        ${w.styleLabel ? `<span class="pill">${esc(w.styleLabel)}</span>` : ""}
        ${w.maturityShort ? `<span class="pill">${esc(w.maturityShort)}</span>` : ""}
        ${istGut(w) ? `<br><span class="marker">◆ gut und günstig</span>` : ""}</td>
      <td data-l="Preis-Leistung" class="pl${valueOf(w) == null ? " noval" : ""}${
        (valueOf(w) ?? 0) < 0 ? " neg" : ""}">${valueText(w)}</td>
      <td data-l="Vivino">${vivino}</td>
      <td data-l="Preis/75cl" class="num">${chf(w.price)}</td>
      <td data-l="Wo kaufen">${shop}</td>
      <td data-l="gegen Markt" class="num${w.bargain == null ? " noval" : ""}">${bargain}</td>
    </tr>`;
  }).join("");
  const COLS = [
    ["name", "Wein", ""], ["value", "Preis-Leistung", "num"], ["rating", "Vivino", ""],
    ["price", "Preis/75cl", "num"], ["shop", "Wo kaufen", ""],
    ["bargain", "gegen Markt", "num"],
  ];
  const head = COLS.map(([k, label, cls]) => {
    const on = S.sort === k;
    const arrow = on ? (S.dir < 0 ? " ▾" : " ▴") : "";
    return `<th class="${cls}${on ? " sorted" : ""}"><button type="button" class="sortbtn"`
      + ` data-col="${k}" aria-label="Nach ${esc(label)} sortieren">${esc(label)}${arrow}</button></th>`;
  }).join("");
  const rest = sorted.length - S.limit;
  box.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table>`
    + (rest > 0
        ? `<p class="more"><button type="button" id="more">Weitere ${Math.min(rest, PAGE)} anzeigen</button>`
          + `<span class="meta"> ${S.limit} von ${sorted.length} angezeigt</span></p>`
        : sorted.length > PAGE
          ? `<p class="more"><span class="meta">Alle ${sorted.length} angezeigt</span></p>`
          : "");
  const more = box.querySelector("#more");
  // Nur nachladen, nicht neu filtern: der Blick soll nicht nach oben springen.
  if (more) more.addEventListener("click", () => { S.limit += PAGE; table(list); });

  box.querySelectorAll(".sortbtn").forEach(b => b.addEventListener("click", () => {
    const col = b.dataset.col;
    // Gleiche Spalte nochmal = Richtung wechseln. Neue Spalte startet in der
    // Richtung, die man dort erwartet: Text A→Z, Zahlen gross→klein.
    if (S.sort === col) S.dir = -S.dir;
    else { S.sort = col; S.dir = (col === "name" || col === "shop") ? 1 : -1; }
    syncSort();
    render();
  }));
}

/* ------------------------------------------------------------------ Filter */
/* Ändert sich die Auswahl, beginnt die Liste wieder bei der ersten Seite — sonst
   stehen nach einem Filterwechsel mehrere Hundert Zeilen einer anderen Menge da. */
function refilter() { S.limit = PAGE; render(); }

function chip(label, pressed, onClick, extra = "", anzahl = null) {
  const b = document.createElement("button");
  b.type = "button"; b.className = "chip"; b.setAttribute("aria-pressed", String(pressed));
  b.innerHTML = extra + esc(label)
    + (anzahl != null ? ` <span class="n">${anzahl}</span>` : "");
  /* Die Kennung überlebt den Neuaufbau der Reihe und trägt den Fokus zurück. */
  b.dataset.chip = label;
  b.addEventListener("click", () => { onClick(); refilter(); });
  return b;
}

/* Wie viele Weine brächte jede Kachel einer Gruppe, wenn man sie wählte?
   Gezählt wird über ``visible(gruppe)`` — also mit allen anderen Filtern, aber ohne
   die eigene Auswahl. ``schluessel`` sagt, welchen Wert ein Wein für diese Gruppe
   trägt; ein Wein kann mehrere haben (er steht bei zwei Händlern). */
function zaehlen(gruppe, schluessel) {
  const n = new Map();
  for (const w of visible(gruppe)) {
    for (const k of schluessel(w)) n.set(k, (n.get(k) || 0) + 1);
  }
  return n;
}

/* Kacheln ohne Treffer werden weggelassen statt ausgegraut.
   Ausgegraut hiesse: eine Reihe voller toter Knöpfe, durch die man sich lesen muss.
   Weggelassen zeigt die Reihe genau das, was die aktuelle Auswahl noch hergibt —
   und ein Blick genügt.

   Eine *gewählte* Kachel bleibt immer stehen, auch bei null: sonst verschwände der
   Knopf, mit dem man die Auswahl wieder aufhebt, und die Seite liesse sich nicht
   mehr in den Ausgangszustand bringen. Das ist der Fall, der bei „Champagner +
   Mövenpick + bis CHF 50" auftrat: null Treffer, und beide Kacheln müssen sichtbar
   bleiben. */
function chipMitZahl(label, key, gewaehlt, anzahl, onClick) {
  if (!anzahl && !gewaehlt) return null;
  return chip(label, gewaehlt, onClick, "", anzahl);
}

function buildFilters() {
  /* Der Fokus überlebt den Neuaufbau. Ohne das springt er nach jedem Klick auf den
     Seitenanfang, und wer mit der Tastatur filtert, verliert die Stelle. */
  const vorher = document.activeElement && document.activeElement.dataset
    ? document.activeElement.dataset.chip : null;
  const run = document.getElementById("fRun"); run.innerHTML = "";
  // Ein einzelner Lauf ist keine Wahl. Die Gruppe kostet sonst Legende plus
  // Chipzeile auf dem knappsten Platz der Seite — dem ersten Handy-Bildschirm.
  // Das Datum steht ohnehin schon in der Stand-Zeile darüber.
  document.getElementById("runBox").hidden = D.runs.length < 2;
  D.runs.forEach(r => run.append(chip(
    r.label, S.run === r.id, () => { S.run = r.id; },
    `<span class="n">${r.wines.length}</span>&nbsp;`)));

  const toggle = (set, key) => () => set.has(key) ? set.delete(key) : set.add(key);
  const anh = (el, c) => { if (c) el.append(c); };

  const nMat = zaehlen("mat", w => [w.maturity || "?"]);
  const mat = document.getElementById("fMat"); mat.innerHTML = "";
  // Kein Farbpunkt: die Beschriftung sagt dasselbe, und dieselbe Farbe stand vorher
  // im Diagramm für einen Händler.
  D.maturities.forEach(m => anh(mat, chipMitZahl(
    m.label, m.key, S.mat.has(m.key), nMat.get(m.key) || 0, toggle(S.mat, m.key))));
  anh(mat, chipMitZahl("keine Angabe", "?", S.mat.has("?"), nMat.get("?") || 0,
                       toggle(S.mat, "?")));

  const nStyle = zaehlen("style", w => [w.style || "?"]);
  const st = document.getElementById("fStyle"); st.innerHTML = "";
  D.styles.forEach(s => anh(st, chipMitZahl(
    s.label, s.key, S.style.has(s.key), nStyle.get(s.key) || 0, toggle(S.style, s.key))));

  /* Die Quellenreihe bekommt Zahlen, aber keine Kachel wird ausgeblendet: sie ist
     eine Entweder-oder-Wahl, und wer versehentlich in einer leeren Welt landet,
     braucht den Weg zurück nach „alle". Ein verschwundener Knopf wäre eine
     Sackgasse. */
  const ohneQuelle = visible("src");
  const nSrc = {
    alle: ohneQuelle.length,
    ch: ohneQuelle.filter(w => w.swiss).length,
    mp: ohneQuelle.filter(w => w.marketplace).length,
  };
  const sr = document.getElementById("fSrc"); sr.innerHTML = "";
  [["alle", "alle"], ["ch", "Schweizer Handel"], ["mp", "Vivino-Marktplatz"]].forEach(([k, label]) => {
    sr.append(chip(label, S.src === k, () => { S.src = k; S.shop.clear(); render(); },
                   "", nSrc[k]));
  });

  /* Die Zahl steht neu in der Kachel und zählt die *aktuelle* Auswahl, nicht den
     ganzen Bestand — darum trägt der Schlüssel den Ländernamen ohne Klammer. */
  const nLand = zaehlen("land", w => [w.country || ""]);
  const la = document.getElementById("fLand"); la.innerHTML = "";
  D.countries.forEach(c => anh(la, chipMitZahl(
    c.key, c.key, S.land.has(c.key), nLand.get(c.key) || 0, toggle(S.land, c.key))));

  const nShop = zaehlen("shop", w => w.retailers || []);
  const sh = document.getElementById("fShop"); sh.innerHTML = "";
  // Ohne Farbpunkt: der Händler trägt hier keine Farbe, nur seinen Namen.
  /* Nur die Händler der gewählten Welt: "Vivino Aktionen" in der Liste der
     Schweizer Händler wäre ein Filter, der nie einen Treffer ergibt. */
  D.retailers.filter(r => S.src === "alle" || (r.key === "vivinoshop") === (S.src === "mp"))
    .forEach(r => anh(sh, chipMitZahl(
      r.name, r.key, S.shop.has(r.key), nShop.get(r.key) || 0, toggle(S.shop, r.key))));

  if (vorher) {
    const zurueck = document.querySelector(`.chip[data-chip="${CSS.escape(vorher)}"]`);
    if (zurueck) zurueck.focus();
  }
}

/* Am Desktop ist der Aufklapper ausgeblendet — dort muss <details> offen sein, sonst
   wäre der Inhalt unerreichbar: kein Griff zum Öffnen, kein Inhalt.
   Geprüft wird die gerenderte Lage der Summary, nicht die Media Query. Die Regel gilt
   dann auch, wenn der Breitenwechsel anders kommt als über ein `change`-Ereignis —
   Fenster ziehen, Drehen, Zoomen. */
const filterBox = document.getElementById("filterBox");
/* Zweiseitig: schmal wird eingeklappt, breit aufgeklappt. Einseitig gedacht bleiben
   die Filter nach einem Wechsel von breit zu schmal offen — Drehen, Fenster ziehen —
   und füllen den ersten Bildschirm wieder. Wer selbst geklickt hat, behält seine
   Wahl; die Ausnahme ist der Desktop, wo der Griff fehlt und offen sein muss. */
let userChoseFilters = false, programmatic = false;
/* Am Klick festgemacht, nicht am `toggle`-Ereignis: das feuert asynchron, und ein
   unmittelbar folgender Resize würde die Wahl sonst wieder überschreiben. */
filterBox.querySelector("summary").addEventListener("click", () => {
  userChoseFilters = true;
});
filterBox.addEventListener("toggle", () => { if (!programmatic) userChoseFilters = true; });
function syncFilterBox() {
  const hidden = getComputedStyle(filterBox.querySelector("summary")).display === "none";
  const want = hidden ? true : (userChoseFilters ? filterBox.open : false);
  if (filterBox.open !== want) {
    programmatic = true; filterBox.open = want; programmatic = false;
  }
}
addEventListener("resize", syncFilterBox);
syncFilterBox();

function activeFilterCount() {
  return S.mat.size + S.style.size + S.shop.size + S.land.size
    + (S.src !== STANDARD_QUELLE ? 1 : 0)
    + (S.q.trim() ? 1 : 0) + (S.minRating != null ? 1 : 0) + (S.maxPrice != null ? 1 : 0)
    + (S.onlyBargain ? 1 : 0) + (S.onlyFound ? 1 : 0) + (S.noVivino ? 1 : 0)
    + S.hideGrapes.size;
}

function render() {
  buildFilters();
  const active = activeFilterCount();
  document.getElementById("filterCount").textContent =
    active ? `· ${active} aktiv` : "· keine aktiv";
  syncFilterBox();
  const list = visible(), total = currentRun().wines.length;
  const rated = list.filter(w => w.rating != null).length;
  // Der Marktpreis fehlt bei der Mehrheit der Weine. Wer nach Ersparnis sortiert,
  // soll wissen, wie viele Weine dazu überhaupt eine Angabe haben — sonst liest
  // sich die Spalte voller "—" wie ein Fehler statt wie eine Lücke in den Daten.
  const priced = list.filter(w => w.bargain != null).length;
  // Treffermenge in die sticky Leiste, Abdeckung darunter: das eine ändert sich mit
  // jedem Klick, das andere ist zum Nachschlagen.
  document.getElementById("count").innerHTML =
    `<b>${list.length}</b> von ${total} Weinen`;
  document.getElementById("coverage").textContent =
    `${rated} davon mit Vivino-Note · ${priced} mit Marktpreis`;
  document.getElementById("tblTitle").textContent =
    list.length === total ? "Alle Weine" : "Gefilterte Weine";
  chart(list); table(list);
}

document.getElementById("q").addEventListener("input", e => { S.q = e.target.value; refilter(); });
const numOrNull = v => v === "" ? null : Number(v);
/* Kopfzeile und Auswahlfeld sind zwei Wege zur selben Sortierung. Nach einem Klick auf
   die Kopfzeile muss das Feld nachziehen, sonst zeigt es etwas anderes an als gilt. */
function syncSort() {
  const el = document.getElementById("fSort");
  const wanted = `${S.sort}:${S.dir}`;
  el.value = [...el.options].some(o => o.value === wanted) ? wanted : "";
}
document.getElementById("fSort").addEventListener("change", e => {
  const [col, dir] = e.target.value.split(":");
  S.sort = col; S.dir = Number(dir); render();
});
document.getElementById("fMinRating").addEventListener("change", e => {
  S.minRating = numOrNull(e.target.value); refilter();
});
document.getElementById("fMaxPrice").addEventListener("change", e => {
  S.maxPrice = numOrNull(e.target.value); refilter();
});
document.getElementById("fBargain").addEventListener("change", e => {
  S.onlyBargain = e.target.checked; refilter();
});
document.getElementById("fNoVivino").addEventListener("change", e => {
  S.noVivino = e.target.checked; refilter();
});
document.getElementById("fFound").addEventListener("change", e => {
  S.onlyFound = e.target.checked; refilter();
});
/* Erst hier, nach den Ereignishandlern: die Auswahlfelder tragen ihren Standardwert
   nicht im HTML, sondern bekommen ihn beim Laden. Ohne das zeigte die Liste 50 Franken
   und Note 4, während in den Feldern "alle" stünde — der Besucher hielte die Auswahl
   für einen Fehler. Die Konstanten bleiben die einzige Quelle: auch „Zurücksetzen"
   greift auf sie zurück. */
document.getElementById("fMinRating").value = String(STANDARD_NOTE);
document.getElementById("fMaxPrice").value = String(STANDARD_PREIS);

/* Die Sorten-Kästchen stehen einmal fest: sie hängen am Bestand, nicht an der
   aktuellen Auswahl. Neu aufzubauen hiesse, sie dem Besucher unter dem Finger
   wegzuziehen. */
(D.grapeFilters || []).forEach(g => {
  const label = document.createElement("label");
  label.className = "cb";
  label.title = `${g.count} Weine im Bestand tragen ${g.label} im Namen`;
  const box = document.createElement("input");
  box.type = "checkbox";
  box.id = "fGrape_" + g.key;
  box.addEventListener("change", e => {
    if (e.target.checked) S.hideGrapes.add(g.key); else S.hideGrapes.delete(g.key);
    refilter();
  });
  label.append(box, document.createTextNode(" " + g.label + " ausblenden"));
  document.getElementById("fGrapes").append(label);
});

document.getElementById("reset").addEventListener("click", () => {
  // Zurücksetzen heisst: auf den Standard, nicht auf leer. Sonst führt der Knopf zu
  // einem Zustand, den man beim Laden nie sieht.
  S.mat.clear(); S.shop.clear(); S.land.clear(); S.q = "";
  S.style = new Set([STANDARD_SORTE]);
  S.src = STANDARD_QUELLE;
  S.minRating = STANDARD_NOTE; S.maxPrice = STANDARD_PREIS;
  S.onlyBargain = false; S.onlyFound = false; S.noVivino = false; S.hideGrapes.clear();
  (D.grapeFilters || []).forEach(g => {
    const box = document.getElementById("fGrape_" + g.key);
    if (box) box.checked = false;
  });
  S.sort = "value"; S.dir = -1; S.limit = PAGE;
  document.getElementById("q").value = "";
  document.getElementById("fMinRating").value = String(STANDARD_NOTE);
  document.getElementById("fMaxPrice").value = String(STANDARD_PREIS);
  document.getElementById("fBargain").checked = false;
  document.getElementById("fNoVivino").checked = false;
  document.getElementById("fFound").checked = false;
  syncSort();
  render();
});
render();
</script>
</body>
</html>
"""

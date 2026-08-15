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
from functools import lru_cache
from collections import Counter
import re
import time
from pathlib import Path
from typing import Any

from ..names import STYLE_LABELS
from ..prices import MARKTPLATZ_QUELLEN
# Die Preis-Leistungs-Rechnung hat einen Besitzer: winecheck.wert. Sie stand hier und
# in aggregate.compute_scores, zwei verschiedene Formeln unter demselben Namen.
from ..wert import (
    PREIS_GEWICHT,
    SELTENHEIT_ANTEIL,
    VALUE_MIN_SAMPLE,
    VALUE_RATING_ANCHOR,
    _add_value_scores,
    _je_typ,
    _value_scores_einer_gruppe,
    _wirksame_note,
)
from ..stiltyp import TYP_LABELS, TYPEN
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
#: Jede Farbe der Seite mit der Schwelle, die ihre **Verwendung** verlangt.
#:
#: Die Trennung nach Verwendung ist der Kern: 4.5 für Kleintext, 3.0 für Grossgrade,
#: Flächen und grafische Objekte. Wo eine Farbe beides muss, gibt es zwei Tokens —
#: ``--gold``/``--goldtx`` und ``--typ1``/``--typ1tx``.
#:
#: Die Typ-Töne fehlten hier, und genau daran ist der Prüfer vorbeigelaufen: sie sind
#: für Diagrammpunkte auf 3:1 bemessen und standen gleichzeitig als 12-px-Text in jeder
#: Tabellenzeile. Drei von vier verfehlten dort 4.5:1 — ``--typ2`` mit 3.42:1 — und
#: ``check_tokens()`` meldete «keine Beanstandung», weil es die vier nicht kannte.
#: Ein Prüfer, dessen Umfang nicht zur Verwendung passt, ist schlimmer als keiner: er
#: gibt Sicherheit, die er nicht deckt. Wer eine Farbe ergänzt, ergänzt sie hier.
_TOKEN_CONTRAST = {
    "hell": (_GROUND_LIGHT, {
        "--ink": ("#1a1719", 4.5), "--muted": ("#6b6668", 4.5),
        "--faint": ("#78716d", 4.5), "--accent": ("#6d1834", 4.5),
        "--goldtx": ("#8a6a3d", 4.5), "--gold": ("#9a7b4f", 3.0),
        "--good": ("#2e7d32", 4.5), "--bad": ("#c62828", 4.5),
        "--line-strong": ("#8f8a86", 3.0),
        # Grafiktöne: Punkte im Diagramm, Ränder der Pillen.
        "--typ1": ("#b4622a", 3.0), "--typ2": ("#a4823f", 3.0),
        "--typ3": ("#6f7d83", 3.0), "--typ4": ("#3d6f86", 3.0),
        # Texttöne: die Versalien in der Pille, 12 px.
        "--typ1tx": ("#a85c27", 4.5), "--typ2tx": ("#886c34", 4.5),
        "--typ3tx": ("#667278", 4.5), "--typ4tx": ("#3d6f86", 4.5),
    }),
    "dunkel": (_GROUND_DARK, {
        "--ink": ("#f0ebec", 4.5), "--muted": ("#a49da0", 4.5),
        "--faint": ("#8b8488", 4.5), "--accent": ("#e0879f", 4.5),
        "--goldtx": ("#d4b587", 4.5), "--gold": ("#c9a877", 3.0),
        "--good": ("#7cc47f", 4.5), "--bad": ("#ef9a9a", 4.5),
        "--line-strong": ("#6f6a6e", 3.0),
        "--typ1": ("#e0915c", 3.0), "--typ2": ("#cfae6d", 3.0),
        "--typ3": ("#9fb0b8", 3.0), "--typ4": ("#7bb4cf", 3.0),
        # Im Dunkeln reichen dieselben Töne für beides: 7.5 bis 8.9:1.
        "--typ1tx": ("#e0915c", 4.5), "--typ2tx": ("#cfae6d", 4.5),
        "--typ3tx": ("#9fb0b8", 4.5), "--typ4tx": ("#7bb4cf", 4.5),
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
        # Wie viele Flaschen man nehmen muss. Nur gesetzt, wenn es mehr als eine ist.
        "units": d.get("units") if (d.get("units") or 1) > 1 else None,
        "url": urls.get(cheapest) or next(iter(urls.values()), ""),
        "market": d.get("market_price"),
        "bargain": d.get("bargain_percent"),
        "style": style,
        "styleLabel": style_label,
        # Stil-Typ. Aeltere Laeufe kennen ihn nicht — dann bleibt er leer, und die
        # Seite behandelt ihn wie "unbekannt", statt einen zu erfinden.
        "typ": d.get("typ") or "",
        "typLabel": d.get("typ_label") or "",
        # Anbauregion: vierte Gruppierungsebene der Preis-Leistungs-Rechnung, und
        # zugleich ein Filter. Die Preisspanne daneben ist gesetzt, nicht gemessen —
        # sie ordnet ein und geht in keine Zahl ein. Siehe winecheck.region.
        "region": d.get("region_key") or "",
        "regionLabel": d.get("region") or "",
        "regionSpanne": d.get("region_preisspanne") or "",
        "typWarum": " · ".join(d.get("typ_signale") or []),
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
    "typ": "ty", "typLabel": "tyl", "typWarum": "tyw",
    "region": "rg", "regionLabel": "rgl", "regionSpanne": "rgs",
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
    # Abnahmemenge: 6 heisst „nur als Sechserkiste zu haben".
    "units": "uq",
    # 1 = stand im Vorlauf noch nicht da. Nur gesetzt, wenn es einen Vorlauf zum
    # Vergleichen gibt — beim ersten Lauf ist kein Wein "neu", sondern alle sind es,
    # und dann sagt die Kennzeichnung nichts.
    "neu": "nu",
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
             # Ob dieser Lauf einen Vorgänger im Cache hatte. Ohne ihn ist "neu" keine
             # Auskunft, und der Filter bleibt weg statt eine leere Menge anzubieten.
             "hasPrev": bool(r.get("hatVorlauf")),
             "wines": [_compact(w) for w in r["wines"]]}
            for r in runs
        ],
        "retailers": [
            {"key": r, "name": names[r], "channel": channels[r]}
            for r in retailers
        ],
        "styles": [{"key": s, "label": STYLE_LABELS[s]} for s in styles],
        # Reihenfolge = Reihenfolge der Achse, nicht Haeufigkeit und nicht
        # alphabetisch. Die Kacheln bilden einen Verlauf ab; wer sie umsortiert,
        # macht aus einer geordneten Achse eine Sammlung von Schubladen.
        "typen": [
            {"key": t, "label": TYP_LABELS[t]}
            for t in TYPEN
            if any(w.get("typ") == t for run in runs for w in run["wines"])
        ],
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

    # Erst zusammenfuegen, dann fuellen. Stil und Verhalten kommen aus echten Dateien
    # unter report/assets; die Auslieferung als *eine* HTML-Datei bleibt — sie ist der
    # Grund, dass die Seite offline und ohne Drittanbieter funktioniert. Nur die Quellen
    # liegen getrennt, weil 1208 Zeilen CSS und JavaScript in einem Python-String von
    # keinem Werkzeug geprueft werden konnten: kein Syntaxfehler fiel auf, keine
    # Formatierung griff, und die Abdeckung von 97 % galt fuer 172 Python-Anweisungen,
    # nicht fuer die Anzeige.
    #
    # Die Reihenfolge ist wesentlich: __PAYLOAD__ steht in app.js, also muss das Skript
    # eingesetzt sein, bevor die Platzhalter gefuellt werden.
    doc = _TEMPLATE.replace("__CSS__", "\n" + _asset("app.css"))
    doc = doc.replace("__JS__", "\n" + _asset("app.js"))
    # Die Schluesselabbildung nur einmal pflegen: das JS bekommt die Umkehrung von
    # _SHORT_KEYS eingesetzt. Vorher stand sie zweimal da, je Richtung einmal, und ein
    # fehlendes Paar hat schon einen Ausfall gekostet — w.swiss war im Browser immer
    # undefiniert, und der Quellenfilter zeigte in jeder Einzelstellung null Weine.
    doc = doc.replace(
        "__KEYS__",
        json.dumps({kurz: lang for lang, kurz in _SHORT_KEYS.items()},
                   ensure_ascii=False, sort_keys=True),
    )
    doc = doc.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))
    doc = doc.replace("__TITLE__", html.escape(title))
    doc = doc.replace("__SOURCE_NAME__", html.escape(SOURCE_NAME))
    # Die Schwellen nicht ausschreiben, sondern einsetzen. Sie standen zweimal da —
    # als Konstante und als Prosa — und liefen auseinander: Commit e79e008 hob
    # GOOD_RATING_MIN auf 4.3, der Satz tausend Zeilen weiter blieb bei 4.2 stehen.
    # Die veroeffentlichte Seite behauptete damit eine Regel, die sie nicht anwandte.
    doc = doc.replace("__GOOD_RATING__", f"{GOOD_RATING_MIN:g}")
    doc = doc.replace("__GOOD_PRICE__", f"{GOOD_PRICE_MAX:g}")
    doc = doc.replace("__SOURCE_PAGE__", html.escape(SOURCE_PAGE))
    doc = doc.replace("__STAMP__", html.escape(datetime_ch()))
    doc = doc.replace("__MARK__", SVG_MARK)
    p.write_text(doc, encoding="utf-8")

    # Die Rasterfassung des Zeichens muss neben der Seite liegen: iOS lädt für den
    # Startbildschirm ausschliesslich PNG. Fehlt sie, zeigt das Telefon wieder ein
    # graues Feld mit dem ersten Buchstaben des Titels.
    schreibe_icons(p.parent)
    return p


#: Stil und Verhalten der Seite. Getrennte Dateien, damit sie pruefbar sind; beim
#: Bauen werden sie eingesetzt, sodass genau eine HTML-Datei herauskommt.
_ASSETS = Path(__file__).resolve().parent / "assets"


@lru_cache(maxsize=4)
def _asset(name: str) -> str:
    """Eine Datei aus ``report/assets`` lesen.

    Zwischengespeichert, weil der Seitenbau sie je Lauf mehrfach anfasst und sich
    waehrend eines Laufs nichts an ihr aendert.
    """
    return (_ASSETS / name).read_text(encoding="utf-8")


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
<style>__CSS__</style>
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
    <!-- Der Typ steht neben der Sorte, nicht darunter: er ist die zweite Achse
         derselben Frage "was fuer ein Wein ist das". Die Reihenfolge der Kacheln ist
         die Reihenfolge der Achse und darf nicht alphabetisch sortiert werden. -->
    <fieldset><legend>Typ</legend><div class="chips" id="fTyp"></div></fieldset>
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
        <!-- Steht zuerst, weil es die Frage ist, mit der man eine Seite wieder aufruft:
             was ist seit letzter Woche dazugekommen. Wird ausgeblendet, wenn es keinen
             Vorlauf zum Vergleichen gibt. -->
        <label class="cb" id="fNeuBox" hidden title="Weine, die im Vorlauf noch nicht dabei waren"><input type="checkbox" id="fNeu"> nur neu seit dem letzten Lauf</label>
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
       <b>gut und günstig</b>: ab Note __GOOD_RATING__ und bis CHF __GOOD_PRICE__.</p>
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
    <!-- Ein Hinweis zur Bedienung darf hier stehen, die Methodik nicht.
         Auf dem Handy standen vor dem ersten Wein zwei Absätze Erklärung, gut einen
         Bildschirm hoch — man scrollte durch die Begründung einer Zahl, die man noch
         nicht gesehen hatte. Wer wissen will, wie gerechnet wird, sucht danach; wer
         eine Flasche sucht, will die Liste. Die Erläuterungen stehen darum unter der
         Tabelle, direkt an dem, was sie erklären. -->
    <p class="tblnote colhint">Spaltentitel antippen sortiert, nochmal antippen kehrt um</p>
    <div id="table"></div>
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
    <!-- Der Typ ist die Korrekturvariable zur Kennzahl darueber und braucht darum
         dieselbe Offenheit: was ist gemessen, was ist abgeleitet, was geschaetzt. -->
    <p class="tblnote"><b>Typ</b> ist aus Name, Vivino-Stil und Vivinos gemessener
       Geschmacksstruktur abgeleitet, nicht verkostet. Er beschreibt die
       <b>Machart, nicht die Qualität</b> — ein straffer Wein ist nicht besser als ein
       fruchtsüsser, er verträgt nur keinen Vergleich mit ihm.
       „Fruchtsüss" heisst dabei nicht „süss": diese Weine sind meist gesetzlich
       trocken. Der süsse Eindruck entsteht aus Restzucker, hohem Alkohol,
       malolaktischem Ausbau und neuem Holz zusammen — nicht aus zugesetztem Zucker.
       Ein <b>?</b> heisst, dass der Typ nur geschätzt ist. Der Grund steht bei jedem
       Wein daneben; ohne Begründung wird kein Typ angezeigt.</p>
  </div>
  </main>

  <footer>
    <!-- Anlass war eine Meldung mit drei Worten — „preis finde ich nicht" — und sie traf
         zu: der Pio Cesare Barolo 2016 stand mit CHF 45.47 in Vivinos Angebotsdaten,
         vinpark.ch verlangt CHF 57.65. Kein veralteter Cache, Vivino liefert die 45.47
         weiterhin. Die Stichprobe steht im Satz, weil eine Warnung ohne Zahl entweder
         überlesen oder überbewertet wird. -->
    <p><b>Preise beim Vivino-Marktplatz.</b> Dort vermittelt Vivino nur — verkauft wird
       von Dritten (vinpark.ch, vino.com, chezgrisoni.ch und andere). Der Betrag stammt
       aus Vivinos Angebotsdaten und wird <b>nicht</b> auf der Seite des Verkäufers
       nachgeprüft, anders als bei den Schweizer Händlern, deren Preise von ihrer eigenen
       Seite gelesen werden. In einer Stichprobe von zwölf Angeboten stand Vivinos Betrag
       bei vier nicht auf der Verkäuferseite — ausverkauft, Preis inzwischen anders, oder
       nur der Referenzpreis vorhanden; in einem nachgeprüften Fall lag Vivino 21 % zu
       tief. Vor dem Kauf dem Verweis folgen und den Preis dort ansehen.</p>
    <p><b>Bewertungen</b> von <a href="https://www.vivino.com" target="_blank" rel="noopener">Vivino</a>.
       Die Achse zeigt ausschliesslich die Vivino-Note in ihrer eigenen Skala 1–5 —
       Falstaff- und andere Kritikerpunkte stehen in der Tabelle, aber nicht auf der
       Achse: zwei Bewertungsgrundlagen auf einer Achse sind nicht vergleichbar.</p>
    <!-- Zwei Quellen, und sie widersprechen sich gelegentlich. Genau das soll man
         sehen: die eine ist redaktionell und grob, die andere fein und ungeprüft.
         Eine davon stillschweigend zu bevorzugen wäre eine Entscheidung, die der
         Seite nicht zusteht. -->
    <p><b>Trinkreife</b> aus zwei Quellen, die nebeneinander stehen und sich nicht
       ersetzen. Die <a href="__SOURCE_PAGE__" target="_blank" rel="noopener">__SOURCE_NAME__</a>
       ist redaktionell geprüft, gilt aber für <b>Region und Weinart</b> und nicht für
       die einzelne Flasche — ein schwacher Wein aus einem starken Jahrgang bekommt
       dort dieselbe Auskunft wie ein grosser. Vivino nennt daneben ein
       <b>Trinkfenster je Wein und Jahrgang</b>, aus Nutzerangaben und damit feiner,
       aber ungeprüft. Wo beide sich widersprechen, steht das an der Zeile, statt dass
       eine Quelle die andere überschreibt. Die <b>Sorte</b> stammt von Vivinos
       Weindatenbank, sonst aus dem Namen; das <b>Herkunftsland</b> ebenso.</p>
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

<script>__JS__</script>
</body>
</html>
"""

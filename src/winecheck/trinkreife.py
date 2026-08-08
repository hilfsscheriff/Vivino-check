"""Trinkreife aus der Vinum-Jahrgangstabelle.

Keine der erreichbaren Quellen führt Trinkreife als Datenfeld: Vivino hat sie nicht
(232 Feldpfade geprüft, die einzigen "from"-Treffer sind Preisfelder, und die
``cellar``-Treffer sind UI-Texte für den *eigenen* Weinkeller des Nutzers), Prodega
nennt sie nirgends, Falstaff ist gesperrt.

Es gibt aber die **Vinum-Trinkreifetabelle**, die Mövenpick als Sponsoringpartner als
PDF veröffentlicht — und zwar als *Text*-PDF, nicht als Bild. OCR ist also nicht nötig.

Aufbau des PDF
--------------
Zwei Spaltenblöcke pro Seite (links x≈30–320, rechts x≈429–720), je mit eigener
Kopfzeile aus den Jahrgängen 25 … 10 und einer Spalte "Ältere Spitzenjahre". Dass
zeilenweises Extrahieren die Blöcke vermischt, ist der Grund für die
Koordinatenauswertung hier: ``extract_text()`` schrieb "Wallis" und "Steiermark" in
dieselbe Zeile.

Drei Dinge stecken nicht im Text, sondern in der Grafik:

* **Weinart** — ein Weinglas links am Zeilenanfang. Gelb ist Weisswein, rot Rotwein.
  Die Reihenfolge ist *nicht* durchgehend weiss-dann-rot: bei Burgenland steht Rot
  zuerst. Eine Annahme über die Reihenfolge wäre falsch gewesen.
* **Jahrgangsqualität** — die Hintergrundfarbe der Zelle: grau mittelmässig, hellgrün
  gut bis sehr gut, dunkelgrün exzellent.
* **Leere Zellen** — "Weine dieses Jahres hätte man besser schon getrunken". Im Text
  fehlen sie einfach, weshalb Zeilen mit 13 statt 16 Codes auftauchen. Nur über die
  x-Position ist erkennbar, *welche* Jahrgänge fehlen.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import pdfplumber
import yaml

#: Quelle. Erscheint mitsamt Abrufdatum in der erzeugten YAML.
SOURCE_URL = (
    "https://www.moevenpick-wein.com/media/wysiwyg/pdf/"
    "Trinkreifetabelle_2026_CH_Moevenpick_V1.pdf"
)
SOURCE_PAGE = "https://www.moevenpick-wein.com/de/magazin/weinwissen/wein-trinkreife-2026"
SOURCE_NAME = "Vinum Trinkreifetabelle 2026 (via Mövenpick)"

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "sources" / "trinkreife.yaml"

#: Die Codes im PDF-Text und was sie laut Legende bedeuten.
MATURITY: dict[str, str] = {
    "g": "zu jung — reifen lassen",
    "k": "macht Spass, wird noch besser",
    "*": "zurzeit höchster Genuss",
    "m": "Zenit überschritten — austrinken",
    "-": "hätte man besser schon getrunken",
}

#: Kurzform für den Report.
MATURITY_SHORT: dict[str, str] = {
    "g": "lagern",
    "k": "kann liegen",
    "*": "jetzt trinken",
    "m": "austrinken",
    "-": "zu alt",
}

#: Sortierung von „am besten jetzt" nach „lieber warten" — für Ranglisten.
MATURITY_ORDER = ("*", "k", "m", "g", "-")

#: Weinstile, deren Trinkfenster der **Stil** bestimmt und nicht die Herkunft.
#:
#: Die Vinum-Tabelle hat als feinste Auflösung Region plus Farbe. Für die meisten
#: Gebiete reicht das, für Süditalien nicht: dieselbe Zeile „Apulien, Basilikata,
#: Kalabrien / rot" deckt den Aglianico del Vulture ab, der zwanzig Jahre kann, und
#: den Alltags-Primitivo, der nach drei Jahren müde wird. Achtzehn Primitivo im
#: Bestand trugen darum „zu jung — reifen lassen", darunter Jahrgang 2025.
#:
#: Diese Liste korrigiert das, aber nur in **eine** Richtung: sie zieht eine
#: Reifeempfehlung auf „jetzt trinken" herunter, sie verlängert nie. Das ist der
#: Unterschied zwischen „die Tabelle ist hier zu grob" und „ich weiss es besser als
#: die Quelle". Wo die Tabelle ohnehin schon zum Trinken rät, ändert sich nichts.
#:
#: Erkennbar an der abweichenden Herkunftsangabe im Bericht: dort steht dann nicht
#: die Vinum-Region, sondern der Stil.
FRUEHTRINKER: dict[str, tuple[str, ...]] = {
    # Der Anlass. Gilt für Primitivo und für den Appassimento-Ausbau, mit dem er
    # meist daherkommt — beide sind auf sofortigen Genuss gemacht.
    "Primitivo, Appassimento": ("primitivo", "appassimento", "appassite"),
    # Ausdrücklich junge Weine. Novello und Nouveau dürfen laut Herkunftsrecht
    # frühestens im Erntejahr in den Verkauf und sind binnen Monaten zu trinken.
    "Novello / Nouveau": ("novello", "nouveau", "primeur"),
}

#: Was den Stil-Vorrang wieder aufhebt.
#:
#: „Primitivo di Manduria **Riserva**" ist genau der Wein, für den die
#: Süditalien-Zeile gemacht ist: längerer Holzausbau, gesetzlich vorgeschriebene
#: Mindestreife, und er kann tatsächlich liegen. Wer solche Weine mit demselben
#: Pinsel anstreicht wie den Supermarkt-Primitivo, macht denselben Fehler noch
#: einmal, nur andersherum.
FRUEHTRINKER_AUSNAHMEN = (
    "riserva", "reserva", "reserve", "gran seleccion", "gran selezione",
)


def _heute() -> int:
    from datetime import date

    return date.today().year


def fenster_code(von: int | None, bis: int | None, heute: int) -> str:
    """Übersetzt ein Trinkfenster in einen Reifecode dieser Tabelle.

    Vivino liefert neben den Jahreszahlen eine eigene ``status``-Zahl. Die wird
    bewusst **nicht** verwendet: was 1, 2, 4 oder 5 bedeutet, steht nirgends
    geschrieben, und die Zuordnung zu den fünf Beschriftungen der Oberfläche
    (``drink_now``, ``hold``, ``past_its_peak`` …) wäre geraten. Château Lafleur
    2007 trägt Status 5 und liegt mitten im Fenster — die naheliegende Deutung
    „über dem Zenit" ist also schon widerlegt.

    Aus zwei Jahreszahlen und dem heutigen Datum folgt dagegen zwingend, was gilt.
    Das ist nachvollziehbar und bleibt richtig, auch wenn Vivino seine Statuszahlen
    umnummeriert.

    ``k`` („macht Spass, wird noch besser") wird für die erste Hälfte des Fensters
    vergeben: der Wein ist trinkbar, hat aber noch Weg vor sich.
    """
    if von is None or bis is None or bis < von:
        return ""
    if heute < von:
        return "g"
    if heute > bis:
        return "m"
    if bis > von and heute < von + (bis - von) / 2:
        return "k"
    return "*"

_STAR = "★"

#: Füllfarben der Weingläser am Zeilenanfang.
_GLASS_WHITE = (0.936, 0.795, 0.0)
_GLASS_RED = (0.627, 0.083, 0.265)

#: Abstand des Weinglases vom Beginn der ersten Jahresspalte. Eng gefasst, damit die
#: Suche nicht in den Nachbarblock greift — links liegt das Glas bei x≈16 und die
#: erste Jahresspalte bei x≈146, rechts bei x≈415 und x≈545.
_GLASS_OFFSET_MAX = 136.0
_GLASS_OFFSET_MIN = 104.0

#: Zellhintergründe = Jahrgangsqualität.
_QUALITY_COLOURS = {
    (0.019, 0.648, 0.209): "exzellent",
    (0.803, 0.888, 0.729): "gut bis sehr gut",
    (0.852, 0.854, 0.855): "mittelmässig",
}

_TOLERANCE = 0.02

#: Die Legende des PDF enthält selbst die Buchstaben g, k und m und wird sonst als
#: Datenzeile gelesen ("Jahrgang bietet m Hat den Zenit überschritten, …").
_LEGEND_MARKERS = (
    "zenit", "jahrgang bietet", "leer:", "austrinken", "reifen lassen",
    "getrunken", "weisswein rotwein", "höchsten genuss", "region", "land /region",
)

#: So viele echte Codes braucht eine Zeile mindestens, damit sie als Daten gilt.
_MIN_CODES = 8


def _is_legend(label: str) -> bool:
    low = label.lower()
    return any(m in low for m in _LEGEND_MARKERS)


@dataclass
class Entry:
    """Eine Zeile der Tabelle: eine Region, eine Weinart."""

    region: str
    wine_type: str                      # "weiss" | "rot" | "unbekannt"
    maturity: dict[int, str] = field(default_factory=dict)   # Jahrgang -> Code
    quality: dict[int, str] = field(default_factory=dict)    # Jahrgang -> Qualität
    older_peaks: list[int] = field(default_factory=list)

    def code(self, vintage: int) -> str | None:
        return self.maturity.get(vintage)


def _colour_matches(colour: Any, target: tuple[float, float, float]) -> bool:
    if not isinstance(colour, (list, tuple)) or len(colour) != 3:
        return False
    return all(abs(float(c) - t) <= _TOLERANCE for c, t in zip(colour, target))


def _quality_for(colour: Any) -> str | None:
    for target, label in _QUALITY_COLOURS.items():
        if _colour_matches(colour, target):
            return label
    return None


def _year_from_header(text: str) -> int | None:
    """``"25"`` ist 2025, ``"99"`` wäre 1999 — die Tabelle führt nur 2010–2025."""
    if not text.isdigit() or len(text) != 2:
        return None
    n = int(text)
    return 2000 + n if n <= 30 else 1900 + n


def _blocks(words: list[dict], page_width: float) -> list[dict[int, float]]:
    """Die Jahres-Kopfzeilen finden und je Block die x-Position pro Jahrgang liefern.

    Das PDF setzt zwei unabhängige Tabellenblöcke nebeneinander; ohne diese Trennung
    landen Regionen aus beiden Blöcken in derselben Zeile.
    """
    candidates = [
        (w, y) for w in words if (y := _year_from_header(w["text"])) is not None
    ]
    if not candidates:
        return []
    # Kopfzeile = die y-Position mit den meisten Jahreszahlen.
    tops: dict[float, list[tuple[dict, int]]] = {}
    for w, y in candidates:
        key = next((k for k in tops if abs(k - w["top"]) < 3), w["top"])
        tops.setdefault(key, []).append((w, y))
    header = max(tops.values(), key=len)

    mid = page_width / 2
    left = {y: w["x0"] for w, y in header if w["x0"] < mid}
    right = {y: w["x0"] for w, y in header if w["x0"] >= mid}
    return [b for b in (left, right) if len(b) >= 8]


def _nearest_year(x: float, columns: dict[int, float], tolerance: float = 7.0) -> int | None:
    best, dist = None, tolerance
    for year, cx in columns.items():
        d = abs(x - cx)
        if d < dist:
            best, dist = year, d
    return best


def parse_pdf(pdf_bytes: bytes) -> list[Entry]:
    """Liest die Tabelle koordinatengenau aus."""
    entries: list[Entry] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            shapes = list(page.rects) + list(page.curves)
            for columns in _blocks(words, page.width):
                entries.extend(_parse_block(words, shapes, columns))
    return entries


def _parse_block(words: list[dict], shapes: list[dict], columns: dict[int, float]) -> list[Entry]:
    first_x = min(columns.values())
    last_x = max(columns.values())

    # Zeilen über die y-Position der Code-Zeichen bilden.
    codes = [
        w for w in words
        if w["text"] in ("g", "k", "m", _STAR)
        and first_x - 8 <= w["x0"] <= last_x + 12
    ]
    rows: dict[float, list[dict]] = {}
    for w in codes:
        key = next((k for k in rows if abs(k - w["top"]) < 4), w["top"])
        rows.setdefault(key, []).append(w)

    out: list[Entry] = []
    for top, cells in sorted(rows.items()):
        centre = _centre(cells[0])
        label = _region_label(words, top, first_x, columns)
        if not label or _is_legend(label):
            continue
        entry = Entry(region=label, wine_type=_wine_type(shapes, centre, first_x))
        for w in cells:
            year = _nearest_year(w["x0"], columns)
            if year is None:
                continue
            entry.maturity[year] = "*" if w["text"] == _STAR else w["text"]
            quality = _cell_quality(shapes, centre, w["x0"])
            if quality:
                entry.quality[year] = quality
        # Fehlende Jahrgänge sind laut Legende "hätte man besser schon getrunken".
        for year in columns:
            entry.maturity.setdefault(year, "-")
        if sum(1 for c in entry.maturity.values() if c != "-") < _MIN_CODES:
            continue
        entry.older_peaks = _older_peaks(words, top, last_x)
        out.append(entry)
    return out


def _centre(word: dict) -> float:
    return (word["top"] + word["bottom"]) / 2


def _region_label(words: list[dict], top: float, first_x: float, columns: dict[int, float]) -> str:
    """Regionsname = die Wörter links der ersten Jahresspalte auf dieser Zeile."""
    block_start = first_x - 130
    parts = [
        w for w in words
        if abs(w["top"] - top) < 4 and block_start <= w["x0"] < first_x - 8
    ]
    label = " ".join(w["text"] for w in sorted(parts, key=lambda w: w["x0"]))
    # Fussnotenmarker aus dem PDF entfernen: "Süd *)", "Südwesten ***)".
    label = re.sub(r"\s*\*+\)\s*$", "", label)
    label = " ".join(label.split()).strip(" -–")
    return label


def _wine_type(shapes: list[dict], centre: float, first_x: float) -> str:
    """Weinart aus der Farbe des Weinglases am Zeilenanfang.

    Das Fenster ist eng an den Blockanfang gebunden. Mit einem offenen ``x0 <
    first_x - 100`` erfasste die Suche beim *rechten* Block auch das Glas der
    gleichhohen Zeile im *linken* Block — dadurch bekamen Amarone und Sfursat
    fälschlich "weiss".
    """
    lo, hi = first_x - _GLASS_OFFSET_MAX, first_x - _GLASS_OFFSET_MIN
    near = sorted(
        (s for s in shapes if abs(_centre(s) - centre) < 5.5 and lo <= s["x0"] < hi),
        key=lambda s: -s["x0"],
    )
    for s in near:
        colour = s.get("non_stroking_color")
        if _colour_matches(colour, _GLASS_RED):
            return "rot"
        if _colour_matches(colour, _GLASS_WHITE):
            return "weiss"
    return "unbekannt"


def _cell_quality(shapes: list[dict], centre: float, x: float) -> str | None:
    for s in shapes:
        if abs(_centre(s) - centre) > 5.5:
            continue
        if s["x0"] - 6 <= x <= s["x1"] + 2:
            quality = _quality_for(s.get("non_stroking_color"))
            if quality:
                return quality
    return None


def _older_peaks(words: list[dict], top: float, last_x: float) -> list[int]:
    """Spalte "Ältere Spitzenjahre" — zweistellige Jahre wie ``01, 99, 95``."""
    parts = [
        w["text"] for w in words
        if abs(w["top"] - top) < 4 and w["x0"] > last_x + 10
    ]
    years: list[int] = []
    for token in " ".join(parts).replace(",", " ").split():
        if token.isdigit() and len(token) == 2:
            n = int(token)
            years.append(2000 + n if n <= 30 else 1900 + n)
    return years


# ------------------------------------------------------------------ Persistenz

def to_yaml(entries: list[Entry], fetched_at: str) -> str:
    data = {
        "source": {
            "name": SOURCE_NAME,
            "pdf": SOURCE_URL,
            "page": SOURCE_PAGE,
            "fetched_at": fetched_at,
            "note": (
                "Jahrgangstabelle von Vinum, als Text-PDF veröffentlicht. Wird jährlich "
                "ersetzt — mit 'wine-check trinkreife' neu einlesen. Weinart stammt aus "
                "der Farbe des Weinglas-Symbols, Jahrgangsqualität aus der "
                "Zellhintergrundfarbe, leere Zellen bedeuten 'hätte man besser schon "
                "getrunken'."
            ),
        },
        "legend": MATURITY,
        "entries": [
            {
                "region": e.region,
                "wine_type": e.wine_type,
                "maturity": {str(y): c for y, c in sorted(e.maturity.items(), reverse=True)},
                "quality": {str(y): q for y, q in sorted(e.quality.items(), reverse=True)},
                "older_peaks": e.older_peaks,
            }
            for e in entries
        ],
    }
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100)


def load(path: Path | str | None = None) -> list[Entry]:
    p = Path(path) if path else DEFAULT_PATH
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out: list[Entry] = []
    for raw in data.get("entries") or []:
        out.append(
            Entry(
                region=raw.get("region") or "",
                wine_type=raw.get("wine_type") or "unbekannt",
                maturity={int(y): c for y, c in (raw.get("maturity") or {}).items()},
                quality={int(y): q for y, q in (raw.get("quality") or {}).items()},
                older_peaks=list(raw.get("older_peaks") or []),
            )
        )
    return out


# ------------------------------------------------------------------ Zuordnung

#: Tabellenregion -> Tokens, die im Weinnamen darauf hindeuten.
#:
#: Die Tabelle ist grob (Toskana, Piemont), Weinnamen sind fein (Bolgheri, Barolo).
#: Diese Übersetzung ist deshalb Handarbeit und bewusst konservativ: was nicht
#: eindeutig zuzuordnen ist, bekommt keine Trinkreife. Eine falsche Region liefert
#: eine falsche Empfehlung, und die wäre schlimmer als eine Lücke.
REGION_TOKENS: dict[str, tuple[str, ...]] = {
    # Schweiz
    "Wallis": ("wallis", "valais", "fendant", "sion", "sierre", "salgesch", "chamoson",
               "leytron", "fully", "vetroz", "humagne", "cornalin", "arvine", "amigne"),
    "Waadt, Neuenburg": ("waadt", "vaud", "lavaux", "chablais", "fechy", "yvorne",
                         "aigle", "dezaley", "epesses", "saint-saphorin", "neuchatel",
                         "neuenburg", "vully", "bonvillars"),
    "Deutschschweiz": ("graubunden", "bundner", "herrschaft", "malans", "flasch", "maienfeld",
                       "jenins", "zurich", "aargau", "schaffhausen", "thurgau", "basel",
                       "luzern", "stgallen", "deutschschweiz", "completer",
                       "raeuschling", "rauschling"),
    "Tessin": ("tessin", "ticino", "sopraceneri", "sottoceneri", "bianco di merlot"),
    "Genf": ("genf", "geneve", "geneva", "satigny", "dardagny"),
    # Italien
    "Piemont -Barolo, Barbaresco": ("barolo", "barbaresco", "langhe", "roero", "gavi",
                                    "monferrato", "nebbiolo", "alba", "piemont", "piemonte",
                                    "arneis", "dolcetto", "nizza"),
    "Barbera": ("barbera",),
    "Toskana -Chianti Classico": ("chianti", "toskana", "toscana", "bolgheri", "maremma",
                                  "carmignano", "cortona", "sangiovese", "supertuscan",
                                  "vernaccia", "morellino"),
    "Montalcino": ("montalcino", "brunello"),
    "Montepulciano": ("montepulciano", "vino nobile"),
    "Veneto -Amarone": ("amarone", "valpolicella", "ripasso", "recioto", "veneto",
                        "venezie", "veronese", "bardolino", "soave", "custoza"),
    "Südtirol": ("sudtirol", "alto adige", "adige", "lagrein", "vernatsch", "schiava",
                 "gewurztraminer bozen"),
    "Friaul": ("friuli", "friaul", "collio", "colli orientali"),
    "Veltlin: Sfursat": ("valtellina", "veltlin", "sfursat", "sforzato"),
    "Süditalien -Apulien, Basilikata, Kampanien": (
        "apulien", "puglia", "primitivo", "salento", "manduria", "negroamaro",
        "salice", "basilikata", "basilicata", "aglianico", "kampanien", "campania",
        "taurasi", "irpinia", "falanghina", "abruzzo", "abruzzen", "molise",
    ),
    "Sizilien": ("sizilien", "sicilia", "siciliane", "etna", "nerodavola", "avola",
                 "grillo", "frappato", "menfi", "noto"),
    # Spanien und Portugal
    "Rioja -Crianza": ("rioja", "rioja crianza"),
    "Reserva, Gran Reserva": ("gran reserva",),
    "Ribera del Duero": ("ribera", "duero", "tempranillo ribera"),
    "Katalonien": ("katalonien", "catalunya", "priorat", "penedes", "montsant", "cava"),
    "Rueda": ("rueda", "verdejo"),
    "Galicien": ("galicien", "galicia", "rias baixas", "albarino", "godello", "valdeorras"),
    "Douro -Rotweine": ("douro", "alentejo", "dao", "bairrada", "portugal"),
    "Vintage Port": ("porto", "vintage port"),
    # Frankreich
    "Bordeaux -Médoc": ("medoc", "margaux", "pauillac", "julien", "estephe", "moulis",
                        "listrac", "haut-medoc", "bordeaux"),
    "Pessac-Léognan": ("pessac", "leognan"),
    "St-Émilion / Pomerol / Fronsac": ("emilion", "pomerol", "fronsac", "castillon",
                                       "lalande"),
    "Sauternes": ("sauternes", "barsac"),
    "Burgund -Côte d’Or (Crus)": ("burgund", "bourgogne", "cote de nuits", "cote de beaune",
                                  "beaune", "pommard", "volnay", "meursault", "gevrey",
                                  "vosne", "nuits", "chambolle", "morey", "aloxe",
                                  "savigny", "mercurey", "givry", "rully", "marsannay"),
    "Chablis (Crus)": ("chablis",),
    "Beaujolais (Crus)": ("beaujolais", "morgon", "fleurie", "brouilly", "moulin-a-vent"),
    "Rhône: -Nord": ("hermitage", "cote-rotie", "rotie", "cornas", "joseph", "crozes"),
    "Süd": ("chateauneuf", "rhone", "gigondas", "vacqueyras", "lirac", "tavel",
               "ventoux", "luberon", "costieres"),
    "Provence": ("provence", "bandol", "cassis", "aix"),
    "Languedoc-Roussillon": ("languedoc", "roussillon", "minervois", "corbieres",
                             "faugeres", "pic saint loup", "liviniere", "pays d'oc", "pays doc"),
    "Jahrgangs-Champagner": ("champagne",),
    "Elsass (Crus)": ("elsass", "alsace",),
    "Loire -Crus (Sancerre, Vouvray etc)": ("loire", "sancerre", "vouvray", "chinon",
                                            "muscadet", "pouilly", "saumur", "bourgueil",
                                            "menetou", "quincy", "anjou"),
    "Südwesten": ("cahors", "madiran", "gaillac", "bergerac", "jurancon", "irouleguy"),
    # Übersee und Rest
    "USA -Kalifornien": ("kalifornien", "california", "napa", "sonoma", "paso robles",
                         "robles", "lodi", "columbia", "washington", "wells"),
    "USA -Oregon": ("oregon", "willamette"),
    "Chile": ("chile", "maipo", "colchagua", "casablanca", "rapel", "aconcagua",
              "curico", "leyda", "limari"),
    "Argentinien": ("argentinien", "argentina", "mendoza", "uco", "salta", "cafayate"),
    "Australien": ("australien", "australia", "barossa", "coonawarra", "mclaren",
                   "hunter", "yarra", "clare", "eden valley"),
    "Südafrika": ("sudafrika", "stellenbosch", "paarl", "swartland", "franschhoek",
                  "western cape", "cape"),
    "Griechenland": ("griechenland", "greece", "nemea", "santorini", "naoussa"),
    "Niederösterreich, Wien": ("niederosterreich", "wachau", "kamptal", "kremstal",
                              "wagram", "wien", "veltliner"),
    "Steiermark": ("steiermark", "vulkanland", "sudsteiermark"),
    "Burgenland": ("burgenland", "leithaberg", "mittelburgenland", "neusiedlersee",
                   "blaufrankisch", "zweigelt"),
    "Ungarn -Tokaj Edelsüss": ("tokaj", "tokaji", "ungarn"),
    "Baden": ("baden",),
    "Württemberg": ("wurttemberg", "trollinger"),
    "Franken, Ostdeutschland": ("franken", "sachsen", "saale"),
    "Mosel": ("mosel", "saar", "ruwer"),
    "Pfalz": ("pfalz",),
    "Rheingau Riesling": ("rheingau",),
    "Rheinhessen": ("rheinhessen",),
    "Nahe, Mittelrhein, Ahr": ("nahe", "mittelrhein"),
    "Ahr": ("ahr",),
}

#: Rot- und Weisswein-Hinweise im Namen, wenn Vivino keine Weinart liefert.
_RED_HINTS = ("rotwein", "rosso", "rouge", "tinto", "red", "merlot", "syrah", "shiraz",
              "cabernet", "pinot noir", "nebbiolo", "sangiovese", "tempranillo",
              "primitivo", "malbec", "barolo", "amarone", "brunello", "zweigelt",
              "blaufrankisch", "lagrein", "aglianico", "negroamaro", "grenache",
              "carmenere", "monastrell", "mourvedre", "petit verdot")
_WHITE_HINTS = ("weisswein", "bianco", "blanc", "blanco", "white", "chardonnay",
                "riesling", "sauvignon blanc", "pinot gris", "pinot grigio", "grigio",
                "chasselas", "fendant", "gruner", "veltliner", "verdejo", "albarino",
                "vermentino", "gewurztraminer", "silvaner", "sylvaner", "muscadet",
                "arneis", "soave", "gavi", "petite arvine", "heida", "johannisberg")


@lru_cache(maxsize=1024)
def _token_re(token: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])")


def _word_in(token: str, haystack: str) -> bool:
    return bool(_token_re(token).search(haystack))


#: Ausdrückliche Farbangaben. Sie schlagen Rebsortennamen: "Ticino DOC Bianco di
#: Merlot … Weisswein" ist ein Weisswein, obwohl "Merlot" darin steht. Ohne diese
#: Rangfolge neutralisierten sich die Signale zu "unbekannt", und der Wein bekam die
#: Trinkreife der Rotwein-Zeile.
_EXPLICIT_RED = ("rotwein", "rosso", "rouge", "tinto", "vino rosso")
_EXPLICIT_WHITE = ("weisswein", "bianco", "blanc", "blanco", "vin blanc", "white wine")
_EXPLICIT_ROSE = ("rosewein", "rose", "rosato", "rosado", "blush")


def guess_wine_type(name: str) -> str:
    """Weinart aus dem Namen, wenn keine bessere Angabe vorliegt.

    Zweistufig: ausdrückliche Farbangaben zuerst, Rebsorten nur als Rückfall.
    Rosé liefert bewusst einen eigenen Wert — die Tabelle führt keine Rosé-Zeilen,
    und ein Rosé bekommt damit korrekt keine Auskunft statt der Rotwein-Reife.
    """
    from .names import strip_accents

    low = strip_accents((name or "").lower())
    if any(_word_in(h, low) for h in _EXPLICIT_ROSE):
        return "rose"
    explicit_red = any(_word_in(h, low) for h in _EXPLICIT_RED)
    explicit_white = any(_word_in(h, low) for h in _EXPLICIT_WHITE)
    if explicit_red != explicit_white:
        return "rot" if explicit_red else "weiss"

    red = any(_word_in(h, low) for h in _RED_HINTS)
    white = any(_word_in(h, low) for h in _WHITE_HINTS)
    if red != white:
        return "rot" if red else "weiss"
    return "unbekannt"


#: Fortsetzungszeilen im PDF tragen ihren Elternnamen nicht mit ("-Süd" steht unter
#: "Rhône:", "-Sauternes" unter "Bordeaux"). Für den Report werden sie hier ergänzt —
#: die Schlüssel bleiben unverändert, damit REGION_TOKENS gültig bleibt.
DISPLAY_NAMES: dict[str, str] = {
    "Süd": "Rhône Süd",
    "Südwesten": "Südwest-Frankreich",
    "Pessac-Léognan": "Bordeaux Pessac-Léognan",
    "St-Émilion / Pomerol / Fronsac": "Bordeaux St-Émilion/Pomerol/Fronsac",
    "Côtes Bdx / Bdx supérieur": "Bordeaux Côtes/supérieur",
    "Pessac-Léognan / Graves / div.": "Bordeaux Graves (weiss)",
    "Sauternes": "Bordeaux Sauternes",
    "Côte d’Or (Crus)": "Burgund Côte d’Or",
    "Chablis (Crus)": "Burgund Chablis",
    "Beaujolais (Crus)": "Burgund Beaujolais",
    "Reserva, Gran Reserva": "Rioja Reserva/Gran Reserva",
    "Montalcino": "Toskana Montalcino",
    "Montepulciano": "Toskana Montepulciano",
    "Barbera": "Piemont Barbera",
    "Vintage Port": "Portugal Vintage Port",
    "Spätlesen": "Loire Spätlesen",
    "Reserva": "Rioja Reserva",
}


def display_region(region: str) -> str:
    return DISPLAY_NAMES.get(region, region)


def _fruehtrinker(low: str) -> str:
    """Welcher Frühtrinker-Stil steckt im Namen — oder keiner?

    ``low`` ist der bereits kleingeschriebene und akzentbefreite Name.
    Zurückgegeben wird die Stilbezeichnung für den Bericht, sonst ein leerer String.
    """
    if any(_word_in(w, low) for w in FRUEHTRINKER_AUSNAHMEN):
        return ""
    for label, marker in FRUEHTRINKER.items():
        if any(_word_in(m, low) for m in marker):
            return label
    return ""


@dataclass
class Match:
    """Eine Trinkreife-Auskunft samt Begründung."""

    code: str
    region: str
    wine_type: str
    vintage: int
    quality: str | None = None
    older_peaks: list[int] = field(default_factory=list)
    #: Gesetzt, wenn der Stil die Regionszeile überstimmt hat — siehe
    #: :data:`FRUEHTRINKER`. Steht dann anstelle der Region im Bericht, damit
    #: sichtbar bleibt, worauf die Auskunft beruht.
    stil: str = ""

    # -- Zweite Meinung ----------------------------------------------------
    #: Vivinos Trinkfenster für genau diesen Wein und Jahrgang. Ersetzt die
    #: Vinum-Auskunft nicht, sondern steht daneben — ausser die Tabelle schweigt,
    #: dann trägt Vivino die Auskunft allein (``quelle == "vivino"``).
    vivino_von: int | None = None
    vivino_bis: int | None = None
    quelle: str = "vinum"

    @property
    def fenster(self) -> str:
        """„2014–2026" für den Bericht, sonst leer."""
        if self.vivino_von is None or self.vivino_bis is None:
            return ""
        return f"{self.vivino_von}–{self.vivino_bis}"

    @property
    def widerspruch(self) -> str:
        """Sagen die beiden Quellen Verschiedenes?

        Beide behalten ihre Stimme; hier steht nur, dass sie sich uneinig sind.
        Wer das liest, kann selbst entscheiden — und das ist mehr wert, als wenn
        eine der beiden stillschweigend gewinnt.
        """
        if self.quelle != "vinum" or not self.fenster:
            return ""
        anderer = fenster_code(self.vivino_von, self.vivino_bis, _heute())
        if not anderer or anderer == self.code:
            return ""
        return f"Vivino: {MATURITY_SHORT.get(anderer, anderer)} ({self.fenster})"

    @property
    def short(self) -> str:
        return MATURITY_SHORT.get(self.code, self.code)

    @property
    def text(self) -> str:
        return MATURITY.get(self.code, self.code)

    @property
    def region_label(self) -> str:
        """Worauf die Auskunft beruht.

        Normalerweise die Zeile der Vinum-Tabelle. Hat der Stil sie überstimmt,
        steht der Stil hier — sonst behauptete der Bericht eine Herkunft für eine
        Aussage, die aus einer anderen Quelle stammt.
        """
        if self.quelle == "vivino":
            return f"Vivino-Trinkfenster {self.fenster}"
        if self.stil:
            return f"{self.stil} (Stil vor Region)"
        return display_region(self.region)

    @property
    def note(self) -> str:
        bits = [f"{self.text} ({self.region_label} {self.wine_type}, Jahrgang {self.vintage})"]
        if self.quality:
            bits.append(f"Jahrgang {self.quality}")
        return ", ".join(bits)


class Table:
    """Nachschlagewerk über der geparsten Tabelle."""

    def __init__(self, entries: list[Entry]):
        self.entries = entries

    @classmethod
    def load(cls, path: Path | str | None = None) -> Table:
        return cls(load(path))

    #: Codes, die eine Reifeempfehlung aussprechen. Nur diese werden vom Stil
    #: überstimmt — „austrinken" oder „zu alt" bleibt stehen, denn ein alter
    #: Primitivo wird durch eine Stilregel nicht wieder jung.
    _REIFT_NOCH = frozenset({"g", "k"})

    def lookup(
        self,
        name: str,
        vintage: int | None,
        wine_type: str = "unbekannt",
        *,
        stil_name: str = "",
    ) -> Match | None:
        """Trinkreife für einen Wein — oder None, wenn nichts Eindeutiges zu sagen ist.

        Ohne Jahrgang, ohne erkennbare Region oder bei widersprüchlichen Kandidaten
        gibt es keine Auskunft. Eine falsche Region liefert eine falsche Empfehlung.
        """
        if not vintage or not self.entries:
            return None
        from .names import strip_accents

        low = strip_accents((name or "").lower())
        # Auf Wortgrenzen prüfen, nicht als Teilstring: "oc" steckt in "DOCa",
        # "bern" in "Cabernet", und damit landete ein Rioja im Languedoc und ein
        # Cabernet in der Deutschschweiz.
        matches: dict[str, int] = {}
        for region, tokens in REGION_TOKENS.items():
            best = max((len(t) for t in tokens if _word_in(t, low)), default=0)
            if best:
                matches[region] = best
        if not matches:
            return None
        # Die spezifischste Region gewinnt: "Rioja Gran Reserva" gehört in die
        # Reserva-Zeile, nicht in die Crianza-Zeile.
        top = max(matches.values())
        regions = [r for r, score in matches.items() if score == top]

        if wine_type == "unbekannt":
            wine_type = guess_wine_type(name)

        candidates = [
            e for e in self.entries
            if e.region in regions and vintage in e.maturity
            and (wine_type == "unbekannt" or e.wine_type == wine_type)
        ]
        if not candidates:
            return None
        codes = {e.maturity[vintage] for e in candidates}
        if len(codes) > 1:
            # Mehrere Regionen oder Weinarten treffen zu und widersprechen sich.
            return None
        best = candidates[0]
        code = best.maturity[vintage]
        # Für die Stilprüfung zählt auch der bei Vivino gefundene Name: Händler
        # lassen die Rebsorte oft weg. "Puglia IGP 2024 Suolo Rosso (Salento)"
        # heisst dort "Suolo Rosso Primitivo - Merlot" — nur so ist er als
        # Primitivo zu erkennen.
        #
        # Ausdrücklich *nur* für den Stil, nicht für die Regionssuche: ein zweiter
        # Name kann eine weitere Herkunft ins Spiel bringen und damit die Zeile
        # wechseln, aus der die Auskunft stammt. Die Stilregel darf präzisieren,
        # sie darf die Quelle nicht verschieben.
        stil = _fruehtrinker(low)
        if not stil and stil_name:
            stil = _fruehtrinker(strip_accents(stil_name.lower()))
        if stil and code in self._REIFT_NOCH:
            # Nur herunterziehen, nie verlängern: die Tabelle ist hier zu grob,
            # nicht falsch. Siehe FRUEHTRINKER.
            code = "*"
        else:
            stil = ""
        return Match(
            code=code,
            region=best.region,
            wine_type=best.wine_type,
            vintage=vintage,
            quality=best.quality.get(vintage),
            older_peaks=best.older_peaks,
            stil=stil,
        )

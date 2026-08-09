"""Stil-Typ: **wie** ein Wein gemacht ist, nicht wie gut er ist.

Warum es das Feld gibt
----------------------
Vivino-Noten sind Publikumsmittelwerte. Weiche, fruchtsüsse, holzgeprägte Weine
erreichen dort verlässlich 4.2 bis 4.4, weil sie kaum jemandem missfallen; straffe,
säure- oder tanninbetonte Weine polarisieren und landen bei 3.9 bis 4.2, auch bei
höherer fachlicher Qualität. Die fruchtsüsse Machart ist zugleich günstig herstellbar
und braucht keine teure Herkunft. Beides zusammen füllt den Quadranten „gut und
günstig" strukturell mit **einem einzigen Geschmacksprofil**.

Die bestehende Preis-Leistungs-Kennzahl normalisiert gegen Weine derselben ``Sorte``
im gleichen Preisband — und ``Sorte`` heisst in diesem Projekt Rotwein, Weisswein,
Rosé, Schaumwein. Ein Primitivo-Appassimento wird damit gegen einen Brunello
gerechnet, weil beide „Rotwein" sind. Genau das ist die Verzerrung.

Die Achse ist **ordinal**: ``fruchtsuess`` → ``weich_modern`` → ``ausgewogen`` →
``straff_herb``. In der Anzeige gehört sie als Verlauf dargestellt, nicht als
unsortierte Gruppe.

Der Typ ist ausdrücklich **keine Qualitätsaussage**. Er sagt nicht, dass ein straffer
Wein besser sei — er sagt, dass man ihn nicht gegen einen fruchtsüssen normalisieren
darf.

Was die Datenlage hergibt, gemessen am 9.8.2026
-----------------------------------------------
Die Kaskade hat drei Stufen mit absteigender Sicherheit; die **erste greifende Stufe
entscheidet**, spätere überschreiben nichts. Vor dem Bauen nachgesehen, was von den
drei Stufen dieses Projekt überhaupt tragen kann:

* **Stufe 1a/1c — Name und Stilmarke: tragen.** Der Weinname ist immer da.
* **Stufe 1b — Analysewerte: tragen heute nicht.** Über 1694 Angebote hinweg enthält
  kein einziges einen Restzucker-, Säure- oder Alkoholwert. Der Code steht trotzdem
  hier: er ist wenige Zeilen, und am Tag, an dem ein Händlerdatenblatt mitgelesen
  wird, ist er der sicherste Weg von allen. Heute feuert er nie, und das soll man
  nachlesen können, statt es zu vermuten.
* **Stufe 2 — Vivino: trägt, und besser als geplant.** Die Explore-Antwort führt pro
  Wein ``taste.structure`` mit gemessenen Werten für Süsse, Tannin und Säure, dazu
  ``user_structure_count`` als Zahl der Urteile, die dahinterstehen. Das ist eine
  *Messung am einzelnen Wein* und schlägt jede Tabelle über Gattungen. Fällt sie aus,
  folgt ``style.baseline_structure`` (der Normalwert seines Stils), danach die
  Stiltabelle.
* **Stufe 3 — Verkostungsnotiz: trägt nicht.** Dieses Projekt liest keine
  Verkostungsnotizen. ``Offer.source_note`` trägt Preis- und Gebindehinweise, Median
  40 Zeichen; die Keyword-Buckets aus der Spec ergeben über den ganzen Bestand
  **null** Treffer. Die Stufe ist implementiert und wird aufgerufen, liefert aber
  ``unbekannt``, solange die Detailseiten der Händler nicht mitgelesen werden. Sie
  vorzutäuschen wäre schlimmer als die Lücke: ein geratener Typ verschiebt eine
  Kennzahl, ohne dass es jemand merkt.

Ohne Begründung kein Typ: jede Einordnung führt ihre Signale im Klartext mit, und die
Anzeige zeigt sie. Ein Wert, den niemand nachprüfen kann, hat in diesem Projekt noch
jedes Mal eine falsche Zahl erzeugt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from .names import strip_accents

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "sources" / "stiltyp.yaml"

#: Die Achse, geordnet von fruchtsüss nach straff. Die Reihenfolge ist Teil der
#: Bedeutung — Filter und Farbverlauf richten sich danach.
TYPEN = ("fruchtsuess", "weich_modern", "ausgewogen", "straff_herb")

#: ``unbekannt`` steht bewusst nicht in :data:`TYPEN`: es ist kein Punkt auf der Achse,
#: sondern das Eingeständnis, keinen zu kennen.
UNBEKANNT = "unbekannt"

TYP_LABELS: dict[str, str] = {
    "fruchtsuess": "Fruchtsüss",
    "weich_modern": "Weich & modern",
    "ausgewogen": "Ausgewogen",
    "straff_herb": "Straff & herb",
    UNBEKANNT: "–",
}

#: Ab hier gilt ein Wein als fruchtsüss, darunter als weich-modern und so weiter.
#: Die Zahlen sind **nicht** geraten, sondern an der Verteilung der echten
#: Strukturwerte festgemacht — siehe :func:`typ_aus_score` für die Begründung.
SCHWELLE_FRUCHTSUESS = 0.40
SCHWELLE_WEICH = 0.10
SCHWELLE_AUSGEWOGEN = -0.10

#: So viele Nutzerurteile muss eine Geschmacksstruktur tragen, damit sie zählt.
#: Darunter ist der Mittelwert von einzelnen Meinungen getrieben und schwankt
#: stärker als der Unterschied zwischen zwei Nachbarkategorien.
MIN_STRUKTUR_URTEILE = 15

#: Unter so vielen Keyword-Treffern insgesamt sagt Stufe 3 nichts. Zwei Wörter in
#: einem Werbetext sind keine Beschreibung eines Weins.
MIN_KEYWORD_TREFFER = 3


def _falten(text: str) -> str:
    """Vergleichsform für das Matchen von Tokens.

    Akzente weg — das erledigt :func:`winecheck.names.strip_accents`, inklusive ``ß`` —
    und zusätzlich die deutsche Umschrift ``ae``/``oe``/``ue`` auf ``a``/``o``/``u``.
    Der zweite Schritt ist nötig, weil Händler dieselben Wörter verschieden schreiben:
    ``strip_accents`` macht aus „Spätlese" ein „spatlese", aus „Spaetlese" dagegen
    „spaetlese", und die beiden träfen sich nie.

    Nebenwirkung, bewusst hingenommen: „Dörrfrucht" und „Dorrfrucht" fallen zusammen,
    „moelleux" wird zu „molleux". Weil **beide** Seiten des Vergleichs gefaltet
    werden, stört das nicht — es könnte höchstens ein Wortpaar zusammenlegen, das
    getrennt gehörte, und in diesen Listen gibt es keines.
    """
    t = strip_accents((text or "").lower())
    return t.replace("ae", "a").replace("oe", "o").replace("ue", "u")


@lru_cache(maxsize=None)
def _wortgrenze(token: str) -> re.Pattern[str]:
    """Wortgrenzen-Muster für ein Token, gefaltet und zwischengespeichert.

    Ohne Wortgrenzen fände „dulce" auch in „Dulcedo" statt, und „rund" in „Grundwein".
    Mehrwortige Tokens („vendemmia tardiva") dürfen dazwischen beliebigen Abstand
    haben, weil Händler dort Bindestriche und doppelte Leerzeichen setzen.
    """
    teile = [re.escape(w) for w in _falten(token).split()]
    return re.compile(r"\b" + r"[\s\-]+".join(teile) + r"\b")


@dataclass(frozen=True)
class Tabelle:
    """Die gepflegten Listen aus ``sources/stiltyp.yaml``."""

    suesse_tokens: tuple[str, ...]
    stilmarken: tuple[str, ...]
    stil_tabelle: dict[str, str]
    opulent: tuple[str, ...]
    straff: tuple[str, ...]

    @classmethod
    def load(cls, path: Path | str | None = None) -> Tabelle:
        rohdaten = yaml.safe_load(Path(path or DEFAULT_PATH).read_text(encoding="utf-8")) or {}
        # Die Süsse-Tokens stehen nach Sprache gruppiert, damit die Liste lesbar
        # bleibt; für das Matchen ist die Gruppierung belanglos.
        tokens: list[str] = []
        for gruppe in (rohdaten.get("suesse_tokens") or {}).values():
            tokens.extend(gruppe or [])
        kw = rohdaten.get("keywords") or {}
        return cls(
            suesse_tokens=tuple(tokens),
            stilmarken=tuple(rohdaten.get("stilmarken") or []),
            stil_tabelle=dict(rohdaten.get("stil_tabelle") or {}),
            opulent=tuple(kw.get("opulent") or []),
            straff=tuple(kw.get("straff") or []),
        )


@lru_cache(maxsize=1)
def tabelle() -> Tabelle:
    return Tabelle.load()


@dataclass
class Struktur:
    """Vivinos gemessene Geschmacksstruktur zu einem Wein.

    Die Werte laufen auf einer Skala von 1 bis 5. ``urteile`` ist
    ``taste.structure.user_structure_count`` — wie viele Nutzer die Struktur
    mitgetragen haben. Ohne diese Zahl wäre der Mittelwert nicht einzuordnen: 4.0
    Süsse aus drei Urteilen und aus dreihundert sind zwei verschiedene Aussagen.
    """

    suesse: float | None = None
    tannin: float | None = None
    saeure: float | None = None
    intensitaet: float | None = None
    urteile: int = 0

    @property
    def brauchbar(self) -> bool:
        return self.suesse is not None and self.urteile >= MIN_STRUKTUR_URTEILE

    @classmethod
    def aus_vivino(cls, roh: dict[str, float] | None) -> Struktur | None:
        """Aus dem, was :mod:`winecheck.ratings.vivino` in den Payload gelegt hat.

        Die Baseline eines Stils trägt keine Urteilszahl — sie ist von Vivino
        gerechnet, nicht von Nutzern gesetzt. Sie bekommt darum ``urteile`` gar nicht
        erst gesetzt und wird über den eigenen Zweig der Kaskade gelesen, nicht über
        :attr:`brauchbar`.
        """
        if not roh:
            return None
        return cls(
            suesse=roh.get("sweetness"),
            tannin=roh.get("tannin"),
            saeure=roh.get("acidity"),
            intensitaet=roh.get("intensity"),
            urteile=int(roh.get("count") or 0),
        )


@dataclass
class Einordnung:
    """Ergebnis der Kaskade. ``signale`` ist Pflicht, nicht Zierde."""

    typ: str = UNBEKANNT
    stufe: int = 0
    signale: list[str] = field(default_factory=list)
    score: float | None = None

    @property
    def label(self) -> str:
        return TYP_LABELS.get(self.typ, self.typ)

    @property
    def unsicher(self) -> bool:
        """Nur Stufe 3 ist eine Schätzung. Die Anzeige hängt daran ein Fragezeichen."""
        return self.stufe == 3


def typ_aus_score(score: float) -> str:
    """Punkt auf der Achse aus dem Rohwert ``-1.0`` (straff) bis ``+1.0`` (fruchtsüss).

    Die Schwellen der Spec (+0.4 / +0.1 / -0.1) setzen eine **zentrierte** Achse
    voraus. Eine naive Normalisierung der Süsse liefert die nicht: praktisch jeder
    trockene Wein liegt bei 1.5 bis 2.0 von 5, und auf -1..+1 gerechnet wäre das
    dauerhaft negativ — jeder Wein käme als ``straff_herb`` heraus, und die Kennzahl
    hätte genau die Verzerrung, die sie beheben soll, nur mit umgekehrtem Vorzeichen.

    Darum rechnet :func:`_score_aus_struktur` nicht gegen die Skalenmitte, sondern
    gegen den beobachteten Normalfall eines trockenen Rotweins. Erst dadurch bedeuten
    die Schwellen der Spec, was sie sagen sollen.
    """
    if score >= SCHWELLE_FRUCHTSUESS:
        return "fruchtsuess"
    if score >= SCHWELLE_WEICH:
        return "weich_modern"
    if score >= SCHWELLE_AUSGEWOGEN:
        return "ausgewogen"
    return "straff_herb"


# ------------------------------------------------------------------ Stufe 1

#: Restzucker ab diesem Wert schmeckt man, unabhängig von der Deklaration.
RESTZUCKER_SUESS = 5.0
#: Darunter gilt ein Wein als durchgegoren.
RESTZUCKER_TROCKEN = 2.0
#: Ab hier trägt die Säure den Wein, sofern er zugleich durchgegoren ist.
SAEURE_STRAFF = 5.5
#: Alkohol allein genügt ab diesem Wert — so viel erreicht ein Rotwein nur über
#: sehr reife oder angetrocknete Trauben, und beides schmeckt süsslich.
ALKOHOL_SUESS = 15.0

_RE_RESTZUCKER = re.compile(
    r"(?:restzucker|zucker|residual\s*sugar|rs)\D{0,12}?(\d{1,3}(?:[.,]\d)?)\s*g", re.I
)
# „Säure" wird von :func:`_falten` zu „saure", nicht zu „saeure" — der Umlaut fällt
# vor der Umschrift. Das Muster läuft auf dem gefalteten Text und muss darum die
# gefaltete Form treffen.
_RE_SAEURE = re.compile(
    r"(?:gesamts|s)aure\D{0,12}?(\d{1,2}(?:[.,]\d)?)\s*g", re.I
)
_RE_ALKOHOL = re.compile(r"(\d{1,2}(?:[.,]\d)?)\s*%\s*(?:vol|alk)", re.I)


def _zahl(text: str) -> float:
    return float(text.replace(",", "."))


def _stufe1(name: str, datenblatt: str, tab: Tabelle) -> Einordnung | None:
    """Harte Signale. Greift eines, ist der Fall entschieden."""
    gefaltet = _falten(name)

    # 1a — Süsse-Token im Namen.
    treffer = [t for t in tab.suesse_tokens if _wortgrenze(t).search(gefaltet)]
    if treffer:
        return Einordnung(
            typ="fruchtsuess",
            stufe=1,
            signale=[f"Name nennt '{t}'" for t in treffer[:3]],
        )

    # 1c — Stilmarke. Vor 1b geprüft, weil eine bekannte Marke keinen Messwert braucht.
    marken = [m for m in tab.stilmarken if _wortgrenze(m).search(gefaltet)]
    if marken:
        return Einordnung(
            typ="fruchtsuess",
            stufe=1,
            signale=[f"Stilmarke '{m}'" for m in marken[:2]],
        )

    # 1b — Analysewerte, falls je eines mitkommt. Siehe Modulkopf: heute nie.
    hay = _falten(datenblatt)
    zucker = _RE_RESTZUCKER.search(hay)
    saeure = _RE_SAEURE.search(hay)
    alkohol = _RE_ALKOHOL.search(hay)
    if zucker:
        wert = _zahl(zucker.group(1))
        if wert >= RESTZUCKER_SUESS:
            return Einordnung("fruchtsuess", 1, [f"Restzucker {wert:.1f} g/l"])
        if wert < RESTZUCKER_TROCKEN and saeure and _zahl(saeure.group(1)) >= SAEURE_STRAFF:
            return Einordnung(
                "straff_herb", 1,
                [f"Restzucker {wert:.1f} g/l", f"Säure {_zahl(saeure.group(1)):.1f} g/l"],
            )
    if alkohol and _zahl(alkohol.group(1)) >= ALKOHOL_SUESS:
        return Einordnung("fruchtsuess", 1, [f"Alkohol {_zahl(alkohol.group(1)):.1f} %"])
    return None


# ------------------------------------------------------------------ Stufe 2

#: Der beobachtete Normalfall eines trockenen Rotweins auf Vivinos Skala 1..5.
#: Gegen diesen Punkt wird gerechnet, nicht gegen die Skalenmitte 3.0 — die
#: Begründung steht in :func:`typ_aus_score`.
NORMAL_SUESSE = 1.9
NORMAL_TANNIN = 3.4
NORMAL_SAEURE = 3.1

#: Wie weit ein Wert vom Normalfall abweichen muss, damit die Abweichung als
#: „ganz anders" gilt. Eine halbe Stufe auf einer Fünferskala ist bei
#: dreistelligen Urteilszahlen deutlich mehr als Rauschen.
SPANNE = 1.0


def _abweichung(wert: float | None, normal: float) -> float:
    """Abweichung vom Normalfall, auf ``-1..+1`` begrenzt."""
    if wert is None:
        return 0.0
    return max(-1.0, min(1.0, (wert - normal) / SPANNE))


def _score_aus_struktur(s: Struktur) -> float:
    """Rohwert aus Süsse, Tannin und Säure.

    Gewichtung nach Spec: Süsse zur Hälfte, Tannin und Säure mit umgekehrtem
    Vorzeichen zu drei und zwei Zehnteln. Süsse wiegt am schwersten, weil sie den
    Eindruck am unmittelbarsten trägt; Tannin vor Säure, weil ein herbes Tannin
    einen Rotwein deutlicher prägt als eine frische Säure.
    """
    return (
        0.5 * _abweichung(s.suesse, NORMAL_SUESSE)
        - 0.3 * _abweichung(s.tannin, NORMAL_TANNIN)
        - 0.2 * _abweichung(s.saeure, NORMAL_SAEURE)
    )


def _stufe2(
    struktur: Struktur | None,
    baseline: Struktur | None,
    stil_name: str,
    tab: Tabelle,
) -> Einordnung | None:
    """Vivino, in drei absteigenden Güten."""
    if struktur is not None and struktur.brauchbar:
        score = _score_aus_struktur(struktur)
        teile = [f"Süsse {struktur.suesse:.1f}/5"]
        if struktur.tannin is not None:
            teile.append(f"Tannin {struktur.tannin:.1f}")
        if struktur.saeure is not None:
            teile.append(f"Säure {struktur.saeure:.1f}")
        return Einordnung(
            typ=typ_aus_score(score),
            stufe=2,
            signale=[
                "Vivino-Geschmacksstruktur: " + ", ".join(teile)
                + f" (aus {struktur.urteile} Urteilen)"
            ],
            score=round(score, 3),
        )

    # Kein eigener Messwert: der Normalwert seines Stils. Eine Gattungsaussage, aber
    # eine von Vivino gerechnete — besser als unsere Tabelle, schlechter als der Wein.
    if baseline is not None and baseline.suesse is not None:
        score = _score_aus_struktur(baseline)
        return Einordnung(
            typ=typ_aus_score(score),
            stufe=2,
            signale=[
                f"Normalwert des Stils '{stil_name or ''}': "
                f"Süsse {baseline.suesse:.1f}/5"
            ],
            score=round(score, 3),
        )

    if stil_name and stil_name in tab.stil_tabelle:
        return Einordnung(
            typ=tab.stil_tabelle[stil_name],
            stufe=2,
            signale=[f"Vivino-Stil '{stil_name}'"],
        )
    return None


# ------------------------------------------------------------------ Stufe 3


def _stufe3(notiz: str, tab: Tabelle) -> Einordnung | None:
    """Keyword-Analyse der Verkostungsnotiz. Siehe Modulkopf: heute ohne Datenbasis."""
    if not notiz.strip():
        return None
    hay = _falten(notiz)
    a = [w for w in tab.opulent if _wortgrenze(w).search(hay)]
    b = [w for w in tab.straff if _wortgrenze(w).search(hay)]
    if len(a) + len(b) < MIN_KEYWORD_TREFFER:
        return None
    score = (len(a) - len(b)) / max(1, len(a) + len(b))
    belege = ", ".join(a[:3] + b[:3])
    return Einordnung(
        typ=typ_aus_score(score),
        stufe=3,
        signale=[f"Notiz nennt {belege}"],
        score=round(score, 3),
    )


# ------------------------------------------------------------------ Kaskade


def einordnen(
    name: str,
    *,
    datenblatt: str = "",
    notiz: str = "",
    struktur: Struktur | None = None,
    baseline: Struktur | None = None,
    stil_name: str = "",
    tab: Tabelle | None = None,
) -> Einordnung:
    """Ordnet einen Wein auf der Stil-Achse ein.

    Die erste greifende Stufe entscheidet. Eine spätere Stufe kann einen gefundenen
    Wert nicht überschreiben — sonst hinge das Ergebnis daran, in welcher Reihenfolge
    Daten nachgeliefert werden, und dieselbe Zeile hiesse von Lauf zu Lauf anders.

    Args:
        datenblatt: Händlertext mit möglichen Analysewerten.
        notiz: Verkostungsnotiz für Stufe 3.
        struktur: Vivinos gemessene Struktur zu genau diesem Wein.
        baseline: Normalwert seines Vivino-Stils.
        stil_name: ``wine.style.name``, für die Tabelle und als Beleg.
    """
    t = tab or tabelle()
    for ergebnis in (
        _stufe1(name, datenblatt, t),
        _stufe2(struktur, baseline, stil_name, t),
        _stufe3(notiz, t),
    ):
        if ergebnis is not None:
            return ergebnis
    return Einordnung()

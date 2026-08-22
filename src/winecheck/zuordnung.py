"""Geprüfte Zuordnungen, wo Vivinos Suche den richtigen Wein nicht hergibt.

Vivinos Suchindex hat Löcher. Das ist im Adapter an zwei Stellen vermerkt: „Fallet
Dart Champagne Brut Cuvée de Réserve" hat 533 Bewertungen und ist über keine
Schreibweise zu finden — dafür gibt es den Rückfall über die Weingutseite. Manchmal
reicht auch der nicht.

Dann bleiben zwei Möglichkeiten: eine Note vom falschen Wein, oder eine
nachgeprüfte Eintragung. Diese Datei ist der Weg für die zweite.

Was ein Eintrag belegen muss
----------------------------
Ein übereinstimmender **Name** genügt nicht. Vivino enthält Dubletten: von Nutzern
angelegte Stummel, die wie der gesuchte Wein heissen, aber keine Bewertungen, einen
einzigen Jahrgang und lückenhafte Angaben tragen — und nicht im Sortiment des Guts
stehen.

Am 21.08.2026 ist genau das passiert: „la Rocca" von Caratello wurde auf
``/w/14033263`` eingetragen, weil der Name passte. Der Eintrag trägt nur Sangiovese,
0 Bewertungen, einen Jahrgang. Der richtige Wein ist ``/w/11745`` — dieselbe Cuvée
aus Cabernet Sauvignon, Merlot und Sangiovese, 4663 Bewertungen, im Sortiment der
Weingutseite. Die Eintragung hat eine **richtige** Note entfernt.

Darum verlangt jeder Eintrag den Vergleich der Substanz — Rebsorten, Appellation,
Zahl der Jahrgänge und Bewertungen, Präsenz im Sortiment des Guts — und dazu Adresse
und Prüfdatum. Eine Beobachtung darf hier stehen, eine Vermutung nicht.

Und ausdrücklich **kein Ersatz für einen besseren Abgleich**. Wer hier einen Wein
einträgt, weil der Matcher ihn falsch zuordnet, behandelt ein Symptom und
verschleiert den Fehler. Diese Liste ist für die Fälle, in denen die Auskunft bei
Vivino selbst nicht auffindbar ist.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .names import normalized_name

DEFAULT_PATH = Path("sources/vivino-zuordnung.yaml")


@dataclass(frozen=True)
class Eintrag:
    """Eine geprüfte Aussage über einen Wein."""

    name: str
    url: str
    grund: str
    geprueft_am: str
    #: Der richtige Wein ist bei Vivino geführt, trägt aber keine verwertbare Note.
    #: Dann gibt es hier keine — und die Adresse steht daneben.
    ohne_note: bool = False


def laden(pfad: Path | None = None) -> dict[str, Eintrag]:
    """Die Liste, geschlüsselt über den normalisierten Händlernamen.

    Derselbe Schlüssel wie im Bewertungs-Cache: damit trifft ein Eintrag denselben
    Wein, den auch der Abgleich sieht, unabhängig von Schreibweise und Reihenfolge.
    """
    p = pfad or DEFAULT_PATH
    if not p.exists():
        return {}
    daten = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    aus: dict[str, Eintrag] = {}
    for roh in daten.get("zuordnungen") or []:
        name = str(roh.get("name") or "").strip()
        if not name:
            continue
        aus[normalized_name(name)] = Eintrag(
            name=name,
            url=str(roh.get("url") or ""),
            grund=" ".join(str(roh.get("grund") or "").split()),
            geprueft_am=str(roh.get("geprueft_am") or ""),
            ohne_note=bool(roh.get("ohne_note")),
        )
    return aus


def finde(name: str, tabelle: dict[str, Eintrag]) -> Eintrag | None:
    return tabelle.get(normalized_name(name)) if tabelle else None

@dataclass(frozen=True)
class Marktplatzkorrektur:
    """Ein Marktplatz-Angebot, dessen Wein bei Vivino falsch daran hängt."""

    url: str
    name: str
    grund: str
    geprueft_am: str


def marktplatz_laden(pfad: Path | None = None) -> dict[str, Marktplatzkorrektur]:
    """Korrekturen für den Vivino-Marktplatz, geschlüsselt über die Angebots-Adresse.

    Der Marktplatz-Adapter übernimmt Note und Weinname **ohne Namensabgleich** — die
    Zuordnung kommt von Vivino selbst, und das ist normalerweise die verlässlichste
    Auskunft, die es gibt. Sie kann aber falsch sein, und dann greift keine der
    Sicherungen des Abgleichs.

    Gefunden am 22.08.2026: Vivinos Schnittstelle liefert den Wein „Secret Spot
    Tinto" (4.3 aus 448 Bewertungen) mit einem Gerstl-Link, der den „Vale do Lacrau
    Reserva" desselben Hauses verkauft. Zwei verschiedene Weine, ein Datensatz. Eine
    Stichprobe von zwölf anderen Marktplatz-Angeboten war fehlerfrei; das ist also
    ein Ausreisser und kein Muster — geprüft wird jede Korrektur trotzdem einzeln.

    Was ein Eintrag belegen muss, steht in dieser Datei über den Einträgen: die
    Substanz, nicht der Name.
    """
    p = pfad or DEFAULT_PATH
    if not p.exists():
        return {}
    daten = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    aus: dict[str, Marktplatzkorrektur] = {}
    for roh in daten.get("marktplatz") or []:
        url = str(roh.get("url") or "").strip()
        name = str(roh.get("name") or "").strip()
        if not url or not name:
            continue
        aus[url] = Marktplatzkorrektur(
            url=url, name=name,
            grund=" ".join(str(roh.get("grund") or "").split()),
            geprueft_am=str(roh.get("geprueft_am") or ""),
        )
    return aus

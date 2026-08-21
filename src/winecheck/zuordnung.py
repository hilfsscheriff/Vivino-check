"""Geprüfte Zuordnungen, wo Vivinos Suche den richtigen Wein nicht hergibt.

Vivinos Suchindex hat Löcher. Das ist im Adapter an zwei Stellen vermerkt: „Fallet
Dart Champagne Brut Cuvée de Réserve" hat 533 Bewertungen und ist über keine
Schreibweise zu finden — dafür gibt es den Rückfall über die Weingutseite. Manchmal
reicht auch der nicht.

Dann bleiben zwei Möglichkeiten: eine Note vom falschen Wein, oder eine
nachgeprüfte Eintragung. Diese Datei ist der Weg für die zweite.

Was hier stehen darf
--------------------
Nur Nachgeprüftes, mit Beleg — Adresse und Prüfdatum in jedem Eintrag. Das ist
dieselbe Regel wie überall in diesem Projekt: eine Beobachtung darf hier stehen,
eine Schätzung nicht.

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

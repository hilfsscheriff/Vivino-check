"""Auflösen von turbo-stream-Payloads (React Router v7 / Remix).

Der Prodega-Easy-Katalog liefert seine Daten unter ``…/catalog.data`` in diesem
Format: eine flache Liste, in der Objekte weder Schlüssel noch Werte direkt
enthalten, sondern beides per Index referenzieren.

.. code-block:: json

    [ {"_1": 2}, "searchTerm", "wein" ]

``{"_1": 2}`` heisst also ``{ liste[1]: liste[2] }`` und damit
``{"searchTerm": "wein"}``. Verwandt mit dem devalue-Format von Nuxt (siehe
:mod:`winecheck.nuxt`), aber dort sind nur die *Werte* Indizes, hier auch die
Schlüssel.

Negative Indizes sind Sentinels für ``undefined``/``null`` und werden zu ``None``.
"""

from __future__ import annotations

import json
import re
from typing import Any

_RE_KEY = re.compile(r"^_(-?\d+)$")


class TurboStream:
    """Löst Index-Referenzen in einem turbo-stream-Array auf."""

    def __init__(self, array: list[Any]):
        self.array = array

    @classmethod
    def parse(cls, text: str) -> TurboStream | None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        return cls(data) if isinstance(data, list) else None

    # ------------------------------------------------------------------ intern
    def _at(self, index: int) -> Any:
        if index < 0 or index >= len(self.array):
            return None
        return self.array[index]

    def resolve(self, value: Any, *, max_depth: int = 24, _seen: frozenset[int] = frozenset()) -> Any:
        """Löst einen Index oder eine bereits aufgelöste Struktur rekursiv auf."""
        if max_depth <= 0:
            return None
        if isinstance(value, bool) or value is None or isinstance(value, (float, str)):
            return value
        if isinstance(value, int):
            if value < 0 or value in _seen:
                return None
            target = self._at(value)
            # Nur Container werden weiterverfolgt. Ein Zahlenwert an der Zielstelle ist
            # der *Wert* und nicht wieder ein Index — sonst landet ``totalCount: 85``
            # bei Listeneintrag 85 und liefert einen zufälligen String. Genau daran
            # sind ``totalCount``, ``itemCount`` und ``pageSize`` zuerst gescheitert.
            if isinstance(target, (dict, list)):
                return self.resolve(target, max_depth=max_depth - 1, _seen=_seen | {value})
            return target
        if isinstance(value, list):
            # Listen enthalten wieder Indizes.
            return [self.resolve(v, max_depth=max_depth - 1, _seen=_seen) for v in value]
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for raw_key, raw_value in value.items():
                m = _RE_KEY.match(raw_key)
                key = self._at(int(m.group(1))) if m else raw_key
                if not isinstance(key, str):
                    key = str(key)
                out[key] = self.resolve(raw_value, max_depth=max_depth - 1, _seen=_seen)
            return out
        return value

    # ------------------------------------------------------------- öffentliche API
    def find_key_index(self, name: str) -> int | None:
        """Index eines Schlüsselstrings — Ausgangspunkt für die Objektsuche."""
        try:
            return self.array.index(name)
        except ValueError:
            return None

    def objects_with(self, *required: str) -> list[dict[str, Any]]:
        """Alle aufgelösten Objekte, die alle genannten Schlüssel tragen.

        Gesucht wird auf der flachen Liste — unabhängig davon, wo im Baum das
        Objekt hängt, und ohne den ganzen Payload aufzulösen.
        """
        indices = {name: self.find_key_index(name) for name in required}
        if any(i is None for i in indices.values()):
            return []
        wanted = {f"_{i}" for i in indices.values()}
        out: list[dict[str, Any]] = []
        for entry in self.array:
            if isinstance(entry, dict) and wanted <= set(entry.keys()):
                resolved = self.resolve(entry)
                if isinstance(resolved, dict):
                    out.append(resolved)
        return out

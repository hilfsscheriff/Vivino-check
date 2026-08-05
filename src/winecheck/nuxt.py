"""Auflösen von Nuxt-3-Payloads (``__NUXT_DATA__``).

Nuxt serialisiert im *devalue*-Format: eine flache Liste, in der Objekte ihre Werte
nicht direkt enthalten, sondern per Index auf andere Listeneinträge zeigen. Damit
lassen sich Zyklen und Mehrfachverweise abbilden — man muss die Verweise aber
auflösen, um an die Daten zu kommen.

Denner liefert seine Aktionsprodukte auf diesem Weg serverseitig mit, deshalb braucht
der Adapter keinen Browser.
"""

from __future__ import annotations

import json
import re
from typing import Any

_RE_PAYLOAD = re.compile(r"<script[^>]*id=\"__NUXT_DATA__\"[^>]*>(.*?)</script>", re.S)

#: Wrapper, die devalue für Vue-Reaktivität einfügt: ``["Ref", 12]`` meint Eintrag 12.
_WRAPPERS = {
    "Ref", "Reactive", "ShallowRef", "ShallowReactive", "EmptyRef", "EmptyShallowRef",
    "NuxtError", "Island",
}


def extract_payload(html: str) -> list[Any] | None:
    """Holt das rohe devalue-Array aus dem HTML."""
    m = _RE_PAYLOAD.search(html or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


class NuxtPayload:
    """Löst Index-Verweise in einem devalue-Array auf."""

    def __init__(self, array: list[Any]):
        self.array = array

    @classmethod
    def from_html(cls, html: str) -> NuxtPayload | None:
        arr = extract_payload(html)
        return cls(arr) if arr is not None else None

    def deref(self, value: Any, *, max_depth: int = 12, _seen: frozenset[int] = frozenset()) -> Any:
        """Löst einen Wert (meist einen Index) rekursiv auf.

        ``_seen`` bricht Zyklen ab — Nuxt-Payloads verweisen regelmässig zurück auf
        Elternobjekte.
        """
        if max_depth <= 0:
            return None
        if isinstance(value, bool) or value is None or isinstance(value, (float, str)):
            return value
        if isinstance(value, int):
            if not (0 <= value < len(self.array)) or value in _seen:
                return value if not (0 <= value < len(self.array)) else None
            return self.deref(
                self.array[value], max_depth=max_depth - 1, _seen=_seen | {value}
            )
        if isinstance(value, list):
            if len(value) == 2 and isinstance(value[0], str) and value[0] in _WRAPPERS:
                return self.deref(value[1], max_depth=max_depth - 1, _seen=_seen)
            return [self.deref(v, max_depth=max_depth - 1, _seen=_seen) for v in value]
        if isinstance(value, dict):
            return {
                k: self.deref(v, max_depth=max_depth - 1, _seen=_seen)
                for k, v in value.items()
            }
        return value

    def find_dicts(self, *, required_keys: set[str]) -> list[dict[str, Any]]:
        """Alle Roh-Objekte, die mindestens die genannten Schlüssel tragen.

        Sucht auf der flachen Liste statt im aufgelösten Baum: schneller, und
        unabhängig davon, wo im Baum das Objekt hängt.
        """
        out: list[dict[str, Any]] = []
        for entry in self.array:
            if isinstance(entry, dict) and required_keys <= set(entry.keys()):
                out.append(entry)
        return out


def flatten_attribute_info(product: dict[str, Any]) -> dict[str, Any]:
    """Macht Denners ``attributeInfo``-Liste zu einem flachen Dict.

    Aus ``[{"attributeName": "name", "vals": [{"value": "Kirschen", ...}]}]`` wird
    ``{"name": "Kirschen"}``. Mehrwertige Attribute (``category``) behalten alle
    Labels als Liste unter ``<name>__labels``.
    """
    flat: dict[str, Any] = {}
    for attr in product.get("attributeInfo") or []:
        if not isinstance(attr, dict):
            continue
        key = attr.get("attributeName")
        if not isinstance(key, str):
            continue
        vals = attr.get("vals")
        if not isinstance(vals, list) or not vals:
            continue
        values, labels = [], []
        for v in vals:
            if isinstance(v, dict):
                values.append(v.get("value"))
                labels.append(v.get("label"))
        if not values:
            continue
        flat[key] = values[0]
        if len(values) > 1:
            flat[f"{key}__labels"] = [x for x in labels if x]
            flat[f"{key}__values"] = values
        else:
            flat[f"{key}__labels"] = [x for x in labels if x]
    return flat

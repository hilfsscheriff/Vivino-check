"""Schweizer Konventionen für die Ausgabe.

* ``ss`` statt ``ß``
* Preise als ``CHF 9.95`` — Punkt als Dezimaltrennzeichen, Apostroph als
  Tausendertrenner (``CHF 1'250.00``)
* Datum als ``5.8.2026`` — ohne führende Nullen
"""

from __future__ import annotations

import time

_SHARP_S = str.maketrans({"ß": "ss"})


def ch(text: str) -> str:
    """Schweizer Schreibweise erzwingen."""
    return (text or "").translate(_SHARP_S)


def chf(value: float | None, *, prefix: str = "CHF ") -> str:
    """``CHF 9.95``, ``CHF 1'250.00``. Ohne Wert ein leerer String — die aufrufende
    Stelle entscheidet, was stattdessen dasteht (nie ein Gedankenstrich in der
    Vivino-Spalte)."""
    if value is None:
        return ""
    whole, _, frac = f"{value:,.2f}".partition(".")
    return f"{prefix}{whole.replace(',', chr(39))}.{frac}"


def date(timestamp: float | None = None) -> str:
    """``5.8.2026`` — ohne führende Nullen."""
    t = time.localtime(timestamp if timestamp is not None else time.time())
    return f"{t.tm_mday}.{t.tm_mon}.{t.tm_year}"


def datetime_ch(timestamp: float | None = None) -> str:
    t = time.localtime(timestamp if timestamp is not None else time.time())
    return f"{t.tm_mday}.{t.tm_mon}.{t.tm_year}, {t.tm_hour:02d}:{t.tm_min:02d}"


def rating_text(value: float | None, scale_max: float, count: int | None = None) -> str:
    """``3.6/5 (42)`` bzw. ``89/100``."""
    if value is None:
        return ""
    base = f"{value:.1f}/{scale_max:.0f}" if scale_max <= 5 else f"{value:.0f}/{scale_max:.0f}"
    return f"{base} ({count})" if count else base


def truncate(text: str, limit: int) -> str:
    t = ch(text or "").strip()
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"

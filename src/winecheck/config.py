"""Laden der Quellen-Registry aus ``sources/retailers.yaml``."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = PROJECT_ROOT / "sources" / "retailers.yaml"

load_dotenv(PROJECT_ROOT / ".env")


@dataclass
class SourceConfig:
    key: str
    name: str
    adapter: str = "generic_html"
    domain: str = ""
    tier: int = 0
    enabled: bool = False
    status: str = "no_adapter"
    urls: list[str] = field(default_factory=list)
    shop_root: str = ""
    promo_keywords: list[str] = field(default_factory=list)
    private_label_brands: list[str] = field(default_factory=list)
    notes: str = ""
    blocked_by: str = ""
    verified_at: str = ""
    vat_included: bool = True
    price_basis: str = "bottle"
    rate_limit_seconds: float = 2.0
    respect_robots: bool = True
    timeout_seconds: float = 30.0
    market: str | None = None
    login: dict[str, str] = field(default_factory=dict)
    scale_max: float = 100.0
    role: str = ""
    api: str = ""
    search_url: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    # -- Zugangsdaten ------------------------------------------------------
    def credentials(self) -> tuple[str | None, str | None, str | None]:
        """Zugangsdaten ausschliesslich aus Umgebungsvariablen — nie aus dem Repo."""
        if not self.login:
            return None, None, None
        user = os.getenv(self.login.get("env_user", "")) or None
        pw = os.getenv(self.login.get("env_pass", "")) or None
        cookie = os.getenv(self.login.get("env_cookie", "")) or None
        return user, pw, cookie

    @property
    def has_credentials(self) -> bool:
        user, pw, cookie = self.credentials()
        return bool(cookie or (user and pw))


@dataclass
class Registry:
    retailers: dict[str, SourceConfig]
    rating_sources: dict[str, SourceConfig]
    path: Path

    def retailer(self, key: str) -> SourceConfig:
        if key not in self.retailers:
            raise KeyError(f"Unbekannter Händler '{key}'. Bekannt: {', '.join(sorted(self.retailers))}")
        return self.retailers[key]

    def enabled_retailers(self) -> list[SourceConfig]:
        return [r for r in self.retailers.values() if r.enabled]

    def select(self, keys: list[str] | None) -> list[SourceConfig]:
        """Auswahl über ``--retailers``. Ohne Angabe alle aktivierten."""
        if not keys:
            return self.enabled_retailers()
        return [self.retailer(k.strip()) for k in keys if k.strip()]

    def rating_source(self, key: str) -> SourceConfig | None:
        return self.rating_sources.get(key)


def _build(entry: dict[str, Any], defaults: dict[str, Any]) -> SourceConfig:
    merged = {**defaults, **{k: v for k, v in entry.items() if v is not None}}
    known = {f for f in SourceConfig.__dataclass_fields__ if f != "raw"}
    kwargs = {k: v for k, v in merged.items() if k in known}
    kwargs.setdefault("key", entry.get("key", ""))
    kwargs.setdefault("name", entry.get("name", entry.get("key", "")))
    return SourceConfig(raw=entry, **kwargs)


def load_registry(path: Path | str | None = None) -> Registry:
    p = Path(path) if path else DEFAULT_REGISTRY
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    defaults = data.get("defaults") or {}
    retailers = {}
    for entry in data.get("retailers") or []:
        cfg = _build(entry, defaults)
        retailers[cfg.key] = cfg
    ratings = {}
    for entry in data.get("rating_sources") or []:
        cfg = _build(entry, defaults)
        ratings[cfg.key] = cfg
    return Registry(retailers=retailers, rating_sources=ratings, path=p)


def write_resolved_urls(registry: Registry, key: str, urls: list[str], note: str = "") -> None:
    """Schreibt beim ersten Lauf aufgelöste Adressen in die YAML zurück.

    Bewusst als Textmanipulation und nicht per yaml.dump: die Datei enthält
    ausführliche Kommentare, die ein Round-Trip durch PyYAML zerstören würde.
    Der Eintrag landet als ``resolved_urls`` unter dem betroffenen Händler.
    """
    text = registry.path.read_text(encoding="utf-8")
    marker = f"  - key: {key}\n"
    if marker not in text or not urls:
        return
    block = "".join(f"      - {u}\n" for u in urls)
    addition = f"    resolved_urls:            # automatisch ergänzt\n{block}"
    if note:
        addition += f"    resolved_note: {note!r}\n"
    start = text.index(marker) + len(marker)
    # Vor dem nächsten Händler-Eintrag einfügen.
    nxt = text.find("\n  - key: ", start)
    insert_at = nxt + 1 if nxt != -1 else len(text)
    if "resolved_urls:" in text[start:insert_at]:
        return
    registry.path.write_text(text[:insert_at] + addition + text[insert_at:], encoding="utf-8")

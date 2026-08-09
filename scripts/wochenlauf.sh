#!/bin/bash
# Wöchentlicher Lauf auf dem Mac: Aktionen holen, bewerten, Seite bauen, einchecken.
#
# Warum lokal und nicht auf GitHub: Vivino sperrt Rechenzentrums-IPs. Ein Testlauf auf
# GitHubs Rechnern holte die Preise fehlerfrei, bekam aber nach 13 Abfragen für 465 von
# 478 Weinen ein "blocked". Über den Hausanschluss läuft es durch.
#
# Wird von ~/Library/LaunchAgents/ch.winecheck.wochenlauf.plist freitags gestartet.
# Von Hand: bash scripts/wochenlauf.sh
#
# set -e fehlt mit Absicht: ein Fehlschlag in einem Schritt soll den Lauf nicht
# stillschweigend beenden, sondern protokolliert und am Ende bewertet werden.
set -uo pipefail

PROJEKT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJEKT" || exit 1

# launchd startet mit einem minimalen PATH — uv liegt nicht darin.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

PROTOKOLL="$PROJEKT/state/wochenlauf.log"
mkdir -p "$(dirname "$PROTOKOLL")"

sage() { printf '%s  %s\n' "$(date '+%d.%m.%Y %H:%M:%S')" "$*" | tee -a "$PROTOKOLL"; }

sage "── Wochenlauf gestartet"

if ! command -v uv >/dev/null 2>&1; then
  sage "FEHLER: uv nicht gefunden. PATH=$PATH"
  exit 1
fi

# -- 1. Aktionen holen ------------------------------------------------------
sage "Aktionen holen …"
if ! uv run wine-check fetch --refresh-prices >>"$PROTOKOLL" 2>&1; then
  sage "FEHLER beim Holen — Lauf abgebrochen, alter Stand bleibt stehen"
  exit 1
fi

# -- 2. Bewertungen ---------------------------------------------------------
# Dauert je nach Anzahl neuer Weine zwischen zwei und vierzig Minuten. Bereits
# bewertete Weine kommen aus dem Cache (90 Tage gültig).
# Einmal im Monat auch die alten Fehlschläge erneut prüfen.
#
# Ein "kein Eintrag" bleibt im Cache liegen, damit nicht jede Woche dieselbe
# erfolglose Suche über die Leitung geht. Das hat aber eine Kehrseite: verbessert
# sich der Namensabgleich, kommt die Verbesserung nie bei den Weinen an, die sie am
# nötigsten hätten — ihr alter Fehlschlag steht ja schon da.
#
# Monatlich, nicht wöchentlich: eine Stichprobe von zwanzig Fehlschlägen ergab zwei
# Treffer. Die restlichen achtzehn waren Walliser und Waadtländer Gewächse,
# Genossenschaftsabfüllungen, ein Zürcher Kleinwinzer — die stehen bei Vivino
# wirklich nicht. Der Durchgang kostet rund 400 zusätzliche Abfragen; für zehn
# Prozent Ausbeute lohnt er einmal im Monat, nicht jede Woche.
if [ "$(date '+%d')" -le 7 ]; then
  sage "Bewertungen abgleichen (mit Wiederholung der Fehlschläge) …"
  uv run wine-check rate --retry-failed >>"$PROTOKOLL" 2>&1
else
  sage "Bewertungen abgleichen …"
  uv run wine-check rate >>"$PROTOKOLL" 2>&1
fi

# -- 3. Report und Seite ----------------------------------------------------
sage "Report und Seite bauen …"
if ! uv run wine-check report --out ./output >>"$PROTOKOLL" 2>&1; then
  sage "FEHLER beim Report — nichts eingecheckt"
  exit 1
fi
uv run wine-check site --out ./docs >>"$PROTOKOLL" 2>&1

# -- 4. Reissleine ----------------------------------------------------------
# Dieselbe Prüfung wie im GitHub-Workflow: ein Lauf, der die Datenlage
# verschlechtert, wird nicht veröffentlicht. Eine blockierte Bewertungsquelle ist
# kein Grund, den guten Stand zu überschreiben.
PRUEFUNG=$(uv run python - <<'PY'
import csv, subprocess, sys

rows = list(csv.DictReader(open("output/results.csv", encoding="utf-8-sig"), delimiter=";"))
bew = sum(1 for r in rows if r.get("vivino_rating"))
blockiert = sum(1 for r in rows if r.get("vivino_status") == "blocked")
alt = subprocess.run(["git", "show", "HEAD:docs/index.html"],
                     capture_output=True, text=True).stdout
alt_bew = alt.count('"r":')

print(f"{len(rows)} Weine, {bew} bewertet, {blockiert} blockiert (bisher {alt_bew} bewertet)")
if blockiert > len(rows) * 0.2:
    sys.exit(f"ABBRUCH: {blockiert} von {len(rows)} blockiert")
if alt_bew >= 20 and bew < alt_bew * 0.66:
    sys.exit(f"ABBRUCH: nur {bew} bewertet gegenüber {alt_bew}")
PY
)
STATUS=$?
sage "$PRUEFUNG"
if [ $STATUS -ne 0 ]; then
  sage "Nicht eingecheckt — der bisherige Stand bleibt online."
  exit 1
fi

# -- 5. Bewertungen für den GitHub-Lauf mitgeben ----------------------------
# Der Wochenlauf auf GitHub holt frische Preise, kann aber nicht bei Vivino
# nachfragen (Rechenzentrums-IPs werden gesperrt). Diese Datei gibt ihm die hier
# ermittelten Noten mit, damit die Seite dort Preise *und* Bewertungen zeigt.
uv run wine-check ratings-export >>"$PROTOKOLL" 2>&1

# -- 6. Einchecken ----------------------------------------------------------
if git diff --quiet -- docs state/ratings-cache.json; then
  sage "Keine Änderung an der Seite — nichts einzuchecken."
else
  git add docs state/ratings-cache.json
  git commit -q -m "Wochenlauf $(date '+%d.%m.%Y')" && sage "eingecheckt"
  if git push -q origin HEAD:main 2>>"$PROTOKOLL"; then
    sage "gepusht — GitHub Pages liefert in ein bis zwei Minuten aus"
  else
    sage "FEHLER beim Push (Zugangsdaten im Schlüsselbund erreichbar?)"
    exit 1
  fi
fi

sage "── Wochenlauf fertig"

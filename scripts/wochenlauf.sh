#!/bin/bash
# Wöchentlicher Lauf auf dem Mac: Aktionen holen, bewerten, Seite bauen, einchecken.
#
# Warum lokal und nicht auf GitHub: Vivino sperrt Rechenzentrums-IPs. Das trifft seit
# 14.08.2026 auch die Preise des Vivino-Marktplatzes (HTTP 403), nicht mehr nur die
# Bewertungen — der GitHub-Lauf sah dort 849 statt 1524 Weinen und ist deshalb
# abgeschaltet. Dieser Lauf hier ist damit der einzige. Ein Testlauf auf
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

# Diese Arbeitskopie ist nicht die, in der von Hand gearbeitet wird — erst den
# aktuellen Stand holen, sonst baut der Lauf auf altem Code.
#
# Hart zurücksetzen statt bloss ziehen: der Klon *erzeugt* bei jedem Lauf
# docs/index.html und state/ratings-cache.json neu. Bricht ein Lauf nach dem Bauen
# ab — etwa an der Reissleine —, bleiben diese Dateien geändert liegen und ein
# ``git pull --ff-only`` scheitert daran ab sofort **jede** Woche. Genau das ist
# passiert: der Lauf vom 14.08. arbeitete 48 Commits hinterher, fand 616 statt 1564
# Weine und wurde von der Reissleine zu Recht gestoppt.
#
# Hier darf zurückgesetzt werden, weil in diesem Klon nichts von Hand entsteht: er
# holt den Stand, rechnet und schiebt das Ergebnis zurück. Die Arbeitskopie unter
# ~/Library/CloudStorage bleibt unberührt.
# -- Sperre: nur ein Lauf zur Zeit ------------------------------------------
# Das Skript nennt den Handstart selbst als vorgesehenen Weg, und der launchd-Auftrag
# holt verpasste Termine beim naechsten Aufwachen nach — also genau dann, wenn sich
# jemand anmeldet und selbst etwas startet. Beide Laeufe teilen Arbeitsverzeichnis,
# Cache und Git-Index, und der Schaden ist still: der Reset des zweiten verwirft die
# Seite, die der erste gerade gebaut hat, und Schritt 6 meldet dann brav "Keine
# Aenderung an der Seite".
#
# mkdir ist die Sperre: es gelingt genau einmal. flock(1) gibt es auf macOS nicht.
SPERRE="$PROJEKT/state/.lauf.lock"
mkdir -p "$PROJEKT/state"
if ! mkdir "$SPERRE" 2>/dev/null; then
  sage "Ein Lauf laeuft schon (Sperre $SPERRE) — abgebrochen."
  exit 0
fi
trap 'rmdir "$SPERRE" 2>/dev/null' EXIT

if ! git fetch -q origin 2>>"$PROTOKOLL"; then
  sage "WARNUNG: git fetch fehlgeschlagen — arbeite mit dem lokalen Stand weiter"
elif ! git reset --hard -q origin/main 2>>"$PROTOKOLL"; then
  sage "WARNUNG: git reset fehlgeschlagen — arbeite mit dem lokalen Stand weiter"
else
  sage "Stand geholt: $(git log --oneline -1)"
fi

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
# Der Rueckgabewert wird ausgewertet. Vorher nicht — und ein abgebrochener rate-Lauf
# lief damit still weiter: report las den Stand des Vorlaufs, alle Reissleinen
# verglichen ihn mit sich selbst, und die Preise der Vorwoche gingen unter dem heutigen
# Datum online.
if [ "$(date '+%d')" -le 7 ]; then
  sage "Bewertungen abgleichen (mit Wiederholung der Fehlschläge) …"
  RATE_OK=0; uv run wine-check rate --retry-failed >>"$PROTOKOLL" 2>&1 || RATE_OK=$?
else
  sage "Bewertungen abgleichen …"
  RATE_OK=0; uv run wine-check rate >>"$PROTOKOLL" 2>&1 || RATE_OK=$?
fi
if [ "$RATE_OK" -ne 0 ]; then
  sage "FEHLER beim Abgleich (Code $RATE_OK) — nichts gebaut, nichts eingecheckt"
  exit 1
fi

# -- 3. Report und Seite ----------------------------------------------------
sage "Report und Seite bauen …"
if ! uv run wine-check report --out ./output >>"$PROTOKOLL" 2>&1; then
  sage "FEHLER beim Report — nichts eingecheckt"
  exit 1
fi
# Auch hier der Rueckgabewert: seit es die Seitensperre gibt (SEITE_MIN_ANTEIL), kann
# 'site' bewusst abbrechen — und dieser Abbruch wurde verschluckt. Der Lauf checkte
# danach die alte Seite ein und meldete Erfolg.
if ! uv run wine-check site --out ./docs >>"$PROTOKOLL" 2>&1; then
  sage "FEHLER beim Seitenbau — nichts eingecheckt (siehe Protokoll)"
  exit 1
fi

# -- 4. Reissleine ----------------------------------------------------------
# Dieselbe Prüfung wie im (abgeschalteten) GitHub-Workflow: ein Lauf, der die Datenlage
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

# -- 5. Bewertungen sichern -------------------------------------------------
# Der Bewertungs-Cache liegt in einer SQLite-Datei, die nicht im Repo steht (zu
# gross, zu unhandlich im Diff). Diese Ausfuhr ist die versionierte Fassung: sie
# überlebt einen neu aufgesetzten Rechner und macht nachvollziehbar, wann eine
# Note dazukam.
#
# Ursprünglich war sie für den GitHub-Lauf gedacht, der Vivino nicht selbst fragen
# kann. Der ist seit 14.08.2026 abgeschaltet — Vivino sperrt inzwischen auch die
# Preise des Marktplatzes für Rechenzentrums-IPs, womit dort die Hälfte des
# Bestands fehlte. Die Ausfuhr bleibt trotzdem: als Sicherung ist sie das wert.
uv run wine-check ratings-export >>"$PROTOKOLL" 2>&1

# -- 5b. Preisreihe sichern -------------------------------------------------
# Dieselbe Rolle wie die Notenausfuhr, fuer die Preise. Die Beobachtungen des Tages
# schreibt bereits "report" in den Cache; hier wird die Reihe in die versionierte
# Datei gespiegelt, damit sie einen Rechnerverlust uebersteht. Geschrieben wird die
# Vereinigung aus Datei und Cache — eine Beobachtung von gestern kann nicht besser
# werden, also darf sie auch nicht verschwinden.
uv run wine-check preise-export >>"$PROTOKOLL" 2>&1

# -- 6. Einchecken ----------------------------------------------------------
if git diff --quiet -- docs state/ratings-cache.json state/preisverlauf.csv; then
  sage "Keine Änderung an der Seite — nichts einzuchecken."
else
  git add docs state/ratings-cache.json state/preisverlauf.csv
  # Der Push haengt am Commit. Vorher stand er in einem eigenen if, und ein an
  # .git/index.lock gescheiterter Commit fuehrte trotzdem zu "gepusht" im Protokoll.
  if ! git commit -q -m "Wochenlauf $(date '+%d.%m.%Y')"; then
    sage "FEHLER beim Einchecken — nicht gepusht"
    exit 1
  fi
  sage "eingecheckt"
  if git push -q origin HEAD:main 2>>"$PROTOKOLL"; then
    sage "gepusht — GitHub Pages liefert in ein bis zwei Minuten aus"
  else
    # Der häufigste Grund ist nicht die Anmeldung, sondern ein Push von anderswo:
    # der zweite Klon oder eine Reparatur zwischen Lauf und Push. Am 27.08.2026 war
    # es genau das, und die alte Meldung schickte die Fehlersuche zum Schlüsselbund.
    # Also erst nachziehen und ein zweites Mal versuchen, dann urteilen.
    sage "Push abgelehnt — hole erst den Fernstand und versuche es erneut"
    if git pull --rebase -q origin main 2>>"$PROTOKOLL" \
       && git push -q origin HEAD:main 2>>"$PROTOKOLL"; then
      sage "gepusht nach Nachziehen — GitHub Pages liefert in ein bis zwei Minuten aus"
    else
      sage "FEHLER beim Push. Die Git-Meldung steht oben in diesem Protokoll:"
      sage "  abgelehnt (fetch first) heisst Fernstand voraus — von Hand rebasen."
      sage "  Authentication/403 heisst Zugangsdaten — Schlüsselbund prüfen."
      exit 1
    fi
  fi
fi

sage "── Wochenlauf fertig"

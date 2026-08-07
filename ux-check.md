# UX-Check — Schweizer Weinaktionen

**Auditziel:** https://hilfsscheriff.github.io/Vivino-check/
**Quelle im Repository:** [src/winecheck/report/site.py](src/winecheck/report/site.py) (Generator), [docs/index.html](docs/index.html) (Artefakt, 201 KB)
**Datum:** 7. August 2026 · Datenstand der ausgelieferten Seite: 6.8.2026, 14:23

> **Codestand — bitte zuerst lesen.** Geprüft wurde die **ausgelieferte** Seite; sie entspricht dem Generator aus Commit `11feb28`. Während des Audits (7.8.2026, 14:30) ist Commit `926f611` „Aligro als Quelle, bessere Vivino-Abfrage, Filter nach oben" dazugekommen und hat `site.py` an 136 Zeilen geändert. **Alle `site.py:`-Zeilenangaben in diesem Bericht beziehen sich auf `11feb28`** — den Stand, der die gemessene Seite erzeugt hat. Was `926f611` bereits erledigt und was offen bleibt, steht in [Abschnitt 2a](#2a-abgleich-mit-dem-aktuellen-codestand-926f611).

---

## 1. Kurzfazit

Die Seite ist technisch bemerkenswert sauber gebaut: eine einzige Datei ohne Drittanbieter, kein horizontales Scrollen von 320 px bis 1280 px, ein Neuaufbau von 400 Zeilen in gemessenen **9 ms**, und die Spaltenfilter wirken bewusst auf Diagramm, Zähler und Tabelle gleichzeitig. Der Textkontrast ist in beiden Farbschemata durchgehend gut (hell ≥ 4.7:1, dunkel ≥ 6:1). Das Fundament trägt.

Das Problem liegt nicht in der Umsetzung, sondern darin, **für wen die Seite gebaut ist**. Der Quelltext nennt als Zweck ausdrücklich die Situation „wenn man am Tisch sitzt und schlechten Empfang hat" — also das Handy. Genau dort wird das Diagramm per `display:none` komplett ausgeblendet, und die Tabelle bietet keinen Ersatz: Es gibt keine Sortierung nach Preis-Leistung. Die Standardsortierung „Note, beste zuerst" eröffnet die Liste mit einer Flasche für CHF 275 und einer für CHF 590. Die Aussage des Diagramms — „oben links = gut und günstig" — existiert auf dem Handy in keiner Form.

**Grösstes systemisches Risiko:** 58 der 127 Diagrammpunkte (46 %) und 58 Tabellenzeilen zeigen eine Vivino-Note aus einem **unbestätigten Namensabgleich** — kenntlich nur an einem hohlen Kreis ohne Legende bzw. an einem einzelnen „?" mit `title`-Attribut, das auf Touch-Geräten nicht existiert. Der Code unterdrückt Produzenten-Mittelwerte aus genau dieser Sorge heraus ([site.py:66](src/winecheck/report/site.py#L66)), zeigt fuzzy-Treffer aber mit vollem visuellem Gewicht. Eine Kaufentscheidung kann so auf der Note eines anderen Weins beruhen.

**Empfohlener erster Schritt:** Die Trefferqualität sichtbar machen (F-01) und eine Preis-Leistungs-Sortierung als Standard einführen (F-02). Beides sind kleine Änderungen im Generator und beheben die zwei Probleme, die den Kernzweck der Seite unterlaufen.

---

## 2. Scope und Methode

| Bereich | Geprüft |
|---|---|
| Screens und Flows | Eine Single-Page-Ansicht: Suche → Filter (Lauf, Trinkreife, Sorte, Händler) → Spaltenfilter → Diagramm → Tabelle → Footer. Flows: Wein suchen, filtern, sortieren, Leerzustand, Zurücksetzen, Tooltip abrufen |
| Viewports | 320 × 800, 375 × 812 (Mobile-Emulation), 1280 × 900 — jeweils hell und dunkel |
| Zustände und Rollen | Default, Hover (Diagramm-Tooltip), Focus (Tastatur), aktiv/inaktiv (Chips), Empty (0 Treffer), Sonderfall 1 Treffer, nach Reset. Nur eine Rolle — die Seite kennt keine Anmeldung |
| Quellen | Gerenderte Seite (Browser-MCP, DevTools-Messungen via JavaScript) **und** Generator-Quellcode |
| Nicht geprüft | Echte Geräte, Screenreader (VoiceOver/NVDA), Safari/Firefox, Landscape, mehrere Läufe im `Lauf`-Filter (produktiv nur einer vorhanden), Druckansicht |

**Messmethode.** Alle Grössen-, Kontrast- und Geometriewerte stammen aus `getComputedStyle` und `getBoundingClientRect` auf der live ausgelieferten Seite. Kontraste sind nach WCAG-2.x-Relativluminanz berechnet, Hintergründe durch Hochlaufen der Elternkette bis zur ersten deckenden Fläche ermittelt. Textzoom wurde durch Setzen von `html { font-size: 32px }` (= 200 %) simuliert.

**Einschränkungen.** Dies ist ein Grundlagencheck, **keine Accessibility-Zertifizierung**. Es wurde kein Screenreader eingesetzt; Aussagen zu assistiver Technik beruhen auf der DOM- und Codestruktur. Die Mobile-Werte stammen aus einer Viewport-Emulation mit Touch-Übersetzung, nicht von einem physischen Gerät. Screenshots tiefer Scrollpositionen liefen im Browser-Panel leer zurück — ein Werkzeugartefakt, kein Seitenfehler: Das DOM meldete an derselben Position 16 gerenderte Zeilen im Viewport. Die ausgelieferte Seite entspricht dem Repository-Stand (Stylesheet-Länge und Breakpoint-Regel verifiziert).

---

## 2a. Abgleich mit dem aktuellen Codestand (`926f611`)

Commit `926f611` ist nach Beginn des Audits entstanden und nimmt einige Punkte schon vorweg. Der Abgleich ist statisch am Generator geprüft (`git diff 11feb28 926f611 -- src/winecheck/report/site.py`); die Wirkung ist **noch nicht gerendert verifiziert**, weil die ausgelieferte Seite den älteren Stand zeigt.

| Finding | Stand in `926f611` | Was bleibt |
|---|---|---|
| **F-10** px skaliert nicht mit | **erledigt** — `.colfilter` 13 px → `.controls` `.82rem`, `.colhint` 12 px → `.74rem` ([site.py:268](src/winecheck/report/site.py#L268), [278](src/winecheck/report/site.py#L278)). In HTML-Text steht kein absoluter px-Wert mehr | Nach dem nächsten Deploy bei 200 % Wurzelschriftgrösse nachmessen |
| **F-03** Fokusstil | **teilweise** — `:focus-visible { outline:2px solid var(--brand); outline-offset:2px }` für `.controls select`, `.chip`, `.reset` ([site.py:274](src/winecheck/report/site.py#L274)). Genau der empfohlene Wert | Fehlt noch für Suchfeld, Tabellenlinks und `.sortbtn` — am einfachsten als globale `:focus-visible`-Regel. **Skip-Link und die 805 Tabstopps sind unverändert offen** |
| **F-15** Feinauswahl weit von den Chips entfernt | **teilweise** — alle Filter liegen jetzt in einer Karte `.filters`, „Feinauswahl" als eigenes `fieldset`, der Sortierhinweis ist aus der Tabellenkarte heraus ([site.py:265–283](src/winecheck/report/site.py#L265)) | Sticky bleibt allein das Suchfeld; die zwei Breakpoints 720 px ([site.py:293](src/winecheck/report/site.py#L293)) und 767 px ([site.py:281](src/winecheck/report/site.py#L281)) bestehen weiter |
| **F-07** Touch-Ziele | **minimal besser** — Checkbox 13 → 15 px, `accent-color` gesetzt | 15 px statt 44 px; `.chip` weiter `min-height:36px` ([site.py:222](src/winecheck/report/site.py#L222)), Selects ~30 px |
| **F-02** Mobile ohne Diagramm und ohne Wertsortierung | **offen** — `.chart { display:none }` bei ≤ 720 px ([site.py:298](src/winecheck/report/site.py#L298)), Sortieroptionen unverändert sechs | Verschärft sich sogar: Die Filterkarte ist jetzt länger, der erste Mobile-Bildschirm zeigt noch mehr Formular vor dem ersten Wein |
| **F-01** unbestätigte Treffer | **offen** — `<span class="warn" title="…">?</span>` ([site.py:569](src/winecheck/report/site.py#L569)), hohle Punkte ([site.py:487](src/winecheck/report/site.py#L487)) | unverändert |
| **F-04** widersprüchlicher Leerzustand | **offen** — Meldung unverändert ([site.py:458](src/winecheck/report/site.py#L458)) | unverändert |
| **F-05** Farbpaletten | **offen** — `_PALETTE` und `_MATURITY_COLOURS` unverändert ([site.py:40–47](src/winecheck/report/site.py#L40)) | unverändert |
| **F-08** `--line` für alles | **offen** — `--line:#e2dadd` ([site.py:195](src/winecheck/report/site.py#L195)), Chip- und Select-Rahmen nutzen es weiter | unverändert |
| **F-09** Typografie | **offen, leicht verschoben** — neu `.controls` `.82rem` (= `.sub`) und `.colhint` `.74rem` (= `.chip .n`). Die Zahl der Werte sinkt nicht, die Doppelbelegung gleicher Grössen für verschiedene Rollen nimmt zu | unverändert |
| **F-06, F-11, F-12, F-13, F-14** | **offen** — Legende, Jahrgangsdopplung ([site.py:582](src/winecheck/report/site.py#L582)), Leerwerte, `aria-live`/`<main>`/`role="tooltip"` ([site.py:399](src/winecheck/report/site.py#L399)), `#fRun` ([site.py:325](src/winecheck/report/site.py#L325)) | unverändert |

**Folge für die Reihenfolge in Abschnitt 9:** Quick Win 4 (px → rem) entfällt, Quick Win 2 (Fokusstil) schrumpft auf „Regel auf alle Bedienelemente ausweiten". Die Ränge 1–5 der Top-5-Massnahmen bleiben unberührt.

---

## 2b. Umsetzungsstand (Commit `457c8df`, 7.8.2026)

Die zehn Quick Wins aus Abschnitt 9 sind umgesetzt und am gerenderten Ergebnis nachgemessen (lokal über HTTP, damit das Skript läuft). Neuer Datenstand: **615 Weine**.

| Quick Win | Umgesetzt | Gemessenes Ergebnis |
|---|---|---|
| 1 · Leerzustand (F-04) | ja | Bei 0 Treffern wird die Diagrammkarte ausgeblendet (`hidden`); die Tabelle allein meldet „Kein Wein passt zu dieser Auswahl." Bei Treffern ohne Note: „Kein Wein dieser Auswahl hat eine Vivino-Note. Die Tabelle zeigt sie trotzdem, mit Preis und Händler." — beide Zweige einzeln geprüft |
| 2 · Fokusstil (F-03a) | ja | Eine globale `:focus-visible`-Regel (2 px `--brand`, Offset 2 px) statt drei Einzelselektoren; gilt jetzt auch für Suchfeld, Tabellenlinks und Sortierköpfe |
| 3 · Jahrgang / „unbekannt" (F-11a, c) | ja | Doppelte Jahrgänge **293 → 0**; „unbekannt"-Pills **97 → 0**; Pills gesamt 588 → 491. Der Filter-Chip „unbekannt" greift weiter (Test deckt das ab) |
| 4 · px → rem (F-10) | entfiel | War in `926f611` schon erledigt |
| 5 · Diagrammlegende (F-06a) | ja | „Farbe = Händler · ○ hohler Kreis = Vivino-Treffer unsicher, die Note kann zu einem anderen Wein gehören" — eigene Klasse `.legend`, bewusst **nicht** unter 767 px versteckt wie `.colhint`, da das Diagramm erst bei 720 px verschwindet |
| 6 · Touch-Ziele (F-07) | ja | Über `--control-h` mit `@media (pointer: coarse)`: auf Touch **44 px** für Chips, Selects, Reset und die ganze Checkbox-Zeile (Checkbox selbst 20 px), auf Zeigergeräten kompakte 36 px — sonst wäre die Filterkarte am Desktop unnötig hoch |
| 7 · `--line-strong` (F-08) | ja | Neues Token, nur für Bedienelemente. Suchfeld und Chip **1.35 → 3.68:1**, Select **1.26 → 3.42:1** gegen ihre Fläche. Tabellenlinien bleiben bei `--line` (1.26:1) — dort ist leise richtig. Der Hellwert `#918085` ist der hellste, der gegen Seitenhintergrund, Karte *und* Chipfläche noch 3:1 schafft |
| 8 · Semantik (F-13) | ja | `<main>` ergänzt, `aria-live="polite"` am Zähler, `role="tooltip"` ohne `aria-describedby` entfernt |
| 9 · „Lauf"-Gruppe (F-14) | ja | `runBox.hidden` bei weniger als zwei Läufen — verifiziert versteckt |
| 10 · Leerwerte / Abdeckung (F-12a, b) | ja | 315 leere „gegen Markt"-Zellen tragen `noval` und entfallen in der Kartenansicht; Zähler nennt jetzt die Abdeckung: „… · 85 mit Marktpreis" |

**Nebenwirkung, bewusst in Kauf genommen:** Die 44-px-Ziele machen die Filterkarte höher — der erste Wein rutscht auf dem Handy von y = 864 px auf **y = 1061 px**. Die Seitenhöhe sinkt trotzdem von 74 839 px auf **64 864 px** (−13 %), weil leere Marktpreis-Zeilen und „unbekannt"-Pills wegfallen. Der eigentliche Fix bleibt F-02 (einklappbare Filter plus „Top 10 Preis-Leistung"), nicht weiteres Kürzen an den Zielgrössen.

**Regressionsschutz:** [tests/test_site.py](tests/test_site.py) — 20 Tests am erzeugten Dokument (Tokens, Breakpoint-Verhalten, Leerzustandslogik, Semantik, Selbstgenügsamkeit ohne Drittanbieter). Gesamtsuite: 331 bestanden, 7 übersprungen (Netzwerktests, `WINECHECK_LIVE=1`).

## 2c. Zweiter Durchgang: F-05 und der Vertrauens-Fix

### F-05 — Farbkollisionen behoben

Der Konflikt war strukturell nicht lösbar, solange beide Bedeutungen Farbe ausgeben: Sperrt man Grün/Teal/Amber für die Trinkreife, bleibt für acht gedeckte Händlerfarben zu wenig Hue-Budget — der geringste Paarabstand fiel auf ΔE 26.3, schlechter als die 30.0 vorher.

Ausschlaggebend war, wofür die Farbe tatsächlich getragen wird: Die **Trinkreife-Farbe stand an genau einer Stelle** — dem Punkt in ihrem eigenen Filter-Chip, direkt neben der Beschriftung, die dasselbe schon sagte. Die **Händlerfarbe** ist im Diagramm dagegen das einzige Händlersignal. Also hat die Trinkreife den Farbkanal abgegeben.

| | vorher | nachher |
|---|---|---|
| Farben mit zwei Bedeutungen | 4 | **0** (strukturell unmöglich) |
| geringster Abstand der Händlerfarben | ΔE 30.0 | **ΔE 41.9** |
| schlechtester Kontrast dunkel | 1.45:1 (Coop) | **3.00:1** |
| schlechtester Kontrast hell | 2.82:1 (Otto's) | **3.22:1** |

Umsetzung: `_SHOP_LIGHT`/`_SHOP_DARK` mit einem Wert je Schema, ausgegeben als CSS-Variablen (`--shop-<key>`) mit `@media (prefers-color-scheme: dark)`-Überschreibung. Die Payload trägt den Variablennamen, nicht den Hexwert — als Hexwert in der JSON könnte die Farbe nicht auf das Schema reagieren. Punkte werden über `style="fill:var(…)"` gefärbt, weil Präsentationsattribute kein `var()` annehmen. `_check_palette()` hält die Zusage fest, damit ein neunter Händler nicht still eine unsichtbare Farbe bekommt.

**Bewusste Nebenwirkung:** Die Trinkreife-Chips haben keinen Farbpunkt mehr. Die Abstufung „jetzt → später" trägt die Chip-Reihenfolge, den Wert die Beschriftung. Wer die Punkte zurück will, braucht eine eigene, nicht-kategoriale Kodierung — sonst kehrt die Kollision zurück.

### F-01 — Vertrauenssignal: die Fehlalarme sind weg

Ausgangspunkt war ein konkreter Fall: Mövenpicks „Mendoza 2021 Chardonnay Alta Angelica Zapata" war korrekt auf Vivino-ID `w/68864` gematcht und trotzdem als unsicher markiert. Ursache: Score 90.9 gegen die Schwelle 93.0, und das einzige nicht abgedeckte Wort war **`mendoza`** — die Region. Händlernamen tragen Region, Land, Farbe und Flaschengrösse mit, Vivino nennt nur den Wein.

Für die Konfidenz zählt jetzt zusätzlich ein Vergleich, der nur die unterscheidenden Bestandteile ansieht ([matching.py](src/winecheck/matching.py)). Bewusst **nur die Konfidenz, nicht die Match-Entscheidung** — welcher Kandidat gewinnt, bleibt unverändert.

Gemessen über die 75 im Lauf als unsicher gespeicherten Paare, alter gegen neuer Matcher:

| Übergang | Anzahl |
|---|---|
| `fuzzy` → `exact` (Wirkung dieser Änderung) | **17** |
| bleibt `fuzzy` (Produzent fehlt wirklich) | 27 |
| war schon `none` (Vetos aus `926f611`) | 21 |
| war schon `exact` / `wine_level` | 10 |
| **Verschlechterungen (bestätigt → unsicher)** | **0** |

Die Fuzzy-Quote unter den bewerteten Weinen sinkt damit von 39 % auf rund 15 %. Was zu Recht markiert bleibt: „Oeil de Perdrix Rosé" ohne „Caves des Coteaux", „Páramos" ohne „Legaris", „Bardolino Classico" ohne „Zeni" — überall fehlt der Produzent im Vivino-Namen. Die Begründung nennt jetzt das fehlende Wort, statt nur „ähnlich" zu sagen.

**Zusatzsicherung:** Heisst ein Weingut nach einer Lage („Caves des Coteaux"), verschwindet der Produzent aus den Tokens — `caves` ist ein Betriebswort, `coteaux` kann als Appellation gelten. Über Vokabular allein ist das nicht trennbar. `_uncovered_producer_words()` prüft darum über `seq`, das die Betriebswörter behält. **Offen gesagt:** Am aktuellen Lauf ändert dieser Schutz nichts (0 Weine hängen an ihm), weil `coteaux` inzwischen nicht mehr als Region geführt wird und der Identitäts-Zweig den Fall schon fängt. Er ist eine Sicherung gegen das handgepflegte Vokabular, kein aktiv tragender Pfad — und als solcher direkt getestet.

**Wichtig für die Wirkung:** Die Konfidenz wird beim `rate`-Lauf in den Cache geschrieben. Die ausgelieferte Seite zeigt die 17 bestätigten Treffer erst nach dem nächsten Rating-Durchgang.

### F-02 — Kernaufgabe: Preis-Leistung, Paginierung, einklappbare Filter

**Der Score.** „Gut und günstig" ist im Diagramm „oben links". Als Zahl: die Regression der Note auf `log10(Preis)` über den Lauf, und der Rest je Wein. Aus den Daten selbst geschätzt statt geraten — im aktuellen Lauf lautet der Trend `Note = 3.313 + 0.481 · log10(Preis)`, eine Verzehnfachung des Preises bringt also knapp einen halben Notenpunkt. Der Wert heisst damit „so viel besser als üblich für dieses Geld", nicht „billig": ein Ruinart für CHF 89.50 steht mit +0.25 auf Platz 6.

Logarithmisch, weil die Note es auch ist — linear gerechnet würde die Spanne von CHF 4.60 bis 590 die Rangfolge von den teuren Weinen her bestimmen. Bei 0.16 Streuung der Residuen würde ein Wein mit zwölf Bewertungen die Liste zufällig anführen, darum wird nach Bewertungszahl gedämpft (`count/(count+50)`). Gerechnet über den ganzen Lauf, nicht über die gefilterte Auswahl: sonst änderte ein Wein seinen Rang, je nachdem was sonst angezeigt wird.

Der Wert steht als eigene Spalte da und ist über der Tabelle in einem Satz erklärt — wonach sortiert wird, muss sichtbar sein.

**Wirkung, gemessen am gerenderten Ergebnis:**

| | vorher | nachher |
|---|---|---|
| Standardsortierung | Note (Liste eröffnete mit CHF 275 und CHF 590) | **Preis-Leistung** |
| Zeilen im DOM | 400 | **50** + „Weitere 50 anzeigen" |
| unerreichbare Weine | 223 hinter dem Deckel | **0** |
| Tabstopps | 834 | **137** (−84 %) |
| Seitenhöhe Desktop | 26 848 px | **4 473 px** |
| Seitenhöhe Handy | 74 839 px | **10 978 px** (−85 %) |
| erster Wein bei 375 px | y = 864 px | **y = 526 px** (über der Falz) |

**Einklappbare Filter.** Die Wertsortierung ändert nur, *was* oben in der Liste steht, nicht *wo* die Liste beginnt — nach den 44-px-Zielen und der Erklärzeile lag der erste Wein bei y = 1210 px, schlechter als vorher. Darum liegen die Filter am Handy in einem `<details>` mit Zähler in der Summary („Filter · 2 aktiv"); Trefferzähler und „Filter zurücksetzen" bleiben ausserhalb und damit immer sichtbar. `<details>` statt eigener Logik, weil Tastatur und Screenreader gratis mitkommen — verifiziert: der Fokus greift nicht in eingeklappte Filter.

Am Desktop ist der Aufklapper ausgeblendet und der Inhalt offen. Diese Kopplung ist die riskante Stelle: greift sie nicht, sind die Filter unerreichbar — kein Griff zum Öffnen, kein Inhalt. Sie hängt darum an der gerenderten Lage der Summary (`getComputedStyle(...).display === "none"`) und an `resize`, nicht an einem `change`-Ereignis der Media Query. Beim Testen war genau das der Fehlerfall: nach einem Breitenwechsel ohne Neuladen blieb `open` falsch.

**Was hier nicht besser wurde:** Der Deckel ist weg, aber lange Listen bleiben lang — wer alle 623 Weine sehen will, klickt zwölfmal. Für den Zweck der Seite („welche Flasche lohnt sich") ist das richtig herum: die Antwort steht auf Seite 1.

## 2d. Dritter Durchgang: F-09, F-15, F-06b, F-11 — damit sind alle Findings erledigt

### F-09 — fünf Textrollen statt dreizehn Werte

Zwischen 11 und 13.6 px lagen zehn Grössen, mehrere unter 0.5 px auseinander — nicht zu sehen, aber dreifach zu pflegen; gleichzeitig teilten verschiedene Rollen dieselbe Grösse. Jetzt: `--fs-page-title` 24, `--fs-title` 18, `--fs-body` 16, `--fs-body-sm` 14, `--fs-label` 12 px. **Gemessen kommen genau fünf Grössen an** (12/14/16/18/24). Der Lesetext liegt auf 16 px statt 13.6 — die Tabelle ist die am längsten gelesene Fläche der Seite. SVG-Text bleibt bewusst in px: er skaliert über die `viewBox` mit der Diagrammbreite, nicht mit der Wurzelschrift.

### F-15 — ein Breakpoint, Zähler und Rückweg bleiben stehen

720 und 767 px nebeneinander erzeugten zwischen den beiden Werten einen Zustand mit sortierbaren Spaltenköpfen, deren Hinweis ausgeblendet war. Jetzt gilt durchgehend 720 px (und 721 px für die Gegenrichtung).

Suchfeld, Treffermenge und „Filter zurücksetzen" stehen zusammen in der sticky Leiste — wer in der Liste liest, ändert die Auswahl ohne Rückweg. Die Abdeckungsangaben sind dafür heruntergerutscht: „623 von 623 Weinen" bleibt oben, „210 davon mit Vivino-Note · 152 mit Marktpreis" steht in der Filterkarte. Das eine ändert sich mit jedem Klick, das andere ist ein Nachschlagewert — und beides zusammen hätte die Leiste am Handy auf zwei Zeilen gebracht. Kosten der Leiste: 111 px, 14 % des Viewports.

**Zwei Fehler, die beim Prüfen aufgefallen sind:**

1. Die Kopplung „Aufklapper versteckt → Inhalt offen" war einseitig gedacht. Nach einem Wechsel von breit zu schmal — Drehen, Fenster ziehen — blieben die Filter offen und füllten den ersten Bildschirm wieder. Sie ist jetzt zweiseitig und respektiert eine bewusste Nutzerentscheidung.
2. Dieser Merker hing am `toggle`-Ereignis, das asynchron feuert: ein unmittelbar folgender Resize überschrieb die Wahl. Er hängt jetzt am Klick.

### F-06b — Überlappung im Diagramm

Ein kleinerer Radius allein bringt nichts: von 6 auf 5 gesenkt bleiben 45 statt 46 Punkte verdeckt — die Punkte liegen in den Daten aufeinander, nicht bloss optisch. Wirksam sind zwei andere Dinge: `fill-opacity: .82` macht Häufungen als dunklere Fläche lesbar, und der Tooltip nennt die Nachbarn („4 weitere Weine an dieser Stelle", mit Note und Preis, ab fünf mit Verweis auf die Tabelle). Damit ist kein Wein mehr unsichtbar, auch wenn er hinter einem anderen liegt.

**Touch-Unterstützung ergänzt.** Zwischen 721 und 900 px ist das Diagramm sichtbar, es hingen aber nur Maus-Ereignisse daran — auf einem Tablet waren die Tooltips damit unerreichbar. Jetzt zeigt das erste Antippen den Wein, das zweite öffnet ihn; Tippen daneben schliesst. Das war ein Punkt aus den offenen Prüfungen in Abschnitt 10, nicht aus den Findings.

### F-11 — Anzeigenamen von Händler-Beiwerk befreit

„Rioja DOCa Crianza Bodegas Izadi (2022) – Rotwein, Spanien (0.75l)" wird zu „Rioja DOCa Crianza Bodegas Izadi". Entfernt werden Farbe (steht als Pill daneben), Land (trägt nichts), die Standardgrösse 0.75 l (Bezugsgrösse des Preises) und der Jahrgang in Klammern (wird einheitlich angehängt).

**Was bewusst bleibt:** Magnum, Halbflasche und Sechserpack. „Ruinart Blanc de Blancs, 1.5 l" ist ein anderer Kauf, keine Wiederholung — das war die Stelle, an der ein grobes „alles nach dem Komma weg" falsch gewesen wäre.

| | vorher | nachher |
|---|---|---|
| Namenslänge Median | 56 Zeichen | **41** |
| Namenslänge Max | 109 | **98** |
| Namen mit Jahrgang im Text | 463 | 273 (der Rest wird angehängt) |

Bereinigt wird nur die **Anzeige**: gematcht und dedupliziert wurde vorher mit dem Originalnamen, und `key` bleibt der Originalschlüssel — durch Tests festgehalten.

### Endstand, gemessen bei 375 px

| | Ausgangslage | jetzt |
|---|---|---|
| erster Wein | y = 864 px | **y = 492 px** |
| Seitenhöhe | 74 839 px | **12 381 px** |
| Zeilen im DOM | 400 | **50** |
| Tabstopps | 834 | **138** |
| Textgrössen | 13 Werte, zehn davon zwischen 11 und 13.6 px | **5** |
| Lesetext | 13.6 px | **16 px** |
| Farben mit zwei Bedeutungen | 4 | **0** |
| schlechtester Händlerkontrast | 1.45:1 (dunkel) | **3.22:1** |
| unerreichbare Weine | 223 | **0** |

## 2e. Vierter Durchgang: Richtung „Etikette" umgesetzt

Nach drei Durchgängen an Struktur und Verhalten hat die Seite ein Designsystem bekommen — Richtung 02 aus den Vorschlägen, nach der Weinetikette gebaut. **Funktion und Verhalten bleiben unverändert:** Preis-Leistung als Standardsortierung, Paginierung, einklappbare Filter, sticky Zähler, Leerzustände, Fokusstil, Landmarken. Neu ist die visuelle Sprache.

| | vorher | jetzt |
|---|---|---|
| Schrift | eine System-Sans für alles | **Didot** (Titel, Weinnamen, Kennzahl) · **Optima** (Text) · **Menlo** (Zahlen) |
| Trennung | gefüllte Karten mit Radius | **Haarlinien**, keine Flächen |
| Bedienelemente | umkastete Felder | **unterstrichen**; nur Pillen behalten ihren Umriss, weil sie schaltbar sind |
| Kennzahl | 14 px Mono, grün/rot | **Didot 1.55 em in Gold** — der Anker der Seite |
| Sorte/Trinkreife | gefüllte Pills | gesperrte Versalien |

**Farbe hat drei Aufgaben und keine vierte:** Akzent (bedienbar), Urteil (gut/schwach), Gold (Wert). Der Händler hat seine Farbe **abgegeben** — er stand nur im Diagramm als Punktfarbe, und dieselben Töne mussten dort gleichzeitig die Trinkreife tragen. Jetzt steht sein Name in der Tabelle und im Tooltip. Damit entfallen die erzeugten `--shop-*`-Variablen und die Palettenprüfung ersatzlos; an ihre Stelle tritt `check_tokens()`, das jede Textfarbe gegen ihren Grund prüft.

Gold ist der Sonderfall: `#9a7b4f` erreicht auf dem hellen Grund nur **3.75:1**. Es trägt darum ausschliesslich Grossgrade und Flächen — die Kennzahl, die Zonenkante. Kleintext in Gold nimmt `--goldtx` mit 4.74:1. Das ist im Test als milderes Ziel (3:1) festgehalten, mit Begründung.

### Das Diagramm zeigt jetzt zwei Dinge getrennt

- **Der Vektor** läuft von der Trendlinie zum Punkt: Richtung = mehr oder weniger Note fürs Geld, Länge = wie viel. Das ist genau die Grösse, nach der die Liste sortiert ist — vorher musste man den Abstand zur Linie schätzen.
- **Das markierte Feld** ist eine feste Regel: **ab Note 4.2 und bis CHF 20**, nur dieser Bereich. Absolut, nicht relativ zur Trendlinie: „besser als üblich fürs Geld" trifft auch eine mittelmässige Flasche für CHF 8.

Die Regel ist eng — im Lauf vom 7.8. erfüllen sie **2 von 174 bewerteten Weinen**. Das Feld nennt seine Regel und die Trefferzahl selbst („2 von 174 Weinen"), damit die Leere nicht wie ein Fehler wirkt, und die erfüllenden Weine sind direkt beschriftet. In der Tabelle tragen sie „◆ gut und günstig". Tabelle und Diagramm benutzen dieselbe Funktion, und die Schwellen stehen als `GOOD_RATING_MIN`/`GOOD_PRICE_MAX` in der Payload — eine Zahl, eine Wahrheit.

### Vier Mängel, beim Prüfen der eigenen Arbeit gefunden

1. **Das Auswahlfeld hatte eine feste Höhe** (`min-height:32px`) statt des Tokens — auf Touch also 32 px statt 44. Der Test für die Touch-Ziele hat es gefangen.
2. **Der Diagrammtext benutzte `.tblnote`**, die Klasse der Tabellenerklärung. Damit zeigte die Prüfung auf den falschen Absatz; jetzt hat er `.chartnote`.
3. **Die Trendlinie war heller als ihr Legendensymbol** — sie lief unter `.axis` (`--line`), das Symbol unter `--muted`. Diagramm und Legende sagten Unterschiedliches; die Linie hat jetzt `.trend`.
4. **Zwei Trennlinien übereinander** zwischen sticky Leiste und Filterkarte, mit leerer Lücke dazwischen.

Kontrolle am gerenderten Ergebnis: **null Kontrastverstösse** in hell und dunkel (4.5:1 Kleintext, 3:1 Grossschrift, Alpha-Kompositing berücksichtigt), kein horizontales Scrollen bei 375 und 1180 px. Suite grün, `tests/test_site.py` auf die Richtung nachgezogen: die Palettentests sind entfallen, dazugekommen sind Tokenzusage, Regelgrenzen, Vektor- und Legendenprüfung sowie ein Test, dass der Händler keine Farbe mehr trägt.

### Was diese Richtung kostet

Didot bricht unter etwa 16 px weg und darf nur gross gesetzt werden — das kostet Höhe. Und die Richtung ist beim Scannen die langsamste der drei Vorschläge: für „schnell im Laden nachsehen" wäre Board 03 oder 04 stärker gewesen. Die Wahl ist getroffen; das bleibt der bewusste Preis.

### Noch offen — und ein Hinweis zur Commit-Nachricht

Die Nachricht von `457c8df` nennt „vier Farbverwechslungen behoben". **F-05 ist im Code unverändert:** `_PALETTE` und `_MATURITY_COLOURS` teilen weiterhin dieselben Werte ([site.py:40–47](src/winecheck/report/site.py#L40)). Im neu erzeugten `docs/index.html` sind es weiterhin **genau vier Kollisionen** — sie sind durch den neuen Händler Aligro nur *umverteilt*, weil `_PALETTE` nach sortierter Händlerreihenfolge indexiert wird:

| Farbe | vorher | jetzt |
|---|---|---|
| `#2e7d32` | Mövenpick + „jetzt trinken" | **Denner** + „zurzeit höchster Genuss" |
| `#1a4f8a` | Denner + „lagern" | **Coop** + „zu jung — reifen lassen" |
| `#ef6c00` | Otto's + „austrinken" | **Mövenpick Wein** + „Zenit überschritten" |
| `#00838f` | SPAR + „kann liegen" | **Prodega** + „macht Spass, wird noch besser" |

Zum Zeitpunkt dieser Notiz war F-05 damit offen. Erledigt wurde es im zweiten Durchgang, siehe Abschnitt 2c.

### Stand aller Findings

| Finding | Stand | wo beschrieben |
|---|---|---|
| F-01 unbestätigte Treffer | **erledigt** — 17 Fehlalarme weg, Fuzzy-Quote 39 % → 15 % | 2c |
| F-02 Mobile / Kernaufgabe | **erledigt** — Preis-Leistung als Standard, Paginierung, einklappbare Filter | 2c |
| F-03 Tastatur | **erledigt** — Fokusstil global, Tabstopps 834 → 138 | 2b, 2c |
| F-04 Leerzustand | **erledigt** | 2b |
| F-05 Farbkollisionen | **erledigt** — 4 → 0, ΔE 30 → 42 | 2c |
| F-06 Diagramm | **erledigt** — Legende, Teiltransparenz, Häufungsliste, Touch | 2b, 2d |
| F-07 Touch-Ziele | **erledigt** — 44 px auf Touch | 2b |
| F-08 Non-Text-Kontrast | **erledigt** — 1.35:1 → 3.68:1 | 2b |
| F-09 Typografie | **erledigt** — 13 Werte → 5 Rollen, Lesetext 16 px | 2d |
| F-10 px skaliert nicht | **erledigt** (war schon in `926f611`) | 2a |
| F-11 Namen | **erledigt** — Median 56 → 41 Zeichen | 2b, 2d |
| F-12 Marktpreis | **erledigt** — Leerwerte weg, Abdeckung benannt | 2b |
| F-13 Semantik | **erledigt** — `<main>`, `aria-live`, ARIA aufgeräumt | 2b |
| F-14 Lauf-Filter | **erledigt** | 2b |
| F-15 Sticky / Breakpoints | **erledigt** — ein Breakpoint, Zähler bleibt stehen | 2d |

Damit sind alle fünfzehn Findings abgearbeitet. Was offen bleibt, sind die Prüfungen, die dieses Audit nicht leisten konnte — siehe Abschnitt 10.

---

## 3. Bereichsbewertung

> Diese Tabelle beschreibt die **Ausgangslage** vom 7.8.2026 und bleibt als Vergleichsmassstab stehen. Der erreichte Stand steht in den Abschnitten 2a–2d.

| Bereich | Urteil (Ausgangslage) | Begründung in einem Satz |
|---|---|---|
| Typografie | **uneinheitlich** | Zehn kaum unterscheidbare Grössen zwischen 11 und 13.6 px, während der eigentliche Lesetext mit 13.6 px unter der deklarierten 16-px-Basis liegt. |
| Spacing und Layout | **solide** | Konsistente Kartenpaddings und Abstände, kein horizontales Scrollen auf keiner geprüften Breite. |
| Komponenten und Zustände | **uneinheitlich** | Zustände sind gedacht (`aria-pressed`, Empty, 1-Treffer-Sonderfall), aber es gibt keinen eigenen Fokusstil und Bedienelemente sind am Rand kaum erkennbar (1.19–1.35:1). |
| Bedienbarkeit und Nutzerführung | **kritisch** | Die Kernfrage „welche Flasche lohnt sich?" ist auf dem Handy nicht beantwortbar, und Notenqualität wird nicht kommuniziert. |
| Responsive Verhalten | **uneinheitlich** | Reflow und Umbrüche sind vorbildlich, aber der wichtigste Inhalt wird auf Mobile ersatzlos entfernt. |
| Accessibility-Grundlagen | **uneinheitlich** | Kontraste und Semantik grösstenteils gut, aber 805 von 834 Tabstopps liegen in der Tabelle, kein Fokusstil, keine Live-Region. |

---

## 4. Top-5-Massnahmen

| Rang | Massnahme | Warum jetzt? | Betroffene Bereiche | Priorität | Aufwand |
|---:|---|---|---|---|---|
| 1 | Unbestätigte Vivino-Treffer als beschriftetes Merkmal auszeichnen, auf Touch abrufbar (F-01) | 46 % der Diagrammpunkte und 58 Tabellenzeilen tragen eine möglicherweise fremde Note; das Warnzeichen ist auf dem Handy unsichtbar | Vertrauen, Kernentscheidung, A11y | **P1** | S |
| 2 | Sortierung „Preis-Leistung" einführen und zum Standard machen (F-02) | Auf Mobile fehlt das Diagramm; ohne Wertsortierung führt die Liste mit CHF 590 an | Kernaufgabe, Mobile | **P1** | S–M |
| 3 | Fokusstil definieren und Skip-Link ergänzen (F-03) | 805 von 834 Tabstopps liegen in der Tabelle; Fokus ist nur der 1-px-Browser-Standard | A11y, Tastatur | **P1** | S |
| 4 | Widersprüchlichen Leerzustand des Diagramms beheben (F-04) | Bei 0 Treffern behauptet das Diagramm „Die Tabelle zeigt alle", während die Tabelle leer ist | Nutzerführung, Vertrauen | **P1** | S |
| 5 | Typografie auf 5 Rollen reduzieren, Lesetext auf 16 px, px → rem (F-09, F-10) | Zehn Grössen zwischen 11 und 13.6 px; bei 200 % Textzoom bleiben Filterlabels auf 13 px stehen | Lesbarkeit, A11y, Wartbarkeit | **P2** | M |

---

## 5. Typografie- und Spacing-Audit

### Ist-Zustand (alle Werte gemessen, `html`-Basis 16 px)

| Rolle | Gemessen | Fundstelle | Problem |
|---|---|---|---|
| Seitentitel `h1` | 21.6 px / 700 / LH 32.4 / LS −0.216 | [site.py:208](src/winecheck/report/site.py#L208) | Nur 1.42× über dem Kartentitel — schwache Hierarchiestufe für die oberste Ebene |
| Kartentitel `.card h2` | 15.2 px / 700 | [site.py:237](src/winecheck/report/site.py#L237) | Kleiner als der Suchfeld-Text (16 px) |
| Suchfeld | 16 px / 400 | [site.py:213](src/winecheck/report/site.py#L213) | Grösster Fliesstext der Seite ist ein Placeholder |
| **Tabellentext `td`** | **13.6 px** / 400 / LH 20.4 | [site.py:248](src/winecheck/report/site.py#L248) | Die eigentliche Lesefläche liegt 15 % unter der deklarierten Basis von 16 px |
| Weinname `.wine` | 13.6 px / 600 | [site.py:255](src/winecheck/report/site.py#L255) | — |
| Zähler `.count` | 13.6 px / 400 | [site.py:230](src/winecheck/report/site.py#L230) | Wertgleich mit `td`, andere Rolle |
| Stand-Zeile `.sub` | 13.12 px / 400 | [site.py:209](src/winecheck/report/site.py#L209) | Wertgleich mit `.reset`, andere Rolle |
| Reset-Button `.reset` | 13.12 px / 400 | [site.py:233](src/winecheck/report/site.py#L233) | Aktion in derselben Grösse wie Metatext |
| Spaltenfilter `.colfilter` | **13 px** (nicht rem) | [site.py:262](src/winecheck/report/site.py#L262) | Skaliert nicht mit Textzoom → F-10 |
| Chip `.chip` | 12.8 px / 600 | [site.py:222](src/winecheck/report/site.py#L222) | — |
| Meta / Footer `.meta`, `footer p` | 12.16 px / 400 | [site.py:256](src/winecheck/report/site.py#L256), [292](src/winecheck/report/site.py#L292) | — |
| Sortierhinweis `.colhint` | **12 px** (nicht rem) | [site.py:267](src/winecheck/report/site.py#L267) | Skaliert nicht mit Textzoom → F-10 |
| Chip-Zähler `.chip .n` | 11.84 px / 600 | [site.py:226](src/winecheck/report/site.py#L226) | 0.96 px Unterschied zum Chip-Text — visuell nicht auflösbar |
| Filterlegende `legend` | 11.52 px / 400 / LS 0.69 / uppercase | [site.py:217](src/winecheck/report/site.py#L217) | — |
| Tabellenkopf `th` | 11.52 px / 600 / LS 0.58 / uppercase | [site.py:249](src/winecheck/report/site.py#L249) | Wertgleich mit `legend`, anderes Gewicht — inkonsistent für dieselbe Label-Ebene |
| Pill `.pill` | 11.2 px / 400 | [site.py:275](src/winecheck/report/site.py#L275) | Kleinster Text der Seite trägt Sorte und Trinkreife — inhaltlich wichtige Angaben |
| SVG `.tick` / `.hint` | 11 px | [site.py:241](src/winecheck/report/site.py#L241), [243](src/winecheck/report/site.py#L243) | — |
| SVG `.alabel` | 12 px | [site.py:242](src/winecheck/report/site.py#L242) | — |

**Befund:** Zwischen 11 px und 13.6 px liegen **zehn verschiedene Grössen** (11 / 11.2 / 11.52 / 11.84 / 12 / 12.16 / 12.8 / 13 / 13.12 / 13.6). Mehrere Paare liegen unter 0.5 px auseinander und sind visuell nicht unterscheidbar, verdoppeln aber die Pflegearbeit. Gleichzeitig tragen drei Paare *dieselbe* Grösse für *verschiedene* Rollen (`.sub`/`.reset`, `.count`/`td`, `legend`/`th`) — die Hierarchie ist also nicht zu fein, sondern zugleich zu fein und zu grob.

### Empfohlener Soll-Zustand

| Token | Verwendung | Grösse | Zeilenhöhe | Weight | Anmerkung |
|---|---|---:|---:|---:|---|
| `--fs-page-title` | `h1` | 1.5 rem (24 px) | 1.25 | 700 | Klare Stufe über dem Kartentitel |
| `--fs-title` | `.card h2` | 1.125 rem (18 px) | 1.3 | 650 | Grösser als der Fliesstext darunter |
| `--fs-body` | `td`, `.wine`, Suchfeld, Tooltip | 1 rem (16 px) | 1.5 | 400 / 600 | Ersetzt 13.6 / 12.8 px — die Lesefläche |
| `--fs-body-sm` | `.sub`, `.count`, `.meta`, `footer p`, `.colfilter`, `.chip` | 0.875 rem (14 px) | 1.45 | 400 | Ersetzt 12.16 / 12.8 / 13 / 13.12 / 13.6 px |
| `--fs-label` | `legend`, `th`, `.pill`, `.chip .n` | 0.75 rem (12 px) | 1.4 | 600, LS 0.05 em | Ersetzt 11.2 / 11.52 / 11.84 px — eine einzige Label-Ebene |

SVG-Text (`.tick` 11 px, `.alabel` 12 px, `.hint` 11 px) darf in px bleiben: Er skaliert über die `viewBox` mit der Diagrammbreite, nicht über die Wurzelschriftgrösse.

### Spacing — Ist-Zustand und Empfehlung

Der Ist-Zustand ist bereits nahe an einer 2-px-Halbschritt-Skala: 2, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 22, 48 px.

| Spacing-Token | Wert | Typische Nutzung | Ersetzt |
|---|---:|---|---|
| `--sp-1` | 4 px | Icon-zu-Text, Pill-Innenraum | 2, 5 px |
| `--sp-2` | 8 px | Chip-Gap, Zellabstand, Kartentitel-Abstand | 6, 7, 9, 10 px |
| `--sp-3` | 12 px | Kartenpadding, Chip-Padding horizontal | 11, 13 px |
| `--sp-4` | 16 px | Kartenabstand, Seitenrand | 14, 16 px |
| `--sp-6` | 24 px | Abschnittsabstand zwischen Filtergruppen und Karten | 22 px |
| `--sp-12` | 48 px | Seitenfuss-Abstand | 48 px |

Kein eigenes Finding — die Abstände wirken gerendert stimmig. Die Skala dient der Wartbarkeit, nicht der Korrektur.

---

## 6. Detaillierte Findings

### [F-01] Unbestätigte Vivino-Treffer erscheinen fast gleichwertig wie bestätigte

- **Priorität:** P1 · **Kategorie:** Vertrauen / Datenqualität / Accessibility · **Aufwand:** S · **Sicherheit:** hoch
- **Fundstelle:** Diagramm (hohle Kreise) und Tabellenspalte „Vivino" (Zeichen „?"), alle Viewports. Code: [site.py:463–470](src/winecheck/report/site.py#L463), [site.py:547–548](src/winecheck/report/site.py#L547)
- **Beobachtung:** 58 der 127 Diagrammpunkte werden hohl gezeichnet, 58 Tabellenzeilen tragen ein einzelnes „?". Beides bedeutet „Namensabgleich unbestätigt". Der Grund steht ausschliesslich in einem `title`-Attribut: `<span class="warn" title="Namensabgleich unbestätigt, gefunden: Sir Winston Churchill Brut Champagne">?</span>`. Im sichtbaren Seitentext kommen weder „unbestätigt" noch eine Erklärung für hohle Punkte vor (geprüft über `document.body.innerText`).
- **Evidenz:** gemessen (58 von 127 hohle `circle.pt`; 58 `td .warn`; `mentionsUnconfirmed: false` im sichtbaren Text) und im Code bestätigt
- **Beleg:** „Grande Cuvée 2019 Muse de Miraval Rosé" zeigt **4.5/5 (2656)**, verlinkt aber auf Vivinos „Alexandra Champagne Rosé (Grande Cuvée)" — ein anderer Wein. „Neuchâtel AOC Oeil de Perdrix Rosé Caves des Coteaux (2025)" zeigt 3.9/5, gefunden wurde „Oeil de Perdrix Rosé" (Gattungsbegriff, kein Produzentenbezug).
- **Auswirkung:** Die Note ist das Entscheidungskriterium der Seite. Bei 46 % der Diagrammpunkte kann sie zu einem anderen Wein gehören, ohne dass das erkennbar ist. Auf Touch-Geräten gibt es **keinen** Weg zur Warnung: `title` erscheint ohne Maus-Hover nicht, das `?` ist nicht fokussierbar, und im Diagramm ist die hohle Form ohne Legende bedeutungslos. Der Code unterdrückt Produzenten-Mittelwerte explizit aus derselben Sorge ([site.py:66–72](src/winecheck/report/site.py#L66)) — fuzzy-Treffer werden ungleich milder behandelt.
- **Empfehlung:** (a) Das „?" durch ein beschriftetes Merkmal ersetzen, das den gefundenen Namen im Klartext zeigt — z. B. `<button class="pill pill-warn">Treffer unsicher</button>`, die den gefundenen Namen unter der Zeile einblendet; die bereits vorhandene gedämpfte Darstellung von „nur Produzenten-Ø" ([site.py:550](src/winecheck/report/site.py#L550)) ist das passende Vorbild. (b) Die Note fuzzy-gematchter Weine gedämpft setzen statt in Volltonfarbe. (c) Im Diagramm eine Legendenzeile ergänzen (siehe F-06).
- **Akzeptanzkriterium:** Auf einem Gerät ohne Hover sind für jede betroffene Zeile die Wörter „Namensabgleich unbestätigt" **und** der gefundene Vivino-Name erreichbar, ohne den Quelltext zu öffnen. Kein Warnhinweis besteht mehr aus einem Symbol allein.

---

### [F-02] Auf dem Handy fehlt das Diagramm ganz — und die Tabelle bietet keinen Ersatz für „gut und günstig"

- **Priorität:** P1 · **Kategorie:** Kernaufgabe / Responsive · **Aufwand:** S–M · **Sicherheit:** hoch
- **Fundstelle:** ≤ 720 px Viewportbreite, Diagrammkarte und Sortierauswahl `#fSort`. Code: [site.py:282](src/winecheck/report/site.py#L282), [site.py:347–356](src/winecheck/report/site.py#L347), [site.py:526–532](src/winecheck/report/site.py#L526)
- **Beobachtung:** Die Regel `.chart { display:none; }` entfernt das Diagramm unterhalb 720 px vollständig — bei 375 px gemessen `display: none`. Die verbleibende Tabelle kennt fünf Sortierungen (Note, Preis auf/ab, Ersparnis, Name, Händler), aber **keine, die Note und Preis verbindet**. Die Standardsortierung ist `rating:-1`, also Note absteigend.
- **Evidenz:** gemessen (Mobile-Emulation 375 × 812) und im Code bestätigt
- **Beleg:** Bei 375 px beginnt die erste Weinzeile bei **y = 864 px** — unterhalb des ersten Bildschirms (812 px). Die Seite ist **74 839 px** hoch (≈ 92 Bildschirme). Die Liste eröffnet mit „Brut 2018 Champagne Cuvée Sir Winston Churchill" zu CHF 275.00, gefolgt von „Pomerol AOC 2007 Château Lafleur" zu CHF 590.00. Der Diagrammhinweis „oben links = gut und günstig" existiert auf Mobile nirgends.
- **Auswirkung:** Der Quelltext nennt als Zweck ausdrücklich die Situation am Tisch mit schlechtem Empfang ([site.py:7–8](src/winecheck/report/site.py#L7)) — also das Handy. Genau dort verliert die Nutzerin die Aussage der Seite: Sie scrollt an vier Filtergruppen vorbei und landet auf einer nach Note sortierten Liste, die mit den teuersten Flaschen beginnt. „Welche Flasche lohnt sich?" ist so nur durch manuelles Quervergleichen von Note und Preis über 92 Bildschirme beantwortbar.
- **Empfehlung:** (a) Eine Sortieroption „Preis-Leistung" ergänzen, die Note und Preis kombiniert (die Datengrundlage liegt vor: `rating` und `price`; die Diagrammlogik `log10(price)` gegen `rating` ist die naheliegende Basis für einen Score) und als Standard setzen. (b) Auf Mobile über der Liste einen kompakten Block „Top 10 Preis-Leistung" einziehen, damit der erste Bildschirm eine Antwort statt eines Filterformulars zeigt. (c) Filtergruppen auf Mobile hinter ein aufklappbares „Filter"-Element legen, statt sie dauerhaft auszuklappen.
- **Akzeptanzkriterium:** Bei 375 px zeigt der erste Bildschirm mindestens drei konkrete Weinempfehlungen mit Note und Preis. `#fSort` enthält eine Preis-Leistungs-Option, die Tabelle und Zähler steuert, und ist beim Laden vorausgewählt.

---

### [F-03] 805 von 834 Tabstopps liegen in der Tabelle; kein eigener Fokusstil

- **Priorität:** P1 · **Kategorie:** Accessibility / Tastatur · **Aufwand:** S · **Sicherheit:** hoch
- **Fundstelle:** Gesamte Seite, Tastaturbedienung, alle Viewports. Code: Stylesheet [site.py:194–295](src/winecheck/report/site.py#L194) (enthält keine Fokusregel), [site.py:202](src/winecheck/report/site.py#L202)
- **Beobachtung:** Die Seite enthält **834 fokussierbare Elemente**, davon **805 innerhalb der Tabelle** (400 Zeilen × ~2 Links) und 26 davor. Es gibt keinen Skip-Link und keine Landmarke `<main>`. Das Stylesheet definiert **keine einzige `:focus`- oder `:focus-visible`-Regel**; gleichzeitig ist `-webkit-tap-highlight-color: transparent` global gesetzt.
- **Evidenz:** gemessen (`querySelectorAll` über fokussierbare Selektoren; `document.activeElement` nach 3 × Tab) und im Code bestätigt
- **Beleg:** Der Fokus auf dem Chip „jetzt trinken" zeigt ausschliesslich den Browser-Standard: `outline: auto 1px rgb(229, 151, 0)`, `outline-offset: 0px`, `box-shadow: none` — ein 1 px dünner Ring ohne Abstand auf einer hellen Chipfläche (#efe8ea). Das Erscheinungsbild hängt damit vollständig vom Browser ab. Landmarken im DOM: nur `svg[role=img]`, `FOOTER`, `DIV[role=tooltip]`.
- **Auswirkung:** Tastaturnutzer erreichen den Footer mit den Quellenangaben und Haftungshinweisen nur über mehrere Hundert Tab-Anschläge. Ein Sprung zurück von der Tabelle zu den Filtern ist gar nicht möglich. Der Fokus selbst ist auf hellen Chips schwer zu verfolgen.
- **Empfehlung:** (a) `:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: inherit; }` ergänzen. (b) Skip-Link „direkt zur Weinliste" als erstes fokussierbares Element und einen Link „zurück zu den Filtern" oberhalb der Tabelle. (c) Den Inhalt in `<main>` fassen. (d) Zeilen paginieren oder progressiv nachladen (z. B. 50 Zeilen + „mehr anzeigen") — das reduziert die Tabstopps von 805 auf ~100 und ist ohnehin ein Gewinn für die Seitenlänge aus F-02.
- **Akzeptanzkriterium:** Vom Suchfeld aus ist der Footer in ≤ 10 Tabstopps erreichbar. Jedes interaktive Element zeigt bei Tastaturfokus einen ≥ 2 px starken Ring mit ≥ 3:1 Kontrast zu seinem Hintergrund, unabhängig vom Browser.

---

### [F-04] Der Leerzustand des Diagramms widerspricht der Tabelle

- **Priorität:** P1 · **Kategorie:** Microcopy / Nutzerführung · **Aufwand:** S · **Sicherheit:** hoch
- **Fundstelle:** Diagrammkarte bei 0 Treffern, Desktop. Code: [site.py:433–438](src/winecheck/report/site.py#L433)
- **Beobachtung:** Sobald weniger als zwei Weine eine Vivino-Note haben, zeigt die Diagrammkarte „**Kein Wein mit Vivino-Note in dieser Auswahl. Die Tabelle zeigt alle.**" Diese Meldung erscheint auch dann, wenn die Tabelle **null** Weine zeigt — die Bedingung prüft nur die bewerteten Punkte, nicht die Gesamtmenge.
- **Evidenz:** gemessen (zwei unabhängige Wege reproduziert) und im Code bestätigt
- **Beleg:** Suche „zzzznichtvorhanden" → Zähler „0 von 400 Weinen · 0 mit Vivino-Note", Diagramm „… Die Tabelle zeigt alle.", Tabelle „Kein Wein passt zu dieser Auswahl.", 0 Zeilen im DOM. Identisch bei der Filterkombination Note ≥ 4.5 + Preis ≤ CHF 10.
- **Auswirkung:** Genau in dem Moment, in dem die Nutzerin Orientierung braucht, verweist die Seite auf eine Tabelle, die leer ist. Der Widerspruch lässt offen, ob die Auswahl kaputt ist oder es wirklich keine Treffer gibt.
- **Empfehlung:** Auf `list.length` verzweigen: bei 0 Treffern die Diagrammkarte ganz ausblenden und den Leerzustand allein in der Tabellenkarte zeigen — mit einer Wiederherstellungsaktion an Ort und Stelle („Filter zurücksetzen") und, wenn möglich, dem Hinweis, welcher Filter die Menge auf 0 gebracht hat.
- **Akzeptanzkriterium:** Bei 0 Treffern behauptet kein Text, die Tabelle zeige etwas. Der Leerzustand enthält genau eine sichtbare Wiederherstellungsaktion.

---

### [F-05] Kategoriefarben sind doppelt belegt und im Dunkelmodus unter 3:1

- **Priorität:** P2 · **Kategorie:** Farbsystem / Accessibility · **Aufwand:** M · **Sicherheit:** hoch
- **Fundstelle:** Filterchips (Trinkreife, Händler) und Diagrammpunkte, hell und dunkel. Code: [site.py:40–47](src/winecheck/report/site.py#L40)
- **Beobachtung:** Zwei getrennte Bedeutungen greifen auf denselben Farbvorrat zu. Vier Farben sind doppelt belegt: `#2e7d32` = Mövenpick **und** „jetzt trinken", `#1a4f8a` = Denner **und** „lagern", `#ef6c00` = Otto's **und** „austrinken", `#00838f` = SPAR **und** „kann liegen". Zusätzlich sind alle Werte fest kodiert und wechseln im Dunkelmodus nicht mit.
- **Evidenz:** gemessen (Kontrast gegen die tatsächlichen Flächen `--panel` und `--chip` in beiden Schemata) und im Code bestätigt
- **Beleg:** Kontrast gegen die Diagrammfläche `--panel`:

  | Farbe | Bedeutung(en) | hell (#f8f4f5) | dunkel (#1e181a) |
  |---|---|---:|---:|
  | `#6b1030` | Coop | 11.05 | **1.45** |
  | `#6a1b9a` | Prodega | 8.61 | **1.86** |
  | `#1a4f8a` | Denner / lagern | 7.61 | **2.11** |
  | `#c62828` | Volg | 5.15 | 3.11 |
  | `#2e7d32` | Mövenpick / jetzt trinken | 4.70 | 3.41 |
  | `#00838f` | SPAR / kann liegen | 4.15 | 3.87 |
  | `#ef6c00` | Otto's / austrinken | **2.82** | 5.68 |

  Im Dunkelmodus liegen drei Händlerfarben unter 3:1, im Hellmodus fällt Otto's-Orange mit 2.82:1 darunter. Gegen die Chipfläche `--chip` sind die dunklen Werte noch etwas schlechter (Coop 1.29, Prodega 1.65, Denner 1.87).
- **Auswirkung:** Wer aus dem Trinkreife-Filter lernt „grün = jetzt trinken", liest im Diagramm dasselbe Grün als Reifegrad — dort bedeutet es Mövenpick. Im Dunkelmodus sind Coop-, Prodega- und Denner-Punkte zusätzlich schwer von der Fläche und voneinander zu trennen; da Farbe im Diagramm das **einzige** Signal für den Händler ist, fällt die Information dann aus.
- **Empfehlung:** (a) Zwei getrennte Paletten definieren, die keine Farbe teilen — Trinkreife bleibt bei der Ampel-Semantik, Händler erhalten einen eigenen, davon klar abgesetzten Satz. (b) Beide Paletten als CSS-Custom-Properties mit `@media (prefers-color-scheme: dark)`-Varianten führen, statt Hex-Werte in Python zu setzen, und die Diagrammpunkte über `var(--shop-coop)` einfärben. (c) Zielwert ≥ 3:1 gegen `--panel` in beiden Schemata.
- **Akzeptanzkriterium:** Keine Farbe steht in beiden Legenden. Jede Kategoriefarbe erreicht in hell **und** dunkel ≥ 3:1 gegen die Fläche, auf der sie liegt.

---

### [F-06] Das Diagramm hat keine Legende, und 24 von 127 Punkten sind verdeckt

- **Priorität:** P2 · **Kategorie:** Datenvisualisierung · **Aufwand:** S–M · **Sicherheit:** hoch
- **Fundstelle:** Diagrammkarte „Vivino-Bewertung gegen Preis", ≥ 721 px. Code: [site.py:463–480](src/winecheck/report/site.py#L463)
- **Beobachtung:** Das Diagramm kodiert zwei Dimensionen über die Punktdarstellung — **Farbe = Händler** und **hohl = Namensabgleich unbestätigt** — und erklärt keine davon. Sichtbarer SVG-Text sind nur die beiden Achsenbeschriftungen und der Hinweis „oben links = gut und günstig". Legendenelemente: 0. Zusätzlich überlappen sich die Punkte im dichten Bereich (CHF 5–20, Note 3.9–4.2) erheblich.
- **Evidenz:** gemessen (Rasterzählung über die tatsächlichen `cx`/`cy`-Werte bei Punktdurchmesser 12 Einheiten) und visuell bestätigt
- **Beleg:** 127 Punkte belegen 103 Rasterzellen; **19 Zellen enthalten Mehrfachbelegungen, 24 Punkte (19 %) liegen dadurch ganz oder teilweise hinter anderen**. Die Händlerfarbe ist nur über die Punkte in den Händler-Chips oberhalb erschliessbar; für hohl vs. gefüllt gibt es im sichtbaren Text keinen Anhaltspunkt (`mentionsHollow: false`).
- **Auswirkung:** Die Farbe — das dichteste Informationssignal des Diagramms — ist nur durch Vergleich mit den Filterchips zu entschlüsseln, und die Unterscheidung gefüllt/hohl bleibt schlicht unlesbar. Ein Fünftel der Punkte ist nicht anklickbar, weil ein anderer Punkt darüberliegt; deren Tooltip ist unerreichbar.
- **Empfehlung:** (a) Eine Legendenzeile direkt unter der `h2`: „Farbe = Händler · hohler Kreis = Vivino-Treffer unsicher". (b) Radius auf 5 senken und `fill-opacity: .8` setzen, damit Überlappungen als dunklere Fläche lesbar werden statt zu verdecken; alternativ minimales Jitter auf der x-Achse. (c) Bei Mehrfachbelegung den Tooltip alle betroffenen Weine auflisten lassen.
- **Akzeptanzkriterium:** Die Bedeutung von Farbe und Füllung steht als sichtbarer Text in der Diagrammkarte. Jeder Punkt ist entweder einzeln anklickbar oder über einen Sammel-Tooltip erreichbar.

---

### [F-07] Touch-Ziele liegen durchgehend unter 44 px

- **Priorität:** P2 · **Kategorie:** Mobile / Accessibility · **Aufwand:** S · **Sicherheit:** hoch
- **Fundstelle:** Alle Bedienelemente bei 375 px. Code: [site.py:222](src/winecheck/report/site.py#L222), [233](src/winecheck/report/site.py#L233), [263–266](src/winecheck/report/site.py#L263)
- **Beobachtung:** Kein Bedienelement ausser dem Suchfeld erreicht 44 px Höhe.
- **Evidenz:** gemessen (`getBoundingClientRect` bei 375 × 812)
- **Beleg:**

  | Element | Gemessen (375 px) |
  |---|---|
  | Suchfeld | 1152 × **42** px |
  | Filterchip | 113.5 × **36** px (kleinster: 53.5 × 36) |
  | „Filter zurücksetzen" | 116.1 × **31.7** px |
  | `select` „Note ab" / „Preis bis" | 55 × **28** px |
  | Checkbox „nur bei Vivino gefunden" | **13 × 13** px (umgebendes Label 169.7 × 19.5 px) |
  | Link in der Kartenansicht | 32.4 × **16** px |

- **Auswirkung:** Die beiden Checkboxen sind mit 13 × 13 px die härtesten Fälle; das Label erweitert die Trefferfläche zwar auf 169.7 × 19.5 px, bleibt aber weniger als halb so hoch wie ein robustes Ziel. Die Links in der Kartenansicht (Vivino-Note, Händler) sind 16 px hoch und führen zu externen Seiten — Fehlgriffe kosten hier einen Seitenwechsel.
- **Empfehlung:** `min-height: 44px` für Chips, Selects und den Reset-Button; die `.colfilter label` als 44 px hohe Tapzeile mit vergrösserter Checkbox (`width/height: 20px`) ausführen; in der Kartenansicht `padding: 6px 0` auf die Links legen, damit die Zeilenbox ≥ 32 px erreicht.
- **Akzeptanzkriterium:** Bei 375 px hat jedes tappbare Element eine Trefferfläche von mindestens 44 × 44 px oder ist durch ≥ 8 px von seinen Nachbarn getrennt.

---

### [F-08] Bedienelemente sind an ihrer Kontur kaum als Bedienelemente erkennbar

- **Priorität:** P2 · **Kategorie:** Affordanz / Non-Text-Kontrast · **Aufwand:** S · **Sicherheit:** hoch
- **Fundstelle:** Suchfeld, inaktive Chips, Selects — hell. Code: [site.py:195](src/winecheck/report/site.py#L195) (`--line: #e2dadd`), [213](src/winecheck/report/site.py#L213), [220](src/winecheck/report/site.py#L220)
- **Beobachtung:** Ein einziges Linien-Token `--line` dient zugleich als Rahmen von Bedienelementen und als Trennlinie in Tabellen. Für Trennlinien ist der Wert richtig zurückhaltend; für Bedienelemente ist er zu schwach.
- **Evidenz:** gemessen
- **Beleg:** Suchfeldrahmen `#e2dadd` gegen Seitenhintergrund `#fffdfd`: **1.35:1**. Chiprahmen: **1.35:1**. Chipfläche `#efe8ea` gegen Seitenhintergrund: **1.19:1**. Select-Rahmen gegen Kartenfläche: **1.26:1**. WCAG 2.2 SC 1.4.11 (Non-Text Contrast, Level AA) verlangt für die Begrenzung eines Bedienelements ≥ 3:1.
- **Auswirkung:** Inaktive Chips lesen sich als flache Beschriftungen statt als Schalter — dass sich alle vier Filtergruppen antippen lassen, ist visuell nicht angekündigt. Das Suchfeld hebt sich fast nur durch seine hellere Füllung ab.
- **Empfehlung:** Ein zweites Token `--line-strong` (hell etwa `#b9adb1`, dunkel etwa `#6a5f63`, jeweils gegen die angrenzende Fläche auf ≥ 3:1 geprüft) für Rahmen von Input, Chip, Select und Button einführen; `--line` bleibt für Tabellenlinien, Kartenrahmen und Footer-Trennlinie.
- **Akzeptanzkriterium:** Die Begrenzung jedes Bedienelements erreicht ≥ 3:1 gegen seine unmittelbare Umgebung, in hell und dunkel. Tabellenlinien bleiben unverändert dezent.

---

### [F-09] Zehn kaum unterscheidbare Textgrössen; der Lesetext liegt unter der eigenen Basis

- **Priorität:** P2 · **Kategorie:** Typografie / Wartbarkeit · **Aufwand:** M · **Sicherheit:** hoch
- **Fundstelle:** Gesamtes Stylesheet, [site.py:194–295](src/winecheck/report/site.py#L194). Vollständige Aufstellung in Abschnitt 5.
- **Beobachtung:** Zwischen 11 px und 13.6 px existieren zehn verschiedene Grössen; mehrere Paare liegen unter 0.5 px auseinander (`.chip` 12.8 / `.colfilter` 13 / `.sub` 13.12; `.chip .n` 11.84 / `legend` 11.52 / `.pill` 11.2). Gleichzeitig teilen drei Rollenpaare dieselbe Grösse (`.sub`/`.reset`, `.count`/`td`, `legend`/`th`). `body` deklariert 16 px, aber die Tabelle — die eigentliche Lesefläche — rendert mit 13.6 px.
- **Evidenz:** gemessen (`getComputedStyle` über 21 Selektoren) und im Code bestätigt
- **Beleg:** Gemessene Grössen: 11 / 11.2 / 11.52 / 11.84 / 12 / 12.16 / 12.8 / 13 / 13.12 / 13.6 / 15.2 / 16 / 21.6 px. Die inhaltlich wichtigen Angaben Sorte und Trinkreife stehen im kleinsten Text der Seite (`.pill`, 11.2 px). `h1` 21.6 px liegt nur 1.42× über `.card h2` 15.2 px.
- **Auswirkung:** Der Haupttext liegt 15 % unter der geläufigen 16-px-Empfehlung für längere Leseflächen — bei 400 Zeilen mit Weinnamen von median 60 Zeichen ist das die am längsten gelesene Fläche der Seite. Die Beinahe-Duplikate erzeugen keinen sichtbaren Unterschied, aber jede Änderung muss an bis zu drei Stellen nachgezogen werden. Dass verschiedene Rollen dieselbe Grösse teilen, macht die Hierarchie an anderer Stelle unscharf.
- **Empfehlung:** Auf die fünf Rollen aus Abschnitt 5 reduzieren (`--fs-page-title`, `--fs-title`, `--fs-body`, `--fs-body-sm`, `--fs-label`), als CSS-Custom-Properties in `:root` definieren und alle Einzelwerte darauf umstellen. `td` und `.wine` auf `--fs-body` (16 px) heben. `.pill` auf `--fs-label` (12 px) — mit dem Weight 600 gewinnt es trotz gleicher Grösse an Präsenz.
- **Akzeptanzkriterium:** Das Stylesheet enthält höchstens fünf `font-size`-Tokens für HTML-Text (SVG-Text ausgenommen). Tabellentext rendert mit 16 px. Keine zwei Tokens liegen weniger als 2 px auseinander.

---

### [F-10] Zwei Bedienbereiche skalieren bei vergrösserter Schrift nicht mit

- **Priorität:** P2 · **Kategorie:** Accessibility (Resize Text) · **Aufwand:** S · **Sicherheit:** hoch
- **Fundstelle:** `.colfilter` und `.colhint`. Code: [site.py:262](src/winecheck/report/site.py#L262), [site.py:267](src/winecheck/report/site.py#L267)
- **Beobachtung:** Die Seite arbeitet fast durchgehend mit `rem`, setzt aber `.colfilter { font-size: 13px }` und `.colhint { font-size: 12px }` in absoluten Pixeln. Bei vergrösserter Wurzelschriftgrösse bleiben diese beiden Bereiche stehen.
- **Evidenz:** gemessen (Wurzelschriftgrösse auf 32 px gesetzt = 200 %)
- **Beleg:** Bei 200 %: `td` 27.2 px, Suchfeld 32 px, `h1` 43.2 px, Chiphöhe 54 px — aber `.colfilter label` bleibt bei **13 px** und `.colhint` bei **12 px**. Kein horizontales Scrollen (`scrollWidth` = 320 bei 320 px Viewport), der Reflow selbst ist also intakt.
- **Auswirkung:** Wer die Schrift vergrössert — die häufigste Anpassung bei nachlassender Sehschärfe —, erhält eine Tabelle in 27 px und direkt darüber die Filterzeile „Note ab / Preis bis / nur bei Vivino gefunden / Sortieren" in unverändert 13 px. Ausgerechnet die Steuerung der Tabelle bleibt klein.
- **Empfehlung:** `13px` → `0.875rem` und `12px` → `0.75rem` (bzw. die Tokens aus F-09). SVG-Text darf in px bleiben, er skaliert über die `viewBox`.
- **Akzeptanzkriterium:** Bei einer Wurzelschriftgrösse von 200 % wächst jeder HTML-Text der Seite proportional mit; kein Bereich bleibt auf seinem Ausgangswert.

---

### [F-11] Weinnamen sind Rohtexte der Händler — der Jahrgang steht in 73 % der Zeilen doppelt

- **Priorität:** P2 · **Kategorie:** Inhalt / Formatierung · **Aufwand:** M · **Sicherheit:** hoch
- **Fundstelle:** Tabellenspalte „Wein" und Diagramm-Tooltip, alle Viewports. Code: [site.py:559–560](src/winecheck/report/site.py#L559)
- **Beobachtung:** Der Name wird unverändert ausgegeben und der Jahrgang anschliessend noch einmal angehängt. Da die Händlernamen den Jahrgang meist schon enthalten, erscheint er zweimal. Die Namen tragen zusätzlich Sorte, Land und Flaschengrösse — Angaben, die als Pill bzw. Spalte daneben schon stehen.
- **Evidenz:** gemessen (Auswertung über alle 400 gerenderten Zeilen) und im Code bestätigt
- **Beleg:** **293 von 400 Zeilen (73 %)** enthalten den angehängten Jahrgang bereits im Namen: „Grand Cru AOC **2020** Château Croix de Labrie **2020**", „Pomerol AOC **2007** Château Lafleur **2007**", „Brut **2018** Champagne Cuvée Sir Winston Churchill **2018**". Namenslänge: Median 60 Zeichen, 270 von 400 über 45 Zeichen, Maximum 109 Zeichen: „Naturaplan Bio Alentejo DOC Marquês de Borba Colheita João Portugal Ramos (2024) – Roséwein, Portugal (0.75l)". Hier stehen Jahrgang, Sorte („Roséwein" neben der Pill „Rosé") und Flaschengrösse („0.75l" neben der Spalte „Preis/75cl") dreifach redundant.
- **Auswirkung:** Beim Überfliegen einer nach Note sortierten Liste ist der Name das Ankerelement. Doppelte Jahreszahlen und angehängte Marketingtexte verlängern jede Zeile auf mehrere Umbrüche — auf Mobile ist eine Karte dadurch 185 px hoch. Produzent und Lage, die tatsächlich unterscheiden, gehen im Rauschen unter.
- **Empfehlung:** (a) Den Jahrgang nur anhängen, wenn er nicht schon im Namen steht — eine Prüfung in [site.py:560](src/winecheck/report/site.py#L560). (b) Im Generator die Händler-Anhänge („– Roséwein, Portugal (0.75l)", „(2024)") aus dem Anzeigenamen entfernen; die Information steht bereits in Pill und Preisspalte. (c) Sortenpills mit dem Wert „unbekannt" weglassen — davon gibt es gemessen **97**; ein Pill, der „unbekannt" sagt, kostet dieselbe visuelle Aufmerksamkeit wie „jetzt trinken", trägt aber nichts.
- **Akzeptanzkriterium:** Keine Zeile zeigt dieselbe Jahreszahl zweimal. Der Anzeigename enthält keine Angabe, die in derselben Zeile schon als Pill oder Spalte steht. Es werden keine „unbekannt"-Pills gerendert.

---

### [F-12] „gegen Markt" ist eine eigene Spalte, aber bei 79 % der Weine leer

- **Priorität:** P2 · **Kategorie:** Informationsarchitektur · **Aufwand:** S–M · **Sicherheit:** hoch
- **Fundstelle:** Tabellenspalte „gegen Markt", Kartenansicht auf Mobile. Code: [site.py:553–555](src/winecheck/report/site.py#L553), [566](src/winecheck/report/site.py#L566)
- **Beobachtung:** Der Marktpreisvergleich ist eine von fünf Spalten und eine von sechs Sortieroptionen („Ersparnis, grösste zuerst"), liegt aber für die grosse Mehrheit der Weine nicht vor. Fehlende Werte werden als „—" gerendert.
- **Evidenz:** gemessen
- **Beleg:** **315 von 400 Zeilen (79 %)** zeigen in dieser Spalte „—". Auf Mobile heisst das: In vier von fünf Karten steht die Zeile „gegen Markt —". Die Meta-Beschreibung der Seite nennt „Marktpreisvergleich" als eines von drei Merkmalen ([site.py:191](src/winecheck/report/site.py#L191)); der Zähler „400 von 400 Weinen · 127 mit Vivino-Note" nennt die Abdeckung der Note, aber nicht die des Marktpreises.
- **Auswirkung:** Ein Fünftel der Tabellenbreite und eine Sortieroption sind meist ohne Inhalt. Wer nach „Ersparnis" sortiert, sieht 85 Weine und danach 315 Leerzeilen, ohne zu erfahren, dass die Angabe schlicht fehlt statt null zu sein. Auf Mobile wird die Kartenhöhe durch eine leere Zeile pro Wein aufgeblasen.
- **Empfehlung:** (a) In der Kartenansicht (≤ 720 px) Felder ohne Wert weglassen, statt „—" zu setzen — das gilt gleichermassen für Sorte und Trinkreife. (b) Die Abdeckung neben den Zähler schreiben, analog zur Note: „400 von 400 Weinen · 127 mit Vivino-Note · 85 mit Marktpreis". (c) Prüfen, ob die Ersparnis besser in die Preiszelle gehört (`CHF 12.50` mit `−37 %` darunter) — dann trägt die Spalte nur, wo sie etwas zu sagen hat.
- **Akzeptanzkriterium:** In der Kartenansicht erscheint keine Zeile ohne Wert. Die Abdeckung des Marktpreises ist im Zähler ablesbar.

---

### [F-13] Filterergebnisse werden assistiver Technik nicht angesagt

- **Priorität:** P3 · **Kategorie:** Accessibility · **Aufwand:** S · **Sicherheit:** mittel
- **Fundstelle:** Zähler `#count`, Tooltip `#tip`, Seitenstruktur. Code: [site.py:314](src/winecheck/report/site.py#L314), [377](src/winecheck/report/site.py#L377)
- **Beobachtung:** Jede Filter-, Such- und Sortieraktion baut Diagramm und Tabelle neu auf und aktualisiert den Zähler. Die Seite enthält **keine einzige `aria-live`-Region**; `#count` hat kein `aria-live`. `#tip` trägt `role="tooltip"`, wird aber von **keinem** Element über `aria-describedby` referenziert. Es fehlt eine `<main>`-Landmarke.
- **Evidenz:** gemessen (0 `[aria-live]`, 0 `[aria-describedby="tip"]`, Landmarken nur `svg[role=img]`, `FOOTER`, `DIV[role=tooltip]`) und im Code bestätigt
- **Auswirkung:** Wer ohne Blick auf den Bildschirm filtert, erfährt nicht, dass sich die Treffermenge geändert hat — der Zähler ändert sich stumm. Das `role="tooltip"` ist ohne Zuordnung wirkungslos.
- **Empfehlung:** `aria-live="polite"` auf `#count`; den Inhalt in `<main>` fassen; `role="tooltip"` entfernen, solange keine `aria-describedby`-Beziehung besteht (die Tabelle ist die zugängliche Alternative zum Diagramm — das ist eine tragfähige Entscheidung und sollte im `aria-label` des SVG benannt werden).
- **Akzeptanzkriterium:** Nach jeder Filteränderung wird die neue Treffermenge programmatisch bekanntgegeben. Kein ARIA-Attribut steht ohne die Beziehung, die es voraussetzt.

---

### [F-14] Die Filtergruppe „Lauf" bietet genau eine Option

- **Priorität:** P3 · **Kategorie:** Nutzerführung / Mobile · **Aufwand:** S · **Sicherheit:** hoch
- **Fundstelle:** `#fRun`, alle Viewports. Code: [site.py:308](src/winecheck/report/site.py#L308), [603–606](src/winecheck/report/site.py#L603)
- **Beobachtung:** Die Gruppe „LAUF" enthält produktiv einen einzigen, dauerhaft aktiven Chip („400 · 6.8.2026") und ist damit keine Wahl.
- **Evidenz:** gemessen (1 Chip in `#fRun`)
- **Auswirkung:** Auf dem ersten Mobile-Bildschirm — dem knappsten Raum der Seite — kostet eine Nicht-Entscheidung eine Legende plus eine Chipzeile. Das Datum steht ohnehin schon in der Stand-Zeile darüber.
- **Empfehlung:** Die Gruppe nur rendern, wenn `D.runs.length > 1`. Die Anzahl (400) lässt sich in den Zähler übernehmen, der sie bereits nennt.
- **Akzeptanzkriterium:** Bei einem einzigen Lauf erscheint keine Filtergruppe „Lauf".

---

### [F-15] Filter scrollen weg, und zwei Breakpoints trennen zusammengehörige Regeln

- **Priorität:** P3 · **Kategorie:** Navigation / Systemkonsistenz · **Aufwand:** M · **Sicherheit:** mittel
- **Fundstelle:** `.search` (sticky), Breakpoints 720 px und 767 px. Code: [site.py:211](src/winecheck/report/site.py#L211), [268](src/winecheck/report/site.py#L268), [277](src/winecheck/report/site.py#L277)
- **Beobachtung:** Nur das Suchfeld ist `position: sticky` (60 px hoch, `top: 0`). Filterchips, Zähler und Reset-Button scrollen weg. Zusätzlich gelten für zusammenhängende Dinge zwei verschiedene Schwellen: Kartenansicht und Diagramm-Ausblendung bei **720 px**, das Ausblenden des Sortierhinweises `.colhint` bei **767 px**.
- **Evidenz:** gemessen (Seitenhöhe 26 848 px bei 1280 px, 74 839 px bei 375 px; `.search` sticky, `fieldset` static; `.colhint` `display: none` bei 375 px)
- **Auswirkung:** Wer in der Liste liest und den Filter anpassen will, muss über tausende Pixel zurück nach oben. Es gibt keinen „nach oben"-Weg ausser manuellem Scrollen. Der Breakpoint-Versatz erzeugt zwischen 721 und 767 px einen Zustand, in dem sortierbare Spaltenköpfe sichtbar sind, ihr Erklärungshinweis aber nicht. Nebenbei: Die sticky Leiste trägt `--bg` (#fffdfd) und schiebt sich beim Scrollen über die Karten in `--panel` (#f8f4f5) — als etwas hellerer 60-px-Streifen sichtbar.
- **Empfehlung:** (a) Zähler und Reset-Button in die sticky Leiste aufnehmen, damit die aktive Auswahl und ihr Rückweg immer sichtbar sind; auf Mobile die Filtergruppen dort als aufklappbares „Filter (2 aktiv)" unterbringen (verbindet sich mit F-02). (b) Einen Breakpoint-Wert festlegen und beide Regeln darauf beziehen. (c) Der sticky Leiste denselben Hintergrund geben wie dem Element, über das sie sich schiebt, oder sie mit einer Unterkante abschliessen.
- **Akzeptanzkriterium:** Die aktive Filterauswahl und ein Weg, sie zu ändern, sind an jeder Scrollposition erreichbar. Das Stylesheet enthält für Layoutwechsel einen einzigen Breakpoint-Wert.

---

## 7. Konsistenzmatrix

| Rolle / Komponente | Referenz (beibehalten) | Abweichende Fundstellen | Empfohlene Vereinheitlichung |
|---|---|---|---|
| Label-Ebene (uppercase, LS) | `legend` 11.52 px / 400 | `th .sortbtn` 11.52 px / **600**, `.pill` 11.2 px / 400 (nicht uppercase) | Ein `--fs-label` = 12 px / 600 / LS 0.05 em für alle drei |
| Fliesstext | `body` 16 px | `td` 13.6 px, `.count` 13.6 px, `.colfilter` 13 px, `.sub` 13.12 px | `--fs-body` 16 px für `td`/`.wine`; `--fs-body-sm` 14 px für Meta-Rollen |
| Sekundäraktion | `.reset` 13.12 px, unterstrichen, `--brand` | `.sortbtn` 11.52 px uppercase, `select` 13 px | Eine Textbutton-Definition mit `--fs-body-sm` und gemeinsamem Fokusstil |
| Kontrollrahmen | `--line` #e2dadd (richtig für Tabellenlinien) | Suchfeld, Chip, Select nutzen denselben Wert (1.19–1.35:1) | `--line-strong` ≥ 3:1 für Bedienelemente, `--line` bleibt für Trennlinien |
| Kategoriefarbe „grün" | `#2e7d32` = „jetzt trinken" (Ampel-Semantik) | `#2e7d32` = Mövenpick; ebenso `#1a4f8a`, `#ef6c00`, `#00838f` doppelt belegt | Getrennte Paletten je Bedeutung, theme-aware als CSS-Variablen |
| Kontrollhöhe | Suchfeld 42 px | Chip 36, Reset 31.7, Select 28, Checkbox 13 px | `--control-h: 44px` als Minimum für alle |
| Leerwert-Darstellung | „keine Note" (gedämpfter Link, erklärt) | „—" in „gegen Markt" (315×), „unbekannt"-Pill (97×) | In der Kartenansicht weglassen; in der Tabelle gedämpft und nur dort, wo die Spalte Kontext gibt |
| Layout-Breakpoint | 720 px (Kartenansicht, Diagramm) | 767 px (`.colhint`) | Ein Wert für beide |

---

## 8. Empfohlenes Mini-Designsystem

Aus den bereits guten Mustern der Seite abgeleitet — die Farbrollen, die Kartenstruktur und das Chip-Muster bleiben erhalten.

```css
:root {
  /* Typografie — 5 Rollen statt 13 Werte */
  --fs-page-title: 1.5rem;    /* h1 */
  --fs-title:      1.125rem;  /* .card h2 */
  --fs-body:       1rem;      /* td, .wine, input, #tip */
  --fs-body-sm:    0.875rem;  /* .sub, .count, .meta, .colfilter, .chip, footer */
  --fs-label:      0.75rem;   /* legend, th, .pill, .chip .n — uppercase, 600 */
  --lh-tight: 1.25; --lh-body: 1.5;

  /* Spacing */
  --sp-1:4px; --sp-2:8px; --sp-3:12px; --sp-4:16px; --sp-6:24px; --sp-12:48px;

  /* Flächen und Text — unverändert, Kontraste sind gemessen gut */
  --ink:#241f20; --muted:#5f5658; --bg:#fffdfd; --panel:#f8f4f5; --chip:#efe8ea;
  --brand:#6b1030; --accent:#6b1030;

  /* NEU: Konturen nach Zweck getrennt (F-08) */
  --line:#e2dadd;        /* Trennlinien, Kartenrahmen — dezent ist hier richtig */
  --line-strong:#b9adb1; /* Rahmen von Input, Chip, Select, Button — >= 3:1 */

  /* Semantische Zustände */
  --ok:#2e7d32; --warn:#ef6c00; --bad:#c62828;

  /* Radien, Schatten, Kontrollmasse */
  --r-sm:7px; --r-md:11px; --r-lg:14px; --r-pill:999px;
  --shadow-pop:0 8px 26px rgba(0,0,0,.18);
  --control-h:44px; --dot:9px;

  /* Ein Breakpoint für Layoutwechsel (F-15) */
  --bp-compact:720px;
}

@media (prefers-color-scheme: dark) {
  :root {
    --ink:#eee8ea; --muted:#a89fa2; --bg:#151113; --panel:#1e181a; --chip:#2a2225;
    --brand:#eaa6bd; --accent:#eaa6bd;
    --line:#393134; --line-strong:#6a5f63;
    --ok:#7cc47f; --warn:#ffa552; --bad:#ef9a9a;
  }
}

/* Kategoriefarben: zwei Bedeutungen, zwei Paletten, beide theme-aware (F-05).
   Zielwert je Wert: >= 3:1 gegen --panel in hell UND dunkel. */
:root {
  --mat-now:#2e7d32; --mat-keep:#00838f; --mat-drink:#ef6c00;
  --mat-cellar:#1a4f8a; --mat-none:#8a8a8a;
  --shop-1:#6b1030; --shop-2:#1a4f8a; /* … pro Händler ein Token */
}
@media (prefers-color-scheme: dark) {
  :root { --shop-1:#e58fa8; --shop-2:#7fb0e8; /* aufgehellte Varianten */ }
}

/* Fokus — gilt für alle Bedienelemente (F-03) */
:focus-visible {
  outline:2px solid var(--accent); outline-offset:2px; border-radius:inherit;
}
```

**Komponentenregeln**

| Komponente | Regel |
|---|---|
| Chip | `min-height: var(--control-h)`, `border: 1px solid var(--line-strong)`, `--fs-body-sm`; aktiv über `aria-pressed="true"` + Füllung `--accent` (das Muster ist gut und bleibt) |
| Select / Checkbox-Zeile | `min-height: var(--control-h)`, Rahmen `--line-strong`, Label als vollflächige Tapzeile |
| Textbutton (Reset, Sortierkopf) | `--fs-body-sm`, `--brand`, unterstrichen, gemeinsamer `:focus-visible`-Stil |
| Karte | `border: 1px solid var(--line)`, `--r-lg`, `padding: var(--sp-3)` |
| Pill | `--fs-label`, Weight 600; **nur rendern, wenn ein Wert vorliegt** |
| Tabelle → Karten | Umschaltung bei `--bp-compact`; Felder ohne Wert entfallen |
| Diagramm | Legendenzeile für Farbe und Füllung; `r: 5`, `fill-opacity: .8`; Punktfarben über `var(--shop-*)` |

---

## 9. Quick Wins und Umsetzungsreihenfolge

| Reihenfolge | Quick Win | Nutzen | Aufwand | Abhängigkeit |
|---:|---|---|---|---|
| 1 | Leerzustand des Diagramms auf `list.length` verzweigen (F-04) | Beseitigt einen sichtbaren Selbstwiderspruch | S | — |
| 2 | `:focus-visible`-Regel ergänzen (F-03a) | Tastaturbedienung wird über alle Browser hinweg verfolgbar | S | — |
| 3 | Jahrgang nur anhängen, wenn nicht im Namen; „unbekannt"-Pills weglassen (F-11a, c) | Räumt 293 doppelte Jahreszahlen und 97 leere Pills ab | S | — |
| 4 | `13px`/`12px` → `rem` (F-10) | Textzoom wirkt auf die gesamte Seite | S | — |
| 5 | Legendenzeile im Diagramm (F-06a) | Macht die Bedeutung von Farbe und Füllung überhaupt lesbar | S | — |
| 6 | `min-height: 44px` auf Chips, Selects, Reset (F-07) | Trefferflächen auf dem Handy | S | Token `--control-h` |
| 7 | `--line-strong` einführen und auf Bedienelemente anwenden (F-08) | Bedienelemente werden als solche erkennbar | S | — |
| 8 | `aria-live` auf den Zähler, `<main>` ergänzen, `role="tooltip"` entfernen (F-13) | Filterwirkung wird wahrnehmbar | S | — |
| 9 | „Lauf"-Gruppe bei einem Lauf ausblenden (F-14) | Gibt den knappsten Platz der Seite frei | S | — |
| 10 | Leere Felder in der Kartenansicht weglassen, Marktpreis-Abdeckung im Zähler (F-12a, b) | Kürzere Karten, ehrlichere Abdeckung | S | — |

**Danach die strukturellen Massnahmen, in dieser Reihenfolge:**

1. **Tokens** — Typografie- und Spacing-Variablen in `:root` anlegen, Einzelwerte darauf umstellen (F-09), einen Breakpoint-Wert festlegen (F-15b).
2. **Farbsystem** — Trinkreife- und Händlerpalette trennen, beide theme-aware, Diagrammpunkte über Variablen einfärben (F-05).
3. **Kernfluss** — Preis-Leistungs-Score berechnen, als Sortieroption und Standard einführen, auf Mobile eine „Top 10"-Sektion über der Liste (F-02).
4. **Trefferqualität** — fuzzy-Treffer als beschriftetes, fokussierbares Merkmal mit Klartext-Auflösung (F-01).
5. **Tabelle** — paginieren oder progressiv laden; das senkt die Tabstopps von 805 auf ~100 und die Seitenhöhe von 74 839 px auf einen handhabbaren Wert (F-03d, F-02).
6. **Sticky-Bereich** — Zähler, Reset und ein aufklappbarer Filter in die sticky Leiste (F-15a).
7. **Regressionsschutz** — Der Generator ist eine Python-Funktion mit deterministischer Ausgabe: Ein Snapshot-Test auf `build()` mit einem festen Datensatz sichert Typografie-Tokens, Breakpoints und die Leerzustandslogik günstig ab. Ergänzend Screenshots bei 375 / 720 / 1280 px in hell und dunkel.

---

## 10. Stärken, Annahmen und offene Prüfungen

### Muster, die erhalten bleiben sollen

- **Keine Drittanbieter, offlinefähig, 201 KB dekodiert.** Die Begründung im Quelltext ([site.py:3–10](src/winecheck/report/site.py#L3)) ist stichhaltig und die Umsetzung konsequent. Nichts davon anfassen.
- **Neuaufbau von 400 Zeilen in gemessenen 9 ms** (Suche tippen: 9.0 ms, zurücksetzen: 6.8 ms). Hier besteht **kein** Performanceproblem — die Empfehlung zur Paginierung folgt aus Tabstopps und Seitenlänge, nicht aus Rechenzeit.
- **Kein horizontales Scrollen** bei 320, 375 und 1280 px, und auch nicht bei 200 % Wurzelschriftgrösse. Der Reflow ist robust.
- **Spaltenfilter wirken auf Diagramm, Zähler und Tabelle gleichzeitig** — mit im Code notierter Begründung ([site.py:416–417](src/winecheck/report/site.py#L416)). Genau richtig.
- **Leere Werte sortieren in beiden Richtungen nach unten** ([site.py:524–525](src/winecheck/report/site.py#L524)) — ein Wein ohne Note ist keine 0. Ein Detail, das häufig falsch gemacht wird.
- **Sortierauswahl und Spaltenkopf bleiben synchron** (`syncSort`, [site.py:639](src/winecheck/report/site.py#L639)).
- **Mobile konsequent gedacht:** `thead` ausgeblendet, Sortierung deshalb über das Select, und der Hinweis auf klickbare Spaltenköpfe ebenfalls ausgeblendet — gemessen 0 sichtbare Sortierbuttons bei 375 px. Kein toter Bedienweg.
- **Textkontraste durchgehend gut:** hell 4.7–14.9:1, dunkel 6.0–14.5:1 über 14 geprüfte Rollen. Der Dunkelmodus ist für Text vollständig und sorgfältig gepflegt.
- **`aria-pressed` auf Filterchips, `aria-label` auf dem SVG, `type="search"` mit sinnvollen Autofill-Abschaltungen.**
- **„Filter zurücksetzen" räumt vollständig auf** — Chips, Suchfeld, Spaltenfilter und Sortierung ([site.py:660–671](src/winecheck/report/site.py#L660)); verifiziert: Zähler springt auf „400 von 400" zurück.
- **Der Tooltip ist inhaltlich vorbildlich:** Note mit Anzahl Bewertungen, Sorte, Trinkreife, Preis, Händler, Abweichung zum Markt, Falstaff — und er wird am Viewportrand korrekt umgeklappt.
- **Die Entscheidung, nur die Vivino-Skala auf die Achse zu lassen** und Produzenten-Mittelwerte nicht als Weinnote auszugeben, ist fachlich richtig und im Footer erklärt. F-01 verlangt nicht, davon abzuweichen, sondern dieselbe Sorgfalt auf fuzzy-Treffer auszudehnen.

### Annahmen

- Primäre Zielgruppe ist eine private Person, die vor dem Kauf oder im Laden eine Kaufentscheidung trifft; Kernaufgabe ist „welche Flasche lohnt sich?". Abgeleitet aus Titel, Footer und den Zweckangaben im Quelltext — nicht vom Auftraggeber bestätigt.
- Das Handy ist der wichtigste Kanal (aus [site.py:7–8](src/winecheck/report/site.py#L7)). Ohne Analytics ist das nicht belegt; sollte der Desktop dominieren, verschiebt sich F-02 von P1 auf P2.
- Der `Lauf`-Filter ist für mehrere Läufe gebaut; F-14 empfiehlt nur, ihn bei genau einem auszublenden, nicht ihn zu entfernen.

### Offene Prüfungen

- **Screenreader** (VoiceOver iOS/macOS, NVDA): Vorlesereihenfolge der Kartenansicht, Wirkung der `data-l`-Pseudoelement-Labels — `content: attr(data-l)` wird je nach Kombination unterschiedlich behandelt. F-13 beruht auf DOM-Analyse, nicht auf einem Screenreader-Test.
- **Echte Touch-Geräte** zwischen 721 und 900 px (iPad Portrait): Die fehlende Touch-Bedienung des Diagramms ist behoben (erstes Antippen zeigt, zweites öffnet, siehe 2d), aber nur in der Emulation geprüft. Verifikation auf einem physischen Gerät steht aus — insbesondere, ob `matchMedia("(hover: hover)")` dort so ausfällt wie erwartet.
- **Safari und Firefox:** Der Fokusring ist der jeweilige Browser-Standard (in der Messumgebung `auto 1px rgb(229,151,0)`); wie sichtbar er dort ausfällt, ist ungeprüft. F-03 löst das unabhängig davon.
- **Mehrere Läufe:** Der `Lauf`-Filter mit ≥ 2 Chips wurde nie gerendert; Umbruchverhalten und ob `S.run` beim Zurücksetzen erhalten bleiben soll, sind offen.
- **Landscape und Browser-Zoom** (statt Wurzelschriftgrösse) wurden nicht geprüft; die Reflow-Messungen bei 320 px legen aber ein gutes Ergebnis nahe.
- **Marktpreis-Abdeckung:** Die 79 % Leerwerte sind gemessen, aber die Ursache liegt in der Datenbeschaffung, nicht im Frontend. F-12 behandelt nur die Darstellung; ob die Abdeckung erhöht werden kann, ist eine Frage an die Pipeline.
- **Screenshots tiefer Scrollpositionen** liefen im Browser-Panel leer zurück. Das DOM meldete an derselben Stelle 16 gerenderte Zeilen im Viewport, weshalb dies als Werkzeugartefakt gewertet wird. Eine visuelle Kontrolle der Tabelle im mittleren Scrollbereich auf einem echten Gerät ist nicht erfolgt.
- **Der Preis-Leistungs-Score** ist am aktuellen Lauf plausibilisiert (Top 10 von Hand gegengelesen, keine dünn belegten Weine darunter), aber nicht über mehrere Läufe. Ob die Steigung von 0.48 Notenpunkten pro Preisdekade stabil bleibt, zeigt erst der Vergleich — bei einem Lauf mit anderer Preisstruktur verschiebt sich die Trendlinie und damit die Rangfolge.
- **Wirkung erst nach dem nächsten Lauf:** Die Seite zeigt die Änderungen nach `wine-check site`, die 17 bestätigten Vivino-Treffer aus 2c erst nach dem nächsten `wine-check rate` — die Konfidenz wird beim Rating in den Cache geschrieben.

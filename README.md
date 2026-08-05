# wine-check

Liest die Aktions- und Sale-Seiten der grössten Schweizer Weinhändler ein, gleicht sie
gegen externe Weinbewertungen ab und sagt händlerübergreifend, wo aktuell das beste
Preis-Leistungs-Verhältnis liegt.

## Grundsätze

* **Keine Bewertung wird geraten.** Kein Treffer heisst `rating = null` plus Status plus
  Klartext-Notiz. Ein ehrliches „keine Fremdbewertung verfügbar" ist wertvoller als eine
  plausible Zahl.
* **Vivino ist Pflichtspalte.** Vivino wird für jeden Wein abgefragt — unabhängig davon,
  ob Falstaff schon einen Wert geliefert hat. Das Ergebnis erscheint immer im Output,
  auch wenn es negativ ist, immer mit klickbarer URL (Weinseite oder Suchurl).
* **Preis-Leistung wird auf den Aktionspreis gerechnet**, nie auf den Rabatt.
  Referenzpreise bei Eigenmarken sind teils konstruiert; der Rabatt ist rein informativ.
* **Preise werden auf CHF pro 75 cl inkl. MwSt normalisiert**, mit dem Normalsatz von
  8.1 % für alkoholische Getränke.

## Installation

```bash
uv sync
```

Zugangsdaten für Prodega in `.env` (Vorlage: `.env.example`). `.env` ist in `.gitignore`.

## Benutzung

```bash
uv run wine-check fetch --retailers coop,denner,prodega
uv run wine-check rate
uv run wine-check report --out ./output
uv run wine-check run --all
```

`fetch` und `rate` sind getrennt, weil `fetch` täglich sinnvoll ist und `rate` nur bei
neuen Weinen.

## Namens-Matching

Das ist der Teil, der bricht — nicht das Scraping. Die Vivino-Suche ist auf Recall
gebaut: „Carmelin" liefert „Carmelo Rodero", „Col del Sol" liefert „Col Vetoraz".
Ohne strenge Prüfung würde das Werkzeug munter fremde Bewertungen zuordnen. Der
Matcher arbeitet darum in drei Schritten, und **Vetos schlagen den Ähnlichkeitswert**:

1. **Normalisieren** — Akzente (`ß`→`ss`, `Ànima`→`anima`), Jahrgang, Volumen,
   Gebinde, rechtliche Bezeichnungen (`DOC`, `IGP`, `AOC`) und Betriebsformen
   (`Tenute`, `Château`, `Domaine`) raus.
2. **Vetos** — fünf Regeln, die einen Match unabhängig vom Score verhindern:
   * *Qualitätsstufe einseitig*: `Classico`, `Riserva`, `Superiore`, `Brut`, `Rosé` …
     → anderer Wein. Das trennt „Valpolicella Ripasso Superiore" von
     „Valpolicella Ripasso **Classico** Superiore".
   * *Farbwiderspruch*: rot gegen weiss. Fehlt die Farbe nur einseitig, ist das
     belanglos — `Rosso` und `Bianco` sind regelmässig Teil des Appellationsnamens
     (Rosso del Veronese), und `Blanc` steckt in Rebsorten (Chenin Blanc).
   * *Fremd-Token*: die Quelle trägt hinter dem ersten gemeinsamen Wort ein eigenes
     Wort, das der Händlername nicht kennt, **und** der Händlername ist nicht
     vollständig abgedeckt → anderer Wein (Zweitwein, andere Cuvée).
   * *Cuvée vor der Betriebsform*: `Pavillon Rouge du Château Margaux` ist nicht
     `Château Margaux`. Nach französischem Muster steht der Cuvée-Name **vor** dem
     Gut, nicht dahinter.
   * *Anker fehlt*: gemeinsam sind nur Rebsorte, Region, Farbe oder Qualitätsstufe →
     kein Produzenten- oder Markenbezug, kein Match. Sonst erbt „Heldenrosé Rosé de
     Gamay" die Note von „Perdono Rosé di Gamay".
3. **Ähnlichkeit** — erst danach entscheidet `rapidfuzz` über die Konfidenz
   (`exact`, `wine_level`, `fuzzy`, `winery_level`). Ab `fuzzy` wird immer die
   gefundene Quell-Bezeichnung mitgegeben.

### Die unangenehme Stelle

Zwei Fälle sind lexikalisch **nicht** unterscheidbar:

* `Provins Valais Les Grands Dignitaires Domherrenwein Fendant` — „Les Grands
  Dignitaires" ist die Produktlinie, der Wein ist derselbe.
* `Antinori Tenuta Guado al Tasso Il Bruciato Bolgheri` — „Il Bruciato" ist der
  Zweitwein, ein anderer Wein.

Beide tragen Zusatzwörter, die der Händlername nicht kennt. Statt zu raten,
entscheidet die Abdeckung: ist der Händlername *vollständig* abgedeckt und sind es
höchstens zwei Zusatzwörter, gilt der Match — aber nur als `fuzzy`, mit ausgegebener
Quell-Bezeichnung. Fehlt dagegen ein Bestandteil des Händlernamens, ist es ein
anderer Wein. Deshalb steht Domherrenwein Fendant mit `vivino_match_confidence =
fuzzy` im Report und Guado al Tasso Superiore als `no_entry` — mit der Begründung,
welcher Kandidat abgelehnt wurde.

`vivino_status` und `vivino_match_confidence` sind zwei verschiedene Dinge: der Status
beschreibt, wie jahrgangsgenau die *Bewertung* ist, die Konfidenz, wie sicher die
*Namenszuordnung* ist. `exact` auf einem `fuzzy`-Match heisst: Jahrgang stimmt, Wein
bitte prüfen.

## Was das Ranking treiben darf

Angezeigt wird alles. Sortiert wird nur mit bestätigten Werten — `exact` und
`wine_level`. Zwei Fälle sind ausdrücklich **nicht** ranking-fähig, beide aus dem
ersten Live-Lauf gelernt:

* **`winery_level`** — ein Produzenten-Durchschnitt ist nicht die Note dieses Weins.
  „Piccini" hat 4.2 aus 752 Bewertungen; über den Chianti Classico Riserva von Piccini
  sagt das nichts Belastbares. Er stand damit auf Platz 3 der Preis-Leistungs-Liste.
* **`fuzzy`** — Namenszuordnung unbestätigt. So kam der Prodega-Fasswein
  „Montagne Vin Rouge" (CHF 1.21 pro 75 cl) mit der Note von „Marsannay ‚La Montagne'
  Rouge" (Burgunder, 4.0 aus 382 Bewertungen) in die Rangliste.

Beide bleiben mit Note, Status und Link in der Vivino-Spalte sichtbar und lassen sich
von Hand übernehmen — sie sortieren nur keine Rangliste.

Die Preis-Leistungs-Rangliste wird **klassenweise** ausgegeben, günstigste Klasse
zuerst. Ein globaler Rang über klassenrelative Werte wäre irreführend und würde
systematisch die teuren Weine nach oben spülen — beim ersten Lauf standen dort
Champagner zu CHF 108 und Pomerol zu CHF 118 an der Spitze.

## Output

| Datei | Inhalt |
|---|---|
| `results.csv` | Alle Felder roh, inkl. Preisvergleich über Händler und aller Vivino-Felder |
| `report.pdf` | Ranglisten, Vivino-Spalte immer gefüllt und verlinkt, Tabelle „ohne Bewertung", Status-Legende |
| `scatter.png` | Preis/75 cl (x, log) gegen normalisierte Bewertung (y), nach Händler gefärbt |
| `diff.md` | Änderungen zum letzten Lauf, inkl. neu aufgetauchter Vivino-Bewertungen |

## Quellen — Stand 5.8.2026

Händler stehen in `sources/retailers.yaml` und können ohne Codeänderung ergänzt werden.
`uv run wine-check sources` zeigt den Status jeder Quelle.

### Was funktioniert

| Quelle | Positionen | Weg |
|---|---|---|
| Mövenpick Wein | ~107 | serverseitiges Magento, `div.cs-product-tile` |
| Prodega (Transgourmet) | ~30 | **öffentlicher Wochenprospekt als PDF**, kein Login nötig |
| Denner | 1–3 | Nuxt-SSR-Payload (`__NUXT_DATA__`) |
| Vivino | Pflichtspalte | JSON-Endpunkt `/api/explore/explore` |

### Was nicht funktioniert, und warum

Vier Quellen sind hinter Bot-Schutz. Eine Schutzmassnahme bei einer *öffentlichen*
Quelle wird nicht umgangen — das Tool meldet `blocked` und protokolliert einen
Retry-Zeitpunkt.

| Quelle | Schutz | Befund |
|---|---|---|
| **Falstaff** | Cloudflare | Ganze Domain HTTP 403 „Attention Required" — auch die `sitemap.xml`, die die eigene `robots.txt` ankündigt. Firewall-Regel, keine JS-Challenge; Header ändern nichts. |
| **Coop** | DataDome | HTTP 403 mit CAPTCHA-Seite, sogar auf `/robots.txt` selbst. |
| **Migros** | Cloudflare | HTTP 403 auf die Wein-Kategorie. |
| **Flaschenpost** | Cloudflare | JS-Challenge („Just a moment…"), obwohl `robots.txt` `/aktionen` erlaubt. |

Weil **Falstaff als Leitquelle nicht erreichbar ist**, läuft das Ranking derzeit über
Vivino. Die Herkunft wird in jeder Zeile mitgeführt (`rank_source`), und die beiden
Skalen — Falstaff 0–100, Vivino 1–5 — werden nie im selben Sortierschlüssel gemischt,
ohne die Quelle anzuzeigen. Der Falstaff-Adapter ist gebaut und greift ohne
Codeänderung, sobald Zugang besteht; in `sources/retailers.yaml` dazu
`enabled: true` setzen.

Lidl, Aldi, Landi, Otto's, Schuler und TopCC antworteten auf die geratenen Deep-Links
mit 404 oder liefern eine reine JavaScript-Hülle. Sie sind mit Status
`url_unverified` eingetragen; `resolve_url` sucht die Promo-Kategorie beim nächsten
Lauf vom Shop-Root aus und protokolliert das Ergebnis, statt zu scheitern.

## Prodega

Der Zugang läuft über zwei Wege, und der erste braucht **keine Zugangsdaten**:

1. **Wochenprospekt.** `transgourmet.ch/de/aktionen` verlinkt die Aktionsbroschüre
   unter `www-static.transgourmet.ch` — öffentlich. Dort stehen die Weinaktionen mit
   Artikelnummer, Bezugsgrösse, Aktionspreis und „statt"-Referenzpreis. Das PDF sagt
   selbst: *„Alle Angebote exklusive MwSt und inklusive VRG."*
2. **Webkatalog.** Für Sortiment und marktspezifische Preise. Zugangsdaten aus
   `PRODEGA_USER`/`PRODEGA_PASS` oder `PRODEGA_COOKIE`. Der Login ist ein
   Standard-Drupal-Formular (`/de/user/login`, Felder `name`, `pass`,
   `form_build_id`, `form_id`) und ist implementiert, aber **ungetestet** — ohne
   gültige Zugangsdaten war der eingeloggte Katalog nicht erreichbar. Markt über
   `market:` in der YAML setzen.

`easy.prodega.ch` leitet auf `web.transgourmet.ch` mit Cookie-Check weiter und ist
ohne Session nicht ansprechbar. Ein offener JSON-Endpunkt der App war ohne Reverse
Engineering nicht auffindbar — laut Auftrag wird das dann gelassen.

Die Prospekt-Positionen werden über **Koordinaten** rekonstruiert, nicht über
`extract_text()`: das Rasterlayout hat vier Spalten, und zeilenweises Extrahieren
liest quer darüber und mischt die Produkte. Jede `Art.-Nr.` ist ein Anker; der
Preisblock steht rund 180 pt darüber, die Bezeichnung darunter. Positionen ohne
sichere Bezugsgrösse landen mit `price_confidence = low` in der Report-Liste
„Unsichere Prospekt-Positionen" zur manuellen Ergänzung — nicht im Ranking.

## Cache

sqlite unter `cache/winecheck.sqlite`, Key = Quelle + normalisierter Name + Jahrgang.

| Inhalt | Gültigkeit |
|---|---|
| Bewertungen | 90 Tage |
| Preise | 1 Tag |
| `rating_not_readable`, `no_entry`, `too_few_ratings`, `ambiguous` | 30 Tage |
| `blocked` | bis zum vermerkten Retry-Zeitpunkt |

Die 30 Tage für Nicht-Treffer sind der Grund, warum `diff.md` neu aufgetauchte
Vivino-Bewertungen zeigen kann: der Eintrag verfällt, wird neu geprüft, und wenn dann
eine Note da ist, fällt es auf.

Flags: `--refresh` (Bewertungen), `--refresh-prices` (Preise), `--retry-failed`
(`blocked` und Nicht-Treffer erneut prüfen).

## Anstand gegenüber den Quellen

Max. eine Anfrage pro 2 Sekunden pro Domain, `robots.txt` wird respektiert,
exponentielles Backoff bei 429/503. Trifft das Tool bei einer *öffentlichen* Quelle auf
eine Cloudflare- oder DataDome-Challenge, bricht es ab und protokolliert `blocked` —
es umgeht sie nicht.

Setz `WINECHECK_CONTACT` in `.env` auf eine erreichbare Mailadresse; sie landet im
User-Agent. Wer geblockt werden will, soll erreichbar sein.

Keine Browser-Automation: kein Selenium, kein Playwright. Die vier blockierten Quellen
bleiben blockiert, bis das anders entschieden wird.

## Tests

```bash
uv run pytest
```

132 Tests: 125 laufen offline, 7 sind Netzwerktests (mit `WINECHECK_LIVE=1`
aktivieren). Schwerpunkte:

* **Matching** — alle Beispielpaare aus dem Auftrag, plus Regressionen für die
  Falschtreffer, die beim ersten Live-Lauf auffielen (Perdono/Heldenrosé,
  generisches Valpolicella, französische Zweitweine).
* **Preisnormalisierung** — u.a. „Karton 6 × 75 cl, CHF 41.70 exkl. MwSt" → CHF 7.51.
* **Vivino-Statuslogik** — alle acht Status-Werte, jeweils mit der Zusicherung, dass
  URL, Query und Notiz gesetzt sind.
* **Report** — dass die Vivino-Spalte in `results.csv` und `report.pdf` nie leer ist.

## Bekannte Grenzen

* **Denner liefert nur 1–3 Positionen.** Der SSR-Payload enthält die
  Aktions-Highlights; die vollständige Weinliste lädt Denner client-seitig über
  Prediggo nach. Ohne Browser ist mehr nicht zu holen.
* **Der Falstaff-Parser ist ungetestet.** Er konnte gegen keine echte Antwort geprüft
  werden, weil die Domain blockiert. Er ist so geschrieben, dass er im Zweifel nichts
  liefert statt etwas zu erfinden.
* **Der Prodega-Webkatalog ist ungetestet** — siehe oben.
* **Lidl und Aldi fehlen** im ersten Release: die Prospekt-URLs wechseln wöchentlich
  und die geratenen Deep-Links antworteten 404. Der PDF-Adapter selbst ist gebaut und
  funktioniert (er liest den Prodega-Prospekt), es fehlt nur die URL-Auflösung.
* **Wine-Searcher** ist nicht gebaut.
* **Grossgebinde können das Ranking dominieren.** Ein 10-Liter-Bag-in-Box bei Prodega
  ergibt umgerechnet CHF 1.21 pro 75 cl. Rechnerisch korrekt, aber selten das, was
  gesucht ist — solche Positionen tragen `Bag-in-Box` in `source_note`.

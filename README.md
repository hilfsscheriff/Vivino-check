# wine-check

**Live: <https://hilfsscheriff.github.io/Vivino-check/>**

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
uv run wine-check trinkreife        # Jahrgangstabelle einlesen, einmal pro Jahr
uv run wine-check site --out ./docs # Webseite für GitHub Pages bauen
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

Ein `winery_level`-Treffer entsteht ausserdem gar nicht mehr, wenn der Händlername ein
zusätzliches **unterscheidendes** Wort trägt. Beispiel aus dem Live-Lauf: „Bordeaux AC
Mouton Cadet Baron Ph de Rothschild" für CHF 9.95 bekam über den Produzenten-Pfad die
4.6 aus 92'093 Bewertungen von Château Mouton Rothschild — der Note eines Premier Grand
Cru Classé. „Cadet" ist genau der Unterschied zwischen Zweitmarke und Erstwein. Reine
Herkunfts- und Qualitätsangaben („Chianti Classico Riserva") lösen die Sperre nicht aus,
sonst verliert der Pfad seinen Zweck. Die Korrektur nahm 30 der 44 Produzenten-Treffer
weg und senkte die Trefferquote von 42 % auf 36 % — genau der Handel, den der Auftrag
verlangt.

Die Preis-Leistungs-Rangliste wird **klassenweise** ausgegeben, günstigste Klasse
zuerst. Ein globaler Rang über klassenrelative Werte wäre irreführend und würde
systematisch die teuren Weine nach oben spülen — beim ersten Lauf standen dort
Champagner zu CHF 108 und Pomerol zu CHF 118 an der Spitze.

### Warum auf der Diagrammachse nur Vivino steht

Die Rangliste im PDF folgt Falstaff als Leitquelle. Die **Diagramme nicht** — dort steht
ausschliesslich die Vivino-Note in ihrer eigenen Skala 1–5.

Vorher waren beide Skalen auf 0–1 normalisiert und lagen auf einer Achse. Rechnerisch
geht das, inhaltlich nicht: ein Falstaff-92 und ein Vivino-4.6 landen dann auf derselben
Höhe, obwohl ein Punkt bei Falstaff etwas anderes bedeutet als ein Zehntel bei Vivino,
aus anderer Grundgesamtheit, mit anderer Verteilung. Ein Streudiagramm behauptet mit der
gemeinsamen Achse Vergleichbarkeit, und die gab es nicht. Vivino ist die einzige Skala,
die für alle Weine dieselbe ist — Pflichtspalte, für jeden Wein abgefragt.

Falstaff- und andere Kritikerpunkte stehen weiter im Tooltip und in der Tabelle.

Auf der Achse gilt zusätzlich:

* **Produzenten-Durchschnitte kommen nicht drauf.** Ein Punkt auf der Achse liest sich
  als Note dieses Weins.
* **`fuzzy`-Treffer kommen drauf, aber hohl gezeichnet.** Sie betreffen 59 der 128
  Punkte; sie zu verschweigen halbiert das Diagramm, sie gefüllt zu zeichnen behauptet
  die Sicherheit eines exakten Treffers. Der Tooltip nennt den gefundenen Namen, die
  Tabelle setzt ein `?` hinter die Note. Beschriftet werden im PNG nur bestätigte
  Punkte — ein Name neben einem Punkt liest sich als Empfehlung.

## Die Webseite

`wine-check site --out ./docs` baut **eine einzige HTML-Datei** mit allen Daten inline.
Kein CDN, keine externen Schriften, keine Bilder von aussen. Drei Gründe:

* Sie läuft per Doppelklick, aus OneDrive und auf GitHub Pages gleichermassen.
* Sie läuft unterwegs ohne Netz weiter, sobald sie einmal geladen ist — genau dann,
  wenn man am Tisch sitzt und schlechten Empfang hat.
* Wer sie mit Freunden teilt, verschickt nicht deren IP-Adressen an ein CDN.

Enthalten: das Diagramm mit Mouseover, eine sortierte Tabelle mit Kaufquelle und
Schnäppchen-Prozent, und kombinierbare Filter nach **Lauf, Trinkreife, Sorte und
Händler** plus Suchfeld über Name, Produzent und Region. Die Schlüssel der eingebetteten
JSON sind gekürzt (`name` → `n`), das spart rund ein Drittel der Dateigrösse.

Veröffentlichen: Repository → Settings → Pages → Branch `main`, Ordner `/docs`. Die
`.nojekyll` wird mitgeschrieben, damit Pages die Datei unverändert ausliefert.

### Tabelle sortieren und filtern

Jeder Spaltentitel ist anklickbar, ein zweiter Klick kehrt die Richtung um. Leere Werte
sortieren in **beiden** Richtungen nach unten — ein Wein ohne Note ist keine 0 und würde
aufsteigend sonst die Liste anführen.

Dazu vier Spaltenfilter, die die Chip-Filter nicht schon abdecken: Note ab, Preis bis,
nur Weine unter dem Marktpreis, und **nur bei Vivino gefunden**.

Der letzte meint „bestätigter Namensabgleich" und ist strenger, als er klingt: draussen
bleiben nicht nur die 272 Weine ohne Eintrag, sondern auch die 59 `fuzzy`-Treffer, deren
Name nur ungefähr passt, und die Produzenten-Mittelwerte. Von 400 Weinen bleiben **69** —
genau die gefüllten Punkte im Diagramm. Wer nur mit Zahlen arbeiten will, denen er traut,
setzt diesen Haken. Sie greifen in `visible()`, also **vor** Diagramm und
Zähler — sonst zeigen Diagramm, Zähler und Tabelle drei verschiedene Mengen, und man weiss
nicht, welche gilt.

Auf dem Handy ist `thead` ausgeblendet, weil die Tabelle dort zur Kartenliste wird; die
Kopfzeilen-Sortierung ist dann nicht bedienbar. Darum gibt es zusätzlich ein
Sortier-Auswahlfeld in der Filterzeile, das auf jeder Breite funktioniert. Beide Wege
teilen denselben Zustand und ziehen gegenseitig nach.

### Ein Lauf ist eine Aktionswoche, kein Neubau

Jeder `report`-Aufruf legte anfangs einen eigenen Lauf an. Nach einem Tag Entwicklung
zeigte der Lauf-Filter dreizehn Chips, alle mit dem Datum „6.8.2026", `diff.md` verglich
gegen den eigenen Neubau von vor zehn Minuten und meldete korrekt „keine Änderungen",
und die Seite war auf 1.4 MB gewachsen. Jetzt ersetzt der jüngste Stand eines Tages den
älteren, und `previous_snapshot` überspringt heutige Läufe. Die Seite ist damit 191 KB
statt 1376 KB.

## Der Skill für unterwegs

`skills/weinkarte/` ist ein Claude-Skill für den Restauranttisch: Foto der Weinkarte rein,
drei Empfehlungen raus — mit Vivino-Note, dem Aufschlag gegenüber dem Ladenpreis und der
Trinkreife des Jahrgangs. Er braucht dieses Repository **nicht**; die Regeln, die
Vivino-Parameter und die Jahrgangstabelle liegen als Referenzdateien darin.

Installieren: den Ordner nach `~/.claude/skills/weinkarte/` kopieren.

Zwei Dinge daraus sind beim Bauen durch Messung entstanden und wären nicht zu erraten:

* **Nach dem Produzenten suchen, nie nach der Appellation.** Der Vivino-Endpunkt sortiert
  nach Bewertung, nicht nach Namensähnlichkeit. „Fontodi Chianti Classico" liefert 666
  Treffer, angeführt von einem Castell'in Villa Riserva 1986 für CHF 821 — Fontodi selbst
  kommt in den ersten 24 nicht vor. „Fontodi" allein liefert 12 von 12 richtige. Dasselbe
  bei Tommasi und Muga.
* **Restaurantpreis geteilt durch Ladenpreis unter 1.5 heisst: falscher Wein.** Kein
  Restaurant verkauft unter dem Ladenpreis. Die vier Fehltreffer beim Test ergaben ×0.1,
  ×0.1, ×0.2 und ×0.5, der richtige ×2.2. Eine Division, die fast jeden Fehlgriff fängt.

Alle Zahlen im Beispiel des Skills sind gemessene Vivino-Werte. Ein Skill, der vor
erfundenen Zahlen warnt, darf im eigenen Beispiel keine haben.

## Trinkreife

**Keine erreichbare Quelle führt Trinkreife als Datenfeld.** Vivino nicht — 232
Feldpfade geprüft, die einzigen „from"-Treffer sind Preisfelder, und die
`cellar`-Treffer sind UI-Texte für den *eigenen* Weinkeller des Nutzers. Prodega
nennt sie nirgends, Falstaff ist gesperrt.

Es gibt aber die **Vinum-Jahrgangstabelle**, die Mövenpick als Sponsoringpartner als
PDF veröffentlicht — und zwar als *Text*-PDF, weshalb kein OCR nötig ist.
`wine-check trinkreife` liest sie ein und schreibt `sources/trinkreife.yaml`
(70 Zeilen, 42 rot, 28 weiss). Die Tabelle erscheint jährlich; einmal pro Jahr
ausführen. Quelle und Abrufdatum stehen in der YAML.

| Stufe | Bedeutung |
|---|---|
| jetzt trinken | bietet zurzeit höchsten Genuss |
| kann liegen | macht bereits Spass, wird aber noch besser |
| lagern | noch zu jung, reifen lassen |
| austrinken | Zenit überschritten |
| zu alt | hätte man besser schon getrunken |

Drei Dinge stecken nicht im Text, sondern in der Grafik, und werden über Koordinaten
und Farben gelesen:

* **Weinart** — ein Weinglas am Zeilenanfang, gelb weiss, rot rot. Die Reihenfolge ist
  *nicht* durchgehend weiss-dann-rot: bei Burgenland steht Rot zuerst. Eine Annahme
  darüber wäre falsch gewesen.
* **Jahrgangsqualität** — die Zellhintergrundfarbe: mittelmässig, gut bis sehr gut,
  exzellent. Steht als eigene Spalte im Report.
* **Leere Zellen** — „hätte man besser schon getrunken". Im Text fehlen sie einfach,
  weshalb Zeilen mit 13 statt 16 Codes auftauchen; nur über die x-Position ist
  erkennbar, *welcher* Jahrgang gemeint ist.

Das PDF setzt zudem zwei Tabellenblöcke nebeneinander — zeilenweises Extrahieren
schrieb „Wallis" und „Steiermark" in dieselbe Zeile.

### Wo keine Auskunft kommt

Die Tabelle gilt für **Region und Weinart**, nicht für die einzelne Flasche. Beim
letzten Lauf gab es für 189 von 400 Weinen eine Auskunft. Leer bleibt es, wenn:

* die Region nicht eindeutig zuzuordnen ist,
* mehrere zutreffende Zeilen sich widersprechen,
* der Wein ein **Rosé** ist — die Tabelle führt keine Rosé-Zeilen, und ein Rosé darf
  nicht die Reife des Rotweins derselben Region erben,
* die Weinart nicht zur vorhandenen Zeile passt: Tessin hat nur eine Rotwein-Zeile,
  ein weisser „Ticino Bianco di Merlot" bekommt sie darum nicht.

Die Zuordnung von feinen Herkünften auf die groben Tabellenregionen ist Handarbeit
(`REGION_TOKENS`) und auf Wortgrenzen geprüft. Ohne das landete ein Rioja im
Languedoc, weil „oc" in „D**OC**a" steckt, und ein Cabernet in der Deutschschweiz,
weil „bern" in „Ca**bern**et" steckt.

## Schnäppchen gegen den Vivino-Marktpreis

Vivino nennt im selben API-Aufruf Händlerpreise für die Schweiz. Auf CHF pro 75 cl
normalisiert (über `bottle_quantity` und `bottle_type.volume_ml`, nur CHF, kein
Währungsumrechnen) ergibt das einen **unabhängigen** Referenzpreis — belastbarer als
das „statt X" des Händlers, das bei Eigenmarken teils konstruiert ist. Die Differenz
steht als `bargain_percent` in der CSV und führt im PDF die Rangliste
„Grösste Schnäppchen": je mehr Prozent unter dem Marktpreis, desto besser.

**Die Falle dabei — Zirkularität.** Mövenpick ist Vivino-Partnerhändler
(`merchant_id` 450). Für Mövenpick-Weine nennt Vivino genau den Mövenpick-Preis:
Château Plince CHF 65 gegen CHF 65, Beaune CHF 79 gegen CHF 79. Ein ungefilterter
Vergleich hätte dort systematisch 0 % ergeben und damit alle Weine anderer Händler
künstlich besser aussehen lassen.

Deshalb werden für jeden Wein die Domains **seiner eigenen Händler** aus den
Vivino-Preisen ausgeschlossen. Bleibt kein unabhängiger Preis, steht in der Spalte die
Begründung statt einer 0. In der Praxis heisst das: bei Mövenpick gibt es meist kein
Schnäppchen-Prozent, bei Prodega, Coop, Denner und Otto's schon.

**Die zweite Falle — Ausreisser.** Der erste Lauf zeigte an der Spitze der Liste
Fantasiewerte: ein Bourgogne Chardonnay für CHF 13.95 gegen CHF 80.86 von
`cultwinesintl.com` (83 %) und ein Champagner für CHF 275 gegen CHF 841 von
`wineuponatime.com`. Das sind Wein-Anlage- und Sammlerplattformen; deren Preise sind
keine vergleichbaren Detailhandelspreise. Kennt Vivino für einen Wein nur *einen*
unabhängigen Preis und der kommt von dort, wird das Schnäppchen künstlich gross —
derselbe Scheinsieger-Mechanismus wie beim falsch umgerechneten Literpreis.

Dagegen zwei Regeln:

* **Schweizer Shops zuerst**, auch wenn ein ausländischer günstiger ist — verglichen
  wird mit dem schweizerischen Detailhandel. Gibt es nur einen ausländischen Preis,
  wird er genommen, aber mit dem Vermerk „kein Schweizer Shop, Vergleich mit Vorsicht".
* **`bargain_plausibility`**, analog zur 45-%-Regel bei Eigenmarken-Rabatten: über
  65 % Ersparnis oder ein Marktpreis ohne Schweizer Shop gilt als `questionable`.
  Solche Zeilen bleiben im Report, führen die Rangliste aber nicht an und tragen ein `!`.

Marktpreise werden nur 30 Tage gecacht, obwohl Bewertungen 90 Tage gelten — sonst
stünde monatelang ein alter Preis und damit ein falsches Prozent im Report.

## Output

| Datei | Inhalt |
|---|---|
| `results.csv` | Alle Felder roh, inkl. Preisvergleich über Händler, aller Vivino-Felder, Marktpreis und `bargain_percent` |
| `report.pdf` | Ranglisten **als Auszüge** plus vollständige Listen aller bewerteten und aller unbewerteten Weine, Spalte „Wo kaufen" mit Händlername, Link und Verkaufskanal, Vivino-Spalte immer gefüllt und verlinkt, Marktpreis-Spalte, Tabelle „ohne Bewertung", Status-Legende |
| `scatter.png` | Preis/75 cl (x, log) gegen **Vivino-Bewertung 1–5** (y), nach Händler gefärbt — für Druck und PDF |
| `scatter.html` | Dasselbe interaktiv: Mouseover zeigt Weinname, Vivino-Bewertung, Preis, Händler und Schnäppchen; Klick öffnet die Händlerseite; Händler in der Legende ausblendbar. Selbstenthaltend, kein CDN, funktioniert offline |
| `diff.md` | Änderungen zum letzten Lauf, inkl. neu aufgetauchter Vivino-Bewertungen |
| `docs/index.html` | Die Webseite — eine einzige Datei mit allen Daten inline, siehe unten |

### Wo der Wein zu kaufen ist

Die Spalte „Wo kaufen" nennt den lesbaren Händlernamen, verlinkt auf die Produktseite
und zeigt den Verkaufskanal darunter — bei Prodega ist die Kundenkarte nötig, und das
ändert die Antwort auf „lohnt sich das". Bei mehreren Händlern stehen alle da, der
günstigste fett. Die Kanäle stehen als `channel` in `sources/retailers.yaml`.

## Quellen — Stand 5.8.2026

Händler stehen in `sources/retailers.yaml` und können ohne Codeänderung ergänzt werden.
`uv run wine-check sources` zeigt den Status jeder Quelle.

### Was funktioniert

| Quelle | Positionen | Weg |
|---|---|---|
| Aktionis | ~226 | Aggregator, serverseitiges HTML — liefert Coop, Otto's, Denner, Lidl, SPAR, Volg |
| Mövenpick Wein | ~115 | serverseitiges Magento, `div.cs-product-tile` |
| Prodega (Transgourmet) | ~68 | **Prodega Easy, öffentlicher JSON-Katalog**, kein Login nötig |
| Denner | 1–3 | Nuxt-SSR-Payload (`__NUXT_DATA__`) |
| Vivino | Pflichtspalte | JSON-Endpunkt `/api/explore/explore`, inkl. Marktpreise |

### Aktionis als Umweg zu den blockierten Händlern

`aktionis.ch` sammelt die Aktionen der Detailhändler ein und liefert sie serverseitig
gerendert: `/q/Wein`, 48 Karten pro Seite, weiter über `?page=N` (`?p=` und `?offset=`
werden ignoriert und liefern still wieder Seite 1). Pro Karte gibt es Aktionspreis,
Referenzpreis, Rabatt, den vollen Namen im `title`-Attribut samt Jahrgang und Volumen
sowie den Händler im `alt` des Logos.

Damit kommen Quellen ins Werkzeug, die direkt nicht einlesbar sind (Coop, Migros, Lidl)
oder für die es keinen eigenen Adapter gibt (Otto's, SPAR, Volg). Die Angebote werden
dem **echten Händler** zugeschrieben, nicht Aktionis.

**Das sind Daten aus zweiter Hand.** Ein Preis, der bei Aktionis falsch steht, steht
danach auch im Report. Die Deal-URL wird als Angebots-URL mitgeführt, damit jede Zeile
bis zur Quelle zurückverfolgbar bleibt. `robots.txt` erlaubt `/q/` und `/deals/`;
gesperrt sind `/admin`, `/login`, `/profile`, `*.pdf`, `/dealtarget/` und `/app` — die
werden nicht angefasst.

### Geprüft und verworfen: QoQa

QoQa hat eine offene JSON-API ohne Schlüssel (`api.qoqa.ch/v2/spotlight?locale=de`) mit
einem eigenen Universum „Wein & Spirituosen". Technisch wäre die Anbindung eine
Stunde Arbeit — inhaltlich taugt sie nicht:

* Die Preise sind **Spannen über verschiedene Lot-Grössen ohne Flaschenzahl**
  („Ab 49.– bis 169.–"). Ein Preis pro 75 cl ist daraus nicht ableitbar, das wäre
  konsequent `price_confidence = low` und damit ausserhalb des Rankings.
* Kein Referenzpreis, Laufzeit rund 24 Stunden — in einem Wochenreport längst abgelaufen.
* Die Titel sind Produzenten- statt Weinnamen („Domaine Dalmeran"), Spirituosen sind
  untergemischt. Der Matcher landete meist auf `winery_level`, was ohnehin nicht rankt.

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

### Falstaff über die Händler

Falstaff selbst bleibt dicht — `.com`, `.at` und `.de` antworten alle mit HTTP 403,
eine API-Subdomain existiert nicht. Mövenpick weist die Punkte aber **selbst am
Produkt aus**: `Falstaff 92/100` steht in der Produktkachel, und der Adapter liest das
mit. Das ist der Ersatz für den blockierten Zugang und in einem Punkt sogar besser:
die Note hängt am *exakten* Artikel, es gibt kein Namens-Matching und damit kein
Fehlzuordnungsrisiko — die Konfidenz ist per Konstruktion `exact`.

Es ist nicht nur Falstaff. Beim Lauf vom 6.8.2026: Suckling 29, Parker 11,
Falstaff 10, Decanter 8, Wine Spectator 7, Jeb Dunnuck 4, Galloni 3, Tim Atkin 3,
Vinum 2 — alle auf der 100-Punkte-Skala. Die Rangfolge ist deshalb
**Falstaff → benannter Kritiker → Vivino**: eine Note am exakten Produkt ist mehr wert
als ein Namenstreffer. Die Quelle steht immer in `rank_source`.

Zwei Vorsichtsmassnahmen:

* **Herkunft in jeder Zeile.** `falstaff_reported_by` nennt den Händler, im Report
  steht „laut Mövenpick". Die Note ist vom Verkäufer berichtet und nicht bei Falstaff
  geprüft — Händler zitieren naturgemäss die freundlichen Noten.
* **Kritikerauswahl nach fester Reihenfolge**, nicht nach der höchsten Note. Sonst wäre
  es eine Auswahl nach Wunschergebnis.

`Veronelli 3/100` wird verworfen: das sind Sterne, keine Punkte. Eine Note auf der
falschen Skala ist schlimmer als eine Lücke.

**Entscheidung vom 6.8.2026: keine Browser-Automation.** Die vier Quellen bleiben
blockiert und werden als solche gemeldet — sie erscheinen in `report.pdf` unter
„Quellen in diesem Lauf" und in `diff.md` unter „Quellen mit Problemen", damit „keine
Coop-Aktionen" nicht wie „Coop hat diese Woche nichts" aussieht. Drei funktionierende
Händler sind besser als sieben halbe.

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

   *Entscheidung vom 6.8.2026: der Prospekt genügt.* Weg 2 bleibt ungenutzt im Code.
   Wer ihn aktivieren will, legt die Zugangsdaten in `.env` — der Adapter nimmt sie
   automatisch und ergänzt den Katalog um den Prospekt herum. Solange nichts gesetzt
   ist, steht die Begründung in jedem Lauf in der Spalte „Bemerkung".

Welcher Prospekt gilt, entscheidet sich über Jahr, Monat und Kalenderwoche im Pfad
(`/public/2026-08/kw33-agh-aktionen-d.pdf`) — nicht lexikografisch, sonst stünde
`kw10` vor `kw9`. Marktberichte und Sortimentskataloge liegen auf derselben Seite und
werden nicht verwechselt: nur `kw…aktionen….pdf` trägt Preise.

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

In `runs` liegt pro Kalendertag höchstens ein Lauf — siehe „Ein Lauf ist eine
Aktionswoche". Nach einer Matcher-Korrektur lassen sich gezielt die betroffenen
Bewertungen verwerfen, statt alle 400 neu abzufragen:

```bash
sqlite3 cache/winecheck.sqlite "DELETE FROM ratings WHERE source='vivino' AND status='winery_level'"
```

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

279 Tests: 272 laufen offline, 7 sind Netzwerktests (mit `WINECHECK_LIVE=1`
aktivieren). Schwerpunkte:

* **Matching** — alle Beispielpaare aus dem Auftrag, plus Regressionen für die
  Falschtreffer, die beim ersten Live-Lauf auffielen (Perdono/Heldenrosé,
  generisches Valpolicella, französische Zweitweine).
* **Preisnormalisierung** — u.a. „Karton 6 × 75 cl, CHF 41.70 exkl. MwSt" → CHF 7.51.
* **Vivino-Statuslogik** — alle acht Status-Werte, jeweils mit der Zusicherung, dass
  URL, Query und Notiz gesetzt sind.
* **Report** — dass die Vivino-Spalte in `results.csv` und `report.pdf` nie leer ist und
  dass jeder der 400 Weine im PDF auffindbar ist, nicht nur die Ranglisten-Auszüge.
* **Diagrammachse** — dass dort nur Vivino landet, auch wenn eine Falstaff-Note
  vorliegt, und dass Produzenten-Durchschnitte draussen bleiben.
* **Läufe** — dass mehrere Neubauten am selben Tag einen Lauf ergeben und `diff.md`
  gegen die Vorwoche vergleicht, nicht gegen sich selbst.

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
* **Alkoholfreies fliegt raus.** Nicht aus Geschmacksgründen: alkoholfreie Getränke
  unterliegen in der Schweiz dem *reduzierten* MwSt-Satz von 2.6 %, nicht dem
  Normalsatz von 8.1 %, mit dem hier gerechnet wird. Ein alkoholfreier Schaumwein
  bekäme sonst einen um 5.4 % zu hohen Preis. Aufgefallen an einem Rimuss aus dem
  Aktionis-Sortiment.
* **Falstaff-Noten gibt es nur, wo der Händler sie ausweist** — beim letzten Lauf 10
  von 400 Weinen, alle von Mövenpick. Prodega und die Aktionis-Quellen führen keine
  Kritikerpunkte. Eine Falstaff-Note für einen Wein, den kein Händler zitiert, ist
  nicht zu beschaffen, solange die Domain gesperrt ist.
* **Bei Mövenpick gibt es meist kein Schnäppchen-Prozent.** Nicht weil die Angebote
  schlecht wären, sondern weil Vivino dort denselben Preis kennt — siehe oben.

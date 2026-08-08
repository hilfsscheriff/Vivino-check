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

### Kurze Abfrage zuerst

Vivino sortiert die Trefferliste nach **Bewertung**, nicht nach Namensähnlichkeit. Eine
Abfrage, die mit der Appellation beginnt, liefert darum die berühmtesten Weine der
Herkunft statt den gesuchten:

| Abfrage | Treffer | erster Kandidat |
|---|---|---|
| `ribera duero protos roble spanien` | 13 | Protos 27 Ribera del Duero, 4.2 (43'583) |
| `protos roble` | **2** | **Protos Roble 2024, 3.9 (882)** |
| `ribera duero protos crianza spanien` | 45 | Protos 27 Ribera del Duero |
| `protos crianza` | **3** | **Protos Crianza 2020, 4.0 (1'112)** |

Die kurze Abfrage lief vorher nur bei `no_entry`. Beide Protos-Weine bekamen aber einen
*falschen, aber akzeptierten* Treffer — und damit kam der bessere Versuch nie zum Zug.
**Ein Fehltreffer verhinderte den Treffer.** Jetzt laufen beide, und das aussagekräftigere
Ergebnis gewinnt.

Die kurze Abfrage ist nicht immer besser: „Rioja Reserva Las Flores" schrumpft auf
`flores` und liefert 247 fremde Weine. Davor schützen die Sperren — was sie ablehnen,
wird `no_entry`, und dann greift die lange Abfrage. Deshalb *beide* versuchen, statt sich
auf eine Strategie festzulegen.

Dazu holt jede Abfrage **24 statt 12** Kandidaten: „Chivite Navarra Colección 125" (rot)
stand hinter dem Blanco und der Vendimia Tardía desselben Hauses und fiel unter den Tisch.

### „Rotwein" ist eine Farbangabe, kein Rechtsbegriff

`Rotwein` und `Weisswein` stehen in den Rechtsbegriffen und fliegen aus den Tokens. Für
die Suchabfrage ist das richtig, für die Farbprüfung nicht: der Händler schreibt die
Farbe fast immer genau so an („… – Rotwein, Spanien"). Ohne sie fehlte die Farbe
einseitig, einseitiges Fehlen ist erlaubt — und der **rote** Chivite Colección 125 bekam
die Note des **Blanco**. Die Farbsperre liest jetzt zusätzlich den Rohtext.

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

### Das Land gehört nicht zur Identität

Händler schreiben es unterschiedlich an. Coop führt „Ribera del Duero DO Protos Roble
(2024) – Rotwein, **Spanien**", Aligro „Ribera del Duero Roble Protos DO 2024". Ein
Token Unterschied, und derselbe Wein stand zweimal im Report — CHF 9.75 bei Coop, CHF
9.67 bei Aligro — statt einmal mit beiden Preisen. Der Händlervergleich ist der Zweck
des Werkzeugs, also darf er nicht an einem Wort scheitern, das nichts über den Wein sagt.

Ländernamen fliegen darum aus dem Dedup-Schlüssel, **sofern danach mindestens zwei
unterscheidende Tokens bleiben**. Diese Bedingung ist der Punkt: „Protos Roble" bleibt
eindeutig, ein generischer „Cabernet Sauvignon, Chile" behält sein Land — sonst fiele er
mit „Cabernet Sauvignon, Australien" zu einer Zeile zusammen, und zwei verschiedene Weine
verschmelzen zu einem Phantompreis.

### Die Suche kennt auch den gefundenen Namen

Mövenpick führt einen Wein als „Mendoza 2021 Chardonnay Alta Angelica Zapata", Vivino als
„Catena Zapata Angélica Zapata Chardonnay Alta". Wer auf der Webseite nach **Catena**
suchte — dem Namen, unter dem das Weingut bekannt ist — fand nichts, obwohl der Wein
korrekt zugeordnet war. Die Suche deckt jetzt auch den gefundenen Namen und die Sorte ab.

### Der Produzent steht bei Mövenpick in der Adresse

Mövenpick benennt Weine nach Herkunft und Lage — „Côtes du Roussillon Villages AOC 2020
Les Dentelles" — und stellt den Produzenten nur in die URL:
`…-aoc-domaine-thunevin-calvet.html`. Für Vivino ist das das wichtigste Wort, weil die
Suche nach Bewertung sortiert und ohne Produzent den berühmtesten Wein der Appellation
liefert.

Der Slug ist Name **plus** Produzent. Was im Slug steht und im Namen fehlt, ist der
Produzent — Viña Errázuriz, Delas, Pol Roger, Poggio Tesoro, Scheiblhofer. Verpackungs-
und Werbewörter („anniversary set 2x", „bio") fliegen raus; bleibt nichts Belastbares,
wird der Name nicht angefasst.

**Ergebnis: exakte Treffer von 99 auf 121, bewertete Weine von 221 auf 241 (35 % → 39 %).**

Dazu ist `Côtes` jetzt ein Regionswort. Es steckt in Côtes du Rhône, du Roussillon, de
Provence und dutzenden mehr und sagt so wenig über den Wein wie „Tal" — es galt aber als
unterscheidend und landete in der kurzen Abfrage: `cotes dentelles` liefert **null**
Treffer, `dentelles` findet Weine. `Coteaux` bleibt bewusst draussen: in „Coteaux du
Layon" ist es eine Appellation, in „Caves des Coteaux" der Produzentenname, und als
Regionswort verlöre die Prüfung „Produzent fehlt in der Quelle" dort ihren Griff.

### Wo auch die beste Abfrage nicht hilft

„Thunevin-Calvet Les Dentelles" hat eine Vivino-Seite mit Bewertung, steht aber in
**keinem** Ergebnis des `explore`-Endpunkts: die Abfrage nach dem Produzenten liefert
alle vierzehn Weine des Hauses, dieser ist nicht dabei — auch ohne Typfilter nicht. Die
HTML-Suche leitet auf denselben Index um, es gibt also keinen zweiten Weg.

Der Wein ist nur unter seiner direkten Adresse erreichbar. `no_entry` mit Suchlink ist
hier die richtige Antwort, und das ist der Grund, warum die Vivino-Spalte immer eine
klickbare URL trägt: was das Werkzeug nicht findet, findet der Mensch in zehn Sekunden.

### Zwei Produzenten sind zwei Weine

Drei Fehltreffer aus einer einzigen Meldung, alle mit derselben Wurzel — der Score war
hoch, weil nach Abzug von Herkunft und Qualitätsstufe kaum etwas übrig blieb:

| Händler | bekam die Note von | |
|---|---|---|
| Gevrey-Chambertin **Faiveley** | **Regnard** Gevrey-Chambertin Rouge | 4.3 (566) |
| Rioja Imperial Cune Reserva | „Rioja Reserva" — ein Sammeleintrag | 4.2 (36'233) |

Zwei neue Sperren, beide vor der Ähnlichkeitsrechnung:

* **Kein gemeinsames unterscheidendes Wort.** Trägt der Fundname überhaupt keines,
  kann er per Konstruktion nicht dieser bestimmte Wein sein.
* **Beide Seiten führen einen eigenen Namen.** Faiveley beim Händler, Regnard in der
  Quelle — einseitige Zusätze bleiben erlaubt und werden anderswo behandelt, aber wenn
  *beide* etwas Eigenes mitbringen, sind es zwei Weine.

### Klammern sind Zweitnamen

Vivino führt Produzenten als „Cune (CVNE)". Der Klammerinhalt galt als zusätzlicher
Namensbestandteil, der dem Händlernamen fehlt — und liess `Cune Crianza` und
`Cune Rosado` durchfallen, obwohl beide Einträge existieren. Klammern mit höchstens zwei
Wörtern fliegen jetzt raus; längere bleiben, weil dort gelegentlich echte
Unterscheidungen stehen („Magnum 1.5 Liter").

### Der Fundname muss erkennbar sein

Vivino trennt Weingut und Wein. „Cune Imperial Rioja Reserva" heisst dort Weingut
„Imperial", Wein „Rioja Reserva". Wir gaben nur den Weinnamen aus — in der Spalte stand
„Rioja Reserva", eine Gattungsbezeichnung, die wie ein Fehltreffer aussieht, obwohl der
Treffer stimmte. **Ich bin selbst darauf hereingefallen** und hielt einen korrekten
Match für falsch. Jetzt steht das Weingut davor, sofern es nicht schon im Weinnamen
vorkommt.

### Dritte Abfrage: nach Bewertungsanzahl

Die Sortierung nach Note begräbt bei grossen Häusern genau die Weine, die im Regal
stehen. `faiveley` liefert 207 Treffer, angeführt von Bâtard-Montrachet und
Mazis-Chambertin Grand Cru; der schlichte Gevrey-Chambertin steht weit hinten. Nach
`ratings_count` sortiert steht er vorne — viele Leute trinken ihn, die Grand Crus fast
niemand. Der Versuch läuft als dritter, nach kurzer und langer Abfrage.

### Sechserpakete zum Paketpreis

Vier Meldungen an einem Nachmittag, alle derselbe Fehler: ein Gebinde galt als eine
Flasche, der Preis war um **Faktor sechs** zu hoch.

| Wein | angezeigt | richtig |
|---|---|---|
| A Mano Primitivo (6 × 75 cl) | CHF 39.90 | **6.65** |
| Côtes-du-Rhône La Renjardière | CHF 20.70 | **3.45** |
| Asinone Anniversary Set (2×2013, 2×2016, 2×2018) | CHF 290 | **48.33** |

Zwei verschiedene Ursachen:

* **Aktionis** führt die Gebindeangabe nicht im Titel, sondern in der Metazeile der
  Karte: „Italien, Apulien, 2025, 6 x 75 cl". In die Preisrechnung ging nur der Titel.
  25 von 91 Positionen waren betroffen.
* **Mövenpick** verkauft Jahrgangs-Sammlungen als eine Position und schreibt die
  Flaschenzahl nur in die Adresse (`…-set-2x2013-2x2016-2x2018-…`). Ohne Volumenangabe
  nahm die Rechnung eine einzelne Flasche an. Der Fehler trifft immer die teuersten
  Positionen, weil nur dort Sets verkauft werden.

Aligro war bereits richtig — dort steht die Flaschenzahl als Zahlenfeld im JSON.

### Abgelaufene Aktionen lebten weiter

Aktionis ist ein Aggregator: seine Funde landen unter „coop", „ottos", „spar", „volg".
Beim Neuladen wurde aber nur der eigene Schlüssel geleert, und die Angebote dieser
Händler sammelten sich an. Coop stand mit **210** Positionen im Cache, während Aktionis
**112** listete — die Differenz waren ausgelaufene Aktionen, deren Detailseite „Angebot
ist abgelaufen" meldete, die im Report aber weiterlebten. Ein Adapter leert jetzt alle
Händler, unter denen er ablegt: 623 auf 478 Weine, und die Bewertungsquote steigt von
37 % auf 42 %, weil die Karteileichen grösstenteils unbewertet waren.

### Brut ist die Standard-Dosage

„Ruinart Blanc de Blancs" gegen „Ruinart Blanc de Blancs **Brut** Champagne" hatte Score
100 und fiel durch, weil „Brut" nur auf einer Seite stand. Praktisch jeder Champagner ist
Brut; Vivino schreibt es aus, Händler oft nicht. Einseitig fehlendes „Brut" ist keine
Unterscheidung mehr — ein *Widerspruch* schon: „Demi-Sec" oder „Extra Dry" schreibt
niemand versehentlich weg.

### Ein Wort vor dem Produzenten

Prompt danach matchte derselbe Wein auf **Dom** Ruinart — die Prestige-Cuvée zum
Vielfachen des Preises. Die Abdeckung hilft dort nicht: der Händlername ist vollständig
in der Quelle enthalten. Es braucht die Position: **genau ein** zusätzliches Wort direkt
vor dem Produzentennamen ist eine eigene Cuvée (Dom Ruinart, Dom Pérignon). Mehrere Wörter
sind es nicht — „Provins Valais Les Grands Dignitaires Domherrenwein" meint denselben
Wein und darf als `fuzzy` durchgehen. Die beiden Bauformen sind lexikalisch nur an der
Länge zu unterscheiden.

### Die Zuordnung muss sichtbar sein

Die Tabelle zeigte ein `?` für einen unbestätigten Abgleich, aber der gefundene Name
stand nur im Tooltip — auf dem Handy gibt es keinen. Damit war nicht nachprüfbar, welcher
Vivino-Wein gemeint ist, und genau das ist die erste Frage bei einem `?`. Der Fundname
steht jetzt als „→ …" unter der Note, sofern er vom Händlernamen abweicht.

### Beiwörter dürfen die Abdeckung nicht drücken

„Insoglio del Cinghiale **Toscana** IGP Tenuta di Biserno" gegen „Biserno **Campo di
Sasso** Insoglio del Cinghiale": alle drei unterscheidenden Wörter des Händlers stecken
in der Quelle, es fehlte nur `Toscana`. Über *alle* Tokens gerechnet waren das 75 %
Abdeckung — unter der Schwelle, und der Wein fiel als Zweitwein-Verdacht durch, obwohl
„Campo di Sasso" nur Bisernos zweites Gut ist.

Händlernamen tragen Region, Land und Farbe mit, Vivino nennt sie meist nicht. Die
Abdeckung zählt darum nur noch unterscheidende Wörter. Das brachte 9 Weine mehr
(199 → 208 bewertet).

**Die Änderung hat prompt eine Sicherung zerschossen**, und ein bestehender Test hat es
gemeldet: bei kurzen Namen steigt die Abdeckung über unterscheidende Wörter schnell über
die Schwelle, und „Oeil de Perdrix Rosé **Caves des Coteaux**" gegen ein blosses „Oeil de
Perdrix Rosé" wurde `exact` — obwohl der Produzent fehlt und diesen Rosé-Typ viele
Neuenburger Häuser keltern. Der Weg über den ganzen Namen verlangt jetzt zusätzlich, dass
kein unterscheidendes Wort des Händlers fehlt.

### Weinhändler auf Shopware — ein Adapter, mehrere Läden

Shopware ist bei Schweizer Weinhändlern verbreitet, und die Produktkacheln sehen überall
gleich aus. Ein neuer Laden braucht darum keinen Code, nur einen Eintrag in
`retailers.yaml`. Bedient werden Selection Schwander (49 Positionen) und Caratello (73).

Übernommen wird **nur, was einen Streichpreis trägt**. Beide führen Vollsortimente von
hunderten Weinen; ohne diese Grenze würde aus dem Aktionsvergleich ein Weinkatalog.
Mengenrabatte („3 % ab 24 Flaschen") bleiben draussen — das ist ein Staffelpreis für
Grossabnehmer, keine Aktion.

Zwei Eigenheiten haben beim Bauen zugeschlagen:

* **Die Preisreihenfolge ist nicht verlässlich.** Schwander schreibt `CHF 13.90 statt
  CHF 15.40`, Caratello `statt CHF 215.00 CHF 189.00`. Wer den ersten Preis nimmt,
  verkauft beim zweiten Laden den alten als Aktionspreis. Der Aktionspreis ist immer der
  niedrigere — das gilt in beiden Schreibweisen.
* **Das Volumen steht neben dem Namen, nicht darin.** Bei keiner der 73
  Caratello-Positionen trug der Name eine Volumenangabe, der Kacheltext dagegen schon
  („… 2016 , 150 cl"). Ohne sie ginge eine Magnum als 75-cl-Flasche durch und stünde zum
  halben Literpreis in der Rangliste. 16 Flaschen sind betroffen — Azelia Barolo Magnum
  CHF 164 wird zu CHF 82.00 pro 75 cl.

**Ergebnis: 478 auf 600 Weine, Trefferquote 44 % auf 47 %.** Fachhändler führen Weine,
die Vivino kennt.

### Geprüft und nicht integrierbar

| Laden | Grund |
|---|---|
| Casa del Vino | robots.txt: `Disallow: /` |
| Baur au Lac Vins | robots.txt: `Disallow: /` |
| Zweifel Weine | robots.txt: `Disallow: /` |

Drei von zehn geprüften Weinhändlern verbieten das Auslesen vollständig. Das wird
respektiert, nicht umgangen. Gerstl, Martel und Bindella wären technisch erreichbar,
nutzen aber je ein eigenes System — dort wäre je ein eigener Adapter nötig.

### Süssweinmerkmale sind ein anderer Wein

„Passito", „Recioto" und „Eiswein" standen schon in den Qualitätsstufen, die
fremdsprachigen Entsprechungen nicht — und daran fiel es auf: ein **roter** „Chivite
Coleccion 125" bekam die Note des gleichnamigen **Vendimia Tardía**, eines
Spätlese-Süssweins desselben Hauses. Ergänzt sind `vendimia`, `tardia`, `vendemmia`,
`tardiva`, `ice`, `muffato`, `botrytis`, `moelleux`, `liquoreux`.

Die Ergänzung hatte eine Nebenwirkung, die erst der Livelauf zeigte: weil „Ice" nun als
Qualitätsstufe gilt, fällt es aus den *unterscheidenden* Wörtern heraus — und der
Zeilenvergleich oben hielt „Porte de Novembre" und „Porte de Novembre **Ice**" plötzlich
für Jahrgänge desselben Weins. Er vergleicht jetzt über **alle** Identitätswörter. Der
Jahrgang ist ohnehin schon heraus, Legaris Crianza 2020/2021/2022 ergeben also weiterhin
dieselbe Menge und behalten ihre Note.

### Vivinos Weintyp schlägt das fehlende Farbwort

Ein weisser „Vermentino San Felice Toscana IGT" für CHF 11.50 bekam die 4.2 aus 23'690
Bewertungen eines „San Felice Campogiovanni **Brunello di Montalcino**". Beide Namen
tragen kein Farbwort — die Farbe steckt allein in der **Rebsorte**, und genau daran
scheiterte die bisherige Prüfung, die Farbwörter gegen Farbwörter hielt.

Vivino liefert `wine.type_id` mit, und der kommt aus deren Weindatenbank statt aus einer
Namensanalyse. Kandidaten, deren Typ der Farbe des Händlernamens widerspricht, fliegen
jetzt raus, **bevor** überhaupt verglichen wird. Schaum- und Süsswein bleiben aussen vor:
ein Prosecco darf weiss *und* Schaumwein sein.

Die erste Fassung hatte prompt einen Fehlalarm: „Chianti Classico Riserva **Il Grigio**
da San Felice" ist ein Roter, „Grigio" gehört zum Weinnamen und nicht zur Sorte. Steht
eine Rebsorte hinter einem Artikel (il, la, le, el …), ist sie ein Eigenname und taugt
nicht als Farbquelle.

Aufgefallen ist es, weil der gescannte Vivino-Link des Nutzers auf **genau den Eintrag**
zeigte, den wir zugeordnet hatten — der beste Beleg, den ein Fehltreffer haben kann.

### Was wir selbst ergänzen, darf nicht gegen den Treffer zählen

Mövenpick nennt den Produzenten nur in der Adresse, wir hängen ihn an. Stand er ohne
Klammern im Namen, rechnete der Matcher **uns** an, was wir selbst ergänzt hatten:
„Douro DOC 2023 Quinta do Vale Meão, **Olazabal Filhos**" gegen „Quinta do Vale Meão
Douro 2023" wurde `fuzzy`, weil die Quelle den Firmennamen nicht nennt — den Vivino gar
nicht führt. In Klammern trägt der Name den Produzenten für die **Suche**, ohne den
Identitätsvergleich zu stören; `tokenize` entfernt Klammern ohnehin, `query_tokens`
behält sie.

### Kritikernoten gehören nicht zum Weinnamen

„Châteauneuf-du-Pape Vieux Télégraphe **Parker 95**" — Vivino kennt keine Note im
Weinnamen, also galt „Parker" als fehlender Bestandteil und stufte einen Volltreffer auf
„unbestätigt". Solche Angaben fliegen jetzt raus, **aber nur wenn eine Zahl folgt**:
sonst verschwände das Weingut Parker in Coonawarra.

Beides zusammen: `fuzzy` von 78 auf 52, `exact` von 118 auf 126.

### Rotwein ist vorgewählt

Er macht den grössten Teil des Sortiments aus (246 von 608). Wer etwas anderes sucht,
klickt einmal; ein Klick auf „Rotwein" hebt die Vorauswahl auf. „Filter zurücksetzen"
führt auf den Standard zurück, nicht auf leer — sonst landet man in einem Zustand, den
man beim Laden nie sieht.

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

## Quellen — Stand 7.8.2026

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

### Aligro statt TopCC

**TopCC geht nicht** — und zwar nicht aus technischen Gründen. Die Prospekte laufen über
iPaper; die Seitenbilder und das PDF liegen auf `files.cdn.ipaper.io`, und deren
robots.txt lautet `User-agent: * / Disallow: /`. Die Weinlagerverkauf-Beilage wäre
inhaltlich genau richtig, ist aber nur unter Missachtung dieses Verbots zu holen.
Eingetragen als `blocked_by: robots`.

**Aligro deckt denselben Kanal ab** und erlaubt den Zugriff: robots.txt sperrt nur
`/admin` und `/panier`. Neun Weinkategorien, 223 Positionen.

Die Kategorieseiten rendern clientseitig, liefern die Daten aber vollständig mit — im
Vue-Attribut `pagination="…"` steckt HTML-entity-kodiertes JSON. Ein GET je Kategorie,
kein Browser. `?limit=192` hebt die Seitengrösse; der Parameter überlebt allerdings
keine Weiterleitung, darum wird der Slug erst aufgelöst und dann gezielt geholt.

#### Die Preisfalle

Aligro zeigt je nach Kundentyp etwas anderes an. Derselbe Wein:

| Kundentyp | Anzeige | Bedeutung |
|---|---|---|
| Privatkunde | `103.- / 6 Flaschen → 83.-` | Kartonpreis, **inkl.** MwSt |
| Gastroprofi | `15.88 / Flasche → 12.80` | Flaschenpreis, **exkl.** MwSt |

83 ÷ 6 = 13.83 und 12.80 × 1.081 = 13.84 — dieselbe Flasche. Wer eine Ansicht ungeprüft
übernimmt, liegt um den Faktor 6 oder um 8.1 % daneben.

Der Adapter liest darum keine Anzeige, sondern die Zahlenfelder: `discountPriceTTC` ist
der Aktionspreis inkl. MwSt fürs Gebinde, `quantityUnit.number` die Flaschenzahl darin.
`unitPrice` wäre bequemer und ist der falsche Wert — Flaschenpreis **ohne** MwSt, nahe
genug am richtigen, um unbemerkt durchzugehen.

#### „Vins" ist Plural

Die Weinerkennung prüft auf Wortgrenzen, damit „Sch**wein**skoteletts" nicht als Wein
durchgeht. Damit traf `vin` aber auch `Vins` nicht — und Aligro benennt seine
Warengruppen französisch im Plural. Die verlässlichste Weinkennung war wirkungslos, und
es kamen nur die Weine durch, deren *Name* zufällig ein Weinwort enthielt: **175 statt
223**. Plurale stehen jetzt einzeln in der Liste.

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

### Der Wein heisst Cabernet, das ist keine Preisangabe

Die MwSt-Erkennung liest den Text, in dem Gebinde und MwSt-Hinweis stehen — und dieser
Text enthält absichtlich den Weinnamen, weil dort „75 cl" und „Karton zu 6" vorkommen.
Zwei Alternativen des Ausdrucks hatten keine Wortgrenze am Anfang:

```
net(?:to)?\b    griff in "Caber-net", "Mio-netto", "Ligor-netto", "Freixe-net"
ht\b            griff in "ni-cht"
```

Damit galt **jeder Cabernet als exkl. MwSt** und wurde um 8.1 % hochgerechnet. Betroffen
waren 13 Weine bei Coop, Mövenpick und Denner, von CHF 3.45 bis CHF 239. Der Preis war
falsch, sah aber völlig normal aus — genau die Sorte Fehler, die einen Scheinsieger
erzeugt, und der Grund, warum der Auftrag die MwSt ausdrücklich benennt.

Die Korrektur ist ein `\b` je Alternative. Prodega, das wirklich exkl. MwSt quotiert,
bleibt unverändert bei 66 Positionen. Die Regressionstests prüfen beide Richtungen: die
vier echten Weinnamen dürfen **nicht** greifen, „exkl. MwSt", „netto", „ohne MwSt" und
„HT" müssen weiter greifen.

Aufgefallen ist es nur, weil Sie gesagt haben, die Mövenpick-Preise seien inkl. MwSt.
Nachrechnen lohnt sich: der Weg von der Rohangabe zum Literpreis hat mehr Stellen, an
denen etwas schieflaufen kann, als man ihm ansieht.

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

420 Tests: 413 laufen offline, 7 sind Netzwerktests (mit `WINECHECK_LIVE=1`
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
* **Aligro** — dass der Gebindepreis durch die Flaschenzahl geteilt wird, dass das
  bequeme `unitPrice`-Feld *nicht* genommen wird, und dass ein unbekanntes Gebinde die
  Konfidenz senkt statt zu raten.
* **Abfragereihenfolge** — dass die kurze Abfrage ohne Herkunft und Land gebaut wird
  und die Rangfolge einen echten Treffer über einen Produzenten-Durchschnitt stellt.

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

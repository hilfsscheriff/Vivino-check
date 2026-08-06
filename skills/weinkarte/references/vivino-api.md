# Vivino abfragen

## Der Endpunkt

```
https://www.vivino.com/api/explore/explore?search_term=<PRODUZENT>&min_rating=1&country_code=CH&currency_code=CHF&per_page=12
```

Antwortet mit JSON auf einen gewöhnlichen GET. Ein normaler Browser-`User-Agent` genügt.
Setz **keine** `Sec-Fetch-*`-Header — `Sec-Fetch-Dest: empty` zusammen mit
`Sec-Fetch-Mode: cors` beantwortet Vivino mit HTTP 415.

Höchstens eine Anfrage alle zwei Sekunden. Bei 429 oder 503 warten, nicht nachdrücken.

`min_rating=1` schliesst nichts aus, erfüllt aber die Bedingung, dass **irgendein** Filter
gesetzt sein muss. Ohne Filter kommt eine leere Trefferliste zurück und kein Fehler — man
merkt es also nur, wenn man auf die Zahlen schaut. `country_code=CH` und
`currency_code=CHF` sorgen dafür, dass die Ladenpreise von Schweizer Händlern in Franken
kommen; sonst vergleicht man einen Restaurantpreis in CHF gegen einen Ladenpreis in Euro.

## Die eine Regel, die alles entscheidet: nach dem Produzenten suchen

**Suche den Produzentennamen. Nie die Appellation.**

Der Endpunkt sortiert nach **Bewertung absteigend**, nicht nach Namensähnlichkeit. Wer
„Chianti Classico" sucht, bekommt darum die höchstbewerteten Chianti Classico der Welt —
nicht den, der auf der Karte steht. Gemessen an echten Karten:

| Suchbegriff | Treffer insgesamt | Erster Treffer | Ladenpreis |
|---|---|---|---|
| `Fontodi Chianti Classico` | 666 | Castell'in Villa Riserva 1986 | CHF 821 |
| `Tommasi Amarone Valpolicella` | 554 | Dal Forno Monte Lodoletta | CHF 734 |
| `Muga Rioja Reserva` | 212 | La Rioja Alta Gran Reserva 890 | CHF 170 |

In allen drei Fällen ist der gesuchte Produzent **unter den ersten 24 Treffern nicht
vorhanden**. Fontodi ist ein verbreiteter Chianti Classico für rund CHF 35; er verschwindet
hinter Weinen, die das Zehnfache kosten, weil sie höher bewertet sind.

Dieselben Weine, nur mit dem Produzenten als Suchbegriff:

| Suchbegriff | Treffer | Produzent getroffen | gefunden |
|---|---|---|---|
| `Fontodi` | 66 | 12 von 12 | Flaccianello, Vin Santo, Terrazze San Leolino |
| `Tommasi` | 58 | 12 von 12 | **Amarone Classico 2020, 4.2 (944), CHF 49.80** |
| `Muga` | 99 | 12 von 12 | Prado Enea, Torre Muga, Aro |
| `Delea` | 1040 | 12 von 12 | Carato Merlot Riserva, Diamante |

Der Produzent ist das unterscheidendste Wort auf jeder Karte. Die Appellation ist ein
Magnet für hunderte berühmte Weine.

**Steht kein Produzent auf der Karte** — häufig bei offenen Weinen — ist eine belastbare
Zuordnung meist nicht möglich. Das ist ein legitimes Ergebnis. Rate keinen Produzenten
dazu.

### `records_matched` als Warnsignal

Der Wert steht in jeder Antwort. Über etwa 200 war der Suchbegriff zu allgemein, und die
Trefferliste ist eine Rangliste berühmter Weine statt eine Antwort auf deine Frage. Dann
mit dem Produzenten allein neu suchen.

### Den richtigen aus den Kandidaten wählen

Nimm **nicht** `matches[0]`. Geh die Liste durch und wähle:

1. Der `winery.name` muss zum Produzenten auf der Karte passen.
2. Dann die Sperren aus `matching.md` anwenden — besonders die Qualitätsstufe. „Vietti
   Barolo" gibt 24 Kandidaten, alle von Vietti, aber **alle** sind Einzellagen
   (Lazzarito, Brunate, Ravera, Monvigliero) oder Riserva. Der einfache Barolo Castiglione
   von der Karte ist keiner davon, und die Einzellagen kosten das Drei- bis Zehnfache.
3. Passt der Jahrgang, nimm die Jahrgangsnote. Sonst die Wein-Note über alle Jahrgänge und
   sag, dass der Jahrgang abweicht.
4. Passt kein Kandidat, ist die Antwort „kein Eintrag". Nicht der nächstbeste.

## Die Plausibilitätsprüfung, die fast jeden Fehltreffer fängt

**Restaurantpreis geteilt durch Ladenpreis. Kommt weniger als etwa 1.5 heraus, hast du
den falschen Wein.** Kein Restaurant verkauft unter dem Ladenpreis.

Aus den Fehltreffern oben: ×0.1, ×0.1, ×0.2, ×0.5. Der richtige Treffer: ×2.2. Die
Prüfung kostet eine Division und trennt sauber. Wenn sie anschlägt, such neu — gib nicht
den Faktor aus.

## Wo die Werte stehen

```
explore_vintage.records_matched          → Anzahl Treffer (0 = kein Eintrag, >200 = zu allgemein)
explore_vintage.matches[i]
  .vintage.name                          → voller Name samt Jahrgang
  .vintage.year                           → Jahrgang
  .vintage.statistics.ratings_average     → Note für DIESEN Jahrgang    ← genauester Wert
  .vintage.statistics.ratings_count       → Anzahl Bewertungen
  .vintage.wine.name                      → Name ohne Produzent
  .vintage.wine.statistics.ratings_average→ Note über alle Jahrgänge
  .vintage.wine.winery.name               → Produzent  ← hiermit die Kandidaten filtern
  .vintage.wine.type_id                   → 1 rot · 2 weiss · 3 Schaumwein · 4 Dessert · 24 Rosé
  .vintage.wine.region.name               → Region (für die Trinkreife-Zuordnung)
  .price.amount                           → Ladenpreis in CHF
  .price.bottle_type_id                   → 1 = 75 cl
  .price.url                              → Händler, aus dem der Preis stammt
```

## Wie wenige Bewertungen sind zu wenige

Unter **30 Bewertungen** ist die Note Zufall. Ein 4.7 aus 6 Stimmen sagt weniger als ein
4.1 aus 3'000. Nenne die Anzahl immer mit — am Tisch entscheidet die jemand anders als du.

## Suchbegriff bauen

Produzent zuerst. Rechtsbegriffe, Gebinde und Jahrgang weglassen. Ein zweites Wort nur,
wenn es die Linie benennt und der Produzent viele Weine hat.

| Auf der Karte | Suchbegriff |
|---|---|
| `Barolo DOCG «Bussia» 2019, Prunotto` | `Prunotto Bussia` |
| `Chianti Classico 2021, Fontodi` | `Fontodi` |
| `Amarone della Valpolicella 2019, Tommasi` | `Tommasi` |
| `Fendant du Valais AOC, 5 dl` | `Fendant Valais` (kein Produzent — Zuordnung unsicher) |
| `Ch. Musar 2017, Bekaa` | `Chateau Musar` |

Karten kürzen (`Ch.`, `Cl.`, `Ris.`, `Cab. Sauv.`) und verschreiben sich. Löse die
Abkürzung auf, bevor du suchst.

## Wenn der Endpunkt nicht erreichbar ist

Schlechter Empfang, Netz gesperrt, Vivino antwortet nicht — dann ist die ehrliche Antwort,
dass es gerade nicht geht. Gib die Suchadresse zum Antippen:

```
https://www.vivino.com/search/wines?q=<SUCHBEGRIFF>
```

Was du **trotzdem** kannst und was am Tisch schon viel wert ist:

* Die Trinkreife aus `trinkreife.md` — die braucht kein Netz.
* Die Karte lesen: welche Positionen plausibel sind, wo die Preisstruktur auffällt,
  welche Weine offensichtlich Massenware sind.
* Glaspreise auf die Flasche hochrechnen und den Vergleich innerhalb der Karte ziehen.

Was du **nicht** tun sollst: eine Note aus dem Gedächtnis nennen. Weinnoten ändern sich,
Jahrgänge unterscheiden sich, und eine Zahl ohne Quelle ist am Tisch nicht überprüfbar.

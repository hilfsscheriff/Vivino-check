---
name: weinkarte
description: Analysiert eine Restaurant-Weinkarte und sagt, welche Flasche das beste Preis-Leistungs-Verhältnis hat — mit echten Vivino-Bewertungen, dem Aufschlag gegenüber dem Ladenpreis und der Trinkreife des Jahrgangs. Nutze diesen Skill immer, wenn ein Foto oder eine Abschrift einer Weinkarte, Getränkekarte oder Weinliste kommt, oder wenn jemand fragt, welchen Wein er im Restaurant nehmen soll, ob ein Weinpreis auf einer Karte in Ordnung ist, wie hoch der Aufschlag ist, welcher Wein auf einer Liste sich lohnt, oder ob ein bestimmter Jahrgang jetzt trinkreif ist — auch wenn die Wörter "Weinkarte" oder "Vivino" nicht fallen. Ebenso bei englischen Formulierungen wie "which wine should I order", "is this wine list overpriced", "check this wine menu". Nicht verwenden für Weinaktionen im Detailhandel, Kellerplanung oder Einkaufslisten.
---

# Weinkarte am Tisch

Du wirst im Restaurant gebraucht, nicht am Schreibtisch. Jemand sitzt da, der Kellner
wartet, auf der Karte stehen dreissig bis achtzig Positionen. Gebraucht wird **eine
Empfehlung in unter einer Minute**, nicht eine Auswertung.

Das prägt jede Entscheidung unten. Wenn du zwischen vollständig und schnell wählen musst,
wähle schnell und sag, was du weggelassen hast.

## Der Ablauf

### 1. Karte lesen

Aus dem Foto oder der Abschrift je Position: **Name, Jahrgang, Preis, Gebinde**
(Flasche / 5 dl / 1 dl / Glas). Wo etwas unleserlich ist, lass es weg statt zu raten —
eine Position weniger schadet nicht.

Rechne Glaspreise auf die Flasche hoch, damit sie vergleichbar werden: 1 dl × 7.5,
2 dl × 3.75, 5 dl × 1.5. Ein Glas zu CHF 9 entspricht CHF 67.50 pro Flasche, und das ist
oft die eigentliche Nachricht.

### 2. Vorauswahl treffen — vor der ersten Abfrage

Das ist der Schritt, der über die Nützlichkeit entscheidet. **Wähle fünf bis acht
Positionen aus, bevor du irgendetwas abfragst.** Achtzig Abfragen dauern zehn Minuten und
sind bis dahin niemandem mehr nützlich.

Auswahl nach dem, was gesagt wurde: Farbe, Budget, Essen. Wurde nichts gesagt, nimm eine
Spanne — zwei bis drei im unteren Preisdrittel, zwei in der Mitte, eine oben — über die
Farben verteilt, und **sag hinterher in einem Halbsatz, wonach du ausgewählt hast**. Frag
nicht nach. Wer im Restaurant sitzt, will keine Rückfrage, sondern eine Antwort; wenn die
Annahme falsch war, korrigiert er sie in fünf Sekunden.

Bevorzuge bei der Vorauswahl das, wo eine Karte typischerweise günstig ist: Winzer aus
Nebenregionen, Jahrgänge, die schon ein paar Jahre liegen, Weissweine aus Gebieten ohne
Prestige. Die berühmten Namen sind auf einer Karte fast immer die teuersten pro
Qualitätspunkt.

### 3. Bewertungen holen

Frag Vivino nach den ausgewählten Weinen ab. Endpunkt, Feldwege und Grenzen stehen in
`references/vivino-api.md` — **lies das, bevor du die erste Anfrage baust.** Zwei Dinge
dort entscheiden über brauchbar oder Unsinn, und beide sind nicht zu erraten:

* **Suche nach dem Produzenten, nie nach der Appellation.** Der Endpunkt sortiert nach
  Bewertung, nicht nach Namensähnlichkeit. „Fontodi Chianti Classico" liefert 666 Treffer,
  angeführt von einem Castell'in Villa Riserva 1986 für CHF 821 — Fontodi selbst kommt in
  den ersten 24 nicht vor. „Fontodi" allein liefert 12 von 12 richtige.
* **Nimm nicht den ersten Treffer.** Filtere die Kandidaten über `winery.name` und wende
  dann die Sperren an.

### 3a. Die Division, die fast jeden Fehltreffer fängt

Restaurantpreis geteilt durch Ladenpreis. **Kommt weniger als etwa 1.5 heraus, hast du den
falschen Wein** — kein Restaurant verkauft unter dem Ladenpreis. Bei den echten
Fehltreffern oben kam ×0.1, ×0.1, ×0.2 und ×0.5 heraus, beim richtigen ×2.2.

Schlägt die Prüfung an, such neu. Gib den Faktor nicht aus.

### 4. Zuordnung prüfen

**Bevor du eine Note weitergibst, prüfe die Sperren in `references/matching.md`.**
Das ist der Teil, den du nicht überspringen darfst. Eine gefundene Note gehört
regelmässig zu einem anderen Wein als dem auf der Karte — bei Zweitweinen, bei
Qualitätsstufen, bei Produzenten-Durchschnitten. „Mouton Cadet" für CHF 9.95 bekommt
sonst die 4.6 von Château Mouton Rothschild.

Findest du nichts, sag das. Ein „zu dem finde ich keine Bewertung" ist am Tisch besser
als eine plausible Zahl, die beim ersten Schluck auffällt.

### 5. Aufschlag rechnen

Der Restaurantpreis geteilt durch den Vivino-Ladenpreis. Das ist die Zahl, die die Karte
lesbar macht — sie trennt „guter Wein" von „guter Wein zu einem Preis, der hier Sinn
ergibt".

| Faktor | Einordnung |
|---|---|
| bis ×2 | ungewöhnlich fair, oft ein Wein, den das Haus selbst mag |
| ×2 – ×2.5 | günstig für die Schweiz |
| ×2.5 – ×3.5 | normal, das ist der Rahmen der meisten Häuser |
| ×3.5 – ×4 | sportlich |
| über ×4 | du zahlst für den Raum, nicht für den Wein |

Beide Preise sind **inklusive 8.1 % Mehrwertsteuer** — Gastronomie ist eine Leistung und
wird zum Normalsatz besteuert, Wein im Laden ebenso. Rechne also nichts um. Der reduzierte
Satz von 2.6 % gilt für Lebensmittel zum Mitnehmen und hat hier nichts zu suchen; wer ihn
einsetzt, verschiebt den Aufschlag um mehrere Prozent in die falsche Richtung.

Fehlt der Ladenpreis, lass die Spalte leer statt zu schätzen. Ein erfundener Aufschlag ist
schlechter als keiner.

### 6. Trinkreife prüfen

Schlag Region und Jahrgang in `references/trinkreife.md` nach. Der Code `g` — zu jung —
ist am Tisch ein Ausschlusskriterium, unabhängig von der Note. Ein Barolo 2022 mit 4.4 ist
eine gute Flasche, nur nicht heute Abend: die Bewertungen stammen von Leuten, die ihn
teils Jahre später getrunken haben. Wer ihn jetzt öffnet, bezahlt ein Versprechen.

Umgekehrt ist ein `*`-Jahrgang mit einer 4.0 heute die bessere Flasche als ein `g` mit
4.4. Das ist oft die wertvollste Auskunft des ganzen Skills, weil sie auf keiner Karte
steht und kein Kellner sie unaufgefordert gibt.

### 7. Antworten — kurz

**Drei Empfehlungen, je eine Zeile.** Dann aufhören.

```
**Nimm den <Wein>, CHF <Preis>** — Vivino <Note> (<Anzahl>), Aufschlag ×<Faktor>, <Reife>
```

Danach höchstens noch:

* eine Zeile, wovon abzuraten ist, wenn etwas auffällt — der teure Wein mit mittlerer
  Note, der hoch bewertete Wein, der noch fünf Jahre braucht;
* eine Zeile, wonach du ausgewählt hast und was du nicht geprüft hast.

Was hier **nicht** hingehört: eine Tabelle aller achtzig Positionen, eine Erklärung der
Methode, eine Einordnung der Region, Verkostungsnotizen. Am Tisch wird das nicht gelesen.
Wer mehr will, fragt nach — dann kannst du ausholen.

## Beispiel

Alle Zahlen unten sind echte Vivino-Werte, am 6.8.2026 abgefragt — nicht erfunden. Ein
Skill, der vor erfundenen Zahlen warnt, darf im eigenen Beispiel keine haben.

Karte (Auszug):

```
Amarone della Valpolicella Classico 2020, Tommasi     110
Rioja Prado Enea Gran Reserva 2016, Muga              165
Merlot Ticino «Carato» Riserva 2022, Delea             92
Fendant du Valais 2024, Provins                        42
```

Abfrage nach Produzent, Kandidaten über `winery.name` gefiltert, Sperren angewandt:

| Wein | Vivino | Laden | Karte | Faktor | Reife |
|---|---|---|---|---|---|
| Muga Prado Enea Gran Reserva 2016 | 4.4 (2'056) | 82.50 | 165 | ×2.0 | `*` Höhepunkt |
| Tommasi Amarone Classico 2020 | 4.2 (944) | 49.80 | 110 | ×2.2 | `g` **zu jung** |
| Delea Carato Merlot Riserva 2022 | 4.2 (834) | 58.60 | 92 | ×1.6 | `k` wird besser |
| Provins Fendant 2024 | 3.9 (44) | 13.90 | 42 | ×3.0 | `k` |

Antwort:

> **Nimm den Muga Prado Enea Gran Reserva 2016, CHF 165** — Vivino 4.4 aus 2'056
> Bewertungen, Aufschlag ×2.0, und der Jahrgang steht genau auf dem Höhepunkt.
> **Wenn es weniger sein soll: Delea Carato Merlot Riserva 2022, CHF 92** — 4.2 aus 834,
> Aufschlag ×1.6 und damit die fairste Kalkulation der Karte.
> **Günstig: Fendant du Valais 2024, CHF 42** — 3.9, aber nur aus 44 Bewertungen, die Note
> ist also dünn abgestützt. Als Apéro in Ordnung.
>
> Den Amarone Tommasi (CHF 110) würde ich heute lassen. Note und Aufschlag sind in
> Ordnung — aber der Jahrgang 2020 ist bei Amarone noch zu jung, und dafür CHF 110 zu
> zahlen heisst, ein Versprechen zu bezahlen.
>
> Vier Positionen geprüft, quer über die Preisspanne; die offenen Gläser und die
> Schaumweine habe ich nicht angeschaut.

Vier Abfragen, drei Empfehlungen, eine Warnung, ein Halbsatz zur Auswahl. Das ist die
Form. Beachte, was hier passiert: der **höchstbewertete und fair kalkulierte** Wein der
Karte ist der, von dem abgeraten wird — weil er heute Abend nicht trinkreif ist. Das ist
die Auskunft, für die es diesen Skill gibt.

## Wenn es hakt

**Foto unscharf oder abgeschnitten:** Nenne, was du lesen konntest, und arbeite damit.
Bitte nur dann um ein neues Foto, wenn weniger als eine Handvoll Positionen erkennbar
sind.

**Kein Netz:** Siehe `references/vivino-api.md` — die Trinkreife funktioniert offline, und
das Lesen der Preisstruktur auch. Sag, was fehlt.

**Nur Weinnamen ohne Jahrgang:** Häufig auf Kartenkarten mit offenen Weinen. Dann nimm
die Wein-Note über alle Jahrgänge und sag, dass der Jahrgang fehlt — ohne Jahrgang gibt
es keine Trinkreife-Auskunft.

**Ein Wein taucht mehrfach auf** (Glas und Flasche): Rechne beides auf die Flasche und
nenne die günstigere Form. Der Unterschied ist oft grösser als der zwischen zwei Weinen.

## Warum das so gebaut ist

Das Regelwerk hier stammt aus einem Werkzeug, das wöchentlich die Aktionen der grossen
Schweizer Weinhändler gegen Vivino und Falstaff prüft
(<https://hilfsscheriff.github.io/Vivino-check/>). Die Sperren in `matching.md` sind keine
Theorie, sondern die Fehler, die dort im Livebetrieb aufgetreten sind — jeder Eintrag
steht für eine Flasche, die beinahe mit der Note einer anderen empfohlen worden wäre.

Der Leitsatz, der über allem steht: **eine Lücke ist besser als eine erfundene Zahl.**
Am Restauranttisch gilt das doppelt, weil die Empfehlung sofort in eine Bestellung
umgesetzt wird und niemand mehr nachprüft, woher die Zahl kam.

# Spec: Stil-Typ («Typ») für Weincheck

**Zielprojekt:** `hilfsscheriff/Vivino-check`
**Version:** 1.1
**Status:** Entwurf zur Umsetzung

---

## 1. Problem und Ziel

### 1.1 Befund

Die bestehende Preis-Leistungs-Kennzahl normalisiert gegen «Weine derselben Sorte zum gleichen Preis». Das erzeugt einen **systematischen Stil-Bias**:

1. Vivino-Noten sind Publikumsmittelwerte. Weiche, fruchtsüsse, holzgeprägte Weine erreichen dort verlässlich 4.2–4.4, weil sie kaum jemandem missfallen. Straffe, säure- oder tanninbetonte Weine polarisieren und landen bei 3.9–4.2, auch bei höherer fachlicher Qualität.
2. Die fruchtsüsse Machart ist günstig herstellbar und braucht keine teure Herkunft. Sie ist im tiefen Preissegment überrepräsentiert.
3. Folge: Der Quadrant «gut und günstig» (Note ≥ 4.2, ≤ CHF 20) füllt sich strukturell mit **einem einzigen Geschmacksprofil**.
4. Zusätzlich ist `Sorte` ein schwacher Prädiktor für den Geschmack. Sangiovese als Appassimento und Sangiovese als Brunello tragen denselben `Sorte`-Wert und sind sensorisch unvereinbar.

### 1.2 Ziel

Ein neues Feld `typ` als **Korrekturvariable**, das

- den sensorischen Endpunkt beschreibt, nicht die Technik,
- als Filter und als Gruppierungsachse für die Preis-Leistungs-Rechnung dient,
- die Konfidenz seiner Herleitung offenlegt,
- nach den bestehenden Prinzipien der Seite arbeitet: nachvollziehbar, im Klartext dokumentiert, ohne Blackbox, ohne Drittressourcen zur Laufzeit.

### 1.3 Nicht-Ziele

- Keine Qualitätsbewertung. `typ` beschreibt die Machart, nicht wie gut der Wein ist.
- Kein ML-Modell. Regelbasiert, deterministisch, auditierbar.
- Keine Aromadeskriptoren als Filter. Gehört in eine Verkostungsnotiz, nicht in eine Facette.
- Keine Reifekategorie. Wird durch `Trinkreife` bereits abgedeckt.
- Keine Körper-Achse. Korreliert zu stark mit `typ`, um eigenständigen Informationswert zu haben.

---

## 2. Kategorien

Vier Werte auf **einer** Achse, plus Rückfallwert. Bewusst grob gehalten: Die Datengrundlage trägt keine feinere Auflösung, und ein Mobilfilter mit mehr als vier Optionen ist unbenutzbar.

| Slug | Label (UI) | Definition | Typische Marker |
|---|---|---|---|
| `fruchtsuess` | Fruchtsüss | Süsser Eindruck am Gaumen, unabhängig von der Technik. Restzucker über ~5 g/l, tiefe Säure, weiche Tannine, oft viel neues Holz | Appassimento, Passito, Ripasso, late harvest, smooth red blend, Coffee Pinotage, Alkohol ≥ 14.5 % |
| `weich_modern` | Weich & modern | Gesetzlich und sensorisch trocken, aber runde Säure und deutliche Holzprägung. Internationaler Stil | Barrique-betont, warme Klimazonen, kommerzielle Cuvées |
| `ausgewogen` | Ausgewogen | Kein Extrem in beide Richtungen. Frucht, Säure und Tannin in Balance | klassische Appellationen mittlerer Reife |
| `straff_herb` | Straff & herb | Säure oder Tannin tragen den Wein. Herber, salziger oder kräutriger Zug | Sangiovese, Nebbiolo, Riesling, Negroamaro klassisch, Cabernet Franc, Tannat |
| `unbekannt` | – | Klassifikation nicht möglich | – |

**Wichtig:** Die Achse ist ordinal (`fruchtsuess` → `straff_herb`). In der UI darf sie als Gradient oder Slider dargestellt werden, nicht als unsortierte Checkbox-Gruppe.

**Wichtig:** Der Slug heisst `fruchtsuess` und nicht `appassimento`. Rund die Hälfte der Weine dieser Kategorie erreicht das Profil **ohne** getrocknete Trauben — über Spätlese, hohen Alkohol, malolaktischen Ausbau, Restzucker und amerikanische Eiche. Eine technikbenannte Kategorie würde diese Hälfte verfehlen.

---

## 3. Datenmodell

Neue Felder pro Wein-Datensatz:

```
typ            : enum   // fruchtsuess | weich_modern | ausgewogen | straff_herb | unbekannt
typ_stufe      : int    // 1 = gesichert, 2 = abgeleitet, 3 = vermutet, 0 = unbekannt
typ_signale    : string[] // menschenlesbare Belege, z.B. ["Name: appassimento", "Alkohol 15.0 %"]
typ_score      : float  // interner Rohwert, -1.0 (straff) bis +1.0 (fruchtsüss); nur für Debug
```

`typ_signale` ist **Pflicht** und wird in der UI angezeigt. Ohne Begründung kein Typ.

---

## 4. Klassifikations-Kaskade

Drei Stufen mit absteigender Sicherheit. **Die erste greifende Stufe entscheidet**; spätere Stufen können den Wert nicht überschreiben. Die entscheidende Stufe wird in `typ_stufe` festgehalten und in der UI ausgewiesen.

### Stufe 1 — Gesichert (`typ_stufe = 1`)

Harte Signale aus Name, Bezeichnung oder Datenblatt. Wenn eines greift, ist der Fall entschieden.

**1a. Trocken-/Süsse-Tokens im Wein- oder Linienname** (case-insensitive, Wortgrenzen beachten, diakritikaunempfindlich):

```
appassimento, passito, ripasso, amarone, recioto, sforzato, sfursat,
vendemmia tardiva, uve appassite, uve stramature,
late harvest, dried grape, sweet red,
vendange tardive, passerille, vin de paille, moelleux, demi-sec,
strohwein, schilfwein, spaetlese, auslese, beerenauslese,
trockenbeerenauslese, eiswein, lieblich, halbtrocken, edelsuess,
cosecha tardia, vendimia tardia, dulce, semidulce, semiseco,
colheita tardia, meio seco,
vinsanto, vin santo, liastos, commandaria, mavrodaphne
```

→ `fruchtsuess`

**1b. Analysewerte, falls im Händlertext oder Datenblatt vorhanden:**

| Bedingung | Ergebnis |
|---|---|
| Restzucker ≥ 5 g/l | `fruchtsuess` |
| Restzucker < 2 g/l **und** Gesamtsäure ≥ 5.5 g/l | `straff_herb` |
| Alkohol ≥ 15.0 % (Rotwein, nicht aufgespritet) | `fruchtsuess` |
| Alkohol ≥ 14.5 % **und** ein Keyword aus Bucket A (§6) | `fruchtsuess` |

**1c. Stilmarken-Blacklist** — Marken und Produktlinien, deren Profil bekannt ist. Als pflegbare Liste in `data/stilmarken.json` auslegen, nicht hartcodiert:

```
apothic, menage a trois, 19 crimes, josh cellars, cupcake,
barista pinotage, coffee pinotage, chocolate block,
yellow tail, jam shed, big red bicycle
```

→ `fruchtsuess`

**1d. Denomination ohne Herkunft** *(neu in 1.1)*

Die untersten Herkunftsstufen existieren **ausschliesslich**, um regionenübergreifendes Verschneiden zu erlauben. Wer sie wählt, verzichtet freiwillig auf jede Herkunftsangabe, die er haben könnte. Das ist eine **Absichtserklärung über die Machart, kein Nebensignal**: der Wein soll jedes Jahr gleich schmecken, unabhängig davon, was welche Lage hergab — und genau dafür wird verschnitten, angetrocknet und im Holz gerundet.

Liste, pflegbar in `data/denominationen.json`:

```
vino d'italia, vino da tavola, vin de france, vin de table,
deutscher wein, vino de españa, wine of chile, wine of argentina,
south eastern australia, european union table wine
```

Logik:

- Denomination in Liste **und** (Jahrgang ist `null` **oder** Name enthält `n.v.` **oder** Sorte in `[cuvée, red blend, white blend]`)
  → `typ = fruchtsuess`, `typ_stufe = 1`, Signal «Denomination ohne Herkunft, jahrgangslos»
- Denomination in Liste, sonst
  → `typ = weich_modern`, `typ_stufe = 2`, Signal «Denomination ohne Herkunft»

Die Regel steht als **letzte** innerhalb Stufe 1. Ein gemessener Restzucker- oder Alkoholwert aus 1b ist eine Tatsache über den Wein im Glas und schlägt eine Absichtserklärung des Abfüllers, auch wenn beide dieselbe Stufe tragen.

**Hinweis zur Abgrenzung:** Botrytis-Weine (Trockenbeerenauslese, Sauternes, Tokaji aszú) erreichen ihre Konzentration über Edelfäule, nicht über Trocknung. Sensorisch landen sie ebenfalls in `fruchtsuess`, was für diesen Zweck korrekt ist. Sie sind ohnehin deklarierte Dessertweine und dürfen zusätzlich über eine bestehende Weinart-Facette ausgefiltert werden.

### Stufe 2 — Abgeleitet (`typ_stufe = 2`)

**Primärquelle: Vivino `wine_style`.**

Vivino führt pro Wein ein strukturiertes Stil-Feld (etwa «Southern Italy Primitivo», «Tuscan Sangiovese», «Northern Rhône Syrah»). Der Wertebereich umfasst grob 200 Einträge und ist stabil. Diese einmal von Hand auf die vier Typen mappen — deutlich robuster als jede Textanalyse.

Ablage: `data/vivino_style_map.json`

```json
{
  "Southern Italy Primitivo":      "fruchtsuess",
  "Southern Italy Red":            "fruchtsuess",
  "Puglian Red":                   "fruchtsuess",
  "Veneto Amarone":                "fruchtsuess",
  "Californian Red Blend":         "fruchtsuess",
  "South African Pinotage":        "fruchtsuess",
  "Australian Shiraz":             "weich_modern",
  "Abruzzese Montepulciano":       "weich_modern",
  "Central Spain Red":             "weich_modern",
  "Ribera del Duero Red":          "ausgewogen",
  "Tuscan Red":                    "ausgewogen",
  "Southern Rhone Red Blend":      "ausgewogen",
  "Languedoc Red":                 "ausgewogen",
  "Brunello di Montalcino":        "straff_herb",
  "Tuscan Sangiovese":             "straff_herb",
  "Piedmont Nebbiolo":             "straff_herb",
  "Barolo":                        "straff_herb",
  "Northern Rhone Syrah":          "straff_herb",
  "Loire Cabernet Franc":          "straff_herb",
  "Rioja Red":                     "ausgewogen"
}
```

*Das ist eine Startmenge, keine vollständige Tabelle.* Beim Import unbekannte `wine_style`-Werte in ein Log schreiben (`logs/unmapped_styles.txt`), damit die Tabelle über die Läufe wächst.

**Fallback, falls `wine_style` nicht abgreifbar ist:** Kombination `Sorte × Land × Region` über eine analoge Tabelle. Schwächer, weil die Sorte-Region-Kombination die Machart nicht mitträgt (siehe §1.1 Punkt 4), aber besser als Stufe 3.

**Optional, falls verfügbar:** Vivino liefert auf manchen Wein-Seiten eine Geschmacksstruktur mit vier Achsen (Bold/Light, Tannic/Smooth, Dry/Sweet, Soft/Acidic). Wenn diese Werte abgreifbar sind, ersetzen sie Stufe 2 und 3 vollständig:

```
score = 0.5 * dry_sweet + 0.3 * smooth_tannic_invertiert + 0.2 * soft_acidic_invertiert
```

Dann ist Stufe 3 nur noch Notnagel.

### Stufe 3 — Vermutet (`typ_stufe = 3`)

Keyword-Analyse der Händler-Verkostungsnotiz. Nur wenn Stufe 1 und 2 nichts liefern.

```
score = (treffer_bucket_A - treffer_bucket_B) / max(1, treffer_bucket_A + treffer_bucket_B)
```

| `score` | `typ` |
|---|---|
| ≥ +0.4 | `fruchtsuess` |
| +0.1 bis +0.4 | `weich_modern` |
| −0.1 bis +0.1 | `ausgewogen` |
| ≤ −0.1 | `straff_herb` |

Bei weniger als drei Gesamttreffern: `unbekannt`. Zu dünne Basis für eine Aussage.

---

## 5. Keyword-Buckets

Ablage: `data/typ_keywords.json`. Diakritikaunempfindlich matchen, Wortstämme genügen.

**Bucket A — opulent / fruchtsüss**

```
vanille, kakao, schokolade, kaffee, espresso, mokka, lakritze,
marmelade, konfiture, konfituere, eingekocht, doerrfrucht, rosine,
dattel, feige, pflaumenkompott, karamell, toffee, honig, kokos,
samtig, samten, weich, rund, cremig, schmeichelnd, sanft, ueppig,
opulent, wuchtig, fuellig, morbido, geschmeidig, milder,
kraftvoll-suess, restsuesse, fruchtsuess,
reich, reichhaltig, dicht, dichte frucht, konzentriert,
bold, powerful, intensiv, gross, kraftvoll, kraeftig
```

*Neu in 1.1:* die Gruppe ab `reich`. Sie beschreibt Konzentration, und Konzentration entsteht bei diesen Weinen auf demselben Weg wie die Süsse — über Reife, Antrocknen und Holz. `kraeftig` steht dabei nicht in der ursprünglichen Vorlage, ist aber nötig: die Händlernotiz des Anlassfalls lautet wörtlich «reich, dicht, kräftig», und `kraftvoll` trifft `kräftig` nicht. Ohne das Wort blieben zwei Treffer, und Stufe 3 hätte am eigenen Anlassfall weiter geschwiegen.

**Bucket B — straff / herb**

```
gerbstoff, tannin-praesent, herb, bitter, salzig, salzig-mineralisch,
mineralisch, kraeuter, kraeutrig, wacholder, thymian, rosmarin,
leder, tabak, teer, rauch, feuerstein, graphit, bleistift,
frisch, frische, saftig-frisch, saeure, saeurebetont, straff,
knackig, kantig, streng, austere, nervig, geradlinig, schlank,
zitrusfrisch, sauerkirsche, rhabarber, blutorange, granatapfel
```

**Fallen, die zu vermeiden sind:**

- «Kirsche» allein ist neutral. Nur `sauerkirsche` in Bucket B, nur `kirschkonfitüre` in Bucket A.
- «Beere» allein ist neutral.
- «Lakritze» steht in Bucket A, weil sie in Händlertexten fast ausschliesslich zusammen mit Kakao und Vanille auftritt. Falls Fehlklassifikationen auffallen, in eine neutrale Liste verschieben.
- Marketingfloskeln («Genuss», «Charakter», «Eleganz») nie einlesen.

---

## 6. Anpassung der Preis-Leistungs-Kennzahl

**Bestehend:** Normalisierung der Note gegen Weine derselben `Sorte` im gleichen Preisband.

**Neu:** Gruppierung nach `(typ, preisband)` statt `(sorte, preisband)`, mit `sorte` als Sekundärachse, wo die Fallzahl es trägt.

Begründung: `typ` ist der stärkere Prädiktor der Vivino-Note als `sorte` (§1.1). Ein Appassimento-Primitivo gegen einen Brunello-Sangiovese zu normalisieren, weil beide «Rotwein Italien» sind, verzerrt die Kennzahl in Richtung der publikumsfreundlichen Machart.

**Mindestfallzahl:** Unter 15 Weinen in einer `(typ, preisband)`-Zelle auf die reine `typ`-Gruppe zurückfallen, unter 15 dort auf global. Fallback-Ebene im Tooltip ausweisen.

**Weine mit `typ = unbekannt`** werden gegen die globale Verteilung normalisiert und in der UI mit dem Hinweis versehen, dass die Kennzahl weniger belastbar ist.

**Rückwärtskompatibilität:** Die alte Kennzahl parallel weiterrechnen und beide Werte im Datensatz halten, bis die Verteilung geprüft ist. Ein Umschalter im Debug-Modus genügt.

---

## 7. UI

### 7.1 Filter

Neue Facette «Typ» neben `Sorte`. Vier Optionen in ordinaler Reihenfolge (`fruchtsuess` links). Mehrfachauswahl. `unbekannt` nur unter «Feinauswahl» einblenden.

### 7.2 Streudiagramm

**Punkte nach `typ` einfärben.** Vier Farben, keine weiteren Kodierungen. Das macht den Bias aus §1.1 auf einen Blick sichtbar, ohne dass eine Kennzahl erklärt werden muss. Geringster Aufwand, grösster Erkenntnisgewinn der ganzen Änderung.

Farbwahl: ordinaler Verlauf (warm → kühl), nicht vier kategoriale Farben, weil die Achse geordnet ist. Auf Farbfehlsichtigkeit prüfen; Form oder Füllung als zweiter Kanal erwägen.

### 7.3 Tabelle

Neue Spalte «Typ», sortierbar wie die bestehenden. Zelle zeigt Label plus Konfidenzhinweis:

- Stufe 1: Label ohne Zusatz
- Stufe 2: Label ohne Zusatz
- Stufe 3: Label mit nachgestelltem `?`
- `unbekannt`: `–`

Tooltip oder Detailzeile listet `typ_signale` im Klartext. Kein Typ ohne Begründung.

### 7.4 Fussnote

Im Stil der bestehenden Erläuterungen:

> **Typ** ist aus Name, Sorte, Region und Vivino-Stil abgeleitet, nicht verkostet. Er beschreibt die Machart, nicht die Qualität. «Fruchtsüss» heisst nicht «süss»: Diese Weine sind meist gesetzlich trocken. Der süsse Eindruck entsteht aus Restzucker, hohem Alkohol, malolaktischem Ausbau und neuem Holz zusammen — nicht aus zugesetztem Zucker. Ein `?` bedeutet, dass der Typ nur aus Verkostungsnotizen geschätzt ist.

---

## 8. Testfälle

Fixtures mit erwarteten Ergebnissen. Aus realen Datensätzen, mit dokumentierter Machart.

| Wein | Erwartet | Erwartete Stufe | Entscheidendes Signal |
|---|---|---|---|
| Santi Nobile Cento X Cento Appassimento Primitivo | `fruchtsuess` | 1 | Token `appassimento` im Namen |
| Cantine Leonardo da Vinci, Uve portate a Cesena | `fruchtsuess` | 1 oder 2 | Linie heisst «Sangiovese Appassimento»; Name allein trägt kein Token → prüft den Linien-/Produzentenabgleich |
| Tenuta Ulisse Amaranta Montepulciano d'Abruzzo | `fruchtsuess` | 1 | Restzucker 7 g/l im Händlerdatenblatt |
| Tenuta Ulisse 10 Vendemmie N.V. | `fruchtsuess` | 2 oder 3 | kein Token, kein Analysewert → Stufe 2 muss greifen |
| Cantina Diomede Canace Nero di Troia | `fruchtsuess` | 2 oder 3 | teilweises Antrocknen am Stock, nicht im Namen |
| Fantini Edizione Cinque Autoctoni N.V. | `weich_modern` | 2 | Barrique-geprägt, aber kein Appassimento |
| Cignomoro 80 Vecchie Vigne Primitivo di Manduria | `weich_modern` | 2 | alte Reben, Barrique, marmeladig, aber trocken |
| Mottura Rosone Negroamaro del Salento | `straff_herb` | 2 | Negroamaro klassisch, herb-mandelig |
| Argiano Brunello di Montalcino 2020 | `ausgewogen` oder `straff_herb` | 2 | warmer Jahrgang, südliche Lage → Grenzfall, beide Werte zulässig |
| Castello Finoto Brunello di Montalcino 2020 | `straff_herb` | 2 | Sangiovese, Slawonische Eiche, adstringierende Tannine |
| Arrocal Reserva de Familia Tinto Fino | `straff_herb` | 2 | Höhenlage, ausgeprägte Säure |
| Domaine des Creisses Les Brunes | `straff_herb` | 2 | Cabernet-dominiert, Basaltboden, neues Holz aber straff |
| Barista Pinotage | `fruchtsuess` | 1 | Stilmarken-Liste |
| Apothic Red | `fruchtsuess` | 1 | Stilmarken-Liste |
| **Gran Sasso Tre Autoctoni N.V.** *(neu in 1.1)* | `fruchtsuess` | 1 | Denomination «Vino d'Italia» + N.V. |

**Zum neuen Fixture:** Farnese Vini (Fantini Group), Denomination «Vino d'Italia» / «Vino da Tavola», in Vivino Sorte «Cuvée» und Region «Vino d'Italia». Nerello Mascalese, Montepulciano und Primitivo aus drei Regionen, 14.5 % Alkohol, kein Jahrgang, CHF 9.95, Vivino 4.2 bei 970 Bewertungen. Sensorisch eindeutig `fruchtsuess`.

**Dieser Fall ergab vor dem Patch `unbekannt`**, und zwar weil jede einzelne Achse leerlief:

- Stufe 1a: kein Treffer, «Tre Autoctoni» ist neutral
- Stufe 1b: 14.5 % greift nur zusammen mit einem Bucket-A-Keyword; die Händlernotiz «reich, dicht, kräftig» stand nicht in Bucket A
- Stufe 2: die Region ist keine Region, die Sorte ist keine Sorte — beide Lookup-Achsen tragen null Information
- Stufe 3: unter der Mindesttrefferzahl von drei

**Offener Widerspruch zu einem Fixture** *(festgestellt am 10.8.2026)*: «Mottura Rosone Negroamaro del Salento» ist hier mit `straff_herb` und der Begründung «Negroamaro klassisch, herb-mandelig» eingetragen. Vivinos gemessene Geschmacksstruktur über **346 Nutzerurteile** sagt Süsse 3.0/5, Tannin 2.6, Säure 2.3 — also die moderne, süsslich ausgebaute Salento-Machart. Die Umsetzung liefert `fruchtsuess` mit Score 0.91. Bei dieser Urteilszahl ist die Messung schwer zu übergehen; wahrscheinlich beschreibt das Fixture den klassischen Stil, während die hier verkaufte Flasche der moderne ist. **Nicht entschieden** — wer den Wein kennt, soll das Fixture bestätigen oder die Erwartung korrigieren.

**Akzeptanzkriterien**

1. Alle Fixtures der Stufe 1 werden exakt getroffen. Kein Spielraum.
2. Über den gesamten aktuellen Datenbestand liegt der Anteil `unbekannt` unter 15 %.
3. Kein Wein erhält einen `typ` ohne mindestens einen Eintrag in `typ_signale`.
4. Die Verteilung im Quadranten «gut und günstig» wird vor und nach der Änderung protokolliert. Erwartung: deutliche Übergewichtung von `fruchtsuess`. Falls sie ausbleibt, ist die Klassifikation zu prüfen, nicht der Befund zu verwerfen.
5. Die Preis-Leistungs-Rangfolge verschiebt sich messbar. Die zehn grössten Rangänderungen manuell gegenlesen.
6. **Weine mit einer Denomination ohne Herkunft dürfen nie `unbekannt` ergeben.** *(neu in 1.1)* Die Denomination ist bei diesen Weinen das einzige verlässliche Signal; wenn sie nicht greift, greift bei ihnen nichts.

---

## 9. Umsetzungsreihenfolge

1. Felder ins Datenmodell, `typ = unbekannt` für alle. Keine UI-Änderung.
2. Stufe 1 implementieren, Fixtures 1, 3, 13, 14, 15 grün.
3. `vivino_style_map.json` anlegen, Stufe 2, Logging unbekannter Styles.
4. Streudiagramm nach `typ` einfärben. **Ab hier ist der Nutzen bereits sichtbar** — guter Punkt für einen ersten Zwischenstand.
5. Stufe 3 mit Keyword-Buckets.
6. Filterfacette und Tabellenspalte.
7. Preis-Leistungs-Umstellung auf `(typ, preisband)`, beide Kennzahlen parallel.
8. Verteilungsvergleich, Fussnote, alte Kennzahl entfernen.

Schritte 1 bis 4 sind für sich wertvoll und liefern schon die Kernaussage. Falls die Zeit knapp wird, dort stoppen.

---

## 10. Offene Punkte

- **Verfügbarkeit von `wine_style`:** Vor Schritt 3 prüfen, ob das Feld über den bestehenden Vivino-Zugriff verlässlich mitkommt. Wenn nicht, entscheidet der Fallback aus §4 Stufe 2 über den Nutzwert der ganzen Änderung.
- **Weisswein und Schaumwein:** Diese Spec ist an Rotwein entwickelt. Für Weissweine trägt die Achse anders (Restzucker ist bei Riesling ein Qualitätsmerkmal, kein Stilmarker). Entweder eine eigene Achse oder Weissweine zunächst auf `unbekannt` setzen und explizit ausweisen.
- **Produzenten-Ebene:** Mehrere Fälle (Leonardo da Vinci, Tenuta Ulisse) sind nur über die Produktlinie klassifizierbar, nicht über den Weinnamen. Eine Tabelle `produzent × linie → typ` wäre die saubere Lösung, aber pflegeintensiv. Zunächst über die Stilmarken-Liste abdecken und beobachten, wie viele Fälle auflaufen.
- **Jahrgangsabhängigkeit:** Ein warmer Jahrgang verschiebt einen Wein um eine Kategorie (Argiano 2020 gegen 2016). Bewusst ignoriert. Falls es störend auffällt, liesse sich die bestehende Trinkreifetabelle als Jahrgangs-Korrektiv nutzen, was aber Aufwand und Fehlerquellen deutlich erhöht.
- **Konzernzugehörigkeit** *(neu in 1.1)*: optionales Feld `konzern`. In einer Stichprobe von 14 Aktionsweinen kamen drei aus derselben Gruppe — Fantini/Farnese mit «Fantini Edizione Cinque Autoctoni», «Cantina Diomede Canace» und «Gran Sasso Tre Autoctoni» —, bei rund 15 Mio. Flaschen Jahresproduktion. Die Seite zeigt heute Sorten- und Regionenvielfalt, aber nicht **Anbietervielfalt**: drei Zeilen können wie drei Entscheidungen aussehen und doch eine sein. Ausdrücklich als **Beobachtungspunkt** aufgenommen, nicht als Anforderung: die Datenpflege ist aufwendig, der Nutzen unbewiesen, und ein halb gepflegtes Konzernfeld wäre schlechter als keines. Erst zählen, wie oft der Fall auftritt.
- **Selbstbeobachtung:** Nach ein paar Wochen prüfen, ob sich das eigene Kaufverhalten verändert. Wenn nicht, war der Befund richtig, aber der Filter nutzlos — dann eher die Standardsortierung anpassen als weitere Facetten bauen.

---

## Changelog

### Version 1.1 — 9. August 2026 (Messungen nachgetragen 10. August)

- **§4 Stufe 1d «Denomination ohne Herkunft» neu.** Die untersten Herkunftsstufen sind eine Absichtserklärung über die Machart, kein Nebensignal. Liste in `data/denominationen.json`. Mit jahrgangslosem Wein, `n.v.` im Namen oder einer Sortenangabe wie «Cuvée» → `fruchtsuess` auf Stufe 1; ohne dieses zweite Zeichen → `weich_modern` auf Stufe 2. Steht als letzte Regel innerhalb Stufe 1, damit ein gemessener Analysewert aus 1b vorgeht. Kaskadenreihenfolge unverändert.
- **§5 Bucket A erweitert** um `reich, reichhaltig, dicht, dichte frucht, konzentriert, bold, powerful, intensiv, gross, kraftvoll` — dazu `kraeftig`, das in der Vorlage fehlte, ohne das aber der eigene Anlassfall weiter durchgefallen wäre.
- **§8 neues Fixture** «Gran Sasso Tre Autoctoni N.V.» → `fruchtsuess`, Stufe 1. Vermerkt, dass der Fall vor dem Patch `unbekannt` ergab, und weshalb jede Achse leerlief.
- **§8 neues Akzeptanzkriterium 6:** Weine mit einer Denomination ohne Herkunft dürfen nie `unbekannt` ergeben.
- **§10 neuer offener Punkt «Konzernzugehörigkeit»** — Anbietervielfalt als Beobachtungspunkt, nicht als Anforderung.
- **§9 Schritt 2** nennt das neue Fixture mit.

**Anmerkungen zur Umsetzung im Zielprojekt** (die Spec selbst bleibt davon unberührt):

- Alle pflegbaren Listen liegen zusammen in `sources/stiltyp.yaml` statt in einzelnen `data/*.json`. Grund: `sources/` trägt schon `trinkreife.yaml` und `retailers.yaml`, und YAML erlaubt Kommentare — bei jeder Zeile steht damit, *warum* sie dasteht. In JSON liesse sich das nicht hinschreiben.
- Die Denomination wird aus Vivinos `wine.region.name` gelesen. Bei den untersten Herkunftsstufen steht dort die Denomination selbst («Vino d'Italia»), während `wine.style.name` nur «Italian Red» liefert und damit nichts beiträgt.
- Der «Optional»-Pfad aus §4 Stufe 2 ist verfügbar und umgesetzt: `wine.taste.structure` liefert Süsse, Tannin und Säure **pro Wein** samt `user_structure_count`. Die handgepflegte `stil_tabelle` ist damit der dritte Rang, nicht der erste.
**Ergebnisse der Umsetzung, gemessen am 10.8.2026** über 1570 Weine:

- **Kriterium 1 erfüllt** — alle Stufe-1-Fixtures treffen, inklusive des neuen Gran Sasso (`fruchtsuess`, Stufe 1, Signal «Denomination ohne Herkunft ('Vino d'Italia'), jahrgangslos»).
- **Kriterium 2 gerissen: 38.0 % `unbekannt` statt unter 15 %.** Das ist kein Klassifikationsfehler, sondern eine Datengrenze: 448 der 597 Weine haben überhaupt keinen Vivino-Treffer, weitere 85 wurden über die Weingutseite gefunden, die weder `taste` noch `style` liefert. Um unter 15 % zu kommen, müsste der `Sorte × Land × Region`-Rückfall aus §4 gebaut werden — von Hand gepflegt, von §4 selbst als schwächster Weg bezeichnet, und jeder Eintrag eine Behauptung über eine Weinart. Offen.
- **Kriterium 3 erfüllt** — kein Wein trägt einen Typ ohne Eintrag in `typ_signale`.
- **Kriterium 4 erfüllt, und deutlich.** Im Quadranten «gut und günstig» (Note ≥ 4.2, ≤ CHF 20, 46 Weine) verteilen sich die eingeordneten auf 59 % `fruchtsuess`, 20 % `weich_modern`, 8 % `ausgewogen`, 13 % `straff_herb`. Über den ganzen bewerteten Bestand sind es 19 / 16 / 21 / 35 %. Die fruchtsüsse Machart ist dort also **dreifach übervertreten**, die straffe fast dreifach unter — genau der Befund aus §1.1.
- **Kriterium 5 erfüllt** — die Rangfolge verschiebt sich um im Median 51 Plätze, nur 11 von 891 vergleichbaren Weinen bleiben stehen. Beim Gegenlesen der zehn grössten Änderungen zeigt sich die beabsichtigte Richtung: zwei Amarone und beide Moët Ice Impérial (Demi-Sec) fallen um 300 bis 500 Plätze, ein Minuty M Rosé und ein Tua Rita Syrah steigen um 500 bis 550.
- **Kalibrierung.** Die Schwellen aus §4 setzen eine zentrierte Achse voraus. Ein geschätzter Normalfall lieferte die nicht — 33 von 39 Weinen fielen auf `straff_herb`. Die Normalwerte sind jetzt die Mediane über 839 Weine mit mindestens 15 Urteilen: Süsse 1.77, Tannin 3.33, Säure 3.39. Gegenprobe: alle 20 Barolo und 27 von 28 Brunello ergeben `straff_herb`, alle 17 Amarone, 9 Appassimento, 7 Ripasso und 26 Primitivo `fruchtsuess`.
- **Nebenertrag.** Das Herkunftsland liegt jetzt für 1061 statt 585 Weine vor, weil es in derselben Antwort steht wie die Note.

- Beim Anlassfall widersprechen sich zwei Signale: Stufe 1d sagt `fruchtsuess`, Vivinos gemessene Struktur nennt eine Süsse von 1.49 von 5. Stufe 1d gewinnt, weil die Kaskade so gebaut ist — die erste greifende Stufe entscheidet. Das ist eine bewusste Entscheidung dieser Spec und kein Versehen der Umsetzung.

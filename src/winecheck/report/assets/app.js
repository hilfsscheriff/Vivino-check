const D = __PAYLOAD__;
/* Kurzschlüssel aus der eingebetteten JSON zurückbenennen — sie halten die Datei
   klein, der Code arbeitet aber mit lesbaren Namen. */
/* Die Umkehrung von _SHORT_KEYS, beim Bauen aus Python eingesetzt — nicht von Hand
   gepflegt. Vorher stand die Abbildung zweimal da, einmal je Richtung, und ein
   fehlendes Paar hat schon einen Ausfall gekostet: w.swiss war im Browser immer
   undefiniert, und der Quellenfilter zeigte in jeder Einzelstellung null Weine. */
const KEYS = __KEYS__;
D.runs.forEach(run => {
  run.wines = run.wines.map(w => {
    const o = { retailers: [], name: "", style: "", maturity: "", styleLabel: "",
                maturityShort: "", cheapest: "", url: "", vivinoUrl: "", vintage: "" };
    for (const [short, long] of Object.entries(KEYS)) {
      if (short in w) o[long] = w[short];
    }
    if (!o.retailers.length && o.cheapest) o.retailers = [o.cheapest];
    return o;
  });
});
/* So viele Zeilen auf einmal. Vorher standen 400 fest im Dokument: bei 623 Weinen
   waren 223 nur über „Filter verfeinern" erreichbar, und die Tabelle allein trug
   über 800 Tabstopps. */
const PAGE = 50;
/* Rotwein ist vorgewählt — er macht den grössten Teil des Sortiments aus, und wer
   etwas anderes sucht, klickt einmal. Ohne Vorauswahl beginnt jeder Besuch mit einer
   Liste, in der Schaumwein, Süsswein und „unbekannt" dazwischenliegen. Ein Klick auf
   „Rotwein" hebt die Vorauswahl wieder auf. */
const STANDARD_SORTE = "rot";
/* "alle" = beide Welten, "ch" = nur Schweizer Handel, "mp" = nur Vivino-Marktplatz.
   Vorgewählt sind beide: der Marktplatz liefert in die Schweiz und gehört damit zur
   Auswahl. Damit die gemeinsame Liste vergleichbar bleibt, wird in dieser Ansicht
   die über beide Welten gerechnete Preis-Leistungs-Zahl verwendet — siehe
   valueOf(). */
const STANDARD_QUELLE = "alle";
/* Die Standardauswahl beantwortet die häufigste Frage: ein guter Rotwein für den
   Alltag. Ohne Grenzen eröffnet die Liste mit Flaschen zu dreihundert Franken und
   mit Weinen, die niemand bewertet hat. Ein Klick hebt jede dieser Grenzen auf.

   Note ab 4.2, nicht ab 4.0: eine 4.1 ist die häufigste Note im Bestand und damit
   glattes Mittelfeld. Ab 4.2 beginnt das obere Drittel — das ist die Schwelle, ab
   der sich das Hinschauen lohnt. */
const STANDARD_NOTE = 4.2;
const STANDARD_PREIS = 50;
const TYP_ORDNUNG = D.typen.map(t => t.key);
const S = { run: D.runs[0].id, mat: new Set(), style: new Set([STANDARD_SORTE]),
            typ: new Set(),
            shop: new Set(), land: new Set(), src: STANDARD_QUELLE, q: "",
            /* Standard ist Preis-Leistung: „welche Flasche lohnt sich" ist die Frage,
               für die es die Seite gibt. Nach Note allein eröffnete die Liste mit den
               teuersten Flaschen. */
            sort: "value", dir: -1, minRating: STANDARD_NOTE, maxPrice: STANDARD_PREIS,
            onlyBargain: false, hideGrapes: new Set(), noVivino: false,
            onlyFound: false, onlyNeu: false, limit: PAGE };
const esc = s => String(s ?? "").replace(/[&<>"']/g, c =>
  ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
/* Null ist kein Preis. Weine, deren Preisbasis unsicher blieb, kommen ohne Betrag
   in den Bericht — als "CHF 0.00" gedruckt las sich das wie ein Gratisangebot.
   Ein Strich sagt, was gemeint ist: hier steht keine belastbare Zahl. */
const chf = v => (v == null || v === 0) ? "—" : "CHF " + Number(v).toFixed(2)
  .replace(/\B(?=(\d{3})+(?!\d))/, "'");
/* Die Händlernamen tragen den Jahrgang meist schon in sich ("Pomerol AOC 2007
   Château Lafleur"). Ihn dann noch anzuhängen, druckt ihn zweimal — bei den
   allermeisten Weinen. Nur anhängen, wenn er im Namen fehlt. */
/* Für die Etiketten im Diagramm: die ersten Wörter genügen, der Tooltip hat den Rest. */
const kurz = n => { const w = String(n).split(" ");
  return w.slice(0, 3).join(" ") + (w.length > 3 ? "…" : ""); };
/* Dieselbe Regel wie im Diagramm: ab Note 4.2 und bis CHF 20, nur dieser Bereich. */
const istGut = w => w.rating != null && w.rating >= D.good.rating
  && w.price > 0 && w.price <= D.good.price;
const vintageSuffix = w => (w.vintage && !String(w.name).includes(String(w.vintage)))
  ? " " + w.vintage : "";
/* Der Wert, nach dem standardmässig sortiert wird, muss auch dastehen — sonst ist die
   Reihenfolge nicht nachvollziehbar. 0 heisst „genau im Preisniveau". */
/* Zwei Preis-Leistungs-Zahlen liegen bereit: eine je Warenwelt, eine über beide.
   Zeigt die Seite nur eine Welt, gilt deren eigene — sie misst "gut für einen
   Schweizer Ladenwein" bzw. "gut für einen Marktplatzwein". Stehen beide Welten in
   derselben Liste, muss die gemeinsame gelten, sonst würden zwei Zahlen sortiert,
   die nicht dasselbe messen. */
const valueOf = w => (S.src === "alle" ? w.valueScoreAll : w.valueScore);
/* Die Abnahmemenge gehört zum Preis. Der Betrag je Flasche ist bei einer Kiste richtig
   gerechnet und vergleichbar — kaufen kann man die Flasche einzeln aber nicht.
   Gemeldet mit den Worten „preis finde ich nicht": Pio Cesare Barolo 2016 stand mit
   CHF 45.47 da, zu haben ist er nur als Sechserkiste zu CHF 272.82. 7 Prozent der
   Marktplatzangebote sind Kisten. */
const gebindeText = w => (w.units > 1)
  ? `nur ${w.units}er-Gebinde, zusammen ${chf(w.price * w.units)}` : "";
const valueText = w => {
  if (valueOf(w) == null) return '<span class="meta">—</span>';
  const v = valueOf(w);
  return (v > 0 ? "+" : v < 0 ? "−" : "±") + Math.abs(v).toFixed(2);
};
/* Wogegen gerechnet wurde. Ohne diese Angabe sieht die Zahl willkuerlich aus:
   gemeldet an zwei Weinen mit derselben Note 4.4, bei denen der teurere die bessere
   Preis-Leistung trug. Beide richtig gerechnet — nur gegen verschiedene Gruppen:
   CHF 27 gegen fruchtsuesse Rote mit einem Schnitt von CHF 18.42, CHF 28.50 gegen
   straffe Rioja mit CHF 24.68. Der zweite ist relativ zu seinesgleichen guenstiger. */
const EBENEN = { region: "Region", sorte: "Sorte", typ: "Typ", gesamt: "alle Weine" };
const valueBezug = w => {
  const b = (S.src === "alle" ? w.valueScoreAllBezug : w.valueScoreBezug);
  if (!b || !b.n) return "";
  const wo = EBENEN[b.ebene] || "vergleichbare";
  return `gegen ${b.n} vergleichbare (${wo}), Ø CHF ${Number(b.preis).toFixed(2)} · Ø Note ${Number(b.note).toFixed(2)}`;
};

function currentRun() { return D.runs.find(r => r.id === S.run) || D.runs[0]; }

/* ``ausser`` blendet **eine** Filtergruppe aus. Gebraucht wird das, um zu zählen,
   was eine Kachel dieser Gruppe brächte: für die Frage „wie viele Rotweine gäbe es"
   darf die Sortenauswahl selbst nicht mitzählen, sonst käme bei jeder nicht
   gewählten Sorte null heraus und die ganze Reihe verschwände nach dem ersten
   Klick. Alle anderen Filter zählen sehr wohl — genau das macht die Zahl nützlich. */
function visible(ausser) {
  const q = S.q.trim().toLowerCase();
  return currentRun().wines.filter(w => {
    if (ausser !== "mat" && S.mat.size && !S.mat.has(w.maturity || "?")) return false;
    if (ausser !== "style" && S.style.size && !S.style.has(w.style || "?")) return false;
    if (ausser !== "typ" && S.typ.size && !S.typ.has(w.typ || "?")) return false;
    /* Die beiden Warenwelten werden nie gemeinsam gezeigt: ihre Preis-Leistungs-
       Zahlen stammen aus getrennten Regressionen und sind untereinander nicht
       vergleichbar. */
    if (ausser !== "src" && S.src === "ch" && !w.swiss) return false;
    if (ausser !== "src" && S.src === "mp" && !w.marketplace) return false;
    if (ausser !== "shop" && S.shop.size && !w.retailers.some(r => S.shop.has(r))) return false;
    if (ausser !== "land" && S.land.size && !S.land.has(w.country || "")) return false;
    // Der bei Vivino gefundene Name gehört in die Suche. Händler benennen Weine oft
    // ohne den Produzenten: Mövenpick führt „Mendoza 2021 Chardonnay Alta Angelica
    // Zapata", Vivino „Catena Zapata Angélica Zapata Chardonnay Alta". Wer nach
    // „Catena" sucht — dem Namen, unter dem das Weingut bekannt ist — fand nichts,
    // obwohl der Wein zugeordnet war.
    if (q) {
      const heu = (w.name + " " + (w.maturityRegion || "") + " " + (w.matchedName || "")
                   + " " + (w.styleLabel || "")).toLowerCase();
      if (!heu.includes(q)) return false;
    }
    // Spaltenfilter greifen hier, nicht erst in der Tabelle: sonst zeigen Diagramm,
    // Zähler und Tabelle drei verschiedene Mengen, und man weiss nicht, welche gilt.
    if (S.minRating != null && !(w.rating != null && w.rating >= S.minRating)) return false;
    if (S.maxPrice != null && !(w.price != null && w.price <= S.maxPrice)) return false;
    if (S.onlyBargain && !(w.bargain != null && w.bargain > 0)) return false;
    if (S.hideGrapes.size && (w.grapes || []).some(g => S.hideGrapes.has(g))) return false;
    if (S.noVivino && w.cheapest === "vivinoshop") return false;
    // "Bei Vivino gefunden" heisst: bestätigter Namensabgleich. Nicht dabei sind
    // fuzzy-Treffer (Name passt nur ungefähr), Produzenten-Mittelwerte und die
    // Weine ohne Eintrag. Das sind genau die gefüllten Punkte im Diagramm.
    if (S.onlyFound && !(w.rating != null && !w.fuzzy)) return false;
    // "neu" heisst: stand im Vorlauf nicht da. Ohne Vorlauf ist das Feld an keinem
    // Wein gesetzt, und der Filter wird darum auch nicht angeboten.
    if (S.onlyNeu && !w.neu) return false;
    return true;
  });
}

/* ---------------------------------------------------------------- Diagramm */
function chart(list) {
  const pts = list.filter(w => w.rating != null && w.price > 0);
  const box = document.getElementById("chart");
  const card = document.querySelector(".chart");
  // Passt kein Wein zur Auswahl, hat das Diagramm nichts zu sagen — dann ganz weg.
  // Vorher stand hier "Die Tabelle zeigt alle", während die Tabelle leer war.
  // Der Leerzustand gehört an eine Stelle, nicht an zwei widersprechende.
  card.hidden = list.length === 0;
  if (list.length === 0) return;
  if (pts.length < 2) {
    box.innerHTML = '<p class="empty">' +
      (pts.length ? "Nur ein Wein mit Vivino-Note — siehe Tabelle."
                  : "Kein Wein dieser Auswahl hat eine Vivino-Note. Die Tabelle "
                    + "zeigt sie trotzdem, mit Preis und Händler.") +
      "</p>";
    return;
  }
  const W = 900, H = 460, L = 52, R = 16, T = 30, B = 46;
  const pw = W - L - R, ph = H - T - B;
  const xs = pts.map(p => Math.log10(p.price));
  const x0 = Math.min(...xs) - .05, x1 = Math.max(...xs) + .05;
  const ys = pts.map(p => p.rating);
  const y0 = Math.max(1, Math.min(...ys) - .1), y1 = Math.min(5, Math.max(...ys) + .1);
  const sx = v => L + (Math.log10(v) - x0) / (x1 - x0 || 1) * pw;
  const sy = v => T + (1 - (v - y0) / (y1 - y0 || 1)) * ph;

  let g = "";
  for (const v of [3,5,7,10,15,20,30,50,75,100,150,200,300,500,800]) {
    if (Math.log10(v) < x0 || Math.log10(v) > x1) continue;
    g += `<line class="grid" x1="${sx(v)}" y1="${T}" x2="${sx(v)}" y2="${T+ph}"/>`
       + `<text class="tick" x="${sx(v)}" y="${T+ph+17}" text-anchor="middle">${v}</text>`;
  }
  for (let i = 0; i <= 4; i++) {
    const v = y0 + i * (y1 - y0) / 4;
    g += `<line class="grid" x1="${L}" y1="${sy(v)}" x2="${L+pw}" y2="${sy(v)}"/>`
       + `<text class="tick" x="${L-7}" y="${sy(v)+4}" text-anchor="end">${v.toFixed(1)}</text>`;
  }
  /* Trendlinie: die Note, die man für diesen Preis üblicherweise bekommt. Aus dem
     Lauf geschätzt, nicht geraten — dieselbe Regression, aus der der
     Preis-Leistungs-Wert kommt. */
  const fit = (() => {
    const lx = pts.map(p => Math.log10(p.price)), ly = pts.map(p => p.rating);
    const n = lx.length, mx = lx.reduce((s, v) => s + v, 0) / n,
          my = ly.reduce((s, v) => s + v, 0) / n;
    const sxx = lx.reduce((s, x) => s + (x - mx) ** 2, 0);
    if (!sxx) return null;
    const bb = lx.reduce((s, x, i) => s + (x - mx) * (ly[i] - my), 0) / sxx;
    return { a: my - bb * mx, b: bb };
  })();
  const erwartet = v => fit ? fit.a + fit.b * Math.log10(v) : null;

  /* Das markierte Feld ist eine feste Regel: ab Note 4.2 und bis CHF 20, nur dieser
     Bereich. Als Rechteck, weil die Regel absolut ist — nicht als Fläche über der
     Trendlinie: „besser als üblich fürs Geld" trifft auch eine mittelmässige Flasche
     für CHF 8. Die Regel ist eng; ist das Feld leer, sagt es das selbst. */
  const gRating = D.good.rating, gPrice = D.good.price;
  const gut = p => p.rating >= gRating && p.price > 0 && p.price <= gPrice;
  const imFeld = pts.filter(gut);
  const zx = Math.min(L + pw, Math.max(L, sx(gPrice)));
  const zy = Math.min(T + ph, Math.max(T, sy(gRating)));
  const zone = (zx > L + 4 && zy > T + 4)
    ? `<rect class="zone" x="${L}" y="${T}" width="${(zx - L).toFixed(1)}" height="${(zy - T).toFixed(1)}"/>`
      + `<path class="zone-edge" d="M ${L} ${zy.toFixed(1)} L ${zx.toFixed(1)} ${zy.toFixed(1)} L ${zx.toFixed(1)} ${T}"/>`
      + `<text class="zone-t" x="${L + 8}" y="${T + 16}">GUT UND GÜNSTIG</text>`
      + `<text class="zone-s" x="${L + 8}" y="${T + 29}">ab Note ${gRating.toFixed(1)} · bis CHF ${gPrice.toFixed(0)}</text>`
      + `<text class="zone-s" x="${L + 8}" y="${(zy - 9).toFixed(1)}">${imFeld.length} von ${pts.length} Weinen</text>`
    : "";

  const trend = fit
    ? `<line class="trend" x1="${sx(Math.pow(10, x0)).toFixed(1)}" y1="${sy(erwartet(Math.pow(10, x0))).toFixed(1)}"`
      + ` x2="${sx(Math.pow(10, x1)).toFixed(1)}" y2="${sy(erwartet(Math.pow(10, x1))).toFixed(1)}"/>`
    : "";

  /* Nur der Punkt. Die Striche zur Trendlinie standen bei 174 Weinen so dicht, dass
     sie das Feld zugezogen haben — die Abweichung liest man am Abstand zur Linie
     ohnehin ab, und als Zahl steht sie in der Tabelle. Weine im markierten Feld sind
     gefüllt und golden, alle anderen hohl und leise; die Kennung hängt nicht an der
     Farbe allein, das Feld ist beschriftet. */
  const circles = pts.map((p, i) => {
    const cls = (gut(p) ? " good" : "") + (p.typ ? " t-" + p.typ : "");
    const x = sx(p.price).toFixed(1), y = sy(p.rating).toFixed(1);
    /* Ein unsichtbarer Trefferkreis vor jedem Punkt. Zwei Gründe: hohle Punkte haben
       `fill:none`, und damit ist ihre Fläche in SVG nicht anklickbar — es reagierte
       nur die 1 px dünne Kontur. Und mit r=10 ist das Ziel auch mit dem Finger
       oder einer unruhigen Hand erreichbar. */
    return `<circle class="hit" data-i="${i}" cx="${x}" cy="${y}" r="10"/>`
      + `<circle class="pt${cls}" cx="${x}" cy="${y}" r="4"/>`;
  }).join("");

  /* Benannt werden die Weine, die die Regel erfüllen — sie sind der Punkt der
     Markierung. Die Etiketten sitzen rechts der Zonenkante, damit sie deren
     Beschriftung nicht überschreiben, und gestaffelt gegen sich selbst. */
  const labels = imFeld.slice(0, 4).map((p, i) => {
    const ax = sx(p.price), ay = sy(p.rating);
    const tx = zx + 20, ty = T + 26 + i * 16;
    return `<path class="lead" d="M ${(ax + 5).toFixed(1)} ${ay.toFixed(1)} L ${(zx + 9).toFixed(1)} ${ty.toFixed(1)} L ${tx.toFixed(1)} ${ty.toFixed(1)}"/>`
      + `<text class="lead-t" x="${(tx + 3).toFixed(1)}" y="${(ty + 3.5).toFixed(1)}">${esc(kurz(p.name))}`
      + ` <tspan fill="var(--goldtx)">${p.rating.toFixed(1)} · ${chf(p.price)}</tspan></text>`;
  }).join("");

  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img"
      aria-label="Vivino-Note gegen Preis, ${pts.length} Weine. Eine Trendlinie zeigt die Note, die für diesen Preis üblich ist. Markiert ist der Bereich ab Note ${gRating.toFixed(1)} bis CHF ${gPrice.toFixed(0)}: ${imFeld.length} von ${pts.length} Weinen.">
    ${zone}${g}
    <line class="axis" x1="${L}" y1="${T+ph}" x2="${L}" y2="${T}"/>
    <line class="axis" x1="${L}" y1="${T+ph}" x2="${L+pw}" y2="${T+ph}"/>
    <text class="alabel" x="${L+pw/2}" y="${H-8}" text-anchor="middle">Preis pro 75 cl inkl. MwSt (CHF, logarithmisch)</text>
    <text class="alabel" transform="rotate(-90 14 ${T+ph/2})" x="14" y="${T+ph/2}" text-anchor="middle">Vivino-Note (1–5)</text>
    ${trend}<g id="pts">${circles}</g>${labels}</svg>`;

  const tip = document.getElementById("tip"), host = box.querySelector("#pts");
  /* Gerenderte Lage je Punkt, um Häufungen zu finden. Ein kleinerer Radius löst das
     Problem nicht — die Punkte liegen in den Daten aufeinander, nicht bloss optisch.
     Erreichbar werden die verdeckten nur, wenn der Tooltip sie mitnennt. */
  const at = pts.map(p => ({ x: +sx(p.price).toFixed(1), y: +sy(p.rating).toFixed(1) }));
  const clusterOf = i => pts
    .map((_, j) => j)
    .filter(j => Math.abs(at[j].x - at[i].x) <= 5 && Math.abs(at[j].y - at[i].y) <= 5);
  const show = (el, ev) => {
    const i = +el.dataset.i, p = pts[i]; if (!p) return;
    const cluster = clusterOf(i).filter(j => j !== i);
    let h = `<span class="n">${esc(p.name)}${vintageSuffix(p)}</span>` + detailRows(p);
    // Verdeckte Nachbarn benennen, sonst weiss man nicht, dass sie da sind.
    if (cluster.length) {
      h += `<div class="also"><b>${cluster.length} weitere${cluster.length === 1 ? "r" : ""}`
        + ` Wein${cluster.length === 1 ? "" : "e"} an dieser Stelle</b>`
        + cluster.slice(0, 4).map(j => {
            const o = pts[j];
            return `<div class="r"><span>${esc(o.name).slice(0, 38)}</span>`
              + `<span class="k">${o.rating.toFixed(1)} · ${chf(o.price)}</span></div>`;
          }).join("")
        + (cluster.length > 4
            ? `<div class="k">… und ${cluster.length - 4} weitere — in der Tabelle</div>`
            : "")
        + `</div>`;
    }
    tip.innerHTML = h; tip.classList.add("on"); place(ev);
  };
  const place = ev => {
    const m = 14, w = tip.offsetWidth, h = tip.offsetHeight;
    let x = ev.clientX + m, y = ev.clientY + m;
    if (x + w > innerWidth - 8) x = ev.clientX - w - m;
    if (y + h > innerHeight - 8) y = ev.clientY - h - m;
    tip.style.left = Math.max(8, x) + "px"; tip.style.top = Math.max(8, y) + "px";
  };
  /* Über data-i statt über die Klasse: so greift es am Trefferkreis wie am Punkt. */
  const treffer = e => e.target.closest && e.target.closest("[data-i]");
  host.addEventListener("mouseover", e => { const el = treffer(e); if (el) show(el, e); });
  host.addEventListener("mousemove", e => { if (tip.classList.contains("on")) place(e); });
  host.addEventListener("mouseout", () => tip.classList.remove("on"));
  /* Auf Touch gibt es kein Hover. Zwischen 721 und 900 px ist das Diagramm sichtbar
     — dort waren die Tooltips bisher unerreichbar, weil nur Maus-Ereignisse hingen.
     Erstes Antippen zeigt den Wein, zweites Antippen öffnet ihn. */
  let armed = null;
  host.addEventListener("click", e => {
    const el = treffer(e); if (!el) return;
    const p = pts[+el.dataset.i];
    const touch = !matchMedia("(hover: hover)").matches;
    if (touch && armed !== el) {
      armed = el;
      show(el, e.touches ? e.touches[0] : e);
      return;
    }
    armed = null;
    const href = p && (p.url || p.vivinoUrl);
    if (href) window.open(href, "_blank", "noopener");
  });
  // Tippen daneben schliesst den Tooltip wieder.
  addEventListener("pointerdown", e => {
    if (!treffer(e)) {
      armed = null; tip.classList.remove("on");
    }
  }, { passive: true });
}


/* Grob prüfen, ob Händler- und Fundname dasselbe sagen — dann ist die Zeile nur
   Wiederholung. Verglichen werden die Wörter, nicht die Zeichenfolge. */
function sameWine(a, b) {
  const w = t => new Set(String(t || "").toLowerCase()
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9 ]+/g, " ").split(/\s+/).filter(x => x.length > 2));
  const A = w(a), B = w(b);
  if (!A.size || !B.size) return false;
  let n = 0; B.forEach(x => { if (A.has(x)) n++; });
  return n === B.size;
}
/* ----------------------------------------------------------------- Tabelle */
/* Wer hatte den Fokus, bevor die Tabelle neu gebaut wurde?
   ``box.innerHTML = …`` entfernt das fokussierte Element aus dem Dokument, und der
   Fokus fällt auf ``BODY`` — gemessen beim Sortieren und beim Nachladen. Sichtbar ist
   das nicht, für die Tastatur ist es der Abbruch: bei 1473 Weinen und 50 je Seite wird
   „Weitere anzeigen" bis zu 29 Mal gedrückt, und jedes Mal beginnt der Weg wieder am
   Dokumentanfang über 159 fokussierbare Elemente.

   Die Filterkacheln lösen dasselbe Problem seit je über ``data-chip`` — hier dieselbe
   Idee mit dem Sortierschlüssel beziehungsweise der Kennung des Knopfes. */
function fokusMerken(box) {
  const a = document.activeElement;
  if (!a || !box.contains(a)) return null;
  if (a.classList.contains("sortbtn")) return { art: "sort", col: a.dataset.col };
  if (a.id === "more") return { art: "more" };
  return null;
}

function fokusZurueck(box, merk) {
  if (!merk) return;
  if (merk.art === "sort") {
    const b = box.querySelector(`.sortbtn[data-col="${CSS.escape(merk.col)}"]`);
    if (b) b.focus();
    return;
  }
  // Nach dem letzten Nachladen ist der Knopf weg. Dann den Absatz an seiner Stelle
  // fokussieren: der Fokus bleibt, wo er war, und die Meldung „Alle N angezeigt" wird
  // gelesen, statt dass beides stillschweigend verschwindet.
  const b = box.querySelector("#more") || box.querySelector(".more");
  if (b) { if (!b.hasAttribute("tabindex")) b.setAttribute("tabindex", "-1"); b.focus(); }
}

/* Die Angaben zu einem Wein, an einer Stelle.
   Vorher standen sie nur im Mouseover des Diagramms — und den gibt es auf dem Handy
   nicht, wo das Diagramm ohnehin ausgeblendet ist. Damit war ausgerechnet auf dem
   Geraet, mit dem man im Laden steht, weder die Machart noch die Region, die
   Trinkreife-Grundlage, die Vergleichsgruppe der Preis-Leistungs-Zahl noch die
   Warnung "laut Vivino, nicht beim Verkaeufer geprueft" zu sehen.
   Eine Funktion fuer beide Ausgaben: zwei Fassungen derselben Angaben laufen in
   diesem Projekt erfahrungsgemaess auseinander. */
function detailRows(p) {
  const row = (k, v) => `<div class="r"><span class="k">${k}</span><span>${v}</span></div>`;
  let h = "";
  h += row("Vivino", p.rating.toFixed(1) + "/5" + (p.ratingCount ? ` (${p.ratingCount})` : ""));
  if (p.fuzzy) h += row("Achtung", `<span class="warn">Namensabgleich unbestätigt`
    + (p.matchedName ? ` — gefunden: „${esc(p.matchedName)}"` : "") + `</span>`);
  if (p.styleLabel) h += row("Sorte", esc(p.styleLabel));
  if (p.typLabel && p.typ) h += row("Typ", esc(p.typLabel)
    + (p.typWarum ? ` <span class="meta">${esc(p.typWarum)}</span>` : ""));
  /* Die Region ist die feinste Ebene der Preis-Leistungs-Rechnung: ein Bordeaux
     für CHF 10 wird gegen Bordeaux gerechnet, nicht gegen alle kräftigen Roten.
     Die Spanne daneben ist ein Erfahrungswert und geht in keine Zahl ein — sie
     ordnet nur ein, wo der Preis dieser Flasche in ihrer Herkunft liegt. */
  if (p.regionLabel) h += row("Region", esc(p.regionLabel)
    + (p.regionSpanne ? ` <span class="meta">üblich CHF ${esc(p.regionSpanne)}</span>` : ""));
  if (p.maturityShort) {
    /* Woher die Auskunft stammt, gehört daneben — sonst liest sich die Vinum-Zeile
       wie eine Aussage über genau diesen Wein, obwohl sie für eine ganze Region
       gilt. Vivinos Fenster ist jahrgangsgenau und steht in Klammern dahinter. */
    let m = "<b>" + esc(p.maturityShort) + "</b>";
    if (p.drinkWindow) m += ` <span class="meta">Vivino ${esc(p.drinkWindow)}</span>`;
    h += row("Trinkreife", m);
    if (p.maturityRegion) h += row("Grundlage", `<span class="meta">${esc(p.maturityRegion)}</span>`);
    /* Sind sich die beiden Quellen uneinig, steht das da. Beide behalten ihre
       Stimme; wer es liest, entscheidet selbst. Das ist mehr wert, als wenn eine
       von beiden stillschweigend gewinnt. */
    if (p.maturityConflict) h += row("uneinig", `<span class="warn">${esc(p.maturityConflict)}</span>`);
  }
  if (valueOf(p) != null) h += row("Preis-Leistung", valueText(p)
    + (valueBezug(p) ? ` <span class="meta">${esc(valueBezug(p))}</span>` : ""));
  h += row("Preis/75cl", chf(p.price));
  if (gebindeText(p)) h += row("Abnahme", `<span class="warn">${esc(gebindeText(p))}</span>`);
  /* Beim Marktplatz gehört die Herkunft des Preises dazu: Vivino vermittelt, verkauft
     wird von Dritten, und der Betrag stammt aus Vivinos Angebotsdaten. In einer
     Stichprobe von zwölf stand er bei vier nicht auf der Verkäuferseite. Hier im
     Tooltip und nicht in der Zeile — 625 von 1459 Weinen betrifft es, in der Liste
     wäre es Rauschen, beim Nachsehen ist es die Antwort. */
  if (p.cheapest === "vivinoshop")
    h += row("Preisquelle", `<span class="warn">laut Vivino, nicht beim Verkäufer geprüft</span>`);
  h += row("Händler", esc((D.retailers.find(r => r.key === p.cheapest) || {}).name || p.cheapest));
  if (p.bargain != null) {
    const c = p.bargain > 0 ? "good" : "bad";
    h += row("gegen Markt", `<span class="${c}">${p.bargain > 0 ? "−" : "+"}`
      + Math.abs(p.bargain).toFixed(0) + "%</span>");
  }
  if (p.falstaff != null) h += row("Falstaff", p.falstaff.toFixed(0) + "/100");
  return h;
}

function table(list) {
  const box = document.getElementById("table");
  /* Einmal verdrahtet, nicht bei jedem Neuzeichnen: table() laeuft bei jeder
     Filteraenderung, und die Zuhoerer wuerden sich sonst stapeln. Der Kasten selbst
     bleibt bestehen, nur sein Inhalt wird ersetzt — darum haelt das Merkmal. */
  if (!box.dataset.wired) {
    box.dataset.wired = "1";
    box.addEventListener("click", e => {
      const b = e.target.closest(".mehr");
      if (!b) return;
      const det = document.getElementById(b.getAttribute("aria-controls"));
      if (!det) return;
      const offen = b.getAttribute("aria-expanded") === "true";
      b.setAttribute("aria-expanded", String(!offen));
      det.hidden = offen;
    });
  }
  const merk = fokusMerken(box);
  if (!list.length) { box.innerHTML = '<p class="empty">Kein Wein passt zu dieser Auswahl.</p>'; return; }
  const shopName = k => (D.retailers.find(r => r.key === k) || {}).name || k;
  /* Beim Vivino-Marktplatz ist Vivino nicht der Verkaeufer, sondern der Vermittler:
     der Link fuehrt bewusst zum Shop, der tatsaechlich liefert, weil nur dort der
     genannte Preis steht. Dann darf die Beschriftung nicht "Vivino Aktionen" sagen —
     wer klickt, landet auf bignens.ch und haelt den Link fuer kaputt. Steht der Shop
     in der Adresse, wird er angeschrieben. */
  const linkZiel = w => {
    const name = shopName(w.cheapest);
    let host = "";
    try { host = new URL(w.url).hostname.replace(/^www\./, ""); } catch (e) { host = ""; }
    if (!host) return name;
    const eigen = (D.retailers.find(r => r.key === w.cheapest) || {}).domain || "";
    if (eigen && (host === eigen || host.endsWith("." + eigen))) return name;
    return `${name} → ${host}`;
  };
  // Leere Werte sortieren immer nach unten, in beiden Richtungen. Ein Wein ohne Note
  // ist keine 0 — er würde sonst bei aufsteigender Sortierung die Liste anführen.
  const KEYS = {
    name:    w => (w.name || "").toLowerCase(),
    rating:  w => w.rating,
    price:   w => w.price,
    shop:    w => shopName(w.cheapest).toLowerCase(),
    bargain: w => w.bargain,
    value:   w => valueOf(w),
    /* Sortiert wird nach der Achsenposition, nicht alphabetisch: "Ausgewogen" gehoert
       zwischen "Weich & modern" und "Straff & herb", nicht an den Anfang. */
    typ:     w => (w.typ ? TYP_ORDNUNG.indexOf(w.typ) : 99),
  };
  const key = KEYS[S.sort] || KEYS.value;
  const sorted = list.slice().sort((a, b) => {
    const x = key(a), y = key(b);
    const xe = x == null || x === "", ye = y == null || y === "";
    if (xe && ye) return 0;
    if (xe) return 1;
    if (ye) return -1;
    if (typeof x === "string") return S.dir * x.localeCompare(y, "de");
    return S.dir * (x - y);
  });
  const rows = sorted.slice(0, S.limit).map((w, i) => {
    const vivino = w.rating != null
      ? `<a href="${esc(w.vivinoUrl)}" target="_blank" rel="noopener">${w.rating.toFixed(1)}/5</a>`
        + (w.ratingCount ? ` <span class="meta">(${w.ratingCount})</span>` : "")
        + (w.fuzzy ? ` <span class="warn" title="Namensabgleich unbestätigt">?</span>` : "")
        // Den gefundenen Namen ausschreiben, wenn er vom Händlernamen abweicht.
        // Ein Tooltip genügt dafür nicht: auf dem Handy gibt es kein Hover, und ohne
        // den Namen ist nicht nachprüfbar, welcher Vivino-Wein gemeint ist — genau
        // die Frage, die man bei einem "?" als Erstes hat.
        + (w.matchedName && !sameWine(w.name, w.matchedName)
            ? `<br><span class="matched">→ ${esc(w.matchedName)}</span>` : "")
      : w.wineryRating != null
        ? `<a href="${esc(w.vivinoUrl)}" target="_blank" rel="noopener" class="meta">nur Produzenten-Ø `
          + w.wineryRating.toFixed(1) + "/5</a>"
        : `<a href="${esc(w.vivinoUrl)}" target="_blank" rel="noopener" class="meta">keine Note</a>`;
    const bargain = w.bargain == null ? '<span class="meta">—</span>'
      : `<span class="${w.bargain > 0 ? "good" : "bad"}">${w.bargain > 0 ? "−" : "+"}`
        + Math.abs(w.bargain).toFixed(0) + "%</span>";
    const shop = w.url ? `<a href="${esc(w.url)}" target="_blank" rel="noopener">${esc(linkZiel(w))}</a>`
                       : esc(shopName(w.cheapest));
    const vs = vintageSuffix(w);
    /* Jede Zeile laesst sich aufklappen. Die Angaben dahinter — Machart, Region,
       Grundlage der Trinkreife, Vergleichsgruppe der Preis-Leistungs-Zahl, Herkunft
       des Preises — standen vorher nur im Mouseover des Diagramms. Auf dem Handy ist
       das Diagramm ausgeblendet und Hover gibt es nicht: dort war nichts davon
       erreichbar, ausgerechnet auf dem Geraet, mit dem man im Laden steht. */
    const id = `det-${i}`;
    return `<tr>
      <td data-l="Wein"><span class="wine">${esc(w.name)}</span>
        ${vs ? `<span class="meta">${vs}</span>` : ""}
        ${w.styleLabel || w.maturityShort || w.neu ? "<br>" : ""}
        ${w.neu ? `<span class="pill neu">neu</span>` : ""}
        ${w.styleLabel ? `<span class="pill">${esc(w.styleLabel)}</span>` : ""}
        ${w.typ && w.typLabel ? `<span class="pill t-${w.typ}" title="${esc(w.typWarum)}">`
            + esc(w.typLabel) + `</span>` : ""}
        ${w.maturityShort ? `<span class="pill">${esc(w.maturityShort)}</span>` : ""}
        ${istGut(w) ? `<br><span class="marker">◆ gut und günstig</span>` : ""}</td>
      <td data-l="Preis-Leistung" class="pl${valueOf(w) == null ? " noval" : ""}${
        (valueOf(w) ?? 0) < 0 ? " neg" : ""}">${valueText(w)}</td>
      <td data-l="Vivino">${vivino}</td>
      <td data-l="Preis/75cl" class="num">${chf(w.price)}${
        gebindeText(w) ? `<br><span class="gebinde">${esc(gebindeText(w))}</span>` : ""}</td>
      <td data-l="Wo kaufen">${shop}</td>
      <td data-l="gegen Markt" class="num${w.bargain == null ? " noval" : ""}">${bargain}</td>
      <td class="mehrzelle"><button class="mehr" type="button" aria-expanded="false"
          aria-controls="${id}"><span class="sr">Details zu ${esc(w.name)}</span></button></td>
    </tr>
    <tr class="det" id="${id}" hidden><td colspan="7">${detailRows(w)}</td></tr>`;
  }).join("");
  const COLS = [
    ["name", "Wein", ""], ["value", "Preis-Leistung", "num"], ["rating", "Vivino", ""],
    ["price", "Preis/75cl", "num"], ["shop", "Wo kaufen", ""],
    ["bargain", "gegen Markt", "num"],
  ];
  /* ``aria-sort`` am Spaltenkopf, nicht nur der Pfeil im Text.
     Vorher trug der Knopf ein festes ``aria-label="Nach X sortieren"``. Das war doppelt
     schädlich: es sagte den Zustand nicht — welche Spalte sortiert, in welcher Richtung —
     und es *überschrieb* als zugänglicher Name den Textinhalt, sodass der Pfeil auch
     nicht vorgelesen wurde. Gehört hat man „Nach Preis-Leistung sortieren, Schaltfläche"
     und damit nichts über die Reihenfolge, die die Seite gerade zeigt.

     Jetzt: der sichtbare Text ist der Name, der Pfeil ist für die Ausgabe verborgen
     (er ist Dekoration derselben Aussage), und der Zustand steht als ``aria-sort`` am
     ``th`` — die Standardform für sortierbare Tabellen. ``scope`` dazu: bei einer
     einzeiligen Kopfzeile leiten Browser es her, geschrieben veraltet es nicht. */
  const head = COLS.map(([k, label, cls]) => {
    const on = S.sort === k;
    const richtung = on ? (S.dir < 0 ? "descending" : "ascending") : "none";
    const arrow = on ? ` <span aria-hidden="true">${S.dir < 0 ? "▾" : "▴"}</span>` : "";
    return `<th class="${cls}${on ? " sorted" : ""}" scope="col" aria-sort="${richtung}">`
      + `<button type="button" class="sortbtn" data-col="${k}">${esc(label)}${arrow}</button></th>`;
  }).join("");
  const rest = sorted.length - S.limit;
  box.innerHTML = `<table><thead><tr>${head}<th class="mehrzelle" scope="col">`
    + `<span class="sr">Details</span></th></tr></thead><tbody>${rows}</tbody></table>`
    + (rest > 0
        ? `<p class="more"><button type="button" id="more">Weitere ${Math.min(rest, PAGE)} anzeigen</button>`
          + `<span class="meta"> ${S.limit} von ${sorted.length} angezeigt</span></p>`
        : sorted.length > PAGE
          ? `<p class="more"><span class="meta">Alle ${sorted.length} angezeigt</span></p>`
          : "");
  const more = box.querySelector("#more");
  // Nur nachladen, nicht neu filtern: der Blick soll nicht nach oben springen.
  if (more) more.addEventListener("click", () => { S.limit += PAGE; table(list); });

  box.querySelectorAll(".sortbtn").forEach(b => b.addEventListener("click", () => {
    const col = b.dataset.col;
    // Gleiche Spalte nochmal = Richtung wechseln. Neue Spalte startet in der
    // Richtung, die man dort erwartet: Text A→Z, Zahlen gross→klein.
    if (S.sort === col) S.dir = -S.dir;
    else { S.sort = col; S.dir = (col === "name" || col === "shop") ? 1 : -1; }
    syncSort();
    render();
  }));

  fokusZurueck(box, merk);
}

/* ------------------------------------------------------------------ Filter */
/* Ändert sich die Auswahl, beginnt die Liste wieder bei der ersten Seite — sonst
   stehen nach einem Filterwechsel mehrere Hundert Zeilen einer anderen Menge da. */
function refilter() { S.limit = PAGE; render(); }

function chip(label, pressed, onClick, extra = "", anzahl = null) {
  const b = document.createElement("button");
  b.type = "button"; b.className = "chip"; b.setAttribute("aria-pressed", String(pressed));
  b.innerHTML = extra + esc(label)
    + (anzahl != null ? ` <span class="n">${anzahl}</span>` : "");
  /* Die Kennung überlebt den Neuaufbau der Reihe und trägt den Fokus zurück. */
  b.dataset.chip = label;
  b.addEventListener("click", () => { onClick(); refilter(); });
  return b;
}

/* Wie viele Weine brächte jede Kachel einer Gruppe, wenn man sie wählte?
   Gezählt wird über ``visible(gruppe)`` — also mit allen anderen Filtern, aber ohne
   die eigene Auswahl. ``schluessel`` sagt, welchen Wert ein Wein für diese Gruppe
   trägt; ein Wein kann mehrere haben (er steht bei zwei Händlern). */
function zaehlen(gruppe, schluessel) {
  const n = new Map();
  for (const w of visible(gruppe)) {
    for (const k of schluessel(w)) n.set(k, (n.get(k) || 0) + 1);
  }
  return n;
}

/* Kacheln ohne Treffer werden weggelassen statt ausgegraut.
   Ausgegraut hiesse: eine Reihe voller toter Knöpfe, durch die man sich lesen muss.
   Weggelassen zeigt die Reihe genau das, was die aktuelle Auswahl noch hergibt —
   und ein Blick genügt.

   Eine *gewählte* Kachel bleibt immer stehen, auch bei null: sonst verschwände der
   Knopf, mit dem man die Auswahl wieder aufhebt, und die Seite liesse sich nicht
   mehr in den Ausgangszustand bringen. Das ist der Fall, der bei „Champagner +
   Mövenpick + bis CHF 50" auftrat: null Treffer, und beide Kacheln müssen sichtbar
   bleiben. */
function chipMitZahl(label, key, gewaehlt, anzahl, onClick) {
  if (!anzahl && !gewaehlt) return null;
  return chip(label, gewaehlt, onClick, "", anzahl);
}

function buildFilters() {
  /* Der Fokus überlebt den Neuaufbau. Ohne das springt er nach jedem Klick auf den
     Seitenanfang, und wer mit der Tastatur filtert, verliert die Stelle. */
  const vorher = document.activeElement && document.activeElement.dataset
    ? document.activeElement.dataset.chip : null;
  const run = document.getElementById("fRun"); run.innerHTML = "";
  // Ein einzelner Lauf ist keine Wahl. Die Gruppe kostet sonst Legende plus
  // Chipzeile auf dem knappsten Platz der Seite — dem ersten Handy-Bildschirm.
  // Das Datum steht ohnehin schon in der Stand-Zeile darüber.
  document.getElementById("runBox").hidden = D.runs.length < 2;
  D.runs.forEach(r => run.append(chip(
    r.label, S.run === r.id, () => { S.run = r.id; },
    `<span class="n">${r.wines.length}</span>&nbsp;`)));

  const toggle = (set, key) => () => set.has(key) ? set.delete(key) : set.add(key);
  const anh = (el, c) => { if (c) el.append(c); };

  const nMat = zaehlen("mat", w => [w.maturity || "?"]);
  const mat = document.getElementById("fMat"); mat.innerHTML = "";
  // Kein Farbpunkt: die Beschriftung sagt dasselbe, und dieselbe Farbe stand vorher
  // im Diagramm für einen Händler.
  D.maturities.forEach(m => anh(mat, chipMitZahl(
    m.label, m.key, S.mat.has(m.key), nMat.get(m.key) || 0, toggle(S.mat, m.key))));
  anh(mat, chipMitZahl("keine Angabe", "?", S.mat.has("?"), nMat.get("?") || 0,
                       toggle(S.mat, "?")));

  const nStyle = zaehlen("style", w => [w.style || "?"]);
  const st = document.getElementById("fStyle"); st.innerHTML = "";
  D.styles.forEach(s => anh(st, chipMitZahl(
    s.label, s.key, S.style.has(s.key), nStyle.get(s.key) || 0, toggle(S.style, s.key))));

  /* Typ-Kacheln in der Reihenfolge der Achse. "unbekannt" steht bewusst am Ende und
     nur, wenn es Weine gibt, die es betrifft — es ist kein Punkt auf der Achse,
     sondern das Eingestaendnis, keinen zu kennen. */
  const nTyp = zaehlen("typ", w => [w.typ || "?"]);
  const ty = document.getElementById("fTyp"); ty.innerHTML = "";
  D.typen.forEach(t => anh(ty, chipMitZahl(
    t.label, t.key, S.typ.has(t.key), nTyp.get(t.key) || 0, toggle(S.typ, t.key))));
  if ((nTyp.get("?") || 0) > 0)
    anh(ty, chipMitZahl("ohne Typ", "?", S.typ.has("?"), nTyp.get("?"), toggle(S.typ, "?")));

  /* Die Quellenreihe bekommt Zahlen, aber keine Kachel wird ausgeblendet: sie ist
     eine Entweder-oder-Wahl, und wer versehentlich in einer leeren Welt landet,
     braucht den Weg zurück nach „alle". Ein verschwundener Knopf wäre eine
     Sackgasse. */
  const ohneQuelle = visible("src");
  const nSrc = {
    alle: ohneQuelle.length,
    ch: ohneQuelle.filter(w => w.swiss).length,
    mp: ohneQuelle.filter(w => w.marketplace).length,
  };
  const sr = document.getElementById("fSrc"); sr.innerHTML = "";
  [["alle", "alle"], ["ch", "Schweizer Handel"], ["mp", "Vivino-Marktplatz"]].forEach(([k, label]) => {
    sr.append(chip(label, S.src === k, () => { S.src = k; S.shop.clear(); render(); },
                   "", nSrc[k]));
  });

  /* Die Zahl steht neu in der Kachel und zählt die *aktuelle* Auswahl, nicht den
     ganzen Bestand — darum trägt der Schlüssel den Ländernamen ohne Klammer. */
  const nLand = zaehlen("land", w => [w.country || ""]);
  const la = document.getElementById("fLand"); la.innerHTML = "";
  D.countries.forEach(c => anh(la, chipMitZahl(
    c.key, c.key, S.land.has(c.key), nLand.get(c.key) || 0, toggle(S.land, c.key))));

  const nShop = zaehlen("shop", w => w.retailers || []);
  const sh = document.getElementById("fShop"); sh.innerHTML = "";
  // Ohne Farbpunkt: der Händler trägt hier keine Farbe, nur seinen Namen.
  /* Nur die Händler der gewählten Welt: "Vivino Aktionen" in der Liste der
     Schweizer Händler wäre ein Filter, der nie einen Treffer ergibt. */
  D.retailers.filter(r => S.src === "alle" || (r.key === "vivinoshop") === (S.src === "mp"))
    .forEach(r => anh(sh, chipMitZahl(
      r.name, r.key, S.shop.has(r.key), nShop.get(r.key) || 0, toggle(S.shop, r.key))));

  if (vorher) {
    const zurueck = document.querySelector(`.chip[data-chip="${CSS.escape(vorher)}"]`);
    if (zurueck) zurueck.focus();
  }
}

/* Die Filter starten zugeklappt — auf jeder Breite.
   Vorher waren sie am Desktop dauerhaft offen und liessen sich nicht einmal
   schliessen: der Griff war ab 721 px per CSS ausgeblendet, und ein <details> ohne
   Griff muss offen bleiben, sonst wäre der Inhalt unerreichbar. Dann kam der Griff
   zurück, und die Vorgabe blieb "breit offen". Auch das ist zu viel: mit Lauf,
   Quelle, Sorte, Typ, Land, Region, Reife, Preis und Note steht ein halber
   Bildschirm Formular über den Weinen, bevor der erste Wein zu sehen ist.

   Zugeklappt heisst nicht unsichtbar: in der Zeile steht "Filter · 4 aktiv". Die
   Vorauswahl bleibt damit angeschrieben, auch wenn man die Kästchen nicht sieht —
   sonst wäre eine gefilterte Liste von einer vollständigen nicht zu unterscheiden. */
const filterBox = document.getElementById("filterBox");
/* Wer selbst geklickt hat, behält seine Wahl über alle folgenden Renderdurchläufe.
   Ohne dieses Merkmal klappte der Kasten bei jeder Filteränderung wieder zu — also
   genau dann, wenn man ihn gerade braucht. */
let userChoseFilters = false, programmatic = false;
/* Am Klick festgemacht, nicht am `toggle`-Ereignis: das feuert asynchron, und ein
   unmittelbar folgendes render() würde die Wahl sonst wieder überschreiben. */
filterBox.querySelector("summary").addEventListener("click", () => {
  userChoseFilters = true;
});
filterBox.addEventListener("toggle", () => { if (!programmatic) userChoseFilters = true; });
function syncFilterBox() {
  /* Die Breite spielt keine Rolle mehr: zugeklappt ist überall die Vorgabe. Damit
     entfällt auch das Nachziehen beim Drehen und Fensterziehen. */
  const want = userChoseFilters ? filterBox.open : false;
  if (filterBox.open !== want) {
    programmatic = true; filterBox.open = want; programmatic = false;
  }
}
syncFilterBox();

function activeFilterCount() {
  return S.mat.size + S.style.size + S.shop.size + S.land.size
    + (S.src !== STANDARD_QUELLE ? 1 : 0)
    + (S.q.trim() ? 1 : 0) + (S.minRating != null ? 1 : 0) + (S.maxPrice != null ? 1 : 0)
    + (S.onlyBargain ? 1 : 0) + (S.onlyFound ? 1 : 0) + (S.noVivino ? 1 : 0)
    + (S.onlyNeu ? 1 : 0)
    + S.hideGrapes.size;
}

function render() {
  buildFilters();
  const active = activeFilterCount();
  document.getElementById("filterCount").textContent =
    active ? `· ${active} aktiv` : "· keine aktiv";
  syncFilterBox();
  const list = visible(), total = currentRun().wines.length;
  const rated = list.filter(w => w.rating != null).length;
  // Der Marktpreis fehlt bei der Mehrheit der Weine. Wer nach Ersparnis sortiert,
  // soll wissen, wie viele Weine dazu überhaupt eine Angabe haben — sonst liest
  // sich die Spalte voller "—" wie ein Fehler statt wie eine Lücke in den Daten.
  const priced = list.filter(w => w.bargain != null).length;
  // Treffermenge in die sticky Leiste, Abdeckung darunter: das eine ändert sich mit
  // jedem Klick, das andere ist zum Nachschlagen.
  document.getElementById("count").innerHTML =
    `<b>${list.length}</b> von ${total} Weinen`;
  /* „Neu" nur anbieten und nur zählen, wenn dieser Lauf einen Vorgänger im Cache hatte.
     Beim ersten Lauf ist kein Wein neu, sondern alle sind es — ein Filter darüber wäre
     eine Auskunft ohne Inhalt, und ein Kästchen, das nichts tut, ist schlimmer als
     keines. Fällt der Vorlauf weg, fällt auch eine gesetzte Auswahl. */
  const hatVorlauf = !!currentRun().hasPrev;
  document.getElementById("fNeuBox").hidden = !hatVorlauf;
  if (!hatVorlauf && S.onlyNeu) { S.onlyNeu = false; document.getElementById("fNeu").checked = false; }
  const neu = hatVorlauf ? list.filter(w => w.neu).length : 0;
  document.getElementById("coverage").textContent =
    `${rated} davon mit Vivino-Note · ${priced} mit Marktpreis`
    + (hatVorlauf ? ` · ${neu} neu seit dem letzten Lauf` : "");
  document.getElementById("tblTitle").textContent =
    list.length === total ? "Alle Weine" : "Gefilterte Weine";
  chart(list); table(list);
}

document.getElementById("q").addEventListener("input", e => { S.q = e.target.value; refilter(); });
const numOrNull = v => v === "" ? null : Number(v);
/* Kopfzeile und Auswahlfeld sind zwei Wege zur selben Sortierung. Nach einem Klick auf
   die Kopfzeile muss das Feld nachziehen, sonst zeigt es etwas anderes an als gilt. */
function syncSort() {
  const el = document.getElementById("fSort");
  const wanted = `${S.sort}:${S.dir}`;
  el.value = [...el.options].some(o => o.value === wanted) ? wanted : "";
}
document.getElementById("fSort").addEventListener("change", e => {
  const [col, dir] = e.target.value.split(":");
  S.sort = col; S.dir = Number(dir); render();
});
document.getElementById("fMinRating").addEventListener("change", e => {
  S.minRating = numOrNull(e.target.value); refilter();
});
document.getElementById("fMaxPrice").addEventListener("change", e => {
  S.maxPrice = numOrNull(e.target.value); refilter();
});
document.getElementById("fBargain").addEventListener("change", e => {
  S.onlyBargain = e.target.checked; refilter();
});
document.getElementById("fNoVivino").addEventListener("change", e => {
  S.noVivino = e.target.checked; refilter();
});
document.getElementById("fNeu").addEventListener("change", e => {
  S.onlyNeu = e.target.checked; refilter();
});
document.getElementById("fFound").addEventListener("change", e => {
  S.onlyFound = e.target.checked; refilter();
});
/* Erst hier, nach den Ereignishandlern: die Auswahlfelder tragen ihren Standardwert
   nicht im HTML, sondern bekommen ihn beim Laden. Ohne das zeigte die Liste 50 Franken
   und Note 4, während in den Feldern "alle" stünde — der Besucher hielte die Auswahl
   für einen Fehler. Die Konstanten bleiben die einzige Quelle: auch „Zurücksetzen"
   greift auf sie zurück. */
document.getElementById("fMinRating").value = String(STANDARD_NOTE);
document.getElementById("fMaxPrice").value = String(STANDARD_PREIS);

/* Die Sorten-Kästchen stehen einmal fest: sie hängen am Bestand, nicht an der
   aktuellen Auswahl. Neu aufzubauen hiesse, sie dem Besucher unter dem Finger
   wegzuziehen. */
(D.grapeFilters || []).forEach(g => {
  const label = document.createElement("label");
  label.className = "cb";
  label.title = `${g.count} Weine im Bestand tragen ${g.label} im Namen`;
  const box = document.createElement("input");
  box.type = "checkbox";
  box.id = "fGrape_" + g.key;
  box.addEventListener("change", e => {
    if (e.target.checked) S.hideGrapes.add(g.key); else S.hideGrapes.delete(g.key);
    refilter();
  });
  label.append(box, document.createTextNode(" " + g.label + " ausblenden"));
  document.getElementById("fGrapes").append(label);
});

document.getElementById("reset").addEventListener("click", () => {
  // Zurücksetzen heisst: auf den Standard, nicht auf leer. Sonst führt der Knopf zu
  // einem Zustand, den man beim Laden nie sieht.
  S.mat.clear(); S.shop.clear(); S.land.clear(); S.q = "";
  S.style = new Set([STANDARD_SORTE]);
  S.src = STANDARD_QUELLE;
  S.minRating = STANDARD_NOTE; S.maxPrice = STANDARD_PREIS;
  S.onlyBargain = false; S.onlyFound = false; S.noVivino = false; S.onlyNeu = false;
  S.hideGrapes.clear();
  (D.grapeFilters || []).forEach(g => {
    const box = document.getElementById("fGrape_" + g.key);
    if (box) box.checked = false;
  });
  S.sort = "value"; S.dir = -1; S.limit = PAGE;
  document.getElementById("q").value = "";
  document.getElementById("fMinRating").value = String(STANDARD_NOTE);
  document.getElementById("fMaxPrice").value = String(STANDARD_PREIS);
  document.getElementById("fBargain").checked = false;
  document.getElementById("fNoVivino").checked = false;
  document.getElementById("fFound").checked = false;
  document.getElementById("fNeu").checked = false;
  syncSort();
  render();
});
render();

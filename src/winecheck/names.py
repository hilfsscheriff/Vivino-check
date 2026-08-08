"""Namens-Normalisierung.

Getrennt von :mod:`winecheck.matching`, weil hier nur *Vokabular* steht — die
Entscheidungslogik liegt im Matcher. Wer eine Rebsorte oder ein Produzentenwort
ergänzen will, ändert nur diese Datei.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

#: Rechtliche Herkunftsbezeichnungen. Händler und Bewertungsquellen schreiben die
#: völlig inkonsistent ("Sicilia DOC" vs. gar nicht), darum raus aus dem Vergleich.
#: Die Unterscheidung DOC/DOCG wird nicht über diese Kürzel getroffen, sondern über
#: die Qualitätsstufen in DISCRIMINATING (Classico, Riserva, ...).
LEGAL_DESIGNATIONS = {
    "doc", "docg", "dop", "igt", "igp", "aoc", "aop", "ao", "do", "doca", "dso",
    "vdp", "vdt", "qba", "ava", "pdo", "pgi", "vino", "vin", "wein", "weine",
    "wines", "vini", "controllata", "denominazione", "origine", "garantita",
    # Weinart als Wort. Aktionis schreibt "… – Rotwein, Österreich (0.75l)"; ohne
    # diese Einträge wäre "rotwein" ein eigenständiger Namensbestandteil und würde
    # als Identität zählen.
    "rotwein", "weisswein", "rosewein", "roséwein", "schaumwein", "perlwein",
    "dessertwein", "likorwein", "likörwein", "sussweim", "susswein", "südwein",
    "sudwein", "landwein", "tafelwein", "qualitatswein", "prädikatswein",
    "pradikatswein", "schaumweine", "stillwein",
    "appellation", "controlee", "protegee", "qualitatswein", "landwein", "tafelwein",
}

#: Betriebsformen und Höflichkeitsformeln vor dem eigentlichen Produzentennamen.
#: "Tenute Rossetti Linda" und "Rossetti Linda" sind derselbe Wein.
PRODUCER_WORDS = {
    "tenuta", "tenute", "azienda", "aziende", "agricola", "agricole", "cantina",
    "cantine", "societa", "soc", "fattoria", "podere", "poderi", "castello",
    "marchesi", "marchese", "barone", "baron", "conte", "contessa", "principe",
    "weingut", "weinkellerei", "kellerei", "winzer", "domaine", "domaines",
    "chateau", "clos", "maison", "cave", "caves", "celler", "cellers", "cellier",
    "bodega", "bodegas", "vinicola", "vinicole", "vignobles", "vignoble", "vigneti",
    "vigneto", "famille", "family", "fils", "freres", "gebruder", "winery",
    "wineries", "estate", "estates", "company", "co", "srl", "spa", "sa", "ag",
    "gmbh", "ltd", "inc", "sarl", "scarl", "eredi", "casa", "quinta", "herdade",
}

#: Füllwörter. Werden beidseitig entfernt; "Il Bruciato" verliert dabei nur das "Il",
#: "Bruciato" bleibt stehen und schlägt als Fremd-Token an.
#: ``an`` und ``am`` fehlen hier absichtlich: sonst verliert "Ànima Negra ÀN/2" seinen
#: Namensbestandteil.
STOPWORDS = {
    "de", "di", "del", "della", "dello", "delle", "dei", "degli", "da", "dal",
    "das", "der", "die", "den", "dem", "le", "la", "les", "el", "il", "lo", "los",
    "las", "the", "of", "and", "e", "y", "et", "und", "a", "al", "alla", "au",
    "aux", "in", "im", "von", "vom", "zu", "zum", "d", "l", "su", "con",
    # Ergänzt, nachdem "Domherrenwein Fendant du Valais" wegen des fehlenden "du"
    # nur 75 % Abdeckung erreichte und damit fälschlich abgelehnt wurde.
    "du", "des", "dos", "ai", "agli", "alle", "allo", "sul", "sui", "aus", "ein",
    "eine", "einer", "sowie", "od", "oder", "or",
}

#: Verpackung, Volumen, Marketing. Kein Teil der Wein-Identität.
PACKAGING_NOISE = {
    "flasche", "flaschen", "bouteille", "bouteilles", "bottle", "bottles",
    "karton", "kartons", "harass", "kiste", "caisse", "tray", "pack", "gebinde",
    "cl", "ml", "dl", "lt", "liter", "litre", "magnumflasche", "stk", "stuck",
    "neu", "aktion", "angebot", "sale", "rabatt", "statt", "nur", "jetzt",
    "trinkreif", "jahrgang", "vintage", "millesime",
    # Verpackungsmaterial. "Montagne Vin Rouge PET" wäre sonst über das Token "pet"
    # spezifisch genug geworden und hätte die Note eines Burgunders geerbt.
    "pet", "tetra", "dose", "bib", "beutel", "pouch", "glas", "schraubverschluss",
    "kunststoff", "einweg", "mehrweg",
}

#: Tokens, die einen Wein von einem anderen unterscheiden. Fehlt eines auf genau einer
#: Seite, ist es ein *anderer* Wein — keine Schreibvariante. Das ist die Regel, die
#: "Valpolicella Ripasso Superiore" von "Valpolicella Ripasso Classico Superiore"
#: trennt und verhindert, dass ein 13-Franken-Wein die Bewertung eines
#: 130-Franken-Weins bekommt.
DISCRIMINATING = {
    # Ausbaustufen über der Grundqualität. „Selezione" stand schon hier, die
    # spanischen und weiteren Entsprechungen nicht — und daran fiel es auf: „Murua
    # Rioja Reserva **Especial**" (CHF 17.90) bekam die Note der schlichten „Murua
    # Reserva". Zwei verschiedene Weine desselben Guts, eine Stufe auseinander.
    #
    # Diese Wörter stehen nie zufällig da; wer sie auf einer Seite liest und auf der
    # anderen nicht, hat den falschen Wein.
    "especial", "special", "speciale", "seleccion", "seleccionada", "limitada",
    "limitata", "edicion", "edizione", "singolare",

    # Süssweinmerkmale. "Passito", "Recioto" und "Eiswein" standen schon hier, die
    # fremdsprachigen Entsprechungen nicht — und daran fiel es auf: „Chivite Navarra
    # Coleccion 125" (rot) bekam die Note von „Chivite Navarra **Vendimia Tardía**
    # Coleccion 125", einem Spätlese-Süsswein desselben Hauses. „La Porte de Novembre"
    # bekam die des „Porte de Novembre **Ice**".
    #
    # Diese Wörter stehen nie zufällig da: wer sie auf einer Seite liest und auf der
    # anderen nicht, hat zwei verschiedene Weine vor sich.
    "vendimia", "tardia", "vendemmia", "tardiva", "ice", "muffato", "botrytis",
    "moelleux", "liquoreux",

    # Lagen- und Qualitätsstufen
    "classico", "classica", "riserva", "riserve", "reserva", "reserve", "gran",
    "grande", "selezione", "superiore", "supérieur", "superieur", "cru", "premier",
    "grand", "1er", "bourgeois", "villages", "vieilles", "vignes", "alte", "reben",
    "vecchio", "vecchie", "antico", "sur", "lie", "lies",
    # Deutsche Prädikate
    "kabinett", "spatlese", "auslese", "beerenauslese", "trockenbeerenauslese",
    "eiswein", "strohwein", "hochgewachs", "grosses", "erstes", "gewachs",
    # Schaumwein-Dosage und Stil
    "brut", "extra", "sec", "demi", "dolce", "amabile", "dulce", "trocken",
    "halbtrocken", "lieblich", "sussreserve", "millesimato", "satèn", "saten",
    # Rosé ist ein eigenes Produkt und steht praktisch nie in einem Appellationsnamen —
    # anders als "Rosso"/"Bianco", die unten als reine Farbtokens behandelt werden.
    "rose", "rosato", "rosado", "blush", "novello", "nouveau",
    # Ausbau
    "barrique", "barricato", "oak", "unfiltered", "unfiltriert", "naturale",
    "passito", "appassimento", "ripasso", "amarone", "recioto", "solera",
    "sinusoidal",
}

#: Regionen, Appellationen und Länder. Diese Tokens dürfen auf *einer* Seite fehlen,
#: ohne dass der Match kippt: eine Quelle, die "Toscana" dazuschreibt, meint denselben
#: Wein. Sie taugen aber nicht zur Unterscheidung von Erst- und Zweitwein — dafür sind
#: DISCRIMINATING und die Fremd-Token-Regel im Matcher zuständig.
REGION_HINTS = {
    # Generische Bestandteile französischer Appellationen. "Côtes" steckt in Côtes du
    # Rhône, du Roussillon, de Provence, de Bordeaux und dutzenden mehr — es sagt so
    # wenig über den Wein wie "Tal". Es galt aber als unterscheidend und landete damit
    # in der kurzen Suchabfrage: "cotes dentelles" liefert **null** Treffer, während
    # "dentelles" den gesuchten Wein findet. Ein Wort machte den Unterschied zwischen
    # Treffer und Fehlgriff.
    # "coteaux" bleibt bewusst draussen: es ist zwar in "Coteaux du Layon" eine
    # Appellation, in "Caves des Coteaux" aber der Produzentenname. Als Regionswort
    # verlöre die Prüfung "Produzent fehlt in der Quelle" dort ihren Griff.
    "cotes", "cote",

    "italia", "italien", "italy", "france", "frankreich", "spanien", "spain",
    "espana", "portugal", "deutschland", "germany", "osterreich", "austria",
    "schweiz", "suisse", "svizzera", "switzerland", "chile", "argentina",
    "argentinien", "australia", "australien", "sudafrika", "africa", "california",
    "kalifornien", "usa", "neuseeland", "zealand", "griechenland", "greece",
    "toscana", "tuscany", "toskana", "piemonte", "piedmont", "veneto", "sicilia",
    "sizilien", "sicily", "puglia", "apulien", "umbria", "umbrien", "abruzzo",
    "marche", "lazio", "campania", "sardegna", "sardinien", "trentino", "alto",
    "adige", "sudtirol", "friuli", "lombardia", "liguria", "emilia", "romagna",
    "molise", "basilicata", "calabria", "bolgheri", "maremma", "chianti",
    "montalcino", "montepulciano", "valpolicella", "soave", "prosecco", "asti",
    "langhe", "roero", "monferrato", "gavi", "bordeaux", "bourgogne", "burgund",
    "burgundy", "rhone", "loire", "alsace", "elsass", "champagne", "provence",
    "languedoc", "roussillon", "beaujolais", "chablis", "medoc", "graves",
    "sauternes", "pomerol", "saint", "emilion", "margaux", "pauillac", "julien",
    "estephe", "rioja", "ribera", "duero", "priorat", "navarra", "rueda",
    "penedes", "somontano", "toro", "jumilla", "carinena", "valencia", "mancha",
    "douro", "alentejo", "dao", "vinho", "verde", "mosel", "rheingau", "pfalz",
    "rheinhessen", "baden", "franken", "nahe", "wachau", "burgenland", "wagram",
    "kamptal", "kremstal", "steiermark", "valais", "wallis", "vaud", "waadt",
    "geneve", "genf", "ticino", "tessin", "neuchatel", "bundner", "herrschaft",
    "graubunden", "aargau", "zurich", "schaffhausen", "thurgau", "illes",
    "balears", "baleares", "mallorca", "katalonien", "catalunya", "valdobbiadene",
    "conegliano", "treviso", "verona", "sicilia", "etna", "vesuvio", "colli",
    "castelli", "romani", "salento", "manduria", "primitivo", "salice",
    "mendoza", "maipo", "colchagua", "casablanca", "rapel", "barossa",
    "coonawarra", "mclaren", "hunter", "marlborough", "stellenbosch", "paarl",
    "napa", "sonoma", "paso", "robles", "willamette",
}

#: Farbtokens. Die dürfen *einseitig* fehlen, ohne den Match zu kippen: "Rosso" und
#: "Bianco" sind regelmässig Teil des Appellationsnamens (Rosso del Veronese, Rosso di
#: Montalcino, Bianco di Custoza) und werden von Händlern beliebig weggelassen oder
#: ergänzt. "Blanc" ist zusätzlich Bestandteil von Rebsortennamen (Chenin Blanc,
#: Pinot Blanc). Ein Veto gibt es nur beim *Widerspruch* — rot gegen weiss.
#: ``nero``, ``negra``, ``noir`` fehlen hier absichtlich: das sind Rebsorten- und
#: Produzentenbestandteile (Nero d'Avola, Anima Negra, Pinot Noir), keine Farbangaben.
COLOUR_TOKENS = {
    "rosso", "rouge", "tinto", "red", "rot", "roter",
    "bianco", "blanco", "blanc", "white", "weiss", "weisser", "branco",
}

#: Welche Farbtokens sich gegenseitig ausschliessen.
COLOUR_GROUPS = {
    "rot": {"rosso", "rouge", "tinto", "red", "rot", "roter"},
    "weiss": {"bianco", "blanco", "blanc", "white", "weiss", "weisser", "branco"},
}


def colour_group(token: str) -> str | None:
    for group, members in COLOUR_GROUPS.items():
        if token in members:
            return group
    return None


#: Rebsorten. Wie Regionen sind das *generische* Tokens: "Rosé de Gamay" und
#: "Rosé di Gamay" teilen Farbe und Rebsorte, sind aber von zwei verschiedenen
#: Produzenten. Ein Match darf sich nie allein auf Rebsorte, Region, Farbe oder
#: Qualitätsstufe stützen — siehe die Anker-Regel in :mod:`winecheck.matching`.
GRAPE_NAMES = {
    "cabernet", "sauvignon", "merlot", "syrah", "shiraz", "grenache", "garnacha",
    "tempranillo", "sangiovese", "nebbiolo", "barbera", "dolcetto", "montepulciano",
    "primitivo", "zinfandel", "aglianico", "nerello", "mascalese", "corvina",
    "rondinella", "molinara", "lagrein", "teroldego", "refosco", "schiava",
    "pinot", "noir", "nero", "gris", "grigio", "bianco", "meunier", "chardonnay",
    "riesling", "silvaner", "sylvaner", "gewurztraminer", "traminer", "muller",
    "thurgau", "kerner", "scheurebe", "elbling", "chasselas", "fendant", "gutedel",
    "viognier", "marsanne", "roussanne", "vermentino", "verdicchio", "vernaccia",
    "trebbiano", "garganega", "glera", "cortese", "arneis", "falanghina", "fiano",
    "greco", "grillo", "catarratto", "inzolia", "carricante", "malvasia",
    "moscato", "muscat", "muskateller", "albarino", "verdejo", "godello",
    "mencia", "monastrell", "mourvedre", "carignan", "cinsault", "carmenere",
    "malbec", "bonarda", "torrontes", "tannat", "petit", "verdot", "franc",
    "blaufrankisch", "lemberger", "zweigelt", "portugieser", "trollinger",
    "spatburgunder", "dornfelder", "regent", "gamay", "gamaret", "garanoir",
    "humagne", "cornalin", "petite", "arvine", "amigne", "heida", "paien",
    "completer", "raeuschling", "rauschling", "riesling", "steen", "chenin",
    "colombard", "semillon", "palomino", "pedro", "ximenez", "airen", "macabeo",
    "parellada", "xarello", "godello", "loureiro", "alvarinho", "touriga",
    "nacional", "franca", "roriz", "barroca", "castelao", "baga", "encruzado",
    "assyrtiko", "agiorgitiko", "xinomavro", "moschofilero", "savatiano",
    "furmint", "harslevelu", "feteasca", "saperavi", "rkatsiteli", "cariñena",
    "graciano", "mazuelo", "bobal", "prieto", "picudo", "trepat", "sumoll",
    "nerodavola", "perricone", "frappato", "nascetta", "timorasso", "ruche",
    "brachetto", "freisa", "grignolino", "pelaverga", "erbaluce", "favorita",
}

_RE_VINTAGE = re.compile(r"(?<!\d)(19[5-9]\d|20[0-3]\d)(?!\d)")
_RE_VOLUME_CHUNK = re.compile(r"\d+(?:[.,]\d+)?\s*(?:cl|ml|dl|l|lt|liter|litre)\b", re.I)
_RE_PACK_CHUNK = re.compile(r"\b\d{1,3}\s*(?:er|[x×*])\b", re.I)
_RE_PCT = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|vol\.?)", re.I)
_RE_NONWORD = re.compile(r"[^a-z0-9]+")
_RE_WS = re.compile(r"\s+")


def strip_accents(text: str) -> str:
    """Unaccent inkl. ß→ss. ``Ànima`` und ``Anima`` müssen dasselbe Token ergeben."""
    text = text.replace("ß", "ss").replace("ẛ", "ss")
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def extract_vintage(text: str) -> int | None:
    """Erster plausibler Jahrgang im Text. Volumenangaben wie 750 fallen durchs Raster."""
    cleaned = _RE_VOLUME_CHUNK.sub(" ", text or "")
    m = _RE_VINTAGE.search(cleaned)
    return int(m.group(1)) if m else None


#: Kritikernamen, die Händler in den Weinnamen schreiben („Vieux Télégraphe **Parker
#: 95**"). Für Vivino ist das kein Namensbestandteil — der Wein hiess dort nie so.
#: Ungefiltert gilt „Parker" als fehlender Bestandteil und stuft einen Volltreffer auf
#: „unbestätigt" herunter.
#:
#: Entfernt wird nur, wenn eine **Zahl folgt**. Sonst verschwände das Weingut Parker in
#: Coonawarra, und ähnliche Fälle gibt es bei fast jedem dieser Namen.
#: Die vollständige Tabelle zum *Auslesen* der Noten steht in ``adapters.base``.
_KRITIKER = (
    "parker", "falstaff", "suckling", "decanter", "vinum", "spectator", "wine spectator",
    "gaultmillau", "gault millau", "penin", "atkin", "dunnuck", "galloni", "vinous",
    "wine advocate", "advocate", "enthusiast", "veronelli", "gambero",
)
_RE_KRITIKERNOTE = re.compile(
    r"\b(?:" + "|".join(_KRITIKER) + r")\s*[:\-]?\s*\d{1,3}(?:\s*(?:/|von)\s*100)?",
    re.I,
)


def tokenize(text: str, *, keep_discriminating: bool = True,
             keep_alias: bool = False) -> list[str]:
    """Zerlegt einen Weinnamen in identitätstragende Tokens.

    Entfernt Akzente, Jahrgang, Volumen, Gebinde, rechtliche Bezeichnungen,
    Betriebsformen, Füll- und Verpackungswörter. Behält Rebsorten, Produzentennamen,
    Lagennamen und — sofern ``keep_discriminating`` — die Qualitätsstufen.
    """
    # Zweitnamen in Klammern zuerst weg — "Cune (CVNE)" ist ein Produzent, nicht zwei.
    # Für die *Suchabfrage* bleiben sie stehen (``keep_alias``): dort ist jeder
    # Produzentenname Gold wert, während er für den Identitätsvergleich stört.
    roh = (text or "") if keep_alias else strip_alias(text or "")
    roh = _RE_KRITIKERNOTE.sub(" ", roh)
    t = strip_accents(roh.lower())
    t = _RE_VOLUME_CHUNK.sub(" ", t)
    t = _RE_PACK_CHUNK.sub(" ", t)
    t = _RE_PCT.sub(" ", t)
    t = _RE_VINTAGE.sub(" ", t)
    t = _RE_NONWORD.sub(" ", t)
    t = _RE_WS.sub(" ", t).strip()

    out: list[str] = []
    for tok in t.split():
        if not tok or tok.isdigit() and len(tok) > 3:
            continue
        if tok in LEGAL_DESIGNATIONS or tok in PRODUCER_WORDS:
            continue
        if tok in STOPWORDS or tok in PACKAGING_NOISE:
            continue
        if not keep_discriminating and tok in DISCRIMINATING:
            continue
        out.append(tok)
    return out


def tokenize_keep_producer(text: str) -> list[str]:
    """Wie :func:`tokenize`, behält aber die Betriebsformen *an ihrer Position*.

    Nötig für die Zweitwein-Erkennung nach französischem Muster: in
    ``Pavillon Rouge du Château Margaux`` steht der Cuvée-Name **vor** dem
    ``Château``. Nur an der Position der Betriebsform lässt sich ein Cuvée-Name von
    einem Produzentenpräfix unterscheiden.
    """
    t = strip_accents((text or "").lower())
    t = _RE_VOLUME_CHUNK.sub(" ", t)
    t = _RE_PACK_CHUNK.sub(" ", t)
    t = _RE_PCT.sub(" ", t)
    t = _RE_VINTAGE.sub(" ", t)
    t = _RE_NONWORD.sub(" ", t)
    t = _RE_WS.sub(" ", t).strip()

    out: list[str] = []
    for tok in t.split():
        if not tok or (tok.isdigit() and len(tok) > 3):
            continue
        if tok in LEGAL_DESIGNATIONS or tok in STOPWORDS or tok in PACKAGING_NOISE:
            continue
        out.append(tok)
    return out


def normalized_name(text: str) -> str:
    """Kanonische Form für Cache-Key und Dedup."""
    return " ".join(tokenize(text))


#: Ländernamen. Sie stehen auch in REGION_HINTS, brauchen aber eine eigene Liste: für
#: die *Identität* eines Weins sind sie belanglos — jeder Ribera del Duero ist spanisch —
#: während die Region sehr wohl zählt. Händler halten es unterschiedlich: Coop schreibt
#: „Ribera del Duero DO Protos Roble – Rotwein, Spanien", Aligro „Ribera del Duero Roble
#: Protos DO". Derselbe Wein, ein Token Unterschied, zwei Zeilen im Report statt einer
#: mit zwei Preisen.
COUNTRY_NAMES = frozenset({
    "spanien", "espagne", "espana", "spain",
    "italien", "italie", "italia", "italy",
    "frankreich", "france", "francia",
    "schweiz", "suisse", "svizzera", "switzerland",
    "osterreich", "autriche", "austria",
    "portugal", "deutschland", "allemagne", "germany",
    "chile", "chili", "argentinien", "argentine", "argentina",
    "australien", "australie", "australia",
    "sudafrika", "afrique", "südafrika",
    "usa", "kalifornien", "californie",
    "neuseeland", "nouvelle", "zelande",
    "griechenland", "grece", "ungarn", "hongrie",
})


#: Vivino führt Produzenten oft mit Zweitnamen in Klammern: „Cune (CVNE)",
#: „Bodegas Muga (Muga)". Der Klammerinhalt ist ein *Alias*, kein zusätzlicher
#: Namensbestandteil — als solcher gelesen liess er den Matcher „Cune Crianza"
#: ablehnen, weil „CVNE" auf der Händlerseite fehlte.
_RE_PARENS = re.compile(r"\(([^)]{2,40})\)")


def strip_alias(text: str) -> str:
    """Klammerzusätze entfernen, wenn sie wie ein Zweitname aussehen.

    Nur Klammern mit höchstens zwei Wörtern fliegen raus. Längere Klammern tragen
    gelegentlich echte Unterscheidungen („(Magnum 1.5 l)"), und ein Zweitname ist
    nie ein halber Satz.
    """
    def ersetze(m: re.Match[str]) -> str:
        inhalt = m.group(1).strip()
        return "" if len(inhalt.split()) <= 2 else m.group(0)
    return _RE_PARENS.sub(ersetze, text or "").strip()


def dedup_key(name: str, vintage: int | None) -> str:
    """Dedup über normalisierten Namen + Jahrgang, nicht über Artikelnummer —
    Artikelnummern sind händlerspezifisch und taugen nicht für den Vergleich.

    Ländernamen fliegen raus, **sofern danach mindestens zwei unterscheidende Tokens
    bleiben**. Diese Bedingung ist der Punkt: „Protos Roble" bleibt eindeutig und wird
    mit der Aligro-Fassung ohne „Spanien" zusammengeführt. Ein generischer
    „Cabernet Sauvignon, Chile" behält sein Land — sonst fiele er mit
    „Cabernet Sauvignon, Australien" zu einer Zeile zusammen, und das wären zwei
    verschiedene Weine zu einem Phantompreis.
    """
    tokens = tokenize(name)
    ohne_land = [t for t in tokens if t not in COUNTRY_NAMES]
    if len(ohne_land) < len(tokens):
        if sum(1 for t in ohne_land if is_distinctive(t)) >= 2:
            tokens = ohne_land
    core = " ".join(sorted(tokens))
    return f"{core}|{vintage or ''}"


def is_distinctive(token: str) -> bool:
    """Trägt das Token Produzenten-, Marken- oder Lageninformation?

    Rebsorten, Regionen, Farben und Qualitätsstufen tun das nicht — sie kommen in
    hunderten Weinen vor und taugen darum weder als Match-Anker noch als Suchbegriff.
    """
    return (
        len(token) > 2
        and not token.isdigit()
        and token not in GRAPE_NAMES
        and token not in REGION_HINTS
        and token not in COLOUR_TOKENS
        and token not in DISCRIMINATING
    )



#: Zusammengesetzte Farbwörter, die als Rechtsbegriff gelten und darum aus den Tokens
#: fliegen — "Rotwein" steht in LEGAL_DESIGNATIONS. Für die *Suchabfrage* ist das
#: richtig, für die Farbprüfung nicht: der Händler schreibt die Farbe fast immer so an
#: ("… – Rotwein, Spanien"), und wer sie hier verliert, ordnet einem Rotwein die Note
#: eines Blanco zu. Genau das passierte bei "Chivite Coleccion 125".
_COMPOUND_COLOURS = {
    "rot": ("rotwein", "vin rouge", "vino tinto", "vinho tinto", "red wine"),
    "weiss": ("weisswein", "weißwein", "vin blanc", "vino blanco", "vinho branco",
              "white wine"),
    "rose": ("rosewein", "roséwein", "vin rose", "vin rosé", "vino rosado", "rose wine"),
}


def colour_from_text(text: str) -> str | None:
    """Farbgruppe aus dem *Rohtext*, auch wenn das Wort kein Token mehr ist.

    Ergänzt :func:`colour_group`, das nur einzelne Tokens kennt. Rosé wird zuerst
    geprüft: "Roséwein" enthält kein "rotwein", aber die Reihenfolge macht die Absicht
    deutlich, dass die spezifischste Angabe gewinnt.
    """
    hay = strip_accents((text or "").lower())
    for group in ("rose", "weiss", "rot"):
        for word in _COMPOUND_COLOURS[group]:
            if strip_accents(word) in hay:
                return group
    return None

def distinctive_tokens(text: str) -> list[str]:
    """Nur die unterscheidenden Tokens, in ursprünglicher Reihenfolge."""
    return [t for t in tokenize(text) if is_distinctive(t)]



def query_tokens(text: str) -> list[str]:
    """Unterscheidende Tokens **für die Suche** — Klammerinhalte zählen mit.

    Mövenpick nennt den Produzenten nur in der Adresse; wir hängen ihn in Klammern an
    („… Quinta do Vale Meão (Olazabal Filhos)"). Für Vivino ist er das wichtigste Wort,
    für den Namensvergleich dagegen ein Zusatz, den die Quelle nicht kennen muss —
    sonst rechnet der Matcher **uns** an, was wir selbst ergänzt haben, und stuft einen
    Volltreffer auf „unbestätigt" herunter.
    """
    return [t for t in tokenize(text, keep_alias=True) if is_distinctive(t)]


def discriminating_tokens(tokens: list[str]) -> set[str]:
    return {t for t in tokens if t in DISCRIMINATING}


def looks_like_private_label(name: str, brands: list[str]) -> bool:
    """Eigenmarken-Erkennung über die in retailers.yaml gepflegten Markennamen."""
    hay = strip_accents((name or "").lower())
    return any(strip_accents(b.lower()) in hay for b in brands if b)


# --------------------------------------------------------------------- Sorte

#: Weinsorten für Filter und Anzeige.
STYLES = ("rot", "weiss", "rose", "schaumwein", "suesswein", "unbekannt")

STYLE_LABELS: dict[str, str] = {
    "rot": "Rotwein",
    "weiss": "Weisswein",
    "rose": "Rosé",
    "schaumwein": "Schaumwein",
    "suesswein": "Süsswein",
    "unbekannt": "unbekannt",
}

#: Vivinos ``wine.type_id`` — verlässlicher als jede Namensanalyse.
VIVINO_TYPE_IDS: dict[int, str] = {
    1: "rot",
    2: "weiss",
    3: "schaumwein",
    4: "rose",
    7: "suesswein",     # Dessertwein
    24: "suesswein",    # Likörwein, Port
}

#: Schaumwein zuerst prüfen: ein "Rosé Champagne" ist Schaumwein, nicht Rosé, und
#: ein "Blanc de Blancs" ist kein stiller Weisswein.
_SPARKLING = (
    "champagne", "champagner", "prosecco", "cava", "cremant", "crémant", "sekt",
    "spumante", "franciacorta", "espumoso", "mousseux", "frizzante", "perlwein",
    "schaumwein", "valdobbiadene", "cartizze", "asti", "lambrusco", "pet nat",
)
_SWEET = (
    "sauternes", "barsac", "edelsuss", "edelsüss", "beerenauslese",
    "trockenbeerenauslese", "eiswein", "strohwein", "passito", "recioto",
    "vin santo", "vinsanto", "tokaji", "tokaj", "porto", "portwein", "madeira",
    "sherry", "moscatel", "banyuls", "pineau", "dessertwein", "likorwein",
    "spatlese", "auslese", "monbazillac", "jurancon moelleux",
)
_ROSE = ("rosewein", "rose", "rosato", "rosado", "blush", "oeil de perdrix", "chiaretto")
_RED_WORDS = ("rotwein", "rosso", "rouge", "tinto", "vino rosso", "red wine")
_WHITE_WORDS = ("weisswein", "bianco", "blanc", "blanco", "white wine", "vin blanc")


def wine_style(name: str, vivino_type_id: int | None = None) -> str:
    """Sorte eines Weins, für Filter und Anzeige.

    Args:
        vivino_type_id: Vivinos ``wine.type_id``. Liegt er vor, gilt er — er kommt aus
            der Weindatenbank und nicht aus einer Namensanalyse.

    Die Reihenfolge der Namensprüfung ist wesentlich: Schaumwein und Süsswein zuerst,
    weil "Rosé Champagne" ein Schaumwein ist und "Sauternes" kein stiller Weisswein.
    Erst danach Farbe, und Farbwörter schlagen Rebsortennamen — sonst wird
    "Bianco di Merlot" zum Rotwein.
    """
    if vivino_type_id is not None and vivino_type_id in VIVINO_TYPE_IDS:
        return VIVINO_TYPE_IDS[vivino_type_id]

    low = strip_accents((name or "").lower())

    def has(words: tuple[str, ...]) -> bool:
        return any(_style_re(w).search(low) for w in words)

    if has(_SPARKLING):
        return "schaumwein"
    if has(_SWEET):
        return "suesswein"
    if has(_ROSE):
        return "rose"
    red_word, white_word = has(_RED_WORDS), has(_WHITE_WORDS)
    if red_word != white_word:
        return "rot" if red_word else "weiss"
    # Rückfall über Rebsorten.
    red_grapes = {"merlot", "syrah", "shiraz", "cabernet", "nebbiolo", "sangiovese",
                  "tempranillo", "primitivo", "malbec", "zweigelt", "blaufrankisch",
                  "lagrein", "aglianico", "negroamaro", "grenache", "carmenere",
                  "monastrell", "mourvedre", "barbera", "dolcetto", "corvina",
                  "pinotage", "touriga", "mencia", "carignan", "cinsault"}
    white_grapes = {"chardonnay", "riesling", "chasselas", "fendant", "veltliner",
                    "verdejo", "albarino", "vermentino", "gewurztraminer", "silvaner",
                    "sylvaner", "arneis", "grigio", "gris", "viognier", "semillon",
                    "chenin", "colombard", "godello", "furmint", "assyrtiko",
                    "johannisberg", "arvine", "heida", "completer", "marsanne"}
    tokens = set(tokenize(name))
    red, white = bool(tokens & red_grapes), bool(tokens & white_grapes)
    if red != white:
        return "rot" if red else "weiss"
    return "unbekannt"


@lru_cache(maxsize=512)
def _style_re(word: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])")

"""Anbauregionen und ihr übliches Preisniveau.

Wozu
----
„Ein Bordeaux für CHF 10 ist viel besser als ein Primitivo für CHF 10." Das stimmt,
und die Preis-Leistungs-Rechnung wusste es nicht: sie verglich einen Wein mit allen
anderen seiner Machart und Sorte, ohne zu fragen, was seine Herkunft normalerweise
kostet. Ein günstiger Primitivo ist gewöhnlich, ein günstiger Bordeaux ist ein Fund.

Zwei Aufgaben, und sie sind verschieden
---------------------------------------
**1. Zusammenfassen.** Vivino nennt 298 verschiedene Regionsnamen für 1347 Weine.
Bordeaux zerfällt darin in „Saint-Émilion Grand Cru" (23), „Pomerol" (19),
„Haut-Médoc" (7), „Pauillac" (7), „Margaux" (7), „Pessac-Léognan" (6) und „Bordeaux"
(6) — jede Zelle zu dünn, um ein Preisniveau zu schätzen, zusammen 75 Weine und damit
belastbar. Ohne diese Tabelle gäbe es nichts zu rechnen.

Zusammengefasst wird nur, was preislich zusammengehört. „Barolo" bleibt neben
„Langhe" stehen, obwohl beides Piemont ist: der Unterschied ist der Punkt, nicht das
Detail. Umgekehrt liegen Pauillac und Margaux in einem Topf, weil sie sich preislich
kaum unterscheiden.

**2. Einordnen.** Jede Region trägt eine Preisspanne — was eine ordentliche Flasche
von dort im Schweizer Handel üblicherweise kostet.

Und hier die wichtige Einschränkung
-----------------------------------
Diese Spannen sind **gesetzt, nicht gemessen**. Sie stammen aus Erfahrungswerten,
nicht aus den Daten dieses Projekts — wie :data:`~winecheck.wert.PREIS_GEWICHT` und
sonst nichts im ganzen Bericht.

Darum fliessen sie **nicht in die Preis-Leistungs-Zahl ein.** Diese rechnet mit dem
Preisniveau, das der Lauf selbst hergibt: die Region wird zu einer Gruppierungsebene
in der Regression, und der Schwerpunkt jeder Region wird gemessen. Ein Bordeaux für
CHF 10 fällt damit auf, weil die Bordeaux *dieses Laufs* im Schnitt teurer sind — und
nicht, weil hier jemand CHF 12–30 hingeschrieben hat.

Die Spanne steht auf der Seite daneben, damit man den Vergleich selbst nachvollziehen
kann. Eine gesetzte Zahl anzuzeigen und zu benennen ist ehrlich; sie still in eine
Kennzahl zu rechnen wäre es nicht. Wer sie eines Tages doch verrechnen will, misst
sie vorher.

Regionen ohne genug Weine im Lauf bekommen keine eigene Kurve, sondern fallen auf die
nächstgröbere Ebene zurück — dieselbe Mechanik wie bei Stil-Typ und Sorte.
"""

from __future__ import annotations

from dataclasses import dataclass

from .names import strip_accents


@dataclass(frozen=True)
class Region:
    """Eine Anbauregion, ihre Schreibweisen und ihr übliches Preisniveau.

    ``von``/``bis`` sind CHF je 75 cl inkl. MwSt im Schweizer Handel — die Spanne, in
    der eine ordentliche Flasche dieser Herkunft üblicherweise liegt. Nicht die
    Extreme: weder der Aktionsposten noch die Ikone des Hauses.
    """

    key: str
    label: str
    land: str
    von: float
    bis: float
    aliase: tuple[str, ...] = ()


#: Die Regionen, grob nach Anbauland sortiert.
#:
#: Die Auswahl folgt dem, was in Schweizer Aktionen tatsächlich vorkommt — gemessen
#: an den 298 Regionsnamen, die Vivino für den Bestand liefert. Eine vollständige
#: Weinatlas-Liste wäre länger und für diesen Zweck nicht besser: eine Region, die im
#: Lauf nie auftaucht, trägt zu keiner Rechnung bei.
REGIONEN: tuple[Region, ...] = (
    # -- Frankreich -------------------------------------------------------
    Region("bordeaux", "Bordeaux", "Frankreich", 12, 30,
           ("bordeaux", "bordeaux superieur", "medoc", "haut-medoc", "graves",
            "cotes de bordeaux", "cotes de bourg", "fronsac", "listrac", "moulis")),
    Region("bordeaux_rechts", "Saint-Émilion & Pomerol", "Frankreich", 30, 90,
           ("saint-emilion", "saint-emilion grand cru", "pomerol", "lalande-de-pomerol",
            "castillon cotes de bordeaux")),
    Region("medoc_cru", "Médoc-Gemeinden", "Frankreich", 28, 85,
           ("pauillac", "margaux", "saint-julien", "saint-estephe",
            "pessac-leognan", "sauternes", "barsac")),
    Region("burgund_rot", "Burgund rot", "Frankreich", 35, 120,
           ("gevrey-chambertin", "nuits-saint-georges", "vosne-romanee", "pommard",
            "volnay", "beaune", "savigny-les-beaune", "mercurey", "santenay",
            "bourgogne", "cote de nuits", "cote de beaune", "chambolle-musigny",
            "morey-saint-denis", "aloxe-corton", "fixin", "marsannay")),
    Region("burgund_weiss", "Burgund weiss", "Frankreich", 22, 80,
           ("chablis", "meursault", "puligny-montrachet", "chassagne-montrachet",
            "saint-aubin", "pouilly-fuisse", "macon", "montagny", "rully")),
    Region("beaujolais", "Beaujolais", "Frankreich", 10, 25,
           ("beaujolais", "morgon", "fleurie", "brouilly", "moulin-a-vent", "julienas")),
    Region("champagne", "Champagne", "Frankreich", 32, 90,
           ("champagne", "champagner")),
    Region("rhone_nord", "Rhône Nord", "Frankreich", 35, 110,
           ("cote-rotie", "hermitage", "crozes-hermitage", "cornas", "saint-joseph",
            "condrieu")),
    Region("rhone_sued", "Rhône Süd", "Frankreich", 22, 60,
           ("chateauneuf-du-pape", "gigondas", "vacqueyras", "lirac", "tavel",
            "rasteau", "cairanne")),
    Region("rhone", "Côtes-du-Rhône", "Frankreich", 9, 20,
           ("cotes-du-rhone", "cotes du rhone", "ventoux", "luberon", "costieres de nimes")),
    Region("provence", "Provence", "Frankreich", 12, 32,
           ("cotes de provence", "provence", "bandol", "coteaux d'aix-en-provence",
            "coteaux varois en provence")),
    Region("languedoc", "Languedoc & Roussillon", "Frankreich", 7, 18,
           ("pays d'oc", "languedoc", "corbieres", "minervois", "faugeres", "fitou",
            "cotes du roussillon", "cotes catalanes", "saint-chinian", "picpoul",
            "cotes de thongue", "mediterranee", "terres du midi", "maury", "banyuls")),
    Region("loire", "Loire", "Frankreich", 12, 30,
           ("sancerre", "pouilly-fume", "vouvray", "muscadet", "chinon", "bourgueil",
            "saumur", "anjou", "touraine", "quincy", "menetou-salon", "val de loire")),
    Region("elsass", "Elsass", "Frankreich", 12, 30,
           ("alsace", "elsass", "cremant d'alsace")),
    Region("sudwest", "Südwestfrankreich", "Frankreich", 9, 22,
           ("cahors", "madiran", "bergerac", "gaillac", "jurancon", "irouleguy",
            "comte tolosan", "gascogne", "cotes de gascogne")),
    Region("jura_savoie", "Jura & Savoie", "Frankreich", 15, 40,
           ("jura", "arbois", "chateau-chalon", "savoie", "bugey")),
    Region("korsika", "Korsika", "Frankreich", 14, 32, ("corse", "patrimonio", "korsika")),

    # -- Italien ----------------------------------------------------------
    Region("toscana", "Toscana", "Italien", 12, 32,
           ("toscana", "toskana", "colli della toscana centrale", "maremma toscana",
            "morellino di scansano", "chianti", "chianti colli senesi", "cortona",
            "colli aretini", "colli pisani", "montecucco", "val di cornia")),
    Region("chianti_classico", "Chianti Classico", "Italien", 15, 38,
           ("chianti classico",)),
    Region("brunello", "Brunello di Montalcino", "Italien", 35, 90,
           ("brunello di montalcino", "rosso di montalcino", "montalcino")),
    Region("bolgheri", "Bolgheri & Supertoskaner", "Italien", 28, 90,
           ("bolgheri", "bolgheri superiore", "bolgheri sassicaia", "suvereto")),
    Region("nobile", "Vino Nobile di Montepulciano", "Italien", 16, 40,
           ("vino nobile di montepulciano", "rosso di montepulciano")),
    Region("barolo", "Barolo", "Italien", 35, 95, ("barolo",)),
    Region("barbaresco", "Barbaresco", "Italien", 28, 80, ("barbaresco",)),
    Region("piemont", "Piemont übrig", "Italien", 11, 30,
           ("piemont", "piemonte", "langhe", "barbera d'alba", "barbera d'asti",
            "dolcetto d'alba", "roero", "nebbiolo d'alba", "gavi", "monferrato",
            "asti", "moscato d'asti", "alta langa", "colli tortonesi")),
    Region("amarone", "Amarone", "Italien", 30, 70,
           ("amarone della valpolicella", "amarone della valpolicella classico",
            "recioto della valpolicella")),
    Region("valpolicella", "Valpolicella", "Italien", 11, 28,
           ("valpolicella", "valpolicella ripasso", "valpolicella classico",
            "valpolicella superiore", "bardolino", "chiaretto di bardolino")),
    Region("prosecco", "Prosecco", "Italien", 8, 18,
           ("prosecco", "conegliano valdobbiadene", "asolo prosecco",
            "prosecco di valdobbiadene")),
    Region("franciacorta", "Franciacorta", "Italien", 20, 48, ("franciacorta",)),
    Region("suedtirol", "Südtirol & Trentino", "Italien", 14, 36,
           ("sudtirol - alto adige", "sudtirol", "alto adige", "trentino",
            "vigneti delle dolomiti", "teroldego rotaliano")),
    Region("friaul", "Friaul & Veneto weiss", "Italien", 10, 26,
           ("friuli", "collio", "colli orientali del friuli", "veneto", "lugana",
            "soave", "custoza", "garda", "delle venezie", "friuli grave", "isonzo")),
    Region("puglia", "Apulien", "Italien", 7, 18,
           ("puglia", "salento", "primitivo di manduria", "salice salentino",
            "negroamaro", "castel del monte", "gioia del colle", "brindisi",
            "copertino", "tarantino")),
    Region("sizilien", "Sizilien", "Italien", 9, 24,
           ("sizilien", "sicilia", "terre siciliane", "etna", "menfi", "cerasuolo di vittoria",
            "noto", "vittoria", "marsala", "pantelleria")),
    Region("abruzzen", "Abruzzen & Marken", "Italien", 7, 17,
           ("abruzzo", "montepulciano d'abruzzo", "trebbiano d'abruzzo",
            "cerasuolo d'abruzzo", "terre di chieti", "marche", "verdicchio",
            "rosso piceno", "offida", "conero")),
    Region("sardinien", "Sardinien", "Italien", 11, 30,
           ("sardegna", "sardinien", "carignano del sulcis", "cannonau di sardegna",
            "vermentino di gallura", "isola dei nuraghi", "vermentino di sardegna")),
    Region("kampanien", "Süditalien übrig", "Italien", 9, 26,
           ("campania", "kampanien", "taurasi", "greco di tufo", "fiano di avellino",
            "aglianico del vulture", "basilicata", "calabria", "kalabrien", "cirò",
            "irpinia", "beneventano", "molise")),
    Region("lombardei", "Lombardei", "Italien", 12, 34,
           ("lombardia", "lombardei", "valtellina superiore", "valtellina",
            "oltrepo pavese", "riviera del garda")),
    Region("umbrien", "Umbrien & Latium", "Italien", 10, 28,
           ("umbria", "umbrien", "montefalco", "orvieto", "lazio", "latium", "frascati")),

    # -- Spanien & Portugal -----------------------------------------------
    Region("rioja", "Rioja", "Spanien", 10, 30, ("rioja", "rioja alta", "rioja alavesa")),
    Region("ribera", "Ribera del Duero", "Spanien", 14, 40, ("ribera del duero",)),
    Region("priorat", "Priorat & Montsant", "Spanien", 20, 60, ("priorat", "montsant")),
    Region("spanien_zentral", "Spanien übrig", "Spanien", 7, 20,
           ("toro", "bierzo", "jumilla", "almansa", "ucles", "la mancha", "yecla",
            "valdepenas", "castilla y leon", "carinena", "calatayud", "campo de borja",
            "somontano", "navarra", "vino de espana", "utiel-requena", "valencia",
            "alicante", "empordà", "emporda", "penedes", "carinena")),
    Region("rueda", "Rueda & Rías Baixas", "Spanien", 10, 24,
           ("rueda", "rias baixas", "albarino", "ribeiro", "valdeorras", "godello")),
    Region("cava", "Cava", "Spanien", 8, 22, ("cava",)),
    Region("sherry", "Jerez", "Spanien", 12, 35, ("jerez", "sherry", "manzanilla", "montilla")),
    Region("douro", "Douro & Portugal", "Portugal", 11, 30,
           ("douro", "porto", "portugal", "alentejo", "dao", "vinho verde", "bairrada",
            "lisboa", "setubal", "tejo", "madeira")),

    # -- Deutschland, Österreich, Schweiz ---------------------------------
    Region("deutschland", "Deutschland", "Deutschland", 10, 28,
           ("mosel", "pfalz", "rheingau", "rheinhessen", "nahe", "baden",
            "wurttemberg", "franken", "ahr", "saale-unstrut", "sachsen", "deutschland")),
    Region("oesterreich", "Österreich", "Österreich", 12, 32,
           ("burgenland", "neusiedlersee", "wachau", "kamptal", "kremstal",
            "weinviertel", "leithaberg", "mittelburgenland", "carnuntum",
            "thermenregion", "steiermark", "sudsteiermark", "osterreich",
            "niederosterreich", "wien", "eisenberg", "traisental")),
    Region("schweiz", "Schweiz", "Schweiz", 14, 38,
           ("valais", "wallis", "vaud", "waadt", "ticino", "tessin", "geneve", "genf",
            "neuchatel", "neuenburg", "graubunden", "bundner herrschaft", "schaffhausen",
            "zurich", "zurcher weinland", "aargau", "thurgau", "bielersee", "schweiz",
            "la cote", "lavaux", "chablais", "trois lacs", "deutschschweiz")),

    # -- Übersee ----------------------------------------------------------
    Region("napa", "Napa Valley", "Vereinigte Staaten", 32, 100,
           ("napa valley", "oakville", "rutherford", "stags leap district",
            "howell mountain", "st. helena", "calistoga")),
    Region("kalifornien", "Kalifornien übrig", "Vereinigte Staaten", 14, 45,
           ("kalifornien", "california", "sonoma county", "russian river valley",
            "paso robles", "central coast", "santa barbara county", "lodi",
            "alexander valley", "dry creek valley", "monterey", "mendocino")),
    Region("pazifik_nordwest", "Oregon & Washington", "Vereinigte Staaten", 18, 50,
           ("willamette valley", "oregon", "columbia valley", "walla walla valley",
            "washington", "yakima valley")),
    Region("mendoza", "Argentinien", "Argentinien", 10, 30,
           ("mendoza", "uco valley", "lujan de cuyo", "valle de uco", "salta",
            "patagonien", "argentinien", "cafayate")),
    Region("chile", "Chile", "Chile", 8, 24,
           ("colchagua valley", "maipo valley", "casablanca valley", "aconcagua",
            "curico valley", "maule valley", "rapel valley", "limari", "leyda",
            "cachapoal", "chile", "itata")),
    Region("suedafrika", "Südafrika", "Südafrika", 10, 30,
           ("stellenbosch", "swartland", "western cape", "franschhoek", "paarl",
            "walker bay", "hemel-en-aarde", "constantia", "elgin", "robertson",
            "sudafrika", "coastal region", "darling")),
    Region("australien", "Australien", "Australien", 11, 35,
           ("barossa valley", "mclaren vale", "coonawarra", "clare valley",
            "eden valley", "yarra valley", "margaret river", "hunter valley",
            "adelaide hills", "australien", "south australia", "heathcote")),
    Region("neuseeland", "Neuseeland", "New Zealand", 13, 35,
           ("marlborough", "central otago", "hawke's bay", "martinborough",
            "neuseeland", "new zealand", "gisborne", "nelson")),
    Region("griechenland", "Griechenland", "Griechenland", 10, 28,
           ("santorini", "nemea", "naoussa", "peloponnes", "griechenland", "kreta",
            "makedonien", "attika")),
    Region("osteuropa", "Osteuropa", "Ungarn", 9, 26,
           ("tokaj", "villany", "eger", "ungarn", "rumanien", "bulgarien", "moldawien",
            "slowenien", "kroatien", "primorska", "istrien", "dalmatien", "georgien",
            "kakheti")),
    Region("libanon_israel", "Naher Osten", "Libanon", 14, 40,
           ("bekaa valley", "libanon", "israel", "galilee", "judean hills")),
)


def _norm(text: str) -> str:
    """Kleinschreibung ohne Akzente — Vivino schreibt „Saint-Émilion", wir suchen
    „saint-emilion"."""
    return " ".join(strip_accents(str(text or "")).lower().split())


#: Alias → Regionsschlüssel. Beim Bauen geprüft: ein Alias darf nur einer Region
#: gehören, sonst entschiede die Reihenfolge der Tabelle über die Zuordnung — genau
#: die Sorte stiller Willkür, die in diesem Projekt schon zweimal teuer war.
_INDEX: dict[str, str] = {}
for _r in REGIONEN:
    for _a in (_r.label, *_r.aliase):
        _k = _norm(_a)
        if _k in _INDEX and _INDEX[_k] != _r.key:
            raise ValueError(
                f"Alias '{_a}' gehört zu '{_INDEX[_k]}' und zu '{_r.key}' — "
                f"die Zuordnung wäre von der Tabellenreihenfolge abhängig"
            )
        _INDEX[_k] = _r.key

NACH_KEY: dict[str, Region] = {r.key: r for r in REGIONEN}


def zuordnen(region_name: str) -> str:
    """Vivinos Regionsnamen auf einen Regionsschlüssel abbilden. ``""`` heisst
    „keine bekannte Region".

    Erst exakt, dann über den längsten passenden Alias, der im Namen steckt:
    „Amarone della Valpolicella Classico" ist nicht in der Tabelle, „amarone della
    valpolicella classico" schon — und „Bolgheri Sassicaia DOC" findet „bolgheri".

    Der längste Alias gewinnt, und das ist wesentlich: „valpolicella" steckt auch in
    „amarone della valpolicella", und Amarone ist preislich das Dreifache. Wer hier
    den ersten Treffer nähme, legte 16 Amarone auf die Valpolicella-Kurve.

    Geraten wird nichts. Ein unbekannter Regionsname bleibt unbekannt und fällt in
    der Rechnung auf die nächstgröbere Ebene zurück.
    """
    n = _norm(region_name)
    if not n:
        return ""
    if n in _INDEX:
        return _INDEX[n]
    treffer = [a for a in _INDEX if a in n]
    if not treffer:
        return ""
    return _INDEX[max(treffer, key=len)]


def spanne(key: str) -> tuple[float, float] | None:
    """Die **gesetzte** Preisspanne einer Region, CHF je 75 cl inkl. MwSt.

    Nicht gemessen — siehe Modulkopf. Sie dient der Anzeige, nicht der Rechnung.
    """
    r = NACH_KEY.get(key)
    return (r.von, r.bis) if r else None


def label(key: str) -> str:
    r = NACH_KEY.get(key)
    return r.label if r else ""

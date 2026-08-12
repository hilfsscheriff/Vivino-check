"""Preis-Leistung — die Kennzahl hat einen Besitzer.

Sie hatte zwei, und beide hiessen dem Nutzer gegenüber „Preis-Leistung":
``aggregate.compute_scores`` setzte eine Rangposition innerhalb der Preisklasse und
trieb damit die PDF-Rangliste, die Regression in ``report/site`` setzte den
Regressionsrest nach ``(typ, sorte)`` und trieb nur die Webseite.

Teuer wurde das, als Spec §6 die Gruppierung auf den Stil-Typ umstellte: umgesetzt
wurde es nur in der Seite, und das PDF rankte weiter nach der Verzerrung, die §6
beheben sollte.
"""

import pytest

from winecheck.aggregate import compute_scores
from winecheck.models import (
    Offer,
    PriceConfidence,
    RetailerPrice,
    VivinoResult,
    VivinoStatus,
    WineRow,
)
from winecheck.wert import _je_typ, _wirksame_note


def _wein(preis, note, typ="ausgewogen", sorte="rot", anzahl=500):
    return {"price": preis, "rating": note, "ratingCount": anzahl, "typ": typ, "style": sorte}


def test_die_rechnung_liegt_nur_noch_in_wert():
    """Regressionssperre gegen den Rückfall: ``report/site`` darf die Formel nicht
    erneut enthalten, sondern muss sie importieren."""
    from pathlib import Path

    quelle = (Path(__file__).resolve().parents[1]
              / "src/winecheck/report/site.py").read_text(encoding="utf-8")
    assert "from ..wert import" in quelle
    # Die Formel selbst — der gedämpfte Rest gegen die gesetzte Steigung — steht dort
    # nicht mehr.
    assert "PREIS_GEWICHT * (math.log10" not in quelle
    assert "def _value_scores_einer_gruppe" not in quelle


def test_der_durchschnittswein_liegt_bei_null():
    """Die Zahl heisst „besser oder schlechter als üblich für dieses Geld". Wer genau
    auf der Kurve liegt, muss null bekommen — sonst bedeutet das Vorzeichen nichts."""
    wines = [_wein(10 * 1.5 ** i, 4.0) for i in range(20)]
    _je_typ(wines, "valueScore", None)
    mitte = sum(w["valueScore"] for w in wines) / len(wines)
    assert abs(mitte) < 1e-9, mitte


def test_wenig_bewertete_weine_werden_gedaempft():
    """Eine 4.6 aus zwölf Bewertungen ist keine 4.6 aus zwölftausend."""
    viele = _wein(10.0, 4.6, anzahl=12000)
    wenige = _wein(10.0, 4.6, anzahl=12)
    wines = [viele, wenige] + [_wein(8 + i, 4.0) for i in range(20)]
    _je_typ(wines, "valueScore", None)
    assert viele["valueScore"] > wenige["valueScore"] > 0


def _zeile(
    preis,
    note,
    anzahl=500,
    typ_name="Irgendein Wein",
    typ="ausgewogen",
    status=VivinoStatus.EXACT,
    konfidenz="exact",
    preis_konfidenz=PriceConfidence.HIGH,
):
    from winecheck.stiltyp import Einordnung

    row = WineRow(
        name=typ_name, vintage=2022, dedup_key=f"{typ_name}-{preis}",
        offers=[Offer(retailer="coop", name=typ_name)],
        prices=[RetailerPrice(retailer="coop", price_per_bottle_incl_vat=preis,
                              price_raw=preis, price_raw_basis="", url="",
                              price_confidence=preis_konfidenz)],
        vivino=VivinoResult(status=status, query="q", url="u", note="n",
                            rating=note, rating_count=anzahl,
                            match_confidence=konfidenz),
    )
    # Der Typ wird gesetzt, nicht erschlossen: geprüft wird hier die Wertrechnung,
    # nicht die Einordnung.
    row._stil = Einordnung(typ=typ, stufe=1, signale=["gesetzt"])
    return row


def test_aggregate_fuehrt_beide_kennzahlen_in_derselben_zeile():
    """Der Kern des Befunds: vorher trug eine Zeile nur die eine Zahl, und die andere
    lag in einem anderen Ausgabekanal. Vergleichen konnte man sie nicht."""
    rows = [_zeile(8 + i, 3.8 + (i % 5) * 0.1, typ_name=f"Wein {i}") for i in range(30)]
    compute_scores(rows)
    mit_beiden = [r for r in rows if r.value_score is not None and r.wert_score is not None]
    assert len(mit_beiden) >= 25, "beide Zahlen müssen an derselben Zeile hängen"
    # Sie sind bewusst verschieden — verschiedene Skalen, verschiedene Gruppierung.
    assert any(abs(r.value_score) > 1 for r in mit_beiden), "value_score ist 0..100"
    assert all(abs(r.wert_score) < 3 for r in mit_beiden), "wert_score ist ein Rest um null"


def _gemischter_bestand():
    """Ein Bestand, der jeden Sonderfall enthält, an dem die Kanäle auseinanderlaufen.

    Die Mischung ist der Punkt: ``unbekannt`` neben echten Typen, ein
    Produzenten-Mittelwert, ein unbestätigter Treffer, eine unsichere Gebindegrösse.
    Ein Bestand aus lauter Normalfällen bewies gar nichts — die Abweichung entstand
    ausschliesslich an den Rändern.
    """
    rows = []
    for typ in ("ausgewogen", "fruchtsuess", "unbekannt"):
        for i in range(14):
            rows.append(_zeile(
                7 + i * 2.5, 3.8 + (i % 6) * 0.1, typ=typ,
                typ_name=f"{typ} Wein {i}",
            ))
    rows.append(_zeile(6.0, 4.3, typ="unbekannt", typ_name="Produzentenmittel",
                       status=VivinoStatus.WINERY_LEVEL, konfidenz="winery_level"))
    rows.append(_zeile(9.2, 4.1, typ="ausgewogen", typ_name="Unbestaetigt",
                       konfidenz="fuzzy"))
    rows.append(_zeile(4.1, 4.2, typ="fruchtsuess", typ_name="Gebinde unklar",
                       preis_konfidenz=PriceConfidence.LOW))
    return rows


def test_csv_und_webseite_zeigen_dieselbe_zahl():
    """Der Kern von CQA-001, eine Ebene tiefer — und der Teil, der beim ersten Anlauf
    offen blieb.

    Die Formel in ein Modul zu ziehen genügt nicht: solange beide Kanäle ihr
    *unterschiedliche Stichproben und Gruppenschlüssel* übergeben, stehen weiterhin
    zwei Zahlen unter einem Namen. Am echten Bestand waren es 295 von 1010, bis zu
    0.132 auf einer Skala von rund ±0.5 — verursacht von 22 Produzenten-Mittelwerten,
    die nur die CSV mitrechnete, und von ``unbekannt``, das nur die Seite als eigene
    Gruppe führte.
    """
    from winecheck.report.diff import snapshot
    from winecheck.report.site import (
        MARKTPLATZ_QUELLEN,
        _add_value_scores,
        _sorten,
        _wine_from_snapshot,
    )

    rows = _gemischter_bestand()
    compute_scores(rows)

    # Derselbe Weg, den cli.site geht.
    wines = [_wine_from_snapshot(d) for d in snapshot(rows)]
    for w in wines:
        haendler = set(w.get("retailers") or [])
        w["marketplace"] = bool(haendler & MARKTPLATZ_QUELLEN)
        w["swiss"] = bool(haendler - MARKTPLATZ_QUELLEN)
        w["grapes"] = _sorten(w)
    _add_value_scores(wines)

    seite = {w["key"]: w.get("valueScoreAll") for w in wines}
    assert any(v is not None for v in seite.values()), "die Seite rechnet nichts"

    for row in rows:
        # Die einzige erlaubte Differenz ist die Rundung der CSV-Spalte auf drei
        # Stellen — 17 Ziffern in einer Tabelle helfen niemandem. Alles darüber ist
        # eine Abweichung in der Rechnung.
        assert row.wert_score == pytest.approx(seite[row.dedup_key], abs=5.1e-4), (
            f"{row.name}: CSV {row.wert_score} gegen Seite {seite[row.dedup_key]}"
        )


def test_der_produzentenmittelwert_bekommt_keine_zahl():
    """``winery_level`` ist nicht die Note dieses Weins — auch nicht als Datenpunkt in
    der Regression. Mouton Cadet für CHF 9.95 trüge sonst die 4.6 von Château Mouton
    Rothschild."""
    rows = _gemischter_bestand()
    compute_scores(rows)
    mittel = next(r for r in rows if r.name == "Produzentenmittel")
    assert mittel.wert_score is None
    assert not mittel.wert_rankable()


def test_unbestaetigt_rechnet_mit_rankt_aber_nicht():
    """Die Trennung, um die es geht: in die Regression ja, an die Spitze nein.

    Fuzzy-Treffer herauszunehmen würde die Gruppen ausdünnen — sie 86 Weine kosten
    ihre Zahl, und die Kurven werden schlechter für alle. Sie ranken zu lassen kostet
    im Zweifel den ersten Platz an einen falsch zugeordneten Wein.
    """
    rows = _gemischter_bestand()
    compute_scores(rows)
    unbestaetigt = next(r for r in rows if r.name == "Unbestaetigt")
    assert unbestaetigt.wert_score is not None, "muss mitrechnen"
    assert not unbestaetigt.wert_rankable(), "darf nicht ranken"


def test_unsichere_gebindegroesse_bekommt_gar_keine_zahl():
    """Ein falsch umgerechneter Literpreis erzeugt einen Scheinsieger, und zwar genau
    an der Spitze, wo am meisten hingesehen wird.

    Festgehalten wird hier, *wo* der Schutz sitzt: nicht in einer eigenen Prüfung der
    Rangliste, sondern in :attr:`WineRow.best_price`, das ``PriceConfidence.LOW`` gar
    nicht durchlässt. Ohne Preis keine Regression, ohne Regression keine Zahl. Der Test
    bewacht diese Kette — wer ``best_price`` einmal lockert, muss hier vorbei.
    """
    rows = _gemischter_bestand()
    compute_scores(rows)
    unklar = next(r for r in rows if r.name == "Gebinde unklar")
    assert unklar.best_price is None, "LOW darf nicht als Preis gelten"
    assert unklar.wert_score is None
    assert unklar.value_score is None
    assert not unklar.wert_rankable()


def test_unbekannt_ist_keine_eigene_gruppe():
    """„Kein Typ" ist keine Machart. Eine eigene Kurve darüber hiesse, aus dem Fehlen
    einer Information eine Erwartung abzuleiten — und genau daran liefen die beiden
    Kanäle auseinander."""
    from winecheck.wert import _typ_gruppe

    assert _typ_gruppe({"typ": "unbekannt"}) == ""
    assert _typ_gruppe({"typ": ""}) == ""
    assert _typ_gruppe({}) == ""
    assert _typ_gruppe({"typ": "straff_herb"}) == "straff_herb"


def test_der_resttopf_wird_auch_nach_sorte_geteilt():
    """Der teuerste Fehler dieser Rechnung, und er stand nicht im Verdacht.

    Weine mit Stil-Typ bekamen eine zweite Ebene nach Sorte, der Resttopf nicht. Am echten
    Bestand hiess das: 38 Champagner mit Medianpreis CHF 42.42 auf einer Kurve mit 30
    Schaumweinen zu CHF 10.86. Wer einen Champagner gegen Prosecco normalisiert, weil er
    von beiden die Machart nicht kennt, misst den Preisunterschied zweier Kategorien.

    Sichtbar war es an der Spitze: Weine ohne Typ stellten 8.5 Prozent der rankbaren Menge
    und 32 Prozent der ersten 25 Plätze. Nach der Korrektur 20 Prozent.
    """
    teuer = [_wein(38 + i, 4.2, typ="unbekannt", sorte="champagner") for i in range(14)]
    billig = [_wein(8 + i * 0.4, 4.2, typ="unbekannt", sorte="schaumwein") for i in range(14)]
    wines = teuer + billig
    _je_typ(wines, "valueScore", None)

    # Gleiche Note, sehr verschiedene Preise: ohne die Sortenteilung stünden die billigen
    # weit im Plus und die teuren weit im Minus — allein wegen ihrer Kategorie.
    assert all(abs(w["valueScore"]) < 0.15 for w in wines), (
        "die Sorte muss trennen, was sich preislich nicht vergleichen lässt: "
        f"Champagner {[round(w['valueScore'], 2) for w in teuer[:3]]}, "
        f"Schaumwein {[round(w['valueScore'], 2) for w in billig[:3]]}"
    )


def test_eine_zu_duenne_sorte_faellt_auf_den_ganzen_topf_zurueck():
    """Drei Weisse gegen vier Rosés gerechnet wäre keine Erwartung, sondern ein Zufall.
    Leer bleiben darf trotzdem keiner."""
    viele = [_wein(10 + i, 4.0, typ="unbekannt", sorte="rot") for i in range(14)]
    wenige = [_wein(12 + i, 4.0, typ="unbekannt", sorte="rose") for i in range(3)]
    wines = viele + wenige
    _je_typ(wines, "valueScore", None)
    assert all("valueScore" in w for w in wines), "keiner darf ohne Zahl bleiben"


def test_die_note_wird_vor_der_seltenheit_gerundet():
    """Vivino liefert float32: 4.2 kommt als 4.199999809265137 an.

    Ungerundet zählte ``x >= r - 1e-9`` das als eigene Notenstufe — eine Stufe, die es nur
    in der Zahlendarstellung gibt, macht eine Note seltener als sie ist. Gemessen bis zu
    0.083 wirksame Note geschenkt, nach der Preisformel rund 31 Prozent Preisvorteil.
    """
    import struct

    def als_float32(x: float) -> float:
        return struct.unpack("f", struct.pack("f", x))[0]

    sauber = [{"rating": 4.2, "price": 20.0} for _ in range(30)]
    schmutzig = [{"rating": als_float32(4.2), "price": 20.0} for _ in range(30)]
    assert schmutzig[0]["rating"] != 4.2, "sonst prüft der Test nichts"

    note_sauber = _wirksame_note(sauber + [{"rating": 4.5, "price": 20.0}] * 3)
    note_schmutzig = _wirksame_note(schmutzig + [{"rating": 4.5, "price": 20.0}] * 3)
    assert note_sauber(4.2) == pytest.approx(note_schmutzig(als_float32(4.2)))


def test_kritikernote_zaehlt_als_fremdbewertung():
    """Sonst widerspricht sich der Bericht: 41 Weine standen unter „Ohne Fremdbewertung"
    und trugen in derselben CSV einen Preis-Leistungs-Wert, den ``ranking_rating`` aus
    genau dieser Kritikernote gebildet hatte."""
    row = _zeile(22.40, None, typ_name="Nur Parker")
    row.vivino = None
    row.critics = {"parker": (93.0, "moevenpick")}
    assert row.has_any_rating
    assert row.ranking_rating()[0] is not None
    # In die Preis-Leistungs-Rangfolge kommt er trotzdem nicht: eine Parker-93 und eine
    # Vivino-4.3 liegen auf verschiedenen Skalen.
    assert not row.wert_rankable()


def test_die_neue_kennzahl_treibt_die_rangliste():
    """Spec §6 verlangte Parallelbetrieb, „bis die Verteilung geprüft ist". Sie ist
    geprüft, und die Umstellung ist erfolgt.

    Gemessen am Bestand von 1473 Weinen: global nach ``value_score`` sortiert besetzten
    die Weine über CHF 80 neunzehn der ersten 25 Plätze und die Klasse unter CHF 10 fiel
    ganz heraus — die Zahl ist eine Rangposition *innerhalb* der Klasse und über Klassen
    hinweg nicht vergleichbar. Nach ``wert_score`` verteilt sich dieselbe Spitze auf
    17/4/3/1/0 über die Klassen, weil der Preis darin herausgerechnet ist.

    Der Sortierschlüssel darf ausschliesslich über :meth:`WineRow.wert_rankable` laufen —
    ungeschützt führten sechs Produzenten-Mittelwerte und zwei unbestätigte Zuordnungen
    die ersten 25 an.
    """
    from pathlib import Path

    pdf = (Path(__file__).resolve().parents[1]
           / "src/winecheck/report/pdf_out.py").read_text(encoding="utf-8")
    assert "wert_score" in pdf
    assert "wert_rankable" in pdf, "ohne die Schutzregel darf nicht sortiert werden"
    assert "value_score" not in pdf, "die alte Zahl gehört in keinen Sortierschlüssel mehr"

    diff = (Path(__file__).resolve().parents[1]
            / "src/winecheck/report/diff.py").read_text(encoding="utf-8")
    assert "wert_rankable" in diff


def test_die_warenwelten_werden_getrennt_gerechnet():
    """Ohne die Trennung standen 15 der 20 empfohlenen Weine nur beim Vivino-Marktplatz,
    in zwei Preisklassen alle vier — in einem Heft mit dem Titel „Aktionen der Schweizer
    Weinhändler".

    Nicht aus einem Fehler der Rechnung: der Marktplatz trägt 640 der 924 rankbaren Weine,
    weil seine Noten von Vivino selbst kommen und keinen Namensabgleich brauchen. Aber die
    beiden Welten haben ein eigenes Preisniveau, und über eine gemeinsame Erwartungskurve
    gelegt wird der systematische Unterschied zu einer Aussage über die einzelnen Weine.
    """
    # Zwei Welten mit eigenem Preisniveau — der Marktplatz liefert aus dem Ausland und ist
    # bei gleicher Note systematisch günstiger. Genau dieser Unterschied darf keine
    # Aussage über die einzelnen Weine werden.
    rows = []
    for i in range(14):
        rows.append(_zeile(20 + i * 2, 4.0 + (i % 4) * 0.1, typ_name=f"Handel {i}"))
    for i in range(14):
        r = _zeile(9 + i, 4.0 + (i % 4) * 0.1, typ_name=f"Markt {i}")
        r.prices[0].retailer = "vivinoshop"
        r.offers[0].retailer = "vivinoshop"
        rows.append(r)
    compute_scores(rows)

    assert all(r.wert_score_welt is not None for r in rows), "beide Welten brauchen eine Zahl"

    # In der eigenen Welt liegt der Durchschnittswein jeder Welt bei null. Über beide
    # gerechnet verschiebt das billigere Preisniveau die ganze Marktplatz-Gruppe nach oben
    # — und das wäre eine Aussage über ihre Weine, die keiner von ihnen verdient hat.
    def mittel(feld, marktplatz):
        g = [r for r in rows if (r.prices[0].retailer == "vivinoshop") is marktplatz]
        return sum(getattr(r, feld) for r in g) / len(g)

    # Toleranz, weil die Spalte auf drei Stellen gerundet ist — nicht, weil die Rechnung
    # ungenau wäre.
    assert abs(mittel("wert_score_welt", True)) < 1e-3
    assert abs(mittel("wert_score_welt", False)) < 1e-3
    assert mittel("wert_score", True) > mittel("wert_score", False) + 0.1, (
        "über beide Welten gerechnet steigt der Marktplatz allein wegen seines "
        "Preisniveaus — deshalb gibt es die getrennte Zahl"
    )


def test_das_pdf_sortiert_nach_der_zahl_der_eigenen_welt():
    """Im ganzen Bericht muss P/L dasselbe bedeuten: den Vergleich mit der eigenen Welt.
    Sonst muss der Leser je Abschnitt raten, gegen was gerechnet wurde."""
    from pathlib import Path

    pdf = (Path(__file__).resolve().parents[1]
           / "src/winecheck/report/pdf_out.py").read_text(encoding="utf-8")
    assert "wert_score_welt" in pdf
    assert "_schweizer_handel" in pdf, "die Listen müssen nach Warenwelt getrennt sein"


def test_die_rangliste_wird_nur_ueber_die_schutzregel_sortiert():
    """Der eine Fehler, der hier weh täte: nach ``wert_score`` sortieren und die
    Eignung vergessen. Dann steht ein Produzenten-Mittelwert auf Platz eins."""
    rows = _gemischter_bestand()
    compute_scores(rows)

    rankbar = [r for r in rows if r.wert_rankable()]
    assert rankbar, "sonst prüft der Test nichts"
    for r in rankbar:
        assert r.vivino.status in (VivinoStatus.EXACT, VivinoStatus.WINE_LEVEL)
        assert r.vivino.match_confidence in ("exact", "wine_level")
        assert r.best_price is not None


def test_die_csv_zeigt_beide():
    from winecheck.report.csv_out import LEAD_COLUMNS

    assert "value_score" in LEAD_COLUMNS and "wert_score" in LEAD_COLUMNS

"""Das Zeichen der Seite: ein Rebberg über dem See.

Warum überhaupt eines
---------------------
Wer die Seite auf den Startbildschirm legt, bekam ein graues Feld mit einem „S" —
iOS nimmt den ersten Buchstaben des Titels, wenn keine Grafik hinterlegt ist.
Dieses Modul liefert die fehlende Grafik in zwei Ausführungen:

* ``SVG_MARK``  — das Zeichen als Vektor, für den Seitenkopf. Bleibt bei jeder
  Vergrösserung scharf.
* ``schreibe_icons()`` — ``apple-touch-icon.png`` (180 px) und ``icon-512.png``.
  iOS akzeptiert für den Startbildschirm **kein** SVG; ohne PNG bliebe es beim
  grauen Buchstaben.

Das Motiv
---------
Terrassierte Rebberge, die zum See hin abfallen, dahinter die Berge — die Lavaux-
Ansicht, die man von der Schweizer Rebfläche im Kopf hat. Vereinfacht auf flache
Farbflächen: das Zeichen ist auf dem Startbildschirm rund 60 px gross, und dort
überlebt keine Textur. Was bei dieser Grösse trägt, sind die drei waagrechten
Bänder — Himmel, See, Rebberg — und die geschwungenen Terrassenlinien.

Eine Geometrie, zwei Ausgaben
-----------------------------
Vektor und Raster stammen aus derselben Beschreibung: ``_formen()`` liefert die
Flächen in Einheitskoordinaten (0…1), ``_nach_pil()`` und ``_nach_svg()`` setzen
sie um. Zwei getrennt gepflegte Zeichnungen wären früher oder später
auseinandergelaufen.

Gezeichnet wird fürs PNG vierfach vergrössert und dann verkleinert: Pillow glättet
beim Zeichnen nicht, und ohne diesen Umweg werden die Berggrate zu Treppen.
"""

from __future__ import annotations

from pathlib import Path

# -- Farben ---------------------------------------------------------------
HIMMEL_OBEN = (176, 208, 227)
HIMMEL_UNTEN = (223, 236, 240)
BERG_FERN = (148, 172, 193)
BERG_NAH = (105, 134, 160)
SCHNEE = (238, 245, 249)
SEE = (116, 160, 190)
SEE_HELL = (147, 185, 208)
UFER = (86, 120, 82)
REB_DUNKEL = (62, 102, 52)
REB = (104, 147, 62)
TERRASSE = (158, 191, 96)


# -- Kurven ----------------------------------------------------------------
def _bezier(p0, p1, p2, p3, n: int = 60):
    """Punkte einer kubischen Bézierkurve.

    Reicht für beide Ausgaben: Pillow braucht Punktfolgen, und fürs SVG wird die
    Kurve ohnehin als ``C``-Befehl geschrieben — die Punktfolge dient dort nur der
    Kontrolle.
    """
    aus = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        aus.append(
            (
                u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
            )
        )
    return aus


#: Die Hangkante: von links oben nach rechts unten, nach oben ausgebaucht. Der
#: Rebberg liegt darunter, der See darüber — eine Kurve trennt das ganze Bild.
_HANG = ((-0.04, 0.30), (0.30, 0.42), (0.58, 0.62), (1.04, 0.70))

#: Der Grat der nahen Bergkette. Rechts höher als links, wie am Genfersee von
#: Westen aus gesehen.
_GRAT_NAH = [
    (0.30, 0.375), (0.40, 0.315), (0.47, 0.345), (0.56, 0.255),
    (0.63, 0.300), (0.71, 0.215), (0.78, 0.270), (0.86, 0.230),
    (0.94, 0.285), (1.02, 0.255),
]
#: Die fernere Kette liegt dahinter und flacher — sie gibt dem Himmel Tiefe.
_GRAT_FERN = [
    (-0.02, 0.360), (0.10, 0.320), (0.20, 0.352), (0.33, 0.300),
    (0.45, 0.340), (0.58, 0.292), (0.70, 0.330), (0.83, 0.286),
    (1.02, 0.322),
]

#: Waagrechter Horizont: wo der See an die Berge stösst.
_SEEKANTE = 0.395

#: Die Rebzeilen laufen **quer** zum Hang, also den Abhang hinunter — nicht parallel
#: zur Hangkante. Genau so steht die Rebe im Lavaux: die Zeilen fallen zum See hin
#: ab, und die Terrassenmauern kreuzen sie waagrecht. Eine Zeichnung mit Bändern
#: längs der Kante sah aus wie ein gestreifter Hügel, nicht wie ein Rebberg.
#: Zehn Zeilen, nicht mehr. Bei dreizehn lagen sie auf dem Startbildschirm rund
#: vier Pixel auseinander und wurden zum Gitter statt zum Rebberg.
_ZEILEN = 10
#: Richtung einer Zeile, von der Hangkante aus abwärts. Nach links geneigt, damit
#: die Zeilen die Kante wirklich kreuzen statt an ihr entlangzulaufen.
_ZEILE_RICHTUNG = (-0.34, 1.0)
_ZEILE_BREITE = 0.021

#: Zwei Terrassenmauern quer über die Zeilen. Sie geben dem Hang die Stufen, ohne
#: dass die Zeilen ihre Richtung verlieren.
_MAUERN = (0.20, 0.44)


def _hang_versetzt(d: float):
    """Die Hangkante, um ``d`` nach unten geschoben."""
    return tuple((x, y + d) for x, y in _HANG)


def _zeilen():
    """Die Rebzeilen als Vierecke: von der Hangkante schräg abwärts aus dem Bild.

    Startpunkte liegen gleichmässig auf der Hangkante. Weil die Kante nach rechts
    abfällt und die Zeilen nach links unten laufen, bleibt jede Zeile von selbst
    unterhalb der Kante — es braucht keinen Beschnitt.
    """
    kante = _bezier(*_HANG, n=_ZEILEN * 3)
    rx, ry = _ZEILE_RICHTUNG
    aus = []
    for i in range(_ZEILEN + 1):
        # Etwas über den rechten Rand hinaus beginnen: sonst bleibt dort ein
        # zeilenloses Dreieck stehen.
        t = i / _ZEILEN
        idx = min(len(kante) - 1, int(t * (len(kante) - 1) * 1.06))
        x0, y0 = kante[idx]
        # Nach unten hin breiter — die Zeile kommt auf den Betrachter zu.
        b0 = _ZEILE_BREITE * 0.45
        b1 = _ZEILE_BREITE * (1.5 + 0.5 * t)
        laenge = 1.5
        x1, y1 = x0 + rx * laenge, y0 + ry * laenge
        aus.append([(x0 - b0, y0), (x0 + b0, y0), (x1 + b1, y1), (x1 - b1, y1)])
    return aus


def _formen() -> list[tuple[str, tuple, dict]]:
    """Das Bild als Liste von Anweisungen in Einheitskoordinaten.

    Jeder Eintrag ist ``(art, daten, optionen)``. ``art`` ist eines von
    ``verlauf``, ``polygon``, ``kurvenband`` — mehr braucht das Motiv nicht.
    """
    f: list[tuple[str, tuple, dict]] = []

    # Himmel als senkrechter Verlauf: unten heller, wie Dunst über dem Wasser.
    f.append(("verlauf", (0.0, 1.0, HIMMEL_OBEN, HIMMEL_UNTEN), {}))

    # Die beiden Bergketten, jede bis zur Seekante heruntergezogen.
    for grat, farbe in ((_GRAT_FERN, BERG_FERN), (_GRAT_NAH, BERG_NAH)):
        f.append(("polygon", (grat + [(1.04, _SEEKANTE), (-0.04, _SEEKANTE)], farbe), {}))

    # Schnee auf den drei höchsten Gipfeln der nahen Kette. Kleine Dreiecke —
    # bei 60 px bleiben davon helle Tupfer, und genau die machen den Berg zum Berg.
    for gx, gy in ((0.56, 0.255), (0.71, 0.215), (0.86, 0.230)):
        f.append(("polygon", ([(gx, gy), (gx + 0.036, gy + 0.045),
                               (gx + 0.012, gy + 0.032), (gx - 0.030, gy + 0.048)], SCHNEE), {}))

    # Der See füllt alles unter der Seekante; der Rebberg legt sich gleich darüber.
    f.append(("polygon", ([(-0.04, _SEEKANTE), (1.04, _SEEKANTE),
                           (1.04, 1.04), (-0.04, 1.04)], SEE), {}))
    # Zwei helle Streifen als Lichtreflex — ohne sie ist der See eine tote Fläche.
    for oben, hoehe in ((0.455, 0.016), (0.520, 0.011)):
        f.append(("polygon", ([(0.30, oben), (1.04, oben),
                               (1.04, oben + hoehe), (0.30, oben + hoehe)], SEE_HELL), {}))

    # Der Rebberg: alles unterhalb der Hangkante.
    f.append(("kurvenband", (_HANG, REB_DUNKEL), {"bis_unten": True}))

    # Die Rebzeilen, quer zum Hang und den Abhang hinunter.
    for viereck in _zeilen():
        f.append(("polygon", (viereck, TERRASSE), {}))

    # Zwei Terrassenmauern legen sich waagrecht über die Zeilen. Sie stufen den
    # Hang, ohne die Richtung der Zeilen zu übernehmen — im Gegenteil, der
    # Kreuzungswinkel macht erst sichtbar, dass die Zeilen quer stehen.
    for d in _MAUERN:
        f.append(("kurvenband", (_hang_versetzt(d), REB), {"dicke": 0.030}))

    # Ein schmaler dunkler Saum an der Kante trennt Hang und Wasser. Zuletzt
    # gezeichnet, damit keine Zeile über den See ragt.
    f.append(("kurvenband", (_HANG, UFER), {"dicke": 0.020}))
    return f


# -- Ausgabe: Pixel --------------------------------------------------------
def _nach_pil(d, n: float) -> None:
    """Malt die Formen auf eine Fläche der Kantenlänge ``n``."""
    def p(pt):
        return (pt[0] * n, pt[1] * n)

    for art, daten, opt in _formen():
        if art == "verlauf":
            y0, y1, c0, c1 = daten
            hoehe = max(1, int((y1 - y0) * n))
            for i in range(hoehe):
                t = i / max(1, hoehe - 1)
                d.line(
                    [(0, y0 * n + i), (n, y0 * n + i)],
                    fill=tuple(round(a + (b - a) * t) for a, b in zip(c0, c1)),
                )
        elif art == "polygon":
            punkte, farbe = daten
            d.polygon([p(x) for x in punkte], fill=farbe)
        elif art == "kurvenband":
            kurve, farbe = daten
            pts = _bezier(*kurve)
            if opt.get("bis_unten"):
                d.polygon([p(x) for x in pts] + [(n * 1.04, n * 1.04), (-n * 0.04, n * 1.04)],
                          fill=farbe)
            else:
                dicke = opt.get("dicke", 0.02)
                unten = [(x, y + dicke) for x, y in reversed(pts)]
                d.polygon([p(x) for x in pts] + [p(x) for x in unten], fill=farbe)


def schreibe_icons(ziel: Path) -> list[Path]:
    """Legt ``apple-touch-icon.png`` und ``icon-512.png`` in ``ziel`` ab.

    Gibt die geschriebenen Pfade zurück. Fehlt Pillow, wird nichts geschrieben und
    eine leere Liste zurückgegeben — die Seite funktioniert auch ohne Icons, nur
    der Startbildschirm sieht wieder karg aus. Daran soll ein Bericht nicht
    scheitern.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:  # pragma: no cover — Pillow kommt über matplotlib mit
        return []

    ziel.mkdir(parents=True, exist_ok=True)
    geschrieben: list[Path] = []
    for name, kante in (("apple-touch-icon.png", 180), ("icon-512.png", 512)):
        gross = kante * 4
        bild = Image.new("RGB", (gross, gross), HIMMEL_OBEN)
        _nach_pil(ImageDraw.Draw(bild), gross)
        bild = bild.resize((kante, kante), Image.LANCZOS)
        pfad = ziel / name
        bild.save(pfad, "PNG", optimize=True)
        geschrieben.append(pfad)
    return geschrieben


# -- Ausgabe: Vektor -------------------------------------------------------
def _nach_svg(kante: int = 64) -> str:
    """Setzt dieselben Formen in SVG-Elemente um."""
    def z(v: float) -> str:
        return f"{v * kante:.2f}".rstrip("0").rstrip(".")

    def pfad(punkte) -> str:
        return " ".join(f"{z(x)},{z(y)}" for x, y in punkte)

    teile: list[str] = []
    for art, daten, opt in _formen():
        if art == "verlauf":
            _, _, c0, c1 = daten
            teile.append(
                f'<linearGradient id="hi" x1="0" y1="0" x2="0" y2="1">'
                f'<stop offset="0" stop-color="rgb{c0}"/>'
                f'<stop offset="1" stop-color="rgb{c1}"/></linearGradient>'
            )
            teile.append(f'<rect width="{kante}" height="{kante}" fill="url(#hi)"/>')
        elif art == "polygon":
            punkte, farbe = daten
            teile.append(f'<polygon points="{pfad(punkte)}" fill="rgb{farbe}"/>')
        elif art == "kurvenband":
            (p0, p1, p2, p3), farbe = daten
            if opt.get("bis_unten"):
                dd = (f"M{z(p0[0])},{z(p0[1])} C{z(p1[0])},{z(p1[1])} "
                      f"{z(p2[0])},{z(p2[1])} {z(p3[0])},{z(p3[1])} "
                      f"L{z(1.04)},{z(1.04)} L{z(-0.04)},{z(1.04)} Z")
            else:
                t = opt.get("dicke", 0.02)
                dd = (f"M{z(p0[0])},{z(p0[1])} C{z(p1[0])},{z(p1[1])} "
                      f"{z(p2[0])},{z(p2[1])} {z(p3[0])},{z(p3[1])} "
                      f"L{z(p3[0])},{z(p3[1] + t)} C{z(p2[0])},{z(p2[1] + t)} "
                      f"{z(p1[0])},{z(p1[1] + t)} {z(p0[0])},{z(p0[1] + t)} Z")
            teile.append(f'<path d="{dd}" fill="rgb{farbe}"/>')

    inneres = "".join(teile)
    # Der Beschnitt hält alles im abgerundeten Feld: die Kurven laufen bewusst über
    # den Rand hinaus, damit an den Kanten keine Lücke entsteht.
    return (
        f'<svg class="mark" viewBox="0 0 {kante} {kante}" role="img" '
        f'aria-label="Rebberg über dem See" focusable="false">'
        f'<defs><clipPath id="mk"><rect width="{kante}" height="{kante}" rx="{kante * 0.22:.0f}"/>'
        f"</clipPath></defs>"
        f'<g clip-path="url(#mk)">{inneres}</g></svg>'
    )


#: Das Zeichen für den Seitenkopf.
SVG_MARK = _nach_svg()

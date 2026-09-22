"""
Pasek mini-gry: jak go znalezc i jak z niego czytac.

    (@)|#########>          |
     ^      ^     ^         ^
     |      |     |         `- prawy koniec paska
     |      |     `- NIEBIESKA rybka: cel; plynie w losowa strone i zawraca
     |      `- ZOLTE wypelnienie: rosnie, dopoki trzymamy klawisz
     `- medalion z rybka (lewy koniec)

Caly modul to czyste patrzenie na piksele - zadnego klikania i zadnego
czytania pamieci gry.

Jak rozpoznajemy pasek, nie znajac z gory rozdzielczosci ani polozenia:

  1. dlugi, niski, dosc pelny prostokat zlozony z ciemnego koryta i/lub
     zoltego wypelnienia,
  2. w ktorym siedzi NIEBIESKA RYBKA - zaden staly element interfejsu jej
     nie ma (zmierzone: pasek 141-215 px rybki, linijki czatu 0),
  3. i ktory lezy POSRODKU okna w poziomie, w dolnej jego czesci - pasek
     zawsze tam wychodzi (zmierzone na oknie 1319 px: srodek paska w 660 px,
     czyli pol piksela od osi).

Te trzy warunki wystarczaja, zeby nie mylic paska z czatem, paskiem many ani
z cieniem pod pomostem - i zeby dzialaly na kazdej rozdzielczosci.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

log = logging.getLogger("rybak")

# Domyslne tempo wypelniania, gdy nie zdazylismy go jeszcze zmierzyc [px/s].
DOMYSLNE_TEMPO = 190.0


def _channels(rgb: np.ndarray):
    a = rgb.astype(np.int16)
    return a[:, :, 0], a[:, :, 1], a[:, :, 2]


def mask_trough(rgb: np.ndarray) -> np.ndarray:
    """Puste (jeszcze nienaladowane) wnetrze paska - ciemny granat/morski."""
    r, g, b = _channels(rgb)
    return (b > r + 8) & (r < 95) & (b >= 35) & (b <= 115) & (g >= r - 5)


def mask_fill(rgb: np.ndarray) -> np.ndarray:
    """Zolte wypelnienie."""
    r, g, b = _channels(rgb)
    return (r > 140) & (g > 130) & (r - b > 70) & (g - b > 60)


def mask_marker(rgb: np.ndarray) -> np.ndarray:
    """Niebieska strzalka - "rybka", w ktora trzeba trafic."""
    r, g, b = _channels(rgb)
    return (b > 100) & (b - r > 55) & (b - g > 30)


# ------------------------------------------------------------ szukanie paska

@dataclass
class Bar:
    x0: int          # pierwszy piksel wnetrza paska (start wypelnienia)
    x1: int          # ostatni piksel wnetrza
    y0: int          # gorny wiersz wnetrza
    y1: int          # dolny wiersz wnetrza

    @property
    def width(self) -> int:
        return self.x1 - self.x0 + 1

    def as_list(self):
        return [int(self.x0), int(self.y0), int(self.x1), int(self.y1)]

    @classmethod
    def from_list(cls, v):
        return cls(int(v[0]), int(v[2]), int(v[1]), int(v[3]))


def mask_frame(rgb: np.ndarray) -> np.ndarray:
    """Jasna, piaskowa obwodka paska - nad i pod korytem."""
    r, g, b = _channels(rgb)
    return (r > 115) & (r - b > 40) & (r >= g - 5) & (g >= b - 5)


def _has_frame(rgb: np.ndarray, x0: int, x1: int, y: int) -> bool:
    """Czy wiersz `y` na odcinku [x0, x1) wyglada na obwodke paska?"""
    h, w = rgb.shape[:2]
    if not (0 <= y < h) or x1 <= x0:
        return False
    row = mask_frame(rgb[y:y + 1, x0:x1])
    return float(row.mean()) >= 0.55


def kandydaci(rgb: np.ndarray, region=None):
    """
    Wszystkie poziome plamy "koryto lub wypelnienie" w obszarze, z miarami,
    po ktorych find_bar decyduje. Bez zadnego odsiewania - to jest material
    do diagnozy: gdy bot nie widzi paska, chcemy wiedziec, czy go w ogole nie
    ma na klatce, czy jest, tylko odpada na jednym warunku.

    Zwraca liste slownikow posortowana od najszerszej plamy.
    """
    import cv2

    h, w = rgb.shape[:2]
    if region is None:
        x0, y0, x1, y1 = 0, 0, w, h
    else:
        x0, y0, x1, y1 = region
        x0 = max(0, int(x0)); y0 = max(0, int(y0))
        x1 = min(w, int(x1)); y1 = min(h, int(y1))
    if x1 <= x0 or y1 <= y0:
        return []
    sub = rgb[y0:y1, x0:x1]

    m = (mask_trough(sub) | mask_fill(sub)).astype(np.uint8) * 255
    # Strzalka dzieli koryto na dwie czesci - scal w poziomie, zeby pasek
    # zostal jedna plama.
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((1, 31), np.uint8))

    n, _lab, stats, _c = cv2.connectedComponentsWithStats(m, 8)
    out = []
    for i in range(1, n):
        bw = int(stats[i, cv2.CC_STAT_WIDTH])
        bh = int(stats[i, cv2.CC_STAT_HEIGHT])
        if bw < 30 or bh < 3:
            continue                        # zwykly szum, nie ma o czym mowic
        bx = int(stats[i, cv2.CC_STAT_LEFT])
        by = int(stats[i, cv2.CC_STAT_TOP])
        ax0, ax1 = x0 + bx, x0 + bx + bw
        top, bot = y0 + by, y0 + by + bh - 1
        # Ile niebieskich pikseli "rybki" siedzi w tym pasie. To najlepszy
        # dowod, ze plama jest paskiem mini-gry, a nie elementem HUD-u:
        # niebieska strzalka pojawia sie tylko w mini-grze.
        pas = rgb[max(0, top - 8):min(h, bot + 9), ax0:ax1]
        rybka = int(mask_marker(pas).sum()) if pas.size else 0
        # Ile z plamy to ciemne koryto. Linijka czatu po sklejeniu liter tez
        # wyglada jak dlugi niski prostokat, ale koryta nie ma wcale -
        # zmierzone: pasek mini-gry 0.23-0.84, linijki czatu 0.00-0.22.
        wnetrze = rgb[top:bot + 1, ax0:ax1]
        koryto = (float(mask_trough(wnetrze).mean()) if wnetrze.size else 0.0)
        out.append({
            "x0": ax0, "x1": ax1 - 1, "y0": top, "y1": bot,
            "w": bw, "h": bh, "rybka": rybka, "koryto": koryto,
            "pelnosc": int(stats[i, cv2.CC_STAT_AREA]) / float(bw * bh),
            "obwodka": any(_has_frame(rgb, ax0, ax1, yy)
                           for yy in (top - 1, top - 2, bot + 1, bot + 2)),
        })
    return sorted(out, key=lambda d: -d["w"])


def _styka_sie(k, prostokaty) -> bool:
    """Czy kandydat zachodzi na ktorys z zakazanych prostokatow?"""
    for zx0, zy0, zx1, zy1 in prostokaty or ():
        if (k["x0"] < zx1 and k["x1"] > zx0
                and k["y0"] < zy1 and k["y1"] > zy0):
            return True
    return False


def find_bar(rgb: np.ndarray, region=None, min_width: int = 110,
             min_height: int = 6, max_height: int = 24,
             require_frame: bool = True, forbid=None) -> Bar | None:
    """
    Znajdz pasek mini-gry na klatce. `region` = (x0, y0, x1, y1) w pikselach
    wzgledem klatki; None = cala klatka.

    Szukamy dlugiej, niskiej, poziomej plamy zlozonej z pustego koryta i/lub
    zoltego wypelnienia. Trawa i woda odpadaja, bo maja niebieski <= czerwony;
    ciemne cienie odpadaja na warunku wysokosci i "pelnosci" prostokata.

    Progi sa parametrami, bo nie kazdy klient rysuje pasek tak samo duzo:
    przy innej rozdzielczosci okna bywa wezszy i nizszy, a bywa tez, ze nie ma
    piaskowej obwodki. Wtedy ustawia je  python run.py --pick-bar.

    `forbid` to prostokaty, ktorych nigdy nie wolno uznac za pasek - wlasne
    paski HP i many. Ich puste czesci maja ten sam ciemny granat co koryto
    mini-gry, wiec przy zle dobranym obszarze szukania bot potrafilby "znalezc"
    pasek w rogu ekranu i trzymac spacje w nieskonczonosc.
    """
    best = None
    for k in kandydaci(rgb, region):
        if k["w"] < min_width or not (min_height <= k["h"] <= max_height):
            continue
        if _styka_sie(k, forbid):
            continue
        if k["w"] < 4 * k["h"]:
            continue
        if k["pelnosc"] < 0.45:
            continue                       # plama ma byc pelnym prostokatem
        # Pasek ma nad i pod soba piaskowa obwodke. Bez tego warunku za pasek
        # robi sie czasem cien pod pomostem albo element HUD-u.
        if require_frame and not k["obwodka"]:
            continue
        if best is None or k["w"] > best["w"]:
            best = k
    if best is None:
        return None
    return Bar(x0=best["x0"], x1=best["x1"], y0=best["y0"], y1=best["y1"])


def read_bar(rgb: np.ndarray, bar: Bar, origin=(0, 0), extra_left: int = 0):
    """
    Odczyt stanu paska. `origin` = (x, y) lewego gornego rogu klatki wzgledem
    okna gry - dzieki temu mozna podac wyciety fragment zamiast calego ekranu.
    `extra_left` poszerza obszar szukania wypelnienia w lewo: przy pojawianiu
    sie paska jego lewy skraj bywa jeszcze przezroczysty i wykrywa sie o
    kilkanascie pikseli za daleko na prawo.

    Zwraca (fill_x, marker, alive):
      fill_x - x prawej krawedzi zoltego wypelnienia (None, gdy puste)
      marker - (srodek, lewa, prawa) niebieskiej strzalki albo None
      alive  - czy pasek w ogole jest jeszcze na ekranie

    UWAGA: strzalka jest rysowana NA pasku, wiec gdy wypelnienie wjedzie pod
    nia, jego krawedz przestaje byc widoczna i fill_x zatrzymuje sie na
    lewym brzegu strzalki. Wlasnie dlatego Fisher nie patrzy na goly odczyt,
    tylko przelicza polozenie wypelnienia z predkosci - patrz Fisher.play.
    """
    ox, oy = origin
    h, w = rgb.shape[:2]
    y0 = max(0, bar.y0 - oy)
    y1 = min(h, bar.y1 - oy + 1)
    # strzalka wystaje nad i pod pasek - szukamy jej w szerszym pasie
    my0 = max(0, bar.y0 - oy - 10)
    my1 = min(h, bar.y1 - oy + 11)
    x0 = max(0, bar.x0 - ox)
    x1 = min(w, bar.x1 - ox + 1)
    xw = max(0, bar.x0 - ox - max(0, extra_left))
    if y1 <= y0 or x1 <= x0:
        return None, None, False

    band = rgb[y0:y1, x0:x1]
    wide = rgb[y0:y1, xw:x1]
    fill = mask_fill(wide)
    trough = mask_trough(band)
    marker = mask_marker(rgb[my0:my1, xw:x1])

    alive = (int(mask_fill(band).sum() + trough.sum())
             > 0.15 * band.shape[0] * band.shape[1])

    fill_x = None
    cols = fill.sum(axis=0)
    # Prog dobieramy do tego, co widac, a nie do zalozonej wysokosci paska.
    # Sztywne "jedna trzecia wysokosci" zawodzilo, gdy pasek wykryl sie
    # wyzszy, niz jest naprawde: prog rosl, a zolty slup zostawal ten sam.
    if cols.size:
        szczyt = int(cols.max())
        prog = max(2, min(wide.shape[0] // 3, int(0.6 * szczyt)))
        solid = np.where(cols >= prog)[0]
        if solid.size:
            fill_x = int(solid.max()) + xw + ox

    marker_span = None
    mcols = marker.sum(axis=0)
    idx = np.where(mcols >= 3)[0]
    if idx.size:
        groups, start = [], idx[0]
        for a, b_ in zip(idx, idx[1:]):
            if b_ - a > 2:
                groups.append((start, a)); start = b_
        groups.append((start, idx[-1]))
        gs, ge = max(groups, key=lambda t: t[1] - t[0])
        marker_span = (int((gs + ge) / 2) + xw + ox,
                       int(gs) + xw + ox, int(ge) + xw + ox)

    return fill_x, marker_span, alive


def _slope(samples, window: float = 0.0) -> float | None:
    """
    Predkosc [px/s] z probek (t, x) - prosta regresja liniowa.

    `window` > 0 obcina probki do ostatnich tylu sekund. Przydaje sie przy
    rybce, ktora potrafi zawrocic: dluga srednia pokazywalaby wtedy ruch w
    strone, w ktora rybka juz nie plynie.
    """
    pts = [(t, x) for t, x in samples if x is not None]
    if window > 0 and pts:
        t_end = pts[-1][0]
        recent = [p for p in pts if t_end - p[0] <= window]
        if len(recent) >= 3:
            pts = recent
    if len(pts) < 3:
        return None
    t = np.array([p[0] for p in pts], dtype=float)
    x = np.array([p[1] for p in pts], dtype=float)
    t -= t[0]
    if t[-1] <= 0.01:
        return None
    return float(np.polyfit(t, x, 1)[0])


def _reflect(x: float, lo: float, hi: float) -> float:
    """Polozenie po odbiciu od koncow paska - rybka zawraca, nie znika."""
    if hi <= lo:
        return x
    span = hi - lo
    y = (x - lo) % (2 * span)
    if y < 0:
        y += 2 * span
    return lo + (y if y <= span else 2 * span - y)


def _marker_speed(marks) -> float:
    """
    Predkosc rybki [px/s] - liczona z krotkiego okna, bo rybka zmienia
    kierunek. Gdy ostatnie probki nie zgadzaja sie ze starszymi co do znaku,
    ufamy tylko tym najswiezszym: wlasnie zawrocila.
    """
    fast = _slope(marks, window=0.10)
    slow = _slope(marks, window=0.30)
    if fast is None:
        return slow or 0.0
    if slow is not None and fast * slow < 0:
        return fast                      # zawrocila - stara srednia klamie
    return fast


# ------------------------------------------------- szukanie bez kalibracji

#: W jakiej czesci okna w ogole ma sens szukac paska (ulamki szerokosci i
#: wysokosci). Pasek zawsze wychodzi posrodku i nisko, wiec waski, symetryczny
#: pas odsiewa czat (wyrownany do lewej), paski HP i many (lewy dolny rog) oraz
#: minimape - i robi to na kazdej rozdzielczosci, bo idzie za srodkiem okna.
OBSZAR = (0.25, 0.40, 0.75, 0.99)


def szukaj_paska(rgb: np.ndarray, obszar=OBSZAR) -> "Bar | None":
    """
    Znajdz pasek mini-gry na klatce BEZ zadnej kalibracji i bez niczego
    zapamietanego. To jest wejscie do calego modulu.

    Kryteria sa tak dobrane, zeby przezyly zmiane rozdzielczosci: zadne nie
    jest podane w bezwzglednych pikselach ekranu. Rozmiar paska liczymy
    wzgledem jego wlasnych proporcji, polozenie - wzgledem srodka okna, a
    tozsamosc rozstrzyga niebieska rybka, ktorej nie ma nigdzie indziej.
    """
    h, w = rgb.shape[:2]
    region = (int(obszar[0] * w), int(obszar[1] * h),
              int(obszar[2] * w), int(obszar[3] * h))
    najlepszy = None
    for k in kandydaci(rgb, region):
        if k["w"] < 60 or not (5 <= k["h"] <= 40):
            continue
        if k["w"] < 4 * k["h"]:              # ma byc dlugi i niski
            continue
        if k["pelnosc"] < 0.45:              # pelny prostokat, nie siatka liter
            continue
        if k["rybka"] < 15:                  # bez rybki to nie mini-gra
            continue
        if k["koryto"] < 0.12:               # linijka czatu nie ma koryta
            continue
        if abs((k["x0"] + k["x1"]) / 2 - w / 2) > 0.08 * w:
            continue                         # pasek stoi posrodku okna
        if najlepszy is None or k["w"] > najlepszy["w"]:
            najlepszy = k
    if najlepszy is None:
        return None
    y0, y1 = _dociagnij_wiersze(rgb, najlepszy)
    return Bar(x0=najlepszy["x0"], x1=najlepszy["x1"], y0=y0, y1=y1)


def _dociagnij_wiersze(rgb: np.ndarray, k) -> tuple:
    """
    Przytnij pasek do wierszy, ktore naprawde sa paskiem.

    Po co: plama, po ktorej go znajdujemy, bywa wyzsza niz sam pasek. Rybka
    jest rysowana NA nim i wystaje nad i pod, a jej ciemnogranatowy obrys
    wpada w te sama maske co puste koryto - wiec plama rosnie w pionie
    dokladnie tam, gdzie akurat plywa rybka.

    Samo w sobie nie brzmi grozne, ale odczyt wypelnienia wymaga, zeby zolty
    slup zajmowal jakas czesc WYSOKOSCI paska. Gdy wysokosc jest zawyzona
    dwukrotnie, prog rosnie dwukrotnie - i wypelnienie przestaje byc
    widoczne, mimo ze w grze pasek rosnie jak zwykle. Objawia sie to
    "co ktores lowienie", bo zalezy od tego, gdzie stala rybka w chwili
    znalezienia paska.

    Zostawiamy wiersze, w ktorych koryto albo wypelnienie zajmuje wiekszosc
    szerokosci - czyli wlasciwe cialo paska.
    """
    y0, y1 = k["y0"], k["y1"]
    x0, x1 = k["x0"], k["x1"] + 1
    h, w = rgb.shape[:2]
    y0 = max(0, min(y0, h - 1)); y1 = max(y0, min(y1, h - 1))
    x0 = max(0, min(x0, w - 1)); x1 = max(x0 + 1, min(x1, w))
    pas = rgb[y0:y1 + 1, x0:x1]
    if pas.size == 0:
        return k["y0"], k["y1"]
    cialo = (mask_trough(pas) | mask_fill(pas))
    udzial = cialo.mean(axis=1)
    dobre = np.where(udzial >= 0.5)[0]
    if dobre.size < 3:
        return k["y0"], k["y1"]
    return int(y0 + dobre.min()), int(y0 + dobre.max())


def opisz_kandydatow(rgb: np.ndarray, obszar=OBSZAR):
    """
    To samo, ale zwraca WSZYSTKICH kandydatow z powodem odrzucenia. Sluzy
    wylacznie do pokazania czlowiekowi, dlaczego bot czegos nie widzi.
    """
    h, w = rgb.shape[:2]
    region = (int(obszar[0] * w), int(obszar[1] * h),
              int(obszar[2] * w), int(obszar[3] * h))
    out = []
    for k in kandydaci(rgb, region):
        if k["w"] < 60 or not (5 <= k["h"] <= 40):
            powod = "za maly"
        elif k["w"] < 4 * k["h"]:
            powod = "za kwadratowy jak na pasek"
        elif k["pelnosc"] < 0.45:
            powod = "dziurawy - to raczej napis"
        elif k["rybka"] < 15:
            powod = "nie ma w nim niebieskiej rybki"
        elif k["koryto"] < 0.12:
            powod = "nie ma ciemnego koryta"
        elif abs((k["x0"] + k["x1"]) / 2 - w / 2) > 0.08 * w:
            powod = "nie jest posrodku okna"
        else:
            powod = None
        out.append((k, powod))
    return out

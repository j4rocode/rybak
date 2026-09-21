"""
"Ktos obok cos powiedzial" - wykrywanie wypowiedzi nad glowami postaci.

Czego NIE robimy: nie patrzymy na okno czatu. Na zatloczonym serwerze leci tam
bez przerwy globalny spam handlowy - kilkadziesiat linijek na minute, z czego
zadna nie dotyczy Ciebie. Alarm na "nowa linijka w czacie" dzwonilby non stop.

Co robimy: patrzymy na SWIAT GRY, gdzie wypowiedz pojawia sie biala linijka
tuz pod nickiem mowiacego. I tu jest caly trik - jak odroznic wypowiedz od
samego nicku, ktory przeciez tez jest napisem?

    Lv 1 Przyjazny SzamiZJajami  [flaga]   <- nick: "Lv 1" biale, "Przyjazny"
                                              zielone, flaga kolorowa
           do u have clams?                <- wypowiedz: sam bialy

Zmierzone na klatkach z gry: w linijce nicku 69-74% jasnych pikseli jest
KOLOROWYCH, w linijce wypowiedzi - 3%. Rozstep jest tak duzy, ze prog 25%
rozdziela je bez pudla.

To jednak za malo, bo bialych napisow w kadrze jest wiecej: nazwa gildii nad
glowa, imie konia, nick postaci bez kolorowego tytulu. Wszystkie one stoja
SAMOTNIE - i tu jest drugi warunek: wypowiedz zawsze ma nad soba nick swojego
autora, kilka pikseli wyzej i w tej samej osi. Biala linijka bez nicku nad
soba nie jest wypowiedzia.

Na koniec liczy sie jeszcze nowosc: linijka musi nie pasowac do niczego z
poprzedniego pomiaru i utrzymac sie przez dwa pomiary z rzedu (zeby nie
zlapac migniecia przy ruchu postaci).
"""

from __future__ import annotations

import logging
import time

import numpy as np

log = logging.getLogger("rybak")


def text_lines(rgb: np.ndarray, region=None, white_min: int = 190,
               min_width: int = 25, min_height: int = 7, max_height: int = 22):
    """
    Wszystkie linijki tekstu w obszarze, z informacja, ile w nich koloru.
    Zwraca liste (x, y, szerokosc, wysokosc, udzial_koloru) - x,y to LEWY
    GORNY rog, bo do skladania nicku z wypowiedzia potrzebne sa krawedzie.
    """
    import cv2

    h, w = rgb.shape[:2]
    if region is None:
        x0, y0, x1, y1 = 0, 0, w, h
    else:
        x0, y0, x1, y1 = region
        x0 = max(0, int(x0)); y0 = max(0, int(y0))
        x1 = min(w, int(x1)); y1 = min(h, int(y1))
    if x1 - x0 < min_width or y1 <= y0:
        return []
    sub = rgb[y0:y1, x0:x1].astype(np.int16)

    mn = sub.min(axis=2)
    mx = sub.max(axis=2)
    biale = (mn >= white_min)
    kolorowe = (mx >= 150) & ((mx - mn) >= 60)
    # Scalamy WSZYSTKIE jasne piksele, nie tylko biale - inaczej nick
    # rozpadlby sie na kawalki miedzy kolorowym tytulem a biala reszta.
    jasne = (biale | kolorowe).astype(np.uint8)
    jasne = cv2.morphologyEx(jasne, cv2.MORPH_CLOSE, np.ones((1, 15), np.uint8))

    n, _lab, st, _c = cv2.connectedComponentsWithStats(jasne, 8)
    out = []
    for i in range(1, n):
        x = int(st[i, cv2.CC_STAT_LEFT]); y = int(st[i, cv2.CC_STAT_TOP])
        bw = int(st[i, cv2.CC_STAT_WIDTH]); bh = int(st[i, cv2.CC_STAT_HEIGHT])
        if bw < min_width or not (min_height <= bh <= max_height) or bw <= bh:
            continue
        ob = biale[y:y + bh, x:x + bw]
        ok_ = kolorowe[y:y + bh, x:x + bw]
        ile_b, ile_k = int(ob.sum()), int(ok_.sum())
        if ile_b + ile_k < 30:
            continue
        gestosc = (ile_b + ile_k) / float(bw * bh)
        if gestosc > 0.6:                  # pelna plama, nie tekst
            continue
        out.append((x + x0, y + y0, bw, bh, ile_k / float(ile_b + ile_k)))
    return sorted(out, key=lambda t: t[1])


def speech_lines(rgb: np.ndarray, region=None, white_min: int = 190,
                 color_fraction: float = 0.25, max_gap: int = 26,
                 max_dx: int = 90):
    """
    Same WYPOWIEDZI - czyli biale linijki wiszace TUZ POD nickiem.

    Bez tego warunku za wypowiedz robi sie kazdy bialy napis w kadrze: nazwa
    gildii nad glowa, imie konia, nick bez kolorowego tytulu. Wszystkie one
    stoja samotnie. Wypowiedz - nigdy: zawsze ma nad soba nick swojego autora,
    kilka pikseli wyzej i mniej wiecej w tej samej osi.

    Zwraca liste (x_srodka, y_srodka, szerokosc, wysokosc).
    """
    linie = text_lines(rgb, region, white_min)
    nicki = [l for l in linie if l[4] > color_fraction]
    biale = [l for l in linie if l[4] <= color_fraction]

    out = []
    for (x, y, bw, bh, _u) in biale:
        srodek = x + bw / 2
        for (nx, ny, nbw, nbh, _nu) in nicki:
            odstep = y - (ny + nbh)        # ile pikseli pod spodem nicku
            if not (-4 <= odstep <= max_gap):
                continue
            if abs(srodek - (nx + nbw / 2)) > max_dx:
                continue
            out.append((int(x + bw // 2), int(y + bh // 2), bw, bh))
            break
    return out


def white_lines(rgb: np.ndarray, region=None, white_min: int = 190,
                color_fraction: float = 0.25, **_ignored):
    """Zgodnosc wstecz - dawniej same biale linijki, dzis tylko wypowiedzi."""
    return speech_lines(rgb, region, white_min, color_fraction)


def _pasuje(a, b, tol_xy: int = 45, tol_w: int = 10) -> bool:
    """Czy to ta sama linijka, tylko drgnela (postac sie rusza)?"""
    return (abs(a[0] - b[0]) <= tol_xy and abs(a[1] - b[1]) <= tol_xy
            and abs(a[2] - b[2]) <= tol_w)


class SpeechWatcher:
    """Pilnuje, czy w swiecie gry nie pojawila sie nowa biala linijka."""

    def __init__(self, cap, cfg: dict | None = None):
        cfg = dict(cfg or {})
        self.cap = cap
        self.enabled = bool(cfg.get("enabled", False))
        self.every = float(cfg.get("sample_every", 0.35))
        self.region_fr = cfg.get("region") or [0.05, 0.15, 0.88, 0.80]
        self.white_min = int(cfg.get("white_min", 190))
        self.color_fraction = float(cfg.get("color_fraction", 0.25))
        # Otwarte okno czatu udaje rozmowy: linijki czatu tez maja nad soba
        # kolorowe nicki, wiec przechodza warunek "wypowiedz pod nickiem".
        # Zmierzone na klatkach: przy zamknietym czacie 1-2 kandydatow,
        # przy otwartym 7-9. Prog 4 rozdziela to z zapasem, a jednoczesnie
        # przepuszcza kilka osob mowiacych naraz.
        self.max_lines = int(cfg.get("max_lines", 4))
        # Ile nowych linijek naraz uznajemy jeszcze za rozmowe, a nie za
        # przebudowe ekranu (otwarcie czatu, teleport, obrot kamery).
        self.max_new = int(cfg.get("max_new", 3))
        self.action = str(cfg.get("action", "notify")).lower()
        self._last = 0.0
        self.prev = []
        self.pending = []
        self._primed = False          # czy mamy juz punkt odniesienia
        self._chat_warned = False

    def region(self):
        a = self.cap.area()
        fr = self.region_fr
        return (int(fr[0] * a.width), int(fr[1] * a.height),
                int(fr[2] * a.width), int(fr[3] * a.height))

    def poll(self):
        """
        Zwroc liste nowych linijek [(x, y, w, h), ...]. Pusta, gdy cisza.
        Wolaj czesto - sam pilnuje odstepu.
        """
        if not self.enabled:
            return []
        now = time.time()
        if now - self._last < self.every:
            return []
        self._last = now

        try:
            img = self.cap.full()
        except Exception:
            return []
        cur = speech_lines(img, self.region(), self.white_min,
                           self.color_fraction)

        if len(cur) > self.max_lines:
            if not self._chat_warned:
                self._chat_warned = True
                log.info("Wypowiedzi: widze %d kandydatow naraz - okno czatu jest "
                         "chyba otwarte, wiec nie pilnuje rozmow", len(cur))
            self.prev, self.pending = [], []
            self._primed = False       # po zamknieciu czatu zacznij od nowa
            return []
        self._chat_warned = False

        # Pierwszy pomiar sluzy wylacznie za punkt odniesienia. Bez tego
        # KAZDY napis widoczny przy starcie - nazwa gildii, cudzy nick -
        # wygladalby jak swiezo wypowiedziane zdanie i bot alarmowalby
        # zaraz po uruchomieniu.
        if not self._primed:
            self._primed = True
            self.prev, self.pending = cur, []
            log.debug("Wypowiedzi: punkt odniesienia - %d bialych linijek na "
                      "ekranie", len(cur))
            return []

        nowe = [c for c in cur if not any(_pasuje(c, p) for p in self.prev)]

        # Nagla lawina nowych linijek to nie rozmowa, tylko zmiana sceny:
        # ktos otworzyl albo zamknal okno czatu, postac sie przeniosla,
        # kamera obrocila. Wtedy tylko przyjmujemy nowy stan za punkt odniesienia.
        if len(nowe) > self.max_new:
            log.debug("Wypowiedzi: %d nowych linijek naraz - to zmiana sceny, "
                      "nie rozmowa", len(nowe))
            self.prev, self.pending = cur, []
            return []

        # Zgloszenie dopiero, gdy linijka pojawila sie w poprzednim pomiarze
        # I DALEJ TAM JEST. Jedno migniecie (drgniecie napisu przy ruchu
        # postaci) nie wystarczy; wypowiedz wisi kilka sekund.
        potwierdzone = [p for p in self.pending
                        if any(_pasuje(p, c) for c in cur)]
        self.pending = nowe
        self.prev = cur
        if potwierdzone:
            log.info("Wypowiedzi: ktos obok cos powiedzial (%d linijek)",
                     len(potwierdzone))
        return potwierdzone

    def shot_around(self, linia, pad_x: int = 95, pad_y: int = 34):
        """
        Wycinek z wypowiedzia I nickiem nad nia - zeby na telefonie bylo
        widac, kto i co powiedzial.
        """
        a = self.cap.area()
        x, y, w, h = linia
        x0 = max(0, x - w // 2 - pad_x)
        x1 = min(a.width, x + w // 2 + pad_x)
        y0 = max(0, y - h // 2 - pad_y)       # nad wypowiedzia jest nick
        y1 = min(a.height, y + h // 2 + 12)
        try:
            return self.cap.region(x0, y0, x1, y1)
        except Exception:
            return None

    def reset(self) -> None:
        self.prev, self.pending = [], []
        self._primed = False

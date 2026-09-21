"""
"Ktos do mnie napisal" - wykrywanie koperty z licznikiem wiadomosci.

CZEGO SZUKAMY. Nie koperty. Okienko rozmowy z koperta wisi w grze caly czas,
takze wtedy, gdy nie masz zadnej nowej wiadomosci - wiec "widze koperte"
znaczy tylko tyle, ze kiedys z kims rozmawiales. Sygnalem jest CZARNE KOLKO
Z CYFRA, ktore dosiada sie do prawego gornego rogu koperty:

        _______(1)        <- kolko: czarne, bialy licznik 1..9
       |\\     /|
       |  \\ /  |          <- koperta: bialy prostokat, jest zawsze
       |__/_\\__|
         Keenji           <- nick nadawcy: zmienia sie, wiec go nie ruszamy

BEZ ZAPAMIETANEGO ZDJECIA. Wczesniejsza wersja porownywala wycinek ekranu z
zapisanym wzorcem ikony - i wymagala, zeby kazdy uzytkownik najpierw ten
wzorzec zrobil, przy nieprzeczytanej wiadomosci, celujac myszka. Dla kogos,
kto pierwszy raz odpala program, to sciana nie do przejscia.

Dlatego szukamy po BUDOWIE, nie po wygladzie. Koperta z licznikiem to jedyna
rzecz na ekranie, ktora sklada sie z trzech elementow naraz:

  1. czarnej, okraglej plamki wielkosci kilkunastu pikseli,
  2. z kilkoma jasnymi pikselami w srodku (cyfra - obojetne, ktora),
  3. przyklejonej do prawego gornego rogu bialego prostokata o proporcjach
     koperty (szerszy niz wyzszy, ale nie pasek).

Zmierzone na klatkach z gry: 0 falszywych alarmow na 79 klatkach bez
wiadomosci i 28 trafien na 30 przy kopercie wklejonej w losowe miejsca.
Pojedyncze pudlo nic nie psuje, bo alarm i tak wymaga, zeby koperte bylo
widac w kilku probkach z rzedu.

SKAD BIERZEMY OBRAZ. Nie ze zrzutu ekranu, tylko z samego okna gry
(PrintWindow) - patrz rybak/zrzut.py. Zrzut ekranu pokazuje to, co lezy na
wierzchu, wiec cudze okno nad gra zaslanialoby koperte; a przy skalowaniu
ekranu w Windows dawalby obraz rozciagniety, w ktorym nic sie nie zgadza.
"""

from __future__ import annotations

import logging
import time
from collections import deque

import numpy as np

log = logging.getLogger("rybak")


def znajdz_koperty(rgb: np.ndarray, min_cyfra: int = 4):
    """
    Koperty z licznikiem widoczne na klatce.

    Zwraca liste (x, y, szerokosc, wysokosc, pikseli_cyfry) - wspolrzedne
    lewego gornego rogu BIALEJ koperty, bez kolka.
    """
    import cv2

    h, w = rgb.shape[:2]
    a = rgb.astype(np.int16)
    mn = a.min(axis=2)
    mx = a.max(axis=2)
    biale = (mn >= 150) & ((mx - mn) <= 55)
    ciemne = (mx <= 80)
    jasne = (mn >= 140)

    # --- kolka licznika: ciemne plamy, ktore po erozji zostaja okragle.
    # Erozja jest tu potrzebna, bo kolko dotyka koperty, a koperta ma wlasny
    # ciemny obrys: bez niej obie rzeczy sa jedna plama i zaden warunek
    # ksztaltu ich nie przepusci. Obrys ma jeden piksel i znika, kolko ma
    # kilkanascie i tylko sie kurczy.
    rdzen = cv2.erode(ciemne.astype(np.uint8), np.ones((3, 3), np.uint8))
    n, _lab, st, _c = cv2.connectedComponentsWithStats(rdzen, 8)
    kolka = []
    for i in range(1, n):
        x = int(st[i, cv2.CC_STAT_LEFT]); y = int(st[i, cv2.CC_STAT_TOP])
        bw = int(st[i, cv2.CC_STAT_WIDTH]); bh = int(st[i, cv2.CC_STAT_HEIGHT])
        ar = int(st[i, cv2.CC_STAT_AREA])
        if not (6 <= bw <= 20 and 6 <= bh <= 20 and abs(bw - bh) <= 5):
            continue
        if not (25 <= ar <= 330):
            continue
        # w kolku musi siedziec cyfra - jakakolwiek
        ile = int(jasne[max(0, y - 2):y + bh + 2, max(0, x - 2):x + bw + 2].sum())
        if ile < min_cyfra or ile > 120:
            continue
        kolka.append((x - 2, y - 2, bw + 4, bh + 4, ile))
    if not kolka:
        return []

    # --- biale prostokaty o proporcjach koperty
    scalone = cv2.morphologyEx(biale.astype(np.uint8), cv2.MORPH_CLOSE,
                               np.ones((3, 3), np.uint8))
    n2, _lab2, st2, _c2 = cv2.connectedComponentsWithStats(scalone, 8)
    koperty = []
    for i in range(1, n2):
        x = int(st2[i, cv2.CC_STAT_LEFT]); y = int(st2[i, cv2.CC_STAT_TOP])
        bw = int(st2[i, cv2.CC_STAT_WIDTH]); bh = int(st2[i, cv2.CC_STAT_HEIGHT])
        ar = int(st2[i, cv2.CC_STAT_AREA])
        if not (14 <= bw <= 60 and 8 <= bh <= 40):
            continue
        if not (1.1 <= bw / float(bh) <= 2.6):
            continue
        if ar < 0.45 * bw * bh:              # pelny prostokat, nie napis
            continue
        koperty.append((x, y, bw, bh))

    out = []
    for (kx, ky, kw, kh, ile) in kolka:
        sx, sy = kx + kw / 2.0, ky + kh / 2.0
        for (x, y, bw, bh) in koperty:
            # kolko siedzi przy PRAWYM GORNYM rogu koperty
            if not (x + 0.4 * bw <= sx <= x + bw + 0.6 * bw):
                continue
            if not (y - 0.9 * bh <= sy <= y + 0.65 * bh):
                continue
            out.append((x, y, bw, bh, ile))
            break
    return out


def beep() -> None:
    """Krotki dzwiek - mozesz patrzec w inne okno."""
    try:
        import winsound
        winsound.Beep(880, 250)
    except Exception:
        pass


class Koperta:
    """Pilnuje, czy nie przyszla nowa wiadomosc prywatna."""

    def __init__(self, zrzut, cfg: dict | None = None):
        cfg = dict(cfg or {})
        self.zrzut = zrzut
        self.wlaczone = bool(cfg.get("wlaczone", True))
        self.co_ile = float(cfg.get("co_ile", 0.25))
        # Alarm dopiero, gdy koperte widac w kilku probkach - zeby jedno
        # przypadkowe dopasowanie (cos bialego przeszlo przez ekran) nie
        # przerwalo lowienia.
        self.okno_s = float(cfg.get("okno_sekund", 2.0))
        self.czesc = float(cfg.get("czesc_probek", 0.5))
        self.dzwiek = bool(cfg.get("dzwiek", True))
        self._ostatnio = 0.0
        self.historia = deque()
        self.gdzie = None

    def sprawdz(self) -> bool:
        """True, gdy wlasnie potwierdzila sie nowa wiadomosc."""
        if not self.wlaczone:
            return False
        teraz = time.time()
        if teraz - self._ostatnio < self.co_ile:
            return False
        self._ostatnio = teraz
        try:
            klatka = self.zrzut.full()
        except Exception:
            return False
        znalezione = znajdz_koperty(klatka)
        if znalezione:
            self.gdzie = znalezione[0]
        self.historia.append((teraz, bool(znalezione)))
        while self.historia and teraz - self.historia[0][0] > self.okno_s:
            self.historia.popleft()
        if len(self.historia) < 4:
            return False
        udzial = sum(1 for _t, v in self.historia if v) / len(self.historia)
        if udzial >= self.czesc:
            log.info("Wiadomosc: koperta z licznikiem na ekranie "
                     "(%.0f%% probek) - przerywam lowienie", udzial * 100)
            if self.dzwiek:
                beep()
            self.historia.clear()
            return True
        return False

    def cisza(self) -> bool:
        """Czy koperta zniknela - czyli wiadomosc przeczytana."""
        try:
            return not znajdz_koperty(self.zrzut.full())
        except Exception:
            return False

    def zapomnij(self) -> None:
        self.historia.clear()

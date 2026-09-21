"""
Zrzut okna gry i klawisze BEZ przelaczania sie na gre.

Normalnie bot pracuje "na wierzchu": zrzut robi z ekranu, klawisze wysyla
przez SendInput do okna aktywnego. Przy lowieniu kusi jednak, zeby w tym
czasie robic na komputerze cos innego - a wtedy trzeba obejsc dwie rzeczy:

1. ZRZUT. Gdy okno gry jest zaslonione, zrzut z ekranu pokazuje to, co lezy
   na wierzchu - czyli Twoja przegladarke, nie gre. `PrintWindow` prosi samo
   okno o narysowanie sie do bufora, wiec dziala takze wtedy, gdy jest
   zakryte. Haczyk: gry rysowane przez DirectX czesto zwracaja wtedy czarny
   obraz, bo nie rysuja przez GDI. Czy Twoj klient tak ma - sprawdza
   `python run.py --bg-test`.

2. KLAWISZE. SendInput trafia zawsze do okna aktywnego, wiec przy pracy w tle
   jest bezuzyteczny. Zostaja komunikaty PostMessage/SendMessage wysylane
   wprost do okna gry. Te z kolei ignoruja klienci czytajacy wejscie przez
   DirectInput albo GetAsyncKeyState - i znowu: sprawdza to `--bg-test`.

Zaden z tych mechanizmow nie jest wstrzykiwaniem kodu ani czytaniem pamieci
gry; to zwykle API okienkowe Windowsa.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

import numpy as np

from .okno import ClientArea, Grabber, client_area

log = logging.getLogger("rybak")

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

PW_CLIENTONLY = 0x1
PW_RENDERFULLCONTENT = 0x2          # Windows 8.1+; bez tego okna DWM sa czarne
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class PrintWindowGrabber:
    """
    Zrzut obszaru klienta okna przez `PrintWindow` - dziala takze, gdy okno
    jest zaslonione albo nieaktywne (ale NIE, gdy jest zminimalizowane).

    Bufor jest tworzony raz na rozmiar okna i uzywany ponownie - przy 90
    zrzutach na sekunde alokowanie go za kazdym razem kosztowaloby wiecej niz
    samo rysowanie.
    """

    def __init__(self, hwnd: int):
        self.hwnd = hwnd
        self._size = None
        self._hdc = None
        self._mem = None
        self._bmp = None
        self._buf = None
        self._flags = PW_CLIENTONLY | PW_RENDERFULLCONTENT

    def _ensure(self, w: int, h: int):
        if self._size == (w, h):
            return
        self.close()
        hdc = user32.GetDC(self.hwnd)
        mem = gdi32.CreateCompatibleDC(hdc)
        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = w
        info.bmiHeader.biHeight = -h          # ujemna = wiersze od gory
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0
        bits = ctypes.c_void_p()
        bmp = gdi32.CreateDIBSection(mem, ctypes.byref(info), DIB_RGB_COLORS,
                                     ctypes.byref(bits), None, 0)
        if not bmp:
            user32.ReleaseDC(self.hwnd, hdc)
            gdi32.DeleteDC(mem)
            raise RuntimeError("CreateDIBSection nie powiodlo sie")
        gdi32.SelectObject(mem, bmp)
        self._hdc, self._mem, self._bmp = hdc, mem, bmp
        self._buf = (ctypes.c_ubyte * (w * h * 4)).from_address(bits.value)
        self._size = (w, h)

    def grab_client(self) -> np.ndarray:
        """Caly obszar klienta jako RGB."""
        area = client_area(self.hwnd)
        w, h = max(1, area.width), max(1, area.height)
        self._ensure(w, h)
        ok = user32.PrintWindow(wintypes.HWND(self.hwnd), self._mem, self._flags)
        if not ok and self._flags != PW_CLIENTONLY:
            # starsze Windowsy nie znaja PW_RENDERFULLCONTENT
            self._flags = PW_CLIENTONLY
            ok = user32.PrintWindow(wintypes.HWND(self.hwnd), self._mem, self._flags)
        img = np.frombuffer(self._buf, dtype=np.uint8).reshape(h, w, 4)
        return img[:, :, 2::-1].copy()        # BGRA -> RGB

    def close(self):
        if self._bmp:
            gdi32.DeleteObject(self._bmp)
        if self._mem:
            gdi32.DeleteDC(self._mem)
        if self._hdc:
            user32.ReleaseDC(self.hwnd, self._hdc)
        self._bmp = self._mem = self._hdc = self._buf = None
        self._size = None


class Capture:
    """
    Wspolne wejscie do obu sposobow zrzutu.

    `mode`:
      "screen" - zrzut z ekranu (szybki, ale okno gry musi byc widoczne)
      "print"  - PrintWindow (dziala pod zaslonietym oknem, jesli klient
                 w ogole rysuje przez GDI)
    """

    def __init__(self, hwnd: int, mode: str = "screen"):
        self.hwnd = hwnd
        self.mode = mode if mode in ("screen", "print") else "screen"
        self._screen = Grabber() if self.mode == "screen" else None
        self._print = PrintWindowGrabber(hwnd) if self.mode == "print" else None

    def area(self) -> ClientArea:
        return client_area(self.hwnd)

    def full(self) -> np.ndarray:
        if self.mode == "print":
            return self._print.grab_client()
        return self._screen.grab(self.area())

    def region(self, x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
        """Wycinek obszaru klienta (wspolrzedne wzgledem okna)."""
        if self.mode == "print":
            return self._print.grab_client()[y0:y1, x0:x1]
        a = self.area()
        sub = ClientArea(a.hwnd, a.left + x0, a.top + y0,
                         max(1, x1 - x0), max(1, y1 - y0))
        return self._screen.grab(sub)

    def close(self):
        if self._screen:
            self._screen.close()
        if self._print:
            self._print.close()


def child_windows(hwnd: int):
    """
    Okna potomne okna gry. Czesc klientow trzyma wlasciwa powierzchnie
    rysowania (i odbiornik klawiszy) w osobnym oknie-dziecku, wiec komunikat
    wyslany do okna glownego trafia w prozne.
    """
    out = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(child, _lparam):
        length = user32.GetWindowTextLengthW(child)
        buf = ctypes.create_unicode_buffer(length + 1)
        if length:
            user32.GetWindowTextW(child, buf, length + 1)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(child, cls, 256)
        out.append((int(child), buf.value, cls.value))
        return True

    user32.EnumChildWindows(wintypes.HWND(hwnd), WNDENUMPROC(cb), 0)
    return out


def print_window_probe(hwnd: int):
    """
    Sprobuj PrintWindow z roznymi flagami i powiedz, ktora (jesli ktorakolwiek)
    daje niepusty obraz. Zwraca liste (opis, flagi, obraz, czy_czarny).
    """
    area = client_area(hwnd)
    w, h = max(1, area.width), max(1, area.height)
    warianty = [
        ("PW_CLIENTONLY | PW_RENDERFULLCONTENT", PW_CLIENTONLY | PW_RENDERFULLCONTENT),
        ("PW_RENDERFULLCONTENT", PW_RENDERFULLCONTENT),
        ("PW_CLIENTONLY", PW_CLIENTONLY),
        ("bez flag", 0),
    ]
    out = []
    for opis, flagi in warianty:
        g = PrintWindowGrabber(hwnd)
        g._flags = flagi
        try:
            g._ensure(w, h)
            user32.PrintWindow(wintypes.HWND(hwnd), g._mem, flagi)
            img = np.frombuffer(g._buf, dtype=np.uint8).reshape(h, w, 4)[:, :, 2::-1].copy()
            out.append((opis, flagi, img, looks_black(img)))
        except Exception as exc:
            out.append((opis, flagi, None, True))
        finally:
            g.close()
    return out


def looks_black(img: np.ndarray) -> bool:
    """Czy zrzut wyszedl czarny/pusty - typowy objaw gry rysowanej DirectX."""
    return float(img.max()) < 12 or float(img.std()) < 2.0


def otworz_oko(hwnd: int):
    """
    Otworz zrzut w trybie, ktory na TYM komputerze ma sens. Zwraca
    (Capture, tryb, skala_okna).

    Decyzja jest jedna i wazna: czy Windows rozciaga okno gry. Gdy tak
    (skalowanie ekranu 125/150%, przez ktore interfejs gry robi sie ogromny),
    zrzut ekranu jest bezuzyteczny - lapie obraz JUZ powiekszony i rozmyty,
    wiec pasek ma inny rozmiar, jego obwodka rozmywa sie ponizej progu, a do
    tego rozjezdzaja sie wspolrzedne: rozmiar wnetrza okna system podaje w
    pikselach gry, a polozenie na ekranie w prawdziwych.

    PrintWindow tego nie dotyczy - kaze GRZE narysowac swoje wnetrze do
    naszego bufora, wiec dostajemy jej wlasne piksele, takie same jak na
    komputerze bez skalowania. Jesli tylko dziala, przechodzimy na niego.
    """
    from .okno import dpi_info

    skala = 1.0
    try:
        d = dpi_info(hwnd)
        skala = d["skala"]
        if d["rozciagane"]:
            probny = Capture(hwnd, "print")
            try:
                if not looks_black(probny.full()):
                    return probny, "print", skala
            except Exception:
                pass
            probny.close()
            log.warning("Windows rozciaga okno gry %.2f raza, a PrintWindow "
                        "zwraca czarny obraz. Ustaw skalowanie tego ekranu na "
                        "100%% (Ustawienia > System > Ekran > Skala).", skala)
    except Exception as exc:
        log.debug("Nie sprawdzilem skalowania: %s", exc)
    return Capture(hwnd, "screen"), "screen", skala


def zmierz_szybkosc(oko, prob: int = 8) -> float:
    """
    Ile sekund zajmuje jeden zrzut. Mini-gra trwa okolo sekundy, wiec tempo
    patrzenia decyduje o celnosci - a PrintWindow bywa wyrazniej wolniejszy
    od zrzutu ekranu. Zamiast zakladac 90 klatek na sekunde i sie rozczarowac,
    mierzymy to raz i dostosowujemy tempo do tego, co ten komputer wyrabia.
    """
    import time as _t
    najlepszy = 1.0
    for _ in range(prob):
        t = _t.perf_counter()
        try:
            oko.full()
        except Exception:
            return najlepszy
        najlepszy = min(najlepszy, _t.perf_counter() - t)
    return najlepszy

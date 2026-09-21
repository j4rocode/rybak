"""
Znajdowanie okna gry i zrzuty jego obszaru klienta.

Uwaga: zrzut ekranu robimy przez GDI/DXGI (mss). Dziala to dla gry w trybie
okienkowym / bezramkowym. W pelnym ekranie "exclusive" zrzut czesto wychodzi
czarny - wtedy przelacz gre na okno bezramkowe.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

import numpy as np

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SetProcessDPIAware()


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


@dataclass
class ClientArea:
    hwnd: int
    left: int
    top: int
    width: int
    height: int

    @property
    def monitor_dict(self):
        return {"left": self.left, "top": self.top,
                "width": self.width, "height": self.height}

    def to_screen(self, x: int, y: int):
        """Wspolrzedne wzgledem okna -> wspolrzedne ekranu."""
        return self.left + int(x), self.top + int(y)


def find_window(title_substring: str) -> int:
    """Zwraca hwnd pierwszego widocznego okna, ktorego tytul zawiera podany tekst."""
    needle = title_substring.lower()
    found = []

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if needle in buf.value.lower():
            found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    if not found:
        raise RuntimeError(
            f"Nie znaleziono okna z tytulem zawierajacym {title_substring!r}. "
            "Sprawdz 'window_title' w config.json."
        )
    return found[0][0]


def list_windows():
    out = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                out.append((hwnd, buf.value))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def client_area(hwnd: int) -> ClientArea:
    rect = RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("GetClientRect nie powiodlo sie")
    pt = wintypes.POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
        raise RuntimeError("ClientToScreen nie powiodlo sie")
    return ClientArea(hwnd=hwnd, left=pt.x, top=pt.y,
                      width=rect.right - rect.left,
                      height=rect.bottom - rect.top)


def dpi_info(hwnd: int) -> dict:
    """
    Czy Windows ROZCIAGA to okno - i jak bardzo.

    Skad problem: gra jest starym programem i nie wie o skalowaniu ekranu.
    Gdy w Windows ustawisz 125% albo 150% (na laptopach to domyslne),
    system pozwala jej rysowac w malej rozdzielczosci, a potem rozciaga
    gotowy obraz jak zdjecie. Dlatego HUD robi sie ogromny i rozmazany.

    Dla bota to podwojny klopot. Po pierwsze zrzut ekranu lapie obraz JUZ
    rozciagniety, wiec pasek jest o polowe wiekszy i rozmyty - piaskowa
    obwodka rozmywa sie ponizej progu, a kolory przestaja trafiac w maski.
    Po drugie rozjezdzaja sie wspolrzedne: rozmiar wnetrza okna system podaje
    w pikselach gry, a polozenie na ekranie - w prawdziwych, wiec zrzut
    wycina inny kawalek, niz mysli, ze wycina.

    Lekarstwo jest jedno i proste: nie zrzucac ekranu, tylko kazac GRZE
    narysowac swoje wnetrze do naszego bufora (PrintWindow). Wtedy dostajemy
    jej wlasne, nierozciagniete piksele - takie same jak na komputerze bez
    skalowania.
    """
    wynik = {"dpi_okna": 0, "dpi_systemu": 96, "skala": 1.0, "rozciagane": False}
    try:
        wynik["dpi_okna"] = int(user32.GetDpiForWindow(hwnd))
    except Exception:
        pass
    try:
        wynik["dpi_systemu"] = int(user32.GetDpiForSystem())
    except Exception:
        pass
    okno = RECT()
    try:
        user32.GetWindowRect(hwnd, ctypes.byref(okno))
        a = client_area(hwnd)
        wynik["okno_px"] = (okno.right - okno.left, okno.bottom - okno.top)
        wynik["wnetrze_px"] = (a.width, a.height)
    except Exception:
        wynik["okno_px"] = wynik["wnetrze_px"] = (0, 0)
    # Okno rysowane w 96 DPI na ekranie o wyzszym = Windows je rozciaga.
    if wynik["dpi_okna"] and wynik["dpi_systemu"] > wynik["dpi_okna"]:
        wynik["skala"] = wynik["dpi_systemu"] / float(wynik["dpi_okna"])
        wynik["rozciagane"] = wynik["skala"] > 1.01
    # Zapas: rama okna nie ma prawa byc szersza niz kilkadziesiat pikseli.
    # Gdy "cale okno" jest duzo wieksze od wnetrza, to nie rama, tylko
    # rozciaganie.
    ow, _oh = wynik["okno_px"]
    cw, _ch = wynik["wnetrze_px"]
    if cw and ow - cw > 80:
        wynik["rozciagane"] = True
        wynik["skala"] = max(wynik["skala"], round(ow / float(cw), 3))
    return wynik


def set_client_size(hwnd: int, width: int, height: int):
    """
    Ustaw OBSZAR KLIENTA okna na dokladnie `width` x `height`.

    Po co: cala kalibracja bota (pasek lowienia, koperta, paski HP) to
    wspolrzedne w pikselach obszaru klienta. Gdy okno ma ten sam rozmiar co
    przy kalibracji, wszystko pasuje co do piksela - niezaleznie od tego, na
    jakim komputerze i jakim ekranie stoi.

    Ramka i belka tytulu nie wchodza do obszaru klienta, a ich grubosc zalezy
    od motywu Windows. Zamiast ja liczyc, mierzymy roznice miedzy calym oknem
    a jego wnetrzem TU I TERAZ i o tyle powiekszamy docelowy rozmiar.
    """
    a = client_area(hwnd)
    okno = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(okno)):
        raise RuntimeError("GetWindowRect nie powiodlo sie")
    dodatek_w = (okno.right - okno.left) - a.width
    dodatek_h = (okno.bottom - okno.top) - a.height
    SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010
    user32.SetWindowPos(wintypes.HWND(hwnd), None,
                        okno.left, okno.top,
                        int(width) + dodatek_w, int(height) + dodatek_h,
                        SWP_NOZORDER | SWP_NOACTIVATE)
    return client_area(hwnd)


def is_foreground(hwnd: int) -> bool:
    return user32.GetForegroundWindow() == hwnd


class Grabber:
    """Cienka nakladka na mss - zwraca obraz RGB jako numpy array."""

    def __init__(self):
        import mss  # import lokalny, zeby modul dalo sie zaimportowac bez mss
        self._sct = mss.mss()

    def grab(self, area: ClientArea) -> np.ndarray:
        raw = self._sct.grab(area.monitor_dict)
        img = np.asarray(raw)          # BGRA, ksztalt (h, w, 4)
        return img[:, :, 2::-1]        # -> RGB

    def close(self):
        try:
            self._sct.close()
        except Exception:
            pass


# ---------------------------------------------------- samo znajdowanie gry

#: Slowa, ktore prawie na pewno znacza "to nie jest gra". Serwery Metin2
#: nazywaja sie roznie (ARTHION, Odien, Valium...), wiec nie da sie zrobic
#: listy tytulow gier - ale da sie odsiac to, co gra na pewno nie jest.
NIE_GRA = (
    "rybak", "eksplorator", "explorer", "chrome", "firefox", "edge", "opera",
    "code", "visual studio", "notatnik", "notepad", "word", "excel",
    "powerpoint", "outlook", "discord", "spotify", "steam", "menedzer",
    "task manager", "ustawienia", "settings", "panel sterowania", "cmd",
    "powershell", "terminal", "python", "przegladarka", "kalkulator",
)

#: Slowa, ktore mocno na nia wskazuja.
CHYBA_GRA = ("metin", "mt2", "metin2")


def _czysty_tytul(t: str) -> str:
    return (t or "").strip().lower()


def znajdz_gre(podpowiedz: str = ""):
    """
    Znajdz okno gry bez pytania uzytkownika o tytul.

    Dlaczego nie mozna po prostu szukac "Metin2": serwery prywatne zmieniaja
    tytul okna na wlasna nazwe (ARTHION, Odien, ...), wiec lista tytulow gier
    nie istnieje. Idziemy wiec od drugiej strony - odsiewamy to, co gra na
    pewno nie jest, i z reszty bierzemy okno najbardziej "gropodobne":
    duze, o proporcjach ekranu, nie nasze wlasne.

    Zwraca (hwnd, tytul) albo (None, None).
    """
    podpowiedz = _czysty_tytul(podpowiedz)
    najlepsze = None
    for hwnd, tytul in list_windows():
        maly = _czysty_tytul(tytul)
        if not maly:
            continue
        if any(s in maly for s in NIE_GRA):
            continue
        try:
            a = client_area(hwnd)
        except Exception:
            continue
        if a.width < 640 or a.height < 400:
            continue                      # okienka narzedziowe i dialogi
        proporcje = a.width / float(a.height)
        if not (1.1 <= proporcje <= 2.6):
            continue                      # gra jest szersza niz wyzsza
        punkty = a.width * a.height
        if podpowiedz and podpowiedz in maly:
            punkty *= 100                 # to, co dzialalo poprzednio
        elif any(s in maly for s in CHYBA_GRA):
            punkty *= 10
        if najlepsze is None or punkty > najlepsze[0]:
            najlepsze = (punkty, hwnd, tytul)
    if najlepsze is None:
        return None, None
    return najlepsze[1], najlepsze[2]


def kandydaci_na_gre():
    """Okna, ktore moglyby byc gra - do listy wyboru w okienku programu."""
    out = []
    for hwnd, tytul in list_windows():
        maly = _czysty_tytul(tytul)
        if not maly or any(s in maly for s in NIE_GRA):
            continue
        try:
            a = client_area(hwnd)
        except Exception:
            continue
        if a.width < 400 or a.height < 300:
            continue
        out.append((hwnd, tytul, a.width, a.height))
    return sorted(out, key=lambda t: -(t[2] * t[3]))

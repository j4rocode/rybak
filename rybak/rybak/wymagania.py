"""
Sprawdzenie, czy sa wszystkie biblioteki - zanim cokolwiek ich uzyje.

Po co osobny modul: na swiezo zainstalowanym Pythonie nie ma ani numpy, ani
opencv, ani mss. Bez tego pierwsze uruchomienie konczy sie sciana tekstu w
rodzaju

    Traceback (most recent call last):
      File "gui.py", line 25, in <module>
        from m2bot.window import client_area, find_window, ...
      File "m2bot\\window.py", line 8, in <module>
        import numpy as np
    ModuleNotFoundError: No module named 'numpy'

z ktorej nie wynika, co masz zrobic - a wystarczy jedno polecenie. Dlatego
pytamy o biblioteki ZANIM sie zaimportuja, i zamiast tracebacku pokazujemy
gotowa komende do wklejenia.

Uzywamy wylacznie biblioteki standardowej, bo to jedyny kod, ktory na pewno
sie uruchomi na golym Pythonie.
"""

from __future__ import annotations

import importlib.util
import sys

# modul, jakim go importujemy  ->  (nazwa w pip, do czego sluzy)
POTRZEBNE = {
    "numpy": ("numpy", "liczenie na obrazie"),
    "cv2": ("opencv-python", "rozpoznawanie paska, koperty i napisow"),
    "mss": ("mss", "zrzuty ekranu"),
}

# Bez tego bot dziala - przydaje sie tylko przy rozpoznawaniu kursora ataku.
DODATKOWE = {
    "win32gui": ("pywin32", "rozpoznawanie ksztaltu kursora"),
}


def _brakuje(spis: dict) -> list:
    """Nazwy pakietow pip, ktorych nie ma. Nie importujemy - tylko pytamy."""
    brak = []
    for modul, (pakiet, _po_co) in spis.items():
        try:
            jest = importlib.util.find_spec(modul) is not None
        except Exception:
            jest = False
        if not jest:
            brak.append(pakiet)
    return brak


def sprawdz():
    """(czego_brakuje, czego_brakuje_opcjonalnie) - obie listy nazw z pip."""
    return _brakuje(POTRZEBNE), _brakuje(DODATKOWE)


def komenda(pakiety) -> str:
    """Polecenie, ktore to doinstaluje - z TYM Pythonem, ktory wlasnie dziala."""
    return f'"{sys.executable}" -m pip install ' + " ".join(pakiety)


def sprawdz_lub_wyjdz(czekaj: bool = True) -> None:
    """
    Gdy czegos brakuje: powiedz co, jak to naprawic - i zakoncz. Bez tego
    program i tak wywroci sie kilka linijek dalej, tyle ze niezrozumiale.
    """
    brak, brak_dod = sprawdz()
    if not brak:
        if brak_dod:
            print(f"(uwaga: brak {', '.join(brak_dod)} - bot zadziala, tylko bez "
                  f"rozpoznawania ksztaltu kursora)")
        return

    opisy = {p: o for _m, (p, o) in POTRZEBNE.items()}
    print()
    print("=" * 62)
    print("  BRAKUJE BIBLIOTEK - bot nie ma czym patrzec na ekran")
    print("=" * 62)
    for p in brak:
        print(f"    - {p:16s} ({opisy.get(p, '')})")
    print()
    print("  Najprosciej: zamknij to okno i kliknij dwa razy w  instaluj.bat")
    print("  (lezy w tym samym folderze co ten plik).")
    print()
    print("  Albo wklej w to okno jedno polecenie:")
    print()
    print("    " + komenda(brak))
    print()
    print("=" * 62)
    if czekaj:
        try:
            input("Nacisnij Enter, zeby zamknac...")
        except Exception:
            pass
    raise SystemExit(1)

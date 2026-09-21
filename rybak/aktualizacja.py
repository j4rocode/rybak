"""
Aktualizacja programu: "wyszla nowa wersja - kliknij i masz".

Problem do rozwiazania: program stoi na kilku komputerach, a poprawki
powstaja na jednym. Przenoszenie plikow recznie konczy sie tym, ze na
laptopie zostaje wersja sprzed miesiaca i nikt nie wie, ktora jest ktora.

Sa dwie drogi i obie robia dokladnie to samo, roznia sie tylko tym, skad
biora paczke:

  * Z INTERNETU - podajesz raz adres paczki ZIP (najwygodniej repozytorium
    na GitHubie) i od tej pory na kazdym komputerze wystarczy "Sprawdz
    aktualizacje". Program sam pobiera, sam porownuje wersje i sam mowi,
    czy jest sens cokolwiek robic.
  * Z PLIKU - wskazujesz ZIP-a przyniesionego na pendrive albo przyslanego
    mailem. Przydaje sie tam, gdzie nie ma internetu albo blokuje go firmowy
    VPN.

Trzy rzeczy, ktorych ten modul pilnuje, bo bez nich aktualizacja potrafi
zrobic wiecej szkody niz pozytku:

  1. USTAWIENIA ZOSTAJA. Plik ustawien i to, czego bot sie nauczyl, nie sa
     nadpisywane - inaczej kazda aktualizacja kasowalaby zmierzone tempo
     ladowania i kanal powiadomien.
  2. STARA WERSJA ZOSTAJE NA DYSKU. Przed podmiana robimy kopie do folderu
     z data. Gdy nowa wersja okaze sie gorsza, jest do czego wrocic.
  3. PACZKA NIE MOZE PISAC POZA SWOIM FOLDEREM. ZIP potrafi zawierac
     sciezki w rodzaju "..\\..\\Windows\\system32\\cos.dll"; takie wpisy
     odrzucamy, zamiast grzecznie je rozpakowac.
"""

from __future__ import annotations

import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

#: Czego aktualizacja nigdy nie nadpisze.
CHRONIONE = ("ustawienia.json",)

#: Ile maksymalnie wazy paczka. Zwykla ma ~120 kB; wiekszy plik to albo
#: pomylka w adresie (trafilismy na strone HTML), albo cos, czego nie
#: chcemy rozpakowywac.
MAX_BAJTOW = 20 * 1024 * 1024


def adres_paczki(adres: str) -> str:
    """
    Zamien to, co czlowiek wklei, na adres paczki ZIP.

    Ludzie wklejaja adres repozytorium ze strony GitHuba, a nie link do
    archiwum - i slusznie, bo ten drugi trzeba znalezc. Robimy to za nich.
    """
    adres = (adres or "").strip().rstrip("/")
    if not adres:
        return ""
    m = re.match(r"^https://github\.com/([^/]+)/([^/]+)$", adres)
    if m:
        return f"https://github.com/{m.group(1)}/{m.group(2)}/archive/refs/heads/main.zip"
    return adres


def pobierz(adres: str, dokad: Path) -> Path:
    """Sciagnij paczke pod wskazana sciezke. Tylko HTTPS."""
    adres = adres_paczki(adres)
    if not adres.lower().startswith("https://"):
        raise ValueError("Adres musi zaczynac sie od https:// - przez zwykle "
                         "http ktos po drodze moglby podmienic paczke.")
    zadanie = Request(adres, headers={"User-Agent": "Rybak"})
    with urlopen(zadanie, timeout=30) as odp:
        dane = odp.read(MAX_BAJTOW + 1)
    if len(dane) > MAX_BAJTOW:
        raise ValueError("Paczka jest podejrzanie duza - sprawdz adres.")
    if dane[:2] != b"PK":
        raise ValueError("To, co pobralem, nie jest paczka ZIP. Najczesciej "
                         "znaczy to, ze adres prowadzi do strony, a nie do "
                         "pliku.")
    dokad.write_bytes(dane)
    return dokad


def _bezpieczne(nazwa: str) -> bool:
    """Czy wpis z ZIP-a na pewno zostanie w swoim folderze."""
    p = Path(nazwa)
    if p.is_absolute() or nazwa.startswith(("/", "\\")):
        return False
    return ".." not in p.parts


def korzen_paczki(zf: zipfile.ZipFile) -> str:
    """
    Gdzie w archiwum zaczyna sie program.

    Nasz ZIP ma w srodku folder "Rybak/", a archiwum z GitHuba - folder o
    nazwie repozytorium z dopiskiem galezi. Zamiast zgadywac, szukamy
    folderu, w ktorym lezy rybak.py.
    """
    for wpis in zf.namelist():
        if Path(wpis).name == "rybak.py":
            rodzic = str(Path(wpis).parent).replace("\\", "/")
            return "" if rodzic in (".", "") else rodzic + "/"
    raise ValueError("W paczce nie ma pliku rybak.py - to nie jest "
                     "aktualizacja Rybaka.")


def wersja_w_paczce(zf: zipfile.ZipFile, korzen: str) -> str:
    try:
        tekst = zf.read(korzen + "rybak/__init__.py").decode("utf-8", "ignore")
    except KeyError:
        return "?"
    m = re.search(r'__version__\s*=\s*"([^"]+)"', tekst)
    return m.group(1) if m else "?"


def nowsza(a: str, b: str) -> bool:
    """Czy wersja `a` jest nowsza niz `b`. '2.10' > '2.9', nie odwrotnie."""
    def klucz(w):
        return [int(x) if x.isdigit() else 0 for x in re.split(r"[.\-_]", w)]
    try:
        return klucz(a) > klucz(b)
    except Exception:
        return a != b


def sprawdz(zrodlo: str, moja_wersja: str, katalog_tymczasowy: Path):
    """
    Pobierz paczke i powiedz, co w niej jest.
    Zwraca (sciezka_do_zip, wersja_w_paczce, czy_nowsza).
    """
    katalog_tymczasowy.mkdir(parents=True, exist_ok=True)
    plik = pobierz(zrodlo, katalog_tymczasowy / "rybak_nowy.zip")
    with zipfile.ZipFile(plik) as zf:
        korzen = korzen_paczki(zf)
        w = wersja_w_paczce(zf, korzen)
    return plik, w, nowsza(w, moja_wersja)


def zainstaluj(paczka: Path, folder: Path, chronione=CHRONIONE):
    """
    Rozpakuj paczke na miejsce programu, robiac najpierw kopie zapasowa.

    Zwraca (ile_plikow, sciezka_kopii). Pliki chronione i wszystko, co
    wyglada na probe wyjscia poza folder, sa pomijane.
    """
    folder = Path(folder)
    with zipfile.ZipFile(paczka) as zf:
        korzen = korzen_paczki(zf)
        do_wgrania = []
        for wpis in zf.namelist():
            if wpis.endswith("/") or not wpis.startswith(korzen):
                continue
            wzgledna = wpis[len(korzen):]
            if not wzgledna or not _bezpieczne(wzgledna):
                continue
            if Path(wzgledna).name in chronione:
                continue
            do_wgrania.append((wpis, wzgledna))
        if not do_wgrania:
            raise ValueError("Paczka jest pusta.")

        # --- kopia zapasowa tego, co zaraz podmienimy
        kopia = folder / ("kopia_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        kopia.mkdir(parents=True, exist_ok=True)
        for _wpis, wzgledna in do_wgrania:
            stary = folder / wzgledna
            if stary.exists():
                cel = kopia / wzgledna
                cel.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(stary, cel)

        for wpis, wzgledna in do_wgrania:
            cel = folder / wzgledna
            cel.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(wpis) as zrodlo_pliku, open(cel, "wb") as wyjscie:
                shutil.copyfileobj(zrodlo_pliku, wyjscie)

    # Skompilowane resztki po starej wersji potrafia przezyc podmiane i
    # przeslonic nowy kod - kasujemy je, zeby nie szukac potem duchow.
    for smiec in folder.rglob("__pycache__"):
        shutil.rmtree(smiec, ignore_errors=True)
    return len(do_wgrania), kopia

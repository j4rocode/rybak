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
from pathlib import Path, PureWindowsPath
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
        # urlopen sam podaza za przekierowaniami, a te moga zejsc z https na
        # zwykle http - wtedy caly warunek wyzej nic nie daje. Sprawdzamy
        # wiec adres, pod ktorym FAKTYCZNIE wyladowalismy.
        koncowy = getattr(odp, "url", adres) or adres
        if not koncowy.lower().startswith("https://"):
            raise ValueError("Adres przekierowal na zwykle http - przerywam, "
                             "bo takiej paczki nikt po drodze nie pilnuje.")
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
    """
    Czy wpis z ZIP-a na pewno zostanie w swoim folderze.

    Sama nieobecnosc ".." nie wystarcza. Na Windowsie sciezka "C:evil.py" -
    bez ukosnika po dwukropku - jest WZGLEDNA wobec biezacego katalogu na
    dysku C, a pathlib przy sklejaniu odrzuca wtedy lewy czlon: folder
    docelowy znika i plik laduje gdzie indziej. Dlatego odrzucamy wszystko,
    co ma dwukropek albo ukosnik odwrotny, i na koniec sprawdzamy wynik
    sklejenia: musi lezec pod folderem programu.
    """
    if not nazwa or ":" in nazwa or "\\" in nazwa:
        return False
    p = PureWindowsPath(nazwa)
    if p.is_absolute() or p.drive or p.root:
        return False
    return ".." not in p.parts and not any(cz in ("", ".") for cz in p.parts)


def _w_folderze(folder: Path, wzgledna: str) -> bool:
    """Ostateczna kontrola: czy sklejona sciezka naprawde zostala w srodku."""
    try:
        cel = (folder / wzgledna).resolve()
        return cel == folder.resolve() or folder.resolve() in cel.parents
    except Exception:
        return False


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
            if not _w_folderze(folder, wzgledna):
                continue
            if Path(wzgledna).name in chronione:
                continue
            do_wgrania.append((wpis, wzgledna))
        if not do_wgrania:
            raise ValueError("Paczka jest pusta.")
        # MAX_BAJTOW ogranicza paczke POBRANA; po rozpakowaniu moze urosnac
        # dowolnie, wiec pytamy archiwum o deklarowane rozmiary, zanim
        # zapiszemy choc jeden bajt.
        po_rozpakowaniu = sum(zf.getinfo(w).file_size for w, _ in do_wgrania)
        if po_rozpakowaniu > 4 * MAX_BAJTOW:
            raise ValueError(f"Po rozpakowaniu paczka zajelaby "
                             f"{po_rozpakowaniu // (1024 * 1024)} MB - "
                             f"to nie jest aktualizacja Rybaka.")

        # --- kopia zapasowa tego, co zaraz podmienimy
        kopia = folder / ("kopia_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        kopia.mkdir(parents=True, exist_ok=True)
        for _wpis, wzgledna in do_wgrania:
            stary = folder / wzgledna
            if stary.exists():
                cel = kopia / wzgledna
                cel.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(stary, cel)

        nieudane = []
        for wpis, wzgledna in do_wgrania:
            cel = folder / wzgledna
            cel.parent.mkdir(parents=True, exist_ok=True)
            # Windows nie pozwala NADPISAC pliku, ktory ktos trzyma otwarty -
            # a wlasnie tak jest z Rybak.bat, bo cmd czyta go w trakcie
            # dzialania. Pozwala za to ZMIENIC MU NAZWE. Odsuwamy wiec stary
            # plik na bok i piszemy nowy w puste miejsce; odsuniete zbieramy
            # i kasujemy przy nastepnym starcie.
            odsuniety = None
            if cel.exists():
                odsuniety = cel.with_name(cel.name + ".stara")
                try:
                    if odsuniety.exists():
                        odsuniety.unlink()
                    cel.rename(odsuniety)
                except Exception:
                    odsuniety = None
            try:
                with zf.open(wpis) as zrodlo_pliku, open(cel, "wb") as wyjscie:
                    shutil.copyfileobj(zrodlo_pliku, wyjscie)
            except Exception as exc:
                nieudane.append(f"{wzgledna}: {exc}")
                if odsuniety is not None and not cel.exists():
                    try:
                        odsuniety.rename(cel)      # wracamy do starego
                    except Exception:
                        pass
        if nieudane:
            raise ValueError(
                "Nie udalo sie podmienic " + str(len(nieudane)) + " plikow:\n"
                + "\n".join(nieudane[:5])
                + "\n\nStara wersja jest w folderze " + kopia.name
                + " - nic nie zginelo.")

    # Skompilowane resztki po starej wersji potrafia przezyc podmiane i
    # przeslonic nowy kod - kasujemy je, zeby nie szukac potem duchow.
    # Do kopii nie zagladamy: to nie jest juz program, tylko archiwum.
    for smiec in folder.rglob("__pycache__"):
        if not any(cz.startswith("kopia_") for cz in smiec.parts):
            shutil.rmtree(smiec, ignore_errors=True)
    posprzataj(folder)
    return len(do_wgrania), kopia


def posprzataj(folder: Path, ile_kopii: int = 3) -> None:
    """
    Usun pliki ".stara" po poprzedniej aktualizacji i najstarsze kopie.

    Bez tego folder programu obrasta: kazda aktualizacja zostawia komplet
    plikow w kopii, a po roku jest ich kilkanascie. Trzy ostatnie w zupelnosci
    wystarcza, zeby miec do czego wrocic.
    """
    folder = Path(folder)
    for stary in folder.rglob("*.stara"):
        try:
            stary.unlink()
        except Exception:
            pass                       # plik wciaz w uzyciu - sprobujemy potem
    kopie = sorted((k for k in folder.glob("kopia_*") if k.is_dir()),
                   key=lambda k: k.name)
    for k in kopie[:-ile_kopii] if len(kopie) > ile_kopii else []:
        shutil.rmtree(k, ignore_errors=True)

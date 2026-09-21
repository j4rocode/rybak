"""
Ustawienia: maly plik JSON obok programu.

Zasada jest taka, ze plik moze NIE ISTNIEC i wszystko ma dzialac. Kazda
wartosc ma sensowny domysl, a to, czego bot uczy sie sam (tempo wypelniania,
wyprzedzenie, poprawka celu), dopisuje sie tu po pierwszym lowieniu. Nikt nie
musi tego pliku ogladac ani ruszac - jest po to, zeby program pamietal
miedzy uruchomieniami.
"""

from __future__ import annotations

import json
from pathlib import Path

#: Plik ustawien lezy OBOK programu, nie w katalogu, z ktorego ktos go
#: uruchomil. Inaczej "python C:\\Rybak\\rybak.py" wywolane z pulpitu
#: czytaloby i zapisywalo ustawienia na pulpicie - a aktualizacja chronilaby
#: wtedy nie ten plik, co trzeba.
PLIK = Path(__file__).resolve().parent.parent / "ustawienia.json"

DOMYSLNE = {
    # Fragment tytulu okna gry. Puste = szukaj sam (patrz rybak/okno.py).
    "okno_gry": "",

    # Skad brac nowe wersje programu. Program sam zamienia adres
    # repozytorium na adres paczki, wiec wystarczy wkleic to, co widac w
    # pasku przegladarki. Puste = aktualizacja tylko z pliku ZIP.
    "zrodlo_aktualizacji": "https://github.com/j4rocode/rybak",

    "lowienie": {
        "przyneta": "1",          # klawisz z przyneta
        "przyneta_co": 1,         # co ile zarzucen nakladac przyneta
        "zarzut": "space",        # klawisz zarzucenia wedki
        "ladowanie": "space",     # klawisz trzymany w mini-grze
        "czekaj_na_branie": 45.0,
        "po_zlowieniu": 1.5,
        # Ponizsze bot mierzy sam - to tylko punkt wyjscia.
        "tempo_px_s": None,
        "wyprzedzenie_ms": 0.0,
        "poprawka_px": 0.0,
        "celowanie_px": 7,
        "klatek_na_sekunde": 90,
        "podglad_ms": 160,
        "uczenie": True,
    },

    # Ktos napisal PW -> przerwij lowienie i wyslij push.
    "koperta": {
        "wlaczone": True,
        "co_ile": 0.25,
        "okno_sekund": 2.0,
        "czesc_probek": 0.5,
        "dzwiek": True,
    },

    # Ktos obok cos powiedzial -> tylko push, lowimy dalej.
    "rozmowy": {
        "wlaczone": False,
        "co_ile": 0.35,
    },

    "powiadomienia": {
        "enabled": False,
        "ntfy_server": "https://ntfy.sh",
        "ntfy_topic": "",
        "priority": 5,
        "attach_screenshot": True,
        "image_max_kb": 250,
        "image_scale": 0.5,
        "timeout": 8.0,
    },
}


def _scal(baza: dict, zmiany: dict) -> dict:
    """
    Nakladamy zapisane ustawienia na domyslne.

    Sekcja, ktora w pliku jest czyms innym niz slownikiem - bo ktos wpisal
    tam null, liczbe albo pomylil sie w nawiasach - jest ODRZUCANA i wraca
    do domyslnej. Inaczej program umieralby tracebackiem przy budowaniu
    okna, zanim zdazy cokolwiek pokazac, a uzytkownik zobaczylby tylko
    "przeczytaj komunikat wyzej".
    """
    out = dict(baza)
    for k, v in (zmiany or {}).items():
        if isinstance(out.get(k), dict):
            out[k] = _scal(out[k], v) if isinstance(v, dict) else dict(out[k])
        else:
            out[k] = v
    return out


def wczytaj(sciezka: str | Path = PLIK) -> dict:
    p = Path(sciezka)
    if not p.exists():
        return json.loads(json.dumps(DOMYSLNE))
    try:
        return _scal(DOMYSLNE, json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        # Uszkodzony plik nie moze blokowac programu - lepiej ruszyc na
        # domyslnych niz pokazac komus traceback o JSON-ie.
        return json.loads(json.dumps(DOMYSLNE))


def zapisz(ust: dict, sciezka: str | Path = PLIK) -> None:
    """
    Zapis przez plik tymczasowy i podmiane nazwy.

    write_text najpierw obcina plik do zera, a potem pisze. Gdyby program
    zginal miedzy jednym a drugim - a zamykanie okna potrafi ubic watek w
    dowolnym momencie - zostalby pusty plik i uzytkownik straciby ustawienia
    razem z tym, czego bot sie nauczyl. os.replace jest niepodzielne: albo
    stara zawartosc, albo nowa.
    """
    import os
    sciezka = Path(sciezka)
    tymczasowy = sciezka.with_name(sciezka.name + ".nowy")
    try:
        tymczasowy.write_text(json.dumps(ust, indent=2, ensure_ascii=False),
                              encoding="utf-8")
        os.replace(tymczasowy, sciezka)
    except Exception:
        try:
            tymczasowy.unlink()
        except Exception:
            pass


def losowy_kanal() -> str:
    """
    Nazwa kanalu powiadomien dla kogos, kto pierwszy raz odpala program.

    ntfy nie ma kont ani hasel: kto zna nazwe kanalu, ten czyta powiadomienia.
    Dlatego nazwa musi byc dluga i niezgadywalna - generujemy ja sami, zeby
    nikt nie wpisal tu "metin" i nie dzielil sie potem zrzutami ekranu z
    calym internetem.
    """
    import secrets
    return "rybak-" + secrets.token_hex(6)

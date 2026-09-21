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

PLIK = "ustawienia.json"

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
    out = dict(baza)
    for k, v in (zmiany or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _scal(out[k], v)
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
    try:
        Path(sciezka).write_text(
            json.dumps(ust, indent=2, ensure_ascii=False), encoding="utf-8")
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

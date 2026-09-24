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
        # Przerwy w sekundach. Skracaj ostroznie: gdy gra nie zdazy przyjac
        # klawisza, bot zarzuca w prozne i traci cala runde zamiast ulamka
        # sekundy.
        # Przerwa miedzy rundami to ZAKRES, w ktorym bot dostraja sie sam.
        # Nie da sie jej rozdzielic na "po zlowieniu" i "po pudle", bo bot
        # nie wie, czy ryba wpadla - celny pasek to nie to samo co zlowiona
        # ryba, ryba potrafi uciec z haczyka mimo idealnego trafienia.
        # Mierzymy wiec to, co widac: czy nastepne zarzucenie sie udalo.
        "po_zlowieniu": 0.7,       # dolna granica przerwy po rundzie
        "po_pudle": 3.0,           # gorna granica
        "po_rundzie": None,        # to, co bot sam wymierzyl

        # Przerwanie animacji wyciagania ryby. Po mini-grze postac dlugo
        # wyciaga rybe i przez ten czas gra nie przyjmuje zarzucenia.
        # Wsiadanie na konia i zsiadanie te animacje ucina, wiec zamiast
        # czekac - przerywamy ja. Skrot bywa inny na innym serwerze.
        "kon_wlaczony": True,
        "kon_skrot": "ctrl+h",
        # Miedzy wsiadaniem a zsiadaniem. Za krotko = gra gubi zsiadanie i
        # postac zostaje na koniu, z ktorego nie da sie lowic.
        "kon_odstep": 0.8,
        "po_koniu": 0.25,          # po zsiadnieciu, zanim zarzucimy
        "kon_przytrzymaj": 0.10,   # jak dlugo trzymac skrot (gra musi go zauwazyc)
        # Ile sekund po puszczeniu spacji patrzymy na pasek, zeby ocenic
        # celnosc. Dopiero PO tym wsiadamy na konia - im krocej, tym
        # wczesniej ucinamy animacje.
        "ocena_s": 0.35,
        "po_przynecie": 0.5,       # od przynety do zarzucenia
        "po_zarzuceniu": 0.9,      # od zarzucenia do patrzenia na pasek
        # Ile zarzucen bez brania, zanim bot uzna, ze skonczyla sie przyneta.
        # Kazde kolejne czeka dluzej, wiec za krotkie przerwy same sie
        # koryguja, zanim dojdzie do zatrzymania.
        "max_pudel": 6,
        # Ponizsze bot mierzy sam - to tylko punkt wyjscia.
        "tempo_px_s": None,
        "wyprzedzenie_ms": 0.0,
        "poprawka_px": 0.0,
        "tempo_nauki": None,      # przy jakim tempie nauczyla sie poprawka
        # O ile pikseli za srodek rybki celowac. TWOJE ustawienie - bot go
        # nie rusza. Mniej (nawet ujemnie) = puszcza wczesniej, czyli
        # zatrzymuje pasek blizej lewej krawedzi rybki. Zwieksz, jesli w grze
        # widzisz, ze przeciaga.
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


def _migruj(ust: dict) -> dict:
    """Poprawki zapisanych wartosci, ktore okazaly sie zlymi domyslami."""
    l = ust.get("lowienie")
    if isinstance(l, dict):
        # 2.13 zapisywal 0,35 s - za malo, gra gubila zsiadanie z konia.
        if l.get("kon_odstep") == 0.35:
            l["kon_odstep"] = 0.8
    return ust


def wczytaj(sciezka: str | Path = PLIK) -> dict:
    p = Path(sciezka)
    if not p.exists():
        return json.loads(json.dumps(DOMYSLNE))
    try:
        return _migruj(_scal(DOMYSLNE, json.loads(p.read_text(encoding="utf-8"))))
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

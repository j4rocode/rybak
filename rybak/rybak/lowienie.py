"""
Petla lowienia: przyneta -> zarzut -> czekanie na branie -> mini-gra.

Mini-gra trwa okolo sekundy: wypelnienie leci ~190 px/s przy pasku szerokim
~210 px. Dlatego nie odmierzamy czasu z gory - patrzymy na pasek kilkadziesiat
razy na sekunde (zrzut samego paska, nie calego ekranu) i puszczamy klawisz,
gdy wypelnienie DOJDZIE tam, gdzie rybka BEDZIE za chwile. "Za chwile", bo
miedzy decyzja a reakcja gry mija kilkadziesiat milisekund, a w tym czasie
pasek zdazy urosnac o kilka pikseli.

Dwie rzeczy bot mierzy sam, po kazdym rzucie, i nie trzeba mu ich podawac:

  * TEMPO WYPELNIANIA - z regresji po probkach z tej samej mini-gry. Dzieki
    temu przezywa i inna rozdzielczosc, i przeczytana w grze ksiege, ktora
    zmienia tempo o kilka procent.
  * OPOZNIENIE WEJSCIA - o ile pasek urosl juz PO puszczeniu klawisza. To
    miara czysta, niezalezna od tego, gdzie akurat plywa rybka.

Nic tu nie czyta pamieci gry - to zwykle patrzenie na piksele i naciskanie
klawisza, tak jak robi to reka gracza.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque

import numpy as np

from . import klawisze
from .koperta import Koperta
from .okno import client_area, is_foreground
from .pasek import (DOMYSLNE_TEMPO, Bar, _marker_speed, _reflect, _slope,
                    read_bar, szukaj_paska)
from .push import Push
from .rozmowy import SpeechWatcher
from .zrzut import Capture, otworz_oko, zmierz_szybkosc

log = logging.getLogger("rybak")


class Rybak:
    """Cala praca bota. Sterowanie: start(), stop()."""

    def __init__(self, hwnd: int, ust: dict, na_zmiane=None):
        self.hwnd = hwnd
        self.ust = ust
        self.na_zmiane = na_zmiane or (lambda: None)
        self.stop_flaga = threading.Event()

        l = ust.get("lowienie") or {}
        self.klawisz_przynety = str(l.get("przyneta", "1"))
        self.przyneta_co = int(l.get("przyneta_co", 1) or 1)
        self.klawisz_zarzutu = str(l.get("zarzut", "space"))
        self.klawisz_ladowania = str(l.get("ladowanie", "space"))
        self.czekaj_na_branie = float(l.get("czekaj_na_branie", 45.0))
        self.fps = float(l.get("klatek_na_sekunde", 90))
        self.podglad_ms = float(l.get("podglad_ms", 160))
        self.po_zlowieniu = float(l.get("po_zlowieniu", 1.5))
        self.uczenie = bool(l.get("uczenie", True))

        # Czego bot nauczyl sie poprzednio. Wszystkie trzy liczby sa tylko
        # punktem wyjscia - poprawia je po kazdym rzucie.
        self.tempo = float(l.get("tempo_px_s") or DOMYSLNE_TEMPO)
        self.wyprzedzenie_ms = float(l.get("wyprzedzenie_ms", 0) or 0)
        self.poprawka = float(l.get("poprawka_px", 0) or 0)
        self.celowanie = float(l.get("celowanie_px", 7))

        self.oko: Capture | None = None
        self.push = Push(ust.get("powiadomienia") or {})
        self.koperta: Koperta | None = None
        self.rozmowy: SpeechWatcher | None = None

        self.zarzucen = 0
        self.prob = 0
        self.trafien = 0
        self.przerwane_wiadomoscia = False
        self.ostatni_blad = None
        self._ostatnia_rozmowa = 0.0

    # ----------------------------------------------------------- sterowanie

    def stop(self) -> None:
        self.stop_flaga.set()

    def _sprawdz_stop(self) -> None:
        if self.stop_flaga.is_set():
            raise _Przerwane()

    def _spij(self, sekund: float) -> None:
        koniec = time.time() + sekund
        while time.time() < koniec:
            self._sprawdz_stop()
            time.sleep(min(0.05, max(0.0, koniec - time.time())))

    def obszar(self):
        return client_area(self.hwnd)

    # --------------------------------------------------------------- oczy

    def _otworz_oczy(self) -> None:
        self.oko, tryb, skala = otworz_oko(self.hwnd)
        a = self.obszar()
        log.info("Okno gry: %dx%d", a.width, a.height)
        # Tempo patrzenia dopasowujemy do tego, co ten komputer wyrabia.
        # Mini-gra trwa okolo sekundy, wiec kazda klatka to kilka pikseli
        # dokladnosci; obiecywanie sobie 90 klatek na slabszym sprzecie
        # konczy sie tym, ze bot spoznia sie systematycznie.
        jeden = zmierz_szybkosc(self.oko)
        mozliwe = 1.0 / max(jeden * 1.6, 0.004)
        if mozliwe < self.fps:
            log.info("Jeden zrzut zajmuje %.0f ms - patrze %d razy na sekunde "
                     "zamiast %d", jeden * 1000, int(mozliwe), int(self.fps))
            self.fps = max(25.0, mozliwe)
        if tryb == "print":
            log.info("Windows rozciaga to okno %.2f raza (stad duzy interfejs) - "
                     "czytam obraz prosto z okna gry, wiec to nie przeszkadza",
                     skala)
        mw = self.ust.get("koperta") or {}
        if mw.get("wlaczone", True):
            self.koperta = Koperta(self.oko, mw)
        rw = self.ust.get("rozmowy") or {}
        if rw.get("wlaczone", False):
            self.rozmowy = SpeechWatcher(self.oko, {
                "enabled": True,
                "sample_every": float(rw.get("co_ile", 0.35)),
            })

    def _zamknij_oczy(self) -> None:
        for co in (self.koperta, self.oko):
            try:
                if co is not None and hasattr(co, "close"):
                    co.close()
            except Exception:
                pass

    def _klatka(self):
        return self.oko.full()

    def _wycinek(self, bar: Bar, pad_x: int = 45, pad_y: int = 14):
        a = self.obszar()
        x0 = max(0, bar.x0 - pad_x)
        y0 = max(0, bar.y0 - pad_y)
        x1 = min(a.width, bar.x1 + pad_x)
        y1 = min(a.height, bar.y1 + pad_y)
        return (x0, y0, x1, y1), (x0, y0)

    def _zrzut_wycinka(self, box):
        return self.oko.region(*box)

    # ------------------------------------------------------------ klawisze

    def _stuknij(self, klawisz: str, trzymaj: float = 0.06) -> None:
        klawisze.send_key_down(klawisz)
        time.sleep(trzymaj)
        klawisze.send_key_up(klawisz)

    # ------------------------------------------------------------ przerwania

    def _czy_wiadomosc(self) -> bool:
        if self.koperta is None or not self.koperta.sprawdz():
            return False
        self.przerwane_wiadomoscia = True
        self._powiadom_o_wiadomosci()
        return True

    def _czy_rozmowa(self) -> None:
        """Ktos obok cos powiedzial - tylko powiadamiamy, lowimy dalej."""
        if self.rozmowy is None:
            return
        linie = self.rozmowy.poll()
        if not linie:
            return
        if time.time() - self._ostatnia_rozmowa < 25:
            return
        self._ostatnia_rozmowa = time.time()
        self.push.send("Metin2: ktos obok cos napisal",
                       f"Lowie dalej. Zlowione: {self.trafien}/{self.prob}.",
                       image_png=self._zrzut_ekranu(), priority=4,
                       tags="speech_balloon")

    def _zrzut_ekranu(self):
        try:
            return Push.encode_image(self._klatka(), self.push.image_max_bytes,
                                     self.push.image_scale)
        except Exception:
            return None

    def _powiadom_o_wiadomosci(self) -> None:
        self.push.send("Metin2: ktos do Ciebie napisal",
                       f"Przerwalem lowienie. Zlowione: {self.trafien}/{self.prob}, "
                       f"zarzucen: {self.zarzucen}.",
                       image_png=self._zrzut_ekranu(), priority=5, tags="envelope")

    # ------------------------------------------------------------- zarzut

    def zarzuc(self) -> None:
        if self.przyneta_co and self.zarzucen % self.przyneta_co == 0:
            self._stuknij(self.klawisz_przynety)
            self._spij(0.8)
        self._stuknij(self.klawisz_zarzutu)
        self.zarzucen += 1
        self._spij(1.2)

    def czekaj_na_pasek(self, ile_sekund: float) -> Bar | None:
        koniec = time.time() + ile_sekund
        zerkniec = bez_focusu = 0
        while time.time() < koniec:
            self._sprawdz_stop()
            if not is_foreground(self.hwnd):
                bez_focusu += 1
                self._spij(0.3)
                continue
            if self._czy_wiadomosc():
                return None
            self._czy_rozmowa()
            zerkniec += 1
            bar = szukaj_paska(self._klatka())
            if bar is not None:
                return bar
            time.sleep(0.08)
        self.ostatni_blad = self._czemu_bez_paska(zerkniec, bez_focusu)
        return None

    def _czemu_bez_paska(self, zerkniec: int, bez_focusu: int) -> str:
        if bez_focusu and not zerkniec:
            return ("ani razu nie zajrzalem na ekran, bo okno gry nie bylo na "
                    "wierzchu - kliknij w gre i jej nie zaslaniaj")
        if bez_focusu > zerkniec:
            return f"gra przewaznie nie byla na wierzchu ({bez_focusu} odbic)"
        return (f"patrzylem {zerkniec} razy i nie bylo paska - ryba nie wziela "
                f"albo skonczyla sie przyneta")

    def czekaj_az_zniknie(self, ile_sekund: float = 6.0) -> None:
        """Po zlowieniu pasek jeszcze chwile gasnie - nie bierz go za nowy."""
        koniec = time.time() + ile_sekund
        while time.time() < koniec:
            self._sprawdz_stop()
            if szukaj_paska(self._klatka()) is None:
                return
            time.sleep(0.1)

    # ------------------------------------------------------------- mini-gra

    def zagraj(self, bar: Bar) -> bool:
        """
        Trzymaj klawisz i pusc go, gdy wypelnienie dogoni rybke.

        Dwa haczyki, przez ktore goly odczyt nie wystarcza:

        * Rybka jest rysowana NA pasku, wiec na ostatnich kilkunastu pikselach
          - dokladnie tam, gdzie trzeba trafic - krawedzi wypelnienia nie
          widac. Liczymy ja wiec z ostatniego CZYSTEGO odczytu i z tempa.
        * Rybka plynie w losowa strone, z losowa predkoscia i zawraca na
          koncach paska. Dlatego jej predkosc liczymy z krotkiego okna i
          przewidujemy polozenie z odbiciem od koncow.
        """
        box, origin = self._wycinek(bar)
        okres = 1.0 / max(20.0, self.fps)
        czyste = deque(maxlen=8)         # (czas, x) wypelnienia sprzed rybki
        rybki = deque(maxlen=12)         # (czas, srodek rybki)
        kotwica = None
        puszczone = False
        x_przy_puszczeniu = None

        # Zanim zaczniemy ladowac, popatrz chwile na sama rybke - inaczej
        # pierwszy rachunek szedlby bez znajomosci jej kierunku.
        podglad = self.podglad_ms / 1000.0
        t_pod = time.time()
        while time.time() - t_pod < podglad:
            self._sprawdz_stop()
            img = self._zrzut_wycinka(box)
            teraz = time.time()
            _f, mk, zyje = read_bar(img, bar, origin, extra_left=35)
            if mk is not None:
                rybki.append((teraz, mk[0]))
            elif not zyje:
                break
            time.sleep(okres)

        t0 = time.time()
        klawisze.send_key_down(self.klawisz_ladowania)
        try:
            while True:
                self._sprawdz_stop()
                img = self._zrzut_wycinka(box)
                # czas mierzymy PO zrzucie - obraz pokazuje stan z chwili
                # zrzutu, a nie z chwili, gdy o niego poprosilismy
                teraz = time.time()
                if teraz - t0 > 6.0:
                    log.warning("Pasek nie doszedl do rybki w 6 s - puszczam")
                    break

                fx, mk, zyje = read_bar(img, bar, origin, extra_left=35)
                if not zyje and teraz - t0 > 0.6:
                    log.info("Pasek zniknal w trakcie")
                    break
                if mk is not None:
                    rybki.append((teraz, mk[0]))
                if fx is None:
                    if teraz - t0 > 1.6:
                        log.warning("Trzymam %r, a pasek nie rosnie - czy to na "
                                    "pewno klawisz ladowania?", self.klawisz_ladowania)
                        break
                    time.sleep(okres)
                    continue

                # Odczyt wypelnienia jest wiarygodny tylko na lewo od rybki.
                if mk is None or fx < mk[1] - 3:
                    czyste.append((teraz, fx))
                    kotwica = (teraz, fx)
                    v = _slope(czyste)
                    if v and 60 < v < 600:
                        self.tempo = v

                v = self.tempo
                v_rybki = _marker_speed(rybki)
                lead = self.wyprzedzenie_ms / 1000.0
                at, ax = kotwica if kotwica else (teraz, fx)
                tutaj = ax + v * (teraz - at)            # wypelnienie teraz
                przewidziane = tutaj + v * lead          # gdy gra odbierze klawisz
                if mk is not None:
                    cel = (_reflect(mk[0] + v_rybki * lead, bar.x0, bar.x1)
                           + self.celowanie - self.poprawka)
                else:
                    cel = bar.x1 + self.celowanie

                if przewidziane >= cel:
                    puszczone, x_przy_puszczeniu = True, tutaj
                    break
                if mk is not None and tutaj > mk[2] + 2:
                    puszczone, x_przy_puszczeniu = True, tutaj
                    break
                if tutaj >= bar.x1 - 3:
                    puszczone, x_przy_puszczeniu = True, tutaj
                    break
                time.sleep(okres)
        finally:
            klawisze.send_key_up(self.klawisz_ladowania)

        self.prob += 1
        if not puszczone:
            return False
        return self._ocen(bar, box, origin, x_przy_puszczeniu)

    def _ocen(self, bar: Bar, box, origin, x_przy_puszczeniu) -> bool:
        """
        Po puszczeniu klawisza wypelnienie zamiera - a rybka plynie dalej.
        Dlatego oceniamy po klatce, w ktorej wypelnienie doszlo NAJDALEJ, a
        nie po tym, co widac pol sekundy pozniej.
        """
        szczyt = -1.0
        rybka_w_szczycie = None
        ostatnia_rybka = None
        koniec = time.time() + 0.8
        while time.time() < koniec:
            img = self._zrzut_wycinka(box)
            fx, mk, zyje = read_bar(img, bar, origin, extra_left=35)
            if mk is not None:
                ostatnia_rybka = mk
            if fx is not None and fx > szczyt:
                szczyt, rybka_w_szczycie = float(fx), mk or ostatnia_rybka
            if not zyje:
                break
            time.sleep(0.012)

        if szczyt < 0 or rybka_w_szczycie is None:
            return False

        srodek, lewa, prawa = rybka_w_szczycie
        pod_rybka = lewa - 3 <= szczyt <= prawa + 1
        blad = 0.0 if pod_rybka else float(szczyt - (srodek + self.celowanie))
        trafione = pod_rybka or abs(blad) <= 8
        if trafione:
            self.trafien += 1
        log.info("Stop na %d px, rybka %d px (%d-%d) -> %s (blad %+.0f px)",
                 szczyt, srodek, lewa, prawa,
                 "TRAFIONE" if trafione else "pudlo", blad)

        # Douczanie. Gdy koniec wypelnienia zostal pod rybka, jego prawdziwe
        # polozenie jest nieznane - wtedy nie ma czego uczyc i tak jestesmy
        # na celu.
        zaslonione = (ostatnia_rybka is not None
                      and ostatnia_rybka[1] - 3 <= szczyt <= ostatnia_rybka[2] + 1)
        if (self.uczenie and x_przy_puszczeniu is not None
                and not zaslonione and self.tempo > 20):
            opoznienie = (szczyt - x_przy_puszczeniu) / self.tempo * 1000.0
            if -50 <= opoznienie <= 400:
                self.wyprzedzenie_ms = max(0.0, min(
                    260.0, 0.5 * self.wyprzedzenie_ms + 0.5 * opoznienie))
            if abs(blad) <= 60:
                self.poprawka = max(-25.0, min(25.0, self.poprawka + 0.5 * blad))
        return trafione

    # ------------------------------------------------------------ petla

    def run(self) -> None:
        try:
            self._otworz_oczy()
            log.info("Lowie. Przyneta=%r zarzut=%r ladowanie=%r",
                     self.klawisz_przynety, self.klawisz_zarzutu,
                     self.klawisz_ladowania)
            if self.push.enabled:
                log.info("Powiadomienia na telefon: %s", self.push.url)
            pudla_z_rzedu = 0
            while not self.stop_flaga.is_set():
                self._sprawdz_stop()
                self._czekaj_na_gre()
                if self._czy_wiadomosc():
                    log.info("Przerwane - masz nowa wiadomosc")
                    break
                self.zarzuc()
                bar = self.czekaj_na_pasek(self.czekaj_na_branie)
                if bar is None:
                    if self.przerwane_wiadomoscia:
                        break
                    pudla_z_rzedu += 1
                    log.warning("Nie doczekalem sie paska (%d z rzedu) - %s",
                                pudla_z_rzedu, self.ostatni_blad or "")
                    if pudla_z_rzedu >= 4:
                        log.error("Cztery razy bez brania - pewnie skonczyla sie "
                                  "przyneta. Zatrzymuje sie.")
                        self.push.send("Metin2: lowienie stoi",
                                       "Cztery zarzucenia bez brania - "
                                       "pewnie skonczyla sie przyneta.",
                                       priority=4, tags="warning")
                        break
                    continue
                pudla_z_rzedu = 0
                self.zagraj(bar)
                self.na_zmiane()
                self.czekaj_az_zniknie(3.0)
                self._spij(self.po_zlowieniu)
        except _Przerwane:
            log.info("Zatrzymane.")
        except Exception as exc:
            log.exception("Cos poszlo nie tak: %s", exc)
        finally:
            skutecznosc = (self.trafien / self.prob * 100) if self.prob else 0.0
            log.info("Koniec. Zarzucen %d, prob %d, trafien %d (%.0f%%), "
                     "tempo %.0f px/s, wyprzedzenie %.0f ms",
                     self.zarzucen, self.prob, self.trafien, skutecznosc,
                     self.tempo, self.wyprzedzenie_ms)
            self._zapisz_nauke()
            self._zamknij_oczy()
            self.na_zmiane()

    def _czekaj_na_gre(self) -> None:
        """Bot pisze do okna na wierzchu - wiec czeka, az gra tam wroci."""
        powiedziane = False
        while not is_foreground(self.hwnd):
            self._sprawdz_stop()
            if not powiedziane:
                powiedziane = True
                log.info("Czekam, az przelaczysz sie na okno gry...")
            time.sleep(0.3)

    def _zapisz_nauke(self) -> None:
        l = self.ust.setdefault("lowienie", {})
        l["tempo_px_s"] = round(self.tempo, 1)
        l["wyprzedzenie_ms"] = round(self.wyprzedzenie_ms, 1)
        l["poprawka_px"] = round(self.poprawka, 1)


class _Przerwane(Exception):
    """Wewnetrzne: ktos nacisnal Stop."""

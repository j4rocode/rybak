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

from . import klawisze
from .koperta import Koperta
from .okno import client_area, is_foreground, okno_zyje
from .pasek import (DOMYSLNE_TEMPO, OBSZAR, Bar, _marker_speed, _reflect,
                    _slope, read_bar, szukaj_paska)
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
        # Trzy przerwy, ktore skladaja sie na odstep miedzy rybami. Sa
        # osobne, bo kazda ma inny powod: gra potrzebuje chwili na zalozenie
        # przynety, chwili na animacje zarzutu, i chwili na zniknieciu
        # poprzedniego paska. Za krotkie - gra gubi klawisz i bot zarzuca w
        # prozne; za dlugie - stoimy bez powodu.
        # PRZERWA PO RUNDZIE - i dlaczego jest to zakres, a nie liczba.
        #
        # Po nieudanej probie animacja w grze trwa dluzej niz po udanej, a
        # zarzucenie w jej trakcie przepada: gra gubi klawisz, wedka nie
        # leci, runda idzie w kosmos. Kusi, zeby czekac dluzej "po pudle" -
        # tylko ze bot NIE WIE, czy ryba wpadla. Wie jedynie, czy celnie
        # zatrzymal pasek, a celny pasek to nie to samo co zlowiona ryba:
        # ryba potrafi uciec z haczyka mimo idealnego trafienia, i wtedy
        # animacja jest ta dluzsza, choc bot zapisal sobie "trafione".
        #
        # Dlatego nie zgadujemy po wyniku, tylko mierzymy JEDYNA rzecz,
        # ktora widac na pewno: czy nastepne zarzucenie sie udalo. Gdy nie -
        # wydluzamy przerwe. Gdy kilka z rzedu poszlo gladko - skracamy.
        # Bot sam dochodzi do wartosci, ktora dziala u Ciebie, miedzy
        # podanym minimum a maksimum.
        self.przerwa_min = float(l.get("po_zlowieniu", 0.7))
        self.przerwa_max = float(l.get("po_pudle", 3.0))
        self.po_rundzie = float(l.get("po_rundzie") or self.przerwa_min)
        self.po_rundzie = max(self.przerwa_min, min(self.przerwa_max, self.po_rundzie))
        self._gladkie_zarzuty = 0
        self.po_przynecie = float(l.get("po_przynecie", 0.5))
        self.po_zarzuceniu = float(l.get("po_zarzuceniu", 0.9))
        # Ile zarzucen bez brania wolno, zanim uznamy, ze skonczyla sie
        # przyneta. Kazde kolejne czeka troche dluzej - jesli powodem byla
        # za krotka przerwa, bot sam sie z tego wygrzebie.
        self.max_pudel = int(l.get("max_pudel", 6) or 6)
        self.uczenie = bool(l.get("uczenie", True))

        # Czego bot nauczyl sie poprzednio. Wszystkie trzy liczby sa tylko
        # punktem wyjscia - poprawia je po kazdym rzucie.
        self.tempo = float(l.get("tempo_px_s") or DOMYSLNE_TEMPO)
        self.wyprzedzenie_ms = float(l.get("wyprzedzenie_ms", 0) or 0)
        self.poprawka = float(l.get("poprawka_px", 0) or 0)
        # Przy jakim tempie nauczyla sie powyzsza poprawka. Poprawka jest w
        # PIKSELACH, a piksele zaleza od tempa - gdy gra zmieni tempo (inny
        # poziom lowienia, przeczytana ksiega), ta sama zwloka to juz inna
        # liczba pikseli. Zamiast uczyc sie od zera, przeliczamy ja.
        self.tempo_nauki = float(l.get("tempo_nauki") or self.tempo)
        self.ostatnie_bledy = deque(maxlen=6)
        # DWA rozne przesuniecia celu, celowo trzymane osobno:
        #   celowanie  - Twoje, reczne. Bot go nigdy nie rusza.
        #   poprawka   - to, czego bot nauczyl sie sam z wlasnych pomiarow.
        # Rozdzielone, bo bot NIE WIDZI, czy gra zaliczyla rybe. Gdy krawedz
        # wypelnienia schowa sie pod rybka, jej prawdziwe polozenie jest
        # nie do zmierzenia - dla bota kazde takie zatrzymanie wyglada na
        # trafienie. Ty widzisz w grze, czy ryba wpadla, wiec ostatnie slowo
        # musi nalezec do Ciebie, a nauka nie moze Twojego ustawienia zjadac.
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
        # Obszar, w ktorym szukamy paska. Zaczynamy waskim pasem posrodku
        # okna - tam pasek wychodzi zawsze - a gdy kilka razy z rzedu nic
        # nie znajdziemy, poszerzamy go. Wolimy szukac szerzej niz nie
        # znalezc wcale na kliencie, ktory rysuje interfejs inaczej.
        self.obszar_szukania = OBSZAR
        self._puste_zarzuty = 0

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
        # Mierzymy takim samym zrzutem, jakiego uzywamy w mini-grze: maly
        # wycinek posrodku okna. Mierzenie calego okna zanizaloby wynik przy
        # zwyklym zrzucie ekranu, gdzie wycinek jest wielokrotnie tanszy.
        proba = (max(0, a.width // 2 - 150), max(0, int(a.height * 0.7) - 20),
                 min(a.width, a.width // 2 + 150), min(a.height, int(a.height * 0.7) + 20))
        jeden = zmierz_szybkosc(self.oko, wycinek=proba)
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
        for co in (self.koperta, self.rozmowy, self.oko):
            try:
                if co is not None and hasattr(co, "close"):
                    co.close()
            except Exception:
                pass

    def _klatka(self):
        return self.oko.full()

    def _wycinek(self, bar: Bar, pad_x: int = 45, pad_y: int = 14):
        # Rozmiar okna bierzemy na nowo, bo gracz mogl je przeciagnac. Gdy
        # sie zmienil, pasek z poprzedniej klatki i tak jest nieaktualny -
        # mowimy o tym glosno, zamiast czytac piksele obok.
        a = self.obszar()
        if bar.x1 >= a.width or bar.y1 >= a.height:
            raise _OknoZmienione()
        x0 = max(0, bar.x0 - pad_x)
        y0 = max(0, bar.y0 - pad_y)
        x1 = min(a.width, bar.x1 + pad_x)
        y1 = min(a.height, bar.y1 + pad_y)
        return (x0, y0, x1, y1), (x0, y0)

    def _zrzut_wycinka(self, box):
        return self.oko.region(*box)

    # ------------------------------------------------------------ klawisze

    def _stuknij(self, klawisz: str, trzymaj: float = 0.06) -> None:
        # key_down/key_up to SendInput ze skankodem - jedyny sposob, ktory
        # ten klient przyjmuje. Warianty send_* i post_* z klawisze.py to
        # komunikaty okienkowe; gra czyta klawiature przez DirectInput i
        # komunikatow nie widzi wcale.
        klawisze.key_down(klawisz)
        time.sleep(trzymaj)
        klawisze.key_up(klawisz)

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
                       f"Lowie dalej. Celnych: {self.trafien}/{self.prob}.",
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
                       f"Przerwalem lowienie. Celnych: {self.trafien}/{self.prob}, "
                       f"zarzucen: {self.zarzucen}.",
                       image_png=self._zrzut_ekranu(), priority=5, tags="envelope")

    # ------------------------------------------------------------- zarzut

    def zarzuc(self) -> None:
        if self.przyneta_co and self.zarzucen % self.przyneta_co == 0:
            self._stuknij(self.klawisz_przynety)
            self._spij(self.po_przynecie)
        self._stuknij(self.klawisz_zarzutu)
        self.zarzucen += 1
        self._spij(self.po_zarzuceniu)

    def czekaj_na_pasek(self, ile_sekund: float) -> Bar | None:
        koniec = time.time() + ile_sekund
        zerkniec = bez_focusu = 0
        while time.time() < koniec:
            self._sprawdz_stop()
            if not okno_zyje(self.hwnd):
                raise _GraZnikla()
            if not is_foreground(self.hwnd):
                bez_focusu += 1
                self._spij(0.3)
                continue
            if self._czy_wiadomosc():
                return None
            self._czy_rozmowa()
            zerkniec += 1
            bar = szukaj_paska(self._klatka(), self.obszar_szukania)
            if bar is not None:
                self.ostatni_blad = None
                self._puste_zarzuty = 0
                return bar
            time.sleep(0.08)
        self.ostatni_blad = self._czemu_bez_paska(zerkniec, bez_focusu)
        self._puste_zarzuty += 1
        if self._puste_zarzuty == 2 and self.obszar_szukania == OBSZAR:
            self.obszar_szukania = (0.10, 0.25, 0.90, 1.0)
            log.info("Dwa zarzucenia bez paska - poszerzam obszar szukania "
                     "na wypadek, gdyby ten klient rysowal go gdzie indziej")
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
        """
        Po zlowieniu pasek jeszcze chwile gasnie - nie bierz go za nowy.

        Wychodzimy w chwili, gdy zniknie, wiec ta wartosc to tylko gorny
        limit, a nie przerwa. Sprawdzamy czesto, zeby nie przeciagac.
        """
        koniec = time.time() + ile_sekund
        while time.time() < koniec:
            self._sprawdz_stop()
            if szukaj_paska(self._klatka(), self.obszar_szukania) is None:
                return
            time.sleep(0.06)

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
        czyste = deque(maxlen=40)        # (czas, x) wypelnienia sprzed rybki
        rybki = deque(maxlen=12)         # (czas, srodek rybki)
        kotwica = None
        puszczone = False
        przeszukane_ponownie = False
        x_przy_puszczeniu = None
        zmierzone_tempo = None
        wiek_kotwicy = 0.0

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
        klawisze.key_down(self.klawisz_ladowania)
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
                    # Nie widzimy wypelnienia. Zanim uznamy, ze klawisz jest
                    # zly, sprawdzamy drugie wytlumaczenie: pasek znalazl sie
                    # nie tam, gdzie patrzymy - bo drgnal albo zmierzylismy go
                    # w chwili, gdy rybka zaslaniala mu brzeg. Raz na rzut
                    # szukamy go od nowa na calej klatce i czytamy dalej z
                    # nowego miejsca.
                    if teraz - t0 > 0.7 and not przeszukane_ponownie:
                        przeszukane_ponownie = True
                        nowy = szukaj_paska(self._klatka(), self.obszar_szukania)
                        if nowy is not None and (nowy.x0 != bar.x0 or nowy.y0 != bar.y0):
                            log.info("Pasek jest gdzie indziej niz myslalem "
                                     "(%s -> %s) - czytam z nowego miejsca",
                                     bar.as_list(), nowy.as_list())
                            bar = nowy
                            box, origin = self._wycinek(bar)
                            czyste.clear()
                            kotwica = None
                            time.sleep(okres)
                            continue
                    if teraz - t0 > 1.8:
                        log.warning("Trzymam %r przez %.1f s, a nie widze, zeby "
                                    "pasek rosl. Jesli w grze rosnie, to znaczy, "
                                    "ze czytam zle miejsce - napisz mi o tym.",
                                    self.klawisz_ladowania, teraz - t0)
                        break
                    time.sleep(okres)
                    continue

                # Odczyt wypelnienia jest wiarygodny tylko na lewo od rybki.
                if mk is None or fx < mk[1] - 3:
                    czyste.append((teraz, fx))
                    kotwica = (teraz, fx)
                    # Tempo liczymy z ostatniego pol sekundy, a nie z osmiu
                    # ostatnich probek. Osiem probek przy 90 klatkach to
                    # ledwie 0,09 s - na tak krotkim odcinku szum odczytu
                    # +-2 px daje +-20 px/s, czyli dziesiec razy wiecej niz
                    # roznica, ktora chcemy wychwycic.
                    v = _slope(czyste, window=0.5)
                    if v and 60 < v < 600:
                        self.tempo = v
                        zmierzone_tempo = v

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

                if (przewidziane >= cel
                        or (mk is not None and tutaj > mk[2] + 2)
                        or tutaj >= bar.x1 - 3):
                    puszczone, x_przy_puszczeniu = True, tutaj
                    # Ile czasu uplynelo od ostatniego PEWNEGO odczytu
                    # krawedzi wypelnienia. To jest miara, na ktorej stoi
                    # cala celnosc: przez ten czas polozenie nie jest
                    # widziane, tylko liczone z tempa. Kilkadziesiat
                    # milisekund to norma; pol sekundy znaczy, ze bot
                    # strzelal w ciemno i kazdy blad tempa urosl
                    # kilkunastokrotnie.
                    wiek_kotwicy = teraz - at
                    break
                time.sleep(okres)
        finally:
            klawisze.key_up(self.klawisz_ladowania)

        self.prob += 1
        if not puszczone:
            return False
        return self._ocen(bar, box, origin, x_przy_puszczeniu,
                          zmierzone_tempo, wiek_kotwicy)

    def _ocen(self, bar: Bar, box, origin, x_przy_puszczeniu,
              zmierzone_tempo=None, wiek_kotwicy=0.0) -> bool:
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
            if self.stop_flaga.is_set():
                break            # Stop ma dzialac od razu, nie po 0,8 s
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
        # Gdy krawedz schowala sie pod rybka, nie wiemy, GDZIE dokladnie
        # stanela - wiec nie udajemy, ze blad wynosi zero. Gra moze taka
        # probe zaliczyc albo nie; widzisz to Ty, nie bot.
        ocena = ("w obrysie rybki, dokladnego miejsca nie widze" if pod_rybka
                 else f"blad {blad:+.0f} px")
        log.info("Stop na %d px, rybka %d px (%d-%d) -> %s (%s, tempo %s, "
                 "na slepo %.0f ms)",
                 szczyt, srodek, lewa, prawa,
                 "celnie" if trafione else "NIECELNIE", ocena,
                 f"{zmierzone_tempo:.0f} px/s" if zmierzone_tempo else "niezmierzone",
                 wiek_kotwicy * 1000)
        if pod_rybka:
            log.debug("Krawedz wypelnienia schowala sie pod rybka - jej "
                      "dokladnego polozenia nie da sie zmierzyc, wiec nie "
                      "mam sie z tego czego uczyc")
        if wiek_kotwicy > 0.25:
            log.warning("Przez ostatnie %.0f ms nie widzialem krawedzi "
                        "wypelnienia i liczylem ja z tempa - stad pudlo. "
                        "Zwykle znaczy to, ze odczyt paska sie urwal.",
                        wiek_kotwicy * 1000)
        if zmierzone_tempo is None:
            log.info("Nie zdazylem zmierzyc tempa w tym rzucie (rybka "
                     "zaslonila wypelnienie od razu) - uzylem zapamietanego "
                     "%.0f px/s", self.tempo)

        # Douczanie. Gdy koniec wypelnienia zostal pod rybka, jego prawdziwe
        # polozenie jest nieznane - wtedy nie ma czego uczyc i tak jestesmy
        # na celu.
        # Zmienilo sie tempo gry? Przelicz poprawke, zamiast uczyc sie od zera.
        if (zmierzone_tempo and self.tempo_nauki
                and abs(zmierzone_tempo - self.tempo_nauki) / self.tempo_nauki > 0.015):
            stara = self.poprawka
            self.poprawka *= zmierzone_tempo / self.tempo_nauki
            log.info("Tempo wypelniania zmienilo sie z %.0f na %.0f px/s "
                     "(%+.1f%%) - przeliczam poprawke celu %.1f -> %.1f px",
                     self.tempo_nauki, zmierzone_tempo,
                     (zmierzone_tempo / self.tempo_nauki - 1) * 100,
                     stara, self.poprawka)
            self.tempo_nauki = zmierzone_tempo

        zaslonione = (ostatnia_rybka is not None
                      and ostatnia_rybka[1] - 3 <= szczyt <= ostatnia_rybka[2] + 1)
        if (self.uczenie and x_przy_puszczeniu is not None
                and not zaslonione and self.tempo > 20):
            opoznienie = (szczyt - x_przy_puszczeniu) / self.tempo * 1000.0
            if -50 <= opoznienie <= 400:
                self.wyprzedzenie_ms = max(0.0, min(
                    260.0, 0.5 * self.wyprzedzenie_ms + 0.5 * opoznienie))
            if abs(blad) <= 60:
                # Gdy ostatnie rzuty chybiaja W TE SAMA STRONE, to nie jest
                # szum, tylko przesuniecie - i nie ma po co dochodzic do
                # niego polowkami. Nadrabiamy wtedy caly blad naraz.
                self.ostatnie_bledy.append(blad)
                krok = 0.5
                if len(self.ostatnie_bledy) >= 4:
                    znaki = [1 if b > 0 else -1 for b in self.ostatnie_bledy if abs(b) > 1]
                    if len(znaki) >= 4 and abs(sum(znaki)) == len(znaki):
                        krok = 1.0
                        log.info("Cztery pudla pod rzad w te sama strone - "
                                 "poprawiam celowanie od razu o caly blad")
                self.poprawka = max(-35.0, min(35.0, self.poprawka + krok * blad))
                if zmierzone_tempo:
                    self.tempo_nauki = zmierzone_tempo
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
                    if pudla_z_rzedu >= self.max_pudel:
                        log.error("%d zarzucen bez brania - pewnie skonczyla sie "
                                  "przyneta. Zatrzymuje sie.", pudla_z_rzedu)
                        self.push.send("Metin2: lowienie stoi",
                                       f"{pudla_z_rzedu} zarzucen bez brania - "
                                       f"pewnie skonczyla sie przyneta.",
                                       priority=4, tags="warning")
                        break
                    # Najczestszy powod nieudanego zarzucenia to zarzucenie
                    # ZA WCZESNIE, w trakcie animacji. Z kazda nieudana proba
                    # czekamy wiec troche dluzej - jesli o to chodzilo, bot
                    # sam znajdzie wlasciwa dlugosc przerwy.
                    self._gladkie_zarzuty = 0
                    stara = self.po_rundzie
                    self.po_rundzie = min(self.przerwa_max, self.po_rundzie + 0.4)
                    if self.po_rundzie > stara:
                        log.info("Wydluzam przerwe po rundzie %.1f -> %.1f s - "
                                 "moze zarzucalem, zanim skonczyla sie animacja",
                                 stara, self.po_rundzie)
                    self._spij(self.po_rundzie + 0.6 * pudla_z_rzedu)
                    continue
                pudla_z_rzedu = 0
                # Zarzut sie udal - pasek przyszedl. Po kilku takich z rzedu
                # mozemy sprobowac czekac krocej; gdy okaze sie, ze za krotko,
                # petla wyzej zaraz to cofnie.
                self._gladkie_zarzuty += 1
                if self._gladkie_zarzuty >= 5 and self.po_rundzie > self.przerwa_min:
                    self._gladkie_zarzuty = 0
                    stara = self.po_rundzie
                    self.po_rundzie = max(self.przerwa_min, self.po_rundzie - 0.1)
                    log.debug("Piec zarzucen z rzedu bez pudla - skracam przerwe "
                              "%.1f -> %.1f s", stara, self.po_rundzie)
                try:
                    zlowione = self.zagraj(bar)
                except _OknoZmienione:
                    log.info("Okno gry zmienilo rozmiar - szukam paska od nowa")
                    continue
                self.na_zmiane()
                self.czekaj_az_zniknie(2.0)
                self._spij(self.po_rundzie)
        except _Przerwane:
            log.info("Zatrzymane.")
        except _GraZnikla:
            log.warning("Okno gry zniknelo - gra zostala zamknieta albo sie "
                        "rozlaczyla. Koncze.")
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
            if not okno_zyje(self.hwnd):
                raise _GraZnikla()
            if not powiedziane:
                powiedziane = True
                log.info("Czekam, az przelaczysz sie na okno gry...")
            time.sleep(0.3)

    def _zapisz_nauke(self) -> None:
        l = self.ust.setdefault("lowienie", {})
        l["tempo_px_s"] = round(self.tempo, 1)
        l["wyprzedzenie_ms"] = round(self.wyprzedzenie_ms, 1)
        l["poprawka_px"] = round(self.poprawka, 1)
        l["tempo_nauki"] = round(self.tempo_nauki, 1)
        l["po_rundzie"] = round(self.po_rundzie, 2)


class _Przerwane(Exception):
    """Wewnetrzne: ktos nacisnal Stop."""


class _GraZnikla(Exception):
    """Wewnetrzne: okno gry przestalo istniec."""


class _OknoZmienione(Exception):
    """Wewnetrzne: okno zmienilo rozmiar, zapamietany pasek jest nieaktualny."""

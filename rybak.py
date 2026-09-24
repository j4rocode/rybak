"""
Rybak - automatyczne lowienie ryb w Metin2.

    Uruchom przez Rybak.bat (jako administrator - inaczej klawisze nie dojda
    do gry).

Cale okienko ma byc zrozumiale dla kogos, kto pierwszy raz to widzi, wiec
trzyma sie trzech zasad:

  * NIC NIE TRZEBA KALIBROWAC. Okno gry program znajduje sam, skalowanie
    ekranu wykrywa sam, pasek mini-gry rozpoznaje po wygladzie (niebieska
    rybka w ciemnym korycie posrodku okna), a tempo ladowania i opoznienie
    klawiatury mierzy w trakcie lowienia.
  * JEDEN PRZYCISK. "Zacznij lowic" i tyle. Reszta to opcje, ktore moga
    zostac nieruszone.
  * KAZDY KOMUNIKAT MOWI, CO ZROBIC. Zamiast "brak uprawnien" - "uruchom
    przez Rybak.bat".
"""

from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except ImportError:                          # pragma: no cover
    print("Brak modulu tkinter. Zainstaluj Pythona z python.org "
          "(przy instalacji zaznacz 'tcl/tk').")
    raise SystemExit(1)

from rybak.wymagania import sprawdz_lub_wyjdz

sprawdz_lub_wyjdz()

from rybak import __version__ as WERSJA                        # noqa: E402
from rybak import aktualizacja, ustawienia                     # noqa: E402
from rybak.lowienie import Rybak                               # noqa: E402
from rybak.okno import kandydaci_na_gre, znajdz_gre            # noqa: E402
from rybak.push import Push                                    # noqa: E402

log = logging.getLogger("rybak")


class DoOkienka(logging.Handler):
    """Log bota trafia do kolejki, a okienko przepisuje go na ekran."""

    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q

    def emit(self, record):
        try:
            self.q.put_nowait(self.format(record))
        except Exception:
            pass


class Okno:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.ust = ustawienia.wczytaj()
        self.kolejka: queue.Queue = queue.Queue()
        self.rybak: Rybak | None = None
        self.watek: threading.Thread | None = None
        self.hwnd = None
        self.tytul_gry = None

        root.title("Rybak - lowienie ryb w Metin2")
        self._dopasuj_do_ekranu()

        # Po aktualizacji zostaja pliki ".stara" - plik w uzyciu nie daje
        # sie skasowac w trakcie podmiany, ale przy nastepnym starcie juz tak.
        try:
            aktualizacja.posprzataj(Path(__file__).resolve().parent)
        except Exception:
            pass

        self._zbuduj()
        self._podlacz_log()
        self._szukaj_gry()
        self._cichy_podglad_wersji()
        self.root.after(120, self._odswiez_log)
        root.protocol("WM_DELETE_WINDOW", self._zamknij)

    # ------------------------------------------------------------- budowa

    def _dopasuj_do_ekranu(self) -> None:
        """
        Rozmiar okna i czcionek dobrany do TEGO ekranu.

        Dwie rzeczy, ktore trzeba tu pogodzic. Po pierwsze program musi byc
        "swiadomy DPI" - inaczej przy skalowaniu ekranu rozjechalyby sie
        wspolrzedne zrzutu i bot patrzylby obok paska. Ale swiadomy DPI
        znaczy tez, ze Windows NIE powieksza mu okna sam: na laptopie ze
        skalowaniem 150% interfejs wyszedlby w dwoch trzecich wielkosci.
        Skalujemy go wiec sami, wedlug prawdziwego DPI.

        Po drugie okno musi sie zmiescic. Na ekranie 1366x768 - a takich
        laptopow jest pelno - wysokie okno wystaje poza pulpit i przycisk
        "Zacznij lowic" lezy poza ekranem. Dlatego docelowy rozmiar
        przycinamy do tego, co ekran naprawde ma.
        """
        try:
            import ctypes
            dpi = int(ctypes.windll.user32.GetDpiForSystem())
        except Exception:
            dpi = 96
        skala = min(2.0, max(1.0, dpi / 96.0))
        if skala > 1.01:
            try:
                self.root.tk.call("tk", "scaling", skala * 96.0 / 72.0)
            except Exception:
                skala = 1.0

        szer = int(640 * skala)
        wys = int(940 * skala)
        try:
            szer = min(szer, int(self.root.winfo_screenwidth() * 0.95))
            wys = min(wys, int(self.root.winfo_screenheight() * 0.90))
        except Exception:
            pass
        self.root.geometry(f"{szer}x{wys}")
        self.root.minsize(min(560, szer), min(430, wys))

    def _pokaz_nauke(self) -> None:
        l = self._sekcja("lowienie")
        p = float(l.get("poprawka_px", 0) or 0)
        tempo = l.get("tempo_px_s")
        self.etykieta_nauki.config(
            text=f"Bot dolozyl od siebie: {-p:+.1f} px"
                 + (f"   (zmierzone tempo {float(tempo):.0f} px/s)" if tempo else ""))

    def _wyzeruj_nauke(self) -> None:
        """
        Skasuj to, czego bot nauczyl sie sam.

        Przydaje sie po zmianie poziomu lowienia albo po przeczytaniu ksiegi:
        stare liczby opisuja gre, ktorej juz nie ma, a bot dochodzi do nowych
        kilka rzutow. Twojego recznego przesuniecia celu to nie rusza.
        """
        if self.rybak is not None:
            messagebox.showwarning("Rybak", "Najpierw zatrzymaj lowienie.")
            return
        l = self._sekcja("lowienie")
        for k in ("poprawka_px", "wyprzedzenie_ms", "tempo_px_s", "tempo_nauki"):
            l[k] = 0.0 if k != "tempo_px_s" else None
        ustawienia.zapisz(self.ust)
        self._pokaz_nauke()
        self._pisz("Wyzerowalem nauke - tempo i poprawka zmierza sie od nowa "
                   "przy najblizszych rzutach.")

    def _sekcja(self, nazwa: str) -> dict:
        """
        Sekcja ustawien, zawsze jako slownik.

        Uzytkownik moze recznie zepsuc ustawienia.json - wpisac tam null
        albo liczbe. Wczytywanie broni sie tylko przed JSON-em, ktory sie
        nie parsuje, wiec bez tego program umieralby tracebackiem, zanim
        jeszcze pokaze okno.
        """
        w = self.ust.get(nazwa)
        if not isinstance(w, dict):
            w = dict(ustawienia.DOMYSLNE.get(nazwa) or {})
            self.ust[nazwa] = w
        return w

    def _zbuduj(self) -> None:
        pad = {"padx": 10, "pady": 4}

        # --- gra
        ramka = ttk.LabelFrame(self.root, text=" 1. Gra ")
        ramka.pack(fill="x", **pad)
        self.etykieta_gry = ttk.Label(ramka, text="Szukam okna gry...")
        self.etykieta_gry.pack(side="left", padx=8, pady=6)
        ttk.Button(ramka, text="Szukaj jeszcze raz",
                   command=self._szukaj_gry).pack(side="right", padx=6, pady=6)
        ttk.Button(ramka, text="Wybierz recznie",
                   command=self._wybierz_gre).pack(side="right", pady=6)

        # --- klawisze
        ramka2 = ttk.LabelFrame(self.root, text=" 2. Klawisze i przerwy ")
        ramka2.pack(fill="x", **pad)
        l = self._sekcja("lowienie")
        self.v_przyneta = tk.StringVar(value=l.get("przyneta", "1"))
        self.v_zarzut = tk.StringVar(value=l.get("zarzut", "space"))
        ttk.Label(ramka2, text="Przyneta:").grid(row=0, column=0, padx=8, pady=6, sticky="w")
        ttk.Entry(ramka2, textvariable=self.v_przyneta, width=8).grid(row=0, column=1)
        ttk.Label(ramka2, text="Zarzucenie i ladowanie:").grid(row=0, column=2, padx=(20, 6))
        ttk.Entry(ramka2, textvariable=self.v_zarzut, width=8).grid(row=0, column=3)
        ttk.Label(ramka2, text="Przerwy w sekundach:").grid(
            row=1, column=0, columnspan=4, padx=8, pady=(8, 2), sticky="w")

        # Cztery przerwy, kazda z innego powodu - dlatego osobno, a nie
        # jednym suwakiem "szybkosc". Najwazniejsza jest "po pudle": po
        # nieudanej probie animacja w grze trwa dluzej i to wlasnie wtedy
        # bot zarzuca za wczesnie, a gra gubi klawisz.
        self.v_przerwy = {}
        opis = [
            ("po_zlowieniu", "po rundzie, min", 0.7,
             "bot sam dostraja sie w tym zakresie"),
            ("po_pudle", "po rundzie, maks", 3.0,
             "zwieksz, jesli gubi zarzuty"),
            ("po_przynecie", "po przynecie", 0.5,
             "od nalozenia przynety do zarzutu"),
            ("po_zarzuceniu", "po zarzuceniu", 0.9,
             "zanim zacznie wypatrywac paska"),
        ]
        for i, (klucz, etykieta, domyslnie, podpowiedz) in enumerate(opis):
            wiersz = 2 + i
            ttk.Label(ramka2, text=etykieta + ":").grid(
                row=wiersz, column=0, padx=(20, 4), sticky="e")
            zm = tk.StringVar(value=str(l.get(klucz, domyslnie)))
            self.v_przerwy[klucz] = zm
            ttk.Spinbox(ramka2, textvariable=zm, width=6, from_=0.0, to=10.0,
                        increment=0.1).grid(row=wiersz, column=1, sticky="w")
            ttk.Label(ramka2, text=podpowiedz).grid(
                row=wiersz, column=2, columnspan=2, padx=(10, 8), sticky="w")
        ttk.Label(ramka2,
                  text="Za krotko = gra gubi klawisz i runda przepada.").grid(
            row=6, column=0, columnspan=4, padx=8, pady=(4, 0), sticky="w")
        ttk.Label(ramka2,
                  text="Po rundzie bot wydluza przerwe po kazdym zgubionym "
                       "zarzuceniu i skraca po pieciu udanych.").grid(
            row=7, column=0, columnspan=4, padx=8, pady=(0, 4), sticky="w")

        # Przerwanie animacji wyciagania - najwiekszy pojedynczy zysk na
        # czasie, wiec ma wlasny wiersz, a nie schowek w pliku ustawien.
        self.v_kon = tk.BooleanVar(value=bool(l.get("kon_wlaczony", True)))
        ttk.Checkbutton(ramka2,
                        text="Przerywaj animacje wyciagania ryby skrotem:",
                        variable=self.v_kon).grid(row=8, column=0, columnspan=2,
                                                  padx=8, sticky="w")
        self.v_kon_skrot = tk.StringVar(value=l.get("kon_skrot", "ctrl+h"))
        ttk.Entry(ramka2, textvariable=self.v_kon_skrot, width=10).grid(
            row=8, column=2, sticky="w")
        ttk.Label(ramka2, text="odstep wsiadz -> zsiadz:").grid(
            row=9, column=0, padx=(20, 4), sticky="e")
        self.v_kon_odstep = tk.StringVar(value=str(l.get("kon_odstep", 0.8)))
        ttk.Spinbox(ramka2, textvariable=self.v_kon_odstep, width=6, from_=0.1,
                    to=3.0, increment=0.1).grid(row=9, column=1, sticky="w")
        ttk.Button(ramka2, text="Sprawdz skrot konia",
                   command=self._test_konia).grid(row=9, column=2, columnspan=2,
                                                  padx=(10, 8), sticky="w")
        ttk.Label(ramka2, text="wsiada na konia i zsiada - to ucina animacje. "
                               "Kon musi byc przywolany.").grid(
            row=10, column=0, columnspan=4, padx=8, pady=(0, 6), sticky="w")

        # --- celowanie
        ramkaC = ttk.LabelFrame(self.root, text=" 3. Celowanie ")
        ramkaC.pack(fill="x", **pad)
        ttk.Label(ramkaC, text="Przesuniecie celu (px):").grid(
            row=0, column=0, padx=8, pady=6, sticky="w")
        self.v_celowanie = tk.StringVar(value=str(l.get("celowanie_px", 7)))
        ttk.Spinbox(ramkaC, textvariable=self.v_celowanie, width=6,
                    from_=-30, to=30, increment=1).grid(row=0, column=1, sticky="w")
        ttk.Label(ramkaC,
                  text="mniej = puszcza wczesniej  |  wiecej = puzniej").grid(
            row=0, column=2, padx=(10, 8), sticky="w")
        self.v_uczenie = tk.BooleanVar(value=bool(l.get("uczenie", True)))
        ttk.Checkbutton(ramkaC, text="Bot moze sam dostrajac celowanie",
                        variable=self.v_uczenie).grid(row=1, column=0, columnspan=2,
                                                      padx=8, sticky="w")
        ttk.Button(ramkaC, text="Wyzeruj nauke",
                   command=self._wyzeruj_nauke).grid(row=1, column=2, padx=(10, 8),
                                                     pady=(0, 6), sticky="w")
        self.etykieta_nauki = ttk.Label(ramkaC, text="")
        self.etykieta_nauki.grid(row=2, column=0, columnspan=3, padx=8,
                                 pady=(0, 6), sticky="w")
        self._pokaz_nauke()

        # --- powiadomienia
        ramka3 = ttk.LabelFrame(self.root, text=" 4. Powiadomienia na telefon (opcjonalne) ")
        ramka3.pack(fill="x", **pad)
        p = self._sekcja("powiadomienia")
        self.v_push = tk.BooleanVar(value=bool(p.get("enabled")))
        ttk.Checkbutton(ramka3, text="Wysylaj powiadomienia",
                        variable=self.v_push).grid(row=0, column=0, padx=8,
                                                   pady=4, sticky="w")
        self.v_kanal = tk.StringVar(
            value=p.get("ntfy_topic") or ustawienia.losowy_kanal())
        ttk.Label(ramka3, text="Kanal:").grid(row=1, column=0, padx=8, sticky="w")
        ttk.Entry(ramka3, textvariable=self.v_kanal, width=32).grid(row=1, column=1,
                                                                   sticky="w")
        ttk.Button(ramka3, text="Jak to wlaczyc na telefonie?",
                   command=self._pomoc_push).grid(row=1, column=2, padx=6)
        ttk.Button(ramka3, text="Wyslij test",
                   command=self._test_push).grid(row=1, column=3, padx=6)

        self.v_koperta = tk.BooleanVar(
            value=bool(self._sekcja("koperta").get("wlaczone", True)))
        self.v_rozmowy = tk.BooleanVar(
            value=bool(self._sekcja("rozmowy").get("wlaczone", False)))
        ttk.Checkbutton(ramka3, text="Przerwij lowienie, gdy ktos napisze PW",
                        variable=self.v_koperta).grid(row=2, column=0, columnspan=2,
                                                      padx=8, sticky="w")
        ttk.Checkbutton(ramka3, text="Powiadom, gdy ktos obok cos powie",
                        variable=self.v_rozmowy).grid(row=3, column=0, columnspan=2,
                                                      padx=8, pady=(0, 6), sticky="w")

        # --- aktualizacja
        ramka35 = ttk.LabelFrame(self.root, text=" 5. Aktualizacja ")
        ramka35.pack(fill="x", **pad)
        self.etykieta_wersji = ttk.Label(ramka35, text=f"Masz wersje {WERSJA}.")
        self.etykieta_wersji.grid(row=0, column=0, columnspan=3, padx=8,
                                  pady=(6, 2), sticky="w")
        ttk.Label(ramka35, text="Adres nowych wersji:").grid(row=1, column=0,
                                                             padx=8, sticky="w")
        self.v_zrodlo = tk.StringVar(value=self.ust.get("zrodlo_aktualizacji", ""))
        ttk.Entry(ramka35, textvariable=self.v_zrodlo, width=34).grid(row=1, column=1,
                                                                      sticky="w")
        self.przycisk_akt = ttk.Button(ramka35, text="Sprawdz aktualizacje",
                                       command=self._sprawdz_aktualizacje)
        self.przycisk_akt.grid(row=1, column=2, padx=6)
        ttk.Button(ramka35, text="Z pliku ZIP...",
                   command=self._aktualizuj_z_pliku).grid(row=1, column=3,
                                                          padx=(0, 8), pady=4)

        # --- sterowanie
        ramka4 = ttk.Frame(self.root)
        ramka4.pack(fill="x", **pad)
        self.przycisk = ttk.Button(ramka4, text="Zacznij lowic",
                                   command=self._start)
        self.przycisk.pack(side="left", ipadx=24, ipady=6)
        self.stan = ttk.Label(ramka4, text="Gotowy.")
        self.stan.pack(side="left", padx=14)

        # --- log
        ramka5 = ttk.LabelFrame(self.root, text=" Co sie dzieje ")
        ramka5.pack(fill="both", expand=True, **pad)
        self.log_box = tk.Text(ramka5, height=6, wrap="word", state="disabled",
                               font=("Consolas", 9))
        pasek = ttk.Scrollbar(ramka5, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=pasek.set)
        pasek.pack(side="right", fill="y")
        self.log_box.pack(fill="both", expand=True, padx=6, pady=6)

    def _podlacz_log(self) -> None:
        log.setLevel(logging.INFO)
        h = DoOkienka(self.kolejka)
        h.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
        log.addHandler(h)
        log.propagate = False

    # -------------------------------------------------------------- gra

    def _szukaj_gry(self) -> None:
        hwnd, tytul = znajdz_gre(self.ust.get("okno_gry", ""))
        self.hwnd, self.tytul_gry = hwnd, tytul
        if hwnd:
            self.etykieta_gry.config(text=f"Znalazlem: {tytul}")
            self._pisz(f"Okno gry: {tytul}")
        else:
            self.etykieta_gry.config(
                text="Nie widze okna gry - wlacz Metina i kliknij 'Szukaj jeszcze raz'")

    def _wybierz_gre(self) -> None:
        okna = kandydaci_na_gre()
        if not okna:
            messagebox.showinfo("Rybak", "Nie widze zadnego okna, ktore moglaby "
                                         "byc gra. Czy Metin jest uruchomiony?")
            return
        top = tk.Toplevel(self.root)
        top.title("Ktore okno to gra?")
        top.geometry("520x320")
        ttk.Label(top, text="Kliknij okno gry, potem OK:").pack(anchor="w", padx=10,
                                                                pady=(10, 4))
        lista = tk.Listbox(top, font=("Consolas", 9))
        for hwnd, tytul, w, h in okna:
            lista.insert("end", f"{w}x{h}   {tytul}")
        lista.pack(fill="both", expand=True, padx=10, pady=4)
        lista.selection_set(0)

        def wybierz():
            i = lista.curselection()
            if i:
                self.hwnd, self.tytul_gry = okna[i[0]][0], okna[i[0]][1]
                self.ust["okno_gry"] = self.tytul_gry
                self.etykieta_gry.config(text=f"Wybrane: {self.tytul_gry}")
                self._pisz(f"Okno gry ustawione recznie: {self.tytul_gry}")
            top.destroy()

        ttk.Button(top, text="OK", command=wybierz).pack(pady=8)

    # ------------------------------------------------------- powiadomienia

    def _pomoc_push(self) -> None:
        messagebox.showinfo(
            "Powiadomienia na telefon",
            "1. Zainstaluj na telefonie darmowa aplikacje 'ntfy'\n"
            "   (Google Play albo App Store).\n\n"
            "2. W aplikacji nacisnij + i wpisz DOKLADNIE te nazwe kanalu:\n\n"
            f"      {self.v_kanal.get()}\n\n"
            "3. Wroc tutaj, zaznacz 'Wysylaj powiadomienia' i nacisnij\n"
            "   'Wyslij test'. Powinno zadzwonic.\n\n"
            "UWAGA: ntfy nie ma hasel - kto zna nazwe kanalu, ten widzi\n"
            "Twoje powiadomienia razem ze zrzutami ekranu. Dlatego nazwa\n"
            "jest dluga i losowa; nie zmieniaj jej na 'metin' i nie podawaj\n"
            "nikomu obcemu.")

    def _test_push(self) -> None:
        self._zbierz_ustawienia()
        cfg = dict(self._sekcja("powiadomienia"))
        cfg["enabled"] = True
        push = Push(cfg)
        if not push.topic:
            messagebox.showwarning("Rybak", "Najpierw wpisz nazwe kanalu.")
            return
        self._pisz(f"Wysylam test na {push.url} ...")

        def wyslij():
            push.send("Rybak: test", "Jesli to widzisz na telefonie - dziala.",
                      priority=4, tags="white_check_mark", blocking=True)
            self.kolejka.put("Test wyslany. Sprawdz telefon.")

        threading.Thread(target=wyslij, daemon=True).start()

    def _test_konia(self) -> None:
        """
        Wcisnij skrot konia dwa razy, bez lowienia.

        Rozdziela dwa pytania, ktore w trakcie lowienia zlewaja sie w jedno:
        czy gra w ogole przyjmuje ten skrot od bota, i czy odstep miedzy
        wsiadaniem a zsiadaniem jest wystarczajacy.
        """
        if self.rybak is not None:
            messagebox.showinfo("Rybak", "Najpierw zatrzymaj lowienie.")
            return
        self._zbierz_ustawienia()
        l = self._sekcja("lowienie")
        skrot = l.get("kon_skrot") or "ctrl+h"
        odstep = float(l.get("kon_odstep", 0.8))
        trzymaj = float(l.get("kon_przytrzymaj", 0.10))
        self._pisz(f"Test konia: kliknij TERAZ w okno gry. Za 3 s wcisne "
                   f"{skrot}, a po {odstep:.1f} s jeszcze raz.")

        def testuj():
            from rybak import klawisze
            time.sleep(3.0)
            self.kolejka.put(f"Wciskam {skrot} - postac powinna WSIASC na konia")
            klawisze.kombinacja(skrot, trzymaj)
            time.sleep(odstep)
            self.kolejka.put(f"Wciskam {skrot} - postac powinna ZSIASC")
            klawisze.kombinacja(skrot, trzymaj)
            self.kolejka.put(
                "Test skonczony. Nie wsiadla ani razu = gra nie przyjmuje "
                "skrotu (kon przywolany? bot uruchomiony jako administrator?). "
                "Wsiadla, ale zostala na koniu = zwieksz odstep.")

        threading.Thread(target=testuj, daemon=True).start()

    # ------------------------------------------------------------ start

    def _zbierz_ustawienia(self) -> None:
        l = self._sekcja("lowienie")
        l["przyneta"] = self.v_przyneta.get().strip() or "1"
        l["zarzut"] = self.v_zarzut.get().strip() or "space"
        l["ladowanie"] = l["zarzut"]
        for klucz, zm in self.v_przerwy.items():
            try:
                l[klucz] = max(0.0, min(10.0, float(
                    zm.get().replace(",", "."))))
            except ValueError:
                pass                  # zostaw to, co bylo - nie karz za literowke
        try:
            l["celowanie_px"] = max(-30.0, min(30.0, float(
                self.v_celowanie.get().replace(",", "."))))
        except ValueError:
            pass
        l["uczenie"] = bool(self.v_uczenie.get())
        l["kon_wlaczony"] = bool(self.v_kon.get())
        l["kon_skrot"] = self.v_kon_skrot.get().strip().lower()
        try:
            l["kon_odstep"] = max(0.1, min(3.0, float(
                self.v_kon_odstep.get().replace(",", "."))))
        except ValueError:
            pass
        p = self._sekcja("powiadomienia")
        p["enabled"] = bool(self.v_push.get())
        p["ntfy_topic"] = self.v_kanal.get().strip()
        self._sekcja("koperta")["wlaczone"] = bool(self.v_koperta.get())
        self._sekcja("rozmowy")["wlaczone"] = bool(self.v_rozmowy.get())
        self.ust["zrodlo_aktualizacji"] = self.v_zrodlo.get().strip()
        if self.tytul_gry:
            self.ust["okno_gry"] = self.tytul_gry
        ustawienia.zapisz(self.ust)

    def _start(self) -> None:
        if self.rybak is not None:
            self.rybak.stop()
            self.stan.config(text="Zatrzymuje...")
            return
        if not self.hwnd:
            messagebox.showwarning("Rybak", "Najpierw wlacz gre i kliknij "
                                            "'Szukaj jeszcze raz'.")
            return
        if not self._czy_admin():
            if not messagebox.askyesno(
                    "Rybak",
                    "Program nie dziala jako administrator.\n\n"
                    "Jesli gra jest uruchomiona jako administrator, Windows nie "
                    "pozwoli wyslac do niej klawiszy - bot bedzie wygladal, "
                    "jakby nic nie robil.\n\n"
                    "Zalecam zamknac to okno i uruchomic Rybak.bat "
                    "(zgodzic sie na pytanie Windowsa).\n\n"
                    "Sprobowac mimo to?"):
                return
        self._zbierz_ustawienia()
        self._pisz("")
        self._pisz("--- START ---")
        self._pisz("Przelacz sie teraz na okno gry. Stanie przy wodzie "
                   "z wedka w rece.")
        self.rybak = Rybak(self.hwnd, self.ust, na_zmiane=self._po_zmianie)
        self.watek = threading.Thread(target=self._praca, daemon=True)
        self.watek.start()
        self.przycisk.config(text="Zatrzymaj")
        self.stan.config(text="Lowie...")

    def _praca(self) -> None:
        try:
            self.rybak.run()
        finally:
            ustawienia.zapisz(self.ust)
            self.kolejka.put("__koniec__")

    def _po_zmianie(self) -> None:
        r = self.rybak
        if r is None:
            return
        self.kolejka.put(
            f"__stan__Zarzucen {r.zarzucen}, celnych {r.trafien}/{r.prob}")

    @staticmethod
    def _czy_admin() -> bool:
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return True           # nie Windows albo nie da sie sprawdzic


    # ------------------------------------------------------- aktualizacja

    def _folder_programu(self) -> Path:
        return Path(__file__).resolve().parent

    def _cichy_podglad_wersji(self) -> None:
        """
        Przy starcie tylko ZERKAMY, czy jest cos nowego, i piszemy to na
        etykiecie. Bez okienka z pytaniem - nikt nie lubi, gdy program
        zaczyna rozmowe, zanim zdazysz kliknac cokolwiek.
        """
        zrodlo = self.ust.get("zrodlo_aktualizacji", "").strip()
        if not zrodlo:
            return

        def zerknij():
            try:
                tymczas = Path(tempfile.gettempdir()) / "rybak_akt"
                _p, wersja, nowsza = aktualizacja.sprawdz(zrodlo, WERSJA, tymczas)
            except Exception:
                return                    # brak sieci to nie powod do alarmu
            if nowsza:
                self.kolejka.put(f"__akt_jest__{wersja}")

        threading.Thread(target=zerknij, daemon=True).start()

    def _sprawdz_aktualizacje(self) -> None:
        zrodlo = self.v_zrodlo.get().strip()
        if not zrodlo:
            messagebox.showinfo(
                "Aktualizacja",
                "Wklej najpierw adres, spod ktorego mam brac nowe wersje.\n\n"
                "Najwygodniej adres repozytorium na GitHubie, np.\n"
                "   https://github.com/ktos/rybak\n"
                "Program sam zamieni go na adres paczki.\n\n"
                "Jesli nie masz takiego adresu, uzyj 'Z pliku ZIP...' i wskaz\n"
                "paczke przyniesiona na pendrive albo przyslana mailem.")
            return
        self.przycisk_akt.config(state="disabled", text="Sprawdzam...")
        threading.Thread(target=self._sprawdz_w_tle, args=(zrodlo,),
                         daemon=True).start()

    def _sprawdz_w_tle(self, zrodlo: str) -> None:
        try:
            tymczas = Path(tempfile.gettempdir()) / "rybak_akt"
            paczka, wersja, nowsza = aktualizacja.sprawdz(zrodlo, WERSJA, tymczas)
        except Exception as exc:
            self.kolejka.put(f"__akt_blad__{exc}")
            return
        self.kolejka.put(f"__akt_gotowe__{paczka}|{wersja}|{int(nowsza)}")

    def _aktualizuj_z_pliku(self) -> None:
        from tkinter import filedialog
        plik = filedialog.askopenfilename(
            title="Wskaz paczke z nowa wersja",
            filetypes=[("Paczka ZIP", "*.zip"), ("Wszystkie pliki", "*.*")])
        if not plik:
            return
        try:
            import zipfile
            with zipfile.ZipFile(plik) as zf:
                wersja = aktualizacja.wersja_w_paczce(
                    zf, aktualizacja.korzen_paczki(zf))
        except Exception as exc:
            messagebox.showerror("Aktualizacja", f"Nie moge otworzyc tej paczki:\n{exc}")
            return
        self._zapytaj_i_zainstaluj(Path(plik), wersja,
                                   aktualizacja.nowsza(wersja, WERSJA))

    def _zapytaj_i_zainstaluj(self, paczka: Path, wersja: str, nowsza: bool) -> None:
        if self.rybak is not None:
            messagebox.showwarning("Aktualizacja",
                                   "Najpierw zatrzymaj lowienie.")
            return
        if not nowsza:
            if not messagebox.askyesno(
                    "Aktualizacja",
                    f"W paczce jest wersja {wersja}, a masz {WERSJA} - "
                    f"czyli nie jest nowsza.\n\nWgrac ja mimo to?"):
                return
        elif not messagebox.askyesno(
                "Aktualizacja",
                f"Jest nowa wersja: {wersja} (masz {WERSJA}).\n\n"
                f"Wgrac ja teraz?\n\n"
                f"Twoje ustawienia i to, czego bot sie nauczyl, zostaja "
                f"nietkniete. Stara wersja zostanie skopiowana do folderu "
                f"'kopia_...' obok programu."):
            return
        try:
            ile, kopia = aktualizacja.zainstaluj(paczka, self._folder_programu())
        except Exception as exc:
            messagebox.showerror("Aktualizacja", f"Nie udalo sie:\n{exc}")
            return
        self._pisz(f"Zaktualizowano do wersji {wersja} ({ile} plikow). "
                   f"Stara wersja: {kopia.name}")
        if messagebox.askyesno(
                "Aktualizacja",
                f"Gotowe - wersja {wersja} wgrana.\n\n"
                f"Zeby zaczela dzialac, program musi sie uruchomic od nowa.\n"
                f"Zrobic to teraz?"):
            self._uruchom_od_nowa()

    def _uruchom_od_nowa(self) -> None:
        """
        Nowy kod zaczyna dzialac dopiero po ponownym starcie - Python wczytal
        stary przy uruchomieniu. Startujemy kopie tym samym Pythonem, wiec
        nowy proces dziedziczy uprawnienia administratora i nie trzeba o nie
        pytac drugi raz.
        """
        self._zbierz_ustawienia()
        try:
            subprocess.Popen([sys.executable, str(self._folder_programu() / "rybak.py")],
                             cwd=str(self._folder_programu()), close_fds=True)
        except Exception as exc:
            messagebox.showerror("Aktualizacja",
                                 f"Nie umiem sie uruchomic od nowa ({exc}).\n"
                                 f"Zamknij to okno i kliknij Rybak.bat.")
            return
        self.root.destroy()
        os._exit(0)

    def _po_sprawdzeniu(self, wiadomosc: str) -> None:
        paczka, wersja, nowsza = wiadomosc.rsplit("|", 2)
        self.przycisk_akt.config(state="normal", text="Sprawdz aktualizacje")
        if nowsza == "1":
            self.etykieta_wersji.config(
                text=f"Masz wersje {WERSJA}. Dostepna: {wersja}!")
            self._zapytaj_i_zainstaluj(Path(paczka), wersja, True)
        else:
            self.etykieta_wersji.config(
                text=f"Masz wersje {WERSJA} - najnowsza.")
            self._pisz(f"Sprawdzone: w zrodle jest wersja {wersja}, "
                       f"czyli nic nowego.")

    # -------------------------------------------------------------- log

    def _pisz(self, tekst: str) -> None:
        self.kolejka.put(tekst)

    def _odswiez_log(self) -> None:
        try:
            while True:
                wiersz = self.kolejka.get_nowait()
                if wiersz == "__koniec__":
                    self.rybak = None
                    self.przycisk.config(text="Zacznij lowic")
                    self.stan.config(text="Gotowy.")
                    self._pokaz_nauke()
                    # Bot mogl sam wydluzyc odstep konia - pokaz nowa wartosc,
                    # inaczej nastepny Start nadpisalby ja stara z okienka.
                    self.v_kon_odstep.set(str(
                        self._sekcja("lowienie").get("kon_odstep", 0.8)))
                    continue
                if wiersz.startswith("__stan__"):
                    self.stan.config(text=wiersz[8:])
                    continue
                if wiersz.startswith("__akt_jest__"):
                    w = wiersz[len("__akt_jest__"):]
                    self.etykieta_wersji.config(
                        text=f"Masz wersje {WERSJA}. Jest juz {w} - "
                             f"kliknij 'Sprawdz aktualizacje'.")
                    continue
                if wiersz.startswith("__akt_gotowe__"):
                    self._po_sprawdzeniu(wiersz[len("__akt_gotowe__"):])
                    continue
                if wiersz.startswith("__akt_blad__"):
                    self.przycisk_akt.config(state="normal",
                                             text="Sprawdz aktualizacje")
                    messagebox.showerror(
                        "Aktualizacja",
                        "Nie udalo sie sprawdzic nowych wersji:\n\n"
                        + wiersz[len("__akt_blad__"):]
                        + "\n\nSprawdz adres i polaczenie z internetem. "
                          "Mozesz tez wgrac nowa wersje z pliku ZIP.")
                    continue
                self.log_box.configure(state="normal")
                self.log_box.insert("end", wiersz + "\n")
                self.log_box.see("end")
                self.log_box.configure(state="disabled")
        except queue.Empty:
            pass
        except Exception as exc:                  # nie wolno przerwac pompy
            # Gdyby cokolwiek tu wybuchlo - zepsuty komunikat, zniszczony
            # widget - a przeplanowanie bylo na koncu, log zamarlby na
            # zawsze i program wygladalby na zawieszony, choc bot pracuje.
            try:
                self.log_box.configure(state="normal")
                self.log_box.insert("end", f"(blad okienka: {exc})\n")
                self.log_box.configure(state="disabled")
            except Exception:
                pass
        finally:
            try:
                self.root.after(120, self._odswiez_log)
            except Exception:
                pass

    def _zamknij(self) -> None:
        # Czekamy, az watek bota naprawde skonczy. Wczesniej bylo tu
        # time.sleep(0.3) - za malo, bo sama ocena rzutu trwa 0,8 s. Watek
        # jest daemon, wiec po wyjsciu z mainloop interpreter ubilby go w
        # dowolnym miejscu, takze w srodku zapisu ustawien: plik zostawalby
        # obciety albo pusty.
        if self.rybak is not None:
            self.rybak.stop()
            if self.watek is not None and self.watek.is_alive():
                self.stan.config(text="Koncze...")
                self.root.update_idletasks()
                self.watek.join(timeout=5.0)
        self._zbierz_ustawienia()
        self.root.destroy()


def main() -> int:
    root = tk.Tk()
    try:
        root.call("source", "sun-valley.tcl")     # jesli ktos dorzuci motyw
    except Exception:
        pass
    Okno(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

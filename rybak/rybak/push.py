"""
Powiadomienia na telefon (ntfy.sh).

Po co: bot potrafi zauwazyc, ze ktos do Ciebie napisal - ale jesli akurat nie
siedzisz przy komputerze, to nic Ci po tym. Wiec obok przerwania lowienia
leci push na telefon, razem z wycinkiem ekranu, na ktorym widac nick nadawcy.

Jak to dziala: ntfy to publiczny serwer, na ktory kazdy moze wyslac wiadomosc
pod dowolna nazwe kanalu, a aplikacja na telefonie te nazwe subskrybuje. Nie
ma kont ani hasel - i to jest zarazem jego jedyna slabosc: KTO ZNA NAZWE
KANALU, TEN CZYTA. Dlatego nazwa ma byc dluga i niezgadywalna, np.
"metin-piotr-7f3k9x", a nie "metin".

Konfiguracja (config.json):

    "push": {
        "enabled": true,
        "ntfy_topic": "metin-piotr-7f3k9x",
        "attach_screenshot": true
    }

Uzywamy tylko biblioteki standardowej, zeby nie dokladac zaleznosci.
"""

from __future__ import annotations

import json
import logging
import threading
import unicodedata
import urllib.error
import urllib.request

log = logging.getLogger("rybak")

DEFAULT_SERVER = "https://ntfy.sh"


# Litery, ktorych rozklad Unicode NIE rozbija na "litera + ogonek", wiec samo
# NFKD ich nie uratuje - "ł" wycielibysmy bez sladu i zostaloby "napisa".
_PODMIANY = str.maketrans({
    "ł": "l", "Ł": "L", "đ": "d", "Đ": "D",
    "ø": "o", "Ø": "O", "æ": "ae", "Æ": "AE", "ß": "ss", "þ": "th",
})


def _ascii(text: str) -> str:
    """
    Naglowki HTTP musza byc ASCII, a "Ktoś napisał" - nie jest. Zdejmujemy
    ogonki zamiast wywalac sie na kodowaniu; "Ktos napisal" czyta sie dobrze.
    """
    norm = unicodedata.normalize("NFKD", text.translate(_PODMIANY))
    return norm.encode("ascii", "ignore").decode("ascii").strip() or "Metin2"


class Push:
    """Wysylka powiadomien. Nigdy nie przerywa pracy bota - bledy tylko loguje."""

    def __init__(self, cfg: dict | None = None):
        cfg = dict(cfg or {})
        self.enabled = bool(cfg.get("enabled", False))
        self.server = str(cfg.get("ntfy_server") or DEFAULT_SERVER).rstrip("/")
        self.topic = str(cfg.get("ntfy_topic") or "").strip()
        self.priority = int(cfg.get("priority", 5))
        self.attach = bool(cfg.get("attach_screenshot", True))
        self.timeout = float(cfg.get("timeout", 8.0))
        # Ile moze wazyc zalacznik i jak mocno pomniejszamy okno gry.
        # 250 kB przy 0.5 to ~660x420 px - nick nad glowa czytelny, a zadanie
        # na tyle male, ze przechodzi przez proxy i VPN.
        self.image_max_bytes = int(float(cfg.get("image_max_kb", 250)) * 1024)
        self.image_scale = float(cfg.get("image_scale", 0.5))
        if self.enabled and not self.topic:
            log.warning("Powiadomienia: wlaczone, ale brak 'push.ntfy_topic' - "
                        "nic nie wysle")
            self.enabled = False

    @property
    def url(self) -> str:
        return f"{self.server}/{self.topic}"

    # --------------------------------------------------------------- wysylka

    def send(self, title: str, message: str, image_png: bytes | None = None,
             priority: int | None = None, tags: str = "envelope",
             blocking: bool = False) -> None:
        """Wyslij powiadomienie. Domyslnie w tle - siec potrafi sie zamyslic."""
        if not self.enabled:
            return
        args = (title, message, image_png, priority, tags)
        if blocking:
            self._send(*args)
        else:
            threading.Thread(target=self._send, args=args, daemon=True).start()

    def _send(self, title, message, image_png, priority, tags) -> None:
        try:
            if image_png:
                self._put_image(title, message, image_png, priority, tags)
            else:
                self._post_json(title, message, priority, tags)
            log.debug("Powiadomienie wyslane: %s", title)
        except urllib.error.HTTPError as exc:
            # 413 = "za duze cialo zadania". Winny jest zalacznik - i to nie
            # musi byc wina ntfy (limit 15 MB), bo po drodze bywa firmowy
            # proxy albo VPN z wlasnym, duzo nizszym limitem. Wazniejsze, ze
            # powiadomienie w ogole dotrze, wiec powtarzamy je bez obrazka.
            if image_png and exc.code in (413, 507, 400):
                log.warning("Powiadomienie z obrazkiem odrzucone (%s %s) - "
                            "wysylam sam tekst", exc.code, exc.reason)
                try:
                    self._post_json(title, message, priority, tags)
                    return
                except Exception as exc2:
                    log.warning("Tekst tez nie poszedl: %s: %s",
                                type(exc2).__name__, exc2)
                    return
            log.warning("Powiadomienie odrzucone przez serwer (%s %s)",
                        exc.code, exc.reason)
        except Exception as exc:
            log.warning("Powiadomienie nie poszlo: %s: %s",
                        type(exc).__name__, exc)

    def _post_json(self, title, message, priority, tags) -> None:
        """Zwykly tekst - przez JSON, wiec polskie znaki przechodza calo."""
        body = json.dumps({
            "topic": self.topic,
            "title": title,
            "message": message,
            "priority": int(priority or self.priority),
            "tags": [t for t in str(tags).split(",") if t],
        }).encode("utf-8")
        req = urllib.request.Request(
            self.server, data=body, method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout):
            pass

    def _put_image(self, title, message, image_png, priority, tags) -> None:
        """Z zalacznikiem - obrazek idzie jako cialo, reszta w naglowkach."""
        png = image_png[:4] == b"\x89PNG"
        req = urllib.request.Request(
            self.url, data=image_png, method="PUT",
            headers={
                "Filename": "wiadomosc.png" if png else "wiadomosc.jpg",
                "Title": _ascii(title),
                "Message": _ascii(message),
                "Priority": str(int(priority or self.priority)),
                "Tags": _ascii(tags),
                "Content-Type": "image/png" if png else "image/jpeg",
            })
        with urllib.request.urlopen(req, timeout=self.timeout):
            pass

    # ------------------------------------------------------------ pomocnicze

    @staticmethod
    def encode_image(rgb, max_bytes: int = 250_000, scale: float = 1.0):
        """
        Zrzut (RGB, numpy) -> male JPEG, zmieszczone w `max_bytes`.

        Dlaczego nie PNG: zrzut okna gry w PNG wazy blisko megabajta, bo PNG
        nie ma jak skrocic trawy i cieni. Ten sam obraz w JPEG to ~70 kB przy
        jakosci, na ktorej wciaz czytasz nick nad glowa. Waga ma znaczenie nie
        z powodu ntfy (tam limit to 15 MB), tylko dlatego, ze po drodze bywa
        proxy albo VPN, ktory odsyla 413 przy duzo mniejszym zadaniu - a wtedy
        nie dostajesz powiadomienia w chwili, gdy najbardziej go potrzebujesz.

        Najpierw schodzimy jakoscia (obraz zostaje ostry), a dopiero gdy to nie
        wystarczy - rozmiarem.
        """
        if rgb is None:
            return None
        try:
            import cv2
            img = rgb[:, :, ::-1]
            if scale and scale != 1.0:
                img = cv2.resize(img, None, fx=scale, fy=scale,
                                 interpolation=cv2.INTER_AREA)
            buf = None
            for jakosc in (85, 75, 60, 45):
                ok, buf = cv2.imencode(".jpg", img,
                                       [cv2.IMWRITE_JPEG_QUALITY, jakosc])
                if ok and buf.size <= max_bytes:
                    return buf.tobytes()
            for krok in (0.7, 0.5, 0.35):
                maly = cv2.resize(img, None, fx=krok, fy=krok,
                                  interpolation=cv2.INTER_AREA)
                ok, buf = cv2.imencode(".jpg", maly,
                                       [cv2.IMWRITE_JPEG_QUALITY, 60])
                if ok and buf.size <= max_bytes:
                    return buf.tobytes()
            return buf.tobytes() if buf is not None else None
        except Exception as exc:
            log.debug("Nie zakodowalem zrzutu: %s", exc)
            return None

    @classmethod
    def encode_png(cls, rgb, max_bytes: int = 250_000):
        """Zgodnosc wstecz - dzis to samo co encode_image (czyli JPEG)."""
        return cls.encode_image(rgb, max_bytes)

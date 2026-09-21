"""
Wysylanie klawiszy i myszy przez SendInput ze scancodami (DirectInput-friendly).

Metin2 (DirectX) czesto ignoruje "wirtualne" klawisze wysylane np. przez
pyautogui, bo czyta stan urzadzenia przez DirectInput. Rozwiazanie: SendInput
z flaga KEYEVENTF_SCANCODE, czyli udajemy fizyczny scancode klawiatury.

Modul dziala tylko na Windows.
"""

from __future__ import annotations

import ctypes
import random
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

# ---------------------------------------------------------------- struktury

ULONG_PTR = ctypes.POINTER(ctypes.c_ulong)


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

# ------------------------------------------------------------- scancode map
# Scancode set 1. Klawisze "rozszerzone" (strzalki, prawy ctrl/alt, numpad /)
# oznaczone sufiksem w EXTENDED.

SCANCODES = {
    "esc": 0x01, "escape": 0x01,
    "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06,
    "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B,
    "minus": 0x0C, "equals": 0x0D, "backspace": 0x0E, "tab": 0x0F,
    "q": 0x10, "w": 0x11, "e": 0x12, "r": 0x13, "t": 0x14,
    "y": 0x15, "u": 0x16, "i": 0x17, "o": 0x18, "p": 0x19,
    "lbracket": 0x1A, "rbracket": 0x1B, "enter": 0x1C, "return": 0x1C,
    "lctrl": 0x1D, "ctrl": 0x1D,
    "a": 0x1E, "s": 0x1F, "d": 0x20, "f": 0x21, "g": 0x22,
    "h": 0x23, "j": 0x24, "k": 0x25, "l": 0x26,
    "semicolon": 0x27, "apostrophe": 0x28, "grave": 0x29,
    "lshift": 0x2A, "shift": 0x2A, "backslash": 0x2B,
    "z": 0x2C, "x": 0x2D, "c": 0x2E, "v": 0x2F, "b": 0x30,
    "n": 0x31, "m": 0x32, "comma": 0x33, "period": 0x34, "slash": 0x35,
    "rshift": 0x36, "lalt": 0x38, "alt": 0x38, "space": 0x39,
    "capslock": 0x3A,
    "f1": 0x3B, "f2": 0x3C, "f3": 0x3D, "f4": 0x3E, "f5": 0x3F,
    "f6": 0x40, "f7": 0x41, "f8": 0x42, "f9": 0x43, "f10": 0x44,
    "f11": 0x57, "f12": 0x58,
    "numlock": 0x45, "scrolllock": 0x46,
    "up": 0x48, "left": 0x4B, "right": 0x4D, "down": 0x50,
    "insert": 0x52, "delete": 0x53, "home": 0x47, "end": 0x4F,
    "pageup": 0x49, "pagedown": 0x51,
    "rctrl": 0x1D, "ralt": 0x38,
}

EXTENDED = {
    "up", "down", "left", "right", "insert", "delete", "home", "end",
    "pageup", "pagedown", "rctrl", "ralt", "numlock",
}

# Virtual-key codes - potrzebne tylko do GetAsyncKeyState (klawisz awaryjny).
VK_CODES = {
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "esc": 0x1B, "escape": 0x1B, "space": 0x20, "tab": 0x09,
    "pause": 0x13, "scrolllock": 0x91, "end": 0x23, "home": 0x24,
    "delete": 0x2E, "insert": 0x2D,
}
VK_CODES.update({"shift": 0x10, "lshift": 0xA0, "rshift": 0xA1,
                 "ctrl": 0x11, "lctrl": 0xA2, "rctrl": 0xA3,
                 "alt": 0x12, "lalt": 0xA4, "ralt": 0xA5})
for _c in "abcdefghijklmnopqrstuvwxyz":
    VK_CODES.setdefault(_c, ord(_c.upper()))
for _c in "0123456789":
    VK_CODES.setdefault(_c, ord(_c))


class InputError(RuntimeError):
    pass


def _send(inputs):
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    sent = user32.SendInput(n, arr, ctypes.sizeof(INPUT))
    if sent != n:
        raise InputError(
            f"SendInput wyslal {sent}/{n} zdarzen "
            f"(err={ctypes.get_last_error()}). "
            "Najczestsza przyczyna: gra dziala jako administrator, a skrypt nie."
        )


def _key_input(scan: int, up: bool, extended: bool) -> INPUT:
    flags = KEYEVENTF_SCANCODE
    if extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    if up:
        flags |= KEYEVENTF_KEYUP
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki = KEYBDINPUT(wVk=0, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=None)
    return inp


def _resolve(key: str):
    k = key.strip().lower()
    if k not in SCANCODES:
        raise KeyError(f"Nieznany klawisz: {key!r}. Dostepne: {sorted(SCANCODES)}")
    return SCANCODES[k], k in EXTENDED


def key_down(key: str) -> None:
    scan, ext = _resolve(key)
    _send([_key_input(scan, False, ext)])


def key_up(key: str) -> None:
    scan, ext = _resolve(key)
    _send([_key_input(scan, True, ext)])


def tap(key: str, hold: float = 0.04, jitter: float = 0.02) -> None:
    """Krotkie nacisniecie z losowym czasem przytrzymania."""
    key_down(key)
    time.sleep(max(0.01, hold + random.uniform(-jitter, jitter)))
    key_up(key)


def hold(key: str, seconds: float) -> None:
    key_down(key)
    try:
        time.sleep(max(0.0, seconds))
    finally:
        key_up(key)


def is_pressed(key: str) -> bool:
    """Stan klawisza globalnie - uzywane do klawisza awaryjnego."""
    k = key.strip().lower()
    vk = VK_CODES.get(k)
    if vk is None:
        raise KeyError(f"Brak kodu VK dla {key!r} (klawisz awaryjny musi byc z listy VK_CODES)")
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


# ------------------------------------------------------------------- mysz


def _virtual_screen():
    return (
        user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
    )


def _abs_move_input(x: int, y: int) -> INPUT:
    vx, vy, vw, vh = _virtual_screen()
    nx = int(round((x - vx) * 65535 / max(1, vw - 1)))
    ny = int(round((y - vy) * 65535 / max(1, vh - 1)))
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi = MOUSEINPUT(
        dx=nx, dy=ny, mouseData=0,
        dwFlags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
        time=0, dwExtraInfo=None,
    )
    return inp


def move_to(x: int, y: int) -> None:
    _send([_abs_move_input(int(x), int(y))])


def cursor_pos():
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def move_smooth(x: int, y: int, steps: int = 6, delay: float = 0.012) -> None:
    """Ruch w kilku krokach z drobnym szumem - mniej robotyczny niz skok."""
    x0, y0 = cursor_pos()
    steps = max(1, int(steps))
    for i in range(1, steps + 1):
        t = i / steps
        # ease-out, zeby koncowka byla wolniejsza
        te = 1 - (1 - t) ** 2
        cx = x0 + (x - x0) * te
        cy = y0 + (y - y0) * te
        if i < steps:
            cx += random.uniform(-1.5, 1.5)
            cy += random.uniform(-1.5, 1.5)
        move_to(int(round(cx)), int(round(cy)))
        time.sleep(delay)


def _button_input(flag: int) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi = MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=flag, time=0, dwExtraInfo=None)
    return inp


def click(button: str = "left", hold_time: float = 0.05) -> None:
    down, up = {
        "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
        "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    }[button]
    _send([_button_input(down)])
    time.sleep(max(0.01, hold_time + random.uniform(-0.015, 0.015)))
    _send([_button_input(up)])


def right_drag(x0: int, y0: int, dx: int, dy: int = 0, steps: int = 14, delay: float = 0.02) -> None:
    """Przeciagniecie z wcisnietym PPM (obrot kamery w Metin2): od (x0,y0) o (dx,dy)."""
    move_to(x0, y0)
    time.sleep(0.05)
    _send([_button_input(MOUSEEVENTF_RIGHTDOWN)])
    try:
        for i in range(1, steps + 1):
            move_to(int(x0 + dx * i / steps), int(y0 + dy * i / steps))
            time.sleep(delay)
    finally:
        _send([_button_input(MOUSEEVENTF_RIGHTUP)])


def click_at(x: int, y: int, button: str = "left") -> None:
    move_smooth(x, y)
    time.sleep(random.uniform(0.03, 0.08))
    click(button)


# ------------------------------------------------------- diagnostyka uprawnien

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TokenElevation = 20

# Bez jawnych argtypes ctypes zaklada c_int dla uchwytow. Pseudo-uchwyt
# biezacego procesu to 0xFFFFFFFFFFFFFFFF i wysypuje sie na OverflowError.
kernel32.GetCurrentProcess.argtypes = []
kernel32.GetCurrentProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.HANDLE)]
advapi32.OpenProcessToken.restype = wintypes.BOOL
advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                         ctypes.c_void_p, wintypes.DWORD,
                                         ctypes.POINTER(wintypes.DWORD)]
advapi32.GetTokenInformation.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                            ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD


def _self_elevated() -> bool:
    """Czy nasz proces dziala z podniesionymi uprawnieniami."""
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(),
                                     TOKEN_QUERY, ctypes.byref(token)):
        return False
    try:
        val = wintypes.DWORD()
        size = wintypes.DWORD()
        ok = advapi32.GetTokenInformation(
            token, TokenElevation, ctypes.cast(ctypes.byref(val), ctypes.c_void_p),
            ctypes.sizeof(val), ctypes.byref(size))
        return bool(ok and val.value)
    finally:
        kernel32.CloseHandle(token)


def _can_open_process(pid: int) -> bool:
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if h:
        kernel32.CloseHandle(h)
        return True
    return False


# --------------------------------------------- alternatywne metody wysylania
# Rozne klienty czytaja klawiature roznymi droganu. SendInput ze scancodem to
# tylko jedna z opcji - ponizej reszta, do przetestowania po kolei.

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102

user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte,
                               wintypes.DWORD, ctypes.c_void_p]
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT


def tap_sendinput_vk(key: str, hold: float = 0.05) -> None:
    """SendInput, ale kodem wirtualnym zamiast scancodu."""
    vk = VK_CODES[key.strip().lower()]
    for up in (False, True):
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.ki = KEYBDINPUT(wVk=vk, wScan=0,
                            dwFlags=KEYEVENTF_KEYUP if up else 0,
                            time=0, dwExtraInfo=None)
        _send([inp])
        if not up:
            time.sleep(hold)


def tap_keybd_event(key: str, hold: float = 0.05) -> None:
    """Stare API keybd_event - niektore klienty reaguja tylko na nie."""
    k = key.strip().lower()
    vk = VK_CODES[k]
    scan = SCANCODES.get(k, 0)
    ext = KEYEVENTF_EXTENDEDKEY if k in EXTENDED else 0
    user32.keybd_event(vk, scan, ext, None)
    time.sleep(hold)
    user32.keybd_event(vk, scan, ext | KEYEVENTF_KEYUP, None)


def _lparam(scan: int, ext: bool, up: bool) -> int:
    lp = 1 | (scan << 16)
    if ext:
        lp |= 1 << 24
    if up:
        lp |= (1 << 30) | (1 << 31)
    return lp


def tap_postmessage(hwnd: int, key: str, hold: float = 0.05) -> None:
    """Komunikat wrzucony do kolejki okna, bez ruszania stanu klawiatury."""
    k = key.strip().lower()
    vk = VK_CODES[k]
    scan = SCANCODES.get(k, 0)
    ext = k in EXTENDED
    user32.PostMessageW(wintypes.HWND(hwnd), WM_KEYDOWN, vk,
                        _lparam(scan, ext, False))
    time.sleep(hold)
    user32.PostMessageW(wintypes.HWND(hwnd), WM_KEYUP, vk,
                        _lparam(scan, ext, True))


def tap_sendmessage(hwnd: int, key: str, hold: float = 0.05) -> None:
    """To samo, ale synchronicznie."""
    k = key.strip().lower()
    vk = VK_CODES[k]
    scan = SCANCODES.get(k, 0)
    ext = k in EXTENDED
    user32.SendMessageW(wintypes.HWND(hwnd), WM_KEYDOWN, vk,
                        _lparam(scan, ext, False))
    time.sleep(hold)
    user32.SendMessageW(wintypes.HWND(hwnd), WM_KEYUP, vk,
                        _lparam(scan, ext, True))


def post_key_down(hwnd: int, key: str) -> None:
    """WM_KEYDOWN wprost do okna gry - bez ruszania globalnego stanu klawiatury."""
    k = key.strip().lower()
    vk = VK_CODES[k]
    scan = SCANCODES.get(k, 0)
    user32.PostMessageW(wintypes.HWND(hwnd), WM_KEYDOWN, vk,
                        _lparam(scan, k in EXTENDED, False))


def post_key_up(hwnd: int, key: str) -> None:
    k = key.strip().lower()
    vk = VK_CODES[k]
    scan = SCANCODES.get(k, 0)
    user32.PostMessageW(wintypes.HWND(hwnd), WM_KEYUP, vk,
                        _lparam(scan, k in EXTENDED, True))


def send_key_down(hwnd: int, key: str) -> None:
    """To samo, ale synchronicznie - gra przetworzy komunikat, zanim wrocimy."""
    k = key.strip().lower()
    vk = VK_CODES[k]
    scan = SCANCODES.get(k, 0)
    user32.SendMessageW(wintypes.HWND(hwnd), WM_KEYDOWN, vk,
                        _lparam(scan, k in EXTENDED, False))


def send_key_up(hwnd: int, key: str) -> None:
    k = key.strip().lower()
    vk = VK_CODES[k]
    scan = SCANCODES.get(k, 0)
    user32.SendMessageW(wintypes.HWND(hwnd), WM_KEYUP, vk,
                        _lparam(scan, k in EXTENDED, True))


def tap_sendinput_long(key: str, hold: float = 0.30) -> None:
    """SendInput ze scancodem, ale trzymany duzo dluzej - na wolne petle gry."""
    tap(key, hold=hold, jitter=0.0)


METODY = {
    "SendInput scancode":        lambda hwnd, k: tap(k, hold=0.06),
    "SendInput scancode dlugi":  lambda hwnd, k: tap_sendinput_long(k),
    "SendInput kod wirtualny":   lambda hwnd, k: tap_sendinput_vk(k),
    "keybd_event":               lambda hwnd, k: tap_keybd_event(k),
    "PostMessage":               lambda hwnd, k: tap_postmessage(hwnd, k),
    "SendMessage":               lambda hwnd, k: tap_sendmessage(hwnd, k),
}


def foreground_title() -> str:
    hwnd = user32.GetForegroundWindow()
    n = user32.GetWindowTextLengthW(hwnd)
    if not n:
        return f"(bez tytulu, hwnd={hwnd})"
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def selftest_mouse(points):
    """
    Czy SendInput w ogole rusza kursorem. Porownuje zadana pozycje z
    odczytana z systemu - bez patrzenia na ekran i bez zgadywania.
    """
    wyniki = []
    for (x, y) in points:
        try:
            move_to(x, y)
        except InputError as exc:
            wyniki.append({"zadane": (x, y), "odczytane": None, "blad": str(exc)})
            continue
        time.sleep(0.12)
        gx, gy = cursor_pos()
        wyniki.append({
            "zadane": (x, y),
            "odczytane": (gx, gy),
            "ok": abs(gx - x) <= 2 and abs(gy - y) <= 2,
            "blad": None,
        })
    return wyniki


def selftest_key(key: str = "lshift"):
    """
    Czy SendInput w ogole wciska klawisze. Sprawdza stan klawisza w systemie
    miedzy wcisnieciem a puszczeniem. Domyslnie Shift - nic nie wpisuje.
    """
    out = {"klawisz": key, "przed": None, "w_trakcie": None, "po": None, "blad": None}
    try:
        out["przed"] = is_pressed(key)
        key_down(key)
        time.sleep(0.12)
        out["w_trakcie"] = is_pressed(key)
    except (InputError, KeyError) as exc:
        out["blad"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            key_up(key)
        except Exception:
            pass
        time.sleep(0.08)
        try:
            out["po"] = is_pressed(key)
        except Exception:
            pass
    out["ok"] = (out["w_trakcie"] is True and out["po"] is False)
    return out


def permission_report(hwnd: int) -> dict:
    """
    Sprawdza, czy mamy prawo wysylac klawisze do okna gry.

    Windows (UIPI) po cichu odrzuca wejscie z procesu o nizszych uprawnieniach
    do okna procesu o wyzszych - SendInput zwraca sukces, a klawisz nigdzie nie
    dociera. To najczestsza przyczyna "bot nic nie robi".
    """
    wynik = {"pid_gry": 0, "python_jako_admin": None,
             "widze_proces_gry": None, "podejrzenie_blokady": False,
             "blad": None}
    try:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        wynik["pid_gry"] = int(pid.value)
        wynik["python_jako_admin"] = _self_elevated()
        wynik["widze_proces_gry"] = _can_open_process(pid.value)
        wynik["podejrzenie_blokady"] = (not wynik["python_jako_admin"]
                                        and not wynik["widze_proces_gry"])
    except Exception as exc:                      # diagnostyka nie moze blokowac testu
        wynik["blad"] = f"{type(exc).__name__}: {exc}"
    return wynik

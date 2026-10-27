"""Shared plumbing for the small always-on-top layered windows.

The drag palette is click-through on purpose (it must never steal the mouse
capture from the window being dragged).  The ball, its bar menu and the
settings panel are the opposite: they are the only things the user *does* click.
So they are ordinary layered windows - no WS_EX_TRANSPARENT - and the fact that
they look round is handled by answering WM_NCHITTEST with HTTRANSPARENT for
every point outside the visible shape.  That keeps the shadow margin from
becoming a dead square that swallows clicks meant for the desktop.

WS_EX_NOACTIVATE matters too: clicking the ball must not take focus away from
whatever the user is working in.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import os
import sys

from . import win32
from .gdiplus import ARGB, Surface

user32 = win32.user32
kernel32 = win32.kernel32

WS_EX_PANEL = (
    win32.WS_EX_TOOLWINDOW
    | win32.WS_EX_LAYERED
    | win32.WS_EX_NOACTIVATE
)

IDC_HAND = 32649
IDC_ARROW = 32512

user32.SetWindowLongPtrW = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
user32.SetWindowLongPtrW.argtypes = [w.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
user32.GetWindowLongPtrW.argtypes = [w.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t


class TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [
        ("cbSize", w.DWORD),
        ("dwFlags", w.DWORD),
        ("hwndTrack", w.HWND),
        ("dwHoverTime", w.DWORD),
    ]


user32.TrackMouseEvent.argtypes = [ctypes.POINTER(TRACKMOUSEEVENT)]
user32.TrackMouseEvent.restype = w.BOOL


def dpi_scale(hwnd: int) -> float:
    """1.0 at 96 dpi, 1.5 at 150%, ...  Falls back to 1.0 if the API is gone."""
    try:
        dpi = user32.GetDpiForWindow(hwnd)
    except AttributeError:                                   # pragma: no cover
        dpi = 0
    return (dpi or 96) / 96.0


def monitor_at(pt):
    mons = win32.enumerate_monitors()
    return win32.monitor_at(pt[0], pt[1], mons) or (mons[0] if mons else None)


def resource_path(name: str) -> str:
    """Locate a file shipped next to the exe (or inside the onefile bundle)."""
    cands = []
    base = getattr(sys, "_MEIPASS", None)
    if base:
        cands.append(os.path.join(base, name))
    if getattr(sys, "frozen", False):
        cands.append(os.path.join(os.path.dirname(sys.executable), name))
    cands.append(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), name))
    for path in cands:
        if path and os.path.exists(path):
            return path
    return ""


class Layered:
    """A borderless, per-pixel-alpha window that paints itself via GDI+."""

    CLASS = "SXSnapLayered"
    TITLE = "SXSnap"

    def __init__(self) -> None:
        self.hwnd = 0
        self.pos = (0, 0)
        self.size = (0, 0)
        self.surf: Surface | None = None
        self.shown = False             # what hide()/show() last did
        self.topmost = True
        self._proc = win32.WNDPROC(self._wnd_proc)
        self._registered = False

    # ------------------------------------------------------------- lifecycle
    def _register(self) -> None:
        if self._registered:
            return
        hinst = kernel32.GetModuleHandleW(None)
        wc = win32.WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(win32.WNDCLASSEXW)
        wc.lpfnWndProc = ctypes.cast(self._proc, ctypes.c_void_p)
        wc.hInstance = hinst
        wc.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(IDC_HAND))
        wc.lpszClassName = self.CLASS
        if not user32.RegisterClassExW(ctypes.byref(wc)):
            err = ctypes.get_last_error()
            if err != 1410:                      # class already registered
                raise OSError(f"RegisterClassExW({self.CLASS}) err={err}")
        self._registered = True

    def create(self) -> int:
        if self.hwnd:
            return self.hwnd
        self._register()
        self.hwnd = user32.CreateWindowExW(
            WS_EX_PANEL, self.CLASS, self.TITLE,
            win32.WS_POPUP, 0, 0, 1, 1, None, None,
            kernel32.GetModuleHandleW(None), None,
        )
        if not self.hwnd:
            raise OSError(f"CreateWindowExW({self.CLASS}) err={ctypes.get_last_error()}")
        return self.hwnd

    def destroy(self) -> None:
        if self.surf is not None:
            self.surf.dispose()
            self.surf = None
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = 0

    # --------------------------------------------------------------- painting
    def geometry(self) -> tuple[int, int]:
        """Window size in physical pixels; subclasses override."""
        return (1, 1)

    def draw(self, surf: Surface) -> None:
        """Paint the whole window; subclasses override."""

    def hit(self, x: int, y: int) -> bool:
        """Is (x, y), in window coordinates, on the visible shape?"""
        return True

    def present(self) -> None:
        if not self.hwnd:
            return
        size = self.geometry()
        if size != self.size or self.surf is None:
            if self.surf is not None:
                self.surf.dispose()
            self.surf = Surface(max(1, size[0]), max(1, size[1]))
            self.size = size
        self.surf.clear(0)
        self.draw(self.surf)
        self.surf.blit(self.hwnd, *self.pos)

    # -------------------------------------------------------------- placement
    def place(self, x: int, y: int) -> None:
        self.pos = (int(x), int(y))

    def show(self) -> None:
        self.present()
        # UpdateLayeredWindow already moved/resized the window; this only fixes
        # the z-order band and makes sure it is visible.
        flag = win32.HWND_TOPMOST if self.topmost else win32.HWND_NOTOPMOST
        user32.SetWindowPos(
            self.hwnd, flag, 0, 0, 0, 0,
            win32.SWP_NOMOVE | win32.SWP_NOSIZE
            | win32.SWP_NOACTIVATE | win32.SWP_SHOWWINDOW,
        )
        user32.ShowWindow(self.hwnd, win32.SW_SHOWNA)
        self.shown = True

    def hide(self) -> None:
        self.shown = False
        if self.hwnd:
            user32.ShowWindow(self.hwnd, win32.SW_HIDE)

    def set_topmost(self, on: bool) -> None:
        if self.topmost == on:
            return
        self.topmost = on
        if self.hwnd:
            flag = win32.HWND_TOPMOST if on else win32.HWND_NOTOPMOST
            user32.SetWindowPos(self.hwnd, flag, 0, 0, 0, 0,
                                win32.SWP_NOSIZE | win32.SWP_NOMOVE | win32.SWP_NOACTIVATE)

    def screen_rect(self) -> tuple[int, int, int, int]:
        x, y = self.pos
        w, h = self.size
        return (x, y, x + w, y + h)

    # ---------------------------------------------------------------- messages
    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == win32.WM_NCHITTEST:
            # lParam carries screen coordinates of the tested point
            sx = ctypes.c_short(lparam & 0xFFFF).value
            sy = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            if not self.hit(sx - self.pos[0], sy - self.pos[1]):
                return win32.HTTRANSPARENT
            return win32.HTCLIENT
        if msg == win32.WM_MOUSELEAVE:
            self.on_mouse_leave()
            return 0
        return self.on_message(hwnd, msg, wparam, lparam)

    def on_message(self, hwnd, msg, wparam, lparam):
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def on_mouse_leave(self) -> None:
        pass

    def watch_mouse_leave(self) -> None:
        tme = TRACKMOUSEEVENT(ctypes.sizeof(TRACKMOUSEEVENT),
                              win32.TME_LEAVE, self.hwnd, 0)
        user32.TrackMouseEvent(ctypes.byref(tme))


# ---------------------------------------------------------------------- toast
class Toast(Layered):
    """A short message that appears next to the ball and fades out.

    Its own window rather than a label on the ball: 46 px cannot hold a
    sentence, and stretching the ball to fit one looks broken.
    """

    CLASS = "SXSnapToast"
    HOLD_MS = 1700

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text
        self._deadline = 0.0

    def geometry(self) -> tuple[int, int]:
        s = dpi_scale(self.hwnd)
        pad = int(round(14 * s))
        width = int(round((len(self.text) * 13.5 + 26) * s))
        height = int(round(34 * s))
        return (max(width, int(round(90 * s))) + pad * 2, height + pad * 2)

    def draw(self, surf: Surface) -> None:
        s = dpi_scale(self.hwnd)
        pad = int(round(14 * s))
        x, y = pad, pad
        ww, hh = self.size[0] - pad * 2, self.size[1] - pad * 2
        for k in range(5, 0, -1):
            grow = k * 1.6 * s
            surf.fill_round(x - grow, y - grow + 2 * s, ww + grow * 2, hh + grow * 2,
                            hh / 2 + grow, ARGB(10, 0, 0, 0))
        surf.fill_round(x, y, ww, hh, hh / 2, ARGB(246, 32, 34, 40))
        surf.stroke_round(x, y, ww, hh, hh / 2, ARGB(26, 255, 255, 255), max(1.0, s))
        surf.text(self.text, x, y, ww, hh, 13.5 * s, ARGB(255, 238, 240, 244))

    def hit(self, x: int, y: int) -> bool:
        return False        # purely informational: clicks fall through

    def show_for(self, x: int, y: int) -> None:
        self.place(x, y)
        self.show()
        self._deadline = _now() + self.HOLD_MS / 1000.0


def _now() -> float:
    import time
    return time.monotonic()

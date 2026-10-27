"""Animated placement, for one case only: crossing to another display.

Lining a window up inside the display it is already on is an instant snap.  An
easing move there was tried and taken back out - the user has just pointed at
the zone, so a 200 ms glide reads as the app thinking about it, not as polish.

What *is* worth animating is the move to the other screen: the window shrinks,
glides across the bezel at the small size, then grows into the zone, so it
visibly "carries over" instead of blinking out on one screen and in on the
other.

Only the *visible* rect is animated.  SetWindowPos talks about the window rect,
which is the visible frame grown by the invisible resize border, so every frame
is converted through the insets measured once at the start; the last step is
place_visible(), which re-measures and nails the final rect exactly - an
animation should never cost accuracy.

The loop runs on the caller's thread (the snap happens on a short-lived timer
thread, well after the mouse was released) and polls CANCEL so a new drag is
never fought over.
"""

from __future__ import annotations

import ctypes
import threading
import time

from . import engine, win32

TRAVEL_MS = 560        # shrink + cross the bezel + grow
FRAME_S = 0.008

# zoom phase boundaries for a cross-display move
_P_SHRINK, _P_FLY = 0.32, 0.66

CANCEL = threading.Event()
_SWP = win32.SWP_NOZORDER | win32.SWP_NOACTIVATE

try:
    _winmm = ctypes.WinDLL("winmm")
except OSError:                                     # pragma: no cover
    _winmm = None


def _period(on: bool) -> None:
    """1 ms timer resolution while animating, so frames are ~8 ms apart."""
    if _winmm is None:
        return
    try:
        if on:
            _winmm.timeBeginPeriod(1)
        else:
            _winmm.timeEndPeriod(1)
    except Exception:                               # pragma: no cover
        pass


# ------------------------------------------------------------------ helpers
def _insets(hwnd: int) -> tuple[int, int, int, int]:
    """visible - window, per edge (positive = the frame is outside)."""
    wl, wt, wr, wb = win32.window_rect(hwnd)
    vl, vt, vr, vb = engine.visible_rect(hwnd)
    return (vl - wl, vt - wt, vr - wr, vb - wb)


def _put(hwnd: int, rect, ins) -> None:
    l, t, r, b = rect
    il, it, ir, ib = ins
    win32.user32.SetWindowPos(
        hwnd, 0,
        int(round(l - il)), int(round(t - it)),
        int(round((r - l) - ir + il)), int(round((b - t) - ib + it)),
        _SWP,
    )


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _mix(r0, r1, t: float):
    return tuple(_lerp(r0[i], r1[i], t) for i in range(4))


def _ease_out(t: float) -> float:
    return 1.0 - (1.0 - t) ** 3


def _ease_in_out(t: float) -> float:
    return 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2


def _centre(r):
    return ((r[0] + r[2]) / 2.0, (r[1] + r[3]) / 2.0)


def _around(c, w: float, h: float):
    return (c[0] - w / 2.0, c[1] - h / 2.0, c[0] + w / 2.0, c[1] + h / 2.0)


def monitor_index(pt, monitors) -> int:
    for i, m in enumerate(monitors):
        l, t, r, b = m.rect
        if l <= pt[0] < r and t <= pt[1] < b:
            return i
    return 0


def crosses_display(r0, r1) -> bool:
    mons = win32.enumerate_monitors()
    if len(mons) < 2:
        return False
    return monitor_index(_centre(r0), mons) != monitor_index(_centre(r1), mons)


# --------------------------------------------------------------------- path
def travel_path(r0, r1):
    w0, h0 = r0[2] - r0[0], r0[3] - r0[1]
    w1, h1 = r1[2] - r1[0], r1[3] - r1[1]
    # the size it shrinks to before crossing over: clearly smaller than either
    # end, but never so tiny that the titlebar disappears
    tw = max(180.0, min(w1 * 0.30, w0 * 0.55))
    th = max(140.0, min(h1 * 0.30, h0 * 0.55))
    c0, c1 = _centre(r0), _centre(r1)
    s0, s1 = _around(c0, tw, th), _around(c1, tw, th)

    def sample(t: float):
        if t < _P_SHRINK:
            return _mix(r0, s0, _ease_in_out(t / _P_SHRINK))
        if t < _P_FLY:
            u = (t - _P_SHRINK) / (_P_FLY - _P_SHRINK)
            return _mix(s0, s1, _ease_in_out(u))
        return _mix(s1, r1, _ease_out((t - _P_FLY) / (1.0 - _P_FLY)))
    return sample


def _play(hwnd: int, sample, ms: int, ins) -> None:
    _period(True)
    try:
        t0 = time.perf_counter()
        while True:
            t = (time.perf_counter() - t0) * 1000.0 / ms
            if t >= 1.0:
                _put(hwnd, sample(1.0), ins)
                return
            _put(hwnd, sample(t), ins)
            if CANCEL.is_set() or not win32.user32.IsWindow(hwnd):
                return
            time.sleep(FRAME_S)
    finally:
        _period(False)


# --------------------------------------------------------------------- api
def animate_to(hwnd: int, target, ms: int | None = None) -> bool:
    """Fly `hwnd` to `target` (a visible rect) across the bezel."""
    if not hwnd or not win32.user32.IsWindow(hwnd):
        return False
    if win32.user32.IsIconic(hwnd):
        return engine.place_visible(hwnd, target)

    start = engine.visible_rect(hwnd)
    if win32.user32.IsZoomed(hwnd):
        # animate from the maximised frame: restoring first would flash the
        # old, unrelated restore rect before the flight begins
        win32.user32.ShowWindow(hwnd, win32.SW_RESTORE)
        time.sleep(0.05)

    r1 = tuple(int(v) for v in target)
    r0 = tuple(int(v) for v in start)
    if max(abs(r0[i] - r1[i]) for i in range(4)) <= 3:
        return engine.place_visible(hwnd, r1)

    duration = int(ms or TRAVEL_MS)
    sample = travel_path(r0, r1)

    ins = _insets(hwnd)
    CANCEL.clear()
    _play(hwnd, sample, duration, ins)
    return engine.place_visible(hwnd, r1)

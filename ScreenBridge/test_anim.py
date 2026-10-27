"""Landing check: where the animation is allowed to run, and where it is not.

The rule is now one-sided - only a move to *another* display is animated:

  * same display must be a plain snap.  `wants_travel()` is the decision the
    app actually uses, so it is tested directly, and the fallback path is timed
    to prove nothing is easing;
  * cross-display must really shrink, travel small across the bezel, then grow,
    and still land on the exact rect (an animation must never cost precision);
  * a no-op must not animate at all.

Frames are sampled from a watcher thread, because the animation runs on the
thread that calls animate_to().
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sxsnap import anim, engine, win32, zones  # noqa: E402
from sxsnap.main import wants_travel  # noqa: E402

W, H = 900, 620


def make_window(x, y):
    """A real top-level window, on its own message-pumping thread."""
    ready = threading.Event()
    box = {}

    def run():
        hinst = win32.kernel32.GetModuleHandleW(None)
        cls = "SXAnimProbe"

        wc = win32.WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(win32.WNDCLASSEXW)
        wc.lpfnWndProc = ctypes.cast(
            win32.WNDPROC(lambda h, m, w, l: win32.user32.DefWindowProcW(h, m, w, l)),
            ctypes.c_void_p)
        wc.hInstance = hinst
        wc.lpszClassName = cls
        win32.user32.RegisterClassExW(ctypes.byref(wc))

        hwnd = win32.user32.CreateWindowExW(
            0, cls, "SXSnap anim probe", win32.WS_POPUP | win32.WS_VISIBLE,
            x, y, W, H, None, None, hinst, None)
        box["hwnd"] = hwnd
        engine.move_to_rect(hwnd, (x, y, x + W, y + H))
        ready.set()

        msg = w.MSG()
        while win32.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            win32.user32.TranslateMessage(ctypes.byref(msg))
            win32.user32.DispatchMessageW(ctypes.byref(msg))

    threading.Thread(target=run, daemon=True).start()
    ready.wait(5)
    return box.get("hwnd", 0)


class Watcher:
    """Sample a window's visible rect while something else animates it."""

    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.frames = []
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        t0 = time.perf_counter()
        while not self._stop.is_set():
            if not win32.user32.IsWindow(self.hwnd):
                break
            self.frames.append(((time.perf_counter() - t0) * 1000.0, engine.visible_rect(self.hwnd)))
            time.sleep(0.006)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        self._t.join(1.0)


def unwrap(v: float, t: float) -> float:
    """Ease-out cubic, the zoom curve."""
    return 1.0 - (1.0 - t) ** 3


def check_landing(label, got, want):
    d = [abs(got[i] - want[i]) for i in range(4)]
    ok = max(d) <= 2
    print(f"  {label:<26} want={want} got={tuple(got)} delta={d} {'PASS' if ok else 'FAIL'}")
    return ok


def main() -> int:
    win32.enable_dpi_awareness()
    mons = win32.enumerate_monitors()
    print("monitors:", [(m.rect, m.dpi) for m in mons])
    if len(mons) < 2:
        print("need two displays for this test")
        return 1

    fails = []

    # ------------------------------------------------- same display: no ease
    hwnd = make_window(200, 200)
    time.sleep(0.4)
    tgt = zones.zones_for(mons[0], "split-v")[1]
    cfg = {"animate": True}
    r0 = engine.visible_rect(hwnd)
    decision = wants_travel(r0, tgt, cfg)
    t0 = time.perf_counter()
    engine.place_visible(hwnd, tgt)
    elapsed = (time.perf_counter() - t0) * 1000.0
    time.sleep(0.25)
    got = engine.visible_rect(hwnd)
    print(f"same display: wants_travel={decision} placed in {elapsed:.1f} ms")
    if decision:
        fails.append("same-display placement would still be animated")
    if elapsed > 80:
        fails.append(f"same-display placement took {elapsed:.0f} ms")
    if not check_landing("same display lands", got, tgt):
        fails.append("same-display landing")

    # the cross-display target must take the other branch
    cross_tgt = engine.target_on_monitor(hwnd, mons[1])
    if not wants_travel(got, cross_tgt, cfg):
        fails.append("cross-display placement is not animated any more")
    else:
        print("cross display: wants_travel=True as expected")
    if wants_travel(got, cross_tgt, {"animate": False}):
        fails.append("animate=False is ignored")

    # -------------------------------------------------------------- travel
    engine.place_visible(hwnd, (180, 180, 180 + W, 180 + H))
    time.sleep(0.35)
    r0 = engine.visible_rect(hwnd)
    tgt = engine.target_on_monitor(hwnd, mons[1])
    with Watcher(hwnd) as w:
        t0 = time.perf_counter()
        anim.animate_to(hwnd, tgt)
        elapsed = (time.perf_counter() - t0) * 1000.0
    time.sleep(0.3)
    got = engine.visible_rect(hwnd)
    print(f"travel: {len(w.frames)} frames in {elapsed:.0f} ms")
    if not check_landing("travel lands exactly", got, tgt):
        fails.append("travel landing")

    w0, h0 = r0[2] - r0[0], r0[3] - r0[1]
    w1, h1 = tgt[2] - tgt[0], tgt[3] - tgt[1]
    widths = [(t, r[2] - r[0]) for t, r in w.frames if r[2] > r[0]]
    if widths:
        smallest = min(x[1] for x in widths)
        print(f"  width {w0} -> {w1}, smallest mid-flight {smallest}")
        if smallest > min(w0, w1) * 0.75:
            fails.append(f"travel: never shrank (min {smallest})")
        mid = [x for x in widths if 0.30 <= x[0] / elapsed <= 0.70]
        if mid:
            span = [r for t, r in w.frames if 0.30 <= t / elapsed <= 0.70]
            l = min(s[0] for s in span)
            r = max(s[2] for s in span)
            print(f"  mid-flight span x={l}..{r} (screens 0..{mons[0].rect[2]} / {mons[1].rect[0]}..)")
            if r < mons[0].rect[2]:
                fails.append("travel: never entered the second display")
        else:
            fails.append("travel: no mid-flight samples")
    else:
        fails.append("travel: no frames captured")

    # --------------------------------------------------------- no-op guard
    with Watcher(hwnd) as w:
        t0 = time.perf_counter()
        anim.animate_to(hwnd, tgt)
        elapsed = (time.perf_counter() - t0) * 1000.0
    print(f"no-op: {len(w.frames)} frames in {elapsed:.0f} ms")
    if elapsed > 120:
        fails.append(f"no-op still animated ({elapsed:.0f} ms)")

    # ------------------------------------------------------- cancel safety
    tgt2 = zones.zones_for(mons[1], "quad")[0]
    timer = threading.Timer(0.12, anim.CANCEL.set)
    timer.start()
    t0 = time.perf_counter()
    anim.animate_to(hwnd, tgt2)
    ms = (time.perf_counter() - t0) * 1000.0
    time.sleep(0.25)
    got = engine.visible_rect(hwnd)
    print(f"cancel: stopped after {ms:.0f} ms")
    if not check_landing("cancel still lands", got, tgt2):
        fails.append("cancel landing")
    anim.CANCEL.clear()

    hwnds = [w for w in (hwnd,) if w]
    for h in hwnds:
        win32.user32.PostMessageW(h, 0x0010, 0, 0)   # WM_CLOSE
    time.sleep(0.3)

    for f in fails:
        print("FAIL:", f)
    print("RESULT:", "PASS" if not fails else "FAIL")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())

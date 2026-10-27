"""State-machine test: drag -> screen chip -> layout zone -> snap.

Synthetic mouse input is blocked in this sandbox (mouse_event produces no
messages at all), so the cursor and the button state are injected instead.
Everything else is real: the dragged window physically moves, the poll sees
its frame follow, the palette paints and hit-tests, and the final placement is
verified against the live window rect.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sxsnap import engine, win32, zones  # noqa: E402

user32 = win32.user32
WS_OVERLAPPEDWINDOW = 0x00CF0000
TEST_CLASS = "SXSnapFlowTestWnd"
_keepalive = {}


def make_window(title="SXSnap Flow Test") -> int:
    """Create the test window on its own message-pumping thread.

    It must own a pump: SetWindowPlacement/SetWindowPos send messages to the
    window's *owning* thread, so a window living on a thread that is not
    pumping deadlocks the caller (which, in the real product, is a Timer
    thread).  Real target windows always have a pump, so this mirrors reality.
    """
    ready = threading.Event()
    holder: dict = {}

    def run():
        hinst = win32.kernel32.GetModuleHandleW(None)
        proc = win32.WNDPROC(lambda h, m, wp, lp: user32.DefWindowProcW(h, m, wp, lp))
        holder["proc"] = proc
        wc = win32.WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(win32.WNDCLASSEXW)
        wc.lpfnWndProc = ctypes.cast(proc, ctypes.c_void_p)
        wc.hInstance = hinst
        wc.hbrBackground = 6
        wc.lpszClassName = TEST_CLASS
        user32.RegisterClassExW(ctypes.byref(wc))
        hwnd = user32.CreateWindowExW(
            0, TEST_CLASS, title, WS_OVERLAPPEDWINDOW,
            260, 260, 800, 520, None, None, hinst, None)
        user32.ShowWindow(hwnd, 5)
        user32.UpdateWindow(hwnd)
        holder["hwnd"] = hwnd
        ready.set()
        msg = w.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    threading.Thread(target=run, daemon=True).start()
    ready.wait(3.0)
    return holder["hwnd"]


class Harness:
    """Injects cursor/button state into the real App state machine."""

    def __init__(self, hwnd: int) -> None:
        from sxsnap.main import App
        self.hwnd = hwnd
        self.cx = 0
        self.cy = 0
        self.down = False
        self.app = App()
        # this test drives the drag machine only; never inherit whatever the
        # user's config file happens to say about the ball or the enabled flag
        self.app.cfg["enabled"] = True
        self.app.pal.create()
        self.app.hwnd = self.app.pal.hwnd
        self.app.pal.dwell_ms = 90

        win32.cursor_pos = lambda: (self.cx, self.cy)
        win32.left_button_down = lambda: self.down
        win32.window_from_point = lambda x, y: hwnd

    def move(self, x, y, ticks=1, delay=0.02):
        self.cx, self.cy = int(x), int(y)
        for _ in range(ticks):
            self.app._on_tick()
            if delay:
                time.sleep(delay)

    def drag_window(self, dx, dy):
        l, t, r, b = win32.window_rect(self.hwnd)
        user32.SetWindowPos(self.hwnd, 0, l + dx, t + dy, r - l, b - t, 0x0004 | 0x0010)

    def collect(self, fn, limit=60, delay=0.03):
        for _ in range(limit):
            self.app._on_tick()
            if fn():
                return True
            time.sleep(delay)
        return False


def main() -> int:
    mode = win32.enable_dpi_awareness()
    mons = win32.enumerate_monitors()
    mon = mons[0]
    print(f"DPI={mode} monitors={len(mons)} {mon.rect} dpi={mon.dpi}")

    hwnd = make_window()
    user32.SetWindowPos(hwnd, 0, 420, 360, 860, 560, 0x0004 | 0x0010)
    time.sleep(0.3)
    print("window:", win32.window_rect(hwnd))

    h = Harness(hwnd)
    l, t, r, b = win32.window_rect(hwnd)
    gx, gy = (l + r) // 2, t + 12

    # ---- 1. button down on the caption --------------------------------
    h.cx, h.cy = gx, gy
    h.down = True
    h.move(gx, gy)
    print("1. tracking:", h.app.tracking, "drag_hwnd ok:", h.app.drag_hwnd == hwnd)

    # ---- 2. the frame follows the cursor -> palette opens --------------
    h.drag_window(-20, 16)
    h.move(gx - 20, gy + 16)
    print("2. moved:", h.app.moved, "palette:", h.app.pal.active,
          "stage:", h.app.pal.stage, "origin:", h.app.pal.origin)
    if not h.app.pal.active:
        return 1

    # ---- 3. rest on chip 1 until the layouts unfold --------------------
    m = h.app.pal.metrics()
    ox, oy = h.app.pal.origin
    cx, cy, cw, ch = m["chips"][0]
    h.move(ox + cx + cw // 2, oy + cy + ch // 2, ticks=1)
    h.collect(lambda: h.app.pal.stage == 1, limit=40, delay=0.03)
    print("3. stage:", h.app.pal.stage, "panel:", h.app.pal._size)
    if h.app.pal.stage != 1:
        return 1

    # ---- 4. hover the middle column of "three columns" ----------------
    li, zi = 2, 1
    m = h.app.pal.metrics()
    ox, oy = h.app.pal.origin
    tx, ty, tw, th = m["thumbs"][li]
    px = ox + tx + int(tw * (zi + 0.5) / 3.0)
    py = oy + ty + th // 2
    h.move(px, py, ticks=3)
    action = h.app.pal.resolve()
    print("4. hover:", h.app.pal.hover_layout, h.app.pal.hover_zone, "action:", action)

    expect = zones.zones_for(mon, zones.LAYOUT_IDS[li], 8, 0)[zi]

    # ---- 5. release -> snap -------------------------------------------
    h.down = False
    h.move(px, py)
    time.sleep(1.0)

    got = engine.visible_rect(hwnd)
    delta = [abs(got[i] - expect[i]) for i in range(4)]
    print("5. expect:", expect)
    print("   got   :", got)
    print("   delta :", delta)
    snap_ok = max(delta) <= 4

    # ---- 6. cross-screen move: release on the other chip --------------
    x_ok = True
    if len(mons) > 1:
        h.cx, h.cy = got[0] + 300, got[1] + 12
        h.down = True
        h.move(h.cx, h.cy)
        h.drag_window(24, 12)
        h.move(h.cx + 24, h.cy + 12)
        if h.app.pal.active:
            m = h.app.pal.metrics()
            ox, oy = h.app.pal.origin
            bx, by, bw, bh = m["chips"][1]
            # a chip is not inside any thumbnail, so releasing there resolves to
            # "move to that display" in either stage
            h.move(ox + bx + bw // 2, oy + by + bh // 2, ticks=2)
            act = h.app.pal.resolve()
            h.down = False
            h.move(ox + bx + bw // 2, oy + by + bh // 2)
            time.sleep(1.2)
            rect = win32.window_rect(hwnd)
            target = mons[1].work
            x_ok = target[0] <= rect[0] < target[2] - 100
            print("6. cross-screen action:", act, "rect:", rect, "on 2nd screen:", x_ok)
    else:
        print("6. skipped (single monitor)")

    print("RESULT:", "PASS" if (snap_ok and x_ok) else "FAIL")
    h.app.pal.destroy()
    user32.PostMessageW(hwnd, 0x0010, 0, 0)
    return 0 if (snap_ok and x_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())

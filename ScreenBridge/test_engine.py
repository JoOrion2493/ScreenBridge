"""Engine-only checks: placement survives maximised / minimised windows, and
crossing to another display keeps the window's *visible* size.

The trap in the first two: a window that was ever maximised remembers a
restore rect, and the shell snaps it back there unless rcNormalPosition is
rewritten before SetWindowPos.  The trap in the third: SetWindowPos speaks
about the window rect, which includes an invisible DPI-scaled border, so a
naive "same size on the other monitor" loses a few pixels per side.
"""

import ctypes
import ctypes.wintypes as w
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sxsnap import engine, win32, zones

user32 = win32.user32
user32.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
user32.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_uint]

SW_MINIMIZE = 6
SW_MAXIMIZE = 3
SW_RESTORE = 9


def find_explorer():
    hits = []

    def cb(h, l):
        if user32.IsWindowVisible(h) and win32.window_class(h) == "CabinetWClass":
            hits.append(h)
        return True

    user32.EnumWindows(win32.ENUMPROC(cb), 0)
    return hits[0] if hits else 0


def autostart_explorer():
    """Open a throwaway folder so the test never asks the user to click."""
    folder = tempfile.mkdtemp(prefix="sxsnap-test-")
    subprocess.Popen(["explorer.exe", folder])
    for _ in range(40):
        time.sleep(0.25)
        h = find_explorer()
        if h:
            return h
    return 0


def check(hwnd, rect, label):
    engine.place_visible(hwnd, rect)
    time.sleep(0.25)
    got = engine.visible_rect(hwnd)
    d = [abs(got[i] - rect[i]) for i in range(4)]
    ok = max(d) <= 2
    print(f"  {label:<30} want={rect}  got={got}  delta={d}  {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    win32.enable_dpi_awareness()
    hwnd = find_explorer() or autostart_explorer()
    if not hwnd:
        print("no explorer window and none could be opened")
        return 1
    print("target:", hwnd, win32.window_text(hwnd))

    mons = win32.enumerate_monitors()
    m0 = mons[0]
    print("monitor 0:", m0.rect, "work:", m0.work)

    left, right = zones.zones_for(m0, "split-v", 8, 0)
    top, bottom = zones.zones_for(m0, "split-h", 8, 0)
    quad = zones.zones_for(m0, "quad", 8, 0)

    results = []

    print("\n[1] normal window")
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetWindowPos(hwnd, 0, m0.rect[0] + 400, m0.rect[1] + 260, 900, 600,
                        win32.SWP_NOZORDER)
    time.sleep(0.5)
    results.append(check(hwnd, left, "normal -> left half"))
    results.append(check(hwnd, right, "normal -> right half"))

    print("\n[2] maximised window")
    user32.ShowWindow(hwnd, SW_MAXIMIZE)
    time.sleep(0.6)
    print("  maximised rect:", win32.window_rect(hwnd))
    results.append(check(hwnd, left, "maximised -> left half"))
    results.append(check(hwnd, top, "maximised -> top half"))

    print("\n[3] minimised window")
    user32.ShowWindow(hwnd, SW_MINIMIZE)
    time.sleep(0.5)
    print("  iconic:", bool(user32.IsIconic(hwnd)))
    results.append(check(hwnd, quad[3], "minimised -> quad/bottom-right"))

    print("\n[4] window rect vs visible rect")
    user32.ShowWindow(hwnd, SW_RESTORE)
    time.sleep(0.4)
    wr, vr = win32.window_rect(hwnd), engine.visible_rect(hwnd)
    print(f"  window={wr}  visible={vr}  inset={[vr[i]-wr[i] for i in range(4)]}")

    print("\n[5] cross display, size must survive")
    if len(mons) > 1:
        before = engine.visible_rect(hwnd)
        bw, bh = before[2] - before[0], before[3] - before[1]
        engine.move_to_monitor(hwnd, mons[1])
        time.sleep(0.4)
        after = engine.visible_rect(hwnd)
        dw = abs((after[2] - after[0]) - bw)
        dh = abs((after[3] - after[1]) - bh)
        on1 = mons[1].rect[0] <= after[0] < mons[1].rect[2]
        ok = dw <= 2 and dh <= 2 and on1
        print(f"  before={before} ({bw}x{bh})")
        print(f"  after ={after} ({after[2]-after[0]}x{after[3]-after[1]})"
              f"  dsize=({dw},{dh})  on 2nd screen={on1}  {'PASS' if ok else 'FAIL'}")
        results.append(ok)
    else:
        print("  only one monitor, skipped")

    passed = sum(1 for r in results if r)
    print(f"\n{passed}/{len(results)} checks passed")
    print("RESULT:", "ALL PASS" if passed == len(results) else "FAILURES")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())

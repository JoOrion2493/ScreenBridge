"""End-to-end: the installed SXSnap.exe must open the drag palette at the
size the user picked in the settings panel.

Real mouse events are used (SetCursorPos + mouse_event), so the app's own
poll - the same one a human drag triggers - drives the whole flow.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import os
import subprocess
import sys
import threading
import time

from PIL import ImageGrab

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sxsnap import config, win32   # noqa: E402

user32 = win32.user32
USER32 = ctypes.WinDLL("user32")
EXE = os.path.join(os.environ["LOCALAPPDATA"], "Programs", "SXSnap", "SXSnap.exe")
TEST_CLASS = "SXSnapSizeTest"


def make_window(title: str) -> int:
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
            0, TEST_CLASS, title, 0x00CF0000,
            300, 300, 760, 480, None, None, hinst, None)
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


def rect_of(hwnd) -> tuple[int, int, int, int]:
    rc = w.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rc))
    return (rc.left, rc.top, rc.right, rc.bottom)


def drag(hwnd: int, title_bar: tuple[int, int], dx: int, dy: int) -> None:
    """Press on the title bar, move, and hold - the palette stays open.

    The sandbox never hands the synthetic drag to the window manager, so the
    window is moved by hand with the same delta - the app only cares that the
    window under the cursor actually moved while the button was down.
    """
    x, y = title_bar
    USER32.SetCursorPos(x, y)
    time.sleep(0.2)
    USER32.mouse_event(0x0002, 0, 0, 0, None)      # LEFTDOWN
    time.sleep(0.25)
    l, t, _r, _b = rect_of(hwnd)
    for i in range(1, 9):
        sx = dx * i // 8
        sy = dy * i // 8
        USER32.SetCursorPos(x + sx, y + sy)
        win32.user32.SetWindowPos(hwnd, 0, l + sx, t + sy, 0, 0,
                                  0x0001 | 0x0004)   # NOSIZE | NOZORDER
        time.sleep(0.07)
    time.sleep(0.6)


def release() -> None:
    USER32.mouse_event(0x0004, 0, 0, 0, None)      # LEFTUP
    time.sleep(0.3)


def kill_all() -> None:
    """The onefile bootloader spawns a child - killing the parent leaves the
    real process (and the singleton mutex) alive, so the next launch would
    quietly exit and the old instance would answer instead."""
    os.system('taskkill /F /IM SXSnap.exe >nul 2>&1')
    time.sleep(1.0)


def unfold(pal: int, rect: tuple[int, int, int, int]) -> tuple[bool, tuple]:
    """Sweep the pointer across the chip row until the layout row unfolds.

    The chip row is centred on the pointer, but at smaller scales the pointer
    can land in the gap between two chips - and then the row never opens.  A
    sweep makes the stage deterministic for every size.
    """
    l, t, r, b = rect
    h = b - t
    y = int(t + h * 0.35)
    for x in range(l + 4, r - 4, 5):
        USER32.SetCursorPos(x, y)
        time.sleep(0.05)
        rc = rect_of(pal)
        if rc[3] - rc[1] > h + 30:
            return True, rc
    return False, rect_of(pal)


def run_one(size: str) -> tuple[int, int, str]:
    """Launch the app with the given size, drag a window, capture the palette."""
    kill_all()
    cfg = config.load()
    cfg["palette_size"] = size
    cfg["ball"] = True
    config.save(cfg)

    proc = subprocess.Popen([EXE])
    try:
        time.sleep(3.0)
        hwnd = make_window(f"SXSnap 尺寸验证 {size}")
        time.sleep(0.8)
        l, t, r, b = rect_of(hwnd)
        # press in the *client* area, never on the title bar: a real button-down
        # on the caption starts the system's modal move loop, which swallows the
        # SetWindowPos calls until the drag ends - the app then sees the window
        # jump only on the last tick, i.e. after the gesture is over
        grab = (l + 120, t + 70)

        pal = 0
        prc = (0, 0, 0, 0)
        for attempt in range(4):
            drag(hwnd, grab, 120 + attempt * 30, 80 + attempt * 20)
            time.sleep(0.9)
            pal = user32.FindWindowW("SXSnapDragPalette", None)
            prc = rect_of(pal) if pal else (0, 0, 0, 0)
            if (prc[2] - prc[0]) > 50:
                break
            release()
            time.sleep(0.4)

        if not pal:
            print(f"  {size}: palette window not found")
            release()
            return (0, 0, size)
        opened, prc = unfold(pal, prc)
        time.sleep(0.4)
        prc = rect_of(pal)
        if (prc[2] - prc[0]) > 50:
            pad = 26
            img = ImageGrab.grab(bbox=(prc[0] - pad, prc[1] - pad,
                                       prc[2] + pad, prc[3] + pad),
                                 all_screens=True)
            img.save(f"shot-live-palette-{size}.png")
            print(f"  {size}: palette {prc[2]-prc[0]}x{prc[3]-prc[1]} "
                  f"(unfolded={opened}) -> shot-live-palette-{size}.png")
            wh = (prc[2] - prc[0], prc[3] - prc[1])
        else:
            print(f"  {size}: palette not visible (rect {prc})")
            wh = (0, 0)
        release()
        user32.DestroyWindow(hwnd)
        return wh[0], wh[1], size
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        kill_all()
        time.sleep(0.4)


def main() -> int:
    win32.enable_dpi_awareness()
    ok = True
    results = []
    for size in ("large", "medium", "small"):
        results.append(run_one(size))

    print("\nsummary:")
    for w, h, name in results:
        print(f"  {name:7s} {w}x{h}")
    for a, b in zip(results, results[1:]):
        if not (b[0] < a[0] and b[1] < a[1]):
            ok = False
            print(f"  FAIL: {a[2]} -> {b[2]} is not smaller")
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Live check of the *installed* SXSnap.exe: the size picker really works.

The app is started as a real process, its windows are driven with the same
messages Windows would send (lparam carries *client* coordinates), and the
state is read back from config.json.  Screenshots of the real desktop prove
the picker is visible and clickable.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import os
import subprocess
import sys
import time

from PIL import ImageGrab

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sxsnap import config, win32   # noqa: E402

user32 = win32.user32
WM_MOUSEMOVE = 0x0200
WM_LBUTTONUP = 0x0202

EXE = os.path.join(os.environ["LOCALAPPDATA"], "Programs", "SXSnap", "SXSnap.exe")

# panel geometry, in layout px (see sxsnap/ball.py)
PANEL_W, PANEL_SHADOW, PANEL_PAD = 320, 14, 14
PANEL_HEAD, ROW_H = 44, 46
SEG_W = 36


def lparam(x: int, y: int) -> int:
    return (int(y) << 16) | (int(x) & 0xFFFF)


def rect_of(hwnd) -> tuple[int, int, int, int]:
    rc = w.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rc))
    return (rc.left, rc.top, rc.right, rc.bottom)


def visible(hwnd) -> bool:
    if not hwnd:
        return False
    rc = rect_of(hwnd)
    return bool(user32.IsWindowVisible(hwnd)) and (rc[2] - rc[0]) > 2


def find(cls: str) -> int:
    return user32.FindWindowW(cls, None) or 0


def wait_visible(cls: str, timeout: float = 12.0) -> tuple[int, tuple]:
    """Wait until the window exists, is visible and has a real size."""
    end = time.time() + timeout
    while time.time() < end:
        h = find(cls)
        if h and visible(h):
            time.sleep(0.3)
            return h, rect_of(h)
        time.sleep(0.15)
    return 0, (0, 0, 0, 0)


def click(hwnd, x: int, y: int) -> None:
    """A click in client coordinates, the way Windows delivers it."""
    user32.SendMessageW(hwnd, WM_MOUSEMOVE, 0, lparam(x, y))
    time.sleep(0.08)
    user32.SendMessageW(hwnd, WM_LBUTTONUP, 0, lparam(x, y))
    time.sleep(0.2)


def shot(box, name: str, zoom: int = 2) -> None:
    img = ImageGrab.grab(bbox=box, all_screens=True)
    if zoom != 1:
        img = img.resize((img.width * zoom, img.height * zoom))
    img.save(name)
    print(f"  saved {name} {img.size}")


def main() -> int:
    win32.enable_dpi_awareness()
    ok = True

    # start from a known size so the test is repeatable
    cfg = config.load()
    cfg["palette_size"] = "large"
    cfg["ball"] = True
    cfg["ball_docked"] = False
    config.save(cfg)

    proc = subprocess.Popen([EXE])
    try:
        ball, brc = wait_visible("SXSnapBall")
        if not ball:
            print("FAIL: the ball window never appeared")
            return 1
        print("ball hwnd:", ball, brc)

        # click the ball -> the vertical menu opens
        bw, bh = brc[2] - brc[0], brc[3] - brc[1]
        user32.SetCursorPos((brc[0] + brc[2]) // 2, (brc[1] + brc[3]) // 2)
        time.sleep(0.15)
        user32.SendMessageW(ball, 0x0201, 1, lparam(bw // 2, bh // 2))
        time.sleep(0.15)
        user32.SendMessageW(ball, WM_LBUTTONUP, 0, lparam(bw // 2, bh // 2))
        time.sleep(0.4)

        menu, mrc = wait_visible("SXSnapBallMenu", 6.0)
        if not menu:
            print("FAIL: the menu never appeared")
            return 1
        print("menu hwnd:", menu, mrc)
        s_menu = user32.GetDpiForWindow(menu) / 96.0
        print("  menu dpi scale:", s_menu)
        shot((mrc[0] - 12, mrc[1] - 12, mrc[2] + 12, mrc[3] + 12),
             "shot-live-menu.png")

        # the settings gear is the 4th tile
        tx = int((12 + 28) * s_menu)
        ty = int((12 + 20 + 3 * (24 + 18) + 12) * s_menu)
        print("  clicking the gear at", (tx, ty))
        click(menu, tx, ty)

        panel, prc = wait_visible("SXSnapSettings", 6.0)
        if not panel:
            print("FAIL: the settings panel never appeared")
            shot((mrc[0] - 20, mrc[1] - 20, mrc[2] + 20, mrc[3] + 20),
                 "shot-live-menu.png")
            return 1
        print("panel hwnd:", panel, prc)
        shot((prc[0] - 12, prc[1] - 12, prc[2] + 12, prc[3] + 12),
             "shot-live-panel-large.png")

        # the size row is the 5th row; the segmented control sits at its right
        #   row top = PANEL_SHADOW + PANEL_HEAD + 4*ROW_H = 242, mid = 265
        #   picker = PANEL_SHADOW + PANEL_W - PANEL_PAD - 3*SEG_W = 240 .. 348
        ps = user32.GetDpiForWindow(panel) / 96.0
        row_mid = int((PANEL_SHADOW + PANEL_HEAD + 4 * ROW_H + ROW_H / 2) * ps)
        seg_w = SEG_W * ps
        picker_left = (PANEL_SHADOW + PANEL_W - PANEL_PAD - 3 * SEG_W) * ps
        print(f"  panel dpi scale {ps}, row_mid {row_mid}, picker {picker_left}")

        for label, index, expect in (("中", 1, "medium"), ("小", 2, "small"),
                                      ("大", 0, "large")):
            click(panel, int(picker_left + seg_w * (index + 0.5)), row_mid)
            time.sleep(0.35)
            got = config.load().get("palette_size")
            print(f"  clicked {label}: palette_size = {got} (want {expect})")
            if got != expect:
                ok = False
                print(f"  FAIL: expected {expect}")
            shot((prc[0] - 12, prc[1] - 12, prc[2] + 12, prc[3] + 12),
                 f"shot-live-panel-{expect}.png")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

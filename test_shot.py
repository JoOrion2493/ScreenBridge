"""Live screenshot: drive the palette open, grab it off the real desktop."""

from __future__ import annotations

import ctypes
import os
import sys
import time

from PIL import ImageGrab

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sxsnap import win32  # noqa: E402
from test_flow import Harness, make_window  # noqa: E402

user32 = win32.user32


def main() -> int:
    win32.enable_dpi_awareness()
    hwnd = make_window("SXSnap · 被拖动的窗口")
    user32.SetWindowPos(hwnd, 0, 300, 300, 900, 620, 0x0004 | 0x0010)
    time.sleep(0.4)

    h = Harness(hwnd)
    l, t, r, b = win32.window_rect(hwnd)
    gx, gy = (l + r) // 2, t + 12

    h.cx, h.cy = gx, gy
    h.down = True
    h.move(gx, gy, delay=0)
    h.drag_window(40, 26)
    h.move(gx + 40, gy + 26, delay=0)

    pal = h.app.pal
    if not pal.active:
        print("palette did not open")
        return 1

    # open the layout row by resting on the first screen chip
    m = pal.metrics()
    ox, oy = pal.origin
    cx, cy, cw, ch = m["chips"][0]
    h.move(ox + cx + cw // 2, oy + cy + ch // 2, ticks=1, delay=0)
    h.collect(lambda: pal.stage == 1, limit=40, delay=0.03)

    # hover a zone: three columns, middle
    m = pal.metrics()
    ox, oy = pal.origin
    tx, ty, tw, th = m["thumbs"][2]
    h.move(ox + tx + int(tw * 0.5), oy + ty + th // 2, ticks=2, delay=0.05)
    time.sleep(0.35)

    m = pal.metrics()
    ox, oy = pal.origin
    pad = 26
    box = (ox - pad, oy - pad, ox + m["w"] + pad, oy + m["h"] + pad)
    print("palette box:", box, "size:", (m["w"], m["h"]))
    shot = ImageGrab.grab(bbox=box, all_screens=True)
    shot.save("shot-palette-live.png")

    # also grab the stage-0 (chips only) state - the window shrinks back to the
    # chip row, so the origin has to be re-derived or the capture is misaligned
    pal.stage = 0
    pal.hover_layout = -1
    pal.hover_zone = -1
    pal._place_window()
    pal.paint()
    time.sleep(0.2)
    m = pal.metrics()
    ox, oy = pal.origin
    small = ImageGrab.grab(bbox=(ox - pad, oy - pad, ox + m["w"] + pad, oy + m["h"] + pad),
                           all_screens=True)
    small.save("shot-palette-live-chips.png")
    print("saved shots", (m["w"], m["h"]), "origin:", (ox, oy))

    pal.end()
    pal.destroy()
    user32.PostMessageW(hwnd, 0x0010, 0, 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

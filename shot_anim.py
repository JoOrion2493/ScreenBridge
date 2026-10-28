"""Draw a trajectory diagram from the real animation samples.

The frames are measured, not drawn by hand: a watcher thread polls the window's
visible rect while animate_to() plays the exact shipped path, and this script
plots those rects over a sketch of the two displays.  So the diagram shows what
the window really did - including the intermediate sizes and the bezel
crossing - without photographing the desktop.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import os
import sys
import threading
import time

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sxsnap import anim, engine, win32, zones  # noqa: E402

W, H = 900, 620
FONT = "C:/Windows/Fonts/msyh.ttc"
MONO = "C:/Windows/Fonts/consola.ttf"


def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def open_window(x, y):
    ready, box = threading.Event(), {}

    def run():
        hinst = win32.kernel32.GetModuleHandleW(None)
        cls = "SXTraceProbe"
        wc = win32.WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(win32.WNDCLASSEXW)
        wc.lpfnWndProc = ctypes.cast(
            win32.WNDPROC(lambda h, m, wp, lp: win32.user32.DefWindowProcW(h, m, wp, lp)),
            ctypes.c_void_p)
        wc.hInstance = hinst
        wc.lpszClassName = cls
        win32.user32.RegisterClassExW(ctypes.byref(wc))
        hwnd = win32.user32.CreateWindowExW(
            0, cls, "SXSnap trace probe", win32.WS_POPUP | win32.WS_VISIBLE,
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


def record(hwnd, target, **kw):
    """Play the animation and sample the live rect as fast as we can."""
    samples = []
    stop = threading.Event()

    def watch():
        t0 = time.perf_counter()
        while not stop.is_set():
            if not win32.user32.IsWindow(hwnd):
                break
            samples.append(((time.perf_counter() - t0) * 1000.0, engine.visible_rect(hwnd)))
            time.sleep(0.007)

    th = threading.Thread(target=watch, daemon=True)
    th.start()
    t0 = time.perf_counter()
    anim.animate_to(hwnd, target, **kw)
    total = (time.perf_counter() - t0) * 1000.0
    stop.set()
    th.join(0.5)
    time.sleep(0.2)
    return samples, total


def draw_trace(mons, samples, total, path, title, cross):
    vl, vt, vr, vb = win32.virtual_screen()
    sw, sh = vr - vl, vb - vt
    k = 1140.0 / sw                      # fit the whole desktop
    padl, padt = 46, 74
    cw, chh = int(sw * k), int(sh * k)
    sheet = Image.new("RGB", (cw + padl * 2, chh + padt + 92), (24, 24, 26))
    d = ImageDraw.Draw(sheet, "RGBA")
    f_t = font(FONT, 22)
    f_s = font(FONT, 15)
    f_m = font(MONO, 14)

    def sc(rect):
        return (padl + (rect[0] - vl) * k, padt + (rect[1] - vt) * k,
                padl + (rect[2] - vl) * k, padt + (rect[3] - vt) * k)

    # --- displays -----------------------------------------------------------
    for i, m in enumerate(mons):
        x0, y0, x1, y1 = sc(m.rect)
        d.rounded_rectangle((x0, y0, x1, y1), 12, fill=(30, 31, 34, 255),
                            outline=(74, 76, 82, 255), width=2)
        d.text((x0 + 14, y0 + 10), f"屏幕 {i + 1}  {m.width}×{m.height} @{m.dpi / 96 * 100:.0f}%",
               font=f_s, fill=(126, 129, 136, 255))

    # --- ghost frames -------------------------------------------------------
    frames = [(t, r) for t, r in samples if r[2] > r[0] and t <= total + 20]
    keep = []
    last = None
    for t, r in frames:
        if last is None or max(abs(r[i] - last[i]) for i in range(4)) >= 6:
            keep.append((t, r))
            last = r
    if keep and keep[-1][1] != samples[-1][1]:
        keep.append((total, samples[-1][1]))

    n = max(1, len(keep) - 1)
    placed = []          # keep the time labels from piling up on each other

    def label(x, y, text, fill, fnt):
        bw, bh = d.textlength(text, font=fnt) + 6, 17
        box = (x - 2, y - 2, x + bw, y + bh)
        for b in placed:
            if not (box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3]):
                return False
        placed.append(box)
        d.text((x, y), text, font=fnt, fill=fill)
        return True

    for i, (t, r) in enumerate(keep):
        u = i / float(n)
        x0, y0, x1, y1 = sc(r)
        if i == 0:
            col = (120, 122, 130, 255)
            d.rounded_rectangle((x0, y0, x1, y1), 8, outline=col, width=2)
            label(x0 + 4, y0 - 20, "起点", col, f_s)
        elif i == len(keep) - 1:
            col = (86, 156, 214, 255)
            d.rounded_rectangle((x0, y0, x1, y1), 8, outline=col, width=3)
            label(x0 + 6, y1 + 3, "落位", col, f_s)
        else:
            a = int(70 + 150 * u)
            col = (120, 190, 255, a)
            d.rounded_rectangle((x0, y0, x1, y1), 6, outline=col, width=2)
            if u in (0.25, 0.5, 0.75) or i % 7 == 3:
                label(x1 + 6, (y0 + y1) / 2 - 9, f"{t:.0f}ms",
                      (146, 158, 175, 210), f_m)

    # --- phase timeline -----------------------------------------------------
    ty = padt + chh + 34
    d.text((padl, ty - 26), title, font=f_t, fill=(235, 236, 240, 255))
    bx0, bx1 = padl, padl + cw
    d.rounded_rectangle((bx0, ty, bx1, ty + 10), 5, fill=(46, 47, 51, 255))
    if cross:
        cuts = [(0.0, 0.32, (138, 180, 235), "缩小"),
                (0.32, 0.66, (120, 210, 190), "穿越"),
                (0.66, 1.0, (200, 170, 235), "展开")]
    else:
        cuts = [(0.0, 1.0, (138, 180, 235), "缩放")]
    for a, b, col, label in cuts:
        x0 = bx0 + (bx1 - bx0) * a
        x1 = bx0 + (bx1 - bx0) * b
        d.rounded_rectangle((x0 + 1, ty, x1 - 1, ty + 10), 5, fill=col + (230,))
        d.text((x0 + 6, ty + 16), label, font=f_s, fill=col + (255,))
    d.text((bx1 - 120, ty + 16), f"{total:.0f} ms / {len(keep)} 帧", font=f_m,
           fill=(150, 152, 158, 255))

    sheet.save(path)
    print(f"{path}: {len(keep)} ghosts over {total:.0f} ms, {sheet.size}")


def main() -> int:
    win32.enable_dpi_awareness()
    mons = win32.enumerate_monitors()
    if len(mons) < 2:
        print("need two displays")
        return 1

    hwnd = open_window(240, 240)
    time.sleep(0.6)

    # same-display placement no longer animates at all, so the only trace worth
    # drawing is the cross-display flight
    tgt = engine.target_on_monitor(hwnd, mons[1])
    samples, total = record(hwnd, tgt)
    draw_trace(mons, samples, total, "shot-anim-travel.png",
               "跨屏搬窗口 —— 缩小 · 穿越 · 展开（travel）", cross=True)

    win32.user32.PostMessageW(hwnd, 0x0010, 0, 0)
    time.sleep(0.3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

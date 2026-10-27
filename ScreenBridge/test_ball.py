"""Off-screen render + hit-test contract for the floating ball shell.

Runs without showing anything: each window paints into its own layered surface,
which is then flattened onto a mock desktop and written to PNG.  The hit tests
matter as much as the pictures - a round ball whose window eats clicks in the
corners is a bug you cannot see in a screenshot.
"""

from __future__ import annotations

import ctypes
import os
import sys
import time

from PIL import Image, ImageChops, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sxsnap import config, win32                      # noqa: E402
from sxsnap.ball import (BALL_D, MENU_ICON, MENU_PAD, MENU_GAP, PANEL_HEAD,   # noqa: E402
                         ROW_H, BallUI, SettingsPanel)
from sxsnap.gdiplus import ARGB, Surface              # noqa: E402


def flatten(surf: Surface, bg=(28, 32, 42)) -> Image.Image:
    """Premultiplied surface -> RGB on top of a flat colour."""
    w, h = surf.width, surf.height
    raw = ctypes.string_at(surf._bits, w * h * 4)
    img = Image.frombuffer("RGBA", (w, h), raw, "raw", "BGRA", 0, 1)
    r, g, b, a = img.split()
    inv = a.point(lambda v: 255 - v)
    chans = []
    for ch, bv in zip((r, g, b), bg):
        base = Image.new("L", (w, h), bv)
        chans.append(ImageChops.add(ch, ImageChops.multiply(base, inv)))
    return Image.merge("RGB", chans)


def alpha(surf: Surface) -> Image.Image:
    w, h = surf.width, surf.height
    raw = ctypes.string_at(surf._bits, w * h * 4)
    return Image.frombuffer("RGBA", (w, h), raw, "raw", "BGRA", 0, 1).getchannel("A")


def render(win, stage: str = "") -> tuple[Image.Image, Image.Image]:
    size = win.geometry()
    surf = Surface(*size)
    surf.clear(0)
    win.draw(surf)
    return flatten(surf), alpha(surf)


def mock_desktop(w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h), (32, 36, 48))
    d = ImageDraw.Draw(img)
    for y in range(0, h, 40):
        d.line([(0, y), (w, y)], fill=(36, 41, 55))
    for x in range(0, w, 40):
        d.line([(x, 0), (x, h)], fill=(36, 41, 55))
    return img


def main() -> int:
    win32.enable_dpi_awareness()
    cfg = dict(config.DEFAULTS)
    cfg["ball_x"], cfg["ball_y"] = 40, 40
    cfg["ball_docked"] = False

    ui = BallUI(cfg, lambda: None)
    for win in (ui.ball, ui.menu, ui.panel, ui.toast):
        win.create()
    ui.restore_position()

    ok = True

    # ---- the disc ---------------------------------------------------------
    ui.ball.hover = False
    img, a = render(ui.ball)
    img.save("shot-ball.png")
    pad = ui.ball.pad()
    d = int(round(BALL_D * ui.ball.scale()))
    corners = [a.getpixel(p) for p in ((0, 0), (img.width - 1, 0),
                                       (0, img.height - 1),
                                       (img.width - 1, img.height - 1))]
    centre = a.getpixel((pad + d // 2, pad + d // 2))
    print(f"ball   {img.size} pad={pad} d={d} corner_alpha={corners} centre_alpha={centre}")
    if max(corners) > 0:
        ok = False
        print("  FAIL: the ball window has opaque corners")

    # clicking the corner of the window must fall through to the desktop
    if ui.ball.hit(1, 1):
        ok = False
        print("  FAIL: corner of the ball window swallows clicks")
    if not ui.ball.hit(pad + d // 2, pad + d // 2):
        ok = False
        print("  FAIL: the disc itself is not clickable")

    # ---- the docked bar ---------------------------------------------------
    ui.docked = True
    ui.edge = "right"
    ui._compute_dock(2000, 900)
    img, a = render(ui.ball)
    img.save("shot-ball-bar.png")
    print(f"bar    {img.size} edge={ui.edge} rect={ui.pos_bar}")
    if ui.ball.hit(1, 1):
        ok = False
        print("  FAIL: bar window swallows clicks in its corner")
    ui.docked = False

    # ---- the menu ---------------------------------------------------------
    ui.menu.items = ui._menu_items()
    ui.menu.hover = 0
    img, a = render(ui.menu)
    img.save("shot-ball-menu.png")
    print(f"menu   {img.size} items={[i[0] for i in ui.menu.items]}")

    for i, item in enumerate(ui.menu.items):
        bx, by, bs, _ = ui.menu.tile_box(i)
        cx, cy = int(bx + bs / 2), int(by + bs / 2)
        if ui.menu.index_at(cx, cy) != i:
            ok = False
            print(f"  FAIL: tile {i} ({item[0]}) not hit at its centre")
    if not ui.menu.hit(ui.menu.size[0] // 2 if ui.menu.size[0] else 1, 4):
        pass
    if ui.menu.hit(2, 2):
        ok = False
        print("  FAIL: menu corner swallows clicks")

    # ---- the settings panel ----------------------------------------------
    ui.panel.hover = 1
    img, a = render(ui.panel)
    img.save("shot-ball-settings.png")
    print(f"panel  {img.size} rows={[r[0] for r in SettingsPanel.ROWS]}")
    for i, row in enumerate(SettingsPanel.ROWS):
        y = int(ui.panel._row_y(i) + ROW_H * ui.panel.scale() / 2)
        if ui.panel._row_index_at(y) != i:
            ok = False
            print(f"  FAIL: row {i} ({row[0]}) not hit at its centre")
    if ui.panel.hit(2, 2):
        ok = False
        print("  FAIL: panel corner swallows clicks")

    # ---- composite preview ------------------------------------------------
    ui.docked = False
    ball_img, ball_a = render(ui.ball)
    menu_img, menu_a = render(ui.menu)
    panel_img, panel_a = render(ui.panel)

    W, H = 460, 560
    canvas = mock_desktop(W, H)
    bx, by = 300, 480
    canvas.paste(ball_img, (bx, by), ball_a)
    mx = bx + ball_img.width // 2 - menu_img.width // 2
    my = by - menu_img.height + ui.ball.pad()
    canvas.paste(menu_img, (mx, max(0, my)), menu_a)
    canvas.save("shot-ball-composite.png")

    canvas2 = mock_desktop(W, H)
    px, py = 80, 150
    canvas2.paste(panel_img, (px, py), panel_a)
    canvas2.paste(ball_img, (W - ball_img.width - 10, H - ball_img.height - 10), ball_a)
    canvas2.save("shot-ball-settings-live.png")

    # docked sliver against the right edge of the mock desktop
    ui.docked = True
    ui.edge = "right"
    ui._compute_dock(2000, 900)
    bar_img, bar_a = render(ui.ball)
    canvas3 = mock_desktop(W, H)
    canvas3.paste(bar_img, (W - bar_img.width, (H - bar_img.height) // 2), bar_a)
    canvas3.save("shot-ball-docked.png")
    ui.docked = False

    # ---- the hide switch must be a round trip ------------------------------
    # (the live test can only reach the panel while the ball exists; this is
    # the "ball already hidden, open the panel from the tray" direction)
    ui.cfg["ball"] = True
    ui.set_visible(True)
    ui.panel_click("hide")
    hidden = (not ui.cfg["ball"]) and (not ui.ball.shown)
    ui.open_settings(near_cursor=True)          # what the tray menu does
    ui.panel_click("hide")
    shown = bool(ui.cfg["ball"]) and ui.ball.shown
    print(f"hide switch: hidden={hidden} shown_again={shown}")
    if not (hidden and shown):
        ok = False
        print("  FAIL: the hide switch does not go both ways")

    # ---- turning snap off while docked undocks in place ---------------------
    ui.cfg["ball_snap"] = True
    ui.docked = True
    ui.edge = "right"
    ui._compute_dock(2400, 700)
    ui._show_ball()
    bar_x = ui.pos_bar[0]
    ui.panel_click("snap")
    stayed = abs(ui.pos_ball[0] - bar_x) < 200
    print(f"snap off while docked: docked={ui.docked} bar_x={bar_x} "
          f"ball_x={ui.pos_ball[0]} stayed_near={stayed}")
    if ui.docked or not stayed:
        ok = False
        print("  FAIL: turning snap off did not undock in place")
    ui.cfg["ball_snap"] = True

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Headless visual check: render the palette offscreen and dump PNGs.

No window is shown, nothing touches the desktop - the same paint() the app
uses draws into a DIB section, which we flatten over a dark background so the
rounded corners and the soft shadow are visible.

Also asserts two contracts:

  * hit-testing - a point inside a thumbnail resolves to that (layout, zone),
    and a release over a chip means "move to that display";
  * the anchor is stage-invariant - the row of screen chips must not move a
    single pixel when the layout row unfolds under it.  That is the bug where
    the panel slid out from under the cursor mid-gesture.
"""

from __future__ import annotations

import ctypes
import os
import sys

from PIL import Image, ImageChops

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sxsnap import win32, zones  # noqa: E402
from sxsnap.palette import Palette  # noqa: E402

BG = (24, 24, 26)


def flatten(surf, bg=BG):
    """Un-premultiply the DIB and composite it over a flat background."""
    w, h = surf.width, surf.height
    raw = ctypes.string_at(surf._bits, w * h * 4)
    img = Image.frombuffer("RGBA", (w, h), raw, "raw", "BGRA", 0, 1)
    r, g, b, a = img.split()
    inv = a.point(lambda v: 255 - v)
    out = []
    for ch, bv in zip((r, g, b), bg):
        base = Image.new("L", (w, h), bv)
        out.append(ImageChops.add(ch, ImageChops.multiply(base, inv)))
    return Image.merge("RGB", out)


def chip_panel_origin(pal) -> tuple[int, int, int, int]:
    """Absolute (l, t, r, b) of the chip row, derived from the window origin."""
    m = pal.metrics()
    cb = m["chip_box"]
    ox, oy = pal.origin
    return (ox + cb[0], oy + cb[1], ox + cb[0] + cb[2], oy + cb[1] + cb[3])


def main() -> int:
    win32.enable_dpi_awareness()
    pal = Palette()
    pal.monitors = win32.enumerate_monitors()
    print("monitors:", [(m.rect, m.dpi) for m in pal.monitors])

    pal.scale = pal.monitors[0].dpi / 96.0
    pal.create()
    pal.active = True
    fails: list[str] = []

    # ---- anchor mid-screen, stage 0: screens only ----
    cursor = (900, 700)
    pal.sel_mon = pal._monitor_index(cursor)
    pal.stage = 0
    pal._anchor(cursor)
    before = chip_panel_origin(pal)
    pal.hover_chip = 0
    pal.paint()
    print("stage 0 size:", pal._size, "chip panel:", before)
    flatten(pal._surface).save("shot-palette-stage1.png")

    # ---- stage 1: layouts unfolded, resting on quad/bottom-right ----
    pal.stage = 1
    pal._place_window()
    pal.hover_chip = 0
    pal.hover_layout = zones.LAYOUT_IDS.index("quad")
    pal.hover_zone = 3
    pal.paint()
    after = chip_panel_origin(pal)
    if before != after:
        fails.append(f"chip row moved on expand: {before} -> {after}")
    print("stage 1 size:", pal._size, "chip panel:", after, "(unmoved)" if before == after else "(MOVED)")
    flatten(pal._surface).save("shot-palette-stage2.png")

    # ---- the preset strip on its own, 2x ----
    m = pal.metrics()
    lx, ly, lw, lh = m["layout"]
    strip = flatten(pal._surface).crop((lx, ly, lx + lw, ly + lh))
    strip.resize((strip.width * 2, strip.height * 2), Image.LANCZOS).save("shot-layouts.png")
    print("preset strip:", (lw, lh), "order:", zones.LAYOUT_IDS)

    # ---- hit-testing contract ----
    ox, oy = pal.origin
    for i, lid in enumerate(zones.LAYOUT_IDS):
        tx, ty, tw, th = m["thumbs"][i]
        zx, zy, zw, zh = zones.layout_by_id(lid)[2][-1]     # last zone
        pt = (ox + tx + int((zx + zw / 2) * tw), oy + ty + int((zy + zh / 2) * th))
        got = pal.update(pt)
        want = ("zone", pal.sel_mon, i, len(zones.layout_by_id(lid)[2]) - 1)
        if pal.resolve() != want:
            fails.append(f"{lid}: {pal.resolve()} != {want}")
        print(f"  {lid:<10} {got:<5} -> {pal.resolve()}")

    if len(pal.monitors) > 1:
        bx, by, bw, bh = m["chips"][1]
        pt = (ox + bx + bw // 2, oy + by + bh // 2)
        print("  chip 2    ", pal.update(pt), "->", pal.resolve())
        if pal.resolve() != ("screen", 1):
            fails.append(f"chip 2 -> {pal.resolve()}, want ('screen', 1)")

    # ---- flipped panel: anchored low, layouts above the chips ----
    cursor = (900, 1380)
    pal.stage = 0
    pal.sel_mon = 0
    pal.hover_chip = 0
    pal.hover_layout = -1
    pal.hover_zone = -1
    pal._anchor(cursor)
    flip_top = chip_panel_origin(pal)
    pal.stage = 1
    pal._place_window()
    pal.hover_layout = zones.LAYOUT_IDS.index("third-v")
    pal.hover_zone = 1
    pal.paint()
    flip_after = chip_panel_origin(pal)
    print("flip:", pal.flip, "chip panel:", flip_top, "->", flip_after)
    if flip_top != flip_after:
        fails.append(f"flipped chip row moved: {flip_top} -> {flip_after}")
    if not pal.flip:
        fails.append("expected flip near the bottom of the display")
    flatten(pal._surface).save("shot-palette-flip.png")

    # ---- the anchor survives every stage change, all over the desktop ----
    vl, vt, vr, vb = win32.virtual_screen()
    probes = 0
    for gy in (vt + 90, (vt + vb) // 2, vb - 120):
        for gx in (vl + 60, (vl + vr) // 4, (vl + vr) // 2, vr * 3 // 4, vr - 60):
            pal.sel_mon = pal._monitor_index((gx, gy))
            pal.scale = pal.monitors[pal.sel_mon].dpi / 96.0
            pal.stage = 0
            pal._anchor((gx, gy))
            a = chip_panel_origin(pal)
            pal.stage = 1
            pal._place_window()
            b = chip_panel_origin(pal)
            m1 = pal.metrics()
            l1, t1, r1, b1 = (pal.origin[0] + m1["layout"][0], pal.origin[1] + m1["layout"][1],
                              pal.origin[0] + m1["layout"][0] + m1["layout"][2],
                              pal.origin[1] + m1["layout"][1] + m1["layout"][3])
            probes += 1
            if a != b:
                fails.append(f"chip row moved at {(gx, gy)}: {a} -> {b}")
            if l1 < vl or r1 > vr or t1 < vt or b1 > vb:
                fails.append(f"layout row off desktop at {(gx, gy)}: {(l1, t1, r1, b1)}")
    print(f"anchor probes: {probes}")

    pal.end()
    pal.destroy()

    for f in fails:
        print("FAIL:", f)
    print("RESULT:", "PASS" if not fails else "FAIL")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())

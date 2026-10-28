"""Off-screen preview: the 大/中/小 picker and the three palette sizes.

Two things get checked here:

  1. the settings panel's size row - the segmented control must show the
     current choice, and clicking a segment must land on that size;
  2. the drag palette at large / medium / small - each step has to be
     visibly smaller than the one before, while keeping the same content.
"""

from __future__ import annotations

import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sxsnap import config, palette, win32     # noqa: E402
from sxsnap.ball import BallUI, SettingsPanel  # noqa: E402
from test_ball import flatten, render          # noqa: E402
from test_palette import flatten as pflatten     # noqa: E402


def main() -> int:
    win32.enable_dpi_awareness()
    ok = True

    # ---- the settings panel, one picture per size choice -------------------
    cfg = dict(config.DEFAULTS)
    cfg["ball_x"], cfg["ball_y"] = 40, 40
    cfg["ball_docked"] = False

    shots = []
    for name in palette.SIZE_ORDER:
        cfg["palette_size"] = name
        ui = BallUI(dict(cfg), lambda: None)
        ui.cfg["palette_size"] = name
        img, _a = render(ui.panel)
        shots.append((name, img))
        print(f"panel[{name}] {img.size}")

        # the active segment must be the one the config points at
        px, py, pw, ph = ui.panel.size_picker_geo()
        seg = pw / 3.0
        want = palette.SIZE_ORDER.index(name)
        centre = px + (want + 0.5) * seg
        if not (px <= centre <= px + pw):
            ok = False
            print(f"  FAIL: segment centre {centre} outside the picker")
        # clicking that segment must select that very size
        ui.cfg["palette_size"] = "large" if name != "large" else "small"
        ui._cycle_size(int(centre))
        if ui.cfg["palette_size"] != name:
            ok = False
            print(f"  FAIL: clicking segment {want} gave {ui.cfg['palette_size']}")
        else:
            print(f"  click on segment {want} -> {name}  OK")

    strip = Image.new("RGB", (max(s.width for _n, s in shots),
                              sum(s.height for _n, s in shots) + 8 * (len(shots) - 1)),
                      (32, 36, 48))
    y = 0
    for _n, s in shots:
        strip.paste(s, (0, y))
        y += s.height + 8
    strip.save("shot-panel-sizes.png")
    print("saved shot-panel-sizes.png", strip.size)

    # ---- the drag palette at the three sizes --------------------------------
    from sxsnap.palette import Palette
    mons = win32.enumerate_monitors()
    sizes = {}
    for name in palette.SIZE_ORDER:
        pal = Palette()
        pal.monitors = mons
        pal.size = name
        pal.sel_mon = 0
        pal.create()
        pal.active = True
        pal.stage = 1
        pal._anchor((mons[0].rect[0] + 200, mons[0].rect[1] + 200))
        pal.paint()
        m = pal.metrics()
        sizes[name] = (m["w"], m["h"])
        print(f"palette[{name}] {m['w']}x{m['h']}")
        pal.end()
        pal.destroy()

    ordered = [sizes[n] for n in palette.SIZE_ORDER]
    for a, b in zip(ordered, ordered[1:]):
        if not (b[0] < a[0] and b[1] < a[1]):
            ok = False
            print(f"  FAIL: {a} -> {b} is not smaller in both axes")

    # stack the three palettes so the shrinkage is obvious at a glance
    pals = []
    for name in palette.SIZE_ORDER:
        pal = Palette()
        pal.monitors = mons
        pal.size = name
        pal.sel_mon = 0
        pal.create()
        pal.active = True
        pal.stage = 1
        pal._anchor((mons[0].rect[0] + 200, mons[0].rect[1] + 200))
        pal.hover_chip = 0
        pal.hover_layout = 0
        pal.paint()
        pals.append((name, flatten(pal._surface)))
        pal.end()
        pal.destroy()

    sheet = Image.new("RGB", (max(p.width for _n, p in pals),
                              sum(p.height for _n, p in pals)
                              + 10 * (len(pals) - 1)), (24, 24, 26))
    y = 0
    for _n, p in pals:
        sheet.paste(p, (0, y))
        y += p.height + 10
    sheet.save("shot-palette-sizes.png")
    print("saved shot-palette-sizes.png", sheet.size)

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())

"""Where the layout row opens, for every arrangement of screens.

The palette has to put the layout row where the pointer can reach it
without dragging across another screen chip:

  a horizontal row of screens  -> the row opens below (or above)
  a vertical column of screens  -> the row opens to the right (or left)

The arrangements are simulated by faking the monitor rectangles inside the
*real* virtual desktop - the mini-map is drawn from the virtual screen, so
the fake screens have to live in its coordinates.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image

from sxsnap import win32                      # noqa: E402
from sxsnap.palette import Palette           # noqa: E402
from test_ball import flatten                 # noqa: E402


class FakeMonitor:
    """Just enough of win32.Monitor for the palette."""

    def __init__(self, number, rect):
        self.handle = 0
        self.device = f"\\\\.\\DISPLAY{number}"
        self.rect = rect
        self.work = rect
        self.primary = False
        self.dpi = 96
        self.number = number
        self.left, self.top = rect[0], rect[1]

    @property
    def width(self):
        return self.rect[2] - self.rect[0]

    @property
    def height(self):
        return self.rect[3] - self.rect[1]


# arrangements as fractions of the virtual desktop
SHAPES = {
    "row2":  [(0, 0, .5, 1), (.5, 0, 1, 1)],
    "col2":  [(0, 0, 1, .5), (0, .5, 1, 1)],
    "row3":  [(0, 0, 1 / 3, 1), (1 / 3, 0, 2 / 3, 1), (2 / 3, 0, 1, 1)],
    "col3":  [(0, 0, 1, 1 / 3), (0, 1 / 3, 1, 2 / 3), (0, 2 / 3, 1, 1)],
    "L":     [(0, 0, .5, .5), (.5, 0, 1, .5), (0, .5, .5, 1)],
    "grid2": [(0, 0, .5, .5), (.5, 0, 1, .5), (0, .5, .5, 1), (.5, .5, 1, 1)],
}

NAMES = {
    "row2":  "2 screens side by side",
    "col2":  "2 screens stacked",
    "row3":  "3 screens in a row",
    "col3":  "3 screens in a column",
    "L":     "L shape (two up, one down-left)",
    "grid2": "2x2 grid",
}


def build(shape: str, vbox) -> tuple[list[FakeMonitor], tuple[int, int]]:
    """Fake monitors for `shape`, plus a cursor in the middle of the first."""
    vl, vt, vr, vb = vbox
    vw, vh = vr - vl, vb - vt
    mons = []
    for i, (fx0, fy0, fx1, fy1) in enumerate(SHAPES[shape]):
        rect = (int(vl + fx0 * vw), int(vt + fy0 * vh),
                int(vl + fx1 * vw), int(vt + fy1 * vh))
        mons.append(FakeMonitor(i + 1, rect))
    r = mons[0].rect
    cursor = ((r[0] + r[2]) // 2, (r[1] + r[3]) // 2)
    return mons, cursor


def place(pal, mons, cursor):
    pal.monitors = mons
    pal.scale = 1.0
    pal.stage = 0
    pal._anchor(cursor)
    pal.stage = 1
    pal._place_window()
    return pal.metrics(1)


def chip_screen_rects(pal, m):
    ox, oy = pal.origin
    return [(ox + cx, oy + cy, cw, chh) for (cx, cy, cw, chh) in m["chips"]]


def main() -> int:
    win32.enable_dpi_awareness()
    ok = True
    pal = Palette()
    pal.dwell_ms = 0
    vbox = win32.virtual_screen()
    print("virtual desktop:", vbox)

    print(f"{'arrangement':<34} {'axis':<5} {'opens':<7} {'blocked':<8} reason")
    for shape in SHAPES:
        mons, cursor = build(shape, vbox)
        pal.monitors = mons
        axis = pal._row_axis()
        m = place(pal, mons, cursor)
        rects = chip_screen_rects(pal, m)
        # the chip the pointer heads for is the selected monitor's
        k = pal.sel_mon
        cx, cy, cw, ch = rects[k]
        px, py = cx + cw / 2.0, cy + ch / 2.0
        blocked = pal._blocked(rects, px, py, pal.lay_dir)
        print(f"{NAMES[shape]:<34} {axis:<5} {pal.lay_dir:<7} {str(blocked):<8} "
              f"chips={[(round(a), round(b)) for a, b, _c, _d in rects]}")

        if blocked:
            ok = False
            print("   FAIL: a screen chip stands between the pointer and the row")
        if axis == "h" and pal.lay_dir not in ("below", "above"):
            ok = False
            print("   FAIL: a horizontal row should open downwards")
        if axis == "v" and pal.lay_dir not in ("right", "left"):
            ok = False
            print("   FAIL: a vertical column should open sideways")

    # ---- render the two headline cases so the result can be looked at -----
    shots = []
    for shape in ("row2", "col2"):
        mons, cursor = build(shape, vbox)
        pal.monitors = mons
        pal.scale = 1.0
        pal.stage = 0
        pal.sel_mon = 0
        pal.hover_chip = 0
        pal.hover_layout = 2
        pal.hover_zone = 1
        pal._anchor(cursor)
        pal.stage = 1
        pal.sel_mon = 0
        pal._place_window()
        pal.create()
        pal.paint()
        shots.append((NAMES[shape], flatten(pal._surface)))
        print(f"  rendered {NAMES[shape]}: {pal._size}, opens {pal.lay_dir}")

    sheet = Image.new("RGB", (max(s.width for _n, s in shots),
                              sum(s.height for _n, s in shots) + 12),
                      (24, 24, 26))
    y = 0
    for _n, s in shots:
        sheet.paste(s, (0, y))
        y += s.height + 12
    sheet.save("shot-palette-arrangement.png")
    print("saved shot-palette-arrangement.png", sheet.size)

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

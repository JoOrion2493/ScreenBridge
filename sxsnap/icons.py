"""Vector glyphs for the floating ball's bar and settings panel.

Everything is stroked with GDI+ into the same premultiplied surface the panels
use, so the icons inherit the antialiasing of the rest of the UI.  They are
drawn from normalised coordinates (0..1 of a square) which makes them cheap to
scale for a 150% display.
"""

from __future__ import annotations

import math

from .gdiplus import Surface


def _axes(cx: float, cy: float, size: float):
    left, top = cx - size / 2.0, cy - size / 2.0

    def X(u: float) -> float:
        return left + u * size

    def Y(v: float) -> float:
        return top + v * size

    return X, Y


# --------------------------------------------------------------------- glyphs
def camera(surf: Surface, cx, cy, size, col, w) -> None:
    """Video camera: body, lens and the wedge on the right."""
    X, Y = _axes(cx, cy, size)
    surf.stroke_round(X(0.04), Y(0.24), X(0.66) - X(0.04), Y(0.80) - Y(0.24),
                      size * 0.13, col, w)
    r = size * 0.155
    surf.ring(X(0.35) - r, Y(0.52) - r, r * 2, r * 2, col, w)
    surf.poly([(X(0.68), Y(0.44)), (X(0.95), Y(0.30)),
               (X(0.95), Y(0.74)), (X(0.68), Y(0.60))], col, w)


def microphone(surf: Surface, cx, cy, size, col, w) -> None:
    """Microphone: capsule head, U-shaped cradle, stand."""
    X, Y = _axes(cx, cy, size)
    surf.stroke_round(X(0.33), Y(0.06), X(0.67) - X(0.33), Y(0.54) - Y(0.06),
                      (X(0.67) - X(0.33)) / 2.0, col, w)
    surf.arc(X(0.20), Y(0.26), X(0.80) - X(0.20), Y(0.74) - Y(0.26), 0, 180, col, w)
    surf.line(X(0.50), Y(0.72), X(0.50), Y(0.92), col, w)
    surf.line(X(0.34), Y(0.94), X(0.66), Y(0.94), col, w)


def layout(surf: Surface, cx, cy, size, col, w, pane=None) -> None:
    """A three-zone window layout - one tall pane left, two stacked right.

    The first attempt (a frame + title bar) still read as "00" at bar size,
    so this follows the classic snap-layout glyph instead: the *asymmetric*
    three-way split cannot be mistaken for two equal columns, which is what
    the original two-pill icon looked like.  When the manager is on, the
    left pane fills with the accent so the tile shows its state.
    """
    X, Y = _axes(cx, cy, size)
    rad = size * 0.10
    # left pane: tall, takes most of the window
    surf.stroke_round(X(0.08), Y(0.10), X(0.47) - X(0.08), Y(0.90) - Y(0.10),
                      rad, col, w)
    # right column: two stacked panes
    surf.stroke_round(X(0.55), Y(0.10), X(0.92) - X(0.55), Y(0.46) - Y(0.10),
                      rad, col, w)
    surf.stroke_round(X(0.55), Y(0.54), X(0.92) - X(0.55), Y(0.90) - Y(0.54),
                      rad, col, w)
    # the "active" zone, filled only when the feature is on
    if pane is not None:
        surf.fill_round(X(0.08), Y(0.10), X(0.47) - X(0.08), Y(0.90) - Y(0.10),
                        rad, pane)


def gear(surf: Surface, cx, cy, size, col, w, teeth: int = 8) -> None:
    """Settings: an eight-toothed gear with a hollow hub."""
    R, r = 0.455, 0.335
    step = 2.0 * math.pi / teeth
    pts = []
    for i in range(teeth):
        a0 = i * step
        for frac, rad in ((0.045, r), (0.135, R), (0.365, R), (0.455, r)):
            ang = a0 + frac * step
            pts.append((cx + size * rad * math.cos(ang),
                        cy + size * rad * math.sin(ang)))
    surf.poly(pts, col, w)
    hub = size * 0.13
    surf.ring(cx - hub, cy - hub, hub * 2, hub * 2, col, w)


def slash(surf: Surface, cx, cy, size, col, w) -> None:
    X, Y = _axes(cx, cy, size)
    surf.line(X(0.22), Y(0.22), X(0.78), Y(0.78), col, w)


def check(surf: Surface, cx, cy, size, col, w) -> None:
    X, Y = _axes(cx, cy, size)
    surf.poly([(X(0.18), Y(0.54)), (X(0.42), Y(0.76)), (X(0.84), Y(0.26))],
              col, w, closed=False)


def power(surf: Surface, cx, cy, size, col, w) -> None:
    """Exit: the power arc plus the stem."""
    X, Y = _axes(cx, cy, size)
    surf.arc(X(0.12), Y(0.14), X(0.88) - X(0.12), Y(0.90) - Y(0.14), 300, 300, col, w)
    surf.line(X(0.50), Y(0.06), X(0.50), Y(0.46), col, w)


GLYPHS = {
    "camera": camera,
    "microphone": microphone,
    "layout": layout,
    "gear": gear,
    "slash": slash,
    "check": check,
    "power": power,
}


def draw(surf: Surface, name: str, cx, cy, size, col, w=1.8) -> None:
    fn = GLYPHS.get(name)
    if fn is not None:
        fn(surf, cx, cy, size, col, w)

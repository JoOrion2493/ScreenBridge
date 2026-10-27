"""Layout templates.

The eight entries mirror "Main screen layout 1..8" from AsusXAppNavigator
(see XAppNavigatorLanguage.ini). Zones are normalised rects (x, y, w, h)
in the 0..1 space of a monitor's work area.
"""

from __future__ import annotations

from .win32 import Monitor

# (id, label, zones)
LAYOUTS: list[tuple[str, str, list[tuple[float, float, float, float]]]] = [
    ("split-v", "左右二分", [(0.0, 0.0, 0.5, 1.0), (0.5, 0.0, 0.5, 1.0)]),
    ("split-h", "上下二分", [(0.0, 0.0, 1.0, 0.5), (0.0, 0.5, 1.0, 0.5)]),
    (
        "third-v",
        "三列",
        [
            (0.0, 0.0, 1.0 / 3.0, 1.0),
            (1.0 / 3.0, 0.0, 1.0 / 3.0, 1.0),
            (2.0 / 3.0, 0.0, 1.0 / 3.0, 1.0),
        ],
    ),
    (
        "left-1-2",
        "左一右二",
        [(0.0, 0.0, 0.5, 1.0), (0.5, 0.0, 0.5, 0.5), (0.5, 0.5, 0.5, 0.5)],
    ),
    (
        "left-2-1",
        "左二右一",
        [(0.0, 0.0, 0.5, 0.5), (0.0, 0.5, 0.5, 0.5), (0.5, 0.0, 0.5, 1.0)],
    ),
    (
        "quad",
        "四宫格",
        [
            (0.0, 0.0, 0.5, 0.5),
            (0.5, 0.0, 0.5, 0.5),
            (0.0, 0.5, 0.5, 0.5),
            (0.5, 0.5, 0.5, 0.5),
        ],
    ),
    (
        "top-1-2",
        "上一下二",
        [(0.0, 0.0, 1.0, 0.5), (0.0, 0.5, 0.5, 0.5), (0.5, 0.5, 0.5, 0.5)],
    ),
    ("full", "全屏", [(0.0, 0.0, 1.0, 1.0)]),
]

LAYOUT_IDS = [x[0] for x in LAYOUTS]
_BY_ID = {x[0]: x for x in LAYOUTS}


def layout_by_id(layout_id: str):
    return _BY_ID.get(layout_id) or LAYOUTS[0]


def layout_index(layout_id: str) -> int:
    try:
        return LAYOUT_IDS.index(layout_id)
    except ValueError:
        return 0


def next_layout(layout_id: str, step: int = 1) -> str:
    i = (layout_index(layout_id) + step) % len(LAYOUTS)
    return LAYOUT_IDS[i]


def zones_for(
    mon: Monitor, layout_id: str, gap: int = 8, margin: int = 0
) -> list[tuple[int, int, int, int]]:
    """Absolute (l, t, r, b) rects for each zone of `mon`.

    Uses the work area so windows never land under the taskbar.
    """
    _, _, norm = layout_by_id(layout_id)
    wl, wt, wr, wb = mon.work
    il = wl + margin
    it = wt + margin
    ir = wr - margin
    ib = wb - margin
    iw = max(1, ir - il)
    ih = max(1, ib - it)

    half = gap // 2
    out: list[tuple[int, int, int, int]] = []
    for zx, zy, zw, zh in norm:
        l = int(round(il + zx * iw)) + half
        t = int(round(it + zy * ih)) + half
        r = int(round(il + (zx + zw) * iw)) - half
        b = int(round(it + (zy + zh) * ih)) - half
        if r - l < 40:
            l, r = int(round(il + zx * iw)), int(round(il + (zx + zw) * iw))
        if b - t < 40:
            t, b = int(round(it + zy * ih)), int(round(it + (zy + zh) * ih))
        out.append((l, t, r, b))
    return out


def hit_zone(rects: list[tuple[int, int, int, int]], x: int, y: int) -> int | None:
    for i, (l, t, r, b) in enumerate(rects):
        if l <= x < r and t <= y < b:
            return i
    return None

"""The drag-time palette.

This is a faithful reimplementation of what ASUS ScreenXpert calls the
App Navigator popup (AsusXAppNavigator.dll): while a window is being dragged
a small panel appears **under the cursor** and the choice happens in two
steps, exactly like the original -

    stage 1  a miniature of the desktop: one chip per display, each drawn at
             its real position and proportion (the arrangement from Windows
             Settings) and labelled with the system's own display number.
             Hover a chip and it opens stage 2 for that display.
    stage 2  a row of layout presets.  Each preset is drawn as its real zone
             split, and the zone under the cursor lights up.

    release on a zone  -> snap the dragged window into that zone
    release on a chip  -> move the whole window to that display

Input never reaches the window: it is WS_EX_TRANSPARENT so the drag keeps its
mouse capture, and the app polls GetCursorPos instead.  Painting is GDI+ onto
a premultiplied DIB, blitted with UpdateLayeredWindow - that is what gives the
rounded corners and the soft shadow their smooth edges.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import os
import time

from . import win32, zones
from .gdiplus import ARGB, StringAlignmentCenter, StringAlignmentNear, Surface

# ---------------------------------------------------------------- palette
C_PANEL = ARGB(243, 42, 42, 44)
C_EDGE = ARGB(20, 255, 255, 255)
C_CHIP_HOT = ARGB(255, 56, 56, 59)
C_ZONE = ARGB(255, 176, 176, 180)
C_ZONE_HOT = ARGB(255, 243, 243, 246)
C_CAPTION = ARGB(255, 168, 172, 182)
# the selected screen has to be obvious at a glance: an accent border, a faint
# accent wash inside it and a brighter number - the unselected chips are
# pushed down in contrast so the two never look alike
C_CHIP_SEL_EDGE = ARGB(255, 96, 165, 250)
C_CHIP_SEL_FILL = ARGB(52, 96, 165, 250)
C_CHIP_SEL_NUM = ARGB(255, 255, 255, 255)
C_CHIP_EDGE = ARGB(140, 158, 160, 168)
C_CHIP_EDGE_HOT = ARGB(225, 216, 218, 224)
C_CHIP_NUM = ARGB(255, 158, 162, 172)

WS_EX_ALL = (
    win32.WS_EX_TOPMOST
    | win32.WS_EX_TOOLWINDOW
    | win32.WS_EX_LAYERED
    | win32.WS_EX_NOACTIVATE
    | win32.WS_EX_TRANSPARENT
)

# How big the palette is, as a factor on top of the display's DPI scale.
# The old look is "large" (1.0); the two smaller steps shrink every panel,
# thumbnail and gap by the same ratio, so the layout never distorts.
SIZE_FACTORS = {
    "large": 1.0,
    "medium": 0.78,
    "small": 0.62,
}
SIZE_LABELS = {
    "large": "大",
    "medium": "中",
    "small": "小",
}
SIZE_ORDER = ["large", "medium", "small"]


def size_factor(name: str) -> float:
    return SIZE_FACTORS.get(name, SIZE_FACTORS["large"])


def _dbg(msg: str) -> None:
    """Gesture-trace logging, on only when SX_DEBUG is set (harness runs)."""
    if not os.environ.get("SX_DEBUG"):
        return
    try:
        import tempfile
        with open(os.path.join(tempfile.gettempdir(), "sxsnap_palette.log"), "a",
                  encoding="utf-8") as fh:
            fh.write(msg + "\n")
    except OSError:
        pass


class Palette:
    CLASS_NAME = "SXSnapDragPalette"

    def __init__(self) -> None:
        self.hwnd = 0
        self.monitors: list[win32.Monitor] = []
        self.scale = 1.0
        # the user's size choice, applied on top of the DPI scale
        self.size = "large"
        self.gap = 8
        self.margin = 0
        self.dwell_ms = 90

        self.active = False
        self.stage = 0                 # 0 = screens only, 1 = layouts expanded
        self.sel_mon = 0               # the display whose layouts are open
        self.hover_chip = -1
        self.hover_layout = -1
        self.hover_zone = -1
        self.origin = (0, 0)           # panel top-left, physical px

        # The two rows are placed independently and the window is the union of
        # them, so unfolding the (much wider) layout row can never drag the
        # chip row away from the pointer - the chip panel is pinned once, at
        # `_anchor_x/_anchor_y`, and only the layout row is fitted to the
        # desktop around it.
        self.flip = False              # layouts above the chips (no room below)
        self.lay_dir = "below"         # where the layout row goes: below/above/right/left
        self._layout_size = (0, 0)     # layout panel size, in px
        self._panel_gap = 10           # gap between the chip panel and the layout row
        self._anchor_x = 0             # chip panel left, absolute px
        self._anchor_y = 0             # chip panel top, absolute px
        self._rel_lay = (0, 0)         # layout panel offset from the chip panel

        self._surface: Surface | None = None
        self._size = (0, 0)
        self._chip_since = 0.0
        self._wndproc = win32.WNDPROC(self._wnd_proc)

    # ------------------------------------------------------------- lifecycle
    def create(self) -> int:
        if self.hwnd:
            return self.hwnd
        hinst = win32.kernel32.GetModuleHandleW(None)

        wc = win32.WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(win32.WNDCLASSEXW)
        wc.style = 0
        wc.lpfnWndProc = ctypes.cast(self._wndproc, ctypes.c_void_p)
        wc.hInstance = hinst
        wc.hCursor = win32.user32.LoadCursorW(None, ctypes.c_void_p(win32.IDC_ARROW))
        wc.hbrBackground = None
        wc.lpszClassName = self.CLASS_NAME
        if not win32.user32.RegisterClassExW(ctypes.byref(wc)):
            err = ctypes.get_last_error()
            if err != 1410:  # ERROR_CLASS_ALREADY_EXISTS
                raise OSError(f"RegisterClassExW failed (err={err})")

        self.hwnd = win32.user32.CreateWindowExW(
            WS_EX_ALL, self.CLASS_NAME, "SXSnap Palette",
            win32.WS_POPUP, 0, 0, 1, 1, None, None, hinst, None,
        )
        if not self.hwnd:
            raise OSError(f"CreateWindowExW failed (err={ctypes.get_last_error()})")
        return self.hwnd

    def destroy(self) -> None:
        if self._surface is not None:
            self._surface.dispose()
            self._surface = None
        if self.hwnd:
            win32.user32.DestroyWindow(self.hwnd)
            self.hwnd = 0

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == win32.WM_DISPLAYCHANGE:
            self.monitors = win32.enumerate_monitors()
            return 0
        return win32.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # -------------------------------------------------------------- geometry
    def _minimap(self):
        """The virtual desktop fitted into the chip panel, real arrangement.

        Monitors keep their actual positions and proportions (secondary left,
        right, above, below, however the user arranged them in Settings), so
        the chips are a miniature map of the desktop rather than an arbitrary
        row.  Returns (map_w, map_h, rects) with rects[i] for self.monitors[i].
        """
        vl, vt, vr, vb = win32.virtual_screen()
        vw, vh = max(1, vr - vl), max(1, vb - vt)
        s = self.scale
        k = min(356 * s / vw, 88 * s / vh)
        mw, mh = vw * k, vh * k
        rects = []
        for m in self.monitors:
            l, t, r, b = m.rect
            rects.append(((l - vl) * k, (t - vt) * k, (r - l) * k, (b - t) * k))
        return mw, mh, rects

    def _chip_geo(self):
        """Stateless chip-panel geometry: (sw, sh, mm_w, mm_h, rects, mx, my).

        Everything derived from the monitors and the scale only - deliberately
        *not* from `_rel_lay`, because the anchor must not depend on where the
        previous anchor put the layout row (the app re-anchors with stale
        state; a fresh prediction must land on the same spot).
        """
        s = self.scale
        pad = int(round(12 * s))
        inner = int(round(10 * s))         # panel edge <-> minimap breathing room
        mm_w, mm_h, rects = self._minimap()
        sw = max(pad * 2 + int(mm_w) + inner * 2, int(round(180 * s)))
        sh = max(pad * 2 + int(mm_h) + inner * 2, int(round(112 * s)))
        # centre the map inside the chip panel
        return sw, sh, mm_w, mm_h, rects, (sw - mm_w) / 2.0, (sh - mm_h) / 2.0

    def metrics(self, stage: int | None = None) -> dict:
        """Window-local geometry for a stage.

        The two rows are placed independently - the chip panel at the anchor,
        the layout panel at `_rel_lay` from it - and the window is the union of
        both.  That is what lets the wide layout row be fitted to the desktop
        without dragging the narrow chip row out from under the pointer.
        `flip` puts the layout row above the chips when the pointer is too low
        for it to unfold downwards.
        """
        st = self.stage if stage is None else stage
        s = self.scale
        pad = int(round(12 * s))
        sw, sh, mm_w, mm_h, mm_rects, mx, my = self._chip_geo()

        tw = int(round(106 * s))
        th = int(round(84 * s))
        tg = int(round(14 * s))
        m = len(zones.LAYOUTS)
        lw = pad * 2 + m * tw + max(0, m - 1) * tg
        lh = pad * 2 + th

        if st == 1:
            dx, dy = self._rel_lay
        else:
            dx = dy = 0
        ox, oy = -min(0, dx), -min(0, dy)   # window origin, in chip-panel space
        out = {
            "w": max(sw, dx + lw) - min(0, dx) if st == 1 else sw,
            "h": max(sh, dy + lh) - min(0, dy) if st == 1 else sh,
            "s": s, "pad": pad, "sw": sw, "sh": sh,
            "chips": [
                (ox + mx + rx, oy + my + ry, rw, rh) for rx, ry, rw, rh in mm_rects
            ],
            "chip_box": (ox, oy, sw, sh),
            "layout": None,
            "thumbs": [],
        }
        if st == 1:
            out["layout"] = (ox + dx, oy + dy, lw, lh)
            out["thumbs"] = [
                (ox + dx + pad + i * (tw + tg), oy + dy + pad, tw, th) for i in range(m)
            ]
        return out

    def _thumb_zones(self, tx, ty, tw, th, layout_id) -> list[tuple[int, int, int, int]]:
        _, _, norm = zones.layout_by_id(layout_id)
        g = max(2, int(round(4 * self.scale)))
        half = g // 2
        out = []
        for zx, zy, zw, zh in norm:
            l = int(round(tx + zx * tw)) + (half if zx > 0.001 else 0)
            t = int(round(ty + zy * th)) + (half if zy > 0.001 else 0)
            r = int(round(tx + (zx + zw) * tw)) - (half if zx + zw < 0.999 else 0)
            b = int(round(ty + (zy + zh) * th)) - (half if zy + zh < 0.999 else 0)
            out.append((l, t, max(l + 2, r), max(t + 2, b)))
        return out

    # --------------------------------------------------------------- anchors
    def _monitor_index(self, pt) -> int:
        for i, m in enumerate(self.monitors):
            l, t, r, b = m.rect
            if l <= pt[0] < r and t <= pt[1] < b:
                return i
        return 0

    # ---------------------------------------------------------- arrangement
    def _row_axis(self) -> str:
        """'h' - the screens form a horizontal row, 'v' - a vertical column.

        Counted on the mini-map: two screens standing side by side are
        horizontal neighbours, two stacked on top of each other are vertical
        ones.  Whichever kind is more common decides the axis; a perfect
        grid has both and counts as "mixed".
        """
        rects = self._minimap()[2]
        h = v = 0
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                ax, ay, aw, ah = rects[i]
                bx, by, bw, bh = rects[j]
                vo = min(ay + ah, by + bh) - max(ay, by)     # vertical overlap
                ho = min(ax + aw, bx + bw) - max(ax, bx)     # horizontal overlap
                if vo > 0 and ho <= 0:
                    h += 1
                elif ho > 0 and vo <= 0:
                    v += 1
        if v > h:
            return "v"
        if h > v:
            return "h"
        return "mix"

    def _blocked(self, chip_rects, px: float, py: float, direction: str) -> bool:
        """Would a chip stand between the pointer and that edge of the panel?

        The pointer has to reach the layout row without dragging across
        another screen chip - that is the whole point of moving the row
        sideways when the screens are stacked.
        """
        for (cx, cy, cw, ch) in chip_rects:
            if direction == "below" and cy >= py and cx <= px <= cx + cw:
                return True
            if direction == "above" and cy + ch <= py and cx <= px <= cx + cw:
                return True
            if direction == "right" and cx >= px and cy <= py <= cy + ch:
                return True
            if direction == "left" and cx + cw <= px and cy <= py <= cy + ch:
                return True
        return False

    def _fits(self, direction: str, box, vbox, wbox) -> bool:
        """Is there room for the layout row on that side of the chip panel?"""
        x, y, sw, sh = box
        vl, vt, vr, vb = vbox
        wt, wb = wbox
        lw, lh = self._layout_size
        gap = self._panel_gap
        if direction == "below":
            return y + sh + gap + lh <= wb - 4
        if direction == "above":
            return y - gap - lh >= wt + 4
        if direction == "right":
            return x + sw + gap + lw <= vr - 4
        return x - gap - lw >= vl + 4

    def _pick_direction(self, chip_rects, px: float, py: float,
                        box, vbox, wbox) -> str:
        """Which side of the chip panel the layout row goes on.

        The arrangement decides the order of the candidates: a horizontal row
        of screens opens downwards, a vertical column opens sideways - the
        row underneath a column of screens meant reaching the top chip by
        dragging across the ones below it.

        A direction is only offered when nothing stands between the pointer
        and that edge, and when the layout row actually fits there.
        """
        order = {
            "h": ("below", "above", "right", "left"),
            "v": ("right", "left", "below", "above"),
            "mix": ("below", "right", "above", "left"),
        }[self._row_axis()]
        for d in order:
            if self._blocked(chip_rects, px, py, d):
                continue
            if not self._fits(d, box, vbox, wbox):
                continue
            return d
        # nothing fits cleanly: take the first direction that is at least
        # not blocked and let the row overlap rather than hide the chips
        for d in order:
            if not self._blocked(chip_rects, px, py, d):
                return d
        return order[0]

    def _layout_origin(self, direction: str, box, px: float, py: float,
                       vbox, wbox) -> tuple[int, int]:
        """Top-left of the layout row, in screen coordinates."""
        x, y, sw, sh = box
        vl, vt, vr, vb = vbox
        wt, wb = wbox
        lw, lh = self._layout_size
        gap = self._panel_gap
        if direction in ("below", "above"):
            # the row runs across, so it has to cover the pointer's x
            lx = int(px - lw / 2.0)
            lx = max(min(lx, vr - 4 - lw), vl + 4)
            if lw >= (vr - vl) - 8:
                lx = vl + 4
            ly = (y + sh + gap) if direction == "below" else (y - gap - lh)
        else:
            # the row stands to the side, so it has to cover the pointer's y
            ly = int(py - lh / 2.0)
            ly = max(min(ly, wb - 4 - lh), wt + 4)
            lx = (x + sw + gap) if direction == "right" else (x - gap - lw)
            lx = max(min(lx, vr - 4 - lw), vl + 4)
        return lx, ly


    def arrangement(self) -> str:
        """A one-word summary of how the displays are laid out.

        Judged on the virtual-desktop rectangles, not on the source-mode
        positions: with the panels on different adapters each one reports its
        own origin at (0, 0), so those positions say nothing about the
        arrangement the user actually sees.
        """
        if len(self.monitors) <= 1:
            return "单屏"
        try:
            from . import displays
            rects = {m.device: m.rect for m in self.monitors}
            return displays.arrangement(rects)
        except Exception:
            return ""

    def _anchor(self, pt) -> None:
        """Pin the chip row to the cursor and fit the layout row around it.

        Called once when the palette opens - and again only when the pointer
        walks far away from it - but *never* on the stage change.  Recomputing
        the anchor there is exactly what used to make the panel lurch as the
        layouts unfolded: the vertical fit flipped the taller box above the
        pointer (a 400 px jolt) and the horizontal clamp, computed against the
        narrow stage-0 width, then had to shove the wide row left by as much as
        a whole display.

        The two rows are placed independently: the chip panel is small and
        always fits under the pointer, the layout row is wide and is fitted
        to the whole desktop - crossing the bezel reads as normal, sliding
        away from the pointer does not.

        Which side of the chip panel the layout row goes on is decided by the
        arrangement of the screens, not by the free space alone - see
        `_pick_direction`.
        """
        if not self.monitors:
            return
        # the anchor is a pure function of the pointer: the display under it
        # decides the scale and which chip gets centred, so a re-anchor never
        # leaves the row pointing at the display the pointer has left
        self.sel_mon = self._monitor_index(pt)
        mi = self.sel_mon
        self.scale = self.monitors[mi].dpi / 96.0 * size_factor(self.size)
        s = self.scale
        gap = int(round(18 * s))           # breathing room between pointer and panel
        m1 = self.metrics(1)
        sw, sh = m1["sw"], m1["sh"]
        lw, lh = m1["layout"][2], m1["layout"][3]
        self._layout_size = (lw, lh)
        self._panel_gap = int(round(10 * s))

        wl, wt, wr, wb = self.monitors[mi].work
        vl, vt, vr, vb = win32.virtual_screen()
        vbox = (vl, vt, vr, vb)
        wbox = (wt, wb)

        # --- chip map: centred on the pointer via the *selected monitor's*
        # own rectangle in the mini-map.  Uses _chip_geo (stateless) rather
        # than the stage-1 chips, which carry the previous anchor's _rel_lay
        # offset - a re-anchor must land where a fresh one would. ------------
        sw0, sh0, mm_w, mm_h, mm_rects, mx0, _ = self._chip_geo()
        rx, ry, rw, rh = mm_rects[mi]
        x = int(pt[0] - (mx0 + rx + rw / 2.0))
        x = max(min(x, vr - 4 - sw), vl + 4)

        # the chip panel sits under the pointer, as before
        y = int(pt[1] + gap)
        y = max(min(y, wb - 4 - sh), wt + 4)
        box = (x, y, sw, sh)

        # --- the chips, in screen coordinates, and the one the pointer heads for
        chip_rects = [(x + cx, y + cy, cw, chh) for (cx, cy, cw, chh) in m1["chips"]]
        cx0, cy0, cw0, ch0 = chip_rects[mi]
        px = cx0 + cw0 / 2.0
        py = cy0 + ch0 / 2.0

        # --- where the layout row goes ---------------------------------------
        direction = self._pick_direction(chip_rects, px, py, box, vbox, wbox)
        lx, ly = self._layout_origin(direction, box, px, py, vbox, wbox)

        self.lay_dir = direction
        self.flip = direction in ("above", "left")
        self._anchor_x = x
        self._anchor_y = y
        self._rel_lay = (lx - x, ly - y)
        self._place_window()

    def _place_window(self) -> None:
        """Derive the window origin from the anchor and the *current* stage.

        Only the window's own top-left moves between stages; the chip panel
        keeps the position `_anchor` gave it.
        """
        m = self.metrics()
        ox, oy = m["chip_box"][0], m["chip_box"][1]
        self.origin = (self._anchor_x - ox, self._anchor_y - oy)

    def _distance(self, pt) -> float:
        m = self.metrics()
        ox, oy = self.origin
        dx = max(0, max(ox - pt[0], pt[0] - (ox + m["w"])))
        dy = max(0, max(oy - pt[1], pt[1] - (oy + m["h"])))
        return (dx * dx + dy * dy) ** 0.5

    # ------------------------------------------------------- state machine
    def begin(self, pt) -> None:
        self.monitors = win32.enumerate_monitors()
        if not self.monitors:
            return

        self.sel_mon = self._monitor_index(pt)
        self.scale = self.monitors[self.sel_mon].dpi / 96.0 * size_factor(self.size)
        self.stage = 0
        self.flip = False
        self.lay_dir = "below"
        self.hover_chip = -1
        self.hover_layout = -1
        self.hover_zone = -1
        self._chip_since = 0.0
        self.active = True

        self.create()
        self._anchor(pt)
        win32.user32.ShowWindow(self.hwnd, win32.SW_SHOWNA)
        self.paint()

    def end(self) -> None:
        if not self.active:
            return
        self.active = False
        self.stage = 0
        self.hover_chip = -1
        self.hover_layout = -1
        self.hover_zone = -1
        if self.hwnd:
            win32.user32.ShowWindow(self.hwnd, win32.SW_HIDE)

    def cancel(self) -> None:
        self.end()

    def update(self, pt) -> str:
        """Recompute hover/selection from a cursor position."""
        if not self.active:
            return "none"

        if self._distance(pt) > 220 * self.scale:
            # dragged far away: bring the palette back to the cursor
            _dbg(f"re-anchor: pt={pt} origin={self.origin} stage={self.stage}")
            self.hover_chip = -1
            self.hover_layout = -1
            self.hover_zone = -1
            self._chip_since = 0.0
            self._anchor(pt)
            self.paint()

        m = self.metrics()
        ox, oy = self.origin
        lx, ly = pt[0] - ox, pt[1] - oy

        # ---- stage 1: which screen chip is under the cursor -----------------
        chip = -1
        for i, (cx, cy, cw, chh) in enumerate(m["chips"]):
            if cx <= lx < cx + cw and cy <= ly < cy + chh:
                chip = i
                break

        if chip != self.hover_chip:
            _dbg(f"hover: pt={pt} chip={chip} (was {self.hover_chip}) "
                 f"chips={[(round(a),round(b),round(c),round(d)) for a,b,c,d in m['chips']]} "
                 f"origin={self.origin}")
            self.hover_chip = chip
            if chip >= 0:
                self._chip_since = time.monotonic()
                if self.stage == 1:
                    self.sel_mon = chip
            else:
                self._chip_since = 0.0
            self.paint()

        if chip >= 0 and self.stage == 0:
            if self._chip_since and (time.monotonic() - self._chip_since) * 1000 >= self.dwell_ms:
                self.stage = 1
                self.sel_mon = chip
                # re-derive the origin for the taller box, but keep the anchor:
                # the chip row must not move out from under the pointer
                self._place_window()
                self.paint()
                return "expand"

        # ---- stage 2: which layout zone is under the cursor ----------------
        if self.stage == 1:
            li = zi = -1
            for i, (tx, ty, tw, th) in enumerate(m["thumbs"]):
                if tx <= lx < tx + tw and ty <= ly < ty + th:
                    lid = zones.LAYOUT_IDS[i]
                    u = (lx - tx) / float(tw)
                    v = (ly - ty) / float(th)
                    for j, (zx, zy, zw, zh) in enumerate(zones.layout_by_id(lid)[2]):
                        if zx <= u < zx + zw and zy <= v < zy + zh:
                            li, zi = i, j
                            break
                    break

            if (li, zi) != (self.hover_layout, self.hover_zone):
                self.hover_layout, self.hover_zone = li, zi
                self.paint()

        return "zone" if self.hover_zone >= 0 else ("chip" if chip >= 0 else "none")

    def resolve(self):
        """The action for a mouse release at the current hover position."""
        if not self.active:
            return None
        if self.stage == 1 and self.hover_layout >= 0 and self.hover_zone >= 0:
            return ("zone", self.sel_mon, self.hover_layout, self.hover_zone)
        if self.hover_chip >= 0:
            return ("screen", self.hover_chip)
        return None

    # ---------------------------------------------------------------- paint
    def paint(self) -> None:
        if not self.hwnd or not self.monitors:
            return
        m = self.metrics()
        if self._surface is None or self._size != (m["w"], m["h"]):
            if self._surface is not None:
                self._surface.dispose()
            self._surface = Surface(m["w"], m["h"])
            self._size = (m["w"], m["h"])

        surf = self._surface
        s = self.scale
        surf.clear(0)

        cb = m["chip_box"]
        lay = m["layout"] if self.stage == 1 else None

        # far panel first, so the near one (and its shadow) sits on top.
        # "near" = the one the pointer reaches first: the chip panel when the
        # layout row opens below or to the right, the layout row otherwise.
        far_first = self.lay_dir in ("above", "left")
        if lay and far_first:
            self._panel(surf, lay[0], lay[1], lay[2], lay[3], s)
        self._panel(surf, cb[0], cb[1], cb[2], cb[3], s)
        if lay and not far_first:
            self._panel(surf, lay[0], lay[1], lay[2], lay[3], s)

        self._paint_chips(surf, m, s)
        if lay:
            self._paint_thumbs(surf, m, s)

        surf.blit(self.hwnd, *self.origin)

    def _panel(self, surf: Surface, x, y, ww, hh, s) -> None:
        r = int(round(10 * s))
        for k in range(7, 0, -1):
            grow = k * 1.7 * s
            alpha = int(3 + 2.2 * (7 - k))
            surf.fill_round(
                x - grow, y - grow + 2 * s, ww + 2 * grow, hh + 2 * grow,
                r + grow, ARGB(min(20, alpha), 0, 0, 0),
            )
        surf.fill_round(x, y, ww, hh, r, C_PANEL)
        surf.stroke_round(x, y, ww, hh, r, C_EDGE, max(1.0, 1.0 * s))

    def _paint_chips(self, surf: Surface, m: dict, s: float) -> None:
        """A miniature of the desktop: each monitor at its real position.

        The label is the system's own display number ("\\\\.\\DISPLAY<N>",
        the same N Settings > Display shows and Identify flashes), so the
        chips always agree with what the user sees in Windows - no matter
        how the displays are arranged or how many there are.  The caption
        above the map spells the arrangement out (横排 / 竖排 / 错落).
        """
        self._paint_caption(surf, m, s)
        for i, (cx, cy, cw, chh) in enumerate(m["chips"]):
            mon = self.monitors[i]
            sel = self.stage == 1 and i == self.sel_mon
            hot = i == self.hover_chip or sel
            # inset so adjacent monitors get a visible bezel gap
            g = max(2.0, 2.5 * s)
            x, y, ww, hh = cx + g, cy + g, cw - 2 * g, chh - 2 * g
            if sel:
                # the chosen screen: a wash of the accent colour inside and a
                # fat accent border around it, so it reads as "this one" even
                # in a screenshot
                surf.fill_round(x, y, ww, hh, 5 * s, C_CHIP_SEL_FILL)
                surf.stroke_round(x, y, ww, hh, 5 * s, C_CHIP_SEL_EDGE, 2.6 * s)
            elif hot:
                surf.fill_round(x, y, ww, hh, 5 * s, C_CHIP_HOT)
                surf.stroke_round(x, y, ww, hh, 5 * s, C_CHIP_EDGE_HOT, 1.8 * s)
            else:
                surf.stroke_round(x, y, ww, hh, 5 * s, C_CHIP_EDGE, 1.4 * s)
            fs = min(24 * s, hh * 0.5)
            if sel:
                surf.text(str(mon.number), x, y, ww, hh, fs, C_CHIP_SEL_NUM, bold=1)
            else:
                surf.text(str(mon.number), x, y, ww, hh, fs, C_CHIP_NUM)

    def _paint_caption(self, surf: Surface, m: dict, s: float) -> None:
        """Spell the arrangement out above the map: 横排 / 竖排 / 错落.

        The map itself already shows the true relative positions; this is the
        explicit word for it, so a user with three screens in a staircase can
        read the arrangement without interpreting the picture.
        """
        arr = self.arrangement()
        if not arr:
            return
        n = len(self.monitors)
        label = arr if n <= 1 else f"{arr} · {n} 屏"

        cb = m["chip_box"]
        _sw, _sh, _mw, _mh, _rects, _mx, my = self._chip_geo()
        if my < 15 * s:
            return                     # no room for a caption - skip it
        surf.text(label, cb[0] + 10 * s, cb[1] + 1 * s, m["sw"] - 20 * s,
                  my - 3 * s, 11.5 * s, C_CAPTION, align=StringAlignmentNear)

    def _paint_thumbs(self, surf: Surface, m: dict, s: float) -> None:
        for i, (tx, ty, tw, th) in enumerate(m["thumbs"]):
            lid = zones.LAYOUT_IDS[i]
            for j, (l, t, r, b) in enumerate(self._thumb_zones(tx, ty, tw, th, lid)):
                hot = i == self.hover_layout and j == self.hover_zone
                surf.fill_round(l, t, r - l, b - t, 3 * s, C_ZONE_HOT if hot else C_ZONE)

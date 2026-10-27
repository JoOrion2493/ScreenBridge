"""The drag-time palette.

This is a faithful reimplementation of what ASUS ScreenXpert calls the
App Navigator popup (AsusXAppNavigator.dll): while a window is being dragged
a small panel appears **under the cursor** and the choice happens in two
steps, exactly like the original -

    stage 1  a row of screen chips, one per display, each a mini screen with
             its number.  Hover a chip and it opens stage 2 for that display.
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
import time

from . import win32, zones
from .gdiplus import ARGB, StringAlignmentCenter, Surface

# ---------------------------------------------------------------- palette
C_PANEL = ARGB(243, 42, 42, 44)
C_EDGE = ARGB(20, 255, 255, 255)
C_CHIP_HOT = ARGB(255, 56, 56, 59)
C_BOX_EDGE = ARGB(232, 203, 203, 206)
C_BOX_EDGE_SEL = ARGB(255, 242, 242, 245)
C_NUM = ARGB(255, 246, 246, 248)
C_GLYPH = ARGB(255, 148, 148, 152)
C_DIV = ARGB(255, 66, 66, 70)
C_ZONE = ARGB(255, 176, 176, 180)
C_ZONE_HOT = ARGB(255, 243, 243, 246)

WS_EX_ALL = (
    win32.WS_EX_TOPMOST
    | win32.WS_EX_TOOLWINDOW
    | win32.WS_EX_LAYERED
    | win32.WS_EX_NOACTIVATE
    | win32.WS_EX_TRANSPARENT
)


class Palette:
    CLASS_NAME = "SXSnapDragPalette"

    def __init__(self) -> None:
        self.hwnd = 0
        self.monitors: list[win32.Monitor] = []
        self.scale = 1.0
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
        cw = int(round(118 * s))
        chh = int(round(96 * s))
        cg = int(round(14 * s))
        n = max(1, len(self.monitors))
        sw = pad * 2 + n * cw + max(0, n - 1) * cg
        sh = pad * 2 + chh

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
            "chips": [(ox + pad + i * (cw + cg), oy + pad, cw, chh) for i in range(n)],
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

    def _anchor(self, pt) -> None:
        """Pin the chip row to the cursor and fit the layout row around it.

        Called once when the palette opens - and again only when the pointer
        walks far away from it - but *never* on the stage change.  Recomputing
        the anchor there is exactly what used to make the panel lurch as the
        layouts unfolded: the vertical fit flipped the taller box above the
        pointer (a 400 px jolt) and the horizontal clamp, computed against the
        narrow stage-0 width, then had to shove the wide row left by as much as
        a whole display.

        So the two rows get separate horizontal fits: the chip panel is small
        and always fits under the pointer, the layout row is wide and is fitted
        to the whole desktop - crossing the bezel reads as normal, sliding away
        from the pointer does not.
        """
        if not self.monitors:
            return
        # the anchor is a pure function of the pointer: the display under it
        # decides the scale and which chip gets centred, so a re-anchor never
        # leaves the row pointing at the display the pointer has left
        self.sel_mon = self._monitor_index(pt)
        mi = self.sel_mon
        self.scale = self.monitors[mi].dpi / 96.0
        s = self.scale
        pad = int(round(12 * s))
        cw = int(round(118 * s))
        cg = int(round(14 * s))
        rg = int(round(10 * s))
        gap = int(round(18 * s))           # breathing room between pointer and panel
        m1 = self.metrics(1)
        sw, sh = m1["sw"], m1["sh"]
        lw, lh = m1["layout"][2], m1["layout"][3]

        wl, wt, wr, wb = self.monitors[mi].work
        vl, vt, vr, vb = win32.virtual_screen()

        # --- chip row: centred on the pointer; only the desktop limits it -----
        # (clamping to the display instead would leave the pointer pointing at
        # a bare patch of panel near a bezel)
        cx = pad + mi * (cw + cg)
        x = int(pt[0] - (cx + cw / 2.0))
        x = max(min(x, vr - 4 - sw), vl + 4)

        # --- layout row: centred too, but fitted to the whole desktop --------
        lx = int(pt[0] - lw / 2.0)
        lx = max(min(lx, vr - 4 - lw), vl + 4)
        if lw >= (vr - vl) - 8:
            lx = vl + 4

        # --- vertical: unfold away from the pointer, never across it ---------
        if (pt[1] + gap) + sh + rg + lh <= wb - 4:
            self.flip = False
            y, dy = int(pt[1] + gap), sh + rg
        elif (pt[1] - gap - sh) - rg - lh >= wt + 4:
            self.flip = True
            y, dy = int(pt[1] - gap - sh), -(rg + lh)
        else:
            # neither side has room (tiny display): keep the chips reachable and
            # let the layout row take whatever slack is left
            self.flip = pt[1] > wt + (wb - wt) // 2
            if self.flip:
                y, dy = max(wt + 4, int(pt[1] - gap - sh)), -(rg + lh)
            else:
                y, dy = int(pt[1] + gap), sh + rg
        y = max(min(y, wb - 4 - sh), wt + 4)

        self._anchor_x = x
        self._anchor_y = y
        self._rel_lay = (lx - x, dy)
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
        self.scale = self.monitors[self.sel_mon].dpi / 96.0
        self.stage = 0
        self.flip = False
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

        # far panel first, so the near one (and its shadow) sits on top
        if lay and self.flip:
            self._panel(surf, lay[0], lay[1], lay[2], lay[3], s)
        self._panel(surf, cb[0], cb[1], cb[2], cb[3], s)
        if lay and not self.flip:
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
        n = len(m["chips"])
        for i, (cx, cy, cw, chh) in enumerate(m["chips"]):
            sel = self.stage == 1 and i == self.sel_mon
            hot = i == self.hover_chip or sel
            if hot:
                surf.fill_round(cx, cy, cw, chh, 7 * s, C_CHIP_HOT)

            bw, bh = 92 * s, 54 * s
            bx = cx + (cw - bw) / 2.0
            by = cy + 12 * s
            surf.stroke_round(bx, by, bw, bh, 5 * s,
                              C_BOX_EDGE_SEL if sel else C_BOX_EDGE, 1.6 * s)
            surf.text(str(i + 1), bx, by, bw, bh, 26 * s, C_NUM)

            gw, gh = 26 * s, 3 * s
            gx = cx + (cw - gw) / 2.0
            gy = by + bh + 11 * s
            surf.fill_round(gx, gy, gw, gh, gh / 2.0, C_GLYPH)
            surf.fill_round(gx + 4 * s, gy + 6 * s, gw - 8 * s, gh, gh / 2.0, C_GLYPH)

            if i < n - 1:
                dx = cx + cw + int(round(7 * s))
                surf.fill_round(dx, cy + 6 * s, max(1.0, 1.0 * s), chh - 12 * s, 0, C_DIV)

    def _paint_thumbs(self, surf: Surface, m: dict, s: float) -> None:
        for i, (tx, ty, tw, th) in enumerate(m["thumbs"]):
            lid = zones.LAYOUT_IDS[i]
            for j, (l, t, r, b) in enumerate(self._thumb_zones(tx, ty, tw, th, lid)):
                hot = i == self.hover_layout and j == self.hover_zone
                surf.fill_round(l, t, r - l, b - t, 3 * s, C_ZONE_HOT if hot else C_ZONE)

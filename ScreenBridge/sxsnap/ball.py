"""The floating ball, its vertical icon bar and the settings panel.

Three separate layered windows, because they have different lifetimes:

  ball    always there (unless the user hides it).  Two looks: the circular
          logo, and - once docked against a screen edge - a short translucent
          blue bar, so it stops covering whatever is underneath.
  bar     the vertical strip from the reference design: camera, microphone,
          layout, settings.  Opens above the ball and closes on any click
          outside it.
  panel   the four switches plus 退出.

Paint and hit-testing live together on purpose: the visible shape and the
clickable shape have to agree, otherwise a round ball gets square corners that
eat clicks meant for the window behind it.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import time

from . import config, devices, icons, win32
from .gdiplus import ARGB, StringAlignmentCenter, StringAlignmentNear, Surface
from .shell import Layered, Toast, dpi_scale, monitor_at, resource_path, user32

# ------------------------------------------------------------------ geometry
BALL_D = 46            # the visible disc
BALL_PAD = 16          # room for the shadow; the window is bigger than the disc
BAR_W, BAR_H = 7, 54   # the docked bar
BAR_PAD = 6

MENU_W = 56
MENU_ICON = 24
MENU_GAP = 18
MENU_PAD = 20
MENU_SHADOW = 12
MENU_OFFSET = 9        # gap between the ball and the bar

PANEL_W = 320
PANEL_PAD = 14
PANEL_HEAD = 44
ROW_H = 46
SEP_H = 13
ACT_H = 44
PANEL_SHADOW = 14

DRAG_SLOP = 5          # px before a press becomes a drag
SNAP_TOL = 36          # DIP: how close to an edge counts as "dropped on it"

# -------------------------------------------------------------------- colour
C_ACCENT = ARGB(255, 96, 165, 250)
C_ACCENT_DIM = ARGB(120, 96, 165, 250)
C_ICON = ARGB(255, 226, 232, 240)
C_ICON_OFF = ARGB(255, 150, 163, 181)
C_ICON_DIM = ARGB(95, 148, 163, 184)
# Fully opaque on purpose: even 250/255 lets the desktop's text ghost through
# a panel this dark, and it is the one artefact users notice immediately.
C_MENU_BG = ARGB(252, 17, 24, 39)
C_MENU_EDGE = ARGB(26, 255, 255, 255)
C_TILE_HOT = ARGB(255, 38, 51, 74)
C_PANEL_BG = ARGB(255, 26, 28, 33)
C_PANEL_EDGE = ARGB(22, 255, 255, 255)
C_TEXT = ARGB(255, 236, 238, 242)
C_TEXT_DIM = ARGB(255, 152, 156, 164)
C_SEP = ARGB(255, 74, 78, 86)
C_TRACK_ON = ARGB(255, 59, 130, 246)
C_TRACK_OFF = ARGB(255, 74, 78, 88)
C_KNOB = ARGB(255, 249, 250, 252)
C_DANGER = ARGB(255, 248, 133, 133)
C_ROW_HOT = ARGB(255, 40, 43, 50)

SWITCH_W, SWITCH_H = 42, 24


def _shadow(surf: Surface, x, y, ww, hh, r, s, layers=6, peak=16):
    for k in range(layers, 0, -1):
        grow = k * 1.7 * s
        alpha = int(3 + (peak - 3) * (layers - k) / max(1, layers - 1))
        surf.fill_round(x - grow, y - grow + 2 * s, ww + grow * 2, hh + grow * 2,
                        r + grow, ARGB(min(peak, alpha), 0, 0, 0))


# ---------------------------------------------------------------------ball
class Ball(Layered):
    CLASS = "SXSnapBall"
    TITLE = "SXSnap"

    def __init__(self, ui: "BallUI") -> None:
        super().__init__()
        self.ui = ui
        self.hover = False
        self._logo = ""

    # ---- geometry ---------------------------------------------------------
    def is_bar(self) -> bool:
        return self.ui.docked

    def scale(self) -> float:
        return dpi_scale(self.hwnd)

    def pad(self) -> int:
        s = self.scale()
        return int(round((BAR_PAD if self.is_bar() else BALL_PAD) * s))

    def shape(self) -> tuple[int, int]:
        """Visible size in px, not counting the shadow margin."""
        s = self.scale()
        if self.is_bar():
            ww, hh = (BAR_H, BAR_W) if self.ui.edge in ("top", "bottom") else (BAR_W, BAR_H)
            return (int(round(ww * s)), int(round(hh * s)))
        d = int(round(BALL_D * s))
        return (d, d)

    def geometry(self) -> tuple[int, int]:
        sw, sh = self.shape()
        p = self.pad()
        return (sw + p * 2, sh + p * 2)

    def visible_rect(self) -> tuple[int, int, int, int]:
        p = self.pad()
        sw, sh = self.shape()
        return (self.pos[0] + p, self.pos[1] + p, self.pos[0] + p + sw, self.pos[1] + p + sh)

    def place_visible(self, x: int, y: int) -> None:
        p = self.pad()
        self.place(x - p, y - p)

    # ---- paint ------------------------------------------------------------
    def draw(self, surf: Surface) -> None:
        s = self.scale()
        p = self.pad()
        sw, sh = self.shape()
        if self.is_bar():
            self._draw_bar(surf, p, p, sw, sh, s)
        else:
            self._draw_ball(surf, p, p, sw, s)

    def _draw_ball(self, surf: Surface, x, y, d, s) -> None:
        r = d / 2.0
        # a soft halo: many low-alpha rings read as a blur, a handful of
        # stronger ones read as banding - which is very visible on a light
        # desktop where the shadow is the only thing around the disc
        layers = 14
        for k in range(layers, 0, -1):
            grow = k * 0.95 * s
            alpha = int(1 + 0.75 * (layers - k))
            surf.fill_round(x - grow, y - grow + 2.2 * s, d + grow * 2, d + grow * 2,
                            r + grow, ARGB(min(10, alpha), 0, 0, 0))

        if not self._logo:
            self._logo = resource_path("ball.png")
        drawn = bool(self._logo) and surf.image(self._logo, x, y, d, d)

        if not drawn:                       # fallback: blue disc + screen glyph
            surf.ellipse(x, y, d, d, ARGB(255, 37, 99, 235))
            icons.layout(surf, x + d / 2, y + d / 2, d * 0.52, ARGB(255, 255, 255, 255),
                         2.0 * s)

        if self.hover or self.ui.menu_open():
            surf.ring(x - 1.5 * s, y - 1.5 * s, d + 3 * s, d + 3 * s,
                      C_ACCENT if self.ui.menu_open() else ARGB(150, 255, 255, 255),
                      2.0 * s)

    def _draw_bar(self, surf: Surface, x, y, sw, sh, s) -> None:
        hot = self.hover or self.ui.menu_open()
        radius = min(sw, sh) / 2.0
        # a soft blue halo so the sliver is noticeable without being loud
        for k in range(5, 0, -1):
            grow = k * 2.0 * s
            surf.fill_round(x - grow, y - grow, sw + grow * 2, sh + grow * 2,
                            radius + grow, ARGB(7, 96, 165, 250))
        alpha = 215 if hot else 150
        surf.fill_round(x, y, sw, sh, radius, ARGB(alpha, 96, 165, 250))
        surf.stroke_round(x, y, sw, sh, radius, ARGB(min(255, alpha + 20), 191, 219, 254),
                          max(1.0, 1.0 * s))
        # three dots hint that it opens into something
        dot = max(1.5, 1.6 * s)
        if sh > sw:
            for i in (-1, 0, 1):
                cy = y + sh / 2 + i * 4.6 * s
                surf.ellipse(x + sw / 2 - dot / 2, cy - dot / 2, dot, dot,
                             ARGB(min(255, alpha + 40), 255, 255, 255))
        else:
            for i in (-1, 0, 1):
                cx = x + sw / 2 + i * 4.6 * s
                surf.ellipse(cx - dot / 2, y + sh / 2 - dot / 2, dot, dot,
                             ARGB(min(255, alpha + 40), 255, 255, 255))

    # ---- hit --------------------------------------------------------------
    def hit(self, x: int, y: int) -> bool:
        p = self.pad()
        sw, sh = self.shape()
        lx, ly = x - p, y - p
        if self.is_bar():
            box = min(sw, sh) / 2.0
            return (-box * 0.4 <= lx <= sw + box * 0.4) and (-box * 0.4 <= ly <= sh + box * 0.4)
        cx, cy, r = sw / 2.0, sh / 2.0, sw / 2.0 + 1
        return (lx - cx) ** 2 + (ly - cy) ** 2 <= r * r

    # ---- messages ---------------------------------------------------------
    def on_message(self, hwnd, msg, wparam, lparam):
        if msg == win32.WM_LBUTTONDOWN:
            self.ui.ball_press()
            return 0
        if msg == win32.WM_LBUTTONUP:
            self.ui.ball_release()
            return 0
        if msg == win32.WM_RBUTTONUP:
            self.ui.open_settings(near_cursor=True)
            return 0
        if msg == win32.WM_MOUSEMOVE:
            if not self.hover:
                self.hover = True
                self.watch_mouse_leave()
                self.present()
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def on_mouse_leave(self) -> None:
        if self.hover:
            self.hover = False
            self.present()


# ---------------------------------------------------------------------menu
class Menu(Layered):
    CLASS = "SXSnapBallMenu"
    TITLE = "SXSnap 菜单"

    def __init__(self, ui: "BallUI") -> None:
        super().__init__()
        self.ui = ui
        self.items: list[tuple] = []
        self.hover = -1

    def scale(self) -> float:
        return dpi_scale(self.hwnd)

    def count(self) -> int:
        return max(1, len(self.items))

    def geometry(self) -> tuple[int, int]:
        s = self.scale()
        ww = (MENU_W + MENU_SHADOW * 2) * s
        hh = (MENU_PAD * 2 + self.count() * MENU_ICON
              + max(0, self.count() - 1) * MENU_GAP + MENU_SHADOW * 2) * s
        return (int(round(ww)), int(round(hh)))

    def note_h(self) -> int:
        s = self.scale()
        return int(round((MENU_PAD * 2 + self.count() * MENU_ICON
                          + max(0, self.count() - 1) * MENU_GAP) * s))

    def tile_box(self, i: int) -> tuple[float, float, float, float]:
        """The *icon* box of tile `i`, centred in the strip."""
        s = self.scale()
        x = (MENU_SHADOW + (MENU_W - MENU_ICON) / 2.0) * s
        y = (MENU_SHADOW + MENU_PAD + i * (MENU_ICON + MENU_GAP)) * s
        side = MENU_ICON * s
        return (x, y, side, side)

    def draw(self, surf: Surface) -> None:
        s = self.scale()
        x = MENU_SHADOW * s
        y = MENU_SHADOW * s
        ww = MENU_W * s
        hh = self.note_h()
        radius = ww / 2.0
        _shadow(surf, x, y, ww, hh, radius, s, layers=7, peak=20)
        surf.fill_round(x, y, ww, hh, radius, C_MENU_BG)
        surf.stroke_round(x, y, ww, hh, radius, C_MENU_EDGE, max(1.0, s))

        for i, item in enumerate(self.items):
            _key, glyph, has, on, _label = item
            bx, by, bs, _ = self.tile_box(i)
            if i == self.hover and has:
                pad = 5 * s
                surf.fill_round(bx - pad, by - pad, bs + pad * 2, bs + pad * 2,
                                11 * s, C_TILE_HOT)
            col = C_ICON if has and on else (C_ICON_OFF if has else C_ICON_DIM)
            if glyph == "gear":
                col = C_ICON
            cx = bx + bs / 2.0
            cy = by + bs / 2.0
            if glyph == "layout":
                # the layout glyph takes an accent fill for its main pane, so
                # "on" reads as a lit-up zone rather than just white strokes
                icons.layout(surf, cx, cy, bs, col, 1.7 * s,
                             pane=ARGB(110, 96, 165, 250) if (has and on) else None)
            else:
                icons.draw(surf, glyph, cx, cy, bs, col, 1.7 * s)
            if has and not on and glyph in ("camera", "microphone", "layout"):
                icons.slash(surf, cx, cy, bs * 1.05, ARGB(255, 248, 113, 113), 1.9 * s)

    def hit(self, x: int, y: int) -> bool:
        """Inside the stadium, not just inside its bounding box."""
        s = self.scale()
        x0, y0 = MENU_SHADOW * s, MENU_SHADOW * s
        ww, hh = MENU_W * s, self.note_h()
        if not (x0 - 2 <= x <= x0 + ww + 2 and y0 - 2 <= y <= y0 + hh + 2):
            return False
        r = ww / 2.0
        cx = x0 + r
        if y < y0 + r:                       # top cap
            return (x - cx) ** 2 + (y - (y0 + r)) ** 2 <= (r + 2) ** 2
        if y > y0 + hh - r:                  # bottom cap
            return (x - cx) ** 2 + (y - (y0 + hh - r)) ** 2 <= (r + 2) ** 2
        return True

    def index_at(self, x: int, y: int) -> int:
        """Tile under a point.  The hit box is the icon grown by half the gap,
        so the whole strip is clickable instead of only the glyphs."""
        s = self.scale()
        for i in range(len(self.items)):
            bx, by, bs, _ = self.tile_box(i)
            pad_x = (MENU_W / 2.0) * s
            half_gap = (MENU_GAP / 2.0 + 3) * s
            if (bx - pad_x / 2 <= x <= bx + bs + pad_x / 2
                    and by - half_gap <= y <= by + bs + half_gap):
                return i
        return -1

    def on_message(self, hwnd, msg, wparam, lparam):
        if msg == win32.WM_MOUSEMOVE:
            x = ctypes.c_short(lparam & 0xFFFF).value
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            i = self.index_at(x, y)
            if i != self.hover:
                self.hover = i
                self.present()
            self.watch_mouse_leave()
            return 0
        if msg == win32.WM_LBUTTONUP:
            x = ctypes.c_short(lparam & 0xFFFF).value
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            i = self.index_at(x, y)
            if i >= 0:
                self.ui.menu_click(i)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def on_mouse_leave(self) -> None:
        if self.hover != -1:
            self.hover = -1
            self.present()


# --------------------------------------------------------------------panel
class SettingsPanel(Layered):
    CLASS = "SXSnapSettings"
    TITLE = "SXSnap 设置"

    ROWS = (
        ("topmost", "始终置顶", "switch"),
        ("startup", "开机自动启动", "switch"),
        ("snap", "贴靠屏幕边缘", "switch"),
        ("hide", "隐藏悬浮球", "switch"),
        ("quit", "退出", "action"),
    )

    def __init__(self, ui: "BallUI") -> None:
        super().__init__()
        self.ui = ui
        self.hover = -1

    def scale(self) -> float:
        return dpi_scale(self.hwnd)

    def geometry(self) -> tuple[int, int]:
        s = self.scale()
        hh = (PANEL_HEAD + ROW_H * 4 + SEP_H + ACT_H + PANEL_PAD + PANEL_SHADOW * 2) * s
        return (int(round((PANEL_W + PANEL_SHADOW * 2) * s)), int(round(hh)))

    def _row_y(self, i: int) -> float:
        s = self.scale()
        y = PANEL_SHADOW + PANEL_HEAD + i * ROW_H
        if i == 4:
            y += SEP_H
        return y * s

    def _row_index_at(self, y: float) -> int:
        for i in range(len(self.ROWS)):
            top = self._row_y(i)
            if top <= y < top + ROW_H * self.scale():
                return i
        return -1

    def draw(self, surf: Surface) -> None:
        s = self.scale()
        x = PANEL_SHADOW * s
        y = PANEL_SHADOW * s
        ww = PANEL_W * s
        hh = (PANEL_HEAD + ROW_H * 4 + SEP_H + ACT_H + PANEL_PAD) * s
        _shadow(surf, x, y, ww, hh, 14 * s, s, layers=8, peak=26)
        surf.fill_round(x, y, ww, hh, 14 * s, C_PANEL_BG)
        surf.stroke_round(x, y, ww, hh, 14 * s, C_PANEL_EDGE, max(1.0, s))

        surf.text("设置", x + PANEL_PAD * s, y + 12 * s,
                  ww - PANEL_PAD * 2 * s, 22 * s, 15 * s, C_TEXT, bold=1,
                  align=StringAlignmentNear)

        for i, (key, label, kind) in enumerate(self.ROWS):
            ry = self._row_y(i)
            row_h = ROW_H * s
            if i == self.hover:
                surf.fill_round(x + 6 * s, ry + 2 * s, ww - 12 * s, row_h - 4 * s,
                                9 * s, C_ROW_HOT)
            if kind == "action":
                surf.line(x + PANEL_PAD * s, ry - SEP_H * s / 2 - 1,
                          x + ww - PANEL_PAD * s, ry - SEP_H * s / 2 - 1, C_SEP,
                          max(1.0, s))
                surf.text(label, x + PANEL_PAD * s, ry, ww - PANEL_PAD * 2 * s, row_h,
                          13.5 * s, C_DANGER, align=StringAlignmentNear)
                continue

            surf.text(label, x + PANEL_PAD * s, ry, ww - PANEL_PAD * 2 * s - SWITCH_W * s,
                      row_h, 13.5 * s, C_TEXT, align=StringAlignmentNear)

            on = bool(self.ui.value(key))
            sx = x + ww - PANEL_PAD * s - SWITCH_W * s
            sy = ry + (row_h - SWITCH_H * s) / 2
            surf.fill_round(sx, sy, SWITCH_W * s, SWITCH_H * s, SWITCH_H * s / 2,
                            C_TRACK_ON if on else C_TRACK_OFF)
            knob = (SWITCH_H - 4) * s
            kx = sx + (SWITCH_W * s - knob - 2 * s) if on else sx + 2 * s
            surf.ellipse(kx, sy + 2 * s, knob, knob, C_KNOB)

    def hit(self, x: int, y: int) -> bool:
        s = self.scale()
        x0, y0 = PANEL_SHADOW * s, PANEL_SHADOW * s
        ww = PANEL_W * s
        hh = (PANEL_HEAD + ROW_H * 4 + SEP_H + ACT_H + PANEL_PAD) * s
        return x0 <= x <= x0 + ww and y0 <= y <= y0 + hh

    def on_message(self, hwnd, msg, wparam, lparam):
        if msg == win32.WM_MOUSEMOVE:
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            i = self._row_index_at(y)
            if i != self.hover:
                self.hover = i
                self.present()
            self.watch_mouse_leave()
            return 0
        if msg == win32.WM_LBUTTONUP:
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            i = self._row_index_at(y)
            if i >= 0:
                self.ui.panel_click(self.ROWS[i][0])
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def on_mouse_leave(self) -> None:
        if self.hover != -1:
            self.hover = -1
            self.present()


# ------------------------------------------------------------------ controller
class BallUI:
    """Owns the three windows and the small state machine between them."""

    def __init__(self, cfg: dict, on_quit) -> None:
        self.cfg = cfg
        self.on_quit = on_quit
        self.ball = Ball(self)
        self.menu = Menu(self)
        self.panel = SettingsPanel(self)
        self.toast = Toast("")
        self._toast_until = 0.0

        self.docked = bool(cfg.get("ball_docked", False))
        self.edge = cfg.get("ball_edge", "right")
        self.pos_ball = (0, 0)          # visible rect of the disc
        self.pos_bar = (0, 0)           # visible rect of the docked bar
        self.dock_center = 0            # centre of the bar along its edge

        self._menu_shown = False
        self._panel_shown = False
        self._press: tuple | None = None
        self._dragging = False
        self._prev_down = False
        self._queue: list[tuple] = []
        self._quitting = False
        # the tray tooltip says whether the ball is hidden; App hooks this up
        self.on_state_change = None

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        for win in (self.ball, self.menu, self.panel, self.toast):
            win.create()
        self.apply_topmost()
        self.restore_position()

        if self.cfg.get("ball", True):
            self._show_ball()
        # a camera we turned off in a previous run must never be left off
        if self.cfg.get("camera_off_by_us"):
            self._spawn(self._restore_camera_bg)

    def hide_all(self) -> None:
        """Everything off screen, but the windows still exist.

        Used on the way out: the devices have to be restored first, and that
        can take a UAC prompt, so the UI must already be gone by then.
        """
        self._quitting = True
        self._menu_shown = False
        self._panel_shown = False
        for win in (self.menu, self.panel, self.toast, self.ball):
            try:
                win.hide()
            except Exception:
                pass

    def destroy(self) -> None:
        for win in (self.ball, self.menu, self.panel, self.toast):
            try:
                win.destroy()
            except Exception:
                pass

    def shutdown(self) -> None:
        """Restore the devices the user asked us to switch, then clean up."""
        self.hide_all()
        self.restore_devices()
        self.destroy()

    # ---------------------------------------------------------------- config
    def value(self, key: str):
        if key == "topmost":
            return self.cfg.get("ball_topmost", True)
        if key == "startup":
            return self.cfg.get("start_with_windows", False)
        if key == "snap":
            return self.cfg.get("ball_snap", True)
        if key == "hide":
            return not self.cfg.get("ball", True)     # switch on == hidden
        return False

    def menu_open(self) -> bool:
        return self._menu_shown

    def panel_open(self) -> bool:
        return self._panel_shown

    def _save(self) -> None:
        config.save(self.cfg)

    def _notify_state(self) -> None:
        if self.on_state_change is None:
            return
        try:
            self.on_state_change()
        except Exception:
            pass

    # --------------------------------------------------------------- geometry
    def scale(self) -> float:
        return max(1.0, dpi_scale(self.ball.hwnd)) if self.ball.hwnd else 1.0

    def _default_position(self) -> tuple[int, int]:
        mons = win32.enumerate_monitors()
        if not mons:
            return (400, 400)
        mon = next((m for m in mons if m.primary), mons[0])
        s = mon.dpi / 96.0
        d = int(round(BALL_D * s))
        margin = int(round(22 * s))
        wl, wt, wr, wb = mon.work
        return (wr - d - margin, wb - d - margin)

    def restore_position(self) -> None:
        x, y = self.cfg.get("ball_x"), self.cfg.get("ball_y")
        d = int(round(BALL_D * self.scale()))
        if isinstance(x, int) and isinstance(y, int):
            if monitor_at((x + d // 2, y + d // 2)) is not None:
                self.pos_ball = (x, y)
                if self.docked:
                    self._compute_dock(self.pos_ball[0] + d // 2,
                                       self.pos_ball[1] + d // 2)
                return
        self.docked = bool(self.cfg.get("ball_docked", False))
        self.pos_ball = self._default_position()
        if self.docked:
            self._compute_dock(self.pos_ball[0] + d // 2, self.pos_ball[1] + d // 2)

    def _show_ball(self) -> None:
        if not self.cfg.get("ball", True):
            self.ball.hide()
            return
        self.ball.place_visible(*(self.pos_bar if self.docked else self.pos_ball))
        self.ball.show()

    def _expanded_ball_position(self) -> None:
        """Where the disc sits while it is popped out of a docked bar.

        Inward from the sliver, aligned with its centre, and clear of it - the
        bar is only 7 DIP thick, so without the offset the disc would sit on top
        of the thing that was just clicked.
        """
        s = self.scale()
        d = int(round(BALL_D * s))
        thick = int(round(BAR_W * s))
        span = int(round(BAR_H * s))
        gap = int(round(4 * s))
        mon = monitor_at((self.pos_bar[0] + 1, self.pos_bar[1] + 1))
        if mon is None:
            return
        wl, wt, wr, wb = mon.work
        bx, by = self.pos_bar

        if self.edge == "left":
            self.pos_ball = (wl + thick + gap, by + (span - d) // 2)
        elif self.edge == "right":
            self.pos_ball = (wr - thick - gap - d, by + (span - d) // 2)
        elif self.edge == "top":
            self.pos_ball = (bx + (span - d) // 2, wt + thick + gap)
        else:
            self.pos_ball = (bx + (span - d) // 2, wb - thick - gap - d)

    # ------------------------------------------------------------------ dock
    def _compute_dock(self, cx: int, cy: int) -> None:
        s = self.scale()
        mon = monitor_at((cx, cy))
        if mon is None:
            self.docked = False
            return
        wl, wt, wr, wb = mon.work
        dists = {
            "left": cx - wl,
            "right": wr - cx,
            "top": cy - wt,
            "bottom": wb - cy,
        }
        self.edge = min(dists, key=dists.get)
        barw = int(round(BAR_W * s))
        barh = int(round(BAR_H * s))
        if self.edge in ("left", "right"):
            y = cy - barh // 2
            y = max(wt + 2, min(y, wb - barh - 2))
            x = wl if self.edge == "left" else wr - barw
            self.pos_bar = (int(x), int(y))
            self.dock_center = y
        else:
            x = cx - barh // 2
            x = max(wl + 2, min(x, wr - barh - 2))
            y = wt if self.edge == "top" else wb - barw
            self.pos_bar = (int(x), int(y))
            self.dock_center = x

    # --------------------------------------------------------------- actions
    def near_edge(self) -> bool:
        """Was the ball left *on* a screen edge?

        Docking used to happen on every drop, which meant the disc turned into
        the sliver no matter where it was released - and then there was no way
        back to a free-floating ball.  Now it only snaps when it is actually
        parked against an edge (or overlapping one, which the drag clamp
        allows); anywhere else it simply stays where it was dropped.
        """
        sw, sh = self.ball.shape()
        x, y = self.pos_ball
        # the centre, not the corner: a ball straddling the bezel belongs to
        # whichever display most of it is on, and near a shared edge the two
        # work areas disagree about where "the" edge is
        mon = monitor_at((x + sw // 2, y + sh // 2))
        if mon is None:
            return False
        wl, wt, wr, wb = mon.work
        gaps = (x - wl, wr - (x + sw), y - wt, wb - (y + sh))
        return min(gaps) <= SNAP_TOL * self.scale()

    def undock(self) -> None:
        """Turn the sliver back into a normal disc, just inside the edge.

        This is what a click on the sliver does, and it sticks: `ball_docked`
        goes false, so the ball stays a ball and can be dragged anywhere.
        """
        if not self.docked:
            return
        self._expanded_ball_position()
        self.docked = False
        self.cfg["ball_docked"] = False
        self.cfg["ball_x"], self.cfg["ball_y"] = self.pos_ball
        self._save()
        self._show_ball()

    def apply_topmost(self) -> None:
        on = bool(self.cfg.get("ball_topmost", True))
        for win in (self.ball, self.menu, self.panel, self.toast):
            win.set_topmost(on)

    def _inside(self, pt) -> bool:
        """Is the point on one of *our visible* windows?

        A hidden window keeps its last rect, so checking geometry alone made a
        once-used settings panel swallow every outside click - which read as
        "the menu never closes".
        """
        for win in (self.ball, self.menu, self.panel):
            if not win.hwnd or not win.shown:
                continue
            x0, y0, x1, y1 = win.screen_rect()
            if x0 - 2 <= pt[0] <= x1 + 2 and y0 - 2 <= pt[1] <= y1 + 2:
                return True
        return False

    # ---- ball press / drag ------------------------------------------------
    def ball_press(self) -> None:
        if self._menu_shown or self._panel_shown:
            self.close_menu()
            self.close_panel()
            self._press = None
            return
        pt = win32.cursor_pos()
        self._press = (pt[0], pt[1], self.ball.pos[0], self.ball.pos[1])
        self._dragging = False

    def ball_release(self) -> None:
        # one path for "the button came up", whether the message arrives or the
        # tick watchdog notices first - `_end_press` is idempotent
        self._end_press()

    def _drag_to(self, window_x: int, window_y: int) -> None:
        s = self.scale()
        pad = self.ball.pad()
        d = int(round(BALL_D * s))
        vx = window_x + pad
        vy = window_y + pad
        mon = monitor_at((vx + d // 2, vy + d // 2))
        if mon is not None:
            wl, wt, wr, wb = mon.work
            vx = max(wl - d // 4, min(vx, wr - d // 4))
            vy = max(wt, min(vy, wb - d))
        self.pos_ball = (vx, vy)
        self.ball.place_visible(vx, vy)
        self.ball.present()

    def _end_press(self) -> None:
        pressed, self._press = self._press, None
        if pressed is None:
            return

        if not self._dragging:
            # a click: on the sliver it means "come back out as a disc"
            if self.docked:
                self.undock()
            self._toggle_menu()
            return

        self._dragging = False
        s = self.scale()
        d = int(round(BALL_D * s))

        if self.docked:
            # dragged by the sliver: grow back into a disc around its centre
            sw, sh = self.ball.shape()
            self.pos_ball = (self.pos_ball[0] + sw // 2 - d // 2,
                             self.pos_ball[1] + sh // 2 - d // 2)
            self.docked = False

        if self.cfg.get("ball_snap", True) and self.near_edge():
            self._compute_dock(self.pos_ball[0] + d // 2, self.pos_ball[1] + d // 2)
            self.docked = True
        else:
            self.docked = False

        self.cfg["ball_docked"] = self.docked
        self.cfg["ball_edge"] = self.edge
        self.cfg["ball_x"], self.cfg["ball_y"] = self.pos_ball
        self._save()
        self._show_ball()

    # ---- menu -------------------------------------------------------------
    def _toggle_menu(self) -> None:
        if self._menu_shown:
            self.close_menu()
        else:
            self.open_menu()

    def open_menu(self) -> None:
        self.close_panel()
        self.menu.items = self._menu_items()
        self.menu.hover = -1
        self.menu.set_topmost(bool(self.cfg.get("ball_topmost", True)))
        self._menu_shown = True
        self._show_ball()                 # a docked bar pops out into the disc
        s = self.scale()
        gw, gh = self.menu.geometry()
        bx0, by0, bx1, by1 = self.ball.visible_rect()
        cx = (bx0 + bx1) // 2
        x = cx - gw // 2
        y = by0 - gh + int(round(MENU_SHADOW * s)) - int(round(MENU_OFFSET * s))
        mon = monitor_at((cx, by0)) or monitor_at((cx, by1))
        if mon is not None:
            wl, wt, wr, wb = mon.work
            if y < wt:
                y = by1 - int(round(MENU_SHADOW * s)) + int(round(MENU_OFFSET * s))
            x = max(wl, min(x, wr - gw))
            y = max(wt, min(y, wb - gh))
        self.menu.place(int(x), int(y))
        self.menu.show()
        self._show_ball()

    def close_menu(self) -> None:
        if not self._menu_shown:
            return
        self._menu_shown = False
        self.menu.hide()
        self._show_ball()

    def _menu_items(self) -> list[tuple]:
        has_mic, mic_on = devices.mic_on()
        has_cam, cam_on = devices.camera_on()
        return [
            ("camera", "camera", has_cam, cam_on, "摄像头"),
            ("mic", "microphone", has_mic, mic_on, "麦克风"),
            ("layout", "layout", True, bool(self.cfg.get("enabled", True)), "窗口布局"),
            ("settings", "gear", True, True, "设置"),
        ]

    def menu_click(self, index: int) -> None:
        if not (0 <= index < len(self.menu.items)):
            return
        key = self.menu.items[index][0]
        if key == "settings":
            self.close_menu()
            self.open_settings()
            return
        if key == "camera":
            self.close_menu()
            self.toggle_camera()
            return
        if key == "mic":
            self.close_menu()
            self.toggle_mic()
            return
        if key == "layout":
            self.close_menu()
            self.toggle_layout()
            return

    # ---- device switches --------------------------------------------------
    def toggle_layout(self) -> None:
        on = not bool(self.cfg.get("enabled", True))
        self.cfg["enabled"] = on
        self._save()
        self._notify_state()
        self.toast_show("布局管理器已开启" if on else "布局管理器已关闭")

    def toggle_mic(self) -> None:
        has, on = devices.mic_on()
        if not has:
            self.toast_show("未检测到麦克风设备")
            return
        if not devices.mic_set(not on):
            self.toast_show("麦克风状态切换失败")
            return
        muted = on            # it was on, so it is now muted
        self.cfg["mic_muted_by_us"] = muted
        self._save()
        self.toast_show("麦克风已静音" if muted else "麦克风已开启")

    def toggle_camera(self) -> None:
        has, on = devices.camera_on()
        if not has:
            self.toast_show("未检测到摄像头设备")
            return
        want = not on
        if want:
            self.toast_show("正在开启摄像头…")
        else:
            self.toast_show("正在关闭摄像头…")
        self._spawn(lambda: self._camera_worker(want))

    def _camera_worker(self, want: bool) -> None:
        if devices.is_admin():
            ok, msg = devices.camera_set_all(want)
        else:
            ok, msg = devices.camera_set_elevated(want)
        self._queue.append(("camera", ok, msg, want))

    def _restore_camera_bg(self) -> None:
        if devices.is_admin():
            ok, _msg = devices.camera_set_all(True)
        else:
            ok, _msg = devices.camera_set_elevated(True)
        self._queue.append(("camera-restore", ok, "", True))

    def restore_devices(self) -> None:
        """Put the camera and the microphone back the way most people want them."""
        if self.cfg.get("mic_muted_by_us"):
            if devices.mic_set(True):
                self.cfg["mic_muted_by_us"] = False
        if self.cfg.get("camera_off_by_us"):
            if devices.is_admin():
                ok, _msg = devices.camera_set_all(True)
            else:
                ok, _msg = devices.camera_set_elevated(True)
            if ok:
                self.cfg["camera_off_by_us"] = False
        self._save()

    def _spawn(self, fn) -> None:
        import threading
        t = threading.Thread(target=fn, daemon=True)
        t.start()

    # ---- settings ---------------------------------------------------------
    def open_settings(self, near_cursor: bool = False) -> None:
        self.close_menu()
        self.panel.hover = -1
        self.panel.set_topmost(bool(self.cfg.get("ball_topmost", True)))
        self._panel_shown = True
        if self.cfg.get("ball", True):
            self._show_ball()
        gw, gh = self.panel.geometry()
        s = self.scale()
        pad = int(round(PANEL_SHADOW * s))
        mon = None
        if near_cursor or not self.cfg.get("ball", True):
            pt = win32.cursor_pos()
            mon = monitor_at(pt)
            x = pt[0] - gw // 2
            y = pt[1] - gh - 12
            if y < (mon.work[1] if mon else 0):
                y = pt[1] + 12
        else:
            bx0, by0, bx1, by1 = self.ball.visible_rect()
            cx, cy = (bx0 + bx1) // 2, (by0 + by1) // 2
            mon = monitor_at((cx, cy))
            x = bx0 - gw + pad * 2
            y = cy - gh // 2
        if mon is not None:
            wl, wt, wr, wb = mon.work
            if x + gw > wr:
                x = wr - gw
            x = max(wl, x)
            y = max(wt, min(y, wb - gh))
        self.panel.place(int(x), int(y))
        self.panel.show()

    def close_panel(self) -> None:
        if not self._panel_shown:
            return
        self._panel_shown = False
        self.panel.hide()
        self._show_ball()

    def panel_click(self, key: str) -> None:
        if key == "topmost":
            self.cfg["ball_topmost"] = not bool(self.cfg.get("ball_topmost", True))
            self._save()
            self.apply_topmost()
            self.panel.present()
            return
        if key == "startup":
            on = not bool(self.cfg.get("start_with_windows", False))
            self.cfg["start_with_windows"] = on
            self._save()
            config.set_startup(on)
            self.panel.present()
            self.toast_show("已设为开机自启动" if on else "已取消开机自启动")
            return
        if key == "snap":
            on = not bool(self.cfg.get("ball_snap", True))
            self.cfg["ball_snap"] = on
            self._save()
            if not on and self.docked:
                # stay exactly where it is, just stop being a sliver
                self.undock()
            self.panel.present()
            self.toast_show("拖到屏幕边缘会贴靠" if on else "悬浮球可自由摆放")
            return
        if key == "hide":
            # a switch, not a one-way door: this used to only ever hide, which
            # left the ball gone with no way back from inside the panel
            visible = bool(self.cfg.get("ball", True))
            self.set_visible(not visible)
            if visible:
                self.toast_show("悬浮球已隐藏，可用托盘图标恢复")
            else:
                self.panel.present()
                self.toast_show("悬浮球已显示")
            return
        if key == "quit":
            self.close_panel()
            if self.on_quit:
                self.on_quit()

    # ---- tray entry points ------------------------------------------------
    def set_visible(self, on: bool) -> None:
        self.cfg["ball"] = on
        self._save()
        self._notify_state()
        if on:
            self.restore_position()
            self._show_ball()
        else:
            self.close_menu()
            self.close_panel()
            self.ball.hide()

    def toggle_visible(self) -> None:
        self.set_visible(not bool(self.cfg.get("ball", True)))

    # ---- toast ------------------------------------------------------------
    def toast_show(self, text: str) -> None:
        if not text:
            return
        self.toast.text = text
        s = self.scale()
        gw, gh = self.toast.geometry()
        anchor = self.ball.visible_rect() if self.cfg.get("ball", True) else None
        if anchor is None:
            pt = win32.cursor_pos()
            x, y = pt[0] - gw // 2, pt[1] - gh - 10
        else:
            x = (anchor[0] + anchor[2]) // 2 - gw // 2
            y = anchor[1] - gh + int(round(BALL_PAD * s))
        mon = monitor_at((x + gw // 2, y + gh // 2)) or monitor_at((x, y))
        if mon is not None:
            wl, wt, wr, wb = mon.work
            x = max(wl, min(x, wr - gw))
            y = max(wt, min(y, wb - gh))
        self.toast.show_for(int(x), int(y))
        self._toast_until = time.monotonic() + Toast.HOLD_MS / 1000.0 + 0.1

    # ---- per-tick ---------------------------------------------------------
    def tick(self) -> None:
        self._drain()
        if self._quitting:
            return
        pt = win32.cursor_pos()
        down = win32.left_button_down()

        if self._press is not None:
            if down:
                dx = pt[0] - self._press[0]
                dy = pt[1] - self._press[1]
                if (not self._dragging
                        and max(abs(dx), abs(dy)) > DRAG_SLOP * self.scale()):
                    self._dragging = True
                    self.close_menu()
                    self.close_panel()
                if self._dragging:
                    self._drag_to(self._press[2] + dx, self._press[3] + dy)
            else:
                self._end_press()
            self._prev_down = down
        else:
            if down and not self._prev_down and (self._menu_shown or self._panel_shown):
                if not self._inside(pt):
                    self.close_menu()
                    self.close_panel()
            self._prev_down = down

        if self._toast_until and time.monotonic() > self._toast_until:
            self._toast_until = 0.0
            self.toast.hide()

    def _drain(self) -> None:
        while self._queue:
            item = self._queue.pop(0)
            kind = item[0]
            if kind == "camera":
                _, ok, msg, want = item
                if ok:
                    self.cfg["camera_off_by_us"] = not want
                    self._save()
                    self.toast_show("摄像头已开启" if want else "摄像头已关闭")
                else:
                    self.toast_show(msg)
            elif kind == "camera-restore":
                _, ok, _msg, _want = item
                if ok:
                    self.cfg["camera_off_by_us"] = False
                    self._save()

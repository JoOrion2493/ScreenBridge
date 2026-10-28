"""SXSnap - the ASUS App Navigator popup, rebuilt for any PC.

Drag any window by its title bar: a panel opens under the cursor showing one
chip per display.  Rest on a chip and its layout presets unfold; rest on a
zone inside a preset and release - the window lands exactly there.  Release on
a chip instead and the whole window jumps to that display.

A floating ball sits in the corner of the screen.  Click it for the vertical
bar: camera, microphone, the layout manager, settings - and 退出 puts the
camera and the microphone back on before it goes.

Detection is a resident poll of GetCursorPos plus "did the dragged window's
frame actually follow the cursor", not SetWinEventHook: MOVESIZESTART arrives
only after the shell has committed to the move loop, which measured 400 ms+
late on this machine - long enough for the panel to miss the whole gesture.
The poll catches it in under 60 ms and cannot drop an event.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import os
import sys
import threading
import traceback

from . import anim, config, devices, engine, win32, zones
from .ball import BallUI
from .palette import Palette

ERROR_ALREADY_EXISTS = 183
IDI_APPLICATION = 32512
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040
MB_ICONINFORMATION = 0x40
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
VK_Q = 0x51
WM_QUIT_NOW = win32.WM_APP + 9

TICK_ID = 1
TICK_MS = 30          # resident cadence; the drag state machine runs on this
SETTLE_MS = 60        # let the move loop finish before we snap the window

# tray menu command ids
TRAY_BALL = 1
TRAY_DRAG = 2
TRAY_SETTINGS = 3
TRAY_QUIT = 4

win32.user32.LoadIconW.argtypes = [w.HINSTANCE, ctypes.c_void_p]
win32.user32.LoadIconW.restype = w.HICON

win32.user32.LoadImageW.argtypes = [
    w.HINSTANCE, w.LPCWSTR, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_uint
]
win32.user32.LoadImageW.restype = w.HANDLE

win32.user32.MessageBoxW.argtypes = [w.HWND, w.LPCWSTR, w.LPCWSTR, ctypes.c_uint]
win32.user32.MessageBoxW.restype = ctypes.c_int

win32.kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, w.BOOL, w.LPCWSTR]
win32.kernel32.CreateMutexW.restype = w.HANDLE

win32.user32.WindowFromPoint.argtypes = [w.POINT]
win32.user32.WindowFromPoint.restype = w.HWND


def _error_log(msg: str) -> None:
    try:
        os.makedirs(config.config_dir(), exist_ok=True)
        with open(os.path.join(config.config_dir(), "error.log"), "a", encoding="utf-8") as fh:
            fh.write(msg + "\n")
    except OSError:
        pass


def _dbg(msg: str) -> None:
    """Gesture-trace logging, on only when SX_DEBUG is set (harness runs)."""
    if not os.environ.get("SX_DEBUG"):
        return
    try:
        with open(os.path.join(config.config_dir(), "debug.log"), "a",
                  encoding="utf-8") as fh:
            fh.write(msg + "\n")
    except OSError:
        pass


def _app_icon() -> int:
    """The shipped brand icon, or the stock one if it is missing."""
    cands = []
    base = getattr(sys, "_MEIPASS", None)
    if base:
        cands.append(os.path.join(base, "sxsnap.ico"))
    if getattr(sys, "frozen", False):
        cands.append(os.path.join(os.path.dirname(sys.executable), "sxsnap.ico"))
    cands.append(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sxsnap.ico"))

    for path in cands:
        if os.path.exists(path):
            h = win32.user32.LoadImageW(
                None, path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if h:
                return h
    return win32.user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))


def wants_travel(start, target, cfg: dict) -> bool:
    """Animate this landing?

    Only when the window is crossing to another display.  A same-display move
    is a plain snap - the user already told us where the window goes, and
    watching it ease into place reads as lag rather than as polish.
    """
    if not cfg.get("animate", True):
        return False
    try:
        return anim.crosses_display(start, target)
    except Exception:
        return False


class App:
    def __init__(self) -> None:
        self.cfg = config.load()
        self.pal = Palette()
        self.ball = BallUI(self.cfg, self.request_quit)
        self.hwnd = 0

        self.tracking = False
        self.moved = False
        self.cancelled = False
        self.drag_hwnd = 0
        self.drag_origin: tuple[int, int, int, int] | None = None
        self._icon = 0
        self._owner = 0
        self._quitting = False
        self._owner_proc = win32.WNDPROC(self._owner_wnd_proc)

    def _owner_wnd_proc(self, hwnd, msg, wp, lp):
        handled = self._on_message(hwnd, msg, wp, lp)
        if handled is not None:
            return handled
        return win32.user32.DefWindowProcW(hwnd, msg, wp, lp)

    # ---------------------------------------------------------- palette size
    def _set_palette_size(self, name: str) -> None:
        """Apply the size the user picked in the settings panel."""
        self.pal.size = name
        self.cfg["palette_size"] = name
        config.save(self.cfg)
        if self.pal.active:
            # redraw the open palette in the new size straight away
            self.pal.begin(win32.cursor_pos())

    # ------------------------------------------------------------------ tray
    def _tip(self) -> str:
        if not self.cfg.get("ball", True):
            return "SXSnap · 悬浮球已隐藏（双击恢复）"
        state = "已启用" if self.cfg.get("enabled", True) else "已暂停"
        return f"SXSnap · {state} · 拖动标题栏选布局"

    def _install_tray(self, action: int) -> None:
        if not self._owner:
            return
        if not self._icon:
            self._icon = _app_icon()
        nid = win32.NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(win32.NOTIFYICONDATAW)
        nid.hWnd = self._owner          # the owner window routes messages back to us
        nid.uID = 1
        nid.uFlags = win32.NIF_MESSAGE | win32.NIF_ICON | win32.NIF_TIP
        nid.uCallbackMessage = win32.WM_TRAYICON
        nid.hIcon = self._icon
        nid.szTip = self._tip()
        win32.shell32.Shell_NotifyIconW(action, ctypes.byref(nid))

    def _tray_menu(self) -> None:
        """The classic Win32 context menu, not one of our dark panels.

        A tray menu is the one place where the system look is the right answer:
        users know how it behaves, and it brings keyboard navigation, the
        drop shadow and click-outside dismissal without any code from us.
        """
        u = win32.user32
        menu = u.CreatePopupMenu()
        if not menu:
            return
        visible = bool(self.cfg.get("ball", True))
        dragging = bool(self.cfg.get("enabled", True))

        u.AppendMenuW(menu, win32.MF_STRING | (win32.MF_CHECKED if visible else 0),
                      TRAY_BALL, "显示悬浮球")
        u.AppendMenuW(menu, win32.MF_STRING | (win32.MF_CHECKED if dragging else 0),
                      TRAY_DRAG, "拖动标题栏选择布局")
        u.AppendMenuW(menu, win32.MF_SEPARATOR, 0, None)
        u.AppendMenuW(menu, win32.MF_STRING, TRAY_SETTINGS, "设置…")
        u.AppendMenuW(menu, win32.MF_SEPARATOR, 0, None)
        u.AppendMenuW(menu, win32.MF_STRING, TRAY_QUIT, "退出")

        pt = win32.cursor_pos()
        # the owner must be foreground or the menu will not close when the user
        # clicks elsewhere; the trailing WM_NULL is the documented dance
        u.SetForegroundWindow(self._owner)
        cmd = u.TrackPopupMenu(
            menu, win32.TPM_RIGHTBUTTON | win32.TPM_RETURNCMD | win32.TPM_NONOTIFY,
            pt[0], pt[1], 0, self._owner, None)
        u.DestroyMenu(menu)
        u.PostMessageW(self._owner, win32.WM_NULL, 0, 0)

        if cmd == TRAY_BALL:
            self.ball.toggle_visible()
            self._install_tray(win32.NIM_MODIFY)
        elif cmd == TRAY_DRAG:
            self.cfg["enabled"] = not dragging
            config.save(self.cfg)
            self._install_tray(win32.NIM_MODIFY)
            self.ball.toast_show("布局管理器已开启" if self.cfg["enabled"] else "布局管理器已关闭")
        elif cmd == TRAY_SETTINGS:
            self.ball.open_settings(near_cursor=True)
        elif cmd == TRAY_QUIT:
            self.request_quit()

    # -------------------------------------------------------------- tracking
    def _acquire(self, x: int, y: int) -> None:
        """Remember the window under the cursor when the button goes down."""
        hwnd = win32.window_from_point(x, y)
        _dbg(f"acquire: pt=({x},{y}) hwnd={hwnd} snappable="
             f"{engine.is_snappable(hwnd) if hwnd else None}")
        if not hwnd or hwnd == self.hwnd:
            return
        if not engine.is_snappable(hwnd):
            return

        self.tracking = True
        self.moved = False
        self.cancelled = False
        self.drag_hwnd = hwnd
        self.drag_origin = win32.window_rect(hwnd)
        # a leftover animation from the previous gesture must not fight this one
        anim.CANCEL.set()

    def _finish(self) -> None:
        if not self.tracking:
            return
        self.tracking = False

        action = None if self.cancelled else self.pal.resolve()
        _dbg(f"finish: cursor={win32.cursor_pos()} action={action} "
             f"stage={self.pal.stage} hover_chip={self.pal.hover_chip} "
             f"hover_layout={self.pal.hover_layout} hover_zone={self.pal.hover_zone} "
             f"sel_mon={self.pal.sel_mon} origin={self.pal.origin} "
             f"chips={[(round(a),round(b),round(c),round(d)) for a,b,c,d in self.pal.metrics()['chips']]}")
        self.pal.end()

        hwnd = self.drag_hwnd
        self.drag_hwnd = 0
        self.drag_origin = None
        self.moved = False
        self.cancelled = False

        if not (action and hwnd):
            return
        # The move loop is still unwinding; snapping straight away gets undone
        # by the window's own WM_EXITSIZEMOVE handler.
        timer = threading.Timer(SETTLE_MS / 1000.0, self._apply, (hwnd, action))
        timer.daemon = True
        timer.start()

    def _apply(self, hwnd: int, action) -> None:
        try:
            place = self._place_target
            if action[0] == "zone":
                _, mi, li, zi = action
                if not (0 <= mi < len(self.pal.monitors)):
                    return
                mon = self.pal.monitors[mi]
                lid = zones.LAYOUT_IDS[li]
                rects = zones.zones_for(
                    mon, lid, int(self.cfg.get("gap", 8)), int(self.cfg.get("margin", 0)))
                if place(hwnd, rects[zi]):
                    self.cfg["layout"] = lid
                    config.save(self.cfg)
            elif action[0] == "screen":
                mi = action[1]
                if not (0 <= mi < len(self.pal.monitors)):
                    return
                target = engine.target_on_monitor(hwnd, self.pal.monitors[mi])
                if target is not None:
                    place(hwnd, target)
        except Exception:
            _error_log("apply:\n" + traceback.format_exc())

    def _place_target(self, hwnd: int, rect) -> bool:
        """Land the window on `rect`."""
        if not win32.user32.IsWindow(hwnd):
            return False
        if wants_travel(engine.visible_rect(hwnd), rect, self.cfg):
            return anim.animate_to(
                hwnd, rect, ms=int(self.cfg.get("anim_travel_ms", anim.TRAVEL_MS)))
        return engine.place_visible(hwnd, rect)

    # ------------------------------------------------------------------- tick
    def _on_tick(self) -> None:
        try:
            self.ball.tick()
            if not self.cfg.get("enabled", True):
                if self.tracking:
                    self.tracking = False
                    self.pal.end()
                return

            x, y = win32.cursor_pos()
            down = win32.left_button_down()

            if not self.tracking:
                if down:
                    self._acquire(x, y)
                return

            if not down:
                self._finish()
                return

            if not self.moved:
                if not win32.user32.IsWindow(self.drag_hwnd):
                    self.tracking = False
                    return
                cur = win32.window_rect(self.drag_hwnd)
                org = self.drag_origin
                if abs(cur[0] - org[0]) > 2 or abs(cur[1] - org[1]) > 2:
                    _dbg(f"moved: hwnd={self.drag_hwnd} cur={cur} org={org} "
                         f"sizing={engine.is_sizing(self.drag_hwnd)}")
                    self.moved = True
                    # a border resize must not summon the palette
                    if engine.is_sizing(self.drag_hwnd):
                        self.cancelled = True
                        return
                    self.pal.gap = int(self.cfg.get("gap", 8))
                    self.pal.margin = int(self.cfg.get("margin", 0))
                    self.pal.begin((x, y))
                else:
                    return

            if self.cancelled:
                return

            if win32.user32.GetAsyncKeyState(win32.VK_ESCAPE) & 0x8000:
                self.cancelled = True
                self.pal.end()
                return

            if self.pal.active:
                self.pal.update((x, y))
        except Exception:
            _error_log("tick:\n" + traceback.format_exc())

    # --------------------------------------------------------------- messages
    def _on_message(self, hwnd, msg, wp, lp):
        if msg == win32.WM_TRAYICON:
            m = lp & 0xFFFF
            if m == WM_LBUTTONDBLCLK:
                # the quickest way back when the ball was hidden
                self.ball.toggle_visible()
                self._install_tray(win32.NIM_MODIFY)
                return 0
            if m == WM_RBUTTONUP:
                self._tray_menu()
                return 0
            return 0
        if msg == win32.WM_HOTKEY:
            self.request_quit()
            return 0
        if msg == WM_QUIT_NOW:
            win32.user32.PostQuitMessage(0)
            return 0
        if msg == win32.WM_DISPLAYCHANGE:
            # a saved ball position may now be off-screen
            try:
                self.ball.restore_position()
                if self.cfg.get("ball", True):
                    self.ball._show_ball()
            except Exception:
                _error_log("displaychange:\n" + traceback.format_exc())
            return 0
        if msg == win32.WM_TIMER:
            self._on_tick()
            return 0
        return None

    # ------------------------------------------------------------------ quit
    def request_quit(self) -> None:
        """Close down, but put the camera and microphone back first.

        Restoring the camera can raise a UAC prompt, so the UI is cleared
        immediately and the restore runs on a worker; it pings the owner window
        when it is done so the message loop exits on the right thread.
        """
        if self._quitting:
            return
        self._quitting = True
        try:
            self.ball.hide_all()
        except Exception:
            _error_log("quit-hide:\n" + traceback.format_exc())
        threading.Thread(target=self._quit_worker, daemon=True).start()

    def _quit_worker(self) -> None:
        try:
            self.ball.restore_devices()
        except Exception:
            _error_log("quit-restore:\n" + traceback.format_exc())
        try:
            win32.user32.PostMessageW(self._owner, WM_QUIT_NOW, 0, 0)
        except Exception:
            pass

    # ------------------------------------------------------------------- main
    def run(self) -> int:
        mode = win32.enable_dpi_awareness()

        self._mutex = win32.kernel32.CreateMutexW(None, False, "Local\\SXSnap_Singleton")
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            return 0

        self.pal.create()
        self.hwnd = self.pal.hwnd
        self.pal.dwell_ms = int(self.cfg.get("dwell_ms", 90))
        self.pal.size = self.cfg.get("palette_size", "large")
        # route WM_TIMER/WM_TRAYICON through a tiny hidden owner window so the
        # palette stays a purely visual, click-through surface
        self._owner = self._make_owner()
        self.ball.on_state_change = lambda: self._install_tray(win32.NIM_MODIFY)
        # the size picker in the settings panel changes the palette right away
        self.ball.on_palette_size = self._set_palette_size
        self.ball.start()

        self._install_tray(win32.NIM_ADD)
        win32.user32.RegisterHotKey(
            self._owner, 1, win32.MOD_CONTROL | win32.MOD_ALT | win32.MOD_SHIFT, VK_Q)
        win32.user32.SetTimer(self._owner, TICK_ID, TICK_MS, None)

        if not self.cfg.get("first_run_done", False):
            ctypes.windll.user32.MessageBoxW(
                None,
                "SXSnap 已在后台运行。\n\n"
                "【悬浮球】屏幕角落的圆形图标，点一下展开图标栏：\n"
                "  摄像头 / 麦克风 / 布局管理器 / 设置\n"
                "  拖动它可以换位置；靠近屏幕边缘会收成一条蓝色短条，\n"
                "  再点一下就展开。退出时会自动把摄像头和麦克风恢复开启。\n\n"
                "【窗口布局】按住任意窗口的标题栏拖动，鼠标下方会弹出面板：\n"
                "  1. 一排屏幕图标，每个代表一块显示器\n"
                "  2. 鼠标移到某个屏幕上，它下面会展开预设布局\n"
                "  3. 移到某个布局的某一格上松手，窗口就落到那一格\n"
                "  4. 直接在某块屏幕上松手，整个窗口搬到那块屏（保持大小）\n"
                "  5. 按 ESC 取消\n\n"
                f"DPI: {mode}   显示器: {len(win32.enumerate_monitors())} 块\n\n"
                "托盘图标：双击 显示/隐藏悬浮球，右键 设置。\n"
                "热键 Ctrl+Alt+Shift+Q 退出。",
                "SXSnap",
                MB_ICONINFORMATION,
            )
            self.cfg["first_run_done"] = True
            config.save(self.cfg)

        msg = w.MSG()
        while True:
            r = win32.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r <= 0:
                break
            win32.user32.TranslateMessage(ctypes.byref(msg))
            win32.user32.DispatchMessageW(ctypes.byref(msg))

        win32.user32.KillTimer(self._owner, TICK_ID)
        self._install_tray(win32.NIM_DELETE)
        win32.user32.UnregisterHotKey(self._owner, 1)
        win32.user32.DestroyWindow(self._owner)
        self.ball.destroy()
        self.pal.destroy()
        return 0

    def _make_owner(self) -> int:
        """A 0x0 hidden window that owns the tray icon, hotkey and timer."""
        hinst = win32.kernel32.GetModuleHandleW(None)
        cls = "SXSnapOwner"

        wc = win32.WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(win32.WNDCLASSEXW)
        wc.lpfnWndProc = ctypes.cast(self._owner_proc, ctypes.c_void_p)
        wc.hInstance = hinst
        wc.lpszClassName = cls
        win32.user32.RegisterClassExW(ctypes.byref(wc))

        hwnd = win32.user32.CreateWindowExW(
            win32.WS_EX_TOOLWINDOW, cls, "SXSnap", win32.WS_POPUP,
            0, 0, 0, 0, None, None, hinst, None,
        )
        if not hwnd:
            raise OSError(f"owner window failed ({ctypes.get_last_error()})")
        return hwnd


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)

    # ---- elevated one-shot: switch the camera and get out -----------------
    # The resident process stays at normal rights; this branch is what it
    # launches with "runas" when the camera button is pressed.  The flag is
    # searched for rather than indexed: whether argv still carries the program
    # name depends on the entry point, and getting that wrong would silently
    # start a second resident instance instead of switching the camera.
    if devices.CAMERA_FLAG in argv:
        pos = argv.index(devices.CAMERA_FLAG)
        on = len(argv) > pos + 1 and argv[pos + 1].lower() in ("on", "1", "true", "enable")
        ok, msg = devices.camera_set_all(on)
        _error_log(f"camera helper: on={on} ok={ok} {msg}")
        return 0 if ok else 1

    try:
        return App().run()
    except Exception:
        _error_log("fatal:\n" + traceback.format_exc())
        return 1

"""Drive the real windows: click the ball, walk the bar, flip a switch.

Clicks are injected as window messages rather than synthesised mouse input -
this sandbox accepts SetCursorPos and mouse_event but never delivers the
resulting button messages to a window, so a real click cannot be simulated.
Everything else is the production path: the same WndProcs, the same messages
Windows would send, and the state is read back from the config file.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import ImageGrab                                    # noqa: E402

from sxsnap import config, win32                             # noqa: E402

user32 = win32.user32
MK_LBUTTON = 0x0001
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_NCHITTEST = 0x0084

PY = r"C:\Users\Legion\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"


def lparam(x: int, y: int) -> int:
    return (int(y) << 16) | (int(x) & 0xFFFF)


def rect_of(hwnd) -> tuple[int, int, int, int]:
    rc = w.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rc))
    return (rc.left, rc.top, rc.right, rc.bottom)


def visible(hwnd) -> bool:
    rc = w.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rc))
    return bool(user32.IsWindowVisible(hwnd)) and (rc.right - rc.left) > 2


USER32 = ctypes.WinDLL("user32")


def press() -> None:
    # idempotent on purpose: a lost button-down in the middle of a drag ends
    # the gesture early, so the walk re-asserts it on every step
    USER32.mouse_event(0x0002, 0, 0, 0, None)      # LEFTDOWN
    time.sleep(0.04)


def release() -> None:
    USER32.mouse_event(0x0004, 0, 0, 0, None)      # LEFTUP
    time.sleep(0.05)


def click(hwnd, x: int, y: int) -> None:
    user32.SendMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam(x, y))
    user32.SendMessageW(hwnd, WM_LBUTTONUP, 0, lparam(x, y))


def shot(box, name: str, zoom: int = 2) -> None:
    img = ImageGrab.grab(bbox=box, all_screens=True)
    if zoom != 1:
        img = img.resize((img.width * zoom, img.height * zoom))
    img.save(name)
    print(f"  saved {name} {img.size}")


def kill_stale() -> int:
    """Kill any instance still holding the singleton, so the test drives *this*
    build rather than whatever happened to survive the previous run."""
    killed = 0
    pids = []

    def cb(h, l):
        if win32.window_class(h) in ("SXSnapBall", "SXSnapOwner"):
            pid = w.DWORD()
            user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value and pid.value not in pids:
                pids.append(pid.value)
        return True

    user32.EnumWindows(win32.ENUMPROC(cb), 0)
    for pid in pids:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        killed += 1
    if killed:
        time.sleep(0.6)
    return killed


def main() -> int:
    win32.enable_dpi_awareness()
    ok = True
    stale = kill_stale()
    print(f"stale instances killed: {stale}")

    cfg_path = config.config_path()
    backup = open(cfg_path, "r", encoding="utf-8").read() if os.path.exists(cfg_path) else "{}"
    cfg = config.load()
    cfg.update({"ball": True, "ball_x": 200, "ball_y": 200, "ball_docked": False,
                "ball_snap": True, "ball_topmost": True, "enabled": True,
                "mic_muted_by_us": False, "camera_off_by_us": False,
                "first_run_done": True})
    config.save(cfg)

    here = os.path.dirname(os.path.abspath(__file__))
    release()
    release()                          # never start with a stuck button
    if os.environ.get("SX_USE_EXE") == "1":
        app = subprocess.Popen([os.path.join(here, "SXSnap.exe")], cwd=here)
        print("target: packaged SXSnap.exe")
    else:
        release()
        release()
        app = subprocess.Popen([PY, "-m", "sxsnap"], cwd=here)
        print("target: source tree")
    try:
        ball = menu = panel = 0
        for _ in range(60):
            time.sleep(0.25)
            ball = user32.FindWindowW("SXSnapBall", None)
            if ball and visible(ball):
                break
        print("ball:", ball, "rect:", rect_of(ball) if ball else None)
        if not ball:
            print("FAIL: the ball never appeared")
            return 1

        # --- click-through outside the disc --------------------------------
        br = rect_of(ball)
        cx, cy = (br[0] + br[2]) // 2, (br[1] + br[3]) // 2
        corner = user32.SendMessageW(ball, WM_NCHITTEST, 0, lparam(br[0] + 2, br[1] + 2))
        middle = user32.SendMessageW(ball, WM_NCHITTEST, 0, lparam(cx, cy))
        print(f"  hit-test: corner={corner} centre={middle} (want {win32.HTTRANSPARENT} / {win32.HTCLIENT})")
        if corner != win32.HTTRANSPARENT or middle != win32.HTCLIENT:
            ok = False

        # --- click the ball -> the bar opens -------------------------------
        user32.SetCursorPos(cx, cy)
        time.sleep(0.1)
        click(ball, (br[2] - br[0]) // 2, (br[3] - br[1]) // 2)
        time.sleep(0.9)
        menu = user32.FindWindowW("SXSnapBallMenu", None)
        print("menu:", menu, "visible:", visible(menu) if menu else None,
              "rect:", rect_of(menu) if menu else None)
        if not menu or not visible(menu):
            ok = False
            print("  FAIL: the bar did not open")
        else:
            mr = rect_of(menu)
            shot((mr[0] - 30, mr[1] - 30, br[2] + 30, br[3] + 30), "shot-ball-live-menu.png")

        # --- hover the bar, then click 窗口布局 ---------------------------
        from sxsnap.ball import MENU_SHADOW, MENU_PAD, MENU_ICON, MENU_GAP
        s_menu = user32.GetDpiForWindow(menu) / 96.0 if menu else 1.0

        def tile_xy(index):
            x = int((MENU_SHADOW + 28) * s_menu)
            y = int((MENU_SHADOW + MENU_PAD + index * (MENU_ICON + MENU_GAP)
                     + MENU_ICON / 2) * s_menu)
            return x, y

        print(f"  menu scale={s_menu} dpi={user32.GetDpiForWindow(menu)} "
              f"tiles={[tile_xy(i) for i in range(4)]}")

        if menu and visible(menu):
            for idx in (0, 1, 2, 3):
                x, y = tile_xy(idx)
                user32.SendMessageW(menu, 0x0200, 0, lparam(x, y))
                time.sleep(0.15)
                mr = rect_of(menu)
                shot((mr[0] - 8, mr[1] - 8, mr[2] + 8, mr[3] + 8),
                     f"shot-ball-live-hover{idx}.png", zoom=2)

        before = json.load(open(cfg_path, encoding="utf-8"))["enabled"]
        if menu and visible(menu):
            x, y = tile_xy(2)
            print(f"  clicking tile 2 at ({x},{y}) lparam={lparam(x, y)}")
            r = user32.SendMessageW(menu, WM_LBUTTONUP, 0, lparam(x, y))
            print("  SendMessage returned", r)
        time.sleep(0.7)
        after = json.load(open(cfg_path, encoding="utf-8"))["enabled"]
        print(f"  layout tile: enabled {before} -> {after}, bar open: {visible(menu)}")
        if before == after:
            ok = False
            print("  FAIL: clicking the layout tile did nothing")
        if visible(menu):
            ok = False
            print("  FAIL: the bar stayed open after a tile was clicked")

        # --- open it again and go to the settings tile ---------------------
        time.sleep(0.3)
        click(ball, (br[2] - br[0]) // 2, (br[3] - br[1]) // 2)
        time.sleep(0.8)
        menu = user32.FindWindowW("SXSnapBallMenu", None)
        print("menu again:", menu, "visible:", visible(menu) if menu else None)
        if not menu or not visible(menu):
            ok = False
            print("  FAIL: the bar did not reopen")
        else:
            x, y = tile_xy(3)
            user32.SendMessageW(menu, WM_LBUTTONUP, 0, lparam(x, y))
            time.sleep(0.8)

        panel = user32.FindWindowW("SXSnapSettings", None)
        print("panel:", panel, "visible:", visible(panel) if panel else None,
              "rect:", rect_of(panel) if panel else None)
        if not panel or not visible(panel):
            ok = False
            print("  FAIL: the settings panel did not open")
        else:
            pr = rect_of(panel)
            shot((pr[0] - 20, pr[1] - 20, pr[2] + 20, pr[3] + 20),
                 "shot-ball-live-settings.png")

            from sxsnap.ball import PANEL_HEAD, ROW_H, PANEL_SHADOW
            s_panel = user32.GetDpiForWindow(panel) / 96.0
            for row, key, label in ((0, "ball_topmost", "始终置顶"),
                                    (1, "start_with_windows", "开机自启动")):
                y = int((PANEL_SHADOW + PANEL_HEAD + row * ROW_H + ROW_H / 2) * s_panel)
                x = int((pr[2] - pr[0]) / 2)
                was = json.load(open(cfg_path, encoding="utf-8")).get(key)
                user32.SendMessageW(panel, WM_LBUTTONUP, 0, lparam(x, y))
                time.sleep(0.55)
                now = json.load(open(cfg_path, encoding="utf-8")).get(key)
                print(f"  switch {label}: {was} -> {now}")
                if was == now:
                    ok = False
                    print(f"  FAIL: {label} did not toggle")

            pr = rect_of(panel)
            shot((pr[0] - 20, pr[1] - 20, pr[2] + 20, pr[3] + 20),
                 "shot-ball-live-settings2.png")

            # clicking the desktop must dismiss the panel.  The click itself
            # never reaches a window here, but GetAsyncKeyState does see the
            # synthetic press - and that is exactly what the dismissal uses.
            pr = rect_of(panel)
            away = (min(pr[2] + 220, 2500), min(pr[3] + 160, 1500))
            print(f"  panel rect={pr} clicking at {away}")
            user32.SetCursorPos(*away)
            time.sleep(0.15)
            press()
            time.sleep(0.35)
            release()
            time.sleep(0.3)
            print("  after an outside click, panel visible:", visible(panel))
            if visible(panel):
                ok = False
                print("  FAIL: the panel did not dismiss")

        # --- dropping in the middle must NOT dock ---------------------------
        def drag_ball_to(target):
            """Press on the ball, hold the button, walk the cursor, release."""
            r = rect_of(ball)
            cx0, cy0 = (r[0] + r[2]) // 2, (r[1] + r[3]) // 2
            user32.SetCursorPos(cx0, cy0)
            time.sleep(0.2)
            press()
            user32.SendMessageW(ball, WM_LBUTTONDOWN, MK_LBUTTON,
                                lparam((r[2] - r[0]) // 2, (r[3] - r[1]) // 2))
            time.sleep(0.15)
            for step in range(1, 11):
                press()
                user32.SetCursorPos(cx0 + (target[0] - cx0) * step // 10,
                                    cy0 + (target[1] - cy0) * step // 10)
                time.sleep(0.09)
            time.sleep(0.25)
            release()
            time.sleep(0.7)

        drag_ball_to((700, 700))
        st = json.load(open(cfg_path, encoding="utf-8"))
        r = rect_of(ball)
        print(f"  dropped mid-screen: docked={st['ball_docked']} "
              f"pos=({st['ball_x']},{st['ball_y']}) size=({r[2]-r[0]},{r[3]-r[1]})")
        if st["ball_docked"]:
            ok = False
            print("  FAIL: it docked although it was not dropped on an edge")
        if (r[2] - r[0]) < 100:
            ok = False
            print("  FAIL: the mid-screen ball is not disc-shaped")

        # --- dropped on an edge: it docks -----------------------------------
        drag_ball_to((2510, 800))
        st = json.load(open(cfg_path, encoding="utf-8"))
        r = rect_of(ball)
        print(f"  dropped on the right edge: docked={st['ball_docked']} edge={st['ball_edge']} "
              f"size=({r[2]-r[0]},{r[3]-r[1]})")
        if not st["ball_docked"] or st["ball_edge"] != "right":
            ok = False
            print("  FAIL: it did not dock to the right edge")
        shot((r[0] - 40, r[1] - 40, r[2] + 40, r[3] + 40),
             "shot-ball-live-docked.png", zoom=3)

        # --- clicking the sliver turns it back into a ball FOR GOOD ---------
        click(ball, (r[2] - r[0]) // 2, (r[3] - r[1]) // 2)
        time.sleep(0.9)
        st = json.load(open(cfg_path, encoding="utf-8"))
        r2 = rect_of(ball)
        menu = user32.FindWindowW("SXSnapBallMenu", None)
        print(f"  clicked the sliver: docked={st['ball_docked']} "
              f"size=({r2[2]-r2[0]},{r2[3]-r2[1]}) bar={visible(menu)}")
        if st["ball_docked"] or (r2[2] - r2[0]) < 100:
            ok = False
            print("  FAIL: clicking the sliver did not restore the disc")
        if not visible(menu):
            ok = False
            print("  FAIL: the bar did not open from the restored disc")
        else:
            mr = rect_of(menu)
            shot((min(mr[0], r2[0]) - 24, min(mr[1], r2[1]) - 24,
                  max(mr[2], r2[2]) + 24, max(mr[3], r2[3]) + 24),
                 "shot-ball-live-docked-menu.png", zoom=1)

        # --- and it STAYS a ball once the bar closes ------------------------
        print("  rects before the outside press: ball", rect_of(ball),
              "menu", rect_of(menu), "panel", rect_of(user32.FindWindowW("SXSnapSettings", None)))
        user32.SetCursorPos(300, 300)
        time.sleep(0.15)
        press()
        time.sleep(0.3)
        release()
        time.sleep(0.6)
        st = json.load(open(cfg_path, encoding="utf-8"))
        r3 = rect_of(ball)
        print(f"  after closing the bar: docked={st['ball_docked']} "
              f"size=({r3[2]-r3[0]},{r3[3]-r3[1]}) bar={visible(menu)}")
        if st["ball_docked"] or (r3[2] - r3[0]) < 100:
            ok = False
            print("  FAIL: the ball collapsed again after the bar closed")
        if visible(menu):
            ok = False
            print("  FAIL: the bar stayed open after an outside click")

        # --- hide it from the settings panel, then bring it back ------------
        click(ball, (r3[2] - r3[0]) // 2, (r3[3] - r3[1]) // 2)
        time.sleep(0.8)
        menu = user32.FindWindowW("SXSnapBallMenu", None)
        if menu and visible(menu):
            x, y = tile_xy(3)
            user32.SendMessageW(menu, WM_LBUTTONUP, 0, lparam(x, y))
            time.sleep(0.8)
        panel = user32.FindWindowW("SXSnapSettings", None)
        if not visible(panel):
            ok = False
            print("  FAIL: the settings panel did not open for the hide test")
        else:
            from sxsnap.ball import PANEL_HEAD, ROW_H, PANEL_SHADOW
            s_panel = user32.GetDpiForWindow(panel) / 96.0
            pr = rect_of(panel)
            hide_y = int((PANEL_SHADOW + PANEL_HEAD + 3 * ROW_H + ROW_H / 2) * s_panel)
            user32.SendMessageW(panel, WM_LBUTTONUP, 0,
                                lparam((pr[2] - pr[0]) // 2, hide_y))
            time.sleep(0.7)
            st = json.load(open(cfg_path, encoding="utf-8"))
            print(f"  after the hide switch: ball={st['ball']} visible={visible(ball)}")
            if st["ball"] or visible(ball):
                ok = False
                print("  FAIL: the hide switch did not hide the ball")

            # the panel is closed now; the tray double-click must bring it back
            owner = user32.FindWindowW("SXSnapOwner", None)
            user32.SendMessageW(owner, win32.WM_TRAYICON, 1, win32.WM_LBUTTONDBLCLK)
            time.sleep(0.8)
            st = json.load(open(cfg_path, encoding="utf-8"))
            print(f"  after a tray double-click: ball={st['ball']} visible={visible(ball)}")
            if not st["ball"] or not visible(ball):
                ok = False
                print("  FAIL: the ball could not be brought back from the tray")

            # the switch is a switch: clicking it again with the ball back on
            # screen hides it once more (the reverse direction is covered by
            # test_ball.py, which can open the panel without the ball)
            r4 = rect_of(ball)
            click(ball, (r4[2] - r4[0]) // 2, (r4[3] - r4[1]) // 2)
            time.sleep(0.8)
            menu = user32.FindWindowW("SXSnapBallMenu", None)
            if menu and visible(menu):
                x, y = tile_xy(3)
                user32.SendMessageW(menu, WM_LBUTTONUP, 0, lparam(x, y))
                time.sleep(0.8)
            panel = user32.FindWindowW("SXSnapSettings", None)
            if visible(panel):
                from sxsnap.ball import PANEL_HEAD, ROW_H, PANEL_SHADOW
                s_panel = user32.GetDpiForWindow(panel) / 96.0
                pr = rect_of(panel)
                hide_y = int((PANEL_SHADOW + PANEL_HEAD + 3 * ROW_H + ROW_H / 2) * s_panel)
                user32.SendMessageW(panel, WM_LBUTTONUP, 0,
                                    lparam((pr[2] - pr[0]) // 2, hide_y))
                time.sleep(0.7)
                st = json.load(open(cfg_path, encoding="utf-8"))
                print(f"  hide switch again: ball={st['ball']} visible={visible(ball)}")
                if st["ball"] or visible(ball):
                    ok = False
                    print("  FAIL: the second click on the hide switch did not hide it")

        print("done")
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(app.pid)], capture_output=True)
        time.sleep(0.4)
        with open(cfg_path, "w", encoding="utf-8") as fh:
            fh.write(backup)
        # the switches this test flips have side effects outside the file
        config.set_startup(False)

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

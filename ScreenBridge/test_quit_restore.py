"""End-to-end on the packaged exe: mute via the ball, quit, mic comes back.

The point of this test is the requirement that 退出 must leave the camera and
the microphone in a usable state.  The microphone half is fully verifiable here
(IAudioEndpointVolume needs no rights); the camera half cannot be, because
disabling a device node requires an administrator, and this machine has no way
to answer a UAC prompt - so the camera is covered by the refusal path instead.
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

from sxsnap import config, devices, win32                  # noqa: E402
from sxsnap.ball import MENU_GAP, MENU_ICON, MENU_PAD, MENU_SHADOW   # noqa: E402

user32 = win32.user32
EXE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "SXSnap.exe")
WM_TRAYICON = win32.WM_TRAYICON


def lparam(x, y):
    return (y << 16) | (x & 0xFFFF)


def find(cls):
    return user32.FindWindowW(cls, None)


def visible(hwnd):
    rc = w.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rc))
    return bool(hwnd) and bool(user32.IsWindowVisible(hwnd)) and rc.right - rc.left > 2


def kill_stale():
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
    if pids:
        time.sleep(0.8)
    return pids


def main() -> int:
    win32.enable_dpi_awareness()
    print("stale:", kill_stale())
    ok = True

    # start from a known state
    devices.mic_set(True)
    cfg = config.load()
    cfg.update({"enabled": True, "ball": True, "ball_topmost": True, "ball_docked": False,
                "ball_x": 600, "ball_y": 500, "mic_muted_by_us": False,
                "camera_off_by_us": False, "first_run_done": True})
    config.save(cfg)
    print("mic before:", devices.mic_on())

    app = subprocess.Popen([EXE])
    try:
        ball = 0
        for _ in range(60):
            time.sleep(0.25)
            ball = find("SXSnapBall")
            if ball and visible(ball):
                break
        print("ball:", ball, "alive:", app.poll() is None)
        if not ball:
            print("FAIL: no ball")
            return 1

        owner = find("SXSnapOwner")
        rc = w.RECT()
        user32.GetWindowRect(ball, ctypes.byref(rc))
        cx, cy = (rc.left + rc.right) // 2, (rc.top + rc.bottom) // 2
        user32.SetCursorPos(cx, cy)
        time.sleep(0.2)

        # --- tray double-click toggles the ball ----------------------------
        user32.SendMessageW(owner, WM_TRAYICON, 1, win32.WM_LBUTTONDBLCLK)
        time.sleep(0.5)
        hidden = not visible(ball)
        user32.SendMessageW(owner, WM_TRAYICON, 1, win32.WM_LBUTTONDBLCLK)
        time.sleep(0.5)
        shown = visible(ball)
        print(f"tray double-click: hidden={hidden} shown_again={shown}")
        if not (hidden and shown):
            ok = False
            print("  FAIL: the tray toggle did not hide and re-show the ball")

        # --- open the bar and mute the microphone --------------------------
        user32.SendMessageW(ball, 0x0201, 1, lparam(60, 60))
        user32.SendMessageW(ball, 0x0202, 0, lparam(60, 60))
        time.sleep(0.9)
        menu = find("SXSnapBallMenu")
        print("bar:", menu, "visible:", visible(menu))
        if not visible(menu):
            ok = False
            print("  FAIL: the bar did not open")
        else:
            s = user32.GetDpiForWindow(menu) / 96.0
            mx = int((MENU_SHADOW + 28) * s)
            my = int((MENU_SHADOW + MENU_PAD + 1 * (MENU_ICON + MENU_GAP)
                      + MENU_ICON / 2) * s)
            user32.SendMessageW(menu, 0x0202, 0, lparam(mx, my))
            time.sleep(0.9)

        state = devices.mic_on()
        saved = json.load(open(config.config_path(), encoding="utf-8"))
        print(f"after the mic tile: state={state} flag={saved['mic_muted_by_us']}")
        if state[1]:
            ok = False
            print("  FAIL: the microphone is still live after the mute tile")
        if not saved["mic_muted_by_us"]:
            ok = False
            print("  FAIL: the 'we muted it' flag was not remembered")

        # --- quit through the hotkey and check the microphone came back ----
        user32.PostMessageW(owner, win32.WM_HOTKEY, 1, 0)
        deadline = time.time() + 12
        while time.time() < deadline and app.poll() is None:
            time.sleep(0.2)
        print("exited:", app.poll() is not None, "code:", app.poll())
        time.sleep(0.6)
        after = devices.mic_on()
        saved = json.load(open(config.config_path(), encoding="utf-8"))
        print(f"after quit: mic={after} flag={saved['mic_muted_by_us']}")
        if not after[1]:
            ok = False
            print("  FAIL: quitting left the microphone muted")
        if saved["mic_muted_by_us"]:
            ok = False
            print("  FAIL: the muted flag survived the quit")

        # --- the camera path must fail cleanly without administrator rights
        if not devices.is_admin():
            cam = devices.camera_set_all(False)
            print(f"camera without rights: {cam}")
            if cam[0]:
                ok = False
                print("  FAIL: camera_set_all claimed success without rights")
            if "管理员" not in cam[1]:
                ok = False
                print("  FAIL: the refusal does not mention the missing rights")
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(app.pid)], capture_output=True)
        devices.mic_set(True)
        cfg = config.load()
        cfg.update({"enabled": True, "ball": True, "mic_muted_by_us": False,
                    "camera_off_by_us": False, "ball_x": None, "ball_y": None})
        config.save(cfg)

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

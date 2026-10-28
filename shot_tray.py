"""Screenshot the tray context menu.

TrackPopupMenu runs its own modal loop and blocks the app's message thread
until something is dismissed - and this sandbox cannot deliver the click that
would dismiss it.  So the menu is captured from a second process and the app is
killed afterwards; that is fine for a screenshot, and it is not part of the
regular test suite for exactly that reason.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import ImageGrab                                     # noqa: E402

from sxsnap import config, win32                              # noqa: E402

user32 = win32.user32
HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    win32.enable_dpi_awareness()
    exe = os.path.join(HERE, "SXSnap.exe")
    if not os.path.exists(exe):
        print("build SXSnap.exe first")
        return 1

    cfg = config.load()
    cfg.update({"ball": True, "ball_x": 200, "ball_y": 200, "ball_docked": False,
                "first_run_done": True})
    config.save(cfg)

    app = subprocess.Popen([exe], cwd=HERE)
    try:
        owner = ball = 0
        for _ in range(60):
            time.sleep(0.25)
            owner = user32.FindWindowW("SXSnapOwner", None)
            ball = user32.FindWindowW("SXSnapBall", None)
            if owner and ball and user32.IsWindowVisible(ball):
                break
        if not owner:
            print("no owner window")
            return 1

        tray = user32.FindWindowW("Shell_TrayWnd", None)
        rc = w.RECT()
        user32.GetWindowRect(tray, ctypes.byref(rc))
        x, y = rc.right - 260, rc.top + 10
        user32.SetCursorPos(x, y)
        time.sleep(0.3)

        # the app will block inside TrackPopupMenu from here on
        user32.PostMessageW(owner, win32.WM_TRAYICON, 1, win32.WM_RBUTTONUP)
        time.sleep(1.2)

        img = ImageGrab.grab(bbox=(x - 40, rc.top - 320, x + 320, rc.bottom),
                             all_screens=True)
        img = img.resize((img.width * 2, img.height * 2))
        img.save("shot-tray-menu.png")
        print("saved shot-tray-menu.png", img.size, "app alive:", app.poll() is None)
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(app.pid)], capture_output=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

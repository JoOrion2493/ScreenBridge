"""Settings persisted as JSON under %LOCALAPPDATA%\\SXSnap."""

from __future__ import annotations

import json
import os
import sys

DEFAULTS = {
    "enabled": True,
    # last layout picked, only used for the tray tooltip
    "layout": "split-v",
    # pixels of breathing room between windows inside a layout
    "gap": 8,
    "margin": 0,
    # how long the cursor must rest on a screen chip before its layouts unfold
    "dwell_ms": 90,
    # how big the drag palette is: "large" | "medium" | "small"
    "palette_size": "large",
    # Cross-display moves: shrink, fly across the bezel, grow.  Same-display
    # placement is deliberately instant - a zoom that eases into a zone reads
    # as lag when all the user asked for is "put it there".
    "animate": True,
    "anim_travel_ms": 560,

    # ------------------------------------------------------- floating ball
    "ball": True,                 # is the ball on screen at all
    "ball_x": None,               # visible disc top-left, physical px
    "ball_y": None,
    "ball_topmost": True,
    "ball_snap": True,            # dock to the nearest screen edge when dropped
    "ball_docked": False,         # currently collapsed into the blue sliver
    "ball_edge": "right",

    "start_with_windows": False,
    # what *we* switched off, so 退出 can put it back
    "camera_off_by_us": False,
    "mic_muted_by_us": False,

    "first_run_done": False,
}


def config_dir() -> str:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = os.path.expanduser("~")
    return os.path.join(base, "SXSnap")


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


def load() -> dict:
    cfg = dict(DEFAULTS)
    p = config_path()
    try:
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    # the registry is the truth for autostart: the user may have removed the
    # entry from Task Manager, and a stale switch would then be a lie
    cfg["start_with_windows"] = startup_enabled()
    return cfg


def save(cfg: dict) -> None:
    try:
        os.makedirs(config_dir(), exist_ok=True)
        with open(config_path(), "w", encoding="utf-8") as fh:
            json.dump(
                {k: cfg.get(k, v) for k, v in DEFAULTS.items()},
                fh,
                ensure_ascii=False,
                indent=2,
            )
    except OSError:
        pass


# ------------------------------------------------------------------ autostart
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "SXSnap"


def _launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    entry = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "sxsnap_entry.py")
    exe = sys.executable
    pyw = exe.replace("python.exe", "pythonw.exe")
    if os.path.exists(pyw):
        exe = pyw
    return f'"{exe}" "{entry}"'


def set_startup(on: bool) -> bool:
    """HKCU Run key - no administrator needed, which is why it is used here."""
    try:
        import winreg
    except ImportError:                                      # pragma: no cover
        return False
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
            if on:
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, _launch_command())
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def startup_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, RUN_VALUE)
            return bool(value)
    except (OSError, ImportError):
        return False

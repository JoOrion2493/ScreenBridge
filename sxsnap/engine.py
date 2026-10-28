"""Window placement.

The one detail that matters: a window that has ever been maximised keeps a
remembered restore rect. Calling SetWindowPos alone lets the shell "restore"
it to that old rect and the window jumps out of the target zone.
So we write rcNormalPosition through SetWindowPlacement first, then refine
with SetWindowPos. This is exactly what AsusXMover/MoveWindowByRect does.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import time

from . import win32

SW_SHOWNORMAL = 1
SW_SHOWMINIMIZED = 2
SW_SHOWMAXIMIZED = 3

SWP_FRAMECHANGED = 0x0020
DWMWA_CLOAKED = 14

_dwm = ctypes.WinDLL("dwmapi")

_WS_EX_TOOLWINDOW = 0x00000080

# Windows that must never be treated as a draggable app.
_SKIP_CLASSES = {
    "Progman",
    "WorkerW",
    "Shell_TrayWnd",
    "Shell_SecondaryTrayWnd",
    "Windows.UI.Core.CoreWindow",
    "ForegroundStaging",
    "DV2ControlHost",
    "MsgrIMEWindowClass",
    "SysShadow",
    "Button",
    "tooltips_class32",
}


def _is_cloaked(hwnd: int) -> bool:
    v = ctypes.c_int(0)
    try:
        hr = _dwm.DwmGetWindowAttribute(
            w.HWND(hwnd), DWMWA_CLOAKED, ctypes.byref(v), ctypes.sizeof(v)
        )
        if hr != 0:
            return False
    except Exception:
        return False
    return v.value != 0


def is_snappable(hwnd: int) -> bool:
    if not hwnd or not win32.user32.IsWindow(hwnd):
        return False
    if not win32.user32.IsWindowVisible(hwnd):
        return False
    if win32.window_class(hwnd) in _SKIP_CLASSES:
        return False
    ex = win32._gwl(hwnd, win32.GWL_EXSTYLE)
    if ex & _WS_EX_TOOLWINDOW:
        return False
    if _is_cloaked(hwnd):
        return False
    return True


def move_to_rect(hwnd: int, rect: tuple[int, int, int, int], verify: bool = True) -> bool:
    """Place `hwnd` at an absolute physical-pixel rect. Returns success."""
    l, t, r, b = (int(v) for v in rect)
    if r - l < 40 or b - t < 40:
        return False
    if not win32.user32.IsWindow(hwnd):
        return False

    if win32.user32.IsIconic(hwnd):
        win32.user32.ShowWindow(hwnd, win32.SW_RESTORE)

    # --- step 1: rewrite the remembered restore rect ---
    wp = win32.WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(win32.WINDOWPLACEMENT)
    if win32.user32.GetWindowPlacement(hwnd, ctypes.byref(wp)):
        if wp.showCmd in (SW_SHOWMAXIMIZED, SW_SHOWMINIMIZED):
            wp.showCmd = SW_SHOWNORMAL
        wp.flags = 0
        wp.ptMinPosition.x = -1
        wp.ptMinPosition.y = -1
        wp.ptMaxPosition.x = -1
        wp.ptMaxPosition.y = -1
        wp.rcNormalPosition.left = l
        wp.rcNormalPosition.top = t
        wp.rcNormalPosition.right = r
        wp.rcNormalPosition.bottom = b
        win32.user32.SetWindowPlacement(hwnd, ctypes.byref(wp))

    # --- step 2: exact size/position, no activate ---
    ok = win32.user32.SetWindowPos(
        hwnd,
        0,
        l,
        t,
        r - l,
        b - t,
        win32.SWP_NOZORDER | win32.SWP_NOACTIVATE | SWP_FRAMECHANGED,
    )

    if not verify:
        return bool(ok)

    # --- step 3: one corrective pass if the shell nudged us ---
    cl, ct, cr, cb = win32.window_rect(hwnd)
    if abs(cl - l) <= 1 and abs(ct - t) <= 1 and abs((cr - cl) - (r - l)) <= 1:
        return True
    win32.user32.SetWindowPos(
        hwnd,
        0,
        l,
        t,
        r - l,
        b - t,
        win32.SWP_NOZORDER | win32.SWP_NOACTIVATE,
    )
    return True


def restore_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    wp = win32.WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(win32.WINDOWPLACEMENT)
    if win32.user32.GetWindowPlacement(hwnd, ctypes.byref(wp)):
        rc = wp.rcNormalPosition
        return (rc.left, rc.top, rc.right, rc.bottom)
    return None


# --------------------------------------------------------------------------
#  "is this drag a resize?" and "move to the other display"
# --------------------------------------------------------------------------

_WM_NCHITTEST = 0x0084
_SMTO_ABORTIFHUNG = 0x0002
_HTCAPTION = 2
_HTLEFT, _HTBOTTOMRIGHT = 10, 17
_SM_CXSIZEFRAME, _SM_CYSIZEFRAME, _SM_CXPADDEDBORDER = 32, 33, 92

_user32_st = win32.user32
_user32_st.SendMessageTimeoutW.argtypes = [
    w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t,
    ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t),
]
_user32_st.SendMessageTimeoutW.restype = ctypes.c_ssize_t


def is_sizing(hwnd: int) -> bool:
    """True when the drag is a border resize, not a titlebar move.

    The shell sends the same MOVESIZESTART for both, and popping a palette over
    the edge being dragged is exactly the annoyance the original avoids.  Ask
    the window itself through WM_NCHITTEST - that is the same value the system
    uses to decide, so it is right for custom-drawn title bars too.  Falls back
    to geometry when the window does not answer.
    """
    if not hwnd or not _user32_st.IsWindow(hwnd):
        return False
    if _user32_st.IsZoomed(hwnd):
        return False

    x, y = win32.cursor_pos()
    lparam = (y << 16) | (x & 0xFFFF)
    result = ctypes.c_size_t(0)
    answered = _user32_st.SendMessageTimeoutW(
        hwnd, _WM_NCHITTEST, 0, lparam, _SMTO_ABORTIFHUNG, 120, ctypes.byref(result)
    )
    if answered:
        hit = int(result.value)
        if _HTLEFT <= hit <= _HTBOTTOMRIGHT:
            return True
        if hit == _HTCAPTION:
            return False

    l, t, r, b = win32.window_rect(hwnd)
    toll = max(6, _user32_st.GetSystemMetrics(_SM_CXSIZEFRAME)
               + _user32_st.GetSystemMetrics(_SM_CXPADDEDBORDER))
    return (x - l <= toll or r - x <= toll or y - t <= toll or b - y <= toll)


def visible_rect(hwnd: int) -> tuple[int, int, int, int]:
    """Window rect without the invisible resize border Win10/11 adds."""
    rc = w.RECT()
    if _dwm.DwmGetWindowAttribute(
        w.HWND(hwnd), 9, ctypes.byref(rc), ctypes.sizeof(rc)  # DWMWA_EXTENDED_FRAME_BOUNDS
    ) == 0 and rc.right > rc.left:
        return (rc.left, rc.top, rc.right, rc.bottom)
    return win32.window_rect(hwnd)


def place_visible(hwnd: int, target: tuple[int, int, int, int], passes: int = 3) -> bool:
    """Land the window's *visible* rect on `target`.

    SetWindowPos talks about the window rect, which on Win10/11 is the visible
    frame grown by an invisible resize border (9px per side at 150%, and the
    border scales with DPI).  Placing the window rect on the zone would leave
    the visible frame inset - two neighbouring zones would show a gap of
    gap + 2*border instead of the configured gap.  So measure the real visible
    rect, correct, and re-measure until it lands.
    """
    move_to_rect(hwnd, target)
    for _ in range(passes):
        v = visible_rect(hwnd)
        d = [target[i] - v[i] for i in range(4)]
        if max(abs(x) for x in d) <= 1:
            break
        gl, gt, gr, gb = win32.window_rect(hwnd)
        # give the window time to settle after WM_DPICHANGED before re-measuring
        time.sleep(0.08)
        move_to_rect(hwnd, (gl + d[0], gt + d[1], gr + d[2], gb + d[3]), verify=False)
    return True


def target_on_monitor(hwnd: int, mon) -> tuple[int, int, int, int] | None:
    """Where the window would land on `mon`: same size, centred, clamped to 90%."""
    cl, ct, cr, cb = visible_rect(hwnd)
    ww, hh = cr - cl, cb - ct
    if ww <= 0 or hh <= 0:
        return None

    wl, wt, wr, wb = mon.work
    aw, ah = wr - wl, wb - wt
    maxw, maxh = int(aw * 0.9), int(ah * 0.9)
    if ww > maxw or hh > maxh:
        k = min(maxw / float(ww), maxh / float(hh))
        ww, hh = int(ww * k), int(hh * k)

    x = wl + (aw - ww) // 2
    y = wt + (ah - hh) // 2
    return (x, y, x + ww, y + hh)


def move_to_monitor(hwnd: int, mon) -> bool:
    """Move the window to `mon`, keeping its size, centred, clamped to 90%."""
    target = target_on_monitor(hwnd, mon)
    if target is None:
        return False
    return place_visible(hwnd, target)

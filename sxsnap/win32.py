"""SXSnap - Win32 bindings.

Pure ctypes, no third-party dependencies. Everything the drag-snap overlay
needs: monitor enumeration, drag detection via SetWinEventHook, layered
click-through window, GDI painting and the two-step window placement.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

try:
    shcore = ctypes.WinDLL("shcore", use_last_error=True)
except OSError:  # pragma: no cover - very old systems
    shcore = None

LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t

WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, ctypes.c_uint, WPARAM, LPARAM)
MONITORENUMPROC = ctypes.WINFUNCTYPE(
    w.BOOL, w.HANDLE, w.HDC, ctypes.POINTER(w.RECT), w.LPARAM
)
ENUMPROC = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
WINEVENTPROC = ctypes.WINFUNCTYPE(
    None, w.HANDLE, w.DWORD, w.HWND, ctypes.c_long, ctypes.c_long, w.DWORD, w.DWORD
)

# ---------------------------------------------------------------- constants
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_PAINT = 0x000F
WM_TIMER = 0x0113
WM_HOTKEY = 0x0312
WM_DISPLAYCHANGE = 0x007E
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_MOUSELEAVE = 0x02A3
WM_NCHITTEST = 0x0084
WM_NCPAINT = 0x0085
WM_SETCURSOR = 0x0020
WM_DPICHANGED = 0x02E0
WM_APP = 0x8000
WM_TRAYICON = WM_APP + 1

HTTRANSPARENT = -1
HTCLIENT = 1

TME_LEAVE = 0x00000002

WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

GWL_EXSTYLE = -20
GWL_STYLE = -16

SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWNA = 8
SW_RESTORE = 9

HWND_TOP = 0
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_NOZORDER = 0x0004

LWA_ALPHA = 0x00000002

DT_LEFT = 0x00000000
DT_CENTER = 0x00000001
DT_RIGHT = 0x00000002
DT_VCENTER = 0x00000004
DT_SINGLELINE = 0x00000020
DT_NOPREFIX = 0x00002000

TRANSPARENT = 1
FW_SEMIBOLD = 600
DEFAULT_CHARSET = 1
CLEARTYPE_QUALITY = 5

PS_SOLID = 0
NULL_BRUSH = 5
NULL_PEN = 8
HOLLOW_BRUSH = NULL_BRUSH

SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CMONITORS = 80

MONITOR_DEFAULTTONEAREST = 2
MONITOR_DEFAULTTOPRIMARY = 1

EVENT_SYSTEM_MOVESIZESTART = 0x000A
EVENT_SYSTEM_MOVESIZEEND = 0x000B
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002

VK_LBUTTON = 0x01
VK_ESCAPE = 0x1B
VK_F1 = 0x70

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

IDC_ARROW = 32512

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def RGB(r: int, g: int, b: int) -> int:
    return (r & 0xFF) | ((g & 0xFF) << 8) | ((b & 0xFF) << 16)


# ---------------------------------------------------------------- structures
class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", w.DWORD),
        ("rcMonitor", w.RECT),
        ("rcWork", w.RECT),
        ("dwFlags", w.DWORD),
        ("szDevice", ctypes.c_wchar * 32),
    ]


class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_uint),
        ("flags", ctypes.c_uint),
        ("showCmd", ctypes.c_uint),
        ("ptMinPosition", w.POINT),
        ("ptMaxPosition", w.POINT),
        ("rcNormalPosition", w.RECT),
    ]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", w.HDC),
        ("fErase", w.BOOL),
        ("rcPaint", w.RECT),
        ("fRestore", w.BOOL),
        ("fIncUpdate", w.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("style", ctypes.c_uint),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", w.HINSTANCE),
        ("hIcon", w.HICON),
        ("hCursor", w.HANDLE),
        ("hbrBackground", w.HBRUSH),
        ("lpszMenuName", w.LPCWSTR),
        ("lpszClassName", w.LPCWSTR),
        ("hIconSm", w.HICON),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", w.DWORD),
        ("hWnd", w.HWND),
        ("uID", ctypes.c_uint),
        ("uFlags", ctypes.c_uint),
        ("uCallbackMessage", ctypes.c_uint),
        ("hIcon", w.HICON),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", w.DWORD),
        ("dwStateMask", w.DWORD),
        ("szInfo", ctypes.c_wchar * 256),
        ("uVersion", ctypes.c_uint),
        ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", w.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", w.HICON),
    ]


# ---------------------------------------------------------------- prototypes
user32.EnumDisplayMonitors.argtypes = [
    w.HDC, ctypes.POINTER(w.RECT), MONITORENUMPROC, w.LPARAM
]
user32.EnumDisplayMonitors.restype = w.BOOL

user32.GetMonitorInfoW.argtypes = [w.HANDLE, ctypes.POINTER(MONITORINFOEXW)]
user32.GetMonitorInfoW.restype = w.BOOL

user32.MonitorFromWindow.argtypes = [w.HWND, w.DWORD]
user32.MonitorFromWindow.restype = w.HANDLE

user32.MonitorFromPoint.argtypes = [w.POINT, w.DWORD]
user32.MonitorFromPoint.restype = w.HANDLE

if shcore is not None:
    try:
        shcore.GetDpiForMonitor.argtypes = [
            w.HANDLE, ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint),
        ]
        shcore.GetDpiForMonitor.restype = ctypes.c_long
    except AttributeError:  # pragma: no cover
        pass

user32.EnumWindows.argtypes = [ENUMPROC, w.LPARAM]
user32.EnumWindows.restype = w.BOOL

user32.IsWindowVisible.argtypes = [w.HWND]
user32.IsWindowVisible.restype = w.BOOL

user32.IsWindow.argtypes = [w.HWND]
user32.IsWindow.restype = w.BOOL

user32.IsIconic.argtypes = [w.HWND]
user32.IsIconic.restype = w.BOOL

user32.IsZoomed.argtypes = [w.HWND]
user32.IsZoomed.restype = w.BOOL

user32.GetWindowTextLengthW.argtypes = [w.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int

user32.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int

user32.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int

user32.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
user32.GetWindowRect.restype = w.BOOL

user32.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
user32.GetWindowThreadProcessId.restype = w.DWORD

user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = w.HWND

user32.GetCursorPos.argtypes = [ctypes.POINTER(w.POINT)]
user32.GetCursorPos.restype = w.BOOL

user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short

user32.WindowFromPoint.argtypes = [w.POINT]
user32.WindowFromPoint.restype = w.HWND

user32.GetAncestor.argtypes = [w.HWND, ctypes.c_uint]
user32.GetAncestor.restype = w.HWND
GA_ROOT = 2

_gwl = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
_swl = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
_gwl.argtypes = [w.HWND, ctypes.c_int]
_gwl.restype = ctypes.c_ssize_t
_swl.argtypes = [w.HWND, ctypes.c_int, ctypes.c_ssize_t]
_swl.restype = ctypes.c_ssize_t

user32.GetWindowPlacement.argtypes = [w.HWND, ctypes.POINTER(WINDOWPLACEMENT)]
user32.GetWindowPlacement.restype = w.BOOL

user32.SetWindowPlacement.argtypes = [w.HWND, ctypes.POINTER(WINDOWPLACEMENT)]
user32.SetWindowPlacement.restype = w.BOOL

user32.SetWindowPos.argtypes = [
    w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint
]
user32.SetWindowPos.restype = w.BOOL

user32.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
user32.ShowWindow.restype = w.BOOL

user32.GetDpiForWindow.argtypes = [w.HWND]
user32.GetDpiForWindow.restype = ctypes.c_uint

user32.SetCapture.argtypes = [w.HWND]
user32.SetCapture.restype = w.HWND

user32.ReleaseCapture.argtypes = []
user32.ReleaseCapture.restype = w.BOOL

user32.GetParent.argtypes = [w.HWND]
user32.GetParent.restype = w.HWND

user32.SetFocus.argtypes = [w.HWND]
user32.SetFocus.restype = w.HWND

user32.GetKeyState.argtypes = [ctypes.c_int]
user32.GetKeyState.restype = ctypes.c_short

user32.SetWinEventHook.argtypes = [
    w.DWORD, w.DWORD, w.HANDLE, WINEVENTPROC, w.DWORD, w.DWORD, w.DWORD
]
user32.SetWinEventHook.restype = w.HANDLE

user32.UnhookWinEvent.argtypes = [w.HANDLE]
user32.UnhookWinEvent.restype = w.BOOL

user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = w.WORD

user32.UnregisterClassW.argtypes = [w.LPCWSTR, w.HINSTANCE]
user32.UnregisterClassW.restype = w.BOOL

user32.CreateWindowExW.argtypes = [
    w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID,
]
user32.CreateWindowExW.restype = w.HWND

user32.DefWindowProcW.argtypes = [w.HWND, ctypes.c_uint, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT

user32.DestroyWindow.argtypes = [w.HWND]
user32.DestroyWindow.restype = w.BOOL

user32.SetLayeredWindowAttributes.argtypes = [
    w.HWND, w.DWORD, ctypes.c_byte, w.DWORD
]
user32.SetLayeredWindowAttributes.restype = w.BOOL

user32.SetTimer.argtypes = [w.HWND, ctypes.c_size_t, ctypes.c_uint, ctypes.c_void_p]
user32.SetTimer.restype = ctypes.c_size_t

user32.KillTimer.argtypes = [w.HWND, ctypes.c_size_t]
user32.KillTimer.restype = w.BOOL

user32.InvalidateRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT), w.BOOL]
user32.InvalidateRect.restype = w.BOOL

user32.GetMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, ctypes.c_uint, ctypes.c_uint]
user32.GetMessageW.restype = ctypes.c_int

user32.TranslateMessage.argtypes = [ctypes.POINTER(w.MSG)]
user32.TranslateMessage.restype = w.BOOL

user32.DispatchMessageW.argtypes = [ctypes.POINTER(w.MSG)]
user32.DispatchMessageW.restype = LRESULT

user32.PeekMessageW.argtypes = [
    ctypes.POINTER(w.MSG), w.HWND, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint
]
user32.PeekMessageW.restype = w.BOOL

user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.PostQuitMessage.restype = None

user32.PostMessageW.argtypes = [w.HWND, ctypes.c_uint, WPARAM, LPARAM]
user32.PostMessageW.restype = w.BOOL

user32.RegisterHotKey.argtypes = [w.HWND, ctypes.c_int, w.DWORD, w.DWORD]
user32.RegisterHotKey.restype = w.BOOL

user32.UnregisterHotKey.argtypes = [w.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = w.BOOL

user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int

user32.SetForegroundWindow.argtypes = [w.HWND]
user32.SetForegroundWindow.restype = w.BOOL

user32.LoadCursorW.argtypes = [w.HINSTANCE, ctypes.c_void_p]
user32.LoadCursorW.restype = w.HANDLE

user32.BeginPaint.argtypes = [w.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.BeginPaint.restype = w.HDC

user32.EndPaint.argtypes = [w.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.EndPaint.restype = w.BOOL

user32.FillRect.argtypes = [w.HDC, ctypes.POINTER(w.RECT), w.HBRUSH]
user32.FillRect.restype = ctypes.c_int

user32.FrameRect.argtypes = [w.HDC, ctypes.POINTER(w.RECT), w.HBRUSH]
user32.FrameRect.restype = ctypes.c_int

user32.DrawTextW.argtypes = [w.HDC, w.LPCWSTR, ctypes.c_int, ctypes.POINTER(w.RECT), ctypes.c_uint]
user32.DrawTextW.restype = ctypes.c_int

user32.GetDC.argtypes = [w.HWND]
user32.GetDC.restype = w.HDC

user32.ReleaseDC.argtypes = [w.HWND, w.HDC]
user32.ReleaseDC.restype = ctypes.c_int

gdi32.CreateSolidBrush.argtypes = [w.DWORD]
gdi32.CreateSolidBrush.restype = w.HBRUSH

gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, w.DWORD]
gdi32.CreatePen.restype = w.HPEN

gdi32.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]
gdi32.SelectObject.restype = w.HGDIOBJ

gdi32.DeleteObject.argtypes = [w.HGDIOBJ]
gdi32.DeleteObject.restype = w.BOOL

gdi32.SetBkMode.argtypes = [w.HDC, ctypes.c_int]
gdi32.SetBkMode.restype = ctypes.c_int

gdi32.SetTextColor.argtypes = [w.HDC, w.DWORD]
gdi32.SetTextColor.restype = w.DWORD

gdi32.RoundRect.argtypes = [
    w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int,
]
gdi32.RoundRect.restype = w.BOOL

gdi32.Rectangle.argtypes = [
    w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int
]
gdi32.Rectangle.restype = w.BOOL

gdi32.CreateFontW.argtypes = [
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.DWORD,
    w.LPCWSTR,
]
gdi32.CreateFontW.restype = w.HANDLE

gdi32.GetStockObject.argtypes = [ctypes.c_int]
gdi32.GetStockObject.restype = w.HGDIOBJ

kernel32.GetModuleHandleW.argtypes = [w.LPCWSTR]
kernel32.GetModuleHandleW.restype = w.HINSTANCE

kernel32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
kernel32.OpenProcess.restype = w.HANDLE

kernel32.CloseHandle.argtypes = [w.HANDLE]
kernel32.CloseHandle.restype = w.BOOL

kernel32.QueryFullProcessImageNameW.argtypes = [
    w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)
]
kernel32.QueryFullProcessImageNameW.restype = w.BOOL

shell32.Shell_NotifyIconW.argtypes = [w.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype = w.BOOL

# -------------------------------------------------------------- popup menus
# The tray icon gets a real Win32 menu rather than a hand-drawn panel: it is
# the one place where users expect the system look, and it brings correct
# keyboard handling, shadows and dismissal for free.
MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
MF_CHECKED = 0x00000008
MF_GRAYED = 0x00000001
TPM_RIGHTBUTTON = 0x0002
TPM_NONOTIFY = 0x0080
TPM_RETURNCMD = 0x0100
WM_NULL = 0x0000

user32.CreatePopupMenu.argtypes = []
user32.CreatePopupMenu.restype = w.HANDLE

user32.AppendMenuW.argtypes = [w.HANDLE, ctypes.c_uint, ctypes.c_size_t, w.LPCWSTR]
user32.AppendMenuW.restype = w.BOOL

user32.TrackPopupMenu.argtypes = [
    w.HANDLE, ctypes.c_uint, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, w.HWND, ctypes.c_void_p,
]
user32.TrackPopupMenu.restype = ctypes.c_int

user32.DestroyMenu.argtypes = [w.HANDLE]
user32.DestroyMenu.restype = w.BOOL


# ---------------------------------------------------------------- helpers
class Monitor:
    __slots__ = ("handle", "device", "rect", "work", "primary", "dpi", "left", "top",
                 "number")

    def __init__(self, handle, device, rect, work, primary, dpi, number=0):
        self.handle = handle
        self.device = device
        self.rect = rect          # (l, t, r, b) physical pixels
        self.work = work
        self.primary = primary
        self.dpi = dpi
        self.number = number      # the number Windows shows in Settings
        self.left = rect[0]
        self.top = rect[1]

    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]

    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]

    @property
    def work_rect(self) -> tuple[int, int, int, int]:
        """Work area expressed in absolute virtual-screen coordinates."""
        wl, wt, wr, wb = self.work
        return (wl, wt, wr, wb)

    def __repr__(self) -> str:
        return f"<Monitor {self.device} {self.rect} dpi={self.dpi}>"


def enable_dpi_awareness() -> str:
    """PerMonitorV2 first, degrade gracefully."""
    try:
        # -4 == DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return "PerMonitorV2"
    except AttributeError:
        pass
    try:
        if shcore and shcore.SetProcessDpiAwareness(2) == 0:
            return "PerMonitor"
    except Exception:
        pass
    try:
        if user32.SetProcessDPIAware():
            return "System"
    except Exception:
        pass
    return "Unaware"


def _display_number(device_name: str, fallback: int = 0) -> int:
    """The N of a GDI device name like \\\\.\\DISPLAY2.

    This is only a *fallback*: the GDI name is allocated per adapter, so on a
    laptop with the panel on the iGPU and an external monitor on the dGPU the
    numbers are 1 and 3 while Windows itself shows 1 and 2.  `enumerate_monitors`
    therefore prefers the number the display configuration reports.
    """
    name = device_name or ""
    tail = name.split("DISPLAY")[-1] if "DISPLAY" in name else ""
    digits = ""
    for ch in reversed(tail):
        if ch.isdigit():
            digits = ch + digits
        else:
            break
    try:
        return int(digits)
    except ValueError:
        return fallback + 1


def enumerate_monitors() -> list[Monitor]:
    out: list[Monitor] = []

    # The number Windows shows for each display.  The GDI name
    # ("\\.\DISPLAY3") is allocated per adapter and drifts away from what
    # Settings displays, so ask the display configuration for the real one
    # and fall back to the GDI name when that call is unavailable.
    numbers: dict[str, int] = {}
    try:
        from . import displays
        numbers = displays.numbers_by_device()
    except Exception:
        pass

    def _cb(hmon, hdc, lprc, data):
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            dpi = 96
            if shcore is not None:
                dx = ctypes.c_uint(0)
                dy = ctypes.c_uint(0)
                try:
                    if shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0:
                        dpi = int(dx.value) or 96
                except Exception:
                    pass
            out.append(
                Monitor(
                    hmon,
                    mi.szDevice,
                    (mi.rcMonitor.left, mi.rcMonitor.top, mi.rcMonitor.right, mi.rcMonitor.bottom),
                    (mi.rcWork.left, mi.rcWork.top, mi.rcWork.right, mi.rcWork.bottom),
                    bool(mi.dwFlags & 1),
                    dpi,
                    numbers.get(mi.szDevice) or _display_number(mi.szDevice, len(out)),
                )
            )
        return 1

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_cb), 0)
    out.sort(key=lambda m: (m.rect[1], m.rect[0]))
    return out


def virtual_screen() -> tuple[int, int, int, int]:
    """Return (left, top, right, bottom) of the whole virtual desktop."""
    return (
        user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_XVIRTUALSCREEN) + user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_YVIRTUALSCREEN) + user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
    )


def cursor_pos() -> tuple[int, int]:
    p = w.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return (p.x, p.y)


def left_button_down() -> bool:
    return bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)


def monitor_at(x: int, y: int, monitors: list[Monitor]) -> Monitor | None:
    for m in monitors:
        l, t, r, b = m.rect
        if l <= x < r and t <= y < b:
            return m
    return None


def window_text(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def window_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    r = w.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def window_exe(hwnd: int) -> str:
    pid = w.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return ""
    try:
        size = w.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
    finally:
        kernel32.CloseHandle(h)
    return ""


def root_window(hwnd: int) -> int:
    return user32.GetAncestor(hwnd, GA_ROOT) or hwnd


def window_from_point(x: int, y: int) -> int:
    """Top-level window under a screen point."""
    pt = w.POINT(int(x), int(y))
    return root_window(user32.WindowFromPoint(pt) or 0)

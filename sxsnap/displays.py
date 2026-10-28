"""The system's own view of the displays: their numbers and their arrangement.

Windows shows a number for every display (Settings > System > Display, and the
"Identify" button that flashes it on screen).  That number is **not** the N in
the GDI device name `\\\\.\\DISPLAYN`:

    our machine:   \\\\DISPLAY1 = the laptop panel (AMD)
                   \\\\DISPLAY3 = the external panel (NVIDIA, on the left)
    Windows says:  laptop = 1, external = 2

The GDI name is allocated per adapter and skips numbers that other adapters
already took, so it drifts out of step with what the user sees in Settings.
The number Windows actually uses is the *path order* of the active display
configuration - the order `QueryDisplayConfig` returns the paths in.

So we ask the display configuration directly:

  * the number  = the path's position in the active-path list (1-based)
  * the layout = the source mode's position inside the virtual desktop, which
    is what makes the mini-map on the palette show a horizontal row, a
    vertical stack, or anything in between exactly as the user arranged it.

Everything here is best-effort: a machine where the call fails still gets the
old GDI-based numbers, so the palette never ends up empty.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w

user32 = ctypes.WinDLL("user32")

QDC_ONLY_ACTIVE_PATHS = 0x00000002

DISPLAYCONFIG_MODE_INFO_TYPE_SOURCE = 1
DISPLAYCONFIG_MODE_INFO_TYPE_TARGET = 2

DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME = 1
DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME = 2

# enough for any sane desk; the call reports back what it actually used
MAX_PATHS = 32
MAX_MODES = 128


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", w.DWORD), ("HighPart", w.LONG)]


class RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", w.UINT), ("Denominator", w.UINT)]


class PIXELFORMAT(ctypes.Structure):
    _fields_ = [("pixelRate", w.UINT), ("hSyncFreq", RATIONAL),
                ("vSyncFreq", RATIONAL), ("activeSize", RATIONAL)]


class POINTL(ctypes.Structure):
    _fields_ = [("x", w.LONG), ("y", w.LONG)]


class SOURCE_MODE(ctypes.Structure):
    _fields_ = [("width", w.UINT), ("height", w.UINT),
                ("pixelFormat", PIXELFORMAT), ("position", POINTL)]


class VIDEO_SIGNAL_INFO(ctypes.Structure):
    _fields_ = [("pixelRate", ctypes.c_uint64), ("hSyncFreq", RATIONAL),
                ("vSyncFreq", RATIONAL), ("activeSize", RATIONAL),
                ("videoStandard", w.UINT), ("scanLineOrdering", w.UINT)]


class TARGET_MODE(ctypes.Structure):
    _fields_ = [("targetVideoSignalInfo", VIDEO_SIGNAL_INFO)]


class ModeUnion(ctypes.Union):
    _fields_ = [("targetMode", TARGET_MODE), ("sourceMode", SOURCE_MODE)]


class MODE_INFO(ctypes.Structure):
    _fields_ = [("infoType", w.UINT), ("id", w.UINT), ("adapterId", LUID),
                ("modeInfo", ModeUnion)]


class PATH_SOURCE(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", w.UINT),
                ("modeInfoIdx", w.UINT), ("statusFlags", w.UINT)]


class PATH_TARGET(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", w.UINT), ("modeInfoIdx", w.UINT),
                ("outputTechnology", w.UINT), ("rotation", w.UINT),
                ("scaling", w.UINT), ("refreshRate", RATIONAL),
                ("scanLineOrdering", w.UINT), ("targetAvailable", w.BOOL),
                ("statusFlags", w.UINT)]


class PATH_INFO(ctypes.Structure):
    _fields_ = [("sourceInfo", PATH_SOURCE), ("targetInfo", PATH_TARGET),
                ("flags", w.UINT)]


class DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [("type", w.UINT), ("size", w.UINT),
                ("adapterId", LUID), ("id", w.UINT)]


class SOURCE_DEVICE_NAME(ctypes.Structure):
    # packed: the header carries no tail padding, so the struct is exactly
    # 20 + 64 bytes
    _pack_ = 1
    _fields_ = [("header", DEVICE_INFO_HEADER), ("viewGdiDeviceName", w.WCHAR * 32)]


class TARGET_DEVICE_NAME(ctypes.Structure):
    """420 bytes exactly - the size the API insists on.

    Getting this wrong is silent: the call just fails with
    ERROR_INVALID_PARAMETER, so the monitor's friendly name ("NE160QDM-NZB",
    "TYPE-C") would be missing.  The layout was found by measuring where the
    strings actually land in the buffer the API fills in.
    """
    _pack_ = 1
    _fields_ = [("header", DEVICE_INFO_HEADER), ("flags", w.UINT),
                ("outputDeviceTechnology", w.WCHAR * 6),
                ("monitorFriendlyDeviceName", w.WCHAR * 64),
                ("monitorDevicePath", w.WCHAR * 128)]


user32.QueryDisplayConfig.restype = w.LONG
user32.QueryDisplayConfig.argtypes = [
    w.UINT, ctypes.POINTER(w.UINT), ctypes.POINTER(PATH_INFO),
    ctypes.POINTER(w.UINT), ctypes.POINTER(MODE_INFO), ctypes.POINTER(LUID),
]
user32.DisplayConfigGetDeviceInfo.restype = w.LONG
user32.DisplayConfigGetDeviceInfo.argtypes = [ctypes.POINTER(DEVICE_INFO_HEADER)]


class DisplayInfo:
    """One entry of the system's display configuration."""

    __slots__ = ("number", "device", "friendly", "position", "size", "primary")

    def __init__(self, number: int, device: str, friendly: str,
                 position: tuple[int, int], size: tuple[int, int],
                 primary: bool = False):
        self.number = number      # the number Windows shows (1-based)
        self.device = device      # "\\.\DISPLAYN"
        self.friendly = friendly  # "Generic PnP Monitor", "Lenovo DisplayHDR"…
        self.position = position  # (x, y) inside the virtual desktop
        self.size = size          # (w, h) in pixels
        self.primary = primary

    def __repr__(self) -> str:
        return (f"<Display {self.number} {self.device} {self.friendly!r} "
                f"pos={self.position} size={self.size}>")


def _source_name(path: PATH_INFO) -> str:
    info = SOURCE_DEVICE_NAME()
    info.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME
    info.header.size = ctypes.sizeof(SOURCE_DEVICE_NAME)
    info.header.adapterId = path.sourceInfo.adapterId
    info.header.id = path.sourceInfo.id
    if user32.DisplayConfigGetDeviceInfo(ctypes.byref(info.header)) != 0:
        return ""
    return info.viewGdiDeviceName or ""


def _target_name(path: PATH_INFO) -> str:
    info = TARGET_DEVICE_NAME()
    info.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME
    info.header.size = ctypes.sizeof(TARGET_DEVICE_NAME)
    info.header.adapterId = path.targetInfo.adapterId
    info.header.id = path.targetInfo.id
    if user32.DisplayConfigGetDeviceInfo(ctypes.byref(info.header)) != 0:
        return ""
    return info.monitorFriendlyDeviceName or ""


def query() -> list[DisplayInfo]:
    """The active displays, numbered the way Windows numbers them.

    The path list is the system's own ordering, and the index of a path in
    that list is the number the user sees in Settings - so we keep the order
    and never renumber it ourselves.
    """
    paths = (PATH_INFO * MAX_PATHS)()
    modes = (MODE_INFO * MAX_MODES)()
    n_paths = w.UINT(MAX_PATHS)
    n_modes = w.UINT(MAX_MODES)

    # NOTE: the "call with NULL to get the count" pattern is *not* supported
    # here - it fails with ERROR_INVALID_PARAMETER on some systems.  Allocating
    # the arrays up front and letting the call fill them works everywhere.
    hr = user32.QueryDisplayConfig(
        QDC_ONLY_ACTIVE_PATHS, ctypes.byref(n_paths), paths,
        ctypes.byref(n_modes), modes, None,
    )
    if hr != 0:
        return []

    out: list[DisplayInfo] = []
    for i in range(n_paths.value):
        path = paths[i]
        device = _source_name(path)
        if not device:
            continue
        friendly = _target_name(path)

        position = (0, 0)
        size = (0, 0)
        idx = path.sourceInfo.modeInfoIdx
        if 0 <= idx < n_modes.value:
            mode = modes[idx]
            if mode.infoType == DISPLAYCONFIG_MODE_INFO_TYPE_SOURCE:
                pos = mode.modeInfo.sourceMode.position
                position = (int(pos.x), int(pos.y))
                size = (int(mode.modeInfo.sourceMode.width),
                        int(mode.modeInfo.sourceMode.height))

        out.append(DisplayInfo(
            number=i + 1,
            device=device,
            friendly=friendly,
            position=position,
            size=size,
        ))
    return out


def numbers_by_device() -> dict[str, int]:
    """{"\\\\.\\DISPLAY3": 2, ...} - the Windows number for each GDI name."""
    return {d.device: d.number for d in query()}


def arrangement(rects: dict[str, tuple[int, int, int, int]]) -> str:
    """A human word for how the displays are laid out.

    `rects` maps a GDI device name to its virtual-screen rect.  The judgement
    is made on those rects, not on the source-mode positions: when the panels
    sit on *different adapters* (a laptop screen on the iGPU and an external
    one on the dGPU, which is the common laptop + monitor case) each adapter
    reports its own source mode with the origin at (0, 0), so those positions
    say nothing about how the desktop is arranged.
    """
    if len(rects) <= 1:
        return "单屏"
    tops = {r[1] for r in rects.values()}
    lefts = {r[0] for r in rects.values()}
    if len(tops) == 1:
        return "横排"
    if len(lefts) == 1:
        return "竖排"
    return "错落"

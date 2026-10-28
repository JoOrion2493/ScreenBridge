"""Camera and microphone switches, done the way Windows actually allows.

**Microphone** - IAudioEndpointVolume::SetMute on the default capture endpoint.
That is exactly what the sound settings' mute button does: it affects every
application, needs no administrator rights, and is instant.

**Camera** - Windows has never shipped a public "turn the camera off" API.  The
隐私 → 相机 switch only writes ConsentStore, which blocks *new* streams per app;
the device stays alive, and apps that already hold it keep working.  What users
mean by "camera off" is the device-manager disable, i.e. CM_Disable_DevNode:
after that no application at all can get a frame.  It requires administrator
rights, so the resident process never elevates - it launches itself with
`runas` for the single call, which is also what ScreenBridge does.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import os
import subprocess
import sys
import threading
import time

from ctypes import POINTER, byref, c_void_p, c_int, c_uint, c_ulong

ole32 = ctypes.WinDLL("ole32")
shell32 = ctypes.WinDLL("shell32")
setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
cfgmgr32 = ctypes.WinDLL("cfgmgr32", use_last_error=True)

CLSCTX_ALL = 23
E_CAPTURE, E_RENDER, E_CONSOLE = 1, 0, 0
DEVICE_STATE_ACTIVE = 0x1

# CM_Get_DevNode_Status
DN_HAS_PROBLEM = 0x00000400
CM_PROB_DISABLED = 22
CR_SUCCESS = 0

CAMERA_CLASSES = (
    "{CA3E7AB9-B4C3-4AE6-8251-579EF933890F}",   # Camera
    "{6BDD1FC6-810F-11D0-BEC7-08002BE2092F}",   # Image
)


class GUID(ctypes.Structure):
    _fields_ = [("d1", c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort),
                ("d4", ctypes.c_ubyte * 8)]


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_int), ("ClassGuid", GUID),
                ("DevInst", ctypes.c_uint), ("Reserved", c_void_p)]


def _guid(text: str) -> GUID:
    g = GUID()
    ole32.CLSIDFromString(ctypes.c_wchar_p(text), byref(g))
    return g


CLSID_MMDEVICE_ENUMERATOR = _guid("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
IID_IMMDEVICE_ENUMERATOR = _guid("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
IID_IAUDIO_ENDPOINT_VOLUME = _guid("{5CDF2C82-841E-4546-9722-0CF74078229A}")


# ------------------------------------------------------------------- protos
setupapi.SetupDiGetClassDevsW.argtypes = [POINTER(GUID), c_void_p, c_void_p, c_uint]
setupapi.SetupDiGetClassDevsW.restype = c_void_p
setupapi.SetupDiEnumDeviceInfo.argtypes = [c_void_p, c_uint, POINTER(SP_DEVINFO_DATA)]
setupapi.SetupDiEnumDeviceInfo.restype = w.BOOL
setupapi.SetupDiGetDeviceInstanceIdW.argtypes = [
    c_void_p, POINTER(SP_DEVINFO_DATA), w.LPWSTR, c_int, POINTER(c_int)]
setupapi.SetupDiGetDeviceInstanceIdW.restype = w.BOOL
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [c_void_p]
setupapi.SetupDiDestroyDeviceInfoList.restype = w.BOOL

cfgmgr32.CM_Locate_DevNodeW.argtypes = [POINTER(c_uint), w.LPCWSTR, c_uint]
cfgmgr32.CM_Locate_DevNodeW.restype = ctypes.c_long
cfgmgr32.CM_Get_DevNode_Status.argtypes = [
    POINTER(c_uint), POINTER(c_uint), c_uint, c_uint]
cfgmgr32.CM_Get_DevNode_Status.restype = ctypes.c_long
cfgmgr32.CM_Disable_DevNode.argtypes = [c_uint, c_uint]
cfgmgr32.CM_Disable_DevNode.restype = ctypes.c_long
cfgmgr32.CM_Enable_DevNode.argtypes = [c_uint, c_uint]
cfgmgr32.CM_Enable_DevNode.restype = ctypes.c_long

ole32.CoInitialize.argtypes = [c_void_p]
ole32.CoInitialize.restype = ctypes.c_long
ole32.CoCreateInstance.argtypes = [
    POINTER(GUID), c_void_p, c_uint, POINTER(GUID), POINTER(c_void_p)]
ole32.CoCreateInstance.restype = ctypes.c_long

shell32.IsUserAnAdmin.argtypes = []
shell32.IsUserAnAdmin.restype = w.BOOL


def _vtable(ptr):
    return ctypes.cast(ptr, POINTER(POINTER(c_void_p)))[0]


def _call(ptr, index, restype, *argtypes):
    return ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(_vtable(ptr)[index])


def _release(ptr) -> None:
    """IUnknown::Release - index 2 on every COM interface."""
    if ptr:
        try:
            _call(ptr, 2, c_ulong)(ptr)
        except OSError:
            pass


def is_admin() -> bool:
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:                                        # pragma: no cover
        return False


# ------------------------------------------------------------------- COM init
_com_threads: set[int] = set()
_com_lock = threading.Lock()


def init_com() -> bool:
    """CoInitialize for the calling thread (STA, once).

    MMDeviceEnumerator is a COM object, so every thread that touches it has to
    have initialised COM first - including the worker that restores the devices
    on exit.  Doing it lazily keeps the entry point free of ordering rules.
    """
    tid = threading.get_ident()
    with _com_lock:
        if tid in _com_threads:
            return True
    hr = ole32.CoInitialize(None)
    if hr in (0, 1):                       # S_OK / S_FALSE (already initialised)
        with _com_lock:
            _com_threads.add(tid)
        return True
    return False


# -----------------------------------------------------------------microphone
def _capture_endpoint():
    """The default capture endpoint, or the first active one.

    Returns an IMMDevice pointer the caller must release, or None.
    """
    if not init_com():
        return None
    enumerator = c_void_p()
    hr = ole32.CoCreateInstance(byref(CLSID_MMDEVICE_ENUMERATOR), None, 1,
                                byref(IID_IMMDEVICE_ENUMERATOR), byref(enumerator))
    if hr != 0 or not enumerator:
        return None

    device = c_void_p()
    try:
        get_default = _call(enumerator, 4, ctypes.c_long, c_int, c_int,
                            POINTER(c_void_p))
        if get_default(enumerator, E_CAPTURE, E_CONSOLE, byref(device)) == 0 and device:
            return device

        # no default capture device: fall back to the first active endpoint so a
        # machine with an unused microphone still gets a working button
        collection = c_void_p()
        enum_ends = _call(enumerator, 3, ctypes.c_long, c_int, c_uint,
                          POINTER(c_void_p))
        if enum_ends(enumerator, E_CAPTURE, DEVICE_STATE_ACTIVE, byref(collection)) != 0:
            return None
        try:
            count = c_uint(0)
            _call(collection, 3, ctypes.c_long, POINTER(c_uint))(collection, byref(count))
            if count.value == 0:
                return None
            item = _call(collection, 4, ctypes.c_long, c_uint, POINTER(c_void_p))
            if item(collection, 0, byref(device)) == 0 and device:
                return device
            return None
        finally:
            _release(collection)
    finally:
        _release(enumerator)


def _endpoint_volume():
    device = _capture_endpoint()
    if not device:
        return None
    volume = c_void_p()
    try:
        activate = _call(device, 3, ctypes.c_long, POINTER(GUID), c_ulong,
                         c_void_p, POINTER(c_void_p))
        hr = activate(device, byref(IID_IAUDIO_ENDPOINT_VOLUME), CLSCTX_ALL,
                      None, byref(volume))
        return volume if hr == 0 and volume else None
    finally:
        _release(device)


def has_microphone() -> bool:
    device = _capture_endpoint()
    if not device:
        return False
    _release(device)
    return True


def mic_on() -> tuple[bool, bool]:
    """(device present, currently picking up sound)."""
    volume = _endpoint_volume()
    if not volume:
        return (False, False)
    try:
        muted = c_int(0)
        if _call(volume, 15, ctypes.c_long, POINTER(c_int))(volume, byref(muted)) != 0:
            return (False, False)
        return (True, muted.value == 0)
    finally:
        _release(volume)


def mic_set(on: bool) -> bool:
    """Mute (on=False) or unmute the default microphone system-wide."""
    volume = _endpoint_volume()
    if not volume:
        return False
    try:
        set_mute = _call(volume, 14, ctypes.c_long, c_int, c_void_p)
        return set_mute(volume, 0 if on else 1, None) == 0
    finally:
        _release(volume)


# ---------------------------------------------------------------------camera
def camera_devices() -> list[tuple[str, bool]]:
    """[(instance id, enabled)] for every camera-ish device that is present."""
    out: list[tuple[str, bool]] = []
    seen: set[str] = set()

    for cls in CAMERA_CLASSES:
        g = _guid(cls)
        devs = setupapi.SetupDiGetClassDevsW(byref(g), None, None, 0x2)  # PRESENT
        if not devs or devs == ctypes.c_void_p(-1).value:
            continue
        try:
            info = SP_DEVINFO_DATA()
            info.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
            index = 0
            while setupapi.SetupDiEnumDeviceInfo(devs, index, byref(info)):
                index += 1
                buf = ctypes.create_unicode_buffer(512)
                need = c_int(0)
                if not setupapi.SetupDiGetDeviceInstanceIdW(
                        devs, byref(info), buf, 512, byref(need)):
                    continue
                dev_id = buf.value
                if not dev_id or dev_id in seen:
                    continue
                seen.add(dev_id)
                out.append((dev_id, device_enabled(dev_id)))
        finally:
            setupapi.SetupDiDestroyDeviceInfoList(devs)
    return out


def device_enabled(instance_id: str) -> bool:
    """True unless the node is actually sitting in the "disabled" state."""
    dev_inst = c_uint(0)
    if cfgmgr32.CM_Locate_DevNodeW(byref(dev_inst), instance_id, 0) != CR_SUCCESS:
        return True
    status = c_uint(0)
    problem = c_uint(0)
    if cfgmgr32.CM_Get_DevNode_Status(byref(status), byref(problem), dev_inst, 0) != CR_SUCCESS:
        return True
    return not (status.value & DN_HAS_PROBLEM and problem.value == CM_PROB_DISABLED)


def camera_on() -> tuple[bool, bool]:
    """(device present, at least one camera enabled)."""
    devs = camera_devices()
    return (bool(devs), any(enabled for _id, enabled in devs))


def camera_set_all(on: bool) -> tuple[bool, str]:
    """Enable/disable every camera.  Needs administrator rights."""
    devs = camera_devices()
    if not devs:
        return (False, "未检测到摄像头设备")

    todo = [(dev_id, enabled) for dev_id, enabled in devs if enabled != on]
    if not todo:
        return (True, "已开启" if on else "已关闭")

    ok = True
    last = ""
    for dev_id, _enabled in todo:
        dev_inst = c_uint(0)
        code = cfgmgr32.CM_Locate_DevNodeW(byref(dev_inst), dev_id, 0)
        if code != CR_SUCCESS:
            ok, last = False, f"找不到设备节点（CR={code}）"
            continue
        fn = cfgmgr32.CM_Enable_DevNode if on else cfgmgr32.CM_Disable_DevNode
        code = fn(dev_inst, 0)
        if code != CR_SUCCESS:
            ok, last = False, f"操作失败（CR={code}），通常是没有管理员权限"

    if ok:
        return (True, "已启用" if on else "已禁用")
    return (False, last or "操作失败")


# ------------------------------------------------------- elevated one-shot arm
CAMERA_FLAG = "--camera-set"


def elevated_command(on: bool) -> list[str] | None:
    """The command that runs `camera_set_all` with administrator rights."""
    if getattr(sys, "frozen", False):
        return [sys.executable, CAMERA_FLAG, "on" if on else "off"]
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "sxsnap_entry.py")
    exe = sys.executable
    pyw = exe.replace("python.exe", "pythonw.exe")
    if os.path.exists(pyw):
        exe = pyw
    return [exe, script, CAMERA_FLAG, "on" if on else "off"]


def camera_set_elevated(on: bool, timeout: float = 45.0) -> tuple[bool, str]:
    """Disable/enable the cameras through a one-shot elevated copy of ourselves.

    Returns (ok, message).  A declined UAC prompt is not an error - it just
    means nothing changed, and the caller says so.
    """
    # never raise a consent dialog for a change that is not needed: this is
    # what keeps a stale "we turned it off" flag from asking for UAC on start
    has, state = camera_on()
    if not has:
        return (False, "未检测到摄像头设备")
    if state == on:
        return (True, "已开启" if on else "已关闭")

    cmd = elevated_command(on)
    if not cmd:
        return (False, "无法定位程序自身")

    # ShellExecute("runas") is what raises the consent dialog; ctypes keeps it
    # dependency-free.  sw_hide so no console flashes if the build has one.
    shell32.ShellExecuteW.argtypes = [w.HWND, w.LPCWSTR, w.LPCWSTR, w.LPCWSTR,
                                      w.LPCWSTR, c_int]
    shell32.ShellExecuteW.restype = c_void_p

    params = subprocess.list2cmdline(cmd[1:])
    code = int(shell32.ShellExecuteW(None, "runas", cmd[0], params, None, 0) or 0)
    if code <= 32:
        if code == 5:            # ERROR_ACCESS_DENIED / user said no
            return (False, "已取消管理员授权，摄像头未变更")
        return (False, f"无法启动管理员进程（{code}）")

    # We cannot wait on a ShellExecute'd process; poll the device state instead.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.35)
        has, state = camera_on()
        if has and state == on:
            return (True, "已启用" if on else "已禁用")
    return (False, "授权后摄像头状态未改变")

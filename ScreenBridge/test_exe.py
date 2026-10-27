"""Drive the packaged SXSnap.exe through the full gesture, end to end.

The real app is used unmodified; the *only* thing this harness does that the
shell normally does is move the dragged window along with the cursor.

Why: this sandbox swallows injected mouse messages.  GetAsyncKeyState still
reports the button correctly (so the exe's polling sees "button down") and
GetCursorPos / WindowFromPoint behave normally, but a synthetic LEFTDOWN never
reaches the window, so the shell never enters its modal move loop and the
window would sit still.  SXSnap's rule for "this is a drag" is exactly
"button down AND the frame followed the cursor", so the harness reproduces the
follow with SetWindowPos.  Everything downstream is the shipped code path:
detection -> palette under the cursor -> dwell on a chip -> layouts unfold ->
hover a zone -> release -> rcNormalPosition double-write.

Two gestures:
  1. titlebar drag -> rest on screen chip 1 -> layouts unfold -> rest on the
     bottom-right zone of the quad preset -> release -> exact zone rect
  2. titlebar drag -> rest on screen chip 2 -> release -> whole window hops to
     the other display, keeping its size.
"""

import ctypes
import ctypes.wintypes as w
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sxsnap import config, engine, win32, zones
from sxsnap.palette import Palette

u = win32.user32
u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u.mouse_event.argtypes = [w.DWORD, w.DWORD, w.DWORD, w.DWORD, ctypes.c_void_p]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_int, ctypes.c_uint]
u.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
u.FindWindowW.argtypes = [w.LPCWSTR, w.LPCWSTR]
u.FindWindowW.restype = w.HWND
u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.PostMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]

LEFTDOWN, LEFTUP = 0x0002, 0x0004
PALETTE_CLASS = Palette.CLASS_NAME

DRAG = {"hwnd": 0, "dx": 0, "dy": 0, "w": 0, "h": 0}
BEFORE: set = set()        # windows that existed before the test opened anything


# --------------------------------------------------------------------- utils
def top_levels():
    hits = set()

    def cb(h, l):
        if u.IsWindowVisible(h):
            hits.add(h)
        return True

    u.EnumWindows(win32.ENUMPROC(cb), 0)
    return hits


def launch_notepad():
    before = top_levels()
    BEFORE.update(before)
    proc = subprocess.Popen(["notepad.exe"])
    deadline = time.time() + 10
    while time.time() < deadline:
        time.sleep(0.25)
        for h in top_levels() - before:
            if not engine.is_snappable(h) or win32.window_class(h) == PALETTE_CLASS:
                continue
            r = win32.window_rect(h)
            if r[2] - r[0] > 200 and r[3] - r[1] > 150:
                return proc, h
    return proc, 0


def wait_ready(budget=15.0):
    """The onefile exe has to unpack ~8 MB and start Python before it registers
    its window class and arms the poll timer.  Waiting a fixed 2 s is a coin
    flip on a cold cache, so wait for the real signal instead."""
    deadline = time.time() + budget
    while time.time() < deadline:
        if u.FindWindowW(PALETTE_CLASS, None):
            time.sleep(0.4)          # create() runs just before SetTimer
            return True
        time.sleep(0.2)
    return False


def palette_rect():
    h = u.FindWindowW(PALETTE_CLASS, None)
    if not h:
        return None
    rc = w.RECT()
    u.GetWindowRect(h, ctypes.byref(rc))
    if rc.right - rc.left <= 1:
        return None      # created at startup but not shown yet
    return (rc.left, rc.top, rc.right, rc.bottom)


def predict(pt, mons):
    """Where the palette should end up if it anchors at `pt`.

    Runs the shipped geometry code in this process, so the numbers the harness
    aims at are the same ones the exe will paint - and any drift between the
    two (a stale build, say) shows up as a failed placement.
    """
    idx = 0
    for i, m in enumerate(mons):
        if m.rect[0] <= pt[0] < m.rect[2] and m.rect[1] <= pt[1] < m.rect[3]:
            idx = i
            break
    p = Palette()
    p.monitors = mons
    p.scale = mons[idx].dpi / 96.0
    p.sel_mon = idx
    p.stage = 0
    p._anchor(pt)
    chip_origin, chip_m = p.origin, p.metrics()
    p.stage = 1
    p._place_window()
    lay_origin, lay_m = p.origin, p.metrics()
    p.destroy()
    return {
        "pt": pt, "scale": p.scale, "sel": idx,
        "chip_origin": chip_origin, "chip_m": chip_m,
        "lay_origin": lay_origin, "lay_m": lay_m,
    }


def far_point(prect, prefer=None, need=380):
    """A cursor point the palette is guaranteed to re-anchor to.

    The app only re-anchors when the pointer is more than 220 * scale away
    from the panel, so a polite little hop leaves it exactly where it was -
    and every later coordinate is then measured against the wrong frame.
    """
    def dist(pt):
        dx = max(prect[0] - pt[0], pt[0] - prect[2], 0)
        dy = max(prect[1] - pt[1], pt[1] - prect[3], 0)
        return (dx * dx + dy * dy) ** 0.5

    if prefer and dist(prefer) >= need:
        return prefer

    vl, vt, vr, vb = win32.virtual_screen()
    xs = [vl + 300, (vl + vr) // 4, (vl + vr) // 2, vr * 3 // 4, vr - 300]
    ys = [vt + 220, (vt + vb) // 2, vb - 260]
    cands = [(x, y) for y in ys for x in xs]
    for c in cands:
        if dist(c) >= need:
            return c
    return max(cands, key=dist)


def anchor_at(prect, mons, prefer=None):
    """Move the pointer far enough that the palette re-anchors, then predict
    the geometry there and check the live window against it."""
    pt = far_point(prect, prefer)
    move_cursor(*pt)
    time.sleep(0.32)
    g = predict(pt, mons)
    got = palette_rect()
    want = (g["chip_origin"][0], g["chip_origin"][1],
            g["chip_origin"][0] + g["chip_m"]["w"],
            g["chip_origin"][1] + g["chip_m"]["h"])
    print(f"  anchor {pt} -> palette {got} predicted {want}")
    g["matched"] = bool(got) and max(abs(got[i] - want[i]) for i in range(4)) <= 2
    return g


def chip_pt(g, idx=None):
    """Centre of a screen chip (default: the display the palette is on)."""
    i = g["sel"] if idx is None else idx
    cx, cy, cw, chh = g["chip_m"]["chips"][i]
    return (g["chip_origin"][0] + cx + cw / 2.0,
            g["chip_origin"][1] + cy + chh / 2.0)


def zone_pt(g, li, zi):
    tx, ty, tw, th = g["lay_m"]["thumbs"][li]
    zx, zy, zw, zh = zones.LAYOUTS[li][2][zi]
    return (g["lay_origin"][0] + tx + (zx + zw / 2.0) * tw,
            g["lay_origin"][1] + ty + (zy + zh / 2.0) * th)


def chip_panel(g, stage=1):
    """Screen rect of the chip row, from the geometry of a given stage."""
    m = g["chip_m"] if stage == 0 else g["lay_m"]
    ox, oy = g["chip_origin"] if stage == 0 else g["lay_origin"]
    cb = m["chip_box"]
    return (ox + cb[0], oy + cb[1], ox + cb[0] + cb[2], oy + cb[1] + cb[3])


# ----------------------------------------------------------------- the drag
def move_cursor(x, y):
    """Move the cursor, and drag the grabbed window along with it - the part
    the shell's move loop normally does."""
    u.SetCursorPos(int(x), int(y))
    if DRAG["hwnd"]:
        u.SetWindowPos(
            DRAG["hwnd"], 0,
            int(x) - DRAG["dx"], int(y) - DRAG["dy"], DRAG["w"], DRAG["h"],
            win32.SWP_NOZORDER | win32.SWP_NOACTIVATE,
        )


def grab_titlebar(hwnd):
    u.ShowWindow(hwnd, win32.SW_RESTORE)
    time.sleep(0.2)
    u.SetForegroundWindow(hwnd)
    time.sleep(0.45)
    r = win32.window_rect(hwnd)
    gx, gy = (r[0] + r[2]) // 2, r[1] + 16
    DRAG.update(hwnd=hwnd, dx=gx - r[0], dy=gy - r[1],
                w=r[2] - r[0], h=r[3] - r[1])
    u.SetCursorPos(gx, gy)
    time.sleep(0.2)
    u.mouse_event(LEFTDOWN, 0, 0, 0, None)
    # let the poll see the button *before* the frame starts moving: the app
    # samples the origin rect when it notices the press, so moving first would
    # leave it comparing against an already-moved rect (real drags never do
    # that - they keep moving)
    time.sleep(0.25)
    for dx in (6, 13, 21):
        move_cursor(gx + dx, gy)
        time.sleep(0.07)
    return gx, gy


def ensure_palette(gx, gy, budget=1.4):
    """Keep nudging until the panel shows up - a coarse drag must not be the
    difference between pass and fail."""
    deadline = time.time() + budget
    step = 21
    while time.time() < deadline:
        prect = palette_rect()
        if prect:
            return prect
        step += 6
        move_cursor(gx + step, gy)
        time.sleep(0.12)
    return palette_rect()


def release():
    u.mouse_event(LEFTUP, 0, 0, 0, None)
    DRAG.update(hwnd=0)


# ------------------------------------------------------------------ gestures
def gesture_zone(mons, li, zi, anchor):
    cfg = config.load()
    gap, margin = int(cfg.get("gap", 8)), int(cfg.get("margin", 0))
    expect = zones.zones_for(mons[0], zones.LAYOUT_IDS[li], gap, margin)[zi]

    gx, gy = grab_titlebar(TEST_HWND)
    prect0 = ensure_palette(gx, gy)
    if not prect0:
        release()
        return None, expect, False

    g = anchor_at(prect0, mons, anchor)
    prect = palette_rect()
    print("  palette (stage 0):", prect)
    if not prect:
        release()
        return None, expect, g["matched"]

    move_cursor(*chip_pt(g, 0))      # chip 1 -> zones land on display 1
    time.sleep(0.45)                 # dwell_ms default 90 -> layouts unfold
    prect1 = palette_rect()
    want1 = (g["lay_origin"][0], g["lay_origin"][1],
             g["lay_origin"][0] + g["lay_m"]["w"], g["lay_origin"][1] + g["lay_m"]["h"])
    # the whole point of the fix: the chip row must not move a pixel when the
    # layout row unfolds under it
    pinned_ok = (prect[0] == chip_panel(g, 0)[0] and prect[1] == chip_panel(g, 0)[1]
                 and chip_panel(g, 0) == chip_panel(g, 1))
    print("  palette (stage 1):", prect1, "predicted:", want1, "chip row pinned:", pinned_ok)

    move_cursor(*zone_pt(g, li, zi))
    time.sleep(0.35)
    release()
    time.sleep(1.8)                  # settle + animation
    return engine.visible_rect(TEST_HWND), expect, pinned_ok and g["matched"]


def gesture_screen(mons, chip, anchor):
    mon = mons[chip]
    cl, ct, cr, cb = engine.visible_rect(TEST_HWND)
    ww, hh = cr - cl, cb - ct
    wl, wt, wr, wb = mon.work
    aw, ah = wr - wl, wb - wt
    maxw, maxh = int(aw * 0.9), int(ah * 0.9)
    if ww > maxw or hh > maxh:
        k = min(maxw / float(ww), maxh / float(hh))
        ww, hh = int(ww * k), int(hh * k)
    x = wl + (aw - ww) // 2
    y = wt + (ah - hh) // 2
    expect = (x, y, x + ww, y + hh)

    gx, gy = grab_titlebar(TEST_HWND)
    prect0 = ensure_palette(gx, gy)
    if not prect0:
        release()
        return None, expect

    g = anchor_at(prect0, mons, anchor)
    move_cursor(*chip_pt(g, chip))
    time.sleep(0.45)                 # it may unfold; the chip stays where it is
    release()
    time.sleep(1.8)
    return engine.visible_rect(TEST_HWND), expect


# ---------------------------------------------------------------------- main
def main():
    global TEST_HWND
    win32.enable_dpi_awareness()
    here = os.path.dirname(os.path.abspath(__file__))
    exe = os.path.join(here, "SXSnap.exe")
    if not os.path.exists(exe):
        print("SXSnap.exe missing")
        return 1
    print(f"exe: {exe}  ({os.path.getsize(exe)/1024/1024:.1f} MB)")

    cfg = config.load()
    cfg["enabled"] = True
    cfg["first_run_done"] = True
    config.save(cfg)
    print("config:", {k: cfg.get(k) for k in ("enabled", "gap", "margin", "dwell_ms")})

    running = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq SXSnap.exe"],
        capture_output=True, text=True, encoding="gbk", errors="replace").stdout
    if "SXSnap.exe" in running:
        print("an SXSnap instance is already running - close it first")
        return 1

    np, hwnd = launch_notepad()
    if not hwnd:
        print("could not open notepad")
        np.terminate()
        return 1
    TEST_HWND = hwnd
    print("notepad hwnd:", hwnd, win32.window_class(hwnd))

    app = subprocess.Popen([exe])
    ready = wait_ready()
    print("SXSnap alive:", app.poll() is None, "pid:", app.pid, "ready:", ready)
    if app.poll() is not None or not ready:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(app.pid)], capture_output=True)
        np.terminate()
        return 1

    mons = win32.enumerate_monitors()
    scale = mons[0].dpi / 96.0
    print(f"monitors: {len(mons)}  scale: {scale:.2f}")

    ok, failures = True, []

    li = zones.LAYOUT_IDS.index("quad")
    got, expect, stayed = gesture_zone(mons, li, 3, (900, 500))
    print("1) zone  quad / bottom-right")
    print("   expect:", expect)
    print("   got   :", got)
    if got is None:
        ok = False
        failures.append("palette never appeared (gesture 1)")
    else:
        d = [abs(got[i] - expect[i]) for i in range(4)]
        print("   delta :", d)
        if max(d) > 6:
            ok = False
            failures.append(f"zone snap off by {max(d)}px")
    if not stayed:
        ok = False
        failures.append("the chip row moved when the layouts unfolded")

    if len(mons) > 1:
        got2, expect2 = gesture_screen(mons, 1, (3000, 500))
        print("2) screen -> 2nd display")
        print("   expect:", expect2)
        print("   got   :", got2)
        if got2 is None:
            ok = False
            failures.append("palette never appeared (gesture 2)")
        else:
            d = [abs(got2[i] - expect2[i]) for i in range(4)]
            print("   delta :", d)
            if max(d) > 6:
                ok = False
                failures.append(f"cross-screen off by {max(d)}px")
    else:
        print("2) single display - cross-screen gesture skipped")

    print()
    for f in failures:
        print("FAIL:", f)
    print("RESULT:", "PASS" if ok else "FAIL")

    # close the scratch notepad windows we opened; WM_CLOSE on an empty
    # document is silent, unlike terminate() which can orphan a Win11 tab
    for h in top_levels() - BEFORE:
        if win32.window_class(h) == "Notepad":
            u.PostMessageW(h, 0x0010, 0, 0)
    time.sleep(0.6)

    for p in (app, np):
        # onefile boots a child process; terminate() alone orphans it and the
        # orphan keeps the singleton mutex, silently blocking the next run
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                           capture_output=True)
            p.wait(timeout=5)
        except Exception:
            pass
    print("cleaned up")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

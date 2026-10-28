"""Tests for the display configuration and the palette size presets.

Three things are checked here:

  1. the numbers on the palette chips are the ones *Windows* shows, not the
     ones in the GDI device name (they drift apart on a multi-adapter desk)
  2. the mini-map really lays the chips out the way the desktop is arranged
  3. the large / medium / small palette sizes change every dimension of the
     panel, and the setting survives a round trip through the config file
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sxsnap import config, displays, palette, win32  # noqa: E402


def main() -> int:
    win32.enable_dpi_awareness()
    ok = True

    # ---------------------------------------------------------------- 1. numbers
    mons = win32.enumerate_monitors()
    print("monitors:")
    for m in mons:
        print(f"  Windows #{m.number}  {m.device}  rect={m.rect} primary={m.primary}")

    cfg_numbers = displays.numbers_by_device()
    print("display configuration says:", cfg_numbers)

    for m in mons:
        if m.device in cfg_numbers and m.number != cfg_numbers[m.device]:
            ok = False
            print(f"  FAIL: {m.device} shows {m.number} but the system says "
                  f"{cfg_numbers[m.device]}")

    # the numbers must be unique and start at 1 - that is what Settings shows
    nums = sorted(m.number for m in mons)
    if nums and nums != list(range(1, len(nums) + 1)):
        ok = False
        print(f"  FAIL: the display numbers are not 1..N: {nums}")
    else:
        print(f"  numbers are 1..{len(nums)} and unique")

    # --------------------------------------------------------- 2. the arrangement
    pal = palette.Palette()
    pal.monitors = mons
    pal.scale = 1.0
    pal.stage = 0
    m = pal.metrics(0)

    # the chips must keep the relative order of the real screens: whichever
    # screen sits further left on the desktop has to be drawn further left
    for a in range(len(mons)):
        for b in range(len(mons)):
            if a == b:
                continue
            ra, rb = mons[a].rect, mons[b].rect
            ca, cb = m["chips"][a], m["chips"][b]
            same_band = abs(ra[1] - rb[1]) < 40
            if same_band and ra[0] < rb[0] and ca[0] > cb[0]:
                ok = False
                print(f"  FAIL: screen {mons[a].number} is left of {mons[a].number} "
                      f"on the desktop but drawn to the right")
    print(f"  arrangement: {displays.arrangement({mm.device: mm.rect for mm in mons})}")

    # the caption the chip panel shows must name the same arrangement
    word = displays.arrangement({mm.device: mm.rect for mm in mons})
    if pal.arrangement() != word:
        ok = False
        print(f"  FAIL: the palette says '{pal.arrangement()}' but the "
              f"arrangement is '{word}'")
    else:
        print(f"  the panel caption says '{pal.arrangement()}'")

    # and the caption must have room to sit in
    _sw, _sh, _mw, mh, _rects, _mx, my = pal._chip_geo()
    if my < 15 * pal.scale:
        ok = False
        print(f"  FAIL: no room for the caption (band {my:.1f}px)")

    # ---------------------------------------------------------- 3. the sizes
    sizes = []
    for name in palette.SIZE_ORDER:
        pal.size = name
        pal.scale = mons[0].dpi / 96.0 * palette.size_factor(name)
        st = pal.metrics(1)
        sizes.append((name, st["w"], st["h"], st["layout"][2], st["layout"][3]))
        print(f"  {name:<7} stage1={st['w']}x{st['h']}  layout={st['layout'][2]}x{st['layout'][3]}")

    # every step must actually shrink the panel
    for (n0, w0, h0, _, _), (n1, w1, h1, _, _) in zip(sizes, sizes[1:]):
        if not (w1 < w0 and h1 < h0):
            ok = False
            print(f"  FAIL: {n1} is not smaller than {n0} ({w1}x{h1} vs {w0}x{h0})")

    # the largest size must be the old look, i.e. factor 1.0
    if palette.size_factor("large") != 1.0:
        ok = False
        print("  FAIL: the large size is not the original look")

    # and the setting must survive a save/load round trip
    saved = dict(config.DEFAULTS)
    saved["palette_size"] = "small"
    config.save(saved)
    back = config.load()
    if back.get("palette_size") != "small":
        ok = False
        print(f"  FAIL: the size setting did not survive: {back.get('palette_size')}")
    else:
        print("  the size setting round-trips through the config file")
    # restore the default so the next run is not left on "small"
    saved["palette_size"] = "large"
    config.save(saved)

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

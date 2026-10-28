"""Build a perfectly circular .ico from logo.png.

Two things matter here and both are easy to get wrong:

  1. The four corners must be *fully* transparent.  A plain resize of an RGBA
     image blends in the colour of the transparent pixels, which leaves a pale
     grey haze in the corners - that is the "shadow in the corners" effect.
     So alpha is resampled in *premultiplied* space and the result is masked
     against a mathematically exact circle with a supersampled edge.
  2. Small sizes get a real 32bpp DIB entry, not PNG: the shell's tray and
     alt-tab paths are ancient and expect BMP for 16..64 px.  128 and 256 are
     PNG, which is what Vista+ expects for large icons.
"""

from __future__ import annotations

import io
import os
import struct

from PIL import Image, ImageDraw

SRC = r"C:\Users\Legion\Pictures\logo.png"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sxsnap.ico")
BALL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ball.png")
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
BALL_SIZE = 256
SUPERSAMPLE = 8


def blue_outer_radius(src: Image.Image) -> float:
    """Distance from the centre to the outer edge of the blue ring.

    The source is a blue ring with a ~4 px white margin before the canvas edge.
    Cutting at the canvas edge leaves a white halo that is very visible on a
    dark taskbar, so the disc is cut exactly where the ring ends instead.
    """
    px = src.load()
    side = src.width
    cx = cy = (side - 1) / 2.0
    best = 0.0
    import math

    for i in range(720):
        ang = i * math.pi / 360.0
        ca, sa = math.cos(ang), math.sin(ang)
        for r in range(int(side / 2), 0, -1):
            x, y = int(round(cx + r * ca)), int(round(cy + r * sa))
            if not (0 <= x < side and 0 <= y < side):
                continue
            pr, pg, pb, pa = px[x, y]
            if pa > 200 and pb > 200 and pr < 170:   # the blue of the ring
                best = max(best, r)
                break
    return best


def circular_alpha(size: int, frac: float = 1.0) -> Image.Image:
    """An 8x supersampled circle mask: antialiased, no corner residue."""
    big = size * SUPERSAMPLE
    mask = Image.new("L", (big, big), 0)
    draw = ImageDraw.Draw(mask)
    inset = int(round((big - big * frac) / 2.0))
    draw.ellipse((inset, inset, big - 1 - inset, big - 1 - inset), fill=255)
    return mask.resize((size, size), Image.LANCZOS)


MASTER_FRAC = 1.0   # circle radius as a fraction of the half-canvas


def make_master() -> Image.Image:
    global MASTER_FRAC
    src = Image.open(SRC).convert("RGBA")
    if src.width != src.height:
        side = min(src.width, src.height)
        src = src.crop(
            ((src.width - side) // 2, (src.height - side) // 2,
             (src.width + side) // 2, (src.height + side) // 2)
        )
    side = src.width

    r = blue_outer_radius(src)
    MASTER_FRAC = min(1.0, (2.0 * r + 1.0) / side)
    print(f"blue ring outer radius = {r:.1f}px of {side} -> mask {MASTER_FRAC:.4f}")

    out = src.copy()
    out.putalpha(circular_alpha(side, MASTER_FRAC))
    return out


def resize_pm(img: Image.Image, size: int) -> Image.Image:
    """Resize in premultiplied space so transparent pixels cannot bleed."""
    if size == img.width:
        return img
    pm = img.convert("RGBa")
    small = pm.resize((size, size), Image.LANCZOS).convert("RGBA")
    # re-assert the circle: resampling can brighten a corner by a fraction
    mask = circular_alpha(size, MASTER_FRAC)
    from PIL import ImageChops
    small.putalpha(ImageChops.multiply(small.getchannel("A"), mask))
    return small


def dib_entry(img: Image.Image) -> bytes:
    """A 32bpp ICO bitmap entry: BITMAPINFOHEADER + BGRA + AND mask."""
    size = img.width
    px = img.load()

    header = struct.pack(
        "<IiiHHIIiiII",
        40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0,
    )

    rows = []
    for y in range(size - 1, -1, -1):          # bottom-up
        row = bytearray()
        for x in range(size):
            r, g, b, a = px[x, y]
            row += bytes((b, g, r, a))
        rows.append(bytes(row))
    xor = b"".join(rows)

    mask_stride = ((size + 31) // 32) * 4
    and_mask = bytes(mask_stride * size)       # all zero: alpha governs

    return header + xor + and_mask


def png_entry(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def build() -> str:
    master = make_master()
    images = [(s, resize_pm(master, s)) for s in SIZES]

    blobs = []
    for size, img in images:
        blobs.append(png_entry(img) if size >= 128 else dib_entry(img))

    count = len(images)
    offset = 6 + 16 * count
    head = struct.pack("<HHH", 0, 1, count)
    directory = b""
    for (size, _img), blob in zip(images, blobs):
        w = 0 if size >= 256 else size
        h = 0 if size >= 256 else size
        directory += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)

    with open(OUT, "wb") as fh:
        fh.write(head + directory + b"".join(blobs))

    # The floating ball draws this one at runtime: GDI+ can open PNG but not
    # ICO, so the disc has to exist as a plain image as well.
    resize_pm(master, BALL_SIZE).save(BALL, format="PNG", optimize=True)
    return OUT


def verify() -> None:
    im = Image.open(OUT)
    print(f"{OUT}  {os.path.getsize(OUT)} bytes  sizes={sorted(im.info.get('sizes', []))}")
    for size, _img in [(s, None) for s in SIZES]:
        im.size = (size, size)
        frame = im.convert("RGBA")
        corners = [frame.getpixel(p)[3] for p in
                   [(0, 0), (size - 1, 0), (0, size - 1), (size - 1, size - 1)]]
        centre = frame.getpixel((size // 2, size // 2))[3]
        # a diagonal point at 0.72 * r must still be inside the disc
        d = int(size * 0.5 + size * 0.5 * 0.72 * 0.7071)
        edge = frame.getpixel((min(d, size - 1), min(d, size - 1)))[3]
        print(f"  {size:3d}px  corners={corners} centre_a={centre} edge_a={edge}")


if __name__ == "__main__":
    build()
    verify()

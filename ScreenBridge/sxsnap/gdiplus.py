"""GDI+ surface for the drag palette.

Why GDI+ instead of plain GDI: the palette has to look like the ASUS one -
rounded corners, soft shadow, smooth 1px-ish borders. Plain GDI `RoundRect`
gives hard, obviously aliased corners on a dark background.

Why a DIB + UpdateLayeredWindow instead of SetLayeredWindowAttributes: the
latter only does a single window-wide alpha, which cannot express "rounded
panel with a shadow and transparent margins" - the corners would be square.
Per-pixel alpha fixes that, and GDI+ must then draw into a *premultiplied*
32bpp bitmap, which is what `PixelFormat32bppPARGB` + `AC_SRC_ALPHA` expect.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
try:
    gdip = ctypes.WinDLL("gdiplus", use_last_error=True)
except OSError:  # pragma: no cover
    gdip = None

PixelFormat32bppPARGB = 0x000E200B

SmoothingModeAntiAlias = 4
TextRenderingHintClearTypeGridFit = 5
TextRenderingHintAntiAlias = 4
PixelOffsetModeHighQuality = 2
CompositingQualityHighQuality = 2
InterpolationModeHighQualityBicubic = 7
CompositingModeSourceOver = 0
CompositingModeSourceCopy = 1

UnitPixel = 2
FontStyleRegular = 0
FontStyleBold = 1
StringAlignmentCenter = 1
StringAlignmentNear = 0

ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
DIB_RGB_COLORS = 0


def ARGB(a: int, r: int, g: int, b: int) -> int:
    """GDI+ ARGB is a little-endian 0xAARRGGBB integer."""
    return ((a & 0xFF) << 24) | ((r & 0xFF) << 16) | ((g & 0xFF) << 8) | (b & 0xFF)


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", w.DWORD),
        ("biWidth", w.LONG),
        ("biHeight", w.LONG),
        ("biPlanes", w.WORD),
        ("biBitCount", w.WORD),
        ("biCompression", w.DWORD),
        ("biSizeImage", w.DWORD),
        ("biXPelsPerMeter", w.LONG),
        ("biYPelsPerMeter", w.LONG),
        ("biClrUsed", w.DWORD),
        ("biClrImportant", w.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", w.DWORD * 3)]


class RectF(ctypes.Structure):
    _fields_ = [
        ("X", ctypes.c_float),
        ("Y", ctypes.c_float),
        ("Width", ctypes.c_float),
        ("Height", ctypes.c_float),
    ]


class GdiplusStartupInput(ctypes.Structure):
    _fields_ = [
        ("GdiplusVersion", ctypes.c_uint),
        ("DebugEventCallback", ctypes.c_void_p),
        ("SuppressBackgroundThread", ctypes.c_int),
        ("SuppressExternalCodecs", ctypes.c_int),
    ]


_token = None


def startup() -> None:
    global _token
    if _token is not None or gdip is None:
        return
    token = ctypes.c_size_t()
    inp = GdiplusStartupInput(1, None, 0, 0)
    gdip.GdiplusStartup(ctypes.byref(token), ctypes.byref(inp), None)
    _token = token

    # ---- prototypes (all __stdcall, all return GpStatus) -----------------
    P = ctypes.c_void_p
    F = ctypes.c_float
    I = ctypes.c_int

    def proto(name, args):
        fn = getattr(gdip, name)
        fn.argtypes = args
        fn.restype = I
        return fn

    global GdipCreateBitmapFromScan0, GdipGetImageGraphicsContext, GdipGraphicsClear
    global GdipSetSmoothingMode, GdipSetTextRenderingHint, GdipSetPixelOffsetMode
    global GdipSetCompositingQuality, GdipSetCompositingMode
    global GdipCreateSolidFill, GdipCreatePen1, GdipCreatePath, GdipAddPathArc
    global GdipAddPathRectangle, GdipAddPathEllipse, GdipAddPathLine
    global GdipClosePathFigure, GdipFillPath, GdipDrawPath, GdipDeletePath
    global GdipDeleteBrush, GdipDeletePen, GdipDeleteGraphics, GdipDisposeImage
    global GdipCreateFontFamilyFromName, GdipCreateFont, GdipCreateStringFormat
    global GdipSetStringFormatAlign, GdipSetStringFormatLineAlign
    global GdipDrawString, GdipDeleteFont, GdipDeleteFontFamily
    global GdipDeleteStringFormat, GdipSetClipPath, GdipResetClip
    global GdipCreateBitmapFromFile, GdipDrawImageRectI, GdipSetInterpolationMode

    proto("GdipCreateBitmapFromScan0", [I, I, I, I, P, ctypes.POINTER(P)])
    proto("GdipGetImageGraphicsContext", [P, ctypes.POINTER(P)])
    proto("GdipGraphicsClear", [P, ctypes.c_uint])
    proto("GdipSetSmoothingMode", [P, I])
    proto("GdipSetTextRenderingHint", [P, I])
    proto("GdipSetPixelOffsetMode", [P, I])
    proto("GdipSetCompositingQuality", [P, I])
    proto("GdipSetCompositingMode", [P, I])
    proto("GdipCreateSolidFill", [ctypes.c_uint, ctypes.POINTER(P)])
    proto("GdipCreatePen1", [ctypes.c_uint, F, I, ctypes.POINTER(P)])
    proto("GdipCreatePath", [I, ctypes.POINTER(P)])
    proto("GdipAddPathArc", [P, F, F, F, F, F, F])
    proto("GdipAddPathRectangle", [P, F, F, F, F])
    proto("GdipAddPathEllipse", [P, F, F, F, F])
    proto("GdipAddPathLine", [P, F, F, F, F])
    proto("GdipClosePathFigure", [P])
    proto("GdipFillPath", [P, P, P])
    proto("GdipDrawPath", [P, P, P])
    proto("GdipDeletePath", [P])
    proto("GdipDeleteBrush", [P])
    proto("GdipDeletePen", [P])
    proto("GdipDeleteGraphics", [P])
    proto("GdipDisposeImage", [P])
    proto("GdipCreateFontFamilyFromName", [ctypes.c_wchar_p, P, ctypes.POINTER(P)])
    proto("GdipCreateFont", [P, F, I, I, ctypes.POINTER(P)])
    proto("GdipCreateStringFormat", [I, ctypes.c_ushort, ctypes.POINTER(P)])
    proto("GdipSetStringFormatAlign", [P, I])
    proto("GdipSetStringFormatLineAlign", [P, I])
    proto("GdipDrawString", [P, ctypes.c_wchar_p, I, P, ctypes.POINTER(RectF), P, P])
    proto("GdipDeleteFont", [P])
    proto("GdipDeleteFontFamily", [P])
    proto("GdipDeleteStringFormat", [P])
    proto("GdipSetClipPath", [P, P, I])
    proto("GdipResetClip", [P])
    proto("GdipCreateBitmapFromFile", [ctypes.c_wchar_p, ctypes.POINTER(P)])
    proto("GdipDrawImageRectI", [P, P, I, I, I, I])
    proto("GdipSetInterpolationMode", [P, I])


# --------------------------------------------------------------- user32/gdi32
user32.UpdateLayeredWindow.argtypes = [
    w.HWND, w.HDC, ctypes.POINTER(w.POINT), ctypes.POINTER(w.SIZE),
    w.HDC, ctypes.POINTER(w.POINT), w.DWORD, ctypes.POINTER(BLENDFUNCTION), w.DWORD,
]
user32.UpdateLayeredWindow.restype = w.BOOL

gdi32.CreateDIBSection.argtypes = [
    w.HDC, ctypes.POINTER(BITMAPINFO), ctypes.c_uint,
    ctypes.POINTER(ctypes.c_void_p), w.HANDLE, w.DWORD,
]
gdi32.CreateDIBSection.restype = w.HBITMAP

gdi32.CreateCompatibleDC.argtypes = [w.HDC]
gdi32.CreateCompatibleDC.restype = w.HDC

gdi32.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]
gdi32.SelectObject.restype = w.HGDIOBJ

gdi32.DeleteObject.argtypes = [w.HGDIOBJ]
gdi32.DeleteObject.restype = w.BOOL

gdi32.DeleteDC.argtypes = [w.HDC]
gdi32.DeleteDC.restype = w.BOOL


class Surface:
    """A premultiplied 32bpp ARGB canvas that can be blitted as a layered window."""

    def __init__(self, width: int, height: int) -> None:
        startup()
        self.width = max(1, int(width))
        self.height = max(1, int(height))

        bmi = BITMAPINFO()
        hdr = bmi.bmiHeader
        hdr.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        hdr.biWidth = self.width
        hdr.biHeight = -self.height          # top-down: y grows downward
        hdr.biPlanes = 1
        hdr.biBitCount = 32
        hdr.biCompression = 0                # BI_RGB
        hdr.biSizeImage = self.width * self.height * 4

        self._bits = ctypes.c_void_p()
        self.hbm = gdi32.CreateDIBSection(
            None, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(self._bits), None, 0
        )
        if not self.hbm:
            raise OSError(f"CreateDIBSection failed ({ctypes.get_last_error()})")

        self.memdc = gdi32.CreateCompatibleDC(None)
        self._old = gdi32.SelectObject(self.memdc, self.hbm)

        self.bitmap = ctypes.c_void_p()
        gdip.GdipCreateBitmapFromScan0(
            self.width, self.height, self.width * 4,
            PixelFormat32bppPARGB, self._bits, ctypes.byref(self.bitmap),
        )

        self.g = ctypes.c_void_p()
        gdip.GdipGetImageGraphicsContext(self.bitmap, ctypes.byref(self.g))
        gdip.GdipSetSmoothingMode(self.g, SmoothingModeAntiAlias)
        gdip.GdipSetTextRenderingHint(self.g, TextRenderingHintAntiAlias)
        gdip.GdipSetPixelOffsetMode(self.g, PixelOffsetModeHighQuality)
        gdip.GdipSetCompositingQuality(self.g, CompositingQualityHighQuality)
        gdip.GdipSetCompositingMode(self.g, CompositingModeSourceOver)

        self._fonts: dict[tuple[int, int], tuple[int, int]] = {}
        self._images: dict[str, object] = {}

    # ------------------------------------------------------------ primitives
    def clear(self, argb: int = 0) -> None:
        gdip.GdipGraphicsClear(self.g, argb)

    def _path(self, x, y, ww, hh, r):
        path = ctypes.c_void_p()
        gdip.GdipCreatePath(0, ctypes.byref(path))
        x, y, ww, hh = float(x), float(y), float(ww), float(hh)
        r = max(0.0, min(float(r), ww / 2.0, hh / 2.0))
        if r <= 0.5:
            gdip.GdipAddPathRectangle(path, x, y, ww, hh)
        else:
            d = r * 2.0
            gdip.GdipAddPathArc(path, x, y, d, d, 180, 90)
            gdip.GdipAddPathArc(path, x + ww - d, y, d, d, 270, 90)
            gdip.GdipAddPathArc(path, x + ww - d, y + hh - d, d, d, 0, 90)
            gdip.GdipAddPathArc(path, x, y + hh - d, d, d, 90, 90)
        gdip.GdipClosePathFigure(path)
        return path

    def fill_round(self, x, y, ww, hh, r, argb) -> None:
        if ww <= 0 or hh <= 0:
            return
        brush = ctypes.c_void_p()
        gdip.GdipCreateSolidFill(argb, ctypes.byref(brush))
        path = self._path(x, y, ww, hh, r)
        gdip.GdipFillPath(self.g, brush, path)
        gdip.GdipDeletePath(path)
        gdip.GdipDeleteBrush(brush)

    def stroke_round(self, x, y, ww, hh, r, argb, width=1.0) -> None:
        if ww <= 0 or hh <= 0:
            return
        pen = ctypes.c_void_p()
        gdip.GdipCreatePen1(argb, float(width), UnitPixel, ctypes.byref(pen))
        path = self._path(x + width / 2.0, y + width / 2.0,
                          max(0.5, ww - width), max(0.5, hh - width), r)
        gdip.GdipDrawPath(self.g, pen, path)
        gdip.GdipDeletePath(path)
        gdip.GdipDeletePen(pen)

    # ------------------------------------------------------------------ text
    def ellipse(self, x, y, ww, hh, argb) -> None:
        """Filled ellipse, sized to the given box."""
        if ww <= 0 or hh <= 0:
            return
        brush = ctypes.c_void_p()
        gdip.GdipCreateSolidFill(argb, ctypes.byref(brush))
        path = ctypes.c_void_p()
        gdip.GdipCreatePath(0, ctypes.byref(path))
        gdip.GdipAddPathEllipse(path, float(x), float(y), float(ww), float(hh))
        gdip.GdipClosePathFigure(path)
        gdip.GdipFillPath(self.g, brush, path)
        gdip.GdipDeletePath(path)
        gdip.GdipDeleteBrush(brush)

    def ring(self, x, y, ww, hh, argb, width=1.0) -> None:
        """Stroked ellipse - the outline of a circle."""
        self._stroke(lambda p: gdip.GdipAddPathEllipse(
            p, float(x), float(y), float(ww), float(hh)), argb, width)

    def line(self, x1, y1, x2, y2, argb, width=1.0) -> None:
        self._stroke(lambda p: gdip.GdipAddPathLine(
            p, float(x1), float(y1), float(x2), float(y2)), argb, width)

    def arc(self, x, y, ww, hh, start, sweep, argb, width=1.0) -> None:
        self._stroke(lambda p: gdip.GdipAddPathArc(
            p, float(x), float(y), float(ww), float(hh),
            float(start), float(sweep)), argb, width)

    def poly(self, points, argb, width=1.0, closed=True) -> None:
        """A polyline - used for the gear, whose teeth are a polygon."""
        if len(points) < 2:
            return

        def add(path):
            for i in range(1, len(points)):
                gdip.GdipAddPathLine(
                    path, float(points[i - 1][0]), float(points[i - 1][1]),
                    float(points[i][0]), float(points[i][1]))
            if closed:
                gdip.GdipAddPathLine(
                    path, float(points[-1][0]), float(points[-1][1]),
                    float(points[0][0]), float(points[0][1]))

        self._stroke(add, argb, width, close=closed)

    def _stroke(self, build, argb, width, close=False) -> None:
        pen = ctypes.c_void_p()
        gdip.GdipCreatePen1(argb, float(width), UnitPixel, ctypes.byref(pen))
        path = ctypes.c_void_p()
        gdip.GdipCreatePath(0, ctypes.byref(path))
        build(path)
        if close:
            gdip.GdipClosePathFigure(path)
        gdip.GdipDrawPath(self.g, pen, path)
        gdip.GdipDeletePath(path)
        gdip.GdipDeletePen(pen)

    # ----------------------------------------------------------------- images
    def image(self, path: str, x, y, ww, hh) -> bool:
        """Draw a bitmap file scaled into the box (cached per path)."""
        bmp = self._images.get(path)
        if bmp is None:
            bmp = ctypes.c_void_p()
            if gdip.GdipCreateBitmapFromFile(ctypes.c_wchar_p(path),
                                             ctypes.byref(bmp)) != 0 or not bmp:
                self._images[path] = False
                return False
            self._images[path] = bmp
        if bmp is False:
            return False
        gdip.GdipSetInterpolationMode(self.g, InterpolationModeHighQualityBicubic)
        gdip.GdipDrawImageRectI(self.g, bmp, int(round(x)), int(round(y)),
                                int(round(ww)), int(round(hh)))
        return True

    # ------------------------------------------------------------------- clip
    def clip_round(self, x, y, ww, hh, r) -> None:
        path = self._path(x, y, ww, hh, r)
        gdip.GdipSetClipPath(self.g, path, 1)      # 1 == CombineModeReplace
        gdip.GdipDeletePath(path)

    def clip_reset(self) -> None:
        gdip.GdipResetClip(self.g)

    def _font(self, size: int, bold: int = 0):
        key = (size, bold)
        hit = self._fonts.get(key)
        if hit is not None:
            return hit
        fam = ctypes.c_void_p()
        ok = 0
        for face in ("Segoe UI", "Microsoft YaHei UI", "Arial"):
            ok = gdip.GdipCreateFontFamilyFromName(face, None, ctypes.byref(fam))
            if ok == 0:
                break
        if ok != 0:
            return None
        font = ctypes.c_void_p()
        gdip.GdipCreateFont(fam, float(size), bold, UnitPixel, ctypes.byref(font))
        self._fonts[key] = (fam, font)
        return self._fonts[key]

    def text(self, s: str, x, y, ww, hh, size, argb, bold=0, align=StringAlignmentCenter):
        got = self._font(int(size), bold)
        if got is None:
            return
        _fam, font = got
        fmt = ctypes.c_void_p()
        gdip.GdipCreateStringFormat(0, 0, ctypes.byref(fmt))
        gdip.GdipSetStringFormatAlign(fmt, align)
        gdip.GdipSetStringFormatLineAlign(fmt, StringAlignmentCenter)
        brush = ctypes.c_void_p()
        gdip.GdipCreateSolidFill(argb, ctypes.byref(brush))
        rc = RectF(float(x), float(y), float(ww), float(hh))
        gdip.GdipDrawString(self.g, s, -1, font, ctypes.byref(rc), fmt, brush)
        gdip.GdipDeleteBrush(brush)
        gdip.GdipDeleteStringFormat(fmt)

    # --------------------------------------------------------------- present
    def blit(self, hwnd: int, screen_x: int, screen_y: int) -> None:
        pt_dst = w.POINT(int(screen_x), int(screen_y))
        size = w.SIZE(self.width, self.height)
        pt_src = w.POINT(0, 0)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        user32.UpdateLayeredWindow(
            hwnd, None, ctypes.byref(pt_dst), ctypes.byref(size),
            self.memdc, ctypes.byref(pt_src), 0, ctypes.byref(blend), ULW_ALPHA,
        )

    def dispose(self) -> None:
        for fam, font in self._fonts.values():
            gdip.GdipDeleteFont(font)
            gdip.GdipDeleteFontFamily(fam)
        self._fonts.clear()
        for bmp in self._images.values():
            if bmp is not False and bmp:
                gdip.GdipDisposeImage(bmp)
        self._images.clear()
        if self.g:
            gdip.GdipDeleteGraphics(self.g)
            self.g = None
        if self.bitmap:
            gdip.GdipDisposeImage(self.bitmap)
            self.bitmap = None
        if self.memdc:
            gdi32.SelectObject(self.memdc, self._old)
            gdi32.DeleteDC(self.memdc)
            self.memdc = None
        if self.hbm:
            gdi32.DeleteObject(self.hbm)
            self.hbm = None

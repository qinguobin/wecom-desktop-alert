# -*- coding: utf-8 -*-
"""
截图 + OCR 探测：验证能不能读到企业微信窗口里的聊天内容。

用法： D:/Python312/python.exe tools/test_screenocr.py [可选：保存截图文件名]
会列出所有企微窗口，逐个截图 -> OCR，打印识别出的文字行。
"""
import os
import sys
import zlib
import struct
import ctypes
import asyncio
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

PW_RENDERFULLCONTENT = 0x00000002
DIB_RGB_COLORS = 0
SRCCOPY = 0x00CC0020


# ---------- 纯标准库 PNG 编码 ----------
def png_bytes(bgra, w, h, stride):
    """bgra: bytes，含 padding。返回 PNG 文件内容"""
    raw = bytearray()
    rowsize = w * 3
    for y in range(h):
        off = y * stride
        raw.append(0)  # filter type 0
        row = bgra[off:off + w * 4]
        # BGRA -> RGB
        for x in range(w):
            b = row[x * 4]
            g = row[x * 4 + 1]
            r = row[x * 4 + 2]
            raw += bytes((r, g, b))
    assert len(raw) == (rowsize + 1) * h

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    hdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", hdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + chunk(b"IEND", b""))


# ---------- 窗口枚举 ----------
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetClassNameW.restype = ctypes.c_int
user32.IsWindowVisible.restype = wintypes.BOOL


def _wins():
    out = []

    @EnumWindowsProc
    def cb(h, _):
        if not user32.IsWindowVisible(h):
            return True
        n = user32.GetWindowTextLengthW(h)
        title = ""
        if n:
            b = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(h, b, n + 1)
            title = b.value
        cb2 = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, cb2, 256)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        out.append((int(h), title, cb2.value, int(pid.value)))
        return True

    user32.EnumWindows(cb, 0)
    return out


def _proc_name(pid):
    h = kernel32.OpenProcess(0x1000, False, pid)
    if not h:
        return "?"
    try:
        buf = ctypes.create_unicode_buffer(260)
        size = wintypes.DWORD(260)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
    finally:
        kernel32.CloseHandle(h)
    return "?"


def wecom_windows():
    """返回企微窗口 [(hwnd, title)]，主窗口标题是「企业微信」，会话窗口标题是会话名"""
    res = []
    for h, title, cls, pid in _wins():
        if _proc_name(pid).lower() == "wxwork.exe":
            res.append((h, title))
    return res


# ---------- 截图 ----------
def capture(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        return None, 0, 0
    hdc = user32.GetWindowDC(hwnd)
    if not hdc:
        return None, 0, 0
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mem, bmp)
    gdi32.BitBlt(mem, 0, 0, w, h, hdc, 0, 0, SRCCOPY)
    bmi = struct.pack(
        "<IiiHHIIiiII", 40, w, -h, 1, 32, 0, w * h * 4, 0, 0, 0, 0)
    buf = (ctypes.c_char * (w * h * 4))()
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(
        (ctypes.c_char * 40).from_buffer_copy(bmi)), DIB_RGB_COLORS)
    gdi32.SelectObject(mem, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)
    return bytes(buf), w, h


# ---------- OCR ----------
_engine = None


def get_engine():
    global _engine
    if _engine is None:
        from winsdk.windows.media.ocr import OcrEngine
        from winsdk.windows.globalization import Language
        _engine = OcrEngine.try_create_from_language(Language("zh-Hans-CN"))
        if _engine is None:
            _engine = OcrEngine.try_create_from_user_profile_languages()
    return _engine


async def _ocr_async(png):
    from winsdk.windows.storage.streams import InMemoryRandomAccessStream, Buffer
    from winsdk.windows.graphics.imaging import (
        BitmapDecoder, BitmapPixelFormat, BitmapAlphaMode)
    s = InMemoryRandomAccessStream()
    buf = bytearray(png)
    wbuf = Buffer(len(buf))
    wbuf.length = len(buf)
    with memoryview(wbuf) as mv:
        mv[:] = buf
    await s.write_async(wbuf)
    s.seek(0)
    dec = await BitmapDecoder.create_async(s)
    sb = await dec.get_software_bitmap_async(
        BitmapPixelFormat.BGRA8, BitmapAlphaMode.PREMULTIPLIED)
    eng = get_engine()
    result = await eng.recognize_async(sb)
    return [l.text for l in result.lines]


def ocr(png):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_ocr_async(png))
    finally:
        loop.close()


def main():
    wins = wecom_windows()
    print("企微窗口数量:", len(wins))
    if not wins:
        print("没有找到企微窗口")
        return
    save = sys.argv[1] if len(sys.argv) > 1 else None
    for h, title in wins:
        data, w, hh = capture(h)
        if not data:
            print("[skip] %s 截图失败" % title)
            continue
        p = png_bytes(data, w, hh, w * 4)
        if save and w > 300 and hh > 300:
            name = save.replace(".png", "") + ("_%s" % (title or "win")) + ".png"
            with open(os.path.join(ROOT, "data", name), "wb") as f:
                f.write(p)
            print("截图已保存:", os.path.join(ROOT, "data", name))
        try:
            lines = ocr(p)
        except Exception as e:
            print("[%s] OCR 失败: %r" % (title, e))
            continue
        print("=" * 60)
        print("窗口: %r  (%dx%d)  OCR 行数=%d" % (title, w, hh, len(lines)))
        for i, ln in enumerate(lines):
            print("  %2d| %s" % (i, ln))


if __name__ == "__main__":
    main()

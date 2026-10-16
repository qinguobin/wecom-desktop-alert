# -*- coding: utf-8 -*-
"""对比不同放大倍数下的 OCR 质量，找最优参数"""
import os
import sys
import struct
import ctypes
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from test_screenocr import wecom_windows, capture, png_bytes, ocr, _proc_name

gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
SRCCOPY = 0x00CC0020
HALFTONE = 4


def capture_scaled(hwnd, scale):
    """截图并按 scale 倍高质量放大，返回 (bgra, w*scale, h*scale, stride)"""
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        return None, 0, 0, 0
    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mem, bmp)
    gdi32.BitBlt(mem, 0, 0, w, h, hdc, 0, 0, SRCCOPY)

    W, H = w * scale, h * scale
    mem2 = gdi32.CreateCompatibleDC(hdc)
    bmp2 = gdi32.CreateCompatibleBitmap(hdc, W, H)
    old2 = gdi32.SelectObject(mem2, bmp2)
    gdi32.SetStretchBltMode(mem2, HALFTONE)
    gdi32.SetBrushOrgEx(mem2, 0, 0, 0)
    gdi32.StretchBlt(mem2, 0, 0, W, H, mem, 0, 0, w, h, SRCCOPY)

    bmi = ctypes.cast(ctypes.create_string_buffer(
        struct.pack("<IiiHHIIiiII", 40, W, -H, 1, 32, 0, W * H * 4, 0, 0, 0, 0)),
        ctypes.c_void_p)
    buf = (ctypes.c_char * (W * H * 4))()
    gdi32.GetDIBits(mem2, bmp2, 0, H, buf, bmi, 0)
    gdi32.SelectObject(mem, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    gdi32.SelectObject(mem2, old2)
    gdi32.DeleteObject(bmp2)
    gdi32.DeleteDC(mem2)
    user32.ReleaseDC(hwnd, hdc)
    return bytes(buf), W, H, W * 4


def main():
    wins = [x for x in wecom_windows() if x[1] == "企业微信"]
    if not wins:
        wins = wecom_windows()
    hwnd, title = wins[0]
    print("目标窗口:", title)
    for scale in (1, 2, 3):
        data, W, H, stride = capture_scaled(hwnd, scale)
        p = png_bytes(data, W, H, stride)
        lines = ocr(p)
        print("=" * 60)
        print("scale=%d  (%dx%d)  行数=%d" % (scale, W, H, len(lines)))
        for i, ln in enumerate(lines):
            print("  %2d| %s" % (i, ln))


if __name__ == "__main__":
    main()

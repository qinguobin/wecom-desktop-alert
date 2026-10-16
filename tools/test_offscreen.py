# -*- coding: utf-8 -*-
"""
把企微主窗口移到屏幕外（不最小化），验证这样还能不能实时读到内容。
结束时会把窗口挪回原位。

用法： D:/Python312/python.exe tools/test_offscreen.py [秒数]
"""
import sys
import time
import hashlib
import ctypes
from ctypes import wintypes
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import screen as S

u = ctypes.WinDLL("user32", use_last_error=True)
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010


def main():
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    mains = [(h, t) for h, t in S.wecom_windows() if t == S.MAIN_TITLE]
    if not mains:
        print("没找到企微主窗口")
        return
    hwnd = mains[0][0]
    r = wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    ox, oy = r.left, r.top
    print("原位置:", ox, oy, " 最小化?", u.IsIconic(hwnd))
    u.SetWindowPos(hwnd, 0, -3000, -3000, 0, 0,
                   SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
    print("已移到屏幕外 (-3000,-3000)，最小化?", u.IsIconic(hwnd), flush=True)
    prev = None
    end = time.time() + secs
    n = 0
    try:
        while time.time() < end:
            n += 1
            bgra, w, h = S.capture_scaled(hwnd, 2)
            lines = S.ocr(bgra, w, h)
            ll = [d["text"] for d in S.parse_list(lines, 0.15, 0.38)
                  if S._line_y(d) >= 0.06]
            key = hashlib.md5("|".join(ll).encode()).hexdigest()[:8]
            tag = "" if key == prev else "   <== 变化!"
            print("%3d %s 最小化=%d 屏幕外=%s 指纹=%s%s" % (
                n, time.strftime("%H:%M:%S"), u.IsIconic(hwnd),
                (r.left < 0), key, tag), flush=True)
            if tag:
                for x in ll[:5]:
                    print("        ", x, flush=True)
            prev = key
            time.sleep(3)
    finally:
        u.SetWindowPos(hwnd, 0, ox, oy, 0, 0,
                       SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
        print("已挪回原位:", ox, oy)


if __name__ == "__main__":
    main()

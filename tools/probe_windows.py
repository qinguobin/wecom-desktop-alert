# -*- coding: utf-8 -*-
"""诊断工具：看看企业微信窗口的控件结构，以及提醒小组件是否在运行。"""
import ctypes
from ctypes import wintypes

u = ctypes.WinDLL("user32")
EnumWindows = u.EnumWindows
EnumChildWindows = u.EnumChildWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
EnumChildProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
GetWindowTextW = u.GetWindowTextW
GetWindowTextLengthW = u.GetWindowTextLengthW
GetClassNameW = u.GetClassNameW


def win_text(hwnd):
    n = GetWindowTextLengthW(hwnd)
    if not n:
        return ""
    b = ctypes.create_unicode_buffer(n + 1)
    GetWindowTextW(hwnd, b, n + 1)
    return b.value


def win_class(hwnd):
    b = ctypes.create_unicode_buffer(256)
    GetClassNameW(hwnd, b, 256)
    return b.value


titles = []


def cb(hwnd, _):
    if u.IsWindowVisible(hwnd):
        titles.append((hwnd, win_text(hwnd), win_class(hwnd)))
    return True


EnumWindows(EnumWindowsProc(cb), 0)

print("=== 顶层窗口（含类名）===")
for h, t, c in titles:
    if t:
        print(f"  [{c}] {t!r}")

print()
print("=== 企业微信窗口 ===")
wecom = [h for h, t, c in titles if "企业微信" in t or "WeCom" in t]
for h in wecom:
    print(f"  hwnd={h} class={win_class(h)}")
    kids = []

    def kcb(k, _):
        kids.append((win_class(k), win_text(k)))
        return True
    EnumChildWindows(h, EnumChildProc(kcb), 0)
    for c, t in kids[:15]:
        print("     child: [%s] %r" % (c, t[:40]))
    print(f"     child count = {len(kids)}")

print()
print("=== UIA 控件树（企业微信）===")
try:
    import uiautomation as auto
    for h in wecom:
        ctl = auto.ControlFromHandle(h)
        nodes = []

        def walk(c, depth):
            if depth > 6 or len(nodes) >= 120:
                return
            try:
                for ch in c.GetChildren():
                    nodes.append((depth, ch.ControlTypeName, ch.ClassName, (ch.Name or "")[:40]))
                    walk(ch, depth + 1)
            except Exception as e:
                nodes.append((depth, "ERR", "", str(e)[:40]))
        walk(ctl, 0)
        for d, ty, cn, nm in nodes[:120]:
            print(f"  {'  ' * d}{ty} [{cn}] {nm!r}")
        print(f"  UIA nodes captured: {len(nodes)}")
except ImportError:
    print("  uiautomation 未安装")

print()
print("=== 提醒小组件 ===")
found = [t for _, t, _ in titles if "待处理" in t]
print("  ", found if found else "(未找到)")

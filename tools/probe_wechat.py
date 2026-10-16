"""探测个人微信(Weixin)窗口结构，看能否读取消息内容。"""
import ctypes
import sys
from ctypes import wintypes

sys.path.insert(0, r"D:\WeComDesktopAlert")
import screen as S

u = ctypes.WinDLL("user32")

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def all_windows():
    out = []

    def cb(h, _):
        if u.IsWindowVisible(h):
            n = u.GetWindowTextLengthW(h)
            b = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(h, b, n + 1)
            cls = ctypes.create_unicode_buffer(256)
            u.GetClassNameW(h, cls, 256)
            out.append((h, b.value, cls.value))
        return True

    u.EnumWindows(EnumWindowsProc(cb), 0)
    return out


def child_classes(hwnd, depth=0, limit=25):
    """枚举子窗口类名，看是否是 Flutter / DirectUI"""
    out = []

    def cb(h, _):
        cls = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(h, cls, 256)
        n = u.GetWindowTextLengthW(h)
        b = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(h, b, n + 1)
        out.append((cls.value, b.value))
        return len(out) < limit

    u.EnumChildWindows(hwnd, ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(cb), 0)
    return out


print("=== 全部可见窗口（含微信） ===")
for h, t, c in all_windows():
    if t and ("微信" in t or "WeChat" in t or "Weixin" in t):
        r = wintypes.RECT()
        u.GetWindowRect(h, ctypes.byref(r))
        print("  hwnd=%d 标题=%r class=%s 矩形=%dx%d 最小化=%d"
              % (h, t, c, r.right - r.left, r.bottom - r.top, u.IsIconic(h)))

print()
print("=== 微信主窗口内部结构 ===")
targets = [(h, t, c) for h, t, c in all_windows()
           if c in ("WeChatMainWndForPC", "WeChatMainWndForStore", "WeixinMainWndForPC")
           or (t == "微信")]

if not targets:
    print("  没找到微信主窗口")
else:
    for h, t, c in targets:
        print("  主窗口 hwnd=%d 标题=%r class=%s 最小化=%d" % (h, t, c, u.IsIconic(h)))
        ch = child_classes(h)
        print("  子窗口数=%d" % len(ch))
        for cls, txt in ch[:12]:
            print("    子: class=%-28s text=%r" % (cls, txt[:30]))

        # 尝试 OCR
        print("  --- 尝试屏幕 OCR ---")
        try:
            bgra, w, hh = S.capture_scaled(h, 2)
            lines = S.ocr(bgra, w, hh)
            print("  OCR 识别到 %d 行:" % len(lines))
            for d in lines[:25]:
                xs = [wd[1] for wd in d["words"]]
                print("     y=%.3f x=%.3f | %s" % (S._line_y(d), sum(xs) / len(xs), d["text"]))
        except Exception as e:
            print("  OCR 失败:", e)

# -*- coding: utf-8 -*-
"""
通知探针 2：不预判窗口类型，抓取所有「新出现」的顶层窗口并导出其 UIA 文本树。

用法： D:/Python312/python.exe tools/probe_toast2.py [持续秒数，默认240]
期间请让别人（或手机端企微）给你发一条企微消息。
结果写入 D:/WeComDesktopAlert/data/toast.log
"""
import os
import sys
import time
import ctypes
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

LOG = os.path.join(ROOT, "data", "toast.log")

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.restype = ctypes.c_int
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowTextLengthW.restype = ctypes.c_int
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

try:
    import uiautomation as auto
    UIA_OK = True
except Exception:
    UIA_OK = False


def snapshot():
    """返回 {hwnd: (class, title, pid, visible, rect)}"""
    out = {}

    @EnumWindowsProc
    def cb(h, _):
        if user32.IsWindowVisible(h):
            n = user32.GetWindowTextLengthW(h)
            title = ""
            if n:
                b = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(h, b, n + 1)
                title = b.value
            cb2 = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(h, cb2, 256)
            cls = cb2.value
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            r = wintypes.RECT()
            user32.GetWindowRect(h, ctypes.byref(r))
            out[int(h)] = (cls, title, int(pid.value),
                           (r.left, r.top, r.right - r.left, r.bottom - r.top))
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return out


def proc_name(pid):
    h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
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


def uia_texts(hwnd, depth=0, out=None, limit=40):
    if out is None:
        out = []
    if depth > 6 or len(out) >= limit:
        return out
    try:
        c = auto.ControlFromHandle(hwnd)
        collect(c, 0, out, limit)
    except Exception:
        pass
    return out


def collect(ctrl, depth, out, limit):
    if depth > 6 or len(out) >= limit:
        return
    try:
        for ch in ctrl.GetChildren():
            nm = (ch.Name or "").strip()
            ct = ch.ControlTypeName or ""
            if nm:
                out.append("%s|%s" % (ct, nm[:60]))
            collect(ch, depth + 1, out, limit)
    except Exception:
        pass


def main():
    seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 240
    print("探针2 已启动 %d 秒，请让别人给你发一条企微消息" % seconds)
    print("日志：", LOG)
    f = open(LOG, "w", encoding="utf-8")
    f.write("probe2 start uia=%s\n" % UIA_OK)
    prev = snapshot()
    known = {h: v for h, v in prev.items()}
    # 预先记录进程名，减少抖动
    pnames = {}
    for h, (cls, title, pid, rect) in prev.items():
        if pid not in pnames:
            pnames[pid] = proc_name(pid)
    end = time.time() + seconds
    while time.time() < end:
        cur = snapshot()
        for h, (cls, title, pid, rect) in cur.items():
            if h in known:
                continue
            known[h] = (cls, title, pid, rect)
            if pid not in pnames:
                pnames[pid] = proc_name(pid)
            pn = pnames.get(pid, "?")
            line = "[NEW] hwnd=%s cls=%s title=%r pid=%s proc=%s rect=%s" % (
                h, cls, title[:40], pid, pn, rect)
            f.write(line + "\n")
            f.flush()
            print(line)
            if UIA_OK:
                ts = uia_texts(h)
                if ts:
                    tl = "[  UIA] %s" % ts[:10]
                    f.write(tl + "\n")
                    f.flush()
                    print(tl)
        # 窗口消失清理
        for h in list(known.keys()):
            if h not in cur:
                known.pop(h, None)
        time.sleep(0.25)
    f.write("probe2 end\n")
    f.close()
    print("探针2 结束")


if __name__ == "__main__":
    main()

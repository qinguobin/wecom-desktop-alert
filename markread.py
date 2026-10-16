# -*- coding: utf-8 -*-
"""
勾掉待办时，把企业微信里对应会话的未读角标也清掉（标记已读）。

企业微信主窗口是 Flutter 渲染的（FLUTTERVIEW），默认不暴露无障碍树，
所以这里用两级策略，都失败也只是记日志，绝不影响小组件本身：
  1) UIA：找到会话列表里该会话 -> 右键 -> 点"标记为已读"（若控件可见）
  2) 快捷键：激活企业微信 -> Ctrl+F 打开搜索 -> 粘贴会话名 -> 回车打开会话
     （打开会话即视为已读，角标消失）-> Esc 收起 -> 切回原来的窗口

配置（config.json 的 mark_read 段）：
  enabled          总开关
  use_uia_first    是否先试 UIA
  fallback_hotkey  UIA 失败时是否用快捷键
  search_hotkey    企微的搜索快捷键，默认 ctrl+f
"""
import ctypes
import logging
import time
from ctypes import wintypes

log = logging.getLogger("wecom.markread")

try:
    import uiautomation as auto
    UIA_OK = True
except Exception:
    UIA_OK = False

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

VK_CONTROL, VK_RETURN, VK_ESCAPE = 0x11, 0x0D, 0x1B
KEYEVENTF_KEYUP = 0x0002
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

# 64 位下句柄会被截断成 32 位，必须显式声明类型，否则剪贴板读写都失败
user32.GetClipboardData.restype = ctypes.c_void_p
user32.GetClipboardData.argtypes = [ctypes.c_uint]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalUnlock.restype = ctypes.c_int
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
user32.SetClipboardData.restype = ctypes.c_void_p
user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

EnumWindows = user32.EnumWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
GetWindowTextW = user32.GetWindowTextW
GetWindowTextLengthW = user32.GetWindowTextLengthW


def _find_wecom_hwnd():
    found = []

    def cb(hwnd, _):
        n = GetWindowTextLengthW(hwnd)
        if n and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(n + 1)
            GetWindowTextW(hwnd, buf, n + 1)
            if "企业微信" in buf.value or "WeCom" in buf.value:
                found.append(hwnd)
        return True

    EnumWindows(EnumWindowsProc(cb), 0)
    return found[0] if found else None


def _press(vk, extra=0):
    user32.keybd_event(vk, 0, extra, 0)
    user32.keybd_event(vk, 0, extra | KEYEVENTF_KEYUP, 0)


def _ctrl_key(ch):
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    _press(ord(ch.upper()))
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def _get_clipboard_text():
    if not user32.OpenClipboard(0):
        return ""
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return ""
        p = kernel32.GlobalLock(h)
        if not p:
            return ""
        try:
            return ctypes.wstring_at(p)
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def _set_clipboard_text(text):
    if not user32.OpenClipboard(0):
        return False
    try:
        user32.EmptyClipboard()
        data = (text + "\0").encode("utf-16-le")
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data) + 2)
        p = kernel32.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        kernel32.GlobalUnlock(h)
        user32.SetClipboardData(CF_UNICODETEXT, h)
        return True
    except Exception:
        return False
    finally:
        user32.CloseClipboard()


def _uia_mark_read(hwnd, sender):
    """UIA 路线：找到会话 -> 右键 -> 标记已读"""
    if not UIA_OK:
        return False, "uiautomation 不可用"
    try:
        root = auto.ControlFromHandle(hwnd)
    except Exception as e:
        return False, "无法获取控件：%s" % e

    hits = []

    def walk(c, depth):
        if depth > 8 or len(hits) >= 20:
            return
        try:
            for ch in c.GetChildren():
                nm = (ch.Name or "").strip()
                if nm and (sender in nm or nm in sender):
                    hits.append(ch)
                walk(ch, depth + 1)
        except Exception:
            pass

    walk(root, 0)
    if not hits:
        return False, "UIA 未找到会话（企业微信是 Flutter 界面，通常读不到）"

    target = hits[-1]
    try:
        target.RightClick(waitTime=0.1)
        time.sleep(0.35)
        # 菜单项里找"已读"
        menu = None
        for _ in range(10):
            for ch in auto.GetRootControl().GetChildren():
                def find(c, depth):
                    if depth > 6:
                        return None
                    try:
                        for k in c.GetChildren():
                            if "已读" in (k.Name or ""):
                                return k
                            r = find(k, depth + 1)
                            if r:
                                return r
                    except Exception:
                        pass
                    return None
                menu = find(ch, 0)
                if menu:
                    break
            if menu:
                break
            time.sleep(0.1)
        if menu:
            menu.Click(waitTime=0.1)
            return True, "已在企业微信中标记已读"
        target.Click(waitTime=0.1)
        return True, "已打开会话（角标清除）"
    except Exception as e:
        return False, "UIA 点击失败：%s" % e


def _hotkey_mark_read(sender, cfg, hwnd):
    """快捷键路线：搜索会话名 -> 回车打开 -> 会话即已读"""
    try:
        import capture
        capture.pause_global(3.0)
    except Exception:
        pass
    old = _get_clipboard_text()
    _set_clipboard_text(sender)
    try:
        # 打开企微搜索框：优先按坐标点击（可校准），否则用快捷键
        offset = cfg.get("click_search_offset")
        if offset:
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            user32.SetCursorPos(rect.left + int(offset[0]), rect.top + int(offset[1]))
            user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
            user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
        else:
            _ctrl_key(cfg.get("search_key", "f"))
        time.sleep(0.25)
        # 粘贴会话名
        _ctrl_key("v")
        time.sleep(0.45)
        # 回车打开会话
        _press(VK_RETURN)
        time.sleep(0.35)
        _press(VK_ESCAPE)
        return True, "已在企业微信中打开会话（角标清除）"
    except Exception as e:
        return False, "快捷键执行失败：%s" % e
    finally:
        try:
            _set_clipboard_text(old)
        except Exception:
            pass


def mark_conversation_read(sender, cfg=None):
    """返回 (ok, 说明文字)"""
    cfg = cfg or {}
    if not cfg.get("enabled", True):
        return True, "已跳过（功能已关闭）"

    hwnd = _find_wecom_hwnd()
    if not hwnd:
        return False, "企业微信未在前台窗口可见"

    prev = user32.GetForegroundWindow()
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.2)

        if cfg.get("use_uia_first", True):
            ok, msg = _uia_mark_read(hwnd, sender)
            if ok:
                log.info("标记已读成功（UIA）：%s", sender)
                return True, msg
            log.info("UIA 路线未生效：%s", msg)

        if cfg.get("fallback_hotkey", True):
            ok, msg = _hotkey_mark_read(sender, cfg, hwnd)
            log.info("标记已读（快捷键）：%s -> %s", sender, msg)
            return ok, msg

        return False, "没有可用的标记已读方式"
    finally:
        if prev:
            user32.SetForegroundWindow(prev)

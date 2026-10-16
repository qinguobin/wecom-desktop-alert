# -*- coding: utf-8 -*-
"""
消息捕获通道。

本地企业微信是 Flutter 界面 + 会话存档接口未开通，直接"读"消息都不可行，
所以这里用最实用也最稳的一条通道：**剪贴板**。
在企业微信里「右键消息 -> 复制」或「选中文本 -> Ctrl+C」，
本模块立刻拿到内容，交给 AI 判断是否需要处理。

会话名的来源：
  - 若当时焦点在独立聊天窗口（企业微信支持把会话拖成独立窗口），窗口标题就是会话名，
    群/单聊判断与群内 @我 的过滤才能生效；
  - 焦点在主窗口时（标题恒为"企业微信"），会话名用"企业微信"占位。
"""
import ctypes
import logging
import time
from ctypes import wintypes

log = logging.getLogger("wecom.capture")

# 程序自己写剪贴板时，全局暂停捕获，避免把会话名当成新消息
_GLOBAL_SUPPRESS_UNTIL = 0.0


def pause_global(seconds=3.0):
    global _GLOBAL_SUPPRESS_UNTIL
    _GLOBAL_SUPPRESS_UNTIL = time.time() + seconds

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
CF_UNICODETEXT = 13

# 64 位下必须显式声明返回类型，否则句柄被截断成 32 位，读出来永远是空
user32.GetClipboardData.restype = ctypes.c_void_p
user32.GetClipboardData.argtypes = [ctypes.c_uint]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalUnlock.restype = ctypes.c_int
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
GetClipboardSequenceNumber = user32.GetClipboardSequenceNumber
GetClipboardSequenceNumber.restype = ctypes.c_ulong
GetClipboardSequenceNumber.argtypes = []
_get_seq = GetClipboardSequenceNumber
if not _get_seq:
    _get_seq = None


def active_window_info():
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", ""
    n = user32.GetWindowTextLengthW(hwnd)
    title = ""
    if n:
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)
    return title, cls.value


def read_clipboard():
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


WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL = 0x0001, 0x0002
VK_SPACE, VK_C, VK_CONTROL = 0x20, 0x43, 0x11
KEYEVENTF_KEYUP = 0x0002


class HotkeyCapture:
    """
    全局热键 Ctrl+Alt+Space：
    在企业微信里选中一段消息文字，按一下 -> 自动复制 -> 进剪贴板通道 -> 钉到桌面。
    （比右键->复制少两步；不占用剪贴板时也不会误触发）
    """

    def __init__(self, modifiers=MOD_CONTROL | MOD_ALT, vk=VK_SPACE, hotkey_id=1):
        self.modifiers = modifiers
        self.vk = vk
        self.hotkey_id = hotkey_id

    def register(self):
        return bool(user32.RegisterHotKey(None, self.hotkey_id, self.modifiers, self.vk))

    def run(self):
        if not self.register():
            log.warning("热键注册失败（可能被别的软件占用），跳过热键捕获")
            return
        log.info("热键已注册：Ctrl+Alt+Space 选中文字即可钉到桌面")
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == WM_HOTKEY and msg.wParam == self.hotkey_id:
                    # 只对企业微信窗口生效，避免把 Ctrl+C 打到别的程序里（比如终端会被中断）
                    title, cls = active_window_info()
                    if "WeWorkWindow" not in cls:
                        log.info("热键触发，但当前焦点不在企业微信（%s），已忽略", title or cls)
                        continue
                    log.info("热键触发 -> 复制企业微信中选中的内容")
                    # 让企业微信把选中的内容复制出来，随后剪贴板通道会接管
                    user32.keybd_event(VK_CONTROL, 0, 0, 0)
                    user32.keybd_event(VK_C, 0, 0, 0)
                    user32.keybd_event(VK_C, 0, 0x0002, 0)
                    user32.keybd_event(VK_CONTROL, 0, 0x0002, 0)
        finally:
            user32.UnregisterHotKey(None, self.hotkey_id)


class ClipboardCapture:
    """监听剪贴板变化，把新复制的内容作为一条消息事件送出"""

    def __init__(self, out_queue, interval=0.8, min_length=2):
        self.q = out_queue
        self.interval = interval
        self.min_length = min_length
        self.suppress_until = 0.0

    def pause(self, seconds=2.0):
        """暂停捕获一段时间（程序自己往剪贴板写东西时用）"""
        self.suppress_until = time.time() + seconds

    def _sender_now(self):
        title, cls = active_window_info()
        if cls == "WeWorkWindow" or "WeWorkWindow" in cls:
            if title and title not in ("企业微信", "WeCom"):
                return title
            return "企业微信"
        return "剪贴板"

    def run(self):
        log.info("剪贴板捕获已启动（每 %.1fs 检查一次）", self.interval)
        last_seq = _get_seq() if _get_seq else None
        last_text = ""
        while True:
            try:
                changed = True
                if _get_seq:
                    seq = _get_seq()
                    changed = seq != last_seq
                    last_seq = seq
                if changed and time.time() >= max(self.suppress_until, _GLOBAL_SUPPRESS_UNTIL):
                    text = (read_clipboard() or "").strip()
                    if (len(text) >= self.min_length and text != last_text
                            and not text.startswith("http") and "\n" not in text[:200]):
                        last_text = text
                        sender = self._sender_now()
                        log.info("剪贴板捕获 %s：%s", sender, text[:40])
                        self.q.put({"sender": sender, "text": text, "ts": time.time()})
            except Exception:
                log.exception("剪贴板监听出错")
            time.sleep(self.interval)

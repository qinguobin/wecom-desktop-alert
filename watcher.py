# -*- coding: utf-8 -*-
"""
企业微信本地客户端消息监听。

说明：企业微信的本地聊天数据库是加密的，无法直接读取，
因此采用「窗口状态监听 + UI 自动化」方案：
  1. 每 N 秒枚举系统顶层窗口，找到标题含"企业微信"的主窗口；
  2. 解析标题里的未读数（如 "企业微信 (3)"），未读数上升 => 有新消息；
  3. 若安装了 uiautomation，则进一步读取会话列表里带未读标记的会话名与预览文本；
  4. 把消息事件字典放进队列，交给分类器判断。
"""
import re
import time
import ctypes
import logging
from ctypes import wintypes

log = logging.getLogger("wecom.watch")

try:
    import uiautomation as auto
    UIA_OK = True
except Exception:
    UIA_OK = False

user32 = ctypes.WinDLL("user32", use_last_error=True)
EnumWindows = user32.EnumWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
GetWindowTextW = user32.GetWindowTextW
GetWindowTextLengthW = user32.GetWindowTextLengthW
IsWindowVisible = user32.IsWindowVisible

TITLE_UNREAD_RE = re.compile(r"企业微信\s*[（(](\d+)[)）]")


def enum_visible_windows():
    titles = []

    def cb(hwnd, _):
        if IsWindowVisible(hwnd):
            n = GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                GetWindowTextW(hwnd, buf, n + 1)
                titles.append((hwnd, buf.value))
        return True

    EnumWindows(EnumWindowsProc(cb), 0)
    return titles


def find_wecom_hwnd(window_keywords=("企业微信", "WeCom")):
    """返回企业微信主窗口句柄与标题；找不到返回 (None, None)"""
    for hwnd, title in enum_visible_windows():
        if any(k in title for k in window_keywords):
            return hwnd, title
    return None, None


def parse_unread(title):
    m = TITLE_UNREAD_RE.search(title or "")
    if m:
        return int(m.group(1))
    return None


def read_unread_chats_via_uia():
    """用 uiautomation 读取左侧会话列表中带未读计数的会话，返回 [(sender, preview, unread)]"""
    if not UIA_OK:
        return []
    items = []
    try:
        root = auto.GetRootControl()
    except Exception as e:
        log.debug("uia root failed: %s", e)
        return []

    def walk(ctrl, depth):
        if depth > 10 or len(items) >= 40:
            return
        try:
            for c in ctrl.GetChildren():
                name = (c.Name or "").strip()
                m = re.match(r"^(.*?)\s*[（(](\d+)[)）]$", name)
                if m and m.group(1):
                    items.append((m.group(1).strip(), "", int(m.group(2))))
                walk(c, depth + 1)
        except Exception:
            pass

    try:
        for top in root.GetChildren():
            title = top.Name or ""
            if "企业微信" in title or "WeCom" in title:
                walk(top, 0)
                break
    except Exception as e:
        log.debug("walk failed: %s", e)
    return items


class WeComWatcher:
    def __init__(self, out_queue, interval=2.0, demo_mode=False):
        self.q = out_queue
        self.interval = interval
        self.demo_mode = demo_mode
        self._last_unread = None
        self._seen_senders = set()
        self._demo_index = 0

    def _emit(self, sender, text):
        self.q.put({"sender": sender, "text": text, "ts": time.time()})
        log.info("捕获消息 %s: %s", sender, text[:40])

    def poll_once(self):
        hwnd, title = find_wecom_hwnd()
        if hwnd is None:
            return
        unread = parse_unread(title)

        # 方式一：标题未读数上升
        if unread is not None:
            if self._last_unread is not None and unread > self._last_unread:
                self._on_new_messages()
            self._last_unread = unread
        else:
            # 方式二：标题不含未读数时，改用 UIA 直接读会话列表
            for sender, preview, n in read_unread_chats_via_uia():
                if sender in self._seen_senders:
                    continue
                self._seen_senders.add(sender)
                self._emit(sender, preview or f"来自 {sender} 的 {n} 条新消息")
            if not self._seen_senders:
                self._seen_senders.clear()

    def _on_new_messages(self):
        chats = read_unread_chats_via_uia()
        if chats:
            for sender, preview, n in chats:
                if sender in self._seen_senders:
                    continue
                self._seen_senders.add(sender)
                self._emit(sender, preview or f"来自 {sender} 的 {n} 条新消息")
        else:
            self._emit("企业微信", "（收到新消息，未能读取内容，请点击前往查看）")

    def _demo_emit(self):
        samples = [
            ("张伟", "@我 这份合同麻烦今天下班前确认一下，急"),
            ("产品群", "本周版本需求评审改到明天上午10点，请各位出席"),
            ("行政通知", "公司将于下月组织体检，详情见附件，无需回复"),
            ("李娜", "客户那边催着要报价，你尽快处理一下"),
        ]
        s, t = samples[self._demo_index % len(samples)]
        self._demo_index += 1
        self._emit(s, t)

    def run(self):
        log.info("企业微信监听启动，轮询间隔 %.0fs，UIA 可用：%s", self.interval, UIA_OK)
        while True:
            try:
                if self.demo_mode:
                    self._demo_emit()
                else:
                    self.poll_once()
            except Exception:
                log.exception("轮询出错")
            time.sleep(self.interval)


if __name__ == "__main__":
    import queue
    logging.basicConfig(level=logging.INFO)
    q = queue.Queue()
    WeComWatcher(q, interval=2.0, demo_mode=True).run()

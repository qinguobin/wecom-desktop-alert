# -*- coding: utf-8 -*-
"""
探测企业微信的搜索快捷键是否可用：
切到企微 -> Ctrl+F -> 粘贴一段标记文本 -> Ctrl+A -> Ctrl+C
把回读到的内容打印出来：
  * 回读到标记文本   => 搜索框被正确唤起，标为已读可以用
  * 回读到聊天内容   => Ctrl+F 没落到搜索框，需要在 config.json 里换 search_key
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import markread as mr  # noqa: E402

MARK = "ZZZHOTKEYPROBE"
KEY = (sys.argv[1] if len(sys.argv) > 1 else "f").lower()

user32 = ctypes.WinDLL("user32")
hwnd = mr._find_wecom_hwnd()
if not hwnd:
    print("未找到可见的企业微信窗口")
    sys.exit(1)

prev = user32.GetForegroundWindow()
try:
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)

    mr._ctrl_key(KEY)
    time.sleep(0.35)
    mr._set_clipboard_text(MARK)
    mr._ctrl_key("v")
    time.sleep(0.5)

    mr._ctrl_key("a")
    time.sleep(0.1)
    mr._ctrl_key("c")
    time.sleep(0.35)
    got = mr._get_clipboard_text()

    mr._press(mr.VK_ESCAPE)
    time.sleep(0.1)
    print("按下的快捷键：Ctrl+%s" % KEY.upper())
    print("回读内容：%r" % got[:120])
    if MARK in (got or ""):
        print("结论：搜索框已唤起，标为已读可用")
    else:
        print("结论：Ctrl+%s 没有落到搜索框，试试把 config.json 的 mark_read.search_key 换成别的键" % KEY.upper())
finally:
    if prev:
        user32.SetForegroundWindow(prev)
    mr._set_clipboard_text("")

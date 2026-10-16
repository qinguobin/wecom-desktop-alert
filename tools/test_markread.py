# -*- coding: utf-8 -*-
"""
单独验证「勾掉 -> 企微内标为已读」这条链路。
用法：
    D:/Python312/python.exe tools/test_markread.py "会话名"
传一个真实会话名，看企业微信里该会话的角标有没有消失。
（企业微信必须处于可见窗口状态；最小化到托盘时无法操作）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import markread  # noqa: E402

cfg = {"enabled": True, "use_uia_first": True, "fallback_hotkey": True, "search_key": "f"}

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "自检-不存在的会话"
    print("目标会话：", name)
    print("注意：脚本会临时把焦点切到企业微信，1~2 秒后自动切回来")
    ok, msg = markread.mark_conversation_read(name, cfg)
    print("结果：", "成功" if ok else "失败", "|", msg)

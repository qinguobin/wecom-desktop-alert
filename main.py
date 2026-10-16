# -*- coding: utf-8 -*-
"""
企业微信消息识别 + 桌面置顶小组件 —— 入口

流程：
    企业微信窗口监听  ->  过滤（群消息只看 @我 的）  ->  AI 判断是否需要处理
    ->  需要的写进待办并显示在桌面置顶小组件  ->  点一下勾掉

数据、日志、依赖环境全部位于 D:\\WeComDesktopAlert，不往 C 盘写任何文件。
"""
import argparse
import atexit
import json
import logging
import os
import queue
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

import paths
from classifier import Classifier
from storage import Store
from widget import Widget, make_item
from watcher import WeComWatcher

DEFAULT_CONFIG = {
    "ai": {
        "api_base": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-4o-mini",
        "timeout": 20
    },
    "watcher": {
        "interval_seconds": 2,
        "demo_mode": False
    },
    "filter": {
        # 你在企业微信里的昵称/姓名/别名，用于识别群里的 @你
        "my_names": ["我"],
        # 明确指定为群的会话名（不在列表里时，按名字含下面关键词来判断）
        "group_senders": [],
        "group_keywords": ["群", "组", "部门", "项目"],
        # 名字里看不出是不是群时，true = 一律当成群（只有 @你 才收）
        "unknown_as_group": False
    },
    "widget": {
        "alpha": 0.97
    },
    "mark_read": {
        "enabled": True,
        "use_uia_first": True,
        "fallback_hotkey": True,
        "search_key": "f",
        # 企微内已经读过、角标没了的话，勾掉时也无需再操作
        "skip_if_wecom_already_clear": True
    },
    "capture": {
        "clipboard": True,
        "hotkey": True,
        "interval_seconds": 0.8,
        "min_length": 2,
        # 屏幕捕获：截图企微窗口 + 系统 OCR，自动发现新消息（主通道）
        "screen": True,
        "screen_interval_seconds": 3,
        "screen_scale": 2,
        "list_x": [0.15, 0.38],
        # 会话存档 API 读取：唯一不受企微窗口状态影响的方式，
        # 但企业必须开通「会话内容存档」，未开通报 853006，会自动停用回落到屏幕捕获
        "api": False,
        "api_interval_seconds": 20,
        "api_lookback_seconds": 120,
        "api_chat_ids": [],
        # 企微是 Flutter 界面，读不到控件树，窗口监听默认关闭，避免白耗
        "window_watch": False
    },
    "auto": {
        "wecom_process_names": ["WXWork.exe"],
        "quit_with_wecom": True,
        "absent_grace_seconds": 20,
        "poll_seconds": 5
    }
}


def load_config():
    p = paths.config_path()
    if not os.path.exists(p):
        with open(p, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        return dict(DEFAULT_CONFIG)
    try:
        with open(p, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return dict(DEFAULT_CONFIG)

    def merge(base, new):
        out = dict(base)
        for k, v in new.items():
            out[k] = merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
        return out
    return merge(DEFAULT_CONFIG, cfg)


def write_pid():
    """记录自身 pid，供看门狗判断程序是否还在运行"""
    try:
        with open(paths.file_in_data("app.pid"), "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        atexit.register(remove_pid)
    except Exception:
        pass


def remove_pid():
    try:
        os.remove(paths.file_in_data("app.pid"))
    except Exception:
        pass


def setup_logging():
    log = logging.getLogger("wecom")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    fh = RotatingFileHandler(paths.log_path(), maxBytes=1024 * 1024, backupCount=3,
                             encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    return log


def is_group(sender, fcfg):
    if sender in fcfg.get("group_senders", []):
        return True
    # OCR 识别的会话名可能有错别字，做模糊匹配
    import difflib
    for g in fcfg.get("group_senders", []):
        if difflib.SequenceMatcher(None, sender, g).ratio() >= 0.6:
            return True
    if any(k in sender for k in fcfg.get("group_keywords", [])):
        return True
    return bool(fcfg.get("unknown_as_group"))


def mentions_me(text, fcfg):
    """群里只有 @你 本人 才算；@所有人 / @全体成员 不算。
    OCR 识别的 @名字 可能有错别字（如 秦国彬->泰国彬），做模糊匹配。"""
    import difflib
    import re as _re
    names = [n for n in fcfg.get("my_names", []) if n]
    for m in _re.finditer(r"@([\w\u4e00-\u9fff·]{1,12})", text):
        who = m.group(1)
        if who in ("所有人", "全体成员", "大家"):
            continue
        for n in names:
            r = difflib.SequenceMatcher(None, who, n).ratio()
            if r >= 0.45 or (r >= 0.3 and who[-1] == n[-1]):
                return True
    for n in names:
        if ("@" + n) in text:
            return True
    return False


class Pipeline(threading.Thread):
    """消费监听事件 -> 过滤 -> AI 判断 -> 交给小组件"""

    def __init__(self, cfg, raw_q, ui_q, store, log):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.raw_q = raw_q
        self.ui_q = ui_q
        self.store = store
        self.log = log
        self.clf = Classifier()

    def run(self):
        fcfg = self.cfg["filter"]
        while True:
            ev = self.raw_q.get()
            try:
                sender = ev.get("sender", "企业微信")
                text = (ev.get("text") or "").strip()

                # 群消息：只接收 @我 的
                if is_group(sender, fcfg) and not mentions_me(text, fcfg):
                    self.log.info("忽略群消息（未@我）：%s | %s", sender, text[:40])
                    continue

                result = self.clf.judge(sender, text)
                if not result.get("need_action"):
                    self.log.info("判定无需处理：%s | %s（%s）", sender, text[:40], result.get("reason"))
                    continue

                item = make_item(sender, text, result.get("priority", "中"),
                                 result.get("reason", ""), result.get("source", ""),
                                 ts=ev.get("ts"))
                if self.store.add(item):
                    self.ui_q.put(item)
                    self.log.info("新增待办[%s] %s：%s", item["priority"], sender, text[:40])
            except Exception:
                self.log.exception("处理消息时出错")


def main():
    ap = argparse.ArgumentParser(description="企业微信消息识别并固定到桌面")
    ap.add_argument("--demo", action="store_true", help="演示模式：不依赖企业微信，循环注入示例消息")
    args = ap.parse_args()

    cfg = load_config()
    if args.demo:
        cfg["watcher"]["demo_mode"] = True

    log = setup_logging()
    write_pid()
    log.info("启动，程序目录：%s，数据目录：%s", paths.home(), paths.data_dir())

    raw_q = queue.Queue()
    ui_q = queue.Queue()
    store = Store()

    if cfg.get("capture", {}).get("window_watch"):
        watcher = WeComWatcher(
            raw_q,
            interval=float(cfg["watcher"].get("interval_seconds", 2)),
            demo_mode=bool(cfg["watcher"].get("demo_mode")),
        )
        threading.Thread(target=watcher.run, daemon=True).start()

    if cfg.get("capture", {}).get("clipboard") and not cfg["watcher"].get("demo_mode"):
        from capture import ClipboardCapture
        clip = ClipboardCapture(raw_q,
                                interval=float(cfg["capture"].get("interval_seconds", 0.8)),
                                min_length=int(cfg["capture"].get("min_length", 2)))
        threading.Thread(target=clip.run, daemon=True).start()
        log.info("已启用剪贴板捕获：在企微里复制一条消息即可自动识别")

        if cfg["capture"].get("hotkey", True):
            from capture import HotkeyCapture
            threading.Thread(target=HotkeyCapture().run, daemon=True).start()

    if cfg.get("capture", {}).get("api") and not cfg["watcher"].get("demo_mode"):
        try:
            import apiread

            def _api_down():
                # API 不通（多半是企业没开通会话存档）时，自动补开屏幕捕获
                if not cfg["capture"].get("screen"):
                    cfg["capture"]["screen"] = True
                    import screen as _sm
                    sw = _sm.ScreenWatcher(
                        raw_q,
                        interval=float(cfg["capture"].get("screen_interval_seconds", 3)),
                        scale=int(cfg["capture"].get("screen_scale", 2)),
                        list_x=tuple(cfg["capture"].get("list_x", [0.15, 0.38])),
                    )
                    threading.Thread(target=sw.run, daemon=True).start()
                    log.info("API 不可用，已自动切回屏幕捕获")

            ar = apiread.ApiReader(
                raw_q,
                interval=float(cfg["capture"].get("api_interval_seconds", 20)),
                lookback=float(cfg["capture"].get("api_lookback_seconds", 120)),
                chat_ids=cfg["capture"].get("api_chat_ids", []),
                cli=apiread.resolve_cli(cfg["capture"].get("api_cli", "")),
                on_disabled=_api_down,
            )
            threading.Thread(target=ar.run, daemon=True).start()
            log.info("已启用会话存档 API 读取")
        except Exception:
            log.exception("会话存档 API 读取启动失败")

    if cfg.get("capture", {}).get("screen", True) and not cfg["watcher"].get("demo_mode"):
        try:
            import screen as screen_mod
            sw = screen_mod.ScreenWatcher(
                raw_q,
                interval=float(cfg["capture"].get("screen_interval_seconds", 3)),
                scale=int(cfg["capture"].get("screen_scale", 2)),
                list_x=tuple(cfg["capture"].get("list_x", [0.15, 0.38])),
            )
            threading.Thread(target=sw.run, daemon=True).start()
            log.info("已启用屏幕捕获：自动识别企微会话列表的新消息")
        except Exception:
            log.exception("屏幕捕获启动失败")

    Pipeline(cfg, raw_q, ui_q, store, log).start()

    wcfg = {"alpha": cfg.get("widget", {}).get("alpha", 0.97),
            "mark_read_enabled": cfg.get("mark_read", {}).get("enabled", True),
            "mark_read": cfg.get("mark_read", {})}
    app = Widget(store, ui_q, wcfg)
    try:
        app.run()
    finally:
        log.info("退出")


if __name__ == "__main__":
    main()

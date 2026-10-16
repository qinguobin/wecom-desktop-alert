# -*- coding: utf-8 -*-
"""
Windows 通知捕获（企业微信新消息的系统 Toast）。

企业微信客户端本身是 Flutter 界面读不到内容，但它弹的新消息通知是
Windows 系统层的 Toast（由 Shell 渲染，不是 Flutter），可以被读到。
本模块轮询系统通知窗口，抓到企业微信的通知就转成一条消息事件。

抓到什么结构取决于企微怎么填通知字段，用 tools/probe_toast.py 实测后再定解析规则，
这里先用最通用的做法：把通知里的文本行按顺序取出来，
  第 1 行通常是应用名（企业微信）
  第 2 行通常是会话/发送人
  其余是消息内容
"""
import logging
import time

try:
    import uiautomation as auto
    UIA_OK = True
except Exception:
    UIA_OK = False

log = logging.getLogger("wecom.toasts")

TOAST_CLASSES = ("CoreWindow", "Toast", "Notification")
APP_NAME = "企业微信"


def _walk_texts(ctrl, depth=0, out=None, limit=40):
    if out is None:
        out = []
    if depth > 6 or len(out) >= limit:
        return out
    try:
        for c in ctrl.GetChildren():
            nm = (c.Name or "").strip()
            if nm:
                out.append(nm)
            _walk_texts(c, depth + 1, out, limit)
    except Exception:
        pass
    return out


def _is_toast(ctrl):
    cls = (ctrl.ClassName or "")
    return any(k in cls for k in TOAST_CLASSES)


def parse_toast(texts):
    """把通知里的文本行解析成 (sender, text)；解析不出来返回 None"""
    if not texts:
        return None
    # 去掉应用名那一行
    body = [t for t in texts if t != APP_NAME]
    if APP_NAME not in texts:
        # 不是企业微信的通知（按应用名识别，避免把别家通知也收进来）
        return None
    if not body:
        return None
    if len(body) == 1:
        return APP_NAME, body[0]
    # 常见结构：[标题(会话/发送人), 内容...]
    sender, text = body[0], " ".join(body[1:]).strip()
    if not text:
        sender, text = APP_NAME, body[0]
    return sender, text


class ToastCapture:
    def __init__(self, out_queue, interval=0.4, app_name=APP_NAME):
        self.q = out_queue
        self.interval = interval
        self.app_name = app_name
        self._seen = set()

    def run(self):
        if not UIA_OK:
            log.warning("uiautomation 不可用，通知捕获未启用")
            return
        log.info("通知捕获已启动（每 %.1fs 扫描一次新的系统通知）", self.interval)
        while True:
            try:
                for w in auto.GetRootControl().GetChildren():
                    if not _is_toast(w):
                        continue
                    try:
                        pid = w.ProcessId
                    except Exception:
                        pid = 0
                    texts = _walk_texts(w)
                    key = tuple(texts[:6])
                    if key in self._seen or not key:
                        continue
                    self._seen.add(key)
                    parsed = parse_toast(texts)
                    if not parsed:
                        continue
                    sender, text = parsed
                    log.info("通知捕获 %s：%s", sender, text[:40])
                    self.q.put({"sender": sender, "text": text, "ts": time.time()})
                    if len(self._seen) > 500:
                        self._seen.clear()
            except Exception:
                log.exception("通知扫描出错")
            time.sleep(self.interval)

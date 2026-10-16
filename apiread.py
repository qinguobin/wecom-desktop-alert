# -*- coding: utf-8 -*-
"""
会话存档 API 读取（唯一能实现"只要企微登录就一定能读到"的方式）。

企业微信的「会话内容存档」是服务端能力：开通后，消息由服务器直接返回，
与企业微信客户端是否开着、是否最小化、停在哪个页面**完全无关**。

前置条件（需要你们企业管理员操作，程序这边做不了）：
  1. 企业微信管理后台 → 管理工具 → 会话内容存档，开通该功能
  2. 企业需完成认证；存档功能通常需单独购买
  3. 需要被读取的成员签署同意书（员工同意）
  4. 本连接器需具备对应权限（见 wecom-cli 报错提示的授权链接）

开通前 `wecom-cli chat messages list` 会返回 errcode 853006
（this tool is not available for your corporation），本模块会自动判定并停用。

开启方式：config.json 里
  "capture": { "api": true, "api_chat_ids": ["成员userid 或 群会话ID", ...] }
"""
import json
import logging
import os
import subprocess
import time

log = logging.getLogger("wecom.api")

DEFAULT_CLI = "wecom-cli"
# wecom-cli 只在我这个环境里有，Windows 的 PATH 里通常没有
CANDIDATES = (
    "wecom-cli.cmd",
    "wecom-cli",
    r"C:\Users\12063\.workbuddy\binaries\node\cli-connector-packages\wecom-cli.cmd",
)


def resolve_cli(preferred=None):
    import shutil
    for c in [preferred] + list(CANDIDATES):
        if not c:
            continue
        p = shutil.which(c) or (c if os.path.isabs(c) and os.path.exists(c) else None)
        if p:
            return p
    return DEFAULT_CLI


def _run(cmd, timeout=30):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or "").strip()
    except Exception as e:
        return -1, repr(e)


def _extract_messages(raw):
    """把 CLI 输出解析成 [(sender, text)]；格式未知时尽量兼容"""
    if not raw:
        return []
    try:
        obj = json.loads(raw)
    except Exception:
        return []
    if isinstance(obj, dict):
        if obj.get("errcode"):
            return [("__err__", str(obj.get("errcode")))]
        # 常见容器字段
        for key in ("results_json", "msg_list", "messages", "list", "data"):
            v = obj.get(key)
            if isinstance(v, list) and v:
                return _from_list(v)
            if isinstance(v, dict):
                for k2 in ("msg_list", "messages", "list", "items"):
                    if isinstance(v.get(k2), list) and v[k2]:
                        return _from_list(v[k2])
        # 兜底：直接在顶层找列表
        for v in obj.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return _from_list(v)
        return []
    if isinstance(obj, list):
        return _from_list(obj)
    return []


def _from_list(items):
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        text = None
        for k in ("text", "content", "msg", "message", "body"):
            v = it.get(k)
            if isinstance(v, dict):
                v = v.get("content") or v.get("text")
            if isinstance(v, str) and v.strip():
                text = v.strip()
                break
        if not text:
            continue
        sender = None
        for k in ("from", "sender", "sender_name", "from_name", "talker", "name"):
            v = it.get(k)
            if isinstance(v, dict):
                v = v.get("name") or v.get("userid")
            if isinstance(v, str) and v.strip():
                sender = v.strip()
                break
        out.append((sender or "", text))
    return out


class ApiReader:
    def __init__(self, out_queue, interval=20, lookback=120,
                 chat_ids=None, cli=DEFAULT_CLI, on_disabled=None):
        self.q = out_queue
        self.interval = interval
        self.lookback = lookback
        self.chat_ids = list(chat_ids or [])
        self.cli = resolve_cli(cli)
        self.on_disabled = on_disabled
        self._dead = False
        self._seen = set()

    def run(self):
        if not self.chat_ids:
            log.warning("API 读取已开启但没有配置 api_chat_ids，自动停用")
            self._disable()
            return
        log.info("API 读取已启动：%d 个会话，每 %ds 拉取一次",
                 len(self.chat_ids), self.interval)
        while not self._dead:
            try:
                self._poll()
            except Exception:
                log.exception("API 拉取出错")
            time.sleep(self.interval)

    def _disable(self):
        self._dead = True
        if self.on_disabled:
            try:
                self.on_disabled()
            except Exception:
                pass

    def _poll(self):
        now = time.time()
        end = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
        begin = time.strftime("%Y-%m-%d %H:%M:%S",
                              time.localtime(now - self.lookback))
        for cid in self.chat_ids:
            code, raw = _run([self.cli, "chat", "messages", "list",
                              "--chat-id", str(cid),
                              "--begin-time", begin, "--end-time", end])
            msgs = _extract_messages(raw)
            if any(s == "__err__" for s, _ in msgs):
                err = next(t for s, t in msgs if s == "__err__")
                if err == "853006":
                    log.warning("企业未开通会话存档（853006），API 读取停用，"
                                "继续用屏幕捕获。开通方法见 README")
                else:
                    log.warning("会话存档接口不可用（errcode=%s），API 读取停用", err)
                self._disable()
                return
            for sender, text in msgs:
                key = (cid, text)
                if key in self._seen:
                    continue
                self._seen.add(key)
                self.q.put({"sender": sender or str(cid), "text": text,
                            "ts": time.time(), "channel": "api"})
                log.info("API 捕获 %s：%s", sender or cid, text[:40])
        if len(self._seen) > 2000:
            self._seen.clear()

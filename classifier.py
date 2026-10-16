# -*- coding: utf-8 -*-
"""
AI 分类器：判断一条企业微信消息是否需要你处理。

有 api_key 时调用 OpenAI 兼容接口（api_base 可换成任意兼容服务，如通义/DeepSeek/Kimi/本地 Ollama 等）；
没配置 key 或调用失败时自动降级为本地关键词规则，保证程序永远可用。

配置读取 D:\\WeComDesktopAlert\\config.json 的 ai 段：
  {
    "ai": {
      "api_base": "https://api.deepseek.com/v1",
      "api_key": "sk-xxxx",
      "model": "deepseek-chat",
      "timeout": 20
    }
  }
"""
import json
import re
import logging
import urllib.request

import paths

log = logging.getLogger("wecom.classify")

DEFAULT_AI = {
    "api_base": "https://api.openai.com/v1",
    "api_key": "",
    "model": "gpt-4o-mini",
    "timeout": 20,
}

# 命中这些 = 需要你动手
KEYWORDS = [
    "@我", "请处理", "待办", "麻烦你", "麻烦帮忙", "麻烦处理", "急", "加急", "尽快",
    "今天", "下班前", "审批", "确认一下", "请确认", "请回复", "需要你", "帮你",
    "帮忙", "截止", "会议", "跟进", "安排一下", "处理一下", "请查收并", "等你",
]

# 命中这些 = 纯通知，直接判为不需要处理（优先级高于上面的关键词）
NEGATIVE_KEYWORDS = [
    "无需回复", "不用回复", "不必回复", "勿回", "不需回复", "仅供参考",
    "知悉即可", "无需处理", "不用处理", "已发送", "已上传", "已发布",
]

# 命中这些 = 高优先级
URGENT_KEYWORDS = ["急", "加急", "尽快", "今天", "下班前", "截止", "@我", "马上"]

PROMPT = """你是企业微信消息助理。判断这条消息是否需要用户亲自处理（需要回复/执行任务/审批/参会/确认/给出结论等）。

规则：
- 消息内容由屏幕 OCR 识别而来，可能有错别字或缺字，请结合上下文理解，不要因为个别错字而误判。
- 群消息里没有被 @用户本人（昵称：{names}，识别可能有错字）时，一律判定为不需要处理，即使消息 @了其他人或 @所有人。
- 纯通知、公告、抄送、无需回复的内容，判定为不需要处理。
- 消息如果是用户自己发出的陈述，判定为不需要处理。
- 需要用户动手的，按紧急程度给 priority。

只输出 JSON，不要任何解释文字：
{{"need_action": true 或 false, "reason": "不超过15字的理由", "priority": "高/中/低"}}

会话来源：{sender}
消息内容：{text}
"""

PRIORITY_ORDER = {"高": 0, "中": 1, "低": 2}


class Classifier:
    def __init__(self):
        cfg = {}
        try:
            with open(paths.config_path(), "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            log.debug("读取配置失败，使用默认：%s", e)
        self.ai = {**DEFAULT_AI, **cfg.get("ai", {})}
        self.names = cfg.get("filter", {}).get("my_names", []) or ["我"]

    def judge(self, sender, text):
        if self.ai.get("api_key"):
            try:
                r = self._call_llm(sender, text)
                r["source"] = "ai"
                return r
            except Exception as e:
                log.warning("AI 调用失败，降级为关键词规则：%s", e)
        r = self._keyword_rule(text)
        r["source"] = "rule"
        return r

    def _keyword_rule(self, text):
        neg = [k for k in NEGATIVE_KEYWORDS if k in text]
        if neg:
            return {
                "need_action": False,
                "reason": "通知类消息（" + "、".join(neg[:2]) + "），无需处理",
                "priority": "低",
            }
        hit = [k for k in KEYWORDS if k in text]
        return {
            "need_action": bool(hit),
            "reason": ("命中：" + "、".join(hit[:3])) if hit else "未命中关键词",
            "priority": "高" if any(k in text for k in URGENT_KEYWORDS) else "中",
        }

    def _call_llm(self, sender, text):
        url = self.ai["api_base"].rstrip("/") + "/chat/completions"
        payload = {
            "model": self.ai["model"],
            "messages": [{
                "role": "user",
                "content": PROMPT.format(sender=sender, text=text[:800],
                                         names="/".join(self.names)),
            }],
            "temperature": 0,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.ai["api_key"],
            },
        )
        with urllib.request.urlopen(req, timeout=int(self.ai.get("timeout", 20))) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        content = raw["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            raise ValueError("模型未返回 JSON：" + content[:200])
        result = json.loads(m.group(0))
        result["need_action"] = bool(result.get("need_action"))
        result.setdefault("reason", "")
        result.setdefault("priority", "中")
        if result["priority"] not in PRIORITY_ORDER:
            result["priority"] = "中"
        return result

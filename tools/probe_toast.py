# -*- coding: utf-8 -*-
"""
通知探针：盯住 Windows 弹出的通知，看能不能读到企业微信新消息的内容。

用法： D:/Python312/python.exe tools/probe_toast.py [持续秒数，默认180]
期间请让别人给你发一条企微消息（或手机端企微给自己发一条）。
结束后看 D:/WeComDesktopAlert/data/toast.log 有没有抓到内容。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "data", "toast.log")

try:
    import uiautomation as auto
except Exception as e:
    print("uiautomation 不可用：", e)
    sys.exit(1)


def collect(ctrl, depth=0, out=None, limit=60):
    if out is None:
        out = []
    if depth > 6 or len(out) >= limit:
        return out
    try:
        for c in ctrl.GetChildren():
            nm = (c.Name or "").strip()
            if nm:
                out.append((c.ControlTypeName, nm[:80]))
            collect(c, depth + 1, out, limit)
    except Exception:
        pass
    return out


def main():
    seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 180
    seen = set()
    end = time.time() + seconds
    print("探针已启动，监听 %d 秒。现在请让别人给你发一条企微消息。" % seconds)
    print("日志：", LOG)
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("probe start\n")
        while time.time() < end:
            try:
                for w in auto.GetRootControl().GetChildren():
                    cls = w.ClassName or ""
                    name = (w.Name or "").strip()
                    if "CoreWindow" not in cls and "Toast" not in cls and "Notification" not in cls:
                        continue
                    try:
                        pid = w.ProcessId
                    except Exception:
                        pid = 0
                    key = (cls, name, pid)
                    if key in seen:
                        continue
                    seen.add(key)
                    texts = [t for _, t in collect(w)]
                    line = "[TOAST] class=%s name=%r pid=%s texts=%s" % (
                        cls, name[:40], pid, texts[:8])
                    print(line)
                    f.write(line + "\n")
                    f.flush()
            except Exception as e:
                f.write("probe error: %r\n" % e)
            time.sleep(0.4)
        f.write("probe end\n")
    print("探针结束")


if __name__ == "__main__":
    main()

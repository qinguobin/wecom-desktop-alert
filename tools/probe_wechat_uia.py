"""用 UIA 探测个人微信窗口，看能否读到聊天内容。"""
import sys

import uiautomation as auto

auto.SetGlobalSearchTimeout(3)

print("=== 查找微信窗口 ===")
found = []
for w in auto.GetRootControl().GetChildren():
    cls = w.ClassName or ""
    name = w.Name or ""
    if "Weixin" in cls or "WeChat" in cls or "Qt51514" in cls or name == "微信":
        found.append(w)
        print("  窗口: class=%s name=%r" % (cls, name))

if not found:
    print("  UIA 未找到微信主窗口")
    for w in auto.GetRootControl().GetChildren():
        if w.Name:
            print("    (其它) class=%s name=%r" % (w.ClassName, w.Name[:40]))

for w in found:
    print()
    print("=== 深挖控件树 ===")
    try:
        for c, depth in auto.WalkTree(w, getFirstChild=True, includeTop=False, maxDepth=4):
            if depth > 4:
                break
            try:
                txt = (c.Name or "")[:50]
            except Exception:
                txt = "<?>"
            print("  " + "  " * depth + "[%s] name=%r ctrl=%s" % (c.ControlTypeName, txt, c.ClassName))
    except Exception as e:
        print("  遍历失败:", e)

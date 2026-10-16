# -*- coding: utf-8 -*-
"""
自检：造几条消息 -> 验证合并卡片/时间排序/单条勾掉/整卡勾掉/收起 是否正常。
不会真的去操作企业微信（mark_read 在自检里关闭）。
用法：  D:/Python312/python.exe selftest.py
"""
import queue
import time

import storage
import widget

cfg = {"alpha": 0.97, "mark_read_enabled": False, "mark_read": {"enabled": False}}

store = storage.Store()
store.clear()
q = queue.Queue()
w = widget.Widget(store, q, cfg)

base = time.time()
samples = [
    ("产品群", "@张三 合同今天下班前确认一下，急", "高", base - 300),
    ("产品群", "@张三 报价单再给客户发一版", "中", base - 60),
    ("李娜", "客户催报价，麻烦你尽快处理一下", "中", base - 30),
    ("行政通知", "下月体检安排已发布", "低", base - 10),
]
items = []
for s, t, p, ts in samples:
    it = widget.make_item(s, t, p, "自检", "test", ts=ts)
    store.add(it)
    q.put(it)
    items.append(it)

w._pump()
w.root.update()
print("卡片数:", len(w.cards), "-> 期望 3")
print("会话:", list(w.cards))
print("产品群内消息数:", len(w.cards["产品群"]["items"]), "-> 期望 2")
print("标题:", w.title_var.get())

# 消息是否按时间从旧到新排列
order = [i["text"][:8] for i in sorted(w.cards["产品群"]["items"].values(), key=lambda x: x["ts"])]
print("产品群时间顺序:", order)

# 勾掉单条
w.tick_message(items[0])
time.sleep(0.4)
w.root.update()
print("勾掉 1 条后 产品群剩余:", len(w.cards["产品群"]["items"]), "-> 期望 1")

# 勾掉整张卡（最后一条也会带走卡片）
w.tick_card("产品群")
time.sleep(0.6)
w.root.update()
print("整卡通掉后 卡片数:", len(w.cards), "-> 期望 2")

# 全部勾掉
w.clear_all()
time.sleep(0.8)
w.root.update()
print("全部勾掉后 卡片数:", len(w.cards), "-> 期望 0")
print("存储剩余:", len(store.all()), "-> 期望 0")

# 收起 / 展开
w.toggle_collapse()
w.root.update()
print("收起高度:", w.root.winfo_height(), "-> 期望 34")
w.toggle_collapse()
w.root.update()
print("展开高度:", w.root.winfo_height())

w.root.after(100, w.quit)
w.root.mainloop()
print("自检结束，界面正常退出")

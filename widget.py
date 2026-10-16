# -*- coding: utf-8 -*-
"""
桌面置顶小组件（基于 tkinter，无需额外依赖）

结构：一个会话一张卡片，卡片内多条消息按时间从上到下排列
  ┌ 卡片 ─────────────────────────┐
  │ ☐ [高] 产品群  (2条)   14:20 ›│
  │    ☐ 14:18 @张三 合同确认一下 │
  │    ☐ 14:20 @张三 报价再看看   │
  └───────────────────────────────┘

  - 卡片头右上「›」或双击卡片 = 切到企业微信
  - 行首 ☐ = 勾掉这一条；卡片头 ☐ = 勾掉整个会话（会顺带把企微里该会话标为已读）
  - 底部：全部勾掉 / 打开企业微信 / 收起
"""
import ctypes
import json
import threading
import time
import tkinter as tk
from ctypes import wintypes
from datetime import datetime

import paths

user32 = ctypes.WinDLL("user32", use_last_error=True)

BG = "#ffffff"
BG_CARD = "#fafbfc"
BG_BAR = "#f5f6f8"
FG = "#1f2328"
FG_DIM = "#6b7280"
FG_DONE = "#9aa0a6"
ACCENT = "#1a73e8"
BORDER = "#e3e5e8"
PRIORITY_COLOR = {"高": "#d93025", "中": "#e8891c", "低": "#6b7280"}
PRIORITY_ORDER = {"高": 0, "中": 1, "低": 2}


def strike(label):
    """给标签加删除线并置灰（保留原字号）"""
    raw = (label.cget("font") or "").replace("{", "").replace("}", "")
    parts = raw.split()
    size, family = 9, "Microsoft YaHei UI"
    if parts and parts[-1].isdigit():
        size = int(parts[-1])
        family = " ".join(parts[:-1]) or family
    elif parts:
        family = " ".join(parts)
    label.configure(fg=FG_DONE, bg="#f1f3f4", font=(family, size, "overstrike"))


def activate_wecom():
    """把企业微信窗口切到前台"""
    EnumWindows = user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    GetWindowTextW = user32.GetWindowTextW
    GetWindowTextLengthW = user32.GetWindowTextLengthW

    found = []

    def cb(hwnd, _):
        n = GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            GetWindowTextW(hwnd, buf, n + 1)
            if "企业微信" in buf.value or "WeCom" in buf.value:
                found.append(hwnd)
        return True

    EnumWindows(EnumWindowsProc(cb), 0)
    if not found:
        return False
    try:
        target = found[0]
        if user32.IsIconic(target):
            user32.ShowWindow(target, 9)
        user32.SetForegroundWindow(target)
        return True
    except Exception:
        return False


class Widget:
    def __init__(self, store, inbox, cfg=None):
        self.store = store
        self.inbox = inbox
        self.cfg = cfg or {}
        self.alive = True

        self.root = tk.Tk()
        self.root.title("待处理消息")
        self.root.configure(bg=BORDER)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", float(self.cfg.get("alpha", 0.97)))

        self._load_geometry()
        self._build_header()

        # 可滚动区域
        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=BG)
        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(
            self.inner_id, width=e.width))
        for w in (self.canvas, self.root):
            w.bind_all("<MouseWheel>", self._on_wheel, add="+")

        self.empty_label = tk.Label(
            self.inner, bg=BG, fg=FG_DIM, font=("Microsoft YaHei UI", 9),
            justify="center",
            text="还没有待处理消息\n\n程序会每 3 秒截图识别企微会话列表，\n"
                 "有需要处理的消息会自动出现在这里。\n"
                 "前提：企微窗口停在「消息」页，且不要最小化")
        self._empty_shown = False
        self._build_footer()

        self.cards = {}          # sender -> card dict
        self.collapsed = False
        self._exp_w, self._exp_h = 340, 420
        self._drag = None
        self.root.after(300, self._pump)

    # ---------- 标题栏 ----------
    def _build_header(self):
        bar = tk.Frame(self.root, bg=BG_BAR, height=34)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        self.title_var = tk.StringVar(value="待处理消息")
        title = tk.Label(bar, textvariable=self.title_var, bg=BG_BAR, fg=FG,
                         font=("Microsoft YaHei UI", 10, "bold"))
        title.pack(side="left", padx=10)

        for txt, cmd in (("—", self.minimize), ("×", self.quit)):
            b = tk.Label(bar, text=txt, bg=BG_BAR, fg=FG_DIM,
                         font=("Microsoft YaHei UI", 11), width=3, cursor="hand2")
            b.pack(side="right")
            b.bind("<Button-1>", lambda e, c=cmd: c())
            b.bind("<Enter>", lambda e, w=b: w.configure(fg=ACCENT))
            b.bind("<Leave>", lambda e, w=b: w.configure(fg=FG_DIM))

        for w in (bar, title):
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>", self._on_drag)
            w.bind("<ButtonRelease-1>", self._stop_drag)
            w.bind("<Double-Button-1>", lambda e: self.toggle_collapse())

    def _build_footer(self):
        f = tk.Frame(self.root, bg=BG_BAR)
        f.pack(fill="x")
        self.footer = f
        for txt, cmd in (("全部勾掉", self.clear_all),
                         ("打开企业微信", self._open_wecom),
                         ("收起", self.minimize)):
            tk.Button(f, text=txt, command=cmd, bg=BG_BAR, fg=FG,
                      font=("Microsoft YaHei UI", 9), relief="flat",
                      activebackground="#e8eaed", cursor="hand2").pack(
                side="left", fill="x", expand=True, padx=2, pady=4)

    # ---------- 滚动 / 拖动 / 几何 ----------
    def _on_wheel(self, e):
        self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

    def _geo_path(self):
        return paths.file_in_data("widget_geometry.json")

    def _load_geometry(self):
        try:
            with open(self._geo_path(), "r", encoding="utf-8") as f:
                g = json.load(f)
            w, h, x, y = g["w"], g["h"], g["x"], g["y"]
        except Exception:
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            w, h, x, y = 340, 420, sw - w - 20, 120
        # 防止把收起状态(34px)存下来导致下次启动窗口只剩标题条
        w, h = max(w, 260), max(h, 200)
        self.root.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")

    def _save_geometry(self):
        if self.collapsed:
            return  # 收起状态下不保存尺寸，避免下次启动打不开
        try:
            g = {"w": self.root.winfo_width(), "h": self.root.winfo_height(),
                 "x": self.root.winfo_x(), "y": self.root.winfo_y()}
            with open(self._geo_path(), "w", encoding="utf-8") as f:
                json.dump(g, f)
        except Exception:
            pass

    def _start_drag(self, e):
        if self.collapsed:
            # 收起状态点一下标题条即展开（双击也可以）
            self.root.after(10, self.toggle_collapse)
            return
        self._drag = (e.x_root, e.y_root, self.root.winfo_x(), self.root.winfo_y())

    def _on_drag(self, e):
        if not self._drag:
            return
        self.root.geometry(f"+{self._drag[2] + e.x_root - self._drag[0]}"
                           f"+{self._drag[3] + e.y_root - self._drag[1]}")

    def _stop_drag(self, e):
        self._drag = None
        self._save_geometry()

    # ---------- 数据流入 ----------
    def _pump(self):
        try:
            while True:
                self._add_message(self.inbox.get_nowait())
        except Exception:
            pass
        self._update_title()
        if self.alive:
            self.root.after(300, self._pump)

    def _update_title(self):
        n = sum(len(c["items"]) for c in self.cards.values())
        base = f"待处理消息 · {n} 条" if n else "待处理消息 · 全部完成"
        base += self._capture_hint()
        self.title_var.set(base)
        if n and self._empty_shown:
            self.empty_label.pack_forget()
            self._empty_shown = False
        elif not n and not self._empty_shown:
            self.empty_label.pack(fill="x", pady=24)
            self._empty_shown = True

    def _capture_hint(self):
        """告诉用户现在为什么抓不到消息：企微没开 / 最小化 / 不在消息页"""
        try:
            import screen
            st = screen.STATUS
        except Exception:
            return ""
        if not st.get("found"):
            return " · 未找到企微"
        if st.get("minimized"):
            return " · 企微已最小化（暂停）"
        if not st.get("chat_view"):
            return " · 企微不在消息页"
        return ""
        if n != getattr(self, "_last_n", -1):
            self._last_n = n
            self.root.after(50, self._refresh_scroll)

    def _refresh_scroll(self):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    # ---------- 卡片 ----------
    def _create_card(self, item):
        sender = item["sender"]
        card = tk.Frame(self.inner, bg=BG_CARD, highlightbackground=BORDER,
                        highlightthickness=1)
        card.pack(fill="x", padx=8, pady=4)

        header = tk.Frame(card, bg=BG_CARD)
        header.pack(fill="x", padx=6, pady=(6, 2))

        chk = tk.Label(header, text="☐", bg=BG_CARD, fg=ACCENT,
                       font=("Segoe UI Symbol", 12), cursor="hand2", width=2)
        chk.pack(side="left")
        chk.bind("<Button-1>", lambda e, s=sender: self.tick_card(s))

        pr = tk.Label(header, text="", bg=FG_DIM, fg="#ffffff",
                      font=("Microsoft YaHei UI", 8, "bold"), padx=4)
        pr.pack(side="left")

        name = tk.Label(header, text=sender, bg=BG_CARD, fg=FG,
                        font=("Microsoft YaHei UI", 9, "bold"), anchor="w")
        name.pack(side="left", padx=4)

        cnt = tk.Label(header, text="", bg=BG_CARD, fg=FG_DIM,
                       font=("Microsoft YaHei UI", 8))
        cnt.pack(side="left")

        openb = tk.Label(header, text="›", bg=BG_CARD, fg=FG_DIM,
                         font=("Microsoft YaHei UI", 14), width=2, cursor="hand2")
        openb.pack(side="right")
        openb.bind("<Button-1>", lambda e: self._open_wecom())

        msgs = tk.Frame(card, bg=BG_CARD)
        msgs.pack(fill="x", padx=6, pady=(0, 4))

        c = {"frame": card, "header": header, "chk": chk, "pr": pr, "cnt": cnt,
             "msgs": msgs, "items": {}, "rows": {}, "name": sender}
        for w in (card, header, name):
            w.bind("<Double-Button-1>", lambda e: self._open_wecom())
        self.cards[sender] = c
        return c

    def _add_message(self, item):
        sender = item["sender"]
        card = self.cards.get(sender) or self._create_card(item)
        card["items"][item["id"]] = item
        self._render_messages(card)
        self._update_card_header(card)
        self._update_title()

    def _render_messages(self, card):
        """按时间从旧到新重绘卡片里的消息行"""
        for row in card["rows"].values():
            row.destroy()
        card["rows"] = {}
        ordered = sorted(card["items"].values(), key=lambda i: i.get("ts", 0))
        for it in ordered:
            row = tk.Frame(card["msgs"], bg=BG_CARD)
            row.pack(fill="x", pady=1)

            chk = tk.Label(row, text="☐", bg=BG_CARD, fg="#5f6368",
                           font=("Segoe UI Symbol", 10), width=2, cursor="hand2")
            chk.pack(side="left")
            chk.bind("<Button-1>", lambda e, i=it: self.tick_message(i))

            tk.Label(row, text=it.get("time", ""), bg=BG_CARD, fg=FG_DIM,
                     font=("Microsoft YaHei UI", 8), width=5, anchor="w").pack(side="left")

            t = tk.Label(row, text=it["text"], bg=BG_CARD, fg="#33383d",
                         font=("Microsoft YaHei UI", 9), anchor="w",
                         justify="left", wraplength=250)
            t.pack(side="left", fill="x", expand=True)
            card["rows"][it["id"]] = row

    def _update_card_header(self, card):
        items = list(card["items"].values())
        if not items:
            return
        top = min(PRIORITY_ORDER.get(i.get("priority"), 1) for i in items)
        label = {0: "高", 1: "中", 2: "低"}[top]
        card["pr"].configure(text=label, bg=PRIORITY_COLOR[label])
        card["cnt"].configure(text=f"{len(items)}条"
                              + (f" · {items[-1].get('time', '')}" if len(items) == 1 else ""))

    # ---------- 勾掉 ----------
    def tick_message(self, item):
        card = self.cards.get(item["sender"])
        if not card or item["id"] not in card["items"]:
            return
        row = card["rows"].get(item["id"])
        if row:
            row.configure(bg="#f1f3f4")
            for w in row.winfo_children():
                if isinstance(w, tk.Label) and w.cget("text") not in ("☐", "☑"):
                    strike(w)
        card["items"].pop(item["id"], None)
        self.store.remove(item["id"])
        self.root.after(280, lambda: self._finalize(card, item))

    def _finalize(self, card, item):
        row = card["rows"].pop(item["id"], None)
        if row:
            row.destroy()
        if not card["items"]:
            self._remove_card(card)
        else:
            self._update_card_header(card)
        self._update_title()

    def _remove_card(self, card):
        sender = card["name"]
        self.cards.pop(sender, None)
        card["msgs"].destroy()
        card["header"].destroy()
        card["frame"].destroy()
        self._update_title()
        if self.cfg.get("mark_read_enabled", True):
            threading.Thread(target=self._mark_read_bg, args=(sender,), daemon=True).start()

    def tick_card(self, sender):
        card = self.cards.get(sender)
        if not card:
            return
        for it in list(card["items"].values()):
            self.tick_message(it)

    def clear_all(self):
        for sender in list(self.cards):
            self.tick_card(sender)

    # ---------- 企微联动 ----------
    def _mark_read_bg(self, sender):
        try:
            import markread
            ok, msg = markread.mark_conversation_read(sender, self.cfg.get("mark_read", {}))
            if not ok:
                self.root.after(0, lambda: self._flash(msg))
        except Exception as e:
            self.root.after(0, lambda: self._flash("标记已读失败：%s" % e))

    def _open_wecom(self):
        if not activate_wecom():
            self._flash("未找到企业微信窗口")

    def _flash(self, msg):
        self.title_var.set(msg[:30])
        self.root.after(1500, self._update_title)

    # ---------- 收起 / 退出 ----------
    def toggle_collapse(self):
        if self.collapsed:
            self.footer.pack(fill="x")
            self.canvas.pack(fill="both", expand=True, before=self.footer)
            self.root.geometry(f"{self._exp_w}x{self._exp_h}"
                               f"+{self.root.winfo_x()}+{self.root.winfo_y()}")
            self.collapsed = False
        else:
            self._exp_w = self.root.winfo_width()
            self._exp_h = self.root.winfo_height()
            self.canvas.pack_forget()
            self.footer.pack_forget()
            self.root.geometry(f"{self._exp_w}x34+{self.root.winfo_x()}+{self.root.winfo_y()}")
            self.collapsed = True

    def minimize(self):
        if not self.collapsed:
            self.toggle_collapse()

    def quit(self):
        self.alive = False
        self._save_geometry()
        self.root.destroy()

    def load_existing(self):
        for item in sorted(self.store.all(), key=lambda i: i.get("ts", 0)):
            self._add_message(item)

    def run(self):
        self.load_existing()
        self.root.mainloop()


def make_item(sender, text, priority="中", reason="", source="rule", ts=None):
    ts = ts or time.time()
    return {
        "id": f"{int(ts*1000)}-{abs(hash((sender, text))) % 100000}",
        "sender": sender,
        "text": text,
        "priority": priority,
        "reason": reason,
        "source": source,
        "ts": ts,
        "time": datetime.fromtimestamp(ts).strftime("%H:%M"),
    }

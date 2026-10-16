# -*- coding: utf-8 -*-
"""待处理事项的本地持久化，全部存在 D 盘 data 目录"""
import json
import os
import threading

import paths

PRIORITY_ORDER = {"高": 0, "中": 1, "低": 2}


class Store:
    def __init__(self):
        self.path = paths.pending_path()
        self.lock = threading.Lock()
        self.items = self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [i for i in data if isinstance(i, dict)]
        except Exception:
            return []

    def save(self):
        with self.lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.items, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)

    def add(self, item):
        # 同一会话同一内容不重复添加
        for i in self.items:
            if i["sender"] == item["sender"] and i["text"] == item["text"]:
                return False
        self.items.append(item)
        self.items.sort(key=lambda x: PRIORITY_ORDER.get(x.get("priority"), 1))
        self.save()
        return True

    def remove(self, item_id):
        self.items = [i for i in self.items if i["id"] != item_id]
        self.save()

    def clear(self):
        self.items = []
        self.save()

    def all(self):
        return list(self.items)

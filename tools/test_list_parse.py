# -*- coding: utf-8 -*-
"""验证 screen.py 的会话列表解析：打印识别到的会话行，检查区域裁剪是否正确"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import screen as S

wins = S.wecom_windows()
print("企微窗口:", [(t or "<无标题>") for _, t in wins])
main = next(((h, t) for h, t in wins if t == S.MAIN_TITLE), None)
if not main:
    print("没找到主窗口")
    sys.exit(1)

hwnd, _ = main
bgra, w, h = S.capture_scaled(hwnd, 2)
print("截图: %dx%d" % (w, h))
lines = S.ocr(bgra, w, h)
print("整窗 OCR 行数:", len(lines))

list_lines = [d for d in S.parse_list(lines, 0.15, 0.38) if S._line_y(d) >= 0.06]
print("\n会话列表列解析到 %d 行：" % len(list_lines))
for d in list_lines:
    print("  y=%.3f | %s" % (S._line_y(d), d["text"]))

# 独立会话窗口
convs = [(h2, t) for h2, t in wins if t != S.MAIN_TITLE]
for h2, t in convs:
    b2, w2, hh2 = S.capture_scaled(h2, 2)
    if not b2:
        continue
    ls = [d for d in S.ocr(b2, w2, hh2) if 0.06 < S._line_y(d) < 0.82]
    print("\n独立窗口 %r 识别 %d 行：" % (t, len(ls)))
    for d in ls[:25]:
        print("  y=%.3f | %s" % (S._line_y(d), d["text"]))

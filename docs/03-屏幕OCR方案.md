# 实测记录 03 · 屏幕捕获 + OCR 方案

这是本项目**唯一走通**的自动读取方案。核心在 `screen.py`。

---

## 为什么它能绕开 Flutter / Qt

Flutter（企微）和 Qt 自绘（微信）都不向 UIA 暴露控件树，
但**它们最终都要把像素画到窗口上**。像素是绕不过去的。

所以流程是：

```
PrintWindow(hwnd, PW_RENDERFULLCONTENT)   ← 强制重渲染，拿到真实画面
        ↓
StretchBlt(HALFTONE) 放大 2 倍            ← 解决 12px 小字识别率差
        ↓
Windows.Media.Ocr (zh-Hans-CN)            ← 系统自带中文 OCR，零额外依赖
        ↓
按 x 坐标筛选会话列表列 → 按 y 排序 → 与上次快照 diff
        ↓
新增/变化的行 = 新消息
```

---

## 三个必须踩对的点

### 1. `PrintWindow(PW_RENDERFULLCONTENT)` 而不是 `BitBlt`

```python
PW_RENDERFULLCONTENT = 2
ok = user32.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT)
if not ok:
    gdi32.BitBlt(mem, 0, 0, w, h, hdc, 0, 0, SRCCOPY)
```

`BitBlt` 对 DirectComposition 合成的窗口只能拿到过期帧——
这是"用户发了消息、程序毫无反应"的直接原因。

### 2. 最小化/屏外时要用还原矩形

最小化后 `GetWindowRect` 会返回垃圾坐标：

| 场景 | GetWindowRect 返回值 |
|---|---|
| 企微最小化 | `(-32000, -32000)` |
| 微信最小化 | `314x50`（小矩形，不是 -32000） |

所以**不能只判断 -32000**，必须用 `IsIconic`：

```python
if r.left <= -20000 or r.top <= -20000 or user32.IsIconic(hwnd):
    plc = WINDOWPLACEMENT()
    plc.length = ctypes.sizeof(plc)
    if user32.GetWindowPlacement(hwnd, ctypes.byref(plc)):
        r = plc.rcNormalPosition
```

### 3. 强制填充 alpha 通道

窗口截图的 alpha 是 0，OCR 引擎会当成全透明图，直接返回 0 行：

```python
ba = bytearray(buf)
ba[3::4] = b"\xff" * (sw * sh)
```

---

## 会话列表的定位

按 **x 坐标区间** 从整窗 OCR 结果里切出会话列表那一列（默认 `x ∈ [0.15, 0.38]`），
再按 y 排序。构造 `screen.py`：

```python
"list_x": [0.15, 0.38]      # 会话列表列的 x 范围（占窗口宽度比例）
"screen_scale": 2           # 放大倍数
"screen_interval_seconds": 3
```

## 消息页判断 `is_chat_view()`

必须确认企微停在「消息」页，否则会把工作台页的"审批""打卡"当成消息。

**第一版（错）**：找顶部的"未读/@我/单聊/群聊"筛选条 → 太严，
实际布局里位置对不上，导致本该能读的也被跳过。

**第二版（对）**：找**会话列表右侧的时间戳**特征——
`刚刚` / `N分钟前` / `昨天` / `HH:MM` / `昨天 HH:MM`。

---

## OCR 错字的模糊匹配

OCR 会把 `@秦国彬` 识别成 `@泰国彬` / `@孬王彬` / `@癸国彬`，精确匹配全漏。
用 `difflib` 做相似度匹配（阈值内算命中）。

副作用是群名也可能被误匹配，所以保留 `filter.group_senders` 白名单兜底。

---

## 性能

| 项 | 值 |
|---|---|
| 单次截图 + 2x 放大 | ~200ms |
| 单次 OCR | ~500ms |
| 一轮全窗口识别 | ~0.7s |
| 轮询间隔 | 3s |

CPU 占用可以接受，但建议不要调到 1s 以下。

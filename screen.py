# -*- coding: utf-8 -*-
"""
屏幕 OCR 捕获：定期截图企业微信窗口并识别内容。

为什么需要它：企微客户端是 Flutter 渲染，UIA 读不到任何控件，
会话存档接口也未开通，通知 Toast 在部分机器上不弹。
但「看」永远有效——截图 + Windows 自带中文 OCR，能直接读到：
  - 主窗口：左侧会话列表（谁发来了什么、有没有 @我）
  - 独立会话窗口：完整消息内容
识别结果与上一轮比对，出现新内容即视为新消息。
"""
import logging
import re
import time
import struct
import ctypes
import asyncio
import difflib
from ctypes import wintypes

log = logging.getLogger("wecom.screen")

# 供小组件显示当前为什么抓不到：企微没开 / 已最小化 / 不在消息页
STATUS = {"found": False, "minimized": False, "chat_view": False}

gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

SRCCOPY = 0x00CC0020
HALFTONE = 4
PW_RENDERFULLCONTENT = 0x00000002

class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.UINT),
        ("flags", wintypes.UINT),
        ("showCmd", wintypes.UINT),
        ("ptMinPosition", wintypes.POINT),
        ("ptMaxPosition", wintypes.POINT),
        ("rcNormalPosition", wintypes.RECT),
    ]


EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetClassNameW.restype = ctypes.c_int
user32.IsWindowVisible.restype = wintypes.BOOL

MAIN_TITLE = "企业微信"
# 消息页会话列表顶部的筛选条，用来判断当前是不是停在「消息」页
CHIP_WORDS = ("未读", "@我", "单聊", "群聊", "内部聊天", "外部聊天", "我的企业")

# 噪声行：时间戳 / 未读角标 / 状态
_NOISE_RE = [
    re.compile(r"^[\d\s\+.:／/]+$"),
    re.compile(r"^\d{1,2}:\d{2}$"),
    re.compile(r"^星期[一二三四五六日天]"),
    re.compile(r"^昨天$|^前天$|^今天$"),
    re.compile(r"^\d+ *(分钟|小时|天)前$"),
    re.compile(r"^\d{1,2}[月/]\d{1,2}"),
    re.compile(r"^\d{4}[/-]\d{1,2}"),
    re.compile(r"^[\d]+ *\+?$"),
    re.compile(r"^正在输入"),
    re.compile(r"^[Vv〇O○□囗且惠]?$"),
]
_CJK = r"\u4e00-\u9fff\u3400-\u4dbf\uff00-\uffef\u3000-\u303f"


def _clean(text):
    """去掉 OCR 在汉字间插入的空格"""
    t = text.strip()
    prev = None
    while prev != t:
        prev = t
        t = re.sub(r"(?<=[%s])\s+(?=[%s])" % (_CJK, _CJK), "", t)
    return t


def _is_noise(text):
    if not text:
        return True
    if "正在输入" in text:
        return True
    for r in _NOISE_RE:
        if r.match(text):
            return True
    return False


# ---------------- 窗口枚举 ----------------

def _wins():
    out = []

    @EnumWindowsProc
    def cb(h, _):
        if not user32.IsWindowVisible(h):
            return True
        n = user32.GetWindowTextLengthW(h)
        title = ""
        if n:
            b = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(h, b, n + 1)
            title = b.value
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        out.append((int(h), title, int(pid.value)))
        return True

    user32.EnumWindows(cb, 0)
    return out


def _proc_name(pid):
    h = kernel32.OpenProcess(0x1000, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(260)
        size = wintypes.DWORD(260)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1]
    finally:
        kernel32.CloseHandle(h)
    return ""


def wecom_windows():
    """[(hwnd, title)]：主窗口（标题=企业微信）+ 独立会话窗口（标题=会话名）"""
    res = []
    for h, title, pid in _wins():
        if _proc_name(pid).lower() == "wxwork.exe" and title:
            res.append((h, title))
    return res


# ---------------- 截图（高质量放大） ----------------

def capture_scaled(hwnd, scale=2):
    # 最小化时 GetWindowRect 返回 -32000 的坐标，或缩成任务栏尺寸的小矩形
    # （微信最小化后返回 314x50 而非 -32000），统一改用还原矩形 rcNormalPosition
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    if r.left <= -20000 or r.top <= -20000 or user32.IsIconic(hwnd):
        plc = WINDOWPLACEMENT()
        plc.length = ctypes.sizeof(plc)
        if user32.GetWindowPlacement(hwnd, ctypes.byref(plc)):
            r = plc.rcNormalPosition
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        return None, 0, 0
    hdc = user32.GetWindowDC(hwnd)
    if not hdc:
        return None, 0, 0
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mem, bmp)
    # PrintWindow + PW_RENDERFULLCONTENT：即使窗口被遮挡/最小化也强制重渲染，
    # Flutter(DirectComposition) 界面必须用它，BitBlt 只能拿到过期画面
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user32.PrintWindow.restype = wintypes.BOOL
    ok = user32.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT)
    if not ok:
        gdi32.BitBlt(mem, 0, 0, w, h, hdc, 0, 0, SRCCOPY)
    W, H = w * scale, h * scale
    mem2 = bmp2 = old2 = None
    if scale > 1:
        mem2 = gdi32.CreateCompatibleDC(hdc)
        bmp2 = gdi32.CreateCompatibleBitmap(hdc, W, H)
        old2 = gdi32.SelectObject(mem2, bmp2)
        gdi32.SetStretchBltMode(mem2, HALFTONE)
        gdi32.SetBrushOrgEx(mem2, 0, 0, 0)
        gdi32.StretchBlt(mem2, 0, 0, W, H, mem, 0, 0, w, h, SRCCOPY)
        src_dc, src_bmp, sw, sh = mem2, bmp2, W, H
    else:
        src_dc, src_bmp, sw, sh = mem, bmp, w, h
    bmi = (ctypes.c_char * 40).from_buffer_copy(
        struct.pack("<IiiHHIIiiII", 40, sw, -sh, 1, 32, 0, sw * sh * 4, 0, 0, 0, 0))
    buf = (ctypes.c_char * (sw * sh * 4))()
    gdi32.GetDIBits(src_dc, src_bmp, 0, sh, buf, bmi, 0)  # DIB_RGB_COLORS=0
    gdi32.SelectObject(mem, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    if mem2:
        gdi32.SelectObject(mem2, old2)
        gdi32.DeleteObject(bmp2)
        gdi32.DeleteDC(mem2)
    user32.ReleaseDC(hwnd, hdc)
    ba = bytearray(buf)
    ba[3::4] = b"\xff" * (sw * sh)  # 强制不透明，否则 OCR 视为全透明
    return bytes(ba), sw, sh


# ---------------- OCR ----------------

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        from winsdk.windows.media.ocr import OcrEngine
        from winsdk.windows.globalization import Language
        _engine = OcrEngine.try_create_from_language(Language("zh-Hans-CN"))
        if _engine is None:
            _engine = OcrEngine.try_create_from_user_profile_languages()
        if _engine is None:
            raise RuntimeError("系统没有可用的 OCR 语言包")
    return _engine


async def _ocr_async(bgra, w, h):
    from winsdk.windows.storage.streams import Buffer
    from winsdk.windows.graphics.imaging import (
        SoftwareBitmap, BitmapPixelFormat, BitmapAlphaMode)
    b = Buffer(len(bgra))
    b.length = len(bgra)
    with memoryview(b) as mv:
        mv[:] = bgra
    sb = SoftwareBitmap.create_copy_from_buffer(
        b, BitmapPixelFormat.BGRA8, w, h, BitmapAlphaMode.PREMULTIPLIED)
    result = await get_engine().recognize_async(sb)
    lines = []
    for ln in result.lines:
        words = []
        for wd in ln.words:
            r = wd.bounding_rect
            words.append((wd.text, (r.x + r.width / 2) / w, (r.y + r.height / 2) / h))
        if words:
            lines.append({"text": _clean(ln.text), "words": words})
    lines.sort(key=lambda d: d["y"] if False else sum(w[2] for w in d["words"]) / len(d["words"]))
    return lines


def ocr(bgra, w, h):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_ocr_async(bgra, w, h))
    finally:
        loop.close()


# ---------------- 会话列表解析 ----------------

def _line_y(d):
    return sum(w[2] for w in d["words"]) / len(d["words"])


def _similar(a, b, th=0.82):
    if a == b:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= th


def parse_list(lines, x0, x1):
    """从整窗 OCR 行里取出会话列表列的行，按 y 排序"""
    out = []
    for d in lines:
        xs = [w[1] for w in d["words"]]
        cx = sum(xs) / len(xs)
        if x0 <= cx <= x1:
            out.append(d)
    return out


_TIME_RES = (
    re.compile(r"^\d{1,2}\s*[:：]\s*\d{1,2}$"),          # 1:40
    re.compile(r"^\d{1,2}\D{1,2}\d{1,2}$"),               # 10/09、10.09
    re.compile(r"^\d+\s*.{0,3}前$"),                      # 5分钟前、3天前、48分前
    re.compile(r"^(昨天|前天|星期[一二三四五六日天])$"),
)


def _looks_like_time(t):
    s = t.replace(" ", "")
    return any(r.match(s) for r in _TIME_RES)


def is_chat_view(lines, x0, x1):
    """当前是不是「消息」页。
    判据：会话列表右侧那列里存在多个时间戳（1:40 / 10/09 / 5分钟前 / 昨天）。
    比找顶部筛选条可靠——筛选条位置会随布局变化，时间戳列位置稳定。
    """
    times = 0
    rows = 0
    for d in lines:
        xs = [w[1] for w in d["words"]]
        cx = sum(xs) / len(xs)
        if 0.28 <= cx <= 0.45 and _looks_like_time(d["text"]):
            times += 1
        if x0 <= cx <= x1 and _line_y(d) > 0.1:
            rows += 1
    return times >= 2 and rows >= 4


def extract_new_messages(cur_lines, prev_lines):
    """对比两轮列表行，返回 [(sender, text)]"""
    msgs = []
    for i, d in enumerate(cur_lines):
        t = d["text"]
        if not t or _is_noise(t):
            continue
        if any(_similar(t, p) for p in prev_lines):
            continue
        # 发送人 = 上面最近的一个非噪声行（会话名在预览的上一行）
        sender = ""
        for j in range(i - 1, max(-1, i - 3), -1):
            st = cur_lines[j]["text"]
            if st and not _is_noise(st):
                sender = st
                break
        msgs.append((sender or "企业微信", t))
    return msgs


# ---------------- 独立会话窗口 ----------------

def extract_window_messages(lines, prev_lines, prev_max_y):
    """独立会话窗口：只认比上一轮更低位置的全新行（排除向上翻历史）"""
    msgs = []
    max_y = prev_max_y
    for d in lines:
        y = _line_y(d)
        t = d["text"]
        if not t or _is_noise(t):
            continue
        if y <= prev_max_y:
            continue
        if any(_similar(t, p) for p in prev_lines):
            continue
        msgs.append(t)
        max_y = max(max_y, y)
    return msgs, max_y


# ---------------- 监视线程 ----------------

class ScreenWatcher:
    def __init__(self, out_queue, interval=3.0, scale=2,
                 list_x=(0.15, 0.38), list_y0=0.06, on_ready=None):
        self.q = out_queue
        self.interval = interval
        self.scale = scale
        self.x0, self.x1 = list_x
        self.y0 = list_y0
        self.on_ready = on_ready
        self._list_prev = []       # 主窗口列表行文本
        self._win_state = {}       # hwnd -> (prev_lines, prev_max_y)
        self._first = True

    def run(self):
        try:
            get_engine()
        except Exception as e:
            log.warning("屏幕捕获不可用：%s", e)
            return
        log.info("屏幕捕获已启动：每 %.1fs 截图识别一次企微窗口", self.interval)
        if self.on_ready:
            try:
                self.on_ready()
            except Exception:
                pass
        while True:
            try:
                self._scan()
            except Exception:
                log.exception("屏幕扫描出错")
            time.sleep(self.interval)

    def _scan(self):
        wins = wecom_windows()
        # 标题相同的企微窗口可能有多个（消息页/工作台页），取面积最大的那个
        mains = [h for h, t in wins if t == MAIN_TITLE]
        for hwnd, title in wins:
            if title != MAIN_TITLE:
                self._scan_conv(hwnd, title)
        if not mains:
            self._list_prev = []
            self._first = True
            STATUS.update(found=False, minimized=False, chat_view=False)
            return
        target = mains[0]
        if len(mains) > 1:
            rr = {}
            for hh in mains:
                r = wintypes.RECT()
                user32.GetWindowRect(hh, ctypes.byref(r))
                rr[hh] = (r.right - r.left) * (r.bottom - r.top)
            target = max(rr, key=rr.get)
        # 最小化时企微会停止渲染，PrintWindow 也只能拿到冻结帧，必须提示用户
        minz = bool(user32.IsIconic(target))
        STATUS["found"] = True
        STATUS["minimized"] = minz
        if minz:
            self._list_prev = []
            self._first = True
            return
        self._scan_main(target)

    def _scan_main(self, hwnd):
        bgra, w, h = capture_scaled(hwnd, self.scale)
        if not bgra:
            return
        lines = ocr(bgra, w, h)
        # 只处理「消息」页；切到工作台/文档等页时清空基线，切回来重新建基线
        chat = is_chat_view(lines, self.x0, self.x1)
        STATUS["chat_view"] = chat
        if not chat:
            if self._list_prev:
                self._list_prev = []
                self._first = True
                log.debug("企微不在消息页，跳过本次识别")
            return
        list_lines = [d for d in parse_list(lines, self.x0, self.x1)
                      if _line_y(d) >= self.y0]
        texts = [d["text"] for d in list_lines]
        if self._first:
            self._first = False
            self._list_prev = texts
            log.info("消息页基线已建立（%d 行）", len(texts))
            return
        for sender, text in extract_new_messages(list_lines, self._list_prev):
            log.info("列表捕获 %s：%s", sender, text[:40])
            self.q.put({"sender": sender, "text": text, "ts": time.time(),
                        "channel": "screen"})
        self._list_prev = texts

    def _scan_conv(self, hwnd, title):
        bgra, w, h = capture_scaled(hwnd, self.scale)
        if not bgra:
            return
        lines = [d for d in ocr(bgra, w, h) if 0.06 < _line_y(d) < 0.82]
        prev_lines, prev_max_y = self._win_state.get(hwnd, ([], 0.0))
        msgs, max_y = extract_window_messages(lines, prev_lines, prev_max_y)
        if msgs and prev_lines:
            text = " ".join(msgs)
            log.info("窗口捕获 %s：%s", title, text[:40])
            self.q.put({"sender": title, "text": text, "ts": time.time(),
                        "channel": "screen"})
        self._win_state[hwnd] = (lines, max_y)

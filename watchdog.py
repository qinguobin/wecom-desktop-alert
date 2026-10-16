# -*- coding: utf-8 -*-
"""
随企业微信自动启停的看门狗（无界面、无第三方依赖、占用极低）

- 检测到企业微信进程（WXWork.exe）-> 自动拉起桌面提醒程序 main.py
- 企业微信退出 -> 提醒程序自动关闭（待办已保存，下次打开企业微信会重新加载）
- 通常随 Windows 登录静默启动（Enable-AutoStart.bat），平时只做一次进程扫描
"""
import ctypes
import json
import logging
import os
import signal
import subprocess
import sys
import time
from ctypes import wintypes

import paths

DEFAULT_AUTO = {
    "wecom_process_names": ["WXWork.exe"],
    # 企业微信退出后是否关闭提醒程序
    "quit_with_wecom": True,
    # 企业微信消失多久后判定为真的退出了（秒），避免更新/重启时误关
    "absent_grace_seconds": 20,
    "poll_seconds": 5,
}

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = -1


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def running_process_names():
    """返回当前所有进程名（小写）集合"""
    names = set()
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        return names
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            names.add(entry.szExeFile.lower())
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return names


def any_process_running(targets):
    names = running_process_names()
    return any(t.lower() in names for t in targets)


def load_auto_config():
    try:
        with open(paths.config_path(), "r", encoding="utf-8") as f:
            cfg = json.load(f).get("auto", {})
    except Exception:
        cfg = {}
    return {**DEFAULT_AUTO, **cfg}


def read_app_pid():
    p = paths.file_in_data("app.pid")
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            pid = int(f.read().strip())
    except Exception:
        return None
    return pid if pid > 0 else None


def pid_alive(pid):
    if not pid:
        return False
    h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if h:
        kernel32.CloseHandle(h)
        return True
    # 权限不足时也能拿到句柄；拿不到再用退出码判断
    return kernel32.GetLastError() == 5


def find_pythonw():
    for c in (r"D:\Python312\pythonw.exe",
              os.path.join(paths.home(), r".venv\Scripts\pythonw.exe")):
        if os.path.exists(c):
            return c
    return "pythonw"


def start_app(log):
    py = find_pythonw()
    script = os.path.join(paths.home(), "main.py")
    try:
        subprocess.Popen([py, script], cwd=paths.home(),
                         creationflags=0x00000008)  # DETACHED_PROCESS
        log.info("企业微信已启动 -> 拉起提醒程序（%s %s）", py, script)
    except Exception:
        log.exception("拉起提醒程序失败")


def stop_app(log):
    pid = read_app_pid()
    if not pid:
        return
    try:
        kernel32.TerminateProcess(kernel32.OpenProcess(0x0001, False, pid), 0)
        log.info("企业微信已退出 -> 关闭提醒程序 pid=%s", pid)
    except Exception as e:
        log.warning("关闭提醒程序失败：%s", e)


def setup_logging():
    log = logging.getLogger("wecom.watchdog")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh = logging.FileHandler(paths.file_in_data("watchdog.log"),
                             encoding="utf-8", mode="a", delay=False)
    fh.setFormatter(fmt)
    log.addHandler(fh)
    return log


def main():
    log = setup_logging()
    cfg = load_auto_config()
    log.info("看门狗启动：监听 %s，每 %ss 扫描一次",
             cfg["wecom_process_names"], cfg["poll_seconds"])

    absent_since = None
    launched = False
    while True:
        try:
            wecom_up = any_process_running(cfg["wecom_process_names"])
            app_up = pid_alive(read_app_pid())

            if wecom_up:
                absent_since = None
                if not app_up:
                    start_app(log)
                    launched = True
            else:
                if absent_since is None:
                    absent_since = time.time()
                if (cfg["quit_with_wecom"] and app_up and launched and
                        time.time() - absent_since >= cfg["absent_grace_seconds"]):
                    stop_app(log)
                    launched = False
        except Exception:
            log.exception("扫描出错")
        time.sleep(cfg["poll_seconds"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass

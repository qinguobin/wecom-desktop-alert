# -*- coding: utf-8 -*-
"""
统一路径管理：程序本体、依赖环境、数据、日志全部落在 D 盘，不占用 C 盘。
可用环境变量 WECOM_ALERT_HOME 覆盖根目录（默认 D:\\WeComDesktopAlert）。
"""
import os

DEFAULT_HOME = r"D:\WeComDesktopAlert"


def home():
    return os.environ.get("WECOM_ALERT_HOME") or DEFAULT_HOME


def data_dir():
    p = os.path.join(home(), "data")
    os.makedirs(p, exist_ok=True)
    return p


def file_in_data(name):
    return os.path.join(data_dir(), name)


def log_path():
    return file_in_data("app.log")


def pending_path():
    return file_in_data("pending.json")


def config_path():
    return os.path.join(home(), "config.json")

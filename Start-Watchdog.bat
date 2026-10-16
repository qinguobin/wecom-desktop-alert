@echo off
chcp 65001 >nul
set "WECOM_ALERT_HOME=D:\WeComDesktopAlert"
set "PYDIR=D:\Python312"
cd /d "%WECOM_ALERT_HOME%"
echo Watchdog running in this window. It starts the alert app when WeCom opens.
echo Press Ctrl+C to stop.
if exist "%PYDIR%\python.exe" (
    "%PYDIR%\python.exe" watchdog.py
) else (
    python watchdog.py
)

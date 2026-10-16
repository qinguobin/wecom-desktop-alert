@echo off
chcp 65001 >nul
set "WECOM_ALERT_HOME=D:\WeComDesktopAlert"
set "PYDIR=D:\Python312"
cd /d "%WECOM_ALERT_HOME%"
if exist "%PYDIR%\python.exe" (
    "%PYDIR%\python.exe" main.py --demo %*
) else (
    python main.py --demo %*
)
pause

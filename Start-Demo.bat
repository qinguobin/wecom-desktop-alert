@echo off
chcp 65001 >nul
set "WECOM_ALERT_HOME=D:\WeComDesktopAlert"
set "PYDIR=D:\Python312"
cd /d "%WECOM_ALERT_HOME%"

if exist "%PYDIR%\pythonw.exe" (
    start "" "%PYDIR%\pythonw.exe" main.py --demo
    exit /b 0
)
if exist "%WECOM_ALERT_HOME%\.venv\Scripts\pythonw.exe" (
    start "" "%WECOM_ALERT_HOME%\.venv\Scripts\pythonw.exe" main.py --demo
    exit /b 0
)
start "" pythonw main.py --demo
exit /b 0

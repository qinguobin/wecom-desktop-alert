@echo off
chcp 65001 >nul
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
if exist "%STARTUP%\WeComAlert-Watchdog.vbs" (
    del /q "%STARTUP%\WeComAlert-Watchdog.vbs"
    echo Disabled. Removed %STARTUP%\WeComAlert-Watchdog.vbs
) else (
    echo Auto-start entry not found, nothing to do.
)
exit /b 0

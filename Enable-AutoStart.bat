@echo off
chcp 65001 >nul
set "HOME_D=D:\WeComDesktopAlert"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

if not exist "%STARTUP%" (
    echo Startup folder not found: %STARTUP%
    exit /b 1
)
copy /y "%HOME_D%\tools\AutoStart.vbs" "%STARTUP%\WeComAlert-Watchdog.vbs" >nul
if errorlevel 1 (
    echo Copy failed.
    exit /b 1
)
echo Enabled. From now on:
echo   - the watchdog starts silently at Windows logon
echo   - it launches the desktop alert app as soon as WeCom starts
echo   - it closes the app when WeCom exits
echo.
echo Startup entry: %STARTUP%\WeComAlert-Watchdog.vbs
echo (a few KB only; the app and its data stay on D:)
exit /b 0

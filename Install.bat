@echo off
chcp 65001 >nul
set "HOME_D=D:\WeComDesktopAlert"
set "PYDIR=D:\Python312"

echo === WeCom Desktop Alert installer : everything stays on D: ===

if exist "%PYDIR%\python.exe" goto havepy

echo Downloading Python 3.12.10 to %HOME_D%\setup ...
if not exist "%HOME_D%\setup" mkdir "%HOME_D%\setup"
curl -L -o "%HOME_D%\setup\python-installer.exe" https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe
if errorlevel 1 goto fail

echo Installing Python to %PYDIR% (silent, per-user, no PATH change) ...
"%HOME_D%\setup\python-installer.exe" /quiet InstallAllUsers=0 TargetDir=%PYDIR% AssociateFiles=0 Shortcuts=0 Include_launcher=0 PrependPath=0 Include_tcltk=1 Include_test=0
if not exist "%PYDIR%\python.exe" goto fail

:havepy
echo Installing dependencies into %PYDIR% ...
"%PYDIR%\python.exe" -m pip install --disable-pip-version-check -r "%HOME_D%\requirements.txt"
if errorlevel 1 goto fail

echo.
echo Done.
echo Next: edit %HOME_D%\config.json - set filter.my_names to your WeCom nickname,
echo       then run Start.bat  (or Start-Demo.bat to see it working without WeCom)
exit /b 0

:fail
echo Installation failed. See messages above.
exit /b 1

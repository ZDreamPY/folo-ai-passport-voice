@echo off
setlocal
cd /d "%~dp0"
title AI Passport Voice - Build EXE

rem Package AI-Passport-Voice.exe (one-file, double-click without Python).
rem Requires local Python 3.11 + pyinstaller (pip install pyinstaller).

set "PY=python.exe"
py -3.11 --version >nul 2>&1 && set "PY=py -3.11"

rem 0) Generate the icon when missing (ASCII-only scripts; ico is not tracked in git).
if not exist "icon.ico" %PY% make_icon.py

rem 1) Stop running tray/forwarder and the old exe to avoid file locks.
taskkill /f /im AI-Passport-Voice.exe >nul 2>&1

rem 2) PyInstaller build (onefile + windowed).
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name AI-Passport-Voice ^
  --icon icon.ico ^
  --hidden-import pystray._win32 ^
  --collect-submodules pystray ^
  tray_app.py
if errorlevel 1 (
  echo Build failed. Read the error above.
  pause
  exit /b 1
)

rem 3) Move the artifact next to start.cmd (start.cmd and autostart use it).
copy /y "dist\AI-Passport-Voice.exe" "AI-Passport-Voice.exe" >nul
echo.
echo Done: AI-Passport-Voice.exe
pause

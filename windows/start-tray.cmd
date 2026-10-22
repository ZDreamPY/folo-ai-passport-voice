@echo off
setlocal
cd /d "%~dp0"
title AI Passport Voice - Tray

rem Prefer the packaged exe (no Python needed); fall back to venv/system Python.
if exist "AI-Passport-Voice.exe" (
  start "" "AI-Passport-Voice.exe" --tray
  exit /b 0
)

rem Pick venv or system Python.
set "PY=python.exe"
set "PYW=pythonw.exe"
if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
  set "PYW=.venv\Scripts\pythonw.exe"
)

rem Dependency check with a visible hint when missing.
%PY% -c "import pystray, PIL, sounddevice" >nul 2>&1
if errorlevel 1 (
  echo Missing dependencies. Run install.cmd first.
  echo Chinese guide: docs/QUICKSTART.zh-CN.md
  pause
  exit /b 1
)

rem Start the resident tray (pythonw = no console); the settings panel opens in the browser.
start "" "%PYW%" tray_app.py
exit /b 0

@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title AI Passport Voice - Setup

rem ============================================================
rem  AI Passport Voice one-click setup (ASCII only: cmd.exe
rem  parses batch files in the ANSI codepage, UTF-8 Chinese
rem  comments would corrupt the script on zh-CN Windows).
rem  1) Detect and install VB-CABLE (downloaded from the
rem     official VB-Audio site, needs admin + one reboot)
rem  2) Detect Python and install pip dependencies
rem ============================================================

echo.
echo ===== AI Passport Voice Setup =====
echo.

rem ---------- Step 1: VB-CABLE detection ----------
set "CABLE_OK="
where py >nul 2>&1 && (
  py -3.11 -c "import sounddevice as sd; import sys; sys.exit(0 if any('cable' in d['name'].lower() for d in sd.query_devices() if d['max_output_channels']>0) else 1)" >nul 2>&1 && set "CABLE_OK=1"
)
if not defined CABLE_OK (
  powershell -NoProfile -Command "if((Get-CimInstance Win32_SoundDevice | Select-Object -ExpandProperty Name) -match 'VB-Audio'){exit 0}else{exit 1}" >nul 2>&1 && set "CABLE_OK=1"
)
if defined CABLE_OK (
  echo [1/2] VB-CABLE virtual audio device: already installed, skip.
) else (
  echo [1/2] VB-CABLE not found. Installing from the official site...
  echo       Source: https://vb-audio.com/Cable/
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-cable.ps1"
  if errorlevel 1 (
    echo.
    echo       Automatic install failed. Please install manually:
    echo       1. Download VBCABLE_Driver_Pack45.zip from https://vb-audio.com/Cable/
    echo       2. Extract, right-click VBCABLE_Setup_x64.exe, "Run as administrator"
    echo       3. REBOOT after installation.
    echo.
  ) else (
    echo.
    echo       The VB-CABLE installer window is open. Click "Install Driver".
    echo       REBOOT is required after installation!
    echo       Then set your IME recognition microphone to "CABLE Output".
    echo.
  )
)

rem ---------- Step 2: Python dependencies (optional) ----------
where py >nul 2>&1 || (
  echo [2/2] Python not found: skip pip setup. Not required when using AI-Passport-Voice.exe.
  goto done
)
py -3.11 --version >nul 2>&1 || (
  echo [2/2] Python 3.11 x64 is required for source-mode runs:
  echo       https://www.python.org/downloads/windows/
  echo       Tick "Add Python to environment variables" during setup, then re-run this script.
  goto done
)
echo [2/2] Installing Python dependencies (sounddevice/pystray/Pillow)...
py -3.11 -m venv .venv 2>nul
if exist ".venv\Scripts\python.exe" (
  set "PIP=.venv\Scripts\python.exe -m pip"
) else (
  set "PIP=py -3.11 -m pip"
)
%PIP% install -r requirements.txt
if errorlevel 1 (
  echo Retrying with the Tsinghua PyPI mirror for mainland networks...
  %PIP% install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
)
if errorlevel 1 (
  echo Dependency install failed: only affects source-mode runs, the exe works without it.
)

:done
echo.
echo ===== Setup finished =====
echo Next: double-click start.cmd to launch the tray, then finish hotkey and
echo audio settings in the settings panel (see docs/QUICKSTART.zh-CN.md).
echo If VB-CABLE was just installed: reboot first, and set the IME microphone
echo to CABLE Output. Chinese guide: docs/QUICKSTART.zh-CN.md
echo.
pause

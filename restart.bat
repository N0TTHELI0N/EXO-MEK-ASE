@echo off
chcp 65001 >nul
rem ASCII-only. Launches the Exo-Mek bot with the REAL venv python,
rem bypassing the broken WindowsApps python stub on PATH.
cd /d "%~dp0"
set "V2=%LOCALAPPDATA%\Temp\opencode\venv\Scripts\python.exe"
if not exist "%V2%" (
  echo VENV_MISSING>&2
  pause
  exit /b 1
)
if exist "run.py" (
  "%V2%" run.py
) else if exist "main.py" (
  "%V2%" main.py
) else (
  echo NO_ENTRY>&2
  pause
  exit /b 1
)

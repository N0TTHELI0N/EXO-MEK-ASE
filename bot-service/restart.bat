@echo off
chcp 65001 >nul
rem ASCII-only. Launches the Exo-Mek BOT SERVICE from its own folder.
rem The Flask dashboard is a separate service - see ..\dashboard-service\.
rem Uses a local .venv when present, otherwise the first working Python.
cd /d "%~dp0"

set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"
if not defined PY for %%P in (python python3 py) do (
  if not defined PY (
    %%P -c "import sys" >nul 2>&1 && set "PY=%%P"
  )
)

if not defined PY (
  echo NO_PYTHON: install Python 3.11+ or create .venv inside this folder.&2
  pause
  exit /b 1
)

if not exist "run.py" (
  echo NO_ENTRY: run.py is missing from this folder.&2
  pause
  exit /b 1
)

echo [%PY%] run.py
"%PY%" run.py %*

@echo off
REM Run the EVE LP -> ISK optimizer command-line tool on Windows.
REM Arguments are passed straight through, e.g.:
REM    run-cli.bat --corp "Caldari Navy:169675" --top 30
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment ^(first run^)...
  py -3 -m venv .venv 2>nul
  if not exist ".venv\Scripts\python.exe" python -m venv .venv
  if not exist ".venv\Scripts\python.exe" (
    echo.
    echo ERROR: could not create a virtual environment.
    echo Install Python 3.9+ first:  winget install --id Python.Python.3.12 -e
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

".venv\Scripts\python.exe" -m eve_lp %*

@echo off
rem Double-click to launch PhotoForge. First run sets everything up automatically.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Setting up PhotoForge for the first time, please wait...
    python -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
)
start "" ".venv\Scripts\pythonw.exe" main.py %*
exit /b 0
:error
echo.
echo Setup failed. Make sure Python 3.10+ is installed from https://python.org
pause

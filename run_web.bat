@echo off
REM CAN CRC Checker web launcher. Usage: run_web.bat [port]
REM
REM frontend/dist is committed to git, so deploy machines do not need Node:
REM   after changing the frontend run: cd frontend && npm run build
REM
REM Comments here stay ASCII on purpose: this file is UTF-8 without a BOM and
REM cmd.exe parses .bat files with the OEM code page, so non-ASCII REM lines
REM can be misread as commands on a Chinese Windows console.
REM
REM The interpreter is probed in order and the first one that can import
REM uvicorn wins:
REM   1. .venv\Scripts\python.exe in this repository
REM   2. python from PATH
REM If neither works we fail with an install hint instead of letting uvicorn
REM raise ModuleNotFoundError.
setlocal
cd /d "%~dp0"

set PORT=%~1
if "%PORT%"=="" set PORT=8000

set "PY="
for %%P in ("%~dp0.venv\Scripts\python.exe" "python") do (
    if not defined PY (
        %%P -c "import uvicorn" >nul 2>&1
        if not errorlevel 1 set "PY=%%~P"
    )
)

if not defined PY (
    echo [ERROR] No Python interpreter with uvicorn found.
    echo   Tried: %~dp0.venv\Scripts\python.exe and python from PATH.
    echo   Install the web dependencies first:
    echo     python -m pip install -r requirements.txt
    echo   Optional venv:
    echo     python -m venv .venv
    echo     .venv\Scripts\python -m pip install -r requirements.txt
    exit /b 1
)

echo CAN CRC Checker Web
echo   Local:  http://127.0.0.1:%PORT%
echo   Bind:   0.0.0.0:%PORT%  (LAN clients can connect if the firewall allows)
echo   Python: %PY%

"%PY%" -m uvicorn webapp.main:app --host 0.0.0.0 --port %PORT%

endlocal

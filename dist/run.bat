@echo off
REM Run CAN CRC Checker with config file
REM Usage: run.bat [config.json]   (default: gwm_config.json)

setlocal
cd /d "%~dp0"

set CONFIG=%~1
if "%CONFIG%"=="" set CONFIG=gwm_config.json

if not exist "%CONFIG%" (
    echo Config not found: %CONFIG%
    exit /b 1
)

echo CRC Check: %CONFIG%
crc-check.exe run -c "%CONFIG%" -v

if %errorlevel% neq 0 pause
endlocal

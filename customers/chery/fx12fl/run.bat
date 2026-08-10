@echo off
REM Chery FX12FL CAN CRC Checker
REM Usage: run.bat [config.json]   (default: config.json)

setlocal
cd /d "%~dp0"

set CONFIG=%~1
if "%CONFIG%"=="" set CONFIG=config.json

if not exist "%CONFIG%" (
    echo Config not found: %CONFIG%
    pause
    exit /b 1
)

echo Chery FX12FL CAN CRC Check: %CONFIG%
crc-check.exe run -c "%CONFIG%" -v

if %errorlevel% neq 0 pause
endlocal

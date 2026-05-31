@echo off
REM ============================================================
REM  CAN CRC Checker — Package for customer distribution
REM  Usage: package.bat <customer>   (e.g. package.bat gwm)
REM ============================================================

set CUSTOMER=%~1
if "%CUSTOMER%"=="" (
    echo Usage: package.bat ^<customer^>
    echo   e.g. package.bat gwm
    echo/
    echo Available customers:
    for /d %%D in (customers\*) do echo   - %%~nxD
    exit /b 1
)

set CUST_DIR=customers\%CUSTOMER%
if not exist "%CUST_DIR%" (
    echo Customer directory not found: %CUST_DIR%
    exit /b 1
)

echo/
echo === Packaging for: %CUSTOMER% ===
echo/

REM Check / build exe
if not exist "dist\crc-check.exe" (
    echo Building exe...
    call build.bat
    if not exist "dist\crc-check.exe" (
        echo Build failed!
        exit /b 1
    )
)

REM Create output dir
set OUT_DIR=release\%CUSTOMER%
if exist "%OUT_DIR%" rmdir /s /q "%OUT_DIR%" 2>nul
mkdir "%OUT_DIR%" 2>nul

REM Copy exe
echo [1/3] Copying exe...
copy /y dist\crc-check.exe "%OUT_DIR%\" >nul 2>&1

REM Copy customer files (excluding trace, report)
echo [2/3] Copying config and scripts...
for %%F in (config.json run.bat run.sh README.md) do (
    if exist "%CUST_DIR%\%%F" copy /y "%CUST_DIR%\%%F" "%OUT_DIR%\" >nul 2>&1
)

REM Copy dbc directory
if exist "%CUST_DIR%\dbc" (
    echo [3/3] Copying dbc...
    mkdir "%OUT_DIR%\dbc" 2>nul
    xcopy /e /i /q /y "%CUST_DIR%\dbc\*" "%OUT_DIR%\dbc\" >nul 2>&1
)

REM Create empty trace dir
mkdir "%OUT_DIR%\trace" 2>nul

echo/
echo === Package ready: %OUT_DIR% ===
dir /b "%OUT_DIR%"
echo/
echo To distribute, zip the %OUT_DIR% folder.

@echo off
REM ============================================================
REM  CAN CRC Checker — Package for customer distribution
REM  Usage: package.bat <customer>   (e.g. package.bat gwm)
REM ============================================================
setlocal enabledelayedexpansion

set CUSTOMER=%~1
if "%CUSTOMER%"=="" (
    echo Usage: package.bat ^<customer^>
    echo   e.g. package.bat gwm
    echo.
    echo Available customers:
    for /d %%D in (customers\*) do echo   - %%~nxD
    exit /b 1
)

set CUST_DIR=customers\%CUSTOMER%
if not exist "%CUST_DIR%" (
    echo Customer directory not found: %CUST_DIR%
    exit /b 1
)

echo.
echo === Packaging for: %CUSTOMER% ===
echo.

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
if exist "%OUT_DIR%" rmdir /s /q "%OUT_DIR%"
mkdir "%OUT_DIR%"

REM Copy exe
echo Copying crc-check.exe...
copy /y dist\crc-check.exe "%OUT_DIR%\" >nul

REM Copy customer files
echo Copying %CUSTOMER% files...
xcopy /e /i /q "%CUST_DIR%\*" "%OUT_DIR%\" >nul

REM Remove trace and report from package (keep dbc)
if exist "%OUT_DIR%\trace" rmdir /s /q "%OUT_DIR%\trace"
if exist "%OUT_DIR%\report.html" del "%OUT_DIR%\report.html"
mkdir "%OUT_DIR%\trace"

echo.
echo === Package ready: %OUT_DIR% ===
dir /b "%OUT_DIR%"
echo.
echo To distribute, zip the %OUT_DIR% folder.
endlocal

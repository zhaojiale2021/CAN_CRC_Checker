@echo off
REM ============================================================
REM  CAN CRC Checker - Package customer release
REM
REM  Usage:
REM    package.bat              Package all customers
REM    package.bat gac/eea40    Package GAC EEA4.0 only
REM    package.bat gac/radar    Package GAC radar buses only
REM    package.bat gwm/de09g    Package GWM DE09G only
REM    package.bat chery/t1jfl3 Package Chery T1JFL3 only
REM    package.bat chery/fx12fl Package Chery FX12FL only
REM    package.bat chery/t1lfl1 Package Chery T1LFL1 only
REM    package.bat baic/b81vs   Package BAIC B81VS only
REM ============================================================
setlocal enabledelayedexpansion

set TARGET=%~1
set RELEASE_DIR=release

echo.
echo ========================================
echo  CAN CRC Checker - Package Release
echo ========================================
echo.

REM Check / build exe
if not exist "dist\crc-check.exe" (
    echo Building exe...
    call build.bat
    if not exist "dist\crc-check.exe" (
        echo Build failed!
        pause
        exit /b 1
    )
)

REM Clean release
if exist "%RELEASE_DIR%" rmdir /s /q "%RELEASE_DIR%"

if "%TARGET%"=="" (
    call :package gac\eea40
    call :package gac\eea30-hev
    call :package gac\eea30-bev
    call :package gac\radar
    call :package gwm\de09g
    call :package gwm\b06-5
    call :package chery\t1jfl3
    call :package chery\fx12fl
    call :package chery\t1lfl1
    call :package baic\b81vs
    goto :end
)

call :package %TARGET%
goto :end

:package
set CUST=%~1
set CUST_SRC=customers\%CUST%
set CUST_OUT=%RELEASE_DIR%\%CUST%

if not exist "%CUST_SRC%" (
    echo [WARN] Not found: %CUST_SRC%
    exit /b 1
)

echo Packaging: %CUST%

mkdir "%CUST_OUT%"              2>nul
mkdir "%CUST_OUT%\dbc"          2>nul
mkdir "%CUST_OUT%\trace"        2>nul

copy /y "dist\crc-check.exe" "%CUST_OUT%\" >nul
if exist "%CUST_SRC%\config.json"   copy /y "%CUST_SRC%\config.json"   "%CUST_OUT%\" >nul
if exist "%CUST_SRC%\run.bat"       copy /y "%CUST_SRC%\run.bat"       "%CUST_OUT%\" >nul
if exist "%CUST_SRC%\run.sh"        copy /y "%CUST_SRC%\run.sh"        "%CUST_OUT%\" >nul
if exist "%CUST_SRC%\README.md"     copy /y "%CUST_SRC%\README.md"     "%CUST_OUT%\" >nul

REM Copy DBC files + dataid.json
if exist "%CUST_SRC%\dbc\*.dbc"     xcopy /y /q "%CUST_SRC%\dbc\*.dbc"     "%CUST_OUT%\dbc\" >nul 2>&1
if exist "%CUST_SRC%\dbc\dataid.json" copy /y "%CUST_SRC%\dbc\dataid.json" "%CUST_OUT%\dbc\" >nul

echo   Done: %CUST_OUT%
exit /b 0

:end
echo.
echo ========================================
echo  Package Complete: %RELEASE_DIR%
echo ========================================
echo.
dir /ad /b "%RELEASE_DIR%" 2>nul
echo.
endlocal

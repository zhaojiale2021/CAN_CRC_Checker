@echo off
REM ============================================================
REM  CAN CRC Checker — Build standalone .exe
REM ============================================================
setlocal

echo.
echo === CAN CRC Checker Build ===
echo.

REM Check PyInstaller
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

REM Clean previous build
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist crc-check.spec del crc-check.spec

echo Building...
pyinstaller --onefile --name crc-check ^
    --hidden-import canmatrix ^
    --hidden-import canmatrix.formats ^
    --hidden-import canmatrix.formats.dbc ^
    --hidden-import openpyxl ^
    --collect-all canmatrix ^
    cli/main.py

echo.
if exist dist\crc-check.exe (
    echo Done: dist\crc-check.exe
    echo Copy to customer directory to use.
) else (
    echo Build failed!
)

echo.
endlocal

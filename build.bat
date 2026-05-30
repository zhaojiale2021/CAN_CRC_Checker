@echo off
REM ============================================================
REM  CAN CRC Checker — Build standalone .exe
REM  Usage: build.bat           (full build with TUI)
REM         build.bat cli       (CLI-only, smaller ~32 MB)
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

REM Common hidden imports
set HIDDEN=--hidden-import canmatrix --hidden-import canmatrix.formats --hidden-import canmatrix.formats.dbc --hidden-import openpyxl --collect-all canmatrix

if "%1"=="cli" (
    echo Building CLI-only version (no TUI)...
    pyinstaller --onefile --name crc-check %HIDDEN% --exclude-module textual --exclude-module rich cli/main.py
    echo.
    echo Done: dist\crc-check.exe
) else (
    echo Building full version (CLI + TUI)...
    pyinstaller --onefile --name crc-check %HIDDEN% --hidden-import textual cli/main.py
    echo.
    echo Done: dist\crc-check.exe
)

REM Show size
if exist dist\crc-check.exe (
    for %%A in (dist\crc-check.exe) do echo Size: %%~zA bytes
)

echo.
echo === Build Complete ===
endlocal

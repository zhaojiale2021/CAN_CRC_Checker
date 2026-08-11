@echo off
REM Install git hooks (pylint 10/10 pre-push gate) into .git/hooks
REM Run once after cloning. Requires python + pylint in PATH.
setlocal
cd /d "%~dp0"

if not exist "hooks\pre-push" (
    echo [ERROR] hooks\pre-push not found
    exit /b 1
)

copy /y "hooks\pre-push" ".git\hooks\pre-push" >nul
echo Installed: .git\hooks\pre-push
echo pylint 10.00/10 required before every git push.
endlocal

@echo off
REM CAN CRC Checker 网页版启动脚本。用法: run_web.bat [端口]
REM
REM 前端产物在 frontend\dist(已提交进 git,部署机无需 Node):
REM   改完前端记得 cd frontend && npm run build
setlocal
cd /d "%~dp0"

set PORT=%~1
if "%PORT%"=="" set PORT=8000

echo CAN CRC Checker Web: http://127.0.0.1:%PORT%
python -m uvicorn webapp.main:app --host 0.0.0.0 --port %PORT%

endlocal

#!/usr/bin/env bash
# CAN CRC Checker 网页版启动脚本。用法: ./run_web.sh [端口]
#
# 前端产物在 frontend/dist(已提交进 git,部署机无需 Node):
#   改完前端记得 cd frontend && npm run build
set -euo pipefail
cd "$(dirname "$0")"

PORT="${1:-${PORT:-8000}}"
exec python3 -m uvicorn webapp.main:app --host 0.0.0.0 --port "$PORT"

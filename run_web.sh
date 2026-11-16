#!/usr/bin/env bash
# CanVouch 网页版启动脚本。用法: ./run_web.sh [端口] [host]
#
# 前端产物在 frontend/dist(已提交进 git,部署机无需 Node):
#   改完前端记得 cd frontend && npm run build
#
# 解释器按顺序探测,第一个能 import uvicorn 的胜出(与 run_web.bat 一致):
#   1. .venv/bin/python(仓库内虚拟环境)
#   2. python3 / python(PATH)
set -euo pipefail
cd "$(dirname "$0")"

PORT="${1:-${PORT:-8000}}"
HOST="${2:-${CANVOUCH_WEB_HOST:-${CRC_WEB_HOST:-127.0.0.1}}}"

PY=""
for candidate in "./.venv/bin/python" "python3" "python"; do
    if command -v "$candidate" >/dev/null 2>&1 \
        && "$candidate" -c "import uvicorn" >/dev/null 2>&1; then
        PY="$candidate"
        break
    fi
done

if [ -z "$PY" ]; then
    echo "[ERROR] No Python interpreter with uvicorn found." >&2
    echo "  Tried: .venv/bin/python, python3, python" >&2
    echo "  Install the web dependencies first:" >&2
    echo "    python3 -m pip install -r requirements.txt" >&2
    exit 1
fi

echo "CanVouch Web"
echo "  Local:  http://127.0.0.1:${PORT}"
echo "  Host:   ${HOST}:${PORT}"
echo "  Python: ${PY}"

exec "$PY" -m uvicorn webapp.main:app --host "$HOST" --port "$PORT"

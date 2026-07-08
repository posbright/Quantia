#!/bin/bash

# 代理池预热常驻守护启动脚本（方案 B）
# 由 supervisor 常驻拉起（见 supervisor/supervisord.conf 的 [program:proxy_warmer]）。

# 获取脚本所在目录，计算项目根目录
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)

export PYTHONIOENCODING=utf-8
export LANG=C.UTF-8
export PYTHONPATH=$PROJECT_ROOT
export LC_CTYPE=C.UTF-8

# Python 解释器：显式 PYTHON_BIN > 项目本地 .venv > 系统 python3（与 cron/_common.sh 一致）
if [ -n "${PYTHON_BIN:-}" ]; then
    PY="$PYTHON_BIN"
elif [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
    PY="$PROJECT_ROOT/.venv/bin/python"
else
    PY="python3"
fi

echo "项目目录: $PROJECT_ROOT"
echo "Python 解释器: $PY"
echo "启动代理池预热守护..."

exec "$PY" $PROJECT_ROOT/quantia/job/proxy_warmer_daemon.py

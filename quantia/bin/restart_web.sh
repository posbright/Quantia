#!/bin/bash

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

# 停止旧的 web 服务（按脚本路径匹配，不依赖解释器名为 python3）
ps -ef | grep 'web_service.py' | grep -v grep | awk '{print $2}' | xargs -r kill -9 2>/dev/null

# 等待进程完全退出
sleep 2

# 确保日志目录存在
mkdir -p $PROJECT_ROOT/quantia/log

# 启动新的 web 服务
nohup "$PY" $PROJECT_ROOT/quantia/web/web_service.py > $PROJECT_ROOT/quantia/log/web_service.log 2>&1 &

echo "Web服务已重启"
echo "项目目录: $PROJECT_ROOT"
echo "日志文件: $PROJECT_ROOT/quantia/log/web_service.log"
echo "访问地址: http://localhost:9988/"

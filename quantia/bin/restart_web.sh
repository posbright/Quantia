#!/bin/bash

# 获取脚本所在目录，计算项目根目录
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)

export PYTHONIOENCODING=utf-8
export LANG=zh_CN.UTF-8
export PYTHONPATH=$PROJECT_ROOT
export LC_CTYPE=zh_CN.UTF-8

# 停止旧的 web 服务
ps -ef | grep python3 | grep 'web_service.py' | grep -v grep | awk '{print $2}' | xargs -r kill -9 2>/dev/null

# 等待进程完全退出
sleep 2

# 确保日志目录存在
mkdir -p $PROJECT_ROOT/quantia/log

# 启动新的 web 服务
nohup python3 $PROJECT_ROOT/quantia/web/web_service.py > $PROJECT_ROOT/quantia/log/web_service.log 2>&1 &

echo "Web服务已重启"
echo "项目目录: $PROJECT_ROOT"
echo "日志文件: $PROJECT_ROOT/quantia/log/web_service.log"
echo "访问地址: http://localhost:9988/"

#!/bin/bash

# 获取脚本所在目录，计算项目根目录
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)

export PYTHONIOENCODING=utf-8
export LANG=zh_CN.UTF-8
export PYTHONPATH=$PROJECT_ROOT
export LC_CTYPE=zh_CN.UTF-8

echo "项目目录: $PROJECT_ROOT"
echo "启动Web服务..."

python3 $PROJECT_ROOT/quantia/web/web_service.py

echo "------Web服务已启动 请不要关闭------"
echo "访问地址: http://localhost:9988/"

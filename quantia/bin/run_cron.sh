#!/bin/bash

# 获取脚本所在目录，计算项目根目录
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)

export PYTHONIOENCODING=utf-8
export LANG=zh_CN.UTF-8
export PYTHONPATH=$PROJECT_ROOT
export LC_CTYPE=zh_CN.UTF-8

# 环境变量输出（用于cron任务）
# https://stackoverflow.com/questions/27771781/how-can-i-access-docker-set-environment-variables-from-a-cron-job
printenv | grep -v "no_proxy" >> /etc/environment

echo "项目目录: $PROJECT_ROOT"

# 启动cron服务（前台运行）
/usr/sbin/cron -f
#!/bin/bash
# ============================================================
#  后台服务管理脚本 — 启动 / 停止 / 重启 / 状态查询
#
#  用法:
#    ./server.sh start     启动后台服务（Web + Vite前端）
#    ./server.sh stop      停止后台服务
#    ./server.sh restart   重启后台服务
#    ./server.sh status    查看运行状态
#    ./server.sh web       仅启动后端 Web (port 9988)
#    ./server.sh front     仅启动前端 Vite dev (port 3000)
# ============================================================

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)

export PYTHONPATH="$PROJECT_ROOT"
export PYTHONIOENCODING=utf-8
export LANG=zh_CN.UTF-8
export LC_CTYPE=zh_CN.UTF-8

WEB_PORT=9988
FRONT_PORT=3000
LOG_DIR="$PROJECT_ROOT/quantia/log"
WEB_PID="$LOG_DIR/web.pid"
FRONT_PID="$LOG_DIR/front.pid"
WEB_LOG="$LOG_DIR/web_service.log"
FRONT_LOG="$LOG_DIR/front_dev.log"

mkdir -p "$LOG_DIR"

# 激活虚拟环境
VENV="$PROJECT_ROOT/.venv/bin/activate"
if [ -f "$VENV" ]; then
    source "$VENV"
fi

# ── 获取端口上的 PID ──
get_pid_on_port() {
    local port=$1
    lsof -ti :"$port" 2>/dev/null | head -1
}

# ── 启动后端 ──
start_web() {
    local pid=$(get_pid_on_port $WEB_PORT)
    if [ -n "$pid" ]; then
        echo "[后端] 端口 $WEB_PORT 已被占用 (PID=$pid)，跳过启动"
        return
    fi
    echo "[后端] 启动 Web 服务 (port $WEB_PORT) ..."
    nohup python3 "$PROJECT_ROOT/quantia/web/web_service.py" \
        > "$WEB_LOG" 2>&1 &
    local new_pid=$!
    echo "$new_pid" > "$WEB_PID"
    sleep 3
    if kill -0 "$new_pid" 2>/dev/null; then
        echo "[后端] 启动成功  PID=$new_pid  http://localhost:$WEB_PORT/"
    else
        echo "[后端] 启动失败，请查看日志: $WEB_LOG"
        tail -20 "$WEB_LOG"
    fi
}

# ── 启动前端 ──
start_front() {
    local pid=$(get_pid_on_port $FRONT_PORT)
    if [ -n "$pid" ]; then
        echo "[前端] 端口 $FRONT_PORT 已被占用 (PID=$pid)，跳过启动"
        return
    fi
    echo "[前端] 启动 Vite 开发服务器 (port $FRONT_PORT) ..."
    cd "$PROJECT_ROOT/quantia/fontWeb"
    nohup npm run dev > "$FRONT_LOG" 2>&1 &
    local new_pid=$!
    echo "$new_pid" > "$FRONT_PID"
    cd "$PROJECT_ROOT"
    sleep 5
    local check_pid=$(get_pid_on_port $FRONT_PORT)
    if [ -n "$check_pid" ]; then
        echo "[前端] 启动成功  PID=$check_pid  http://localhost:$FRONT_PORT/"
    else
        echo "[前端] 启动失败，请查看日志: $FRONT_LOG"
        tail -20 "$FRONT_LOG"
    fi
}

# ── 停止后端 ──
stop_web() {
    local pid=$(get_pid_on_port $WEB_PORT)
    if [ -n "$pid" ]; then
        kill -9 "$pid" 2>/dev/null || true
        echo "[后端] 已停止 PID=$pid"
    else
        echo "[后端] 未运行"
    fi
    rm -f "$WEB_PID"
}

# ── 停止前端 ──
stop_front() {
    local pid=$(get_pid_on_port $FRONT_PORT)
    if [ -n "$pid" ]; then
        kill -9 "$pid" 2>/dev/null || true
        echo "[前端] 已停止 PID=$pid"
    else
        echo "[前端] 未运行"
    fi
    rm -f "$FRONT_PID"
}

# ── 状态查询 ──
show_status() {
    echo "===== 服务状态 ====="
    local web_pid=$(get_pid_on_port $WEB_PORT)
    if [ -n "$web_pid" ]; then
        echo "[后端] 运行中  PID=$web_pid  http://localhost:$WEB_PORT/"
    else
        echo "[后端] 未运行"
    fi
    local front_pid=$(get_pid_on_port $FRONT_PORT)
    if [ -n "$front_pid" ]; then
        echo "[前端] 运行中  PID=$front_pid  http://localhost:$FRONT_PORT/"
    else
        echo "[前端] 未运行"
    fi
    echo "===================="
}

# ── 帮助 ──
show_usage() {
    echo ""
    echo "  后台服务管理脚本"
    echo "  ────────────────────────────────"
    echo "  用法: $(basename "$0") <命令>"
    echo ""
    echo "  命令:"
    echo "    start     启动后端 + 前端"
    echo "    stop      停止后端 + 前端"
    echo "    restart   重启全部服务"
    echo "    status    查看运行状态"
    echo "    web       仅启动后端 (port $WEB_PORT)"
    echo "    front     仅启动前端 (port $FRONT_PORT)"
    echo ""
}

# ── 主入口 ──
case "${1:-}" in
    start)
        start_web
        start_front
        ;;
    stop)
        stop_web
        stop_front
        ;;
    restart)
        stop_web
        stop_front
        sleep 2
        start_web
        start_front
        ;;
    status)
        show_status
        ;;
    web)
        start_web
        ;;
    front)
        start_front
        ;;
    *)
        show_usage
        ;;
esac

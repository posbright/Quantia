#!/bin/bash
# ═══════════════════════════════════════════════════════════
# Cron 脚本公共库 — 所有定时脚本在 source 前必须设置 PROJECT_ROOT
# ═══════════════════════════════════════════════════════════

# ─── 环境初始化 ───
# 设置 PATH、编码、PYTHONPATH，加载 .env 文件，创建日志目录
init_env() {
    export PATH=/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin:$PATH
    export PYTHONIOENCODING=utf-8
    export LANG=zh_CN.UTF-8
    export LC_CTYPE=zh_CN.UTF-8
    export PYTHONPATH=$PROJECT_ROOT

    # 加载 .env（兼容方法 A 系统环境变量 + 方法 B .env 文件）
    if [ -f "$PROJECT_ROOT/.env" ]; then
        set -a; source "$PROJECT_ROOT/.env"; set +a
    fi

    # Python 解释器（可通过 .env 的 PYTHON_BIN 覆盖）
    export PYTHON_BIN="${PYTHON_BIN:-python3}"

    # 日志目录
    LOG_DIR=$PROJECT_ROOT/quantia/log
    mkdir -p "$LOG_DIR"
}

# ─── 日志工具 ───
_ts() { date '+%Y-%m-%d %H:%M:%S'; }

log_info()  { echo "[$(_ts)] [INFO]  $*" >> "$LOG_FILE"; }
log_warn()  { echo "[$(_ts)] [WARN]  $*" >> "$LOG_FILE"; }
log_error() { echo "[$(_ts)] [ERROR] $*" >> "$LOG_FILE"; }

# 格式化秒数为可读字符串（如 1h05m30s / 3m22s / 45s）
elapsed_fmt() {
    local s=$1
    if [ "$s" -ge 3600 ] 2>/dev/null; then
        printf "%dh%02dm%02ds" $((s/3600)) $((s%3600/60)) $((s%60))
    elif [ "$s" -ge 60 ] 2>/dev/null; then
        printf "%dm%02ds" $((s/60)) $((s%60))
    else
        printf "%ds" "$s"
    fi
}

# ─── 交易日检测 ───
# 用法: check_trade_day "任务名称"
# 非交易日时自动 exit 0，调用方无需处理返回值
check_trade_day() {
    local task_name="${1:-任务}"
    local is_trade
    is_trade=$("$PYTHON_BIN" -c "
import sys; sys.path.insert(0, '$PROJECT_ROOT')
try:
    import quantia.lib.trade_time as trd
    print('1' if trd.is_trade_date() else '0')
except Exception:
    print('1')
" 2>/dev/null)

    if [ "$is_trade" = "0" ]; then
        log_info "非交易日，跳过${task_name}"
        exit 0
    fi
}

# ─── 运行 Python 作业 ───
# 用法: run_job "标签" "脚本相对路径" [超时秒数]
# 返回: Python 进程退出码（124 = 超时）
run_job() {
    local label="$1"
    local script="$2"
    local timeout="${3:-0}"
    local start_ts rc end_ts dur dur_str

    start_ts=$(date +%s)
    log_info "────── ${label} 开始 ──────"

    if [ "$timeout" -gt 0 ] 2>/dev/null; then
        timeout "$timeout" "$PYTHON_BIN" "$PROJECT_ROOT/$script" >> "$LOG_FILE" 2>&1
    else
        "$PYTHON_BIN" "$PROJECT_ROOT/$script" >> "$LOG_FILE" 2>&1
    fi
    rc=$?

    end_ts=$(date +%s)
    dur=$((end_ts - start_ts))
    dur_str=$(elapsed_fmt $dur)

    if [ $rc -eq 0 ]; then
        log_info "────── ${label} 完成 ✓ (${dur_str}) ──────"
    elif [ $rc -eq 124 ]; then
        log_error "────── ${label} 超时 ✗ (限制 ${timeout}s, 已用 ${dur_str}) ──────"
    else
        log_error "────── ${label} 失败 ✗ (退出码 ${rc}, ${dur_str}) ──────"
    fi

    return $rc
}

# ─── 运行 Shell 子脚本（用于 run_workdayly 编排） ───
# 用法: run_sub "标签" "脚本绝对路径"
# 返回: 子脚本退出码
run_sub() {
    local label="$1"
    local script="$2"
    local start_ts rc end_ts dur dur_str

    start_ts=$(date +%s)
    log_info "══════ ${label} 开始 ══════"

    bash "$script"
    rc=$?

    end_ts=$(date +%s)
    dur=$((end_ts - start_ts))
    dur_str=$(elapsed_fmt $dur)

    if [ $rc -eq 0 ]; then
        log_info "══════ ${label} 完成 ✓ (${dur_str}) ══════"
    else
        log_warn "══════ ${label} 异常 ✗ (退出码 ${rc}, ${dur_str}) ══════"
    fi

    return $rc
}

# ─── 服务管理（OOM 防护） ───
# 在低内存服务器上，内存密集型任务前停止非关键服务，完成后恢复

# 需要停止的服务列表（可通过 .env 的 QUANTIA_STOP_SERVICES 覆盖）
# 默认: nginx + supervisor 管理的 Quantia web 服务
_STOP_SERVICES="${QUANTIA_STOP_SERVICES:-nginx}"

# 停止服务，释放内存给密集型任务
# 用法: stop_services_for_memory "任务名称"
stop_services_for_memory() {
    local reason="${1:-内存密集型任务}"
    log_info "◆ 停止服务以释放内存（原因: ${reason}）"

    # 停止 supervisor 管理的 web 服务（如果有 supervisorctl）
    if command -v supervisorctl &>/dev/null; then
        supervisorctl stop run_web 2>/dev/null && \
            log_info "  ✓ supervisord: run_web 已停止" || \
            log_warn "  ⚠ supervisord: run_web 停止失败（可能未运行）"
    fi

    # 停止系统服务
    for svc in $_STOP_SERVICES; do
        if systemctl is-active --quiet "$svc" 2>/dev/null; then
            systemctl stop "$svc" 2>/dev/null && \
                log_info "  ✓ ${svc} 已停止" || \
                log_warn "  ⚠ ${svc} 停止失败"
        else
            log_info "  - ${svc} 未运行，跳过"
        fi
    done
}

# 恢复服务
# 用法: start_services_after_memory
start_services_after_memory() {
    log_info "◆ 恢复服务"

    # 恢复系统服务
    for svc in $_STOP_SERVICES; do
        systemctl start "$svc" 2>/dev/null && \
            log_info "  ✓ ${svc} 已启动" || \
            log_warn "  ⚠ ${svc} 启动失败"
    done

    # 恢复 supervisor 管理的 web 服务
    if command -v supervisorctl &>/dev/null; then
        supervisorctl start run_web 2>/dev/null && \
            log_info "  ✓ supervisord: run_web 已启动" || \
            log_warn "  ⚠ supervisord: run_web 启动失败"
    fi
}

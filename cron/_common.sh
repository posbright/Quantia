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

# ─── T+1 任务交易日检测 ───
# 用法: check_trade_day_t1 "任务名称" [最大间隔天数=4]
# 适用于"次日凌晨运行、处理上一交易日数据"的任务（analysis / paper / report，
# crontab DOW 2-6 含周六凌晨槽位以处理周五数据）。
#
# 与 check_trade_day 的区别：
#   check_trade_day   校验「运行当天」是否为交易日 —— 适合 T 日盘后运行的 fetch/kline。
#   check_trade_day_t1 校验「最近一个交易日」是否在 N 天内 —— 适合 T+1 凌晨运行的任务。
#
# 修复缺陷：原先三个 T+1 任务复用 check_trade_day，在周六凌晨因
# is_trade_date(周六)=False 被误跳过，导致每个周五的策略选股/模拟交易/报告
# 永久缺失。改用「最近交易日」判定后，周六凌晨可正常处理周五数据；
# 仅在长假等「最近交易日已超过 N 天」时才跳过空跑。
check_trade_day_t1() {
    local task_name="${1:-任务}"
    local max_gap="${2:-4}"
    local ok
    ok=$("$PYTHON_BIN" -c "
import sys, datetime; sys.path.insert(0, '$PROJECT_ROOT')
try:
    import quantia.lib.trade_time as trd
    _, run_date_nph = trd.get_trade_date_last()
    last = run_date_nph.date() if hasattr(run_date_nph, 'date') else run_date_nph
    gap = (datetime.date.today() - last).days
    print('1' if 0 <= gap <= $max_gap else '0')
except Exception:
    print('1')
" 2>/dev/null)

    if [ "$ok" = "0" ]; then
        log_info "最近 ${max_gap} 天内无交易日，跳过${task_name}"
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

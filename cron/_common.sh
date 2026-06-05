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
    LAST_STAGE_DURATION=$dur

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
    LAST_STAGE_DURATION=$dur

    if [ $rc -eq 0 ]; then
        log_info "══════ ${label} 完成 ✓ (${dur_str}) ══════"
    else
        log_warn "══════ ${label} 异常 ✗ (退出码 ${rc}, ${dur_str}) ══════"
    fi

    return $rc
}

# ─── 阶段结果汇总（供 run_workdayly 等编排脚本在末尾输出成功/失败清单） ───
# STAGE_SUMMARY 累积每个阶段的结果行；STAGE_FAIL/STAGE_WARN 计数。
# STAGE_DURATIONS 累积「耗时秒|标签|状态」，供末尾耗时排行（辅助任务编排）。
STAGE_SUMMARY=()
STAGE_DURATIONS=()
STAGE_FAIL=0
STAGE_WARN=0
LAST_STAGE_DURATION=0

# 用法: record_stage "阶段标签" 退出码 [warn] [耗时秒]
#   第三参数为 "warn" 时，失败记为 ⚠ 警告（非关键，不计入失败数）；
#       否则失败记为 ✗ 失败（关键，计入 STAGE_FAIL）。
#   第四参数为耗时（秒）；省略时自动取 run_sub/run_job 导出的 LAST_STAGE_DURATION。
record_stage() {
    local label="$1" rc="$2" mode="${3:-critical}" dur="${4:-$LAST_STAGE_DURATION}"
    local dur_str status
    dur="${dur:-0}"
    dur_str=$(elapsed_fmt "$dur")
    if [ "$rc" -eq 0 ]; then
        status="成功"
        STAGE_SUMMARY+=("✓ 成功  ${label}  [耗时 ${dur_str}]")
    elif [ "$mode" = "warn" ]; then
        status="警告"
        STAGE_SUMMARY+=("⚠ 警告  ${label} (退出码 ${rc}, 非关键)  [耗时 ${dur_str}]")
        STAGE_WARN=$((STAGE_WARN + 1))
    else
        status="失败"
        STAGE_SUMMARY+=("✗ 失败  ${label} (退出码 ${rc})  [耗时 ${dur_str}]")
        STAGE_FAIL=$((STAGE_FAIL + 1))
    fi
    STAGE_DURATIONS+=("${dur}|${label}|${status}")
    # 用后即清零，避免下个未显式传 dur 的阶段误用上一个阶段耗时
    LAST_STAGE_DURATION=0
}

# 用法: print_stage_summary
# 在日志末尾逐行输出各阶段成功/失败明细 + 统计 + 耗时排行（降序）。
print_stage_summary() {
    local total=${#STAGE_SUMMARY[@]}
    local ok=$((total - STAGE_FAIL - STAGE_WARN))
    log_info "──────── 任务执行结果汇总 ────────"
    local line
    for line in "${STAGE_SUMMARY[@]}"; do
        log_info "  ${line}"
    done
    log_info "──────── 共 ${total} 项：成功 ${ok}，失败 ${STAGE_FAIL}，警告 ${STAGE_WARN} ────────"

    # 耗时排行（降序）+ 总耗时，便于后期按耗时编排任务
    if [ "$total" -gt 0 ]; then
        local total_dur=0 d
        for line in "${STAGE_DURATIONS[@]}"; do
            d="${line%%|*}"
            total_dur=$((total_dur + ${d:-0}))
        done
        log_info "──────── 各阶段耗时排行（降序） ────────"
        local sorted rank=1 lbl st
        sorted=$(printf '%s\n' "${STAGE_DURATIONS[@]}" | sort -t'|' -k1,1 -rn)
        while IFS='|' read -r d lbl st; do
            [ -z "$lbl" ] && continue
            log_info "  $(printf '%2d' $rank). $(printf '%8s' "$(elapsed_fmt "${d:-0}")")  ${lbl} (${st})"
            rank=$((rank + 1))
        done <<< "$sorted"
        log_info "──────── 阶段总耗时 $(elapsed_fmt $total_dur) ────────"
    fi
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

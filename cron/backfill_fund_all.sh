#!/bin/bash
# ═══════════════════════════════════════════════════════════
# 基金中心数据一键全量铺底（首次初始化用，非定时任务）
# 在服务器 /root/Quantia 本地执行：写 localhost MySQL，零公网压力。
#
# 用法：
#   bash /root/Quantia/cron/backfill_fund_all.sh
#   # 可选：覆盖 TopN（每个净值型桶按近1年收益取前 N 只）
#   QUANTIA_FUND_NAV_TOPN=300 bash /root/Quantia/cron/backfill_fund_all.sh
#
# 依赖顺序（必须）：
#   F8 净值历史 ──┐
#                 ├─► F7 综合评分（夏普/最大回撤/近5年依赖净值历史）
#   cn_fund_rank ─┘
#   F10 画像（独立）   F12 重仓股（独立）
#
# 注意：本脚本是 fetch 管道（F8/F10/F12 调外部源），仅应在服务器本地跑。
#       日常增量由 cron.workdayly/run_fetch、run_analysis 与
#       cron.monthly/run_fund_profile_holding 自动维护，无需重复手动跑。
# ═══════════════════════════════════════════════════════════
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
source "$PROJECT_ROOT/cron/_common.sh"

init_env
LOG_FILE=$LOG_DIR/backfill_fund_all.log

# 全量 TopN（本地 socket，可放心调大）；允许从环境覆盖
export QUANTIA_FUND_NAV_TOPN="${QUANTIA_FUND_NAV_TOPN:-200}"
export QUANTIA_FUND_PROFILE_TOPN="${QUANTIA_FUND_PROFILE_TOPN:-200}"
export QUANTIA_FUND_HOLDING_TOPN="${QUANTIA_FUND_HOLDING_TOPN:-200}"

log_info "══════ 基金全量铺底开始 (NAV_TOPN=$QUANTIA_FUND_NAV_TOPN, "\
"PROFILE_TOPN=$QUANTIA_FUND_PROFILE_TOPN, HOLDING_TOPN=$QUANTIA_FUND_HOLDING_TOPN) ══════"

FAILED=0

# ① F8 净值历史 → cn_fund_nav_history（必须先于 F7）
run_job "F8 基金净值历史 (fetch_fund_nav_history_job)" \
    "quantia/job/fetch_fund_nav_history_job.py" \
    "${QUANTIA_FUND_NAV_TIMEOUT:-7200}" || FAILED=$((FAILED + 1))

# ② F10 基金画像 → cn_fund_profile（独立，失败不阻断）
run_job "F10 基金画像 (fetch_fund_profile_job)" \
    "quantia/job/fetch_fund_profile_job.py" \
    "${QUANTIA_FUND_PROFILE_TIMEOUT:-3600}" || FAILED=$((FAILED + 1))

# ③ F12 重仓股 → cn_fund_holding（独立，失败不阻断）
run_job "F12 基金重仓股 (fetch_fund_holding_job)" \
    "quantia/job/fetch_fund_holding_job.py" \
    "${QUANTIA_FUND_HOLDING_TIMEOUT:-3600}" || FAILED=$((FAILED + 1))

# ④ F7 综合评分 → cn_fund_rank_score（读 rank+nav 计算，零 API；放最后）
run_job "F7 基金综合评分 (analysis_fund_score_job)" \
    "quantia/job/analysis_fund_score_job.py" \
    "${QUANTIA_FUND_SCORE_TIMEOUT:-1800}" || FAILED=$((FAILED + 1))

if [ $FAILED -eq 0 ]; then
    log_info "══════ 基金全量铺底完成 ✓ ══════"
else
    log_warn "══════ 基金全量铺底结束 ✗ ($FAILED/4 步失败，详见上方日志) ══════"
fi
exit $FAILED

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F7 基金多因子综合评分（analysis 管道，只读 MySQL + 纯计算）。

读 cn_fund_rank（当日截面）+ cn_fund_profile（规模/画像）+ cn_fund_nav_history
（夏普/回撤/Calmar/近5年，仅已回填的基金）+ cn_fund_holding（主行业），
按 fund_type 分桶截面打分，写 cn_fund_rank_score（主键 (date, code)）。

严守管道分离（AGENTS 规则 1/8）：本 job 全程只读 MySQL + 计算，不调外部 API。
评分为排序辅助，禁落库为可交易 strategy_template（与 Phase 9 评分类范式一致）。

用法：
    python analysis_fund_score_job.py            # 全量截面打分
"""
import datetime
import logging
import math
import os.path
import sys

import numpy as np
import pandas as pd

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
try:
    from quantia.lib.log_config import setup_logging
    setup_logging('analysis')
except Exception:
    log_path = os.path.join(cpath_current, 'log')
    os.makedirs(log_path, exist_ok=True)
    logging.basicConfig(
        format='%(asctime)s [%(levelname)s] %(message)s',
        filename=os.path.join(log_path, 'fund_score_job.log'),
        level=logging.INFO,
    )

import quantia.core.tablestructure as tbs
import quantia.core.fund.scoring as scoring
import quantia.lib.database as mdb
from quantia.core.fund import data_readiness
from quantia.lib.job_tracker import record_task_start, record_task_end

__author__ = 'Quantia'
__date__ = '2026/06/01'

_JOB_NAME = 'run_fund_score'
_RANK_TABLE = tbs.TABLE_CN_FUND_RANK['name']
_PROFILE_TABLE = tbs.TABLE_CN_FUND_PROFILE['name']
_NAV_TABLE = tbs.TABLE_CN_FUND_NAV_HISTORY['name']
_HOLDING_TABLE = tbs.TABLE_CN_FUND_HOLDING['name']
_SCORE_TABLE = tbs.TABLE_CN_FUND_RANK_SCORE['name']
_SCORE_COLS = list(tbs.TABLE_CN_FUND_RANK_SCORE['columns'])
_CORE_FUND_TYPES = ('股票型', '混合型', '指数型', '债券型', '货币型')

# cn_fund_rank 评分需要的列（截面因子 + 货币型因子）
_RANK_FACTOR_COLS = [
    'code', 'fund_type', 'rate_3m', 'rate_6m', 'rate_1y', 'rate_3y', 'rate_ytd',
    'fee', 'seven_day_annual', 'million_unit_income',
]


def _completeness_threshold():
    value = float(os.environ.get('QUANTIA_FUND_COMPLETENESS_THRESHOLD', '0.90'))
    if not math.isfinite(value) or not 0 < value <= 1:
        raise ValueError('QUANTIA_FUND_COMPLETENESS_THRESHOLD 必须是 (0, 1] 内的有限数')
    return value


def _load_rank_latest():
    """读 cn_fund_rank 最新快照日的截面因子。"""
    if not mdb.checkTableIsExist(_RANK_TABLE):
        return pd.DataFrame(columns=_RANK_FACTOR_COLS), None
    cols = ', '.join(f'`{c}`' for c in _RANK_FACTOR_COLS)
    sql = (
        f"SELECT {cols} FROM `{_RANK_TABLE}` "
        f"WHERE `date` = (SELECT MAX(`date`) FROM `{_RANK_TABLE}`)"
    )
    df = pd.read_sql(sql, con=mdb.engine())
    date_rows = mdb.executeSqlFetch(f"SELECT MAX(`date`) FROM `{_RANK_TABLE}`")
    snap = date_rows[0][0] if date_rows and date_rows[0] else None
    if df.empty:
        return df, snap
    df['code'] = df['code'].astype(str)
    return df, snap


def check_rank_readiness(job_date=None):
    """只读 DB 评估基金排名截面；QDII/FOF 不进入首版硬门槛。"""
    job_date = job_date or datetime.date.today()
    threshold = _completeness_threshold()
    same_day = os.environ.get('QUANTIA_ANALYSIS_SAME_DAY', '').strip().lower() in (
        '1', 'true', 'yes', 'on')
    snapshots = mdb.executeSqlFetch(
        f"SELECT `date`, COUNT(*) FROM `{_RANK_TABLE}` "
        f"GROUP BY `date` ORDER BY `date` DESC LIMIT 6") or []
    snapshot_date = snapshots[0][0] if snapshots else None
    latest_count = snapshots[0][1] if snapshots else 0
    previous_counts = [row[1] for row in snapshots[1:]]
    expected_operator = '<=' if same_day else '<'
    expected_rows = mdb.executeSqlFetch(
        f"SELECT MAX(`trade_date`) FROM `cn_stock_trade_date` "
        f"WHERE `trade_date` {expected_operator} %s",
        (job_date,)) or []
    expected_snapshot = expected_rows[0][0] if expected_rows and expected_rows[0] else None
    target_rows = mdb.executeSqlFetch(
        "SELECT MAX(`trade_date`) FROM `cn_stock_trade_date` WHERE `trade_date` < %s",
        (snapshot_date,)) if snapshot_date else []
    target_nav_date = target_rows[0][0] if target_rows and target_rows[0] else None
    fresh_count = core_count = 0
    if snapshot_date and target_nav_date:
        placeholders = ','.join(['%s'] * len(_CORE_FUND_TYPES))
        rows = mdb.executeSqlFetch(
            f"SELECT SUM(CASE WHEN `nav_date` >= %s THEN 1 ELSE 0 END), COUNT(*) "
            f"FROM `{_RANK_TABLE}` WHERE `date` = %s "
            f"AND `fund_type` IN ({placeholders})",
            (target_nav_date, snapshot_date) + _CORE_FUND_TYPES) or []
        if rows and rows[0]:
            fresh_count = int(rows[0][0] or 0)
            core_count = int(rows[0][1] or 0)
    result = data_readiness.evaluate(
        snapshot_date, expected_snapshot, latest_count, previous_counts,
        fresh_count, core_count, threshold, threshold)
    result['schedule_mode'] = 'same_day' if same_day else 't_plus_one'
    result['target_nav_date'] = target_nav_date
    return result


def _load_scale_map():
    """读 cn_fund_profile 的 (code → scale_yi)。缺表/缺值由评分填中性。"""
    if not mdb.checkTableIsExist(_PROFILE_TABLE):
        return {}
    rows = mdb.executeSqlFetch(
        f"SELECT `code`, `scale_yi` FROM `{_PROFILE_TABLE}`")
    return {str(r[0]): r[1] for r in rows if r and r[0] is not None}


def _load_main_industry_map():
    """读 cn_fund_holding 加权得 (code → 主行业)。"""
    if not mdb.checkTableIsExist(_HOLDING_TABLE):
        return {}
    df = pd.read_sql(
        f"SELECT `code`, `industry`, `hold_ratio` FROM `{_HOLDING_TABLE}`",
        con=mdb.engine())
    if df.empty:
        return {}
    df['code'] = df['code'].astype(str)
    return scoring.compute_main_industry(df)


def _nav_codes():
    """已回填净值历史的基金 code（B2 风险指标仅对这些可算）。"""
    if not mdb.checkTableIsExist(_NAV_TABLE):
        return []
    rows = mdb.executeSqlFetch(f"SELECT DISTINCT `code` FROM `{_NAV_TABLE}`")
    return [str(r[0]) for r in rows if r and r[0] is not None]


def _load_nav_series(code):
    """单基金 (nav_date, acc_nav) 升序序列。"""
    df = pd.read_sql(
        f"SELECT `nav_date`, `acc_nav` FROM `{_NAV_TABLE}` "
        f"WHERE `code` = %s ORDER BY `nav_date` ASC",
        con=mdb.engine(), params=(str(code),))
    return df


def _build_risk_metrics():
    """逐基金（仅已回填净值历史者）算 sharpe/calmar/max_drawdown/rate_5y。

    逐 code 处理避免一次物化全市场净值序列（内存效率）。返回 DataFrame。
    """
    codes = _nav_codes()
    recs = []
    for code in codes:
        try:
            df = _load_nav_series(code)
            if df is None or df.empty:
                continue
            acc = df['acc_nav']
            recs.append({
                'code': str(code),
                'sharpe': scoring.compute_sharpe(acc),
                'calmar': scoring.compute_calmar(acc),
                'max_drawdown': scoring.compute_max_drawdown(acc),
                'rate_5y': scoring.compute_rate_5y(df['nav_date'], acc),
            })
        except Exception:
            logging.warning(f"analysis_fund_score_job: {code} 风险指标计算失败，跳过",
                            exc_info=True)
    if not recs:
        return pd.DataFrame(columns=['code', 'sharpe', 'calmar', 'max_drawdown', 'rate_5y'])
    return pd.DataFrame(recs)


def build_score_df(score_date=None):
    """装配因子 + 截面打分，返回对齐 cn_fund_rank_score 的 DataFrame（纯编排，便于单测 mock DB）。"""
    rank_df, snap = _load_rank_latest()
    if rank_df.empty:
        return pd.DataFrame(columns=_SCORE_COLS), snap
    score_date = score_date or snap or datetime.date.today()

    rank_df = rank_df.copy()
    rank_df['scale_yi'] = rank_df['code'].map(_load_scale_map())
    rank_df['main_industry'] = rank_df['code'].map(_load_main_industry_map())

    risk_df = _build_risk_metrics()
    if not risk_df.empty:
        rank_df = rank_df.merge(risk_df, on='code', how='left')
    else:
        for c in ('sharpe', 'calmar', 'max_drawdown', 'rate_5y'):
            rank_df[c] = np.nan

    scored = scoring.compute_scores(rank_df, score_date=score_date)
    # 对齐表列序，缺失补 None
    for col in _SCORE_COLS:
        if col not in scored.columns:
            scored[col] = None
    return scored[_SCORE_COLS], score_date


def _save_scores(scored, score_date):
    """删当日旧分后写入（主键 (date, code)）。"""
    if scored is None or len(scored.index) == 0:
        return 0
    if mdb.checkTableIsExist(_SCORE_TABLE):
        try:
            mdb.executeSql(
                f"DELETE FROM `{_SCORE_TABLE}` WHERE `date` = %s", (score_date,))
        except Exception:
            logging.warning("analysis_fund_score_job: 删除当日旧评分失败，改用 upsert",
                            exc_info=True)
        cols_type = None
    else:
        cols_type = tbs.get_field_types(tbs.TABLE_CN_FUND_RANK_SCORE['columns'])
    mdb.insert_db_from_df(scored, _SCORE_TABLE, cols_type, False, "`date`,`code`")
    return len(scored.index)


def run(score_date=None, job_date=None):
    job_date = job_date or datetime.date.today()
    start = record_task_start(_JOB_NAME, 'score', job_date)
    try:
        readiness = check_rank_readiness(job_date)
        if not readiness['ready']:
            message = '基金评分数据未就绪：' + '；'.join(readiness['reasons'])
            record_task_end(_JOB_NAME, 'score', job_date, start, success=False,
                            message=message, rows_affected=0)
            logging.warning('%s；metrics=%s', message, readiness)
            return 0
        logging.info('基金评分截面门控通过：%s', readiness)
        scored, eff_date = build_score_df(score_date)
        if scored is None or len(scored.index) == 0:
            record_task_end(_JOB_NAME, 'score', job_date, start, success=False,
                            message='无可评分基金（cn_fund_rank 为空？）', rows_affected=0)
            logging.warning("analysis_fund_score_job: 无可评分基金")
            return 0
        n = _save_scores(scored, eff_date)
        record_task_end(_JOB_NAME, 'score', job_date, start, success=True,
                        message=f"评分 {n} 只（截止 {eff_date}）", rows_affected=n)
        logging.info(f"analysis_fund_score_job 完成：评分 {n} 只，date={eff_date}")
        return n
    except Exception as e:
        record_task_end(_JOB_NAME, 'score', job_date, start, success=False,
                        message=str(e), rows_affected=0)
        logging.error("analysis_fund_score_job 失败", exc_info=True)
        raise


def main():
    if run() <= 0:
        raise SystemExit(3)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P5 每日精选榜生成（analysis 管道，只读 MySQL + 纯计算）。

每个 fund_type 桶内 Top10 精选（蓝图 §7 / 风险 5）：
  读 cn_fund_rank_score（quality_score=score, max_drawdown）当日截面 +
  cn_fund_rank（name, rate_1y）→ 桶内先取 Top-N by quality → AC 份额去重 →
  截 Top10 → 逐只用 timing.py 纯函数从 cn_fund_nav_history 算 timing 弱标签，
  写 cn_fund_daily_pick（主键 (date, fund_type, code)）。

严守管道分离（AGENTS 规则 1/7/8）：全程只读 MySQL + 计算，不调外部 API；
SELECT 显式列，NULL 容忍（货币型/债券型 timing 多为空，不丢弃基金）。
timing 由 timing.py 统一计算（单一事实源，禁另写 timing 公式）；final_score
V1=quality_score（择时仅展示、不参与主排序）。写库 chunksize=500、NaN/inf 清洗。

用法：
    python analysis_fund_pick_job.py            # 以今日为运行日生成
"""
import datetime
import logging
import math
import os.path
import sys

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
        filename=os.path.join(log_path, 'fund_pick_job.log'),
        level=logging.INFO,
    )

import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
from quantia.core.fund import pick_selection, timing
from quantia.lib.job_tracker import record_task_start, record_task_end

__author__ = 'Quantia'
__date__ = '2026/07/09'

_JOB_NAME = 'run_fund_pick'
_SCORE_TABLE = tbs.TABLE_CN_FUND_RANK_SCORE['name']
_RANK_TABLE = tbs.TABLE_CN_FUND_RANK['name']
_NAV_TABLE = tbs.TABLE_CN_FUND_NAV_HISTORY['name']
_PICK_TABLE = tbs.TABLE_CN_FUND_DAILY_PICK['name']
_PICK_COLS = list(tbs.TABLE_CN_FUND_DAILY_PICK['columns'])

_PRE_N = 25              # 桶内先取 Top-N（>10，供去重后回填）
_TOP_K = 10             # 每桶最终 Top10
_STALE_DAYS = 7         # 净值滞后阈值（防线1，超过则 timing 档位置空）
_MIN_SAMPLES = 2        # timing 最少净值样本
_MONEY_TYPE = '货币型'   # 货币型不做点位择时


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(f) else f


def _to_date(v):
    if v is None:
        return None
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    try:
        return datetime.date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


def _resolve_as_of(table, pick_date):
    """取 <= pick_date 的最新截面日；无则 None。"""
    try:
        row = mdb.executeSqlFetch(
            f"SELECT MAX(`date`) FROM `{table}` WHERE `date` <= %s", (pick_date,))
        return _to_date(row[0][0]) if row and row[0] else None
    except Exception:
        logging.warning("analysis_fund_pick_job: 取 %s 截面日失败", table, exc_info=True)
        return None


def _load_candidates(score_as_of, rank_as_of):
    """读桶内候选：quality_score / max_drawdown / name / rate_1y / fund_type。"""
    srows = mdb.executeSqlFetch(
        f"SELECT `code`, `fund_type`, `score`, `max_drawdown` FROM `{_SCORE_TABLE}` "
        f"WHERE `date` = %s", (score_as_of,))
    meta = {}
    if rank_as_of is not None:
        rrows = mdb.executeSqlFetch(
            f"SELECT `code`, `name`, `rate_1y` FROM `{_RANK_TABLE}` "
            f"WHERE `date` = %s", (rank_as_of,))
        for code, name, rate_1y in (rrows or ()):
            meta[code] = (name, _num(rate_1y))

    buckets = {}
    for code, fund_type, score, mdd in (srows or ()):
        if not fund_type:
            continue
        name, rate_1y = meta.get(code, (None, None))
        buckets.setdefault(fund_type, []).append({
            'code': code,
            'name': name,
            'fund_type': fund_type,
            'quality_score': _num(score),
            'max_drawdown': _num(mdd),
            'rate_1y': rate_1y,
            'scale': None,  # V1 无规模列，AC 去重退化为 A 类优先 + code 稳定
        })
    return buckets


def _load_nav_map(codes, pick_date):
    """批量读候选净值序列（<= pick_date，升序）。返回 {code: [(date, unit, acc)]}。"""
    nav_map = {}
    if not codes:
        return nav_map
    placeholders = ','.join(['%s'] * len(codes))
    rows = mdb.executeSqlFetch(
        f"SELECT `code`, `nav_date`, `unit_nav`, `acc_nav` FROM `{_NAV_TABLE}` "
        f"WHERE `code` IN ({placeholders}) AND `nav_date` <= %s "
        f"ORDER BY `code`, `nav_date` ASC",
        tuple(codes) + (pick_date,))
    for code, nav_date, unit, acc in (rows or ()):
        nav_map.setdefault(code, []).append((_to_date(nav_date), _num(unit), _num(acc)))
    return nav_map


def _compute_timing(nav_rows, fund_type, pick_date):
    """用 timing.py 纯函数算 timing 弱标签。返回 (score, tier, nav_as_of, lag_days)。

    NULL 容忍：货币型/样本不足/滞后 → score/tier 置空但仍保留基金与 nav 截面。
    """
    if not nav_rows:
        return None, None, None, None
    nav_as_of = nav_rows[-1][0]
    lag = (pick_date - nav_as_of).days if nav_as_of else None

    if fund_type == _MONEY_TYPE:
        return None, None, nav_as_of, lag

    acc = [r[2] for r in nav_rows if r[2] is not None]
    if len(acc) >= _MIN_SAMPLES:
        nav_series = acc
    else:
        nav_series = [r[1] for r in nav_rows if r[1] is not None]
    if len(nav_series) < _MIN_SAMPLES:
        return None, None, nav_as_of, lag

    # 防线1：净值滞后 > 7 天 → 不产出档位（与 Handler 一致）
    if lag is not None and lag > _STALE_DAYS:
        return None, None, nav_as_of, lag

    dd = timing.drawdown_from_high(nav_series)
    trend = timing.nav_trend_score(nav_series)
    res = timing.compose_timing_score(dd, trend, None)
    score = res.get('score')
    return (round(score, 1) if score is not None else None), res.get('tier'), nav_as_of, lag


def build_pick_df(pick_date):
    """生成精选榜 DataFrame（表列序）。返回 (df, score_as_of)。"""
    if not mdb.checkTableIsExist(_SCORE_TABLE):
        return None, None
    score_as_of = _resolve_as_of(_SCORE_TABLE, pick_date)
    if score_as_of is None:
        return None, None
    rank_as_of = _resolve_as_of(_RANK_TABLE, pick_date) \
        if mdb.checkTableIsExist(_RANK_TABLE) else None

    buckets = _load_candidates(score_as_of, rank_as_of)
    if not buckets:
        return None, score_as_of

    # 先桶内选出 Top10（去重后），再统一批量取净值算 timing
    selected = []
    for fund_type, cands in buckets.items():
        picked = pick_selection.select_bucket_top(cands, top_k=_TOP_K, pre_n=_PRE_N)
        selected.extend(picked)

    has_nav = mdb.checkTableIsExist(_NAV_TABLE)
    nav_map = _load_nav_map([r['code'] for r in selected], pick_date) if has_nav else {}

    records = []
    for r in selected:
        code = r['code']
        fund_type = r['fund_type']
        tscore, tier, nav_as_of, lag = _compute_timing(
            nav_map.get(code, []), fund_type, pick_date)
        quality = r.get('quality_score')
        records.append({
            'date': pick_date,
            'fund_type': fund_type,
            'rank_in_type': r['rank_in_type'],
            'code': code,
            'name': r.get('name'),
            'quality_score': quality,
            'timing_score': tscore,
            'timing_tier': tier,
            'final_score': quality,  # V1 口径 C：final=quality
            'max_drawdown': r.get('max_drawdown'),
            'rate_1y': r.get('rate_1y'),
            'score_as_of': score_as_of,
            'nav_as_of': nav_as_of,
            'data_lag_days': lag,
        })

    if not records:
        return None, score_as_of
    df = pd.DataFrame(records, columns=_PICK_COLS)
    # NaN/inf → None（源头清洗，防 MySQL 拒写）
    df = df.astype(object).where(pd.notnull(df), None)
    for col in ('quality_score', 'timing_score', 'final_score', 'max_drawdown', 'rate_1y'):
        df[col] = df[col].map(_num)
    return df, score_as_of


def _save_picks(df, pick_date):
    """删当日旧榜后写入（主键 (date, fund_type, code)）。"""
    if df is None or len(df.index) == 0:
        return 0
    if mdb.checkTableIsExist(_PICK_TABLE):
        try:
            mdb.executeSql(
                f"DELETE FROM `{_PICK_TABLE}` WHERE `date` = %s", (pick_date,))
        except Exception:
            logging.warning("analysis_fund_pick_job: 删除当日旧榜失败，改用 upsert",
                            exc_info=True)
        cols_type = None
    else:
        cols_type = tbs.get_field_types(tbs.TABLE_CN_FUND_DAILY_PICK['columns'])
    mdb.insert_db_from_df(df, _PICK_TABLE, cols_type, False,
                          "`date`,`fund_type`,`code`")
    return len(df.index)


def run(pick_date=None, job_date=None):
    pick_date = _to_date(pick_date) or datetime.date.today()
    job_date = job_date or datetime.date.today()
    start = record_task_start(_JOB_NAME, 'pick', job_date)
    try:
        df, score_as_of = build_pick_df(pick_date)
        if df is None or len(df.index) == 0:
            record_task_end(_JOB_NAME, 'pick', job_date, start, success=True,
                            message='无可入选基金（cn_fund_rank_score 为空？）',
                            rows_affected=0)
            logging.warning("analysis_fund_pick_job: 无可入选基金")
            return 0
        n = _save_picks(df, pick_date)
        n_bucket = df['fund_type'].nunique()
        record_task_end(_JOB_NAME, 'pick', job_date, start, success=True,
                        message=f"精选 {n} 只 / {n_bucket} 桶（质量截面 {score_as_of}）",
                        rows_affected=n)
        logging.info("analysis_fund_pick_job 完成：%s 只 / %s 桶，date=%s，score_as_of=%s",
                     n, n_bucket, pick_date, score_as_of)
        return n
    except Exception as e:
        record_task_end(_JOB_NAME, 'pick', job_date, start, success=False,
                        message=str(e), rows_affected=0)
        logging.error("analysis_fund_pick_job 失败", exc_info=True)
        raise


def main():
    pick_date = None
    for arg in sys.argv[1:]:
        if arg.startswith('--date='):
            pick_date = arg.split('=', 1)[1].strip()
    run(pick_date=pick_date)


if __name__ == '__main__':
    main()

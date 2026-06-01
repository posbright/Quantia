#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F12 基金季度前十大重仓股缓存（独立慢 job，季频）。

逐基金抓取 fund_portfolio_hold_em 最新季度前十大重仓股，LEFT JOIN 本项目股票
行业表（cn_stock_selection，只读 MySQL）回填 industry，写 cn_fund_holding。
支持「按行业筛选/对比」+ 详情持仓展示。

抓取范围：默认覆盖含权益的桶（股票型/混合型/指数型）按近1年收益的 Top-N；
货币型/纯债型无股票重仓 → 跳过。行业映射仅对 A 股有效，QDII/港股/海外/债券
持仓归 "未分类"。属 fetch 管道（akshare 抓取 + 读库回填，均允许）。
低频 cron（cron.monthly）或手动触发。

用法：
    python fetch_fund_holding_job.py [code1 code2 ...]
    python fetch_fund_holding_job.py
"""
import datetime
import logging
import os.path
import random
import sys
import time

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
try:
    from quantia.lib.log_config import setup_logging
    setup_logging('fetch')
except Exception:
    log_path = os.path.join(cpath_current, 'log')
    os.makedirs(log_path, exist_ok=True)
    logging.basicConfig(
        format='%(asctime)s [%(levelname)s] %(message)s',
        filename=os.path.join(log_path, 'fund_holding_job.log'),
        level=logging.INFO,
    )

import quantia.core.tablestructure as tbs
import quantia.core.crawling.fund_em as fem
import quantia.lib.database as mdb
import quantia.lib.envconfig as _cfg
from quantia.lib.job_tracker import record_task_start, record_task_end

__author__ = 'Quantia'
__date__ = '2026/06/01'

_JOB_NAME = 'run_fund_holding'
_RANK_TABLE = tbs.TABLE_CN_FUND_RANK['name']
_HOLDING_TABLE = tbs.TABLE_CN_FUND_HOLDING['name']
_SELECTION_TABLE = tbs.TABLE_CN_STOCK_SELECTION['name']
_HOLDING_COLS = list(tbs.TABLE_CN_FUND_HOLDING['columns'])
# 含权益重仓的桶（货币型/纯债无股票重仓）
_EQUITY_TYPES = ['股票型', '混合型', '指数型']
_UNKNOWN_INDUSTRY = '未分类'


def _select_target_codes(limit_per_type):
    """含权益桶按近1年收益取 Top-N 的 code。"""
    if not mdb.checkTableIsExist(_RANK_TABLE):
        return []
    placeholders = ','.join(['%s'] * len(_EQUITY_TYPES))
    sql = (
        f"SELECT code FROM ("
        f"  SELECT code,"
        f"    ROW_NUMBER() OVER (PARTITION BY fund_type ORDER BY (`rate_1y` IS NULL), `rate_1y` DESC) AS rn"
        f"  FROM `{_RANK_TABLE}`"
        f"  WHERE `date` = (SELECT MAX(`date`) FROM `{_RANK_TABLE}`)"
        f"    AND fund_type IN ({placeholders})"
        f") t WHERE t.rn <= %s"
    )
    rows = mdb.executeSqlFetch(sql, (*_EQUITY_TYPES, int(limit_per_type)))
    return [str(r[0]) for r in rows if r and r[0] is not None]


def _load_industry_map():
    """读 cn_stock_selection 的 (stock_code → industry) 映射（只读 MySQL，不调外部 API）。"""
    if not mdb.checkTableIsExist(_SELECTION_TABLE):
        return {}
    try:
        rows = mdb.executeSqlFetch(
            f"SELECT `code`, `industry` FROM `{_SELECTION_TABLE}`")
    except Exception:
        logging.warning("fetch_fund_holding_job: 读取行业映射失败，全部归未分类", exc_info=True)
        return {}
    out = {}
    for r in rows:
        if r and r[0] is not None:
            out[str(r[0]).zfill(6)] = r[1]
    return out


def _join_industry(df, industry_map):
    """按 stock_code 回填 industry，缺失填 未分类。纯函数。"""
    def _lookup(sc):
        ind = industry_map.get(str(sc).zfill(6)) if sc is not None else None
        return ind if ind else _UNKNOWN_INDUSTRY
    df = df.copy()
    df['industry'] = df['stock_code'].map(_lookup)
    return df


def save_fund_holding(code, year, industry_map, update_date):
    """抓取 + 行业回填 + 删旧重写单只基金最新季度持仓，返回写入行数。"""
    df = fem.fund_holding_latest(code, year)
    if df is None or len(df.index) == 0:
        return 0
    df = _join_industry(df, industry_map)
    df['update_date'] = update_date
    # 对齐表列序，缺失列补 None
    for col in _HOLDING_COLS:
        if col not in df.columns:
            df[col] = None
    df = df[_HOLDING_COLS]

    # 删旧（同 code 旧季度）后重写，避免换季后陈旧季度残留
    if mdb.checkTableIsExist(_HOLDING_TABLE):
        try:
            mdb.executeSql(
                f"DELETE FROM `{_HOLDING_TABLE}` WHERE `code` = %s", (str(code),))
        except Exception:
            logging.warning(f"fetch_fund_holding_job: {code} 删除旧持仓失败，改用 upsert", exc_info=True)
        cols_type = None
    else:
        cols_type = tbs.get_field_types(tbs.TABLE_CN_FUND_HOLDING['columns'])
    mdb.insert_db_from_df(df, _HOLDING_TABLE, cols_type, False,
                          "`code`,`quarter`,`stock_code`")
    return len(df.index)


def run(codes=None, limit_per_type=None, job_date=None):
    job_date = job_date or datetime.date.today()
    update_date = job_date
    year = job_date.year
    if limit_per_type is None:
        limit_per_type = _cfg.get_int('QUANTIA_FUND_HOLDING_TOPN', 200)
    if not codes:
        codes = _select_target_codes(limit_per_type)
    if not codes:
        logging.warning("fetch_fund_holding_job: 无目标基金（cn_fund_rank 为空？）")
        return 0

    industry_map = _load_industry_map()
    start = record_task_start(_JOB_NAME, 'holding', job_date)
    total_rows = 0
    ok = 0
    for code in codes:
        try:
            n = save_fund_holding(code, year, industry_map, update_date)
            total_rows += n
            if n > 0:
                ok += 1
        except Exception:
            logging.warning(f"fetch_fund_holding_job: {code} 处理失败，跳过", exc_info=True)
        finally:
            time.sleep(random.uniform(0.5, 1.5))  # 限速
    record_task_end(_JOB_NAME, 'holding', job_date, start, success=True,
                    message=f"{ok}/{len(codes)} 基金有持仓", rows_affected=total_rows)
    logging.info(f"fetch_fund_holding_job 完成：{ok}/{len(codes)} 基金，共 {total_rows} 行持仓")
    return total_rows


def main():
    args = [a for a in sys.argv[1:] if a.strip()]
    run(codes=args or None)


if __name__ == '__main__':
    main()

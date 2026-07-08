#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
筹码分布历史回填（可选，零 API）。

日常流式分析只算"当日"一行；本脚本为最近 N 个交易日补齐历史筹码指标，
便于个股详情/回测查看趋势。纯本地：只读 cache/hist/ 缓存，绝不发起外部请求。

用法：
    python -m quantia.job.backfill_chip_distribution

环境变量：
    QUANTIA_CYQ_BACKFILL_DAYS         回填最近多少个交易日（默认 90）
    QUANTIA_CYQ_BACKFILL_MAX_SECONDS  时间预算，秒；0=不限（默认 0）
    QUANTIA_CYQ_LOOKBACK/FACTOR/MIN_BARS  同 chip_distribution 模块
"""

import logging
import time
import datetime
import os.path
import sys

import pandas as pd

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
import quantia.core.stockfetch as stf
import quantia.core.kline.chip_distribution as cyqd
import quantia.lib.envconfig as _cfg

__author__ = 'Quantia'
__date__ = '2026/07/07'

_BACKFILL_DAYS = _cfg.get_int('QUANTIA_CYQ_BACKFILL_DAYS', 90)
_MAX_SECONDS = _cfg.get_int('QUANTIA_CYQ_BACKFILL_MAX_SECONDS', 0)
_WRITE_BATCH = 500


def _get_stock_list():
    """从 cn_stock_spot 取最新一天股票列表（date/code/name），零 API。"""
    table_name = tbs.TABLE_CN_STOCK_SPOT['name']
    if not mdb.checkTableIsExist(table_name):
        return None
    fk_cols = list(tbs.TABLE_CN_STOCK_FOREIGN_KEY['columns'].keys())
    sql = (f"SELECT `{'`,`'.join(fk_cols)}` FROM `{table_name}` "
           f"WHERE `date` = (SELECT MAX(`date`) FROM `{table_name}`)")
    data = pd.read_sql(sql, mdb.engine())
    if data is None or len(data) == 0:
        return None
    return data


def _flush(rows, cols_type, table_name):
    if not rows:
        return
    data = pd.DataFrame(rows)
    mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")
    rows.clear()


def backfill(days=None, max_seconds=None):
    """回填最近 days 个交易日的筹码分布指标。"""
    days = _BACKFILL_DAYS if days is None else int(days)
    max_seconds = _MAX_SECONDS if max_seconds is None else int(max_seconds)
    start_time = time.time()

    table_name = tbs.TABLE_CN_STOCK_CHIP_DISTRIBUTION['name']
    cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_CHIP_DISTRIBUTION['columns'])

    stock_list = _get_stock_list()
    if stock_list is None:
        logging.warning("筹码回填：无股票列表，退出。")
        return
    logging.info(f"===== 筹码分布回填开始：{len(stock_list)} 只 × 最近 {days} 日 =====")

    date_end = datetime.datetime.now().strftime("%Y-%m-%d")
    date_start = (datetime.datetime.now() - datetime.timedelta(days=1200)).strftime("%Y-%m-%d")

    fk_cols = list(tbs.TABLE_CN_STOCK_FOREIGN_KEY['columns'].keys())
    rows = []
    processed = 0
    written = 0
    budget_hit = False

    for _, srow in stock_list.iterrows():
        if max_seconds > 0 and (time.time() - start_time) >= max_seconds:
            budget_hit = True
            break
        code = srow['code']
        name = srow['name']
        try:
            hist = stf.read_stock_hist_from_cache(code, date_start, date_end)
        except Exception:
            hist = None
        processed += 1
        if hist is None or len(hist) == 0 or 'date' not in hist.columns:
            continue
        hist = hist.sort_values('date').reset_index(drop=True)
        # 按需从 DB(cn_stock_spot/cn_etf_spot) 补齐换手率（旧缓存缺 turnover 时）。仅读 DB，无外部请求。
        hist = stf.backfill_turnover_from_spot(code, hist)
        n = len(hist)
        # 对最近 days 个交易日，逐日计算"截止该日"的筹码指标
        for end_idx in range(max(0, n - days), n):
            window = hist.iloc[: end_idx + 1]
            metrics = cyqd.compute_chip_metrics(window)
            if metrics is None:
                continue
            d = window.iloc[-1]['date']
            date_str = pd.Timestamp(d).strftime("%Y-%m-%d")
            row = {'date': date_str, 'code': code, 'name': name}
            row.update(metrics)
            rows.append(row)
            written += 1
            if len(rows) >= _WRITE_BATCH:
                _flush(rows, cols_type, table_name)

    _flush(rows, cols_type, table_name)
    elapsed = time.time() - start_time
    suffix = "（触发时间预算，提前结束）" if budget_hit else ""
    logging.info(f"===== 筹码分布回填完成：处理 {processed} 只，写入 {written} 行，"
                 f"耗时 {elapsed:.1f}s{suffix} =====")


def main():
    backfill()


if __name__ == '__main__':
    if not logging.getLogger().handlers:
        try:
            from quantia.lib.log_config import setup_logging
            setup_logging('backfill_chip')
        except Exception:
            logging.basicConfig(
                format='%(asctime)s [%(levelname)s] %(message)s',
                level=logging.INFO,
            )
    main()

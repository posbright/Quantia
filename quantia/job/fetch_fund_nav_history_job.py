#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F8 基金净值历史回填（独立慢 job，不进每日 fetch 主链）。

逐基金抓取「单位净值走势 + 累计净值走势」，合并写 cn_fund_nav_history，
供回撤 / 夏普 / 净值曲线计算。**派生风险/收益指标一律用 acc_nav（累计净值）**。

抓取范围（落地性）：默认仅覆盖各 fund_type 桶按近1年收益的 Top-N（排除货币型，
货币型无单位/累计净值走势），断点续抓（跳过库中已有最新 nav_date 的 code）。
属 fetch 管道（akshare 单源）。低频 cron（cron.workdayly）或手动触发。

用法：
    python fetch_fund_nav_history_job.py [code1 code2 ...]   # 指定基金
    python fetch_fund_nav_history_job.py                     # 自动选 Top-N
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
        filename=os.path.join(log_path, 'fund_nav_history_job.log'),
        level=logging.INFO,
    )

import quantia.core.tablestructure as tbs
import quantia.core.crawling.fund_em as fem
import quantia.lib.database as mdb
import quantia.lib.envconfig as _cfg
from quantia.lib.job_tracker import record_task_start, record_task_end

__author__ = 'Quantia'
__date__ = '2026/06/01'

_JOB_NAME = 'run_fund_nav_history'
_RANK_TABLE = tbs.TABLE_CN_FUND_RANK['name']
_NAV_TABLE = tbs.TABLE_CN_FUND_NAV_HISTORY['name']
_MONEY_TYPE = '货币型'


def _select_target_codes(limit_per_type):
    """各净值型桶的目标 code（排除货币型）。

    - limit_per_type > 0：各桶按近1年收益取 Top-N。
    - limit_per_type <= 0：全量回填（不限桶内数量），用于一次性铺底
      （配 QUANTIA_FUND_NAV_TOPN=0）。
    """
    if not mdb.checkTableIsExist(_RANK_TABLE):
        return []
    limit_per_type = int(limit_per_type)
    if limit_per_type <= 0:
        sql = (
            f"SELECT code FROM `{_RANK_TABLE}` "
            f"WHERE `date` = (SELECT MAX(`date`) FROM `{_RANK_TABLE}`) "
            f"  AND fund_type <> %s"
        )
        rows = mdb.executeSqlFetch(sql, (_MONEY_TYPE,))
        return [str(r[0]) for r in rows if r and r[0] is not None]
    sql = (
        f"SELECT code FROM ("
        f"  SELECT code, fund_type,"
        f"    ROW_NUMBER() OVER (PARTITION BY fund_type ORDER BY (`rate_1y` IS NULL), `rate_1y` DESC) AS rn"
        f"  FROM `{_RANK_TABLE}`"
        f"  WHERE `date` = (SELECT MAX(`date`) FROM `{_RANK_TABLE}`)"
        f"    AND fund_type <> %s"
        f") t WHERE t.rn <= %s"
    )
    rows = mdb.executeSqlFetch(sql, (_MONEY_TYPE, limit_per_type))
    return [str(r[0]) for r in rows if r and r[0] is not None]


def _existing_max_navdate(code):
    """库中该基金已有的最新净值日（断点续抓增量过滤），无则 None。"""
    if not mdb.checkTableIsExist(_NAV_TABLE):
        return None
    rows = mdb.executeSqlFetch(
        f"SELECT MAX(`nav_date`) FROM `{_NAV_TABLE}` WHERE `code` = %s", (code,))
    if rows and rows[0] and rows[0][0] is not None:
        return rows[0][0]
    return None


def save_fund_nav_history(code):
    """抓取 + 增量写入单只基金净值历史，返回写入行数（0 表示无新增/失败）。"""
    hist = fem.fund_nav_history(code)
    if hist is None or len(hist.index) == 0:
        return 0

    max_date = _existing_max_navdate(code)
    if max_date is not None:
        # 仅保留库中最新日之后的增量行
        hist = hist[hist['nav_date'].map(lambda d: d is not None and d > max_date)]
    if len(hist.index) == 0:
        return 0

    cols_type = None
    if not mdb.checkTableIsExist(_NAV_TABLE):
        cols_type = tbs.get_field_types(tbs.TABLE_CN_FUND_NAV_HISTORY['columns'])
    mdb.insert_db_from_df(hist, _NAV_TABLE, cols_type, False, "`code`,`nav_date`")
    return len(hist.index)


def run(codes=None, limit_per_type=None, job_date=None):
    job_date = job_date or datetime.date.today()
    if limit_per_type is None:
        limit_per_type = _cfg.get_int('QUANTIA_FUND_NAV_TOPN', 200)
    if not codes:
        codes = _select_target_codes(limit_per_type)
    if not codes:
        logging.warning("fetch_fund_nav_history_job: 无目标基金（cn_fund_rank 为空？）")
        return 0

    start = record_task_start(_JOB_NAME, 'nav_history', job_date)
    total_rows = 0
    ok = 0
    for code in codes:
        try:
            n = save_fund_nav_history(code)
            total_rows += n
            if n > 0:
                ok += 1
        except Exception:
            logging.warning(f"fetch_fund_nav_history_job: {code} 处理失败，跳过", exc_info=True)
        finally:
            time.sleep(random.uniform(0.5, 1.5))  # 限速
    record_task_end(_JOB_NAME, 'nav_history', job_date, start, success=True,
                    message=f"{ok}/{len(codes)} 基金有新增", rows_affected=total_rows)
    logging.info(f"fetch_fund_nav_history_job 完成：{ok}/{len(codes)} 基金，共 {total_rows} 行")
    return total_rows


def main():
    args = [a for a in sys.argv[1:] if a.strip()]
    run(codes=args or None)


if __name__ == '__main__':
    main()

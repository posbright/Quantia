#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公司概况缓存（独立慢 job，季/月频）。

逐个股抓取东方财富 F10 经营分析（经营范围 / 主营构成明细 / 经营评述），
透视为单行 upsert 写 cn_stock_company_profile（主键 code 覆盖），供个股详情页
「公司概况」卡展示。经营范围/主营构成/经营评述季度级稳定，不必每日抓。

属 fetch 管道（东方财富单源），只有本管道可调用外部 API。低频 cron
（cron.monthly）或手动触发；全量约 4900 只需较长时间，建议分批。

用法：
    python fetch_company_profile_job.py [code1 code2 ...]   # 指定股票
    python fetch_company_profile_job.py                     # 全量（增量跳过近期已更新）
"""
import datetime
import json
import logging
import os.path
import random
import sys
import time

import pandas as pd

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
        filename=os.path.join(log_path, 'company_profile_job.log'),
        level=logging.INFO,
    )

import quantia.core.tablestructure as tbs
import quantia.core.crawling.stock_business_em as sbe
import quantia.lib.database as mdb
import quantia.lib.envconfig as _cfg
from quantia.lib.job_tracker import record_task_start, record_task_end

__author__ = 'Quantia'
__date__ = '2026/06/26'

_JOB_NAME = 'run_company_profile'
_PROFILE_TABLE = tbs.TABLE_CN_STOCK_COMPANY_PROFILE['name']
_PROFILE_COLS = list(tbs.TABLE_CN_STOCK_COMPANY_PROFILE['columns'])
# 增量跳过阈值：update_date 在此天数内视为已更新（可用 force 覆盖）
_SKIP_DAYS = 25


def _select_target_codes(limit=None):
    """从 cn_stock_spot 取最新交易日 A 股 / 北交所代码。"""
    if not mdb.checkTableIsExist('cn_stock_spot'):
        return []
    try:
        rows = mdb.executeSqlFetch(
            "SELECT DISTINCT `code` FROM `cn_stock_spot` "
            "WHERE `date` = (SELECT MAX(`date`) FROM `cn_stock_spot`) "
            "AND `code` REGEXP '^[0368]' "
            "ORDER BY `code`"
        )
    except Exception:
        logging.warning("fetch_company_profile_job: 获取股票列表失败", exc_info=True)
        return []
    codes = [str(r[0]) for r in rows if r and r[0] is not None]
    if limit:
        codes = codes[:int(limit)]
    return codes


def _recently_updated_codes(cutoff_date):
    """已在 cutoff_date 之后更新过的 code 集合（用于增量跳过）。"""
    if not mdb.checkTableIsExist(_PROFILE_TABLE):
        return set()
    try:
        rows = mdb.executeSqlFetch(
            f"SELECT `code` FROM `{_PROFILE_TABLE}` WHERE `update_date` >= %s",
            (cutoff_date,))
    except Exception:
        logging.warning("fetch_company_profile_job: 读取已更新集合失败", exc_info=True)
        return set()
    return {str(r[0]) for r in rows if r and r[0] is not None}


def save_company_profile(code, update_date):
    """抓取 + upsert 单只个股公司概况，返回 1（成功）/ 0（无数据/失败）。"""
    result = sbe.stock_business_composition(code)
    if not result:
        return 0
    mainop = result.get('mainop') or []
    data = {
        'code': str(code).zfill(6),
        'report_date': result.get('report_date'),
        'business_scope': result.get('business_scope'),
        'business_review': result.get('business_review'),
        'mainop': json.dumps(mainop, ensure_ascii=False, default=str) if mainop else None,
        'update_date': update_date,
    }
    df = pd.DataFrame([{c: data.get(c) for c in _PROFILE_COLS}])[_PROFILE_COLS]

    cols_type = None
    if not mdb.checkTableIsExist(_PROFILE_TABLE):
        cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_COMPANY_PROFILE['columns'])
    mdb.insert_db_from_df(df, _PROFILE_TABLE, cols_type, False, "`code`")
    return 1


def run(codes=None, limit=None, force=False, job_date=None):
    job_date = job_date or datetime.date.today()
    update_date = job_date
    explicit = bool(codes)
    if not codes:
        codes = _select_target_codes(limit)
    if not codes:
        logging.warning("fetch_company_profile_job: 无目标股票（cn_stock_spot 为空？）")
        return 0

    # 增量跳过：仅对全量模式生效；显式指定 codes 或 force 时不跳过
    skip = set()
    if not force and not explicit:
        cutoff = job_date - datetime.timedelta(days=_SKIP_DAYS)
        skip = _recently_updated_codes(cutoff)
    targets = [c for c in codes if c not in skip]

    start = record_task_start(_JOB_NAME, 'profile', job_date)
    ok = 0
    for code in targets:
        try:
            ok += save_company_profile(code, update_date)
        except Exception:
            logging.warning(f"fetch_company_profile_job: {code} 处理失败，跳过", exc_info=True)
        finally:
            time.sleep(random.uniform(0.8, 1.5))  # 限速
    record_task_end(_JOB_NAME, 'profile', job_date, start, success=True,
                    message=f"{ok}/{len(targets)} 公司概况更新（跳过 {len(skip)}）",
                    rows_affected=ok)
    logging.info(f"fetch_company_profile_job 完成：{ok}/{len(targets)} 公司概况"
                 f"（增量跳过 {len(skip)}）")
    return ok


def main():
    args = [a for a in sys.argv[1:] if a.strip()]
    force = '--force' in args
    codes = [a for a in args if not a.startswith('--')]
    run(codes=codes or None, force=force)


if __name__ == '__main__':
    main()

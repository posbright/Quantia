#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公司概况缓存（独立慢 job，季/月频）。

逐个股抓取东方财富 F10 经营分析（经营范围 / 主营构成明细 / 经营评述），
透视为单行 upsert 写 cn_stock_company_profile（主键 code 覆盖），供个股详情页
「公司概况」卡展示。经营范围/主营构成/经营评述季度级稳定，不必每日抓。

属 fetch 管道（东方财富单源），只有本管道可调用外部 API。低频 cron
（cron.monthly）或手动触发；全量约 4900 只需较长时间，建议分批。
超时预算 QUANTIA_COMPANY_PROFILE_MAX_SECONDS（秒，<=0 不限时）到点干净自停，
下次运行靠 update_date 增量续跑。

用法：
    python fetch_company_profile_job.py [code1 code2 ...]   # 指定股票
    python fetch_company_profile_job.py                     # 全量（增量跳过近期已更新）
    python fetch_company_profile_job.py --limit=500         # 全量前 500 只
    python fetch_company_profile_job.py 000651 --force      # 强制刷新指定股票
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
import quantia.core.crawling.stock_business_ths as sbt
import quantia.lib.database as mdb
import quantia.lib.envconfig as _cfg
from quantia.lib.job_tracker import record_task_start, record_task_end

__author__ = 'Quantia'
__date__ = '2026/06/26'

_JOB_NAME = 'run_company_profile'
_PROFILE_TABLE = tbs.TABLE_CN_STOCK_COMPANY_PROFILE['name']
_PROFILE_COLS = list(tbs.TABLE_CN_STOCK_COMPANY_PROFILE['columns'])
# 增量跳过阈值：update_date 在此天数内视为已更新（可用 force 覆盖）。
# 数据为季度级稳定；月度 cron + 80 天跳过 ⇒ 每只个股约每季刷新一轮，把全量刷新自然
# 摊到 ~3 个月，月度只补新股/过期股，既保新股时效又大幅降负载。
_SKIP_DAYS = 80

# 熔断阈值：连续失败（BusinessFetchError 等）达此数视为东方财富封禁/不可用，提前中止本轮，
# 避免对死接口空转 1.5h、并降低进一步被封风险；下月靠增量续跑。<=0 关闭熔断。
_MAX_CONSECUTIVE_FAILURES = _cfg.get_int('QUANTIA_COMPANY_PROFILE_MAX_FAILS', 30)


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
    """抓取 + upsert 单只个股公司概况，返回 1（成功）/ 0（无数据）。

    主源东方财富；传输层失败（BusinessFetchError，如封禁）时降级到同花顺备源
    （仅经营范围 + 主营业务定性描述，无定量占比）。两源均传输失败时抛出
    BusinessFetchError 交由上层 run() 熔断计数。
    """
    try:
        result = sbe.stock_business_composition(code)
    except sbe.BusinessFetchError:
        # 东方财富封禁/传输故障 → 降级同花顺（独立基础设施）。同花顺也失败则继续抛出。
        logging.info(f"fetch_company_profile_job: {code} 东方财富抳取失败，降级同花顺备源")
        result = sbt.stock_business_composition_ths(code)
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


def run(codes=None, limit=None, force=False, job_date=None, max_seconds=None):
    job_date = job_date or datetime.date.today()
    update_date = job_date
    explicit = bool(codes)
    if max_seconds is None:
        max_seconds = _cfg.get_int('QUANTIA_COMPANY_PROFILE_MAX_SECONDS', 0)
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
    started_at = time.monotonic()
    ok = 0
    processed = 0
    stopped_early = False
    aborted = False
    consecutive_fail = 0
    for code in targets:
        # 时间预算：全量约 4900 只需 1.5~2h，超预算时干净自停（下次运行靠增量续跑），
        # 避免被 cron timeout 的 SIGTERM 在写库中途打断。max_seconds<=0 表示不限时。
        if max_seconds and (time.monotonic() - started_at) >= max_seconds:
            stopped_early = True
            logging.info(f"fetch_company_profile_job: 达到时间预算 {max_seconds}s，"
                         f"已处理 {processed}/{len(targets)}，剩余留待下次续跑")
            break
        try:
            ok += save_company_profile(code, update_date)
            consecutive_fail = 0  # 成功或"响应正常但无数据"⇒ 数据源可达，重置熔断计数
        except Exception:
            consecutive_fail += 1
            logging.warning(f"fetch_company_profile_job: {code} 处理失败，跳过", exc_info=True)
        processed += 1
        # 熔断：连续失败达阈值 ⇒ 疑似东方财富封禁/不可用，提前中止，避免空转 + 加剧封禁
        if _MAX_CONSECUTIVE_FAILURES and consecutive_fail >= _MAX_CONSECUTIVE_FAILURES:
            aborted = True
            logging.error(
                f"fetch_company_profile_job: 连续 {consecutive_fail} 只抓取失败，"
                f"疑似东方财富封禁/不可用，提前熔断中止（已处理 {processed}/{len(targets)}），"
                f"剩余留待下次续跑")
            break
        time.sleep(random.uniform(0.8, 1.5))  # 限速
    tail = ''
    if stopped_early:
        tail = '，超时自停'
    elif aborted:
        tail = f'，连续失败{consecutive_fail}次熔断中止'
    msg = f"{ok}/{processed} 公司概况更新（跳过 {len(skip)}{tail}）"
    record_task_end(_JOB_NAME, 'profile', job_date, start, success=not aborted,
                    message=msg, rows_affected=ok)
    logging.info(f"fetch_company_profile_job 完成：{msg}")
    return ok


def main():
    args = [a for a in sys.argv[1:] if a.strip()]
    force = '--force' in args
    limit = None
    for a in args:
        if a.startswith('--limit='):
            try:
                limit = int(a.split('=', 1)[1])
            except ValueError:
                limit = None
    codes = [a for a in args if not a.startswith('--')]
    run(codes=codes or None, limit=limit, force=force)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据获取作业（独立运行）

职责：集中执行所有需要外部 API 的数据获取任务。
与 analysis_daily_job.py 配合使用，实现获取与分析解耦。

执行顺序（串行执行，按内存占用从低到高排列）：
1. 初始化数据库
2. 股票/ETF 实时行情入库
3. 综合选股数据入库
4. 资金流向、龙虎榜等扩展数据
5. 收盘后数据（大宗交易等）

设计原则：
- 串行执行所有任务，子进程隔离内存密集型操作
- 每个子任务执行前检查数据新鲜度，已有完整数据时跳过
- 每个子任务记录开始/结束日志及耗时
- 作业整体状态通过 cn_job_status 表追踪（供 kline_cache_daily_job 查询）
- 历史K线缓存增量更新已独立为 kline_cache_daily_job.py
- 即使某个阶段失败，后续阶段仍会继续
- 可独立于分析任务运行
"""

import time
import datetime
import logging
import gc
import os.path
import sys

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
        filename=os.path.join(log_path, 'stock_fetch_job.log'),
        level=logging.INFO,
    )
import init_job as bj
import subprocess
import basic_data_daily_job as hdj
import selection_data_daily_job as sddj
import quantia.lib.trade_time as trd
from quantia.lib.job_tracker import (
    record_task_start, record_task_end, record_task_skipped,
    is_job_completed, is_data_fresh,
)
import quantia.lib.envconfig as _cfg

__author__ = 'Quantia'
__date__ = '2026/03/12'

# 子进程超时（秒）
_JOB_TIMEOUT = _cfg.get_int('QUANTIA_JOB_TIMEOUT', 1800)

_JOB_DIR = os.path.dirname(os.path.abspath(__file__))
_JOB_NAME = 'run_fetch'

# 数据新鲜度阈值：当日数据行数 >= 此值时认为已完整
# 可通过环境变量覆盖
_FRESHNESS_THRESHOLDS = {
    'cn_stock_spot': _cfg.get_int('QUANTIA_FRESH_STOCK_SPOT', 3000),
    'cn_etf_spot': _cfg.get_int('QUANTIA_FRESH_ETF_SPOT', 200),
    'cn_stock_selection': _cfg.get_int('QUANTIA_FRESH_SELECTION', 100),
    'cn_stock_fund_flow': _cfg.get_int('QUANTIA_FRESH_FUND_FLOW', 2000),
    'cn_fund_rank': _cfg.get_int('QUANTIA_FRESH_FUND_RANK', 8000),
    'cn_stock_lhb': 1,  # 龙虎榜数据量不固定，有数据即可
    'cn_stock_bonus': 1,
    'cn_stock_blocktrade': 1,
}


def _enrich_stock_spot_from_selection():
    """用 cn_stock_selection 交叉补全 cn_stock_spot 最新快照的 pe9/roe_weight/industry。

    背景：行情源降级到腾讯/新浪时，cn_stock_spot 的 市盈率TTM(pe9)/加权ROE(roe_weight)
    恒为 0、industry 常为空。东方财富选股器表 cn_stock_selection 同时落库且这三列可靠，
    故在每日 selection 入库后，用其最新值补全 spot 最新交易日的降级缺失。

    约束：
    - 仅在 spot 值缺失(0/空) 且 selection 值有效时填充，幂等；不覆盖已有有效值。
    - 不污染 pe9 的 TTM 语义：亏损股 selection.pe9=0 时保持 spot.pe9=0，由 dtsyl 兜底。
    - 纯 DB→DB 操作，不调用外部 API（符合 fetch/analysis/web 管道分离）。
    """
    import quantia.lib.database as mdb

    date_rows = mdb.executeSqlFetch('SELECT MAX(date) FROM cn_stock_spot')
    if not date_rows or date_rows[0][0] is None:
        logging.warning('[spot补全] cn_stock_spot 无数据，跳过')
        return
    spot_date = date_rows[0][0]

    # 每只股票取 selection 最近30天内的最新一行（基本面季度级稳定，足够新鲜）
    update_sql = """
        UPDATE cn_stock_spot s
        JOIN (
            SELECT sel.code, sel.pe9, sel.roe_weight, sel.industry
            FROM cn_stock_selection sel
            JOIN (
                SELECT code, MAX(date) md FROM cn_stock_selection
                WHERE date >= DATE_SUB(%s, INTERVAL 30 DAY)
                GROUP BY code
            ) latest ON sel.code = latest.code AND sel.date = latest.md
        ) sl ON s.code = sl.code
        SET s.pe9 = CASE WHEN (s.pe9 IS NULL OR s.pe9 = 0) AND sl.pe9 > 0
                         THEN sl.pe9 ELSE s.pe9 END,
            s.roe_weight = CASE WHEN (s.roe_weight IS NULL OR s.roe_weight = 0) AND sl.roe_weight <> 0
                                THEN sl.roe_weight ELSE s.roe_weight END,
            s.industry = CASE WHEN (s.industry IS NULL OR s.industry = '')
                                   AND sl.industry IS NOT NULL AND sl.industry <> ''
                              THEN sl.industry ELSE s.industry END
        WHERE s.date = %s
          AND ((s.pe9 IS NULL OR s.pe9 = 0)
               OR (s.roe_weight IS NULL OR s.roe_weight = 0)
               OR (s.industry IS NULL OR s.industry = ''))
    """
    mdb.executeSql(update_sql, (spot_date, spot_date))

    stat = mdb.executeSqlFetch(
        """SELECT COUNT(*),
                  SUM(CASE WHEN pe9 > 0 THEN 1 ELSE 0 END),
                  SUM(CASE WHEN roe_weight <> 0 THEN 1 ELSE 0 END),
                  SUM(CASE WHEN industry IS NOT NULL AND industry <> '' THEN 1 ELSE 0 END)
           FROM cn_stock_spot WHERE date = %s""", (spot_date,))
    if stat and stat[0]:
        total, pe_ok, roe_ok, ind_ok = stat[0]
        logging.info(f"[spot补全] {spot_date} 补全后：total={total} pe9>0={pe_ok} "
                     f"roe!=0={roe_ok} industry非空={ind_ok}")


def _run_job_subprocess(script_name, label, timeout=_JOB_TIMEOUT):
    """以独立子进程运行 job 脚本，防止 OOM 波及当前进程。

    Returns:
        bool: True 表示子进程正常退出（exit code 0），False 表示失败。
    """
    script_path = os.path.join(_JOB_DIR, script_name)
    try:
        logging.info(f"{label}: 启动子进程 {script_name}")
        result = subprocess.run(
            [sys.executable, script_path],
            env={**os.environ, 'PYTHONPATH': cpath},
            timeout=timeout,
        )
        if result.returncode != 0:
            logging.warning(f"{label}: 子进程退出码 {result.returncode}（可能 OOM 被杀）")
            return False
        else:
            logging.info(f"{label}: 子进程执行成功")
            return True
    except subprocess.TimeoutExpired:
        logging.error(f"{label}: 子进程执行超时（{timeout}秒）")
        return False
    except Exception as e:
        logging.error(f"{label}: 子进程启动异常", exc_info=True)
        return False


def _check_and_skip(table_name, date_str, task_label, settlement_hour=None):
    """检查 API 数据新鲜度，决定是否跳过该任务。

    跳过条件（同时满足）：
    1. 未设置 QUANTIA_FORCE_FETCH=1
    2. 当前时间已过结算时间（默认 18:00），API 数据不再变化
    3. 表中当日数据行数 >= 阈值

    Args:
        settlement_hour: 可选，覆盖默认结算小时。基金净值多在 20:00-23:00 才披露、
            QDII T+2，需传入更晚的结算小时（如 23），避免未披露时误判已结算而入空。

    Returns:
        bool: True 表示数据已完整且已结算，应跳过该任务。
    """
    if _cfg.get_bool('QUANTIA_FORCE_FETCH', False):
        return False

    # API 数据仅在结算时间后（默认 18:00）才可信赖跳过
    if not trd.is_post_settlement(date_str, settlement_hour=settlement_hour):
        logging.info(f"[{task_label}] 尚未过结算时间，需更新 API 数据")
        return False

    threshold = _FRESHNESS_THRESHOLDS.get(table_name, 1)
    fresh, count = is_data_fresh(table_name, date_str, threshold)
    if fresh:
        logging.info(f"[{task_label}] 数据已完整且已过结算时间（{table_name}: {count} 条 >= {threshold}），跳过")
        return True
    return False


def main():
    start = time.time()
    logging.info("====== 数据获取任务开始 [%s] ======" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    # 获取交易日期
    try:
        run_date, run_date_nph = trd.get_trade_date_last()
        date_str = run_date_nph.strftime("%Y-%m-%d")
    except Exception as e:
        logging.error("获取交易日期失败，无法继续", exc_info=True)
        return

    # 检查整体作业是否已完成（仅在结算时间后才信赖跳过）
    if is_job_completed(_JOB_NAME, run_date_nph) and trd.is_post_settlement(run_date_nph):
        logging.info(f"数据获取任务已于今日（{date_str}）成功完成且已过结算时间，跳过。设置 QUANTIA_FORCE_FETCH=1 可强制执行。")
        return
    elif is_job_completed(_JOB_NAME, run_date_nph):
        logging.info(f"数据获取任务已完成，但尚未过结算时间，将重新获取 API 数据")

    overall_start = record_task_start(_JOB_NAME, '__overall__', run_date_nph)
    all_success = True

    # Phase 0: 初始化数据库
    t0 = record_task_start(_JOB_NAME, 'init_db', run_date_nph)
    try:
        bj.main()
        record_task_end(_JOB_NAME, 'init_db', run_date_nph, t0, success=True)
    except Exception as e:
        logging.error(f"数据获取 init_job 异常", exc_info=True)
        record_task_end(_JOB_NAME, 'init_db', run_date_nph, t0, success=False, message=str(e))
        all_success = False

    # Phase 1: 股票实时行情入库
    if _check_and_skip('cn_stock_spot', date_str, '股票行情'):
        record_task_skipped(_JOB_NAME, 'stock_spot', run_date_nph, '数据已完整')
    else:
        t1 = record_task_start(_JOB_NAME, 'stock_spot', run_date_nph)
        try:
            hdj.main()
            record_task_end(_JOB_NAME, 'stock_spot', run_date_nph, t1, success=True)
        except Exception as e:
            logging.error(f"数据获取 basic_data_daily 异常", exc_info=True)
            record_task_end(_JOB_NAME, 'stock_spot', run_date_nph, t1, success=False, message=str(e))
            all_success = False

    # Phase 2: 综合选股数据入库
    if _check_and_skip('cn_stock_selection', date_str, '综合选股'):
        record_task_skipped(_JOB_NAME, 'selection_data', run_date_nph, '数据已完整')
    else:
        t2 = record_task_start(_JOB_NAME, 'selection_data', run_date_nph)
        try:
            sddj.main()
            record_task_end(_JOB_NAME, 'selection_data', run_date_nph, t2, success=True)
        except Exception as e:
            logging.error(f"数据获取 selection_data 异常", exc_info=True)
            record_task_end(_JOB_NAME, 'selection_data', run_date_nph, t2, success=False, message=str(e))
            all_success = False

    # Phase 2.5: 用 selection 交叉补全 spot 降级缺失的 pe9/roe_weight/industry
    # （非关键增强：失败不影响整体作业完成判定，仅记录）
    t2b = record_task_start(_JOB_NAME, 'enrich_spot', run_date_nph)
    try:
        _enrich_stock_spot_from_selection()
        record_task_end(_JOB_NAME, 'enrich_spot', run_date_nph, t2b, success=True)
    except Exception as e:
        logging.error("数据获取 enrich_spot 异常", exc_info=True)
        record_task_end(_JOB_NAME, 'enrich_spot', run_date_nph, t2b, success=False, message=str(e))

    # Phase 2.6: 场外基金排名入库（净值型+货币型）
    # 基金净值多在 20:00-23:00 才披露、QDII T+2，结算门用 QUANTIA_FUND_SETTLEMENT_HOUR(默认23)。
    # 非关键增强：失败不影响整体作业完成判定，仅记录。
    _fund_settle_hour = _cfg.get_int('QUANTIA_FUND_SETTLEMENT_HOUR', 23)
    if _check_and_skip('cn_fund_rank', date_str, '基金排名', settlement_hour=_fund_settle_hour):
        record_task_skipped(_JOB_NAME, 'fund_rank', run_date_nph, '数据已完整')
    else:
        t2c = record_task_start(_JOB_NAME, 'fund_rank', run_date_nph)
        try:
            hdj.save_nph_fund_data(run_date_nph, before=False)
            record_task_end(_JOB_NAME, 'fund_rank', run_date_nph, t2c, success=True)
        except Exception as e:
            logging.error("数据获取 fund_rank 异常", exc_info=True)
            record_task_end(_JOB_NAME, 'fund_rank', run_date_nph, t2c, success=False, message=str(e))

    # Phase 3: 扩展数据（资金流向、龙虎榜等）
    # 以独立子进程运行，防止 OOM 波及当前进程
    t3 = record_task_start(_JOB_NAME, 'basic_data_other', run_date_nph)
    ok = _run_job_subprocess('basic_data_other_daily_job.py', '数据获取 basic_data_other')
    record_task_end(_JOB_NAME, 'basic_data_other', run_date_nph, t3, success=ok)
    if not ok:
        all_success = False

    # Phase 4: 收盘后数据（大宗交易等）
    t4 = record_task_start(_JOB_NAME, 'after_close', run_date_nph)
    ok = _run_job_subprocess('basic_data_after_close_daily_job.py', '数据获取 after_close')
    record_task_end(_JOB_NAME, 'after_close', run_date_nph, t4, success=ok)
    if not ok:
        all_success = False

    # 释放缓存
    try:
        from quantia.core.singleton_stock import stock_data
        stock_data.release()
        gc.collect()
    except Exception:
        logging.debug("释放单例缓存异常", exc_info=True)

    # 记录整体状态（供 kline_cache_daily_job 查询）
    elapsed = time.time() - start
    record_task_end(
        _JOB_NAME, '__overall__', run_date_nph, overall_start,
        success=all_success,
        message=f"总耗时 {elapsed:.1f}s，{'全部成功' if all_success else '部分失败'}"
    )

    logging.info("====== 数据获取任务完成，耗时 %.1f 秒%s ======" % (
        elapsed, '' if all_success else '（部分任务失败）'))


if __name__ == '__main__':
    main()

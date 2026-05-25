#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
手动获取3个选股页面的数据

用途：在服务器上手动执行，获取以下3个页面的数据：
  1. 综合选股     → cn_stock_selection
  2. GPT综合选股  → cn_stock_strategy_gpt_value
  3. 基本面选股   → cn_stock_spot_buy

执行顺序：
  1. basic_data_daily_job  → 获取每日行情（cn_stock_spot），基本面选股依赖此表
  2. selection_data_daily_job → 获取综合选股数据
  3. basic_data_other_daily_job.stock_spot_buy → 从cn_stock_spot筛选基本面选股
  4. gpt_value_data_job → 从cn_stock_selection筛选GPT综合选股

使用方式：
  # 获取最近交易日数据（默认）
  python quantia/job/fetch_three_pages.py

  # 指定日期
  python quantia/job/fetch_three_pages.py 2026-03-04

  # 指定日期区间
  python quantia/job/fetch_three_pages.py 2026-03-01 2026-03-04
"""

import time
import datetime
import logging
import os
import sys

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)

try:
    from quantia.lib.log_config import setup_logging
    setup_logging('fetch_three_pages')
except Exception:
    log_path = os.path.join(cpath_current, 'log')
    os.makedirs(log_path, exist_ok=True)
    logging.basicConfig(
        format='%(asctime)s [%(levelname)s] %(message)s',
        level=logging.INFO,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(os.path.join(log_path, 'fetch_three_pages.log'), encoding='utf-8')
        ]
    )

import quantia.lib.trade_time as trd
import quantia.lib.database as mdb

__author__ = 'Quantia'
__date__ = '2026/03/04'


def verify_db_connection():
    """验证数据库连接"""
    try:
        result = mdb.executeSqlFetch("SELECT 1")
        if result:
            logging.info("数据库连接正常")
            return True
    except Exception as e:
        logging.error(f"数据库连接失败: {e}")
    return False


def verify_table_data(table_name, date_str):
    """验证表中指定日期的数据量"""
    try:
        result = mdb.executeSqlFetch(
            f"SELECT COUNT(*) FROM `{table_name}` WHERE `date` = %s", (date_str,)
        )
        count = result[0][0] if result else 0
        return count
    except Exception as e:
        logging.warning(f"查询 {table_name} 异常: {e}")
        return -1


def fetch_for_date(run_date):
    """为指定日期获取3个页面的数据"""
    date_str = run_date.strftime("%Y-%m-%d") if hasattr(run_date, 'strftime') else str(run_date)

    logging.info("=" * 60)
    logging.info(f"开始获取数据: {date_str}")
    logging.info("=" * 60)

    results = {}

    # Step 1: 获取每日行情数据（基本面选股依赖此表）
    logging.info("")
    logging.info("[Step 1/4] 每日行情 (cn_stock_spot) — 基本面选股依赖此表")
    try:
        import quantia.job.basic_data_daily_job as hdj
        start = time.time()
        hdj.save_nph_stock_spot_data(run_date, before=False)
        elapsed = time.time() - start
        count = verify_table_data('cn_stock_spot', date_str)
        logging.info(f"  完成: {count} 条, 耗时 {elapsed:.1f}s")
        results['cn_stock_spot'] = count
    except Exception as e:
        logging.error(f"  失败: {e}", exc_info=True)
        results['cn_stock_spot'] = -1

    # Step 2: 获取综合选股数据
    logging.info("")
    logging.info("[Step 2/4] 综合选股 (cn_stock_selection)")
    try:
        import quantia.job.selection_data_daily_job as sddj
        start = time.time()
        sddj.save_nph_stock_selection_data(run_date, before=False)
        elapsed = time.time() - start
        count = verify_table_data('cn_stock_selection', date_str)
        logging.info(f"  完成: {count} 条, 耗时 {elapsed:.1f}s")
        results['cn_stock_selection'] = count
    except Exception as e:
        logging.error(f"  失败: {e}", exc_info=True)
        results['cn_stock_selection'] = -1

    # Step 3: 基本面选股（从cn_stock_spot筛选）
    # 注意：stock_spot_buy 已从 basic_data_other_daily_job 移至 analysis_daily_job
    # 此处直接导入 analysis_daily_job 中的函数
    logging.info("")
    logging.info("[Step 3/4] 基本面选股 (cn_stock_spot_buy)")
    try:
        import quantia.job.analysis_daily_job as adj
        start = time.time()
        adj._run_stock_spot_buy(date_str)
        elapsed = time.time() - start
        count = verify_table_data('cn_stock_spot_buy', date_str)
        logging.info(f"  完成: {count} 条, 耗时 {elapsed:.1f}s")
        results['cn_stock_spot_buy'] = count
    except Exception as e:
        logging.error(f"  失败: {e}", exc_info=True)
        results['cn_stock_spot_buy'] = -1

    # Step 4: GPT综合选股（从cn_stock_selection筛选）
    logging.info("")
    logging.info("[Step 4/4] GPT综合选股 (cn_stock_strategy_gpt_value)")
    try:
        import quantia.job.gpt_value_data_job as gptj
        start = time.time()
        gptj.prepare(run_date)
        elapsed = time.time() - start
        count = verify_table_data('cn_stock_strategy_gpt_value', date_str)
        logging.info(f"  完成: {count} 条, 耗时 {elapsed:.1f}s")
        results['cn_stock_strategy_gpt_value'] = count
    except Exception as e:
        logging.error(f"  失败: {e}", exc_info=True)
        results['cn_stock_strategy_gpt_value'] = -1

    # 汇总结果
    logging.info("")
    logging.info("=" * 60)
    logging.info(f"数据获取结果汇总 ({date_str})")
    logging.info("=" * 60)

    page_map = {
        'cn_stock_spot': '每日行情(依赖)',
        'cn_stock_selection': '综合选股',
        'cn_stock_spot_buy': '基本面选股',
        'cn_stock_strategy_gpt_value': 'GPT综合选股',
    }

    all_ok = True
    for table, count in results.items():
        status = "OK" if count > 0 else ("FAIL" if count < 0 else "EMPTY")
        if status != "OK":
            all_ok = False
        logging.info(f"  [{status}] {page_map.get(table, table)}: {count} 条")

    if all_ok:
        logging.info("\n所有数据获取成功！页面应已可正常显示。")
    else:
        logging.warning("\n部分数据获取失败，请检查日志。")

    return results


def main():
    start_total = time.time()

    # 验证数据库连接
    if not verify_db_connection():
        logging.error("数据库连接失败，无法继续。请检查数据库配置。")
        sys.exit(1)

    if len(sys.argv) == 3:
        # 日期区间: python fetch_three_pages.py 2026-03-01 2026-03-04
        start_date = datetime.datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
        end_date = datetime.datetime.strptime(sys.argv[2], "%Y-%m-%d").date()
        run_date = start_date
        while run_date <= end_date:
            if trd.is_trade_date(run_date):
                fetch_for_date(run_date)
            run_date += datetime.timedelta(days=1)
    elif len(sys.argv) == 2:
        # 指定日期: python fetch_three_pages.py 2026-03-04
        if ',' in sys.argv[1]:
            dates = sys.argv[1].split(',')
            for d in dates:
                run_date = datetime.datetime.strptime(d.strip(), "%Y-%m-%d").date()
                if trd.is_trade_date(run_date):
                    fetch_for_date(run_date)
        else:
            run_date = datetime.datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
            fetch_for_date(run_date)
    else:
        # 默认：最近交易日
        run_date, run_date_nph = trd.get_trade_date_last()
        fetch_for_date(run_date_nph)

    elapsed_total = time.time() - start_total
    logging.info(f"\n总耗时: {elapsed_total:.1f}s")


if __name__ == '__main__':
    main()

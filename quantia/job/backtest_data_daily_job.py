#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略回测作业（Phase 5）

流式版本：逐只股票从磁盘缓存读取历史数据进行回测，不加载全量单例
- 内存占用：~50 MB（vs 原架构 ~1670 MB）
- 仅处理需要回测的股票（DB 中 backtest 列为 NULL 的记录）
"""


import logging
import concurrent.futures
import gc
import os
import os.path
import sys
import datetime
import pandas as pd

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
# 统一日志：stock_backtest.log + stock_error.log + sys.excepthook 兜底
try:
    from quantia.lib.log_config import setup_logging
    setup_logging('backtest')
except Exception:
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s [%(levelname)s] %(message)s')
import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
import quantia.lib.trade_time as trd
import quantia.core.stockfetch as stf
import quantia.core.backtest.rate_stats as rate
import quantia.lib.envconfig as _cfg

__author__ = 'Quantia'
__date__ = '2026/02/14'


# 股票策略回归测试。
def prepare():
    tables = [tbs.TABLE_CN_STOCK_INDICATORS_BUY, tbs.TABLE_CN_STOCK_INDICATORS_SELL]
    tables.extend(tbs.TABLE_CN_STOCK_STRATEGIES)
    # GPT综合选股独立于策略列表，单独加入回测
    tables.append(tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE)
    backtest_columns = list(tbs.TABLE_CN_STOCK_BACKTEST_DATA['columns'])
    backtest_columns.insert(0, 'code')
    backtest_columns.insert(0, 'date')
    backtest_column = backtest_columns

    # 计算缓存读取的日期范围
    now = datetime.datetime.now()
    years = stf.HIST_DATA_DEFAULT_YEARS
    date_start, _ = trd.get_trade_hist_interval(now, years)
    date_end = now.strftime("%Y%m%d")

    # 回归测试表，逐表顺序处理以控制内存占用（适配 ≤2GB 服务器）
    # 可通过环境变量 QUANTIA_BACKTEST_OUTER_WORKERS 覆盖（默认 1：顺序执行）
    outer_workers = _cfg.get_int('QUANTIA_BACKTEST_OUTER_WORKERS', 1)
    total_tables = len(tables)
    logging.info(f"backtest.prepare 开始：共 {total_tables} 张策略表，outer_workers={outer_workers}，日期区间 {date_start}~{date_end}")
    overall_start = datetime.datetime.now()
    with concurrent.futures.ThreadPoolExecutor(max_workers=outer_workers) as executor:
        for idx, table in enumerate(tables, start=1):
            executor.submit(process, table, date_start, date_end, backtest_column, idx, total_tables)
    elapsed = (datetime.datetime.now() - overall_start).total_seconds()
    logging.info(f"backtest.prepare 完成：共 {total_tables} 张表，总耗时 {elapsed:.1f}s")


def process(table, date_start, date_end, backtest_column, idx=0, total=0):
    table_name = table['name']
    tag = f"[{idx}/{total}] {table_name}" if total else table_name
    t0 = datetime.datetime.now()
    if not mdb.checkTableIsExist(table_name):
        logging.info(f"backtest {tag} 跳过：表不存在")
        return

    column_tail = tuple(table['columns'])[-1]
    now_date = datetime.datetime.now().date()
    sql = f"SELECT * FROM `{table_name}` WHERE `date` < %s AND `{column_tail}` is NULL"
    try:
        data = pd.read_sql(sql=sql, con=mdb.engine(), params=(now_date,))
        read_sec = (datetime.datetime.now() - t0).total_seconds()
        if data is None or len(data.index) == 0:
            logging.info(f"backtest {tag} 无待回测记录（read_sql {read_sec:.1f}s）")
            return
        logging.info(f"backtest {tag} 待回测 {len(data.index)} 行（read_sql {read_sec:.1f}s）开始 run_check")

        subset = data[list(tbs.TABLE_CN_STOCK_FOREIGN_KEY['columns'])]
        subset = subset.astype({'date': 'string'})
        stocks = [tuple(x) for x in subset.values]

        # 海龟交易使用带止损/止盈退出机制的回测
        rate_func = None
        if table_name == 'cn_stock_strategy_turtle_trade':
            from functools import partial
            rate_func = partial(rate.get_rates_with_exit,
                                trailing_exit_days=20, stop_loss_pct=10)

        rc_t0 = datetime.datetime.now()
        results = run_check(stocks, date_start, date_end, backtest_column,
                            rate_func=rate_func)
        rc_sec = (datetime.datetime.now() - rc_t0).total_seconds()
        if results is None:
            logging.info(f"backtest {tag} run_check 无结果（{rc_sec:.1f}s）")
            return
        logging.info(f"backtest {tag} run_check 完成 {len(results)} 条（{rc_sec:.1f}s）开始写库")

        wr_t0 = datetime.datetime.now()
        data_new = pd.DataFrame(results.values())
        mdb.update_db_from_df(data_new, table_name, ('date', 'code'))
        wr_sec = (datetime.datetime.now() - wr_t0).total_seconds()
        total_sec = (datetime.datetime.now() - t0).total_seconds()
        logging.info(f"backtest {tag} 写库完成（{wr_sec:.1f}s）总耗时 {total_sec:.1f}s")

    except Exception as e:
        logging.error(f"backtest_data_daily_job.process处理异常：{table}表", exc_info=True)
    finally:
        gc.collect()


# 内层并发线程数（每线程加载 ~1-3MB DataFrame）
# 默认 2（适配 ≤2GB 服务器），可通过环境变量 QUANTIA_BACKTEST_INNER_WORKERS 覆盖
_INNER_WORKERS = _cfg.get_int('QUANTIA_BACKTEST_INNER_WORKERS', 2)


def run_check(stocks, date_start, date_end, backtest_column, workers=_INNER_WORKERS,
              rate_func=None):
    """
    逐只股票从缓存读取历史数据并计算回测收益率

    与原版的区别：
    - 原版：从内存 dict 直接查 data_all.get((date, code, name))
    - 新版：从磁盘缓存按需读取 read_stock_hist_from_cache(code, ...)

    注意：缓存读取在线程内部执行，避免主线程一次性加载所有数据到内存

    参数:
        rate_func: 自定义收益率计算函数，签名同 rate.get_rates。默认使用 rate.get_rates。
    """
    if rate_func is None:
        rate_func = rate.get_rates
    data = {}

    def _process_stock(stock):
        """在线程内读取缓存+计算回测，避免主线程内存堆积"""
        code = stock[1]
        hist_data = stf.read_stock_hist_from_cache(code, date_start, date_end)
        if hist_data is None or len(hist_data) == 0:
            return None
        return rate_func(stock, hist_data, backtest_column, len(backtest_column) - 1)

    # 分批提交（时间换空间）：每批 50 只股票，避免一次创建大量 Future 对象
    _CHUNK = 50
    try:
        for chunk_start in range(0, len(stocks), _CHUNK):
            chunk = stocks[chunk_start:chunk_start + _CHUNK]
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_stock = {executor.submit(_process_stock, stock): stock for stock in chunk}
                for future in concurrent.futures.as_completed(future_to_stock):
                    stock = future_to_stock[future]
                    try:
                        _data_ = future.result()
                        if _data_ is not None:
                            data[stock] = _data_
                    except Exception as e:
                        logging.error(f"backtest_data_daily_job.run_check处理异常：{stock[1]}代码", exc_info=True)
            gc.collect()
    except Exception as e:
        logging.error(f"backtest_data_daily_job.run_check处理异常", exc_info=True)
    if not data:
        return None
    else:
        return data


def main():
    prepare()
    summarize_backtest()


def _migrate_summary_columns(summary_table, horizons):
    """检查 cn_stock_backtest 表是否缺少 avg_rate_N 列，缺少则自动添加。"""
    try:
        rows = mdb.executeSqlFetch(f"SHOW COLUMNS FROM `{summary_table}`")
        existing_names = {row[0] for row in rows} if rows else set()
    except Exception as e:
        logging.error(f"Migration SHOW COLUMNS failed for {summary_table}: {e}")
        existing_names = set()

    for h in horizons:
        col = f'avg_rate_{h}'
        if existing_names and col in existing_names:
            continue
        try:
            mdb.executeSql(f"ALTER TABLE `{summary_table}` ADD COLUMN `{col}` FLOAT NULL")
            logging.info(f"Auto-migrated: added column `{col}` to `{summary_table}`")
        except Exception as e:
            # 1060 = Duplicate column name — column already exists, safe to ignore
            if '1060' in str(e):
                pass
            else:
                logging.error(f"Migration ADD COLUMN `{col}` failed: {e}")


def summarize_backtest():
    """
    汇总各策略表的回测结果到 cn_stock_backtest 表

    从每个策略表中读取选股记录，统计选股数量。
    如果有回测收益数据(rate_N不为NULL)，同时计算平均收益率和成功率。

    成功率定义：使用最短可用horizon（rate_5优先，不存在时用rate_3，再不存在用rate_1）
    判断 rate_N > 0 的比例。
    """
    # 汇总表覆盖的 horizon 列表（与 cn_stock_backtest 表结构一致）
    SUMMARY_HORIZONS = [1, 3, 5, 10, 20, 30, 60, 90, 120]
    # 成功率计算优先使用的 horizon（依优先级尝试）
    SUCCESS_HORIZONS = [5, 3, 1]

    try:
        tables = [tbs.TABLE_CN_STOCK_INDICATORS_BUY, tbs.TABLE_CN_STOCK_INDICATORS_SELL]
        tables.extend(tbs.TABLE_CN_STOCK_STRATEGIES)
        tables.append(tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE)

        summary_table = tbs.TABLE_CN_STOCK_BACKTEST['name']

        # 自动迁移：如果表已存在但缺少新增的 avg_rate_N 列，自动 ALTER TABLE 添加
        if mdb.checkTableIsExist(summary_table):
            _migrate_summary_columns(summary_table, SUMMARY_HORIZONS)
            mdb.executeSql(f"DELETE FROM `{summary_table}`")

        all_rows = []

        for table in tables:
            table_name = table['name']
            if not mdb.checkTableIsExist(table_name):
                continue

            try:
                # 动态构建 AVG 子句
                avg_parts = []
                for h in SUMMARY_HORIZONS:
                    if h <= tbs.RATE_FIELDS_COUNT:
                        avg_parts.append(f"ROUND(AVG(`rate_{h}`), 4) as avg_rate_{h}")
                    else:
                        avg_parts.append(f"NULL as avg_rate_{h}")
                avg_clause = ",\n                    ".join(avg_parts)

                # 成功率：依次尝试 rate_5, rate_3, rate_1，取第一个非全 NULL 的
                # 使用 COALESCE 方式：先看 rate_5，NULL 时降级到 rate_3，再降级到 rate_1
                success_expr = "COALESCE(`rate_5`, `rate_3`, `rate_1`)"

                sql = f"""SELECT `date`,
                    COUNT(*) as stock_count,
                    SUM(CASE WHEN {success_expr} IS NOT NULL THEN 1 ELSE 0 END) as backtested_count,
                    SUM(CASE WHEN {success_expr} > 0 THEN 1 ELSE 0 END) as success_count,
                    {avg_clause}
                    FROM `{table_name}`
                    GROUP BY `date`
                    ORDER BY `date` DESC"""

                data = pd.read_sql(sql=sql, con=mdb.engine())
                if data is None or len(data) == 0:
                    continue

                # 添加策略名称（使用中文名，供前端数据表直接展示）
                # dashboard API 的 _get_strategy_map() 同时支持中文名和表名查找
                data['strategy_name'] = table.get('cn', table_name)
                # 转数值类型
                for nc in ('success_count', 'backtested_count', 'stock_count'):
                    data[nc] = pd.to_numeric(data[nc], errors='coerce').fillna(0).astype(int)
                # 成功率 = 成功数 / 已回测数 * 100（除以已回测数，而非全部选股数）
                has_backtest = data['backtested_count'] > 0
                if has_backtest.any():
                    data.loc[has_backtest, 'success_rate'] = (
                        data.loc[has_backtest, 'success_count'] / data.loc[has_backtest, 'backtested_count'] * 100
                    ).round(2)
                if (~has_backtest).any():
                    data.loc[~has_backtest, 'success_rate'] = None

                # 按 cn_stock_backtest 表的列顺序整理
                cols = list(tbs.TABLE_CN_STOCK_BACKTEST['columns'].keys())
                for col in cols:
                    if col not in data.columns:
                        data[col] = None
                data = data[cols]

                all_rows.append(data)

            except Exception as e:
                logging.warning(f"汇总策略 {table_name} 回测数据异常：{e}")

        if not all_rows:
            logging.info("回测汇总：无可汇总的数据")
            return

        result = pd.concat(all_rows, ignore_index=True)

        cols_type = None
        if not mdb.checkTableIsExist(summary_table):
            cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_BACKTEST['columns'])

        mdb.insert_db_from_df(result, summary_table, cols_type, False, "`date`,`strategy_name`")
        logging.info(f"回测汇总完成：{len(result)} 条记录，覆盖 {len(all_rows)} 个策略")

    except Exception as e:
        logging.error(f"backtest_data_daily_job.summarize_backtest处理异常", exc_info=True)


# main函数入口
if __name__ == '__main__':
    main()

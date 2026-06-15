#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流式数据分析处理器（Phase 4 统一入口）

核心思想：单次遍历 + 按需读取 + 及时释放
- 从磁盘缓存逐只读取股票历史数据（~350 KB/只）
- 对每只股票同时运行：指标计算、K线形态识别、全部策略检测
- 结果分批写入数据库（每 BATCH_SIZE 只股票写入一次）
- 处理完即释放内存，峰值内存 < 100 MB（vs 原架构 ~1670 MB）

替代模块：
- indicators_data_daily_job.py（指标计算）
- klinepattern_data_daily_job.py（K线形态）
- strategy_data_daily_job.py（策略选股）

设计要点：
1. 零API调用：所有数据从 Phase 1 已更新的本地缓存读取
2. 单次遍历：4900 只股票 × 1 次缓存读取 = 4900 次 I/O
   （原架构：3 + 13 = 16 次遍历 × 4900 = 78400 次 I/O）
3. 容错：单只股票处理失败不影响其他股票
4. 批量写入：减少数据库连接开销
"""

import logging
import time
import datetime
import gc
import concurrent.futures
import pandas as pd
import os.path
import sys

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
import quantia.lib.trade_time as trd
import quantia.core.stockfetch as stf
import quantia.core.indicator.calculate_indicator as idr
import quantia.core.indicator.buy_sell_signal as bss
import quantia.core.pattern.pattern_recognitions as kpr
from quantia.core.singleton_stock import stock_data
import quantia.lib.envconfig as _cfg

__author__ = 'Quantia'
__date__ = '2026/02/14'

# 批量写入大小：每处理 BATCH_SIZE 只股票后统一写入数据库
# 默认 50（适配 ≤2GB 服务器），可通过环境变量 QUANTIA_BATCH_SIZE 覆盖
BATCH_SIZE = _cfg.get_int('QUANTIA_BATCH_SIZE', 50)

# 并发线程数：控制同时读取缓存的股票数（每只 ~1-3 MB DataFrame）
# 默认 2（适配 ≤2GB 服务器），可通过环境变量 QUANTIA_ANALYSIS_WORKERS 覆盖
ANALYSIS_WORKERS = _cfg.get_int('QUANTIA_ANALYSIS_WORKERS', 2)


def _get_stock_list_from_db(date):
    """
    从数据库 cn_stock_spot 表获取股票列表（零API调用）。
    当 analysis_daily_job 独立运行时，不应发起外部请求获取股票列表，
    而是使用 fetch_daily_job 已经入库的行情数据。

    Returns:
        pd.DataFrame | None: 包含 date/code/name 列的 DataFrame
    """
    table_name = tbs.TABLE_CN_STOCK_SPOT['name']
    date_str = date.strftime("%Y-%m-%d")
    try:
        if not mdb.checkTableIsExist(table_name):
            return None
        fk_cols = list(tbs.TABLE_CN_STOCK_FOREIGN_KEY['columns'].keys())
        sql = f"SELECT `{'`,`'.join(fk_cols)}` FROM `{table_name}` WHERE `date` = %s"
        data = pd.read_sql(sql, mdb.engine(), params=(date_str,))
        if data is not None and len(data) > 0:
            return data
        # 当天没有数据时，尝试使用最近一天的数据
        sql_latest = f"SELECT `{'`,`'.join(fk_cols)}` FROM `{table_name}` WHERE `date` = (SELECT MAX(`date`) FROM `{table_name}`)"
        data = pd.read_sql(sql_latest, mdb.engine())
        if data is not None and len(data) > 0:
            logging.info(f"流式分析：使用最近入库日期的股票列表（{len(data)} 只）")
            # 替换日期为当前分析日期
            data['date'] = date_str
            return data
    except Exception as e:
        logging.warning(f"从数据库获取股票列表异常：{e}")
    return None


def _get_stock_tops_from_db(date):
    """
    从数据库 cn_stock_lhb（龙虎榜）表获取近90天上榜股票列表。
    如果表不存在或无数据，返回 None（不发起外部API请求）。

    说明：
        原 fetch_stock_top_entity_data() 使用 API 获取机构买入数据，
        此处用 cn_stock_lhb 表的上榜记录替代（数据由 basic_data_other_daily_job 入库），
        作为 check_high_tight 策略 istop 参数的来源（超集近似）。

    Returns:
        set | None: 近90天内出现在龙虎榜上的股票代码集合
    """
    try:
        table_name = tbs.TABLE_CN_STOCK_lHB['name']
        if not mdb.checkTableIsExist(table_name):
            return None
        date_str = date.strftime("%Y-%m-%d")
        run_date = date + datetime.timedelta(days=-90)
        start_str = run_date.strftime("%Y-%m-%d")
        sql = f"SELECT `code` FROM `{table_name}` WHERE `date` >= %s AND `date` <= %s"
        data = pd.read_sql(sql, mdb.engine(), params=(start_str, date_str))
        if data is not None and len(data) > 0:
            return set(data['code'].values)
    except Exception:
        logging.warning("获取龙虎榜代码集合异常", exc_info=True)
    return None


def streaming_analysis(date):
    """
    流式分析主函数：单次遍历所有股票，同时计算指标、K线形态和策略

    参数：
        date: 交易日期 (datetime.datetime)
    """
    start_time = time.time()
    date_str = date.strftime("%Y-%m-%d")
    logging.info(f"===== Phase 4: 流式分析开始 [{date_str}] =====")

    # 检查 Phase 2 是否失败（由 execute_daily_job 设置环境变量）
    phase2_failed = _cfg.get_bool('QUANTIA_PHASE2_FAILED', False)
    if phase2_failed:
        logging.warning(
            "⚠ Phase 2 K线缓存更新失败（可能 OOM），本次分析将使用已有缓存。"
            "指标/策略结果基于缓存中最后一根K线，可能不包含当日行情。"
        )

    # 1. 获取股票列表 — 优先从数据库读取（零API），单例作为降级方案
    spot = _get_stock_list_from_db(date)
    if spot is not None:
        logging.info(f"流式分析：从数据库获取股票列表（{len(spot)} 只，零API调用）")
    else:
        logging.info("流式分析：数据库无股票列表，降级为 stock_data 单例（可能发起API）")
        try:
            spot = stock_data(date).get_data()
            if spot is None:
                stock_data.release()
                import time as _time
                _time.sleep(3)
                spot = stock_data(date).get_data()
            if spot is None:
                logging.error("流式分析：stock_data 重试后仍返回 None，无法获取股票列表")
                return
        except Exception as e:
            logging.error(f"流式分析：获取股票列表异常", exc_info=True)
            return

    _subset = spot[list(tbs.TABLE_CN_STOCK_FOREIGN_KEY['columns'])]
    stocks = [tuple(x) for x in _subset.values]
    total_stocks = len(stocks)
    logging.info(f"流式分析：共 {total_stocks} 只股票待处理")

    # 2. 计算日期范围（用于从缓存读取）
    years = stf.HIST_DATA_DEFAULT_YEARS
    date_start, _ = trd.get_trade_hist_interval(date, years)
    date_end = date.strftime("%Y%m%d") if hasattr(date, 'strftime') else str(date).replace("-", "")

    # 3. 构建分析列定义
    # 指标列
    indicator_columns = list(tbs.STOCK_STATS_DATA['columns'])
    indicator_columns.insert(0, 'code')
    indicator_columns.insert(0, 'date')

    # K线形态列
    kline_columns = tbs.STOCK_KLINE_PATTERN_DATA['columns']

    # 策略列表 + 龙虎榜数据（check_high_tight 需要）
    strategies = tbs.TABLE_CN_STOCK_STRATEGIES
    stock_tops = _get_stock_tops_from_db(date)
    if stock_tops is None:
        # 数据采集和数据分析分离：分析管道不发起API请求
        # 龙虎榜数据由 basic_data_other_daily_job（fetch管道）负责入库
        logging.warning(f"流式分析：数据库无龙虎榜数据，check_high_tight 策略将跳过。"
                        f"请确认 fetch_daily_job / basic_data_other_daily_job 已正常运行")
    else:
        logging.info(f"流式分析：从数据库获取龙虎榜数据（{len(stock_tops)} 只，零API调用）")

    # 4. 验证数据库表 schema（旧版表列数不足时自动重建）
    _ensure_table_schema(tbs.TABLE_CN_STOCK_INDICATORS['name'], tbs.TABLE_CN_STOCK_INDICATORS['columns'])
    _ensure_table_schema(tbs.TABLE_CN_STOCK_KLINE_PATTERN['name'], tbs.TABLE_CN_STOCK_KLINE_PATTERN['columns'])
    for strategy in strategies:
        _ensure_table_schema(strategy['name'], strategy['columns'])

    # 5. 准备数据库表（记录需要清理的表，延迟到首次写入时清理）
    # 采用延迟删除策略：不在开头一次性 DELETE 所有表的当日数据，
    # 而是在每个表首次写入前才 DELETE，避免中途崩溃导致数据丢失
    tables_cleaned = set()  # 记录已经清理过的表

    # 6. 初始化结果缓冲区
    indicator_results = {}      # {(date, code, name): pd.Series}
    kline_results = {}          # {(date, code, name): pd.Series}
    strategy_results = {s['name']: [] for s in strategies}  # {table_name: [(date, code, name)]}
    strategy_extras = {s['name']: {} for s in strategies}   # {table_name: {(date, code, name): {field: value}}}

    processed = 0
    skipped = 0
    errors = 0
    stale_cache = 0  # 缓存数据不含目标日期的股票数

    # 6. 逐只股票流式处理（多线程并发，但控制同时在内存中的数据量）
    # workers=2 意味着同时最多 2 只股票的历史数据在内存中（~0.7 MB）
    def _process_one_stock(stock):
        """单只股票的完整分析流程（在线程池内执行）"""
        code = stock[1]
        result = {
            'indicator': None,
            'kline': None,
            'strategies': {},  # {table_name: True/dict}
            'stale': False,    # 缓存不含目标日期
        }

        hist_data = stf.read_stock_hist_from_cache(code, date_start, date_end)
        if hist_data is None or len(hist_data) == 0:
            return stock, 'skipped', result

        # 检测缓存新鲜度：缓存最后日期是否 >= 目标日期
        try:
            cache_max_date = hist_data['date'].max()
            cache_max_str = cache_max_date.strftime("%Y-%m-%d") if hasattr(cache_max_date, 'strftime') else str(cache_max_date)[:10]
            if cache_max_str < date_str:
                result['stale'] = True
                # 仍然继续处理：基于最后可用K线计算指标（优于跳过）
        except Exception as e:
            logging.debug(f"缓存日期解析异常: {code} - {e}")  # 不影响后续计算

        # --- 指标计算 ---
        try:
            indicator_result = idr.get_indicator(stock, hist_data, indicator_columns, date=date)
            if indicator_result is not None:
                result['indicator'] = indicator_result
        except Exception as e:
            logging.info(f"指标计算异常：{code} - {e}")

        # --- K线形态识别 ---
        try:
            kline_result = kpr.get_pattern_recognition(stock, hist_data, kline_columns, date=date)
            if kline_result is not None:
                result['kline'] = kline_result
        except Exception as e:
            logging.info(f"K线形态识别异常：{code} - {e}")

        # --- 策略检测 ---
        for strategy in strategies:
            try:
                func = strategy['func']
                if func.__name__ == 'check_high_tight' and stock_tops is not None:
                    matched = func(stock, hist_data, date=date, istop=(code in stock_tops))
                else:
                    matched = func(stock, hist_data, date=date)
                if matched:
                    result['strategies'][strategy['name']] = matched
            except Exception as e:
                logging.info(f"策略检测异常：{code} {strategy['name']} - {e}")

        # 显式释放大 DataFrame，降低 GC 延迟回收的影响
        del hist_data

        return stock, 'ok', result

    # 分批提交（时间换空间）：不再一次性创建 ~4900 个 Future，改为每批 BATCH_SIZE
    for chunk_start in range(0, total_stocks, BATCH_SIZE):
        chunk = stocks[chunk_start:chunk_start + BATCH_SIZE]

        with concurrent.futures.ThreadPoolExecutor(max_workers=ANALYSIS_WORKERS) as executor:
            future_to_stock = {executor.submit(_process_one_stock, stock): stock for stock in chunk}
            for future in concurrent.futures.as_completed(future_to_stock):
                stock = future_to_stock[future]
                code = stock[1]
                try:
                    _, status, result = future.result()
                    if status == 'skipped':
                        skipped += 1
                        continue

                    if result.get('stale'):
                        stale_cache += 1

                    if result['indicator'] is not None:
                        indicator_results[stock] = result['indicator']
                    if result['kline'] is not None:
                        kline_results[stock] = result['kline']
                    for s_name, matched in result['strategies'].items():
                        if matched:
                            strategy_results[s_name].append(stock)
                            if isinstance(matched, dict):
                                strategy_extras[s_name][stock] = matched

                    processed += 1

                except Exception as e:
                    errors += 1
                    logging.error(f"流式分析处理异常：{code} -", exc_info=True)

        # 每批处理完后：写入数据库 + 释放内存
        _flush_results(indicator_results, kline_results, strategy_results, strategy_extras, date_str, strategies, tables_cleaned)
        indicator_results.clear()
        kline_results.clear()
        for k in strategy_results:
            strategy_results[k] = []
        for k in strategy_extras:
            strategy_extras[k] = {}
        gc.collect()
        logging.info(f"流式分析进度：{processed}/{total_stocks}（跳过 {skipped}，过期缓存 {stale_cache}，错误 {errors}）")

    # 7. 最后一批已在循环内写入，无需额外 flush

    elapsed = time.time() - start_time

    # 缓存过期率检测：大量过期缓存意味着 Phase 2 可能失败
    if stale_cache > 0:
        stale_pct = stale_cache / max(processed, 1) * 100
        if stale_pct > 80:
            logging.warning(
                f"⚠ 缓存过期率 {stale_pct:.0f}%（{stale_cache}/{processed}）！"
                f"K线缓存未包含 {date_str} 的数据，指标/策略结果基于前一交易日。"
                f"请检查 Phase 2（fetch_data_job）是否因 OOM 被杀。"
            )
        else:
            logging.info(f"缓存过期：{stale_cache} 只股票的缓存未覆盖 {date_str}（占比 {stale_pct:.1f}%）")

    logging.info(
        f"===== Phase 4: 流式分析完成 =====\n"
        f"  总数: {total_stocks}，处理: {processed}，跳过: {skipped}，过期缓存: {stale_cache}，错误: {errors}\n"
        f"  耗时: {elapsed:.1f}秒"
    )


def _prepare_tables(date_str, strategies):
    """清理当日旧数据，为批量写入做准备（已弃用，改为延迟删除）"""
    pass


def _clean_table_if_needed(table_name, date_str, tables_cleaned):
    """延迟清理：首次写入某表时才 DELETE 当日旧数据，避免中途崩溃丢数据"""
    if table_name not in tables_cleaned:
        try:
            if mdb.checkTableIsExist(table_name):
                del_sql = f"DELETE FROM `{table_name}` WHERE `date` = %s"
                mdb.executeSql(del_sql, (date_str,))
        except Exception as e:
            logging.warning(f"清理表 {table_name} 异常：{e}")
        tables_cleaned.add(table_name)


def _ensure_table_schema(table_name, expected_columns):
    """
    检查表的列是否与代码定义一致，不一致则重建表。
    解决旧版数据库 schema 与新版代码不兼容的问题。
    例如：旧版 cn_stock_indicators 只有 26 列，新版有 77 列。
    """
    if not mdb.checkTableIsExist(table_name):
        return  # 表不存在，后续 insert_db_from_df 会自动创建

    try:
        # 使用 mdb.get_connection() 代替 raw pymysql.connect()，
        # 享受线程安全的连接复用和自动重试
        with mdb.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COLUMN_NAME FROM information_schema.columns "
                    "WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
                    (mdb.db_database, table_name)
                )
                db_columns = set(row[0] for row in cur.fetchall())

        code_columns = set(expected_columns.keys())

        # 检查是否有代码中定义但数据库缺失的列
        missing = code_columns - db_columns
        if missing:
            logging.warning(
                f"表 {table_name} schema 不兼容：缺少 {len(missing)} 列 "
                f"(如 {list(missing)[:5]})，将删除重建"
            )
            mdb.executeSql(f"DROP TABLE `{table_name}`")
            logging.info(f"已删除旧表 {table_name}，将在写入时自动重建")
    except Exception as e:
        mdb._invalidate_shared_conn()
        logging.error(f"检查表 {table_name} schema 异常（后续写入可能失败）", exc_info=True)


def _flush_results(indicator_results, kline_results, strategy_results, strategy_extras, date_str, strategies, tables_cleaned):
    """将缓冲区中的分析结果批量写入数据库"""

    # --- 写入指标数据 ---
    if indicator_results:
        try:
            _write_indicator_results(indicator_results, date_str, tables_cleaned)
        except Exception as e:
            logging.error(f"写入指标数据异常", exc_info=True)

    # --- 写入K线形态数据 ---
    if kline_results:
        try:
            _write_kline_results(kline_results, date_str, tables_cleaned)
        except Exception as e:
            logging.error(f"写入K线形态数据异常", exc_info=True)

    # --- 写入策略数据 ---
    for strategy in strategies:
        table_name = strategy['name']
        matched_stocks = strategy_results.get(table_name, [])
        if matched_stocks:
            try:
                extras = strategy_extras.get(table_name, {})
                _write_strategy_results(matched_stocks, table_name, date_str, tables_cleaned, extras)
            except Exception as e:
                logging.error(f"写入策略数据异常：{table_name} -", exc_info=True)


def _write_indicator_results(results, date_str, tables_cleaned):
    """写入指标计算结果"""
    table_name = tbs.TABLE_CN_STOCK_INDICATORS['name']
    _clean_table_if_needed(table_name, date_str, tables_cleaned)
    cols_type = None
    if not mdb.checkTableIsExist(table_name):
        cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_INDICATORS['columns'])

    dataKey = pd.DataFrame(results.keys())
    _columns = tuple(tbs.TABLE_CN_STOCK_FOREIGN_KEY['columns'])
    dataKey.columns = _columns

    dataVal = pd.DataFrame(results.values())
    dataVal.drop('date', axis=1, inplace=True, errors='ignore')

    data = pd.merge(dataKey, dataVal, on=['code'], how='left')
    if date_str != data.iloc[0]['date']:
        data['date'] = date_str
    mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")


def _write_kline_results(results, date_str, tables_cleaned):
    """写入K线形态识别结果"""
    table_name = tbs.TABLE_CN_STOCK_KLINE_PATTERN['name']
    _clean_table_if_needed(table_name, date_str, tables_cleaned)
    cols_type = None
    if not mdb.checkTableIsExist(table_name):
        cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_KLINE_PATTERN['columns'])

    dataKey = pd.DataFrame(results.keys())
    _columns = tuple(tbs.TABLE_CN_STOCK_FOREIGN_KEY['columns'])
    dataKey.columns = _columns

    dataVal = pd.DataFrame(results.values())

    data = pd.merge(dataKey, dataVal, on=['code'], how='left')
    if date_str != data.iloc[0]['date']:
        data['date'] = date_str
    mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")


def _write_strategy_results(matched_stocks, table_name, date_str, tables_cleaned, extras=None):
    """写入策略选股结果（含策略指标数据）"""
    _clean_table_if_needed(table_name, date_str, tables_cleaned)
    # 查找该表对应的列定义
    strategy_def = None
    for s in tbs.TABLE_CN_STOCK_STRATEGIES:
        if s['name'] == table_name:
            strategy_def = s
            break
    cols_type = None
    if not mdb.checkTableIsExist(table_name):
        cols_type = tbs.get_field_types(strategy_def['columns'] if strategy_def else tbs.TABLE_CN_STOCK_STRATEGIES[0]['columns'])

    data = pd.DataFrame(matched_stocks)
    columns = tuple(tbs.TABLE_CN_STOCK_FOREIGN_KEY['columns'])
    data.columns = columns

    # 合并策略返回的额外指标列（如放量上涨的 p_change, volume, vol_ratio 等）
    extra_keys = set()
    if extras:
        for stock_key, metrics in extras.items():
            extra_keys.update(metrics.keys())
        for key in extra_keys:
            data[key] = data.apply(
                lambda row, k=key: extras.get((row['date'], row['code'], row['name']), {}).get(k),
                axis=1
            )

    _columns_backtest = list(tbs.TABLE_CN_STOCK_BACKTEST_DATA['columns'])
    all_columns = list(columns) + sorted(extra_keys) + _columns_backtest
    data = data.reindex(columns=all_columns)
    if date_str != data.iloc[0]['date']:
        data['date'] = date_str
    mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")


def guess_indicators(date):
    """
    指标二次筛选：买入/卖出信号

    从已写入的指标表中筛选符合条件的股票，与流式分析独立运行。
    依赖 cn_stock_indicators 表已由 streaming_analysis 写入。
    """
    # 先验证 indicators 表是否存在且有数据
    _table_name = tbs.TABLE_CN_STOCK_INDICATORS['name']
    if not mdb.checkTableIsExist(_table_name):
        logging.info("guess_indicators: cn_stock_indicators 表不存在，跳过")
        return

    # 验证 buy/sell 表 schema（旧表可能缺少 rate_21~rate_100 列）
    _ensure_table_schema(tbs.TABLE_CN_STOCK_INDICATORS_BUY['name'], tbs.TABLE_CN_STOCK_INDICATORS_BUY['columns'])
    _ensure_table_schema(tbs.TABLE_CN_STOCK_INDICATORS_SELL['name'], tbs.TABLE_CN_STOCK_INDICATORS_SELL['columns'])

    _guess_buy(date)
    _guess_sell(date)


def _guess_buy(date):
    """筛选买入信号：超卖深跌抄底 + 限定基本面范围 + 排除 ST。"""
    try:
        data = bss.select_buy_signals(date)
        if data is None or len(data.index) == 0:
            return

        table_name = tbs.TABLE_CN_STOCK_INDICATORS_BUY['name']
        if mdb.checkTableIsExist(table_name):
            del_sql = f"DELETE FROM `{table_name}` WHERE `date` = %s"
            mdb.executeSql(del_sql, (date,))
            cols_type = None
        else:
            cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_INDICATORS_BUY['columns'])

        _columns_backtest = list(tbs.TABLE_CN_STOCK_BACKTEST_DATA['columns'])
        data = data.reindex(columns=list(data.columns) + _columns_backtest)
        mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")
    except Exception as e:
        logging.error(f"streaming_analysis_job._guess_buy处理异常", exc_info=True)


def _guess_sell(date):
    """筛选卖出信号：超买见顶派发 + 贴近历史峰值 + 排除 ST（不限基本面）。"""
    try:
        data = bss.select_sell_signals(date)
        if data is None or len(data.index) == 0:
            return

        table_name = tbs.TABLE_CN_STOCK_INDICATORS_SELL['name']
        if mdb.checkTableIsExist(table_name):
            del_sql = f"DELETE FROM `{table_name}` WHERE `date` = %s"
            mdb.executeSql(del_sql, (date,))
            cols_type = None
        else:
            cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_INDICATORS_SELL['columns'])

        _columns_backtest = list(tbs.TABLE_CN_STOCK_BACKTEST_DATA['columns'])
        data = data.reindex(columns=list(data.columns) + _columns_backtest)
        mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")
    except Exception as e:
        logging.error(f"streaming_analysis_job._guess_sell处理异常", exc_info=True)


def main():
    """流式分析入口（兼容 run_with_args 调用模式）"""
    import quantia.lib.run_template as runt
    runt.run_with_args(streaming_analysis)
    runt.run_with_args(guess_indicators)


# main函数入口
if __name__ == '__main__':
    main()

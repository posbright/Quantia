#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import concurrent.futures
import inspect
import json
import pandas as pd
import os.path
import sys

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
import quantia.lib.run_template as runt
import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
from quantia.core.singleton_stock import stock_hist_data
from quantia.core.stockfetch import fetch_stock_top_entity_data
import quantia.lib.envconfig as _cfg

__author__ = 'Quantia'
__date__ = '2026/02/14'

_STRATEGY_WORKERS = _cfg.get_int('QUANTIA_STRATEGY_WORKERS', 4)
_STRATEGY_OUTER_WORKERS = _cfg.get_int('QUANTIA_STRATEGY_OUTER_WORKERS', 2)

# 支持「UI 可调参数真正接入每日选股」的策略：策略结果表名 -> 参数配置 strategy_key。
# 仅对白名单内的策略读取 cn_strategy_params 并按函数签名过滤后传入 check()，
# 避免影响未开启参数化的其它策略。
_PARAM_WIRED_STRATEGIES = {
    'cn_stock_strategy_enter': 'enter',
    'cn_stock_strategy_keep_increasing': 'keep_increasing',
    'cn_stock_strategy_parking_apron': 'parking_apron',
    'cn_stock_strategy_backtrace_ma250': 'backtrace_ma250',
    'cn_stock_strategy_breakthrough_platform': 'breakthrough_platform',
    'cn_stock_strategy_low_backtrace_increase': 'low_backtrace_increase',
    'cn_stock_strategy_turtle_trade': 'turtle_trade',
    'cn_stock_strategy_high_tight_flag': 'high_tight_flag',
    'cn_stock_strategy_climax_limitdown': 'climax_limitdown',
    'cn_stock_strategy_low_atr': 'low_atr',
}


def _load_strategy_kwargs(table_name, strategy_fun):
    """读取该策略已保存的可调参数（cn_strategy_params），按 check() 签名过滤后返回。

    未配置/读取失败/无白名单时返回空 dict，check() 使用其默认参数。
    """
    strategy_key = _PARAM_WIRED_STRATEGIES.get(table_name)
    if not strategy_key:
        return {}
    try:
        if not mdb.checkTableIsExist('cn_strategy_params'):
            return {}
        rows = mdb.executeSqlFetch(
            "SELECT `param_key`, `param_value` FROM `cn_strategy_params` WHERE `strategy_key` = %s",
            (strategy_key,))
        if not rows:
            return {}
        accepted = set(inspect.signature(strategy_fun).parameters.keys())
        kwargs = {}
        for param_key, raw in rows:
            if param_key not in accepted or raw is None:
                continue
            if isinstance(raw, (int, float, bool)):
                kwargs[param_key] = raw
            else:
                try:
                    kwargs[param_key] = json.loads(raw)
                except (TypeError, ValueError):
                    continue
        return kwargs
    except Exception:
        logging.error(f"加载策略可调参数异常：{table_name}", exc_info=True)
        mdb._invalidate_shared_conn()
        return {}



def prepare(date, strategy):
    try:
        logging.info(f"strategy_data_daily_job开始执行：{strategy.get('name', strategy)}，日期{date}")
        stocks_data = stock_hist_data(date=date).get_data()
        if stocks_data is None:
            logging.warning(f"strategy_data_daily_job：stock_hist_data返回None，跳过策略{strategy.get('name', strategy)}")
            return
        table_name = strategy['name']
        strategy_func = strategy['func']
        extra_kwargs = _load_strategy_kwargs(table_name, strategy_func)
        results, extras = run_check(strategy_func, table_name, stocks_data, date, extra_kwargs=extra_kwargs)
        if results is None:
            return

        # 删除老数据。
        if mdb.checkTableIsExist(table_name):
            del_sql = f"DELETE FROM `{table_name}` WHERE `date` = %s"
            mdb.executeSql(del_sql, (date,))
            cols_type = None
        else:
            cols_type = tbs.get_field_types(strategy['columns'])

        data = pd.DataFrame(results)
        columns = tuple(tbs.TABLE_CN_STOCK_FOREIGN_KEY['columns'])
        data.columns = columns

        # 合并策略返回的额外指标列（如放量上涨的 p_change, volume, vol_ratio 等）
        extra_keys = set()
        if extras:
            for stock_key, metrics in extras.items():
                extra_keys.update(metrics.keys())
            for key in extra_keys:
                data[key] = data.apply(
                    lambda row: extras.get((row['date'], row['code'], row['name']), {}).get(key),
                    axis=1
                )

        _columns_backtest = list(tbs.TABLE_CN_STOCK_BACKTEST_DATA['columns'])
        all_columns = list(columns) + sorted(extra_keys) + _columns_backtest
        data = data.reindex(columns=all_columns)
        # 单例，时间段循环必须改时间
        date_str = date.strftime("%Y-%m-%d")
        if date.strftime("%Y-%m-%d") != data.iloc[0]['date']:
            data['date'] = date_str
        mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")

    except Exception as e:
        logging.error(f"strategy_data_daily_job.prepare处理异常：{strategy}策略", exc_info=True)


def run_check(strategy_fun, table_name, stocks, date, workers=_STRATEGY_WORKERS, extra_kwargs=None):
    is_check_high_tight = False
    if strategy_fun.__name__ == 'check_high_tight':
        stock_tops = fetch_stock_top_entity_data(date)
        if stock_tops is not None:
            is_check_high_tight = True
    extra_kwargs = extra_kwargs or {}
    data = []
    extras = {}  # stock_key -> metrics dict (for strategies that return enriched data)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            if is_check_high_tight:
                future_to_data = {executor.submit(strategy_fun, k, stocks[k], date=date, istop=(k[1] in stock_tops), **extra_kwargs): k for k in stocks}
            else:
                future_to_data = {executor.submit(strategy_fun, k, stocks[k], date=date, **extra_kwargs): k for k in stocks}
            for future in concurrent.futures.as_completed(future_to_data):
                stock = future_to_data[future]
                try:
                    result = future.result()
                    if result:
                        data.append(stock)
                        if isinstance(result, dict):
                            extras[stock] = result
                except Exception as e:
                    logging.error(f"strategy_data_daily_job.run_check处理异常：{stock[1]}代码策略{table_name}", exc_info=True)
    except Exception as e:
        logging.error(f"strategy_data_daily_job.run_check处理异常策略{table_name}", exc_info=True)
    if not data:
        return None, {}
    else:
        return data, extras



def main():
    # 使用方法传递。并发数通过 QUANTIA_STRATEGY_OUTER_WORKERS 配置
    with concurrent.futures.ThreadPoolExecutor(max_workers=_STRATEGY_OUTER_WORKERS) as executor:
        for strategy in tbs.TABLE_CN_STOCK_STRATEGIES:
            executor.submit(runt.run_with_args, prepare, strategy)


# main函数入口
if __name__ == '__main__':
    main()

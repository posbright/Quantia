#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import logging
import concurrent.futures
import pandas as pd
import os.path
import sys

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
import quantia.lib.run_template as runt
import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
import quantia.core.indicator.calculate_indicator as idr
from quantia.core.singleton_stock import stock_hist_data
import quantia.lib.envconfig as _cfg

__author__ = 'Quantia'
__date__ = '2026/02/14'

_INDICATOR_WORKERS = _cfg.get_int('QUANTIA_INDICATOR_WORKERS', 4)


def prepare(date):
    try:
        logging.info(f"indicators_data_daily_job开始执行：{date}")
        stocks_data = stock_hist_data(date=date).get_data()
        if stocks_data is None:
            logging.warning("indicators_data_daily_job：stock_hist_data返回None，跳过")
            return
        logging.info(f"indicators_data_daily_job获取到{len(stocks_data)}只股票历史数据，开始计算指标")
        results = run_check(stocks_data, date=date)
        if results is None:
            logging.warning("indicators_data_daily_job：run_check返回None，无指标数据")
            return

        table_name = tbs.TABLE_CN_STOCK_INDICATORS['name']
        # 删除老数据。
        if mdb.checkTableIsExist(table_name):
            del_sql = f"DELETE FROM `{table_name}` WHERE `date` = %s"
            mdb.executeSql(del_sql, (date,))
            cols_type = None
        else:
            cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_INDICATORS['columns'])

        dataKey = pd.DataFrame(results.keys())
        _columns = tuple(tbs.TABLE_CN_STOCK_FOREIGN_KEY['columns'])
        dataKey.columns = _columns

        dataVal = pd.DataFrame(results.values())
        dataVal.drop('date', axis=1, inplace=True, errors='ignore')  # 删除日期字段，然后和原始数据合并。

        data = pd.merge(dataKey, dataVal, on=['code'], how='left')
        # data.set_index('code', inplace=True)
        # 单例，时间段循环必须改时间
        date_str = date.strftime("%Y-%m-%d")
        if date.strftime("%Y-%m-%d") != data.iloc[0]['date']:
            data['date'] = date_str
        mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")

    except Exception as e:
        logging.error(f"indicators_data_daily_job.prepare处理异常", exc_info=True)


def run_check(stocks, date=None, workers=_INDICATOR_WORKERS):
    data = {}
    columns = list(tbs.STOCK_STATS_DATA['columns'])
    columns.insert(0, 'code')
    columns.insert(0, 'date')
    data_column = columns
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_data = {executor.submit(idr.get_indicator, k, stocks[k], data_column, date=date): k for k in stocks}
            for future in concurrent.futures.as_completed(future_to_data):
                stock = future_to_data[future]
                try:
                    _data_ = future.result()
                    if _data_ is not None:
                        data[stock] = _data_
                except Exception as e:
                    logging.error(f"indicators_data_daily_job.run_check处理异常：{stock[1]}代码", exc_info=True)
    except Exception as e:
        logging.error(f"indicators_data_daily_job.run_check处理异常", exc_info=True)
    if not data:
        return None
    else:
        return data


# 对每日指标数据，进行筛选。将符合条件的。二次筛选出来。
# 只是做简单筛选
def guess_buy(date):
    try:
        _table_name = tbs.TABLE_CN_STOCK_INDICATORS['name']
        if not mdb.checkTableIsExist(_table_name):
            return

        _columns = tuple(tbs.TABLE_CN_STOCK_FOREIGN_KEY['columns'])
        _selcol = '`,`'.join(_columns)
        sql = f'''SELECT `{_selcol}` FROM `{_table_name}` WHERE `date` = %s and
                `kdjk` >= 80 and `kdjd` >= 70 and `kdjj` >= 100 and `rsi_6` >= 80 and
                `cci` >= 100 and `cr` >= 300 and `wr_6` >= -20 and `vr` >= 160'''
        data = pd.read_sql(sql=sql, con=mdb.engine(), params=(date,))
        data = data.drop_duplicates(subset="code", keep="last")
        # data.set_index('code', inplace=True)

        if len(data.index) == 0:
            return

        table_name = tbs.TABLE_CN_STOCK_INDICATORS_BUY['name']
        # 删除老数据。
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
        logging.error(f"indicators_data_daily_job.guess_buy处理异常", exc_info=True)


# 设置卖出数据。
def guess_sell(date):
    try:
        _table_name = tbs.TABLE_CN_STOCK_INDICATORS['name']
        if not mdb.checkTableIsExist(_table_name):
            return

        _columns = tuple(tbs.TABLE_CN_STOCK_FOREIGN_KEY['columns'])
        _selcol = '`,`'.join(_columns)
        sql = f'''SELECT `{_selcol}` FROM `{_table_name}` WHERE `date` = %s and
                `kdjk` < 20 and `kdjd` < 30 and `kdjj` < 10 and `rsi_6` < 20 and
                `cci` < -100 and `cr` < 40 and `wr_6` < -80 and `vr` < 40'''
        data = pd.read_sql(sql=sql, con=mdb.engine(), params=(date,))
        data = data.drop_duplicates(subset="code", keep="last")
        # data.set_index('code', inplace=True)
        if len(data.index) == 0:
            return

        table_name = tbs.TABLE_CN_STOCK_INDICATORS_SELL['name']
        # 删除老数据。
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
        logging.error(f"indicators_data_daily_job.guess_sell处理异常", exc_info=True)


def main():
    # 使用方法传递。
    runt.run_with_args(prepare)
    # 二次筛选数据。直接计算买卖股票数据。
    runt.run_with_args(guess_buy)
    runt.run_with_args(guess_sell)


# main函数入口
if __name__ == '__main__':
    main()

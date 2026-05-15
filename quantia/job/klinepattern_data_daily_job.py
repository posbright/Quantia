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
from quantia.core.singleton_stock import stock_hist_data
import quantia.core.pattern.pattern_recognitions as kpr
import quantia.lib.envconfig as _cfg

__author__ = 'Quantia'
__date__ = '2026/02/14'

_KLINE_PATTERN_WORKERS = _cfg.get_int('QUANTIA_KLINE_PATTERN_WORKERS', 4)


def prepare(date):
    try:
        logging.info(f"klinepattern_data_daily_job开始执行：{date}")
        stocks_data = stock_hist_data(date=date).get_data()
        if stocks_data is None:
            logging.warning("klinepattern_data_daily_job：stock_hist_data返回None，跳过")
            return
        logging.info(f"klinepattern_data_daily_job获取到{len(stocks_data)}只股票历史数据，开始识别K线形态")
        results = run_check(stocks_data, date=date)
        if results is None:
            logging.warning("klinepattern_data_daily_job：run_check返回None，无K线形态数据")
            return

        table_name = tbs.TABLE_CN_STOCK_KLINE_PATTERN['name']
        # 删除老数据。
        if mdb.checkTableIsExist(table_name):
            del_sql = f"DELETE FROM `{table_name}` WHERE `date` = %s"
            mdb.executeSql(del_sql, (date,))
            cols_type = None
        else:
            cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_KLINE_PATTERN['columns'])

        dataKey = pd.DataFrame(results.keys())
        _columns = tuple(tbs.TABLE_CN_STOCK_FOREIGN_KEY['columns'])
        dataKey.columns = _columns

        dataVal = pd.DataFrame(results.values())

        data = pd.merge(dataKey, dataVal, on=['code'], how='left')
        # 单例，时间段循环必须改时间
        date_str = date.strftime("%Y-%m-%d")
        if date.strftime("%Y-%m-%d") != data.iloc[0]['date']:
            data['date'] = date_str
        mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")

    except Exception as e:
        logging.error(f"klinepattern_data_daily_job.prepare处理异常", exc_info=True)


def run_check(stocks, date=None, workers=_KLINE_PATTERN_WORKERS):
    data = {}
    columns = tbs.STOCK_KLINE_PATTERN_DATA['columns']
    data_column = columns
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_data = {executor.submit(kpr.get_pattern_recognition, k, stocks[k], data_column, date=date): k for k in stocks}
            for future in concurrent.futures.as_completed(future_to_data):
                stock = future_to_data[future]
                try:
                    _data_ = future.result()
                    if _data_ is not None:
                        data[stock] = _data_
                except Exception as e:
                    logging.error(f"klinepattern_data_daily_job.run_check处理异常：{stock[1]}代码", exc_info=True)
    except Exception as e:
        logging.error(f"klinepattern_data_daily_job.run_check处理异常", exc_info=True)
    if not data:
        return None
    else:
        return data


def main():
    # 使用方法传递。
    runt.run_with_args(prepare)


# main函数入口
if __name__ == '__main__':
    main()

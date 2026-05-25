#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os.path
import sys
import time as _time

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
# 统一日志：stock_basic_after_close.log + stock_error.log + sys.excepthook 兜底
try:
    from quantia.lib.log_config import setup_logging
    setup_logging('basic_after_close')
except Exception:
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s [%(levelname)s] %(message)s')
import quantia.lib.run_template as runt
import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
import quantia.core.stockfetch as stf
from quantia.job.job_utils import fetch_with_retry as _fetch_with_retry

__author__ = 'Quantia'
__date__ = '2026/02/14'


# 每日股票大宗交易
def save_after_close_stock_blocktrade_data(date):
    try:
        data = _fetch_with_retry(lambda: stf.fetch_stock_blocktrade_data(date), "大宗交易")
        if data is None or len(data.index) == 0:
            return

        table_name = tbs.TABLE_CN_STOCK_BLOCKTRADE['name']
        # 删除老数据。
        if mdb.checkTableIsExist(table_name):
            del_sql = f"DELETE FROM `{table_name}` WHERE `date` = %s"
            mdb.executeSql(del_sql, (date,))
            cols_type = None
        else:
            cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_BLOCKTRADE['columns'])

        mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")
    except Exception as e:
        logging.error(f"basic_data_after_close_daily_job.save_stock_blocktrade_data处理异常", exc_info=True)

# 每日尾盘抢筹
def save_after_close_stock_chip_race_end_data(date):
    try:
        data = _fetch_with_retry(lambda: stf.fetch_stock_chip_race_end(date), "尾盘抢筹")
        if data is None or len(data.index) == 0:
            return

        table_name = tbs.TABLE_CN_STOCK_CHIP_RACE_END['name']
        # 删除老数据。
        if mdb.checkTableIsExist(table_name):
            del_sql = f"DELETE FROM `{table_name}` WHERE `date` = %s"
            mdb.executeSql(del_sql, (date,))
            cols_type = None
        else:
            cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_CHIP_RACE_END['columns'])

        mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")
    except Exception as e:
        logging.error(f"basic_data_after_close_daily_job.save_after_close_stock_chip_race_end_data", exc_info=True)

def main():
    runt.run_with_args(save_after_close_stock_blocktrade_data)
    _time.sleep(30)  # 防限流延迟
    runt.run_with_args(save_after_close_stock_chip_race_end_data)


# main函数入口
if __name__ == '__main__':
    main()

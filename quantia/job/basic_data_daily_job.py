#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import datetime
import logging
import os.path
import sys

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
import quantia.lib.run_template as runt
import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
import quantia.core.stockfetch as stf
import quantia.lib.trade_time as trd
from quantia.core.singleton_stock import stock_data

__author__ = 'Quantia'
__date__ = '2026/02/14'


# 股票实时行情数据。
def save_nph_stock_spot_data(date, before=True):
    if before:
        return
    # 股票列表
    try:
        data = stock_data(date).get_data()
        if data is None or len(data.index) == 0:
            return

        table_name = tbs.TABLE_CN_STOCK_SPOT['name']
        # 删除老数据。
        if mdb.checkTableIsExist(table_name):
            try:
                del_sql = f"DELETE FROM `{table_name}` WHERE `date` = %s"
                mdb.executeSql(del_sql, (date,))
            except Exception as e:
                logging.warning(f"basic_data_daily_job.save_stock_spot_data删除旧数据失败，将使用upsert模式继续: {e}")
            cols_type = None
        else:
            cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_SPOT['columns'])

        mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")

    except Exception as e:
        logging.error(f"basic_data_daily_job.save_stock_spot_data处理异常", exc_info=True)


# 基金实时行情数据。
def save_nph_etf_spot_data(date, before=True):
    if before:
        return
    # 股票列表
    try:
        data = stf.fetch_etfs(date)
        if data is None or len(data.index) == 0:
            return

        table_name = tbs.TABLE_CN_ETF_SPOT['name']
        # 删除老数据。
        if mdb.checkTableIsExist(table_name):
            try:
                del_sql = f"DELETE FROM `{table_name}` WHERE `date` = %s"
                mdb.executeSql(del_sql, (date,))
            except Exception as e:
                logging.warning(f"basic_data_daily_job.save_nph_etf_spot_data删除旧数据失败，将使用upsert模式继续: {e}")
            cols_type = None
        else:
            cols_type = tbs.get_field_types(tbs.TABLE_CN_ETF_SPOT['columns'])

        mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")
    except Exception as e:
        logging.error(f"basic_data_daily_job.save_nph_etf_spot_data处理异常", exc_info=True)


# 场外开放式基金（净值型+货币型）排名数据。
def save_nph_fund_data(date, before=True):
    if before:
        return
    try:
        data = stf.fetch_funds(date)
        if data is None or len(data.index) == 0:
            return

        table_name = tbs.TABLE_CN_FUND_RANK['name']
        # 删除老数据。
        if mdb.checkTableIsExist(table_name):
            try:
                del_sql = f"DELETE FROM `{table_name}` WHERE `date` = %s"
                mdb.executeSql(del_sql, (date,))
            except Exception as e:
                logging.warning(f"basic_data_daily_job.save_nph_fund_data删除旧数据失败，将使用upsert模式继续: {e}")
            cols_type = None
        else:
            cols_type = tbs.get_field_types(tbs.TABLE_CN_FUND_RANK['columns'])

        mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")
    except Exception as e:
        logging.error(f"basic_data_daily_job.save_nph_fund_data处理异常", exc_info=True)


# 指数实时行情数据。
def save_nph_index_spot_data(date, before=True):
    if before:
        return
    try:
        data = stf.fetch_index_spots(date)
        if data is None or len(data.index) == 0:
            return

        table_name = tbs.TABLE_CN_INDEX_SPOT['name']
        # 删除老数据。
        if mdb.checkTableIsExist(table_name):
            try:
                del_sql = f"DELETE FROM `{table_name}` WHERE `date` = %s"
                mdb.executeSql(del_sql, (date,))
            except Exception as e:
                logging.warning(f"basic_data_daily_job.save_nph_index_spot_data删除旧数据失败，将使用upsert模式继续: {e}")
            cols_type = None
        else:
            cols_type = tbs.get_field_types(tbs.TABLE_CN_INDEX_SPOT['columns'])

        mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")
    except Exception as e:
        logging.error(f"basic_data_daily_job.save_nph_index_spot_data处理异常", exc_info=True)



def main():
    if len(sys.argv) > 1:
        # 批量模式（指定日期/日期范围）— 由 run_with_args 逐日期解析
        runt.run_with_args(save_nph_stock_spot_data)
        runt.run_with_args(save_nph_etf_spot_data)
        runt.run_with_args(save_nph_index_spot_data)
    else:
        # 当前时间模式（hourly cron / execute_daily_job 调用）
        # 确定日期一次，stock和ETF共享同一日期，
        # 避免两次独立 get_trade_date_last() 在 09:30/15:00 边界产生不同日期
        _init_logging()
        run_date, run_date_nph = trd.get_trade_date_last()
        logging.info(f"basic_data_daily_job 当前时间模式: run_date_nph={run_date_nph}")
        save_nph_stock_spot_data(run_date_nph, False)
        save_nph_etf_spot_data(run_date_nph, False)
        save_nph_index_spot_data(run_date_nph, False)


def _init_logging():
    """独立运行时初始化日志（execute_daily_job 调用时已有 handler，不会重复）"""
    if not logging.getLogger().handlers:
        try:
            from quantia.lib.log_config import setup_logging
            setup_logging('basic')
        except Exception:
            logging.basicConfig(
                format='%(asctime)s [%(levelname)s] %(message)s',
                level=logging.INFO,
            )


# main函数入口
if __name__ == '__main__':
    main()

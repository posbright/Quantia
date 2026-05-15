#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import logging
import pandas as pd
import os.path
import sys

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
import quantia.lib.run_template as runt
import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
import quantia.core.stockfetch as stf

__author__ = 'Quantia'
__date__ = '2026/02/14'


def save_nph_stock_selection_data(date, before=True):
    if before:
        return

    try:
        data = stf.fetch_stock_selection()
        if data is None or len(data) == 0:
            # 首次获取失败，等待后重试一次（可能是瞬时网络问题）
            logging.warning("selection_data: 首次获取选股数据失败，10秒后重试")
            import time as _time
            _time.sleep(10)
            data = stf.fetch_stock_selection()
        if data is None or len(data) == 0:
            logging.error("selection_data: 重试后仍无法获取选股数据，跳过本次更新")
            return

        logging.info(f"selection_data: 获取到 {len(data)} 条选股数据")

        table_name = tbs.TABLE_CN_STOCK_SELECTION['name']
        # 获取数据中的日期，用于删除老数据
        if 'date' in data.columns and len(data) > 0:
            _date = data.iloc[0]['date']
        else:
            _date = date.strftime("%Y-%m-%d") if hasattr(date, 'strftime') else str(date)

        # 删除老数据。
        if mdb.checkTableIsExist(table_name):
            del_sql = f"DELETE FROM `{table_name}` WHERE `date` = %s"
            mdb.executeSql(del_sql, (_date,))
            cols_type = None
        else:
            cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_SELECTION['columns'])

        mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")
        logging.info(f"selection_data: 成功写入 {len(data)} 条数据, date={_date}")
    except Exception as e:
        logging.error(f"selection_data_daily_job.save_nph_stock_selection_data处理异常", exc_info=True)


def main():
    runt.run_with_args(save_nph_stock_selection_data)


# main函数入口
if __name__ == '__main__':
    main()

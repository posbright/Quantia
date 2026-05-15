#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import concurrent.futures
import os.path
import sys
import time as _time
import pandas as pd

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
# 统一日志：stock_basic_other.log + stock_error.log + sys.excepthook 兜底
try:
    from quantia.lib.log_config import setup_logging
    setup_logging('basic_other')
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

# API获取重试间隔（秒）
_RETRY_DELAY = 10
# 子任务间防限流延迟（秒）—— 本地模式减少等待
_TASK_DELAY = 5 if os.environ.get('QUANTIA_LOCAL_MODE') == '1' else 30


# 每日股票龙虎榜
def save_nph_stock_lhb_data(date, before=True):
    if before:
        return

    try:
        data = _fetch_with_retry(lambda: stf.fetch_stock_lhb_data(date), "龙虎榜")
        if data is None or len(data.index) == 0:
            return

        table_name = tbs.TABLE_CN_STOCK_lHB['name']
        # 删除老数据。
        if mdb.checkTableIsExist(table_name):
            del_sql = f"DELETE FROM `{table_name}` WHERE `date` = %s"
            mdb.executeSql(del_sql, (date,))
            cols_type = None
        else:
            cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_lHB['columns'])
        mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")
    except Exception as e:
        logging.error(f"basic_data_other_daily_job.save_stock_lhb_data处理异常", exc_info=True)
    # stock_spot_buy 已移至 analysis_daily_job.py（GPT综合选股后执行）

# 每日股票龙虎榜(新浪)
def save_nph_stock_top_data(date, before=True):
    if before:
        return

    try:
        data = _fetch_with_retry(lambda: stf.fetch_stock_top_data(date), "龙虎榜(新浪)")
        if data is None or len(data.index) == 0:
            return

        table_name = tbs.TABLE_CN_STOCK_TOP['name']
        # 删除老数据。
        if mdb.checkTableIsExist(table_name):
            del_sql = f"DELETE FROM `{table_name}` WHERE `date` = %s"
            mdb.executeSql(del_sql, (date,))
            cols_type = None
        else:
            cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_TOP['columns'])
        mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")
    except Exception as e:
        logging.error(f"basic_data_other_daily_job.save_stock_top_data处理异常", exc_info=True)


# 每日股票资金流向
def save_nph_stock_fund_flow_data(date, before=True):
    if before:
        return

    try:
        times = tuple(range(4))
        results = run_check_stock_fund_flow(times)
        if results is None:
            logging.warning("资金流向：所有时间段数据均获取失败")
            return

        # 使用第一个成功获取的时间段作为基础数据（不再强制要求 t=0"今日"）
        # 原逻辑：t=0 失败则整体跳过 → 导致 cn_stock_fund_flow 始终为空
        # 新逻辑：任何时间段均可作为基础（都包含 code, name, new_price 列）
        data = None
        base_t = None
        for t in range(4):
            if results.get(t) is not None and len(results[t]) > 0:
                data = results[t]
                base_t = t
                break

        if data is None:
            logging.warning("资金流向：所有时间段返回数据为空")
            return

        logging.info(f"资金流向：使用 t={base_t} 作为基础数据（{len(data)} 条）")

        # 合并其他时间段的数据
        for t in range(4):
            if t == base_t:
                continue
            r = results.get(t)
            if r is not None and len(r) > 0:
                r = r.drop(columns=['name', 'new_price'], errors='ignore')
                # 避免合并时 change_rate 冲突（不同时间段有各自的 change_rate_N）
                if t > 0 and 'change_rate' in r.columns:
                    r = r.drop(columns=['change_rate'], errors='ignore')
                data = pd.merge(data, r, on=['code'], how='left')
                logging.info(f"资金流向：合并 t={t} 数据成功")
            else:
                logging.warning(f"资金流向：t={t} 数据为空，跳过")

        if len(data.index) == 0:
            return

        data.insert(0, 'date', date.strftime("%Y-%m-%d"))

        table_name = tbs.TABLE_CN_STOCK_FUND_FLOW['name']
        # 删除老数据。
        if mdb.checkTableIsExist(table_name):
            del_sql = f"DELETE FROM `{table_name}` WHERE `date` = %s"
            mdb.executeSql(del_sql, (date,))
            cols_type = None
        else:
            cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_FUND_FLOW['columns'])

        mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")
        logging.info(f"资金流向数据入库成功：{len(data)} 条")
    except Exception as e:
        logging.error(f"basic_data_other_daily_job.save_nph_stock_fund_flow_data处理异常", exc_info=True)


def run_check_stock_fund_flow(times):
    data = {}
    indicator_names = {0: '今日', 1: '3日', 2: '5日', 3: '10日'}
    try:
        for k in times:
            try:
                _data = _fetch_with_retry(
                    lambda _k=k: stf.fetch_stocks_fund_flow(_k),
                    f"资金流向 t={k}({indicator_names.get(k, '?')})"
                )
                if _data is not None and len(_data) > 0:
                    data[k] = _data
                    logging.info(f"资金流向 t={k}({indicator_names.get(k, '?')}) 获取成功：{len(_data)} 条")
                else:
                    logging.warning(f"资金流向 t={k}({indicator_names.get(k, '?')}) 返回空数据")
            except Exception as e:
                logging.error(f"资金流向 t={k}({indicator_names.get(k, '?')}) 获取异常", exc_info=True)
    except Exception as e:
        logging.error(f"basic_data_other_daily_job.run_check_stock_fund_flow处理异常", exc_info=True)
    # try:
    #     with concurrent.futures.ThreadPoolExecutor(max_workers=len(times)) as executor:
    #         future_to_data = {executor.submit(stf.fetch_stocks_fund_flow, k): k for k in times}
    #         for future in concurrent.futures.as_completed(future_to_data):
    #             _time = future_to_data[future]
    #             try:
    #                 _data_ = future.result()
    #                 if _data_ is not None:
    #                     data[_time] = _data_
    #             except Exception as e:
    #                 logging.error(f"basic_data_other_daily_job.run_check_stock_fund_flow处理异常：代码", exc_info=True)
    # except Exception as e:
    #     logging.error(f"basic_data_other_daily_job.run_check_stock_fund_flow处理异常", exc_info=True)
    if not data:
        return None
    else:
        return data


# 每日行业资金流向
def save_nph_stock_sector_fund_flow_data(date, before=True):
    if before:
        return

    # times = tuple(range(2))
    # with concurrent.futures.ThreadPoolExecutor(max_workers=len(times)) as executor:
    #     {executor.submit(stock_sector_fund_flow_data, date, k): k for k in times}
    stock_sector_fund_flow_data(date, 0)
    stock_sector_fund_flow_data(date, 1)

def stock_sector_fund_flow_data(date, index_sector):
    try:
        times = tuple(range(3))
        results = run_check_stock_sector_fund_flow(index_sector, times)
        if results is None:
            return

        data = None
        for t in times:
            r = results.get(t)
            if r is None:
                continue
            if data is None:
                data = r
            else:
                data = pd.merge(data, r, on=['name'], how='left')

        if data is None or len(data.index) == 0:
            return

        data.insert(0, 'date', date.strftime("%Y-%m-%d"))

        if index_sector == 0:
            tbs_table = tbs.TABLE_CN_STOCK_FUND_FLOW_INDUSTRY
        else:
            tbs_table = tbs.TABLE_CN_STOCK_FUND_FLOW_CONCEPT
        table_name = tbs_table['name']
        # 删除老数据。
        if mdb.checkTableIsExist(table_name):
            del_sql = f"DELETE FROM `{table_name}` WHERE `date` = %s"
            mdb.executeSql(del_sql, (date,))
            cols_type = None
        else:
            cols_type = tbs.get_field_types(tbs_table['columns'])

        mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`name`")
    except Exception as e:
        logging.error(f"basic_data_other_daily_job.stock_sector_fund_flow_data处理异常", exc_info=True)


def run_check_stock_sector_fund_flow(index_sector, times):
    data = {}
    indicator_names = {0: '今日', 1: '3日', 2: '5日'}
    try:
        # 顺序执行（与 run_check_stock_fund_flow 对齐）：
        # 1. 避免 ThreadPoolExecutor 在 API 超时时无限阻塞（无法被 Ctrl+C 中断）
        # 2. 减少对 EastMoney API 的并发压力，降低 500/限流概率
        for k in times:
            try:
                _data = _fetch_with_retry(
                    lambda _k=k: stf.fetch_stocks_sector_fund_flow(index_sector, _k),
                    f"板块资金流向 sector={index_sector} t={k}({indicator_names.get(k, '?')})"
                )
                if _data is not None and len(_data) > 0:
                    data[k] = _data
                    logging.info(f"板块资金流向 sector={index_sector} t={k}({indicator_names.get(k, '?')}) 获取成功：{len(_data)} 条")
                else:
                    logging.warning(f"板块资金流向 sector={index_sector} t={k}({indicator_names.get(k, '?')}) 返回空数据")
            except Exception as e:
                logging.error(f"板块资金流向 sector={index_sector} t={k}({indicator_names.get(k, '?')}) 获取异常", exc_info=True)
    except Exception as e:
        logging.error(f"basic_data_other_daily_job.run_check_stock_sector_fund_flow处理异常", exc_info=True)
    if not data:
        return None
    else:
        return data


# 每日股票分红配送
def save_nph_stock_bonus(date, before=True):
    if before:
        return

    try:
        data = _fetch_with_retry(lambda: stf.fetch_stocks_bonus(date), "股票分红配送")
        if data is None or len(data.index) == 0:
            return

        table_name = tbs.TABLE_CN_STOCK_BONUS['name']
        # 删除老数据。
        if mdb.checkTableIsExist(table_name):
            del_sql = f"DELETE FROM `{table_name}` WHERE `date` = %s"
            mdb.executeSql(del_sql, (date,))
            cols_type = None
        else:
            cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_BONUS['columns'])
        mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")
    except Exception as e:
        logging.error(f"basic_data_other_daily_job.save_nph_stock_bonus处理异常", exc_info=True)


# 基本面选股
def stock_spot_buy(date):
    try:
        _table_name = tbs.TABLE_CN_STOCK_SPOT['name']
        if not mdb.checkTableIsExist(_table_name):
            return

        sql = f'''SELECT * FROM `{_table_name}` WHERE `date` = %s and
                `pe9` > 0 and `pe9` <= 20 and `pbnewmrq` <= 10 and `roe_weight` >= 15'''
        data = pd.read_sql(sql=sql, con=mdb.engine(), params=(date,))
        data = data.drop_duplicates(subset="code", keep="last")
        if len(data.index) == 0:
            return

        table_name = tbs.TABLE_CN_STOCK_SPOT_BUY['name']
        # 删除老数据。
        if mdb.checkTableIsExist(table_name):
            del_sql = f"DELETE FROM `{table_name}` WHERE `date` = %s"
            mdb.executeSql(del_sql, (date,))
            cols_type = None
        else:
            cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_SPOT_BUY['columns'])

        mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")
    except Exception as e:
        logging.error(f"basic_data_other_daily_job.stock_spot_buy处理异常", exc_info=True)


# 每日早盘抢筹
def stock_chip_race_open_data(date):
    try:
        data = _fetch_with_retry(lambda: stf.fetch_stock_chip_race_open(date), "早盘抢筹",
                                 retries=0)  # 早盘数据依赖时段，462错误无需重试
        if data is None or len(data.index) == 0:
            return

        table_name = tbs.TABLE_CN_STOCK_CHIP_RACE_OPEN['name']
        # 删除老数据。
        if mdb.checkTableIsExist(table_name):
            del_sql = f"DELETE FROM `{table_name}` WHERE `date` = %s"
            mdb.executeSql(del_sql, (date,))
            cols_type = None
        else:
            cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_CHIP_RACE_OPEN['columns'])

        mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")
    except Exception as e:
        logging.error(f"basic_data_other_daily_job.stock_chip_race_open_data", exc_info=True)


# 每日涨停原因
def stock_imitup_reason_data(date):
    try:
        data = _fetch_with_retry(lambda: stf.fetch_stock_limitup_reason(date), "涨停原因")
        if data is None or len(data.index) == 0:
            return

        table_name = tbs.TABLE_CN_STOCK_LIMITUP_REASON['name']
        # 删除老数据。
        if mdb.checkTableIsExist(table_name):
            del_sql = f"DELETE FROM `{table_name}` WHERE `date` = %s"
            mdb.executeSql(del_sql, (date,))
            cols_type = None
        else:
            cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_LIMITUP_REASON['columns'])

        mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")
    except Exception as e:
        logging.error(f"basic_data_other_daily_job.stock_imitup_reason_data", exc_info=True)

def main():
    runt.run_with_args(save_nph_stock_lhb_data)
    _time.sleep(_TASK_DELAY)
    runt.run_with_args(save_nph_stock_bonus)
    _time.sleep(_TASK_DELAY)
    runt.run_with_args(save_nph_stock_fund_flow_data)
    _time.sleep(_TASK_DELAY)
    runt.run_with_args(save_nph_stock_sector_fund_flow_data)
    _time.sleep(_TASK_DELAY)
    runt.run_with_args(stock_chip_race_open_data)
    _time.sleep(_TASK_DELAY)
    runt.run_with_args(stock_imitup_reason_data)


# main函数入口
if __name__ == '__main__':
    main()

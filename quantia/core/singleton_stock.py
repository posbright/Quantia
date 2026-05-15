#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import concurrent.futures
import quantia.core.stockfetch as stf
import quantia.core.tablestructure as tbs
import quantia.lib.trade_time as trd
from quantia.lib.singleton_type import singleton_type

__author__ = 'Quantia'
__date__ = '2026/02/14'

# 历史数据默认年数（与 stockfetch.py 保持一致，支持环境变量覆盖）
_DEFAULT_HIST_YEARS = stf.HIST_DATA_DEFAULT_YEARS


# 读取当天股票数据
class stock_data(metaclass=singleton_type):
    def __init__(self, date):
        self.data = None
        try:
            self.data = stf.fetch_stocks(date)
        except Exception as e:
            logging.error(f"singleton.stock_data处理异常", exc_info=True)

    def get_data(self):
        return self.data

    @classmethod
    def release(cls):
        """释放单例实例，回收内存"""
        from quantia.lib.singleton_type import singleton_type
        with singleton_type.single_lock:
            if hasattr(cls, '_instance'):
                del cls._instance


# 读取股票历史数据（支持增量更新和自定义时间范围）
class stock_hist_data(metaclass=singleton_type):
    def __init__(self, date=None, stocks=None, workers=2, years=None, date_start=None, date_end=None):
        """
        初始化股票历史数据
        
        参数：
            date: 基准日期
            stocks: 股票列表，格式 [(date, code), ...]
            workers: 并发线程数
            years: 历史数据年数，默认读取环境变量 HIST_DATA_DEFAULT_YEARS（默认10年）
            date_start: 自定义起始日期 YYYYMMDD
            date_end: 自定义结束日期 YYYYMMDD
        """
        if years is None:
            years = _DEFAULT_HIST_YEARS
        if stocks is None:
            _spot = stock_data(date).get_data()
            if _spot is None:
                logging.error("stock_hist_data初始化失败：stock_data返回None，无法获取股票列表")
                self.data = None
                return
            _subset = _spot[list(tbs.TABLE_CN_STOCK_FOREIGN_KEY['columns'])]
            stocks = [tuple(x) for x in _subset.values]
        if stocks is None or len(stocks) == 0:
            logging.error("stock_hist_data初始化失败：股票列表为空")
            self.data = None
            return
        
        logging.info(f"stock_hist_data开始初始化：{len(stocks)}只股票，{workers}线程，{years}年历史数据")
        
        # 限制并发数，避免过多线程同时请求 API 导致限流/封禁
        workers = min(workers, 4)
        
        # 获取时间区间
        if date_start is None:
            date_start, is_cache = trd.get_trade_hist_interval(stocks[0][0], years)
        else:
            is_cache = True
        
        if date_end is None:
            date_end = stocks[0][0].replace("-", "") if isinstance(stocks[0][0], str) else stocks[0][0].strftime("%Y%m%d")
        
        _data = {}
        try:
            # max_workers是None还是没有给出，将默认为机器cup个数*5
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_stock = {
                    executor.submit(stf.fetch_stock_hist, stock, date_start, date_end, is_cache, years): stock 
                    for stock in stocks
                }
                for future in concurrent.futures.as_completed(future_to_stock):
                    stock = future_to_stock[future]
                    try:
                        __data = future.result()
                        if __data is not None:
                            _data[stock] = __data
                    except Exception as e:
                        logging.error(f"singleton.stock_hist_data处理异常：{stock[1]}代码", exc_info=True)
        except Exception as e:
            logging.error(f"singleton.stock_hist_data处理异常", exc_info=True)
        if not _data:
            logging.error(f"stock_hist_data初始化完成但数据为空：{len(stocks)}只股票全部获取失败")
            self.data = None
        else:
            logging.info(f"stock_hist_data初始化完成：成功获取{len(_data)}/{len(stocks)}只股票的历史数据")
            self.data = _data

    def get_data(self):
        return self.data

    @classmethod
    def release(cls):
        """释放单例实例，回收内存（可释放数百MB历史数据）"""
        from quantia.lib.singleton_type import singleton_type
        with singleton_type.single_lock:
            if hasattr(cls, '_instance'):
                del cls._instance

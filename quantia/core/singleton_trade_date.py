#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import datetime
import logging
import threading
import quantia.core.stockfetch as stf
from quantia.lib.singleton_type import singleton_type

__author__ = 'Quantia'
__date__ = '2026/02/14'


# 读取股票交易日历数据
# 单例模式：进程内只创建一次。为防止 Web 服务器跨午夜运行导致交易日历过期，
# get_data() 每次调用会检查是否跨日，跨日时自动刷新。
class stock_trade_date(metaclass=singleton_type):
    def __init__(self):
        self.data = None
        self._loaded_date = None  # 记录数据加载时的日期
        self._refresh_lock = threading.Lock()  # 防止多线程同时刷新
        self._refresh()

    def _refresh(self):
        try:
            new_data = stf.fetch_stocks_trade_date()
            if new_data is not None and len(new_data) > 30:
                self.data = new_data
                self._loaded_date = datetime.date.today()
            else:
                # 返回数据异常（空或太少），保留旧数据比无数据好
                logging.warning("stock_trade_date: 获取交易日历返回结果异常(None或太少)，保留已有数据")
        except Exception as e:
            # 保留旧数据 — 过时的交易日历远比无数据好
            logging.error(f"singleton.stock_trade_date刷新失败，保留已有数据", exc_info=True)

    def get_data(self):
        # 跨日检测：Web 服务器可能运行数天不重启，
        # 若当前日期与加载日期不同，重新获取交易日历
        today = datetime.date.today()
        need_refresh = False
        if self._loaded_date is None and self.data is None:
            # 初始加载失败，允许重试
            need_refresh = True
        elif self._loaded_date is not None and today != self._loaded_date:
            need_refresh = True
        if need_refresh:
            # 多线程保护：避免多线程同时触发刷新
            with self._refresh_lock:
                # 双重检查：进入锁后再次确认是否仍需刷新
                if self.data is None or (self._loaded_date is not None and today != self._loaded_date):
                    if self._loaded_date is not None:
                        logging.info(f"stock_trade_date: 检测到跨日({self._loaded_date} → {today})，刷新交易日历")
                    else:
                        logging.info("stock_trade_date: 初次加载失败，重试刷新交易日历")
                    self._refresh()
        return self.data

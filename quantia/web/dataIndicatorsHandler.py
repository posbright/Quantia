#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from abc import ABC
from tornado import gen
import logging
import datetime
import quantia.core.stockfetch as stf
import quantia.core.kline.visualization as vis
import quantia.web.base as webBase

__author__ = 'Quantia'
__date__ = '2026/02/14'


# 获得页面数据。
class GetDataIndicatorsHandler(webBase.BaseHandler, ABC):
    @gen.coroutine
    def get(self):
        code = self.get_argument("code", default=None, strip=False)
        date = self.get_argument("date", default=None, strip=False)
        name = self.get_argument("name", default=None, strip=False)
        strategy = self.get_argument("strategy", default='', strip=True)
        comp_list = []
        try:
            if code is not None:
                req_date = date or datetime.datetime.now().strftime('%Y-%m-%d')
                # 指数页必须读取指数缓存，不能回退到同代码股票K线（如 000004）。
                if 'index' in (strategy or '').lower():
                    stock = stf.read_index_hist_from_cache(code)
                    if stock is None or stock.empty:
                        # 指数缓存缺失时，按需补当前指数缓存后重试。
                        end_ymd = datetime.datetime.now().strftime('%Y%m%d')
                        start_ymd = (datetime.datetime.now() - datetime.timedelta(
                            days=stf.HIST_DATA_DEFAULT_YEARS * 365)).strftime('%Y%m%d')
                        stf.index_hist_cache_incremental(code, start_ymd, end_ymd)
                        stock = stf.read_index_hist_from_cache(code)
                else:
                    # 股票/ETF：仅从股票缓存读取
                    stock = stf.read_hist_from_cache((req_date, code))

                if stock is not None:
                    pk = vis.get_plot_kline(code, stock, date, name)
                    if pk is not None:
                        comp_list.append(pk)
                    else:
                        logging.warning(f"指标页面：{code} K线图生成失败")
                else:
                    logging.warning(f"指标页面：{code} 缓存无数据（strategy={strategy}），请确认数据采集任务已运行")
        except Exception as e:
            logging.error(f"dataIndicatorsHandler.GetDataIndicatorsHandler处理异常", exc_info=True)

        self.render("stock_indicators.html", comp_list=comp_list,
                    leftMenu=webBase.GetLeftMenu(self.request.uri))


# 关注股票。
class SaveCollectHandler(webBase.BaseHandler, ABC):
    @gen.coroutine
    def get(self):
        import datetime
        import quantia.core.tablestructure as tbs
        code = self.get_argument("code", default=None, strip=False)
        otype = self.get_argument("otype", default=None, strip=False)
        try:
            table_name = tbs.TABLE_CN_STOCK_ATTENTION['name']
            if otype == '1':
                sql = f"DELETE FROM `{table_name}` WHERE `code` = %s"
                self.db.execute(sql, code)
            else:
                sql = f"INSERT INTO `{table_name}`(`datetime`, `code`) VALUE(%s, %s)"
                self.db.execute(sql, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"), code)
        except Exception as e:
            logging.warning(f"SaveCollectHandler处理异常: {e}")
        self.write("{\"data\":[{}]}")

#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""
Date: 2026/1/30
Desc: 新浪财经-个股资金流向数据
作为东方财富API的备选数据源
"""
import time
import random
import logging
import requests
import pandas as pd
from io import StringIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from quantia.core.singleton_proxy import proxys

__author__ = 'Quantia'
__date__ = '2026/02/14'


def stock_individual_fund_flow_rank_sina(indicator: str = "5日") -> pd.DataFrame:
    """
    新浪财经-资金流向排名
    http://vip.stock.finance.sina.com.cn/moneyflow/
    :param indicator: choice of {"今日", "3日", "5日", "10日"}
    :type indicator: str
    :return: 指定 indicator 资金流向排行
    :rtype: pandas.DataFrame

    注意: 新浪个股资金流向接口只返回"今日"数据(不区分3日/5日/10日)
    且不提供超大单/大单/中单/小单的分类明细，这些字段用0填充
    """
    try:
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_ssggzj"
        params = {
            "page": 1,
            "num": 5000,
            "sort": "netamount",
            "asc": 0,
        }
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'http://vip.stock.finance.sina.com.cn/',
        }

        proxy_pool = proxys()
        current_proxy = proxy_pool.get_proxies()
        proxy_url = current_proxy.get("http") if current_proxy else None
        try:
            response = requests.get(url, params=params, headers=headers, proxies=current_proxy, timeout=30)
            proxy_pool.report_success(proxy_url)
        except Exception as e:
            proxy_pool.report_failure(proxy_url)
            raise
        if response.status_code != 200:
            return pd.DataFrame()

        text = response.text
        if not text or text == 'null':
            return pd.DataFrame()

        import json
        data = json.loads(text)

        if not data:
            return pd.DataFrame()

        stocks = []
        for item in data:
            try:
                symbol = item.get('symbol', '')
                # 去掉sh/sz前缀
                code = symbol[2:] if len(symbol) > 2 else symbol
                stock = {
                    '代码': code,
                    '名称': item.get('name', ''),
                    '最新价': _safe_float(item.get('trade', 0)),
                    '涨跌幅': _safe_float(item.get('changeratio', 0)) * 100,
                    '主力净流入': _safe_float(item.get('netamount', 0)),
                    '主力净流入占比': _safe_float(item.get('ratioamount', 0)) * 100,
                    '超大单净流入': 0,
                    '超大单净流入占比': 0,
                    '大单净流入': 0,
                    '大单净流入占比': 0,
                    '中单净流入': 0,
                    '中单净流入占比': 0,
                    '小单净流入': 0,
                    '小单净流入占比': 0,
                }
                stocks.append(stock)
            except Exception:
                continue

        if not stocks:
            return pd.DataFrame()

        temp_df = pd.DataFrame(stocks)
        return temp_df

    except Exception as e:
        logging.warning(f"新浪个股资金流向获取失败: {e}")
        return pd.DataFrame()


def _safe_float(value):
    """安全转换为浮点数"""
    try:
        if value is None or value == '' or value == '-':
            return 0.0
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _safe_int(value):
    """安全转换为整数"""
    try:
        if value is None or value == '' or value == '-':
            return 0
        return int(float(value))
    except (ValueError, TypeError):
        return 0


def stock_sector_fund_flow_rank_sina(
    indicator: str = "今日", sector_type: str = "行业资金流"
) -> pd.DataFrame:
    """
    新浪财经-板块资金流向排名（行业/概念）
    http://vip.stock.finance.sina.com.cn/moneyflow/

    作为东方财富 stock_sector_fund_flow_rank 的备选数据源。

    注意：新浪只返回"今日"数据（不区分5日/10日），
    且不提供超大单/大单/中单/小单分类明细。

    :param indicator: choice of {"今日", "5日", "10日"}（实际都返回今日数据）
    :param sector_type: choice of {"行业资金流", "概念资金流"}
    :return: 板块资金流向数据
    """
    sector_type_map = {"行业资金流": 1, "概念资金流": 2}
    fenlei = sector_type_map.get(sector_type, 1)

    try:
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_bk"
        params = {
            "page": 1,
            "num": 500,
            "sort": "netamount",
            "asc": 0,
            "fenlei": fenlei,
        }
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'http://vip.stock.finance.sina.com.cn/',
        }

        proxy_pool = proxys()
        current_proxy = proxy_pool.get_proxies()
        proxy_url = current_proxy.get("http") if current_proxy else None
        try:
            response = requests.get(url, params=params, headers=headers, proxies=current_proxy, timeout=30)
            proxy_pool.report_success(proxy_url)
        except Exception as e:
            proxy_pool.report_failure(proxy_url)
            raise
        if response.status_code != 200:
            return pd.DataFrame()

        text = response.text
        if not text or text == 'null':
            return pd.DataFrame()

        import json
        data = json.loads(text)

        if not data:
            return pd.DataFrame()

        rows = []
        for item in data:
            try:
                # 新浪返回的 ts_name 是主力净流入最大股
                row = {
                    '名称': item.get('name', ''),
                    '涨跌幅': _safe_float(item.get('avg_changeratio', 0)) * 100,
                    '主力净流入-净额': _safe_float(item.get('netamount', 0)),
                    '主力净流入-净占比': _safe_float(item.get('ratioamount', 0)) * 100,
                    '超大单净流入-净额': 0,
                    '超大单净流入-净占比': 0,
                    '大单净流入-净额': 0,
                    '大单净流入-净占比': 0,
                    '中单净流入-净额': 0,
                    '中单净流入-净占比': 0,
                    '小单净流入-净额': 0,
                    '小单净流入-净占比': 0,
                    '主力净流入最大股': item.get('ts_name', ''),
                }
                rows.append(row)
            except Exception:
                continue

        if not rows:
            return pd.DataFrame()

        return pd.DataFrame(rows)

    except Exception as e:
        logging.warning(f"新浪板块资金流向获取失败: {e}")
        return pd.DataFrame()

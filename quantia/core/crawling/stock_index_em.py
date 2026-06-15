#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""
Date: 2025/07/15
Desc: 东方财富-指数行情（实时 + 历史K线）
https://quote.eastmoney.com/center/gridlist.html#index_sh
https://quote.eastmoney.com/center/gridlist.html#index_sz
"""
import random
import time
import math
import logging
import pandas as pd
from quantia.core.eastmoney_fetcher import eastmoney_fetcher
import quantia.lib.envconfig as _cfg

__author__ = 'Quantia'
__date__ = '2025/07/15'

# 指数K线API内部延迟（与股票爬虫延迟开关共用 QUANTIA_CRAWL_DELAY_ENABLED）
_CRAWL_DELAY_ENABLED = _cfg.get_bool('QUANTIA_CRAWL_DELAY_ENABLED', True)
_CRAWL_DELAY_INDEX_MIN = _cfg.get_float('QUANTIA_CRAWL_DELAY_INDEX_MIN', 0.2)
_CRAWL_DELAY_INDEX_MAX = _cfg.get_float('QUANTIA_CRAWL_DELAY_INDEX_MAX', 0.5)

# 创建全局实例，供所有函数使用
fetcher = eastmoney_fetcher()

# 主要上证/中证指数代码集合（以 000 开头但属上海交易所）
# 用于正确判断 market_id
_SH_INDEX_CODES = {
    '000001', '000002', '000003', '000010', '000015', '000016',
    '000300', '000688', '000852', '000905', '000906', '000985',
    '000986', '000903', '000904', '000991', '000992',
}


def stock_index_spot_em() -> pd.DataFrame:
    """
    东方财富-指数实时行情（沪深两市全部指数）
    https://quote.eastmoney.com/center/gridlist.html#index_sh
    https://quote.eastmoney.com/center/gridlist.html#index_sz

    :return: 指数实时行情 DataFrame
    :rtype: pandas.DataFrame
    """
    url = "http://push2.eastmoney.com/api/qt/clist/get"
    page_size = 50
    page_current = 1
    # fs: "m:1+s:2" 上证指数, "m:0+t:5" 深证指数
    params = {
        "pn": page_current,
        "pz": page_size,
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "wbp2u": "|0|0|0|web",
        "fid": "f12",
        "fs": "m:1 s:2,m:0 t:5",
        "fields": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f22,f11,f62,f128,f136,f115,f152",
        "_": "1672806290972",
    }
    r = fetcher.make_request(url, params=params)
    data_json = r.json()

    data = (data_json.get("data") or {}).get("diff")
    if not data:
        return pd.DataFrame()

    data_count = data_json["data"]["total"]
    page_count = math.ceil(data_count / page_size)
    while page_count > 1:
        time.sleep(random.uniform(2, 3))
        page_current += 1
        params["pn"] = page_current
        r = fetcher.make_request(url, params=params)
        data_json = r.json()
        _data = (data_json.get("data") or {}).get("diff")
        if _data:
            data.extend(_data)
        page_count -= 1

    temp_df = pd.DataFrame(data)
    temp_df.rename(
        columns={
            "f12": "代码",
            "f14": "名称",
            "f2": "最新价",
            "f3": "涨跌幅",
            "f4": "涨跌额",
            "f5": "成交量",
            "f6": "成交额",
            "f17": "开盘价",
            "f15": "最高价",
            "f16": "最低价",
            "f18": "昨收",
            "f8": "换手率",
            "f21": "流通市值",
            "f20": "总市值",
        },
        inplace=True,
    )
    temp_df = temp_df[
        [
            "代码",
            "名称",
            "最新价",
            "涨跌幅",
            "涨跌额",
            "成交量",
            "成交额",
            "开盘价",
            "最高价",
            "最低价",
            "昨收",
            "换手率",
            "总市值",
            "流通市值",
        ]
    ]
    for col in ["最新价", "涨跌幅", "涨跌额", "成交量", "成交额",
                "开盘价", "最高价", "最低价", "昨收", "换手率",
                "流通市值", "总市值"]:
        temp_df[col] = pd.to_numeric(temp_df[col], errors="coerce")
    # 防御：过滤异常长度的代码（正常指数代码 ≤ 12 字符）
    temp_df["代码"] = temp_df["代码"].astype(str).str.strip()
    temp_df = temp_df[temp_df["代码"].str.len() <= 12].reset_index(drop=True)
    return temp_df


def _get_index_market_id(code: str) -> int:
    """
    获取指数代码对应的东方财富市场ID

    000xxx 系列（上证/中证指数）→ 1（上交所）
    399xxx 系列（深证指数）→ 0（深交所）
    """
    if code.startswith('399'):
        return 0  # 深交所
    else:
        return 1  # 上交所（000xxx 系列默认为上证/中证指数）


def stock_index_hist_em(
    symbol: str = "000300",
    period: str = "daily",
    start_date: str = "19700101",
    end_date: str = "20500101",
) -> pd.DataFrame:
    """
    东方财富-指数历史 K 线数据

    :param symbol: 指数代码（如 '000300' 沪深300, '399001' 深证成指）
    :param period: K 线周期 {'daily', 'weekly', 'monthly'}
    :param start_date: 开始日期 YYYYMMDD
    :param end_date: 结束日期 YYYYMMDD
    :return: 指数历史 K 线 DataFrame
    :rtype: pandas.DataFrame
    """
    market_id = _get_index_market_id(symbol)
    period_dict = {"daily": "101", "weekly": "102", "monthly": "103"}
    url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "klt": period_dict.get(period, "101"),
        "fqt": "0",  # 指数不需要复权
        "secid": f"{market_id}.{symbol}",
        "beg": start_date,
        "end": end_date,
        "_": "1623766962675",
    }
    if _CRAWL_DELAY_ENABLED:
        time.sleep(random.uniform(_CRAWL_DELAY_INDEX_MIN, _CRAWL_DELAY_INDEX_MAX))
    r = fetcher.make_request(url, params=params)
    # 空响应体守卫：东方财富在软限流时常返回 HTTP 200 + 空 body，
    # 直接 r.json() 会抛 "Expecting value: line 1 column 1 (char 0)"。
    # 这里显式识别为「无数据」返回空 DataFrame，让上层多源降级正常切换。
    if not (r.text and r.text.strip()):
        logging.warning(f"指数 {symbol} 东方财富返回空响应体（疑似限流）")
        return pd.DataFrame()
    try:
        data_json = r.json()
    except ValueError as e:
        logging.warning(f"指数 {symbol} 东方财富响应非 JSON（疑似限流）：{e}")
        return pd.DataFrame()
    if not (data_json.get("data") and data_json["data"].get("klines")):
        return pd.DataFrame()

    temp_df = pd.DataFrame(
        [item.split(",") for item in data_json["data"]["klines"]]
    )
    temp_df.columns = [
        "日期",
        "开盘",
        "收盘",
        "最高",
        "最低",
        "成交量",
        "成交额",
        "振幅",
        "涨跌幅",
        "涨跌额",
        "换手率",
    ]
    temp_df.index = pd.to_datetime(temp_df["日期"])
    temp_df.reset_index(inplace=True, drop=True)

    for col in ["开盘", "收盘", "最高", "最低", "成交量", "成交额",
                "振幅", "涨跌幅", "涨跌额", "换手率"]:
        temp_df[col] = pd.to_numeric(temp_df[col], errors="coerce")

    return temp_df

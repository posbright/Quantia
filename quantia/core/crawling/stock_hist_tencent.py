#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""
Date: 2026/2/10
Desc: 腾讯财经-A股历史K线数据
作为东方财富API的备选数据源

API说明：
    URL: https://web.ifzq.gtimg.cn/appstock/app/fqkline/get
    参数:
        param: 股票代码（如 sz000001）
        _var: 返回变量名
        fqtype: 复权类型（qfq前复权, hfq后复权, 空不复权）
        p: 起始日期
        e: 结束日期
        n: 请求条数（最多300条/请求）
    返回格式:
        {data: {szXXXXXX: {qfqday: [[日期,开盘,收盘,最高,最低,成交量], ...]}}}
"""
import time
import random
import requests
import pandas as pd
import datetime
import logging
import quantia.lib.envconfig as _cfg

__author__ = 'Quantia'
__date__ = '2026/02/14'

# 爬虫内部延迟开关（当调度层已有限流时可关闭，避免双重延迟）
_CRAWL_DELAY_ENABLED = _cfg.get_bool('QUANTIA_CRAWL_DELAY_ENABLED', True)
_CRAWL_DELAY_TC_SHORT_MIN = _cfg.get_float('QUANTIA_CRAWL_DELAY_TC_SHORT_MIN', 0.3)
_CRAWL_DELAY_TC_SHORT_MAX = _cfg.get_float('QUANTIA_CRAWL_DELAY_TC_SHORT_MAX', 0.8)
_CRAWL_DELAY_TC_LONG_MIN = _cfg.get_float('QUANTIA_CRAWL_DELAY_TC_LONG_MIN', 0.5)
_CRAWL_DELAY_TC_LONG_MAX = _cfg.get_float('QUANTIA_CRAWL_DELAY_TC_LONG_MAX', 1.5)

# 请求配置
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://stockapp.finance.qq.com/',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
}

# 腾讯API单次最大返回条数
MAX_RECORDS_PER_REQUEST = 300


def _get_market_prefix(code):
    """获取市场前缀（支持股票和ETF）"""
    code = str(code)
    if code.startswith(('4', '8', '920')):
        return 'bj'  # 北交所
    if code.startswith(('6', '5', '9')):
        return 'sh'  # 上交所（含5开头的沪市ETF: 510xxx, 511xxx, 512xxx等）
    else:
        return 'sz'  # 深交所（含1开头的深市ETF: 159xxx）


def _safe_float(value):
    """安全转换为浮点数"""
    try:
        if value is None or value == '' or value == '-':
            return 0.0
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _convert_fq_type(adjust):
    """
    转换复权类型参数
    腾讯API: qfq=前复权, hfq=后复权, 空=不复权
    """
    if adjust == 'qfq':
        return 'qfq'
    elif adjust == 'hfq':
        return 'hfq'
    else:
        return ''


def _get_kline_key(fq_type):
    """根据复权类型获取返回数据的key名"""
    if fq_type == 'qfq':
        return 'qfqday'
    elif fq_type == 'hfq':
        return 'hfqday'
    else:
        return 'day'


def _fetch_one_batch(full_code, fq_type, kline_key, start_date, end_date, datalen):
    """
    获取单批次K线数据

    返回：
        list: K线数据列表 [[日期,开盘,收盘,最高,最低,成交量], ...]
        None: 获取失败
    """
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    params = {
        "param": f"{full_code},day,{start_date},{end_date},{datalen},{fq_type}",
        "_var": f"kline_day{fq_type}",
    }

    try:
        # timeout=(连接超时, 读取超时)：防止SSL握手阶段无限等待
        response = requests.get(url, params=params, headers=HEADERS, timeout=(10, 30))
        response.raise_for_status()

        text = response.text
        # 返回格式: kline_dayqfq={...}  需要提取JSON部分
        json_start = text.find('{')
        if json_start < 0:
            return None

        import json
        data = json.loads(text[json_start:])

        if data.get('code') != 0:
            return None

        stock_data = data.get('data', {}).get(full_code, {})

        # 尝试按复权类型key获取，如果没有则尝试 day
        kline_data = stock_data.get(kline_key)
        if not kline_data and kline_key != 'day':
            kline_data = stock_data.get('day')

        return kline_data if kline_data else None

    except Exception as e:
        logging.warning(f"腾讯K线数据获取失败: {full_code} - {e}")
        return None


def stock_zh_a_hist_tencent(
    symbol: str,
    period: str = "daily",
    start_date: str = "19700101",
    end_date: str = "22220101",
    adjust: str = "",
) -> pd.DataFrame:
    """
    从腾讯财经获取A股历史行情数据

    参数：
        symbol: 股票代码，如 "000001"
        period: K线周期，目前仅支持 "daily"
        start_date: 起始日期，格式 YYYYMMDD
        end_date: 结束日期，格式 YYYYMMDD
        adjust: 复权类型，"qfq"前复权，"hfq"后复权，""不复权

    返回：
        DataFrame: 包含历史行情数据的DataFrame，列名与 CN_STOCK_HIST_DATA 一致
                   [date, open, close, high, low, volume, amount, amplitude, quote_change, ups_downs, turnover]
    """
    try:
        market_prefix = _get_market_prefix(symbol)
        full_code = f"{market_prefix}{symbol}"
        fq_type = _convert_fq_type(adjust)
        kline_key = _get_kline_key(fq_type)

        # 格式化日期
        start_str = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
        end_str = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"

        # 腾讯API单次最多返回300条，需要分批获取
        # 计算大概需要的交易日数
        start_dt = datetime.datetime.strptime(start_date, "%Y%m%d")
        end_dt = datetime.datetime.strptime(end_date, "%Y%m%d")
        days_diff = (end_dt - start_dt).days
        estimated_trading_days = int(days_diff * 0.7) + 50

        all_records = []

        if estimated_trading_days <= MAX_RECORDS_PER_REQUEST:
            # 单次请求即可
            if _CRAWL_DELAY_ENABLED:
                time.sleep(random.uniform(_CRAWL_DELAY_TC_SHORT_MIN, _CRAWL_DELAY_TC_SHORT_MAX))
            records = _fetch_one_batch(full_code, fq_type, kline_key, start_str, end_str, MAX_RECORDS_PER_REQUEST)
            if records:
                all_records.extend(records)
        else:
            # 需要分批获取（按时间段切分）
            batch_days = int(MAX_RECORDS_PER_REQUEST / 0.7)  # 约428个自然日
            current_start = start_dt
            batch_count = 0

            while current_start < end_dt:
                current_end = min(current_start + datetime.timedelta(days=batch_days), end_dt)
                batch_start_str = current_start.strftime("%Y-%m-%d")
                batch_end_str = current_end.strftime("%Y-%m-%d")

                if _CRAWL_DELAY_ENABLED:
                    time.sleep(random.uniform(_CRAWL_DELAY_TC_LONG_MIN, _CRAWL_DELAY_TC_LONG_MAX))
                records = _fetch_one_batch(full_code, fq_type, kline_key, batch_start_str, batch_end_str, MAX_RECORDS_PER_REQUEST)
                if records:
                    all_records.extend(records)

                current_start = current_end + datetime.timedelta(days=1)
                batch_count += 1

                # 安全限制：最多50批（约35年数据）
                if batch_count >= 50:
                    break

        if not all_records:
            return None

        # 转换为DataFrame
        # 腾讯返回格式: [日期, 开盘, 收盘, 最高, 最低, 成交量]
        # 注意：除权除息日的行会额外返回第7列（分红信息字典），需要截取前6列
        # 例如: ['2025-05-30', '15.300', '14.890', '15.300', '14.860', '110448.000',
        #        {'nd': '2024', 'fh_sh': '1.2', 'djr': '2025-05-29', ...}]
        cleaned_records = [row[:6] for row in all_records]
        df = pd.DataFrame(cleaned_records, columns=['date', 'open', 'close', 'high', 'low', 'volume'])

        # 确保数值类型
        for col in ['open', 'close', 'high', 'low', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        # 去重（分批获取可能有重叠）
        df = df.drop_duplicates(subset=['date'], keep='last')

        # 计算缺失的列
        # 腾讯API返回的volume单位是 手（已实测验证：000001返回431041，对应431041手=4310万股）
        # 成交额(元) = 成交量(手) × 100(股/手) × 平均价格(元/股)
        df['amount'] = df['volume'] * 100 * (df['open'] + df['close']) / 2

        # 振幅 = (最高 - 最低) / 昨收 * 100
        df['amplitude'] = ((df['high'] - df['low']) / df['close'].shift(1) * 100).round(4)

        # 涨跌幅 = (收盘 - 昨收) / 昨收 * 100
        df['quote_change'] = ((df['close'] - df['close'].shift(1)) / df['close'].shift(1) * 100).round(4)

        # 涨跌额 = 收盘 - 昨收
        df['ups_downs'] = (df['close'] - df['close'].shift(1)).round(4)

        # 换手率（需要流通股数据，此处置0）
        df['turnover'] = 0.0

        # 处理日期过滤
        df['date'] = pd.to_datetime(df['date'])
        start_filter = pd.to_datetime(start_date)
        end_filter = pd.to_datetime(end_date)
        df = df[(df['date'] >= start_filter) & (df['date'] <= end_filter)]

        # 转换日期格式
        df['date'] = df['date'].dt.strftime('%Y-%m-%d')

        # 按标准列顺序排列（与 CN_STOCK_HIST_DATA 一致）
        standard_columns = ['date', 'open', 'close', 'high', 'low', 'volume', 'amount',
                            'amplitude', 'quote_change', 'ups_downs', 'turnover']
        for col in standard_columns:
            if col not in df.columns:
                df[col] = 0.0

        df = df[standard_columns].copy()
        df = df.sort_values(by='date').reset_index(drop=True)

        # 替换inf值并填充NaN（shift计算的第一行会产生NaN）
        import numpy as np
        df = df.replace([np.inf, -np.inf], np.nan)
        df = df.fillna(0)

        if len(df) == 0:
            return None

        return df

    except Exception as e:
        logging.error(f"stock_hist_tencent.stock_zh_a_hist_tencent处理异常：{symbol} -", exc_info=True)
    return None

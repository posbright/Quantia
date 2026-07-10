#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""
Date: 2026/1/30
Desc: 新浪财经-A股历史K线数据
作为东方财富API的备选数据源
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
_CRAWL_DELAY_SINA_MIN = _cfg.get_float('QUANTIA_CRAWL_DELAY_SINA_MIN', 3.0)
_CRAWL_DELAY_SINA_MAX = _cfg.get_float('QUANTIA_CRAWL_DELAY_SINA_MAX', 6.0)

# 请求配置
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://finance.sina.com.cn/',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
}

def _get_market_prefix(code):
    """获取市场前缀（支持股票和ETF）"""
    code = str(code)
    if code.startswith(('4', '8', '920')):
        return 'bj'  # 北交所
    if code.startswith(('6', '5', '9')):
        return 'sh'  # 上交所（含5开头的沪市ETF: 510xxx, 511xxx, 512xxx等）
    return 'sz'  # 深交所（含1开头的深市ETF: 159xxx）


def _safe_float(value):
    """安全转换为浮点数"""
    try:
        if value is None or value == '' or value == '-':
            return 0.0
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _convert_adjust_type(adjust):
    """转换复权类型参数"""
    # 新浪财经的复权参数
    # 后复权: hfq
    # 前复权: qfq
    # 不复权: 空字符串
    if adjust == 'hfq':
        return 'hfq'
    elif adjust == 'qfq':
        return 'qfq'
    else:
        return ''


def stock_zh_a_hist_sina(
    symbol: str,
    period: str = "daily",
    start_date: str = "19700101",
    end_date: str = "22220101",
    adjust: str = "",
) -> pd.DataFrame:
    """
    从新浪财经获取A股历史行情数据

    参数：
        symbol: 股票代码，如 "000001"
        period: K线周期，支持 "daily", "weekly", "monthly"
        start_date: 起始日期，格式 YYYYMMDD
        end_date: 结束日期，格式 YYYYMMDD
        adjust: 复权类型，"qfq"前复权，"hfq"后复权，""不复权

    返回：
        DataFrame: 包含历史行情数据的DataFrame
    """
    try:
        market_prefix = _get_market_prefix(symbol)
        full_code = f"{market_prefix}{symbol}"

        # 新浪财经历史K线API
        # URL格式: https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sh600000&scale=240&ma=no&datalen=1000
        # scale: 5,15,30,60分钟线; 240日线; 1680周线

        if period == "daily":
            scale = 240
        elif period == "weekly":
            scale = 1680
        elif period == "monthly":
            scale = 7200  # 月线
        else:
            scale = 240

        # 计算需要获取的数据条数
        start_dt = datetime.datetime.strptime(start_date, "%Y%m%d")
        end_dt = datetime.datetime.strptime(end_date, "%Y%m%d")
        days_diff = (end_dt - start_dt).days

        # 估算需要的K线数量（考虑节假日，实际交易日约为总天数的70%）
        if period == "daily":
            datalen = max(int(days_diff * 0.7) + 100, 1000)
        elif period == "weekly":
            datalen = max(int(days_diff / 7) + 50, 500)
        else:
            datalen = max(int(days_diff / 30) + 20, 200)

        # 限制最大数据量
        datalen = min(datalen, 5000)

        url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        params = {
            "symbol": full_code,
            "scale": scale,
            "ma": "no",
            "datalen": datalen
        }

        # 添加随机延迟（防止456限流），可通过 QUANTIA_CRAWL_DELAY_ENABLED=0 关闭
        if _CRAWL_DELAY_ENABLED:
            time.sleep(random.uniform(_CRAWL_DELAY_SINA_MIN, _CRAWL_DELAY_SINA_MAX))

        response = requests.get(url, params=params, headers=HEADERS, timeout=30)
        response.raise_for_status()

        # 新浪返回的是JSON数据
        try:
            data = response.json()
        except (ValueError, Exception):
            # 尝试处理JS变量格式
            text = response.text
            if text.startswith('['):
                import json
                data = json.loads(text)
            else:
                logging.warning(f"新浪历史数据格式解析失败: {symbol}")
                return None

        if not data or len(data) == 0:
            return None

        # 转换为DataFrame
        df = pd.DataFrame(data)

        # 标准化列名
        # 新浪返回格式: {day, open, high, low, close, volume}
        if 'day' in df.columns:
            df = df.rename(columns={
                'day': 'date',
                'open': 'open',
                'high': 'high',
                'low': 'low',
                'close': 'close',
                'volume': 'volume'
            })

        # 确保数值类型
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # 新浪API返回的volume单位是 股（已实测验证：000001返回43104098，对应431041手）
        # 1. 先用原始volume（股）计算成交额（元）：amount = 股数 × 均价
        # 2. 再将volume从 股 转换为 手（除以100），与东方财富/腾讯保持一致
        if 'amount' not in df.columns:
            # 估算成交额(元) = 成交量(股) × 平均价格(元/股)
            df['amount'] = df['volume'] * (df['open'] + df['close']) / 2

        # 将volume从 股 转为 手（与东方财富/腾讯统一，fetch_stock_hist 会再 *100 转回股）
        df['volume'] = df['volume'] / 100

        if 'amplitude' not in df.columns:
            # 计算振幅
            df['amplitude'] = ((df['high'] - df['low']) / df['close'].shift(1) * 100).round(4)

        if 'quote_change' not in df.columns:
            # 计算涨跌幅
            df['quote_change'] = ((df['close'] - df['close'].shift(1)) / df['close'].shift(1) * 100).round(4)

        if 'ups_downs' not in df.columns:
            # 计算涨跌额
            df['ups_downs'] = (df['close'] - df['close'].shift(1)).round(4)

        if 'turnover' not in df.columns:
            # 换手率需要流通股数据，这里设为0
            df['turnover'] = 0.0

        # 处理日期格式
        df['date'] = pd.to_datetime(df['date'])

        # 过滤日期范围
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        df = df[(df['date'] >= start_dt) & (df['date'] <= end_dt)]

        # 转换日期格式为字符串
        df['date'] = df['date'].dt.strftime('%Y-%m-%d')

        # 按照标准顺序排列列（与 CN_STOCK_HIST_DATA 一致）
        standard_columns = ['date', 'open', 'close', 'high', 'low', 'volume', 'amount', 'amplitude', 'quote_change', 'ups_downs', 'turnover']

        # 确保所有标准列都存在
        for col in standard_columns:
            if col not in df.columns:
                df[col] = 0.0

        df = df[standard_columns].copy()

        # 排序并重置索引
        df = df.sort_values(by='date').reset_index(drop=True)

        # 替换inf值并填充NaN
        import numpy as np
        df = df.replace([np.inf, -np.inf], np.nan)
        df = df.fillna(0)

        return df

    except Exception as e:
        logging.warning(f"新浪财经获取历史数据失败: {symbol} - {e}")
        return None


def stock_zh_a_hist_sina_v2(
    symbol: str,
    period: str = "daily",
    start_date: str = "19700101",
    end_date: str = "22220101",
    adjust: str = "",
) -> pd.DataFrame:
    """
    备选方案：使用新浪财经的另一个接口获取历史数据

    参数同 stock_zh_a_hist_sina
    """
    try:
        market_prefix = _get_market_prefix(symbol)

        # 使用新浪财经的财务接口获取历史数据
        # 格式：https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData?symbol=sh600000&scale=240&ma=no&datalen=1000

        if period == "daily":
            scale = 240
        elif period == "weekly":
            scale = 1680
        else:
            scale = 240

        # 计算数据量
        start_dt = datetime.datetime.strptime(start_date, "%Y%m%d")
        end_dt = datetime.datetime.strptime(end_date, "%Y%m%d")
        days_diff = (end_dt - start_dt).days
        datalen = min(max(int(days_diff * 0.7) + 100, 1000), 5000)

        url = f"https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
        params = {
            "symbol": f"{market_prefix}{symbol}",
            "scale": scale,
            "ma": "no",
            "datalen": datalen
        }

        # 添加随机延迟（防止456限流），可通过 QUANTIA_CRAWL_DELAY_ENABLED=0 关闭
        if _CRAWL_DELAY_ENABLED:
            time.sleep(random.uniform(_CRAWL_DELAY_SINA_MIN, _CRAWL_DELAY_SINA_MAX))

        response = requests.get(url, params=params, headers=HEADERS, timeout=30)
        response.raise_for_status()

        data = response.json()

        if not data or len(data) == 0:
            return None

        df = pd.DataFrame(data)

        # 处理与主函数相同
        if 'day' in df.columns:
            df = df.rename(columns={'day': 'date'})

        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # 新浪API返回的volume单位是 股，先用原始值计算成交额，再转换为 手
        if 'amount' not in df.columns:
            df['amount'] = df['volume'] * (df['open'] + df['close']) / 2

        # 将volume从 股 转为 手（与东方财富/腾讯统一）
        df['volume'] = df['volume'] / 100

        if 'amplitude' not in df.columns:
            df['amplitude'] = ((df['high'] - df['low']) / df['close'].shift(1) * 100).round(4)

        if 'quote_change' not in df.columns:
            df['quote_change'] = ((df['close'] - df['close'].shift(1)) / df['close'].shift(1) * 100).round(4)

        if 'ups_downs' not in df.columns:
            df['ups_downs'] = (df['close'] - df['close'].shift(1)).round(4)

        if 'turnover' not in df.columns:
            df['turnover'] = 0.0

        df['date'] = pd.to_datetime(df['date'])

        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        df = df[(df['date'] >= start_dt) & (df['date'] <= end_dt)]

        df['date'] = df['date'].dt.strftime('%Y-%m-%d')

        standard_columns = ['date', 'open', 'close', 'high', 'low', 'volume', 'amount', 'amplitude', 'quote_change', 'ups_downs', 'turnover']
        for col in standard_columns:
            if col not in df.columns:
                df[col] = 0.0

        df = df[standard_columns].copy()
        df = df.sort_values(by='date').reset_index(drop=True)
        df = df.fillna(0)

        return df

    except Exception as e:
        logging.warning(f"新浪财经备选接口获取历史数据失败: {symbol} - {e}")
        return None


if __name__ == "__main__":
    # 测试代码
    print("测试新浪财经历史K线数据获取...")

    # 测试获取平安银行历史数据
    df = stock_zh_a_hist_sina(
        symbol="000001",
        period="daily",
        start_date="20240101",
        end_date="20240130",
        adjust=""
    )

    if df is not None and len(df) > 0:
        print(f"成功获取 {len(df)} 条数据:")
        print(df.head(10))
    else:
        print("获取数据失败")

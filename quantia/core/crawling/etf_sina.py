#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""
Date: 2026/1/30
Desc: 新浪财经-ETF实时行情数据
作为东方财富API的备选数据源
"""
import time
import logging
import random
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
import quantia.lib.envconfig as _cfg

__author__ = 'Quantia'
__date__ = '2026/02/14'

_CRAWL_WORKERS = _cfg.get_int('QUANTIA_CRAWL_WORKERS', 5)


def _get_etf_codes():
    """获取ETF代码列表"""
    codes = []

    # 沪市ETF代码范围: 510xxx, 511xxx, 512xxx, 513xxx, 515xxx, 516xxx, 517xxx, 518xxx, 560xxx, 561xxx, 562xxx, 563xxx, 588xxx
    sh_prefixes = ['510', '511', '512', '513', '515', '516', '517', '518', '560', '561', '562', '563', '588']
    for prefix in sh_prefixes:
        for i in range(1000):
            codes.append(f'sh{prefix}{str(i).zfill(3)}')

    # 深市ETF代码范围: 159xxx
    for i in range(10000):
        codes.append(f'sz159{str(i).zfill(3)}')

    return codes


def _parse_sina_etf_data(text):
    """解析新浪财经返回的ETF数据"""
    etfs = []
    lines = text.strip().split('\n')

    for line in lines:
        if 'hq_str_' not in line or '="' not in line:
            continue

        try:
            # 数据格式: var hq_str_sh510050="50ETF,3.500,3.508,3.502,3.515,3.495,...";
            # 提取代码
            code_part = line.split('hq_str_')[1].split('=')[0]
            code = code_part[2:]  # 去掉sh或sz前缀

            # 提取数据
            data_part = line.split('="')[1].rstrip('";')
            if not data_part:
                continue

            parts = data_part.split(',')
            if len(parts) < 32:
                continue

            # 检查是否有有效价格
            price = parts[3]
            if not price or price == '0.00' or price == '':
                continue

            # 新浪数据字段说明:
            # 0:名称 1:今开 2:昨收 3:当前价 4:最高 5:最低 6:买一价 7:卖一价
            # 8:成交量(股) 9:成交额(元)

            name = parts[0]

            # 计算涨跌幅和涨跌额
            current_price = _safe_float(parts[3])
            pre_close = _safe_float(parts[2])
            ups_downs = round(current_price - pre_close, 4) if pre_close > 0 else 0
            change_rate = round((ups_downs / pre_close) * 100, 4) if pre_close > 0 else 0

            etf = {
                '代码': code,
                '名称': name,
                '最新价': current_price,
                '涨跌幅': change_rate,
                '涨跌额': ups_downs,
                '成交量': _safe_int(parts[8]),  # 股
                '成交额': _safe_float(parts[9]),  # 元
                '今开': _safe_float(parts[1]),
                '最高': _safe_float(parts[4]),
                '最低': _safe_float(parts[5]),
                '昨收': pre_close,
                '换手率': 0,  # 新浪不提供换手率
                '总市值': 0,  # 新浪不提供
                '流通市值': 0,  # 新浪不提供
            }
            etfs.append(etf)
        except Exception:
            continue

    return etfs


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


def _fetch_batch(codes_batch, timeout=30):
    """批量获取ETF数据"""
    url = f'http://hq.sinajs.cn/list={",".join(codes_batch)}'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://finance.sina.com.cn/',
    }
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code == 200:
            # 新浪返回的是GBK编码
            response.encoding = 'gbk'
            return _parse_sina_etf_data(response.text)
    except Exception:
        logging.debug(f"ETF新浪批量获取异常：{codes_batch[:3]}...", exc_info=True)
    return []


def fund_etf_spot_sina() -> pd.DataFrame:
    """
    新浪财经-ETF-实时行情
    https://finance.sina.com.cn/
    :return: ETF实时行情
    :rtype: pandas.DataFrame
    """
    all_codes = _get_etf_codes()
    all_etfs = []

    # 每批查询100个
    batch_size = 100
    batches = [all_codes[i:i + batch_size] for i in range(0, len(all_codes), batch_size)]

    # 使用多线程并发获取
    with ThreadPoolExecutor(max_workers=_CRAWL_WORKERS) as executor:
        futures = []
        for i, batch in enumerate(batches):
            if i > 0 and i % 10 == 0:
                time.sleep(random.uniform(0.5, 1))
            future = executor.submit(_fetch_batch, batch)
            futures.append(future)

        for future in as_completed(futures):
            try:
                etfs = future.result()
                all_etfs.extend(etfs)
            except Exception:
                continue

    if not all_etfs:
        return pd.DataFrame()

    temp_df = pd.DataFrame(all_etfs)

    # 按照东方财富的ETF列顺序排列
    columns_order = [
        "代码", "名称", "最新价", "涨跌幅", "涨跌额", "成交量", "成交额",
        "今开", "最高", "最低", "昨收", "换手率", "总市值", "流通市值"
    ]

    # 确保所有列都存在
    for col in columns_order:
        if col not in temp_df.columns:
            temp_df[col] = 0

    temp_df = temp_df[columns_order]

    # 类型转换
    numeric_columns = ["最新价", "涨跌幅", "涨跌额", "今开", "最高", "最低", "昨收", "换手率"]
    for col in numeric_columns:
        temp_df[col] = pd.to_numeric(temp_df[col], errors="coerce")

    int_columns = ["成交量", "成交额", "总市值", "流通市值"]
    for col in int_columns:
        temp_df[col] = pd.to_numeric(temp_df[col], errors="coerce").fillna(0).astype('int64')

    return temp_df

#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""
Date: 2026/1/30
Desc: 腾讯财经-ETF实时行情数据
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

    # 沪市ETF代码范围: 510xxx, 511xxx, 512xxx, 513xxx, 515xxx, 516xxx, 517xxx, 518xxx, 560xxx, 561xxx, 562xxx, 563xxx
    sh_prefixes = ['510', '511', '512', '513', '515', '516', '517', '518', '560', '561', '562', '563', '588']
    for prefix in sh_prefixes:
        for i in range(1000):
            codes.append(f'sh{prefix}{str(i).zfill(3)}')

    # 深市ETF代码范围: 159xxx
    for i in range(10000):
        codes.append(f'sz159{str(i).zfill(3)}')

    return codes


def _parse_tencent_etf_data(text):
    """解析腾讯财经返回的ETF数据"""
    etfs = []
    lines = text.strip().split(';')

    for line in lines:
        if '~' not in line or 'v_' not in line:
            continue

        try:
            parts = line.split('~')
            if len(parts) < 50:
                continue

            # 检查是否有有效价格
            price = parts[3]
            if not price or price == '0.00' or price == '':
                continue

            code = parts[2]
            name = parts[1]

            # ETF数据格式与股票类似
            etf = {
                '代码': code,
                '名称': name,
                '最新价': _safe_float(parts[3]),
                '涨跌幅': _safe_float(parts[32]),
                '涨跌额': _safe_float(parts[31]),
                '成交量': _safe_int(parts[36]) * 100 if parts[36] else 0,
                '成交额': _safe_float(parts[37]) * 10000 if parts[37] else 0,
                '今开': _safe_float(parts[5]),
                '最高': _safe_float(parts[33]) if len(parts) > 33 else _safe_float(parts[41]),
                '最低': _safe_float(parts[34]) if len(parts) > 34 else _safe_float(parts[42]),
                '昨收': _safe_float(parts[4]),
                '换手率': _safe_float(parts[38]),
                '总市值': _safe_float(parts[45]) * 10000 if len(parts) > 45 and parts[45] else 0,
                '流通市值': _safe_float(parts[44]) * 10000 if len(parts) > 44 and parts[44] else 0,
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
    url = f'http://qt.gtimg.cn/q={",".join(codes_batch)}'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://finance.qq.com/',
    }
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code == 200:
            response.encoding = 'gbk'
            return _parse_tencent_etf_data(response.text)
    except Exception:
        logging.debug(f"ETF腾讯批量获取异常：{codes_batch[:3]}...", exc_info=True)
    return []


def fund_etf_spot_tencent() -> pd.DataFrame:
    """
    腾讯财经-ETF-实时行情
    https://finance.qq.com/
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

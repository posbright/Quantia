#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""
Date: 2026/1/30
Desc: 新浪财经-A股实时行情数据
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


def _get_stock_codes():
    """获取所有A股代码列表"""
    codes = []

    # 沪市股票代码范围
    sh_prefixes = ['600', '601', '603', '605', '688']
    for prefix in sh_prefixes:
        for i in range(1000):
            codes.append(f'sh{prefix}{str(i).zfill(3)}')

    # 深市股票代码范围
    sz_prefixes = ['000', '001', '002', '003', '300', '301']
    for prefix in sz_prefixes:
        for i in range(1000):
            codes.append(f'sz{prefix}{str(i).zfill(3)}')

    return codes


def _parse_sina_data(text):
    """解析新浪财经返回的数据"""
    stocks = []
    lines = text.strip().split('\n')

    for line in lines:
        if 'hq_str_' not in line or '="' not in line:
            continue

        try:
            # 数据格式: var hq_str_sh600000="浦发银行,10.07,10.12,10.10,10.15,10.00,...";
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
            # 8:成交量(股) 9:成交额(元) 10-19:买一到买五价格和数量 20-29:卖一到卖五价格和数量
            # 30:日期 31:时间

            name = parts[0]

            # 计算涨跌幅和涨跌额
            current_price = _safe_float(parts[3])
            pre_close = _safe_float(parts[2])
            ups_downs = round(current_price - pre_close, 4) if pre_close > 0 else 0
            change_rate = round((ups_downs / pre_close) * 100, 4) if pre_close > 0 else 0

            # 计算振幅
            high = _safe_float(parts[4])
            low = _safe_float(parts[5])
            amplitude = round((high - low) / pre_close * 100, 4) if pre_close > 0 else 0

            stock = {
                '代码': code,
                '名称': name,
                '最新价': current_price,
                '涨跌幅': change_rate,
                '涨跌额': ups_downs,
                '成交量': _safe_int(parts[8]),  # 股
                '成交额': _safe_float(parts[9]),  # 元
                '振幅': amplitude,
                '换手率': 0,  # 新浪不提供换手率
                '量比': 0,  # 新浪不提供量比
                '今开': _safe_float(parts[1]),
                '最高': high,
                '最低': low,
                '昨收': pre_close,
                '涨速': 0,  # 新浪不提供
                '5分钟涨跌': 0,  # 新浪不提供
                '60日涨跌幅': 0,  # 新浪不提供
                '年初至今涨跌幅': 0,  # 新浪不提供
                '市盈率动': 0,  # 新浪不提供
                '市盈率TTM': 0,  # 新浪不提供
                '市盈率静': 0,  # 新浪不提供
                '市净率': 0,  # 新浪不提供
                '每股收益': 0,  # 新浪不提供
                '每股净资产': 0,  # 新浪不提供
                '每股公积金': 0,  # 新浪不提供
                '每股未分配利润': 0,  # 新浪不提供
                '加权净资产收益率': 0,  # 新浪不提供
                '毛利率': 0,  # 新浪不提供
                '资产负债率': 0,  # 新浪不提供
                '营业收入': 0,  # 新浪不提供
                '营业收入同比增长': 0,  # 新浪不提供
                '归属净利润': 0,  # 新浪不提供
                '归属净利润同比增长': 0,  # 新浪不提供
                '报告期': None,  # 新浪不提供
                '总股本': 0,  # 新浪不提供
                '已流通股份': 0,  # 新浪不提供
                '总市值': 0,  # 新浪不提供
                '流通市值': 0,  # 新浪不提供
                '所处行业': '',  # 新浪不提供
                '上市时间': None,  # 新浪不提供
            }
            stocks.append(stock)
        except Exception:
            continue

    return stocks


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
    """批量获取股票数据"""
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
            return _parse_sina_data(response.text)
    except Exception:
        logging.debug(f"股票新浪批量获取异常：{codes_batch[:3]}...", exc_info=True)
    return []


def stock_zh_a_spot_sina() -> pd.DataFrame:
    """
    新浪财经-沪深A股-实时行情
    https://finance.sina.com.cn/
    :return: 实时行情
    :rtype: pandas.DataFrame
    """
    all_codes = _get_stock_codes()
    all_stocks = []

    # 每批查询100个股票
    batch_size = 100
    batches = [all_codes[i:i + batch_size] for i in range(0, len(all_codes), batch_size)]

    # 使用多线程并发获取
    with ThreadPoolExecutor(max_workers=_CRAWL_WORKERS) as executor:
        futures = []
        for i, batch in enumerate(batches):
            # 添加延迟避免限流
            if i > 0 and i % 10 == 0:
                time.sleep(random.uniform(0.5, 1))
            future = executor.submit(_fetch_batch, batch)
            futures.append(future)

        for future in as_completed(futures):
            try:
                stocks = future.result()
                all_stocks.extend(stocks)
            except Exception:
                continue

    if not all_stocks:
        return pd.DataFrame()

    temp_df = pd.DataFrame(all_stocks)

    # 按照东方财富的列顺序排列
    columns_order = [
        "代码", "名称", "最新价", "涨跌幅", "涨跌额", "成交量", "成交额",
        "振幅", "换手率", "量比", "今开", "最高", "最低", "昨收",
        "涨速", "5分钟涨跌", "60日涨跌幅", "年初至今涨跌幅",
        "市盈率动", "市盈率TTM", "市盈率静", "市净率",
        "每股收益", "每股净资产", "每股公积金", "每股未分配利润",
        "加权净资产收益率", "毛利率", "资产负债率",
        "营业收入", "营业收入同比增长", "归属净利润", "归属净利润同比增长",
        "报告期", "总股本", "已流通股份", "总市值", "流通市值",
        "所处行业", "上市时间"
    ]

    # 确保所有列都存在
    for col in columns_order:
        if col not in temp_df.columns:
            temp_df[col] = 0 if col not in ['报告期', '上市时间', '所处行业'] else None

    temp_df = temp_df[columns_order]

    # 类型转换
    numeric_columns = ["最新价", "涨跌幅", "涨跌额", "振幅", "换手率", "量比",
                       "今开", "最高", "最低", "昨收", "涨速", "5分钟涨跌",
                       "60日涨跌幅", "年初至今涨跌幅", "市盈率动", "市盈率TTM",
                       "市盈率静", "市净率", "每股收益", "每股净资产", "每股公积金",
                       "每股未分配利润", "加权净资产收益率", "毛利率", "资产负债率",
                       "营业收入同比增长", "归属净利润同比增长"]

    for col in numeric_columns:
        temp_df[col] = pd.to_numeric(temp_df[col], errors="coerce")

    int_columns = ["成交量", "成交额", "营业收入", "归属净利润", "总股本", "已流通股份", "总市值", "流通市值"]
    for col in int_columns:
        temp_df[col] = pd.to_numeric(temp_df[col], errors="coerce").fillna(0).astype('int64')

    return temp_df

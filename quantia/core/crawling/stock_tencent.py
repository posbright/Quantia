#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""
Date: 2026/1/30
Desc: 腾讯财经-A股实时行情数据
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
    # 600xxx, 601xxx, 603xxx, 605xxx - 沪市A股
    # 688xxx - 科创板
    sh_prefixes = ['600', '601', '603', '605', '688']
    for prefix in sh_prefixes:
        for i in range(1000):
            codes.append(f'sh{prefix}{str(i).zfill(3)}')

    # 深市股票代码范围
    # 000xxx, 001xxx, 002xxx, 003xxx - 深市A股
    # 300xxx, 301xxx - 创业板
    sz_prefixes = ['000', '001', '002', '003', '300', '301']
    for prefix in sz_prefixes:
        for i in range(1000):
            codes.append(f'sz{prefix}{str(i).zfill(3)}')

    return codes


def _parse_tencent_data(text):
    """解析腾讯财经返回的数据"""
    stocks = []
    lines = text.strip().split(';')

    for line in lines:
        if '~' not in line or 'v_' not in line:
            continue

        try:
            # 数据格式: v_sh600000="1~浦发银行~600000~10.07~10.12~10.10~..."
            parts = line.split('~')
            if len(parts) < 50:
                continue

            # 检查是否有有效价格
            price = parts[3]
            if not price or price == '0.00' or price == '':
                continue

            code = parts[2]
            name = parts[1]

            # 提取数据字段
            # 腾讯数据字段说明:
            # 0:未知 1:名称 2:代码 3:当前价格 4:昨收 5:今开 6:成交量(手) 7:外盘 8:内盘
            # 9:买一价 10:买一量 ... 29:卖五量 30:时间 31:涨跌 32:涨跌% 33:最高 34:最低
            # 35:价格/成交量(手)/成交额 36:成交量(手) 37:成交额(万) 38:换手率 39:市盈率
            # 40:未知 41:最高 42:最低 43:振幅 44:流通市值 45:总市值 46:市净率 47:涨停价 48:跌停价

            stock = {
                '代码': code,
                '名称': name,
                '最新价': _safe_float(parts[3]),
                '涨跌幅': _safe_float(parts[32]),
                '涨跌额': _safe_float(parts[31]),
                '成交量': _safe_int(parts[36]) * 100 if parts[36] else 0,  # 转为股
                '成交额': _safe_float(parts[37]) * 10000 if parts[37] else 0,  # 转为元
                '振幅': _safe_float(parts[43]),
                '换手率': _safe_float(parts[38]),
                '量比': 0,  # 腾讯不提供量比
                '今开': _safe_float(parts[5]),
                '最高': _safe_float(parts[33]) if len(parts) > 33 else _safe_float(parts[41]),
                '最低': _safe_float(parts[34]) if len(parts) > 34 else _safe_float(parts[42]),
                '昨收': _safe_float(parts[4]),
                '涨速': 0,  # 腾讯不提供涨速
                '5分钟涨跌': 0,  # 腾讯不提供
                '60日涨跌幅': 0,  # 腾讯不提供
                '年初至今涨跌幅': 0,  # 腾讯不提供
                '市盈率动': _safe_float(parts[39]) if len(parts) > 39 else 0,
                '市盈率TTM': 0,  # 腾讯不提供
                '市盈率静': 0,  # 腾讯不提供
                '市净率': _safe_float(parts[46]) if len(parts) > 46 else 0,
                '每股收益': 0,  # 腾讯不提供
                '每股净资产': 0,  # 腾讯不提供
                '每股公积金': 0,  # 腾讯不提供
                '每股未分配利润': 0,  # 腾讯不提供
                '加权净资产收益率': 0,  # 腾讯不提供
                '毛利率': 0,  # 腾讯不提供
                '资产负债率': 0,  # 腾讯不提供
                '营业收入': 0,  # 腾讯不提供
                '营业收入同比增长': 0,  # 腾讯不提供
                '归属净利润': 0,  # 腾讯不提供
                '归属净利润同比增长': 0,  # 腾讯不提供
                '报告期': None,  # 腾讯不提供
                '总股本': 0,  # 腾讯不提供
                '已流通股份': 0,  # 腾讯不提供
                '总市值': _safe_float(parts[45]) * 10000 if len(parts) > 45 and parts[45] else 0,  # 转为元
                '流通市值': _safe_float(parts[44]) * 10000 if len(parts) > 44 and parts[44] else 0,  # 转为元
                '所处行业': '',  # 腾讯不提供
                '上市时间': None,  # 腾讯不提供
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
    url = f'http://qt.gtimg.cn/q={",".join(codes_batch)}'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://finance.qq.com/',
    }
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code == 200:
            # 腾讯返回的是GBK编码
            response.encoding = 'gbk'
            return _parse_tencent_data(response.text)
    except Exception:
        logging.debug(f"股票腾讯批量获取异常：{codes_batch[:3]}...", exc_info=True)
    return []


def stock_zh_a_spot_tencent() -> pd.DataFrame:
    """
    腾讯财经-沪深A股-实时行情
    https://finance.qq.com/
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

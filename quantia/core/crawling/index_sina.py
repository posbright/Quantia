#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""
Date: 2026/03/18
Desc: 新浪财经-指数实时行情数据
作为东方财富指数API的备选数据源（第三优先级）

新浪API特点：
- 支持 000xxx（上证/中证指数）和 399xxx（深证指数）
- 缺少换手率、总市值、流通市值字段（填 0）
- 作为最后的兜底方案, 核心价格数据可靠
"""
import time
import logging
import random
import requests
import pandas as pd

__author__ = 'Quantia'
__date__ = '2026/03/18'

# ── 核心指数代码列表（确保即使 DB 为空也能获取关键指数）──
_CORE_INDEX_CODES = [
    # 上证系列
    '000001', '000002', '000003', '000010', '000015', '000016',
    '000300', '000688', '000852', '000905', '000906',
    '000009', '000011', '000012', '000017', '000018',
    # 深证系列
    '399001', '399002', '399003', '399005', '399006',
    '399008', '399012', '399015', '399016', '399300',
    '399673', '399989', '399975', '399976', '399377',
]


def _code_to_sina(code):
    """将标准指数代码转换为新浪格式（sh/sz前缀）"""
    code = str(code).strip()
    if code.startswith('399'):
        return f'sz{code}'
    else:
        return f'sh{code}'


def _safe_float(value):
    """安全转换为浮点数"""
    try:
        if value is None or value == '' or value == '-':
            return 0.0
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _safe_int_from_float(value):
    """安全转换为整数"""
    try:
        if value is None or value == '' or value == '-':
            return 0
        return int(float(value))
    except (ValueError, TypeError):
        return 0


def _parse_sina_index_data(text, codes_list):
    """
    解析新浪财经返回的指数数据

    新浪数据字段（,分隔）：
    var hq_str_sh000001="上证指数,3260.7994,...";
    0:名称 1:今开 2:昨收 3:最新价 4:最高 5:最低 6:买一(无) 7:卖一(无) 8:成交量(手) 9:成交额(元)

    注意：新浪不提供 换手率、总市值、流通市值
    涨跌幅、涨跌额需根据当前价与昨收计算

    :param text: API 原始返回文本
    :param codes_list: 请求的指数代码列表（用于提取代码信息）
    :return: list[dict]
    """
    indexes = []
    lines = text.strip().split(';\n')

    for line in lines:
        if 'hq_str_' not in line or '="' not in line:
            continue

        try:
            # 提取代码和数据
            # 格式: var hq_str_sh000001="上证指数,3260.7994,...";
            var_part, data_part = line.split('="', 1)
            data_part = data_part.rstrip('"').rstrip(';').rstrip('"')

            if not data_part:
                continue

            # 提取代码 (sh000001 → 000001)
            market_code = var_part.split('_')[-1]
            code = market_code[2:]

            parts = data_part.split(',')
            if len(parts) < 10:
                continue

            name = parts[0].strip()
            price = _safe_float(parts[3])
            pre_close = _safe_float(parts[2])

            # 跳过无效数据
            if not name or price <= 0:
                continue

            # 计算涨跌额和涨跌幅
            ups_downs = round(price - pre_close, 4) if pre_close > 0 else 0.0
            change_rate = round(ups_downs / pre_close * 100, 4) if pre_close > 0 else 0.0

            index_data = {
                '代码': code,
                '名称': name,
                '最新价': price,
                '涨跌幅': change_rate,
                '涨跌额': ups_downs,
                '成交量': _safe_int_from_float(parts[8]) * 100 if parts[8] else 0,  # 手→股
                '成交额': _safe_float(parts[9]),  # 元（sina 已经是元）
                '开盘价': _safe_float(parts[1]),
                '最高价': _safe_float(parts[4]),
                '最低价': _safe_float(parts[5]),
                '昨收': pre_close,
                '换手率': 0.0,       # 新浪不提供
                '总市值': 0,          # 新浪不提供
                '流通市值': 0,        # 新浪不提供
            }
            indexes.append(index_data)
        except Exception:
            continue

    return indexes


def _fetch_batch(codes_batch, timeout=30):
    """批量获取指数数据"""
    sina_codes = [_code_to_sina(c) for c in codes_batch]
    url = f'http://hq.sinajs.cn/list={",".join(sina_codes)}'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://finance.sina.com.cn/',
    }
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code == 200:
            response.encoding = 'gbk'
            return _parse_sina_index_data(response.text, codes_batch)
    except Exception:
        logging.debug(f"指数新浪批量获取异常：{codes_batch[:3]}...", exc_info=True)
    return []


def _get_index_codes_from_db():
    """从数据库获取已知的指数代码列表"""
    try:
        import quantia.lib.database as mdb
        if not mdb.checkTableIsExist('cn_index_spot'):
            return []
        df = pd.read_sql('SELECT DISTINCT code FROM cn_index_spot ORDER BY code', mdb.engine())
        if df is not None and len(df) > 0:
            return df['code'].tolist()
    except Exception as e:
        logging.debug(f"从DB获取指数代码列表失败：{e}")
    return []


def index_spot_sina() -> pd.DataFrame:
    """
    新浪财经-沪深指数-实时行情

    作为第三优先级数据源。新浪缺少换手率和市值数据，
    但价格数据可靠，可作为最后的兜底方案。

    列顺序与 TABLE_CN_INDEX_SPOT 对齐：
    代码, 名称, 最新价, 涨跌幅, 涨跌额, 成交量, 成交额,
    开盘价, 最高价, 最低价, 昨收, 换手率, 总市值, 流通市值

    :return: 指数实时行情 DataFrame
    :rtype: pandas.DataFrame
    """
    # 获取代码列表
    db_codes = _get_index_codes_from_db()
    all_codes = list(set(db_codes + _CORE_INDEX_CODES))
    all_codes.sort()

    if not all_codes:
        logging.warning("指数新浪：无可用指数代码列表")
        return pd.DataFrame()

    all_indexes = []
    batch_size = 80

    for i in range(0, len(all_codes), batch_size):
        batch = all_codes[i:i + batch_size]
        try:
            result = _fetch_batch(batch)
            all_indexes.extend(result)
        except Exception:
            continue
        if i > 0:
            time.sleep(random.uniform(0.3, 0.6))

    if not all_indexes:
        return pd.DataFrame()

    temp_df = pd.DataFrame(all_indexes)

    # 列顺序与东方财富一致
    columns_order = [
        "代码", "名称", "最新价", "涨跌幅", "涨跌额", "成交量", "成交额",
        "开盘价", "最高价", "最低价", "昨收", "换手率", "总市值", "流通市值",
    ]

    for col in columns_order:
        if col not in temp_df.columns:
            temp_df[col] = 0

    temp_df = temp_df[columns_order]

    # 类型转换
    for col in ["最新价", "涨跌幅", "涨跌额", "开盘价", "最高价", "最低价", "昨收", "换手率"]:
        temp_df[col] = pd.to_numeric(temp_df[col], errors="coerce")
    for col in ["成交量", "成交额", "总市值", "流通市值"]:
        temp_df[col] = pd.to_numeric(temp_df[col], errors="coerce").fillna(0).astype('int64')

    # 防御：过滤异常长度的代码
    temp_df["代码"] = temp_df["代码"].astype(str).str.strip()
    temp_df = temp_df[temp_df["代码"].str.len() <= 12].reset_index(drop=True)

    # 去重
    temp_df = temp_df.drop_duplicates(subset=['代码'], keep='first').reset_index(drop=True)

    return temp_df

#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""
Date: 2026/03/18
Desc: 腾讯财经-指数实时行情数据
作为东方财富指数API的备选数据源

腾讯API特点：
- 支持 000xxx（上证/中证指数）和 399xxx（深证指数）
- 覆盖约 ~533 个常见指数（EastMoney覆盖 ~1067 个）
- 需要预先知道指数代码列表（无枚举接口）
- 返回格式与股票相同，通过 qt.gtimg.cn 批量查询
"""
import time
import logging
import random
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

__author__ = 'Quantia'
__date__ = '2026/03/18'

# ── 核心指数代码列表（确保即使 DB 为空也能获取关键指数）──
# 这些是最重要的沪深指数，任何情况下都应尝试获取
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


def _code_to_tencent(code):
    """将标准指数代码转换为腾讯格式（sh/sz前缀）"""
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
    """安全转换为整数（先转float再转int，处理科学计数法）"""
    try:
        if value is None or value == '' or value == '-':
            return 0
        return int(float(value))
    except (ValueError, TypeError):
        return 0


def _parse_tencent_index_data(text):
    """
    解析腾讯财经返回的指数数据

    腾讯数据字段（~分隔）：
    0:未知 1:名称 2:代码 3:最新价 4:昨收 5:今开
    31:涨跌额 32:涨跌幅 33:最高 34:最低
    36:成交量(手) 37:成交额(万) 38:换手率
    44:流通市值(亿) 45:总市值(亿)

    Returns:
        list[dict]: 指数数据列表
    """
    indexes = []
    lines = text.strip().split(';')

    for line in lines:
        if '~' not in line or 'v_' not in line:
            continue

        try:
            parts = line.split('~')
            if len(parts) < 37:
                continue

            code = parts[2]
            name = parts[1]
            price = _safe_float(parts[3])

            # 跳过无效数据（无名称或无价格）
            if not name or name == code or price <= 0:
                continue

            index_data = {
                '代码': code,
                '名称': name,
                '最新价': price,
                '涨跌幅': _safe_float(parts[32]),
                '涨跌额': _safe_float(parts[31]),
                '成交量': _safe_int_from_float(parts[36]) * 100 if parts[36] else 0,  # 手→股
                '成交额': _safe_float(parts[37]) * 10000 if parts[37] else 0,  # 万→元
                '开盘价': _safe_float(parts[5]),
                '最高价': _safe_float(parts[33]) if len(parts) > 33 else 0.0,
                '最低价': _safe_float(parts[34]) if len(parts) > 34 else 0.0,
                '昨收': _safe_float(parts[4]),
                '换手率': _safe_float(parts[38]) if len(parts) > 38 else 0.0,
                '总市值': _safe_float(parts[45]) * 100000000 if len(parts) > 45 and parts[45] else 0,  # 亿→元
                '流通市值': _safe_float(parts[44]) * 100000000 if len(parts) > 44 and parts[44] else 0,  # 亿→元
            }
            indexes.append(index_data)
        except Exception:
            continue

    return indexes


def _fetch_batch(codes_batch, timeout=30):
    """批量获取指数数据"""
    tencent_codes = [_code_to_tencent(c) for c in codes_batch]
    url = f'http://qt.gtimg.cn/q={",".join(tencent_codes)}'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://finance.qq.com/',
    }
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code == 200:
            response.encoding = 'gbk'
            return _parse_tencent_index_data(response.text)
    except Exception:
        logging.debug(f"指数腾讯批量获取异常：{codes_batch[:3]}...", exc_info=True)
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


def index_spot_tencent() -> pd.DataFrame:
    """
    腾讯财经-沪深指数-实时行情

    数据获取策略：
    1. 先从 DB 读取已知指数代码列表（覆盖最全）
    2. 合并核心指数代码（确保关键指数不遗漏）
    3. 批量查询腾讯API

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
        logging.warning("指数腾讯：无可用指数代码列表")
        return pd.DataFrame()

    all_indexes = []
    batch_size = 80

    # 顺序批量获取（指数数量不大，无需并发）
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

    # 去重（DB代码 + 核心代码可能重复）
    temp_df = temp_df.drop_duplicates(subset=['代码'], keep='first').reset_index(drop=True)

    return temp_df


def _fmt_dash_date(yyyymmdd):
    """将 YYYYMMDD 转为腾讯 K线接口所需的 YYYY-MM-DD；非法输入返回空串。"""
    s = str(yyyymmdd or '').strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    # 已是带分隔符的日期则原样返回
    return s


def index_hist_tencent(symbol="000300", start_date="19700101",
                       end_date="20500101", timeout=30) -> pd.DataFrame:
    """
    腾讯财经-指数历史日 K 线（东方财富指数 K线 API 的备选源）。

    使用腾讯 fqkline 日线接口（指数无需复权）：
        https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh000001,day,2024-01-01,2024-12-31,640,

    返回 DataFrame 列名与 stock_index_hist_em 对齐（中文列名），
    便于上层 _normalize_index_hist 直接复用；腾讯仅提供
    日期/开盘/收盘/最高/最低/成交量，其余列缺省为 NaN。

    :param symbol: 指数代码（如 '000300'）
    :param start_date: 起始日期 YYYYMMDD
    :param end_date: 结束日期 YYYYMMDD
    :return: 指数历史 K 线 DataFrame（失败/无数据时为空 DataFrame）
    """
    tx_code = _code_to_tencent(symbol)
    beg = _fmt_dash_date(start_date)
    end = _fmt_dash_date(end_date)
    # 腾讯 fqkline 接口 count 上限为 2000（实测 >2000 返回 param error）。
    # count 为「返回的最近 N 根」上限，且仍受 [beg, end] 区间二次约束；
    # 区间内不足 2000 根时只返回区间内的数据，故固定取 2000 安全且足够：
    #   - 增量 tail：区间窄，仅返回区间内寥寥数根；
    #   - 兜底全量：返回最近 2000 根（约 8 年），满足备用源需求。
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={tx_code},day,{beg},{end},2000,"
    )
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://gu.qq.com/',
    }
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code != 200 or not (response.text and response.text.strip()):
            return pd.DataFrame()
        data_json = response.json()
    except Exception as e:
        logging.debug(f"指数腾讯历史K线获取异常 {symbol}: {e}")
        return pd.DataFrame()

    node = (data_json.get('data') or {}).get(tx_code) or {}
    # 优先取未复权日线（day），兼容个别接口返回 qfqday
    klines = node.get('day') or node.get('qfqday') or []
    if not klines:
        return pd.DataFrame()

    rows = []
    for item in klines:
        # 每行至少 [日期, 开盘, 收盘, 最高, 最低, 成交量]
        if not item or len(item) < 6:
            continue
        rows.append(item[:6])
    if not rows:
        return pd.DataFrame()

    temp_df = pd.DataFrame(rows, columns=["日期", "开盘", "收盘", "最高", "最低", "成交量"])
    temp_df.index = pd.to_datetime(temp_df["日期"])
    temp_df.reset_index(inplace=True, drop=True)
    for col in ["开盘", "收盘", "最高", "最低", "成交量"]:
        temp_df[col] = pd.to_numeric(temp_df[col], errors="coerce")
    return temp_df


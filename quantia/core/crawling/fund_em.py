#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""场外开放式基金（净值型 + 货币型）数据薄封装。

不逆向东财：直接包 akshare 现成函数 + 中文列 → 英文列映射 + 费率/数值解析，
统一对齐 tablestructure.TABLE_CN_FUND_RANK 列。

- 净值型：fund_open_fund_rank_em(symbol=类型) → 单位/累计净值 + 全周期收益率
- 货币型：fund_money_rank_em() → 万份收益 / 7日年化 / 多周期收益率

属 fetch 管道（仅此处 + stockfetch + fetch_* 可调外部 API）。
"""
import logging
import random
import re
import time

import pandas as pd

__author__ = 'Quantia'
__date__ = '2026/06/01'

# fund_open_fund_rank_em 支持的净值型 symbol（货币型单独走 fund_money_rank_em）
_NAV_TYPES = ['股票型', '混合型', '债券型', '指数型', 'QDII', 'FOF']

# 净值型中文列 → 英文列
_NAV_COL_MAP = {
    '基金代码': 'code',
    '基金简称': 'name',
    '日期': 'nav_date',
    '单位净值': 'unit_nav',
    '累计净值': 'acc_nav',
    '日增长率': 'day_growth',
    '近1周': 'rate_1w',
    '近1月': 'rate_1m',
    '近3月': 'rate_3m',
    '近6月': 'rate_6m',
    '近1年': 'rate_1y',
    '近2年': 'rate_2y',
    '近3年': 'rate_3y',
    '今年来': 'rate_ytd',
    '成立来': 'rate_since',
    '手续费': 'fee',
}

# 货币型中文列 → 英文列
_MONEY_COL_MAP = {
    '基金代码': 'code',
    '基金简称': 'name',
    '日期': 'nav_date',
    '万份收益': 'million_unit_income',
    '年化收益率7日': 'seven_day_annual',
    '近1月': 'rate_1m',
    '近3月': 'rate_3m',
    '近6月': 'rate_6m',
    '近1年': 'rate_1y',
    '近2年': 'rate_2y',
    '近3年': 'rate_3y',
    '今年来': 'rate_ytd',
    '成立来': 'rate_since',
    '手续费': 'fee',
}

# 数值型目标列（统一 coerce 为 float，未披露 → NaN）
_NUMERIC_COLS = [
    'unit_nav', 'acc_nav', 'day_growth', 'million_unit_income', 'seven_day_annual',
    'rate_1w', 'rate_1m', 'rate_3m', 'rate_6m', 'rate_1y', 'rate_2y', 'rate_3y',
    'rate_ytd', 'rate_since', 'fee',
]


def _parse_fee(value) -> float:
    """费率解析：'0.15%' → 0.15；'0'/'---'/''/NaN → None。"""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s in ('---', '--', '-', '<NA>', 'nan', 'None'):
        return None
    m = re.search(r'-?\d+(\.\d+)?', s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except (TypeError, ValueError):
        return None


def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """把已映射的数值列统一 coerce 为 float；费率单独走百分数解析。"""
    if 'fee' in df.columns:
        df['fee'] = df['fee'].map(_parse_fee)
    for col in _NUMERIC_COLS:
        if col == 'fee' or col not in df.columns:
            continue
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df


def _map_nav_columns(df: pd.DataFrame) -> pd.DataFrame:
    """净值型列映射 + 数值清洗（丢弃 序号/自定义 等未映射列）。"""
    keep = {cn: en for cn, en in _NAV_COL_MAP.items() if cn in df.columns}
    out = df[list(keep)].rename(columns=keep).copy()
    return _coerce_numeric(out)


def _map_money_columns(df: pd.DataFrame) -> pd.DataFrame:
    """货币型列映射 + 数值清洗。"""
    keep = {cn: en for cn, en in _MONEY_COL_MAP.items() if cn in df.columns}
    out = df[list(keep)].rename(columns=keep).copy()
    return _coerce_numeric(out)


def fund_rank_all() -> pd.DataFrame:
    """净值型逐类型 + 货币型，统一到 TABLE_CN_FUND_RANK 列（不含 date）。

    某类型失败仅记录并跳过，不中断其他类型；全部失败返回 None。
    """
    import akshare as ak

    frames = []
    for t in _NAV_TYPES:
        try:
            df = ak.fund_open_fund_rank_em(symbol=t)
            if df is None or len(df.index) == 0:
                logging.warning(f"fund_em.fund_rank_all: {t} 返回空")
                continue
            df = _map_nav_columns(df)
            df['fund_type'] = t
            frames.append(df)
        except Exception:
            logging.warning(f"fund_em.fund_rank_all: {t} 抓取失败，跳过", exc_info=True)
        finally:
            time.sleep(random.uniform(1.0, 2.0))  # 限速

    try:
        money = ak.fund_money_rank_em()
        if money is not None and len(money.index) > 0:
            money = _map_money_columns(money)
            money['fund_type'] = '货币型'
            frames.append(money)
        else:
            logging.warning("fund_em.fund_rank_all: 货币型返回空")
    except Exception:
        logging.warning("fund_em.fund_rank_all: 货币型抓取失败，跳过", exc_info=True)

    if not frames:
        logging.error("fund_em.fund_rank_all: 所有基金类型均获取失败")
        return None

    return pd.concat(frames, ignore_index=True)

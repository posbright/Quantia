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

# akshare 外部抓取重试配置（东财/雪球偶发瞬时断连：RemoteDisconnected / 连接重置）
_FETCH_MAX_RETRIES = 3
_FETCH_BACKOFF_BASE = 1.5  # 秒，指数退避基数


def _is_transient_fetch_error(e) -> bool:
    """仅网络/连接类瞬态异常才值得重试；数据缺失类（KeyError 等）立即放弃。"""
    if isinstance(e, (KeyError, ValueError, TypeError, IndexError)):
        return False
    msg = str(e).lower()
    transient_markers = ('remotedisconnected', 'connection aborted', 'connection reset',
                         'connection refused', 'timed out', 'timeout', 'temporarily',
                         'max retries', 'proxyerror', 'protocolerror', 'broken pipe',
                         'ssl', 'unexpected_eof', 'eof occurred', 'decryption failed',
                         'bad record mac', 'wrong version number')
    return any(m in msg for m in transient_markers) or \
        e.__class__.__name__ in ('ConnectionError', 'ProtocolError', 'Timeout',
                                 'ReadTimeout', 'ConnectTimeout', 'ChunkedEncodingError',
                                 'SSLError', 'SSLEOFError', 'SSLZeroReturnError')


def _fetch_with_retry(fn, *args, _desc='', **kwargs):
    """对 akshare 调用做有限次重试 + 指数退避（含轻微抖动）。

    仅吞掉瞬态网络异常并重试，非瞬态异常或末次失败将异常抛回调用方按原逻辑处理。
    """
    last_exc = None
    for attempt in range(1, _FETCH_MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 —— akshare 抛出的异常类型繁杂，统一研判后决定是否重试
            last_exc = e
            if attempt < _FETCH_MAX_RETRIES and _is_transient_fetch_error(e):
                sleep_s = _FETCH_BACKOFF_BASE * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                logging.debug(f"fund_em 抓取瞬态失败（第{attempt}/{_FETCH_MAX_RETRIES}次重试）{_desc}：{type(e).__name__}")
                time.sleep(sleep_s)
            else:
                raise
    raise last_exc

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


# ── F8 净值历史（回撤/夏普/净值曲线）─────────────────────────────────
# 来源 fund_open_fund_info_em(symbol=code, indicator='单位净值走势' / '累计净值走势')。
# ⚠️ 长期收益/夏普/回撤一律用 acc_nav（累计净值，已还原分红拆分），unit_nav 仅展示。

_NAV_UNIT_COL_MAP = {
    '净值日期': 'nav_date',
    '单位净值': 'unit_nav',
    '日增长率': 'day_growth',
}
_NAV_ACC_COL_MAP = {
    '净值日期': 'nav_date',
    '累计净值': 'acc_nav',
}


def _map_nav_history(unit_df, acc_df, code) -> pd.DataFrame:
    """合并单位净值走势 + 累计净值走势为一行/日，对齐 TABLE_CN_FUND_NAV_HISTORY 列。

    纯函数（不调外部 API），供单测直接传样例 DataFrame。
    """
    if unit_df is None or len(unit_df.index) == 0:
        return None
    keep_u = {cn: en for cn, en in _NAV_UNIT_COL_MAP.items() if cn in unit_df.columns}
    out = unit_df[list(keep_u)].rename(columns=keep_u).copy()

    if acc_df is not None and len(acc_df.index) > 0:
        keep_a = {cn: en for cn, en in _NAV_ACC_COL_MAP.items() if cn in acc_df.columns}
        acc = acc_df[list(keep_a)].rename(columns=keep_a).copy()
        out = out.merge(acc, on='nav_date', how='left')
    if 'acc_nav' not in out.columns:
        out['acc_nav'] = pd.NA

    out['nav_date'] = pd.to_datetime(out['nav_date'], errors='coerce').dt.date
    for col in ('unit_nav', 'acc_nav', 'day_growth'):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors='coerce')
        else:
            out[col] = pd.NA
    out.insert(0, 'code', str(code))
    out = out.dropna(subset=['nav_date'])
    out = out[['code', 'nav_date', 'unit_nav', 'acc_nav', 'day_growth']]
    return out


def fund_nav_history(code) -> pd.DataFrame:
    """逐基金净值历史（单位+累计净值走势合并）。netvalue 型适用，货币型应在调用方跳过。"""
    import akshare as ak

    try:
        unit = _fetch_with_retry(ak.fund_open_fund_info_em, symbol=str(code),
                                 indicator='单位净值走势', _desc=f'{code} 单位净值')
    except Exception:
        logging.warning(f"fund_em.fund_nav_history: {code} 单位净值走势抓取失败", exc_info=True)
        return None
    try:
        acc = _fetch_with_retry(ak.fund_open_fund_info_em, symbol=str(code),
                                indicator='累计净值走势', _desc=f'{code} 累计净值')
    except Exception as e:
        # 东财累计净值接口偶发瞬时断连（RemoteDisconnected），重试耗尽后单位净值已足够入库，
        # 简洁告警避免整栈回溯刷屏。
        logging.warning(f"fund_em.fund_nav_history: {code} 累计净值走势抓取失败（仅用单位净值）：{type(e).__name__}")
        acc = None
    return _map_nav_history(unit, acc, code)


# ── F10 规模 + 画像（规模因子 & 投资价值分析）─────────────────────────
# 来源 fund_individual_basic_info_xq(symbol=code) → item/value 透视为一行。

# 画像 item 中文名 → 英文列（容错：缺失 item 留 None）
_PROFILE_ITEM_MAP = {
    '基金名称': 'name',
    '基金全称': 'full_name',
    '成立时间': 'setup_date',
    '最新规模': 'scale_yi',
    '基金公司': 'company',
    '基金经理': 'manager',
    '基金类型': 'fund_type_detail',
    '基金评级': 'rating',
    '投资策略': 'strategy',
    '投资目标': 'objective',
    '业绩比较基准': 'benchmark',
}


def _parse_scale_yi(value):
    """规模解析：'26.44亿' → 26.44；'5000万' → 0.05（亿）；空/无效 → None。"""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s in ('---', '--', '-', '<NA>', 'nan', 'None', '暂无数据'):
        return None
    m = re.search(r'-?\d+(\.\d+)?', s)
    if not m:
        return None
    try:
        num = float(m.group(0))
    except (TypeError, ValueError):
        return None
    if '万' in s and '亿' not in s:
        return round(num * 1e-4, 6)  # 万元 → 亿元
    return num


def _pivot_profile(info_df, code) -> dict:
    """item/value 画像透视为单行 dict，对齐 TABLE_CN_FUND_PROFILE 列。纯函数。"""
    if info_df is None or len(info_df.index) == 0:
        return None
    if 'item' not in info_df.columns or 'value' not in info_df.columns:
        return None
    kv = dict(zip(info_df['item'].astype(str), info_df['value']))
    row = {'code': str(code)}
    for cn, en in _PROFILE_ITEM_MAP.items():
        val = kv.get(cn)
        if en == 'scale_yi':
            row[en] = _parse_scale_yi(val)
        elif en == 'setup_date':
            d = pd.to_datetime(val, errors='coerce')
            row[en] = d.date() if pd.notna(d) else None
        else:
            s = None if val is None else str(val).strip()
            row[en] = s if s and s not in ('<NA>', 'nan', 'None', '---') else None
    return row


def fund_profile(code) -> dict:
    """逐基金规模/画像。返回单行 dict（不含 update_date，由 job 补入库日）。"""
    import akshare as ak

    try:
        info = _fetch_with_retry(ak.fund_individual_basic_info_xq, symbol=str(code),
                                 _desc=f'{code} 画像')
    except KeyError:
        # 雪球对部分基金（新发/QDII/未收录）返回的 JSON 不含 'data' 键 —— 预期内的外部缺失，
        # 简洁告警避免整栈回溯刷屏。
        logging.warning(f"fund_em.fund_profile: {code} 雪球无画像数据（跳过）")
        return None
    except Exception:
        logging.warning(f"fund_em.fund_profile: {code} 画像抓取失败", exc_info=True)
        return None
    return _pivot_profile(info, code)


# ── F12 季度前十大重仓股（持仓展示 + 行业筛选/对比）──────────────────
# 来源 fund_portfolio_hold_em(symbol=code, date=年份)，取最新季度。

_HOLDING_COL_MAP = {
    '股票代码': 'stock_code',
    '股票名称': 'stock_name',
    '占净值比例': 'hold_ratio',
    '持股数': 'hold_shares',
    '持仓市值': 'hold_value',
    '季度': 'quarter',
}


def _parse_ratio(value):
    """占净值比例解析：'5.21%' / '5.21' → 5.21；空/无效 → None。"""
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


def _pick_latest_quarter(df: pd.DataFrame) -> pd.DataFrame:
    """从含多季度的持仓表里取最新季度（季度字符串字典序最大即最新，如 '2025年1季度'）。"""
    if df is None or len(df.index) == 0 or '季度' not in df.columns:
        return df
    latest = sorted(df['季度'].dropna().astype(str).unique())[-1]
    return df[df['季度'].astype(str) == latest].copy()


def _map_holding_columns(df: pd.DataFrame, code) -> pd.DataFrame:
    """最新季度前十大重仓股列映射 + 比例解析（行业留待 job 读库回填）。纯函数。"""
    if df is None or len(df.index) == 0:
        return None
    latest = _pick_latest_quarter(df)
    keep = {cn: en for cn, en in _HOLDING_COL_MAP.items() if cn in latest.columns}
    out = latest[list(keep)].rename(columns=keep).copy()
    if 'hold_ratio' in out.columns:
        out['hold_ratio'] = out['hold_ratio'].map(_parse_ratio)
    for col in ('hold_shares', 'hold_value'):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors='coerce')
    out['stock_code'] = out['stock_code'].astype(str).str.zfill(6) if 'stock_code' in out.columns else None
    out.insert(0, 'code', str(code))
    return out


def fund_holding_latest(code, year) -> pd.DataFrame:
    """逐基金最新季度前十大重仓股；当年无披露则回退上一年。

    东财 fundf10 偶发 SSLError / EOF / 连接重置：经 _fetch_with_retry 做有限次
    指数退避重试，避免一次瞬态抖动就把整只基金判定为「无持仓」拉低覆盖率。
    """
    import akshare as ak

    df = None
    last_error = None
    got_clean_response = False
    for y in (year, year - 1):
        try:
            df = _fetch_with_retry(
                ak.fund_portfolio_hold_em, symbol=str(code), date=str(y),
                _desc=f"holding {code}/{y}")
            got_clean_response = True  # akshare 正常返回（即便为空），非抓取异常
        except Exception as e:
            last_error = e
            logging.warning(f"fund_em.fund_holding_latest: {code}/{y} 抓取失败", exc_info=True)
            df = None
        if df is not None and len(df.index) > 0:
            break
    if df is not None and len(df.index) > 0:
        return _map_holding_columns(df, code)
    # 无数据：区分「确实无披露」与「持续抓取失败」。
    # 全部年份都未拿到一次干净响应（纯瞬态/SSL 失败）则向上抛出，避免误判为「无持仓」
    # 而被全覆盖逻辑标记为本周期已尝试，从而本月不再重试。
    if not got_clean_response and last_error is not None:
        raise last_error
    return None

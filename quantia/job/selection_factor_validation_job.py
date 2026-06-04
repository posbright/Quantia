#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
综合选股 —— 因子有效性验证编排（M0）。

离线研究脚本，手动运行。**仅读 MySQL**（cn_stock_selection 快照），不做任何外部 API 调用，
符合 AGENTS.md 规则 1（Analysis 管道只读 DB）。未来收益直接用快照中的 `new_price`
按交易日历前移计算，避免逐股拉 K 线。

产出（M0 交付物 = 经验证的权重/阈值参数）：
1. 单因子 IC：每个连续因子方向化后与未来 N 日收益的 Spearman IC 时序，汇总
   均值 IC / IC std / IR / t 统计量 / IC 胜率。判定 |mean IC| > 0.03 为有效。
2. 维度 IC：维度绝对分 Q_d 的 IC。
3. 分层回测：按综合质量分 Q 分 5 层，检验各层未来收益单调性（高分层收益更高）。

用法：
    python -m quantia.job.selection_factor_validation_job --start 2025-06-01 --end 2026-02-14
    python -m quantia.job.selection_factor_validation_job --horizons 5,10,20 --rebalance 5

数据源（--source）：
    selection : cn_stock_selection 日频，因子最全但历史短(~35 交易日)，纯读 DB。
    spot      : cn_stock_spot 日频，因子子集、基本面多为空，仅 pbnewmrq/dtsyl 有效。
    financial : cn_stock_financial 季频财务（长历史 2017+），映射到盈利/成长/健康维度，
                价格用 stockfetch 取日线缓存（缺失走外部 API），按报告期+披露滞后做
                point-in-time 对齐计算前向收益。⚠ 该源会触发外部价格 API（用户确认）。
    python -m quantia.job.selection_factor_validation_job --source financial \
        --start 2018-01-01 --end 2024-12-31 --horizons 20,60 --max-codes 300 --lag 60
"""
from __future__ import annotations

import argparse
import logging
import os.path
import sys

import pandas as pd

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)

import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
import quantia.core.selection_scoring as sc

__author__ = 'Quantia'
__date__ = '2026/02/14'

_TABLE = tbs.TABLE_CN_STOCK_SELECTION['name']

# 可选数据源：名称 → tablestructure 表定义。
# selection 因子最全(35 交易日)；spot 因子子集但历史更长(70 交易日)。
_SOURCE_TABLES = {
    'selection': tbs.TABLE_CN_STOCK_SELECTION,
    'spot': tbs.TABLE_CN_STOCK_SPOT,
}

# financial 源：cn_stock_financial 季频财务 → 映射到 FACTOR_DIRECTIONS 因子名，
# 复用既有方向/维度配置。覆盖 profitability/growth/health 三个长历史基本面维度。
# 价格不在该表内，需用 stockfetch 取日线缓存计算前向收益（point-in-time 对齐）。
_FINANCIAL_FACTOR_MAP = {
    'revenue_yoy': 'toi_yoy_ratio',          # 营收同比 → 成长·营收
    'net_profit_yoy': 'netprofit_yoy_ratio',  # 净利同比 → 成长·利润
    'roe': 'roe_weight',                      # ROE → 盈利
    'roa': 'jroa',                            # ROA → 盈利
    'gross_margin': 'sale_gpr',               # 毛利率 → 盈利·利润率
    'net_profit_margin': 'sale_npr',          # 净利率 → 盈利·利润率
    'asset_liability_ratio': 'debt_asset_ratio',  # 资产负债率 → 健康·杠杆(低优)
    'current_ratio': 'current_ratio',         # 流动比率 → 健康·流动性
    'quick_ratio': 'speed_ratio',             # 速动比率 → 健康·流动性
}


# ---------------------------------------------------------------------------
# 数据加载（只读 DB）
# ---------------------------------------------------------------------------

def load_selection_panel(start_date: str, end_date: str, source: str = 'selection') -> pd.DataFrame:
    """加载 [start, end] 区间内数据源全字段面板（date, code, industry, new_price + 因子）。"""
    table_def = _SOURCE_TABLES[source]
    table_name = table_def['name']
    factor_fields = sorted(sc.FACTOR_DIRECTIONS.keys())
    cols = ['date', 'code', 'industry', 'new_price'] + factor_fields
    # 仅取表中真实存在的列，避免历史字段缺失导致 SQL 报错
    table_cols = set(table_def['columns'].keys())
    cols = [c for c in cols if c in table_cols]
    col_sql = ', '.join(f'`{c}`' for c in cols)
    sql = (f"SELECT {col_sql} FROM `{table_name}` "
           f"WHERE `date` BETWEEN %s AND %s ORDER BY `date`, `code`")
    df = pd.read_sql(sql=sql, con=mdb.engine(), params=(start_date, end_date))
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
    return df


# ---------------------------------------------------------------------------
# 未来收益（用快照 new_price，按交易日历前移）
# ---------------------------------------------------------------------------

def compute_forward_returns(panel: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """
    返回长表 [date, code, fwd_ret]：date 时点持有 horizon 个交易日的收益。
    交易日历取面板内排序后的唯一日期；fwd_ret = price[t+horizon] / price[t] − 1。
    """
    px = panel.pivot_table(index='date', columns='code', values='new_price').sort_index()
    # 价格 ≤ 0（停牌/缺失）置 NaN，避免 price/0 = inf 污染收益
    px = px.where(px > 0)
    fwd = px.shift(-horizon) / px - 1.0
    out = (fwd.reset_index()
              .melt(id_vars='date', var_name='code', value_name='fwd_ret')
              .replace([float('inf'), float('-inf')], pd.NA)
              .dropna(subset=['fwd_ret']))
    return out


# ---------------------------------------------------------------------------
# financial 源：季频财务面板 + 价格前向收益（point-in-time 对齐）
# ---------------------------------------------------------------------------

def load_financial_panel(start_date: str, end_date: str, min_fill: float = 0.30,
                         code_filter: list[str] | None = None) -> pd.DataFrame:
    """
    加载 cn_stock_financial 标准季报面板，列名映射为 FACTOR_DIRECTIONS 因子名。
    'date' 列 = report_date（报告期）。仅保留标准季末(3/31,6/30,9/30,12/31)。
    剔除整体填充率 < min_fill 的报告期（如未结算的当季/历史空期）。
    """
    fin_cols = list(_FINANCIAL_FACTOR_MAP.keys())
    col_sql = ', '.join(f'`{c}`' for c in (['report_date', 'code'] + fin_cols))
    params: list = [start_date, end_date]
    code_clause = ""
    if code_filter:
        code_filter = [str(code) for code in code_filter if code]
        if code_filter:
            placeholders = ', '.join(['%s'] * len(code_filter))
            code_clause = f" AND `code` IN ({placeholders})"
            params.extend(code_filter)
    sql = (f"SELECT {col_sql} FROM `cn_stock_financial` "
           f"WHERE `report_date` BETWEEN %s AND %s "
           f"AND MONTH(`report_date`) IN (3,6,9,12) "
           f"AND DAY(`report_date`) IN (30,31)"
           f"{code_clause} "
           f"ORDER BY `report_date`, `code`")
    df = pd.read_sql(sql=sql, con=mdb.engine(), params=tuple(params))
    if df.empty:
        return df
    df = df.rename(columns={'report_date': 'date', **_FINANCIAL_FACTOR_MAP})
    df['date'] = pd.to_datetime(df['date'])
    # 按报告期过滤低填充期（用核心因子 roe_weight 的非零占比近似）
    keep = []
    for d, g in df.groupby('date'):
        fill = (g['roe_weight'].notna() & (g['roe_weight'] != 0)).mean()
        if fill >= min_fill:
            keep.append(d)
    df = df[df['date'].isin(keep)].reset_index(drop=True)
    industry_map = _load_latest_selection_industry_map()
    if industry_map:
        df['industry'] = df['code'].astype(str).map(industry_map)
    return df


def load_selection_pool_codes() -> set:
    """返回原综合选股池（cn_stock_selection）出现过的全部股票代码集合。"""
    sql = f"SELECT DISTINCT `code` FROM `{_TABLE}`"
    df = pd.read_sql(sql=sql, con=mdb.engine())
    return set(df['code'].astype(str)) if not df.empty else set()


def _load_latest_selection_industry_map() -> dict[str, str]:
    """从 cn_stock_selection 最新交易日回填 code -> industry。"""
    sql = """
        SELECT `code`, `industry`
        FROM `cn_stock_selection`
        WHERE `date` = (SELECT MAX(`date`) FROM `cn_stock_selection`)
          AND `industry` IS NOT NULL AND `industry` <> ''
    """
    try:
        rows = mdb.executeSqlFetch(sql) or []
    except Exception as e:
        logging.warning(f"[financial] 读取行业映射失败: {e}")
        return {}
    return {str(code): str(industry) for code, industry in rows if code and industry}


def fetch_price_panel(codes, date_start: str, date_end: str) -> pd.DataFrame:
    """
    用 stockfetch 取日线收盘价（缓存优先，缺失则外部 API 拉取并回写缓存）。
    返回宽表 px：index=交易日(datetime)，columns=code，值=close。
    date_start/date_end 为 YYYYMMDD。本函数会触发外部 API（用户已确认）。
    """
    import os
    import quantia.core.stockfetch as sf
    frames = {}
    n = len(codes)
    cache_only = str(os.getenv('QUANTIA_PRICE_CACHE_ONLY', '0')).strip().lower() in {'1', 'true', 'yes', 'on'}
    for i, code in enumerate(codes, 1):
        try:
            if cache_only:
                # 全池评估可仅用本地缓存，避免外部 API 超时拖慢任务。
                data = sf.read_stock_hist_from_cache(code, date_start, date_end)
            else:
                data = sf.fetch_stock_hist((date_end, code), date_start, date_end, is_cache=True)
        except Exception as e:
            logging.warning(f"[financial] 取价失败 {code}: {e}")
            data = None
        if data is not None and len(data) > 0 and 'close' in data.columns:
            s = pd.Series(
                pd.to_numeric(data['close'], errors='coerce').values,
                index=pd.to_datetime(data['date']),
            )
            frames[code] = s[~s.index.duplicated(keep='last')]
        if i % 50 == 0 or i == n:
            logging.info(f"[financial] 取价进度 {i}/{n}")
    if not frames:
        return pd.DataFrame()
    px = pd.DataFrame(frames).sort_index()
    px = px.where(px > 0)
    return px


def compute_forward_returns_financial(panel: pd.DataFrame, px: pd.DataFrame,
                                      horizon: int, lag_days: int = 60) -> pd.DataFrame:
    """
    财务因子前向收益：报告期 report_date 后滞后 lag_days 自然日（披露滞后，防前视），
    取该日起第一个交易日 t0 与第 horizon 个交易日后的收盘价计算收益。
    返回长表 [date(report_date), code, fwd_ret]。
    """
    if px.empty:
        return pd.DataFrame(columns=['date', 'code', 'fwd_ret'])
    trade_idx = px.index  # DatetimeIndex 升序
    rows = []
    for report_date, g in panel.groupby('date'):
        avail = report_date + pd.Timedelta(days=lag_days)
        pos = trade_idx.searchsorted(avail, side='left')
        if pos >= len(trade_idx) or pos + horizon >= len(trade_idx):
            continue
        d0, d1 = trade_idx[pos], trade_idx[pos + horizon]
        p0, p1 = px.loc[d0], px.loc[d1]
        ret = (p1 / p0 - 1.0).replace([float('inf'), float('-inf')], pd.NA)
        codes = g['code'].unique()
        sub = ret.reindex(codes).dropna()
        for code, v in sub.items():
            rows.append((report_date, code, float(v)))
    return pd.DataFrame(rows, columns=['date', 'code', 'fwd_ret'])



# ---------------------------------------------------------------------------
# 验证主流程
# ---------------------------------------------------------------------------

def _rebalance_dates(panel: pd.DataFrame, rebalance: int) -> list:
    dates = sorted(panel['date'].unique())
    return dates[::max(1, rebalance)]


def validate_factor_ic(panel: pd.DataFrame, fwd: pd.DataFrame, rebalance: int) -> pd.DataFrame:
    """每个连续因子的 IC 汇总（横截面 IC 时序 → 统计量）。"""
    fwd_map = {d: g.set_index('code')['fwd_ret'] for d, g in fwd.groupby('date')}
    factors = sorted(f for f in sc.FACTOR_DIRECTIONS if f in panel.columns)
    rdates = _rebalance_dates(panel, rebalance)

    ic_lists: dict[str, list[float]] = {f: [] for f in factors}
    for d in rdates:
        ret = fwd_map.get(d)
        if ret is None or ret.empty:
            continue
        snap = panel[panel['date'] == d].set_index('code')
        common = snap.index.intersection(ret.index)
        if len(common) < 5:
            continue
        snap = snap.loc[common]
        ret_d = ret.loc[common]
        for f in factors:
            direction = sc.FACTOR_DIRECTIONS[f]
            fac = sc.directionalize(snap[f], direction)
            ic_lists[f].append(sc.spearman_ic(fac, ret_d))

    rows = []
    for f in factors:
        s = sc.ic_summary(ic_lists[f])
        s['factor'] = f
        s['direction'] = sc.FACTOR_DIRECTIONS[f]
        s['effective'] = bool(abs(s['ic_mean']) > 0.03) if s['n'] else False
        rows.append(s)
    cols = ['factor', 'direction', 'n', 'ic_mean', 'ic_std', 'ir', 't_stat', 'ic_win_rate', 'effective']
    return pd.DataFrame(rows, columns=cols).sort_values('ic_mean', ascending=False, key=lambda c: c.abs())


def validate_dimension_ic(panel: pd.DataFrame, fwd: pd.DataFrame, rebalance: int,
                          weights: dict[str, float] | None = None) -> pd.DataFrame:
    """每个维度绝对分 Q_d 的 IC 汇总。"""
    fwd_map = {d: g.set_index('code')['fwd_ret'] for d, g in fwd.groupby('date')}
    weights = weights or sc.DEFAULT_WEIGHTS
    dims = [d for d in weights if d in sc.DIMENSION_FAMILIES]
    rdates = _rebalance_dates(panel, rebalance)

    ic_lists: dict[str, list[float]] = {d: [] for d in dims}
    for d in rdates:
        ret = fwd_map.get(d)
        if ret is None or ret.empty:
            continue
        snap = panel[panel['date'] == d].set_index('code')
        common = snap.index.intersection(ret.index)
        if len(common) < 5:
            continue
        snap = snap.loc[common]
        ret_d = ret.loc[common]
        for dim in dims:
            q = sc.compute_dimension_q(snap, dim)
            if q is not None:
                ic_lists[dim].append(sc.spearman_ic(q, ret_d))

    rows = []
    for dim in dims:
        s = sc.ic_summary(ic_lists[dim])
        s['dimension'] = dim
        s['weight'] = weights[dim]
        s['effective'] = bool(abs(s['ic_mean']) > 0.03) if s['n'] else False
        rows.append(s)
    cols = ['dimension', 'weight', 'n', 'ic_mean', 'ic_std', 'ir', 't_stat', 'ic_win_rate', 'effective']
    return pd.DataFrame(rows, columns=cols)


def validate_layered_backtest(panel: pd.DataFrame, fwd: pd.DataFrame,
                              rebalance: int, n_groups: int = 5,
                              weights: dict[str, float] | None = None) -> dict:
    fwd_map = {d: g.set_index('code')['fwd_ret'] for d, g in fwd.groupby('date')}
    rdates = _rebalance_dates(panel, rebalance)
    weights = weights or sc.DEFAULT_WEIGHTS

    grp_returns: dict[int, list[float]] = {i: [] for i in range(n_groups)}
    mono_list: list[float] = []
    # 每期最少样本：理想为每组 5 只（n_groups*5）；样本不足时放宽到每组 2 只，
    # 避免小样本（如冒烟测试）下分层结果全空。正式全市场跑会远超该下限。
    min_per_period = n_groups * 2
    for d in rdates:
        ret = fwd_map.get(d)
        if ret is None or ret.empty:
            continue
        snap = panel[panel['date'] == d].set_index('code')
        common = snap.index.intersection(ret.index)
        if len(common) < min_per_period:
            continue
        snap = snap.loc[common]
        ret_d = ret.loc[common]
        q, _ = sc.compute_quality_score(snap, weights=weights)
        layer = sc.layered_returns(q, ret_d, n_groups)
        if not layer:
            continue
        for i, v in layer.items():
            grp_returns[i].append(v)
        mono_list.append(sc.monotonicity(layer))

    avg = {i: (float(pd.Series(v).mean()) if v else float('nan')) for i, v in grp_returns.items()}
    top, bottom = avg.get(n_groups - 1, float('nan')), avg.get(0, float('nan'))
    return {
        'group_avg_return': avg,
        'top_minus_bottom': (top - bottom) if pd.notna(top) and pd.notna(bottom) else float('nan'),
        'avg_monotonicity': float(pd.Series(mono_list).mean()) if mono_list else float('nan'),
        'periods': len(mono_list),
    }


def derive_auto_weights_from_dimension_ic(panel: pd.DataFrame, fwd: pd.DataFrame,
                                          rebalance: int,
                                          base_weights: dict[str, float] | None = None) -> tuple[dict[str, float], pd.DataFrame]:
    """M1.1：按维度 |IC| 自动估计权重，并与基准权重做平滑混合。"""
    base = dict(base_weights or sc.DEFAULT_WEIGHTS)
    dim_ic = validate_dimension_ic(panel, fwd, rebalance, weights=base)

    raw: dict[str, float] = {}
    for _, row in dim_ic.iterrows():
        dim = row['dimension']
        n = row['n']
        ic = row['ic_mean']
        if n and pd.notna(ic):
            raw[dim] = abs(float(ic))

    usable = [d for d, v in raw.items() if v > 0]
    if not usable:
        return base, dim_ic

    raw_sum = sum(raw[d] for d in usable)
    base_sum = sum(base.get(d, 0.0) for d in usable)

    blended: dict[str, float] = {}
    for d in usable:
        ic_part = raw[d] / raw_sum if raw_sum > 0 else 1.0 / len(usable)
        base_part = (base.get(d, 0.0) / base_sum) if base_sum > 0 else 1.0 / len(usable)
        # 以数据驱动为主（70%），保留基准先验（30%）抑制小样本噪声
        blended[d] = 0.7 * ic_part + 0.3 * base_part

    total = sum(blended.values())
    if total <= 0:
        return base, dim_ic
    weights = {d: (blended.get(d, 0.0) / total) for d in base}
    return weights, dim_ic


def _normalize_on_keys(values: dict[str, float], keys: list[str]) -> dict[str, float]:
    s = sum(max(0.0, float(values.get(k, 0.0))) for k in keys)
    if s <= 0:
        return {k: 0.0 for k in keys}
    return {k: max(0.0, float(values.get(k, 0.0))) / s for k in keys}


def _apply_floor_cap(weights: dict[str, float], keys: list[str], floor: float, cap: float) -> dict[str, float]:
    """在有效维度上施加权重地板/上限并重归一。"""
    if not keys:
        return weights
    k = len(keys)
    floor = max(0.0, min(float(floor), 0.20))
    cap = max(0.20, min(float(cap), 1.0))
    if floor * k >= 1.0:
        floor = 0.99 / k

    # 先做地板
    norm = _normalize_on_keys(weights, keys)
    scaled = {d: floor + (1.0 - floor * k) * norm[d] for d in keys}

    # 再做上限并把超出的质量按比例分配到未触顶维度
    capped = dict(scaled)
    overflow = 0.0
    for d in keys:
        if capped[d] > cap:
            overflow += capped[d] - cap
            capped[d] = cap
    if overflow > 0:
        free = [d for d in keys if capped[d] < cap]
        if free:
            room_sum = sum(cap - capped[d] for d in free)
            if room_sum > 0:
                for d in free:
                    add = overflow * ((cap - capped[d]) / room_sum)
                    capped[d] += add

    # 最后归一到 1（仅 active keys）
    final = _normalize_on_keys(capped, keys)
    out = dict(weights)
    for d in weights:
        out[d] = final.get(d, 0.0)
    return out


def derive_auto_weights_m12(panel: pd.DataFrame,
                            fwd_short: pd.DataFrame,
                            fwd_long: pd.DataFrame,
                            rebalance: int,
                            base_weights: dict[str, float] | None = None,
                            floor: float = 0.08,
                            cap: float = 0.55) -> tuple[dict[str, float], pd.DataFrame, pd.DataFrame]:
    """M1.2：短中窗联合 + 一致性惩罚 + 地板/上限约束，提升权重稳健性。"""
    base = dict(base_weights or sc.DEFAULT_WEIGHTS)
    short_ic = validate_dimension_ic(panel, fwd_short, rebalance, weights=base)
    long_ic = validate_dimension_ic(panel, fwd_long, rebalance, weights=base)
    short_map = {r['dimension']: r for _, r in short_ic.iterrows()}
    long_map = {r['dimension']: r for _, r in long_ic.iterrows()}

    raw: dict[str, float] = {}
    active: list[str] = []
    for dim in base:
        s = short_map.get(dim)
        l = long_map.get(dim)
        if s is None:
            continue
        ic_s = float(s['ic_mean']) if pd.notna(s['ic_mean']) else 0.0
        wr_s = float(s['ic_win_rate']) if pd.notna(s['ic_win_rate']) else 0.5
        ic_l = float(l['ic_mean']) if (l is not None and pd.notna(l['ic_mean'])) else 0.0
        wr_l = float(l['ic_win_rate']) if (l is not None and pd.notna(l['ic_win_rate'])) else 0.5

        # 一致性：短中窗同向=1.0，任一接近0=0.6，反向=0.3
        if abs(ic_s) < 0.01 or abs(ic_l) < 0.01:
            consistency = 0.6
        elif ic_s * ic_l > 0:
            consistency = 1.0
        else:
            consistency = 0.3

        # 稳定性：胜率越高，放大越多；最低不低于 0.5
        stability = max(0.5, min(1.0, (wr_s + wr_l) / 2.0))

        score = (0.7 * abs(ic_s) + 0.3 * abs(ic_l)) * consistency * stability
        if score > 0:
            raw[dim] = score
            active.append(dim)

    if not active:
        return base, short_ic, long_ic

    raw_norm = _normalize_on_keys(raw, active)
    base_sum = sum(base.get(d, 0.0) for d in active)
    base_norm = {d: (base.get(d, 0.0) / base_sum if base_sum > 0 else 1.0 / len(active)) for d in active}

    # 数据驱动 75% + 先验 25%
    mixed = {d: 0.75 * raw_norm[d] + 0.25 * base_norm[d] for d in active}
    full = {d: mixed.get(d, 0.0) for d in base}
    full = _apply_floor_cap(full, active, floor=floor, cap=cap)
    return full, short_ic, long_ic


def derive_auto_weights_m15(panel: pd.DataFrame,
                            fwd_short: pd.DataFrame,
                            fwd_long: pd.DataFrame,
                            rebalance: int,
                            base_weights: dict[str, float] | None = None,
                            floor: float = 0.06,
                            cap: float = 0.45,
                            lock_lower: float = 0.85,
                            lock_upper: float = 1.10) -> tuple[dict[str, float], pd.DataFrame, pd.DataFrame]:
    """M1.5：在 M1.2 基础上加入相对权重锁定与分位上限，抑制权重过度集中。"""
    base = dict(base_weights or sc.DEFAULT_WEIGHTS)
    w, short_ic, long_ic = derive_auto_weights_m12(panel, fwd_short, fwd_long, rebalance, base, floor, cap)
    active = [d for d in base if float(w.get(d, 0.0)) > 0]
    if not active:
        return w, short_ic, long_ic

    lock_rank_caps = [0.40, 0.30, 0.20] if len(active) >= 3 else [0.50, 0.35]
    locked = sc.constrain_relative_weights(
        w,
        active,
        anchor=base,
        lock_lower=lock_lower,
        lock_upper=lock_upper,
        rank_caps=lock_rank_caps,
    )
    return locked, short_ic, long_ic


def derive_auto_weights_m16(panel: pd.DataFrame,
                            fwd_short: pd.DataFrame,
                            fwd_long: pd.DataFrame,
                            rebalance: int,
                            base_weights: dict[str, float] | None = None,
                            floor: float = 0.08,
                            cap: float = 0.45,
                            lock_lower: float = 0.0,
                            lock_upper: float = 2.00) -> tuple[dict[str, float], pd.DataFrame, pd.DataFrame]:
    """M1.6：轻约束版，仅保留温和上界约束，不设置下界锁定与分位硬帽。"""
    base = dict(base_weights or sc.DEFAULT_WEIGHTS)
    w, short_ic, long_ic = derive_auto_weights_m12(panel, fwd_short, fwd_long, rebalance, base, floor, cap)
    active = [d for d in base if float(w.get(d, 0.0)) > 0]
    if not active:
        return w, short_ic, long_ic

    locked = sc.constrain_relative_weights(
        w,
        active,
        anchor=base,
        lock_lower=lock_lower,
        lock_upper=lock_upper,
        rank_caps=None,
    )
    return locked, short_ic, long_ic


def _subset_panel_and_fwd(panel: pd.DataFrame, fwd: pd.DataFrame,
                          start_date=None, end_date=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """按 date 范围切分 panel/fwd（闭区间）。"""
    p = panel
    r = fwd
    if start_date is not None:
        p = p[p['date'] >= start_date]
        r = r[r['date'] >= start_date]
    if end_date is not None:
        p = p[p['date'] <= end_date]
        r = r[r['date'] <= end_date]
    return p.reset_index(drop=True), r.reset_index(drop=True)


def _blend_weights(a: dict[str, float], b: dict[str, float], alpha: float) -> dict[str, float]:
    keys = sorted(set(a) | set(b))
    mixed = {k: alpha * float(a.get(k, 0.0)) + (1.0 - alpha) * float(b.get(k, 0.0)) for k in keys}
    s = sum(max(0.0, v) for v in mixed.values())
    if s <= 0:
        return {k: 0.0 for k in keys}
    return {k: max(0.0, mixed[k]) / s for k in keys}


def _safe_float(x, default=-1e9):
    return float(x) if pd.notna(x) else float(default)


def derive_auto_weights_m13(panel: pd.DataFrame,
                            fwd_short: pd.DataFrame,
                            fwd_long: pd.DataFrame,
                            rebalance: int,
                            base_weights: dict[str, float] | None = None,
                            floor: float = 0.08,
                            cap: float = 0.55,
                            split_date: str | None = None,
                            long_guard: float = 0.0) -> tuple[dict[str, float], pd.DataFrame, pd.DataFrame, dict]:
    """M1.3：时间切分(训练/验证) + 长窗保底约束，稳健选择权重。"""
    base = dict(base_weights or sc.DEFAULT_WEIGHTS)
    dates = sorted(pd.to_datetime(panel['date'].unique()))
    if len(dates) < 4:
        w, ic_s, ic_l = derive_auto_weights_m12(panel, fwd_short, fwd_long, rebalance, base, floor, cap)
        info = {'split_date': None, 'selected_alpha': 1.0, 'valid_short_tb': float('nan'), 'valid_long_tb': float('nan')}
        return w, ic_s, ic_l, info

    if split_date:
        split = pd.to_datetime(split_date)
    else:
        idx = max(1, int(len(dates) * 0.67) - 1)
        split = dates[idx]

    p_train, f_train_s = _subset_panel_and_fwd(panel, fwd_short, end_date=split)
    _, f_train_l = _subset_panel_and_fwd(panel, fwd_long, end_date=split)
    p_valid, f_valid_s = _subset_panel_and_fwd(panel, fwd_short, start_date=split + pd.Timedelta(days=1))
    _, f_valid_l = _subset_panel_and_fwd(panel, fwd_long, start_date=split + pd.Timedelta(days=1))

    if p_train.empty or p_valid.empty:
        w, ic_s, ic_l = derive_auto_weights_m12(panel, fwd_short, fwd_long, rebalance, base, floor, cap)
        info = {'split_date': split.strftime('%Y-%m-%d'), 'selected_alpha': 1.0,
                'valid_short_tb': float('nan'), 'valid_long_tb': float('nan')}
        return w, ic_s, ic_l, info

    w_train, ic_s, ic_l = derive_auto_weights_m12(p_train, f_train_s, f_train_l, rebalance, base, floor, cap)

    candidates = [round(x, 1) for x in [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.0]]
    rows = []
    for a in candidates:
        w = _blend_weights(w_train, base, a)
        lay_s = validate_layered_backtest(p_valid, f_valid_s, rebalance, n_groups=5, weights=w)
        lay_l = validate_layered_backtest(p_valid, f_valid_l, rebalance, n_groups=5, weights=w)
        row = {
            'alpha': a,
            'short_tb': _safe_float(lay_s.get('top_minus_bottom')),
            'long_tb': _safe_float(lay_l.get('top_minus_bottom')),
            'short_mono': _safe_float(lay_s.get('avg_monotonicity'), default=-1.0),
            'long_mono': _safe_float(lay_l.get('avg_monotonicity'), default=-1.0),
            'w': w,
        }
        rows.append(row)

    feasible = [r for r in rows if r['long_tb'] >= long_guard]
    if feasible:
        best = max(feasible, key=lambda r: (r['short_tb'], r['short_mono'], r['long_mono']))
    else:
        # 无法满足长窗保底时，优先“尽量减小长窗负值”再看短窗表现
        best = max(rows, key=lambda r: (r['long_tb'], r['short_tb'], r['short_mono']))

    info = {
        'split_date': split.strftime('%Y-%m-%d'),
        'selected_alpha': best['alpha'],
        'valid_short_tb': best['short_tb'],
        'valid_long_tb': best['long_tb'],
        'valid_short_mono': best['short_mono'],
        'valid_long_mono': best['long_mono'],
    }
    return best['w'], ic_s, ic_l, info

def derive_auto_weights_by_industry(panel: pd.DataFrame,
                                    fwd_short: pd.DataFrame,
                                    fwd_long: pd.DataFrame,
                                    rebalance: int,
                                    base_weights: dict[str, float] | None = None,
                                    floor: float = 0.08,
                                    cap: float = 0.55) -> tuple[dict[str, dict[str, float]], dict]:
    """
    M1.4：按行业分组，为每个行业单独校准权重，发现行业特异信号。
    
    返回：
    - industry_weights: {industry_name -> {dimension -> weight}}
    - industry_stats: {industry_name -> {'n_stocks': int, 'periods': int}}
    """
    if 'industry' not in panel.columns:
        logging.warning("[M1.4] 面板无 industry 列，返回全球权重")
        w, _, _ = derive_auto_weights_m12(panel, fwd_short, fwd_long, rebalance, base_weights, floor, cap)
        all_ind = panel['code'].nunique()
        return {'_global': w}, {'_global': {'n_stocks': all_ind, 'periods': len(pd.to_datetime(panel['date']).unique())}}

    base = dict(base_weights or sc.DEFAULT_WEIGHTS)
    industries = sorted(panel['industry'].dropna().unique())
    
    # 仅用样本充足的行业（≥10只股票、≥3个报告期）
    valid_inds = []
    ind_stats = {}
    for ind in industries:
        ind_panel = panel[panel['industry'] == ind]
        n_stocks = ind_panel['code'].nunique()
        n_periods = len(pd.to_datetime(ind_panel['date']).unique())
        if n_stocks >= 10 and n_periods >= 3:
            valid_inds.append(ind)
            ind_stats[ind] = {'n_stocks': n_stocks, 'periods': n_periods}

    if not valid_inds:
        logging.warning(f"[M1.4] 无有效行业（≥10股、≥3期），样本: {industries}")
        w, _, _ = derive_auto_weights_m12(panel, fwd_short, fwd_long, rebalance, base_weights, floor, cap)
        return {'_global': w}, {'_global': {'n_stocks': panel['code'].nunique(), 'periods': len(pd.to_datetime(panel['date']).unique())}}

    industry_weights = {}
    for ind in valid_inds:
        ind_panel = panel[panel['industry'] == ind]
        ind_fwd_s = fwd_short[fwd_short['code'].isin(ind_panel['code'].unique())]
        ind_fwd_l = fwd_long[fwd_long['code'].isin(ind_panel['code'].unique())]
        
        try:
            w, _, _ = derive_auto_weights_m12(ind_panel, ind_fwd_s, ind_fwd_l, rebalance, base_weights, floor, cap)
            industry_weights[ind] = w
        except Exception as e:
            logging.warning(f"[M1.4] 行业 {ind} 权重计算失败: {e}，使用基准权重")
            industry_weights[ind] = base

    # 兜底：样本不足行业用全球权重
    global_w, _, _ = derive_auto_weights_m12(panel, fwd_short, fwd_long, rebalance, base_weights, floor, cap)
    for ind in industries:
        if ind not in industry_weights:
            industry_weights[ind] = global_w

    return industry_weights, ind_stats


def apply_weights_by_industry(panel: pd.DataFrame, industry_weights: dict[str, dict[str, float]]) -> dict[str, float]:
    """
    在面板级别应用行业权重：每只股票使用其行业权重计算质量分。
    返回标准权重（加权平均），用于报告。
    """
    if not industry_weights or '_global' in industry_weights:
        # 没有行业权重或用全球权重模式
        return industry_weights.get('_global', sc.DEFAULT_WEIGHTS)

    # 加权平均：按行业样本占比聚合
    agg = {d: [] for d in sc.DEFAULT_WEIGHTS}
    for ind, w in industry_weights.items():
        n = (panel['industry'] == ind).sum()
        if n > 0:
            for d in agg:
                agg[d].append((w.get(d, 0.0), n))
    
    if not agg[list(agg.keys())[0]]:
        return sc.DEFAULT_WEIGHTS
    
    total_weight = sum(n for _, n in agg[list(agg.keys())[0]])
    merged = {}
    for d in agg:
        if agg[d]:
            merged[d] = sum(w * n for w, n in agg[d]) / total_weight if total_weight > 0 else 1.0 / len(agg)
    return merged

# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------

def _fmt(x, p=4):
    return f"{x:.{p}f}" if isinstance(x, (int, float)) and pd.notna(x) else 'nan'


def _report_layered_only(h: int, layered: dict) -> dict:
    """仅打印分层结果（用于 M1.4）。"""
    print(f"\n----- 未来 {h} 日收益 -----")
    print("\n[分层回测] 各层平均未来收益（0=最低分层 … 高=最高分层）")
    for i in sorted(layered['group_avg_return']):
        print(f"  层{i}: {_fmt(layered['group_avg_return'][i])}")
    print(f"  Top−Bottom = {_fmt(layered['top_minus_bottom'])}  "
          f"平均单调性 = {_fmt(layered['avg_monotonicity'])}  样本期={layered['periods']}")
    return layered


def _report_horizon(panel: pd.DataFrame, fwd: pd.DataFrame, h: int,
                    rebalance: int, n_groups: int,
                    weights: dict[str, float] | None = None) -> dict:
    """计算并打印单个未来收益窗口的 IC / 维度 / 分层结果。"""
    factor_ic = validate_factor_ic(panel, fwd, rebalance)
    dim_ic = validate_dimension_ic(panel, fwd, rebalance, weights=weights)
    layered = validate_layered_backtest(panel, fwd, rebalance, n_groups, weights=weights)

    print(f"\n----- 未来 {h} 日收益 -----")
    print("\n[单因子 IC]（按 |mean IC| 降序）")
    with pd.option_context('display.max_rows', None, 'display.width', 160,
                           'display.float_format', lambda v: _fmt(v)):
        print(factor_ic.to_string(index=False))
    print("\n[维度 IC]")
    with pd.option_context('display.float_format', lambda v: _fmt(v)):
        print(dim_ic.to_string(index=False))
    print("\n[分层回测] 各层平均未来收益（0=最低分层 … 高=最高分层）")
    for i in sorted(layered['group_avg_return']):
        print(f"  层{i}: {_fmt(layered['group_avg_return'][i])}")
    print(f"  Top−Bottom = {_fmt(layered['top_minus_bottom'])}  "
          f"平均单调性 = {_fmt(layered['avg_monotonicity'])}  样本期={layered['periods']}")
    return {'factor_ic': factor_ic, 'dimension_ic': dim_ic, 'layered': layered}


def run(start_date: str, end_date: str, horizons=(5, 10, 20),
        rebalance: int = 5, n_groups: int = 5, source: str = 'selection',
        max_codes: int = 0, lag_days: int = 60, pool: str = 'all',
    weight_template: str = 'm1_auto_ic_m12', auto_horizon: int = 20,
        auto_long_horizon: int = 60, auto_floor: float = 0.08,
        auto_cap: float = 0.55, auto_split_date: str | None = None,
        auto_long_guard: float = 0.0) -> dict:
    weights = None if weight_template in ('m1_auto_ic', 'm1_auto_ic_m12', 'm1_auto_ic_m13', 'm1_auto_ic_m14', 'm1_auto_ic_m15', 'm1_auto_ic_m16') else sc.resolve_weight_template(weight_template)
    if source == 'financial':
        return _run_financial(start_date, end_date, horizons, n_groups, max_codes, lag_days,
                      pool, weights, weight_template, auto_horizon,
                              auto_long_horizon, auto_floor, auto_cap,
                              auto_split_date, auto_long_guard)

    panel = load_selection_panel(start_date, end_date, source=source)
    if panel.empty:
        print(f"[M0] 区间 {start_date}~{end_date} 表 {source} 无数据，请确认数据已回填。")
        return {}

    n_dates = panel['date'].nunique()
    n_codes = panel['code'].nunique()
    n_factors = sum(1 for f in sc.FACTOR_DIRECTIONS if f in panel.columns)
    print("=" * 78)
    print(f"[M0] 因子有效性验证  数据源={_SOURCE_TABLES[source]['name']}  "
          f"区间={start_date}~{end_date}  交易日={n_dates}  股票数≈{n_codes}  可用因子={n_factors}")
    print(f"      调仓步长={rebalance}日  未来收益窗口={list(horizons)}  分层={n_groups}  模板={weight_template}")
    print("=" * 78)

    if weight_template == 'm1_auto_ic':
        train_h = auto_horizon if auto_horizon in horizons else min(horizons)
        fwd_train = compute_forward_returns(panel, train_h)
        weights, train_dim_ic = derive_auto_weights_from_dimension_ic(panel, fwd_train, rebalance, sc.DEFAULT_WEIGHTS)
        w_show = ', '.join(f"{k}={weights[k]:.3f}" for k in sorted(weights, key=weights.get, reverse=True) if weights[k] > 0)
        print(f"[M1.1] auto-ic 训练窗口={train_h}日  自动权重: {w_show}")
        with pd.option_context('display.float_format', lambda v: _fmt(v)):
            print("[M1.1] 训练窗维度IC:")
            print(train_dim_ic.to_string(index=False))
        industry_weights = None
    elif weight_template == 'm1_auto_ic_m12':
        h_s = auto_horizon if auto_horizon in horizons else min(horizons)
        h_l = auto_long_horizon if auto_long_horizon in horizons else max(horizons)
        fwd_s = compute_forward_returns(panel, h_s)
        fwd_l = compute_forward_returns(panel, h_l)
        weights, ic_s, ic_l = derive_auto_weights_m12(panel, fwd_s, fwd_l, rebalance,
                                                      sc.DEFAULT_WEIGHTS, auto_floor, auto_cap)
        w_show = ', '.join(f"{k}={weights[k]:.3f}" for k in sorted(weights, key=weights.get, reverse=True) if weights[k] > 0)
        print(f"[M1.2] auto-ic 训练窗口=({h_s},{h_l})  floor={auto_floor:.3f} cap={auto_cap:.3f}  自动权重: {w_show}")
        with pd.option_context('display.float_format', lambda v: _fmt(v)):
            print("[M1.2] 短窗维度IC:")
            print(ic_s.to_string(index=False))
            print("[M1.2] 长窗维度IC:")
            print(ic_l.to_string(index=False))
        industry_weights = None
    elif weight_template == 'm1_auto_ic_m15':
        h_s = auto_horizon if auto_horizon in horizons else min(horizons)
        h_l = auto_long_horizon if auto_long_horizon in horizons else max(horizons)
        fwd_s = compute_forward_returns(panel, h_s)
        fwd_l = compute_forward_returns(panel, h_l)
        weights, ic_s, ic_l = derive_auto_weights_m15(
            panel, fwd_s, fwd_l, rebalance, sc.DEFAULT_WEIGHTS,
            max(auto_floor, 0.10), min(auto_cap, 0.40), lock_lower=0.85, lock_upper=1.10
        )
        w_show = ', '.join(f"{k}={weights[k]:.3f}" for k in sorted(weights, key=weights.get, reverse=True) if weights[k] > 0)
        print(f"[M1.5] auto-ic 训练窗口=({h_s},{h_l})  floor={max(auto_floor, 0.10):.3f} cap={min(auto_cap, 0.40):.3f}  lock=[0.85,1.10] 自动权重: {w_show}")
        with pd.option_context('display.float_format', lambda v: _fmt(v)):
            print("[M1.5] 短窗维度IC:")
            print(ic_s.to_string(index=False))
            print("[M1.5] 长窗维度IC:")
            print(ic_l.to_string(index=False))
        industry_weights = None
    elif weight_template == 'm1_auto_ic_m16':
        h_s = auto_horizon if auto_horizon in horizons else min(horizons)
        h_l = auto_long_horizon if auto_long_horizon in horizons else max(horizons)
        fwd_s = compute_forward_returns(panel, h_s)
        fwd_l = compute_forward_returns(panel, h_l)
        weights, ic_s, ic_l = derive_auto_weights_m16(
            panel, fwd_s, fwd_l, rebalance, sc.DEFAULT_WEIGHTS,
            auto_floor, min(auto_cap, 0.45), lock_lower=0.0, lock_upper=2.00
        )
        w_show = ', '.join(f"{k}={weights[k]:.3f}" for k in sorted(weights, key=weights.get, reverse=True) if weights[k] > 0)
        print(f"[M1.6] auto-ic 训练窗口=({h_s},{h_l})  floor={auto_floor:.3f} cap={min(auto_cap, 0.45):.3f}  lock=[0.00,2.00] 自动权重: {w_show}")
        with pd.option_context('display.float_format', lambda v: _fmt(v)):
            print("[M1.6] 短窗维度IC:")
            print(ic_s.to_string(index=False))
            print("[M1.6] 长窗维度IC:")
            print(ic_l.to_string(index=False))
        industry_weights = None
    elif weight_template == 'm1_auto_ic_m13':
        h_s = auto_horizon if auto_horizon in horizons else min(horizons)
        h_l = auto_long_horizon if auto_long_horizon in horizons else max(horizons)
        fwd_s = compute_forward_returns(panel, h_s)
        fwd_l = compute_forward_returns(panel, h_l)
        weights, ic_s, ic_l, info = derive_auto_weights_m13(
            panel, fwd_s, fwd_l, rebalance, sc.DEFAULT_WEIGHTS,
            auto_floor, auto_cap, auto_split_date, auto_long_guard
        )
        w_show = ', '.join(f"{k}={weights[k]:.3f}" for k in sorted(weights, key=weights.get, reverse=True) if weights[k] > 0)
        print(f"[M1.3] auto-ic split={info['split_date']} alpha={info['selected_alpha']} guard={auto_long_guard:.4f} 自动权重: {w_show}")
        print(f"[M1.3] valid: short_tb={_fmt(info['valid_short_tb'])} long_tb={_fmt(info['valid_long_tb'])} "
              f"short_mono={_fmt(info['valid_short_mono'])} long_mono={_fmt(info['valid_long_mono'])}")
        with pd.option_context('display.float_format', lambda v: _fmt(v)):
            print("[M1.3] 训练窗短窗维度IC:")
            print(ic_s.to_string(index=False))
            print("[M1.3] 训练窗长窗维度IC:")
            print(ic_l.to_string(index=False))
        industry_weights = None
    elif weight_template == 'm1_auto_ic_m14':
        h_s = auto_horizon if auto_horizon in horizons else min(horizons)
        h_l = auto_long_horizon if auto_long_horizon in horizons else max(horizons)
        fwd_s = compute_forward_returns(panel, h_s)
        fwd_l = compute_forward_returns(panel, h_l)
        industry_weights, ind_stats = derive_auto_weights_by_industry(
            panel, fwd_s, fwd_l, rebalance, sc.DEFAULT_WEIGHTS, auto_floor, auto_cap
        )
        weights = apply_weights_by_industry(panel, industry_weights)
        w_show = ', '.join(f"{k}={weights[k]:.3f}" for k in sorted(weights, key=weights.get, reverse=True) if weights[k] > 0)
        print(f"[M1.4] 行业感知权重校准完成。聚合全局权重: {w_show}")
        if ind_stats and len(ind_stats) > 0:
            print(f"[M1.4] 有效行业数: {len(ind_stats)}")
            for ind, stats in sorted(ind_stats.items()):
                ind_w = industry_weights.get(ind, {})
                ind_w_show = ', '.join(f"{k}={v:.3f}" for k, v in sorted(ind_w.items(), key=lambda x: x[1], reverse=True) if v > 0)[:60]
                print(f"  {ind:8s}: {stats['n_stocks']:4d} 股, {stats['periods']:3d} 期 | {ind_w_show}")

    result: dict = {'panel_dates': n_dates, 'panel_codes': n_codes, 'horizons': {}}
    for h in horizons:
        fwd = compute_forward_returns(panel, h)
        if weight_template == 'm1_auto_ic_m14':
            layered = validate_layered_backtest_with_industry_weights(panel, fwd, rebalance, n_groups, industry_weights)
            result['horizons'][h] = _report_layered_only(h, layered)
        else:
            result['horizons'][h] = _report_horizon(panel, fwd, h, rebalance, n_groups, weights=weights)
    print("\n" + "=" * 78)
    print("[M0] 验证完成。判定参考：|mean IC|>0.03 视为有效；分层应近似单调且 Top−Bottom>0。")
    print("=" * 78)
    return result


def _run_financial(start_date: str, end_date: str, horizons, n_groups: int,
                   max_codes: int, lag_days: int, pool: str = 'all',
                   weights: dict[str, float] | None = None,
                   weight_template: str = 'm1_auto_ic_m12', auto_horizon: int = 20,
                   auto_long_horizon: int = 60, auto_floor: float = 0.08,
                   auto_cap: float = 0.55, auto_split_date: str | None = None,
                   auto_long_guard: float = 0.0) -> dict:
    """financial 源：季频财务因子 + 价格前向收益（PIT 对齐）。调仓=按报告期。"""
    code_filter = None
    pool_codes = None
    pool_note = "全市场"
    if pool == 'selection':
        pool_codes = sorted(load_selection_pool_codes())
        if pool_codes:
            pool_note = f"综合选股池({len(pool_codes)}只)"
            if max_codes and len(pool_codes) > max_codes:
                code_filter = pool_codes[:max_codes]
        else:
            print("[M0] 警告：cn_stock_selection 为空，回退全市场。")
    panel = load_financial_panel(start_date, end_date, code_filter=code_filter)
    if panel.empty:
        print(f"[M0] 区间 {start_date}~{end_date} cn_stock_financial 无合格报告期数据。")
        return {}

    # 目标股票池：pool='selection' 时仅保留原综合选股池出现过的股票
    if pool == 'selection':
        if pool_codes:
            panel = panel[panel['code'].isin(pool_codes)].reset_index(drop=True)
            if panel.empty:
                print("[M0] 综合选股池与 cn_stock_financial 无交集，无法验证。")
                return {}

    codes = sorted(panel['code'].unique())
    if max_codes and len(codes) > max_codes:
        codes = codes[:max_codes]
        panel = panel[panel['code'].isin(codes)].reset_index(drop=True)

    n_periods = panel['date'].nunique()
    n_factors = sum(1 for f in sc.FACTOR_DIRECTIONS if f in panel.columns)
    print("=" * 78)
    print(f"[M0] 因子有效性验证  数据源=cn_stock_financial(季频)  股票池={pool_note}  "
          f"区间={start_date}~{end_date}  报告期={n_periods}  股票数≈{len(codes)}  可用因子={n_factors}")
    print(f"      披露滞后={lag_days}日  未来收益窗口={list(horizons)}(交易日)  分层={n_groups}  模板={weight_template}")
    print("=" * 78)

    # 价格区间：覆盖最早报告期到最晚报告期+滞后+最长窗口缓冲
    px_start = (panel['date'].min()).strftime('%Y%m%d')
    buf_days = lag_days + max(horizons) * 2 + 15
    px_end = (panel['date'].max() + pd.Timedelta(days=buf_days)).strftime('%Y%m%d')
    print(f"[financial] 取价区间 {px_start}~{px_end}，股票 {len(codes)} 只（缓存优先，缺失走外部 API）...")
    px = fetch_price_panel(codes, px_start, px_end)
    if px.empty:
        print("[M0] 价格获取为空，无法计算前向收益。")
        return {}
    print(f"[financial] 价格面板：{px.shape[0]} 交易日 × {px.shape[1]} 股票")

    if weight_template == 'm1_auto_ic':
        train_h = auto_horizon if auto_horizon in horizons else min(horizons)
        fwd_train = compute_forward_returns_financial(panel, px, train_h, lag_days)
        weights, train_dim_ic = derive_auto_weights_from_dimension_ic(panel, fwd_train, 1, sc.DEFAULT_WEIGHTS)
        w_show = ', '.join(f"{k}={weights[k]:.3f}" for k in sorted(weights, key=weights.get, reverse=True) if weights[k] > 0)
        print(f"[M1.1] auto-ic 训练窗口={train_h}日  自动权重: {w_show}")
        with pd.option_context('display.float_format', lambda v: _fmt(v)):
            print("[M1.1] 训练窗维度IC:")
            print(train_dim_ic.to_string(index=False))
        industry_weights = None
    elif weight_template == 'm1_auto_ic_m12':
        h_s = auto_horizon if auto_horizon in horizons else min(horizons)
        h_l = auto_long_horizon if auto_long_horizon in horizons else max(horizons)
        fwd_s = compute_forward_returns_financial(panel, px, h_s, lag_days)
        fwd_l = compute_forward_returns_financial(panel, px, h_l, lag_days)
        weights, ic_s, ic_l = derive_auto_weights_m12(panel, fwd_s, fwd_l, 1,
                                                      sc.DEFAULT_WEIGHTS, auto_floor, auto_cap)
        w_show = ', '.join(f"{k}={weights[k]:.3f}" for k in sorted(weights, key=weights.get, reverse=True) if weights[k] > 0)
        print(f"[M1.2] auto-ic 训练窗口=({h_s},{h_l})  floor={auto_floor:.3f} cap={auto_cap:.3f}  自动权重: {w_show}")
        with pd.option_context('display.float_format', lambda v: _fmt(v)):
            print("[M1.2] 短窗维度IC:")
            print(ic_s.to_string(index=False))
            print("[M1.2] 长窗维度IC:")
            print(ic_l.to_string(index=False))
        industry_weights = None
    elif weight_template == 'm1_auto_ic_m15':
        h_s = auto_horizon if auto_horizon in horizons else min(horizons)
        h_l = auto_long_horizon if auto_long_horizon in horizons else max(horizons)
        fwd_s = compute_forward_returns_financial(panel, px, h_s, lag_days)
        fwd_l = compute_forward_returns_financial(panel, px, h_l, lag_days)
        weights, ic_s, ic_l = derive_auto_weights_m15(
            panel, fwd_s, fwd_l, 1, sc.DEFAULT_WEIGHTS,
            max(auto_floor, 0.10), min(auto_cap, 0.40), lock_lower=0.85, lock_upper=1.10
        )
        w_show = ', '.join(f"{k}={weights[k]:.3f}" for k in sorted(weights, key=weights.get, reverse=True) if weights[k] > 0)
        print(f"[M1.5] auto-ic 训练窗口=({h_s},{h_l})  floor={max(auto_floor, 0.10):.3f} cap={min(auto_cap, 0.40):.3f}  lock=[0.85,1.10] 自动权重: {w_show}")
        with pd.option_context('display.float_format', lambda v: _fmt(v)):
            print("[M1.5] 短窗维度IC:")
            print(ic_s.to_string(index=False))
            print("[M1.5] 长窗维度IC:")
            print(ic_l.to_string(index=False))
        industry_weights = None
    elif weight_template == 'm1_auto_ic_m16':
        h_s = auto_horizon if auto_horizon in horizons else min(horizons)
        h_l = auto_long_horizon if auto_long_horizon in horizons else max(horizons)
        fwd_s = compute_forward_returns_financial(panel, px, h_s, lag_days)
        fwd_l = compute_forward_returns_financial(panel, px, h_l, lag_days)
        weights, ic_s, ic_l = derive_auto_weights_m16(
            panel, fwd_s, fwd_l, 1, sc.DEFAULT_WEIGHTS,
            auto_floor, min(auto_cap, 0.45), lock_lower=0.0, lock_upper=2.00
        )
        w_show = ', '.join(f"{k}={weights[k]:.3f}" for k in sorted(weights, key=weights.get, reverse=True) if weights[k] > 0)
        print(f"[M1.6] auto-ic 训练窗口=({h_s},{h_l})  floor={auto_floor:.3f} cap={min(auto_cap, 0.45):.3f}  lock=[0.00,2.00] 自动权重: {w_show}")
        with pd.option_context('display.float_format', lambda v: _fmt(v)):
            print("[M1.6] 短窗维度IC:")
            print(ic_s.to_string(index=False))
            print("[M1.6] 长窗维度IC:")
            print(ic_l.to_string(index=False))
        industry_weights = None
    elif weight_template == 'm1_auto_ic_m13':
        h_s = auto_horizon if auto_horizon in horizons else min(horizons)
        h_l = auto_long_horizon if auto_long_horizon in horizons else max(horizons)
        fwd_s = compute_forward_returns_financial(panel, px, h_s, lag_days)
        fwd_l = compute_forward_returns_financial(panel, px, h_l, lag_days)
        weights, ic_s, ic_l, info = derive_auto_weights_m13(
            panel, fwd_s, fwd_l, 1, sc.DEFAULT_WEIGHTS,
            auto_floor, auto_cap, auto_split_date, auto_long_guard
        )
        w_show = ', '.join(f"{k}={weights[k]:.3f}" for k in sorted(weights, key=weights.get, reverse=True) if weights[k] > 0)
        print(f"[M1.3] auto-ic split={info['split_date']} alpha={info['selected_alpha']} guard={auto_long_guard:.4f} 自动权重: {w_show}")
        print(f"[M1.3] valid: short_tb={_fmt(info['valid_short_tb'])} long_tb={_fmt(info['valid_long_tb'])} "
              f"short_mono={_fmt(info['valid_short_mono'])} long_mono={_fmt(info['valid_long_mono'])}")
        with pd.option_context('display.float_format', lambda v: _fmt(v)):
            print("[M1.3] 训练窗短窗维度IC:")
            print(ic_s.to_string(index=False))
            print("[M1.3] 训练窗长窗维度IC:")
            print(ic_l.to_string(index=False))
        industry_weights = None

    elif weight_template == 'm1_auto_ic_m14':
        h_s = auto_horizon if auto_horizon in horizons else min(horizons)
        h_l = auto_long_horizon if auto_long_horizon in horizons else max(horizons)
        fwd_s = compute_forward_returns_financial(panel, px, h_s, lag_days)
        fwd_l = compute_forward_returns_financial(panel, px, h_l, lag_days)
        industry_weights, ind_stats = derive_auto_weights_by_industry(
            panel, fwd_s, fwd_l, 1, sc.DEFAULT_WEIGHTS, auto_floor, auto_cap
        )
        weights = apply_weights_by_industry(panel, industry_weights)
        w_show = ', '.join(f"{k}={weights[k]:.3f}" for k in sorted(weights, key=weights.get, reverse=True) if weights[k] > 0)
        print(f"[M1.4] 行业感知权重校准完成。聚合全局权重: {w_show}")
        if ind_stats and len(ind_stats) > 0:
            print(f"[M1.4] 有效行业数: {len(ind_stats)}")
            for ind, stats in sorted(ind_stats.items()):
                ind_w = industry_weights.get(ind, {})
                ind_w_show = ', '.join(f"{k}={v:.3f}" for k, v in sorted(ind_w.items(), key=lambda x: x[1], reverse=True) if v > 0)[:60]
                print(f"  {ind:8s}: {stats['n_stocks']:4d} 股, {stats['periods']:3d} 期 | {ind_w_show}")


    result: dict = {'panel_periods': n_periods, 'panel_codes': len(codes), 'horizons': {}}
    for h in horizons:
        fwd = compute_forward_returns_financial(panel, px, h, lag_days)
        # 报告期即调仓点 → rebalance=1
        if weight_template == 'm1_auto_ic_m14':
            layered = validate_layered_backtest_with_industry_weights(panel, fwd, 1, n_groups, industry_weights)
            result['horizons'][h] = _report_layered_only(h, layered)
        else:
            result['horizons'][h] = _report_horizon(panel, fwd, h, 1, n_groups, weights=weights)
    print("\n" + "=" * 78)
    print("[M0] 验证完成。判定参考：|mean IC|>0.03 视为有效；分层应近似单调且 Top−Bottom>0。")
    print("=" * 78)
    return result


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description='综合选股因子有效性验证（M0）')
    p.add_argument('--start', required=True, help='起始日期 YYYY-MM-DD')
    p.add_argument('--end', required=True, help='结束日期 YYYY-MM-DD')
    p.add_argument('--horizons', default='5,10,20', help='未来收益窗口（逗号分隔），默认 5,10,20')
    p.add_argument('--rebalance', type=int, default=5, help='调仓/采样步长（交易日），默认 5')
    p.add_argument('--groups', type=int, default=5, help='分层组数，默认 5')
    p.add_argument('--source', default='selection', choices=['selection', 'spot', 'financial'],
                   help='数据源：selection(因子全/短) / spot(因子少/长) / financial(季频财务+取价,长历史)')
    p.add_argument('--max-codes', type=int, default=0,
                   help='financial 源限制股票数（0=全市场，取价耗时长；建议先用 300 试跑）')
    p.add_argument('--pool', default='all', choices=['all', 'selection'],
                   help='financial 源目标股票池：all(全市场) / selection(原综合选股池)')
    p.add_argument('--weight-template', default='m1_auto_ic_m12',
                   choices=['balanced', 'm1_selection_pool', 'm1_auto_ic', 'm1_auto_ic_m12', 'm1_auto_ic_m13', 'm1_auto_ic_m14', 'm1_auto_ic_m15', 'm1_auto_ic_m16'],
                   help='Q/评级权重模板：默认 m1_auto_ic_m12；可选 balanced / m1_selection_pool / m1_auto_ic / m1_auto_ic_m12 / m1_auto_ic_m13 / m1_auto_ic_m14 / m1_auto_ic_m15 / m1_auto_ic_m16')
    p.add_argument('--auto-horizon', type=int, default=20,
                   help='m1_auto_ic 训练窗口（交易日），默认 20')
    p.add_argument('--auto-long-horizon', type=int, default=60,
                   help='m1_auto_ic_m12 长窗训练窗口（交易日），默认 60')
    p.add_argument('--auto-floor', type=float, default=0.08,
                   help='m1_auto_ic_m12 每个有效维度权重下限，默认 0.08')
    p.add_argument('--auto-cap', type=float, default=0.55,
                   help='m1_auto_ic_m12 单维度权重上限，默认 0.55')
    p.add_argument('--auto-split-date', default='',
                   help='m1_auto_ic_m13 训练/验证分割日期 YYYY-MM-DD（默认按报告期67%分位）')
    p.add_argument('--auto-long-guard', type=float, default=0.0,
                   help='m1_auto_ic_m13 验证集长窗 Top−Bottom 保底阈值，默认 0.0')
    p.add_argument('--lag', type=int, default=60,
                   help='financial 源披露滞后自然日（防前视），默认 60')
    return p.parse_args(argv)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    args = _parse_args(argv)
    horizons = tuple(int(x) for x in args.horizons.split(',') if x.strip())
    run(args.start, args.end, horizons=horizons, rebalance=args.rebalance,
        n_groups=args.groups, source=args.source,
        max_codes=args.max_codes, lag_days=args.lag, pool=args.pool,
        weight_template=args.weight_template, auto_horizon=args.auto_horizon,
        auto_long_horizon=args.auto_long_horizon,
        auto_floor=args.auto_floor, auto_cap=args.auto_cap,
        auto_split_date=(args.auto_split_date.strip() or None),
        auto_long_guard=args.auto_long_guard)


if __name__ == '__main__':
    main()


#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""composite_alpha_v1 综合选股策略：参数寻优 + Walk-Forward 验证（离线研究脚本）。

严格对齐 document/综合选股策略方案_多因子融合与回测优化_V1.md 的 V1.1 修订：
- 横截面打分（非逐票 check），调用 core/strategy/composite_alpha_v1.py。
- 财务用 PIT 面板（report_date + lag 披露滞后），禁止最新快照前视（见 6.2/6.3）。
- 目标函数**先同量纲归一化再加权**，修复夏普被百分数指标淹没的量纲 Bug（见 5.2）。
- 胜率用**逐笔交易胜率**，并设最少交易笔数硬约束（见 5.2）。
- Walk-Forward：训练期搜参 → 验证期锁参评估（见 5.3）。
- 筹码/资金流在回测期降级（历史无可靠数据），由打分模块自动重归一（见 6.1）。

用法（父目录 .venv）：
    cd C:\\xapproject\\Quantia\\Quantia
    ..\\.venv\\Scripts\\python.exe tools/optimize_composite_alpha.py \
        --start 2022-01-01 --end 2025-12-31 --max-codes 300 --top-k 5
"""
from __future__ import annotations

import argparse
import datetime
import itertools
import json
import logging
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import quantia.lib.envconfig as _cfg  # noqa: F401  触发 .env 加载
from quantia.core.backtest import data_feed
from quantia.core.backtest import risk_metrics
from quantia.core.strategy import composite_alpha_v1 as ca

logging.basicConfig(level=logging.WARNING,
                    format='%(asctime)s %(levelname)s %(message)s')
_LOG = logging.getLogger('optimize_composite')
_LOG.setLevel(logging.INFO)

_OUTPUT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..',
                                            'quantia', 'cache', 'optimize'))
_OUTPUT_FILE = os.path.join(_OUTPUT_DIR, 'composite_alpha_best_params.json')

# 回测期可用的基本面/估值/技术维度（PIT 财务面板字段 + 价格代理）。
# chip/flow 在历史回测期降级（缺列），由打分模块自动重归一。
_BACKTEST_DIMENSION_FACTORS = {
    'fund': [
        ('roe_weight', 'high'),
        ('jroa', 'high'),
        ('sale_gpr', 'high'),
        ('sale_npr', 'high'),
        ('toi_yoy_ratio', 'high'),
        ('netprofit_yoy_ratio', 'high'),
        ('debt_asset_ratio', 'low'),
        ('current_ratio', 'high'),
    ],
    # 估值：PE/PB 代理（现价/PIT eps、现价/PIT bps），越低越便宜（M0 验证：估值反转最强）
    'value': [
        ('pe_proxy', 'low'),
        ('pb_proxy', 'low'),
    ],
    'tech': [
        ('atr_pct', 'low'),
        ('ma20_slope', 'high'),
        ('mom_20', 'high'),
    ],
}

# 参数网格（维度权重 + 门槛 + 持仓 + 大盘择时）。网格数受控（<= max_combos）。
# w_fund/w_value 为基本面/估值权重，tech = 1-w_fund-w_value；regime_ma 为择时均线窗口（0=关）。
_DEFAULT_GRID = {
    'w_fund': [0.4, 0.5],
    'w_value': [0.2, 0.35],
    'quality_gate': [55.0, 70.0],
    'trade_gate': [60.0],
    'top_positions': [15],
    'regime_ma': [0, 60],
}
_FIXED = {
    'lag_days': 60,       # 财务披露滞后（自然日），PIT 防前视
    'rebalance_days': 21,  # 月度调仓
    'min_listing_rows': 120,
    'cost_buy': 0.0005,   # 买入侧成本：佣金+滑点 ≈ 0.05%
    'cost_sell': 0.0015,  # 卖出侧成本：佣金+印花税0.1%+滑点 ≈ 0.15%
}


# ─────────────────────── 数据加载 ───────────────────────

def _load_financial_panel(start, end, max_codes, seed=42):
    from quantia.job.selection_factor_validation_job import load_financial_panel
    hist_start = (pd.Timestamp(start) - pd.DateOffset(years=2)).strftime('%Y-%m-%d')
    panel = load_financial_panel(hist_start, str(end))
    if panel is None or panel.empty:
        return panel
    panel['code'] = panel['code'].astype(str).str.zfill(6)
    panel['date'] = pd.to_datetime(panel['date'])
    # 补充 eps/bps（构造 PE/PB 估值代理，PIT），按 (code, report_date) 合并
    try:
        import quantia.lib.database as mdb
        sql = ("SELECT `code`, `report_date`, `eps`, `bps` FROM `cn_stock_financial` "
               "WHERE `report_date` BETWEEN %s AND %s "
               "AND MONTH(`report_date`) IN (3,6,9,12) AND DAY(`report_date`) IN (30,31)")
        ext = pd.read_sql(sql=sql, con=mdb.engine(), params=(hist_start, str(end)))
        if ext is not None and not ext.empty:
            ext['code'] = ext['code'].astype(str).str.zfill(6)
            ext['report_date'] = pd.to_datetime(ext['report_date'])
            ext = ext.rename(columns={'report_date': 'date'})
            panel = panel.merge(ext, on=['code', 'date'], how='left')
    except Exception as e:
        _LOG.warning(f"eps/bps 补充失败（估值维度将降级）: {e}")
    # 股票池：随机代表性抽样（替代字母序前 N，减少选样偏差）
    if max_codes and max_codes > 0:
        all_codes = sorted(panel['code'].unique())
        if len(all_codes) > max_codes:
            rng = np.random.RandomState(seed)
            pick = set(rng.choice(all_codes, size=max_codes, replace=False).tolist())
            panel = panel[panel['code'].isin(pick)].reset_index(drop=True)
    return panel


class _Regime:
    """大盘择时：基准收盘价与其自身均线比较，判断当日是否处于上升趋势。"""
    def __init__(self, bday_int=None, bclose=None):
        self._d = None if bday_int is None else np.asarray(bday_int, dtype='int64')
        self._c = None if bclose is None else np.asarray(bclose, dtype=float)

    def ok(self, day_int, window):
        """window<=0 关闭择时（恒 True）；数据不足时放行（True）。"""
        if window is None or window <= 0 or self._d is None or len(self._d) == 0:
            return True
        i = int(np.searchsorted(self._d, day_int, side='right')) - 1
        if i < window:
            return True
        ma = float(np.mean(self._c[i - window + 1:i + 1]))
        return float(self._c[i]) >= ma


class _Prices:
    """按 code 缓存价格数组，供技术因子与定价。"""
    def __init__(self):
        self._d = {}

    def add(self, code, df):
        d = df['date'].values.astype('datetime64[D]').astype('int64')
        close = df['close'].to_numpy(dtype=float)
        self._d[code] = (d, close)

    def has(self, code):
        return code in self._d

    def idx_asof(self, code, day_int):
        if code not in self._d:
            return -1
        d, _ = self._d[code]
        return int(np.searchsorted(d, day_int, side='right')) - 1

    def close_at(self, code, i):
        return float(self._d[code][1][i])

    def tech_factors(self, code, i, window=20):
        """返回 (atr_pct, ma20_slope, mom_20)；数据不足返回 None。"""
        if code not in self._d:
            return None
        _, close = self._d[code]
        if i < window * 2:
            return None
        win = close[i - window + 1:i + 1]
        prev = close[i - window:i]
        pchg = np.abs((win - prev) / np.where(prev == 0, np.nan, prev)) * 100
        atr_pct = float(np.nanmean(pchg))
        ma_now = float(np.mean(close[i - window + 1:i + 1]))
        ma_prev = float(np.mean(close[i - 2 * window + 1:i - window + 1]))
        ma20_slope = (ma_now / ma_prev - 1.0) * 100 if ma_prev > 0 else 0.0
        first = float(close[i - window + 1])
        mom_20 = (float(close[i]) / first - 1.0) * 100 if first > 0 else 0.0
        return atr_pct, ma20_slope, mom_20


def _load_prices(codes, start, end):
    prices = _Prices()
    hist_start = (pd.Timestamp(start) - pd.DateOffset(days=400)).strftime('%Y-%m-%d')
    ok = 0
    for code in codes:
        try:
            df = data_feed.load_stock_data(code, hist_start, str(end), cache_only=True)
        except Exception:
            df = None
        if df is None or len(df) < 60:
            continue
        prices.add(code, df.sort_values('date').reset_index(drop=True))
        ok += 1
    _LOG.info(f"价格缓存可用 {ok}/{len(codes)} 只")
    return prices


# ─────────────────────── PIT 截面装配 ───────────────────────

def _pit_cross_section(panel_by_code_sorted, prices, codes, day_int, lag_days):
    """在交易日 day_int 装配 PIT 截面：每只票取 report_date+lag<=day 的最新财报 + 当日技术因子。"""
    lag = np.timedelta64(lag_days, 'D')
    rows = []
    for code in codes:
        recs = panel_by_code_sorted.get(code)
        if not recs:
            continue
        # recs: list of (report_date_int, visible_int, factor_dict)，按 report 升序
        chosen = None
        for rep_int, vis_int, fdict in recs:
            if vis_int <= day_int:
                chosen = fdict
            else:
                break
        if chosen is None:
            continue
        i = prices.idx_asof(code, day_int)
        if i < 0:
            continue
        tech = prices.tech_factors(code, i)
        if tech is None:
            continue
        row = {'code': code, 'close': prices.close_at(code, i)}
        row.update(chosen)
        row['atr_pct'], row['ma20_slope'], row['mom_20'] = tech
        # PE/PB 估值代理（PIT：现价 / 最新可见报告的 eps、bps）
        eps = chosen.get('eps')
        bps = chosen.get('bps')
        close_px = row['close']
        row['pe_proxy'] = (close_px / eps) if (eps is not None and eps > 0) else np.nan
        row['pb_proxy'] = (close_px / bps) if (bps is not None and bps > 0) else np.nan
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _build_panel_index(panel, lag_days):
    """把面板整理成 {code: [(report_int, visible_int, factor_dict), ...]}（按报告期升序）。"""
    fund_cols = [c for c, _ in _BACKTEST_DIMENSION_FACTORS['fund']]
    # 额外携带 eps/bps 用于 PE/PB 估值代理（PIT）
    carry = fund_cols + ['eps', 'bps']
    present = [c for c in carry if c in panel.columns]
    out = {}
    for code, g in panel.groupby('code'):
        g = g.sort_values('date')
        recs = []
        for _, r in g.iterrows():
            rep = pd.Timestamp(r['date'])
            rep_int = np.datetime64(rep, 'D').astype('int64')
            vis_int = np.datetime64(rep + pd.Timedelta(days=lag_days), 'D').astype('int64')
            fdict = {c: (float(r[c]) if pd.notna(r[c]) else np.nan) for c in present}
            recs.append((rep_int, vis_int, fdict))
        out[str(code)] = recs
    return out


def _rank_ic(x: np.ndarray, y: np.ndarray) -> float:
    """无 scipy 的 Spearman rank-IC：对秩做 Pearson。"""
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 5:
        return 0.0
    rx = pd.Series(x[mask]).rank().values
    ry = pd.Series(y[mask]).rank().values
    if np.std(rx) < 1e-12 or np.std(ry) < 1e-12:
        return 0.0
    return float(np.corrcoef(rx, ry)[0, 1])


def _compute_ic_weights(panel_idx, prices, codes, trade_dates_int, a, b, lag_days, rebal):
    """在 [a,b) 训练折上，按各因子 rank-IC(方向化) 对前向收益做加权。

    返回 {因子列名: 权重}（负 IC 截断为 0）；无有效样本返回 None（回退等权）。
    """
    factors = []
    for dim in ('fund', 'value', 'tech'):
        factors.extend(_BACKTEST_DIMENSION_FACTORS.get(dim, []))
    ic_acc = {c: [] for c, _ in factors}
    ti = trade_dates_int[a:b]
    for k in range(0, len(ti) - rebal, rebal):
        d0 = ti[k]
        d1 = ti[k + rebal]
        cs = _pit_cross_section(panel_idx, prices, codes, d0, lag_days)
        if cs.empty or 'code' not in cs.columns:
            continue
        # 前向收益：d0→d1 各票收盘价变化
        fwd = {}
        for code in cs['code']:
            i0 = prices.idx_asof(code, d0)
            i1 = prices.idx_asof(code, d1)
            if i0 < 0 or i1 < 0:
                continue
            p0 = prices.close_at(code, i0)
            p1 = prices.close_at(code, i1)
            fwd[code] = (p1 / p0 - 1.0) if p0 > 0 else np.nan
        cs = cs.assign(_fwd=cs['code'].map(fwd))
        y = pd.to_numeric(cs['_fwd'], errors='coerce').values
        for col, direction in factors:
            if col not in cs.columns:
                continue
            x = pd.to_numeric(cs[col], errors='coerce').values
            if direction == 'low':
                x = -x
            ic_acc[col].append(_rank_ic(x, y))
    weights = {}
    for col, vals in ic_acc.items():
        if vals:
            weights[col] = max(0.0, float(np.mean(vals)))
    if not weights or sum(weights.values()) <= 0:
        return None
    return weights


# ─────────────────────── 回测 ───────────────────────

def _run_backtest(panel_idx, prices, codes, trade_dates_int, params, capital, regime=None,
                  factor_weights=None):
    w_fund = float(params['w_fund'])
    w_value = float(params.get('w_value', 0.0))
    w_tech = max(0.0, round(1.0 - w_fund - w_value, 4))
    weights = {'fund': w_fund, 'value': w_value, 'tech': w_tech}
    rebal = params['rebalance_days']
    top_positions = int(params['top_positions'])
    quality_gate = params['quality_gate']
    trade_gate = params['trade_gate']
    regime_ma = int(params.get('regime_ma', 0) or 0)
    # 交易成本（修复：月度全额换仓不能零成本，否则系统性高估夏普/收益）
    cost_buy = float(params.get('cost_buy', 0.0))    # 买入侧：佣金+滑点
    cost_sell = float(params.get('cost_sell', 0.0))  # 卖出侧：佣金+印花税+滑点

    cash = float(capital)
    positions = {}  # code -> {shares, cost}
    nav = []
    trades = []  # 逐笔净盈亏（已扣两侧成本）

    def _sell(code, pos, price):
        nonlocal cash
        proceeds = pos['shares'] * price * (1.0 - cost_sell)
        cash += proceeds
        # 净盈亏 = 卖出净收入 − 买入总成本（含买入侧成本）
        buy_cost = pos['shares'] * pos['cost'] * (1.0 + cost_buy)
        trades.append(proceeds - buy_cost)

    for di, day_int in enumerate(trade_dates_int):
        is_rebal = (di % rebal == 0)
        if is_rebal:
            # 先全部清仓（月度换仓）
            for code, pos in list(positions.items()):
                i = prices.idx_asof(code, day_int)
                if i < 0:
                    continue
                _sell(code, pos, prices.close_at(code, i))
                del positions[code]
            # 装配截面并选股（大盘择时：弱市只清仓不买入）
            regime_ok = regime.ok(day_int, regime_ma) if regime is not None else True
            cs = _pit_cross_section(panel_idx, prices, codes, day_int, params['lag_days']) if regime_ok else pd.DataFrame()
            if not cs.empty:
                scores = ca.compute_composite_scores(
                    cs, weights=weights, dimension_factors=_BACKTEST_DIMENSION_FACTORS,
                    factor_weights=factor_weights)
                picked = ca.select_candidates(
                    cs, scores=scores, quality_gate=quality_gate,
                    trade_gate=trade_gate, top_n=top_positions)
                if not picked.empty:
                    alloc = cash / len(picked)
                    for _, r in picked.iterrows():
                        code = r['code']
                        price = float(r['close'])
                        if price <= 0:
                            continue
                        # 买入含成本：实际支出 = 名义 × (1+cost_buy)
                        spend = min(alloc, cash)
                        shares = spend / (price * (1.0 + cost_buy))
                        cash -= shares * price * (1.0 + cost_buy)
                        positions[code] = {'shares': shares, 'cost': price}

        # 组合净值
        holdings = 0.0
        for code, pos in positions.items():
            i = prices.idx_asof(code, day_int)
            holdings += pos['shares'] * (prices.close_at(code, i) if i >= 0 else pos['cost'])
        nav.append(cash + holdings)

    # 期末清仓计入逐笔
    last_day = trade_dates_int[-1]
    for code, pos in list(positions.items()):
        i = prices.idx_asof(code, last_day)
        if i >= 0:
            _sell(code, pos, prices.close_at(code, i))
    return nav, trades


def _evaluate(panel_idx, prices, codes, trade_dates, trade_dates_int, params, capital, regime=None,
              factor_weights=None):
    nav, trades = _run_backtest(panel_idx, prices, codes, trade_dates_int, params, capital,
                                regime=regime, factor_weights=factor_weights)
    if not nav or len(nav) < 2 or nav[0] <= 0:
        return None
    nav_norm = [v / nav[0] for v in nav]
    metrics = risk_metrics.calculate_metrics(nav_norm, dates=trade_dates)
    # 逐笔交易胜率（修订：低频用逐笔而非按日）
    n_trades = len(trades)
    wins = sum(1 for p in trades if p > 0)
    trade_win_rate = (wins / n_trades * 100) if n_trades else 0.0
    metrics = dict(metrics)
    metrics['trade_count'] = n_trades
    metrics['trade_win_rate'] = round(trade_win_rate, 2)
    return metrics


# ─────────────────────── 目标函数（同量纲归一化）───────────────────────

def _normalize(vals):
    """min-max 归一到 [0,1]；常量列返回全 0.5。"""
    arr = np.array(vals, dtype=float)
    lo, hi = np.nanmin(arr), np.nanmax(arr)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi - lo < 1e-12:
        return np.full_like(arr, 0.5)
    return (arr - lo) / (hi - lo)


def _score_objective(results, w):
    """先对每个指标做同量纲归一化，再加权（修复量纲 Bug）。

    objective = a*z(Sharpe) + b*z(TradeWinRate) + c*z(AnnualReturn)
              - d*z(MaxDrawdown) + e*z(MinFoldSharpe)
    其中 Sharpe/AnnualReturn/WinRate/MaxDrawdown 均取跨折均值，MinFoldSharpe 为最差折夏普（稳健项）。
    """
    if not results:
        return
    sharpe = _normalize([r['metrics'].get('sharpe_ratio', 0) for r in results])
    winr = _normalize([r['metrics'].get('trade_win_rate', 0) for r in results])
    annual = _normalize([r['metrics'].get('annual_return', 0) for r in results])
    mdd = _normalize([r['metrics'].get('max_drawdown', 0) for r in results])
    min_sh = _normalize([r['metrics'].get('min_fold_sharpe', 0) for r in results])
    for k, r in enumerate(results):
        r['objective'] = round(float(
            w['a'] * sharpe[k] + w['b'] * winr[k] + w['c'] * annual[k]
            - w['d'] * mdd[k] + w.get('e', 0.0) * min_sh[k]), 4)


def _aggregate_folds(fold_metrics):
    """将多折样本外指标聚合为稳健汇总（均值 + 最差折夏普）。"""
    if not fold_metrics:
        return None
    def _m(key):
        vals = [fm.get(key, 0.0) for fm in fold_metrics if fm is not None]
        return float(np.mean(vals)) if vals else 0.0
    sharpes = [fm.get('sharpe_ratio', 0.0) for fm in fold_metrics if fm is not None]
    agg = {
        'sharpe_ratio': round(_m('sharpe_ratio'), 4),
        'annual_return': round(_m('annual_return'), 4),
        'max_drawdown': round(_m('max_drawdown'), 4),
        'trade_win_rate': round(_m('trade_win_rate'), 4),
        'min_fold_sharpe': round(float(np.min(sharpes)), 4) if sharpes else 0.0,
        'trade_count': int(sum(fm.get('trade_count', 0) for fm in fold_metrics if fm is not None)),
        'n_folds': len([fm for fm in fold_metrics if fm is not None]),
    }
    return agg


# ─────────────────────── 主流程 ───────────────────────

def _build_combos(grid, fixed):
    keys = list(grid.keys())
    for vals in itertools.product(*[grid[k] for k in keys]):
        p = dict(fixed)
        p.update(dict(zip(keys, vals)))
        yield p


def _parse_args():
    p = argparse.ArgumentParser(description='综合多因子选股参数寻优 + Walk-Forward')
    p.add_argument('--start', type=str, default=None)
    p.add_argument('--end', type=str, default=None)
    p.add_argument('--max-codes', type=int, default=300)
    p.add_argument('--capital', type=float, default=1_000_000.0)
    p.add_argument('--top-k', type=int, default=5)
    p.add_argument('--min-trades', type=int, default=20, help='有效结果最少逐笔交易数')
    p.add_argument('--benchmark', type=str, default='000300')
    p.add_argument('--wf-splits', type=int, default=2, help='Walk-Forward 段数（含1个验证段）')
    p.add_argument('--obj-a', type=float, default=0.45, help='夏普权重')
    p.add_argument('--obj-b', type=float, default=0.25, help='逐笔胜率权重')
    p.add_argument('--obj-c', type=float, default=0.20, help='年化收益权重')
    p.add_argument('--obj-d', type=float, default=0.10, help='最大回撤惩罚权重')
    p.add_argument('--obj-e', type=float, default=0.30, help='最差折夏普(稳健)权重')
    p.add_argument('--cost-buy', type=float, default=None, help='买入侧成本(小数)，默认0.0005')
    p.add_argument('--cost-sell', type=float, default=None, help='卖出侧成本(小数)，默认0.0015')
    p.add_argument('--max-combos', type=int, default=64)
    return p.parse_args()


def _trade_dates(start, end):
    tds = data_feed.get_trading_dates(start, end)
    if not tds:
        return None, None
    ints = np.array([np.datetime64(d, 'D').astype('int64') for d in tds], dtype='int64')
    return tds, ints


def main():
    args = _parse_args()
    end = pd.Timestamp(args.end).date() if args.end else datetime.date.today()
    start = (pd.Timestamp(args.start).date() if args.start
             else (pd.Timestamp(end) - pd.DateOffset(years=3)).date())
    if start >= end:
        raise SystemExit(f'窗口非法：start={start} >= end={end}')

    grid = {k: list(v) for k, v in _DEFAULT_GRID.items()}
    fixed = dict(_FIXED)
    if args.cost_buy is not None:
        fixed['cost_buy'] = float(args.cost_buy)
    if args.cost_sell is not None:
        fixed['cost_sell'] = float(args.cost_sell)
    combos = list(_build_combos(grid, fixed))
    if len(combos) > args.max_combos:
        raise SystemExit(f'组合数 {len(combos)} 超上限 {args.max_combos}')
    _LOG.info(f"参数组合 {len(combos)}；区间 {start}~{end}")

    panel = _load_financial_panel(start, end, args.max_codes)
    if panel is None or panel.empty:
        raise SystemExit('cn_stock_financial 面板为空：请先铺底财务数据。')
    codes = sorted(panel['code'].astype(str).unique())
    _LOG.info(f"财务面板股票 {len(codes)} 只，报告期 {panel['date'].nunique()} 个")

    prices = _load_prices(codes, start, end)
    codes = [c for c in codes if prices.has(c)]
    if len(codes) < 20:
        raise SystemExit(f'可用价格股票过少（{len(codes)}），无法回测。')
    panel_idx = _build_panel_index(panel, _FIXED['lag_days'])

    trade_dates, trade_dates_int = _trade_dates(start, end)
    if trade_dates is None or len(trade_dates) < 60:
        raise SystemExit('交易日不足。')

    # 大盘择时基准（沪深300），构建 _Regime
    regime = _Regime()
    try:
        hist_start = (pd.Timestamp(start) - pd.DateOffset(days=400)).strftime('%Y-%m-%d')
        bdf = data_feed.load_benchmark_data(args.benchmark, hist_start, str(end))
        if bdf is not None and len(bdf) > 0:
            bdf = bdf.sort_values('date')
            bday = bdf['date'].values.astype('datetime64[D]').astype('int64')
            bclose = pd.to_numeric(bdf['close'], errors='coerce').to_numpy(dtype=float)
            regime = _Regime(bday, bclose)
            _LOG.info(f"择时基准 {args.benchmark} 载入 {len(bday)} 条")
        else:
            _LOG.warning("择时基准缺失，regime_ma 将恒为放行")
    except Exception as e:
        _LOG.warning(f"择时基准加载失败，regime 关闭: {e}")

    # Walk-Forward 多折：等分为 wf_splits 段，每段都作为一个样本外测试折。
    # 参数是小网格（无逐折拟合），因此每折都是独立的样本外表现；按跨折聚合选优。
    n = len(trade_dates)
    seg = n // max(2, args.wf_splits)
    folds = []
    for s in range(args.wf_splits):
        a = s * seg
        b = n if s == args.wf_splits - 1 else (s + 1) * seg
        if b - a >= 40:
            folds.append((a, b))
    if len(folds) < 2:
        raise SystemExit('可用折数不足（<2），请缩短区间或减少 wf-splits。')
    _LOG.info(f"Walk-Forward 折数 {len(folds)}（各折样本外）")

    obj_w = {'a': args.obj_a, 'b': args.obj_b, 'c': args.obj_c,
             'd': args.obj_d, 'e': args.obj_e}

    # 因子 IC 加权：仅用第一折训练估计，避免用到各评估折的未来信息
    ic_weights = _compute_ic_weights(
        panel_idx, prices, codes, trade_dates_int, folds[0][0], folds[0][1],
        _FIXED['lag_days'], _FIXED['rebalance_days'])
    if ic_weights:
        top_ic = sorted(ic_weights.items(), key=lambda kv: kv[1], reverse=True)[:6]
        _LOG.info("因子IC加权(训练折, top): " + ", ".join(f"{k}={v:.3f}" for k, v in top_ic))
    else:
        _LOG.info("IC 加权无有效样本，回退等权")

    def _eval_range(params, a, b):
        td = trade_dates[a:b]
        ti = trade_dates_int[a:b]
        if len(td) < 30:
            return None
        return _evaluate(panel_idx, prices, codes, td, ti, params, args.capital,
                         regime=regime, factor_weights=ic_weights)

    min_trades_per_fold = max(3, args.min_trades // len(folds))

    # 跨折搜参：每个组合在每一折上评估，聚合为稳健样本外指标
    t0 = time.time()
    results = []
    for k, params in enumerate(combos, 1):
        fold_ms = []
        for (a, b) in folds:
            m = _eval_range(params, a, b)
            if m is not None and m.get('trade_count', 0) >= min_trades_per_fold:
                fold_ms.append(m)
        if len(fold_ms) < 2:
            continue
        agg = _aggregate_folds(fold_ms)
        if agg is None or agg['trade_count'] < args.min_trades:
            continue
        agg['fold_sharpes'] = [round(fm.get('sharpe_ratio', 0), 3) for fm in fold_ms]
        results.append({'params': params, 'metrics': agg})
        if k % 8 == 0 or k == len(combos):
            _LOG.info(f"搜参进度 {k}/{len(combos)}，用时 {time.time()-t0:.0f}s")
    if not results:
        raise SystemExit('无有效结果（检查价格缓存/最少交易数/折数）。')
    _score_objective(results, obj_w)
    results.sort(key=lambda r: r['objective'], reverse=True)
    top = results[:args.top_k]

    # 成本敏感性：对 Top1 在全区间用 0.5x/1x/2x 成本各跑一次
    best = top[0]
    cost_sens = []
    base_cb, base_cs = fixed['cost_buy'], fixed['cost_sell']
    for mult in (0.0, 1.0, 2.0):
        p = dict(best['params'])
        p['cost_buy'] = base_cb * mult
        p['cost_sell'] = base_cs * mult
        m = _eval_range(p, 0, n)
        if m:
            cost_sens.append({'cost_mult': mult, 'sharpe': m.get('sharpe_ratio'),
                              'annual_return': m.get('annual_return'),
                              'trade_win_rate': m.get('trade_win_rate')})

    # 输出
    print('\n============ 综合多因子选股 跨折样本外寻优 Top {} ============'.format(len(top)))
    print(f'股票 {len(codes)} 只 | 区间 {start}~{end} | 组合 {len(combos)} | 折数 {len(folds)} | 有效 {len(results)}')
    print('聚合(均值): 夏普/年化%/回撤%/逐笔胜率% | 最差折夏普 | 各折夏普 | 参数')
    for rank, r in enumerate(top, 1):
        m = r['metrics']
        print('#{} obj={} | {}/{}/{}/{} | min={} | {} | w_fund={} w_value={} qgate={} tgate={} pos={} regime={}'.format(
            rank, r['objective'],
            m.get('sharpe_ratio'), m.get('annual_return'), m.get('max_drawdown'),
            m.get('trade_win_rate'), m.get('min_fold_sharpe'), m.get('fold_sharpes'),
            r['params']['w_fund'], r['params'].get('w_value', 0), r['params']['quality_gate'],
            r['params']['trade_gate'], r['params']['top_positions'],
            r['params'].get('regime_ma', 0)))
    print('\n成本敏感性(Top1，全区间):')
    for cs in cost_sens:
        print('  cost×{}: 夏普={} 年化%={} 逐笔胜率%={}'.format(
            cs['cost_mult'], cs['sharpe'], cs['annual_return'], cs['trade_win_rate']))

    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    payload = {
        'generated_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'meta': {'start': str(start), 'end': str(end), 'codes': len(codes),
                 'combos': len(combos), 'folds': len(folds),
                 'min_trades': args.min_trades, 'objective_weights': obj_w,
                 'cost_buy': base_cb, 'cost_sell': base_cs},
        'cost_sensitivity_top1': cost_sens,
        'presets': [{'params': r['params'], 'objective': r['objective'],
                     'oos_aggregate': r['metrics']}
                    for r in top],
    }
    with open(_OUTPUT_FILE, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)
    _LOG.info(f"已保存最优参数到 {_OUTPUT_FILE}")


if __name__ == '__main__':
    main()

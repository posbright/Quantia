#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""低ATR成长策略参数寻优脚本（离线研究，非定时任务）。

流程：
1. 选出 top-N 只基本面较好的股票（dynamic_universe.fetch_universe，读 cn_stock_selection
   综合评分；DB 不可用时降级为本地 K 线缓存里的股票）。
2. 加载这些股票的历史日 K 线（data_feed，cache_only 离线模式，不发外网请求）。
3. 对低ATR成长「选股参数 + 交易参数」做网格回测：每个交易日在股票池里用
   low_atr 选股逻辑产生买入信号，按 止盈/止损/最长持有 规则平仓，跟踪组合净值。
4. 用 risk_metrics.calculate_metrics 计算夏普/年化收益/最大回撤等，按
   "夏普 + 收益" 综合目标排序，输出并保存最优的几套参数。
5. 可选 --apply：把 Top1 参数写入 cn_strategy_params，使每日选股与UI立即采用。

用法示例（父目录 .venv）：
    cd C:\\xapproject\\Quantia\\Quantia
    ..\\.venv\\Scripts\\python.exe tools/optimize_low_atr_params.py \
        --top-n 100 --start 2023-01-01 --end 2025-12-31 --top-k 5

    # 满意后把最优参数落库为默认（每日任务/UI 生效）：
    ..\\.venv\\Scripts\\python.exe tools/optimize_low_atr_params.py --apply

免责：
- 基本面股票池取自 cn_stock_selection 最新快照，存在幸存者/时点偏差。
- K 线走本地缓存离线模式，缓存不足的股票会被跳过。
- 结果为历史拟合，实盘需结合样本外验证与风控。
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

logging.basicConfig(level=logging.WARNING,
                    format='%(asctime)s %(levelname)s %(message)s')
_LOG = logging.getLogger('optimize_low_atr')
_LOG.setLevel(logging.INFO)

_STRATEGY_KEY = 'low_atr'
_OUTPUT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..',
                                            'quantia', 'cache', 'optimize'))
_OUTPUT_FILE = os.path.join(_OUTPUT_DIR, 'low_atr_best_params.json')

# 网格默认值（可用 CLI 覆盖）。控制组合数量在可接受范围内。
_DEFAULT_GRID = {
    'max_atr': [4.0, 6.0, 8.0],
    'min_price_range': [1.05, 1.08, 1.12],
    'analysis_days': [15, 20, 30],
    'min_total_return': [0.0, 3.0, 6.0],
    'min_up_days_ratio': [0.0, 0.5],
    'max_drawdown': [8.0, 12.0],
}
# 交易参数网格（组合数敏感，默认单点，用 CLI 展开）。
_DEFAULT_TRADE_GRID = {
    'take_profit': [0.15],
    'stop_loss': [-0.07],
    'max_hold_days': [20],
}
# 固定选股参数（不参与寻优，可 CLI 覆盖）。
_FIXED = {
    'min_listing_days': 120,
    'min_turnover': 0.3,
}


# ─────────────────────────── 股票池 ───────────────────────────

def _select_universe(top_n: int, force_refresh: bool):
    """返回 [(code, name), ...]，优先基本面综合评分，降级本地缓存。"""
    try:
        from quantia.core.composite.dynamic_universe import fetch_universe
        df = fetch_universe(top_n=top_n, force_refresh=force_refresh)
        if df is not None and len(df) > 0:
            names = df['name'] if 'name' in df.columns else ['' for _ in range(len(df))]
            pairs = list(zip(df['code'].astype(str).str.zfill(6), names))
            _LOG.info(f"基本面股票池: {len(pairs)} 只（cn_stock_selection 综合评分）")
            return pairs
    except Exception as e:
        _LOG.warning(f"基本面股票池获取失败，降级本地缓存: {e}")

    codes = data_feed.get_all_cached_stocks() or []
    codes = [c for c in codes if data_feed._is_likely_stock_code(c)][:top_n]
    _LOG.info(f"降级股票池: {len(codes)} 只（本地 K 线缓存）")
    return [(c, '') for c in codes]


# ─────────────────────────── 数据加载 ───────────────────────────

class _StockSeries:
    """单只股票的紧凑数值序列，供快速信号与定价使用。"""
    __slots__ = ('code', 'name', 'dates_int', 'close', 'pchange', 'volume')

    def __init__(self, code, name, df):
        self.code = code
        self.name = name
        d = df['date']
        self.dates_int = d.values.astype('datetime64[D]').astype('int64')
        self.close = df['close'].to_numpy(dtype=float)
        pre = df['close'].shift(1)
        self.pchange = ((df['close'] / pre - 1.0) * 100.0).fillna(0.0).to_numpy(dtype=float)
        if 'volume' in df.columns:
            self.volume = pd.to_numeric(df['volume'], errors='coerce').fillna(0.0).to_numpy(dtype=float)
        else:
            self.volume = np.zeros(len(self.close), dtype=float)

    def idx_asof(self, day_int: int) -> int:
        """返回 <= day_int 的最后一个交易日下标；无则 -1。"""
        pos = int(np.searchsorted(self.dates_int, day_int, side='right')) - 1
        return pos


def _load_series(pairs, start, end):
    """加载股票池 K 线（离线缓存），返回 list[_StockSeries]。"""
    # 多留一段前置历史以满足 min_listing_days 与窗口计算。
    hist_start = (pd.Timestamp(start) - pd.DateOffset(days=900)).strftime('%Y-%m-%d')
    series = []
    skipped = 0
    for code, name in pairs:
        try:
            df = data_feed.load_stock_data(code, hist_start, end, cache_only=True)
        except Exception:
            df = None
        if df is None or len(df) < 60:
            skipped += 1
            continue
        df = df[['date', 'close'] + (['volume'] if 'volume' in df.columns else [])].copy()
        df = df.sort_values('date').reset_index(drop=True)
        series.append(_StockSeries(code, name, df))
    _LOG.info(f"加载 K 线成功 {len(series)} 只，跳过 {skipped} 只（缓存不足）")
    return series


# ─────────────────────────── 信号（镜像 low_atr.check_low_increase）───────────────────────────

def _signal(s: _StockSeries, i: int, p: dict) -> bool:
    """在下标 i（当日）判断 s 是否满足低ATR成长买入条件。

    逻辑严格镜像 quantia/core/strategy/low_atr.py::check_low_increase，
    以保证寻优结论与生产选股一致（见 _self_check 等价性自检）。
    """
    window = int(p['analysis_days'])
    listing_days = int(p['min_listing_days'])
    available = i + 1
    if available < listing_days:
        return False
    if i - window + 1 < 0:
        return False

    lo = i - window + 1
    close = s.close[lo:i + 1]
    pchg = s.pchange[lo:i + 1]
    days = window

    total_change = float(np.abs(pchg[pchg != 0]).sum())
    inc_days = int((pchg > 0).sum())
    atr = total_change / days
    if atr > p['max_atr']:
        return False

    up_ratio = inc_days / days
    if p['min_up_days_ratio'] > 0 and up_ratio < p['min_up_days_ratio']:
        return False

    highest = float(close.max())
    lowest = float(close.min())
    ratio = (highest - lowest) / lowest if lowest != 0 else 0.0

    first_close = float(close[0])
    last_close = float(close[-1])
    total_return = (last_close - first_close) / first_close * 100 if first_close else 0.0
    if p['min_total_return'] > 0 and total_return < p['min_total_return']:
        return False

    peak = np.maximum.accumulate(close)
    with np.errstate(divide='ignore', invalid='ignore'):
        dd = np.where(peak != 0, (peak - close) / peak * 100.0, 0.0)
    window_dd = float(np.nanmax(dd)) if len(dd) else 0.0
    if p['max_drawdown'] < 100 and window_dd > p['max_drawdown']:
        return False

    if p['min_turnover'] > 0:
        amount = last_close * float(s.volume[i])
        if amount < p['min_turnover'] * 1e8:
            return False

    return ratio > (p['min_price_range'] - 1.0)


def _self_check() -> bool:
    """对随机窗口比对 _signal 与 low_atr.check_low_increase 的布尔一致性。"""
    try:
        from quantia.core.strategy.low_atr import check_low_increase
    except Exception as e:
        _LOG.warning(f"跳过等价性自检（无法导入 low_atr）: {e}")
        return True
    rng = np.random.RandomState(7)
    n = 320
    close = 10 * np.cumprod(1 + rng.normal(0.001, 0.02, n))
    dates = pd.bdate_range('2022-01-01', periods=n)
    df = pd.DataFrame({
        'date': dates,
        'close': np.round(close, 2),
        'volume': rng.randint(2_000_000, 8_000_000, n).astype(float),
    })
    df['p_change'] = (df['close'] / df['close'].shift(1) - 1).fillna(0) * 100
    s = _StockSeries('000001', 't', df)
    params_sets = [
        dict(max_atr=6, min_price_range=1.08, analysis_days=20, min_total_return=3,
             min_up_days_ratio=0.5, max_drawdown=8, min_listing_days=120, min_turnover=0),
        dict(max_atr=10, min_price_range=1.1, analysis_days=10, min_total_return=0,
             min_up_days_ratio=0, max_drawdown=100, min_listing_days=250, min_turnover=0),
    ]
    mismatches = 0
    for p in params_sets:
        for i in range(p['min_listing_days'], n):
            fast = _signal(s, i, p)
            ref = check_low_increase(
                (df['date'].iloc[i].strftime('%Y-%m-%d'), '000001', 't'),
                df.iloc[:i + 1], date=None,
                max_atr=p['max_atr'], min_price_range=p['min_price_range'],
                analysis_days=p['analysis_days'], min_listing_days=p['min_listing_days'],
                min_total_return=p['min_total_return'], min_up_days_ratio=p['min_up_days_ratio'],
                max_drawdown=p['max_drawdown'], min_turnover=p['min_turnover'])
            ref_bool = bool(ref) if not isinstance(ref, dict) else True
            if fast != ref_bool:
                mismatches += 1
    if mismatches:
        _LOG.warning(f"等价性自检发现 {mismatches} 处差异（结果仅供参考）")
        return False
    _LOG.info("等价性自检通过：快速信号与 low_atr.check_low_increase 一致")
    return True


# ─────────────────────────── 组合回测 ───────────────────────────

def _run_backtest(series, trade_dates_int, params, capital, max_positions):
    """单套参数的组合回测，返回 nav_list（与 trade_dates 等长）。"""
    cash = float(capital)
    positions = {}  # code -> dict(shares, cost, hold_days)
    idx_map = {s.code: s for s in series}
    nav = []

    for t in trade_dates_int:
        # 1) 更新持有天数
        for pos in positions.values():
            pos['hold_days'] += 1

        # 2) 卖出检查
        for code in list(positions.keys()):
            s = idx_map[code]
            i = s.idx_asof(t)
            if i < 0:
                continue
            price = s.close[i]
            pos = positions[code]
            if pos['cost'] <= 0:
                continue
            profit = (price - pos['cost']) / pos['cost']
            if (profit >= params['take_profit'] or profit <= params['stop_loss']
                    or pos['hold_days'] >= params['max_hold_days']):
                cash += pos['shares'] * price
                del positions[code]

        # 3) 买入检查
        if len(positions) < max_positions:
            alloc = capital / max_positions
            for s in series:
                if len(positions) >= max_positions:
                    break
                if s.code in positions:
                    continue
                i = s.idx_asof(t)
                if i < 0:
                    continue
                if cash < alloc * 0.5:
                    break
                if _signal(s, i, params):
                    price = s.close[i]
                    if price <= 0:
                        continue
                    invest = min(alloc, cash)
                    shares = invest / price
                    cash -= shares * price
                    positions[s.code] = {'shares': shares, 'cost': price, 'hold_days': 0}

        # 4) 组合净值
        holdings_value = 0.0
        for code, pos in positions.items():
            s = idx_map[code]
            i = s.idx_asof(t)
            if i < 0:
                holdings_value += pos['shares'] * pos['cost']
            else:
                holdings_value += pos['shares'] * s.close[i]
        nav.append(cash + holdings_value)

    return nav


def _evaluate(series, trade_dates, trade_dates_int, bench_nav, params,
              capital, max_positions):
    nav = _run_backtest(series, trade_dates_int, params, capital, max_positions)
    if not nav or len(nav) < 2 or nav[0] <= 0:
        return None
    nav_norm = [v / nav[0] for v in nav]
    metrics = risk_metrics.calculate_metrics(
        nav_norm, benchmark_series=bench_nav, dates=trade_dates)
    return metrics


# ─────────────────────────── 网格与目标 ───────────────────────────

def _build_combos(grid, trade_grid, fixed):
    sel_keys = list(grid.keys())
    trd_keys = list(trade_grid.keys())
    for sel_vals in itertools.product(*[grid[k] for k in sel_keys]):
        for trd_vals in itertools.product(*[trade_grid[k] for k in trd_keys]):
            p = dict(fixed)
            p.update(dict(zip(sel_keys, sel_vals)))
            p.update(dict(zip(trd_keys, trd_vals)))
            yield p


def _objective(metrics, sharpe_w, return_w):
    """综合目标：夏普与年化收益的加权和（都做温和缩放）。"""
    sharpe = float(metrics.get('sharpe_ratio', 0) or 0)
    annual = float(metrics.get('annual_return', 0) or 0)
    return sharpe_w * sharpe + return_w * (annual / 100.0)


# ─────────────────────────── 落库 ───────────────────────────

_SELECTION_PARAM_KEYS = ('max_atr', 'min_price_range', 'analysis_days',
                         'min_listing_days', 'min_total_return',
                         'min_up_days_ratio', 'max_drawdown', 'min_turnover')


def _apply_to_db(best_params):
    """把 Top1 选股参数写入 cn_strategy_params，并记录一条 backtest 历史。"""
    try:
        from quantia.web import strategyParamsHandler as sph
        sph._ensure_params_table()
        snapshot = {}
        for k in _SELECTION_PARAM_KEYS:
            if k in best_params:
                val = best_params[k]
                if k in ('analysis_days', 'min_listing_days'):
                    val = int(val)
                sph._save_param(_STRATEGY_KEY, k, val)
                snapshot[k] = val
        sph._record_params_history(_STRATEGY_KEY, snapshot,
                                   list(snapshot.keys()), source='backtest')
        _LOG.info(f"已写入 cn_strategy_params（strategy_key=low_atr）: {snapshot}")
        return True
    except Exception as e:
        _LOG.error(f"写入 cn_strategy_params 失败: {e}", exc_info=True)
        return False


def _save_results(results, meta):
    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    payload = {
        'generated_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'meta': meta,
        'presets': results,
    }
    with open(_OUTPUT_FILE, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    _LOG.info(f"已保存最优参数预设到 {_OUTPUT_FILE}")


# ─────────────────────────── CLI ───────────────────────────

def _parse_list(text, cast):
    return [cast(x) for x in str(text).split(',') if str(x).strip() != '']


def _parse_args():
    p = argparse.ArgumentParser(description='低ATR成长策略参数寻优')
    p.add_argument('--top-n', type=int, default=100, help='基本面股票池数量（默认100）')
    p.add_argument('--start', type=str, default=None, help='回测起 YYYY-MM-DD（默认 end 前3年）')
    p.add_argument('--end', type=str, default=None, help='回测止 YYYY-MM-DD（默认今天）')
    p.add_argument('--capital', type=float, default=1_000_000.0, help='初始资金')
    p.add_argument('--max-positions', type=int, default=5, help='最大同时持仓数')
    p.add_argument('--top-k', type=int, default=5, help='保存最优参数套数')
    p.add_argument('--sharpe-weight', type=float, default=1.0, help='目标中夏普权重')
    p.add_argument('--return-weight', type=float, default=1.0, help='目标中年化收益权重')
    p.add_argument('--min-trades', type=int, default=10, help='有效结果最少交易日胜率样本（过滤空跑）')
    p.add_argument('--max-combos', type=int, default=600, help='组合数上限保护')
    p.add_argument('--refresh-universe', action='store_true', help='强制刷新基本面股票池缓存')
    p.add_argument('--benchmark', type=str, default='000300', help='基准指数代码')
    # 网格覆盖
    p.add_argument('--grid-max-atr', type=str, default=None)
    p.add_argument('--grid-min-price-range', type=str, default=None)
    p.add_argument('--grid-analysis-days', type=str, default=None)
    p.add_argument('--grid-min-total-return', type=str, default=None)
    p.add_argument('--grid-min-up-days-ratio', type=str, default=None)
    p.add_argument('--grid-max-drawdown', type=str, default=None)
    p.add_argument('--grid-take-profit', type=str, default=None)
    p.add_argument('--grid-stop-loss', type=str, default=None)
    p.add_argument('--grid-max-hold-days', type=str, default=None)
    p.add_argument('--min-listing-days', type=int, default=None)
    p.add_argument('--min-turnover', type=float, default=None)
    p.add_argument('--apply', action='store_true', help='把 Top1 参数写入 cn_strategy_params（生效于每日选股/UI）')
    return p.parse_args()


def _resolve_grids(args):
    grid = {k: list(v) for k, v in _DEFAULT_GRID.items()}
    trade = {k: list(v) for k, v in _DEFAULT_TRADE_GRID.items()}
    fixed = dict(_FIXED)
    if args.grid_max_atr:
        grid['max_atr'] = _parse_list(args.grid_max_atr, float)
    if args.grid_min_price_range:
        grid['min_price_range'] = _parse_list(args.grid_min_price_range, float)
    if args.grid_analysis_days:
        grid['analysis_days'] = _parse_list(args.grid_analysis_days, int)
    if args.grid_min_total_return:
        grid['min_total_return'] = _parse_list(args.grid_min_total_return, float)
    if args.grid_min_up_days_ratio:
        grid['min_up_days_ratio'] = _parse_list(args.grid_min_up_days_ratio, float)
    if args.grid_max_drawdown:
        grid['max_drawdown'] = _parse_list(args.grid_max_drawdown, float)
    if args.grid_take_profit:
        trade['take_profit'] = _parse_list(args.grid_take_profit, float)
    if args.grid_stop_loss:
        trade['stop_loss'] = _parse_list(args.grid_stop_loss, float)
    if args.grid_max_hold_days:
        trade['max_hold_days'] = _parse_list(args.grid_max_hold_days, int)
    if args.min_listing_days is not None:
        fixed['min_listing_days'] = int(args.min_listing_days)
    if args.min_turnover is not None:
        fixed['min_turnover'] = float(args.min_turnover)
    return grid, trade, fixed


def main():
    args = _parse_args()
    end = pd.Timestamp(args.end).date() if args.end else datetime.date.today()
    start = (pd.Timestamp(args.start).date() if args.start
             else (pd.Timestamp(end) - pd.DateOffset(years=3)).date())
    if start >= end:
        raise SystemExit(f'窗口非法：start={start} >= end={end}')

    _self_check()

    grid, trade, fixed = _resolve_grids(args)
    combos = list(_build_combos(grid, trade, fixed))
    if len(combos) > args.max_combos:
        raise SystemExit(
            f'组合数 {len(combos)} 超过上限 {args.max_combos}，请收窄网格或调大 --max-combos')
    _LOG.info(f"参数组合数: {len(combos)}；回测区间 {start} ~ {end}")

    pairs = _select_universe(args.top_n, args.refresh_universe)
    if not pairs:
        raise SystemExit('股票池为空：请先铺底 cn_stock_selection 或本地 K 线缓存。')

    series = _load_series(pairs, start, end)
    if len(series) < 5:
        raise SystemExit(f'可用股票过少（{len(series)}），无法回测。请检查 K 线缓存。')

    trade_dates = data_feed.get_trading_dates(start, end)
    if not trade_dates or len(trade_dates) < 30:
        raise SystemExit('交易日不足，无法回测。')
    trade_dates_int = np.array(
        [np.datetime64(d, 'D').astype('int64') for d in trade_dates], dtype='int64')

    # 基准净值（对齐交易日；缺失则为 None）
    bench_nav = None
    try:
        bdf = data_feed.load_benchmark_data(args.benchmark, start, end)
        if bdf is not None and len(bdf) > 0:
            bmap = {np.datetime64(d.date() if hasattr(d, 'date') else d, 'D').astype('int64'): c
                    for d, c in zip(bdf['date'], bdf['close'])}
            aligned, last = [], None
            for ti in trade_dates_int:
                if ti in bmap:
                    last = float(bmap[ti])
                aligned.append(last if last is not None else np.nan)
            ser = pd.Series(aligned).ffill().bfill()
            if ser.notna().all() and ser.iloc[0] > 0:
                bench_nav = (ser / ser.iloc[0]).tolist()
    except Exception as e:
        _LOG.warning(f"基准加载失败，跳过基准指标: {e}")

    # 网格回测
    results = []
    t0 = time.time()
    for n, params in enumerate(combos, 1):
        metrics = _evaluate(series, trade_dates, trade_dates_int, bench_nav,
                            params, args.capital, args.max_positions)
        if metrics is None:
            continue
        obj = _objective(metrics, args.sharpe_weight, args.return_weight)
        results.append({
            'params': {k: (int(params[k]) if k in ('analysis_days', 'min_listing_days', 'max_hold_days')
                           else params[k]) for k in params},
            'objective': round(obj, 4),
            'sharpe_ratio': metrics.get('sharpe_ratio', 0),
            'annual_return': metrics.get('annual_return', 0),
            'total_return': metrics.get('total_return', 0),
            'max_drawdown': metrics.get('max_drawdown', 0),
            'sortino_ratio': metrics.get('sortino_ratio', 0),
            'daily_win_rate': metrics.get('daily_win_rate', 0),
        })
        if n % 20 == 0 or n == len(combos):
            _LOG.info(f"进度 {n}/{len(combos)}，用时 {time.time() - t0:.0f}s")

    if not results:
        raise SystemExit('所有组合均无有效结果（可能缓存数据不足或区间过短）。')

    results.sort(key=lambda r: (r['objective'], r['sharpe_ratio'], r['annual_return']),
                 reverse=True)
    top = results[:args.top_k]

    print('\n================ 低ATR成长 参数寻优 Top {} ================'.format(len(top)))
    print(f'股票池 {len(series)} 只 | 区间 {start}~{end} | 组合 {len(combos)} | 有效 {len(results)}')
    header = ('#  目标   夏普   年化%  累计%  回撤%  日胜率% | '
              'ATR 振幅 窗口 涨幅 上涨占比 回撤上限 止盈 止损 持有')
    print(header)
    for rank, r in enumerate(top, 1):
        p = r['params']
        print('{:<2} {:>5} {:>6} {:>6} {:>6} {:>6} {:>7} | '
              '{:>3} {:>4} {:>3} {:>3} {:>6} {:>6} {:>4} {:>5} {:>3}'.format(
                  rank, r['objective'], r['sharpe_ratio'], r['annual_return'],
                  r['total_return'], r['max_drawdown'], r['daily_win_rate'],
                  p['max_atr'], p['min_price_range'], p['analysis_days'],
                  p['min_total_return'], p['min_up_days_ratio'], p['max_drawdown'],
                  p['take_profit'], p['stop_loss'], p['max_hold_days']))

    _save_results(top, {
        'start': str(start), 'end': str(end),
        'universe_size': len(series), 'combos': len(combos),
        'valid': len(results), 'capital': args.capital,
        'max_positions': args.max_positions,
        'sharpe_weight': args.sharpe_weight, 'return_weight': args.return_weight,
    })

    if args.apply and top:
        _apply_to_db(top[0]['params'])
    elif top:
        print('\n提示：如需将 Top1 参数落库为每日选股/UI 默认，追加 --apply 重新运行，'
              '或按上表手动在「策略参数配置」页保存。')


if __name__ == '__main__':
    main()

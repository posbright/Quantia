#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基金「分批建仓次数 vs 收益/回撤」实验脚本（一次性研究，非定时任务）。

随机抽取 N 只有净值历史覆盖的基金，在同一时间窗口内，对若干分批次数 k
（1=一次性全仓，其余为等距分批/类定投）分别模拟建仓持有到期末，
聚合输出每个 k 的中位总收益、资金加权年化 IRR、平均最大回撤，
回答"分多少次买入最优"。

用法（生产服务器本地，已铺底 cn_fund_nav_history）：
    cd /root/Quantia
    /root/Quantia/.venv/bin/python tools/fund_staged_buy_experiment.py \
        --n 100 --window-years 3 --ks 1,2,3,6,12,24 --capital 10000 --seed 42

本地开发库（净值数据稀疏时）可调小 --n、放宽 --min-points 先验证逻辑。

重要免责（实验设计内置偏差，解读结论时务必同步）：
- 幸存者偏差：cn_fund_rank 仅含当前存活基金，清盘基金被剔除，收益系统性偏高。
- 覆盖偏差：默认回填仅各类型 TopN，"随机"实为"有净值子集随机"；
  需先跑 QUANTIA_FUND_NAV_TOPN=0 全量回填才接近全市场随机。
- 上涨市中"总收益率"几乎必然 k=1 最高（平凡解）；分批价值在 IRR/回撤维度。
"""
import argparse
import datetime
import os
import random
import statistics
import sys

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import quantia.lib.envconfig  # noqa: F401  触发 .env 加载
import quantia.lib.database as mdb
from quantia.core.fund.fund_backtest import simulate_staged_buy

_NAV_TABLE = 'cn_fund_nav_history'
_RANK_TABLE = 'cn_fund_rank'


def _parse_args():
    p = argparse.ArgumentParser(description='基金分批建仓次数实验')
    p.add_argument('--n', type=int, default=100, help='随机抽取基金数（默认100）')
    p.add_argument('--window-years', type=float, default=3.0,
                   help='回测窗口年数（默认3年；--start/--end 可覆盖）')
    p.add_argument('--start', type=str, default=None, help='窗口起 YYYY-MM-DD（覆盖 window-years）')
    p.add_argument('--end', type=str, default=None, help='窗口止 YYYY-MM-DD（默认数据最新日）')
    p.add_argument('--ks', type=str, default='1,2,3,6,12,24', help='分批次数列表，逗号分隔')
    p.add_argument('--capital', type=float, default=10000.0, help='每只基金总投入金额')
    p.add_argument('--min-points', type=int, default=120,
                   help='窗口内最少净值点（默认120≈半年交易日，过滤覆盖不足）')
    p.add_argument('--cover-tol-days', type=int, default=30,
                   help='首/末净值点对窗口端点的容差天数（默认30）')
    p.add_argument('--fund-type', type=str, default=None,
                   help='仅限某基金类型（如 股票型；默认全部净值型）')
    p.add_argument('--seed', type=int, default=42, help='随机种子（可复现）')
    return p.parse_args()


def _resolve_window(args):
    if args.end:
        end = pd.Timestamp(args.end).date()
    else:
        row = mdb.executeSqlFetch(f"SELECT MAX(`nav_date`) FROM `{_NAV_TABLE}`")
        if not row or not row[0] or not row[0][0]:
            raise SystemExit('cn_fund_nav_history 无数据，请先铺底净值历史。')
        end = row[0][0]
        if isinstance(end, datetime.datetime):
            end = end.date()
    if args.start:
        start = pd.Timestamp(args.start).date()
    else:
        start = (pd.Timestamp(end) - pd.DateOffset(years=args.window_years)).date()
    if start >= end:
        raise SystemExit(f'窗口非法：start={start} >= end={end}')
    return start, end


def _candidate_codes(start, end, args):
    """筛选窗口内净值覆盖达标的基金 code（首点近起点、末点近终点、点数够）。"""
    tol = datetime.timedelta(days=args.cover_tol_days)
    start_tol = start + tol
    end_tol = end - tol
    type_join = ''
    params = [start.isoformat(), end.isoformat()]
    if args.fund_type:
        # 用最新快照的 fund_type 过滤
        type_join = (
            f" AND h.`code` IN (SELECT `code` FROM `{_RANK_TABLE}` "
            f"WHERE `date` = (SELECT MAX(`date`) FROM `{_RANK_TABLE}`) "
            f"AND `fund_type` = %s)"
        )
        params.append(args.fund_type)
    sql = (
        f"SELECT h.`code` FROM `{_NAV_TABLE}` h "
        f"WHERE h.`nav_date` BETWEEN %s AND %s{type_join} "
        f"GROUP BY h.`code` "
        f"HAVING MIN(h.`nav_date`) <= %s AND MAX(h.`nav_date`) >= %s "
        f"   AND COUNT(*) >= %s"
    )
    params += [start_tol.isoformat(), end_tol.isoformat(), int(args.min_points)]
    rows = mdb.executeSqlFetch(sql, tuple(params))
    return [str(r[0]) for r in rows if r and r[0] is not None]


def _load_series(code, start, end):
    df = pd.read_sql(
        f"SELECT `nav_date`, `acc_nav` FROM `{_NAV_TABLE}` "
        f"WHERE `code` = %s AND `nav_date` BETWEEN %s AND %s "
        f"ORDER BY `nav_date` ASC",
        con=mdb.engine(), params=(str(code), start.isoformat(), end.isoformat()))
    return df


def _agg(values):
    """对一列指标（可能含 None）做 计数/中位/均值，返回字典。"""
    vals = [v for v in values if v is not None]
    if not vals:
        return {'count': 0, 'median': None, 'mean': None}
    return {
        'count': len(vals),
        'median': statistics.median(vals),
        'mean': statistics.fmean(vals),
    }


def _fmt_pct(x):
    return '—' if x is None else f'{x * 100:+.2f}%'


def _fmt_num(x):
    return '—' if x is None else f'{x:.3f}'


def main():
    args = _parse_args()
    if not mdb.checkTableIsExist(_NAV_TABLE):
        raise SystemExit('表 cn_fund_nav_history 不存在，请先铺底。')

    ks = [int(x) for x in args.ks.split(',') if x.strip()]
    if not ks:
        raise SystemExit('--ks 为空')

    start, end = _resolve_window(args)
    print(f'窗口: {start} ~ {end} | 分批方案 k={ks} | 每基金投入 {args.capital:.0f}')

    candidates = _candidate_codes(start, end, args)
    print(f'覆盖达标候选基金: {len(candidates)} 只'
          + (f'（类型={args.fund_type}）' if args.fund_type else ''))
    if not candidates:
        raise SystemExit('无覆盖达标基金，请放宽 --min-points / --cover-tol-days 或扩大净值回填。')

    random.seed(args.seed)
    n_pick = min(args.n, len(candidates))
    picked = random.sample(candidates, n_pick)
    print(f'随机抽取: {n_pick} 只（seed={args.seed}）\n')

    # 收集每个 k 的各基金指标
    by_k = {k: {'total_return': [], 'irr': [], 'max_drawdown': []} for k in ks}
    used = 0
    for code in picked:
        df = _load_series(code, start, end)
        if df.empty or len(df.index) < 2:
            continue
        ok = False
        for k in ks:
            res = simulate_staged_buy(df['nav_date'], df['acc_nav'], k, args.capital)
            if res is None:
                continue
            by_k[k]['total_return'].append(res['total_return'])
            by_k[k]['irr'].append(res['irr'])
            by_k[k]['max_drawdown'].append(res['max_drawdown'])
            ok = True
        if ok:
            used += 1
    print(f'实际参与回测基金: {used} 只\n')

    # 汇总表
    header = (f"{'k(买入次数)':<12}{'样本':>6}{'总收益中位':>12}{'总收益均值':>12}"
              f"{'IRR中位':>10}{'IRR均值':>10}{'回撤均值':>10}")
    print(header)
    print('-' * len(header))
    rows = []
    for k in ks:
        tr = _agg(by_k[k]['total_return'])
        ir = _agg(by_k[k]['irr'])
        dd = _agg(by_k[k]['max_drawdown'])
        rows.append((k, tr, ir, dd))
        print(f"{k:<12}{tr['count']:>6}{_fmt_pct(tr['median']):>12}{_fmt_pct(tr['mean']):>12}"
              f"{_fmt_pct(ir['median']):>10}{_fmt_pct(ir['mean']):>10}{_fmt_pct(dd['mean']):>10}")

    # 结论：分别按 总收益中位 / IRR中位 / 回撤均值(越大越好,即越接近0) 找最优 k
    def _best(metric_getter, *, higher_better=True):
        cand = [(k, metric_getter(tr, ir, dd)) for k, tr, ir, dd in rows
                if metric_getter(tr, ir, dd) is not None]
        if not cand:
            return None
        return (max if higher_better else min)(cand, key=lambda t: t[1])

    best_tr = _best(lambda tr, ir, dd: tr['median'])
    best_irr = _best(lambda tr, ir, dd: ir['median'])
    best_dd = _best(lambda tr, ir, dd: dd['mean'])  # 回撤为负，max 即最接近0=回撤最小

    print('\n最优买入次数（不同口径）:')
    if best_tr:
        print(f'  · 总收益率最高     : k={best_tr[0]}（中位 {_fmt_pct(best_tr[1])}）'
              f'  ← 上涨市常退化为 k=1，参考价值低')
    if best_irr:
        print(f'  · 资金加权IRR最高  : k={best_irr[0]}（中位 {_fmt_pct(best_irr[1])}）'
              f'  ← 时间价值公平口径')
    if best_dd:
        print(f'  · 最大回撤最小     : k={best_dd[0]}（均值 {_fmt_pct(best_dd[1])}）'
              f'  ← 分批的真实价值')

    print('\n免责: 含幸存者偏差(剔除清盘基金)与净值覆盖偏差; 结论仅供研究, 非投资建议。')


if __name__ == '__main__':
    main()

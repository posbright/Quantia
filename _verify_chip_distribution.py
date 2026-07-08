#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
筹码分布准确性冒烟脚本（离线抽样校验，可联网环境执行）。

用途：在**能联网**的环境里，把本地自算的筹码指标与东财 `ak.stock_cyq_em`
最后一行做趋势/量级比对，验证算法准确性。因窗口长度与复权口径差异，
不要求逐位相等，重点看 获利比例 / 平均成本 / 90%·70% 成本区间 是否同量级、同趋势。

用法：
    python _verify_chip_distribution.py                 # 默认几只样本股
    python _verify_chip_distribution.py 000001 600519   # 指定股票

设计：
- 本脚本是**离线校验工具**，不属于生产分析管道，允许直接调用 akshare 联网
  （生产分析管道仍严格零 API，见 AGENTS.md 规则 1）。
- 无网络 / 接口失败时优雅跳过联网对比，只做本地缓存自算冒烟。
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Windows 控制台默认 cp1252，无法输出中文 —— 强制 UTF-8
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import logging
logging.disable(logging.CRITICAL)  # 屏蔽缓存/DB 重试噪声，只看校验结果

import pandas as pd

import quantia.core.kline.chip_distribution as cyqd

_DEFAULT_SYMBOLS = ['000001', '600519', '000858', '300750']
_EM_COL_MAP = {
    '获利比例': 'winner_rate',
    '平均成本': 'avg_cost',
    '90成本-低': 'cost_90_low',
    '90成本-高': 'cost_90_high',
    '90集中度': 'concentration_90',
    '70成本-低': 'cost_70_low',
    '70成本-高': 'cost_70_high',
    '70集中度': 'concentration_70',
}


def _fmt(m):
    if m is None:
        return 'None'
    return ', '.join(f"{k}={round(v, 4) if v is not None else None}" for k, v in m.items())


def verify_online(symbol):
    """联网：akshare 取带 turnover 的 qfq K 线自算 vs stock_cyq_em 最后一行。"""
    try:
        import akshare as ak
    except Exception as e:
        print(f"  [跳过] akshare 不可用：{e}")
        return

    try:
        k = ak.stock_zh_a_hist(symbol=symbol, period='daily',
                               start_date='20240101', end_date='20261231', adjust='qfq')
        if k is None or len(k) == 0:
            print(f"  [跳过] {symbol} K 线为空")
            return
        k = k.rename(columns={'开盘': 'open', '收盘': 'close', '最高': 'high',
                              '最低': 'low', '换手率': 'turnover'})
        local = cyqd.compute_chip_metrics(k)
        print(f"  本地自算(截止当日): {_fmt(local)}")
    except Exception as e:
        print(f"  [跳过] 拉取/自算失败：{type(e).__name__}: {e}")
        return

    try:
        cyq = ak.stock_cyq_em(symbol=symbol, adjust='qfq')
        if cyq is None or len(cyq) == 0:
            print(f"  [跳过] {symbol} stock_cyq_em 为空")
            return
        row = cyq.tail(1).iloc[0]
        em = {}
        for cn, en in _EM_COL_MAP.items():
            if cn in cyq.columns:
                val = row[cn]
                # 东财获利比例是 0~1，本地是 0~100，统一到百分比
                if en == 'winner_rate':
                    val = float(val) * 100.0
                em[en] = round(float(val), 4)
        print(f"  东财 stock_cyq_em : {em}  (日期 {row.get('日期', '?')})")

        if local is not None:
            print("  差异对照（本地 vs 东财）：")
            for en in _EM_COL_MAP.values():
                lv = local.get(en)
                ev = em.get(en)
                if lv is None or ev is None:
                    continue
                diff = lv - ev
                base = abs(ev) if abs(ev) > 1e-9 else 1.0
                print(f"    {en:18s} 本地={lv:10.4f}  东财={ev:10.4f}  Δ={diff:+8.4f} ({diff / base * 100:+6.2f}%)")
    except Exception as e:
        print(f"  [跳过] stock_cyq_em 失败：{type(e).__name__}: {e}")


def verify_local_cache(symbol):
    """离线：从本地缓存自算（若缓存含 turnover）。"""
    try:
        import quantia.core.stockfetch as stf
        h = stf.read_stock_hist_from_cache(symbol, '2020-01-01', '2030-01-01')
    except Exception as e:
        print(f"  [本地缓存] 读取失败：{e}")
        return
    if h is None or len(h) == 0:
        print("  [本地缓存] 无缓存")
        return
    if 'turnover' not in h.columns or h.tail(120)['turnover'].notna().sum() < 20:
        print("  [本地缓存] 缺少足够 turnover，跳过（需 Fetch 管道补齐换手率）")
        return
    m = cyqd.compute_chip_metrics(h)
    print(f"  [本地缓存] 自算: {_fmt(m)}")


def main():
    symbols = sys.argv[1:] or _DEFAULT_SYMBOLS
    print(f"===== 筹码分布准确性冒烟：{symbols} =====")
    for sym in symbols:
        print(f"\n[{sym}]")
        verify_local_cache(sym)
        verify_online(sym)
    print("\n完成。提示：本地/东财因窗口与复权口径差异，看量级与趋势一致即可，不要求逐位相等。")


if __name__ == '__main__':
    main()

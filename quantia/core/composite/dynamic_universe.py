"""
基本面预筛动态股票池 + 缓存（用户决策 #2: 实时获取 + 效率优先缓存文件）。

策略：
1. 缓存文件 `quantia/cache/composite/_universe_today.pkl`，TTL 24h
2. 每个交易日 08:30 由 cron 调用 `--refresh` 强制刷新
3. 回测/UI 直接读缓存（毫秒级）

评分公式（与 V3 一致）：
    0.20·rank(ROE) + 0.20·rank(net_profit_3y_cagr)
  + 0.15·rank(profit_yoy) + 0.15·rank(1-debt_ratio)
  + 0.15·rank(net_margin) + 0.10·rank(1-PE) + 0.05·rank(1-PB)
"""
from __future__ import annotations

import argparse
import logging
import os
import pickle
import time
from typing import Optional

import pandas as pd

from quantia.lib import database as mdb

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "cache", "composite")
CACHE_FILE = os.path.normpath(os.path.join(CACHE_DIR, "_universe_today.pkl"))
CACHE_TTL_SECONDS = 24 * 3600

# 与 V3 一致的过滤器
DEFAULT_FILTERS = {
    "min_market_cap_yi": 30,
    "max_pe": 80,
    "min_pe": 0,
    "min_roe": 7.0,
    "max_debt": 80.0,
    "min_profit_yoy": -20.0,
}


def _ensure_cache_dir() -> None:
    if not os.path.isdir(CACHE_DIR):
        os.makedirs(CACHE_DIR, exist_ok=True)


def _cache_is_fresh() -> bool:
    if not os.path.isfile(CACHE_FILE):
        return False
    age = time.time() - os.path.getmtime(CACHE_FILE)
    return age < CACHE_TTL_SECONDS


def _query_universe_from_db(top_n: int, filters: dict) -> pd.DataFrame:
    """从 cn_stock_selection 拉取最新一天的数据，应用基本面过滤后返回 top_n。"""
    cols = [
        "code", "name", "industry", "total_market_cap", "pe9", "pbnewmrq",
        "roe_weight", "sale_npr", "netprofit_yoy_ratio",
        "netprofit_growthrate_3y", "debt_asset_ratio",
    ]
    sql = (
        f"SELECT {', '.join(cols)} FROM cn_stock_selection "
        "WHERE date = (SELECT MAX(date) FROM cn_stock_selection) "
        "  AND total_market_cap >= %s "
        "  AND pe9 BETWEEN %s AND %s "
        "  AND roe_weight >= %s "
        "  AND debt_asset_ratio <= %s "
        "  AND netprofit_yoy_ratio >= %s "
        "  AND new_price > 0"
    )
    params = (
        filters["min_market_cap_yi"] * 1e8,
        filters["min_pe"],
        filters["max_pe"],
        filters["min_roe"],
        filters["max_debt"],
        filters["min_profit_yoy"],
    )
    rows = mdb.executeSqlFetch(sql, params)
    if not rows:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(rows, columns=cols)
    # 类型转换
    for c in ("total_market_cap", "pe9", "pbnewmrq", "roe_weight", "sale_npr",
              "netprofit_yoy_ratio", "netprofit_growthrate_3y", "debt_asset_ratio"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["roe_weight", "pe9", "pbnewmrq", "debt_asset_ratio"]).reset_index(drop=True)
    if df.empty:
        return df

    # 综合评分（与 V3 一致）
    df["s_roe"] = df["roe_weight"].rank(pct=True)
    df["s_3y"] = df["netprofit_growthrate_3y"].rank(pct=True)
    df["s_grw"] = df["netprofit_yoy_ratio"].rank(pct=True)
    df["s_dbt"] = (-df["debt_asset_ratio"]).rank(pct=True)
    df["s_npr"] = df["sale_npr"].rank(pct=True)
    df["s_pe"] = (-df["pe9"]).rank(pct=True)
    df["s_pb"] = (-df["pbnewmrq"]).rank(pct=True)
    df["score"] = (
        0.20 * df["s_roe"] + 0.20 * df["s_3y"] + 0.15 * df["s_grw"]
        + 0.15 * df["s_dbt"] + 0.15 * df["s_npr"]
        + 0.10 * df["s_pe"] + 0.05 * df["s_pb"]
    )
    df = df.sort_values("score", ascending=False).head(top_n).reset_index(drop=True)
    df["code"] = df["code"].astype(str).str.zfill(6)
    return df


def fetch_universe(top_n: int = 100, force_refresh: bool = False,
                   **filter_overrides) -> pd.DataFrame:
    """
    返回基本面综合评分前 top_n 的股票（columns: code, name, industry, score, ...）。

    用法：
        df = fetch_universe(top_n=100)
        codes = df["code"].tolist()
    """
    if not force_refresh and _cache_is_fresh():
        try:
            with open(CACHE_FILE, "rb") as fh:
                cached = pickle.load(fh)
            if isinstance(cached, pd.DataFrame) and len(cached) >= 1:
                if top_n >= len(cached):
                    return cached
                return cached.head(top_n).copy()
        except Exception as e:
            logging.warning(f"读取缓存失败，回退到查 DB: {e}")

    filters = {**DEFAULT_FILTERS, **filter_overrides}
    df = _query_universe_from_db(top_n, filters)
    _ensure_cache_dir()
    try:
        with open(CACHE_FILE, "wb") as fh:
            pickle.dump(df, fh)
    except Exception as e:
        logging.warning(f"写缓存失败（不影响返回）: {e}")
    return df


def fundamentals_signal(code: str, snapshot_date: Optional[pd.Timestamp] = None,
                        score_quantile_lt: float = 0.30,
                        roe_yoy_drop_pct_lt: float = -50.0) -> dict:
    """
    返回当日基本面买卖参考（用户决策 #4 — 阈值字段化，可后期调整）。

    返回结构：
        {"score": 87.3, "score_quantile": 0.92, "ROE": 18.5,
         "ROE_yoy_drop_pct": -8.2,
         "buy_bias": True,  # 综合评分 > 90 分位
         "sell_bias": False  # score_quantile < 阈值 OR ROE 同比跌幅 < 阈值（更负）
        }
    """
    df = fetch_universe(top_n=10000)  # 全量评分，用于求该股的分位
    if df.empty or "code" not in df.columns:
        return {"score": None, "score_quantile": None, "buy_bias": False, "sell_bias": False}
    code = str(code).zfill(6)
    row = df[df["code"] == code]
    if row.empty:
        # 不在基本面池里 → 评分极低，触发卖出参考
        return {"score": 0.0, "score_quantile": 0.0, "buy_bias": False, "sell_bias": True,
                "reason": "not_in_fundamentals_pool"}
    r = row.iloc[0]
    quant = float((df["score"] < r["score"]).mean())
    roe_yoy = float(r["netprofit_yoy_ratio"]) if pd.notna(r["netprofit_yoy_ratio"]) else 0.0
    sell = (quant < score_quantile_lt) or (roe_yoy < roe_yoy_drop_pct_lt)
    return {
        "score": float(r["score"]),
        "score_quantile": quant,
        "ROE": float(r["roe_weight"]) if pd.notna(r["roe_weight"]) else None,
        "ROE_yoy_drop_pct": roe_yoy,
        "buy_bias": quant > 0.90,
        "sell_bias": bool(sell),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="强制刷新缓存")
    parser.add_argument("--top-n", type=int, default=100)
    args = parser.parse_args()
    df = fetch_universe(top_n=args.top_n, force_refresh=args.refresh)
    print(f"universe: {len(df)} codes; cache file: {CACHE_FILE}")
    if not df.empty:
        print(df[["code", "name", "industry", "score"]].head(10).to_string(index=False))


if __name__ == "__main__":
    main()


__all__ = [
    "fetch_universe", "fundamentals_signal",
    "CACHE_FILE", "CACHE_TTL_SECONDS", "DEFAULT_FILTERS",
]

#!/usr/bin/env python3
"""Kronos Phase 1 多锚点滚动验证 CLI。"""

from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path

import pandas as pd

from quantia.core.backtest.data_feed import load_stock_data
from quantia.kronos.rolling_validation import http_provider, run_rolling_validation
from quantia.lib import database as mdb
from quantia.lib.trade_time import get_previous_trade_date, is_post_settlement, is_trade_date


def _csv_ints(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _codes(value: str) -> list[str]:
    path = Path(value)
    raw = path.read_text(encoding="utf-8").splitlines() if path.is_file() else value.split(",")
    codes = [item.strip() for item in raw if item.strip()]
    invalid = [code for code in codes if len(code) != 6 or not code.isdigit()]
    if invalid:
        raise ValueError(f"invalid stock codes: {invalid[:5]}")
    return codes


def _latest_complete_date(today: datetime.date | None = None) -> datetime.date:
    today = today or datetime.date.today()
    if is_trade_date(today) and is_post_settlement(today):
        return today
    return get_previous_trade_date(today)


def _available_trade_dates(anchor_start: str, actual_end: datetime.date) -> list[Any]:
    return pd.read_sql(
        "SELECT trade_date FROM cn_stock_trade_date "
        "WHERE trade_date >= %s AND trade_date <= %s ORDER BY trade_date",
        mdb.engine(), params=(anchor_start, actual_end),
    )["trade_date"].tolist()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run production-equivalent Kronos rolling validation")
    parser.add_argument("--codes", required=True, help="comma-separated codes or one-code-per-line file")
    parser.add_argument("--anchor-start", required=True)
    parser.add_argument("--anchor-end", required=True)
    parser.add_argument(
        "--actual-end",
        help="pin the latest available actual date; defaults to min(DB spot max, last complete day)",
    )
    parser.add_argument("--lookbacks", default="90,128,256")
    parser.add_argument("--horizons", default="1,3,5,10,15,30")
    parser.add_argument("--anchor-step", type=int, default=5)
    parser.add_argument("--max-anchors", type=int, default=0)
    parser.add_argument("--provider-url", default=os.environ.get(
        "QUANTIA_KPRED_LOCAL_URL", "http://127.0.0.1:18081/v1/open-api/kpred"))
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if args.actual_end:
        actual_end = pd.Timestamp(args.actual_end).date()
    else:
        spot_max = pd.read_sql(
            "SELECT MAX(date) AS max_date FROM cn_stock_spot", mdb.engine()
        ).iloc[0]["max_date"]
        if pd.isna(spot_max):
            raise RuntimeError("cn_stock_spot has no actual data")
        actual_end = min(pd.Timestamp(spot_max).date(), _latest_complete_date())
    trade_dates = _available_trade_dates(args.anchor_start, actual_end)
    result = run_rolling_validation(
        _codes(args.codes), trade_dates, load_stock_data,
        http_provider(args.provider_url, args.timeout),
        anchor_start=args.anchor_start,
        anchor_end=args.anchor_end,
        lookbacks=_csv_ints(args.lookbacks),
        horizons=_csv_ints(args.horizons),
        anchor_step=args.anchor_step,
        max_anchors=args.max_anchors,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({
        "output": str(output),
        "records": len(result["records"]),
        "config_hash": result["config_hash"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
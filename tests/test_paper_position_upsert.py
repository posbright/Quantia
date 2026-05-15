# -*- coding: utf-8 -*-
"""回归测试：cn_stock_backtest_position 写入必须使用 UPSERT，
防止并发调度（5min hourly + after_close）撞 unique key 1062，
丢失整个交易事务（含钉钉通知）。
"""
import pathlib
import re


def _read_paper_engine() -> str:
    p = pathlib.Path(__file__).resolve().parent.parent / 'quantia' / 'paper_trading' / 'paper_engine.py'
    return p.read_text(encoding='utf-8')


def test_paper_position_insert_uses_upsert():
    src = _read_paper_engine()
    # 找到所有 INSERT INTO cn_stock_backtest_position ... 的 SQL 语句
    matches = re.findall(
        r"INSERT INTO cn_stock_backtest_position[\s\S]{20,800}?(?=\)\s*'\s*[,)])",
        src,
    )
    assert matches, '未找到 INSERT INTO cn_stock_backtest_position 语句'
    for m in matches:
        assert 'ON DUPLICATE KEY UPDATE' in m, (
            'cn_stock_backtest_position 的 INSERT 必须使用 ON DUPLICATE KEY UPDATE，'
            f'否则并发调度会触发 1062. 当前 SQL:\n{m}'
        )

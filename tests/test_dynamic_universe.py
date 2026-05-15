"""动态股票池缓存测试。"""
import os
import time
import pytest
import pandas as pd

from quantia.core.composite import dynamic_universe as du


def test_fetch_universe_returns_dataframe():
    df = du.fetch_universe(top_n=20, force_refresh=True)
    assert isinstance(df, pd.DataFrame)
    if not df.empty:
        assert "code" in df.columns
        assert "score" in df.columns
        assert len(df) <= 20


def test_cache_file_created():
    df = du.fetch_universe(top_n=20, force_refresh=True)
    assert os.path.isfile(du.CACHE_FILE)


def test_cache_hit_avoids_db():
    # 第一次刷新
    du.fetch_universe(top_n=20, force_refresh=True)
    mtime1 = os.path.getmtime(du.CACHE_FILE)
    # 第二次不刷新 → 读缓存 → 文件 mtime 不变
    time.sleep(0.05)
    df = du.fetch_universe(top_n=10, force_refresh=False)
    mtime2 = os.path.getmtime(du.CACHE_FILE)
    assert mtime1 == mtime2
    assert len(df) <= 10


def test_force_refresh_rewrites_cache():
    du.fetch_universe(top_n=20, force_refresh=True)
    mtime1 = os.path.getmtime(du.CACHE_FILE)
    time.sleep(1.05)
    du.fetch_universe(top_n=20, force_refresh=True)
    mtime2 = os.path.getmtime(du.CACHE_FILE)
    assert mtime2 >= mtime1


def test_fundamentals_signal_unknown_code_is_sell_bias():
    sig = du.fundamentals_signal("999999")
    assert sig["sell_bias"] is True
    assert sig["score_quantile"] == 0.0

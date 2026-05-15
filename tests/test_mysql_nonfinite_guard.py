#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import math

import numpy as np
import pandas as pd


def test_keep_increasing_does_not_emit_inf_when_ma30_start_invalid():
    from quantia.core.strategy.keep_increasing import check

    dates = pd.bdate_range('2026-01-01', periods=30)
    data = pd.DataFrame({
        'date': dates,
        'close': np.linspace(10, 20, len(dates)),
        'p_change': np.linspace(0.1, 3.0, len(dates)),
    })

    assert check((dates[-1].strftime('%Y-%m-%d'), '000001', 'demo'), data, threshold=30) is False


def test_database_sanitizes_nonfinite_values_for_mysql():
    from quantia.lib import database

    data = pd.DataFrame({
        'code': ['000001', '000002', '000003'],
        'value': [1.5, float('inf'), -float('inf')],
        'nan_value': [np.nan, 2.0, 3.0],
    })

    sanitized = database._sanitize_dataframe_for_mysql(data)

    assert sanitized['value'].map(lambda value: isinstance(value, float) and math.isinf(value)).sum() == 0
    assert database._mysql_safe_value(float('inf')) is None
    assert database._mysql_safe_value(-float('inf')) is None
    assert database._mysql_safe_value(np.float64('inf')) is None
    assert database._is_mysql_null_value(float('nan')) is True
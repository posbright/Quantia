#!/usr/local/bin/python
# -*- coding: utf-8 -*-


import numpy as np
import pandas as pd
import talib as tl

__author__ = 'Quantia'
__date__ = '2026/02/14'


# 各板块单日跌停限制（取正值，%）。A股涨跌停幅度因板块/是否ST而异：
#   - 创业板(300/301)、科创板(688)：±20%（ST 同样 ±20%，不是 ±5%）
#   - 北交所(8xx/920/430)、4开头：±30%
#   - 主板 ST/*ST：±5%
#   - 主板普通：±10%
def _board_limit_pct(code, name):
    code = str(code or '')
    nm = str(name or '').upper()
    is_st = 'ST' in nm
    if code.startswith(('300', '301', '688')):
        return 20.0
    if code.startswith(('8', '920', '430', '4')):
        return 30.0
    if is_st:
        return 5.0
    return 10.0


# 放量跌停（重构版）
# 旧实现仅以固定 -9.5% 判定"跌停"，既忽略板块差异（创业板/科创板跌停为 -20%、
# 北交所 -30%、主板 ST -5%），又从不校验是否真正"封死跌停板"，导致大量"大跌但
# 未封板"的股票被误选；同时前复权(QFQ)历史价在除权/停牌复牌处会产生伪跳变
# （例如把 ST 单日跌幅算成 -35%），进一步污染结果。
#
# 重构后的"放量跌停"判定（三者同时满足）：
#   1. 单日真实跌幅贴近所属板块的跌停限制（自适应阈值，并剔除超过限制过多的
#      除权/复牌伪影）；
#   2. 收盘价封死在当日最低价附近（封板确认，同日内比值对复权不敏感）；
#   3. 放量：当日成交量 ≥ 5 日均量的 vol_ratio 倍，且成交额 ≥ min_turnover 亿。
#
# 参数（可经 UI/数据库 cn_strategy_params 真正接入每日选股与验证中心）：
#   vol_ratio          当日成交量需达到5日均量的倍数，默认 2.0
#   min_turnover       最低成交额(亿)，默认 2
#   near_limit_buffer  距板块跌停限制的容差(%)，默认 0.8（跌幅 ≥ 限制-0.8% 视为触及跌停）
#   sealed_tol         封板容差(%)，默认 0.5（收盘价 ≤ 当日最低价 ×(1+0.5%) 视为封板）
#   threshold          分析所需最少历史交易日数，默认 60
def check(code_name, data, date=None, threshold=60,
          vol_ratio=2.0, min_turnover=2,
          near_limit_buffer=0.8, sealed_tol=0.5):
    if date is None:
        end_date = code_name[0]
    else:
        end_date = date.strftime("%Y-%m-%d")
    if end_date is not None:
        if not pd.api.types.is_datetime64_any_dtype(data['date']):
            data = data.copy()
            data['date'] = pd.to_datetime(data['date'])
        end_date = pd.Timestamp(end_date)
        mask = (data['date'] <= end_date)
        data = data.loc[mask].copy()
    if len(data.index) < threshold:
        return False

    # 参数归一化（UI/DB 传入可能是字符串）
    try:
        vol_ratio_th = float(vol_ratio)
    except (TypeError, ValueError):
        vol_ratio_th = 2.0
    try:
        min_amount = float(min_turnover) * 100000000
    except (TypeError, ValueError):
        min_amount = 200000000
    try:
        buffer_pct = abs(float(near_limit_buffer))
    except (TypeError, ValueError):
        buffer_pct = 0.8
    try:
        sealed_ratio = 1.0 + abs(float(sealed_tol)) / 100.0
    except (TypeError, ValueError):
        sealed_ratio = 1.005

    # 至少需要 threshold+1 根K线（含前一交易日用于算单日涨跌幅）
    data = data.tail(n=threshold + 1)
    if len(data.index) < threshold + 1:
        return False

    last = data.iloc[-1]
    prev = data.iloc[-2]
    last_close = float(last['close'])
    last_low = float(last['low'])
    last_vol = float(last['volume'])
    prev_close = float(prev['close'])
    if prev_close <= 0 or last_close <= 0:
        return False

    # 1) 单日真实跌幅 + 板块自适应跌停阈值
    real_pct = (last_close / prev_close - 1.0) * 100.0
    code = code_name[1] if (isinstance(code_name, (list, tuple)) and len(code_name) > 1) else None
    name = code_name[2] if (isinstance(code_name, (list, tuple)) and len(code_name) > 2) else None
    limit = _board_limit_pct(code, name)
    # 除权/停牌复牌伪影：单日跌幅显著超过板块限制（>2.5%）属价格断点，剔除
    if real_pct < -(limit + 2.5):
        return False
    # 触及跌停：跌幅贴近板块限制
    if real_pct > -(limit - buffer_pct):
        return False

    # 2) 封板确认：收盘价封死在当日最低价附近
    if last_close > last_low * sealed_ratio:
        return False

    # 3) 放量：成交额 + 量比
    amount = last_close * last_vol
    if amount < min_amount:
        return False

    vol_ma5_arr = tl.MA(data['volume'].values.astype(float), timeperiod=5)
    # 用"截至前一日"的5日均量，避免当日放量自我稀释
    mean_vol = vol_ma5_arr[-2] if len(vol_ma5_arr) >= 2 else np.nan
    if mean_vol is None or not np.isfinite(mean_vol) or mean_vol <= 0:
        return False

    vr = last_vol / mean_vol
    if vr < vol_ratio_th:
        return False

    return {
        'p_change': round(float(real_pct), 2),
        'volume': int(last_vol),
        'vol_ma5': int(round(float(mean_vol))),
        'vol_ratio': round(float(vr), 2),
        'amount': round(float(amount), 2),
    }

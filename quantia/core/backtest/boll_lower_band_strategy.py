#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Built-in BOLL lower-band value strategy template."""

BOLL_LOWER_BAND_VALUE_STRATEGY_CODE = r'''# BOLL带下轨价值低位策略 v1.0
# 核心：基本面质量过滤 + 估值安全边际 + BOLL低位 + 趋势持有/高估拐点退出

def initialize(context):
    set_benchmark('000300')
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001,
                             open_commission=0.0003, close_commission=0.0003,
                             close_today_commission=0, min_commission=5), type='stock')
    g.pool_size = 120
    g.max_candidates = 35
    g.max_positions = 5
    g.initial_weight = 0.15
    g.confirm_weight = 0.20
    g.add_weight = 0.10
    g.max_weight = 0.30
    g.min_roe = 8
    g.min_quality_score = 70
    g.max_pe = 80
    g.max_pb = 8
    g.min_market_cap = 30
    g.day_count = 0
    g.high_price = {}
    g.trimmed = {}
    g.added = {}
    run_daily(trade, time='every_bar')


def _to_float(value, default=0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _current_date_key(context):
    text = str(context.current_dt)
    return text[:10]


def _latest_fundamentals(context):
    q = query(
        valuation.code,
        valuation.market_cap,
        valuation.pe_ratio,
        valuation.pb_ratio,
        indicator.roe,
        indicator.inc_net_profit_year_on_year,
        indicator.gross_profit_margin,
        indicator.net_profit_margin,
        cash_flow.net_operate_cash_flow,
    ).filter(
        valuation.market_cap > g.min_market_cap,
        valuation.pe_ratio > 0,
        valuation.pe_ratio < g.max_pe,
        valuation.pb_ratio > 0,
        valuation.pb_ratio < g.max_pb,
        indicator.roe > g.min_roe,
        indicator.inc_net_profit_year_on_year > -30,
    ).order_by(
        indicator.roe.desc()
    ).limit(g.pool_size)

    df = get_fundamentals(q, date=context.current_dt)
    if df is None or len(df) == 0:
        return []

    rows = []
    for _, row in df.iterrows():
        code = str(row['code']).split('.')[0]
        if len(code) != 6:
            continue
        pe = _to_float(row.get('pe_ratio', 0))
        pb = _to_float(row.get('pb_ratio', 0))
        roe = _to_float(row.get('roe', 0))
        growth = _to_float(row.get('inc_net_profit_year_on_year', 0))
        gross_margin = _to_float(row.get('gross_profit_margin', 0))
        net_margin = _to_float(row.get('net_profit_margin', 0))
        cash_flow_value = _to_float(row.get('net_operate_cash_flow', 0))

        value_score = 0
        if pe > 0:
            value_score += max(0, min(40, (g.max_pe - pe) / g.max_pe * 40))
        if pb > 0:
            value_score += max(0, min(25, (g.max_pb - pb) / g.max_pb * 25))
        quality_score = max(0, min(25, roe * 1.2))
        growth_score = max(0, min(10, growth / 5))
        margin_score = max(0, min(10, (gross_margin + net_margin) / 8))
        cash_score = 8 if cash_flow_value > 0 else 0
        score = value_score + quality_score + growth_score + margin_score + cash_score
        rows.append({'code': code, 'pe': pe, 'pb': pb, 'roe': roe, 'score': score})

    rows = sorted(rows, key=lambda item: item['score'], reverse=True)
    return rows[:g.max_candidates]


def _history(code, count):
    return attribute_history(code, count, '1d', ['close', 'high', 'low', 'volume'])


def _aggregate_bars(h, period_days):
    if h is None or len(h) < period_days:
        return pd.DataFrame(columns=['close', 'high', 'low', 'volume'])
    rows = []
    offset = len(h) % period_days
    if offset == 0:
        offset = period_days
    for end in range(offset + period_days, len(h) + 1, period_days):
        part = h.iloc[end - period_days:end]
        if len(part) < period_days:
            continue
        rows.append({
            'close': part['close'].iloc[-1],
            'high': part['high'].max() if 'high' in part.columns else part['close'].max(),
            'low': part['low'].min() if 'low' in part.columns else part['close'].min(),
            'volume': part['volume'].sum() if 'volume' in part.columns else 0,
        })
    return pd.DataFrame(rows)


def _boll(close, period=20):
    if close is None or len(close) < max(5, period):
        return None
    window = close.tail(period)
    middle = window.mean()
    std = window.std()
    return {
        'middle': middle,
        'upper': middle + 2 * std,
        'lower': middle - 2 * std,
    }


def _middle_slope(close, period=20, shift=3):
    if close is None or len(close) < period + shift:
        return 0
    current = close.tail(period).mean()
    previous = close.iloc[-period-shift:-shift].mean()
    if previous == 0:
        return 0
    return (current - previous) / previous


def _macd_green_shrinking(close):
    if close is None or len(close) < 35:
        return False
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    hist = dif - dea
    return hist.iloc[-1] < 0 and hist.iloc[-1] > hist.iloc[-2]


def _relative_strength_ok(close):
    try:
        bench = attribute_history('000300', 80, '1d', ['close'])
        if bench is None or len(bench) < 60 or len(close) < 60:
            return True
        stock_ret = close.iloc[-1] / close.iloc[-20] - 1
        bench_close = bench['close']
        bench_ret = bench_close.iloc[-1] / bench_close.iloc[-20] - 1
        return stock_ret >= bench_ret * 0.8
    except Exception:
        return True


def _market_allows_entry(context):
    h = attribute_history('000300', 520, '1d', ['close', 'high', 'low', 'volume'])
    if h is None or len(h) < 120:
        return True
    monthly = _aggregate_bars(h, 21)
    if len(monthly) >= 12:
        close = monthly['close']
        last = _to_float(close.iloc[-1])
        ma20 = close.tail(min(20, len(close))).mean()
        slope = _middle_slope(close, min(12, len(close) - 3), 3)
        boll = _boll(close, min(20, len(close)))
        lower = boll['lower'] if boll else ma20 * 0.85
        market_weak = last < ma20 * 0.95 and slope < 0
        channel_break = last < lower and slope < 0
        return not (market_weak or channel_break)
    close = h['close']
    last = _to_float(close.iloc[-1])
    ma120 = close.tail(120).mean()
    prev_ma120 = close.iloc[-140:-20].mean() if len(close) >= 140 else ma120
    long_middle = close.tail(120).mean()
    long_lower = long_middle - 2 * close.tail(120).std()
    market_weak = last < ma120 * 0.95 and ma120 < prev_ma120
    channel_break = last < long_lower and long_middle < prev_ma120
    return not (market_weak or channel_break)


def _rsi(close, period):
    if len(close) < period + 1:
        return 50
    diff = close.diff().dropna()
    up = diff.clip(lower=0).tail(period).mean()
    down = (-diff.clip(upper=0)).tail(period).mean()
    if down == 0:
        return 100
    rs = up / down
    return 100 - 100 / (1 + rs)


def _valid_number(value):
    try:
        return value == value
    except Exception:
        return False


def _ma5_crosses_ma20_up(close, lookback=5):
    if close is None or len(close) < 25:
        return False
    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    if not (_valid_number(ma5.iloc[-1]) and _valid_number(ma20.iloc[-1])):
        return False
    if ma5.iloc[-1] <= ma20.iloc[-1]:
        return False
    ma5_rising = ma5.iloc[-1] > ma5.iloc[-2]
    if len(ma5) >= 3 and _valid_number(ma5.iloc[-3]):
        ma5_rising = ma5_rising and ma5.iloc[-2] >= ma5.iloc[-3]
    if not ma5_rising:
        return False
    start = max(1, len(close) - max(1, lookback))
    for i in range(start, len(close)):
        values = [ma5.iloc[i - 1], ma20.iloc[i - 1], ma5.iloc[i], ma20.iloc[i]]
        if not all(_valid_number(v) for v in values):
            continue
        if ma5.iloc[i - 1] <= ma20.iloc[i - 1] and ma5.iloc[i] > ma20.iloc[i]:
            return True
    return False


def _monthly_lower_breakout_seen(monthly_close, lookback=6):
    if monthly_close is None or len(monthly_close) < 12:
        return False
    period = min(20, len(monthly_close))
    middle = monthly_close.rolling(period).mean()
    lower = middle - 2 * monthly_close.rolling(period).std()
    start = max(period - 1, len(monthly_close) - max(1, lookback))
    for i in range(start, len(monthly_close)):
        if not (_valid_number(monthly_close.iloc[i]) and _valid_number(lower.iloc[i])):
            continue
        if monthly_close.iloc[i] <= lower.iloc[i] * 1.02:
            return True
    return False


def _technical_state(code):
    h = _history(code, 520)
    if h is None or len(h) < 120:
        return None
    close = h['close']
    volume = h['volume'] if 'volume' in h.columns else close * 0
    last = _to_float(close.iloc[-1])
    if last <= 0:
        return None

    ma20 = close.tail(20).mean()
    ma60 = close.tail(60).mean()
    ma120 = close.tail(120).mean() if len(close) >= 120 else ma60
    prev_ma20 = close.iloc[-25:-5].mean() if len(close) >= 25 else ma20
    prev_ma60 = close.iloc[-80:-20].mean() if len(close) >= 80 else ma60
    daily_boll = _boll(close, 20)
    daily_upper = daily_boll['upper']
    daily_lower = daily_boll['lower']

    weekly = _aggregate_bars(h, 5)
    monthly = _aggregate_bars(h, 21)
    weekly_close = weekly['close'] if len(weekly) > 0 else close.tail(0)
    monthly_close = monthly['close'] if len(monthly) > 0 else close.tail(0)
    weekly_boll = _boll(weekly_close, 20) if len(weekly_close) >= 20 else None
    monthly_period = min(20, len(monthly_close))
    monthly_boll = _boll(monthly_close, monthly_period) if len(monthly_close) >= 12 else None
    monthly_lower_breakout_seen = _monthly_lower_breakout_seen(monthly_close, 6)
    daily_ma5_cross_ma20_up = _ma5_crosses_ma20_up(close, 10)

    long_window = close.tail(120)
    long_middle = long_window.mean()
    long_lower = long_middle - 2 * long_window.std()
    price_percentile = (long_window < last).sum() / max(len(long_window), 1)

    monthly_low_zone = False
    monthly_middle_slope = 0
    monthly_lower_slope = 0
    if monthly_boll:
        monthly_low_zone = last <= monthly_boll['lower'] * 1.05
        monthly_middle_slope = _middle_slope(monthly_close, min(12, len(monthly_close) - 3), 3)
        lower_series = monthly_close.rolling(min(12, len(monthly_close))).mean() - 2 * monthly_close.rolling(min(12, len(monthly_close))).std()
        if len(lower_series.dropna()) >= 4:
            prev_lower = lower_series.dropna().iloc[-4]
            if prev_lower != 0:
                monthly_lower_slope = (lower_series.dropna().iloc[-1] - prev_lower) / prev_lower

    weekly_middle = weekly_boll['middle'] if weekly_boll else ma60
    weekly_middle_slope = _middle_slope(weekly_close, 20, 3) if len(weekly_close) >= 23 else 0
    weekly_trend_healthy = last >= weekly_middle * 0.97 and weekly_middle_slope >= -0.02

    recent_low = close.tail(5).min()
    previous_low = close.tail(20).min()
    no_new_low = recent_low >= previous_low * 0.995
    rsi14 = _rsi(close, 14)
    vol_recent = volume.tail(5).mean()
    vol_mid = volume.tail(20).mean()
    volume_ok = vol_mid <= 0 or vol_recent >= vol_mid * 0.5
    strong_downtrend = ma20 < ma60 and ma60 < ma120 and ma20 < prev_ma20 and ma60 < prev_ma60
    rebound_blocked = ma20 < ma60 and close.tail(10).max() < close.iloc[-80:-20].max() * 0.98 and last < ma60
    low_zone = monthly_low_zone or last <= long_lower * 1.10 or price_percentile <= 0.35
    channel_not_extreme = monthly_middle_slope >= -0.05 and monthly_lower_slope >= -0.10
    macd_improving = _macd_green_shrinking(close)
    relative_strength_ok = _relative_strength_ok(close)

    stable_count = 0
    if last > daily_lower:
        stable_count += 1
    if no_new_low:
        stable_count += 1
    if rsi14 >= 35:
        stable_count += 1
    if macd_improving:
        stable_count += 1
    if weekly_middle_slope >= -0.02:
        stable_count += 1
    if relative_strength_ok:
        stable_count += 1
    if close.tail(5).mean() >= close.tail(10).mean() * 0.98:
        stable_count += 1
    if volume_ok:
        stable_count += 1

    return {
        'last': last,
        'ma20': ma20,
        'ma60': ma60,
        'ma120': ma120,
        'daily_upper': daily_upper,
        'daily_lower': daily_lower,
        'weekly_middle': weekly_middle,
        'weekly_middle_slope': weekly_middle_slope,
        'monthly_lower': monthly_boll['lower'] if monthly_boll else long_lower,
        'monthly_middle_slope': monthly_middle_slope,
        'long_lower': long_lower,
        'low_zone': low_zone,
        'monthly_lower_breakout_seen': monthly_lower_breakout_seen,
        'daily_ma5_cross_ma20_up': daily_ma5_cross_ma20_up,
        'post_break_price_ok': monthly_lower_breakout_seen and last <= ma60 * 1.10,
        'channel_not_extreme': channel_not_extreme,
        'strong_downtrend': strong_downtrend,
        'rebound_blocked': rebound_blocked,
        'stable_count': stable_count,
        'rsi': rsi14,
        'volume_ok': volume_ok,
        'trend_healthy': ma20 >= ma60 * 0.98 and last >= ma60 * 0.95 and weekly_trend_healthy,
        'weekly_break': last < weekly_middle * 0.95 and weekly_middle_slope < 0,
        'macd_improving': macd_improving,
        'relative_strength_ok': relative_strength_ok,
    }


def _is_entry(row, state):
    if state is None:
        return False
    value_ok = row['pe'] <= 35 or row['pb'] <= 2.5
    quality_ok = row['roe'] >= g.min_roe and row['score'] >= g.min_quality_score
    trend_ok = not state['strong_downtrend'] and not state['rebound_blocked']
    entry_trigger = state['monthly_lower_breakout_seen'] and state['daily_ma5_cross_ma20_up']
    return value_ok and quality_ok and entry_trigger and trend_ok and state['stable_count'] >= 3


def _target_value(context, weight):
    return context.portfolio.total_value * min(weight, g.max_weight)


def _sell_risk_positions(context):
    for code in list(context.portfolio.positions.keys()):
        pos = context.portfolio.positions[code]
        if pos.amount <= 0:
            continue
        state = _technical_state(code)
        if state is None:
            continue
        last = state['last']
        high = g.high_price.get(code, last)
        if last > high:
            high = last
        g.high_price[code] = high
        profit = pos.profit_rate
        drawdown_from_high = (high - last) / high if high > 0 else 0

        if profit <= -0.20 or state['weekly_break']:
            order_target(code, 0)
            g.high_price.pop(code, None)
            g.trimmed.pop(code, None)
            g.added.pop(code, None)
            log.info('拐点/止损清仓 ' + code)
            continue

        over_upper = last > state['daily_upper']
        overvalued_profit = profit > 0.45
        exhaustion = drawdown_from_high > 0.08 and last < state['ma20']
        if overvalued_profit and exhaustion:
            order_target(code, 0)
            g.high_price.pop(code, None)
            g.trimmed.pop(code, None)
            g.added.pop(code, None)
            log.info('高估衰竭清仓 ' + code)
        elif over_upper and not state['trend_healthy']:
            target = max(pos.value * 0.70, _target_value(context, 0.05))
            order_target_value(code, target)
            g.trimmed[code] = True
            log.info('上轨风险减仓 ' + code)
        elif over_upper and code not in g.trimmed:
            target = pos.value * 0.85
            order_target_value(code, target)
            g.trimmed[code] = True
            log.info('强趋势上轨小幅减仓 ' + code)


def _buy_candidates(context):
    if not _market_allows_entry(context):
        log.info('大盘环境弱势，暂停BOLL低位新开仓')
        return
    fundamentals = _latest_fundamentals(context)
    selected = []
    for row in fundamentals:
        code = row['code']
        state = _technical_state(code)
        if _is_entry(row, state):
            score = row['score'] + state['stable_count'] * 5 - state['rsi'] * 0.1
            selected.append((score, code, state))

    selected = sorted(selected, reverse=True)
    for _, code, state in selected:
        if code in context.portfolio.positions:
            pos = context.portfolio.positions[code]
            target_value = _target_value(context, g.confirm_weight)
            if pos.value < _target_value(context, g.confirm_weight) * 0.90 and state['trend_healthy']:
                order_target_value(code, target_value)
                log.info('周线企稳提高仓位 ' + code)
            elif pos.profit_rate <= -0.10 and code not in g.added and state['stable_count'] >= 3 and not state['strong_downtrend']:
                add_target = min(pos.value + context.portfolio.total_value * g.add_weight,
                                 _target_value(context, g.max_weight))
                if add_target > pos.value * 1.05:
                    order_target_value(code, add_target)
                    g.added[code] = True
                    log.info('亏损企稳加仓 ' + code)
            elif code in g.trimmed and state['trend_healthy'] and state['stable_count'] >= 3 and state['last'] <= state['ma20'] * 1.03:
                order_target_value(code, target_value)
                g.trimmed.pop(code, None)
                log.info('趋势回调企稳回补 ' + code)
            continue
        if len(context.portfolio.positions) >= g.max_positions:
            break
        order_target_value(code, _target_value(context, g.initial_weight))
        g.high_price[code] = state['last']
        g.trimmed.pop(code, None)
        g.added.pop(code, None)
        log.info('月线下轨后MA5上穿MA20买入 ' + code)


def trade(context):
    g.day_count += 1
    _sell_risk_positions(context)
    if g.day_count % 5 != 1:
        return
    _buy_candidates(context)
'''


BOLL_LOWER_BAND_VALUE_TEMPLATE = {
    'id': 'boll_lower_band_value',
    'name': 'BOLL带下轨价值低位策略',
    'category': 'stock',
    'description': '基本面质量与估值过滤后，在BOLL低位分批买入；上涨趋势持有，高估或拐点确认后退出。',
    'code': BOLL_LOWER_BAND_VALUE_STRATEGY_CODE,
}
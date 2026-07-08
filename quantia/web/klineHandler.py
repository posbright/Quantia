#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K线数据JSON API

提供前端ECharts所需的K线数据（OHLCV + 技术指标），
用于替代Bokeh服务端渲染方式。
"""

import json
import logging
import datetime
import numpy as np
from abc import ABC

import quantia.core.stockfetch as stf
import quantia.core.kline.chip_distribution as cyqd
import quantia.web.base as webBase
from quantia.lib.database import executeSqlFetch

__author__ = 'Quantia'
__date__ = '2026/02/14'

# 筹码标量指标字段（与 cn_stock_chip_distribution 表 / compute_chip_metrics 对齐）
_CHIP_METRIC_KEYS = (
    'winner_rate', 'avg_cost', 'cost_90_low', 'cost_90_high',
    'concentration_90', 'cost_70_low', 'cost_70_high', 'concentration_70',
)


def _safe_float(val):
    """将 numpy/pandas 数值转为 Python float，NaN 转 None"""
    if val is None:
        return None
    try:
        f = float(val)
        if np.isnan(f) or np.isinf(f):
            return None
        return round(f, 4)
    except (TypeError, ValueError):
        return None


def _compute_ma(closes, period):
    """计算移动平均线"""
    result = []
    for i in range(len(closes)):
        if i < period - 1:
            result.append(None)
        else:
            avg = sum(closes[i - period + 1:i + 1]) / period
            result.append(round(avg, 4))
    return result


def _compute_ema(closes, period):
    """计算指数移动平均线"""
    result = []
    k = 2.0 / (period + 1)
    ema = None
    for c in closes:
        if c is None:
            result.append(None)
            continue
        if ema is None:
            ema = c
        else:
            ema = c * k + ema * (1 - k)
        result.append(round(ema, 4))
    return result


def _compute_boll(closes, period=20, nbdev=2):
    """计算布林带 (上轨, 中轨, 下轨)"""
    upper, middle, lower = [], [], []
    for i in range(len(closes)):
        if i < period - 1:
            upper.append(None)
            middle.append(None)
            lower.append(None)
        else:
            window = closes[i - period + 1:i + 1]
            ma = sum(window) / period
            std = (sum((x - ma) ** 2 for x in window) / period) ** 0.5
            middle.append(round(ma, 4))
            upper.append(round(ma + nbdev * std, 4))
            lower.append(round(ma - nbdev * std, 4))
    return upper, middle, lower


def _compute_rsi(closes, period=14):
    """计算RSI"""
    result = [None]
    for i in range(1, len(closes)):
        if i < period:
            result.append(None)
            continue
        gains, losses = 0.0, 0.0
        for j in range(i - period + 1, i + 1):
            diff = closes[j] - closes[j - 1]
            if diff > 0:
                gains += diff
            else:
                losses -= diff
        avg_gain = gains / period
        avg_loss = losses / period
        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(round(100 - 100 / (1 + rs), 2))
    return result


def _compute_macd(closes, fast=12, slow=26, signal=9):
    """计算MACD (DIF, DEA, MACD柱)"""
    ema_fast = _compute_ema(closes, fast)
    ema_slow = _compute_ema(closes, slow)
    dif = []
    for ef, es in zip(ema_fast, ema_slow):
        if ef is None or es is None:
            dif.append(None)
        else:
            dif.append(round(ef - es, 4))
    # DEA = EMA(DIF, signal) — 跳过 None 值而非用 0 填充，避免数据失真
    dea = _compute_ema(dif, signal)
    macd_hist = []
    for d, a in zip(dif, dea):
        if d is None or a is None:
            macd_hist.append(None)
        else:
            macd_hist.append(round(2 * (d - a), 4))
    return dif, dea, macd_hist


def _compute_kdj(closes, highs, lows, n=9, m1=3, m2=3):
    """计算KDJ指标"""
    length = len(closes)
    k_vals = [50.0] * length
    d_vals = [50.0] * length
    j_vals = [50.0] * length
    for i in range(length):
        if i < n - 1:
            continue
        window_high = max(highs[i - n + 1:i + 1])
        window_low = min(lows[i - n + 1:i + 1])
        if window_high == window_low:
            rsv = 50.0
        else:
            rsv = (closes[i] - window_low) / (window_high - window_low) * 100
        prev_k = k_vals[i - 1] if i > 0 else 50.0
        prev_d = d_vals[i - 1] if i > 0 else 50.0
        k_vals[i] = round((m1 - 1) / m1 * prev_k + 1 / m1 * rsv, 2)
        d_vals[i] = round((m2 - 1) / m2 * prev_d + 1 / m2 * k_vals[i], 2)
        j_vals[i] = round(3 * k_vals[i] - 2 * d_vals[i], 2)
    # 前 n-1 个设为 None
    for i in range(min(n - 1, length)):
        k_vals[i] = None
        d_vals[i] = None
        j_vals[i] = None
    return k_vals, d_vals, j_vals


def _compute_wr(closes, highs, lows, period=10):
    """计算威廉指标 WR"""
    result = []
    for i in range(len(closes)):
        if i < period - 1:
            result.append(None)
        else:
            window_high = max(highs[i - period + 1:i + 1])
            window_low = min(lows[i - period + 1:i + 1])
            if window_high == window_low:
                result.append(0.0)
            else:
                result.append(round((window_high - closes[i]) / (window_high - window_low) * -100, 2))
    return result


def _compute_bbi(closes):
    """计算多空趋势 BBI (Bull Bear Index)
    BBI = (MA3 + MA6 + MA12 + MA24) / 4
    MABB = MA(BBI, 6) 信号线
    """
    ma3 = _compute_ma(closes, 3)
    ma6 = _compute_ma(closes, 6)
    ma12 = _compute_ma(closes, 12)
    ma24 = _compute_ma(closes, 24)
    bbi = []
    for a, b, c, d in zip(ma3, ma6, ma12, ma24):
        if any(v is None for v in (a, b, c, d)):
            bbi.append(None)
        else:
            bbi.append(round((a + b + c + d) / 4, 4))
    # MABB signal line: MA of BBI values
    bbi_for_ma = [v if v is not None else 0 for v in bbi]
    mabb = _compute_ma(bbi_for_ma, 6)
    # 前 23 个设为 None (需要 MA24 的24个数据点)
    for i in range(min(23, len(mabb))):
        mabb[i] = None
    return bbi, mabb


def _resample_to_period(df, period):
    """
    将日线数据重采样为周线/月线/季线/年线
    period: 'W' / 'M' / 'Q' / 'Y'
    """
    import pandas as pd
    if df is None or df.empty:
        return df

    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date')

    agg_dict = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
    }
    # 只聚合存在的列
    agg_dict = {k: v for k, v in agg_dict.items() if k in df.columns}

    if period == 'W':
        resampled = df.resample('W-FRI').agg(agg_dict)
    elif period == 'M':
        resampled = df.resample('ME').agg(agg_dict)
    elif period == 'Q':
        resampled = df.resample('QE').agg(agg_dict)
    elif period == 'Y':
        resampled = df.resample('YE').agg(agg_dict)
    else:
        return df.reset_index()

    resampled = resampled.dropna(subset=['open'])
    resampled = resampled.reset_index()
    resampled['date'] = resampled['date'].dt.strftime('%Y-%m-%d')
    return resampled


def _slice_kline_result(result, start_date=None, end_date=None, warmup_days=0, days=None):
    dates = result.get('dates') or []
    if not dates:
        return result

    start_idx = 0
    end_idx = len(dates)
    if start_date:
        found = next((i for i, d in enumerate(dates) if d >= start_date), None)
        if found is not None:
            start_idx = max(0, found - max(0, int(warmup_days or 0)))
    if end_date:
        found = next((i for i, d in enumerate(dates) if d > end_date), None)
        end_idx = found if found is not None else len(dates)

    if not start_date and not end_date and days:
        try:
            n = int(days)
            if 0 < n < len(dates):
                start_idx = len(dates) - n
        except (ValueError, TypeError):
            pass

    def slice_value(value):
        if isinstance(value, list) and len(value) == len(dates):
            return value[start_idx:end_idx]
        if isinstance(value, dict):
            return {k: slice_value(v) for k, v in value.items()}
        return value

    sliced = {k: slice_value(v) for k, v in result.items()}
    sliced['total'] = len(sliced.get('dates') or [])
    sliced['source_total'] = len(dates)
    sliced['indicator_source'] = 'full_cache_before_slice'
    return sliced


class GetKlineDataHandler(webBase.BaseHandler, ABC):
    """
    K线数据JSON API（仿东方财富风格，返回全量数据供前端 dataZoom 控制视图）

    参数:
        code: 股票代码 (必填)
        date: 日期 (可选, 默认今天)
        period: 周期 (可选, 默认 'daily')
                可选值: daily / weekly / monthly / quarterly / yearly
        days: 返回天数 (可选, 不设置则返回全部可用数据)
        name: 股票名称 (可选)

    返回:
        {
            code, name, period, total,
            dates, ohlc, volumes,
            ma: {ma5, ma10, ma20, ma30, ma60},
            vol_ma: {ma5, ma10},
            boll: {upper, middle, lower},
            rsi, macd: {dif, dea, histogram},
            kdj: {k, d, j},
            wr: {wr10, wr6},
        }
    """

    def get(self):
        self.set_header('Content-Type', 'application/json;charset=UTF-8')
        code = self.get_argument("code", default=None, strip=True)
        date = self.get_argument("date", default=None, strip=True)
        period = self.get_argument("period", default="daily", strip=True)
        days = self.get_argument("days", default=None, strip=True)
        start_date = self.get_argument("start_date", default=None, strip=True)
        end_date = self.get_argument("end_date", default=None, strip=True)
        warmup_days = self.get_argument("warmup_days", default="0", strip=True)
        name = self.get_argument("name", default="", strip=True)
        data_type = self.get_argument("type", default=None, strip=True)  # 'index'/'stock'/None

        if not code:
            self.set_status(400)
            self.write(json.dumps({"error": "缺少 code 参数"}, ensure_ascii=False))
            return

        try:
            # K线图始终返回到最新可用数据，不受前端 date 参数截断
            # （前端 date 来自列表页导航上下文，可能是旧日期如3月3号）
            today = datetime.datetime.now().strftime('%Y-%m-%d')

            # 根据 type 参数决定缓存查找顺序，避免同代码股票/指数混淆
            # （如 000001 同时对应上证指数和平安银行）
            if data_type == 'index':
                stock = stf.read_index_hist_from_cache(code)
                if stock is None or stock.empty:
                    # 指数缓存缺失时，按需仅补当前指数缓存，避免错误回退到同代码股票K线。
                    try:
                        end_ymd = datetime.datetime.now().strftime('%Y%m%d')
                        start_ymd = (datetime.datetime.now() - datetime.timedelta(
                            days=stf.HIST_DATA_DEFAULT_YEARS * 365)).strftime('%Y%m%d')
                        stf.index_hist_cache_incremental(code, start_ymd, end_ymd)
                        stock = stf.read_index_hist_from_cache(code)
                    except Exception as e:
                        logging.warning(f"指数缓存按需更新失败: {code} - {e}")
                if stock is None or stock.empty:
                    self.write(json.dumps({
                        "error": "无指数K线数据（指数缓存未命中或更新失败）",
                        "code": code,
                        "type": "index"
                    }, ensure_ascii=False))
                    return
            else:
                stock = stf.read_hist_from_cache((today, code), years=50)
                if stock is None or stock.empty:
                    stock = stf.read_index_hist_from_cache(code)

            if stock is None or stock.empty:
                self.write(json.dumps({"error": "无K线数据（缓存未命中，请确认数据采集任务已运行）", "code": code}, ensure_ascii=False))
                return

            # 根据 period 重采样
            period_map = {
                'daily': None,
                'weekly': 'W',
                'monthly': 'M',
                'quarterly': 'Q',
                'yearly': 'Y',
            }
            resample_key = period_map.get(period)
            if resample_key:
                stock = _resample_to_period(stock, resample_key)

            # 提取数据
            dates = stock['date'].astype(str).tolist()
            opens = [_safe_float(v) for v in stock['open'].tolist()]
            closes = [_safe_float(v) for v in stock['close'].tolist()]
            highs = [_safe_float(v) for v in stock['high'].tolist()]
            lows = [_safe_float(v) for v in stock['low'].tolist()]
            volumes = [int(v) if v == v else 0 for v in stock['volume'].tolist()]

            # OHLC 格式 (ECharts candlestick: [open, close, low, high])
            ohlc = []
            for o, c, l, h in zip(opens, closes, lows, highs):
                ohlc.append([o, c, l, h])

            # 每日明细字段（供 tooltip 展示）：换手率/振幅/涨跌幅。
            # 历史缓存含这些列；指数或重采样后可能缺失，故按列存在性兜底。
            def _col_or_none(col_name):
                if col_name in stock.columns:
                    return [_safe_float(v) for v in stock[col_name].tolist()]
                return None

            # 缓存标准列名为 turnover（见 CN_STOCK_HIST_DATA），旧代码误用 turnoverrate
            # 导致换手率恒为 None；此处优先 turnover 并向后兼容旧列名。
            turnover = _col_or_none('turnover') or _col_or_none('turnoverrate')
            amplitude = _col_or_none('amplitude')
            change_pct = _col_or_none('quote_change')

            # 用于计算指标的 close/high/low 数组（None->0）
            closes_clean = [c if c is not None else 0 for c in closes]
            highs_clean = [h if h is not None else 0 for h in highs]
            lows_clean = [l if l is not None else 0 for l in lows]

            # 计算指标
            ma5 = _compute_ma(closes_clean, 5)
            ma10 = _compute_ma(closes_clean, 10)
            ma20 = _compute_ma(closes_clean, 20)
            ma30 = _compute_ma(closes_clean, 30)
            ma60 = _compute_ma(closes_clean, 60)
            vol_ma5 = _compute_ma(volumes, 5)
            vol_ma10 = _compute_ma(volumes, 10)
            boll_upper, boll_middle, boll_lower = _compute_boll(closes_clean, 20, 2)
            rsi = _compute_rsi(closes_clean, 14)
            macd_dif, macd_dea, macd_hist = _compute_macd(closes_clean, 12, 26, 9)
            kdj_k, kdj_d, kdj_j = _compute_kdj(closes_clean, highs_clean, lows_clean, 9, 3, 3)
            wr10 = _compute_wr(closes_clean, highs_clean, lows_clean, 10)
            wr6 = _compute_wr(closes_clean, highs_clean, lows_clean, 6)
            bbi, mabb = _compute_bbi(closes_clean)

            result = {
                "code": code,
                "name": name,
                "period": period,
                "total": len(dates),
                "dates": dates,
                "ohlc": ohlc,
                "volumes": volumes,
                "turnover": turnover,
                "amplitude": amplitude,
                "change_pct": change_pct,
                "ma": {
                    "ma5": ma5,
                    "ma10": ma10,
                    "ma20": ma20,
                    "ma30": ma30,
                    "ma60": ma60,
                },
                "vol_ma": {
                    "ma5": vol_ma5,
                    "ma10": vol_ma10,
                },
                "boll": {
                    "upper": boll_upper,
                    "middle": boll_middle,
                    "lower": boll_lower,
                },
                "rsi": rsi,
                "macd": {
                    "dif": macd_dif,
                    "dea": macd_dea,
                    "histogram": macd_hist,
                },
                "kdj": {
                    "k": kdj_k,
                    "d": kdj_d,
                    "j": kdj_j,
                },
                "wr": {
                    "wr10": wr10,
                    "wr6": wr6,
                },
                "bbi": {
                    "bbi": bbi,
                    "mabb": mabb,
                },
            }

            result = _slice_kline_result(
                result,
                start_date=start_date,
                end_date=end_date,
                warmup_days=warmup_days,
                days=days,
            )

            self.write(json.dumps(result, ensure_ascii=False))

        except Exception as e:
            logging.error(f"klineHandler.GetKlineDataHandler处理异常", exc_info=True)
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}, ensure_ascii=False))


def _d10(value):
    """归一化为 YYYY-MM-DD（截前 10 位），供日期字符串比较。"""
    return str(value)[:10]


def _pick_chip_metrics(source):
    """从 dict 抽取标准筹码标量字段（缺失置 None）。"""
    return {k: _safe_float(source.get(k)) for k in _CHIP_METRIC_KEYS}


def _query_chip_db(code, target_date):
    """查最近一条 date<=target_date 的筹码标量行（仅显式列，符合"验证优先"）。

    Returns:
        dict | None：含 date/name/close + 8 个标量字段。
    """
    try:
        rows = executeSqlFetch(
            "SELECT date, name, close, winner_rate, avg_cost, cost_90_low, cost_90_high, "
            "concentration_90, cost_70_low, cost_70_high, concentration_70 "
            "FROM cn_stock_chip_distribution WHERE code=%s AND date<=%s "
            "ORDER BY date DESC LIMIT 1",
            (code, target_date),
        )
    except Exception:
        logging.debug(f"筹码分布 DB 查询失败: {code}", exc_info=True)
        return None
    if not rows:
        return None
    r = rows[0]
    return {
        'date': _d10(r[0]),
        'name': r[1] or '',
        'close': _safe_float(r[2]),
        'winner_rate': _safe_float(r[3]),
        'avg_cost': _safe_float(r[4]),
        'cost_90_low': _safe_float(r[5]),
        'cost_90_high': _safe_float(r[6]),
        'concentration_90': _safe_float(r[7]),
        'cost_70_low': _safe_float(r[8]),
        'cost_70_high': _safe_float(r[9]),
        'concentration_70': _safe_float(r[10]),
    }


class GetChipDistributionHandler(webBase.BaseHandler, ABC):
    """筹码分布 API（DB 标量优先，直方图现算）。

    参数:
        code: 股票代码 (必填)
        date: 目标日期 (可选，默认今天；取 <= 该日的最近一条 DB 标量)
        name: 股票名称 (可选)

    返回:
        {
            code, name, has_chip, metrics_source, metrics_as_of, close,
            metrics: {winner_rate, avg_cost, cost_90_low/high, concentration_90,
                      cost_70_low/high, concentration_70} | null,
            distribution: {prices:[...], chips:[...], as_of} | null,
            message
        }

    说明:
        - metrics 优先取 cn_stock_chip_distribution 表（快）；DB miss 或过期
          （早于本地缓存最新交易日）则用本地缓存现算。
        - distribution（筹码峰图直方图）DB 不存储，始终现算，需缓存含 turnover；
          缺 turnover 的股票（如新浪源）distribution 为 null，仅返回标量。
    """

    def get(self):
        self.set_header('Content-Type', 'application/json;charset=UTF-8')
        code = self.get_argument("code", default=None, strip=True)
        date = self.get_argument("date", default=None, strip=True)
        name = self.get_argument("name", default="", strip=True)

        if not code:
            self.set_status(400)
            self.write(json.dumps({"error": "缺少 code 参数"}, ensure_ascii=False))
            return

        try:
            today = datetime.datetime.now().strftime('%Y-%m-%d')
            target = _d10(date) if date else today

            db_row = _query_chip_db(code, target)

            # 现算直方图 + 标量（需缓存含 turnover）
            computed = None
            cache_last_date = None
            stock = stf.read_hist_from_cache((today, code), years=50)
            if stock is not None and not stock.empty:
                cache_last_date = _d10(stock['date'].iloc[-1])
                if 'turnover' in stock.columns:
                    try:
                        computed = cyqd.compute_chip_distribution(stock)
                    except Exception:
                        logging.debug(f"compute_chip_distribution 异常: {code}", exc_info=True)
                        computed = None

            # DB 行是否过期（早于本地缓存最新交易日）
            db_stale = (
                db_row is not None and cache_last_date is not None
                and db_row['date'] < cache_last_date
            )

            metrics = None
            metrics_source = 'none'
            metrics_as_of = None
            close = None

            if db_row is not None and not db_stale:
                metrics = _pick_chip_metrics(db_row)
                metrics_source = 'db'
                metrics_as_of = db_row['date']
                close = db_row['close']
            elif computed is not None:
                metrics = _pick_chip_metrics(computed['metrics'])
                metrics_source = 'compute'
                metrics_as_of = cache_last_date
                close = computed['close']
            elif db_row is not None:
                # 过期但无法现算（缺 turnover）→ 退回 DB 标量并标注 stale
                metrics = _pick_chip_metrics(db_row)
                metrics_source = 'db_stale'
                metrics_as_of = db_row['date']
                close = db_row['close']

            distribution = None
            if computed is not None:
                distribution = {
                    'prices': computed['prices'],
                    'chips': computed['chips'],
                    'as_of': cache_last_date,
                }

            has_chip = metrics is not None
            message = ""
            if not has_chip:
                message = "该股暂无筹码数据（缺少历史换手率，无法计算）"
            elif distribution is None:
                message = "筹码峰图需换手率数据，该股暂缺，仅显示成本指标"

            result = {
                'code': code,
                'name': name or (db_row['name'] if db_row else ''),
                'has_chip': has_chip,
                'metrics_source': metrics_source,
                'metrics_as_of': metrics_as_of,
                'close': close,
                'metrics': metrics,
                'distribution': distribution,
                'message': message,
            }
            self.write(json.dumps(result, ensure_ascii=False))

        except Exception as e:
            logging.error("klineHandler.GetChipDistributionHandler处理异常", exc_info=True)
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}, ensure_ascii=False))

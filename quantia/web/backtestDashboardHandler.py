#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回测看板 API Handler

目标：为前端“回测看板”提供更直观的汇总/明细/分布/时间序列/买卖配对数据。

说明：
- 本模块尽量复用现有宽表结构（策略表/指标表 rate_1~rate_100）。
- 跨策略总览优先基于 cn_stock_backtest（字段 avg_rate_1/3/5/10/20）。
"""

import datetime
import json
import logging
import re
from abc import ABC

import numpy as np
import pandas as pd

import quantia.core.stockfetch as stf
import quantia.core.tablestructure as tbs
import quantia.lib.trade_time as trd
import quantia.lib.database as mdb
import quantia.web.base as webBase
from quantia.core.backtest.rate_stats import ROUND_TRIP_COST_PCT
from quantia.web.utils import parse_int_list as _parse_int_list, json_default as _json_default

__author__ = 'Quantia'
__date__ = '2026/02/27'


SUMMARY_HORIZONS = [1, 3, 5, 10, 20, 30, 60, 90, 120]
MAX_TABLE_HORIZON = 100


_DATE_RE = re.compile(r'^(?P<y>\d{4})[-/\.]?(?P<m>\d{1,2})[-/\.]?(?P<d>\d{1,2})$')


# _json_default 和 _parse_int_list 已抽取到 quantia.web.utils


def _parse_date_ymd(text: str):
    """Parse date input into ('YYYY-MM-DD', datetime.date) or (None, None)."""
    if text is None:
        return None, None
    s = str(text).strip()
    if not s:
        return None, None
    m = _DATE_RE.match(s)
    if not m:
        return None, None
    try:
        y = int(m.group('y'))
        mo = int(m.group('m'))
        d = int(m.group('d'))
        dt = datetime.date(y, mo, d)
    except Exception:
        return None, None
    return dt.strftime('%Y-%m-%d'), dt


def _to_yyyymmdd_loose(v: object) -> str:
    """Convert date-like input to YYYYMMDD string.

    Accepts:
    - datetime/date
    - 'YYYY-MM-DD', 'YYYY/MM/DD', 'YYYY.MM.DD', 'YYYYMMDD'
    - anything else -> ''
    """
    if v is None:
        return ''
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.strftime('%Y%m%d')
    s = str(v).strip()
    if not s:
        return ''
    m = _DATE_RE.match(s)
    if m:
        try:
            y = int(m.group('y'))
            mo = int(m.group('m'))
            d = int(m.group('d'))
            dt = datetime.date(y, mo, d)
            return dt.strftime('%Y%m%d')
        except Exception:
            return ''
    # fallback: remove common separators and validate length
    s2 = s.replace('-', '').replace('/', '').replace('.', '')
    return s2 if len(s2) == 8 and s2.isdigit() else ''


def _to_dash_ymd_loose(v: object) -> str:
    """Convert date-like input to YYYY-MM-DD string when possible."""
    if v is None:
        return ''
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.strftime('%Y-%m-%d')
    s = str(v).strip()
    if not s:
        return ''
    m = _DATE_RE.match(s)
    if m:
        try:
            y = int(m.group('y'))
            mo = int(m.group('m'))
            d = int(m.group('d'))
            dt = datetime.date(y, mo, d)
            return dt.strftime('%Y-%m-%d')
        except Exception:
            return s
    s2 = s.replace('-', '').replace('/', '').replace('.', '')
    if len(s2) == 8 and s2.isdigit():
        return f"{s2[:4]}-{s2[4:6]}-{s2[6:]}"
    return s


def _pick_first_sell_after(buy_key: str, sell_dates: list) -> str:
    """Pick the first sell signal strictly after buy_key.

    - buy_key: YYYYMMDD
    - sell_dates: list of date-like values (typically strings from DB)

    Returns original sell date string (as stored in DB) or '' if not found.
    """
    if not buy_key:
        return ''
    try:
        items = sell_dates or []
    except Exception:
        items = []

    for d in items:
        dk = _to_yyyymmdd_loose(d)
        if not dk:
            continue
        if dk > buy_key:
            return str(d)
    return ''


def _apply_max_hold_exit_rule(buy_idx: int, sell_idx: object, max_hold: int, hist_len: int):
    """Decide exit type and final sell index.

    If sell_idx is missing or beyond max_hold, exit_type becomes 'timeout' and
    sell index is clamped to buy_idx + max_hold.

    Returns: (exit_type, final_sell_idx)
    """
    try:
        buy_i = int(buy_idx)
    except Exception:
        buy_i = 0
    try:
        max_hold_i = int(max_hold)
    except Exception:
        max_hold_i = 100
    max_hold_i = max(1, min(max_hold_i, 250))
    try:
        n = int(hist_len)
    except Exception:
        n = 0

    def clamp_timeout_idx():
        if n <= 0:
            return buy_i
        return min(buy_i + max_hold_i, n - 1)

    if sell_idx is None:
        return 'timeout', clamp_timeout_idx()

    try:
        sell_i = int(sell_idx)
    except Exception:
        return 'timeout', clamp_timeout_idx()

    if sell_i < buy_i:
        return 'timeout', clamp_timeout_idx()

    if sell_i - buy_i > max_hold_i:
        return 'timeout', clamp_timeout_idx()

    return 'signal', sell_i


def _get_table_trade_date_count(table_name: str, start_date: str, end_date: str):
    sql = f"SELECT COUNT(DISTINCT `date`) as cnt FROM `{table_name}` WHERE `date` >= %s AND `date` <= %s"
    df = pd.read_sql(sql, con=mdb.engine(), params=(start_date, end_date))
    try:
        return int(df.iloc[0]['cnt']) if df is not None and len(df) > 0 else 0
    except Exception:
        logging.debug(f"_get_table_trade_date_count 解析异常：{table_name}", exc_info=True)
        return 0


def _resolve_date_range(handler: webBase.BaseHandler, table_name: str, default_days: int):
    """Resolve date range from query args.

    Priority:
    1) start_date/end_date (either present triggers explicit range)
    2) days (recent N distinct trade dates)

    Returns: (date_range_dict, error_message)
    """
    start_arg = handler.get_argument('start_date', default='', strip=True)
    end_arg = handler.get_argument('end_date', default='', strip=True)

    has_start_arg = bool(str(start_arg or '').strip())
    has_end_arg = bool(str(end_arg or '').strip())

    start_s, start_dt = _parse_date_ymd(start_arg)
    end_s, end_dt = _parse_date_ymd(end_arg)

    # Strict: if user provided an arg but it's invalid, fail fast
    if has_start_arg and not start_dt:
        return None, 'start_date 格式不正确，支持 YYYY-MM-DD 或 YYYYMMDD'
    if has_end_arg and not end_dt:
        return None, 'end_date 格式不正确，支持 YYYY-MM-DD 或 YYYYMMDD'

    explicit = bool(has_start_arg or has_end_arg)
    if explicit:
        if start_s and not end_s:
            end_s, end_dt = start_s, start_dt
        if end_s and not start_s:
            start_s, start_dt = end_s, end_dt

        if not start_s or not end_s or not start_dt or not end_dt:
            return None, 'start_date/end_date 格式不正确，支持 YYYY-MM-DD 或 YYYYMMDD'

        if start_dt > end_dt:
            start_s, end_s = end_s, start_s
            start_dt, end_dt = end_dt, start_dt

        # 防止误传导致超大查询（按自然日粗略限制）
        if (end_dt - start_dt).days > 366:
            return None, '日期区间过大，请控制在 366 天以内'

        cnt = _get_table_trade_date_count(table_name, start_s, end_s)
        return {'start': start_s, 'end': end_s, 'count': cnt}, None

    # fallback: days
    days = handler.get_argument('days', default=str(default_days), strip=True)
    try:
        days_i = int(days)
    except Exception:
        days_i = int(default_days)
    days_i = max(1, min(days_i, 365))

    date_range = _get_recent_date_range(table_name, days_i)
    if not date_range:
        return None, None
    return date_range, None


def _get_strategy_map():
    """strategy_key -> {table, cn, type}

    支持多种 key 查找：
    1. 表名（主键）：如 'cn_stock_strategy_enter'
    2. 中文名（兼容旧数据）：如 '放量上涨'
    3. 别名：如 'indicators_buy'
    """
    mapping = {}
    for s in tbs.TABLE_CN_STOCK_STRATEGIES:
        entry = {'table': s['name'], 'cn': s['cn'], 'type': 'strategy'}
        mapping[s['name']] = entry
        # 中文名反向映射（兼容旧版 cn_stock_backtest 中 strategy_name 为中文的数据）
        if s['cn'] and s['cn'] != s['name']:
            mapping[s['cn']] = entry

    buy_entry = {'table': tbs.TABLE_CN_STOCK_INDICATORS_BUY['name'], 'cn': '指标买入信号', 'type': 'indicator'}
    mapping[tbs.TABLE_CN_STOCK_INDICATORS_BUY['name']] = buy_entry
    mapping['indicators_buy'] = buy_entry
    mapping['指标买入信号'] = buy_entry

    sell_entry = {'table': tbs.TABLE_CN_STOCK_INDICATORS_SELL['name'], 'cn': '指标卖出信号', 'type': 'indicator'}
    mapping[tbs.TABLE_CN_STOCK_INDICATORS_SELL['name']] = sell_entry
    mapping['indicators_sell'] = sell_entry
    mapping['指标卖出信号'] = sell_entry

    gpt_entry = {
        'table': tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE['name'],
        'cn': tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE['cn'],
        'type': 'strategy',
    }
    mapping[tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE['name']] = gpt_entry
    if tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE['cn'] != tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE['name']:
        mapping[tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE['cn']] = gpt_entry
    return mapping


def _resolve_strategy(strategy_key: str, strategy_map: dict = None):
    """查找策略，支持精确匹配 + strip 容错。

    Returns: (meta_dict, None) on success, (None, error_msg) on failure.
    """
    if not strategy_key or not strategy_key.strip():
        return None, '缺少 strategy 参数'
    key = strategy_key.strip()
    if strategy_map is None:
        strategy_map = _get_strategy_map()
    meta = strategy_map.get(key)
    if meta:
        return meta, None
    # 尝试去掉可能的前缀/后缀空格或不可见字符
    key_clean = key.strip('\t\n\r\x00\ufeff')
    if key_clean != key:
        meta = strategy_map.get(key_clean)
        if meta:
            return meta, None
    # 列出可用策略供诊断
    available = sorted(set(v['table'] for v in strategy_map.values()))
    return None, f"未知 strategy: '{key}'，可用策略: {', '.join(available)}"


def _get_recent_date_range(table_name: str, trade_days: int):
    trade_days = int(trade_days) if trade_days else 30
    trade_days = max(1, min(trade_days, 365))

    sql_dates = f"SELECT DISTINCT `date` FROM `{table_name}` ORDER BY `date` DESC LIMIT {trade_days}"
    df = pd.read_sql(sql_dates, con=mdb.engine())
    if df is None or len(df) == 0:
        return None

    dates = sorted(df['date'].astype(str).tolist())
    return {'start': dates[0], 'end': dates[-1], 'count': len(dates)}


class DashboardOverviewHandler(webBase.BaseHandler, ABC):
    """跨策略总览（基于 cn_stock_backtest）"""

    def get(self):
        self.set_header('Content-Type', 'application/json;charset=UTF-8')
        try:
            self._handle()
        except Exception:
            logging.error("回测看板Overview处理异常", exc_info=True)
            self.write(json.dumps({'error': '服务器内部错误'}, ensure_ascii=False))

    def _handle(self):
        days = self.get_argument('days', default='60', strip=True)
        metric = self.get_argument('metric', default='5', strip=True)  # best/worst 基于哪个 horizon

        try:
            days_i = int(days)
        except Exception:
            days_i = 60
        days_i = max(1, min(days_i, 365))

        metric_list = _parse_int_list(metric, default=[5], min_value=1, max_value=120, max_items=1)
        metric_h = metric_list[0] if metric_list else 5
        if metric_h not in SUMMARY_HORIZONS:
            metric_h = 5

        summary_table = tbs.TABLE_CN_STOCK_BACKTEST['name']
        if not mdb.checkTableIsExist(summary_table):
            self.write(json.dumps({'error': '回测汇总表不存在，请先运行 backtest_data_daily_job.py'}, ensure_ascii=False))
            return

        date_range, err = _resolve_date_range(self, summary_table, 60)
        if err:
            self.write(json.dumps({'error': err}, ensure_ascii=False))
            return
        if not date_range:
            self.write(json.dumps({'error': '回测汇总表无数据'}, ensure_ascii=False))
            return

        start_date = date_range['start']
        end_date = date_range['end']

        cols = ['date', 'strategy_name', 'stock_count', 'success_rate']
        for h in SUMMARY_HORIZONS:
            cols.append(f'avg_rate_{h}')

        sql = f"SELECT {', '.join([f'`{c}`' for c in cols])} FROM `{summary_table}` WHERE `date` >= %s AND `date` <= %s"
        df = pd.read_sql(sql, con=mdb.engine(), params=(start_date, end_date))
        if df is None or len(df) == 0:
            self.write(json.dumps({'error': '指定区间无回测汇总数据'}, ensure_ascii=False))
            return

        strategy_map = _get_strategy_map()

        items = []
        for strategy_name, g in df.groupby('strategy_name'):
            total_signals = int(g['stock_count'].fillna(0).sum())
            # success_rate: 排除 NULL (未回测) 行，只取有数据的行做平均
            sr_valid = g['success_rate'].dropna()
            avg_success = round(float(sr_valid.mean()), 2) if len(sr_valid) > 0 else None

            avg_rates = {}
            for h in SUMMARY_HORIZONS:
                c = f'avg_rate_{h}'
                if c in g.columns:
                    vals = g[c].dropna()
                    avg_rates[f'{h}d'] = round(float(vals.mean()), 2) if len(vals) > 0 else None
                else:
                    avg_rates[f'{h}d'] = None

            metric_col = f'avg_rate_{metric_h}'
            best_day = None
            worst_day = None
            if metric_col in g.columns and not g[metric_col].isna().all():
                best_idx = g[metric_col].astype(float).idxmax()
                worst_idx = g[metric_col].astype(float).idxmin()
                best_day = str(df.loc[best_idx, 'date'])
                worst_day = str(df.loc[worst_idx, 'date'])

            meta = strategy_map.get(strategy_name)
            if not meta:
                # 尝试 strip 容错
                meta = strategy_map.get(str(strategy_name).strip())
            if not meta:
                logging.warning(f"回测看板Overview: 跳过未知 strategy_name='{strategy_name}'")
                continue
            items.append({
                'strategy_name': strategy_name,
                'strategy_cn': meta.get('cn', strategy_name),
                'type': meta.get('type', 'unknown'),
                'total_signals': total_signals,
                'avg_success_rate': avg_success,
                'avg_returns': avg_rates,
                'best_day': best_day,
                'worst_day': worst_day,
            })

        # 默认按 metric_h 的 avg 收益降序
        metric_key = f'{metric_h}d'
        items.sort(key=lambda x: float(x.get('avg_returns', {}).get(metric_key, 0) or 0), reverse=True)

        self.write(json.dumps({
            'date_range': date_range,
            'horizons': SUMMARY_HORIZONS,
            'metric_horizon': metric_h,
            'items': items,
        }, ensure_ascii=False, default=_json_default))


class PerformanceTimelineHandler(webBase.BaseHandler, ABC):
    """策略表现时间序列（按信号日汇总的 avg_rate_N）"""

    def get(self):
        self.set_header('Content-Type', 'application/json;charset=UTF-8')
        try:
            self._handle()
        except Exception:
            logging.error("回测看板Timeline处理异常", exc_info=True)
            self.write(json.dumps({'error': '服务器内部错误'}, ensure_ascii=False))

    def _handle(self):
        strategies_csv = self.get_argument('strategies', default='', strip=True)
        days = self.get_argument('days', default='90', strip=True)
        horizon = self.get_argument('horizon', default='5', strip=True)

        try:
            days_i = int(days)
        except Exception:
            days_i = 90
        days_i = max(1, min(days_i, 365))

        horizon_list = _parse_int_list(horizon, default=[5], min_value=1, max_value=120, max_items=1)
        h = horizon_list[0] if horizon_list else 5
        if h not in SUMMARY_HORIZONS:
            self.write(json.dumps({'error': f'horizon 仅支持 {SUMMARY_HORIZONS}'}, ensure_ascii=False))
            return

        summary_table = tbs.TABLE_CN_STOCK_BACKTEST['name']
        if not mdb.checkTableIsExist(summary_table):
            self.write(json.dumps({'error': '回测汇总表不存在'}, ensure_ascii=False))
            return

        date_range, err = _resolve_date_range(self, summary_table, 90)
        if err:
            self.write(json.dumps({'error': err}, ensure_ascii=False))
            return
        if not date_range:
            self.write(json.dumps({'error': '回测汇总表无数据'}, ensure_ascii=False))
            return

        start_date = date_range['start']
        end_date = date_range['end']

        selected = [s.strip() for s in strategies_csv.split(',') if s.strip()]
        if not selected:
            selected = []

        params = [start_date, end_date]
        strategy_filter = ''
        if selected:
            placeholders = ','.join(['%s'] * len(selected))
            strategy_filter = f" AND `strategy_name` IN ({placeholders})"
            params.extend(selected)

        sql = f"""SELECT `date`, `strategy_name`, `avg_rate_{h}` as v
                  FROM `{summary_table}`
                  WHERE `date` >= %s AND `date` <= %s {strategy_filter}
                  ORDER BY `date` ASC"""
        df = pd.read_sql(sql, con=mdb.engine(), params=tuple(params))
        if df is None or len(df) == 0:
            self.write(json.dumps({'error': '指定区间无数据'}, ensure_ascii=False))
            return

        strategy_map = _get_strategy_map()
        series = []
        for strategy_name, g in df.groupby('strategy_name'):
            meta = strategy_map.get(strategy_name, {'cn': strategy_name})
            data = []
            for _, r in g.iterrows():
                data.append({'date': str(r['date']), 'value': None if pd.isna(r['v']) else round(float(r['v']), 2)})
            series.append({'strategy_name': strategy_name, 'strategy_cn': meta.get('cn', strategy_name), 'data': data})

        self.write(json.dumps({
            'date_range': date_range,
            'horizon': h,
            'series': series,
        }, ensure_ascii=False, default=_json_default))


class StrategyDetailHandler(webBase.BaseHandler, ABC):
    """单策略选股明细（支持自定义 horizons<=100）"""

    def get(self):
        self.set_header('Content-Type', 'application/json;charset=UTF-8')
        try:
            self._handle()
        except Exception:
            logging.error("回测看板StrategyDetail处理异常", exc_info=True)
            self.write(json.dumps({'error': '服务器内部错误'}, ensure_ascii=False))

    def _handle(self):
        strategy = self.get_argument('strategy', default='', strip=True)
        days = self.get_argument('days', default='30', strip=True)
        horizons_csv = self.get_argument('horizons', default='', strip=True)
        page = self.get_argument('page', default='1', strip=True)
        page_size = self.get_argument('page_size', default='50', strip=True)

        meta, err = _resolve_strategy(strategy)
        if err:
            self.write(json.dumps({'error': err}, ensure_ascii=False))
            return

        table_name = meta['table']
        if not mdb.checkTableIsExist(table_name):
            self.write(json.dumps({'error': f'策略表不存在: {table_name}'}, ensure_ascii=False))
            return

        horizons = _parse_int_list(horizons_csv, default=[1, 3, 5, 10, 20], min_value=1, max_value=MAX_TABLE_HORIZON, max_items=12)
        if not horizons:
            horizons = [1, 3, 5, 10, 20]

        try:
            days_i = int(days)
        except Exception:
            days_i = 30
        days_i = max(1, min(days_i, 365))

        try:
            page_i = int(page)
            page_size_i = int(page_size)
        except Exception:
            page_i, page_size_i = 1, 50
        page_i = max(1, page_i)
        page_size_i = max(10, min(page_size_i, 200))
        offset = (page_i - 1) * page_size_i

        date_range, err = _resolve_date_range(self, table_name, 30)
        if err:
            self.write(json.dumps({'error': err}, ensure_ascii=False))
            return
        if not date_range:
            self.write(json.dumps({'error': '该策略表无数据'}, ensure_ascii=False))
            return

        start_date = date_range['start']
        end_date = date_range['end']

        rate_cols = [f"`rate_{h}` as `rate_{h}`" for h in horizons]
        sql_cnt = f"SELECT COUNT(*) as cnt FROM `{table_name}` WHERE `date` >= %s AND `date` <= %s"
        cnt_df = pd.read_sql(sql_cnt, con=mdb.engine(), params=(start_date, end_date))
        total = int(cnt_df.iloc[0]['cnt']) if cnt_df is not None and len(cnt_df) > 0 else 0

        sql = f"""SELECT `date`, `code`, `name`, {', '.join(rate_cols)}
                  FROM `{table_name}`
                  WHERE `date` >= %s AND `date` <= %s
                  ORDER BY `date` DESC
                  LIMIT {offset}, {page_size_i}"""
        df = pd.read_sql(sql, con=mdb.engine(), params=(start_date, end_date))
        rows = []
        if df is not None and len(df) > 0:
            for _, r in df.iterrows():
                item = {'date': str(r['date']), 'code': str(r['code']), 'name': r.get('name')}
                for h in horizons:
                    v = r.get(f'rate_{h}')
                    item[f'rate_{h}'] = None if pd.isna(v) else round(float(v), 2)
                rows.append(item)

        self.write(json.dumps({
            'strategy_name': strategy,
            'strategy_cn': meta.get('cn', strategy),
            'date_range': date_range,
            'horizons': horizons,
            'page': page_i,
            'page_size': page_size_i,
            'total': total,
            'rows': rows,
        }, ensure_ascii=False, default=_json_default))


class ReturnDistributionHandler(webBase.BaseHandler, ABC):
    """收益分布（直方图）"""

    def get(self):
        self.set_header('Content-Type', 'application/json;charset=UTF-8')
        try:
            self._handle()
        except Exception:
            logging.error("回测看板ReturnDistribution处理异常", exc_info=True)
            self.write(json.dumps({'error': '服务器内部错误'}, ensure_ascii=False))

    def _handle(self):
        strategy = self.get_argument('strategy', default='', strip=True)
        days = self.get_argument('days', default='60', strip=True)
        horizon = self.get_argument('horizon', default='5', strip=True)

        meta, err = _resolve_strategy(strategy)
        if err:
            self.write(json.dumps({'error': err}, ensure_ascii=False))
            return

        table_name = meta['table']
        if not mdb.checkTableIsExist(table_name):
            self.write(json.dumps({'error': f'策略表不存在: {table_name}'}, ensure_ascii=False))
            return

        try:
            days_i = int(days)
        except Exception:
            days_i = 60
        days_i = max(1, min(days_i, 365))

        h_list = _parse_int_list(horizon, default=[5], min_value=1, max_value=MAX_TABLE_HORIZON, max_items=1)
        h = h_list[0] if h_list else 5

        date_range, err = _resolve_date_range(self, table_name, 60)
        if err:
            self.write(json.dumps({'error': err}, ensure_ascii=False))
            return
        if not date_range:
            self.write(json.dumps({'error': '该策略表无数据'}, ensure_ascii=False))
            return

        start_date = date_range['start']
        end_date = date_range['end']

        sql = f"SELECT `rate_{h}` as v FROM `{table_name}` WHERE `date` >= %s AND `date` <= %s AND `rate_{h}` IS NOT NULL"
        df = pd.read_sql(sql, con=mdb.engine(), params=(start_date, end_date))
        if df is None or len(df) == 0:
            # 无收益数据属于正常情况（信号太新，尚无 rate 数据），返回空分布而非 error
            bins_empty = [{'range': lab, 'count': 0, 'percentage': 0} for lab in ['<-10%', '-10%~-5%', '-5%~0%', '0%~5%', '5%~10%', '>10%']]
            self.write(json.dumps({
                'strategy_name': strategy,
                'strategy_cn': meta.get('cn', strategy),
                'date_range': date_range,
                'horizon': h,
                'bins': bins_empty,
                'total': 0,
            }, ensure_ascii=False, default=_json_default))
            return

        values = df['v'].astype(float)

        bins = [(-999, -10), (-10, -5), (-5, 0), (0, 5), (5, 10), (10, 999)]
        labels = ['<-10%', '-10%~-5%', '-5%~0%', '0%~5%', '5%~10%', '>10%']

        counts = []
        total = len(values)
        for (lo, hi), lab in zip(bins, labels):
            if lab == '<-10%':
                c = int((values < -10).sum())
            elif lab == '>10%':
                c = int((values > 10).sum())
            else:
                c = int(((values >= lo) & (values < hi)).sum())
            counts.append({'range': lab, 'count': c, 'percentage': round(100.0 * c / total, 2) if total else 0})

        self.write(json.dumps({
            'strategy_name': strategy,
            'strategy_cn': meta.get('cn', strategy),
            'date_range': date_range,
            'horizon': h,
            'bins': counts,
            'total': total,
        }, ensure_ascii=False, default=_json_default))


class TradePairHandler(webBase.BaseHandler, ABC):
    """买入-卖出配对明细

    v1：买入来自某策略/指标买入表，卖出来自 indicators_sell 表（取 buy_date 之后最早的一次）。
    """

    def get(self):
        self.set_header('Content-Type', 'application/json;charset=UTF-8')
        try:
            self._handle()
        except Exception:
            logging.error("回测看板TradePair处理异常", exc_info=True)
            self.write(json.dumps({'error': '服务器内部错误'}, ensure_ascii=False))

    def _handle(self):
        strategy = self.get_argument('strategy', default='', strip=True)
        days = self.get_argument('days', default='60', strip=True)
        page = self.get_argument('page', default='1', strip=True)
        page_size = self.get_argument('page_size', default='50', strip=True)
        max_hold = self.get_argument('max_hold', default='100', strip=True)

        meta, err = _resolve_strategy(strategy)
        if err:
            self.write(json.dumps({'error': err}, ensure_ascii=False))
            return

        buy_table = meta['table']
        sell_table = tbs.TABLE_CN_STOCK_INDICATORS_SELL['name']

        if not mdb.checkTableIsExist(buy_table):
            self.write(json.dumps({'error': f'买入表不存在: {buy_table}'}, ensure_ascii=False))
            return
        if not mdb.checkTableIsExist(sell_table):
            self.write(json.dumps({'error': f'卖出表不存在: {sell_table}'}, ensure_ascii=False))
            return

        try:
            days_i = int(days)
        except Exception:
            days_i = 60
        days_i = max(1, min(days_i, 365))

        try:
            page_i = int(page)
            page_size_i = int(page_size)
        except Exception:
            page_i, page_size_i = 1, 50
        page_i = max(1, page_i)
        page_size_i = max(10, min(page_size_i, 100))
        offset = (page_i - 1) * page_size_i

        try:
            max_hold_i = int(max_hold)
        except Exception:
            max_hold_i = 100
        max_hold_i = max(1, min(max_hold_i, 250))

        date_range, err = _resolve_date_range(self, buy_table, 60)
        if err:
            self.write(json.dumps({'error': err}, ensure_ascii=False))
            return
        if not date_range:
            self.write(json.dumps({'error': '该策略表无数据'}, ensure_ascii=False))
            return

        start_date = date_range['start']
        end_date = date_range['end']

        sql_cnt = f"SELECT COUNT(*) as cnt FROM `{buy_table}` WHERE `date` >= %s AND `date` <= %s"
        cnt_df = pd.read_sql(sql_cnt, con=mdb.engine(), params=(start_date, end_date))
        total = int(cnt_df.iloc[0]['cnt']) if cnt_df is not None and len(cnt_df) > 0 else 0

        sql_buy = f"""SELECT `date`, `code`, `name`
                      FROM `{buy_table}`
                      WHERE `date` >= %s AND `date` <= %s
                      ORDER BY `date` DESC
                      LIMIT {offset}, {page_size_i}"""
        buy_df = pd.read_sql(sql_buy, con=mdb.engine(), params=(start_date, end_date))
        if buy_df is None or len(buy_df) == 0:
            self.write(json.dumps({'strategy_name': strategy, 'total': total, 'rows': []}, ensure_ascii=False))
            return

        buy_rows = []
        codes = sorted(set(buy_df['code'].astype(str).tolist()))
        min_buy_date = str(buy_df['date'].astype(str).min())
        min_buy_date_dash = _to_dash_ymd_loose(min_buy_date) or min_buy_date

        # 批量拉取卖出信号
        placeholders = ','.join(['%s'] * len(codes))
        sql_sell = f"SELECT `code`, `date` FROM `{sell_table}` WHERE `code` IN ({placeholders}) AND `date` > %s ORDER BY `code`, `date` ASC"
        sell_params = list(codes) + [min_buy_date_dash]
        sell_df = pd.read_sql(sql_sell, con=mdb.engine(), params=tuple(sell_params))

        sell_map = {}
        if sell_df is not None and len(sell_df) > 0:
            for _, r in sell_df.iterrows():
                c = str(r['code'])
                d = str(r['date'])
                sell_map.setdefault(c, []).append(d)

        # 缓存范围
        now = datetime.datetime.now()
        years = stf.HIST_DATA_DEFAULT_YEARS
        cache_start, _ = trd.get_trade_hist_interval(now, years)
        cache_end = now.strftime("%Y%m%d")

        # 逐条计算（按页）
        for _, r in buy_df.iterrows():
            buy_date_raw = r['date']
            buy_date = _to_dash_ymd_loose(buy_date_raw) or str(buy_date_raw)
            buy_key = _to_yyyymmdd_loose(buy_date_raw) or _to_yyyymmdd_loose(buy_date)
            code = str(r['code'])
            name = r.get('name')

            sell_date = _pick_first_sell_after(buy_key, sell_map.get(code, []))
            sell_key = _to_yyyymmdd_loose(sell_date) if sell_date else ''

            hist = stf.read_stock_hist_from_cache(code, cache_start, cache_end)
            if hist is None or len(hist) == 0:
                continue

            hist = hist.copy()
            hist['date_key'] = hist['date'].apply(_to_yyyymmdd_loose)
            idxs = hist.index[hist['date_key'] == buy_key].tolist() if buy_key else []
            if not idxs:
                continue
            buy_idx = int(idxs[0])

            # 修正: 使用T+1开盘价作为买入价（信号在T日收盘后产生）
            if buy_idx + 1 < len(hist) and 'open' in hist.columns:
                exec_idx = buy_idx + 1
                buy_price = float(hist.loc[hist.index[exec_idx], 'open'])
                # 涨停检测
                t_close = float(hist.loc[buy_idx, 'close'])
                if buy_price > 0 and t_close > 0 and (buy_price - t_close) / t_close >= 0.095:
                    continue  # T+1开盘涨停，无法买入
                buy_date = _to_dash_ymd_loose(hist.loc[hist.index[exec_idx], 'date'])
                buy_idx = exec_idx  # 更新buy_idx为实际执行日
            else:
                buy_price = float(hist.loc[buy_idx, 'close'])

            if sell_date:
                sell_idxs = hist.index[hist['date_key'] == sell_key].tolist() if sell_key else []
                sell_idx_raw = int(sell_idxs[0]) if sell_idxs else None
            else:
                sell_idx_raw = None

            exit_type, sell_idx = _apply_max_hold_exit_rule(buy_idx, sell_idx_raw, max_hold_i, len(hist))
            if exit_type == 'timeout':
                sell_date = _to_dash_ymd_loose(hist.loc[sell_idx, 'date'])
            else:
                sell_date = _to_dash_ymd_loose(sell_date)

            sell_price = float(hist.loc[sell_idx, 'close'])
            hold_days = max(0, sell_idx - buy_idx)
            raw_return = round(100.0 * (sell_price - buy_price) / buy_price, 2) if buy_price else 0
            return_rate = round(raw_return - ROUND_TRIP_COST_PCT, 2)

            buy_rows.append({
                'buy_date': buy_date,
                'sell_date': sell_date,
                'code': code,
                'name': name,
                'hold_days': hold_days,
                'buy_price': round(buy_price, 2),
                'sell_price': round(sell_price, 2),
                'return_rate': return_rate,
                'exit_type': exit_type,
            })

        self.write(json.dumps({
            'strategy_name': strategy,
            'strategy_cn': meta.get('cn', strategy),
            'date_range': date_range,
            'page': page_i,
            'page_size': page_size_i,
            'total': total,
            'max_hold': max_hold_i,
            'rows': buy_rows,
        }, ensure_ascii=False, default=_json_default))

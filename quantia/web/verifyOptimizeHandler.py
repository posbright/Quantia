#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""选股验证中心 — 优化分析 API Handler

提供持仓天数扫描、信号质量诊断、止盈止损矩阵、市场环境分类、
信号衰减分析、交易成本敏感性等只读分析接口。

数据来源: MySQL + cache/hist/（遵守 Fetch/Analysis/Web 分离原则）
"""

import datetime
import hashlib
import json
import logging
import math
import uuid
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
import quantia.web.base as webBase
from quantia.core.backtest.data_feed import load_benchmark_data
from quantia.core.backtest.rate_stats import ROUND_TRIP_COST_PCT
from quantia.web.utils import parse_int_list as _parse_int_list, json_default as _json_default

__author__ = 'Quantia'
__date__ = '2026/05/15'

# ── 常量 ──────────────────────────────────────────────────────────────

RATE_FIELDS_COUNT = tbs.RATE_FIELDS_COUNT  # 100
_BACKTEST_DATA_TABLE = tbs.TABLE_CN_STOCK_BACKTEST_DATA['name']
_BACKTEST_SUMMARY_TABLE = tbs.TABLE_CN_STOCK_BACKTEST['name']
_CUSTOM_COMPARE_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix='verify-custom')
_CUSTOM_COMPARE_TASKS = {}
_CUSTOM_COMPARE_TASK_KEYS = {}

# 策略白名单（表名 → 中文名映射）
_STRATEGY_MAP = None


def _get_strategy_map():
    """strategy_key -> {table, cn}，复用 backtestDashboardHandler 逻辑。"""
    global _STRATEGY_MAP
    if _STRATEGY_MAP is not None:
        return _STRATEGY_MAP
    mapping = {}
    for s in tbs.TABLE_CN_STOCK_STRATEGIES:
        entry = {'table': s['name'], 'cn': s['cn']}
        mapping[s['name']] = entry
        if s['cn'] and s['cn'] != s['name']:
            mapping[s['cn']] = entry
        # 短名映射: cn_stock_strategy_keep_increasing → keep_increasing
        short = s['name'].replace('cn_stock_strategy_', '')
        if short != s['name']:
            mapping[short] = entry
    # GPT 策略
    gpt = tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE
    gpt_entry = {'table': gpt['name'], 'cn': gpt['cn']}
    mapping[gpt['name']] = gpt_entry
    if gpt['cn'] != gpt['name']:
        mapping[gpt['cn']] = gpt_entry
    gpt_short = gpt['name'].replace('cn_stock_strategy_', '')
    if gpt_short != gpt['name']:
        mapping[gpt_short] = gpt_entry
    _STRATEGY_MAP = mapping
    return mapping


class VerifyStrategyListHandler(webBase.BaseHandler):
    """GET /quantia/api/verify/strategy_list

    返回所有可用于验证分析的策略列表（内置信号策略 + 有回测结果的用户自定义策略）。
    内置策略走 rate_* 信号表分析; 自定义策略走 cn_stock_backtest_portfolio 回测结果。
    """

    def get(self):
        try:
            groups = []
            # 1) 内置策略 — 按类型分组
            tech_items = []
            pattern_items = []
            value_items = []
            for s in tbs.TABLE_CN_STOCK_STRATEGIES:
                short_key = s['name'].replace('cn_stock_strategy_', '')
                item = {'value': short_key, 'label': s['cn'], 'table': s['name'], 'type': 'signal'}
                # 按策略功能分组
                if short_key in ('enter', 'keep_increasing', 'parking_apron', 'backtrace_ma250',
                                 'breakthrough_platform', 'low_atr'):
                    tech_items.append(item)
                elif short_key in ('climax_limitdown', 'high_tight_flag', 'low_backtrace_increase'):
                    pattern_items.append(item)
                else:
                    value_items.append(item)
            groups.append({'label': '技术指标', 'category': 'tech', 'items': tech_items})
            groups.append({'label': '量价形态', 'category': 'pat', 'items': pattern_items})
            groups.append({'label': '趋势突破', 'category': 'vol', 'items': value_items})

            # GPT 策略
            gpt = tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE
            gpt_short = gpt['name'].replace('cn_stock_strategy_', '')
            groups.append({
                'label': '基本面',
                'category': 'fund',
                'items': [{'value': gpt_short, 'label': gpt['cn'], 'table': gpt['name'], 'type': 'signal'}],
            })

            # 2) 用户自定义策略（仅显示有已完成回测结果的）
            custom_items = []
            try:
                rows = mdb.executeSqlFetch(
                    "SELECT sc.id, sc.name, sc.description, COUNT(bp.id) AS bt_count "
                    "FROM cn_stock_strategy_code sc "
                    "LEFT JOIN cn_stock_backtest_portfolio bp "
                    "  ON bp.strategy_id = sc.id AND bp.status = 'completed' "
                    "WHERE sc.status != 'archived' "
                    "GROUP BY sc.id, sc.name, sc.description "
                    "HAVING bt_count > 0 "
                    "ORDER BY sc.updated_at DESC LIMIT 50"
                )
                if rows:
                    for r in rows:
                        custom_items.append({
                            'value': f'custom_{r[0]}',
                            'label': r[1],
                            'description': r[2] or '',
                            'custom_id': r[0],
                            'type': 'backtest',
                            'backtest_count': r[3],
                        })
            except Exception:
                logging.debug("读取自定义策略列表失败（表可能不存在）", exc_info=True)

            if custom_items:
                groups.append({'label': '用户自定义', 'category': 'custom', 'items': custom_items})

            _write_json(self, {'groups': groups})
        except Exception:
            logging.error("策略列表异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)


def _resolve_strategy(key: str):
    """查找策略元数据，返回 (meta, error_msg)。"""
    if not key or not key.strip():
        return None, '缺少 strategy 参数'
    key = key.strip()
    smap = _get_strategy_map()
    meta = smap.get(key)
    if meta:
        return meta, None
    available = sorted(set(v['table'] for v in smap.values()))
    return None, f"未知 strategy: '{key}'，可用: {', '.join(available)}"


def _parse_date(s):
    """解析 YYYY-MM-DD 或 YYYYMMDD 格式日期字符串。"""
    if not s:
        return None
    s = str(s).strip().replace('/', '-')
    for fmt in ('%Y-%m-%d', '%Y%m%d'):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _safe_float(v, digits=4):
    """安全转 float，NaN/Inf 返回 None。"""
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    try:
        return round(float(v), digits)
    except (TypeError, ValueError):
        return None


def _calc_annualized_sharpe(rates, holding_days, rf_annual=0.015):
    """计算年化夏普比率。

    rates: 1-D array of return percentages (e.g. 3.5 means 3.5%)
    holding_days: 持仓天数
    rf_annual: 年化无风险利率 (默认 1.5%)
    """
    rates = np.asarray(rates, dtype=float)
    rates = rates[np.isfinite(rates)]
    if len(rates) < 2:
        return None
    avg = rates.mean()
    std = rates.std(ddof=1)
    if std == 0:
        return 0.0
    rf_period = rf_annual * holding_days / 252 * 100  # 转为百分比单位
    annualization = math.sqrt(252 / holding_days)
    return round(float((avg - rf_period) / std * annualization), 4)


def _calc_sortino(rates, holding_days, rf_annual=0.015):
    """计算年化 Sortino 比率。"""
    rates = np.asarray(rates, dtype=float)
    rates = rates[np.isfinite(rates)]
    if len(rates) < 2:
        return None
    avg = rates.mean()
    rf_period = rf_annual * holding_days / 252 * 100
    downside = rates[rates < 0]
    if len(downside) < 1:
        return None
    downside_std = downside.std(ddof=1)
    if downside_std == 0:
        return 0.0
    annualization = math.sqrt(252 / holding_days)
    return round(float((avg - rf_period) / downside_std * annualization), 4)


def _load_backtest_data(strategy_table, start_date, end_date, rate_cols=None):
    """从策略表加载回测数据。

    Returns: DataFrame with date, code, name + rate columns, or None.
    """
    if not mdb.checkTableIsExist(strategy_table):
        return None
    if rate_cols is None:
        rate_cols = [f'rate_{i}' for i in range(1, RATE_FIELDS_COUNT + 1)]
    base_cols = ['date', 'code', 'name']
    all_cols = base_cols + rate_cols
    cols_sql = ', '.join(f'`{c}`' for c in all_cols)
    sql = f"SELECT {cols_sql} FROM `{strategy_table}` WHERE `date` >= %s AND `date` <= %s"
    try:
        df = pd.read_sql(sql, con=mdb.engine(), params=(str(start_date), str(end_date)))
    except Exception as e:
        logging.error(f"读取 {strategy_table} 失败: {e}", exc_info=True)
        return None
    return df if df is not None and len(df) > 0 else None


def _write_json(handler, data):
    """统一 JSON 响应写入。"""
    handler.set_header('Content-Type', 'application/json;charset=UTF-8')
    handler.write(json.dumps(data, ensure_ascii=False, default=_json_default))


def _write_error(handler, msg, code=400):
    """统一错误响应。"""
    handler.set_status(code)
    _write_json(handler, {'error': msg})


def _parse_common_args(handler):
    """解析通用参数 strategy / start_date / end_date。

    Returns: (strategy_meta, start_date, end_date, error_msg)
    """
    strategy_key = handler.get_argument('strategy', default='', strip=True)
    meta, err = _resolve_strategy(strategy_key)
    if err:
        return None, None, None, err

    start_s = handler.get_argument('start_date', default='', strip=True)
    end_s = handler.get_argument('end_date', default='', strip=True)

    start_date = _parse_date(start_s)
    end_date = _parse_date(end_s)

    if not start_date or not end_date:
        return None, None, None, 'start_date 和 end_date 必填，格式 YYYY-MM-DD'

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    if (end_date - start_date).days > 366:
        return None, None, None, '日期区间过大，请控制在 366 天以内'

    if (end_date - start_date).days < 7:
        return None, None, None, '日期区间过短，请至少选择 7 天以上的范围以获得有意义的统计结果'

    return meta, start_date, end_date, None


def _parse_custom_strategy_args(handler):
    """解析自定义策略对比参数。"""
    strategy_key = handler.get_argument('strategy', default='', strip=True)
    if not strategy_key.startswith('custom_'):
        return None, None, None, None, '此接口仅支持自定义策略 (custom_*)'

    try:
        strategy_id = int(strategy_key.replace('custom_', ''))
    except ValueError:
        return None, None, None, None, '无效的策略ID'

    start_s = handler.get_argument('start_date', default='', strip=True)
    end_s = handler.get_argument('end_date', default='', strip=True)
    start_date = _parse_date(start_s)
    end_date = _parse_date(end_s)

    if not start_date or not end_date:
        return None, None, None, None, 'start_date 和 end_date 必填，格式 YYYY-MM-DD'
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    if (end_date - start_date).days > 366:
        return None, None, None, None, '日期区间过大，请控制在 366 天以内'
    if (end_date - start_date).days < 7:
        return None, None, None, None, '日期区间过短，请至少选择 7 天以上的范围以获得有意义的统计结果'

    return strategy_key, strategy_id, start_date, end_date, None


def _benchmark_return_series(benchmark, start_date, end_date):
    """返回基准指数累计净值序列，起点归一化为 100。"""
    try:
        df = load_benchmark_data(benchmark or '000300', start_date, end_date)
    except Exception:
        logging.warning("加载基准收益序列失败: %s %s~%s", benchmark, start_date, end_date, exc_info=True)
        return []
    if df is None or len(df) == 0 or 'close' not in df.columns:
        return []

    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date')
    base = None
    series = []
    for _, row in df.iterrows():
        close = row.get('close')
        if close is None:
            continue
        close_val = float(close)
        if not np.isfinite(close_val) or close_val <= 0:
            continue
        if base is None:
            base = close_val
        cumulative = close_val / base * 100 if base else 100
        series.append({
            'date': row['date'].strftime('%Y-%m-%d'),
            'cumulative': _safe_float(cumulative),
        })
    return series


def _series_from_nav(nav_data, include_benchmark=False):
    """将回测 NAV 数据转换为前端收益曲线序列。"""
    series = []
    benchmark_series = []
    base_nav = None
    base_benchmark = None
    for item in nav_data or []:
        date_text = item.get('date', '')
        try:
            nav_val = float(item.get('nav', 1.0))
        except (TypeError, ValueError):
            continue
        if not np.isfinite(nav_val) or nav_val <= 0:
            continue
        if base_nav is None:
            base_nav = nav_val
        series.append({
            'date': date_text,
            'cumulative': _safe_float(nav_val / base_nav * 100 if base_nav else 100),
        })

        if include_benchmark:
            try:
                bm_nav = float(item.get('benchmark_nav', 1.0))
            except (TypeError, ValueError):
                continue
            if np.isfinite(bm_nav) and bm_nav > 0:
                if base_benchmark is None:
                    base_benchmark = bm_nav
                benchmark_series.append({
                    'date': date_text,
                    'cumulative': _safe_float(bm_nav / base_benchmark * 100 if base_benchmark else 100),
                })
    return series, benchmark_series


def _calc_rolling_nav_analysis(nav_data, holding_days_list, trade_count=0):
    """基于组合 NAV 计算不同持有窗口的滚动收益统计。"""
    values = []
    for item in nav_data or []:
        try:
            nav_val = float(item.get('nav', 0))
        except (TypeError, ValueError):
            continue
        if np.isfinite(nav_val) and nav_val > 0:
            values.append(nav_val)

    if len(values) < 2:
        return [], None, None

    nav = np.asarray(values, dtype=float)
    trading_days = len(nav)
    daily_signal_count = round(float(trade_count or 0) / trading_days, 1) if trading_days else 0.0
    analysis = []
    best_sharpe = None
    best_holding_days = None

    for d in holding_days_list:
        if d <= 0 or len(nav) <= d:
            continue
        base = nav[:-d]
        future = nav[d:]
        rates = (future / base - 1) * 100
        rates = rates[np.isfinite(rates)]
        if len(rates) == 0:
            continue

        avg_ret = float(rates.mean())
        std_ret = float(rates.std(ddof=1)) if len(rates) > 1 else 0.0
        sharpe = _calc_annualized_sharpe(rates, d)
        sortino = _calc_sortino(rates, d)
        win_rate = float((rates > 0).mean() * 100)
        gains = rates[rates > 0]
        losses = rates[rates < 0]
        if len(gains) > 0 and len(losses) > 0:
            profit_loss_ratio = float(gains.mean() / abs(losses.mean()))
        elif len(gains) > 0:
            profit_loss_ratio = float('inf')
        else:
            profit_loss_ratio = 0.0

        max_loss = float(rates.min())
        annualized_ret = avg_ret * (252 / d) if d > 0 else 0.0
        if max_loss < 0:
            calmar_ratio = annualized_ret / abs(max_loss)
        else:
            calmar_ratio = float('inf') if annualized_ret > 0 else 0.0

        analysis.append({
            'holding_days': d,
            'avg_return': _safe_float(avg_ret),
            'median_return': _safe_float(float(np.median(rates))),
            'win_rate': _safe_float(win_rate),
            'return_std': _safe_float(std_ret),
            'sharpe_approx': _safe_float(sharpe),
            'sortino_approx': _safe_float(sortino),
            'max_single_loss': _safe_float(max_loss),
            'max_single_gain': _safe_float(float(rates.max())),
            'percentile_10': _safe_float(float(np.percentile(rates, 10))),
            'percentile_25': _safe_float(float(np.percentile(rates, 25))),
            'percentile_75': _safe_float(float(np.percentile(rates, 75))),
            'percentile_90': _safe_float(float(np.percentile(rates, 90))),
            'signal_count': len(rates),
            'profit_loss_ratio': _safe_float(round(profit_loss_ratio, 2)),
            'calmar_ratio': _safe_float(round(calmar_ratio, 2)),
            'daily_signal_count': _safe_float(daily_signal_count),
        })

        if sharpe is not None and (best_sharpe is None or sharpe > best_sharpe):
            best_sharpe = sharpe
            best_holding_days = d

    return analysis, best_holding_days, best_sharpe


def _load_cached_custom_backtest(strategy_id, start_date, end_date, benchmark):
    """优先复用完整覆盖所选区间的已完成自定义回测。"""
    try:
        rows = mdb.executeSqlFetch(
            "SELECT id, result_json, benchmark FROM cn_stock_backtest_portfolio "
            "WHERE strategy_id = %s AND status = 'completed' "
            "AND start_date <= %s AND end_date >= %s "
            "ORDER BY completed_at DESC LIMIT 5",
            (strategy_id, str(start_date), str(end_date)))
    except Exception:
        logging.debug("读取自定义策略覆盖区间回测缓存失败", exc_info=True)
        return None, None

    benchmark = str(benchmark or '000300')
    for bt_id, result_json_raw, cached_benchmark in rows or []:
        cached_benchmark = str(cached_benchmark or '000300')
        if cached_benchmark and cached_benchmark != benchmark:
            continue
        if not result_json_raw:
            continue
        try:
            result = json.loads(result_json_raw) if isinstance(result_json_raw, str) else result_json_raw
        except Exception:
            logging.debug("解析自定义回测缓存失败: id=%s", bt_id, exc_info=True)
            continue
        if not isinstance(result, dict) or result.get('status') != 'completed':
            continue

        nav = []
        for item in result.get('nav', []) or []:
            date_text = item.get('date', '')
            if date_text < str(start_date) or date_text > str(end_date):
                continue
            nav.append(item)
        if len(nav) < 2:
            continue

        result = dict(result)
        result['nav'] = nav
        result['trades'] = [t for t in (result.get('trades', []) or [])
                            if str(start_date) <= str(t.get('date', '')) <= str(end_date)]
        result['positions'] = [p for p in (result.get('positions', []) or [])
                               if str(start_date) <= str(p.get('date', '')) <= str(end_date)]
        result['_cached_backtest_id'] = bt_id
        return result, f'backtest_portfolio_cache:{bt_id}'

    return None, None


def _build_custom_compare_payload(strategy_key, strategy_name, start_date, end_date, result, data_source):
    """把自定义策略回测结果转换为策略对比页统一响应。"""
    if result.get('status') != 'completed':
        return {
            'strategy': strategy_key,
            'strategy_cn': strategy_name,
            'period': f'{start_date} ~ {end_date}',
            'status': 'failed',
            'total_signals': 0,
            'analysis': [],
            'series': [],
            'benchmark_series': [],
            'message': result.get('message') or '自定义策略回测失败',
            'hints': result.get('hints') or [],
            'data_source': data_source,
        }

    metrics = result.get('metrics', {}) or {}
    nav_series = result.get('nav', []) or []
    trades = result.get('trades', []) or []
    trade_count = metrics.get('trade_count') or len(trades)
    analysis, best_holding_days, best_sharpe = _calc_rolling_nav_analysis(
        nav_series, [5, 10, 20], trade_count=trade_count)
    series, benchmark_series = _series_from_nav(nav_series, include_benchmark=True)

    return {
        'strategy': strategy_key,
        'strategy_cn': strategy_name,
        'period': f'{start_date} ~ {end_date}',
        'status': 'completed',
        'total_signals': trade_count or 0,
        'analysis': analysis,
        'best_holding_days': best_holding_days,
        'best_sharpe': _safe_float(best_sharpe),
        'series': series,
        'benchmark_series': benchmark_series,
        'metrics': metrics,
        'data_source': data_source,
    }


def _custom_compare_task_key(strategy_id, strategy_code, start_date, end_date, initial_cash,
                             benchmark, commission, tax, slippage):
    code_hash = hashlib.sha256((strategy_code or '').encode('utf-8')).hexdigest()
    return (
        int(strategy_id), code_hash, str(start_date), str(end_date),
        round(float(initial_cash or 0), 2), str(benchmark or '000300'),
        round(float(commission or 0), 8), round(float(tax or 0), 8),
        round(float(slippage or 0), 8),
    )


def _find_reusable_custom_compare_task(cache_key):
    task_id = _CUSTOM_COMPARE_TASK_KEYS.get(cache_key)
    if not task_id:
        return None
    task = _CUSTOM_COMPARE_TASKS.get(task_id)
    if not task:
        _CUSTOM_COMPARE_TASK_KEYS.pop(cache_key, None)
        return None
    if task.get('status') == 'failed':
        _CUSTOM_COMPARE_TASK_KEYS.pop(cache_key, None)
        return None
    return task_id


def _start_custom_compare_task(strategy_key, strategy_id, strategy_name, strategy_code,
                               start_date, end_date, initial_cash, benchmark,
                               commission, tax, slippage, cache_key=None):
    """启动自定义策略对比后台任务，避免单个 HTTP 请求等待长回测。"""
    task_id = str(uuid.uuid4())[:8]
    _CUSTOM_COMPARE_TASKS[task_id] = {
        'status': 'running',
        'strategy': strategy_key,
        'strategy_cn': strategy_name,
        'period': f'{start_date} ~ {end_date}',
        'cache_key': cache_key,
        'result': None,
        'message': '自定义策略回测计算中，请稍候...',
    }
    if cache_key is not None:
        _CUSTOM_COMPARE_TASK_KEYS[cache_key] = task_id

    def _run():
        try:
            from quantia.core.backtest.portfolio_engine import PortfolioBacktestEngine
            engine = PortfolioBacktestEngine()
            result = engine.run(
                strategy_code, str(start_date), str(end_date),
                initial_cash=initial_cash,
                benchmark=benchmark,
                commission=commission,
                tax=tax,
                slippage=slippage,
            )
            _persist_custom_compare_result(
                strategy_id, strategy_name, strategy_code,
                start_date, end_date, initial_cash, benchmark, result)
            payload = _build_custom_compare_payload(
                strategy_key, strategy_name, start_date, end_date,
                result, 'portfolio_engine_live')
            task = _CUSTOM_COMPARE_TASKS.get(task_id)
            if task is not None:
                task['status'] = payload.get('status') or 'completed'
                task['result'] = payload
                task['message'] = payload.get('message') or 'done'
        except Exception as e:
            logging.error("自定义策略对比后台任务异常: task_id=%s", task_id, exc_info=True)
            task = _CUSTOM_COMPARE_TASKS.get(task_id)
            if task is not None:
                task['status'] = 'failed'
                task['result'] = {
                    'strategy': strategy_key,
                    'strategy_cn': strategy_name,
                    'period': f'{start_date} ~ {end_date}',
                    'status': 'failed',
                    'total_signals': 0,
                    'analysis': [],
                    'series': [],
                    'benchmark_series': [],
                    'message': str(e),
                    'data_source': 'portfolio_engine_live',
                }
                task['message'] = str(e)
            if cache_key is not None:
                _CUSTOM_COMPARE_TASK_KEYS.pop(cache_key, None)
        finally:
            try:
                mdb.close_thread_connection()
            except Exception:
                pass

    _CUSTOM_COMPARE_EXECUTOR.submit(_run)
    return task_id


def _persist_custom_compare_result(strategy_id, strategy_name, strategy_code,
                                   start_date, end_date, initial_cash, benchmark, result):
    """将后台对比回测结果落库，供下次同区间对比复用。"""
    if result.get('status') != 'completed':
        return
    try:
        if not mdb.checkTableIsExist('cn_stock_backtest_portfolio'):
            return
        m = result.get('metrics', {}) or {}
        result_to_save = dict(result)
        result_to_save['strategy_code_snapshot'] = strategy_code
        now = datetime.datetime.now()
        mdb.executeSql(
            'INSERT INTO cn_stock_backtest_portfolio '
            '(strategy_id, strategy_name, start_date, end_date, initial_cash, benchmark, status, '
            'started_at, completed_at, total_return, annual_return, max_drawdown, '
            'sharpe_ratio, alpha, beta, win_rate, trade_count, result_json) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (strategy_id, strategy_name or None, str(start_date), str(end_date), initial_cash,
             benchmark or '000300', 'completed', now, now,
             m.get('total_return'), m.get('annual_return'), m.get('max_drawdown'),
             m.get('sharpe_ratio'), m.get('alpha'), m.get('beta'),
             m.get('daily_win_rate'), m.get('trade_count'),
             json.dumps(result_to_save, ensure_ascii=False, default=str)))
    except Exception:
        logging.warning("自定义策略对比结果落库失败（不影响本次响应）", exc_info=True)


def _custom_compare_task_payload(task_id):
    task = _CUSTOM_COMPARE_TASKS.get(task_id)
    if not task:
        return {'status': 'failed', 'task_id': task_id, 'message': '对比任务不存在或已过期'}
    if task.get('status') == 'running':
        return {
            'status': 'running',
            'task_id': task_id,
            'strategy': task.get('strategy'),
            'strategy_cn': task.get('strategy_cn'),
            'period': task.get('period'),
            'analysis': [],
            'series': [],
            'benchmark_series': [],
            'message': task.get('message'),
        }
    result = task.get('result') or {}
    result = dict(result)
    result['task_id'] = task_id
    return result


# ── API 1: 持仓天数扫描 ──────────────────────────────────────────────

class HoldingPeriodAnalysisHandler(webBase.BaseHandler):
    """GET /quantia/api/verify/holding_period

    对选定策略的每个持仓天数统计: 平均收益、胜率、夏普、Sortino、分位数等。
    """

    def get(self):
        try:
            self._handle()
        except Exception:
            logging.error("持仓天数扫描异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)

    def _handle(self):
        meta, start_date, end_date, err = _parse_common_args(self)
        if err:
            _write_error(self, err)
            return

        # 可选参数: 指定持仓天数列表
        days_arg = self.get_argument('holding_days', default='', strip=True)
        if days_arg:
            holding_days_list = _parse_int_list(days_arg, min_value=1, max_value=RATE_FIELDS_COUNT, max_items=30)
        else:
            holding_days_list = [1, 2, 3, 5, 7, 10, 15, 20, 30, 60]

        if not holding_days_list:
            _write_error(self, 'holding_days 参数无效')
            return

        rate_cols = [f'rate_{d}' for d in holding_days_list]
        df = _load_backtest_data(meta['table'], start_date, end_date, rate_cols)
        if df is None:
            _write_json(self, {
                'strategy': meta['table'],
                'strategy_cn': meta['cn'],
                'period': f'{start_date} ~ {end_date}',
                'total_signals': 0,
                'analysis': [],
                'message': '该时间范围内无策略信号',
            })
            return

        total_signals = len(df)
        analysis = []
        best_sharpe = None
        best_holding_days = None

        for d in holding_days_list:
            col = f'rate_{d}'
            if col not in df.columns:
                continue
            rates = df[col].dropna().values
            if len(rates) == 0:
                continue

            avg_ret = float(rates.mean())
            std_ret = float(rates.std(ddof=1)) if len(rates) > 1 else 0.0
            sharpe = _calc_annualized_sharpe(rates, d)
            sortino = _calc_sortino(rates, d)
            win_rate = float((rates > 0).mean() * 100)

            # 盈亏比 = avg_gain / abs(avg_loss)
            gains = rates[rates > 0]
            losses = rates[rates < 0]
            if len(gains) > 0 and len(losses) > 0:
                profit_loss_ratio = float(gains.mean() / abs(losses.mean()))
            elif len(gains) > 0:
                profit_loss_ratio = float('inf')
            else:
                profit_loss_ratio = 0.0

            # Calmar = 年化收益 / |最大回撤|  (近似: 用max_single_loss代替回撤)
            max_loss = float(rates.min())
            annualized_ret = avg_ret * (252 / d) if d > 0 else 0.0
            if max_loss < 0:
                calmar_ratio = annualized_ret / abs(max_loss)
            else:
                calmar_ratio = float('inf') if annualized_ret > 0 else 0.0

            # 日均信号数 = total_signals / trading_days
            trading_days = len(df['date'].unique()) if 'date' in df.columns else 1
            daily_signal_count = round(total_signals / max(trading_days, 1), 1)

            item = {
                'holding_days': d,
                'avg_return': _safe_float(avg_ret),
                'median_return': _safe_float(float(np.median(rates))),
                'win_rate': _safe_float(win_rate),
                'return_std': _safe_float(std_ret),
                'sharpe_approx': _safe_float(sharpe),
                'sortino_approx': _safe_float(sortino),
                'max_single_loss': _safe_float(float(rates.min())),
                'max_single_gain': _safe_float(float(rates.max())),
                'percentile_10': _safe_float(float(np.percentile(rates, 10))),
                'percentile_25': _safe_float(float(np.percentile(rates, 25))),
                'percentile_75': _safe_float(float(np.percentile(rates, 75))),
                'percentile_90': _safe_float(float(np.percentile(rates, 90))),
                'signal_count': len(rates),
                'profit_loss_ratio': _safe_float(round(profit_loss_ratio, 2)),
                'calmar_ratio': _safe_float(round(calmar_ratio, 2)),
                'daily_signal_count': _safe_float(daily_signal_count),
            }
            analysis.append(item)

            if sharpe is not None and (best_sharpe is None or sharpe > best_sharpe):
                best_sharpe = sharpe
                best_holding_days = d

        _write_json(self, {
            'strategy': meta['table'],
            'strategy_cn': meta['cn'],
            'period': f'{start_date} ~ {end_date}',
            'total_signals': total_signals,
            'analysis': analysis,
            'best_holding_days': best_holding_days,
            'best_sharpe': _safe_float(best_sharpe),
        })


class CustomStrategyCompareHandler(webBase.BaseHandler):
    """GET /quantia/api/verify/custom_compare

    按页面选择的时间区间运行自定义组合策略，
    再基于回测 NAV 计算 5/10/20 交易日滚动收益统计。
    命中覆盖区间缓存时同步返回；未命中时启动后台任务并通过 task_id 轮询。

    参数: strategy=custom_<id>&start_date=...&end_date=...&benchmark=...
    """

    async def get(self):
        try:
            await self._handle()
        except Exception:
            logging.error("自定义策略对比异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)

    async def _handle(self):
        task_id = self.get_argument('task_id', default='', strip=True)
        if task_id:
            _write_json(self, _custom_compare_task_payload(task_id))
            return

        strategy_key, strategy_id, start_date, end_date, err = _parse_custom_strategy_args(self)
        if err:
            _write_error(self, err)
            return

        rows = mdb.executeSqlFetch(
            "SELECT name, code, initial_cash, benchmark, commission_rate, stamp_tax_rate, slippage "
            "FROM cn_stock_strategy_code WHERE id = %s AND status != 'archived' LIMIT 1",
            (strategy_id,))
        if not rows:
            _write_json(self, {
                'strategy': strategy_key,
                'strategy_cn': f'策略#{strategy_id}',
                'total_signals': 0,
                'analysis': [],
                'series': [],
                'benchmark_series': [],
                'message': '自定义策略不存在或已归档',
            })
            return

        strategy_name, strategy_code = rows[0][0], rows[0][1]
        initial_cash = float(rows[0][2] or 1000000)
        benchmark = self.get_argument('benchmark', default=(rows[0][3] or '000300'), strip=True) or '000300'
        commission = float(rows[0][4] or 0.0003)
        tax = float(rows[0][5] or 0.001)
        slippage = float(rows[0][6] or 0.002)

        if not strategy_code:
            _write_json(self, {
                'strategy': strategy_key,
                'strategy_cn': strategy_name or f'策略#{strategy_id}',
                'period': f'{start_date} ~ {end_date}',
                'total_signals': 0,
                'analysis': [],
                'series': [],
                'benchmark_series': [],
                'message': '自定义策略代码为空',
            })
            return

        result, data_source = _load_cached_custom_backtest(strategy_id, start_date, end_date, benchmark)
        if result is None:
            cache_key = _custom_compare_task_key(
                strategy_id, strategy_code, start_date, end_date,
                initial_cash, benchmark, commission, tax, slippage)
            reusable_task_id = _find_reusable_custom_compare_task(cache_key)
            if reusable_task_id:
                payload = _custom_compare_task_payload(reusable_task_id)
                payload['cache_hit'] = True
                payload['message'] = payload.get('message') or '已复用同参数分析任务'
                _write_json(self, payload)
                return

            task_id = _start_custom_compare_task(
                strategy_key, strategy_id, strategy_name or f'策略#{strategy_id}', strategy_code,
                start_date, end_date, initial_cash, benchmark,
                commission, tax, slippage, cache_key=cache_key)
            _write_json(self, {
                'strategy': strategy_key,
                'strategy_cn': strategy_name or f'策略#{strategy_id}',
                'period': f'{start_date} ~ {end_date}',
                'status': 'running',
                'task_id': task_id,
                'cache_hit': False,
                'analysis': [],
                'series': [],
                'benchmark_series': [],
                'message': '未找到覆盖该区间的已完成回测，已启动后台对比任务',
            })
            return

        payload = _build_custom_compare_payload(
            strategy_key, strategy_name, start_date, end_date, result, data_source)
        _write_json(self, payload)


class CustomStrategyReturnSeriesHandler(webBase.BaseHandler):
    """GET /quantia/api/verify/custom_return_series

    从 cn_stock_backtest_portfolio.result_json 提取自定义策略的 NAV 序列，
    映射成与 SignalReturnSeriesHandler 兼容的对比格式。
    """

    def get(self):
        try:
            self._handle()
        except Exception:
            logging.error("自定义策略收益曲线异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)

    def _handle(self):
        strategy_key = self.get_argument('strategy', default='', strip=True)
        if not strategy_key.startswith('custom_'):
            _write_error(self, '此接口仅支持自定义策略 (custom_*)')
            return

        try:
            strategy_id = int(strategy_key.replace('custom_', ''))
        except ValueError:
            _write_error(self, '无效的策略ID')
            return

        name_rows = mdb.executeSqlFetch(
            "SELECT name FROM cn_stock_strategy_code WHERE id = %s", (strategy_id,))
        strategy_name = name_rows[0][0] if name_rows else f'策略#{strategy_id}'

        rows = mdb.executeSqlFetch(
            "SELECT result_json FROM cn_stock_backtest_portfolio "
            "WHERE strategy_id = %s AND status = 'completed' "
            "ORDER BY completed_at DESC LIMIT 1",
            (strategy_id,)
        )
        if not rows or not rows[0][0]:
            _write_json(self, {
                'strategy': strategy_key,
                'strategy_cn': strategy_name,
                'series': [],
            })
            return

        try:
            rj = json.loads(rows[0][0]) if isinstance(rows[0][0], str) else rows[0][0]
            nav_data = rj.get('nav', [])
        except Exception:
            nav_data = []

        # 可选日期过滤
        start_s = self.get_argument('start_date', default='', strip=True)
        end_s = self.get_argument('end_date', default='', strip=True)
        start_date = _parse_date(start_s)
        end_date = _parse_date(end_s)

        # NAV → cumulative return (以 100 为基准，与信号策略一致)
        # 如果有日期过滤，先筛选范围内的数据，再以第一个点为基准归一化
        filtered_nav = []
        for item in nav_data:
            d = item.get('date', '')
            if start_date and d < str(start_date):
                continue
            if end_date and d > str(end_date):
                continue
            filtered_nav.append(item)

        series, benchmark_series = _series_from_nav(filtered_nav, include_benchmark=True)

        _write_json(self, {
            'strategy': strategy_key,
            'strategy_cn': strategy_name,
            'series': series,
            'benchmark_series': benchmark_series,
        })


# ── API 2: 信号质量诊断 ──────────────────────────────────────────────

# 可用于诊断的指标白名单
_SIGNAL_QUALITY_INDICATORS = {
    'rsi_6', 'rsi_12', 'kdjk', 'kdjd', 'kdjj',
    'macd', 'macds', 'macdh',
    'cr', 'cci', 'atr',
    'close', 'volume', 'turnover',
}

class SignalQualityHandler(webBase.BaseHandler):
    """GET /quantia/api/verify/signal_quality

    按指定指标分桶，统计各区间的信号质量（平均收益、胜率、夏普）。
    """

    def get(self):
        try:
            self._handle()
        except Exception:
            logging.error("信号质量诊断异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)

    def _handle(self):
        meta, start_date, end_date, err = _parse_common_args(self)
        if err:
            _write_error(self, err)
            return

        indicator = self.get_argument('indicator', default='rsi_6', strip=True).strip()
        if indicator not in _SIGNAL_QUALITY_INDICATORS:
            _write_error(self, f"不支持的指标: '{indicator}'，可用: {', '.join(sorted(_SIGNAL_QUALITY_INDICATORS))}")
            return

        holding_days_arg = self.get_argument('holding_days', default='5', strip=True)
        try:
            holding_days = max(1, min(int(holding_days_arg), RATE_FIELDS_COUNT))
        except (TypeError, ValueError):
            holding_days = 5

        # 自定义分桶 (可选)
        buckets_arg = self.get_argument('buckets', default='', strip=True)

        # 加载策略回测数据 (仅需 rate_N)
        rate_col = f'rate_{holding_days}'
        strategy_table = meta['table']
        if not mdb.checkTableIsExist(strategy_table):
            _write_error(self, f"策略表 {strategy_table} 不存在")
            return

        indicators_table = tbs.TABLE_CN_STOCK_INDICATORS['name']
        if not mdb.checkTableIsExist(indicators_table):
            _write_error(self, f"指标表 {indicators_table} 不存在")
            return

        # JOIN 策略表和指标表获取信号时刻的指标值
        sql = f"""
            SELECT s.`date`, s.`code`, s.`{rate_col}` AS rate,
                   i.`{indicator}` AS ind_val
            FROM `{strategy_table}` s
            INNER JOIN `{indicators_table}` i
                ON s.`date` = i.`date` AND s.`code` = i.`code`
            WHERE s.`date` >= %s AND s.`date` <= %s
              AND s.`{rate_col}` IS NOT NULL
              AND i.`{indicator}` IS NOT NULL
        """
        try:
            df = pd.read_sql(sql, con=mdb.engine(), params=(str(start_date), str(end_date)))
        except Exception as e:
            logging.error(f"信号质量查询失败: {e}", exc_info=True)
            _write_error(self, '查询失败', 500)
            return

        if df is None or len(df) == 0:
            _write_json(self, {
                'strategy': meta['table'],
                'indicator': indicator,
                'holding_days': holding_days,
                'buckets': [],
                'message': '该时间范围内无匹配数据',
            })
            return

        # 分桶逻辑
        if buckets_arg:
            # 自定义分桶: "0-30,30-50,50-70,70-100"
            bucket_ranges = []
            for part in buckets_arg.split(','):
                parts = part.strip().split('-')
                if len(parts) == 2:
                    try:
                        lo, hi = float(parts[0]), float(parts[1])
                        bucket_ranges.append((lo, hi))
                    except ValueError:
                        continue
        else:
            # 自动四分位分桶
            q = df['ind_val'].quantile([0, 0.25, 0.5, 0.75, 1.0]).values
            bucket_ranges = [(q[0], q[1]), (q[1], q[2]), (q[2], q[3]), (q[3], q[4])]

        buckets_result = []
        for lo, hi in bucket_ranges:
            mask = (df['ind_val'] >= lo) & (df['ind_val'] < hi)
            # 最后一个桶包含上界
            if (lo, hi) == bucket_ranges[-1]:
                mask = (df['ind_val'] >= lo) & (df['ind_val'] <= hi)
            subset = df.loc[mask, 'rate'].values

            if len(subset) == 0:
                continue

            avg_ret = float(subset.mean())
            win_rate = float((subset > 0).mean() * 100)
            sharpe = _calc_annualized_sharpe(subset, holding_days)

            # 质量评级
            if sharpe is not None and sharpe >= 2.5 and win_rate >= 65:
                quality = 'golden'
            elif sharpe is not None and sharpe >= 1.5 and win_rate >= 55:
                quality = 'good'
            elif sharpe is not None and sharpe >= 0:
                quality = 'neutral'
            else:
                quality = 'filter'

            buckets_result.append({
                'range': f'{lo:.1f}-{hi:.1f}',
                'range_lo': _safe_float(lo),
                'range_hi': _safe_float(hi),
                'signal_count': int(len(subset)),
                'pct': _safe_float(len(subset) / len(df) * 100),
                'avg_return': _safe_float(avg_ret),
                'win_rate': _safe_float(win_rate),
                'sharpe': _safe_float(sharpe),
                'quality': quality,
            })

        # 生成过滤建议: 标记 quality=filter 的区间
        filter_ranges = [b['range'] for b in buckets_result if b['quality'] == 'filter']
        golden_ranges = [b['range'] for b in buckets_result if b['quality'] == 'golden']

        # 计算过滤后的预期提升
        expected_improvement = {}
        if filter_ranges:
            kept = [b for b in buckets_result if b['quality'] != 'filter']
            if kept:
                total_kept_signals = sum(b['signal_count'] for b in kept)
                if total_kept_signals > 0:
                    # 加权平均
                    kept_win_rate = sum(b['win_rate'] * b['signal_count'] for b in kept if b['win_rate'] is not None) / total_kept_signals
                    kept_sharpe_vals = [b['sharpe'] for b in kept if b['sharpe'] is not None]
                    all_rates = df['rate'].dropna().values
                    overall_win_rate = float((all_rates > 0).mean() * 100)
                    overall_sharpe = _calc_annualized_sharpe(all_rates, holding_days)
                    expected_improvement['win_rate_delta'] = _safe_float(kept_win_rate - overall_win_rate)
                    if overall_sharpe and kept_sharpe_vals:
                        avg_kept_sharpe = sum(s * b['signal_count'] for s, b in zip(kept_sharpe_vals, [b for b in kept if b['sharpe'] is not None])) / sum(b['signal_count'] for b in kept if b['sharpe'] is not None)
                        expected_improvement['sharpe_delta'] = _safe_float(avg_kept_sharpe - overall_sharpe)

        _write_json(self, {
            'strategy': meta['table'],
            'strategy_cn': meta['cn'],
            'indicator': indicator,
            'holding_days': holding_days,
            'total_signals': len(df),
            'buckets': buckets_result,
            'recommendation': {
                'filter_ranges': filter_ranges,
                'golden_ranges': golden_ranges,
                'expected_improvement': expected_improvement,
            },
        })


# ── API 3: 止盈止损矩阵 ──────────────────────────────────────────────

class StopLossTakeProfitMatrixHandler(webBase.BaseHandler):
    """GET /quantia/api/verify/sl_tp_matrix

    对 (SL, TP) 网格的每个组合，模拟止盈止损并统计夏普/胜率/回撤。
    """

    def get(self):
        try:
            self._handle()
        except Exception:
            logging.error("止盈止损矩阵异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)

    def _handle(self):
        meta, start_date, end_date, err = _parse_common_args(self)
        if err:
            _write_error(self, err)
            return

        # 止损水平 (负值百分比)
        sl_arg = self.get_argument('sl_range', default='-2,-3,-5,-8,-10', strip=True)
        tp_arg = self.get_argument('tp_range', default='3,5,8,10,15', strip=True)
        max_hold_arg = self.get_argument('max_hold_days', default='20', strip=True)

        try:
            sl_levels = sorted(set(float(x.strip()) for x in sl_arg.split(',') if x.strip()), reverse=True)
        except ValueError:
            sl_levels = [-2, -3, -5, -8, -10]

        try:
            tp_levels = sorted(set(float(x.strip()) for x in tp_arg.split(',') if x.strip()))
        except ValueError:
            tp_levels = [3, 5, 8, 10, 15]

        try:
            max_hold = max(1, min(int(max_hold_arg), RATE_FIELDS_COUNT))
        except (TypeError, ValueError):
            max_hold = 20

        # 加载逐日收益
        rate_cols = [f'rate_{d}' for d in range(1, max_hold + 1)]
        df = _load_backtest_data(meta['table'], start_date, end_date, rate_cols)
        if df is None:
            _write_json(self, {
                'strategy': meta['table'],
                'max_hold_days': max_hold,
                'matrix': [],
                'message': '该时间范围内无策略信号',
            })
            return

        # 构造 rates_matrix: shape (N_trades, max_hold)
        rate_df = df[rate_cols].copy()
        rates_matrix = rate_df.values  # (N, max_hold)

        matrix = []
        best_sharpe = None
        best_combo = None

        for sl in sl_levels:
            for tp in tp_levels:
                final_rates = self._simulate_sl_tp(rates_matrix, sl, tp, max_hold)
                valid = final_rates[np.isfinite(final_rates)]
                if len(valid) == 0:
                    continue

                avg_ret = float(valid.mean())
                std_ret = float(valid.std(ddof=1)) if len(valid) > 1 else 0.0
                win_rate = float((valid > 0).mean() * 100)
                sharpe = _calc_annualized_sharpe(valid, max_hold)

                # 统计命中分布
                sl_hit, tp_hit, expired = self._count_exits(rates_matrix, sl, tp, max_hold)

                item = {
                    'stop_loss': sl,
                    'take_profit': tp,
                    'sharpe': _safe_float(sharpe),
                    'avg_return': _safe_float(avg_ret),
                    'win_rate': _safe_float(win_rate),
                    'return_std': _safe_float(std_ret),
                    'avg_hold_days': _safe_float(self._avg_hold_days(rates_matrix, sl, tp, max_hold)),
                    'trades_hit_sl': int(sl_hit),
                    'trades_hit_tp': int(tp_hit),
                    'trades_expired': int(expired),
                    'total_trades': int(len(valid)),
                }
                matrix.append(item)

                if sharpe is not None and (best_sharpe is None or sharpe > best_sharpe):
                    best_sharpe = sharpe
                    best_combo = {'stop_loss': sl, 'take_profit': tp, 'sharpe': _safe_float(sharpe)}

        _write_json(self, {
            'strategy': meta['table'],
            'strategy_cn': meta['cn'],
            'period': f'{start_date} ~ {end_date}',
            'max_hold_days': max_hold,
            'total_signals': len(df),
            'matrix': matrix,
            'best_combo': best_combo,
        })

    @staticmethod
    def _simulate_sl_tp(rates_matrix, sl, tp, max_hold):
        """向量化模拟止盈止损。

        rates_matrix: (N, max_hold), 每列为 rate_1..rate_max_hold
        返回: 1-D array (N,) 每笔交易的最终收益。
        """
        n_trades = rates_matrix.shape[0]
        mat = rates_matrix[:, :max_hold].copy()

        # 累积有效性掩码: NaN 之后的所有位置视为无效（与逐行循环行为一致）
        valid_mask = np.cumprod(np.isfinite(mat), axis=1).astype(bool)
        mat[~valid_mask] = np.nan

        # 布尔矩阵: 各天是否触达 SL/TP（NaN 位置的比较结果为 False）
        hit_sl = mat <= sl
        hit_tp = mat >= tp
        hit_any = hit_sl | hit_tp

        # argmax 在全 False 行返回 0，需要区分
        has_exit = hit_any.any(axis=1)
        # 首次触达的列索引
        first_exit_day = np.argmax(hit_any, axis=1)

        # 确定退出类型: SL 优先于 TP（同天同时满足算 SL）
        exit_is_sl = hit_sl[np.arange(n_trades), first_exit_day] & has_exit

        final_rates = np.full(n_trades, np.nan)
        final_rates[has_exit & exit_is_sl] = sl
        final_rates[has_exit & ~exit_is_sl] = tp

        # 未触达 SL/TP 的，取最后一天收益（如果有效）
        no_exit = ~has_exit
        last_col = mat[:, max_hold - 1]
        valid_expired = no_exit & np.isfinite(last_col)
        final_rates[valid_expired] = last_col[valid_expired]

        return final_rates

    @staticmethod
    def _count_exits(rates_matrix, sl, tp, max_hold):
        """统计各退出原因的笔数（向量化）。"""
        mat = rates_matrix[:, :max_hold].copy()
        n_trades = mat.shape[0]
        valid_mask = np.cumprod(np.isfinite(mat), axis=1).astype(bool)
        mat[~valid_mask] = np.nan

        hit_sl = mat <= sl
        hit_tp = mat >= tp
        hit_any = hit_sl | hit_tp
        has_exit = hit_any.any(axis=1)
        first_exit_day = np.argmax(hit_any, axis=1)

        exit_is_sl = hit_sl[np.arange(n_trades), first_exit_day] & has_exit
        exit_is_tp = hit_tp[np.arange(n_trades), first_exit_day] & has_exit & ~exit_is_sl

        no_exit = ~has_exit
        last_col = mat[:, max_hold - 1]
        valid_expired = no_exit & np.isfinite(last_col)

        return int(exit_is_sl.sum()), int(exit_is_tp.sum()), int(valid_expired.sum())

    @staticmethod
    def _avg_hold_days(rates_matrix, sl, tp, max_hold):
        """计算平均持仓天数（向量化）。"""
        mat = rates_matrix[:, :max_hold].copy()
        n_trades = mat.shape[0]
        valid_mask = np.cumprod(np.isfinite(mat), axis=1).astype(bool)
        mat[~valid_mask] = np.nan

        hit_any = (mat <= sl) | (mat >= tp)
        has_exit = hit_any.any(axis=1)
        first_exit_day = np.argmax(hit_any, axis=1)  # 0-based column index

        no_exit = ~has_exit
        last_col = mat[:, max_hold - 1]
        valid_expired = no_exit & np.isfinite(last_col)

        # 持仓天数: 触达的为 first_exit_day + 1, 到期的为 max_hold
        days = np.zeros(n_trades)
        days[has_exit] = first_exit_day[has_exit] + 1
        days[valid_expired] = max_hold

        valid_mask = has_exit | valid_expired
        if valid_mask.sum() == 0:
            return 0.0
        return float(days[valid_mask].mean())


# ── API 4: 市场环境分类 ──────────────────────────────────────────────

class MarketRegimeHandler(webBase.BaseHandler):
    """GET /quantia/api/verify/market_regime

    用 MA20/MA60 交叉 + ATR 中位数对市场环境分类，
    然后分环境统计策略表现。
    """

    def get(self):
        try:
            self._handle()
        except Exception:
            logging.error("市场环境分类异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)

    def _handle(self):
        meta, start_date, end_date, err = _parse_common_args(self)
        if err:
            _write_error(self, err)
            return

        benchmark = self.get_argument('benchmark', default='000300', strip=True).strip()
        holding_days_arg = self.get_argument('holding_days', default='5', strip=True)
        try:
            holding_days = max(1, min(int(holding_days_arg), RATE_FIELDS_COUNT))
        except (TypeError, ValueError):
            holding_days = 5

        # 加载基准指数数据 (从缓存/DB，不调用外部 API)
        from quantia.core.backtest.data_feed import load_benchmark_data
        # 需要额外前置 60 日用于 MA60 计算
        extended_start = start_date - datetime.timedelta(days=90)
        bench_df = load_benchmark_data(benchmark, str(extended_start), str(end_date))
        if bench_df is None or len(bench_df) == 0:
            _write_error(self, f"无法加载基准 {benchmark} 数据")
            return

        # 确保日期排序
        bench_df = bench_df.sort_values('date').reset_index(drop=True)
        bench_df['date'] = pd.to_datetime(bench_df['date'])

        # 计算 MA 和 ATR
        bench_df['ma20'] = bench_df['close'].rolling(20, min_periods=20).mean()
        bench_df['ma60'] = bench_df['close'].rolling(60, min_periods=60).mean()

        if 'high' in bench_df.columns and 'low' in bench_df.columns:
            bench_df['tr'] = np.maximum(
                bench_df['high'] - bench_df['low'],
                np.maximum(
                    abs(bench_df['high'] - bench_df['close'].shift(1)),
                    abs(bench_df['low'] - bench_df['close'].shift(1))
                )
            )
            bench_df['atr20'] = bench_df['tr'].rolling(20, min_periods=20).mean()
        else:
            # 无高低价时用收益率波动替代
            bench_df['atr20'] = bench_df['close'].pct_change().rolling(20).std()

        atr_median = bench_df['atr20'].median()

        # 分类
        bench_df['regime'] = 'sideways'
        mask_bull = (bench_df['ma20'] > bench_df['ma60']) & (bench_df['atr20'] > atr_median)
        mask_bear = (bench_df['ma20'] < bench_df['ma60']) & (bench_df['atr20'] > atr_median)
        bench_df.loc[mask_bull, 'regime'] = 'bull'
        bench_df.loc[mask_bear, 'regime'] = 'bear'

        # 裁剪到请求日期范围
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)
        bench_range = bench_df[(bench_df['date'] >= start_ts) & (bench_df['date'] <= end_ts)].copy()

        if len(bench_range) == 0:
            # 日期可能落在周末/节假日，尝试向前扩展到最近交易日
            last_trade_date = bench_df[bench_df['date'] <= end_ts]['date'].max()
            first_trade_date = bench_df[bench_df['date'] >= start_ts]['date'].min()
            hint_parts = []
            if pd.notna(last_trade_date):
                hint_parts.append(f"最近交易日为 {last_trade_date.strftime('%Y-%m-%d')}")
            hint_parts.append('请扩大日期范围（建议至少30天）以覆盖足够的交易日')
            _write_error(self, f'指定范围内({start_date}~{end_date})无交易数据，' + '，'.join(hint_parts))
            return

        # 生成 regime 序列
        regime_series = bench_range[['date', 'regime']].copy()
        regime_series['date'] = regime_series['date'].dt.strftime('%Y-%m-%d')

        # 合并成连续段
        regimes = []
        if len(regime_series) > 0:
            rows = regime_series.to_dict('records')
            cur = {'start': rows[0]['date'], 'end': rows[0]['date'], 'type': rows[0]['regime'], 'days': 1}
            for r in rows[1:]:
                if r['regime'] == cur['type']:
                    cur['end'] = r['date']
                    cur['days'] += 1
                else:
                    regimes.append(cur)
                    cur = {'start': r['date'], 'end': r['date'], 'type': r['regime'], 'days': 1}
            regimes.append(cur)

        # 加载策略数据并按环境统计
        rate_col = f'rate_{holding_days}'
        df = _load_backtest_data(meta['table'], start_date, end_date, [rate_col])
        strategy_by_regime = {}

        if df is not None and len(df) > 0:
            df['date'] = pd.to_datetime(df['date'])
            # 合并环境标签
            regime_lookup = bench_range[['date', 'regime']].set_index('date')['regime']
            df['regime'] = df['date'].map(regime_lookup)

            for regime_type in ['bull', 'bear', 'sideways']:
                subset = df[df['regime'] == regime_type]
                rates = subset[rate_col].dropna().values
                if len(rates) == 0:
                    strategy_by_regime[regime_type] = {
                        'avg_return': None, 'sharpe': None, 'win_rate': None, 'signal_count': 0,
                    }
                    continue

                strategy_by_regime[regime_type] = {
                    'avg_return': _safe_float(float(rates.mean())),
                    'sharpe': _safe_float(_calc_annualized_sharpe(rates, holding_days)),
                    'win_rate': _safe_float(float((rates > 0).mean() * 100)),
                    'signal_count': int(len(rates)),
                }

        _write_json(self, {
            'strategy': meta['table'],
            'strategy_cn': meta['cn'],
            'benchmark': benchmark,
            'holding_days': holding_days,
            'period': f'{start_date} ~ {end_date}',
            'regimes': regimes,
            'strategy_by_regime': strategy_by_regime,
            'classification_method': 'MA20/MA60 crossover + ATR median',
        })


# ── API 5: 信号衰减分析 ──────────────────────────────────────────────

class SignalDecayHandler(webBase.BaseHandler):
    """GET /quantia/api/verify/signal_decay

    按月分组统计策略的胜率/收益率/夏普变化趋势。
    """

    def get(self):
        try:
            self._handle()
        except Exception:
            logging.error("信号衰减分析异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)

    def _handle(self):
        meta, start_date, end_date, err = _parse_common_args(self)
        if err:
            _write_error(self, err)
            return

        holding_days_arg = self.get_argument('holding_days', default='5', strip=True)
        try:
            holding_days = max(1, min(int(holding_days_arg), RATE_FIELDS_COUNT))
        except (TypeError, ValueError):
            holding_days = 5

        rate_col = f'rate_{holding_days}'
        df = _load_backtest_data(meta['table'], start_date, end_date, [rate_col])
        if df is None:
            _write_json(self, {
                'strategy': meta['table'],
                'holding_days': holding_days,
                'monthly': [],
                'message': '该时间范围内无策略信号',
            })
            return

        df['date'] = pd.to_datetime(df['date'])
        df['month'] = df['date'].dt.to_period('M')

        monthly = []
        for period, group in df.groupby('month'):
            rates = group[rate_col].dropna().values
            if len(rates) == 0:
                continue
            monthly.append({
                'month': str(period),
                'signal_count': int(len(rates)),
                'avg_return': _safe_float(float(rates.mean())),
                'win_rate': _safe_float(float((rates > 0).mean() * 100)),
                'sharpe': _safe_float(_calc_annualized_sharpe(rates, holding_days)),
                'return_std': _safe_float(float(rates.std(ddof=1))) if len(rates) > 1 else None,
            })

        # 衰减检测: 前半段 vs 后半段夏普对比
        decay_warning = None
        if len(monthly) >= 4:
            half = len(monthly) // 2
            first_sharpes = [m['sharpe'] for m in monthly[:half] if m['sharpe'] is not None]
            second_sharpes = [m['sharpe'] for m in monthly[half:] if m['sharpe'] is not None]
            if first_sharpes and second_sharpes:
                first_avg = np.mean(first_sharpes)
                second_avg = np.mean(second_sharpes)
                if first_avg > 0 and second_avg < first_avg * 0.7:
                    decay_warning = f"夏普从前半段 {first_avg:.2f} 下降到后半段 {second_avg:.2f}，Alpha 可能在衰减"

        _write_json(self, {
            'strategy': meta['table'],
            'strategy_cn': meta['cn'],
            'holding_days': holding_days,
            'period': f'{start_date} ~ {end_date}',
            'monthly': monthly,
            'decay_warning': decay_warning,
        })


# ── API 7: 交易成本敏感性 ────────────────────────────────────────────

class CostSensitivityHandler(webBase.BaseHandler):
    """GET /quantia/api/verify/cost_sensitivity

    展示不同交易成本假设下的策略表现变化。
    """

    def get(self):
        try:
            self._handle()
        except Exception:
            logging.error("成本敏感性分析异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)

    def _handle(self):
        meta, start_date, end_date, err = _parse_common_args(self)
        if err:
            _write_error(self, err)
            return

        holding_days_arg = self.get_argument('holding_days', default='5', strip=True)
        try:
            holding_days = max(1, min(int(holding_days_arg), RATE_FIELDS_COUNT))
        except (TypeError, ValueError):
            holding_days = 5

        rate_col = f'rate_{holding_days}'
        df = _load_backtest_data(meta['table'], start_date, end_date, [rate_col])
        if df is None:
            _write_json(self, {
                'strategy': meta['table'],
                'scenarios': [],
                'message': '该时间范围内无策略信号',
            })
            return

        rates = df[rate_col].dropna().values
        if len(rates) == 0:
            _write_json(self, {'strategy': meta['table'], 'scenarios': [], 'message': '无有效收益数据'})
            return

        # 当前 rate 已包含 ROUND_TRIP_COST_PCT (0.20%) 的交易成本
        # 模拟不同成本: 先还原到毛收益，再减去不同成本
        current_cost = ROUND_TRIP_COST_PCT  # 0.20
        gross_rates = rates + current_cost  # 毛收益

        cost_levels = [0.0, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]
        scenarios = []

        for cost in cost_levels:
            net_rates = gross_rates - cost
            avg_ret = float(net_rates.mean())
            win_rate = float((net_rates > 0).mean() * 100)
            sharpe = _calc_annualized_sharpe(net_rates, holding_days)

            scenarios.append({
                'cost_pct': cost,
                'avg_return': _safe_float(avg_ret),
                'win_rate': _safe_float(win_rate),
                'sharpe': _safe_float(sharpe),
                'is_current': abs(cost - current_cost) < 0.001,
            })

        _write_json(self, {
            'strategy': meta['table'],
            'strategy_cn': meta['cn'],
            'holding_days': holding_days,
            'period': f'{start_date} ~ {end_date}',
            'total_signals': int(len(rates)),
            'current_cost_pct': current_cost,
            'scenarios': scenarios,
        })


# ── API 6: 卖出方式对比 ──────────────────────────────────────────────

class ExitCompareHandler(webBase.BaseHandler):
    """GET /quantia/api/verify/exit_compare

    对比四种卖出策略: 固定持有 / 跟踪止损 / 止盈止损 / 指标反转
    """

    def get(self):
        try:
            self._handle()
        except Exception:
            logging.error("卖出方式对比异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)

    def _handle(self):
        meta, start_date, end_date, err = _parse_common_args(self)
        if err:
            _write_error(self, err)
            return

        holding_days_arg = self.get_argument('holding_days', default='5', strip=True)
        try:
            holding_days = max(1, min(int(holding_days_arg), RATE_FIELDS_COUNT))
        except (TypeError, ValueError):
            holding_days = 5

        # 跟踪止损回看天数
        trailing_days_arg = self.get_argument('trailing_days', default='10,15,20', strip=True)
        try:
            trailing_days_list = sorted(set(
                max(5, min(int(x.strip()), 60))
                for x in trailing_days_arg.split(',') if x.strip()
            ))
        except ValueError:
            trailing_days_list = [10, 15, 20]

        # 加载完整逐日数据
        max_hold = max(holding_days, max(trailing_days_list) + 10)
        max_hold = min(max_hold, RATE_FIELDS_COUNT)
        rate_cols = [f'rate_{d}' for d in range(1, max_hold + 1)]
        df = _load_backtest_data(meta['table'], start_date, end_date, rate_cols)
        if df is None:
            _write_json(self, {
                'strategy': meta['table'],
                'exit_strategies': [],
                'message': '该时间范围内无策略信号',
            })
            return

        rates_matrix = df[rate_cols].values
        total_signals = len(df)
        exit_strategies = []

        # 策略 1: 固定持有 N 天
        fixed_rates = rates_matrix[:, holding_days - 1]  # rate_N (0-indexed col)
        valid_fixed = fixed_rates[np.isfinite(fixed_rates)]
        if len(valid_fixed) > 0:
            exit_strategies.append({
                'exit_type': 'fixed_holding',
                'label': f'固定持有{holding_days}天',
                'holding_days': holding_days,
                'avg_return': _safe_float(float(valid_fixed.mean())),
                'win_rate': _safe_float(float((valid_fixed > 0).mean() * 100)),
                'sharpe': _safe_float(_calc_annualized_sharpe(valid_fixed, holding_days)),
                'sortino': _safe_float(_calc_sortino(valid_fixed, holding_days)),
                'max_single_loss': _safe_float(float(valid_fixed.min())),
                'signal_count': int(len(valid_fixed)),
            })

        # 策略 2: 跟踪止损 (多个回看天数)
        for trail_d in trailing_days_list:
            trail_rates = self._simulate_trailing_stop(rates_matrix, trail_d, max_hold)
            valid_trail = trail_rates[np.isfinite(trail_rates)]
            if len(valid_trail) > 0:
                avg_hold = self._trailing_avg_hold(rates_matrix, trail_d, max_hold)
                exit_strategies.append({
                    'exit_type': 'trailing_stop',
                    'label': f'跟踪止损({trail_d}日低点)',
                    'trailing_days': trail_d,
                    'avg_return': _safe_float(float(valid_trail.mean())),
                    'win_rate': _safe_float(float((valid_trail > 0).mean() * 100)),
                    'sharpe': _safe_float(_calc_annualized_sharpe(valid_trail, holding_days)),
                    'sortino': _safe_float(_calc_sortino(valid_trail, holding_days)),
                    'max_single_loss': _safe_float(float(valid_trail.min())),
                    'avg_hold_days': _safe_float(avg_hold),
                    'signal_count': int(len(valid_trail)),
                })

        # 策略 3: 止盈止损（选用最优组合附近）
        # 用 P75 作为 TP, P25 作为 SL
        valid_fixed_for_pct = fixed_rates[np.isfinite(fixed_rates)]
        if len(valid_fixed_for_pct) > 20:
            tp = float(np.percentile(valid_fixed_for_pct, 75))
            sl = float(np.percentile(valid_fixed_for_pct, 25))
            if sl >= 0:
                sl = -abs(tp) * 0.5  # 确保止损为负
            tp = max(tp, 1.0)
            sl = min(sl, -1.0)

            sltp_rates = StopLossTakeProfitMatrixHandler._simulate_sl_tp(
                rates_matrix, sl, tp, holding_days
            )
            valid_sltp = sltp_rates[np.isfinite(sltp_rates)]
            if len(valid_sltp) > 0:
                exit_strategies.append({
                    'exit_type': 'sl_tp',
                    'label': f'止盈{tp:.1f}%/止损{sl:.1f}%',
                    'stop_loss': _safe_float(sl),
                    'take_profit': _safe_float(tp),
                    'avg_return': _safe_float(float(valid_sltp.mean())),
                    'win_rate': _safe_float(float((valid_sltp > 0).mean() * 100)),
                    'sharpe': _safe_float(_calc_annualized_sharpe(valid_sltp, holding_days)),
                    'sortino': _safe_float(_calc_sortino(valid_sltp, holding_days)),
                    'max_single_loss': _safe_float(float(valid_sltp.min())),
                    'signal_count': int(len(valid_sltp)),
                })

        # 策略 4: 收益回撤止盈 (从最高收益回撤 X% 后退出)
        for drawback_pct in [3.0, 5.0]:
            dd_rates = self._simulate_drawback_exit(rates_matrix, drawback_pct, max_hold)
            valid_dd = dd_rates[np.isfinite(dd_rates)]
            if len(valid_dd) > 0:
                exit_strategies.append({
                    'exit_type': 'drawback_exit',
                    'label': f'回撤{drawback_pct:.0f}%止盈',
                    'drawback_pct': drawback_pct,
                    'avg_return': _safe_float(float(valid_dd.mean())),
                    'win_rate': _safe_float(float((valid_dd > 0).mean() * 100)),
                    'sharpe': _safe_float(_calc_annualized_sharpe(valid_dd, holding_days)),
                    'sortino': _safe_float(_calc_sortino(valid_dd, holding_days)),
                    'max_single_loss': _safe_float(float(valid_dd.min())),
                    'signal_count': int(len(valid_dd)),
                })

        # 找最优
        best_strategy = None
        best_sharpe_val = None
        for es in exit_strategies:
            if es['sharpe'] is not None and (best_sharpe_val is None or es['sharpe'] > best_sharpe_val):
                best_sharpe_val = es['sharpe']
                best_strategy = es['exit_type']

        _write_json(self, {
            'strategy': meta['table'],
            'strategy_cn': meta['cn'],
            'period': f'{start_date} ~ {end_date}',
            'total_signals': total_signals,
            'exit_strategies': exit_strategies,
            'best_strategy': best_strategy,
        })

    @staticmethod
    def _simulate_trailing_stop(rates_matrix, trailing_days, max_hold):
        """模拟跟踪止损: 当日收益跌破最近 trailing_days 日内的最低收益时退出。"""
        n_trades = rates_matrix.shape[0]
        cols = min(max_hold, rates_matrix.shape[1])
        mat = rates_matrix[:, :cols].copy()
        valid_mask = np.cumprod(np.isfinite(mat), axis=1).astype(bool)
        mat[~valid_mask] = np.nan

        final_rates = np.full(n_trades, np.nan)
        for i in range(n_trades):
            row = mat[i]
            exited = False
            for d in range(cols):
                if np.isnan(row[d]):
                    break
                # 从第 trailing_days 天开始检测
                if d >= trailing_days:
                    window_min = np.nanmin(row[max(0, d - trailing_days):d])
                    if row[d] < window_min:
                        final_rates[i] = row[d]
                        exited = True
                        break
            if not exited:
                # 找最后一个有效值
                valid_cols = np.where(valid_mask[i])[0]
                if len(valid_cols) > 0:
                    final_rates[i] = mat[i, valid_cols[-1]]
        return final_rates

    @staticmethod
    def _trailing_avg_hold(rates_matrix, trailing_days, max_hold):
        """计算跟踪止损的平均持仓天数。"""
        n_trades = rates_matrix.shape[0]
        cols = min(max_hold, rates_matrix.shape[1])
        mat = rates_matrix[:, :cols].copy()
        valid_mask = np.cumprod(np.isfinite(mat), axis=1).astype(bool)
        mat[~valid_mask] = np.nan

        days_list = []
        for i in range(n_trades):
            row = mat[i]
            hold = 0
            for d in range(cols):
                if np.isnan(row[d]):
                    break
                hold = d + 1
                if d >= trailing_days:
                    window_min = np.nanmin(row[max(0, d - trailing_days):d])
                    if row[d] < window_min:
                        break
            if hold > 0:
                days_list.append(hold)
        return float(np.mean(days_list)) if days_list else 0.0

    @staticmethod
    def _simulate_drawback_exit(rates_matrix, drawback_pct, max_hold):
        """模拟回撤止盈: 从持有期间最高收益回撤 drawback_pct 个百分点时退出。"""
        n_trades = rates_matrix.shape[0]
        cols = min(max_hold, rates_matrix.shape[1])
        mat = rates_matrix[:, :cols].copy()
        valid_mask = np.cumprod(np.isfinite(mat), axis=1).astype(bool)
        mat[~valid_mask] = np.nan

        final_rates = np.full(n_trades, np.nan)
        for i in range(n_trades):
            row = mat[i]
            peak = -np.inf
            exited = False
            for d in range(cols):
                if np.isnan(row[d]):
                    break
                if row[d] > peak:
                    peak = row[d]
                # 从峰值回撤超过阈值
                if peak > 0 and (peak - row[d]) >= drawback_pct:
                    final_rates[i] = row[d]
                    exited = True
                    break
            if not exited:
                valid_cols = np.where(valid_mask[i])[0]
                if len(valid_cols) > 0:
                    final_rates[i] = mat[i, valid_cols[-1]]
        return final_rates


# ── API 7: 日级收益序列 (累计走势图数据源) ────────────────────────────

class SignalReturnSeriesHandler(webBase.BaseHandler):
    """GET /quantia/api/verify/return_series

    返回策略的日级平均收益时间序列，用于累计收益走势 + 水下回撤图。
    """

    def get(self):
        try:
            self._handle()
        except Exception:
            logging.error("收益序列异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)

    def _handle(self):
        meta, start_date, end_date, err = _parse_common_args(self)
        if err:
            _write_error(self, err)
            return

        holding_days_arg = self.get_argument('holding_days', default='5', strip=True)
        benchmark = self.get_argument('benchmark', default='000300', strip=True) or '000300'
        try:
            holding_days = max(1, min(int(holding_days_arg), RATE_FIELDS_COUNT))
        except (TypeError, ValueError):
            holding_days = 5

        rate_col = f'rate_{holding_days}'
        df = _load_backtest_data(meta['table'], start_date, end_date, [rate_col])
        if df is None:
            _write_json(self, {
                'strategy': meta['table'],
                'strategy_cn': meta['cn'],
                'series': [],
                'benchmark_series': _benchmark_return_series(benchmark, start_date, end_date),
            })
            return

        df['date'] = pd.to_datetime(df['date'])
        # 按日计算该日所有信号的平均收益
        daily = df.groupby('date')[rate_col].mean().sort_index()

        # 构建累计收益 (假设每日等权再平衡)
        cumulative = (1 + daily / 100).cumprod() * 100  # 起始 100
        # 水下回撤
        running_max = cumulative.cummax()
        drawdown = (cumulative - running_max) / running_max * 100

        series = []
        for date, cum_val in cumulative.items():
            d_str = date.strftime('%Y-%m-%d')
            series.append({
                'date': d_str,
                'cumulative': _safe_float(round(float(cum_val), 2)),
                'drawdown': _safe_float(round(float(drawdown.loc[date]), 2)),
                'daily_return': _safe_float(round(float(daily.loc[date]), 2)),
            })

        _write_json(self, {
            'strategy': meta['table'],
            'strategy_cn': meta['cn'],
            'holding_days': holding_days,
            'series': series,
            'benchmark_series': _benchmark_return_series(benchmark, start_date, end_date),
        })

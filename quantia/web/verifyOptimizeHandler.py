#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""选股验证中心 — 优化分析 API Handler

提供持仓天数扫描、信号质量诊断、止盈止损矩阵、市场环境分类、
信号衰减分析、交易成本敏感性等只读分析接口。

数据来源: MySQL + cache/hist/

【架构例外】当策略表 (cn_stock_strategy_*) 在请求区间无数据时，
_compute_signals_from_kline_cache() 会扫描 cache/hist/ 跑策略 check() 计算
信号 + 前向收益，结果落盘到 cache/signal/。这违反 AGENTS.md 规则 1 "Web
层不得跑分析"，仅作为兜底，对外部 API 仍零调用。可通过
QUANTIA_VERIFY_FALLBACK_ENABLED=0 关闭。
"""

import datetime
import hashlib
import json
import logging
import math
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

import quantia.core.tablestructure as tbs
import quantia.core.stockfetch as stf
import quantia.core.indicator.calculate_indicator as idr
import quantia.lib.database as mdb
import quantia.lib.envconfig as _envcfg
import quantia.web.base as webBase
from quantia.core.backtest.data_feed import load_benchmark_data
from quantia.core.backtest.rate_stats import ROUND_TRIP_COST_PCT
from quantia.web.utils import parse_int_list as _parse_int_list, json_default as _json_default

__author__ = 'Quantia'
__date__ = '2026/05/15'

# ── 常量 ──────────────────────────────────────────────────────────────

RATE_FIELDS_COUNT = tbs.RATE_FIELDS_COUNT  # 100
# 持仓天数扫描的真正可分析上限：DB 仅有 rate_1..100，>100 时走 K 线兜底动态算
MAX_HOLDING_DAYS_EXTENDED = 240
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


def _max_rate_day(rate_cols):
    """从 rate_cols 中提取最大 N 值，如 ['rate_1','rate_60','rate_180'] -> 180。"""
    mx = 0
    for c in rate_cols or []:
        try:
            mx = max(mx, int(str(c).replace('rate_', '')))
        except (ValueError, AttributeError):
            continue
    return mx


def _load_backtest_data(strategy_table, start_date, end_date, rate_cols=None):
    """从策略表加载回测数据。

    Returns: DataFrame with date, code, name + rate columns, or None.

    路由规则：
    - max(N) ≤ 100 且 DB 有数据 → DB 读取（最快）。
    - max(N) ≤ 100 且 DB 空 → K 线兜底（max_rate=100，可缓存复用）。
    - max(N) > 100 → 直接 K 线兜底（DB 本身没有 rate_>100 的列），
      max_rate 对齐到 max(N)，缓存按 max_rate 分文件。
    """
    if rate_cols is None:
        rate_cols = [f'rate_{i}' for i in range(1, RATE_FIELDS_COUNT + 1)]

    max_day = _max_rate_day(rate_cols)
    needs_extended = max_day > RATE_FIELDS_COUNT

    df = None
    if not needs_extended and mdb.checkTableIsExist(strategy_table):
        base_cols = ['date', 'code', 'name']
        all_cols = base_cols + rate_cols
        cols_sql = ', '.join(f'`{c}`' for c in all_cols)
        sql = f"SELECT {cols_sql} FROM `{strategy_table}` WHERE `date` >= %s AND `date` <= %s"
        try:
            df = pd.read_sql(sql, con=mdb.engine(), params=(str(start_date), str(end_date)))
        except Exception as e:
            logging.error(f"读取 {strategy_table} 失败: {e}", exc_info=True)
            df = None

    if df is None or len(df) == 0:
        # ── DB 缺数据 / 请求 N>100 → 走 K 线缓存 fallback ──
        max_rate = max(RATE_FIELDS_COUNT, max_day) if max_day > 0 else RATE_FIELDS_COUNT
        fallback_df = _compute_signals_from_kline_cache(
            strategy_table, start_date, end_date, max_rate=max_rate)
        if fallback_df is not None and len(fallback_df) > 0:
            keep = ['date', 'code', 'name'] + [c for c in rate_cols if c in fallback_df.columns]
            df = fallback_df[keep].copy()

    return df if df is not None and len(df) > 0 else None


# ──────────────────────────────────────────────────────────────────────
# Signal fallback: 当策略表在请求区间无数据时，扫描 cache/hist/ K 线，
# 临时执行 strategy func 得到 (date, code, name, rate_1..rate_N) 信号集，
# 结果落盘到 cache/signal/<table>_<start>_<end>.gzip.pickle 供后续命中。
#
# 架构例外：本来 AGENTS.md 规则 1 禁止 Web 层跑分析。此处作为 DB 数据缺
# 失时的兜底（用户选项 C，知情同意）；首次扫描耗时较长，但后续走文件缓存。
# 通过环境变量控制：
#   QUANTIA_VERIFY_FALLBACK_ENABLED=1   (默认开启)
#   QUANTIA_VERIFY_FALLBACK_MAX_STOCKS=300
#   QUANTIA_VERIFY_FALLBACK_WORKERS=4
# ──────────────────────────────────────────────────────────────────────

_SIGNAL_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), 'cache', 'signal'
)
_FALLBACK_ENABLED = _envcfg.get_bool('QUANTIA_VERIFY_FALLBACK_ENABLED', True)
_FALLBACK_MAX_STOCKS = _envcfg.get_int('QUANTIA_VERIFY_FALLBACK_MAX_STOCKS', 300)
_FALLBACK_WORKERS = _envcfg.get_int('QUANTIA_VERIFY_FALLBACK_WORKERS', 4)
_FALLBACK_HIST_BUFFER_DAYS = 365 * 2  # K 线前置缓冲（供 TA-Lib 窗口用）
_FALLBACK_FORWARD_BUFFER_DAYS = 130   # 后向缓冲（供 rate_60 等前向收益计算）


def _signal_cache_path(strategy_table: str, start_date, end_date, max_rate: int = 100) -> str:
    if not os.path.exists(_SIGNAL_CACHE_DIR):
        try:
            os.makedirs(_SIGNAL_CACHE_DIR, exist_ok=True)
        except Exception:
            pass
    # max_rate 不同 → 缓存文件分开，避免 100 档与 240 档相互覆盖
    return os.path.join(
        _SIGNAL_CACHE_DIR,
        f"{strategy_table}_{start_date}_{end_date}_r{int(max_rate)}.gzip.pickle",
    )


def _load_signal_cache_file(path: str):
    if not os.path.exists(path):
        return None
    try:
        return pd.read_pickle(path, compression='gzip')
    except Exception as e:
        logging.warning(f"[signal-fallback] 读取缓存文件失败 {path}: {e}")
        return None


def _save_signal_cache_file(path: str, df: pd.DataFrame) -> None:
    try:
        df.to_pickle(path, compression='gzip')
    except Exception as e:
        logging.warning(f"[signal-fallback] 写缓存文件失败 {path}: {e}")


def _get_builtin_strategy_func(strategy_table: str):
    """根据策略表名找到内置 check() 函数。返回 (func, threshold) 或 (None, 60)。"""
    for s in tbs.TABLE_CN_STOCK_STRATEGIES:
        if s.get('name') == strategy_table:
            return s.get('func'), s.get('size', 60)
    return None, 60


def _load_fallback_stock_universe(max_stocks: int):
    """从 cn_stock_spot 取最近一天的股票列表（限制条数）。返回 [(date, code, name), ...]。"""
    try:
        spot_table = tbs.TABLE_CN_STOCK_SPOT['name']
        if not mdb.checkTableIsExist(spot_table):
            return []
        fk_cols = list(tbs.TABLE_CN_STOCK_FOREIGN_KEY['columns'].keys())
        cols_sql = ', '.join(f'`{c}`' for c in fk_cols)
        sql = (
            f"SELECT {cols_sql} FROM `{spot_table}` "
            f"WHERE `date` = (SELECT MAX(`date`) FROM `{spot_table}`) "
            f"LIMIT {int(max_stocks)}"
        )
        df = pd.read_sql(sql, mdb.engine())
        if df is None or df.empty:
            return []
        return [tuple(x) for x in df[fk_cols].values]
    except Exception as e:
        logging.warning(f"[signal-fallback] 读取股票列表失败: {e}")
        return []


def _scan_one_stock_for_signals(stock, strategy_func, threshold, start_ts, end_ts,
                                 ext_start_str, ext_end_str, rate_cols_all):
    """单只股票扫描：返回 [{date,code,name,p_change,rate_1..rate_N}, ...]"""
    code = stock[1]
    name = stock[2] if len(stock) > 2 else ''
    try:
        hist = stf.read_stock_hist_from_cache(code, ext_start_str, ext_end_str)
    except Exception:
        return []
    if hist is None or len(hist) < threshold + 5:
        return []
    try:
        if not pd.api.types.is_datetime64_any_dtype(hist['date']):
            hist = hist.copy()
            hist['date'] = pd.to_datetime(hist['date'])
    except Exception:
        return []

    in_range = hist[(hist['date'] >= start_ts) & (hist['date'] <= end_ts)]
    if in_range.empty:
        return []

    closes = hist['close'].reset_index(drop=True)
    dates_all = hist['date'].reset_index(drop=True).tolist()
    date_to_idx = {d: i for i, d in enumerate(dates_all)}

    rows = []
    for _, row in in_range.iterrows():
        d = row['date']
        try:
            matched = strategy_func(stock, hist, date=d.to_pydatetime())
        except TypeError:
            # 个别策略需要 istop 等额外参数；这里 fallback 用 False
            try:
                matched = strategy_func(stock, hist, date=d.to_pydatetime(), istop=False)
            except Exception:
                continue
        except Exception:
            continue
        if not matched:
            continue
        idx = date_to_idx.get(d)
        if idx is None:
            continue
        base = float(row['close']) if row.get('close') is not None else 0.0
        if base <= 0:
            continue
        rec = {
            'date': d.strftime('%Y-%m-%d'),
            'code': code,
            'name': name,
            'p_change': float(row.get('p_change', 0.0) or 0.0),
        }
        for i, col in enumerate(rate_cols_all, start=1):
            fwd = idx + i
            if fwd < len(closes):
                try:
                    rec[col] = (float(closes.iloc[fwd]) - base) / base * 100
                except Exception:
                    rec[col] = None
            else:
                rec[col] = None
        rows.append(rec)
    return rows


def _compute_signals_from_kline_cache(strategy_table: str, start_date, end_date,
                                       max_rate: int = RATE_FIELDS_COUNT):
    """DB 无数据时的 fallback：扫 cache/hist/ 跑策略 check() 算信号 + 前向收益。

    1. 优先读 cache/signal/<table>_<start>_<end>_r{max_rate}.gzip.pickle。
    2. miss 时扫描 cn_stock_spot 最近一天的前 max_stocks 只股票，逐只调用
       策略 check() 函数；命中则基于同一份 K 线计算 rate_1..rate_{max_rate}。
       后向缓冲按 max_rate 动态放大（默认 130 天足够 rate_60，max_rate=240
       时放宽到约 360 天）。
    3. 完成后写入 gzip.pickle 缓存供下次直接读取。
    """
    if not _FALLBACK_ENABLED:
        return None

    max_rate = max(1, int(max_rate))
    cache_path = _signal_cache_path(strategy_table, start_date, end_date, max_rate)
    cached = _load_signal_cache_file(cache_path)
    if cached is not None and len(cached) > 0:
        logging.info(
            f"[signal-fallback] 命中文件缓存 {cache_path}: {len(cached)} rows (max_rate={max_rate})"
        )
        return cached

    strategy_func, threshold = _get_builtin_strategy_func(strategy_table)
    if strategy_func is None:
        logging.info(f"[signal-fallback] 策略 {strategy_table} 不在内置注册表，跳过 fallback")
        return None

    stocks = _load_fallback_stock_universe(_FALLBACK_MAX_STOCKS)
    if not stocks:
        logging.info("[signal-fallback] 股票列表为空，跳过 fallback")
        return None

    total = len(stocks)
    logging.info(
        f"[signal-fallback] 开始扫描 {total} 只股票，区间 {start_date}~{end_date}，"
        f"策略={strategy_table}, max_rate={max_rate}"
    )

    # max_rate 越大，后向缓冲越长。粗估：1 个交易日 ≈ 1.45 个自然日
    forward_buffer_days = max(_FALLBACK_FORWARD_BUFFER_DAYS, int(max_rate * 1.5) + 30)
    ext_start = (start_date - datetime.timedelta(days=_FALLBACK_HIST_BUFFER_DAYS)).strftime('%Y%m%d')
    ext_end = (end_date + datetime.timedelta(days=forward_buffer_days)).strftime('%Y%m%d')
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    rate_cols_all = [f'rate_{i}' for i in range(1, max_rate + 1)]

    results = []
    with ThreadPoolExecutor(max_workers=max(1, _FALLBACK_WORKERS),
                             thread_name_prefix='verify-fallback') as ex:
        futs = [
            ex.submit(_scan_one_stock_for_signals, s, strategy_func, threshold,
                      start_ts, end_ts, ext_start, ext_end, rate_cols_all)
            for s in stocks
        ]
        done = 0
        for fut in as_completed(futs):
            done += 1
            try:
                rows = fut.result()
                if rows:
                    results.extend(rows)
            except Exception:
                pass
            if done % 50 == 0:
                logging.info(
                    f"[signal-fallback] 已扫描 {done}/{total}，累计信号 {len(results)} 条"
                )

    logging.info(
        f"[signal-fallback] 扫描完成：{strategy_table} 区间 {start_date}~{end_date}，"
        f"共 {len(results)} 条信号"
    )
    if not results:
        return None
    df = pd.DataFrame(results)
    _save_signal_cache_file(cache_path, df)
    return df


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
        # 非重叠采样：相邻样本完全独立，避免重叠窗口造成的高度
        # 自相关 → std 严重低估 → sharpe 被放大、win_rate 接近 100%。
        # 仅当样本数 >= 3 时才统计 sharpe / sortino，避免极端值。
        sampled = nav[::d]
        if len(sampled) < 2:
            # 数据窗口短于持仓周期，无法形成完整周期 → 跳过
            continue
        rates = (sampled[1:] / sampled[:-1] - 1) * 100
        rates = rates[np.isfinite(rates)]
        if len(rates) == 0:
            continue

        avg_ret = float(rates.mean())
        std_ret = float(rates.std(ddof=1)) if len(rates) > 1 else 0.0
        # 样本数 < 3 时 std 不可靠，sharpe / sortino 置 None
        if len(rates) < 3:
            sharpe = None
            sortino = None
        else:
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


def _collect_custom_buy_trades(strategy_id, start_date, end_date, benchmark):
    """从内存中正在运行/已完成的自定义对比任务 或 持久化的回测结果中收集 buy 交易。

    优先使用内存中最近完成的任务（用户刚刚跑过 verify/compare 才能保证一致性），
    fallback 到 cn_stock_backtest_portfolio 表中覆盖该区间的已完成回测。
    返回 [{date, code, price}, ...] 列表（按日期升序）。
    """
    trades = []
    for task in (_CUSTOM_COMPARE_TASKS.values() if _CUSTOM_COMPARE_TASKS else []):
        if task.get('status') != 'completed':
            continue
        ck = task.get('cache_key')
        raw = task.get('raw_result')
        if not ck or not raw or not isinstance(raw, dict):
            continue
        try:
            if int(ck[0]) != int(strategy_id):
                continue
        except (TypeError, ValueError):
            continue
        if str(task.get('start_date')) > str(start_date) or str(task.get('end_date')) < str(end_date):
            # 区间不完全覆盖也接受（兼容用户改窄区间）
            pass
        trades = raw.get('trades', []) or []
        if trades:
            break

    if not trades:
        result, _ = _load_cached_custom_backtest(strategy_id, start_date, end_date, benchmark)
        trades = (result or {}).get('trades', []) if result else []

    out = []
    s_str = str(start_date)
    e_str = str(end_date)
    for t in trades or []:
        if t.get('direction') != 'buy':
            continue
        date_str = str(t.get('date', ''))
        if not date_str or date_str < s_str or date_str > e_str:
            continue
        try:
            price = float(t.get('price', 0) or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        code = str(t.get('code', '') or '').strip()
        if not code:
            continue
        out.append({'date': date_str, 'code': code, 'price': price})
    out.sort(key=lambda x: x['date'])
    return out


def _build_custom_trade_rate_matrix(buy_trades, max_hold):
    """逐笔买入事件 + 后续 K 线 → (N, max_hold) 收益矩阵。

    单只股票的全量 K 线只读取一次（缓存在本函数内），避免重复 IO。
    返回 numpy.ndarray，dtype=float64，单位为百分比。
    """
    if not buy_trades or max_hold <= 0:
        return np.zeros((0, max_hold), dtype=float)

    hist_cache = {}
    rows = []
    for tr in buy_trades:
        code = tr['code']
        if code not in hist_cache:
            try:
                # 给 read_stock_hist_from_cache 传宽区间，让其返回完整缓存。
                hist = stf.read_stock_hist_from_cache(code, '19900101', '20991231')
            except Exception:
                hist = None
            if hist is not None and len(hist) > 0:
                try:
                    if not pd.api.types.is_datetime64_any_dtype(hist['date']):
                        hist = hist.copy()
                        hist['date'] = pd.to_datetime(hist['date'])
                except Exception:
                    hist = None
            hist_cache[code] = hist
        hist = hist_cache[code]
        if hist is None or len(hist) == 0 or 'close' not in getattr(hist, 'columns', []):
            continue

        target_ts = pd.Timestamp(tr['date'])
        date_arr = hist['date'].values
        idxs = np.where(date_arr >= np.datetime64(target_ts))[0]
        if len(idxs) == 0:
            continue
        idx = int(idxs[0])
        buy_price = float(tr['price'])
        closes = hist['close'].values
        rate_row = np.full(max_hold, np.nan)
        for d in range(1, max_hold + 1):
            fwd = idx + d
            if fwd >= len(closes):
                break
            try:
                close_v = float(closes[fwd])
                if close_v > 0 and buy_price > 0:
                    rate_row[d - 1] = (close_v - buy_price) / buy_price * 100
            except (TypeError, ValueError):
                continue
        if np.isfinite(rate_row).any():
            rows.append(rate_row)

    if not rows:
        return np.zeros((0, max_hold), dtype=float)
    return np.vstack(rows)


# 自动回测的内存级 single-flight 锁，避免同一策略短时间内并发触发多次回测。
_AUTO_BACKTEST_INFLIGHT = {}


def _auto_run_custom_backtest(strategy_id, start_date, end_date,
                              benchmark='000300', initial_cash=1000000):
    """同步运行一次自定义策略回测，结果落 `cn_stock_backtest_portfolio` 并返回。

    被 `_build_custom_strategy_dataframe(auto_run=True)` 调用：当区间内既无内存
    任务也无 DB 缓存命中时，避免直接对前端报"无可复用回测"。仅复用 DB 中已存的
    `cn_stock_strategy_code.code`，不接受外部代码注入。

    Returns:
      (trades, error_msg)。trades 为买入交易列表，与 _collect_custom_buy_trades
      同构；失败时 trades 为空、error_msg 描述原因。
    """
    try:
        rows = mdb.executeSqlFetch(
            "SELECT name, code FROM cn_stock_strategy_code WHERE id=%s AND "
            "(status IS NULL OR status != 'archived')", (strategy_id,))
    except Exception as exc:
        logging.error("读取自定义策略代码异常: id=%s", strategy_id, exc_info=True)
        return [], f'无法读取自定义策略代码: {exc}'
    if not rows:
        return [], f'自定义策略 #{strategy_id} 不存在或已归档'
    strategy_name, strategy_code = rows[0][0] or '', rows[0][1] or ''
    if not strategy_code or len(strategy_code) < 16:
        return [], f'自定义策略 #{strategy_id} 缺失策略代码'

    # 同一策略 + 同一区间，多个请求并发时只跑一次
    lock_key = (int(strategy_id), str(start_date), str(end_date), str(benchmark))
    if _AUTO_BACKTEST_INFLIGHT.get(lock_key):
        return [], '该策略正在回测中，请稍后再试'
    _AUTO_BACKTEST_INFLIGHT[lock_key] = True

    try:
        from quantia.core.backtest.portfolio_engine import PortfolioBacktestEngine
        engine = PortfolioBacktestEngine()
        logging.info(
            "[auto-backtest] strategy_id=%s name=%s window=%s~%s",
            strategy_id, strategy_name, start_date, end_date)
        result = engine.run(
            strategy_code, str(start_date), str(end_date),
            initial_cash=initial_cash, benchmark=str(benchmark or '000300'))
    except Exception as exc:
        logging.error("[auto-backtest] 引擎运行异常: id=%s", strategy_id, exc_info=True)
        _AUTO_BACKTEST_INFLIGHT.pop(lock_key, None)
        return [], f'自动回测失败: {exc}'

    try:
        if not isinstance(result, dict) or result.get('status') != 'completed':
            msg = (result or {}).get('message') if isinstance(result, dict) else None
            return [], f'自动回测未完成: {msg or "unknown"}'
        # 持久化（与 RunPortfolioBacktestHandler 一致），方便下次直接命中缓存。
        try:
            import quantia.web.portfolioBacktestHandler as pbh
            try:
                pbh._ensure_backtest_table()
            except Exception:
                logging.debug("_ensure_backtest_table 跳过", exc_info=True)
            m = result.get('metrics', {}) or {}
            now = datetime.datetime.now()
            snapshot = dict(result)
            snapshot['strategy_code_snapshot'] = strategy_code
            mdb.executeSql(
                'INSERT INTO cn_stock_backtest_portfolio '
                '(strategy_id, strategy_name, start_date, end_date, initial_cash, status, '
                'started_at, completed_at, total_return, annual_return, '
                'max_drawdown, sharpe_ratio, alpha, beta, win_rate, trade_count, '
                'benchmark, result_json) '
                'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (strategy_id, strategy_name or None, str(start_date), str(end_date),
                 initial_cash, 'completed', now, now,
                 m.get('total_return'), m.get('annual_return'),
                 m.get('max_drawdown'), m.get('sharpe_ratio'),
                 m.get('alpha'), m.get('beta'),
                 m.get('daily_win_rate'), m.get('trade_count'),
                 str(benchmark or '000300'),
                 json.dumps(snapshot, ensure_ascii=False, default=str)))
        except Exception as exc:
            logging.warning("[auto-backtest] 结果入库失败（不影响本次返回）: %s", exc)

        trades = []
        s_str, e_str = str(start_date), str(end_date)
        for t in result.get('trades', []) or []:
            if t.get('direction') != 'buy':
                continue
            d = str(t.get('date', ''))
            if not d or d < s_str or d > e_str:
                continue
            try:
                price = float(t.get('price', 0) or 0)
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            code = str(t.get('code', '') or '').strip()
            if not code:
                continue
            trades.append({'date': d, 'code': code, 'price': price})
        trades.sort(key=lambda x: x['date'])
        return trades, None
    finally:
        _AUTO_BACKTEST_INFLIGHT.pop(lock_key, None)


def _build_custom_strategy_dataframe(strategy_key, start_date, end_date,
                                     max_hold, benchmark='000300',
                                     auto_run=False):
    """把自定义策略的逐笔 buy 交易 + 后续 K 线收益拼成与 `_load_backtest_data`
    完全同构的 DataFrame，供 6 个 verify-optimize handler 直接复用其后段分析逻辑。

    Args:
      auto_run: 当内存任务 / DB 缓存均无 buy 记录时，是否自动调用
                `_auto_run_custom_backtest` 跑一次。默认 False 以保持旧行为；
                因子实验室 / 部分前端入口可显式打开。

    Returns:
      (df, total_trades, error_msg)

      df: 列 [date, code, name, rate_1, rate_2, ..., rate_{max_hold}]；
          rate_* 单位为百分比；K 线缺失/未来日期 → NaN（与 DB 路径一致）。
          找不到任何可用 buy 交易时返回 (None, 0, message)；
          有 buy 但 K 线全部缺失时返回 (empty-df, len(trades), kline_message)。

    备注：max_hold 上限不再被 RATE_FIELDS_COUNT 限制，调用方负责
    传入合理值；helper 不会调用任何外部 API（仅读 cache/hist/）。
    """
    strategy_key = (strategy_key or '').strip()
    if not strategy_key.startswith('custom_'):
        return None, 0, '此接口仅支持自定义策略 (custom_*)'
    try:
        strategy_id = int(strategy_key.replace('custom_', ''))
    except ValueError:
        return None, 0, '无效的策略ID'

    if max_hold <= 0:
        return None, 0, 'max_hold 必须为正整数'

    trades = _collect_custom_buy_trades(strategy_id, start_date, end_date, benchmark)
    if not trades and auto_run:
        new_trades, auto_err = _auto_run_custom_backtest(
            strategy_id, start_date, end_date, benchmark)
        if new_trades:
            trades = new_trades
        elif auto_err:
            return None, 0, f'当前自定义策略在该区间无买入记录，已尝试自动回测但失败：{auto_err}'
    if not trades:
        return None, 0, '当前自定义策略在该区间无可复用回测或买入记录，请先运行组合回测/策略对比'

    # 单遍 K 线缓存扫描 + 行级 forward 收益 → 与 _build_custom_trade_rate_matrix
    # 完全等价，但同时保留 (date, code) 元信息。
    hist_cache = {}
    keep_dates = []
    keep_codes = []
    keep_rows = []
    for tr in trades:
        code = str(tr.get('code') or '').strip()
        if not code:
            continue
        if code not in hist_cache:
            try:
                hist = stf.read_stock_hist_from_cache(code, '19900101', '20991231')
            except Exception:
                hist = None
            if hist is not None and len(hist) > 0:
                try:
                    if not pd.api.types.is_datetime64_any_dtype(hist['date']):
                        hist = hist.copy()
                        hist['date'] = pd.to_datetime(hist['date'])
                except Exception:
                    hist = None
            hist_cache[code] = hist
        hist = hist_cache[code]
        if hist is None or len(hist) == 0 or 'close' not in getattr(hist, 'columns', []):
            continue

        target_ts = pd.Timestamp(tr['date'])
        date_arr = hist['date'].values
        idxs = np.where(date_arr >= np.datetime64(target_ts))[0]
        if len(idxs) == 0:
            continue
        idx = int(idxs[0])
        try:
            buy_price = float(tr.get('price') or 0)
        except (TypeError, ValueError):
            continue
        if buy_price <= 0:
            continue
        closes = hist['close'].values
        rate_row = np.full(max_hold, np.nan, dtype=np.float64)
        for d in range(1, max_hold + 1):
            fwd = idx + d
            if fwd >= len(closes):
                break
            try:
                close_v = float(closes[fwd])
                if close_v > 0:
                    rate_row[d - 1] = (close_v - buy_price) / buy_price * 100
            except (TypeError, ValueError):
                continue
        if not np.isfinite(rate_row).any():
            continue
        keep_dates.append(str(tr['date']))
        keep_codes.append(code)
        keep_rows.append(rate_row)

    if not keep_rows:
        return pd.DataFrame(), len(trades), '逐笔 K 线缓存不足，无法构建收益序列'

    rate_cols = [f'rate_{d}' for d in range(1, max_hold + 1)]
    df = pd.DataFrame(np.vstack(keep_rows), columns=rate_cols)
    df.insert(0, 'name', '')
    df.insert(0, 'code', keep_codes)
    df.insert(0, 'date', pd.to_datetime(keep_dates))
    return df, len(trades), None


def _build_custom_compare_payload(strategy_key, strategy_name, start_date, end_date, result, data_source, holding_days_list=None):
    """把自定义策略回测结果转换为策略对比页统一响应。

    holding_days_list: 用户在前端勾选的持仓天数；不传时回退到 [5,10,20]
    （历史默认），上限受 MAX_HOLDING_DAYS_EXTENDED 控制（在调用端校验）。
    """
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
    days_list = holding_days_list or [5, 10, 20]
    analysis, best_holding_days, best_sharpe = _calc_rolling_nav_analysis(
        nav_series, days_list, trade_count=trade_count)
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
                               commission, tax, slippage, cache_key=None,
                               holding_days_list=None):
    """启动自定义策略对比后台任务，避免单个 HTTP 请求等待长回测。

    holding_days_list 仅作为首次构建 payload 的默认值；任务完成后会保留原始
    回测结果，后续轮询请求可携带新的 holding_days 重新计算分析。
    """
    task_id = str(uuid.uuid4())[:8]
    _CUSTOM_COMPARE_TASKS[task_id] = {
        'status': 'running',
        'strategy': strategy_key,
        'strategy_cn': strategy_name,
        'start_date': str(start_date),
        'end_date': str(end_date),
        'period': f'{start_date} ~ {end_date}',
        'cache_key': cache_key,
        'result': None,
        'raw_result': None,
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
                result, 'portfolio_engine_live',
                holding_days_list=holding_days_list)
            task = _CUSTOM_COMPARE_TASKS.get(task_id)
            if task is not None:
                task['status'] = payload.get('status') or 'completed'
                task['result'] = payload
                task['raw_result'] = result if payload.get('status') == 'completed' else None
                task['data_source'] = 'portfolio_engine_live'
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


def _custom_compare_task_payload(task_id, holding_days_list=None):
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
    raw = task.get('raw_result')
    if raw is not None and holding_days_list:
        payload = _build_custom_compare_payload(
            task.get('strategy'), task.get('strategy_cn'),
            task.get('start_date'), task.get('end_date'),
            raw, task.get('data_source') or 'portfolio_engine_live',
            holding_days_list=holding_days_list)
        payload['task_id'] = task_id
        return payload
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
        strategy_arg = self.get_argument('strategy', default='', strip=True)
        if strategy_arg.startswith('custom_'):
            self._handle_custom(strategy_arg)
            return

        meta, start_date, end_date, err = _parse_common_args(self)
        if err:
            _write_error(self, err)
            return

        # 可选参数: 指定持仓天数列表
        days_arg = self.get_argument('holding_days', default='', strip=True)
        if days_arg:
            holding_days_list = _parse_int_list(
                days_arg,
                min_value=1,
                max_value=MAX_HOLDING_DAYS_EXTENDED,
                max_items=30,
            )
        else:
            # 短/中/长三档默认：1d~3w 短期，1~3 个月中期，6 个月~1 年长期
            holding_days_list = [1, 3, 5, 10, 20, 40, 60, 120, 180, 240]

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

        self._run_holding_analysis(df, meta['table'], meta['cn'],
                                   start_date, end_date, holding_days_list)

    def _handle_custom(self, strategy_key):
        """自定义策略持仓扫描：从已完成的回测/对比任务收集 buy 交易 + 后续 K 线
        forward 收益，构造 (date, code, rate_*) DataFrame 后复用同一分析逻辑。"""
        strategy_key, strategy_id, start_date, end_date, err = _parse_custom_strategy_args(self)
        if err:
            _write_error(self, err)
            return

        days_arg = self.get_argument('holding_days', default='', strip=True)
        if days_arg:
            holding_days_list = _parse_int_list(
                days_arg,
                min_value=1,
                max_value=MAX_HOLDING_DAYS_EXTENDED,
                max_items=30,
            )
        else:
            holding_days_list = [1, 3, 5, 10, 20, 40, 60, 120, 180, 240]
        if not holding_days_list:
            _write_error(self, 'holding_days 参数无效')
            return

        max_hold = max(holding_days_list)
        benchmark = self.get_argument('benchmark', default='000300', strip=True) or '000300'
        df, total_trades, build_err = _build_custom_strategy_dataframe(
            strategy_key, start_date, end_date, max_hold, benchmark)
        if build_err and (df is None or len(df) == 0):
            _write_json(self, {
                'strategy': strategy_key,
                'strategy_cn': '自定义策略',
                'period': f'{start_date} ~ {end_date}',
                'total_signals': int(total_trades or 0),
                'analysis': [],
                'message': build_err,
                'data_source': 'custom_trades+kline',
            })
            return

        self._run_holding_analysis(df, strategy_key, '自定义策略',
                                   start_date, end_date, holding_days_list,
                                   data_source='custom_trades+kline')

    def _run_holding_analysis(self, df, label, cn, start_date, end_date,
                              holding_days_list, data_source=None):
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

        payload = {
            'strategy': label,
            'strategy_cn': cn,
            'period': f'{start_date} ~ {end_date}',
            'total_signals': total_signals,
            'analysis': analysis,
            'best_holding_days': best_holding_days,
            'best_sharpe': _safe_float(best_sharpe),
        }
        if data_source:
            payload['data_source'] = data_source
        _write_json(self, payload)


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
        # 解析持仓天数（与内建策略保持一致），允许在轮询时携带以重新计算
        days_arg = self.get_argument('holding_days', default='', strip=True)
        if days_arg:
            holding_days_list = _parse_int_list(
                days_arg,
                min_value=1,
                max_value=MAX_HOLDING_DAYS_EXTENDED,
                max_items=30,
            ) or [5, 10, 20]
        else:
            holding_days_list = [5, 10, 20]

        task_id = self.get_argument('task_id', default='', strip=True)
        if task_id:
            _write_json(self, _custom_compare_task_payload(task_id, holding_days_list=holding_days_list))
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
                payload = _custom_compare_task_payload(reusable_task_id, holding_days_list=holding_days_list)
                payload['cache_hit'] = True
                payload['message'] = payload.get('message') or '已复用同参数分析任务'
                _write_json(self, payload)
                return

            task_id = _start_custom_compare_task(
                strategy_key, strategy_id, strategy_name or f'策略#{strategy_id}', strategy_code,
                start_date, end_date, initial_cash, benchmark,
                commission, tax, slippage, cache_key=cache_key,
                holding_days_list=holding_days_list)
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
            strategy_key, strategy_name, start_date, end_date, result, data_source,
            holding_days_list=holding_days_list)
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
# 注：仅保留 calculate_indicator.get_indicators 实际产出的列 + hist 原生 close/volume。
# turnover/amount 等需要 cn_stock_hist_data 维度的字段被有意排除，避免兜底路径静默 0 结果。
_SIGNAL_QUALITY_INDICATORS = {
    'rsi_6', 'rsi_12', 'kdjk', 'kdjd', 'kdjj',
    'macd', 'macds', 'macdh',
    'cr', 'cci', 'atr',
    'close', 'volume',
}


def _signal_quality_cache_path(strategy_table, indicator, holding_days, start_date, end_date) -> str:
    if not os.path.exists(_SIGNAL_CACHE_DIR):
        try:
            os.makedirs(_SIGNAL_CACHE_DIR, exist_ok=True)
        except Exception:
            pass
    safe_ind = str(indicator).replace('/', '_').replace('\\', '_')
    return os.path.join(
        _SIGNAL_CACHE_DIR,
        f"quality_{strategy_table}_{safe_ind}_hd{int(holding_days)}_{start_date}_{end_date}.gzip.pickle",
    )


def _build_signal_quality_fallback(strategy_table, indicator, holding_days, start_date, end_date):
    """信号诊断兜底：当 cn_stock_indicators JOIN 无数据时，
    走 K 线缓存：先用 _load_backtest_data 取该 rate_N 的信号集（自带 K 线回退），
    再为每个涉及的股票单次 get_indicators，按 (date, code) 查出指标值。

    结果写盘到 cache/signal/quality_<table>_<ind>_hd<N>_<start>_<end>.gzip.pickle，
    后续命中直接读盘（同 _compute_signals_from_kline_cache 的策略）。

    Returns: DataFrame[date, code, rate, ind_val] 或 None。
    """
    # 1) 命中文件缓存
    cache_path = _signal_quality_cache_path(strategy_table, indicator, holding_days, start_date, end_date)
    if os.path.exists(cache_path):
        try:
            cached = pd.read_pickle(cache_path, compression='gzip')
            if cached is not None and not cached.empty:
                logging.info(
                    f"[signal-quality] 命中缓存 {cache_path}: {len(cached)} rows"
                )
                return cached
        except Exception as exc:
            logging.warning(f"[signal-quality] 读缓存失败 {cache_path}: {exc}")

    rate_col = f'rate_{holding_days}'
    base = _load_backtest_data(strategy_table, start_date, end_date, [rate_col])
    if base is None or base.empty:
        return None
    if rate_col not in base.columns:
        return None

    base = base[['date', 'code', rate_col]].rename(columns={rate_col: 'rate'})
    base = base.dropna(subset=['rate'])
    if base.empty:
        return None

    # 统一为 Timestamp 便于查找
    base['date'] = pd.to_datetime(base['date'])

    # 计算 K 线读取范围：往前留 _FALLBACK_HIST_BUFFER_DAYS 给指标窗口
    earliest = base['date'].min()
    latest = base['date'].max()
    ext_start = (earliest - datetime.timedelta(days=_FALLBACK_HIST_BUFFER_DAYS)).strftime('%Y%m%d')
    ext_end = (latest + datetime.timedelta(days=5)).strftime('%Y%m%d')

    results = []
    skipped_read = 0
    skipped_calc = 0
    for code, grp in base.groupby('code'):
        try:
            hist = stf.read_stock_hist_from_cache(code, ext_start, ext_end)
        except Exception as exc:
            skipped_read += 1
            logging.debug(f"[signal-quality] read_hist 失败 code={code}: {exc}")
            continue
        if hist is None or hist.empty:
            continue
        try:
            ind_df = idr.get_indicators(hist, end_date=latest, threshold=120)
        except Exception as exc:
            skipped_calc += 1
            logging.debug(f"[signal-quality] get_indicators 失败 code={code}: {exc}")
            continue
        if ind_df is None or ind_df.empty or indicator not in ind_df.columns:
            continue
        if not pd.api.types.is_datetime64_any_dtype(ind_df['date']):
            ind_df = ind_df.copy()
            ind_df['date'] = pd.to_datetime(ind_df['date'])
        # 去重保护：缓存极少数情况下可能存在同一日期重复行
        ind_df = ind_df.drop_duplicates(subset=['date'], keep='last')
        # 向量化合并替代 iterrows，性能与正确性更稳
        ind_lookup = ind_df[['date', indicator]].rename(columns={indicator: 'ind_val'})
        merged = grp.merge(ind_lookup, on='date', how='left')
        merged = merged.dropna(subset=['ind_val'])
        # 过滤 inf
        merged = merged[~merged['ind_val'].isin([float('inf'), float('-inf')])]
        if merged.empty:
            continue
        merged['date_str'] = merged['date'].dt.strftime('%Y-%m-%d')
        for _, row in merged.iterrows():
            results.append({
                'date': row['date_str'],
                'code': code,
                'rate': float(row['rate']),
                'ind_val': float(row['ind_val']),
            })

    if skipped_read or skipped_calc:
        logging.info(
            f"[signal-quality] 兜底跳过：read={skipped_read} calc={skipped_calc}"
        )

    if not results:
        return None
    out = pd.DataFrame(results)
    # 2) 写文件缓存（失败不影响主流程）
    try:
        out.to_pickle(cache_path, compression='gzip')
        logging.info(f"[signal-quality] 写缓存 {cache_path}: {len(out)} rows")
    except Exception as exc:
        logging.warning(f"[signal-quality] 写缓存失败 {cache_path}: {exc}")
    return out


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
        strategy_arg = self.get_argument('strategy', default='', strip=True)
        if strategy_arg.startswith('custom_'):
            self._handle_custom(strategy_arg)
            return

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

        df = None
        indicators_table = tbs.TABLE_CN_STOCK_INDICATORS['name']
        # 仅当两表都存在时尝试 JOIN；否则直接走 K 线兜底
        if mdb.checkTableIsExist(strategy_table) and mdb.checkTableIsExist(indicators_table):
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
                df = None

        used_fallback = False
        if df is None or len(df) == 0:
            # DB JOIN 无数据 → 走 K 线兜底：用信号 fallback 缓存 + 临时算指标
            logging.info(
                f"[signal-quality] DB JOIN 空 → K 线兜底 strategy={strategy_table}, "
                f"indicator={indicator}, hd={holding_days}, {start_date}~{end_date}"
            )
            df = _build_signal_quality_fallback(
                strategy_table, indicator, holding_days, start_date, end_date)
            used_fallback = df is not None and not df.empty

        if df is None or len(df) == 0:
            _write_json(self, {
                'strategy': meta['table'],
                'indicator': indicator,
                'holding_days': holding_days,
                'buckets': [],
                'message': '该时间范围内无匹配数据',
            })
            return

        self._write_buckets(df, meta['table'], meta['cn'], indicator, holding_days,
                            buckets_arg, data_source='kline_fallback' if used_fallback else 'db')

    def _handle_custom(self, strategy_key):
        strategy_key, strategy_id, start_date, end_date, err = _parse_custom_strategy_args(self)
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

        buckets_arg = self.get_argument('buckets', default='', strip=True)
        benchmark = self.get_argument('benchmark', default='000300', strip=True) or '000300'

        rate_df, total_trades, build_err = _build_custom_strategy_dataframe(
            strategy_key, start_date, end_date, holding_days, benchmark)
        if build_err and (rate_df is None or len(rate_df) == 0):
            _write_json(self, {
                'strategy': strategy_key,
                'strategy_cn': '自定义策略',
                'indicator': indicator,
                'holding_days': holding_days,
                'buckets': [],
                'message': build_err,
                'data_source': 'custom_trades+kline',
            })
            return

        rate_col = f'rate_{holding_days}'
        rate_df = rate_df.copy()
        rate_df['date_str'] = pd.to_datetime(rate_df['date']).dt.strftime('%Y-%m-%d')

        # 从 cn_stock_indicators 拉取 (date, code) → indicator 值
        indicators_table = tbs.TABLE_CN_STOCK_INDICATORS['name']
        ind_map = {}
        if mdb.checkTableIsExist(indicators_table):
            try:
                sql = (
                    f"SELECT `date`, `code`, `{indicator}` AS ind_val "
                    f"FROM `{indicators_table}` "
                    f"WHERE `date` >= %s AND `date` <= %s "
                    f"AND `{indicator}` IS NOT NULL"
                )
                ind_df = pd.read_sql(sql, con=mdb.engine(),
                                     params=(str(start_date), str(end_date)))
                if ind_df is not None and len(ind_df) > 0:
                    ind_df['date'] = pd.to_datetime(ind_df['date']).dt.strftime('%Y-%m-%d')
                    ind_map = {(r['date'], str(r['code'])): r['ind_val']
                               for _, r in ind_df.iterrows()}
            except Exception:
                logging.warning("[signal-quality custom] 查询指标失败", exc_info=True)

        rate_df['ind_val'] = rate_df.apply(
            lambda r: ind_map.get((r['date_str'], str(r['code']))), axis=1)
        rate_df = rate_df.rename(columns={rate_col: 'rate'})
        merged = rate_df.dropna(subset=['rate', 'ind_val'])[['date', 'code', 'rate', 'ind_val']]
        if len(merged) == 0:
            _write_json(self, {
                'strategy': strategy_key,
                'strategy_cn': '自定义策略',
                'indicator': indicator,
                'holding_days': holding_days,
                'buckets': [],
                'message': f'自定义策略在该区间无法匹配 {indicator} 指标值（cn_stock_indicators 缺失或买入日缺指标）',
                'data_source': 'custom_trades+kline',
            })
            return

        self._write_buckets(merged, strategy_key, '自定义策略', indicator, holding_days,
                            buckets_arg, data_source='custom_trades+indicators')

    def _write_buckets(self, df, label, cn, indicator, holding_days, buckets_arg,
                       data_source=None):
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
            # 自动四分位分桶；当指标值高度集中导致分位点重复时（如 RSI 极端区
            # 间），需要去重后再切桶，避免出现 (x, x) 的空桶被跳过 → 表格只
            # 显示部分桶的现象。
            q_raw = df['ind_val'].quantile([0, 0.25, 0.5, 0.75, 1.0]).values
            q_unique = sorted(set(float(v) for v in q_raw if np.isfinite(v)))
            if len(q_unique) >= 2:
                bucket_ranges = [(q_unique[i], q_unique[i + 1]) for i in range(len(q_unique) - 1)]
            else:
                vmin = float(df['ind_val'].min())
                vmax = float(df['ind_val'].max())
                bucket_ranges = [(vmin, vmax)] if np.isfinite(vmin) and np.isfinite(vmax) else []

        buckets_result = []
        for lo, hi in bucket_ranges:
            mask = (df['ind_val'] >= lo) & (df['ind_val'] < hi)
            # 最后一个桶包含上界
            if (lo, hi) == bucket_ranges[-1]:
                mask = (df['ind_val'] >= lo) & (df['ind_val'] <= hi)
            subset = df.loc[mask, 'rate'].values

            if len(subset) == 0:
                # 始终输出该桶占位，避免前端表格"只有部分数据"的错觉
                buckets_result.append({
                    'range': f'{lo:.1f}-{hi:.1f}',
                    'range_lo': _safe_float(lo),
                    'range_hi': _safe_float(hi),
                    'signal_count': 0,
                    'pct': 0.0,
                    'avg_return': None,
                    'win_rate': None,
                    'sharpe': None,
                    'quality': 'no_data',
                })
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

        # 生成过滤建议: 标记 quality=filter 的区间（no_data 桶不参与统计）
        filter_ranges = [b['range'] for b in buckets_result if b['quality'] == 'filter']
        golden_ranges = [b['range'] for b in buckets_result if b['quality'] == 'golden']

        # 计算过滤后的预期提升
        expected_improvement = {}
        if filter_ranges:
            kept = [b for b in buckets_result if b['quality'] not in ('filter', 'no_data') and b['signal_count'] > 0]
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
            'strategy': label,
            'strategy_cn': cn,
            'indicator': indicator,
            'holding_days': holding_days,
            'total_signals': len(df),
            'buckets': buckets_result,
            'recommendation': {
                'filter_ranges': filter_ranges,
                'golden_ranges': golden_ranges,
                'expected_improvement': expected_improvement,
            },
            'data_source': data_source or 'db',
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
        strategy_arg = self.get_argument('strategy', default='', strip=True)
        is_custom = strategy_arg.startswith('custom_')

        if is_custom:
            self._handle_custom(strategy_arg)
            return

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
        # 注意：当 max_hold > 当前 RATE_FIELDS_COUNT 实际有数据的列数时（例如用户
        # 把 max_hold_days 调到极大值），尾部 rate_* 列可能全为 NULL，pandas 会把
        # 它们推断成 object dtype，后续 np.isfinite 会抛 TypeError。这里强制
        # 转 float64，None/字符串 → NaN，与下游 NaN 处理路径一致。
        rate_df = df[rate_cols].copy()
        rates_matrix = np.asarray(rate_df.values, dtype=np.float64)  # (N, max_hold)

        matrix, best_combo = self._scan_sl_tp_grid(rates_matrix, sl_levels, tp_levels, max_hold)

        _write_json(self, {
            'strategy': meta['table'],
            'strategy_cn': meta['cn'],
            'period': f'{start_date} ~ {end_date}',
            'max_hold_days': max_hold,
            'total_signals': len(df),
            'matrix': matrix,
            'best_combo': best_combo,
        })

    def _handle_custom(self, strategy_key):
        """自定义策略 SL/TP 矩阵：基于回测的 buy 交易 + K 线缓存逐笔模拟。"""
        strategy_key, strategy_id, start_date, end_date, err = _parse_custom_strategy_args(self)
        if err:
            _write_error(self, err)
            return

        sl_arg = self.get_argument('sl_range', default='-2,-3,-5,-8,-10', strip=True)
        tp_arg = self.get_argument('tp_range', default='3,5,8,10,15', strip=True)
        max_hold_arg = self.get_argument('max_hold_days', default='20', strip=True)
        benchmark = self.get_argument('benchmark', default='000300', strip=True) or '000300'

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

        trades = _collect_custom_buy_trades(strategy_id, start_date, end_date, benchmark)
        if not trades:
            _write_json(self, {
                'strategy': strategy_key,
                'max_hold_days': max_hold,
                'matrix': [],
                'total_signals': 0,
                'message': '当前自定义策略在该区间无可复用回测或买入记录，请先运行组合回测/策略对比',
            })
            return

        rates_matrix = _build_custom_trade_rate_matrix(trades, max_hold)
        if rates_matrix.shape[0] == 0:
            _write_json(self, {
                'strategy': strategy_key,
                'max_hold_days': max_hold,
                'matrix': [],
                'total_signals': 0,
                'message': '逐笔 K 线缓存不足，无法计算止盈止损矩阵',
            })
            return

        matrix, best_combo = self._scan_sl_tp_grid(rates_matrix, sl_levels, tp_levels, max_hold)
        _write_json(self, {
            'strategy': strategy_key,
            'period': f'{start_date} ~ {end_date}',
            'max_hold_days': max_hold,
            'total_signals': int(rates_matrix.shape[0]),
            'matrix': matrix,
            'best_combo': best_combo,
            'data_source': 'custom_trades+kline',
        })

    @classmethod
    def _scan_sl_tp_grid(cls, rates_matrix, sl_levels, tp_levels, max_hold):
        matrix = []
        best_sharpe = None
        best_combo = None
        for sl in sl_levels:
            for tp in tp_levels:
                final_rates = cls._simulate_sl_tp(rates_matrix, sl, tp, max_hold)
                valid = final_rates[np.isfinite(final_rates)]
                if len(valid) == 0:
                    continue

                avg_ret = float(valid.mean())
                std_ret = float(valid.std(ddof=1)) if len(valid) > 1 else 0.0
                win_rate = float((valid > 0).mean() * 100)
                sharpe = _calc_annualized_sharpe(valid, max_hold)

                sl_hit, tp_hit, expired = cls._count_exits(rates_matrix, sl, tp, max_hold)

                matrix.append({
                    'stop_loss': sl,
                    'take_profit': tp,
                    'sharpe': _safe_float(sharpe),
                    'avg_return': _safe_float(avg_ret),
                    'win_rate': _safe_float(win_rate),
                    'return_std': _safe_float(std_ret),
                    'avg_hold_days': _safe_float(cls._avg_hold_days(rates_matrix, sl, tp, max_hold)),
                    'trades_hit_sl': int(sl_hit),
                    'trades_hit_tp': int(tp_hit),
                    'trades_expired': int(expired),
                    'total_trades': int(len(valid)),
                })

                if sharpe is not None and (best_sharpe is None or sharpe > best_sharpe):
                    best_sharpe = sharpe
                    best_combo = {'stop_loss': sl, 'take_profit': tp, 'sharpe': _safe_float(sharpe)}
        return matrix, best_combo

    @staticmethod
    def _simulate_sl_tp(rates_matrix, sl, tp, max_hold):
        """向量化模拟止盈止损。

        rates_matrix: (N, max_hold), 每列为 rate_1..rate_max_hold
        返回: 1-D array (N,) 每笔交易的最终收益。
        """
        n_trades = rates_matrix.shape[0]
        # 显式转 float64：DB 返回的 rate 列可能因全 NULL 而被 pandas 推断为
        # object dtype，会让 np.isfinite 抛 TypeError。先转 float（None/字符串
        # → NaN），再做后续矩阵运算。
        mat = np.array(rates_matrix[:, :max_hold], dtype=np.float64, copy=True)

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
        strategy_arg = self.get_argument('strategy', default='', strip=True)
        is_custom = strategy_arg.startswith('custom_')

        benchmark = self.get_argument('benchmark', default='000300', strip=True).strip() or '000300'
        holding_days_arg = self.get_argument('holding_days', default='5', strip=True)
        try:
            holding_days = max(1, min(int(holding_days_arg), RATE_FIELDS_COUNT))
        except (TypeError, ValueError):
            holding_days = 5

        if is_custom:
            strategy_key, strategy_id, start_date, end_date, err = _parse_custom_strategy_args(self)
            if err:
                _write_error(self, err)
                return
            label, cn = strategy_key, '自定义策略'
        else:
            meta, start_date, end_date, err = _parse_common_args(self)
            if err:
                _write_error(self, err)
                return
            label, cn = meta['table'], meta['cn']

        # 加载基准指数数据 (从缓存/DB，不调用外部 API)
        from quantia.core.backtest.data_feed import load_benchmark_data
        # 需要额外前置 60 日用于 MA60 计算
        extended_start = start_date - datetime.timedelta(days=90)
        bench_df = load_benchmark_data(benchmark, str(extended_start), str(end_date))
        if bench_df is None or len(bench_df) == 0:
            # 基准在该区间无数据（常见于未来日期/极冷门指数）→ 返回 200 + 空结
            # 果，避免前端把 400 当成"配置错误"。日志保留以便排查缓存问题。
            logging.info(
                "market_regime: 基准 %s 在 %s ~ %s 无数据",
                benchmark, start_date, end_date,
            )
            _write_json(self, {
                'strategy': label,
                'strategy_cn': cn,
                'benchmark': benchmark,
                'regimes': [],
                'message': f'基准 {benchmark} 在该时间范围内无数据',
            })
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
        if is_custom:
            df, _trades_n, _build_err = _build_custom_strategy_dataframe(
                strategy_arg, start_date, end_date, holding_days, benchmark)
            data_source = 'custom_trades+kline'
        else:
            df = _load_backtest_data(meta['table'], start_date, end_date, [rate_col])
            data_source = None
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

        payload = {
            'strategy': label,
            'strategy_cn': cn,
            'benchmark': benchmark,
            'holding_days': holding_days,
            'period': f'{start_date} ~ {end_date}',
            'regimes': regimes,
            'strategy_by_regime': strategy_by_regime,
            'classification_method': 'MA20/MA60 crossover + ATR median',
        }
        if data_source:
            payload['data_source'] = data_source
        _write_json(self, payload)


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
        strategy_arg = self.get_argument('strategy', default='', strip=True)
        if strategy_arg.startswith('custom_'):
            self._handle_custom(strategy_arg)
            return

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

        self._run_decay_analysis(df, meta['table'], meta['cn'],
                                 start_date, end_date, holding_days)

    def _handle_custom(self, strategy_key):
        strategy_key, strategy_id, start_date, end_date, err = _parse_custom_strategy_args(self)
        if err:
            _write_error(self, err)
            return

        holding_days_arg = self.get_argument('holding_days', default='5', strip=True)
        try:
            holding_days = max(1, min(int(holding_days_arg), RATE_FIELDS_COUNT))
        except (TypeError, ValueError):
            holding_days = 5

        benchmark = self.get_argument('benchmark', default='000300', strip=True) or '000300'
        df, total_trades, build_err = _build_custom_strategy_dataframe(
            strategy_key, start_date, end_date, holding_days, benchmark)
        if build_err and (df is None or len(df) == 0):
            _write_json(self, {
                'strategy': strategy_key,
                'strategy_cn': '自定义策略',
                'holding_days': holding_days,
                'monthly': [],
                'message': build_err,
                'data_source': 'custom_trades+kline',
            })
            return

        self._run_decay_analysis(df, strategy_key, '自定义策略',
                                 start_date, end_date, holding_days,
                                 data_source='custom_trades+kline')

    def _run_decay_analysis(self, df, label, cn, start_date, end_date,
                            holding_days, data_source=None):
        rate_col = f'rate_{holding_days}'
        df = df.copy()
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

        payload = {
            'strategy': label,
            'strategy_cn': cn,
            'holding_days': holding_days,
            'period': f'{start_date} ~ {end_date}',
            'monthly': monthly,
            'decay_warning': decay_warning,
        }
        if data_source:
            payload['data_source'] = data_source
        _write_json(self, payload)


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
        strategy_arg = self.get_argument('strategy', default='', strip=True)
        if strategy_arg.startswith('custom_'):
            self._handle_custom(strategy_arg)
            return

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

        self._write_cost_scenarios(rates, meta['table'], meta['cn'],
                                   start_date, end_date, holding_days)

    def _handle_custom(self, strategy_key):
        strategy_key, strategy_id, start_date, end_date, err = _parse_custom_strategy_args(self)
        if err:
            _write_error(self, err)
            return

        holding_days_arg = self.get_argument('holding_days', default='5', strip=True)
        try:
            holding_days = max(1, min(int(holding_days_arg), RATE_FIELDS_COUNT))
        except (TypeError, ValueError):
            holding_days = 5

        benchmark = self.get_argument('benchmark', default='000300', strip=True) or '000300'
        df, total_trades, build_err = _build_custom_strategy_dataframe(
            strategy_key, start_date, end_date, holding_days, benchmark)
        if build_err and (df is None or len(df) == 0):
            _write_json(self, {
                'strategy': strategy_key,
                'strategy_cn': '自定义策略',
                'scenarios': [],
                'message': build_err,
                'data_source': 'custom_trades+kline',
            })
            return

        rate_col = f'rate_{holding_days}'
        rates = df[rate_col].dropna().values
        if len(rates) == 0:
            _write_json(self, {
                'strategy': strategy_key,
                'strategy_cn': '自定义策略',
                'scenarios': [],
                'message': '逐笔 K 线缓存不足，无法计算',
                'data_source': 'custom_trades+kline',
            })
            return

        self._write_cost_scenarios(rates, strategy_key, '自定义策略',
                                   start_date, end_date, holding_days,
                                   data_source='custom_trades+kline')

    def _write_cost_scenarios(self, rates, label, cn, start_date, end_date,
                              holding_days, data_source=None):
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

        payload = {
            'strategy': label,
            'strategy_cn': cn,
            'holding_days': holding_days,
            'period': f'{start_date} ~ {end_date}',
            'total_signals': int(len(rates)),
            'current_cost_pct': current_cost,
            'scenarios': scenarios,
        }
        if data_source:
            payload['data_source'] = data_source
        _write_json(self, payload)


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
        strategy_arg = self.get_argument('strategy', default='', strip=True)
        if strategy_arg.startswith('custom_'):
            self._handle_custom(strategy_arg)
            return

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

        rates_matrix = np.asarray(df[rate_cols].values, dtype=np.float64)
        total_signals = len(df)
        self._write_exit_compare(rates_matrix, total_signals, meta['table'], meta['cn'],
                                 start_date, end_date, holding_days, trailing_days_list,
                                 max_hold)

    def _handle_custom(self, strategy_key):
        strategy_key, strategy_id, start_date, end_date, err = _parse_custom_strategy_args(self)
        if err:
            _write_error(self, err)
            return

        holding_days_arg = self.get_argument('holding_days', default='5', strip=True)
        try:
            holding_days = max(1, min(int(holding_days_arg), RATE_FIELDS_COUNT))
        except (TypeError, ValueError):
            holding_days = 5

        trailing_days_arg = self.get_argument('trailing_days', default='10,15,20', strip=True)
        try:
            trailing_days_list = sorted(set(
                max(5, min(int(x.strip()), 60))
                for x in trailing_days_arg.split(',') if x.strip()
            ))
        except ValueError:
            trailing_days_list = [10, 15, 20]

        max_hold = max(holding_days, max(trailing_days_list) + 10)
        max_hold = min(max_hold, RATE_FIELDS_COUNT)
        benchmark = self.get_argument('benchmark', default='000300', strip=True) or '000300'
        df, total_trades, build_err = _build_custom_strategy_dataframe(
            strategy_key, start_date, end_date, max_hold, benchmark)
        if build_err and (df is None or len(df) == 0):
            _write_json(self, {
                'strategy': strategy_key,
                'strategy_cn': '自定义策略',
                'exit_strategies': [],
                'message': build_err,
                'data_source': 'custom_trades+kline',
            })
            return

        rate_cols = [f'rate_{d}' for d in range(1, max_hold + 1)]
        rates_matrix = np.asarray(df[rate_cols].values, dtype=np.float64)
        self._write_exit_compare(rates_matrix, len(df), strategy_key, '自定义策略',
                                 start_date, end_date, holding_days, trailing_days_list,
                                 max_hold, data_source='custom_trades+kline')

    def _write_exit_compare(self, rates_matrix, total_signals, label, cn,
                            start_date, end_date, holding_days, trailing_days_list,
                            max_hold, data_source=None):
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

        payload = {
            'strategy': label,
            'strategy_cn': cn,
            'period': f'{start_date} ~ {end_date}',
            'total_signals': total_signals,
            'exit_strategies': exit_strategies,
            'best_strategy': best_strategy,
        }
        if data_source:
            payload['data_source'] = data_source
        _write_json(self, payload)

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
        strategy_arg = self.get_argument('strategy', default='', strip=True)
        if strategy_arg.startswith('custom_'):
            self._handle_custom(strategy_arg)
            return

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

        self._write_return_series(df, meta['table'], meta['cn'],
                                  holding_days, benchmark, start_date, end_date)

    def _handle_custom(self, strategy_key):
        strategy_key, strategy_id, start_date, end_date, err = _parse_custom_strategy_args(self)
        if err:
            _write_error(self, err)
            return

        holding_days_arg = self.get_argument('holding_days', default='5', strip=True)
        benchmark = self.get_argument('benchmark', default='000300', strip=True) or '000300'
        try:
            holding_days = max(1, min(int(holding_days_arg), RATE_FIELDS_COUNT))
        except (TypeError, ValueError):
            holding_days = 5

        df, total_trades, build_err = _build_custom_strategy_dataframe(
            strategy_key, start_date, end_date, holding_days, benchmark)
        if build_err and (df is None or len(df) == 0):
            _write_json(self, {
                'strategy': strategy_key,
                'strategy_cn': '自定义策略',
                'series': [],
                'benchmark_series': _benchmark_return_series(benchmark, start_date, end_date),
                'message': build_err,
                'data_source': 'custom_trades+kline',
            })
            return

        self._write_return_series(df, strategy_key, '自定义策略',
                                  holding_days, benchmark, start_date, end_date,
                                  data_source='custom_trades+kline')

    def _write_return_series(self, df, label, cn, holding_days, benchmark,
                             start_date, end_date, data_source=None):
        rate_col = f'rate_{holding_days}'
        df = df.copy()
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

        payload = {
            'strategy': label,
            'strategy_cn': cn,
            'holding_days': holding_days,
            'series': series,
            'benchmark_series': _benchmark_return_series(benchmark, start_date, end_date),
        }
        if data_source:
            payload['data_source'] = data_source
        _write_json(self, payload)

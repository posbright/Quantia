#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""选股验证中心 — 策略融合实验 API Handler

提供多策略信号交集/并集/投票/轮动等融合分析接口。

数据来源: MySQL + cache/hist/（遵守 Fetch/Analysis/Web 分离原则）
"""

import datetime
import json
import logging
import math
import time
from collections import defaultdict
from itertools import combinations

import numpy as np
import pandas as pd

import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
import quantia.web.base as webBase
from quantia.web.verifyOptimizeHandler import (
    _calc_annualized_sharpe, _get_strategy_map, _json_default,
    _load_backtest_data,
    _parse_date, _resolve_strategy, _safe_float, _write_error, _write_json,
    RATE_FIELDS_COUNT,
)

__author__ = 'Quantia'
__date__ = '2026/05/16'

logger = logging.getLogger(__name__)


# ── 策略融合运算 ──────────────────────────────────────────────────────

class StrategyFusionHandler(webBase.BaseHandler):
    """POST /quantia/api/verify/fusion

    对多策略进行信号融合（交集/并集/投票），计算融合后的收益指标。
    """

    def post(self):
        try:
            self._handle()
        except Exception:
            logger.error("策略融合异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)

    def _handle(self):
        try:
            body = json.loads(self.request.body)
        except (json.JSONDecodeError, TypeError):
            _write_error(self, '请求体必须为 JSON')
            return

        # v2 schema (五维真融合) 走新通路。旧 schema (仅 strategy_names) 继续走 legacy。
        if int(body.get('version', 0) or 0) >= 2 or 'dimensions' in body:
            return _handle_v2(self, body)

        strategy_names = body.get('strategy_names', [])
        if not isinstance(strategy_names, list) or len(strategy_names) < 2:
            _write_error(self, '至少需要选择 2 个策略')
            return
        if len(strategy_names) > 6:
            _write_error(self, '最多支持 6 个策略融合')
            return

        mode = body.get('mode', 'intersection')
        if mode not in ('intersection', 'union', 'vote', 'rotation'):
            _write_error(self, "mode 必须为 intersection / union / vote / rotation")
            return

        vote_threshold = int(body.get('vote_threshold', 2))
        if mode == 'vote':
            vote_threshold = max(2, min(vote_threshold, len(strategy_names)))

        start_s = body.get('start_date', '')
        end_s = body.get('end_date', '')
        start_date = _parse_date(start_s)
        end_date = _parse_date(end_s)
        if not start_date or not end_date:
            _write_error(self, 'start_date 和 end_date 必填，格式 YYYY-MM-DD')
            return
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        if (end_date - start_date).days > 366:
            _write_error(self, '日期区间过大，请控制在 366 天以内')
            return

        holding_days = max(1, min(int(body.get('holding_days', 5)), RATE_FIELDS_COUNT))
        rate_col = f'rate_{holding_days}'

        # 解析过滤条件
        filters = body.get('filters', {})
        if not isinstance(filters, dict):
            filters = {}

        # 解析各策略
        strategy_metas = []
        for name in strategy_names:
            meta, err = _resolve_strategy(name)
            if err:
                _write_error(self, err)
                return
            strategy_metas.append(meta)

        # 加载各策略数据
        strategy_data = {}  # table_name -> DataFrame(date, code, rate)
        individual_results = {}

        for meta in strategy_metas:
            table = meta['table']
            if table in strategy_data:
                continue
            if not mdb.checkTableIsExist(table):
                _write_error(self, f"策略表 {table} 不存在")
                return

            sql = f"""
                SELECT `date`, `code`, `{rate_col}` AS rate
                FROM `{table}`
                WHERE `date` >= %s AND `date` <= %s
                  AND `{rate_col}` IS NOT NULL
            """
            try:
                df = pd.read_sql(sql, con=mdb.engine(), params=(str(start_date), str(end_date)))
            except Exception as e:
                logger.error(f"加载策略 {table} 失败: {e}", exc_info=True)
                _write_error(self, f'加载策略 {table} 失败', 500)
                return

            if df is None or len(df) == 0:
                df = pd.DataFrame(columns=['date', 'code', 'rate'])

            strategy_data[table] = df

        # 应用指标过滤条件
        if filters:
            strategy_data = self._apply_filters(strategy_data, filters, start_date, end_date)

        # 计算各策略个体指标（过滤后）
        for meta in strategy_metas:
            table = meta['table']
            if table in individual_results:
                continue
            df = strategy_data.get(table, pd.DataFrame(columns=['date', 'code', 'rate']))
            rates = df['rate'].dropna().values
            if len(rates) > 0:
                individual_results[table] = {
                    'cn': meta['cn'],
                    'avg_return': _safe_float(float(rates.mean())),
                    'win_rate': _safe_float(float((rates > 0).mean() * 100)),
                    'sharpe': _safe_float(_calc_annualized_sharpe(rates, holding_days)),
                    'signal_count': int(len(rates)),
                }
            else:
                individual_results[table] = {
                    'cn': meta['cn'],
                    'avg_return': None, 'win_rate': None, 'sharpe': None, 'signal_count': 0,
                }

        # 融合逻辑
        tables = [meta['table'] for meta in strategy_metas]
        fusion_df = self._fuse_signals(strategy_data, tables, mode, vote_threshold)

        # 计算融合结果指标
        if fusion_df is not None and len(fusion_df) > 0:
            rates = fusion_df['rate'].dropna().values
            fusion_result = {
                'avg_return': _safe_float(float(rates.mean())) if len(rates) > 0 else None,
                'win_rate': _safe_float(float((rates > 0).mean() * 100)) if len(rates) > 0 else None,
                'sharpe': _safe_float(_calc_annualized_sharpe(rates, holding_days)) if len(rates) > 1 else None,
                'max_single_loss': _safe_float(float(rates.min())) if len(rates) > 0 else None,
                'max_single_gain': _safe_float(float(rates.max())) if len(rates) > 0 else None,
                'signal_count': int(len(rates)),
                'daily_signal_avg': _safe_float(float(fusion_df.groupby('date').size().mean())),
            }
        else:
            fusion_result = {
                'avg_return': None, 'win_rate': None, 'sharpe': None,
                'max_single_loss': None, 'max_single_gain': None,
                'signal_count': 0, 'daily_signal_avg': 0,
            }

        # 计算提升幅度
        improvement = {}
        if fusion_result['sharpe'] is not None:
            ind_sharpes = [v['sharpe'] for v in individual_results.values() if v['sharpe'] is not None]
            if ind_sharpes:
                best_ind = max(ind_sharpes)
                if best_ind and best_ind != 0:
                    improvement['sharpe_vs_best'] = f"{(fusion_result['sharpe'] - best_ind) / abs(best_ind) * 100:+.1f}%"

        # 日级累计走势 (用于前端收益走势图)
        daily_series = []
        if fusion_df is not None and len(fusion_df) > 0:
            fdf = fusion_df.copy()
            fdf['date'] = pd.to_datetime(fdf['date'])
            daily_avg = fdf.groupby('date')['rate'].mean().sort_index()
            cumulative = (1 + daily_avg / 100).cumprod() * 100
            running_max = cumulative.cummax()
            drawdown = (cumulative - running_max) / running_max * 100
            for dt, cum_val in cumulative.items():
                daily_series.append({
                    'date': dt.strftime('%Y-%m-%d'),
                    'cumulative': _safe_float(round(float(cum_val), 2)),
                    'drawdown': _safe_float(round(float(drawdown.loc[dt]), 2)),
                })

        _write_json(self, {
            'fusion_mode': mode,
            'vote_threshold': vote_threshold if mode == 'vote' else None,
            'holding_days': holding_days,
            'period': f'{start_date} ~ {end_date}',
            'fusion_result': fusion_result,
            'individual_results': individual_results,
            'improvement': improvement,
            'daily_series': daily_series,
        })

    @staticmethod
    def _fuse_signals(strategy_data, tables, mode, vote_threshold):
        """融合多策略信号。

        Returns DataFrame with (date, code, rate) for fused signals.
        """
        if not tables:
            return pd.DataFrame(columns=['date', 'code', 'rate'])

        # 为每个策略构建 (date, code) 集合
        dfs = []
        for t in tables:
            df = strategy_data.get(t)
            if df is not None and len(df) > 0:
                dfs.append(df[['date', 'code', 'rate']].copy().assign(_src=t))

        if not dfs:
            return pd.DataFrame(columns=['date', 'code', 'rate'])

        combined = pd.concat(dfs, ignore_index=True)

        if mode == 'intersection':
            # 取所有策略都选中的 (date, code)
            counts = combined.groupby(['date', 'code']).size().reset_index(name='cnt')
            valid = counts[counts['cnt'] >= len(tables)][['date', 'code']]
            # 取第一个策略的 rate 作为代表
            first_table = tables[0]
            first_df = strategy_data[first_table]
            result = valid.merge(first_df[['date', 'code', 'rate']], on=['date', 'code'], how='inner')

        elif mode == 'union':
            # 取任一策略选中的，去重 (date, code) 取平均 rate
            result = combined.groupby(['date', 'code'])['rate'].mean().reset_index()

        elif mode == 'vote':
            # >= vote_threshold 个策略选中
            counts = combined.groupby(['date', 'code']).size().reset_index(name='cnt')
            valid = counts[counts['cnt'] >= vote_threshold][['date', 'code']]
            result = combined.groupby(['date', 'code'])['rate'].mean().reset_index()
            result = valid.merge(result, on=['date', 'code'], how='inner')

        elif mode == 'rotation':
            # 环境轮动: 按市场环境切换策略
            # 简化实现: 按月轮动，每月用该月表现最好的策略
            result = StrategyFusionHandler._rotation_fuse(strategy_data, tables, combined)

        else:
            result = pd.DataFrame(columns=['date', 'code', 'rate'])

        return result

    @staticmethod
    def _rotation_fuse(strategy_data, tables, combined):
        """环境轮动融合: 按月选择该月信号最多(最活跃)的策略。"""
        if combined.empty:
            return pd.DataFrame(columns=['date', 'code', 'rate'])

        combined = combined.copy()
        combined['date'] = pd.to_datetime(combined['date'])
        combined['month'] = combined['date'].dt.to_period('M')

        # 按月+策略计算平均收益, 选每月最优策略
        monthly_perf = combined.groupby(['month', '_src'])['rate'].mean().reset_index()
        best_per_month = monthly_perf.loc[monthly_perf.groupby('month')['rate'].idxmax()]
        month_to_table = dict(zip(best_per_month['month'], best_per_month['_src']))

        # 取每月最优策略的信号
        results = []
        for month, table in month_to_table.items():
            month_data = combined[(combined['month'] == month) & (combined['_src'] == table)]
            results.append(month_data[['date', 'code', 'rate']])

        if results:
            return pd.concat(results, ignore_index=True)
        return pd.DataFrame(columns=['date', 'code', 'rate'])

    @staticmethod
    def _apply_filters(strategy_data, filters, start_date, end_date):
        """应用指标过滤条件到各策略数据。

        filters 格式: {"rsi_6_max": 70, "rsi_6_min": 30, "vol_ratio_min": 1.0, ...}
        支持: {indicator}_{max|min} 格式
        """
        import quantia.core.tablestructure as tbs

        # 解析过滤条件
        filter_conditions = []
        for key, value in filters.items():
            parts = key.rsplit('_', 1)
            if len(parts) != 2 or parts[1] not in ('max', 'min'):
                continue
            indicator = parts[0]
            bound = parts[1]
            try:
                threshold = float(value)
            except (TypeError, ValueError):
                continue
            filter_conditions.append((indicator, bound, threshold))

        if not filter_conditions:
            return strategy_data

        # 从指标表获取需要的指标
        indicators_table = tbs.TABLE_CN_STOCK_INDICATORS['name']
        if not mdb.checkTableIsExist(indicators_table):
            return strategy_data

        indicator_cols = list(set(fc[0] for fc in filter_conditions))
        cols_sql = ', '.join(['`date`', '`code`'] + [f'`{c}`' for c in indicator_cols])
        sql = f"SELECT {cols_sql} FROM `{indicators_table}` WHERE `date` >= %s AND `date` <= %s"
        try:
            ind_df = pd.read_sql(sql, con=mdb.engine(), params=(str(start_date), str(end_date)))
        except Exception:
            return strategy_data

        if ind_df is None or len(ind_df) == 0:
            return strategy_data

        # 对每个策略数据应用过滤
        filtered = {}
        for table, df in strategy_data.items():
            if df is None or len(df) == 0:
                filtered[table] = df
                continue
            merged = df.merge(ind_df, on=['date', 'code'], how='inner')
            mask = pd.Series(True, index=merged.index)
            for indicator, bound, threshold in filter_conditions:
                if indicator not in merged.columns:
                    continue
                if bound == 'max':
                    mask &= merged[indicator] <= threshold
                else:
                    mask &= merged[indicator] >= threshold
            filtered[table] = merged.loc[mask, ['date', 'code', 'rate']].reset_index(drop=True)

        return filtered


# ── 策略融合 v2 — 五维真融合 ──────────────────────────────────────────
#
# 设计 doc: document/strategy_fusion_redesign_plan.md
#
# 五维数据源：
#   tech   → cn_stock_strategy_<x>  (items = 策略表名/别名, 同维 OR)
#   fund   → cn_stock_selection     (items = "<col>_<op>_<val>", 同维 AND)
#   flow   → cn_stock_fund_flow     (items = "<col>_<op>_<val>", 同维 AND)
#   sent   → cn_stock_selection     (items = "<col>_<op>_<val>", 同维 AND, 不同列子集)
#   custom → cn_stock_strategy_<custom_id> 或 composite_<id> (items 同 tech)
#
# 收益评估：cn_stock_backtest_data 表 (date, code, rate_1..rate_100)
#   若该表无数据，fallback 用 cn_stock_strategy_* union 出 (date, code, rate_N)。

_DIM_LABEL = {'tech': '技术信号', 'fund': '基本面', 'flow': '资金流', 'sent': '情绪', 'custom': '自定义'}

# fund / flow / sent 字段白名单：避免 SQL 注入并控制可选过滤范围
_FUND_ALLOWED_COLS = {
    'pe9': '市盈率TTM', 'pbnewmrq': '市净率MRQ', 'pettmdeducted': '市盈率TTM扣非',
    'ps9': '市销率TTM', 'pcfjyxjl9': '市现率TTM', 'roe_weight': '净资产收益率ROE',
    'jroa': '总资产净利率ROA', 'roic': '投入资本回报率ROIC',
    'sale_gpr': '毛利率', 'sale_npr': '净利率', 'zxgxl': '最新股息率',
    'ycpeg': '预测PEG', 'dtsyl': '动态市盈率',
    'total_market_cap': '总市值', 'free_cap': '流通市值',
}
_FLOW_ALLOWED_COLS = {
    'fund_amount': '当日主力净流入', 'fund_rate': '当日主力净流入占比',
    'fund_amount_3': '3日主力净流入', 'fund_rate_3': '3日主力净流入占比',
    'fund_amount_5': '5日主力净流入', 'fund_rate_5': '5日主力净流入占比',
    'fund_amount_10': '10日主力净流入', 'fund_rate_10': '10日主力净流入占比',
    'fund_amount_super': '当日超大单净流入', 'fund_rate_super': '当日超大单净流入占比',
    'fund_amount_large': '当日大单净流入', 'fund_rate_large': '当日大单净流入占比',
}
_SENT_ALLOWED_COLS = {
    'turnoverrate': '换手率', 'volume_ratio': '量比',
    'change_rate': '涨跌幅', 'amplitude': '振幅', 'ups_downs': '涨跌额',
}

_OP_MAP = {'lt': '<', 'lte': '<=', 'gt': '>', 'gte': '>=', 'eq': '='}


class _ValidationError(Exception):
    """v2 spec 解析校验失败。"""


def _parse_item_expr(item: str, allowed_cols: dict):
    """解析 'col_op_val' 形式表达式。

    返回 (col, sql_op, threshold) 或 raise _ValidationError。
    item 必须以 allowed_cols 中的某个 col 起始（最长前缀匹配，因为 col 名可能含 '_'）。
    """
    if not isinstance(item, str) or not item.strip():
        raise _ValidationError(f"item 必须为非空字符串: {item!r}")
    s = item.strip()
    # 最长前缀匹配 column 名
    matched_col = None
    for col in sorted(allowed_cols.keys(), key=len, reverse=True):
        if s.startswith(col + '_'):
            matched_col = col
            break
    if not matched_col:
        raise _ValidationError(f"未知列: {item!r}（允许列: {', '.join(sorted(allowed_cols.keys()))}）")
    tail = s[len(matched_col) + 1:]
    parts = tail.split('_', 1)
    if len(parts) != 2:
        raise _ValidationError(f"item 格式错误: {item!r}, 应为 '<col>_<op>_<val>'")
    op_key, val_s = parts
    if op_key not in _OP_MAP:
        raise _ValidationError(f"不支持的操作符 {op_key!r}, 仅支持 {list(_OP_MAP.keys())}")
    try:
        threshold = float(val_s)
    except ValueError:
        raise _ValidationError(f"阈值不是数字: {val_s!r}")
    return matched_col, _OP_MAP[op_key], threshold


def _parse_v2_spec(body):
    """解析 v2 schema 请求体，返回 dict 形式 spec。

    抛 _ValidationError 表示请求非法。
    """
    mode = body.get('mode') or 'weighted_score'
    if mode not in ('weighted_score', 'vote', 'condition_tree', 'rotation'):
        raise _ValidationError("mode 必须为 weighted_score / vote / condition_tree / rotation")

    start_date = _parse_date(body.get('start_date', ''))
    end_date = _parse_date(body.get('end_date', ''))
    if not start_date or not end_date:
        raise _ValidationError('start_date 和 end_date 必填，格式 YYYY-MM-DD')
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    if (end_date - start_date).days > 366:
        raise _ValidationError('日期区间过大，请控制在 366 天以内')

    try:
        holding_days = int(body.get('holding_days', 10))
    except (TypeError, ValueError):
        raise _ValidationError('holding_days 必须为整数')
    holding_days = max(1, min(holding_days, RATE_FIELDS_COUNT))

    try:
        min_score = float(body.get('min_score', 0.6))
    except (TypeError, ValueError):
        min_score = 0.6
    min_score = max(0.0, min(min_score, 1.0))

    vote_threshold_raw = body.get('vote_threshold')

    dimensions_raw = body.get('dimensions') or {}
    if not isinstance(dimensions_raw, dict):
        raise _ValidationError('dimensions 必须为对象')

    dimensions = {}
    for k in ('tech', 'fund', 'flow', 'sent', 'custom'):
        d = dimensions_raw.get(k) or {}
        items = d.get('items') or []
        if not isinstance(items, list):
            items = []
        try:
            weight = float(d.get('weight', 0))
        except (TypeError, ValueError):
            weight = 0.0
        dimensions[k] = {
            'key': k,
            'enabled': bool(d.get('enabled', False)) and len(items) > 0,
            'weight': max(0.0, weight),
            'items': [str(x).strip() for x in items if str(x).strip()],
        }

    enabled_dims = [k for k, v in dimensions.items() if v['enabled']]
    if not enabled_dims:
        raise _ValidationError('至少需要启用 1 个维度并选中信号项')

    if mode == 'vote':
        if vote_threshold_raw is None:
            vote_threshold = max(2, (len(enabled_dims) + 1) // 2)
        else:
            try:
                vote_threshold = int(vote_threshold_raw)
            except (TypeError, ValueError):
                raise _ValidationError('vote_threshold 必须为整数')
            vote_threshold = max(1, min(vote_threshold, len(enabled_dims)))
    else:
        vote_threshold = None

    return {
        'mode': mode,
        'start_date': start_date,
        'end_date': end_date,
        'holding_days': holding_days,
        'min_score': min_score,
        'vote_threshold': vote_threshold,
        'dimensions': dimensions,
    }


# ── 维度信号加载器 ────────────────────────────────────────────────────

def _load_dim_signals_tech(items, start_date, end_date):
    """技术维度：items = 策略表名/别名/中文名，同维 OR (UNION)。"""
    warnings = []
    frames = []
    seen_tables = set()
    for item in items:
        meta, err = _resolve_strategy(item)
        if err or not meta:
            warnings.append(f"技术维度跳过无效策略 {item!r}: {err or '未知'}")
            continue
        table = meta['table']
        if table in seen_tables:
            continue
        seen_tables.add(table)
        if not mdb.checkTableIsExist(table):
            warnings.append(f"技术维度表 {table} 不存在，跳过")
            continue
        sql = f"SELECT `date`, `code` FROM `{table}` WHERE `date` >= %s AND `date` <= %s"
        try:
            df = pd.read_sql(sql, con=mdb.engine(), params=(str(start_date), str(end_date)))
        except Exception as e:
            logger.warning(f"技术维度加载 {table} 失败: {e}")
            warnings.append(f"技术维度加载 {table} 失败")
            continue
        if df is not None and len(df) > 0:
            frames.append(df[['date', 'code']])
    if not frames:
        return pd.DataFrame(columns=['date', 'code']), warnings
    merged = pd.concat(frames, ignore_index=True).drop_duplicates(subset=['date', 'code']).reset_index(drop=True)
    return merged, warnings


def _load_dim_signals_table_filter(table, allowed_cols, items, start_date, end_date, dim_label):
    """通用：从指定表按 items (col_op_val) 同维 AND 过滤。"""
    warnings = []
    if not items:
        return pd.DataFrame(columns=['date', 'code']), warnings
    if not mdb.checkTableIsExist(table):
        warnings.append(f"{dim_label}维度表 {table} 不存在")
        return pd.DataFrame(columns=['date', 'code']), warnings
    conds = []
    parsed = []
    for item in items:
        try:
            col, op, val = _parse_item_expr(item, allowed_cols)
        except _ValidationError as e:
            warnings.append(f"{dim_label}维度跳过 {item!r}: {e}")
            continue
        parsed.append((col, op, val))
        conds.append(f"`{col}` {op} %s")
    if not parsed:
        return pd.DataFrame(columns=['date', 'code']), warnings
    where_extra = ' AND '.join(conds)
    sql = (f"SELECT `date`, `code` FROM `{table}` "
           f"WHERE `date` >= %s AND `date` <= %s AND {where_extra}")
    params = [str(start_date), str(end_date)] + [v for (_, _, v) in parsed]
    try:
        df = pd.read_sql(sql, con=mdb.engine(), params=tuple(params))
    except Exception as e:
        logger.warning(f"{dim_label}维度查询 {table} 失败: {e}")
        warnings.append(f"{dim_label}维度查询失败")
        return pd.DataFrame(columns=['date', 'code']), warnings
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=['date', 'code']), warnings
    df = df[['date', 'code']].drop_duplicates().reset_index(drop=True)
    return df, warnings


def _load_dim_signals_custom(items, start_date, end_date):
    """自定义策略维度：items = ['custom_<id>', ...]，取回测 buy 交易作为信号。

    数据源：cn_stock_backtest_portfolio.result_json -> trades[]（direction=='buy'）。
    透过 verifyOptimizeHandler._collect_custom_buy_trades 复用现有缓存 / 内存任务通路。
    同维 OR（多个自定义策略合并去重）。
    """
    from quantia.web.verifyOptimizeHandler import _collect_custom_buy_trades
    warnings = []
    frames = []
    seen = set()
    for item in items:
        s = str(item).strip()
        if not s:
            continue
        if s in seen:
            continue
        seen.add(s)
        if not s.startswith('custom_'):
            warnings.append(f"自定义维度跳过非 custom_<id> 键 {item!r}")
            continue
        try:
            sid = int(s.replace('custom_', '', 1))
        except ValueError:
            warnings.append(f"自定义维度无法解析 ID: {item!r}")
            continue
        try:
            trades = _collect_custom_buy_trades(sid, start_date, end_date, '000300')
        except Exception as e:
            logger.warning(f"自定义策略 #{sid} 加载 buy 交易失败: {e}")
            warnings.append(f"自定义策略 #{sid} 加载失败")
            continue
        if not trades:
            warnings.append(f"自定义策略 #{sid} 在该区间无 buy 交易（请先在「策略管理 → 回测」跑完整覆盖此区间的回测）")
            continue
        df = pd.DataFrame(trades)
        if 'date' not in df.columns or 'code' not in df.columns:
            warnings.append(f"自定义策略 #{sid} 回测结果缺少 date/code 字段")
            continue
        # 统一日期类型为 datetime64[ns]，与其他维度（pd.read_sql 的 DATE 列）对齐
        df['date'] = pd.to_datetime(df['date'], errors='coerce').dt.normalize()
        df = df.dropna(subset=['date'])
        df = df[['date', 'code']].drop_duplicates()
        if len(df) > 0:
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=['date', 'code']), warnings
    merged = pd.concat(frames, ignore_index=True).drop_duplicates(
        subset=['date', 'code']).reset_index(drop=True)
    return merged, warnings


def _load_dim_signals(key, items, start_date, end_date):
    """统一入口：返回 (DataFrame[date, code], warnings)。"""
    if key == 'tech':
        return _load_dim_signals_tech(items, start_date, end_date)
    if key == 'fund':
        return _load_dim_signals_table_filter(
            'cn_stock_selection', _FUND_ALLOWED_COLS, items, start_date, end_date, '基本面')
    if key == 'flow':
        return _load_dim_signals_table_filter(
            'cn_stock_fund_flow', _FLOW_ALLOWED_COLS, items, start_date, end_date, '资金流')
    if key == 'sent':
        return _load_dim_signals_table_filter(
            'cn_stock_selection', _SENT_ALLOWED_COLS, items, start_date, end_date, '情绪')
    if key == 'custom':
        return _load_dim_signals_custom(items, start_date, end_date)
    return pd.DataFrame(columns=['date', 'code']), [f"未知维度 {key}"]


# ── 融合 ──────────────────────────────────────────────────────────────

def _fuse_v2(dim_signals, spec):
    """根据 spec.mode 把多维 (date, code) 集融合为最终入选集。

    Args:
        dim_signals: dict[dim_key, DataFrame[date, code]]
        spec: dict from _parse_v2_spec

    Returns:
        DataFrame[date, code] 去重后的最终信号集。
    """
    enabled = [k for k, df in dim_signals.items() if df is not None and len(df) > 0]
    if not enabled:
        return pd.DataFrame(columns=['date', 'code'])

    mode = spec['mode']
    if mode == 'rotation':
        # Stage 1: rotation 简化为 weighted_score（warning 已在主流程加）
        mode = 'weighted_score'

    if mode == 'condition_tree':
        ordered = sorted(enabled, key=lambda k: -spec['dimensions'][k]['weight'])
        result = dim_signals[ordered[0]][['date', 'code']].drop_duplicates()
        for k in ordered[1:]:
            result = result.merge(
                dim_signals[k][['date', 'code']].drop_duplicates(),
                on=['date', 'code'], how='inner')
        return result.reset_index(drop=True)

    # weighted_score / vote 都依赖每对 (date,code) 命中的维度集合
    pieces = []
    for k in enabled:
        df = dim_signals[k][['date', 'code']].drop_duplicates().copy()
        df['_dim'] = k
        df['_w'] = float(spec['dimensions'][k]['weight'])
        pieces.append(df)
    all_rows = pd.concat(pieces, ignore_index=True)

    if mode == 'vote':
        threshold = spec.get('vote_threshold') or max(2, (len(enabled) + 1) // 2)
        counts = all_rows.groupby(['date', 'code'])['_dim'].nunique().reset_index(name='_n')
        return counts[counts['_n'] >= threshold][['date', 'code']].reset_index(drop=True)

    # weighted_score
    total_w = sum(spec['dimensions'][k]['weight'] for k in enabled) or 1.0
    scored = all_rows.groupby(['date', 'code'])['_w'].sum().reset_index(name='_score')
    scored['_score'] = scored['_score'] / total_w
    return scored[scored['_score'] >= spec['min_score']][['date', 'code']].reset_index(drop=True)


# ── 收益评估 ──────────────────────────────────────────────────────────

def _load_rate_df(start_date, end_date, holding_days):
    """加载 (date, code) → rate_N 映射。

    优先从 cn_stock_backtest_data 表读，若表不存在或为空，从所有
    cn_stock_strategy_* 表 UNION 出 (date, code, rate_N)。
    """
    rate_col = f'rate_{holding_days}'
    table = tbs.TABLE_CN_STOCK_BACKTEST_DATA['name']
    if mdb.checkTableIsExist(table):
        sql = (f"SELECT `date`, `code`, `{rate_col}` AS rate FROM `{table}` "
               f"WHERE `date` >= %s AND `date` <= %s AND `{rate_col}` IS NOT NULL")
        try:
            df = pd.read_sql(sql, con=mdb.engine(), params=(str(start_date), str(end_date)))
            if df is not None and len(df) > 0:
                return df.drop_duplicates(subset=['date', 'code']).reset_index(drop=True)
        except Exception as e:
            logger.warning(f"cn_stock_backtest_data 查询失败: {e}")

    # fallback: union all cn_stock_strategy_*
    frames = []
    for s in tbs.TABLE_CN_STOCK_STRATEGIES:
        tname = s['name']
        if not mdb.checkTableIsExist(tname):
            continue
        sql = (f"SELECT `date`, `code`, `{rate_col}` AS rate FROM `{tname}` "
               f"WHERE `date` >= %s AND `date` <= %s AND `{rate_col}` IS NOT NULL")
        try:
            df = pd.read_sql(sql, con=mdb.engine(), params=(str(start_date), str(end_date)))
        except Exception:
            continue
        if df is not None and len(df) > 0:
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=['date', 'code', 'rate'])
    combined = pd.concat(frames, ignore_index=True)
    return combined.groupby(['date', 'code'], as_index=False)['rate'].mean()


def _evaluate(signal_df, rate_df, holding_days):
    """对 (date, code) 集做收益评估。

    Returns:
        (metrics_dict, daily_series_list)
    """
    empty = ({
        'avg_return': None, 'win_rate': None, 'sharpe': None,
        'max_drawdown': None, 'signal_count': 0, 'daily_signal_avg': 0,
        'total_return': None,
    }, [])
    if signal_df is None or len(signal_df) == 0:
        return empty
    if rate_df is None or len(rate_df) == 0:
        m = empty[0].copy()
        m['signal_count'] = int(len(signal_df))
        m['daily_signal_avg'] = _safe_float(float(signal_df.groupby('date').size().mean()))
        return m, []

    merged = signal_df.merge(rate_df, on=['date', 'code'], how='inner')
    if len(merged) == 0:
        m = empty[0].copy()
        m['signal_count'] = int(len(signal_df))
        m['daily_signal_avg'] = _safe_float(float(signal_df.groupby('date').size().mean()))
        return m, []

    rates = merged['rate'].dropna().astype(float).values
    rates = rates[np.isfinite(rates)]
    if len(rates) == 0:
        return empty

    # 日级序列：每日入选股平均收益 → 累计净值 + 回撤
    fdf = merged.copy()
    fdf['date'] = pd.to_datetime(fdf['date'])
    daily_avg = fdf.groupby('date')['rate'].mean().sort_index()
    cumulative = (1 + daily_avg / 100).cumprod() * 100
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max * 100
    daily_signal_count = fdf.groupby('date').size().sort_index()

    daily_series = []
    for dt, cum_val in cumulative.items():
        daily_series.append({
            'date': dt.strftime('%Y-%m-%d'),
            'cumulative': _safe_float(round(float(cum_val), 2)),
            'drawdown': _safe_float(round(float(drawdown.loc[dt]), 2)),
            'signal_count': int(daily_signal_count.loc[dt]),
        })

    max_dd = float(drawdown.min()) if len(drawdown) > 0 else 0.0
    total_return = float(cumulative.iloc[-1] - 100) if len(cumulative) > 0 else None

    metrics = {
        'avg_return': _safe_float(float(rates.mean())),
        'win_rate': _safe_float(float((rates > 0).mean() * 100)),
        'sharpe': _safe_float(_calc_annualized_sharpe(rates, holding_days)) if len(rates) > 1 else None,
        'max_drawdown': _safe_float(max_dd),
        'signal_count': int(len(rates)),
        'daily_signal_avg': _safe_float(float(daily_signal_count.mean())),
        'total_return': _safe_float(total_return),
    }
    return metrics, daily_series


# ── 主流程 ────────────────────────────────────────────────────────────

def _calc_improvement(fusion_result, individual_results):
    out = {}
    if fusion_result.get('sharpe') is None:
        return out
    sharpes = [v.get('sharpe') for v in individual_results.values() if v.get('sharpe') is not None]
    if sharpes:
        best = max(sharpes)
        if best and best != 0:
            out['sharpe_vs_best_single'] = f"{(fusion_result['sharpe'] - best) / abs(best) * 100:+.1f}%"
    dds = [v.get('max_drawdown') for v in individual_results.values() if v.get('max_drawdown') is not None]
    if dds and fusion_result.get('max_drawdown') is not None:
        worst = min(dds)  # 回撤越负越差
        if worst and worst != 0:
            out['drawdown_vs_worst_single'] = f"{(fusion_result['max_drawdown'] - worst) / abs(worst) * 100:+.1f}%"
    return out


def _shapley_naive(individual_results, fusion_result):
    """Stage 1 占位：用 fusion.sharpe - individual.sharpe 的归一化作为贡献。

    保留作为 Stage 3 真 Shapley 超时 fallback。
    """
    if not individual_results or fusion_result.get('sharpe') is None:
        return []
    fusion_sharpe = fusion_result['sharpe'] or 0.0
    deltas = []
    for k, v in individual_results.items():
        ind = v.get('sharpe') or 0.0
        deltas.append((k, max(0.0, fusion_sharpe - ind)))
    total = sum(d for _, d in deltas) or 1.0
    items = []
    for k, d in sorted(deltas, key=lambda x: -x[1]):
        items.append({
            'dim': k,
            'cn': _DIM_LABEL.get(k, k),
            'contribution': _safe_float(d / total),
            'sharpe_delta': _safe_float(d),
        })
    for i, it in enumerate(items, 1):
        it['rank'] = i
    return items


# ── Stage 3: 真 Shapley / AB / Overlap ────────────────────────────────

def _fuse_subset_signals(dim_signals_subset, spec):
    """对 dim_signals 的子集运行融合（权重重新归一化），返回融合 DataFrame。"""
    if not dim_signals_subset:
        return pd.DataFrame(columns=['date', 'code'])
    if len(dim_signals_subset) == 1:
        # 单维：信号即融合结果
        df = next(iter(dim_signals_subset.values()))
        return df[['date', 'code']].drop_duplicates().reset_index(drop=True)
    # 多维：重写 spec 的 dimensions weights，仅子集启用
    sub_dims = {}
    subset_weights = {k: spec['dimensions'][k]['weight'] for k in dim_signals_subset.keys()}
    total_w = sum(subset_weights.values()) or 1.0
    for k, dim in spec['dimensions'].items():
        if k in dim_signals_subset:
            new_w = dim['weight'] / total_w * 100
            sub_dims[k] = {**dim, 'weight': new_w, 'enabled': True}
        else:
            sub_dims[k] = {**dim, 'enabled': False}
    sub_spec = dict(spec)
    sub_spec['dimensions'] = sub_dims
    sub_spec['vote_threshold'] = min((spec.get('vote_threshold') or 2), len(dim_signals_subset))
    return _fuse_v2(dim_signals_subset, sub_spec)


def _shapley_real(dim_signals, spec, rate_df, time_budget_s=8.0):
    """真 Shapley value via 2^n 子集枚举。

    返回 (shapley_list, used_fallback, diag)。如超时返回 (None, True, diag)。
    """
    keys = list(dim_signals.keys())
    n = len(keys)
    if n < 2:
        return [], False, {'reason': 'less_than_2_dims', 'n': n}

    t_start = time.time()
    subset_sharpe = {frozenset(): 0.0}
    n_eval = 0
    timeout = False

    for size in range(1, n + 1):
        for combo in combinations(keys, size):
            if time.time() - t_start > time_budget_s:
                timeout = True
                break
            sub = {k: dim_signals[k] for k in combo}
            fused = _fuse_subset_signals(sub, spec)
            m, _ = _evaluate(fused, rate_df, spec.get('holding_days', 10))
            sharpe = m.get('sharpe')
            subset_sharpe[frozenset(combo)] = float(sharpe) if sharpe is not None else 0.0
            n_eval += 1
        if timeout:
            break

    diag = {
        'n_dims': n, 'n_subsets_evaluated': n_eval, 'total_subsets': 2 ** n,
        'elapsed_s': round(time.time() - t_start, 3),
    }
    if timeout:
        diag['reason'] = 'timeout'
        return None, True, diag

    # Shapley: phi_k = Σ over S ⊆ N\{k} : |S|!(n-|S|-1)!/n! * (v(S∪{k}) - v(S))
    fact = math.factorial
    shapley_map = {}
    for k in keys:
        phi = 0.0
        others = [x for x in keys if x != k]
        for size in range(len(others) + 1):
            for combo in combinations(others, size):
                S = frozenset(combo)
                S_with_k = S | {k}
                weight = fact(len(S)) * fact(n - len(S) - 1) / fact(n)
                phi += weight * (subset_sharpe.get(S_with_k, 0.0) - subset_sharpe.get(S, 0.0))
        shapley_map[k] = phi

    sorted_items = sorted(shapley_map.items(), key=lambda x: -x[1])
    items = []
    for rank, (k, v) in enumerate(sorted_items, 1):
        items.append({
            'dim': k,
            'cn': _DIM_LABEL.get(k, k),
            'name': _DIM_LABEL.get(k, k),
            'contrib': _safe_float(v),
            'contribution': _safe_float(v),
            'sharpe_delta': _safe_float(v),
            'rank': rank,
        })
    return items, False, diag


def _ab_steps(dim_signals, shapley_items, spec, rate_df):
    """按 Shapley 排序逐维累加融合，返回累计步进列表。"""
    if not shapley_items:
        return []
    ordered_keys = [s['dim'] for s in shapley_items if s.get('dim') in dim_signals]
    steps = []
    for i in range(1, len(ordered_keys) + 1):
        sub_keys = ordered_keys[:i]
        sub = {k: dim_signals[k] for k in sub_keys}
        fused = _fuse_subset_signals(sub, spec)
        m, _ = _evaluate(fused, rate_df, spec.get('holding_days', 10))
        steps.append({
            'step': i,
            'dims': sub_keys,
            'label': ' + '.join(_DIM_LABEL.get(k, k) for k in sub_keys),
            'sharpe': m.get('sharpe'),
            'win_rate': m.get('win_rate'),
            'max_drawdown': m.get('max_drawdown'),
            'signal_count': m.get('signal_count'),
            'avg_return': m.get('avg_return'),
        })
    return steps


def _overlap(dim_signals):
    """计算日历热图 + Jaccard 共现矩阵。

    Returns: {calendar: [{date, signal_count, dims_hit}], co_occurrence: [{a, b, jaccard}]}
    """
    if not dim_signals:
        return {'calendar': [], 'co_occurrence': []}

    # 每维度的 (date, code) 集合
    key_sets = {}
    for k, df in dim_signals.items():
        if df is None or len(df) == 0:
            key_sets[k] = set()
            continue
        key_sets[k] = set(zip(df['date'].astype(str), df['code'].astype(str)))

    # 日历：date -> 独立 code 总数 + 命中维度数
    by_date_codes = defaultdict(set)
    by_date_dims = defaultdict(set)
    for k, s in key_sets.items():
        for date, code in s:
            by_date_codes[date].add(code)
            by_date_dims[date].add(k)
    calendar = sorted(
        ({'date': d, 'signal_count': len(by_date_codes[d]), 'dims_hit': len(by_date_dims[d])}
         for d in by_date_codes),
        key=lambda x: x['date'],
    )

    # Jaccard
    keys = list(key_sets.keys())
    pairs = []
    for k1 in keys:
        for k2 in keys:
            s1, s2 = key_sets[k1], key_sets[k2]
            union = len(s1 | s2)
            jacc = (len(s1 & s2) / union) if union else 0.0
            pairs.append({'a': k1, 'b': k2, 'jaccard': round(jacc, 4)})

    return {'calendar': calendar, 'co_occurrence': pairs}


def _handle_v2(handler, body):
    """v2 五维真融合主入口。"""
    try:
        spec = _parse_v2_spec(body)
    except _ValidationError as e:
        _write_error(handler, str(e))
        return
    except Exception:
        logger.error('v2 spec 解析异常', exc_info=True)
        _write_error(handler, '请求体校验失败', 400)
        return

    warnings = []

    # 1. 各维度信号
    dim_signals = {}
    for k, dim in spec['dimensions'].items():
        if not dim['enabled']:
            continue
        df, w = _load_dim_signals(k, dim['items'], spec['start_date'], spec['end_date'])
        if w:
            warnings.extend(w)
        if df is None or len(df) == 0:
            warnings.append(f"{_DIM_LABEL.get(k, k)}维度命中 0 条，已剔除")
            continue
        dim_signals[k] = df

    if not dim_signals:
        _write_json(handler, {
            'version': 2,
            'fusion_result': None,
            'individual_results': {},
            'daily_series': [],
            'shapley': [],
            'ab_steps': [],
            'overlap': {'calendar': [], 'co_occurrence': []},
            'improvement': {},
            'warnings': warnings + ['所有启用维度命中为 0，无法融合'],
            'diagnostics': {'enabled_dims': [], 'mode': spec['mode']},
        })
        return

    if spec['mode'] == 'rotation':
        warnings.append('rotation 模式 Stage 1 暂等同 weighted_score，将在 Stage 3 引入真 regime 检测')

    # 2. 主融合
    fused = _fuse_v2(dim_signals, spec)

    # 3. 收益数据
    rate_df = _load_rate_df(spec['start_date'], spec['end_date'], spec['holding_days'])
    if rate_df is None or len(rate_df) == 0:
        warnings.append(f"区间内 rate_{spec['holding_days']} 数据为空，指标可能为空")

    # 4. evaluate 融合 + 单维
    fusion_result, daily_series = _evaluate(fused, rate_df, spec['holding_days'])
    individual_results = {}
    for k, df in dim_signals.items():
        m, _ds = _evaluate(df, rate_df, spec['holding_days'])
        m['cn'] = _DIM_LABEL.get(k, k)
        individual_results[k] = m

    # 5. improvement + Stage 3 真 Shapley / AB / Overlap
    improvement = _calc_improvement(fusion_result, individual_results)

    # 5a. Shapley（≥2 维启用时计算；超时 fallback 到 naive）
    shapley_diag = {}
    if len(dim_signals) >= 2:
        shapley, used_fb, sh_diag = _shapley_real(dim_signals, spec, rate_df, time_budget_s=8.0)
        shapley_diag = sh_diag
        if used_fb or shapley is None:
            warnings.append(f"Shapley 真值计算超时（已评估 {sh_diag.get('n_subsets_evaluated',0)}/{sh_diag.get('total_subsets','?')} 子集），降级为快速估算")
            shapley = _shapley_naive(individual_results, fusion_result)
    else:
        shapley = _shapley_naive(individual_results, fusion_result)

    # 5b. AB 累加
    ab = _ab_steps(dim_signals, shapley, spec, rate_df)

    # 5c. Overlap
    overlap = _overlap(dim_signals)

    _write_json(handler, {
        'version': 2,
        'mode': spec['mode'],
        'holding_days': spec['holding_days'],
        'period': f"{spec['start_date']} ~ {spec['end_date']}",
        'fusion_result': fusion_result,
        'individual_results': individual_results,
        'daily_series': daily_series,
        'shapley': shapley,
        'ab_steps': ab,
        'overlap': overlap,
        'improvement': improvement,
        'warnings': warnings,
        'diagnostics': {
            'enabled_dims': list(dim_signals.keys()),
            'mode': spec['mode'],
            'fusion_signal_count': int(len(fused)),
            'min_score': spec['min_score'] if spec['mode'] == 'weighted_score' else None,
            'vote_threshold': spec['vote_threshold'] if spec['mode'] == 'vote' else None,
            'shapley': shapley_diag,
        },
    })


# ── AI 优化建议 ───────────────────────────────────────────────────────

class OptimizeSuggestHandler(webBase.BaseHandler):
    """GET /quantia/api/verify/optimize_suggest

    基于持仓天数分析和止盈止损分析结果，生成优化建议。
    """

    def get(self):
        try:
            self._handle()
        except Exception:
            logger.error("优化建议异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)

    def _handle(self):
        strategy_key = self.get_argument('strategy', default='', strip=True)
        meta, err = _resolve_strategy(strategy_key)
        if err:
            _write_error(self, err)
            return

        start_s = self.get_argument('start_date', default='', strip=True)
        end_s = self.get_argument('end_date', default='', strip=True)
        start_date = _parse_date(start_s)
        end_date = _parse_date(end_s)
        if not start_date or not end_date:
            _write_error(self, 'start_date 和 end_date 必填')
            return
        if start_date > end_date:
            start_date, end_date = end_date, start_date

        # 加载数据做简单分析
        rate_cols = [f'rate_{d}' for d in [1, 3, 5, 7, 10, 15, 20, 30]]
        table = meta['table']

        # 走 _load_backtest_data：DB 有则直接读，DB 空则走 K 线兜底，
        # 与买卖点优化页其它端点保持一致，避免 2025 历史区间无建议。
        df = _load_backtest_data(table, start_date, end_date, rate_cols)

        if df is None or len(df) == 0:
            _write_json(self, {'suggestions': [], 'message': '无数据，无法生成建议'})
            return

        suggestions = []

        # 建议 1: 最优持仓周期
        best_d = None
        best_sharpe = None
        for d in [1, 3, 5, 7, 10, 15, 20, 30]:
            col = f'rate_{d}'
            if col not in df.columns:
                continue
            rates = df[col].dropna().values
            if len(rates) < 10:
                continue
            sharpe = _calc_annualized_sharpe(rates, d)
            if sharpe is not None and (best_sharpe is None or sharpe > best_sharpe):
                best_sharpe = sharpe
                best_d = d

        if best_d:
            suggestions.append({
                'type': 'holding_period',
                'icon': '⏱',
                'title': '持仓周期建议',
                'content': f'最优持仓天数为 {best_d} 天（年化夏普 {best_sharpe:.2f}）',
                'params': {'holding_days': best_d, 'sharpe': _safe_float(best_sharpe)},
            })

        # 建议 2: 止盈止损参数
        if best_d and best_d <= 20:
            rate_col_best = f'rate_{best_d}'
            rates = df[rate_col_best].dropna().values
            if len(rates) > 20:
                p75 = float(np.percentile(rates, 75))
                p25 = float(np.percentile(rates, 25))
                suggested_tp = round(p75, 1)
                suggested_sl = round(p25, 1) if p25 < 0 else round(-abs(p75) * 0.5, 1)
                suggestions.append({
                    'type': 'stop_loss_take_profit',
                    'icon': '🛡️',
                    'title': '止盈止损建议',
                    'content': f'建议止盈 {suggested_tp}%，止损 {suggested_sl}%（基于 P75/P25 分位数）',
                    'params': {'take_profit': suggested_tp, 'stop_loss': suggested_sl},
                })

        # 建议 3: 信号质量
        if best_d:
            rate_col_best = f'rate_{best_d}'
            rates = df[rate_col_best].dropna().values
            if len(rates) > 0:
                win_rate = float((rates > 0).mean() * 100)
                if win_rate < 50:
                    suggestions.append({
                        'type': 'filter',
                        'icon': '🎯',
                        'title': '买入过滤建议',
                        'content': f'当前胜率仅 {win_rate:.1f}%，建议叠加 RSI/MACD 过滤低质量信号',
                        'params': {'current_win_rate': _safe_float(win_rate)},
                    })
                elif win_rate >= 65:
                    suggestions.append({
                        'type': 'filter',
                        'icon': '🎯',
                        'title': '信号质量评估',
                        'content': f'胜率 {win_rate:.1f}% 表现良好，可考虑保持当前策略参数',
                        'params': {'current_win_rate': _safe_float(win_rate)},
                    })

        _write_json(self, {
            'strategy': meta['table'],
            'strategy_cn': meta['cn'],
            'period': f'{start_date} ~ {end_date}',
            'suggestions': suggestions,
        })


# ── Stage 4: 方案持久化 + 代码导出 ────────────────────────────────────

_fusion_scheme_table_ready = False


def _ensure_fusion_scheme_table():
    """Idempotent CREATE for `cn_stock_fusion_scheme`."""
    global _fusion_scheme_table_ready
    if _fusion_scheme_table_ready:
        return
    if not mdb.checkTableIsExist('cn_stock_fusion_scheme'):
        mdb.executeSql("""
            CREATE TABLE IF NOT EXISTS `cn_stock_fusion_scheme` (
              `id` INT AUTO_INCREMENT PRIMARY KEY,
              `name` VARCHAR(200) NOT NULL COMMENT '方案名称',
              `description` VARCHAR(500) DEFAULT '' COMMENT '简要描述',
              `mode` VARCHAR(32) NOT NULL DEFAULT 'weighted_score',
              `scheme` JSON NOT NULL COMMENT 'v2 spec JSON',
              `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
              `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY `uk_name` (`name`),
              INDEX `idx_updated` (`updated_at`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        logger.info('[verify_fusion] 已创建表 cn_stock_fusion_scheme')
    _fusion_scheme_table_ready = True


def _render_fusion_code(spec: dict) -> str:
    """Generate a runnable Python script that POSTs the v2 spec back to /verify/fusion.

    The output is intentionally a thin client wrapper around the canonical API
    rather than a re-implementation — keeps the truth source in the backend.
    """
    mode = spec.get('mode', 'weighted_score')
    mode_cn = {'weighted_score': '加权打分', 'vote': '投票', 'condition_tree': '条件树',
               'rotation': '动量轮动'}.get(mode, mode)
    enabled = [k for k, d in (spec.get('dimensions') or {}).items()
               if d.get('enabled') and d.get('items')]
    dim_summary = ', '.join(f"{_DIM_LABEL.get(k, k)}({(spec['dimensions'][k] or {}).get('weight', 0)}%)"
                            for k in enabled) or '(无)'

    lines = [
        '"""Quantia 策略融合 v2 自动生成代码',
        '',
        f'模式: {mode_cn}',
        f'区间: {spec.get("start_date")} ~ {spec.get("end_date")}'
        f'，持仓 {spec.get("holding_days")} 天',
        f'启用维度: {dim_summary}',
        '"""',
        'import json',
        'import urllib.request',
        '',
        'API = "http://localhost:9988/quantia/api/verify/fusion"',
        '',
        'PAYLOAD = ' + json.dumps(spec, ensure_ascii=False, indent=2, default=str),
        '',
        'def run() -> dict:',
        '    req = urllib.request.Request(',
        '        API,',
        '        data=json.dumps(PAYLOAD).encode("utf-8"),',
        '        headers={"Content-Type": "application/json"},',
        '    )',
        '    with urllib.request.urlopen(req) as resp:',
        '        return json.loads(resp.read())',
        '',
        'if __name__ == "__main__":',
        '    result = run()',
        '    fr = result.get("fusion_result", {})',
        '    print(f"融合结果: sharpe={fr.get(\'sharpe\')} '
        'win_rate={fr.get(\'win_rate\')}% signals={fr.get(\'signal_count\')}")',
        '    for it in result.get("shapley", []):',
        '        print(f"  [{it.get(\'rank\')}] {it.get(\'name\')}: '
        'contrib={it.get(\'contrib\')}")',
    ]
    return '\n'.join(lines)


class FusionExportCodeHandler(webBase.BaseHandler):
    """POST /quantia/api/verify/fusion_export

    把前端的 v2 spec 转成可运行的 Python 脚本字符串（后端统一生成、便于以后扩展）。
    Body: 完整 v2 spec（同 /verify/fusion 请求体）。
    Response: { code: str, length: int }
    """

    def post(self):
        try:
            self._handle()
        except Exception:
            logger.error('fusion 代码导出异常', exc_info=True)
            _write_error(self, '服务器内部错误', 500)

    def _handle(self):
        try:
            body = json.loads(self.request.body)
        except (json.JSONDecodeError, TypeError):
            _write_error(self, '请求体必须为 JSON')
            return
        # 复用 spec 校验
        try:
            spec = _parse_v2_spec(body)
        except _ValidationError as e:
            _write_error(self, str(e))
            return
        # 把 date 还原为字符串，方便 JSON 序列化
        spec_out = dict(spec)
        spec_out['start_date'] = str(spec['start_date'])
        spec_out['end_date'] = str(spec['end_date'])
        # 去除前端不需要看到的内部字段（如果有）
        code = _render_fusion_code(spec_out)
        _write_json(self, {'code': code, 'length': len(code)})


class FusionSchemeSaveHandler(webBase.BaseHandler):
    """POST /quantia/api/verify/fusion_scheme

    保存/更新融合方案。Body: { name, description?, id?, ...v2 spec }
    - 不传 id：新建（按 name 唯一）
    - 传 id：按 id 更新
    """

    def post(self):
        try:
            self._handle()
        except Exception:
            logger.error('fusion 方案保存异常', exc_info=True)
            _write_error(self, '服务器内部错误', 500)

    def _handle(self):
        try:
            body = json.loads(self.request.body)
        except (json.JSONDecodeError, TypeError):
            _write_error(self, '请求体必须为 JSON')
            return
        name = str(body.get('name', '')).strip()
        if not name or len(name) > 200:
            _write_error(self, '方案名称必填，不超过 200 字符')
            return
        description = str(body.get('description', '')).strip()[:500]
        scheme_id = body.get('id')
        try:
            spec = _parse_v2_spec(body)
        except _ValidationError as e:
            _write_error(self, str(e))
            return
        spec_json = dict(spec)
        spec_json['start_date'] = str(spec['start_date'])
        spec_json['end_date'] = str(spec['end_date'])
        scheme_str = json.dumps(spec_json, ensure_ascii=False, default=str)

        _ensure_fusion_scheme_table()

        if scheme_id:
            scheme_id = int(scheme_id)
            mdb.executeSql("""
                UPDATE `cn_stock_fusion_scheme`
                SET `name` = %s, `description` = %s, `mode` = %s, `scheme` = %s
                WHERE `id` = %s
            """, (name, description, spec.get('mode'), scheme_str, scheme_id))
            _write_json(self, {'id': scheme_id, 'message': '已更新'})
            return

        # 新建（按 name 唯一）：若同名存在，转为更新
        rows = mdb.executeSqlFetch(
            "SELECT `id` FROM `cn_stock_fusion_scheme` WHERE `name` = %s LIMIT 1",
            (name,))
        if rows:
            existing_id = int(rows[0][0])
            mdb.executeSql("""
                UPDATE `cn_stock_fusion_scheme`
                SET `description` = %s, `mode` = %s, `scheme` = %s
                WHERE `id` = %s
            """, (description, spec.get('mode'), scheme_str, existing_id))
            _write_json(self, {'id': existing_id, 'message': '已覆盖同名方案'})
            return

        mdb.executeSql("""
            INSERT INTO `cn_stock_fusion_scheme`
                (`name`, `description`, `mode`, `scheme`)
            VALUES (%s, %s, %s, %s)
        """, (name, description, spec.get('mode'), scheme_str))
        rows = mdb.executeSqlFetch('SELECT LAST_INSERT_ID()')
        new_id = int(rows[0][0]) if rows else None
        _write_json(self, {'id': new_id, 'message': '已保存'})


class FusionSchemeListHandler(webBase.BaseHandler):
    """GET /quantia/api/verify/fusion_scheme/list

    返回最近 50 个方案的元数据（不含 scheme JSON 全量）。
    """

    def get(self):
        try:
            _ensure_fusion_scheme_table()
            rows = mdb.executeSqlFetch("""
                SELECT `id`, `name`, `description`, `mode`, `scheme`,
                       `created_at`, `updated_at`
                FROM `cn_stock_fusion_scheme`
                ORDER BY `updated_at` DESC
                LIMIT 50
            """)
            items = []
            for r in (rows or []):
                scheme_data = r[4]
                if isinstance(scheme_data, str):
                    try:
                        scheme_data = json.loads(scheme_data)
                    except json.JSONDecodeError:
                        scheme_data = None
                items.append({
                    'id': r[0],
                    'name': r[1],
                    'description': r[2] or '',
                    'mode': r[3],
                    'scheme': scheme_data,
                    'created_at': r[5].strftime('%Y-%m-%d %H:%M') if r[5] else '',
                    'updated_at': r[6].strftime('%Y-%m-%d %H:%M') if r[6] else '',
                })
            _write_json(self, {'items': items})
        except Exception:
            logger.error('fusion 方案列表异常', exc_info=True)
            _write_error(self, '服务器内部错误', 500)


class FusionSchemeDeleteHandler(webBase.BaseHandler):
    r"""DELETE /quantia/api/verify/fusion_scheme/(\d+)"""

    def delete(self, scheme_id):
        try:
            sid = int(scheme_id)
            _ensure_fusion_scheme_table()
            mdb.executeSql(
                'DELETE FROM `cn_stock_fusion_scheme` WHERE `id` = %s', (sid,))
            _write_json(self, {'id': sid, 'message': '已删除'})
        except Exception:
            logger.error('fusion 方案删除异常', exc_info=True)
            _write_error(self, '服务器内部错误', 500)

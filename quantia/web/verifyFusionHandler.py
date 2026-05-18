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

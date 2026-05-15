#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自定义回测 API Handler

支持用户指定股票代码、策略、回测时长来执行回测并返回结果。
"""

import json
import logging
import datetime
import numpy as np
import pandas as pd
import concurrent.futures
from abc import ABC
from tornado import gen
from tornado.ioloop import IOLoop
import quantia.web.base as webBase
import quantia.core.stockfetch as stf
import quantia.core.tablestructure as tbs
import quantia.core.indicator.calculate_indicator as idr
import quantia.core.pattern.pattern_recognitions as kpr
import quantia.lib.trade_time as trd
import quantia.lib.database as mdb
from quantia.core.backtest.rate_stats import ROUND_TRIP_COST_PCT
from quantia.web.utils import parse_int_list as _parse_int_list, json_default as _json_default

__author__ = 'Quantia'
__date__ = '2026/02/14'


# 可选回测周期
BACKTEST_PERIODS = {
    '1w': {'label': '1周', 'days': 5},
    '2w': {'label': '2周', 'days': 10},
    '1m': {'label': '1个月', 'days': 20},
    '3m': {'label': '3个月', 'days': 60},
    '6m': {'label': '6个月', 'days': 120},
    '1y': {'label': '1年', 'days': 250},
}

# 默认展示/统计的收益周期（交易日）
DEFAULT_HORIZONS = [1, 3, 5, 10, 20]
MAX_TABLE_HORIZON = 100

# 可选策略列表
STRATEGY_LIST = []
for s in tbs.TABLE_CN_STOCK_STRATEGIES:
    STRATEGY_LIST.append({
        'name': s['name'],
        'cn': s['cn'],
        'type': 'strategy'
    })
STRATEGY_LIST.append({
    'name': 'indicators_buy',
    'cn': '指标买入信号',
    'type': 'indicator'
})
STRATEGY_LIST.append({
    'name': 'indicators_sell',
    'cn': '指标卖出信号',
    'type': 'indicator'
})
STRATEGY_LIST.append({
    'name': tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE['name'],
    'cn': tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE['cn'],
    'type': 'strategy'
})


class GetBacktestConfigHandler(webBase.BaseHandler, ABC):
    """获取回测配置（可选周期、策略列表）"""
    def get(self):
        self.set_header('Content-Type', 'application/json;charset=UTF-8')
        response = {
            'periods': [{'value': k, 'label': v['label'], 'days': v['days']} for k, v in BACKTEST_PERIODS.items()],
            'strategies': STRATEGY_LIST,
            'default_horizons': DEFAULT_HORIZONS,
            'max_table_horizon': MAX_TABLE_HORIZON,
        }
        self.write(json.dumps(response, ensure_ascii=False))


class RunBacktestHandler(webBase.BaseHandler, ABC):
    """执行自定义回测"""
    def get(self):
        self.set_header('Content-Type', 'application/json;charset=UTF-8')

        code = self.get_argument("code", default=None, strip=True)
        strategy = self.get_argument("strategy", default=None, strip=True)
        period = self.get_argument("period", default="1m", strip=True)
        start_date = self.get_argument("start_date", default=None, strip=True)
        end_date = self.get_argument("end_date", default=None, strip=True)
        checkpoints = self.get_argument("checkpoints", default=None, strip=True)

        try:
            result = _run_backtest(code, strategy, period, start_date, end_date, checkpoints)
            self.write(json.dumps(result, ensure_ascii=False, default=_json_default))
        except Exception as e:
            logging.error(f"RunBacktestHandler处理异常", exc_info=True)
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}, ensure_ascii=False))


class RunBatchBacktestHandler(webBase.BaseHandler, ABC):
    """批量回测：对某策略在指定时间段内的所有选股记录进行回测"""
    @gen.coroutine
    def get(self):
        self.set_header('Content-Type', 'application/json;charset=UTF-8')

        strategy = self.get_argument("strategy", default=None, strip=True)
        period = self.get_argument("period", default="1m", strip=True)
        limit = self.get_argument("limit", default="30", strip=True)
        horizons = self.get_argument("horizons", default=None, strip=True)
        success_days = self.get_argument("success_days", default=None, strip=True)

        if not strategy:
            self.set_status(400)
            self.write(json.dumps({"error": "缺少 strategy 参数"}, ensure_ascii=False))
            return

        try:
            # 批量回测可能耗时较长，offload到线程池避免阻塞IOLoop
            result = yield IOLoop.current().run_in_executor(
                None, lambda: _run_batch_backtest(strategy, period, int(limit),
                                                   horizons=horizons, success_days=success_days))
            self.write(json.dumps(result, ensure_ascii=False, default=_json_default))
        except Exception as e:
            logging.error(f"RunBatchBacktestHandler处理异常", exc_info=True)
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}, ensure_ascii=False))


# _parse_int_list 和 _json_default 已抽取到 quantia.web.utils


def _run_backtest(code, strategy, period, start_date_str, end_date_str, checkpoints_csv=None):
    """
    对单只股票执行回测

    参数：
        code: 股票代码（如 "000001"）
        strategy: 策略名称（如 "cn_stock_strategy_enter"）或 None（只看收益）
        period: 回测周期（"1w"/"2w"/"1m"/"3m"/"6m"/"1y"）
        start_date_str: 起始日期 YYYY-MM-DD（可选）
        end_date_str: 结束日期 YYYY-MM-DD（可选）

    返回：
        {
            code, name, period,
            buy_date, buy_price,
            returns: [{days, rate, price}, ...],  # 各周期收益率
            strategy_result: True/False,  # 策略是否命中
            indicators: {kdjk, rsi_6, ...}  # 关键指标值
        }
    """
    if not code:
        return {"error": "缺少股票代码参数"}

    period_info = BACKTEST_PERIODS.get(period, BACKTEST_PERIODS['1m'])
    max_days = period_info['days']

    checkpoints = _parse_int_list(checkpoints_csv, default=DEFAULT_HORIZONS, min_value=1, max_value=250, max_items=30)

    # 计算日期范围
    now = datetime.datetime.now()
    years = stf.HIST_DATA_DEFAULT_YEARS
    cache_start, _ = trd.get_trade_hist_interval(now, years)
    cache_end = now.strftime("%Y%m%d")

    # 读取历史数据
    hist = stf.read_stock_hist_from_cache(code, cache_start, cache_end)
    if hist is None or len(hist) == 0:
        return {"error": f"股票 {code} 无缓存数据，请先执行数据获取"}

    # 确定买入日期
    if start_date_str:
        buy_date = start_date_str
    else:
        # 默认使用有足够后续数据的日期（倒数第 max_days+1 天）
        # 避免选最后一天导致 "之后无足够交易数据" 错误
        idx = max(0, len(hist) - max_days - 1)
        buy_date = hist['date'].iloc[idx]

    # 获取买入日及之后的数据
    mask = hist['date'] >= buy_date
    future_data = hist.loc[mask].head(max_days + 2)  # +2: 信号日(T) + 执行日(T+1) + max_days

    if len(future_data) <= 1:
        return {"error": f"买入日 {buy_date} 之后无足够交易数据"}

    # 修正: 使用T+1开盘价作为买入价（信号在T日收盘后产生，最早T+1开盘买入）
    if len(future_data) >= 2 and 'open' in future_data.columns:
        buy_price = future_data.iloc[1]['open']  # T+1 开盘价
        buy_date_actual = future_data.iloc[1]['date']  # 实际买入日
        # 涨停检测: T+1开盘涨停则无法买入
        t_close = future_data.iloc[0]['close']
        if buy_price > 0 and t_close > 0 and (buy_price - t_close) / t_close >= 0.095:
            return {"error": f"买入日 {buy_date_actual} 开盘涨停，无法买入"}
        future_for_calc = future_data.iloc[1:]  # 从T+1开始
    else:
        buy_price = future_data.iloc[0]['close']
        buy_date_actual = future_data.iloc[0]['date']
        future_for_calc = future_data

    # 防御：买入价为0或异常时无法计算收益率
    if buy_price is None or buy_price <= 0:
        return {"error": f"买入价异常({buy_price})，无法计算收益"}

    # 计算各天收益率（扣除交易成本）
    returns = []
    for days in checkpoints:
        if days > max_days:
            break
        if days < len(future_for_calc):
            sell_price = future_for_calc.iloc[days]['close']
            raw_rate = round(100 * (sell_price - buy_price) / buy_price, 2)
            rate = round(raw_rate - ROUND_TRIP_COST_PCT, 2)
            sell_date = future_for_calc.iloc[days]['date']
            returns.append({
                'days': days,
                'rate': rate,
                'raw_rate': raw_rate,  # 未扣费收益（供参考）
                'price': round(float(sell_price), 2),
                'date': sell_date
            })

    # 计算区间最高/最低
    if len(future_for_calc) > 1:
        high_price = float(future_for_calc['high'].max())
        low_price = float(future_for_calc['low'].min())
        max_return = round(100 * (high_price - buy_price) / buy_price - ROUND_TRIP_COST_PCT, 2)
        max_drawdown = round(100 * (low_price - buy_price) / buy_price, 2)
    else:
        max_return = 0
        max_drawdown = 0

    # 策略检测
    strategy_result = None
    if strategy:
        strategy_result = _check_strategy(strategy, code, hist, buy_date)

    # 计算关键指标
    indicators = _calc_key_indicators(hist, buy_date)

    # 获取股票名称
    stock_name = _get_stock_name(code)

    result = {
        'code': code,
        'name': stock_name,
        'period': period_info['label'],
        'buy_date': buy_date_actual,
        'buy_price': round(float(buy_price), 2),
        'returns': returns,
        'checkpoints': checkpoints,
        'max_return': max_return,
        'max_drawdown': max_drawdown,
        'strategy': strategy,
        'strategy_result': strategy_result,
        'indicators': indicators,
        'data_points': len(future_data) - 1,
    }
    return result


def _run_batch_backtest(strategy_name, period, limit=30, horizons=None, success_days=None):
    """
    批量回测：从策略表读取历史选股记录，计算各周期收益

    返回：
        {
            strategy, period, total, success_count, success_rate,
            avg_returns: {1d, 5d, 10d, 20d},
            details: [{date, stock_count, avg_rate, success_rate}, ...]
        }
    """
    period_info = BACKTEST_PERIODS.get(period, BACKTEST_PERIODS['1m'])
    max_days = period_info['days']

    horizon_list = _parse_int_list(horizons, default=DEFAULT_HORIZONS, min_value=1, max_value=MAX_TABLE_HORIZON, max_items=12)
    if not horizon_list:
        horizon_list = list(DEFAULT_HORIZONS)

    success_days_list = _parse_int_list(success_days, default=None, min_value=1, max_value=MAX_TABLE_HORIZON, max_items=1)
    if success_days_list:
        success_day = success_days_list[0]
    else:
        success_day = min(max_days, max(horizon_list))

    # 查找策略对应的表名和函数
    table_name = None
    strategy_cn = strategy_name
    strategy_func = None
    for s in tbs.TABLE_CN_STOCK_STRATEGIES:
        if s['name'] == strategy_name:
            table_name = s['name']
            strategy_cn = s['cn']
            strategy_func = s['func']
            break
    if table_name is None:
        if strategy_name == 'indicators_buy':
            table_name = tbs.TABLE_CN_STOCK_INDICATORS_BUY['name']
            strategy_cn = '指标买入信号'
        elif strategy_name == 'indicators_sell':
            table_name = tbs.TABLE_CN_STOCK_INDICATORS_SELL['name']
            strategy_cn = '指标卖出信号'
        elif strategy_name == tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE['name']:
            table_name = tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE['name']
            strategy_cn = tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE['cn']
        else:
            return {"error": f"未知策略: {strategy_name}"}

    if not mdb.checkTableIsExist(table_name):
        # 策略表不存在时，尝试从缓存数据动态计算
        if strategy_func is not None:
            return _compute_batch_backtest_onthefly(
                strategy_func, strategy_cn, strategy_name, period_info, limit,
                horizon_list=horizon_list, success_day=success_day,
            )
        else:
            return {"error": f"策略表 {table_name} 不存在，请先运行数据分析任务（streaming_analysis_job.py）"}

    # 读取策略表中有回测数据的记录
    try:
        # 获取每日汇总（支持用户自定义 horizon_list）
        select_avgs = []
        for h in horizon_list:
            select_avgs.append(f"ROUND(AVG(`rate_{h}`), 2) as avg_{h}d")
        rate_col = f'rate_{min(success_day, MAX_TABLE_HORIZON)}'
        sql = f"""SELECT `date`, COUNT(*) as stock_count,
                  {', '.join(select_avgs)},
                  SUM(CASE WHEN `{rate_col}` > 0 THEN 1 ELSE 0 END) as success_count
                  FROM `{table_name}`
                  WHERE `rate_1` IS NOT NULL
                  GROUP BY `date` ORDER BY `date` DESC LIMIT {limit}"""
        data = pd.read_sql(sql=sql, con=mdb.engine())
    except Exception as e:
        # 查询失败（可能是表结构不匹配），尝试动态计算
        if strategy_func is not None:
            logging.warning(f"策略表 {table_name} 查询失败，切换到动态计算模式: {e}")
            return _compute_batch_backtest_onthefly(
                strategy_func, strategy_cn, strategy_name, period_info, limit,
                horizon_list=horizon_list, success_day=success_day,
            )
        return {"error": f"查询失败: {e}"}

    if data is None or len(data) == 0:
        # 表存在但无回测数据，尝试动态计算
        if strategy_func is not None:
            return _compute_batch_backtest_onthefly(
                strategy_func, strategy_cn, strategy_name, period_info, limit,
                horizon_list=horizon_list, success_day=success_day,
            )
        return {"error": "无回测数据，请先执行策略计算和回测"}

    # 汇总统计
    total_stocks = int(data['stock_count'].sum())
    total_success = int(data['success_count'].sum())
    overall_success_rate = round(100 * total_success / total_stocks, 2) if total_stocks > 0 else 0

    details = []
    for _, row in data.iterrows():
        sc = int(row['stock_count'])
        succ = int(row['success_count'])
        avg_map = {}
        for h in horizon_list:
            avg_map[f'avg_{h}d'] = row.get(f'avg_{h}d')
        details.append({
            'date': row['date'],
            'stock_count': sc,
            'success_count': succ,
            'success_rate': round(100 * succ / sc, 2) if sc > 0 else 0,
            **avg_map,
        })

    avg_returns = {}
    for h in horizon_list:
        col = f'avg_{h}d'
        avg_returns[f'{h}d'] = round(float(data[col].mean()), 2) if (col in data.columns and not data[col].isna().all()) else 0

    result = {
        'strategy': strategy_cn,
        'strategy_name': strategy_name,
        'period': period_info['label'],
        'horizons': horizon_list,
        'success_days': success_day,
        'total_stocks': total_stocks,
        'total_days': len(data),
        'success_count': total_success,
        'success_rate': overall_success_rate,
        'avg_returns': avg_returns,
        'details': details,
    }
    return result


def _compute_batch_backtest_onthefly(strategy_func, strategy_cn, strategy_name, period_info, limit, horizon_list=None, success_day=None):
    """
    策略表不存在时，从缓存数据动态计算批量回测结果。

    流程：
    1. 获取所有股票代码
    2. 获取最近 limit 个交易日
    3. 并行遍历所有股票：加载缓存 → 逐日检测策略 → 计算收益
    4. 聚合为与数据库查询相同格式的结果
    """
    import quantia.lib.trade_time as trd_mod

    max_days = period_info['days']

    horizon_list = list(horizon_list) if horizon_list else list(DEFAULT_HORIZONS)
    horizon_list = [int(h) for h in horizon_list if 1 <= int(h) <= MAX_TABLE_HORIZON]
    horizon_list = sorted(set(horizon_list))
    if not horizon_list:
        horizon_list = list(DEFAULT_HORIZONS)

    if success_day is None:
        success_day = min(max_days, max(horizon_list))
    rate_days = min(int(success_day), MAX_TABLE_HORIZON)

    # 1. 获取股票代码列表
    try:
        spot_table = tbs.TABLE_CN_STOCK_SPOT['name']
        if not mdb.checkTableIsExist(spot_table):
            return {"error": "股票基础数据表不存在，请先运行数据获取任务（fetch_data_job.py）"}
        stocks_df = pd.read_sql(f"SELECT `code` FROM `{spot_table}`", mdb.engine())
        stock_codes = stocks_df['code'].tolist()
    except Exception as e:
        return {"error": f"获取股票列表失败: {e}"}

    if not stock_codes:
        return {"error": "无股票数据"}

    # 2. 获取最近的交易日列表
    now = datetime.datetime.now()
    trade_dates = []
    d = now.date()
    for _ in range(limit * 3 + 30):
        d = trd_mod.get_one_previous_trade_date(d)
        if d not in trade_dates:
            trade_dates.append(d)
        if len(trade_dates) >= limit:
            break

    if not trade_dates:
        return {"error": "无法获取交易日列表"}

    # 3. 计算缓存日期范围
    years = stf.HIST_DATA_DEFAULT_YEARS
    cache_start, _ = trd.get_trade_hist_interval(now, years)
    cache_end = now.strftime("%Y%m%d")

    # 4. 初始化每日结果容器
    date_results = {}
    for d in trade_dates:
        ds = d.strftime("%Y-%m-%d")
        date_results[ds] = {
            'stock_count': 0,
            'success_count': 0,
            'rates': {h: [] for h in horizon_list},
        }

    # 5. 定义单只股票处理函数
    func_name = strategy_func.__name__

    def _process_stock(code):
        """加载单只股票缓存，检测策略命中，计算收益"""
        results = []
        hist = stf.read_stock_hist_from_cache(code, cache_start, cache_end)
        if hist is None or len(hist) < 30:
            return results

        for trade_date in trade_dates:
            date_str = trade_date.strftime("%Y-%m-%d")
            stock = (trade_date, code)
            try:
                if func_name == 'check_high_tight':
                    matched = strategy_func(stock, hist, date=trade_date, istop=False)
                else:
                    matched = strategy_func(stock, hist, date=trade_date)
                if not matched:
                    continue
            except Exception:
                logging.debug(f"批量回测策略检测异常：{code} {date_str}", exc_info=True)
                continue

            # 计算各周期收益率（使用T+1开盘价买入，扣除交易成本）
            mask = hist['date'] >= date_str
            future = hist.loc[mask]
            if len(future) < 3:  # 至少需要T, T+1, T+2
                continue
            # T+1开盘价作为买入价
            if 'open' in future.columns:
                buy_price = float(future.iloc[1]['open'])
                # 涨停检测
                t_close = float(future.iloc[0]['close'])
                if buy_price > 0 and t_close > 0 and (buy_price - t_close) / t_close >= 0.095:
                    continue  # 涨停无法买入
                future_from_buy = future.iloc[1:]  # 从T+1开始
            else:
                buy_price = float(future.iloc[0]['close'])
                future_from_buy = future
            if buy_price <= 0:
                continue
            rates = {}
            for days in horizon_list:
                if days < len(future_from_buy):
                    sell_price = float(future_from_buy.iloc[days]['close'])
                    raw_rate = round(100.0 * (sell_price - buy_price) / buy_price, 2)
                    rates[days] = round(raw_rate - ROUND_TRIP_COST_PCT, 2)
            results.append((date_str, rates))
        return results

    # 6. 并行处理所有股票（分批处理，降低内存峰值）
    logging.info(f"批量回测动态计算：{strategy_cn}，{len(stock_codes)} 只股票，{len(trade_dates)} 个交易日")
    _BATCH_SIZE = 500  # 每批处理的股票数
    _MAX_WORKERS = min(4, max(1, len(stock_codes) // 200))
    for batch_start in range(0, len(stock_codes), _BATCH_SIZE):
        batch = stock_codes[batch_start:batch_start + _BATCH_SIZE]
        batch_idx = batch_start // _BATCH_SIZE + 1
        total_batches = (len(stock_codes) + _BATCH_SIZE - 1) // _BATCH_SIZE
        logging.info(f"批量回测进度：批次 {batch_idx}/{total_batches}（{len(batch)} 只股票）")
        with concurrent.futures.ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
            future_map = {executor.submit(_process_stock, code): code for code in batch}
            for future in concurrent.futures.as_completed(future_map):
                try:
                    results = future.result()
                    for date_str, rates in results:
                        if date_str not in date_results:
                            continue
                        dr = date_results[date_str]
                        dr['stock_count'] += 1
                        for days in horizon_list:
                            if days in rates:
                                dr['rates'][days].append(rates[days])
                        if rate_days in rates and rates[rate_days] > 0:
                            dr['success_count'] += 1
                except Exception:
                    logging.warning(f"批量回测线程结果异常：{future_map.get(future, '?')}", exc_info=True)
                    continue
        # 线程池退出后清理残留 DB 连接
        try:
            import quantia.lib.database as _mdb
            _mdb.close_thread_connection()
        except Exception:
            pass

    # 7. 聚合结果
    details = []
    total_stocks = 0
    total_success = 0
    all_rates = {h: [] for h in horizon_list}

    for d in trade_dates:
        ds = d.strftime("%Y-%m-%d")
        dr = date_results[ds]
        sc = dr['stock_count']
        if sc == 0:
            continue
        total_stocks += sc
        total_success += dr['success_count']
        avg_map = {}
        for h in horizon_list:
            vals = dr['rates'][h]
            avg_map[f'avg_{h}d'] = round(sum(vals) / len(vals), 2) if vals else None
            all_rates[h].extend(vals)

        details.append({
            'date': d,
            'stock_count': sc,
            'success_count': dr['success_count'],
            'success_rate': round(100.0 * dr['success_count'] / sc, 2) if sc > 0 else 0,
            **avg_map,
        })

    if not details:
        return {"error": "无回测数据：该策略在最近交易日无选股记录（已从缓存动态计算）"}

    overall_sr = round(100.0 * total_success / total_stocks, 2) if total_stocks > 0 else 0

    avg_returns = {}
    for h in horizon_list:
        vals = all_rates[h]
        avg_returns[f'{h}d'] = round(sum(vals) / len(vals), 2) if vals else 0

    return {
        'strategy': f'{strategy_cn}（实时计算）',
        'strategy_name': strategy_name,
        'period': period_info['label'],
        'horizons': horizon_list,
        'success_days': rate_days,
        'total_stocks': total_stocks,
        'total_days': len(details),
        'success_count': total_success,
        'success_rate': overall_sr,
        'avg_returns': avg_returns,
        'details': details,
    }


def _check_strategy(strategy_name, code, hist_data, buy_date):
    """检测某策略是否在买入日命中"""
    try:
        date_obj = datetime.datetime.strptime(buy_date, "%Y-%m-%d").date() if isinstance(buy_date, str) else buy_date
        stock = (date_obj, code)

        for s in tbs.TABLE_CN_STOCK_STRATEGIES:
            if s['name'] == strategy_name:
                return bool(s['func'](stock, hist_data, date=date_obj))

        return None  # 不支持/未找到
    except Exception as e:
        logging.debug(f"策略检测异常：{code} {strategy_name} - {e}")
        return None


def _calc_key_indicators(hist_data, buy_date):
    """计算买入日的关键技术指标"""
    try:
        result = idr.get_indicators(hist_data, end_date=buy_date, threshold=1, calc_threshold=90)
        if result is None or len(result) == 0:
            return {}

        row = result.iloc[-1]
        return {
            'kdjk': _safe_round(row.get('kdjk')),
            'kdjd': _safe_round(row.get('kdjd')),
            'rsi_6': _safe_round(row.get('rsi_6')),
            'macd': _safe_round(row.get('macd')),
            'cci': _safe_round(row.get('cci')),
            'cr': _safe_round(row.get('cr')),
            'wr_6': _safe_round(row.get('wr_6')),
            'vr': _safe_round(row.get('vr')),
            'atr': _safe_round(row.get('atr')),
        }
    except Exception:
        logging.debug("计算关键技术指标异常", exc_info=True)
        return {}


def _safe_round(val, decimals=2):
    """安全取整"""
    if val is None or (isinstance(val, float) and (np.isnan(val) or np.isinf(val))):
        return None
    return round(float(val), decimals)


def _get_stock_name(code):
    """通过数据库查询股票名称"""
    try:
        table = tbs.TABLE_CN_STOCK_SPOT['name']
        if mdb.checkTableIsExist(table):
            sql = f"SELECT `name` FROM `{table}` WHERE `code` = %s LIMIT 1"
            result = pd.read_sql(sql, mdb.engine(), params=(code,))
            if result is not None and len(result) > 0:
                return result.iloc[0]['name']
    except Exception:
        logging.debug(f"查询股票名称异常：{code}", exc_info=True)
    return code

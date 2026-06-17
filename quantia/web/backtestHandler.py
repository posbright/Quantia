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


def _list_custom_strategies():
    """读取用户自定义策略（cn_stock_strategy_code，非归档）→ 单股回测可选项。

    返回 [{'name': 'custom_<id>', 'cn': <名称>, 'type': 'custom'}, ...]。
    仅读 MySQL；表不存在 / 读取失败时返回空列表（不影响内置策略可用性）。
    """
    out = []
    try:
        if not mdb.checkTableIsExist('cn_stock_strategy_code'):
            return out
        rows = mdb.executeSqlFetch(
            "SELECT id, name FROM cn_stock_strategy_code "
            "WHERE (status IS NULL OR status != 'archived') ORDER BY id DESC")
    except Exception:
        logging.debug("读取自定义策略列表异常", exc_info=True)
        return out
    for r in rows or []:
        sid = r[0]
        name = (r[1] or '').strip() or f'自定义策略#{sid}'
        out.append({'name': f'custom_{sid}', 'cn': name, 'type': 'custom'})
    return out


class GetBacktestConfigHandler(webBase.BaseHandler, ABC):
    """获取回测配置（可选周期、策略列表）"""
    def get(self):
        self.set_header('Content-Type', 'application/json;charset=UTF-8')
        # 内置策略 + 用户自定义策略（custom_<id>）。自定义部分动态查询，
        # 保证新建/归档后即时生效；查询失败时仅退化为内置列表。
        strategies = list(STRATEGY_LIST) + _list_custom_strategies()
        response = {
            'periods': [{'value': k, 'label': v['label'], 'days': v['days']} for k, v in BACKTEST_PERIODS.items()],
            'strategies': strategies,
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


# ============================================================================
# 单股区间买卖点回测（见 document/backtest/single_stock_backtest_dev_plan.md）
# ============================================================================

# 历史表名（避免依赖 tablestructure 中可能未部署的列定义）
SINGLE_BACKTEST_HISTORY_TABLE = 'cn_stock_single_backtest_history'

# 策略 → 推荐叠加指标映射（键为完整表名 cn_stock_strategy_*）
_ALL_OVERLAYS = ['ma5', 'ma10', 'ma20', 'ma30', 'ma60', 'ma250', 'boll', 'vol', 'macd', 'kdj', 'rsi']
STRATEGY_OVERLAY_MAP = {
    'cn_stock_strategy_keep_increasing': ['ma5', 'ma10', 'ma20', 'ma30', 'ma60'],
    'cn_stock_strategy_backtrace_ma250': ['ma250', 'ma20'],
    'cn_stock_strategy_enter': ['vol', 'ma20', 'macd'],
    'cn_stock_strategy_low_backtrace_increase': ['vol', 'ma20', 'macd'],
    'cn_stock_strategy_parking_apron': ['ma20', 'vol'],
    'cn_stock_strategy_breakthrough_platform': ['ma20', 'vol'],
    'cn_stock_strategy_high_tight_flag': ['ma20', 'vol'],
    'cn_stock_strategy_turtle_trade': ['ma20', 'ma60', 'vol'],
    'cn_stock_strategy_low_atr': ['ma20', 'macd'],
    'cn_stock_strategy_climax_limitdown': ['vol', 'macd'],
    'cn_stock_strategy_trend_pullback': ['ma20', 'ma60', 'macd'],
    'cn_stock_strategy_oversold_rebound': ['kdj', 'rsi', 'macd'],
    'cn_stock_strategy_breakout_confirm': ['ma20', 'vol', 'macd'],
    'indicators_buy': ['kdj', 'rsi', 'macd'],
    'indicators_sell': ['kdj', 'rsi', 'macd'],
}
_DEFAULT_OVERLAY = ['ma20']

_RISK_FREE_RATE = 0.03  # 年化无风险利率

_SINGLE_INDICATOR_TABLE_MAP = {
    'indicators_buy': (tbs.TABLE_CN_STOCK_INDICATORS_BUY['name'], '指标买入信号'),
    'indicators_sell': (tbs.TABLE_CN_STOCK_INDICATORS_SELL['name'], '指标卖出信号'),
}

# ── 单股回测退出逻辑分类（修复 A：入场/退出解耦）─────────────────────────────
# 事件型策略：入场信号仅在特定交易日成立（放量、突破、反弹、跌停当天等），
# 其入场条件**不可**复用为"持仓条件"——否则买入次日条件必然不成立，
# 会把回测退化成 T+1 一日交易，胜率/收益失真。这类策略默认走规则退出
# （止损 / 止盈 / 最大持仓），与入场条件解耦。
_EVENT_STRATEGIES = frozenset({
    'cn_stock_strategy_enter',                 # 放量上涨
    'cn_stock_strategy_parking_apron',         # 停机坪
    'cn_stock_strategy_breakthrough_platform', # 突破平台
    'cn_stock_strategy_high_tight_flag',       # 高而窄的旗形
    'cn_stock_strategy_climax_limitdown',      # 放量跌停
    'cn_stock_strategy_trend_pullback',        # 趋势回调
    'cn_stock_strategy_oversold_rebound',      # 超跌反弹
    'cn_stock_strategy_breakout_confirm',      # 突破确认
    'indicators_buy',                          # 指标买入信号（事件型）
    'indicators_sell',                         # 指标卖出信号（事件型）
})
# 状态型策略（均线多头、海龟、低ATR、回踩年线、无大幅回撤）入场条件可连续多日
# 成立，复用入场条件做持仓判断是合理的（条件消失即离场），仍走 strategy_signal。

# 事件型策略的默认规则退出参数（按收盘价逐日判定）
_EVENT_EXIT_STOP_LOSS = 0.08    # 止损：跌破买入价 8%
_EVENT_EXIT_TAKE_PROFIT = 0.15  # 止盈：涨过买入价 15%
_EVENT_EXIT_MAX_HOLD = 20       # 最大持仓交易日


def _is_index_code(code):
    """指数代码识别：6 位指数（000300/399xxx 等）须走 load_benchmark_data，本功能仅支持个股。"""
    if not code:
        return False
    c = str(code).strip()
    # 上证指数 000001 与平安银行 000001 同号，靠前缀难以区分；这里仅拦截常见指数段
    if c.startswith('399') or c.startswith('880'):
        return True
    if c in ('000300', '000016', '000905', '000852', '000688', '000010', '000009'):
        return True
    return False


def _price_limit_ratio(code, name):
    """按板块 / ST 返回单日涨跌停比例（小数）。主板 10%、创业板/科创板 20%、ST 5%、北交所 30%。"""
    code = str(code or '').strip()
    name = str(name or '')
    if 'ST' in name.upper() or '退' in name:
        return 0.05
    # 北交所
    if code.startswith('8') or code.startswith('4') or code.startswith('92'):
        return 0.30
    # 创业板 300/301、科创板 688/689
    if code.startswith('300') or code.startswith('301') or code.startswith('688') or code.startswith('689'):
        return 0.20
    return 0.10


def _cache_covers_range(hist, start_date_str, end_date_str):
    """缓存历史是否覆盖回测区间末（修复 C：判断是否需要 spot 补全）。

    只要缓存最新日期 < 区间末，就视为不足，触发 cn_stock_spot 补全。
    缓存为空也视为不足。
    """
    if hist is None or len(hist) == 0 or 'date' not in getattr(hist, 'columns', []):
        return False
    try:
        h = hist['date']
        if not pd.api.types.is_datetime64_any_dtype(h):
            h = pd.to_datetime(h)
        cache_max = h.max()
        end_ts = pd.Timestamp(str(end_date_str).replace('-', '')) \
            if '-' not in str(end_date_str) else pd.Timestamp(end_date_str)
        # 允许 3 个自然日宽松度（周末/节假日缓存可能停在周五）
        return cache_max >= (end_ts - pd.Timedelta(days=3))
    except Exception:
        return True  # 判断异常时不强制补全，沿用缓存


def _resolve_single_strategy(strategy_name):
    """解析策略：返回 (func, cn) 或 (None, None)。仅支持 TABLE_CN_STOCK_STRATEGIES 的 check() 策略。"""
    for s in tbs.TABLE_CN_STOCK_STRATEGIES:
        if s.get('name') == strategy_name:
            return s.get('func'), s.get('cn', strategy_name)
    return None, None


def _normalize_backtest_date(value):
    """将日期输入统一归一化成 YYYY-MM-DD，兼容 YYYYMMDD / datetime / Timestamp。"""
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.strftime('%Y-%m-%d')
    text = str(value).strip()
    if not text:
        return None
    try:
        return pd.Timestamp(text).strftime('%Y-%m-%d')
    except Exception:
        return text


def _load_single_indicator_signal_dates(strategy_name, code, start_date_str, end_date_str):
    """读取单股区间内的指标信号日期集合（一次查库，供逐日 O(1) 匹配）。"""
    mapping = _SINGLE_INDICATOR_TABLE_MAP.get(strategy_name)
    if not mapping:
        return None
    table_name, _ = mapping
    if not mdb.checkTableIsExist(table_name):
        return None
    start_date_norm = _normalize_backtest_date(start_date_str)
    end_date_norm = _normalize_backtest_date(end_date_str)
    if not start_date_norm or not end_date_norm:
        return None
    try:
        rows = mdb.executeSqlFetch(
            f"SELECT `date` FROM `{table_name}` "
            "WHERE `code`=%s AND `date` >= %s AND `date` <= %s "
            "ORDER BY `date` ASC",
            (code, start_date_norm, end_date_norm),
        )
    except Exception:
        logging.debug("读取指标信号日期异常: %s %s", strategy_name, code, exc_info=True)
        return None

    dates = set()
    for r in rows or []:
        raw = r['date'] if isinstance(r, dict) else r[0]
        try:
            dates.add(pd.Timestamp(raw).date())
        except Exception:
            continue
    return dates


def _resolve_single_strategy_with_indicator(strategy_name, code=None, start_date_str=None, end_date_str=None):
    """解析单股回测策略：支持内置 check() + indicators_buy/sell。"""
    func, cn = _resolve_single_strategy(strategy_name)
    if func is not None:
        return func, cn

    mapping = _SINGLE_INDICATOR_TABLE_MAP.get(strategy_name)
    if not mapping:
        return None, None
    _table_name, cn = mapping
    if not (code and start_date_str and end_date_str):
        return None, None

    signal_dates = _load_single_indicator_signal_dates(strategy_name, code, start_date_str, end_date_str)
    if signal_dates is None:
        return None, None

    def _indicator_match(_stock, _hist, date=None, **_kw):
        if date is None:
            return False
        try:
            return pd.Timestamp(date).date() in signal_dates
        except Exception:
            return False

    return _indicator_match, cn


def _resolve_custom_strategy(strategy_key):
    """解析自定义策略 custom_<id> → (strategy_id:int, name:str) 或 (None, None)。

    仅读 cn_stock_strategy_code（非归档）。不存在 / 已归档 / 读取失败 → (None, None)。
    """
    try:
        sid = int(str(strategy_key).replace('custom_', ''))
    except (TypeError, ValueError):
        return None, None
    try:
        rows = mdb.executeSqlFetch(
            "SELECT name FROM cn_stock_strategy_code WHERE id=%s AND "
            "(status IS NULL OR status != 'archived')", (sid,))
    except Exception:
        logging.debug("读取自定义策略名异常: id=%s", sid, exc_info=True)
        return None, None
    if not rows:
        return None, None
    return sid, ((rows[0][0] or '').strip() or f'自定义策略#{sid}')


def _strategy_hit(strategy_func, stock, hist, d):
    """在日期 d 调用策略函数，命中返回 True。兼容需要 istop 的策略。"""
    try:
        matched = strategy_func(stock, hist, date=d)
    except TypeError:
        try:
            matched = strategy_func(stock, hist, date=d, istop=False)
        except Exception:
            return False
    except Exception:
        return False
    return bool(matched)


def _series_or_none(values):
    """numpy/Series → 含 None 的纯 Python list（NaN/inf → None），满足 JSON + DB 有限值要求。"""
    out = []
    for v in values:
        if v is None:
            out.append(None)
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            out.append(None)
            continue
        if np.isnan(fv) or np.isinf(fv):
            out.append(None)
        else:
            out.append(round(fv, 3))
    return out


def _build_kline_and_indicators(hist, recommended, available):
    """基于完整历史构建 K 线数组 + 指标序列（从历史起点对齐，前期不足周期补 None）。"""
    h = hist.copy()
    if not pd.api.types.is_datetime64_any_dtype(h['date']):
        h['date'] = pd.to_datetime(h['date'])
    h = h.sort_values('date').reset_index(drop=True)

    dates = h['date'].dt.strftime('%Y-%m-%d').tolist()
    kline = []
    for _, r in h.iterrows():
        kline.append({
            'date': r['date'].strftime('%Y-%m-%d'),
            'open': _safe_round(r.get('open')),
            'close': _safe_round(r.get('close')),
            'low': _safe_round(r.get('low')),
            'high': _safe_round(r.get('high')),
            'volume': _safe_round(r.get('volume'), 0),
        })

    close = h['close'].astype('float64')
    ma = {}
    for p in (5, 10, 20, 30, 60, 250):
        ma[str(p)] = _series_or_none(close.rolling(window=p, min_periods=p).mean().values)

    boll = {'up': [None] * len(h), 'mid': [None] * len(h), 'dn': [None] * len(h)}
    macd = {'dif': [None] * len(h), 'dea': [None] * len(h), 'hist': [None] * len(h)}
    kdj = {'k': [None] * len(h), 'd': [None] * len(h), 'j': [None] * len(h)}
    rsi = {'6': [None] * len(h), '12': [None] * len(h), '24': [None] * len(h)}
    try:
        ind = idr.get_indicators(h, end_date=None, threshold=1, calc_threshold=None)
        if ind is not None and len(ind) > 0:
            ind = ind.copy()
            if not pd.api.types.is_datetime64_any_dtype(ind['date']):
                ind['date'] = pd.to_datetime(ind['date'])
            ind_map = {d.strftime('%Y-%m-%d'): row for d, row in zip(ind['date'], ind.to_dict('records'))}
            for i, ds in enumerate(dates):
                row = ind_map.get(ds)
                if not row:
                    continue
                boll['up'][i] = _safe_round(row.get('boll_ub'), 3)
                boll['mid'][i] = _safe_round(row.get('boll'), 3)
                boll['dn'][i] = _safe_round(row.get('boll_lb'), 3)
                macd['dif'][i] = _safe_round(row.get('macd'), 3)
                macd['dea'][i] = _safe_round(row.get('macds'), 3)
                macd['hist'][i] = _safe_round(row.get('macdh'), 3)
                kdj['k'][i] = _safe_round(row.get('kdjk'), 3)
                kdj['d'][i] = _safe_round(row.get('kdjd'), 3)
                kdj['j'][i] = _safe_round(row.get('kdjj'), 3)
                rsi['6'][i] = _safe_round(row.get('rsi_6'), 3)
                rsi['12'][i] = _safe_round(row.get('rsi_12'), 3)
                rsi['24'][i] = _safe_round(row.get('rsi_24'), 3)
    except Exception:
        logging.debug('单股回测指标计算异常', exc_info=True)

    indicators = {
        'recommended': recommended,
        'available': available,
        'ma': ma,
        'boll': boll,
        'macd': macd,
        'kdj': kdj,
        'rsi': rsi,
    }
    return kline, indicators


def _compute_single_sharpe(closed_trades):
    """已平仓交易的交易级夏普（非重叠样本）。样本不足/std为0 → None。"""
    if not closed_trades or len(closed_trades) < 2:
        return None
    rates = np.array([t['rate'] / 100.0 for t in closed_trades], dtype='float64')
    holds = np.array([max(1, int(t.get('hold_days') or 1)) for t in closed_trades], dtype='float64')
    excess = rates - _RISK_FREE_RATE * holds / 252.0
    std = float(np.std(excess, ddof=1))
    if std == 0 or not np.isfinite(std):
        return None
    avg_hold = float(np.mean(holds))
    if avg_hold <= 0:
        return None
    sharpe = float(np.mean(excess)) / std * np.sqrt(252.0 / avg_hold)
    if not np.isfinite(sharpe):
        return None
    return round(sharpe, 2)


def _load_single_hist(code, start_date_str, end_date_str):
    """读取个股完整历史：缓存优先 + cn_stock_spot 兜底补全（修复 C）。

    返回按日期升序的 DataFrame（date 为 datetime），无数据返回 None。
    仅读 MySQL + cache/hist/，不发起外部 API（AGENTS.md 规则 1）。
    内置路径与自定义路径共用，避免补全逻辑分叉。
    """
    hist = stf.read_stock_hist_from_cache(code, '19900101', '20991231')
    # read_stock_hist_from_cache 仅在缓存文件"完全不存在"时才回退 spot，
    # 文件存在但只有少量行（本地/新股/同步中断）时会静默产出空结果 → 这里主动补全。
    if hist is None or len(hist) == 0 or not _cache_covers_range(hist, start_date_str, end_date_str):
        spot_hist = stf._fallback_kline_from_spot(code, '19900101', '20991231')
        if spot_hist is not None and len(spot_hist) > 0:
            if hist is None or len(hist) == 0:
                hist = spot_hist
            else:
                # 合并缓存与 spot，按日期去重（缓存为前复权优先，spot 补缺日）
                hist = pd.concat([hist, spot_hist], ignore_index=True)
                if not pd.api.types.is_datetime64_any_dtype(hist['date']):
                    hist['date'] = pd.to_datetime(hist['date'])
                hist = hist.drop_duplicates(subset=['date'], keep='first')
    if hist is None or len(hist) == 0:
        return None
    hist = hist.copy()
    if not pd.api.types.is_datetime64_any_dtype(hist['date']):
        hist['date'] = pd.to_datetime(hist['date'])
    hist = hist.sort_values('date').reset_index(drop=True)
    return hist


def _summarize_single_trades(trades):
    """单股回测交易列表 → 汇总统计 dict（内置 / 自定义路径共用，保证口径一致）。

    胜率/复利累计/夏普仅基于已平仓交易；rate 已含双边成本。
    """
    closed = [t for t in trades if t['status'] == 'closed']
    open_trades = [t for t in trades if t['status'] == 'open']
    win = [t for t in closed if t['rate'] > 0]
    lose = [t for t in closed if t['rate'] <= 0]
    closed_count = len(closed)
    win_rate = round(100.0 * len(win) / closed_count, 2) if closed_count > 0 else None
    # 复利累计收益
    if closed:
        comp = 1.0
        for t in closed:
            comp *= (1.0 + t['rate'] / 100.0)
        cum_return = round((comp - 1.0) * 100.0, 2)
        avg_return = round(sum(t['rate'] for t in closed) / closed_count, 2)
        max_trade_return = round(max(t['rate'] for t in closed), 2)
        max_trade_drawdown = round(min(t['rate'] for t in closed), 2)
    else:
        cum_return = None
        avg_return = None
        max_trade_return = None
        max_trade_drawdown = None
    sharpe = _compute_single_sharpe(closed)
    return {
        'trade_count': len(trades),
        'closed_count': closed_count,
        'open_count': len(open_trades),
        'win_count': len(win),
        'lose_count': len(lose),
        'win_rate': win_rate,
        'cum_return': cum_return,
        'avg_return': avg_return,
        'sharpe': sharpe,
        'max_trade_return': max_trade_return,
        'max_trade_drawdown': max_trade_drawdown,
    }


def _run_single_backtest(code, strategy, start_date_str, end_date_str, hold_days=None, allow_overlap=False):
    """单股区间买卖点回测。返回含 kline / indicators / trades / summary 的 dict。"""
    if not code:
        return {"error": "缺少股票代码参数"}
    if not strategy:
        return {"error": "缺少策略参数"}
    # 自定义策略（custom_<id>）走组合回测交易过滤法（方案 2），与内置 check() 路径解耦。
    if str(strategy).startswith('custom_'):
        return _run_single_custom_backtest(code, strategy, start_date_str, end_date_str)
    if _is_index_code(code):
        return {"error": "暂不支持指数回测，请输入个股代码"}
    if not start_date_str or not end_date_str:
        return {"error": "缺少回测区间参数"}

    strategy_func, strategy_cn = _resolve_single_strategy_with_indicator(
        strategy, code=code, start_date_str=start_date_str, end_date_str=end_date_str)
    if strategy_func is None:
        return {"error": f"策略 {strategy} 暂不支持单股区间回测"}

    # 解析持仓周期 / 退出模式
    #   - 显式 hold_days  → 固定持仓（fixed）
    #   - 事件型策略       → 规则退出（rule_exit，止损/止盈/最大持仓）
    #   - 状态型策略       → 入场条件消失即离场（strategy_signal）
    exit_mode = 'strategy_signal'
    if hold_days is not None and str(hold_days).strip() != '':
        try:
            hold_days = int(hold_days)
        except (TypeError, ValueError):
            return {"error": f"持仓周期参数非法：{hold_days}"}
        if hold_days < 1:
            return {"error": "持仓周期须为正整数"}
        exit_mode = 'fixed'
    else:
        hold_days = None
        if strategy in _EVENT_STRATEGIES:
            exit_mode = 'rule_exit'

    # 读取完整历史缓存（含区间前预热，供 MA250/长周期指标）+ spot 兜底补全（修复 C）
    hist = _load_single_hist(code, start_date_str, end_date_str)
    if hist is None:
        return {"error": f"股票 {code} 无缓存数据，请先执行数据获取"}

    stock_name = _get_stock_name(code)
    limit_ratio = _price_limit_ratio(code, stock_name)
    # 涨停跳过阈值：贴近涨停（留 5% 余量）即视为无法买入
    limit_skip = limit_ratio * 0.95

    start_ts = pd.Timestamp(start_date_str.replace('-', '')) if '-' not in str(start_date_str) else pd.Timestamp(start_date_str)
    end_ts = pd.Timestamp(end_date_str.replace('-', '')) if '-' not in str(end_date_str) else pd.Timestamp(end_date_str)

    in_range = hist[(hist['date'] >= start_ts) & (hist['date'] <= end_ts)]
    if in_range.empty:
        return {"error": "回测区间内无交易数据"}

    # 裁剪到区间末：保留区间前完整历史供指标预热（plan §3.4 line 143），
    # 但移除 end_ts 之后的"未来"K线，避免买卖点/持仓中定价越过区间末（lookahead）。
    hist = hist[hist['date'] <= end_ts].reset_index(drop=True)

    stock = (code, code, stock_name)
    dates_all = hist['date'].tolist()
    n = len(hist)

    # 逐日扫描买入信号
    signal_idx = []
    for idx in range(n):
        d = dates_all[idx]
        if d < start_ts or d > end_ts:
            continue
        if _strategy_hit(strategy_func, stock, hist, d.to_pydatetime()):
            signal_idx.append(idx)

    trades = []
    no = 0
    held_until = -1  # 去重：持仓期内重复信号合并
    for sig in signal_idx:
        if not allow_overlap and sig <= held_until:
            continue
        # T+1 开盘买入
        buy_i = sig + 1
        if buy_i >= n:
            continue  # 信号日为最后一根，无法 T+1 买入
        t_close = float(hist.iloc[sig]['close'])
        buy_price = float(hist.iloc[buy_i]['open'])
        if buy_price <= 0 or t_close <= 0:
            continue
        if (buy_price - t_close) / t_close >= limit_skip:
            continue  # T+1 开盘涨停，无法买入

        # 确定卖出
        sell_i = None
        exit_reason = None
        if exit_mode == 'fixed':
            target = buy_i + hold_days
            if target < n:
                sell_i = target
                exit_reason = 'hold_expired'
        elif exit_mode == 'rule_exit':
            # 事件型策略：入场信号仅当日成立，不能复用入场条件做持仓判断。
            # 改用与入场解耦的规则退出（按收盘价逐日判定）：
            #   止损 -8% / 止盈 +15% / 最大持仓 20 交易日，三者先到先离场。
            stop_price = buy_price * (1 - _EVENT_EXIT_STOP_LOSS)
            target_price = buy_price * (1 + _EVENT_EXIT_TAKE_PROFIT)
            for j in range(buy_i + 1, n):
                c_j = float(hist.iloc[j]['close'])
                if c_j <= stop_price:
                    sell_i, exit_reason = j, 'stop_loss'
                    break
                if c_j >= target_price:
                    sell_i, exit_reason = j, 'take_profit'
                    break
                if (j - buy_i) >= _EVENT_EXIT_MAX_HOLD:
                    sell_i, exit_reason = j, 'max_hold'
                    break
        else:  # strategy_signal：状态型策略，买入后首个入场条件不再成立日离场
            for j in range(buy_i + 1, n):
                if not _strategy_hit(strategy_func, stock, hist, dates_all[j].to_pydatetime()):
                    sell_i = j
                    exit_reason = 'sell_signal'
                    break

        no += 1
        if sell_i is not None and sell_i < n:
            sell_price = float(hist.iloc[sell_i]['close'])
            raw_rate = round(100.0 * (sell_price - buy_price) / buy_price, 2)
            rate = round(raw_rate - ROUND_TRIP_COST_PCT, 2)
            hd = sell_i - buy_i
            trades.append({
                'no': no,
                'buy_date': hist.iloc[buy_i]['date'].strftime('%Y-%m-%d'),
                'buy_price': round(buy_price, 2),
                'sell_date': hist.iloc[sell_i]['date'].strftime('%Y-%m-%d'),
                'sell_price': round(sell_price, 2),
                'hold_days': hd,
                'exit_reason': exit_reason,
                'rate': rate,
                'raw_rate': raw_rate,
                'status': 'closed',
                'win': rate > 0,
            })
            held_until = sell_i
        else:
            # 区间末仍持仓
            last_close = float(hist.iloc[-1]['close'])
            raw_rate = round(100.0 * (last_close - buy_price) / buy_price, 2)
            rate = round(raw_rate - ROUND_TRIP_COST_PCT, 2)
            trades.append({
                'no': no,
                'buy_date': hist.iloc[buy_i]['date'].strftime('%Y-%m-%d'),
                'buy_price': round(buy_price, 2),
                'sell_date': None,
                'sell_price': None,
                'hold_days': n - 1 - buy_i,
                'exit_reason': 'interval_end',
                'rate': rate,
                'raw_rate': raw_rate,
                'status': 'open',
                'win': None,
            })
            held_until = n - 1

    # 汇总统计
    summary = _summarize_single_trades(trades)

    recommended = STRATEGY_OVERLAY_MAP.get(strategy, list(_DEFAULT_OVERLAY))
    kline, indicators = _build_kline_and_indicators(hist, recommended, list(_ALL_OVERLAYS))

    return {
        'code': code,
        'name': stock_name,
        'strategy': strategy,
        'strategy_cn': strategy_cn,
        'start_date': start_ts.strftime('%Y-%m-%d'),
        'end_date': end_ts.strftime('%Y-%m-%d'),
        'hold_days': hold_days,
        'exit_mode': exit_mode,
        'kline': kline,
        'indicators': indicators,
        'trades': trades,
        'summary': summary,
    }


def _custom_code_match(trade_code, target_code):
    """组合引擎交易 code 与目标股票代码比对（兼容带交易所前/后缀的写法）。"""
    tc = str(trade_code or '').strip()
    if not tc:
        return False
    if tc == target_code:
        return True
    # 提取 6 位数字部分（600000.XSHG / sh600000 / 600000 → 600000）
    digits = ''.join(ch for ch in tc if ch.isdigit())
    tgt_digits = ''.join(ch for ch in str(target_code) if ch.isdigit())
    return bool(digits) and digits[-6:] == tgt_digits[-6:]


def _run_single_custom_backtest(code, strategy, start_date_str, end_date_str, benchmark='000300'):
    """自定义策略单股回测（方案 2：组合回测交易过滤法）。

    复用 verify-center 的组合回测设施（_load_cached_custom_backtest /
    _auto_run_custom_backtest），将该策略在区间内的真实组合交易过滤到目标股票，
    按时间顺序配对成 round-trip 渲染到单股 K 线上。语义：
    "这只股票在该组合策略下的真实买卖点"。仅读 MySQL + cache/hist/（规则 1），
    不发起外部 API。该股在区间内未被策略选中时返回空交易 + 友好提示（非错误）。
    """
    if _is_index_code(code):
        return {"error": "暂不支持指数回测，请输入个股代码"}
    if not start_date_str or not end_date_str:
        return {"error": "缺少回测区间参数"}

    strategy_id, strategy_cn = _resolve_custom_strategy(strategy)
    if strategy_id is None:
        return {"error": f"自定义策略 {strategy} 不存在或已归档"}

    # 区间规范化为 YYYY-MM-DD（组合回测缓存以该格式存储/比对）
    def _fmt(d):
        s = str(d).strip()
        return s if '-' in s else f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    s_date, e_date = _fmt(start_date_str), _fmt(end_date_str)

    # 获取组合回测全量交易（buy + sell）：优先缓存，缺失时自动跑一次再读
    from quantia.web import verifyOptimizeHandler as voh
    result, _src = voh._load_cached_custom_backtest(strategy_id, s_date, e_date, benchmark)
    if result is None:
        _, auto_err = voh._auto_run_custom_backtest(strategy_id, s_date, e_date, benchmark)
        if auto_err:
            return {"error": f"自定义策略回测失败：{auto_err}"}
        result, _src = voh._load_cached_custom_backtest(strategy_id, s_date, e_date, benchmark)
    all_trades = (result or {}).get('trades', []) or []

    # 读取目标股票完整历史（缓存 + spot 兜底）并裁剪到区间末，供 K 线/指标 + 区间末持仓估值
    hist = _load_single_hist(code, s_date, e_date)
    if hist is None:
        return {"error": f"股票 {code} 无缓存数据，请先执行数据获取"}
    stock_name = _get_stock_name(code)
    end_ts = pd.Timestamp(e_date)
    start_ts = pd.Timestamp(s_date)
    hist = hist[hist['date'] <= end_ts].reset_index(drop=True)
    if hist.empty:
        return {"error": "回测区间内无交易数据"}
    dates_str = hist['date'].dt.strftime('%Y-%m-%d').tolist()
    date_to_idx = {ds: i for i, ds in enumerate(dates_str)}

    def _idx_for(dstr):
        """交易日期 → hist 行号；精确命中优先，否则取首个 >= 的交易日。"""
        i = date_to_idx.get(dstr)
        if i is not None:
            return i
        for k, ds in enumerate(dates_str):
            if ds >= dstr:
                return k
        return None

    # 过滤目标股票交易，按日期升序，状态机配对 round-trip
    code_trades = [t for t in all_trades if _custom_code_match(t.get('code'), code)]
    code_trades.sort(key=lambda x: str(x.get('date', '')))

    trades = []
    no = 0
    pos = None  # (buy_idx, buy_date_str, buy_price)
    for t in code_trades:
        direction = str(t.get('direction', '') or '')
        dstr = str(t.get('date', '') or '')
        if not dstr or dstr < s_date or dstr > e_date:
            continue
        try:
            price = float(t.get('price', 0) or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        if direction == 'buy':
            if pos is None:  # 已持仓时的加仓忽略，仅以首笔买入计入场
                bi = _idx_for(dstr)
                if bi is None:
                    continue
                pos = (bi, dates_str[bi], price)
        elif direction == 'sell':
            if pos is not None:  # 空仓时的卖出忽略
                si = _idx_for(dstr)
                if si is None:
                    continue
                bi, bdate, bprice = pos
                raw_rate = round(100.0 * (price - bprice) / bprice, 2)
                rate = round(raw_rate - ROUND_TRIP_COST_PCT, 2)
                no += 1
                trades.append({
                    'no': no,
                    'buy_date': bdate,
                    'buy_price': round(bprice, 2),
                    'sell_date': dates_str[si],
                    'sell_price': round(price, 2),
                    'hold_days': si - bi,
                    'exit_reason': 'strategy_sell',
                    'rate': rate,
                    'raw_rate': raw_rate,
                    'status': 'closed',
                    'win': rate > 0,
                })
                pos = None
    # 区间末仍持仓
    if pos is not None:
        bi, bdate, bprice = pos
        last_close = float(hist.iloc[-1]['close'])
        raw_rate = round(100.0 * (last_close - bprice) / bprice, 2)
        rate = round(raw_rate - ROUND_TRIP_COST_PCT, 2)
        no += 1
        trades.append({
            'no': no,
            'buy_date': bdate,
            'buy_price': round(bprice, 2),
            'sell_date': None,
            'sell_price': None,
            'hold_days': (len(dates_str) - 1) - bi,
            'exit_reason': 'interval_end',
            'rate': rate,
            'raw_rate': raw_rate,
            'status': 'open',
            'win': None,
        })

    summary = _summarize_single_trades(trades)
    kline, indicators = _build_kline_and_indicators(hist, list(_DEFAULT_OVERLAY), list(_ALL_OVERLAYS))

    payload = {
        'code': code,
        'name': stock_name,
        'strategy': strategy,
        'strategy_cn': strategy_cn,
        'start_date': start_ts.strftime('%Y-%m-%d'),
        'end_date': end_ts.strftime('%Y-%m-%d'),
        'hold_days': None,
        'exit_mode': 'custom',
        'kline': kline,
        'indicators': indicators,
        'trades': trades,
        'summary': summary,
    }
    if not trades:
        payload['message'] = (
            f'股票 {code} 在 {s_date} ~ {e_date} 区间内未被自定义策略「{strategy_cn}」'
            f'选中买卖（该策略按其自身股票池/选股逻辑运作，可能从未持有此股）。'
        )
    return payload


def _ensure_single_history_table():
    """惰性建表：单股回测历史。"""
    sql = f"""CREATE TABLE IF NOT EXISTS `{SINGLE_BACKTEST_HISTORY_TABLE}` (
        `id` BIGINT NOT NULL AUTO_INCREMENT,
        `created_at` DATETIME NOT NULL,
        `code` VARCHAR(8) NOT NULL,
        `name` VARCHAR(32) DEFAULT NULL,
        `strategy` VARCHAR(64) NOT NULL,
        `strategy_cn` VARCHAR(64) DEFAULT NULL,
        `start_date` DATE DEFAULT NULL,
        `end_date` DATE DEFAULT NULL,
        `hold_days` INT DEFAULT NULL,
        `exit_mode` VARCHAR(16) DEFAULT NULL,
        `trade_count` INT DEFAULT 0,
        `win_rate` FLOAT DEFAULT NULL,
        `cum_return` FLOAT DEFAULT NULL,
        `avg_return` FLOAT DEFAULT NULL,
        `detail_json` MEDIUMTEXT,
        PRIMARY KEY (`id`),
        KEY `idx_code` (`code`),
        KEY `idx_strategy` (`strategy`),
        KEY `idx_created` (`created_at`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
    mdb.executeSql(sql)
    # 刷新表存在性缓存，避免刚建表后历史列表因 TTL 内的 False 缓存返回空
    try:
        mdb._cache_table_exists(SINGLE_BACKTEST_HISTORY_TABLE, True)
    except Exception:
        pass


def _finite_or_none(v):
    if v is None:
        return None
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    if np.isnan(fv) or np.isinf(fv):
        return None
    return fv


def _save_single_history(result):
    """写入单股回测历史；detail_json 仅存 入参+trades+summary（不含 kline/indicators）。返回插入 id 或 None。"""
    try:
        _ensure_single_history_table()
        detail = {
            'code': result.get('code'),
            'name': result.get('name'),
            'strategy': result.get('strategy'),
            'strategy_cn': result.get('strategy_cn'),
            'start_date': result.get('start_date'),
            'end_date': result.get('end_date'),
            'hold_days': result.get('hold_days'),
            'exit_mode': result.get('exit_mode'),
            'trades': result.get('trades'),
            'summary': result.get('summary'),
        }
        summary = result.get('summary', {})
        sql = f"""INSERT INTO `{SINGLE_BACKTEST_HISTORY_TABLE}`
            (`created_at`, `code`, `name`, `strategy`, `strategy_cn`, `start_date`, `end_date`,
             `hold_days`, `exit_mode`, `trade_count`, `win_rate`, `cum_return`, `avg_return`, `detail_json`)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
        params = (
            datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            result.get('code'),
            result.get('name'),
            result.get('strategy'),
            result.get('strategy_cn'),
            result.get('start_date'),
            result.get('end_date'),
            result.get('hold_days'),
            result.get('exit_mode'),
            summary.get('trade_count', 0),
            _finite_or_none(summary.get('win_rate')),
            _finite_or_none(summary.get('cum_return')),
            _finite_or_none(summary.get('avg_return')),
            json.dumps(detail, ensure_ascii=False, default=_json_default),
        )
        mdb.executeSql(sql, params)
        row = mdb.executeSqlFetch("SELECT LAST_INSERT_ID()")
        if row and len(row) > 0:
            return int(row[0][0])
    except Exception:
        logging.error("保存单股回测历史失败", exc_info=True)
    return None


class SingleStockBacktestHandler(webBase.BaseHandler, ABC):
    """单股区间买卖点回测"""
    @gen.coroutine
    def get(self):
        self.set_header('Content-Type', 'application/json;charset=UTF-8')
        code = self.get_argument("code", default=None, strip=True)
        strategy = self.get_argument("strategy", default=None, strip=True)
        start_date = self.get_argument("start_date", default=None, strip=True)
        end_date = self.get_argument("end_date", default=None, strip=True)
        hold_days = self.get_argument("hold_days", default=None, strip=True)
        save = self.get_argument("save", default="0", strip=True)
        allow_overlap = self.get_argument("allow_overlap", default="0", strip=True) == "1"

        try:
            result = yield IOLoop.current().run_in_executor(
                None, lambda: _run_single_backtest(code, strategy, start_date, end_date,
                                                   hold_days=hold_days, allow_overlap=allow_overlap))
            if save == "1" and 'error' not in result:
                new_id = yield IOLoop.current().run_in_executor(None, lambda: _save_single_history(result))
                result['history_id'] = new_id
            self.write(json.dumps(result, ensure_ascii=False, default=_json_default))
        except Exception as e:
            logging.error("SingleStockBacktestHandler处理异常", exc_info=True)
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}, ensure_ascii=False))


class BacktestHistoryListHandler(webBase.BaseHandler, ABC):
    """回测历史列表（分页，不含 detail_json）"""
    def get(self):
        self.set_header('Content-Type', 'application/json;charset=UTF-8')
        code = self.get_argument("code", default=None, strip=True)
        strategy = self.get_argument("strategy", default=None, strip=True)
        start = self.get_argument("start", default=None, strip=True)
        end = self.get_argument("end", default=None, strip=True)
        try:
            page = max(1, int(self.get_argument("page", default="1", strip=True)))
            page_size = min(100, max(1, int(self.get_argument("page_size", default="20", strip=True))))
        except ValueError:
            page, page_size = 1, 20

        try:
            if not mdb.checkTableIsExist(SINGLE_BACKTEST_HISTORY_TABLE):
                self.write(json.dumps({'total': 0, 'page': page, 'page_size': page_size, 'items': []},
                                      ensure_ascii=False))
                return
            where = []
            params = []
            if code:
                where.append("`code` = %s")
                params.append(code)
            if strategy:
                where.append("`strategy` = %s")
                params.append(strategy)
            if start:
                where.append("`created_at` >= %s")
                params.append(start + " 00:00:00")
            if end:
                where.append("`created_at` <= %s")
                params.append(end + " 23:59:59")
            where_sql = (" WHERE " + " AND ".join(where)) if where else ""
            total = mdb.executeSqlCount(
                f"SELECT COUNT(*) FROM `{SINGLE_BACKTEST_HISTORY_TABLE}`{where_sql}", tuple(params))
            offset = (page - 1) * page_size
            rows = mdb.executeSqlFetch(
                f"""SELECT `id`,`created_at`,`code`,`name`,`strategy`,`strategy_cn`,`start_date`,`end_date`,
                    `hold_days`,`exit_mode`,`trade_count`,`win_rate`,`cum_return`,`avg_return`
                    FROM `{SINGLE_BACKTEST_HISTORY_TABLE}`{where_sql}
                    ORDER BY `id` DESC LIMIT %s OFFSET %s""",
                tuple(params) + (page_size, offset))
            cols = ['id', 'created_at', 'code', 'name', 'strategy', 'strategy_cn', 'start_date', 'end_date',
                    'hold_days', 'exit_mode', 'trade_count', 'win_rate', 'cum_return', 'avg_return']
            items = [dict(zip(cols, r)) for r in (rows or [])]
            self.write(json.dumps({'total': total, 'page': page, 'page_size': page_size, 'items': items},
                                  ensure_ascii=False, default=_json_default))
        except Exception as e:
            logging.error("BacktestHistoryListHandler处理异常", exc_info=True)
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}, ensure_ascii=False))


class BacktestHistoryDetailHandler(webBase.BaseHandler, ABC):
    """回测历史详情（解析 detail_json）"""
    def get(self):
        self.set_header('Content-Type', 'application/json;charset=UTF-8')
        hid = self.get_argument("id", default=None, strip=True)
        if not hid:
            self.set_status(400)
            self.write(json.dumps({"error": "缺少 id 参数"}, ensure_ascii=False))
            return
        try:
            if not mdb.checkTableIsExist(SINGLE_BACKTEST_HISTORY_TABLE):
                self.set_status(404)
                self.write(json.dumps({"error": "记录不存在"}, ensure_ascii=False))
                return
            rows = mdb.executeSqlFetch(
                f"SELECT `detail_json` FROM `{SINGLE_BACKTEST_HISTORY_TABLE}` WHERE `id` = %s LIMIT 1",
                (hid,))
            if not rows or len(rows) == 0:
                self.set_status(404)
                self.write(json.dumps({"error": "记录不存在"}, ensure_ascii=False))
                return
            detail = json.loads(rows[0][0]) if rows[0][0] else {}
            self.write(json.dumps(detail, ensure_ascii=False, default=_json_default))
        except Exception as e:
            logging.error("BacktestHistoryDetailHandler处理异常", exc_info=True)
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}, ensure_ascii=False))


class BacktestHistoryDeleteHandler(webBase.BaseHandler, ABC):
    """删除回测历史记录"""
    def delete(self):
        self.set_header('Content-Type', 'application/json;charset=UTF-8')
        hid = self.get_argument("id", default=None, strip=True)
        if not hid:
            self.set_status(400)
            self.write(json.dumps({"error": "缺少 id 参数"}, ensure_ascii=False))
            return
        try:
            if mdb.checkTableIsExist(SINGLE_BACKTEST_HISTORY_TABLE):
                mdb.executeSql(
                    f"DELETE FROM `{SINGLE_BACKTEST_HISTORY_TABLE}` WHERE `id` = %s", (hid,))
            self.write(json.dumps({"success": True, "id": hid}, ensure_ascii=False))
        except Exception as e:
            logging.error("BacktestHistoryDeleteHandler处理异常", exc_info=True)
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}, ensure_ascii=False))

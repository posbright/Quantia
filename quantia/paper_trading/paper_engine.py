#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模拟交易引擎

每日执行策略逻辑，使用当日真实行情数据模拟成交，
持仓和资金状态在每日收盘后持久化到数据库。

核心流程：
1. 从 DB 加载策略代码和上次运行状态
2. 恢复 Context / Portfolio / g 对象
3. 加载当日行情数据
4. 执行 before_trading_start → handle_data → after_trading_end
5. 撮合订单（使用当日收盘价）
6. 保存状态到 DB
7. 记录交易和持仓快照
"""

import logging
import time
import datetime
import json
import pandas as pd

from quantia.core.backtest.strategy_context import (
    Context, GlobalVars, DataProxy, TradeRecord, NavRecord,
)
from quantia.core.backtest.strategy_sandbox import compile_strategy
from quantia.core.backtest.data_feed import load_stock_data, load_benchmark_data
from .state_manager import serialize_portfolio, restore_portfolio

_INDEX_CODES = {
    '000002', '000003', '000016', '000300', '000688',
    '000852', '000905', '000906', '000985',
    '399001', '399006', '399300', '399905', '399951',
}

# 模块级股票名称缓存：避免每笔交易/通知都打 DB
_STOCK_NAME_CACHE = {}


def _resolve_stock_name(code):
    """根据 code 取股票/指数名称（带模块级缓存）。

    用于补全 paper_engine 持仓/交易记录中的 ``name`` 字段（IM 通知、前端列表
    都依赖该字段；若策略只调用 ``order(code, ...)`` 而未指定名称，
    Position.name 默认空串，导致下游展示只有代码不易识别）。
    """
    code = _normalize_security_code(code)
    if not code:
        return ''
    if code in _STOCK_NAME_CACHE:
        return _STOCK_NAME_CACHE[code]
    name = ''
    try:
        import quantia.lib.database as mdb
        # 优先 cn_stock_spot（A 股个股），命中即返回
        rows = mdb.executeSqlFetch(
            'SELECT name FROM cn_stock_spot WHERE code=%s LIMIT 1', (code,))
        if rows and rows[0] and rows[0][0]:
            name = str(rows[0][0]).strip()
        else:
            # 指数（cn_index_spot）兜底
            rows = mdb.executeSqlFetch(
                'SELECT name FROM cn_index_spot WHERE code=%s LIMIT 1', (code,))
            if rows and rows[0] and rows[0][0]:
                name = str(rows[0][0]).strip()
    except Exception:
        logging.debug(f"[模拟交易] 查询股票名称失败 code={code}", exc_info=True)
    _STOCK_NAME_CACHE[code] = name
    return name


def _build_derived_reason(direction, order_info, log_lines, exec_price=None,
                           exec_amount=None, strategy_name=None):
    """从策略 log + order 参数派生真实交易理由（reason_source='derived'）。

    优先级：
      1) 策略 ``log.info/warn`` 中提到该 code 的最近条目（截取 5 条）。
      2) order_api + target_amount/value/percent + 实际成交价数量。
    """
    code = order_info.get('code') or ''
    matched = []
    if log_lines:
        # 反向扫描最近 50 条，挑出明确提到该 code 的（最多 5 条）
        for line in reversed(log_lines[-50:]):
            if code and code in str(line):
                matched.append(str(line).strip())
                if len(matched) >= 5:
                    break
        matched.reverse()

    parts = []
    if strategy_name:
        parts.append(f"[{strategy_name}]")
    parts.append('买入' if direction == 'buy' else '卖出/调仓')

    api = order_info.get('order_api') or ''
    api_desc_map = {
        'order': 'order(amount)',
        'order_target': 'order_target(target_amount)',
        'order_value': 'order_value(value)',
        'order_target_value': 'order_target_value(target_value)',
        'order_target_percent': 'order_target_percent(target_percent)',
    }
    if api:
        parts.append(f"({api_desc_map.get(api, api)})")

    param_bits = []
    if order_info.get('target_amount') is not None:
        param_bits.append(f"目标股数={order_info['target_amount']}")
    if order_info.get('target_percent') is not None:
        try:
            param_bits.append(f"目标仓位={float(order_info['target_percent']) * 100:.2f}%")
        except Exception:
            pass
    if order_info.get('value') is not None and order_info.get('order_api') in (
            'order_value', 'order_target_value'):
        try:
            param_bits.append(f"目标市值Δ={float(order_info['value']):.0f}元")
        except Exception:
            pass
    if exec_price is not None and exec_amount:
        param_bits.append(f"实际成交 {exec_amount} 股 @ {float(exec_price):.3f}")
    if param_bits:
        parts.append('；'.join(param_bits))

    head = ' '.join(parts)
    if matched:
        return head + '\n策略日志:\n  - ' + '\n  - '.join(matched)
    return head


def _normalize_security_code(code):
    text = str(code or '').strip()
    return text.split('.')[0] if '.' in text else text


def _is_index_code(code):
    clean = _normalize_security_code(code)
    return clean in _INDEX_CODES or clean.startswith('399')


def _load_security_data(code, start_date=None, end_date=None):
    clean = _normalize_security_code(code)
    if _is_index_code(clean):
        return clean, load_benchmark_data(clean, start_date, end_date)
    return clean, load_stock_data(clean, start_date, end_date)


def _cache_security_data(context, data_proxy, code, loaded_df):
    """Cache dynamically loaded K-line data and update the current-day bar."""
    if loaded_df is None or not hasattr(context, '_engine') or not context._engine:
        return
    context._engine._stock_data[code] = loaded_df
    data_proxy._set_history(code, loaded_df)
    current_date = pd.Timestamp(context.current_dt).normalize()
    dates = pd.to_datetime(loaded_df['date']).dt.normalize()
    today_row = loaded_df[dates == current_date]
    if len(today_row) > 0:
        row_data = today_row.iloc[0]
        data_proxy._set_current(code, {
            'open': row_data.get('open', row_data['close']),
            'high': row_data.get('high', row_data['close']),
            'low': row_data.get('low', row_data['close']),
            'close': row_data['close'],
            'volume': row_data.get('volume', 0),
            'pre_close': row_data.get('pre_close', row_data['close']),
        })


def _date_text(value):
    if value is None:
        return None
    if hasattr(value, 'strftime'):
        return value.strftime('%Y-%m-%d')
    text = str(value).strip()
    return text[:10] if text else None


def _first_close_on_or_after(df, date_text):
    if df is None or len(df) == 0:
        return None
    target = pd.Timestamp(date_text).normalize()
    rows = df[pd.to_datetime(df['date']).dt.normalize() >= target]
    if len(rows) == 0:
        return None
    return float(rows.iloc[0]['close'])


def _last_close_on_or_before(df, date_text):
    if df is None or len(df) == 0:
        return None
    target = pd.Timestamp(date_text).normalize()
    rows = df[pd.to_datetime(df['date']).dt.normalize() <= target]
    if len(rows) == 0:
        return None
    return float(rows.iloc[-1]['close'])


def _compute_paper_benchmark_value(context, paper_id, date_str):
    """Return normalized benchmark NAV for the paper account current date."""
    benchmark_code = _normalize_security_code(getattr(context, 'benchmark', '000300') or '000300')
    base_code = _normalize_security_code(getattr(context, 'benchmark_base_code', None) or '')
    base_price = getattr(context, 'benchmark_base_price', None)
    base_date = _date_text(getattr(context, 'benchmark_base_date', None))

    try:
        base_price = float(base_price) if base_price else None
    except (TypeError, ValueError):
        base_price = None

    if base_code and base_code != benchmark_code:
        base_price = None
        base_date = None

    if not base_date:
        base_date = date_str
        try:
            import quantia.lib.database as mdb
            rows = mdb.executeSqlFetch(
                'SELECT MIN(date) FROM cn_stock_paper_nav WHERE paper_id=%s',
                (paper_id,))
            if rows and rows[0] and rows[0][0]:
                candidate = _date_text(rows[0][0])
                if candidate:
                    base_date = candidate
        except Exception:
            logging.debug("[模拟交易] 获取模拟盘基准起点失败", exc_info=True)

    try:
        df = load_benchmark_data(benchmark_code, base_date, date_str)
        if base_price is None or base_price <= 0:
            base_price = _first_close_on_or_after(df, base_date)
        current_price = _last_close_on_or_before(df, date_str)
        if base_price and current_price:
            context.benchmark_base_code = benchmark_code
            context.benchmark_base_date = base_date
            context.benchmark_base_price = base_price
            return round(current_price / base_price, 6)
    except Exception:
        logging.warning(f"[模拟交易] 基准 {benchmark_code} NAV 计算失败", exc_info=True)

    context.benchmark_base_code = benchmark_code
    context.benchmark_base_date = base_date
    if base_price:
        context.benchmark_base_price = base_price
    return 1.0

# 基本面数据提供器（延迟初始化，仅在策略需要时加载）
_fundamental_provider = None

def _get_fundamental_provider(engine_obj=None):
    """获取或创建基本面数据提供器单例"""
    global _fundamental_provider
    if _fundamental_provider is None:
        try:
            from quantia.core.backtest.fundamentals import FundamentalDataProvider
            _fundamental_provider = FundamentalDataProvider(engine_obj)
        except Exception as e:
            logging.warning(f"[模拟交易] 基本面数据提供器加载失败: {e}")
    elif engine_obj is not None:
        # 更新引擎引用，确保 context.current_dt 是最新的
        _fundamental_provider._engine = engine_obj
    return _fundamental_provider

__author__ = 'Quantia'
__date__ = '2026/03/13'


def _net_same_bar_orders(pending_orders, context, today_prices):
    """同一 handle_data（同 bar）内对同一标的的多笔订单做价值空间净额合并。

    背景：部分策略的卖出循环与买入循环不互斥，会对同一标的先 ``order_target(code,0)``
    卖光、又 ``order_target_value(code,target)`` 买回，产生"卖光再买回"的无效换手
    （双倍佣金 + T+1 锁定 + 次轮陈旧价成交）。本函数把同一标的的多笔订单按聚宽语义
    在「价值空间」顺序回放为一个净目标，再折算成单笔净额订单，最终持仓不变但消除中间
    的对冲成交。单笔订单 / 无当日价 / 无法估值的标的保持原样，行为完全等价。

    回放规则（与 order_* 包装的 delta 计算口径一致，均相对 bar 起始持仓）：
      - order_target(T)        -> 目标值 = T * price        （绝对，后者覆盖前者）
      - order_target_value(Tv) -> 目标值 = stored_value + 起始持仓市值（绝对）
      - order_target_percent(p)-> 目标值 = p * total_value   （绝对）
      - order(amt)             -> 目标值 += amt * price      （增量累加）
      - order_value(v)         -> 目标值 += v                （增量累加）
    """
    from collections import OrderedDict
    groups = OrderedDict()
    for o in pending_orders:
        groups.setdefault(o.get('code'), []).append(o)

    netted = []
    for code, orders in groups.items():
        if len(orders) <= 1:
            netted.extend(orders)
            continue
        exec_price = today_prices.get(code)
        if not exec_price or exec_price <= 0:
            netted.extend(orders)  # 无法估值，保持原样
            continue

        pos = context.portfolio.positions.get(code)
        start_value = pos.value if (pos and pos.amount > 0) else 0.0

        running = start_value
        for o in orders:
            api = o.get('order_api')
            amt = o.get('amount')
            val = o.get('value')
            if api == 'order_target':
                running = (o.get('target_amount') or 0) * exec_price
            elif api == 'order_target_value':
                running = (val if val is not None else 0.0) + start_value
            elif api == 'order_target_percent':
                running = (o.get('target_percent') or 0) * context.portfolio.total_value
            else:
                # 增量型 order / order_value
                if amt is not None:
                    running += amt * exec_price
                elif val is not None:
                    running += val

        net_value = running - start_value
        merged = dict(orders[-1])  # 沿用最后一笔订单的 reason/decision/indicators
        merged['amount'] = None
        merged['value'] = net_value
        netted.append(merged)

    return netted


def run_paper_trading_daily(paper_id, scheduled=False, now=None):
    """
    执行指定模拟盘的每日交易。

    Args:
        paper_id: 模拟交易实例 ID

    Returns:
        dict: 执行结果 {'status': 'ok'/'error', 'message': str, 'trades': int}
    """
    import quantia.lib.database as mdb
    import quantia.lib.trade_time as trd

    started_at = datetime.datetime.now()
    result = None
    date_str = None

    try:
        # 盘前窗口窄门：今天是交易日且尚未到 09:30 时，trd.get_trade_date_last()
        # 会把 run_date_nph 回退到上一个交易日，导致：
        #   (a) 本次执行的交易被写入"昨日"的 date_str —— 与昨日收盘批次同一天，
        #       前端 K 线图上呈现"同日卖出 + 同日买入"假象；
        #   (b) prev_run_date_str == date_str 让 _on_new_day 跳过，T+1 closeable
        #       不刷新；
        #   (c) cn_stock_spot 还是昨日收盘价，用陈旧价格撮合次日开盘前的下单。
        # 解决方法：识别该精确窗口直接 skip，等开盘后由下一次 hourly 调度补跑。
        # 午休 / 收盘后 / 周末 / 节假日不进入此分支。
        _now_for_preopen_check = now or datetime.datetime.now()
        if (trd.is_trade_date(_now_for_preopen_check.date())
                and not trd.is_open(_now_for_preopen_check)):
            result = {
                'status': 'skipped',
                'message': '盘前不执行（09:30 前会将交易归入上一交易日，'
                           '导致日期错乱与 T+1 失效），等待开盘后由下一次调度补跑',
            }
            return result

        # 1. 获取当前交易日
        run_date, run_date_nph = trd.get_trade_date_last()
        if not trd.is_trade_date(run_date_nph):
            result = {'status': 'skipped', 'message': '非交易日'}
            return result

        date_str = run_date_nph.strftime('%Y-%m-%d')

        # 2. 加载模拟盘信息
        _ensure_paper_table()
        rows = mdb.executeSqlFetch(
            'SELECT pt.id, pt.strategy_id, pt.initial_cash, pt.status, '
            'pt.last_run_date, pt.state_json, sc.code as strategy_code, '
            'pt.run_frequency, pt.start_at, pt.last_run_at, '
            'pt.name as paper_name, sc.name as strategy_name '
            'FROM cn_stock_paper_trading pt '
            'JOIN cn_stock_strategy_code sc ON pt.strategy_id = sc.id '
            'WHERE pt.id = %s', (paper_id,))

        if not rows:
            result = {'status': 'error', 'message': f'模拟盘 {paper_id} 不存在'}
            return result

        row = rows[0]
        status = row[3]
        last_run_date = row[4]
        state_json = row[5]
        strategy_code = row[6]
        run_frequency = _normalize_run_frequency(row[7] if len(row) > 7 else 'daily')
        start_at = row[8] if len(row) > 8 else None
        last_run_at = row[9] if len(row) > 9 else None
        initial_cash = float(row[2]) if row[2] else 1000000
        paper_name = row[10] if len(row) > 10 else None
        strategy_name = row[11] if len(row) > 11 else None

        if status != 'running':
            result = {'status': 'skipped', 'message': f'模拟盘状态为 {status}'}
            return result

        now_dt = now or datetime.datetime.now()
        due, reason = _is_paper_due(
            run_frequency, start_at, last_run_date, last_run_at,
            date_str, now_dt, scheduled=scheduled)
        if not due:
            result = {'status': 'skipped', 'message': reason}
            return result

        logging.info(f"[模拟交易] 执行模拟盘 #{paper_id}，日期 {date_str}")

        # 3. 编译策略
        try:
            strategy_funcs = compile_strategy(strategy_code)
        except Exception as e:
            _update_paper_error(paper_id, str(e))
            result = {'status': 'error', 'message': f'策略编译失败: {e}'}
            return result

        # 4. 初始化/恢复上下文
        context = Context(initial_cash)
        g = GlobalVars()
        data_proxy = DataProxy()

        if state_json:
            # 恢复之前的状态
            restore_portfolio(context, state_json, g)
            logging.info(f"[模拟交易] 恢复状态: 现金={context.portfolio.available_cash:.2f}, "
                         f"持仓={len(context.portfolio.positions)}只")

        context.current_dt = run_date_nph
        context._engine = type('E', (), {'g': g, 'context': context, '_stock_data': {},
                                          '_pending_orders': [],
                                          '_trade_records': [], '_log_messages': [],
                                          '_custom_records': {}})()

        # 5. 加载持仓股票的当日行情
        all_codes = set(context.portfolio.positions.keys())
        # 从 context 和 g 中发现更多股票代码
        for obj in [context, g]:
            for attr in dir(obj):
                if attr.startswith('_'):
                    continue
                val = getattr(obj, attr, None)
                if isinstance(val, str):
                    clean = _normalize_security_code(val)
                    if len(clean) == 6 and clean.isdigit():
                        all_codes.add(clean)
                elif isinstance(val, (list, tuple, set)):
                    for item in val:
                        if isinstance(item, str):
                            clean = _normalize_security_code(item)
                            if len(clean) == 6 and clean.isdigit():
                                all_codes.add(clean)

        today_prices = {}
        pre_start = (pd.Timestamp(date_str) - pd.Timedelta(days=60)).strftime('%Y-%m-%d')

        # 优先从数据库批量加载当日行情（由定时任务每日写入 cn_stock_spot）
        from quantia.core.backtest.data_feed import _batch_load_today_from_db
        stock_codes = [code for code in all_codes if not _is_index_code(code)]
        db_today = _batch_load_today_from_db(stock_codes, date_str) if stock_codes else {}

        for code in all_codes:
            code, df = _load_security_data(code, pre_start, date_str)
            if df is not None:
                context._engine._stock_data[code] = df
                data_proxy._set_history(code, df)
                today_row = df[df['date'] == pd.Timestamp(date_str)]
                if len(today_row) > 0:
                    row_data = today_row.iloc[0]
                    today_prices[code] = row_data['close']
                    data_proxy._set_current(code, {
                        'open': row_data.get('open', row_data['close']),
                        'high': row_data.get('high', row_data['close']),
                        'low': row_data.get('low', row_data['close']),
                        'close': row_data['close'],
                        'volume': row_data.get('volume', 0),
                        'pre_close': row_data.get('pre_close', row_data['close']),
                    })
                elif code in db_today:
                    # K线缓存有历史数据但缺今日，用 DB 行情补全
                    spot = db_today[code]
                    today_prices[code] = spot['close']
                    data_proxy._set_current(code, {
                        'open': spot['open'],
                        'high': spot['high'],
                        'low': spot['low'],
                        'close': spot['close'],
                        'volume': spot['volume'],
                        'pre_close': spot.get('pre_close', spot['close']),
                    })
            elif code in db_today:
                # 完全无缓存，但 DB 有今日行情（至少可参与撮合）
                spot = db_today[code]
                today_prices[code] = spot['close']
                data_proxy._set_current(code, {
                    'open': spot['open'],
                    'high': spot['high'],
                    'low': spot['low'],
                    'close': spot['close'],
                    'volume': spot['volume'],
                    'pre_close': spot.get('pre_close', spot['close']),
                })

        # 跨交易日判断：同一交易日多次运行（hourly/15m）不应重置 T+1 closeable_amount。
        prev_run_date_str = str(last_run_date) if last_run_date else None
        is_new_trade_day = (prev_run_date_str is None) or (prev_run_date_str < date_str)

        # 更新持仓价格 + T+1：仅跨日才重置 closeable_amount
        if is_new_trade_day:
            context.portfolio._on_new_day(today_prices)
        else:
            # 同日重入：仅刷新最新价格与总资产，保留 T+1 closeable_amount
            for _code, _price in today_prices.items():
                _pos = context.portfolio.positions.get(_code)
                if _pos:
                    _pos._update_price(_price)
            context.portfolio._update_value()

        # 6. 执行策略
        api_ns = _create_api(context, data_proxy, g)
        pending_orders = []

        # Phase 8: AI pre-trade gate 配置只在每轮执行开始时加载一次（缓存到闭包），
        # 避免策略生成多笔订单时反复打 DB。任何加载异常都视为「未启用 gate」放行。
        _ai_gate_cfg = None
        try:
            from quantia.ai_decision import config as _ai_cfg_pre
            _ai_gate_cfg = _ai_cfg_pre.load_config_for_source('paper', paper_id)
            if _ai_gate_cfg is not None and not _ai_gate_cfg.is_gate():
                _ai_gate_cfg = None  # 仅留痕模式 → 不启用 pre-trade 阻断
        except Exception as _ai_cfg_err:
            logging.debug(
                f"[模拟交易] AI gate 配置加载失败(放行所有订单): {_ai_cfg_err}"
            )
            _ai_gate_cfg = None

        def _order_proxy(code, amount=None, value=None, *,
                          reason=None, decision=None, indicators=None, selection=None,
                          order_api=None, target_amount=None, target_percent=None):
            code = _normalize_security_code(code)
            # 动态加载未预加载的股票数据
            if code not in context._engine._stock_data:
                code, df = _load_security_data(code, pre_start, date_str)
                if df is not None:
                    context._engine._stock_data[code] = df
                    data_proxy._set_history(code, df)
                    today_row = df[df['date'] == pd.Timestamp(date_str)]
                    if len(today_row) > 0:
                        row_data = today_row.iloc[0]
                        today_prices[code] = row_data['close']
                        data_proxy._set_current(code, {
                            'open': row_data.get('open', row_data['close']),
                            'high': row_data.get('high', row_data['close']),
                            'low': row_data.get('low', row_data['close']),
                            'close': row_data['close'],
                            'volume': row_data.get('volume', 0),
                            'pre_close': row_data.get('pre_close', row_data['close']),
                        })
            # 如果仍无今日价格，尝试从 DB 单只加载
            if code not in today_prices and not _is_index_code(code):
                from quantia.core.backtest.data_feed import _load_today_from_db
                db_row = _load_today_from_db(code, date_str)
                if db_row is not None:
                    spot = db_row.iloc[0]
                    today_prices[code] = float(spot['close'])
                    data_proxy._set_current(code, {
                        'open': float(spot['open']),
                        'high': float(spot['high']),
                        'low': float(spot['low']),
                        'close': float(spot['close']),
                        'volume': int(spot['volume']),
                        'pre_close': float(spot['pre_close']) if pd.notna(spot.get('pre_close')) else float(spot['close']),
                    })
            # Phase 8: AI 真正的 pre-trade gate（默认关闭：cfg.is_gate()=False
            # 时不会进入此分支）。仅当配置 enabled=1 AND enabled_as_gate=1 时
            # 启用：撮合前调用 score_trade(decision_phase='pre_buy'/'pre_sell')；
            # 若返回 GATE_REJECT，则跳过本笔订单（不进入 pending_orders），
            # 等价于策略未发出信号。任何异常（DB / provider / 配置）均放行
            # 并 warning，避免 AI 故障阻塞撮合。
            #
            # 推断方向：order/order_target → amount 符号；
            #          order_value/order_target_value/order_target_percent → value 符号。
            _direction = None
            if amount is not None and amount != 0:
                _direction = 'buy' if amount > 0 else 'sell'
            elif value is not None and value != 0:
                _direction = 'buy' if value > 0 else 'sell'
            if _direction is not None:
                try:
                    if _ai_gate_cfg is not None:
                        from quantia.ai_decision import service as _ai_svc_pre
                        from quantia.ai_decision.schema import GATE_REJECT as _GATE_REJECT
                        _phase = 'pre_buy' if _direction == 'buy' else 'pre_sell'
                        _ai_pre = _ai_svc_pre.score_trade(
                            cfg=_ai_gate_cfg, source_type='paper', source_id=paper_id,
                            run_id=None, code=code, name=None,
                            decision_date=date_str, decision_phase=_phase,
                            direction=_direction,
                            indicators=indicators, selection=selection,
                        ) or {}
                        if _ai_pre.get('ai_gate_result') == _GATE_REJECT:
                            logging.info(
                                f"[模拟交易] AI 闸门拒绝 {code} {_direction} "
                                f"(score={_ai_pre.get('ai_score')}, "
                                f"reason={(_ai_pre.get('reason_summary') or '')[:80]})"
                            )
                            return
                except Exception as _ai_pre_err:
                    logging.warning(
                        f"[模拟交易] AI pre-trade gate 异常(放行 {code}): {_ai_pre_err}"
                    )
            pending_orders.append({
                'code': code, 'amount': amount, 'value': value,
                # Phase 2: 策略可显式传入交易解释；旧策略不传则为 None。
                'reason': reason, 'decision': decision,
                'indicators': indicators, 'selection': selection,
                'order_api': order_api,
                'target_amount': target_amount, 'target_percent': target_percent,
            })

        def _get_current_amount(code):
            pos = context.portfolio.positions.get(code)
            return pos.amount if pos else 0

        def _get_current_value(code):
            pos = context.portfolio.positions.get(code)
            return pos.value if pos and pos.amount > 0 else 0

        # Phase 2: 所有 order_* 包装均接受 **kw（reason/decision/indicators/selection），
        # 旧策略不传 kwargs 时行为完全等价；新策略可显式传入。
        api_ns['order'] = lambda code, amount, **kw: _order_proxy(
            code, amount=int(amount), order_api='order', **kw)
        api_ns['order_target'] = lambda code, target, **kw: _order_proxy(
            code, amount=int(target) - _get_current_amount(code),
            order_api='order_target', target_amount=int(target), **kw)
        api_ns['order_value'] = lambda code, value, **kw: _order_proxy(
            code, value=float(value), order_api='order_value', **kw)
        api_ns['order_target_value'] = lambda code, target_value, **kw: _order_proxy(
            code, value=float(target_value) - _get_current_value(code),
            order_api='order_target_value', **kw)
        api_ns['order_target_percent'] = lambda code, percent, **kw: _order_proxy(
            code, value=float(percent) * context.portfolio.total_value - _get_current_value(code),
            order_api='order_target_percent', target_percent=float(percent), **kw)

        # 每次都执行 initialize（注册 run_daily/run_weekly 回调 + 设置 context 参数）
        try:
            strategy_funcs['initialize'].__globals__.update(api_ns)
            strategy_funcs['initialize'](context)
        except Exception as e:
            if not state_json:
                # 首次运行 initialize 失败是致命的
                _update_paper_error(paper_id, f'initialize 异常: {e}')
                return {'status': 'error', 'message': f'initialize 异常: {e}'}
            else:
                # 恢复运行时 initialize 仍需成功注册回调/参数。失败后继续执行会
                # 用半初始化状态撮合并覆盖 state_json，存在模拟盘状态污染风险。
                logging.error(f"[模拟交易] initialize 异常（恢复运行失败）: {e}")
                _update_paper_error(paper_id, f'initialize 异常: {e}')
                return {'status': 'error', 'message': f'initialize 异常: {e}'}

        # RC1 修复：initialize 每轮都会重跑并把 context.hold_days / g.days 等调仓
        # 计数器重置为默认值。此处在 initialize 之后回填持久化的运行期标量，使调仓
        # 门按真实交易日连续推进；否则 hourly 调度下 hold_days 恒为 1，hold_days%20
        # ==1 恒真 → 每次运行都调仓，表现为“同日卖出又买入”。
        if state_json:
            from quantia.paper_trading.state_manager import restore_runtime_vars
            restore_runtime_vars(context, state_json, g)

        # 日频策略逻辑（before_trading_start / handle_data / run_daily / run_weekly
        # 回调）每个交易日只执行一次。hourly 调度下同一交易日的后续运行只刷新行情与
        # NAV，不再重复推进计数器或调仓，从根上消除“同日买入又卖出”的换手。
        if is_new_trade_day:
            # before_trading_start
            if strategy_funcs.get('before_trading_start'):
                try:
                    strategy_funcs['before_trading_start'].__globals__.update(api_ns)
                    strategy_funcs['before_trading_start'](context)
                except Exception as e:
                    logging.warning(f"[模拟交易] before_trading_start 异常: {e}")

            # handle_data
            if strategy_funcs.get('handle_data'):
                try:
                    strategy_funcs['handle_data'].__globals__.update(api_ns)
                    strategy_funcs['handle_data'](context, data_proxy)
                except Exception as e:
                    logging.warning(f"[模拟交易] handle_data 异常: {e}")

            # 执行 run_weekly 注册的回调
            if api_ns.get('_weekly_callbacks'):
                py_weekday = run_date_nph.weekday() if hasattr(run_date_nph, 'weekday') else pd.Timestamp(run_date_nph).weekday()
                jq_weekday = py_weekday + 1  # 聚宽: 1=Mon ... 5=Fri
                for (cb, wd) in api_ns['_weekly_callbacks']:
                    if jq_weekday == wd:
                        try:
                            cb.__globals__.update(api_ns)
                            cb(context)
                        except Exception as e:
                            cb_name = getattr(cb, '__name__', str(cb))
                            logging.warning(f"[模拟交易] run_weekly({cb_name}) 异常: {e}")

            # 执行 run_daily 注册的回调
            for cb in api_ns.get('_daily_callbacks', []):
                try:
                    cb.__globals__.update(api_ns)
                    cb(context)
                except Exception as e:
                    cb_name = getattr(cb, '__name__', str(cb))
                    logging.warning(f"[模拟交易] run_daily({cb_name}) 异常: {e}")
        else:
            logging.info(
                f"[模拟交易] #{paper_id} {date_str} 同一交易日重入，"
                f"跳过日频策略逻辑（仅刷新行情/NAV）")

        # 7. 撮合订单
        # 同 bar 对冲单净额合并：消除同一标的在一次 handle_data 内“卖光再买回”的
        # 无效换手与双倍佣金（同日买卖的结构性兜底，惠及所有策略）。
        pending_orders = _net_same_bar_orders(pending_orders, context, today_prices)
        trade_records = []
        # Phase 2: 与 trade_records 严格 1:1 对应，记录每笔成交对应的策略原始订单输入。
        signal_inputs = []
        for order_info in pending_orders:
            code = order_info['code']
            if code not in today_prices:
                logging.warning(f"[模拟交易] 股票 {code} 无当日行情数据，跳过订单")
                continue

            exec_price = today_prices[code]
            amount = order_info.get('amount')

            if amount is None and order_info.get('value') is not None:
                value = order_info['value']
                if value > 0:
                    amount = int(value / exec_price / 100) * 100
                else:
                    amount = -int(abs(value) / exec_price / 100) * 100

            if not amount or amount == 0:
                continue

            if amount > 0:
                # 买入
                amount = int(amount / 100) * 100
                if amount <= 0:
                    continue
                actual_price = exec_price * (1 + context.slippage_rate)
                total_cost = actual_price * amount
                commission = max(total_cost * context.commission_rate, 5.0)
                if total_cost + commission > context.portfolio.available_cash:
                    affordable = context.portfolio.available_cash / (actual_price * (1 + context.commission_rate))
                    amount = int(affordable / 100) * 100
                    if amount <= 0:
                        continue
                    total_cost = actual_price * amount
                    commission = max(total_cost * context.commission_rate, 5.0)
                    # 防御：最低佣金5元可能导致超支
                    if total_cost + commission > context.portfolio.available_cash:
                        continue

                pos = context.portfolio._get_or_create_position(code)
                if not pos.name:
                    pos.name = _resolve_stock_name(code)
                pos._on_buy(amount, actual_price, commission)
                pos._update_price(exec_price)  # 用市场收盘价估值，而非含滑点的成交价
                context.portfolio.available_cash -= (total_cost + commission)

                trade = TradeRecord(run_date_nph, code, pos.name, 'buy', exec_price, amount)
                trade.commission = round(commission, 2)
                try:
                    from quantia.core.backtest import trade_decision as _td
                    _derived = _build_derived_reason(
                        'buy', order_info, api_ns.get('_log_buffer') or [],
                        exec_price=exec_price, exec_amount=amount,
                        strategy_name=strategy_name)
                    _r = _td.resolve_reason('buy', order_info.get('reason'),
                                             derived_reason=_derived)
                    trade.reason = _r.get('reason', '')
                    trade.reason_source = _r.get('reason_source', '')
                except Exception:
                    trade.reason = order_info.get('reason') or ''
                trade_records.append(trade)
                signal_inputs.append(order_info)

            elif amount < 0:
                # 卖出
                sell_amount = abs(amount)
                pos = context.portfolio.positions.get(code)
                if not pos or pos.closeable_amount <= 0:
                    continue
                sell_amount = min(sell_amount, pos.closeable_amount)
                if sell_amount <= 0:
                    continue

                actual_price = exec_price * (1 - context.slippage_rate)
                total_income = actual_price * sell_amount
                commission = max(total_income * context.commission_rate, 5.0)
                tax = total_income * context.stamp_tax_rate

                # Bug 修复：在 _on_sell 之前捕获 avg_cost；若清仓 _on_sell 会把
                # avg_cost 重置为 0，导致后续平仓盈亏/收益率计算永远为 0。
                avg_cost_before = float(pos.avg_cost or 0.0)
                if not pos.name:
                    pos.name = _resolve_stock_name(code)
                pos_name_before = pos.name
                pos._on_sell(sell_amount, exec_price)  # 剩余持仓以市场收盘价估值
                context.portfolio.available_cash += (total_income - commission - tax)

                trade = TradeRecord(run_date_nph, code, pos_name_before, 'sell', exec_price, sell_amount)
                trade.commission = round(commission, 2)
                trade.tax = round(tax, 2)
                # 平仓盈亏 = (实际成交价 - 持仓均价) * 数量 - 佣金 - 印花税
                # 收益率 = (实际成交价 / 持仓均价 - 1) * 100   （含滑点扣减）
                if avg_cost_before > 0 and sell_amount > 0:
                    trade.close_profit = (actual_price - avg_cost_before) * sell_amount - commission - tax
                    trade.return_rate = (actual_price / avg_cost_before - 1.0) * 100.0
                try:
                    from quantia.core.backtest import trade_decision as _td
                    _derived = _build_derived_reason(
                        'sell', order_info, api_ns.get('_log_buffer') or [],
                        exec_price=exec_price, exec_amount=sell_amount,
                        strategy_name=strategy_name)
                    _r = _td.resolve_reason('sell', order_info.get('reason'),
                                             derived_reason=_derived)
                    trade.reason = _r.get('reason', '')
                    trade.reason_source = _r.get('reason_source', '')
                except Exception:
                    trade.reason = order_info.get('reason') or ''
                trade_records.append(trade)
                signal_inputs.append(order_info)

        context.portfolio._update_value()

        # after_trading_end
        if strategy_funcs.get('after_trading_end'):
            try:
                strategy_funcs['after_trading_end'].__globals__.update(api_ns)
                strategy_funcs['after_trading_end'](context)
            except Exception as e:
                logging.warning(f"[模拟交易] after_trading_end 异常: {e}")

        # 8–11: 保存状态、交易、持仓、NAV（在单个事务中执行）
        _ensure_trade_table()
        _ensure_position_table()
        _ensure_nav_table()
        _ensure_intraday_nav_table()

        position_value = context.portfolio.total_value - context.portfolio.available_cash
        benchmark_value = _compute_paper_benchmark_value(context, paper_id, date_str)
        new_state = serialize_portfolio(context)

        with mdb.get_connection() as conn:
            conn.autocommit(False)
            try:
                cur = conn.cursor()

                # 8. 保存状态
                try:
                    cur.execute(
                        'UPDATE cn_stock_paper_trading SET last_run_date=%s, last_run_at=%s, '
                        'state_json=%s, current_cash=%s, current_value=%s WHERE id=%s',
                        (date_str, now_dt, new_state, context.portfolio.available_cash,
                         context.portfolio.total_value, paper_id))
                except Exception as update_error:
                    if 'last_run_at' not in str(update_error):
                        raise
                    logging.warning("[模拟交易] last_run_at 列不存在，使用旧表结构保存状态")
                    cur.execute(
                        'UPDATE cn_stock_paper_trading SET last_run_date=%s, '
                        'state_json=%s, current_cash=%s, current_value=%s WHERE id=%s',
                        (date_str, new_state,
                         float(context.portfolio.available_cash),
                         float(context.portfolio.total_value), paper_id))

                # 9. 记录交易（executed_at 列不存在时降级为旧结构）
                # Phase 2: 记录每条 trade 的自增 ID，便于事务提交后回填到 cn_stock_trade_signal.trade_id
                trade_ids = []
                for t in trade_records:
                    try:
                        cur.execute(
                            'INSERT INTO cn_stock_backtest_trade '
                            '(paper_id, date, executed_at, code, name, direction, price, amount, value, '
                            ' commission, tax, close_profit, return_rate, slippage_cost, reason, reason_source) '
                            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                            (paper_id, date_str, now_dt, t.code, t.name, t.direction,
                             t.price, t.amount, t.value, t.commission, t.tax,
                             round(float(getattr(t, 'close_profit', 0) or 0), 2),
                             round(float(getattr(t, 'return_rate', 0) or 0), 4),
                             round(float(getattr(t, 'slippage_cost', 0) or 0), 2),
                             (getattr(t, 'reason', '') or '')[:2000],
                             (getattr(t, 'reason_source', '') or '')[:32]))
                    except Exception as trade_err:
                        # 旧表结构兜底：缺 executed_at 或新增的 close_profit 等列时降级。
                        msg = str(trade_err)
                        if ('executed_at' in msg or 'close_profit' in msg or
                                'return_rate' in msg or 'slippage_cost' in msg or
                                'reason' in msg):
                            logging.warning(
                                f"[模拟交易] 列缺失({msg})，使用旧表结构记录交易，新字段丢失")
                            cur.execute(
                                'INSERT INTO cn_stock_backtest_trade '
                                '(paper_id, date, code, name, direction, price, amount, value, commission, tax) '
                                'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                                (paper_id, date_str, t.code, t.name, t.direction,
                                 t.price, t.amount, t.value, t.commission, t.tax))
                        else:
                            raise
                    try:
                        trade_ids.append(int(cur.lastrowid) if cur.lastrowid else None)
                    except Exception:
                        trade_ids.append(None)

                # 10. 持仓快照（DELETE + UPSERT；UPSERT 兜底防止并发调度撞 unique key）
                cur.execute(
                    'DELETE FROM cn_stock_backtest_position WHERE paper_id=%s AND date=%s',
                    (paper_id, date_str))
                for code, pos in context.portfolio.positions.items():
                    if pos.amount > 0:
                        weight = pos.value / context.portfolio.total_value * 100 if context.portfolio.total_value > 0 else 0
                        cur.execute(
                            'INSERT INTO cn_stock_backtest_position '
                            '(paper_id, date, code, name, amount, avg_cost, close_price, '
                            'market_value, profit, profit_rate, weight) '
                            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) '
                            'ON DUPLICATE KEY UPDATE name=VALUES(name), amount=VALUES(amount), '
                            'avg_cost=VALUES(avg_cost), close_price=VALUES(close_price), '
                            'market_value=VALUES(market_value), profit=VALUES(profit), '
                            'profit_rate=VALUES(profit_rate), weight=VALUES(weight)',
                            (paper_id, date_str, code, pos.name, pos.amount,
                             round(pos.avg_cost, 3), round(pos.price, 3),
                             round(pos.value, 2), round(pos.profit, 2),
                             round(pos.profit_rate, 6), round(weight, 6)))

                # 11. 每日 NAV 记录（UPSERT）
                cur.execute(
                    'INSERT INTO cn_stock_paper_nav '
                    '(paper_id, date, total_value, cash, position_value, benchmark_value) '
                    'VALUES (%s,%s,%s,%s,%s,%s) '
                    'ON DUPLICATE KEY UPDATE total_value=VALUES(total_value), '
                    'cash=VALUES(cash), position_value=VALUES(position_value), '
                    'benchmark_value=VALUES(benchmark_value)',
                    (paper_id, date_str,
                     round(context.portfolio.total_value, 2),
                     round(context.portfolio.available_cash, 2),
                     round(position_value, 2),
                     benchmark_value))

                # 11b. 日内实时 NAV 快照（hourly/15m 调度下每次写入，日级调度仅在收盘后一条）
                try:
                    cur.execute(
                        'INSERT INTO cn_stock_paper_nav_intraday '
                        '(paper_id, datetime, total_value, cash, position_value) '
                        'VALUES (%s,%s,%s,%s,%s) '
                        'ON DUPLICATE KEY UPDATE total_value=VALUES(total_value), '
                        'cash=VALUES(cash), position_value=VALUES(position_value)',
                        (paper_id, now_dt,
                         round(context.portfolio.total_value, 2),
                         round(context.portfolio.available_cash, 2),
                         round(position_value, 2)))
                except Exception as intraday_err:
                    logging.warning(
                        f"[模拟交易] 日内 NAV 快照写入失败(不阢达主事务): {intraday_err}")

                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    logging.exception(f"[模拟交易] 模拟盘 #{paper_id} 事务回滚失败")
                raise
            finally:
                try:
                    conn.autocommit(True)
                except Exception:
                    logging.warning(f"[模拟交易] 模拟盘 #{paper_id} 恢复 autocommit 失败", exc_info=True)

        logging.info(f"[模拟交易] 模拟盘 #{paper_id} 完成: "
                     f"交易 {len(trade_records)} 笔, "
                     f"总资产 {context.portfolio.total_value:.2f}")

        # Phase 2: 主事务提交成功后再持久化交易信号 / 决策明细 / 指标快照 / 候选筛选快照。
        # 单独事务，任何失败仅 warning，不回滚已提交的成交。
        signal_id_by_index = {}
        if trade_records:
            try:
                from quantia.core.backtest import trade_decision as _td
                from quantia.core.backtest import trade_signal_store as _tss
                run_id = f"paper-{paper_id}-{now_dt.strftime('%Y%m%d%H%M%S')}"
                for idx, t in enumerate(trade_records):
                    order_info = signal_inputs[idx] if idx < len(signal_inputs) else {}
                    # 复用撮合阶段已落到 TradeRecord 的真实 reason / reason_source，
                    # 避免在此处再次 resolve 时丢失 derived 上下文，导致信号表里又
                    # 写回 generated 兜底文案。
                    resolved = {
                        'reason': getattr(t, 'reason', '') or '',
                        'reason_source': getattr(t, 'reason_source', '') or 'generated',
                    }
                    if not resolved['reason']:
                        resolved = _td.resolve_reason(t.direction, order_info.get('reason'))
                    norm = _td.normalize_decision_payload(
                        order_info.get('decision'),
                        indicators=order_info.get('indicators'),
                        selection=order_info.get('selection'),
                    )
                    sig_hash = _td.compute_signal_hash(
                        source_type='paper', source_id=paper_id, run_id=run_id,
                        code=t.code, direction=t.direction, signal_date=date_str,
                        requested_amount=order_info.get('amount'),
                        requested_value=order_info.get('value'),
                    )
                    # Phase 4: AI 评分（默认禁用 → ai_* 全部 None；启用但非
                    # gate → 仅留痕；启用 gate → 拒绝路径在 _order_proxy 处理，
                    # 此处只把评分结果落库与 signal 关联）。
                    ai_meta = {}
                    try:
                        from quantia.ai_decision import service as _ai_svc
                        from quantia.ai_decision import config as _ai_cfg
                        _cfg = _ai_cfg.load_config_for_source('paper', paper_id)
                        if _cfg is not None and _cfg.is_enabled():
                            ai_meta = _ai_svc.score_trade(
                                cfg=_cfg, source_type='paper', source_id=paper_id, run_id=run_id,
                                code=t.code, name=t.name,
                                decision_date=date_str,
                                decision_phase='post_signal',
                                direction=t.direction,
                                indicators=order_info.get('indicators'),
                                selection=order_info.get('selection'),
                            ) or {}
                    except Exception as ai_err:
                        logging.warning(f"[模拟交易] AI 评分调用失败(不影响交易): {ai_err}")
                        ai_meta = {}
                    sig_id = _tss.persist_signal_with_relations(
                        source_type='paper', source_id=paper_id, run_id=run_id,
                        strategy_id=None, strategy_name=None,
                        signal_date=date_str, code=t.code, name=t.name,
                        direction=t.direction, order_api=order_info.get('order_api'),
                        requested_amount=order_info.get('amount'),
                        requested_value=order_info.get('value'),
                        target_amount=order_info.get('target_amount'),
                        target_percent=order_info.get('target_percent'),
                        reason=resolved['reason'], reason_source=resolved['reason_source'],
                        signal_hash=sig_hash,
                        decision_rules=norm.get('rules') or None,
                        indicators=norm.get('indicators') or None,
                        selection=norm.get('selection') or None,
                        ai_score_id=ai_meta.get('ai_score_id'),
                        ai_score=ai_meta.get('ai_score'),
                        ai_action=ai_meta.get('ai_action'),
                        ai_gate_result=ai_meta.get('ai_gate_result'),
                    )
                    if sig_id:
                        signal_id_by_index[idx] = sig_id
                        tid = trade_ids[idx] if idx < len(trade_ids) else None
                        if tid:
                            _tss.link_signal_to_trade(sig_id, tid)
            except Exception as sig_err:
                logging.warning(f"[模拟交易] 模拟盘 #{paper_id} 交易信号持久化失败(不影响交易): {sig_err}",
                                exc_info=True)

        if trade_records:
            try:
                from quantia.notification import notify_trade_records
                # Phase 2 / 文档 §7：把策略原始 signal_id + 模拟盘/策略/运行 元数据 +
                # 成交后仓位/平仓盈亏/收益率/滑点透传给通知层，使钉钉 markdown
                # 与文档 §7.1 / §7.2 模板一一对应。
                total_value_now = float(getattr(context.portfolio, 'total_value', 0.0) or 0.0)
                signal_meta = []
                for idx, t in enumerate(trade_records):
                    pos_after_pct = None
                    try:
                        if total_value_now > 0:
                            pos_value = float(getattr(t, 'value', 0) or 0)
                            pos_after_pct = pos_value / total_value_now
                    except Exception:
                        pos_after_pct = None
                    signal_meta.append({
                        'signal_id': signal_id_by_index.get(idx),
                        'paper_name': paper_name,
                        'strategy_name': strategy_name or strategy_code,
                        'strategy_code': strategy_code,
                        'run_id': run_id if 'run_id' in locals() else None,
                        'slippage_cost': getattr(t, 'slippage_cost', None),
                        'close_profit': getattr(t, 'close_profit', None),
                        'return_rate': getattr(t, 'return_rate', None),
                        'position_after_pct': pos_after_pct,
                    })
                notify_stats = notify_trade_records(
                    paper_id, trade_records, date_str,
                    executed_at=now_dt, signal_meta=signal_meta)
                logging.info(f"[模拟交易] 模拟盘 #{paper_id} 通知事件: {notify_stats}")
            except Exception as notify_error:
                logging.warning(f"[模拟交易] 模拟盘 #{paper_id} 通知处理失败(不影响交易): {notify_error}", exc_info=True)

        result = {
            'status': 'ok',
            'message': f'执行完成，{len(trade_records)} 笔交易',
            'trades': len(trade_records),
            'total_value': round(context.portfolio.total_value, 2),
        }
        return result

    except Exception as e:
        logging.error(f"[模拟交易] 模拟盘 #{paper_id} 异常", exc_info=True)
        result = {'status': 'error', 'message': str(e)}
        return result

    finally:
        # 无论成功/失败/跳过，都记录执行日志到 DB
        if result is not None:
            try:
                from quantia.paper_trading.scheduler import (
                    _ensure_execution_log_table, _save_execution_log)
                _save_execution_log(
                    paper_id, date_str or str(datetime.date.today()),
                    started_at, result.get('status', 'unknown'),
                    result.get('message', ''),
                    trades=result.get('trades', 0),
                    total_value=result.get('total_value'))
            except Exception:
                logging.debug("[模拟交易] 记录执行日志失败", exc_info=True)


def run_all_paper_trading(scheduled=False):
    """
    执行所有状态为 running 的模拟盘。

    可由 cron 定时触发，每个交易日收盘后执行。
    """
    import quantia.lib.database as mdb

    _ensure_paper_table()
    rows = mdb.executeSqlFetch(
        'SELECT id FROM cn_stock_paper_trading WHERE status = %s', ('running',))

    if not rows:
        logging.info("[模拟交易] 无运行中的模拟盘")
        return

    results = []
    for row in rows:
        paper_id = row[0]
        try:
            result = run_paper_trading_daily(paper_id, scheduled=scheduled)
        except Exception as e:
            logging.error(f"[模拟交易] #{paper_id} 执行异常", exc_info=True)
            result = {'status': 'error', 'message': str(e)}
        results.append({'id': paper_id, **result})
        logging.info(f"[模拟交易] #{paper_id}: {result.get('status')} - {result.get('message', '')}")

    return results


def _create_api(context, data_proxy, g):
    """创建策略 API 命名空间（兼容聚宽风格调用）"""

    def history(code, count, field='close'):
        code = _normalize_security_code(code)
        df = context._engine._stock_data.get(code) if hasattr(context, '_engine') and context._engine else None
        if df is None:
            start_date = (pd.Timestamp(context.current_dt) - pd.Timedelta(days=max(int(count) * 3, 80))).strftime('%Y-%m-%d')
            end_date = pd.Timestamp(context.current_dt).strftime('%Y-%m-%d')
            loaded_code, loaded_df = _load_security_data(code, start_date, end_date)
            if loaded_df is not None and hasattr(context, '_engine') and context._engine:
                code = loaded_code
                _cache_security_data(context, data_proxy, code, loaded_df)
                df = loaded_df
        if df is None:
            return pd.Series(dtype=float)
        mask = df['date'] <= pd.Timestamp(context.current_dt)
        subset = df.loc[mask].tail(count)
        if field in subset.columns:
            return subset[field].reset_index(drop=True)
        return pd.Series(dtype=float)

    def attribute_history(security, count, unit='1d', fields=None,
                          skip_paused=True, df=True, fq='pre'):
        """聚宽 attribute_history 兼容"""
        code = security.split('.')[0] if '.' in security else security
        stock_df = context._engine._stock_data.get(code) if hasattr(context, '_engine') and context._engine else None
        if stock_df is None:
            start_date = (pd.Timestamp(context.current_dt) - pd.Timedelta(days=max(int(count) * 3, 80))).strftime('%Y-%m-%d')
            end_date = pd.Timestamp(context.current_dt).strftime('%Y-%m-%d')
            loaded_code, loaded_df = _load_security_data(code, start_date, end_date)
            if loaded_df is not None and hasattr(context, '_engine') and context._engine:
                code = loaded_code
                _cache_security_data(context, data_proxy, code, loaded_df)
                stock_df = loaded_df
        if stock_df is None:
            cols = fields or ['close']
            return pd.DataFrame(columns=cols)
        mask = stock_df['date'] <= pd.Timestamp(context.current_dt)
        subset = stock_df.loc[mask].tail(count)
        if fields:
            cols = [f for f in fields if f in subset.columns]
            return subset[cols].reset_index(drop=True)
        return subset[['open', 'high', 'low', 'close', 'volume']].reset_index(drop=True)

    def get_price(code, start_date=None, end_date=None, fields=None):
        code = _normalize_security_code(code)
        df = context._engine._stock_data.get(code) if hasattr(context, '_engine') and context._engine else None
        if df is None:
            return pd.DataFrame()
        result = df.copy()
        if start_date:
            result = result[result['date'] >= pd.Timestamp(start_date)]
        if end_date:
            result = result[result['date'] <= pd.Timestamp(end_date)]
        if fields:
            cols = ['date'] + [f for f in fields if f in result.columns]
            result = result[cols]
        return result.reset_index(drop=True)

    def set_order_cost(cost_obj=None, type='stock', **kwargs):
        """兼容聚宽 set_order_cost(OrderCost(...), type='stock') 及关键字参数"""
        if cost_obj is not None and isinstance(cost_obj, dict):
            context.commission_rate = cost_obj.get('open_commission', 0.0003)
            context.stamp_tax_rate = cost_obj.get('close_tax', 0.001)
        elif cost_obj is not None and hasattr(cost_obj, '_data'):
            # _OrderCost object
            context.commission_rate = cost_obj._data.get('open_commission', 0.0003)
            context.stamp_tax_rate = cost_obj._data.get('close_tax', 0.001)
        elif isinstance(cost_obj, (int, float)):
            context.commission_rate = cost_obj
        # 支持关键字参数：commission, tax, slippage
        if 'commission' in kwargs:
            context.commission_rate = kwargs['commission']
        if 'tax' in kwargs:
            context.stamp_tax_rate = kwargs['tax']
        if 'slippage' in kwargs:
            context.slippage_rate = kwargs['slippage']

    class _OrderCost:
        """聚宽 OrderCost 兼容"""
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
            self._data = kwargs
        def get(self, key, default=None):
            return self._data.get(key, default)

    # run_daily 回调注册
    _daily_callbacks = []
    _weekly_callbacks = []

    def run_daily(func, time='every_bar', reference_security=None):
        _daily_callbacks.append(func)

    def run_weekly(func, weekday=1, time='every_bar', reference_security=None):
        _weekly_callbacks.append((func, weekday))

    def run_monthly(func, monthday=1, time='every_bar', reference_security=None):
        _daily_callbacks.append(func)

    class _Log:
        def __init__(self, buf):
            self._buf = buf
        def _capture(self, level, msg):
            try:
                text = msg if isinstance(msg, str) else str(msg)
            except Exception:
                text = repr(msg)
            self._buf.append(f"[{level}] {text}")
            # 限长，避免长跑模拟盘内存涨
            if len(self._buf) > 200:
                del self._buf[:len(self._buf) - 200]
        def info(self, msg): self._capture('info', msg); logging.info(f"[模拟盘策略] {msg}")
        def warn(self, msg): self._capture('warn', msg); logging.warning(f"[模拟盘策略] {msg}")
        def warning(self, msg): self._capture('warn', msg); logging.warning(f"[模拟盘策略] {msg}")
        def error(self, msg): self._capture('error', msg); logging.error(f"[模拟盘策略] {msg}")
        def debug(self, msg): logging.debug(f"[模拟盘策略] {msg}")
        def set_level(self, *args, **kwargs): pass

    _strategy_log_buffer = []

    def get_all_cached_stocks():
        try:
            from quantia.core.backtest.data_feed import get_all_cached_stocks as _gacs
            return _gacs()
        except Exception:
            return []

    # ── 基本面数据查询（基于实盘数据 cn_stock_selection / cn_stock_spot）──

    # 聚宽字段名 → cn_stock_selection 列名映射
    _JQ_FIELD_MAP = {
        # valuation
        'market_cap': 'total_market_cap',
        'pe_ratio': 'pe9',
        'pb_ratio': 'pbnewmrq',
        'circulating_market_cap': 'free_cap',
        # indicator
        'roe': 'roe_weight',
        'eps': 'basic_eps',
        'inc_total_revenue_year_on_year': 'toi_yoy_ratio',
        'inc_net_profit_year_on_year': 'netprofit_yoy_ratio',
        'inc_revenue_year_on_year': 'toi_yoy_ratio',
        'net_profit_margin': 'sale_npr',
        'gross_profit_margin': 'sale_gpr',
        # balance
        'total_liability': 'debt_asset_ratio',  # 近似：资产负债率
        'total_assets': None,  # cn_stock_selection 无此字段
        'total_current_assets': None,
        'total_current_liability': None,
        # cash_flow
        'net_operate_cash_flow': 'per_netcash_operate',  # 近似：每股经营现金流
        'net_invest_cash_flow': None,
        'net_finance_cash_flow': None,
    }

    def get_fundamentals(q, date=None):
        """从 cn_stock_selection 查询真实基本面数据（模拟交易专用）。

        cn_stock_selection 由每日定时任务从东方财富选股器 API 获取，
        包含 70+ 列真实基本面数据（PE/PB/ROE/毛利率/负债率/增长率等），
        与 GPT 综合选股策略使用完全相同的数据源。
        """
        query_date = date or context.current_dt
        date_str = query_date.strftime('%Y-%m-%d') if hasattr(query_date, 'strftime') else str(query_date)[:10]

        try:
            import quantia.lib.database as mdb

            # 查询 cn_stock_selection 的最新日期（可能 date_str 当天还没获取到）
            date_rows = mdb.executeSqlFetch(
                'SELECT MAX(date) FROM cn_stock_selection WHERE date <= %s', (date_str,))
            if not date_rows or date_rows[0][0] is None:
                logging.warning(f"[模拟交易] cn_stock_selection 无 <= {date_str} 的数据")
                # 回退到 FundamentalDataProvider
                return _get_fundamentals_fallback(q, query_date)
            actual_date = date_rows[0][0]

            # 构建查询列（code 必选 + 策略请求的字段）
            select_cols = ['code', 'name']
            jq_to_db = {}  # jq_field → db_col 映射（用于结果列重命名）
            from quantia.core.backtest.fundamentals import _FieldExpr
            for field_expr in q._fields:
                if isinstance(field_expr, _FieldExpr):
                    jq_name = field_expr._name
                    db_col = _JQ_FIELD_MAP.get(jq_name, jq_name)
                    if db_col and db_col not in select_cols:
                        select_cols.append(db_col)
                        jq_to_db[jq_name] = db_col

            # 同样处理过滤条件中引用的字段
            for f in q._filters:
                if isinstance(f, tuple) and len(f) >= 3:
                    jq_name = f[1]
                    db_col = _JQ_FIELD_MAP.get(jq_name, jq_name)
                    if db_col and db_col not in select_cols:
                        select_cols.append(db_col)
                        jq_to_db[jq_name] = db_col

            # 也加入估值相关常用列
            for extra in ['total_market_cap', 'free_cap', 'pe9', 'pbnewmrq',
                          'roe_weight', 'sale_gpr', 'sale_npr', 'debt_asset_ratio']:
                if extra not in select_cols:
                    select_cols.append(extra)

            cols_sql = ', '.join(f'`{c}`' for c in select_cols)
            rows = mdb.executeSqlFetch(
                f'SELECT {cols_sql} FROM cn_stock_selection WHERE date = %s AND new_price > 0',
                (actual_date,))

            if not rows or len(rows) == 0:
                logging.warning(f"[模拟交易] cn_stock_selection {actual_date} 无数据")
                return _get_fundamentals_fallback(q, query_date)

            result = pd.DataFrame(rows, columns=select_cols)

            # 数值列转 float
            for c in result.columns:
                if c not in ('code', 'name', 'date'):
                    result[c] = pd.to_numeric(result[c], errors='coerce')

            # 市值单位转换：cn_stock_selection 的 total_market_cap 单位是元 → 转为亿元
            if 'total_market_cap' in result.columns:
                result['total_market_cap'] = result['total_market_cap'] / 1e8  # 元 → 亿
            if 'free_cap' in result.columns:
                result['free_cap'] = result['free_cap'] / 1e8

            # 将 DB 列名映射回聚宽字段名，方便策略使用
            rename_map = {}
            for jq_name, db_col in jq_to_db.items():
                if db_col in result.columns and jq_name != db_col:
                    rename_map[db_col] = jq_name
            # 标准映射（回测引擎兼容）
            if 'total_market_cap' in result.columns:
                rename_map.setdefault('total_market_cap', 'market_cap')
            if 'pe9' in result.columns:
                rename_map.setdefault('pe9', 'pe_ratio')
            if 'pbnewmrq' in result.columns:
                rename_map.setdefault('pbnewmrq', 'pb_ratio')
            if 'free_cap' in result.columns:
                rename_map.setdefault('free_cap', 'circulating_market_cap')
            if 'roe_weight' in result.columns:
                rename_map.setdefault('roe_weight', 'roe')
            if 'basic_eps' in result.columns:
                rename_map.setdefault('basic_eps', 'eps')
            if 'sale_npr' in result.columns:
                rename_map.setdefault('sale_npr', 'net_profit_margin')
            if 'sale_gpr' in result.columns:
                rename_map.setdefault('sale_gpr', 'gross_profit_margin')
            if rename_map:
                result = result.rename(columns=rename_map)

            # 应用过滤条件
            # 构建反向映射: jq_name → db_col（已经 rename 过，所以用 jq_name）
            for f in q._filters:
                if not isinstance(f, tuple) or len(f) < 3:
                    continue
                op = f[0]
                # div_* 操作符处理 balance.total_liability / balance.total_assets 等
                if op.startswith('div_'):
                    # 对于 debt_asset_ratio 已在 cn_stock_selection 中，直接用
                    numerator, denominator = f[1], f[2]
                    threshold = f[3]
                    if numerator == 'total_liability' and denominator == 'total_assets':
                        col = 'debt_asset_ratio'
                        if col in result.columns:
                            cmp = op.replace('div_', '')
                            if cmp == 'lt':
                                result = result[result[col] < threshold * 100]  # 百分比
                            elif cmp == 'gt':
                                result = result[result[col] > threshold * 100]
                            elif cmp == 'le':
                                result = result[result[col] <= threshold * 100]
                            elif cmp == 'ge':
                                result = result[result[col] >= threshold * 100]
                    continue
                field = f[1]
                if field not in result.columns:
                    continue
                if op == 'between' and len(f) >= 4:
                    result = result[(result[field] >= f[2]) & (result[field] <= f[3])]
                elif op == 'gt':
                    result = result[result[field] > f[2]]
                elif op == 'lt':
                    result = result[result[field] < f[2]]
                elif op == 'ge':
                    result = result[result[field] >= f[2]]
                elif op == 'le':
                    result = result[result[field] <= f[2]]
                elif op == 'in_':
                    result = result[result[field].isin(f[2])]

            # 排序
            if q._order_by_clause is not None and isinstance(q._order_by_clause, tuple):
                direction, field = q._order_by_clause
                if field in result.columns:
                    result = result.sort_values(field, ascending=(direction == 'asc'))

            # 限制行数
            if q._limit_val is not None:
                result = result.head(q._limit_val)

            if len(result) > 0:
                logging.info(f"[模拟交易] get_fundamentals 从 cn_stock_selection({actual_date}) "
                             f"查得 {len(result)} 只股票")

            return result.reset_index(drop=True)

        except Exception as e:
            logging.warning(f"[模拟交易] get_fundamentals 查询异常: {e}")
            return _get_fundamentals_fallback(q, query_date)

    def _get_fundamentals_fallback(q, query_date):
        """回退到 FundamentalDataProvider（当 cn_stock_selection 不可用时）"""
        provider = _get_fundamental_provider(context._engine if hasattr(context, '_engine') else None)
        if provider is None:
            return pd.DataFrame()
        try:
            return provider.get_fundamentals(q, query_date)
        except Exception:
            return pd.DataFrame()

    # ── 指数成份股查询 ──
    # 主流宽基指数 → cn_stock_selection 标记列（白名单，固定取值，无注入风险）
    _SELECTION_FLAG_COL = {
        '000300': 'is_hs300',    # 沪深300
        '000016': 'is_sz50',     # 上证50
        '000905': 'is_zz500',    # 中证500
        '000852': 'is_zz1000',   # 中证1000
        '399673': 'is_cy50',     # 创业板50
    }
    # 中证银行指数(399951) 无对应 is_* 列，用内置静态名单
    _STATIC_INDEX_STOCKS = {
        '399951': [
            '601398', '601939', '601288', '601988', '600036', '601166',
            '000001', '601328', '601818', '600016', '601009', '600000',
            '601229', '002142', '600015', '601838', '601916', '601998',
            '600926', '601169', '601077', '600908', '601658', '601528',
            '601860', '601963', '601187', '002839', '002936', '002948',
            '002966', '600919',
        ],
    }
    _index_stocks_cache = {}

    def get_index_stocks(index_code, date=None):
        clean = index_code.split('.')[0] if '.' in index_code else index_code
        if clean in _STATIC_INDEX_STOCKS:
            return list(_STATIC_INDEX_STOCKS[clean])

        col = _SELECTION_FLAG_COL.get(clean)
        if col:
            if clean in _index_stocks_cache:
                return list(_index_stocks_cache[clean])
            try:
                import quantia.lib.database as mdb
                cur = date or context.current_dt
                ref_date = (cur.strftime('%Y-%m-%d')
                            if hasattr(cur, 'strftime') else str(cur)[:10]) if cur else None
                snap = None
                if ref_date:
                    r = mdb.executeSqlFetch(
                        "SELECT MAX(date) FROM cn_stock_selection "
                        "WHERE date <= %s AND `" + col + "` = %s",
                        (ref_date, '是'))
                    snap = r[0][0] if r and r[0] else None
                if snap is None:  # 退回全局最新快照
                    r = mdb.executeSqlFetch(
                        "SELECT MAX(date) FROM cn_stock_selection "
                        "WHERE `" + col + "` = %s", ('是',))
                    snap = r[0][0] if r and r[0] else None
                stocks = []
                if snap is not None:
                    rows = mdb.executeSqlFetch(
                        "SELECT DISTINCT code FROM cn_stock_selection "
                        "WHERE date = %s AND `" + col + "` = %s",
                        (snap, '是'))
                    stocks = [row[0] for row in (rows or [])]
                _index_stocks_cache[clean] = stocks
                if not stocks:
                    logging.warning(f"[模拟交易] 指数 {index_code} 在 cn_stock_selection "
                                    f"无成份股数据，返回空列表")
                return list(stocks)
            except Exception as e:
                logging.warning(f"[模拟交易] get_index_stocks({index_code}) 查询失败: {e}")
                _index_stocks_cache[clean] = []
                return []

        logging.warning(f"[模拟交易] 未知指数 {index_code}，返回空列表")
        return []


    # ── get_all_securities ──
    def get_all_securities(types=None, date=None):
        codes = get_all_cached_stocks()
        if codes:
            return pd.DataFrame({'code': codes, 'display_name': codes, 'type': 'stock'}).set_index('code')
        return pd.DataFrame(columns=['display_name', 'type'])

    # ── get_current_data ──
    def get_current_data():
        provider = _get_fundamental_provider(context._engine if hasattr(context, '_engine') else None)
        if provider is not None:
            try:
                from quantia.core.backtest.fundamentals import _CurrentDataProxy
                return _CurrentDataProxy(provider, context._engine if hasattr(context, '_engine') else None)
            except Exception:
                pass
        return {}

    # ── 聚宽 query DSL 对象 ──
    try:
        from quantia.core.backtest.fundamentals import valuation, indicator, balance, cash_flow, query as jq_query
        _valuation = valuation
        _indicator = indicator
        _balance = balance
        _cash_flow = cash_flow
        _query = jq_query
    except Exception:
        _valuation = None
        _indicator = None
        _balance = None
        _cash_flow = None
        _query = lambda *a, **kw: None

    ns = {
        'history': history,
        'attribute_history': attribute_history,
        'get_price': get_price,
        'log': _Log(_strategy_log_buffer),
        '_log_buffer': _strategy_log_buffer,
        'g': g,
        'record': lambda **kw: None,
        'set_benchmark': lambda code: setattr(context, 'benchmark', _normalize_security_code(code)),
        'set_option': lambda *a, **kw: None,
        'set_order_cost': set_order_cost,
        'OrderCost': lambda **kw: kw,
        'run_daily': run_daily,
        'run_weekly': run_weekly,
        'run_monthly': run_monthly,
        'order_target': lambda code, amount: None,
        'order_value': lambda code, value: None,
        'order': lambda code, amount: None,
        'order_target_percent': lambda code, percent: None,
        'get_index_stocks': get_index_stocks,
        'get_all_securities': get_all_securities,
        'get_all_cached_stocks': get_all_cached_stocks,
        'get_fundamentals': get_fundamentals,
        'get_current_data': get_current_data,
        'get_security_info': lambda code: type('Info', (), {'start_date': None, 'display_name': '', 'name': ''})(),
        'normalize_code': lambda code: code.split('.')[0] if '.' in code else code,
        '_daily_callbacks': _daily_callbacks,
        '_weekly_callbacks': _weekly_callbacks,
    }
    # 注入聚宽 query DSL 对象
    if _valuation is not None:
        ns['valuation'] = _valuation
        ns['indicator'] = _indicator
        ns['balance'] = _balance
        ns['cash_flow'] = _cash_flow
        ns['query'] = _query
    return ns


def _update_paper_error(paper_id, message):
    """更新模拟盘错误状态"""
    import quantia.lib.database as mdb
    try:
        mdb.executeSql(
            'UPDATE cn_stock_paper_trading SET status=%s WHERE id=%s',
            ('stopped', paper_id))
    except Exception:
        pass


_RUN_FREQUENCY_MINUTES = {
    'daily': 24 * 60,
    'hourly': 60,
    '15m': 15,
}


def _normalize_run_frequency(value):
    value = (value or 'daily').strip() if isinstance(value, str) else 'daily'
    return value if value in _RUN_FREQUENCY_MINUTES else 'daily'


def _as_datetime(value):
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.date):
        return datetime.datetime.combine(value, datetime.time.min)
    if value:
        text = str(value).strip()
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
            try:
                return datetime.datetime.strptime(text[:19] if 'T' in text else text, fmt)
            except ValueError:
                continue
    return None


# 每日模拟盘等到收盘+数据落库后才执行；可通过 QUANTIA_PAPER_DAILY_AFTER_HOUR 调整
import os as _os
try:
    _PAPER_DAILY_AFTER_HOUR = int(_os.environ.get('QUANTIA_PAPER_DAILY_AFTER_HOUR', '16'))
except (TypeError, ValueError):
    _PAPER_DAILY_AFTER_HOUR = 16


def _is_paper_due(run_frequency, start_at, last_run_date, last_run_at,
                  date_str, now_dt, scheduled=False):
    start_dt = _as_datetime(start_at)
    if start_dt and now_dt < start_dt:
        return False, f'未到开始时间 ({start_dt.strftime("%Y-%m-%d %H:%M:%S")})'

    freq = _normalize_run_frequency(run_frequency)
    if freq == 'daily':
        if scheduled and now_dt.hour < _PAPER_DAILY_AFTER_HOUR:
            return False, f'等待今日收盘后执行 (≥ {_PAPER_DAILY_AFTER_HOUR:02d}:00)'
        if last_run_date and str(last_run_date) >= date_str:
            return False, f'今日已运行 ({last_run_date})'
        return True, 'ok'

    # hourly / 15m: 数据源仍是日级 K 线 + cn_stock_spot 日级快照，
    # 盘中并无分钟级行情；保留触发能力但避免盘前/午休空跑。
    if scheduled:
        try:
            import quantia.lib.trade_time as _trd
            in_session = _trd.is_tradetime(now_dt)
            after_close = _trd.is_close(now_dt)
            if not (in_session or after_close):
                return False, '非交易时段'
        except Exception:
            # trade_time 加载失败时不阢达主逻辑
            pass
    last_dt = _as_datetime(last_run_at)
    if last_dt:
        interval = datetime.timedelta(minutes=_RUN_FREQUENCY_MINUTES[freq])
        next_dt = last_dt + interval
        if now_dt < next_dt:
            return False, f'未到下次运行时间 ({next_dt.strftime("%Y-%m-%d %H:%M:%S")})'
    return True, 'ok'


def _add_paper_column_safe(column_name, ddl):
    import quantia.lib.database as mdb
    try:
        rows = mdb.executeSqlFetch(
            "SELECT COUNT(*) FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'cn_stock_paper_trading' "
            "AND COLUMN_NAME = %s", (column_name,))
        exists = rows and rows[0][0] > 0
        if not exists:
            mdb.executeSql(f'ALTER TABLE cn_stock_paper_trading ADD COLUMN {ddl}')
    except Exception as e:
        logging.warning(f"[模拟交易] 添加 cn_stock_paper_trading.{column_name} 失败/已存在: {e}")


def _ensure_paper_columns():
    _add_paper_column_safe('backtest_id', '`backtest_id` INT DEFAULT NULL AFTER `strategy_id`')
    _add_paper_column_safe('run_frequency', "`run_frequency` VARCHAR(20) DEFAULT 'daily' AFTER `status`")
    _add_paper_column_safe('start_at', '`start_at` DATETIME DEFAULT CURRENT_TIMESTAMP AFTER `run_frequency`')
    _add_paper_column_safe('last_run_at', '`last_run_at` DATETIME DEFAULT NULL AFTER `last_run_date`')


# 进程内一次性建表标记：cn_stock_paper_trading 是静态 schema，建表/迁移只需检查一次。
# 避免每次 run_all_paper_trading（交易时段每 30min）都触发 checkTableIsExist + 多次
# SELECT COUNT 列检查的无谓 DB 往返（连接占用）。
_paper_table_ensured = False


def _ensure_paper_table():
    global _paper_table_ensured
    if _paper_table_ensured:
        return
    import quantia.lib.database as mdb
    if mdb.checkTableIsExist('cn_stock_paper_trading'):
        _ensure_paper_columns()
        _paper_table_ensured = True
        return
    mdb.executeSql('''
        CREATE TABLE IF NOT EXISTS `cn_stock_paper_trading` (
            `id` INT AUTO_INCREMENT PRIMARY KEY,
            `strategy_id` INT NOT NULL,
            `backtest_id` INT DEFAULT NULL,
            `name` VARCHAR(100),
            `initial_cash` DECIMAL(15,2) DEFAULT 1000000.00,
            `current_cash` DECIMAL(15,2),
            `current_value` DECIMAL(15,2),
            `status` ENUM('running','paused','stopped') DEFAULT 'running',
            `run_frequency` VARCHAR(20) DEFAULT 'daily',
            `start_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
            `started_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
            `last_run_date` DATE,
            `last_run_at` DATETIME DEFAULT NULL,
            `state_json` LONGTEXT,
            INDEX `idx_strategy` (`strategy_id`),
            INDEX `idx_backtest` (`backtest_id`),
            INDEX `idx_status` (`status`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''')
    _paper_table_ensured = True


def _ensure_trade_table():
    import quantia.lib.database as mdb
    if mdb.checkTableIsExist('cn_stock_backtest_trade'):
        # 已存在：检查是否需要补上 executed_at 列（阶殲2升级）
        try:
            cols = mdb.executeSqlFetch(
                "SHOW COLUMNS FROM cn_stock_backtest_trade LIKE 'executed_at'")
            if not cols:
                logging.info("[模拟交易] 为 cn_stock_backtest_trade 添加 executed_at 列")
                mdb.executeSql(
                    'ALTER TABLE cn_stock_backtest_trade '
                    'ADD COLUMN executed_at DATETIME NULL AFTER date')
        except Exception as e:
            logging.warning(f"[模拟交易] executed_at 列检查/迁移失败(不阢达主逻辑): {e}")
        # Phase 3 补丁：补充平仓盈亏 / 收益率 / 滑点成本 / reason / reason_source 列
        # （旧表未持久化导致前端、通知中卖出 PnL 永远为 0，reason 仅能从 signal 表回溯）。
        _migrations = [
            ("close_profit", "ADD COLUMN close_profit DECIMAL(15,2) NULL AFTER tax"),
            ("return_rate",  "ADD COLUMN return_rate DECIMAL(10,4) NULL AFTER close_profit"),
            ("slippage_cost","ADD COLUMN slippage_cost DECIMAL(15,2) NULL AFTER return_rate"),
            ("reason",       "ADD COLUMN reason VARCHAR(2000) NULL AFTER slippage_cost"),
            ("reason_source","ADD COLUMN reason_source VARCHAR(32) NULL AFTER reason"),
        ]
        for col, ddl in _migrations:
            try:
                exists = mdb.executeSqlFetch(f"SHOW COLUMNS FROM cn_stock_backtest_trade LIKE '{col}'")
                if not exists:
                    logging.info(f"[模拟交易] 为 cn_stock_backtest_trade 添加 {col} 列")
                    mdb.executeSql(f"ALTER TABLE cn_stock_backtest_trade {ddl}")
            except Exception as e:
                logging.warning(f"[模拟交易] {col} 列迁移失败(不影响主逻辑): {e}")
        return
    mdb.executeSql('''
        CREATE TABLE IF NOT EXISTS `cn_stock_backtest_trade` (
            `id` INT AUTO_INCREMENT PRIMARY KEY,
            `backtest_id` INT DEFAULT NULL,
            `paper_id` INT DEFAULT NULL,
            `date` DATE NOT NULL,
            `executed_at` DATETIME NULL,
            `code` VARCHAR(6) NOT NULL,
            `name` VARCHAR(20),
            `direction` ENUM('buy','sell') NOT NULL,
            `price` DECIMAL(10,3) NOT NULL,
            `amount` INT NOT NULL,
            `value` DECIMAL(15,2),
            `commission` DECIMAL(10,2),
            `tax` DECIMAL(10,2),
            `close_profit` DECIMAL(15,2) NULL,
            `return_rate` DECIMAL(10,4) NULL,
            `slippage_cost` DECIMAL(15,2) NULL,
            `reason` VARCHAR(2000) NULL,
            `reason_source` VARCHAR(32) NULL,
            INDEX `idx_bt_date` (`backtest_id`, `date`),
            INDEX `idx_paper_date` (`paper_id`, `date`),
            INDEX `idx_paper_executed_at` (`paper_id`, `executed_at`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''')


def _ensure_position_table():
    import quantia.lib.database as mdb
    if mdb.checkTableIsExist('cn_stock_backtest_position'):
        try:
            indexes = mdb.executeSqlFetch(
                "SHOW INDEX FROM cn_stock_backtest_position WHERE Key_name = 'uq_paper_position'")
            if not indexes:
                logging.info("[模拟交易] 为 cn_stock_backtest_position 添加模拟盘持仓唯一索引")
                mdb.executeSql(
                    'ALTER TABLE cn_stock_backtest_position '
                    'ADD UNIQUE KEY uq_paper_position (paper_id, date, code)')
        except Exception as e:
            logging.warning(f"[模拟交易] 持仓唯一索引检查/迁移失败(不影响主逻辑): {e}")
        return
    mdb.executeSql('''
        CREATE TABLE IF NOT EXISTS `cn_stock_backtest_position` (
            `id` INT AUTO_INCREMENT PRIMARY KEY,
            `backtest_id` INT DEFAULT NULL,
            `paper_id` INT DEFAULT NULL,
            `date` DATE NOT NULL,
            `code` VARCHAR(6) NOT NULL,
            `name` VARCHAR(20),
            `amount` INT NOT NULL,
            `avg_cost` DECIMAL(10,3),
            `close_price` DECIMAL(10,3),
            `market_value` DECIMAL(15,2),
            `profit` DECIMAL(15,2),
            `profit_rate` DECIMAL(10,6),
            `weight` DECIMAL(10,6),
            INDEX `idx_bt_date` (`backtest_id`, `date`),
            INDEX `idx_paper_date` (`paper_id`, `date`),
            UNIQUE KEY `uq_paper_position` (`paper_id`, `date`, `code`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''')


def _ensure_nav_table():
    """确保模拟盘每日 NAV 记录表存在"""
    import quantia.lib.database as mdb
    if mdb.checkTableIsExist('cn_stock_paper_nav'):
        try:
            cols = mdb.executeSqlFetch(
                "SHOW COLUMNS FROM cn_stock_paper_nav LIKE 'benchmark_value'")
            if not cols:
                logging.info("[模拟交易] 为 cn_stock_paper_nav 添加 benchmark_value 列")
                mdb.executeSql(
                    'ALTER TABLE cn_stock_paper_nav '
                    'ADD COLUMN benchmark_value DECIMAL(10,6) DEFAULT 1.0 AFTER position_value')
        except Exception as e:
            logging.warning(f"[模拟交易] benchmark_value 列检查/迁移失败(不影响主逻辑): {e}")
        return
    mdb.executeSql('''
        CREATE TABLE IF NOT EXISTS `cn_stock_paper_nav` (
            `id` INT AUTO_INCREMENT PRIMARY KEY,
            `paper_id` INT NOT NULL,
            `date` DATE NOT NULL,
            `total_value` DECIMAL(15,2) NOT NULL,
            `cash` DECIMAL(15,2),
            `position_value` DECIMAL(15,2),
            `benchmark_value` DECIMAL(10,6) DEFAULT 1.0,
            UNIQUE KEY `uq_paper_date` (`paper_id`, `date`),
            INDEX `idx_paper` (`paper_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''')


def _ensure_intraday_nav_table():
    """确保模拟盘日内 NAV 快照表存在（hourly/15m 调度写入）"""
    import quantia.lib.database as mdb
    if mdb.checkTableIsExist('cn_stock_paper_nav_intraday'):
        return
    mdb.executeSql('''
        CREATE TABLE IF NOT EXISTS `cn_stock_paper_nav_intraday` (
            `id` INT AUTO_INCREMENT PRIMARY KEY,
            `paper_id` INT NOT NULL,
            `datetime` DATETIME NOT NULL,
            `total_value` DECIMAL(15,2) NOT NULL,
            `cash` DECIMAL(15,2),
            `position_value` DECIMAL(15,2),
            UNIQUE KEY `uq_paper_dt` (`paper_id`, `datetime`),
            INDEX `idx_paper_dt` (`paper_id`, `datetime`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''')

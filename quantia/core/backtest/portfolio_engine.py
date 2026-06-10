#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
组合回测引擎 — 聚宽风格的事件驱动回测

核心流程：
1. 用户提交策略代码（Python 字符串）
2. 沙箱编译提取 initialize / handle_data 等函数
3. 按交易日逐日驱动：加载行情 → 执行策略 → 撮合订单 → 记录净值
4. 回测完成后计算风险指标，返回结构化结果

支持：
- 多股票组合回测
- T+1 交易规则
- A股涨跌停限制
- 佣金 + 印花税 + 滑点
- 基准对比（沪深300）
- 完整的交易记录和持仓快照
"""

import logging
import datetime
import time
import os
from collections import OrderedDict
import numpy as np
import pandas as pd

from .strategy_context import (
    Context, GlobalVars, DataProxy, Portfolio, Position,
    TradeRecord, NavRecord,
)
from .strategy_sandbox import compile_strategy, validate_code
from .data_feed import load_stock_data, load_multiple_stocks, get_trading_dates, load_benchmark_data, get_all_cached_stocks
from .risk_metrics import calculate_metrics
from .fundamentals import (
    FundamentalDataProvider, valuation as _valuation_obj,
    indicator as _indicator_obj, balance as _balance_obj,
    cash_flow as _cash_flow_obj,
    query as _query_func, OrderCost as _OrderCost,
    _CurrentDataProxy,
)

__author__ = 'Quantia'
__date__ = '2026/03/13'


class _LRUStockData:
    """有界 LRU 缓存，对外表现为 ``{code: DataFrame}`` 字典。

    用于替代回测引擎中无上限增长的 ``_stock_data`` 字典：当常驻股票数量
    超过 ``capacity`` 时，淘汰最久未访问（least-recently-used）的 K 线
    DataFrame 以释放内存，从而把全市场加载改为「流式 / 按需 + 有界常驻」，
    避免无上限加载导致服务器 OOM。被淘汰的股票在后续访问时会通过
    ``_ensure_stock_loaded`` 透明地重新加载，数据完全一致，不影响回测结果。

    ``pin`` 的代码（如基准指数）永不淘汰。
    """

    def __init__(self, capacity):
        self._capacity = max(1, int(capacity))
        self._data = OrderedDict()
        self._pinned = set()

    # —— dict 兼容接口 ——
    def __contains__(self, code):
        return code in self._data

    def __len__(self):
        return len(self._data)

    def __iter__(self):
        # 复制 key 列表，避免迭代期间淘汰导致 RuntimeError
        return iter(list(self._data.keys()))

    def get(self, code, default=None):
        if code in self._data:
            self._data.move_to_end(code)
            return self._data[code]
        return default

    def __getitem__(self, code):
        if code in self._data:
            self._data.move_to_end(code)
            return self._data[code]
        raise KeyError(code)

    def __setitem__(self, code, df):
        if code in self._data:
            self._data.move_to_end(code)
        self._data[code] = df
        self._evict_if_needed()

    def keys(self):
        return list(self._data.keys())

    def values(self):
        return list(self._data.values())

    def items(self):
        return list(self._data.items())

    # —— LRU 控制 ——
    def pin(self, code):
        """将代码标记为常驻（永不淘汰），如基准指数。"""
        self._pinned.add(code)

    def _evict_if_needed(self):
        while len(self._data) > self._capacity:
            evicted = None
            for k in self._data:  # OrderedDict 头部即最久未使用
                if k not in self._pinned:
                    evicted = k
                    break
            if evicted is None:
                break  # 全部被 pin，无法继续淘汰
            self._data.pop(evicted, None)


class PortfolioBacktestEngine:
    """
    组合回测引擎

    使用方式：
        engine = PortfolioBacktestEngine()
        result = engine.run(
            strategy_code='def initialize(context): ...',
            start_date='2024-01-01',
            end_date='2025-01-01',
            initial_cash=1000000,
        )
    """

    # 常见指数代码，用于区分股票和指数（history/get_price 需要不同数据源）
    _INDEX_CODES = {
        '000002', '000003', '000016', '000300', '000688',
        '000852', '000905', '000906', '000985',
        '399001', '399006', '399300', '399905', '399951',
    }

    # 常驻内存中的最大股票数量（K 线 DataFrame）。超出后按 LRU 淘汰，
    # 被淘汰股票在再次访问时透明重载。可通过环境变量覆盖，避免大票池
    # 全市场加载导致 OOM。
    _MAX_STOCKS_IN_MEM = int(os.environ.get('QUANTIA_BT_MAX_STOCKS_IN_MEM', '1000'))
    # 预加载时分批拉取的批大小，降低加载峰值内存。
    _PRELOAD_BATCH_SIZE = int(os.environ.get('QUANTIA_BT_PRELOAD_BATCH', '300'))

    def __init__(self):
        self.context = None
        self.data_proxy = None
        self.g = None
        self._strategy_funcs = None
        self._stock_data = _LRUStockData(self._MAX_STOCKS_IN_MEM)  # {code: DatetimeIndex-indexed DataFrame}，有界 LRU
        self._benchmark_data = None    # DataFrame
        self._nav_records = []         # [NavRecord]
        self._trade_records = []       # [TradeRecord]
        # Phase 3: 与 _trade_records 严格 1:1 对应。记录每笔成交背后
        # 的策略订单输入（reason/decision/indicators/selection/order_api/target_*）。
        # 回测结束后由外部 handler 读取并调用 persist_signal_with_relations。
        self._signal_inputs = []
        self._position_snapshots = []  # [{date, positions: [...]}]
        self._custom_records = {}      # record() 记录的自定义指标
        self._log_messages = []        # 策略日志
        self._pending_orders = []      # 待执行订单（向后兼容，即时执行模式下不使用）
        self._deferred_position_cleanups = []  # 延迟清理的空仓代码（避免迭代中删除字典）
        self._all_codes = set()        # 策略涉及的所有股票代码
        self._daily_callbacks = []     # run_daily() 注册的日级回调
        self._weekly_callbacks = []    # run_weekly() 注册的周级回调 [(func, weekday, time)]
        self._current_day_prices = {}  # 当日价格 {code: close_price}
        self._fundamental_provider = None  # 基本面数据提供器
        self._stock_names = {}         # 股票名称缓存 {code: name}
        self._index_stocks_cache = {}  # get_index_stocks 结果缓存 {clean_code: [codes]}
        # 订单执行遥测：用于在 0 笔交易时给出基于真实运行证据的诊断。
        # 每个键代表一种订单结果，值为发生次数。
        self._order_stats = {
            'submitted': 0,                # _submit_order 调用次数（含被立即拒绝的）
            'executed_buy': 0,             # 成功买入笔数
            'executed_sell': 0,            # 成功卖出笔数
            'rejected_no_data': 0,         # 无行情数据
            'rejected_bad_price': 0,       # 价格<=0
            'rejected_limit_up': 0,        # 涨停买入被拒
            'rejected_limit_down': 0,      # 跌停卖出被拒
            'rejected_zero_amount': 0,     # value/exec_price 取整后 0 股
            'rejected_insufficient_cash': 0,  # 现金不足
            'rejected_no_position': 0,     # 卖出时无持仓 / 可卖余额=0
            'rejected_lot_size': 0,        # 卖出不足 1 手且非残股
        }

    def run(self, strategy_code, start_date, end_date,
            initial_cash=1000000.0, benchmark='000300',
            commission=0.0003, tax=0.001, slippage=0.002):
        """
        运行回测。

        Args:
            strategy_code: Python 策略代码字符串
            start_date: 回测开始日期 'YYYY-MM-DD'
            end_date: 回测结束日期 'YYYY-MM-DD'
            initial_cash: 初始资金
            benchmark: 基准指数代码（默认沪深300）
            commission: 佣金率（双边，默认万三）
            tax: 印花税率（卖方，默认千一）
            slippage: 滑点率（默认千二）

        Returns:
            dict: 回测结果，包含 metrics/nav/trades/positions
        """
        start_time = time.time()
        logging.info(f"[回测引擎] 开始回测: {start_date} ~ {end_date}, 初始资金={initial_cash}")
        self._strategy_errors = []  # 收集策略运行时错误
        self._error_counts = {}  # 相同错误计数，用于抑制重复日志
        # 每次 run() 都重置订单遥测（同一引擎实例可能被多次复用）
        for _k in self._order_stats:
            self._order_stats[_k] = 0

        # 0. 参数校验
        if initial_cash is None or initial_cash <= 0:
            return {'status': 'error', 'message': f'初始资金必须大于0，当前值: {initial_cash}', 'hints': self._diagnose_engine_error(f'初始资金必须大于0，当前值: {initial_cash}')}

        # 1. 编译策略
        self._raw_strategy_code = strategy_code or ''
        try:
            self._strategy_funcs = compile_strategy(strategy_code)
        except (ValueError, SyntaxError) as e:
            return {'status': 'error', 'message': str(e), 'hints': self._diagnose_engine_error(str(e))}

        # 2. 初始化上下文
        self.context = Context(initial_cash)
        self.context.benchmark = benchmark
        self.context.commission_rate = commission
        self.context.stamp_tax_rate = tax
        self.context.slippage_rate = slippage
        self.context._engine = self
        self.data_proxy = DataProxy()
        self.g = GlobalVars()

        # 3. 获取交易日列表
        # 预留足够前导数据供多周期策略 history()/attribute_history() 使用
        pre_start = (pd.Timestamp(start_date) - pd.Timedelta(days=750)).strftime('%Y-%m-%d')
        trading_dates = get_trading_dates(start_date, end_date)
        if not trading_dates:
            return {'status': 'error', 'message': f'无交易日: {start_date} ~ {end_date}', 'hints': self._diagnose_engine_error(f'无交易日: {start_date} ~ {end_date}')}
        logging.info(f"[回测引擎] 交易日: {len(trading_dates)} 天")
        self._log_messages.append(
            f"[系统] 回测区间 {start_date} ~ {end_date}，共 {len(trading_dates)} 个交易日，初始资金 {initial_cash:,.0f}")

        # 4. 注入策略 API 到函数命名空间
        api_ns = self._create_strategy_api()

        # 5. 执行 initialize
        try:
            self._call_with_api(self._strategy_funcs['initialize'], [self.context], api_ns)
        except Exception as e:
            _msg = f'initialize 执行错误: {e}'
            return {'status': 'error', 'message': _msg, 'hints': self._diagnose_engine_error(_msg)}

        # 6. 预加载策略涉及的股票数据
        self._discover_and_load_stocks(pre_start, end_date)
        self._log_messages.append(
            f"[系统] 预加载完成：候选股票 {len(self._stock_data)} 只")

        # 7. 加载基准数据
        self._benchmark_data = load_benchmark_data(benchmark, start_date, end_date)
        benchmark_prices = {}
        if self._benchmark_data is not None:
            for _, row in self._benchmark_data.iterrows():
                d = row['date'].date() if hasattr(row['date'], 'date') else row['date']
                benchmark_prices[d] = row['close']
            # 将基准数据注入 _stock_data，使策略中 history(benchmark) 可用
            bm_code = self._normalize_code(benchmark)
            if bm_code not in self._stock_data:
                bm_full = load_benchmark_data(bm_code, pre_start, end_date)
                if bm_full is not None:
                    self._stock_data[bm_code] = self._to_indexed_df(bm_full)
            # 基准频繁访问且需要全程可用，固定常驻不被 LRU 淘汰
            self._stock_data.pin(bm_code)

        # 8. 主回测循环
        prev_nav = 1.0
        prev_bm_nav = 1.0
        initial_bm_price = None

        for i, date in enumerate(trading_dates):
            # 聚宽兼容：current_dt 应为 datetime.datetime（策略中调 .date()）
            if isinstance(date, datetime.date) and not isinstance(date, datetime.datetime):
                self.context.current_dt = datetime.datetime.combine(date, datetime.time(15, 0))
            else:
                self.context.current_dt = date
            self.context.previous_dt = trading_dates[i - 1] if i > 0 else None

            # 8a. 加载当日行情
            today_prices = self._load_day_prices(date)
            self._current_day_prices = today_prices
            self.context.portfolio._on_new_day(today_prices)

            # 8b. before_trading_start
            if self._strategy_funcs.get('before_trading_start'):
                try:
                    self._call_with_api(self._strategy_funcs['before_trading_start'],
                                        [self.context], api_ns)
                except Exception as e:
                    self._record_error(f"{date} before_trading_start", e)

            # 8c. handle_data
            if self._strategy_funcs.get('handle_data'):
                try:
                    self._call_with_api(self._strategy_funcs['handle_data'],
                                        [self.context, self.data_proxy], api_ns)
                except Exception as e:
                    self._record_error(f"{date} handle_data", e)

            # 8c-2. 执行 run_weekly 注册的回调（聚宽中周度调仓 time='10:30' 先于日度风控 time='14:30'）
            if self._weekly_callbacks:
                # 获取当日是星期几（0=周一...6=周日）
                if hasattr(date, 'weekday'):
                    py_weekday = date.weekday()  # 0=Mon
                else:
                    py_weekday = pd.Timestamp(date).weekday()
                # 聚宽 weekday: 1=Mon, 2=Tue, ..., 5=Fri
                jq_weekday = py_weekday + 1
                for (cb, wd, time_rule) in self._weekly_callbacks:
                    if jq_weekday == wd:
                        try:
                            self._call_with_api(cb, [self.context], api_ns)
                        except Exception as e:
                            cb_name = getattr(cb, '__name__', str(cb))
                            self._record_error(f"{date} run_weekly({cb_name})", e)

            # 8c-3. 执行 run_daily 注册的回调（日度风控 time='14:30' 在周度调仓之后）
            for cb in self._daily_callbacks:
                try:
                    self._call_with_api(cb, [self.context], api_ns)
                except Exception as e:
                    cb_name = getattr(cb, '__name__', str(cb))
                    self._record_error(f"{date} run_daily({cb_name})", e)

            # 8d. 清理延迟标记的空仓（在所有回调完成后执行，避免迭代中删除字典）
            if self._deferred_position_cleanups:
                for _code in self._deferred_position_cleanups:
                    if _code in self.context.portfolio.positions and \
                            self.context.portfolio.positions[_code].amount == 0:
                        del self.context.portfolio.positions[_code]
                self._deferred_position_cleanups.clear()

            # 8e. 执行待处理订单（即时执行模式下队列为空）
            self._execute_pending_orders(date, today_prices)

            # 8e. 更新组合价值（使用收盘价）
            self.context.portfolio._update_value()

            # 8f. after_trading_end
            if self._strategy_funcs.get('after_trading_end'):
                try:
                    self._call_with_api(self._strategy_funcs['after_trading_end'],
                                        [self.context], api_ns)
                except Exception as e:
                    self._record_error(f"{date} after_trading_end", e)

            # 8g. 记录净值
            nav = self.context.portfolio.total_value / initial_cash
            daily_return = (nav / prev_nav - 1) if prev_nav > 0 else 0

            # 基准净值
            bm_price = benchmark_prices.get(date)
            if bm_price and initial_bm_price is None:
                initial_bm_price = bm_price
            bm_nav = bm_price / initial_bm_price if bm_price and initial_bm_price else prev_bm_nav
            bm_return = (bm_nav / prev_bm_nav - 1) if prev_bm_nav > 0 else 0

            self._nav_records.append(NavRecord(
                date=date, nav=nav, benchmark_nav=bm_nav,
                cash=self.context.portfolio.available_cash,
                market_value=self.context.portfolio.market_value,
                total_value=self.context.portfolio.total_value,
                daily_return=daily_return,
                benchmark_return=bm_return,
            ))

            # 8h. 持仓快照
            pos_snap = []
            for code, pos in self.context.portfolio.positions.items():
                if pos.amount > 0:
                    pos_snap.append({
                        'code': code, 'name': pos.name,
                        'amount': pos.amount, 'avg_cost': round(pos.avg_cost, 3),
                        'price': round(pos.price, 3),
                        'value': round(pos.value, 2),
                        'profit': round(pos.profit, 2),
                        'profit_rate': round(pos.profit_rate * 100, 2),
                        'weight': round(pos.value / self.context.portfolio.total_value * 100, 2)
                        if self.context.portfolio.total_value > 0 else 0,
                    })
            if pos_snap:
                self._position_snapshots.append({'date': date, 'positions': pos_snap})

            # 8i. 每 20 个交易日输出一条进度日志（让前端 SSE 有插脸）
            if (i + 1) % 20 == 0 or i == len(trading_dates) - 1:
                pos_count = len(pos_snap)
                self._log_messages.append(
                    f"[{date}] [PROGRESS] day {i+1}/{len(trading_dates)} "
                    f"NAV={nav:.4f} (基准 {bm_nav:.4f}) "
                    f"总资产={self.context.portfolio.total_value:,.0f} "
                    f"持仓={pos_count}只 交易总计={len(self._trade_records)}笔")

            prev_nav = nav
            prev_bm_nav = bm_nav

        # 9. 计算风险指标
        nav_values = [r.nav for r in self._nav_records]
        bm_values = [r.benchmark_nav for r in self._nav_records]
        date_values = [r.date for r in self._nav_records]
        metrics = calculate_metrics(nav_values, bm_values, self._trade_records, dates=date_values)

        elapsed = time.time() - start_time
        logging.info(f"[回测引擎] 完成: 收益={metrics['total_return']:.2f}%, "
                     f"最大回撤={metrics['max_drawdown']:.2f}%, "
                     f"夏普={metrics['sharpe_ratio']:.2f}, 耗时={elapsed:.1f}s")
        self._log_messages.append(
            f"[系统] 回测完成 | 收益={metrics['total_return']:.2f}% 基准={metrics.get('benchmark_return', 0):.2f}% "
            f"超额={metrics.get('excess_return', 0):.2f}% 最大回撤={metrics['max_drawdown']:.2f}% "
            f"夏普={metrics['sharpe_ratio']:.2f} 交易次数={metrics.get('trade_count', 0)} 耗时={elapsed:.1f}s")
        # 即使 trade_count>0，只要存在运行期异常或有大量被拒订单，也输出诊断 hints
        # （便于"成交了但远低于预期"场景排查）。0 笔交易仍走完整 _diagnose_zero_trades。
        zero_trade_hints = []
        if metrics.get('trade_count', 0) == 0:
            zero_trade_hints = self._diagnose_zero_trades()
            self._log_messages.append(
                "[系统] [WARN] 全程 0 笔交易。可能原因 / 建议改进："
            )
            for h in zero_trade_hints:
                self._log_messages.append(f"[系统] [WARN]   • {h.get('title', '')} — {h.get('suggestion', '')}")
        elif self._strategy_errors or any('[ERROR]' in L for L in self._log_messages[-2000:]):
            # 有交易但伴随异常或日志里有 [ERROR]：保留"运行期异常"+"日志反解" 两段诊断，
            # 避免把 "0 笔交易" 路径下的拒单分析也塞给用户造成误导。
            err_hints = self._diagnose_zero_trades()
            zero_trade_hints = [h for h in err_hints
                                if ('策略抛出异常' in str(h.get('title', '')))
                                or ('日志反解' in str(h.get('title', '')))]

        return {
            'status': 'completed',
            'metrics': metrics,
            'nav': [r.to_dict() for r in self._nav_records],
            'trades': [t.to_dict() for t in self._trade_records],
            'positions': self._position_snapshots,
            'logs': self._log_messages[-2000:],  # 最近2000条日志（以前 200 不够）
            'errors': self._strategy_errors[-50:],  # 最近50条策略错误
            'hints': zero_trade_hints,  # 0 笔交易时的诊断+改进建议
            'order_stats': dict(self._order_stats),  # 订单执行计数器（供前端 / 修复 prompt 使用）
            'elapsed': round(elapsed, 1),
            'params': {
                'start_date': start_date,
                'end_date': end_date,
                'initial_cash': initial_cash,
                'benchmark': benchmark,
                'commission': commission,
                'tax': tax,
                'slippage': slippage,
            }
        }

    # ── 策略 API 函数 ──

    @staticmethod
    def _normalize_code(code):
        """将聚宽风格股票代码（如 '000001.XSHE'）转为6位纯数字代码"""
        if isinstance(code, str) and '.' in code:
            return code.split('.')[0]
        return code

    def _diagnose_zero_trades(self):
        """全程 0 笔交易时，结合运行期遥测+源码生成结构化诊断+改进建议。

        证据优先级（高→低）：
        1) 运行期 traceback（_strategy_errors）：直接定位到具体行/异常类型；
        1b) 日志 [ERROR] 行解析：策略自己 try/except 把异常吞掉只 log.error 时，
            从日志里反解出 NameError / AttributeError / TypeError 等关键错误；
        2) 订单执行计数器（_order_stats）：精确告知是 涨停/现金不足/无持仓/订单量0
           等哪一类拒绝主导，含次数；
        3) 日志模式扫描：选股池为空、无行情等；
        4) 源码静态规则（regex）：典型陷阱（day==1 / talib.STOCH 解包 / 裸 except）；
        5) 仅当以上都未产生任何 hint 时，才用通用阈值放宽建议兜底。

        每一条 hint 都会包含与当次回测真实情况相关的数字 / 错误片段，避免输出
        与策略无关的恒定文案。返回 [{title, suggestion, severity, ref?}]。
        """
        import re as _re
        code = getattr(self, '_raw_strategy_code', '') or ''
        logs = self._log_messages or []
        errors = self._strategy_errors or []
        stats = dict(getattr(self, '_order_stats', {}) or {})
        hints = []

        # ── 1. 运行期异常（最强信号）──
        if errors:
            err_top = errors[0]
            err_msg = (err_top.get('error') or '').strip()
            err_type = (err_top.get('type') or '').strip()
            err_where = (err_top.get('where') or err_top.get('context') or err_top.get('phase') or '').strip()
            tb = (err_top.get('traceback') or '').strip()
            tb_last_line = ''
            for ln in reversed(tb.splitlines()):
                if ln.strip():
                    tb_last_line = ln.strip()
                    break
            # 用于关键字匹配的"全文"——含异常类型/消息/traceback 末行
            err_haystack = ' '.join([err_type, err_msg, tb_last_line]).lower()
            suggestion_parts = [
                f"策略运行期间共抛出 {len(errors)} 次异常",
            ]
            if err_where:
                suggestion_parts.append(f"首次发生在: {err_where}")
            if tb_last_line and tb_last_line != err_msg:
                suggestion_parts.append(f"末行: {tb_last_line}")
            # 根据异常类型给出针对性提示
            if 'valueerror' in err_haystack and 'unpack' in err_haystack:
                suggestion_parts.append(
                    '看起来是元组解包数量与函数返回不匹配（如 k,d,j = talib.STOCH 实际只返回两个）。'
                    '请检查报错行的等号左侧变量数量。')
            elif 'nameerror' in err_haystack:
                suggestion_parts.append(
                    '变量未定义。可能是首次调用前未初始化（如 g.xxx），'
                    '或循环里引用了 except 分支未赋值的变量。')
            elif 'keyerror' in err_haystack:
                suggestion_parts.append(
                    'dict 取不到 key。常见原因：data[code] 在停牌日；'
                    'context.portfolio.positions[code] 未持仓即访问。请用 .get() 兜底。')
            elif 'indexerror' in err_haystack:
                suggestion_parts.append(
                    '序列下标越界。通常是 history(N) 在回测起点处取不够 N 根 K 线；'
                    '应判断 len(arr) >= N 再访问 arr[-1]。')
            elif 'zerodivision' in err_haystack:
                suggestion_parts.append(
                    '除零错误。除数可能是前一根 K 线的成交量/收盘价为 0（停牌或新股首日），'
                    '请加 if divisor: 守卫，或用 numpy.where(denom!=0, ...) 兜底。')
            elif 'attributeerror' in err_haystack:
                suggestion_parts.append(
                    '属性访问错误。可能是某个对象在异常分支未被赋值仍为 None，'
                    '或调用了不存在的 API（拼写错误 / 仿聚宽 API 没有此方法）。')
            _title_type = err_type or '未知错误'
            hints.append({
                'title': f'策略抛出异常 ({_title_type}): {err_msg[:100] or "无消息"}',
                'suggestion': ' '.join(suggestion_parts),
                'severity': 'high',
                'evidence': {
                    'error_count': len(errors),
                    'error_type': err_type,
                    'first_error': err_msg[:300],
                    'first_traceback_tail': tb[-500:] if tb else '',
                },
            })

        # ── 1b. 日志 [ERROR] 行解析（策略自己 try/except 把异常吞掉只 log.error 时的关键证据）──
        # 用户报告："运行日志里明明全是 name 'ta' is not defined，诊断却完全没体现"，
        # 根因是策略写了 try: ... except Exception as e: log.error(f"处理 {code} 时发生错误: {e}")，
        # 引擎的 _record_error 永远拿不到这些异常，必须从日志反解。
        log_patterns = {}  # exception kind -> {count, sample, kind, ...}

        def _bump(key, sample, **extra):
            ent = log_patterns.setdefault(key, {'count': 0, 'sample': sample, **extra})
            ent['count'] += 1

        for L in logs[-2000:]:
            if '[ERROR]' not in L:
                continue
            seg = L.split('[ERROR]', 1)[-1].strip()
            m = _re.search(r"name ['\"]([\w\.]+)['\"] is not defined", seg)
            if m:
                _bump(f"NameError:{m.group(1)}", L, kind='NameError', var=m.group(1))
                continue
            m = _re.search(r"['\"](\w+)['\"] object has no attribute ['\"](\w+)['\"]", seg)
            if m:
                _bump(f"AttributeError:{m.group(1)}.{m.group(2)}", L,
                      kind='AttributeError', obj=m.group(1), attr=m.group(2))
                continue
            m = _re.search(r"unsupported operand type\(s\) for [^:]+: ['\"]([^'\"]+)['\"] and ['\"]([^'\"]+)['\"]", seg)
            if m:
                _bump(f"TypeError:{m.group(1)}-{m.group(2)}", L,
                      kind='TypeError', left=m.group(1), right=m.group(2))
                continue
            if 'division by zero' in seg or 'float division by zero' in seg:
                _bump('ZeroDivisionError', L, kind='ZeroDivisionError')
                continue
            if 'list index out of range' in seg or 'index out of range' in seg:
                _bump('IndexError', L, kind='IndexError')
                continue
            m = _re.search(r"KeyError:?\s*['\"]?([^'\"\s,]+)", seg)
            if m:
                _bump(f"KeyError:{m.group(1)[:30]}", L, kind='KeyError', k=m.group(1))
                continue
            # 兜底：识别任何 XxxError / XxxException 关键字
            m = _re.search(r"(\w+(?:Error|Exception))", seg)
            if m:
                _bump(f"{m.group(1)}:other", L, kind=m.group(1), msg=seg[:200])

        # 已知简写映射 → 沙箱不会自动注入这些名字，给出明确 import 提示
        _SHIM_HINT = {
            'ta': '沙箱不会自动注入 `ta`。请在策略最顶部加 `import talib as ta`，或把 `ta.XXX(...)` 改为 `talib.XXX(...)`。',
            'np': '沙箱不会自动注入 `np`。请在策略最顶部加 `import numpy as np`。',
            'pd': '沙箱不会自动注入 `pd`。请在策略最顶部加 `import pandas as pd`。',
            'talib': '请在策略最顶部加 `import talib`（沙箱允许，但需显式导入）。',
            'numpy': '请在策略最顶部加 `import numpy`。',
            'pandas': '请在策略最顶部加 `import pandas`。',
            'math': '请在策略最顶部加 `import math`。',
        }
        if log_patterns:
            ranked = sorted(log_patterns.items(), key=lambda kv: -kv[1]['count'])[:3]
            for _key, info in ranked:
                kind = info['kind']
                count = info['count']
                sample = (info['sample'] or '')[:200]
                if kind == 'NameError':
                    var = info.get('var', '?')
                    sug = _SHIM_HINT.get(
                        var,
                        f"变量 `{var}` 未定义。请检查拼写、确认在使用前已赋值（含 except 分支），"
                        f"或在策略顶部 import 对应模块。沙箱默认仅注入 order/order_target/log/g/"
                        f"context/data/history/attribute_history/get_index_stocks 等聚宽 API，"
                        f"numpy/pandas/talib 等需显式 import。")
                    hints.append({
                        'title': f"日志反解：策略 try/except 吞掉了 NameError `{var}` 共 {count} 次",
                        'suggestion': f"{sug} 示例日志: {sample}",
                        'severity': 'high',
                        'evidence': {'kind': 'NameError', 'var': var, 'count': count, 'sample': sample},
                    })
                elif kind == 'AttributeError':
                    obj = info.get('obj', '?')
                    attr = info.get('attr', '?')
                    hints.append({
                        'title': f"日志反解：AttributeError `{obj}.{attr}` 不存在，共 {count} 次",
                        'suggestion': f"对象 `{obj}` 没有属性 `{attr}`。请确认 API 名称拼写"
                                      f"（如 context.portfolio.positions 而非 .holdings），"
                                      f"或对象在 except 分支里未被赋值仍为 None。 示例日志: {sample}",
                        'severity': 'high',
                        'evidence': {'kind': 'AttributeError', 'obj': obj, 'attr': attr,
                                     'count': count, 'sample': sample},
                    })
                elif kind == 'TypeError':
                    hints.append({
                        'title': f"日志反解：TypeError 操作数类型不兼容（{info.get('left','?')} 与 {info.get('right','?')}），共 {count} 次",
                        'suggestion': '请检查 + - * / 两侧的类型：常见是 None / NaN 与数字相加，'
                                      '或字符串与数字混算。请加 if x is None: continue 守卫，或 float() 转换。'
                                      f' 示例日志: {sample}',
                        'severity': 'high',
                        'evidence': {'kind': 'TypeError', 'count': count, 'sample': sample},
                    })
                elif kind == 'ZeroDivisionError':
                    hints.append({
                        'title': f'日志反解：ZeroDivisionError 共 {count} 次',
                        'suggestion': '除数为 0。常见原因：停牌日 / 新股首日 close 或 volume 为 0。'
                                      f'请加 if divisor: 守卫，或用 numpy.where(denom!=0, ...)。 示例日志: {sample}',
                        'severity': 'high',
                        'evidence': {'kind': 'ZeroDivisionError', 'count': count, 'sample': sample},
                    })
                elif kind == 'IndexError':
                    hints.append({
                        'title': f'日志反解：IndexError 序列越界共 {count} 次',
                        'suggestion': '下标越界。通常是 history(N) 在回测起点处取不够 N 根；'
                                      f'请先判断 len(arr) >= N 再访问 arr[-1]。 示例日志: {sample}',
                        'severity': 'high',
                        'evidence': {'kind': 'IndexError', 'count': count, 'sample': sample},
                    })
                elif kind == 'KeyError':
                    k = info.get('k', '?')
                    hints.append({
                        'title': f"日志反解：KeyError `{k}` 共 {count} 次",
                        'suggestion': f"dict 取不到 key `{k}`。常见：data[code] 在停牌日不存在；"
                                      f"context.portfolio.positions[code] 未持仓即访问。请用 .get() 兜底。 示例日志: {sample}",
                        'severity': 'high',
                        'evidence': {'kind': 'KeyError', 'key': k, 'count': count, 'sample': sample},
                    })
                else:
                    hints.append({
                        'title': f'日志反解：{kind} 共 {count} 次（被策略 try/except 吞掉）',
                        'suggestion': '策略内部用 try/except 捕获了异常并仅 log.error，主诊断器拿不到 traceback。'
                                      f' 示例日志: {sample}',
                        'severity': 'high',
                        'evidence': {'kind': kind, 'count': count, 'sample': sample},
                    })

        # ── 2. 订单执行计数器：精确报告"提交了但被拒"的根因分布 ──
        submitted = int(stats.get('submitted', 0))
        executed = int(stats.get('executed_buy', 0)) + int(stats.get('executed_sell', 0))
        if submitted > 0 and executed == 0:
            # 至少有过下单尝试，但都失败了——给出 top reject reason
            reject_keys = [
                ('rejected_no_data', '无行情数据（停牌 / 退市 / 代码错误）',
                 '请检查股票代码是否带后缀错位（如 "000001" 而非 "000001.XSHE"），'
                 '或回测区间是否落在该股票停牌日。'),
                ('rejected_bad_price', '行情价格异常(<=0)',
                 '数据源该日 close 字段异常，建议跳过该日或检查数据完整性。'),
                ('rejected_limit_up', '涨停无法买入',
                 '买入信号触发时股票已涨停。建议用 open/avg 价位下单，'
                 '或在 buy 条件里加 (data[code].close - data[code].pre_close)/pre_close < 0.09 过滤。'),
                ('rejected_limit_down', '跌停无法卖出',
                 '卖出信号触发时股票已跌停。可在卖出条件里跳过当日跌停股，等次日开盘再处理。'),
                ('rejected_zero_amount', '下单金额取整后不足 1 手',
                 '可用资金 / 股价 / 100 < 1，建议把 order_value(code, cash * 0.1) 这种小百分比'
                 '调大，或减少同时下单的股票数。'),
                ('rejected_insufficient_cash', '现金不足',
                 '请检查仓位管理：是否在同一根 bar 重复下单买入同一标的，'
                 '或没有先 order_target_value(..., 0) 卖出旧仓再买新仓。'),
                ('rejected_no_position', '卖出时无可卖持仓',
                 '常见于：a) T+1 当日买入不可卖出当日卖出；'
                 'b) 对从未持有过的股票 order_target(..., 0)；'
                 'c) 持仓代码与卖出代码格式不一致（"000001" vs "000001.XSHE"）。'),
                ('rejected_lot_size', '卖出数量不足 1 手且持仓非残股',
                 '请使用 order_target(code, 0) 而非 order(code, -N)，让系统按 100 股整手取整。'),
            ]
            top_reasons = [(k, n, d, s) for (k, d, s) in reject_keys
                           for n in [int(stats.get(k, 0))] if n > 0]
            top_reasons.sort(key=lambda x: -x[1])
            for k, n, desc, sug in top_reasons[:3]:
                hints.append({
                    'title': f'{desc} — 累计 {n} 次（共提交 {submitted} 次订单）',
                    'suggestion': sug,
                    'severity': 'high' if n >= submitted * 0.5 else 'medium',
                    'evidence': {'counter': k, 'count': n, 'submitted': submitted},
                })
        elif submitted == 0 and not errors and not log_patterns:
            # 一笔都没下：要么 handle_data 没跑到 order，要么策略里压根没有 order_* 调用
            # 若已检测到 _strategy_errors 或日志反解出的异常，就跳过这一段以免误导。
            if not _re.search(r"order(?:_target|_value|_target_value|_target_percent|_percent)?\s*\(", code):
                hints.append({
                    'title': '策略源码里找不到任何 order/order_target/order_value 调用',
                    'suggestion': '请确认 buy/sell 分支中真正调用了下单 API。'
                                  '仅修改 context.holdings 或 g.target_list 不会产生成交。',
                    'severity': 'high',
                })
            else:
                hints.append({
                    'title': 'handle_data / 调度回调中未触发任何下单语句',
                    'suggestion': '虽然代码包含 order_*，但运行期间从未进入到那一行。'
                                  '请检查：(a) 触发条件（if 嵌套）是否在回测区间内能成立；'
                                  '(b) 是否依赖 run_monthly/run_weekly 但 weekday/day 触发条件错误（如 day==1）；'
                                  '(c) 选股池是否在每天循环开头就 return 提前退出了。',
                    'severity': 'high',
                    'evidence': {'submitted': 0},
                })

        # ── 3. 日志特征：选股池为空 ──
        empty_pick_lines = [L for L in logs[-500:]
                            if ('选股' in L or '候选' in L or '股票池' in L) and
                            ('0 只' in L or ' 0只' in L or '为空' in L)]
        if empty_pick_lines:
            hints.append({
                'title': '选股 / 股票池筛选结果为空',
                'suggestion': f'示例日志: {empty_pick_lines[-1][:200]} — '
                              '请放宽 query().filter() 阈值，或用 get_index_stocks 作为兜底候选池。',
                'severity': 'medium',
                'evidence': {'log_match': empty_pick_lines[-1][:300]},
            })

        # ── 4. 源码静态规则：仅作为补充（不再作为唯一证据） ──
        if _re.search(r"current_dt\s*\.\s*day\s*==\s*1", code) or            _re.search(r"\.day\s*==\s*1", code):
            hints.append({
                'title': '使用了 day==1 触发陷阱',
                'suggestion': '中国 A 股 1/1、5/1、10/1 都是节假日，handle_data 当天不会被调用。'
                              '改用月份游标：if m in (1,4,7,10) and m != g.last_month: ... g.last_month = m',
                'severity': 'medium',
                'ref': 'strategy_coder.md#触发陷阱',
            })
        if _re.search(r"[a-zA-Z_]\w*\s*,\s*[a-zA-Z_]\w*\s*,\s*[a-zA-Z_]\w*\s*=\s*talib\s*\.\s*STOCH", code):
            hints.append({
                'title': 'talib.STOCH 解包数量错误',
                'suggestion': 'talib.STOCH 返回 (slowk, slowd) 两个值。'
                              '请改为: slowk, slowd = talib.STOCH(...); j = 3*slowk - 2*slowd。',
                'severity': 'medium',
                'ref': 'strategy_coder.md#talib',
            })
        if _re.search(r"except\s*:\s*\n\s*(continue|pass)", code):
            hints.append({
                'title': '裸 except 静默吞掉异常',
                'suggestion': '请把 except: continue/pass 改为 except Exception as e: log.warn(f"...: {e}"); continue，'
                              '否则 talib 解包错、history 不足等问题会全程沉默。',
                'severity': 'medium',
            })

        # ── 5. 兜底（仅当以上所有证据都不存在）──
        if not hints:
            hints.append({
                'title': '未发现明确的失败信号',
                'suggestion': f'本次提交了 {submitted} 笔订单、成功 {executed} 笔、'
                              f'记录到 {len(errors)} 次异常。如确认期望有成交，请：'
                              '(a) 打开「运行日志」逐日检查触发情况；'
                              '(b) 在 handle_data 里增加 log.info(f"{context.current_dt} 判断结果: ...") '
                              '观察分支走向；(c) 检查 initialize 中 set_universe / g.target_list 是否非空。',
                'severity': 'low',
                'evidence': {'submitted': submitted, 'executed': executed,
                             'errors': len(errors)},
            })

        return hints

    def _diagnose_engine_error(self, error_message):
        """status='error' 时（initialize 抛错 / 编译失败 / 无交易日 等）的诊断。

        与 _diagnose_zero_trades 不同：此时回测连主循环都没进，只能依据
        error_message 字符串特征给提示。返回 [{title, suggestion, severity}]。
        """
        msg = (error_message or '').strip()
        hints = []
        if not msg:
            return hints
        lower = msg.lower()
        if 'syntax' in lower or msg.startswith(('编译失败', 'SyntaxError')):
            hints.append({
                'title': '策略代码语法错误',
                'suggestion': f'{msg[:200]} — 请检查 def 行后冒号、缩进、引号配对。'
                              '可以先用本地编辑器跑一次 python -m py_compile xxx.py 排查。',
                'severity': 'high',
            })
        elif 'import' in lower and ('禁止' in msg or 'forbidden' in lower or 'not allowed' in lower):
            hints.append({
                'title': '策略沙箱拒绝导入',
                'suggestion': f'{msg[:200]} — Quantia 沙箱只允许 talib / numpy / pandas / math '
                              '等白名单模块，请删除 import os/sys/subprocess 等危险导入。',
                'severity': 'high',
            })
        elif '初始资金' in msg or 'initial_cash' in lower:
            hints.append({
                'title': '初始资金参数错误',
                'suggestion': f'{msg[:200]} — 请在前端「回测参数」里把初始资金设为大于 0 的数值。',
                'severity': 'high',
            })
        elif '无交易日' in msg or 'no trading' in lower:
            hints.append({
                'title': '回测区间内无交易日',
                'suggestion': f'{msg[:200]} — 请检查开始/结束日期是否落在长假期间，'
                              '或交易日历是否已加载到 cache。',
                'severity': 'high',
            })
        elif 'initialize' in lower:
            hints.append({
                'title': 'initialize() 执行失败',
                'suggestion': f'{msg[:200]} — 请检查 initialize 里 set_universe / '
                              'set_benchmark / g.xxx 等初始化语句，常见问题：'
                              '调用了未提供的 API、context.attribute 拼写错误。',
                'severity': 'high',
            })
        else:
            hints.append({
                'title': f'回测引擎错误: {msg[:120]}',
                'suggestion': f'{msg[:400]} — 请把完整错误信息粘到 AI 助手「修复」对话里。',
                'severity': 'high',
            })
        return hints


    def _create_strategy_api(self):
        """创建策略可调用的 API 函数集（兼容聚宽风格）"""
        engine = self
        _nc = engine._normalize_code   # 代码标准化快捷引用

        # ── 基本面数据提供器 ──
        engine._fundamental_provider = FundamentalDataProvider(engine)

        def order(code, amount, **kw):
            """按股数下单（正=买入，负=卖出）"""
            engine._submit_order(_nc(code), amount=int(amount),
                                 order_api='order', **kw)

        def order_target(code, target_amount, **kw):
            """调整到目标持仓股数"""
            clean = _nc(code)
            pos = engine.context.portfolio.positions.get(clean)
            current = pos.amount if pos else 0
            diff = int(target_amount) - current
            if diff != 0:
                engine._submit_order(clean, amount=diff,
                                     order_api='order_target',
                                     target_amount=int(target_amount), **kw)

        def order_value(code, value, **kw):
            """按金额下单"""
            engine._submit_order(_nc(code), value=float(value),
                                 order_api='order_value', **kw)

        def order_target_value(code, target_value, **kw):
            """调整到目标持仓金额"""
            clean = _nc(code)
            target_value = float(target_value)
            pos = engine.context.portfolio.positions.get(clean)
            if target_value <= 0 and pos and pos.closeable_amount > 0:
                engine._submit_order(clean, amount=-pos.closeable_amount,
                                     order_api='order_target_value', **kw)
                return
            current_value = pos.value if pos and pos.amount > 0 else 0
            diff = target_value - current_value
            if abs(diff) > 100:
                engine._submit_order(clean, value=diff,
                                     order_api='order_target_value', **kw)

        def order_target_percent(code, percent, **kw):
            """调整到目标仓位比例（总资产百分比）"""
            clean = _nc(code)
            target_value = float(percent) * engine.context.portfolio.total_value
            pos = engine.context.portfolio.positions.get(clean)
            current_value = pos.value if pos and pos.amount > 0 else 0
            diff = target_value - current_value
            if abs(diff) > 100:
                engine._submit_order(clean, value=diff,
                                     order_api='order_target_percent',
                                     target_percent=float(percent), **kw)

        def history(code, count, *args, **kwargs):
            """获取最近 N 个交易日的数据。

            支持两种调用风格：
              - 项目原签名：history(code, count, field='close')
              - 聚宽风格：history(code, count, unit='1d', field='close')
                          / history(code, count, '1d', 'close')
            兼容性优先：当传入 4 个位置参数时，第 3 个视为 unit（仅 '1d' 受支持，
            其它会回退到日线并不报错），第 4 个视为 field。
            """
            field = 'close'
            if args:
                # 形如 history(code, count, '1d', 'close') 或 history(code, count, 'close')
                if len(args) == 1:
                    field = args[0]
                else:
                    # args[0] 是 unit（忽略，统一按日线返回），args[1] 是 field
                    field = args[1]
            if 'field' in kwargs:
                field = kwargs['field']
            elif 'fields' in kwargs and not args:
                # 兼容个别调用方写成 fields='close'
                f = kwargs['fields']
                if isinstance(f, str):
                    field = f
                elif isinstance(f, (list, tuple)) and f:
                    field = f[0]
            clean = _nc(code)
            idx_df = engine._stock_data.get(clean)
            if idx_df is None:
                engine._ensure_stock_loaded(clean)
                idx_df = engine._stock_data.get(clean)
                if idx_df is None:
                    return pd.Series(dtype=float)
            current_date = pd.Timestamp(engine.context.current_dt)
            subset = idx_df.loc[:current_date].iloc[-count:]
            if field in subset.columns:
                return subset[field].reset_index(drop=True)
            return pd.Series(dtype=float)

        def attribute_history(security, count, unit='1d', fields=None,
                              skip_paused=True, df=True, fq='pre'):
            """聚宽 attribute_history — 获取单只股票多字段历史数据

            返回 DataFrame，index 为日期，columns 为 fields 中的字段名。
            """
            clean = _nc(security)
            engine._ensure_stock_loaded(clean)
            idx_df = engine._stock_data.get(clean)
            if idx_df is None:
                if fields:
                    return pd.DataFrame(columns=fields)
                return pd.DataFrame()
            current_date = pd.Timestamp(engine.context.current_dt)
            subset = idx_df.loc[:current_date].iloc[-count:]
            if fields is None:
                fields = ['open', 'close', 'high', 'low', 'volume', 'money']
            result_cols = {}
            for f in fields:
                if f in subset.columns:
                    result_cols[f] = subset[f].values
                elif f == 'money':
                    if 'volume' in subset.columns and 'close' in subset.columns:
                        result_cols['money'] = (subset['volume'] * subset['close'] * 100).values
                    else:
                        result_cols['money'] = [0] * len(subset)
                else:
                    result_cols[f] = [0] * len(subset)
            result = pd.DataFrame(result_cols, index=subset.index)
            return result

        def get_price(code, start_date=None, end_date=None, count=None,
                      frequency='daily', fields=None, fq=None, **kwargs):
            """获取历史数据（兼容聚宽 count/end_date 模式和 start_date/end_date 模式）"""
            clean = _nc(code)
            engine._ensure_stock_loaded(clean)
            idx_df = engine._stock_data.get(clean)
            if idx_df is None:
                return pd.DataFrame()
            result = idx_df
            if end_date:
                result = result.loc[:pd.Timestamp(end_date)]
            elif count:
                result = result.loc[:pd.Timestamp(engine.context.current_dt)]
            if start_date:
                result = result.loc[pd.Timestamp(start_date):]
            if count and count > 0:
                result = result.iloc[-count:]
            result = result.reset_index()  # bring 'date' back as column
            if fields:
                # 兼容聚宽 fields 含 'money'（映射到 deal_amount 或 volume*close）
                cols = ['date']
                for f in fields:
                    if f == 'money' and 'money' not in result.columns:
                        if 'deal_amount' in result.columns:
                            result['money'] = result['deal_amount']
                        elif 'amount' in result.columns:
                            result['money'] = result['amount']
                        elif 'volume' in result.columns and 'close' in result.columns:
                            result['money'] = result['volume'] * result['close'] * 100
                    if f == 'paused' and 'paused' not in result.columns:
                        result['paused'] = 0
                    if f in result.columns:
                        cols.append(f)
                result = result[cols]
            return result.reset_index(drop=True)

        def set_benchmark(code):
            """设定基准指数（兼容聚宽 .XSHG/.XSHE 后缀）"""
            # 去掉聚宽的交易所后缀
            clean = code.split('.')[0] if '.' in code else code
            engine.context.benchmark = clean

        def set_order_cost(cost_or_commission=0.0003, tax=0.001, slippage=0.002, **kwargs):
            """设定交易成本（兼容聚宽 OrderCost 和旧版参数两种调用方式）"""
            if isinstance(cost_or_commission, _OrderCost):
                oc = cost_or_commission
                engine.context.commission_rate = max(oc.open_commission, oc.close_commission)
                engine.context.stamp_tax_rate = oc.close_tax
                # 聚宽 min_commission -> 引擎暂不支持全局设置
            else:
                engine.context.commission_rate = cost_or_commission
                engine.context.stamp_tax_rate = tax
                engine.context.slippage_rate = slippage

        def set_option(option, value=None):
            """聚宽 set_option() — 当前回测引擎中为兼容性空操作"""
            pass

        def run_daily(func, time_rule='every_bar', time='open', reference_security=None):
            """注册日级回调函数（兼容聚宽 run_daily）"""
            engine._daily_callbacks.append(func)

        def run_weekly(func, weekday=None, tradingday=None, time='open', reference_security=None):
            """注册周级回调函数（兼容聚宽 run_weekly）

            Args:
                func: 回调函数
                weekday: 每周星期几执行（1=周一, ..., 5=周五）
                tradingday: 同 weekday（聚宽兼容别名）
                time: 'before_open' / 'open' / 'after_close' / 'every_bar'
            """
            # weekday 优先；都为 None 时默认周一 (1)
            wd = weekday if weekday is not None else (tradingday if tradingday is not None else 1)
            engine._weekly_callbacks.append((func, wd, time))

        def get_index_stocks(index_code, date=None):
            """获取指数成份股列表（兼容聚宽 get_index_stocks）

            数据源优先级（均只读 MySQL，符合"分析管道不访问外部 API"约束）：
            1. 主流宽基指数（沪深300/上证50/中证500/中证1000/创业板50）从
               cn_stock_selection 表的 is_* 标记列读取（取 <= 回测当前日的最新
               快照，无则退回全局最新快照）。
            2. 中证银行指数(399951) 用内置静态名单（该指数无对应 is_* 列）。
            """
            clean = index_code.split('.')[0] if '.' in index_code else index_code

            # 中证银行指数 (399951) 成份股 — 截至2024年（无 is_* 标记列覆盖）
            _STATIC_INDEX_STOCKS = {
                '399951': [
                    '601398',  # 工商银行
                    '601939',  # 建设银行
                    '601288',  # 农业银行
                    '601988',  # 中国银行
                    '600036',  # 招商银行
                    '601166',  # 兴业银行
                    '000001',  # 平安银行
                    '601328',  # 交通银行
                    '601818',  # 光大银行
                    '600016',  # 民生银行
                    '601009',  # 南京银行
                    '600000',  # 浦发银行
                    '601229',  # 上海银行
                    '002142',  # 宁波银行
                    '600015',  # 华夏银行
                    '601838',  # 成都银行
                    '601916',  # 浙商银行
                    '601998',  # 中信银行
                    '600926',  # 杭州银行
                    '601169',  # 北京银行
                    '601077',  # 渝农商行
                    '600908',  # 无锡银行
                    '601658',  # 邮储银行
                    '601528',  # 瑞丰银行
                    '601860',  # 紫金银行
                    '601963',  # 重庆银行
                    '601187',  # 厦门国际银行
                    '002839',  # 张家港行
                    '002936',  # 郑州银行
                    '002948',  # 青岛银行
                    '002966',  # 苏州银行
                    '600919',  # 江苏银行
                ],
            }
            if clean in _STATIC_INDEX_STOCKS:
                return list(_STATIC_INDEX_STOCKS[clean])

            # 主流宽基指数 → cn_stock_selection 标记列（白名单，固定取值，无注入风险）
            _SELECTION_FLAG_COL = {
                '000300': 'is_hs300',    # 沪深300
                '000016': 'is_sz50',     # 上证50
                '000905': 'is_zz500',    # 中证500
                '000852': 'is_zz1000',   # 中证1000
                '399673': 'is_cy50',     # 创业板50
            }
            col = _SELECTION_FLAG_COL.get(clean)
            if col:
                if clean in engine._index_stocks_cache:
                    return list(engine._index_stocks_cache[clean])
                try:
                    from quantia.lib.database import executeSqlFetch
                    cur = engine.context.current_dt
                    ref_date = None
                    if cur is not None:
                        ref_date = (cur.strftime('%Y-%m-%d')
                                    if hasattr(cur, 'strftime') else str(cur)[:10])
                    snap = None
                    if ref_date:
                        r = executeSqlFetch(
                            "SELECT MAX(date) FROM cn_stock_selection "
                            "WHERE date <= %s AND `" + col + "` = %s",
                            (ref_date, '是'))
                        snap = r[0][0] if r and r[0] else None
                    if snap is None:  # 回测区间早于数据起点 → 退回全局最新快照
                        r = executeSqlFetch(
                            "SELECT MAX(date) FROM cn_stock_selection "
                            "WHERE `" + col + "` = %s", ('是',))
                        snap = r[0][0] if r and r[0] else None
                    stocks = []
                    if snap is not None:
                        rows = executeSqlFetch(
                            "SELECT DISTINCT code FROM cn_stock_selection "
                            "WHERE date = %s AND `" + col + "` = %s",
                            (snap, '是'))
                        stocks = [row[0] for row in (rows or [])]
                    engine._index_stocks_cache[clean] = stocks
                    if not stocks:
                        engine._log_messages.append(
                            f"[{engine.context.current_dt}] [WARN] 指数 {index_code} "
                            f"在 cn_stock_selection 无成份股数据，返回空列表")
                    return list(stocks)
                except Exception as e:
                    logging.warning(f"[回测] get_index_stocks({index_code}) 查询失败: {e}")
                    engine._index_stocks_cache[clean] = []
                    return []

            engine._log_messages.append(
                f"[{engine.context.current_dt}] [WARN] 未知指数 {index_code}，返回空列表")
            return []

        def get_fundamentals(q, date=None):
            """聚宽 get_fundamentals() — 查询基本面数据。
            为兼容策略中 ``code in data`` / ``data[code].close`` 的常见用法，
            这里**主动延迟加载**返回结果中所有股票的 K 线，并立即设置当日 bar，
            使后续 ``data.keys()`` 包含这些新选出的股票。"""
            df = engine._fundamental_provider.get_fundamentals(q, date)
            try:
                if df is not None and 'code' in getattr(df, 'columns', []):
                    cur_date = engine.context.current_dt
                    if cur_date is not None:
                        ts_date = pd.Timestamp(cur_date.date() if hasattr(cur_date, 'date') else cur_date)
                        for code in df['code'].astype(str).tolist():
                            clean = code.split('.')[0] if '.' in code else code
                            if clean in engine._stock_data:
                                idx_df = engine._stock_data[clean]
                            else:
                                engine._load_single_stock(clean)
                                idx_df = engine._stock_data.get(clean)
                            if idx_df is not None and ts_date in idx_df.index:
                                row = idx_df.loc[ts_date]
                                close = float(row['close'])
                                engine.data_proxy._set_current(clean, {
                                    'open': float(row.get('open', close)),
                                    'high': float(row.get('high', close)),
                                    'low': float(row.get('low', close)),
                                    'close': close,
                                    'volume': int(row.get('volume', 0)),
                                    'pre_close': float(row.get('pre_close', close)),
                                })
            except Exception as _e:
                logging.debug(f"get_fundamentals 自动加载失败: {_e}")
            return df

        def get_current_data():
            """聚宽 get_current_data() — 获取当前股票数据（停牌等）"""
            return _CurrentDataProxy(engine._fundamental_provider, engine)

        def get_all_securities(types=None, date=None):
            """聚宽 get_all_securities() — 返回全部候选股票代码"""
            provider = engine._fundamental_provider
            # 仅需候选代码列表，无需全市场 K 线 → load_klines=False 避免 OOM
            provider._init_data(load_klines=False)
            codes = list(provider._candidate_codes) if provider._candidate_codes else []
            # 也包含已加载的 K 线股票
            for code in engine._stock_data:
                if code not in codes:
                    codes.append(code)
            result = pd.DataFrame({'code': codes}, index=codes)
            result.index.name = None
            return result

        def get_security_info(code):
            """聚宽 get_security_info() — 返回股票基本信息 stub"""
            class _SecurityInfo:
                def __init__(self):
                    self.start_date = datetime.date(2010, 1, 1)  # 默认上市日期
                    self.display_name = ''
                    self.name = ''
                    self.type = 'stock'
            return _SecurityInfo()

        def record(**kwargs):
            """记录自定义指标"""
            date = engine.context.current_dt
            for key, val in kwargs.items():
                engine._custom_records.setdefault(key, []).append({
                    'date': str(date), 'value': val,
                })

        class _Log:
            def info(self, msg):
                engine._log_messages.append(f"[{engine.context.current_dt}] [INFO] {msg}")
            def warn(self, msg):
                engine._log_messages.append(f"[{engine.context.current_dt}] [WARN] {msg}")
            def warning(self, msg):
                engine._log_messages.append(f"[{engine.context.current_dt}] [WARN] {msg}")
            def error(self, msg):
                engine._log_messages.append(f"[{engine.context.current_dt}] [ERROR] {msg}")
            def debug(self, msg):
                engine._log_messages.append(f"[{engine.context.current_dt}] [DEBUG] {msg}")
            def set_level(self, *args, **kwargs):
                pass  # 兼容聚宽 log.set_level()

        return {
            'order': order,
            'order_target': order_target,
            'order_value': order_value,
            'order_target_value': order_target_value,
            'history': history,
            'attribute_history': attribute_history,
            'get_price': get_price,
            'set_benchmark': set_benchmark,
            'set_order_cost': set_order_cost,
            'set_option': set_option,
            'run_daily': run_daily,
            'run_weekly': run_weekly,
            'get_index_stocks': get_index_stocks,
            'get_fundamentals': get_fundamentals,
            'get_current_data': get_current_data,
            'record': record,
            'log': _Log(),
            'g': self.g,
            # 聚宽兼容对象
            'query': _query_func,
            'valuation': _valuation_obj,
            'indicator': _indicator_obj,
            'balance': _balance_obj,
            'cash_flow': _cash_flow_obj,
            'OrderCost': _OrderCost,
            # 聚宽兼容 shim
            'get_all_securities': get_all_securities,
            'get_security_info': get_security_info,
            'get_all_cached_stocks': lambda: get_all_cached_stocks(),
        }

    def _call_with_api(self, func, args, api_ns):
        """注入 API 到函数的全局命名空间后调用"""
        if func is None:
            return
        func.__globals__.update(api_ns)
        func(*args)

    def _record_error(self, context_desc, exception):
        """记录策略运行时错误（含完整traceback）。
        相同错误消息超过 3 次后抑制日志输出，避免日志膨胀。"""
        import traceback
        tb = traceback.format_exception(type(exception), exception, exception.__traceback__)
        # 过滤掉引擎内部帧，只保留策略相关帧
        strategy_tb = [line for line in tb if '<strategy>' in line or not line.startswith('  File')]
        full_msg = ''.join(tb)
        error_key = str(exception)
        self._error_counts[error_key] = self._error_counts.get(error_key, 0) + 1
        count = self._error_counts[error_key]
        _MAX_REPEATED_LOGS = 3
        if count <= _MAX_REPEATED_LOGS:
            short_msg = f"[回测] {context_desc} 异常: {exception}"
            logging.warning(f"{short_msg}\n{''.join(strategy_tb)}")
            if count == _MAX_REPEATED_LOGS:
                logging.warning(f"[回测] 相同错误 '{error_key}' 已出现 {count} 次，后续不再重复记录日志")
        self._strategy_errors.append({
            'context': context_desc,
            'error': str(exception),
            'type': type(exception).__name__,
            'traceback': full_msg,
        })

    # ── 股票名称解析 ──

    def _resolve_stock_name(self, code):
        """获取股票名称，优先缓存，降级查询数据库"""
        if code in self._stock_names:
            return self._stock_names[code]
        name = self._query_stock_name(code)
        self._stock_names[code] = name
        return name

    _db_available = None  # None=unknown, True/False after first attempt

    @staticmethod
    def _query_stock_name(code):
        """从数据库查询单只股票名称"""
        if PortfolioBacktestEngine._db_available is False:
            return ''
        try:
            import quantia.core.tablestructure as tbs
            import quantia.lib.database as mdb
            table = tbs.TABLE_CN_STOCK_SPOT['name']
            if mdb.checkTableIsExist(table):
                sql = f"SELECT `name` FROM `{table}` WHERE `code` = %s LIMIT 1"
                result = pd.read_sql(sql, mdb.engine(), params=(code,))
                if result is not None and len(result) > 0:
                    PortfolioBacktestEngine._db_available = True
                    return result.iloc[0]['name']
            PortfolioBacktestEngine._db_available = True
        except Exception:
            logging.debug(f"查询股票名称异常: {code}", exc_info=True)
            PortfolioBacktestEngine._db_available = False
        return ''

    def _load_stock_names_batch(self, codes):
        """批量加载股票名称到缓存"""
        if not codes or PortfolioBacktestEngine._db_available is False:
            for c in (codes or []):
                if c not in self._stock_names:
                    self._stock_names[c] = ''
            return
        uncached = [c for c in codes if c not in self._stock_names]
        if not uncached:
            return
        try:
            import quantia.core.tablestructure as tbs
            import quantia.lib.database as mdb
            table = tbs.TABLE_CN_STOCK_SPOT['name']
            if mdb.checkTableIsExist(table):
                placeholders = ','.join(['%s'] * len(uncached))
                sql = f"SELECT `code`, `name` FROM `{table}` WHERE `code` IN ({placeholders})"
                result = pd.read_sql(sql, mdb.engine(), params=tuple(uncached))
                if result is not None and len(result) > 0:
                    for _, row in result.iterrows():
                        self._stock_names[row['code']] = row['name']
        except Exception:
            logging.debug("批量查询股票名称异常", exc_info=True)
        # 未查到的标记为空字符串
        for c in uncached:
            if c not in self._stock_names:
                self._stock_names[c] = ''

    # ── 订单管理 ──

    def _submit_order(self, code, amount=None, value=None, *,
                       reason=None, decision=None, indicators=None, selection=None,
                       order_api=None, target_amount=None, target_percent=None):
        """提交并立即执行订单（即时执行模式，兼容聚宽行为）。

        Phase 3: 接受策略传入的 reason/decision/indicators/selection。
        """
        self._order_stats['submitted'] += 1
        # 动态加载该股票数据
        if code not in self._stock_data:
            self._load_single_stock(code)
            self._all_codes.add(code)

        date = self.context.current_dt

        # 确保当日行情可用
        if code not in self._current_day_prices:
            self._update_stock_day_price(code, date)

        if code not in self._current_day_prices:
            self._order_stats['rejected_no_data'] += 1
            self._log_messages.append(
                f"[{date}] [WARN] {code} 无行情数据，订单取消")
            return

        order_info = {
            'code': code, 'amount': amount, 'value': value,
            'reason': reason, 'decision': decision,
            'indicators': indicators, 'selection': selection,
            'order_api': order_api,
            'target_amount': target_amount, 'target_percent': target_percent,
        }
        self._execute_single_order(order_info, date)

    def _update_stock_day_price(self, code, date):
        """更新指定股票的当日行情到 data_proxy 和 _current_day_prices"""
        idx_df = self._stock_data.get(code)
        if idx_df is None:
            return
        ts_date = pd.Timestamp(date).normalize()
        if ts_date not in idx_df.index:
            return
        row = idx_df.loc[ts_date]
        exec_price = float(row['close'])
        self._current_day_prices[code] = exec_price
        bar = {
            'open': float(row.get('open', exec_price)),
            'high': float(row.get('high', exec_price)),
            'low': float(row.get('low', exec_price)),
            'close': exec_price,
            'volume': int(row.get('volume', 0)),
            'pre_close': float(row.get('pre_close', exec_price)),
        }
        self.data_proxy._set_current(code, bar)

    def _execute_single_order(self, order_info, date):
        """执行单笔订单（使用收盘价模拟成交）"""
        code = order_info['code']
        if code not in self._current_day_prices:
            self._order_stats['rejected_no_data'] += 1
            self._log_messages.append(
                f"[{date}] [WARN] {code} 无行情数据，订单取消")
            return

        exec_price = self._current_day_prices[code]

        # 防御：价格为0或负数时无法成交
        if exec_price is None or exec_price <= 0:
            self._order_stats['rejected_bad_price'] += 1
            self._log_messages.append(
                f"[{date}] [WARN] {code} 价格异常({exec_price})，订单取消")
            return

        # 涨跌停检测
        idx_df = self._stock_data.get(code)
        ts_date = pd.Timestamp(date).normalize()
        if idx_df is not None and ts_date in idx_df.index:
                row = idx_df.loc[ts_date]
                exec_price = float(row['close'])
                pre_close = float(row.get('pre_close', exec_price))
                if pre_close and pre_close > 0:
                    change_pct = (exec_price - pre_close) / pre_close
                    limit_pct = 0.195 if code.startswith(('688', '300')) else 0.095

                    order_amount = order_info.get('amount')
                    order_value_v = order_info.get('value')
                    is_buy = (order_amount is not None and order_amount > 0) or \
                             (order_value_v is not None and order_value_v > 0)
                    is_sell = (order_amount is not None and order_amount < 0) or \
                              (order_value_v is not None and order_value_v < 0)

                    if is_buy and change_pct >= limit_pct:
                        self._order_stats['rejected_limit_up'] += 1
                        self._log_messages.append(
                            f"[{date}] [WARN] {code} 涨停({change_pct*100:.1f}%)，买入取消")
                        return
                    if is_sell and change_pct <= -limit_pct:
                        self._order_stats['rejected_limit_down'] += 1
                        self._log_messages.append(
                            f"[{date}] [WARN] {code} 跌停({change_pct*100:.1f}%)，卖出取消")
                        return

        # 确定成交数量
        amount = order_info.get('amount')
        if amount is None and order_info.get('value') is not None:
            value = order_info['value']
            if value > 0:
                amount = int(value / exec_price / 100) * 100
            else:
                # 卖出：先尝试100股取整，不足100股时允许零股卖出
                raw_amount = abs(value) / exec_price
                amount_rounded = int(raw_amount / 100) * 100
                if amount_rounded <= 0:
                    amount_rounded = int(raw_amount)  # 允许零股
                amount = -amount_rounded

        if amount is None or amount == 0:
            # 价值太小被取整为 0 股，以前静默返回，这里记录下来供诊断使用。
            if order_info.get('value') is not None:
                self._order_stats['rejected_zero_amount'] += 1
                self._log_messages.append(
                    f"[{date}] [WARN] {code} 下单金额 {order_info.get('value')} 取整后不足 1 手（可用资金过少或单补仓位过小），订单取消")
            return

        # 买入
        if amount > 0:
            amount = int(amount / 100) * 100
            if amount <= 0:
                self._order_stats['rejected_zero_amount'] += 1
                return
            actual_price = exec_price * (1 + self.context.slippage_rate)
            total_cost = actual_price * amount
            commission = max(total_cost * self.context.commission_rate, 5.0)
            required = total_cost + commission

            if required > self.context.portfolio.available_cash:
                affordable = self.context.portfolio.available_cash / (actual_price * (1 + self.context.commission_rate))
                amount = int(affordable / 100) * 100
                if amount <= 0:
                    self._order_stats['rejected_insufficient_cash'] += 1
                    self._log_messages.append(
                        f"[{date}] [WARN] {code} 现金不足（可用 {self.context.portfolio.available_cash:,.0f}，需 {required:,.0f}），订单取消")
                    return
                total_cost = actual_price * amount
                commission = max(total_cost * self.context.commission_rate, 5.0)
                # 防御：最低佣金5元可能导致超支，再次检查
                if total_cost + commission > self.context.portfolio.available_cash:
                    self._order_stats['rejected_insufficient_cash'] += 1
                    return

            stock_name = self._resolve_stock_name(code)
            pos = self.context.portfolio._get_or_create_position(code, stock_name)
            pos._on_buy(amount, actual_price, commission)
            pos._update_price(exec_price)  # 用市场收盘价估值，而非含滑点的成交价
            self.context.portfolio.available_cash -= (total_cost + commission)
            self.context.portfolio._update_value()

            trade = TradeRecord(date, code, stock_name, 'buy', exec_price, amount)
            trade.commission = round(commission, 2)
            trade.slippage_cost = round(exec_price * self.context.slippage_rate * amount, 2)
            try:
                from quantia.core.backtest import trade_decision as _td
                _derived = self._derive_reason_from_logs(date, code, 'buy')
                _r = _td.resolve_reason('buy', order_info.get('reason'),
                                        derived_reason=_derived)
                trade.reason = _r.get('reason', '')
                trade.reason_source = _r.get('reason_source', '')
            except Exception:
                trade.reason = order_info.get('reason') or ''
            self._trade_records.append(trade)
            # Phase 3: 1:1 平行记录策略订单输入。
            self._signal_inputs.append(order_info)
            self._order_stats['executed_buy'] += 1
            self._log_messages.append(
                f"[{date}] [TRADE] BUY  {code} {stock_name} ×{amount} @ {exec_price:.2f} = {amount * exec_price:,.0f} 佣金 {commission:.2f}")

        # 卖出
        elif amount < 0:
            sell_amount = abs(amount)
            pos = self.context.portfolio.positions.get(code)
            if not pos or pos.closeable_amount <= 0:
                self._order_stats['rejected_no_position'] += 1
                self._log_messages.append(
                    f"[{date}] [WARN] {code} 卖出请求但无可卖持仓（T+1 当日买入不可卖 / 从未持仓），订单取消")
                return

            sell_amount = min(sell_amount, pos.closeable_amount)
            # 按 A 股 100 股整手规则取整；仅当持仓本身是奇零残股（<100）
            # 时才允许一次性清空，否则小于 100 股的卖出请求应拒绝而非
            # 静默放大为全仓清仓（历史 bug: sell 50 → 意外清空 300 股持仓）。
            rounded = int(sell_amount / 100) * 100
            if rounded <= 0:
                if pos.closeable_amount < 100:
                    sell_amount = pos.closeable_amount  # 残股一次清空
                else:
                    self._order_stats['rejected_lot_size'] += 1
                    self._log_messages.append(
                        f"[{date}] [WARN] {code} 卖出数量不足一手，订单被拒绝: {sell_amount}股")
                    return  # 请求量不足一手，拒绝订单
            else:
                sell_amount = rounded

            # 卖出前记录持仓均价，用于计算平仓盈亏
            avg_cost_before_sell = pos.avg_cost

            actual_price = exec_price * (1 - self.context.slippage_rate)
            total_income = actual_price * sell_amount
            commission = max(total_income * self.context.commission_rate, 5.0)
            tax = total_income * self.context.stamp_tax_rate

            pos._on_sell(sell_amount, exec_price)  # 剩余持仓以市场收盘价估值
            self.context.portfolio.available_cash += (total_income - commission - tax)
            self.context.portfolio._update_value()

            # 延迟清理空仓（避免用户策略代码迭代 positions 时 del 导致
            # 'dictionary changed size during iteration' 异常）
            if pos.amount == 0 and code in self.context.portfolio.positions:
                self._deferred_position_cleanups.append(code)

            stock_name = self._resolve_stock_name(code)
            trade = TradeRecord(date, code, stock_name, 'sell', exec_price, sell_amount)
            trade.commission = round(commission, 2)
            trade.tax = round(tax, 2)
            trade.slippage_cost = round(exec_price * self.context.slippage_rate * sell_amount, 2)
            # 平仓盈亏 = (卖出价 - 持仓均价) × 卖出数量
            trade.close_profit = round((exec_price - avg_cost_before_sell) * sell_amount, 2)
            # 收益率 = (卖出价 - 持仓均价) / 持仓均价 × 100
            if avg_cost_before_sell > 0:
                trade.return_rate = round((exec_price - avg_cost_before_sell) / avg_cost_before_sell * 100, 2)
            try:
                from quantia.core.backtest import trade_decision as _td
                _derived = self._derive_reason_from_logs(date, code, 'sell')
                _r = _td.resolve_reason('sell', order_info.get('reason'),
                                        derived_reason=_derived)
                trade.reason = _r.get('reason', '')
                trade.reason_source = _r.get('reason_source', '')
            except Exception:
                trade.reason = order_info.get('reason') or ''
            self._trade_records.append(trade)
            # Phase 3: 1:1 平行记录策略订单输入。
            self._signal_inputs.append(order_info)
            self._order_stats['executed_sell'] += 1
            self._log_messages.append(
                f"[{date}] [TRADE] SELL {code} {stock_name} ×{sell_amount} @ {exec_price:.2f} 盈亏 {trade.close_profit:+,.0f} 起佣 {commission:.2f}")

    def _derive_reason_from_logs(self, date, code: str, direction: str):
        """从当日策略 log.info 中反推该笔交易的真实原因。

        策略作者通常不会给 ``order_target``等 API 传 ``reason=``，但在下
        单前会用 ``log.info("金叉买入 " + code + ...)`` 输出判况说明。
        扫描同一 bar 近期的 INFO 日志，取含 code + 方向关键词的最近一条作为派生
        reason，避免出现 "策略触发买入信号…" 这种毫无信息量的兑底文案。
        """
        if not self._log_messages or not code:
            return None
        date_str = str(date)
        if direction == 'buy':
            dir_words = ('买入', '加仓', '回补', '建仓', '金叉')
        else:
            dir_words = ('卖出', '减仓', '清仓', '止损', '止盈',
                         '退出', '调仓', '超时', '死叉', '轮出')
        # 只扫近期日志避免 O(n) 扫全部
        for line in reversed(self._log_messages[-300:]):
            s = str(line)
            if '[TRADE]' in s:
                # 跳过引擎自己写入的成交日志
                continue
            if date_str not in s:
                continue
            if code not in s:
                continue
            if not any(w in s for w in dir_words):
                continue
            # 去掉 "[date] [LEVEL] " 前缀，仅保留正文
            idx = s.find('] [')
            if idx >= 0:
                tail = s[idx + 3:]
                idx2 = tail.find('] ')
                if idx2 >= 0:
                    return tail[idx2 + 2:].strip()
            return s.strip()
        return None

    def _execute_pending_orders(self, date, prices):
        """执行当轮所有挂单（使用收盘价模拟成交）"""
        for order_info in self._pending_orders:
            code = order_info['code']
            if code not in prices:
                self._log_messages.append(
                    f"[{date}] [WARN] {code} 无行情数据，订单取消")
                continue

            bar = prices[code]
            exec_price = bar  # 使用收盘价

            # 防御：价格为0或负数时无法成交
            if exec_price is None or exec_price <= 0:
                self._log_messages.append(
                    f"[{date}] [WARN] {code} 价格异常({exec_price})，订单取消")
                continue

            # 涨跌停检测
            idx_df = self._stock_data.get(code)
            ts_date_order = pd.Timestamp(date)
            if idx_df is not None and ts_date_order in idx_df.index:
                    row = idx_df.loc[ts_date_order]
                    exec_price = float(row['close'])
                    pre_close = float(row.get('pre_close', exec_price))
                    if pre_close and pre_close > 0:
                        change_pct = (exec_price - pre_close) / pre_close
                        # 涨跌停阈值：科创板(688)/创业板(300)=20%，其他=10%
                        limit_pct = 0.195 if code.startswith(('688', '300')) else 0.095

                        # 涨停检测（买入）
                        order_amount = order_info.get('amount')
                        order_value_v = order_info.get('value')
                        is_buy = (order_amount is not None and order_amount > 0) or \
                                 (order_value_v is not None and order_value_v > 0)
                        is_sell = (order_amount is not None and order_amount < 0) or \
                                  (order_value_v is not None and order_value_v < 0)

                        if is_buy and change_pct >= limit_pct:
                            self._log_messages.append(
                                f"[{date}] [WARN] {code} 涨停({change_pct*100:.1f}%)，买入取消")
                            continue
                        # 跌停检测（卖出）
                        if is_sell and change_pct <= -limit_pct:
                            self._log_messages.append(
                                f"[{date}] [WARN] {code} 跌停({change_pct*100:.1f}%)，卖出取消")
                            continue

            # 确定成交数量
            amount = order_info.get('amount')
            if amount is None and order_info.get('value') is not None:
                value = order_info['value']
                if value > 0:
                    # 买入：按金额计算股数（取整百）
                    amount = int(value / exec_price / 100) * 100
                else:
                    # 卖出：按金额计算股数
                    amount = -int(abs(value) / exec_price / 100) * 100

            if amount is None or amount == 0:
                continue

            # 买入
            if amount > 0:
                amount = int(amount / 100) * 100  # 取整百
                if amount <= 0:
                    continue
                # 含滑点的实际成交价
                actual_price = exec_price * (1 + self.context.slippage_rate)
                total_cost = actual_price * amount
                commission = max(total_cost * self.context.commission_rate, 5.0)  # 最低5元
                required = total_cost + commission

                if required > self.context.portfolio.available_cash:
                    # 资金不足，减少买入量
                    affordable = self.context.portfolio.available_cash / (actual_price * (1 + self.context.commission_rate))
                    amount = int(affordable / 100) * 100
                    if amount <= 0:
                        continue
                    total_cost = actual_price * amount
                    commission = max(total_cost * self.context.commission_rate, 5.0)
                    # 防御：最低佣金5元可能导致超支
                    if total_cost + commission > self.context.portfolio.available_cash:
                        continue

                # 执行买入
                stock_name = self._resolve_stock_name(code)
                pos = self.context.portfolio._get_or_create_position(code, stock_name)
                pos._on_buy(amount, actual_price, commission)
                pos._update_price(exec_price)  # 用市场收盘价估值，而非含滑点的成交价
                self.context.portfolio.available_cash -= (total_cost + commission)

                trade = TradeRecord(date, code, stock_name, 'buy', exec_price, amount)
                trade.commission = round(commission, 2)
                trade.slippage_cost = round(exec_price * self.context.slippage_rate * amount, 2)
                try:
                    from quantia.core.backtest import trade_decision as _td
                    _derived = self._derive_reason_from_logs(date, code, 'buy')
                    _r = _td.resolve_reason('buy', order_info.get('reason'),
                                            derived_reason=_derived)
                    trade.reason = _r.get('reason', '')
                    trade.reason_source = _r.get('reason_source', '')
                except Exception:
                    trade.reason = order_info.get('reason') or ''
                self._trade_records.append(trade)

            # 卖出
            elif amount < 0:
                sell_amount = abs(amount)
                pos = self.context.portfolio.positions.get(code)
                if not pos or pos.closeable_amount <= 0:
                    continue

                sell_amount = min(sell_amount, pos.closeable_amount)
                sell_amount = int(sell_amount / 100) * 100
                if sell_amount <= 0:
                    # 可能不足100股但有余股，允许卖出
                    sell_amount = pos.closeable_amount

                # 卖出前记录持仓均价，用于计算平仓盈亏
                avg_cost_before_sell = pos.avg_cost

                actual_price = exec_price * (1 - self.context.slippage_rate)
                total_income = actual_price * sell_amount
                commission = max(total_income * self.context.commission_rate, 5.0)
                tax = total_income * self.context.stamp_tax_rate

                # 执行卖出
                pos._on_sell(sell_amount, exec_price)  # 剩余持仓以市场收盘价估值
                self.context.portfolio.available_cash += (total_income - commission - tax)

                stock_name = self._resolve_stock_name(code)
                trade = TradeRecord(date, code, stock_name, 'sell', exec_price, sell_amount)
                trade.commission = round(commission, 2)
                trade.tax = round(tax, 2)
                trade.slippage_cost = round(exec_price * self.context.slippage_rate * sell_amount, 2)
                # 平仓盈亏 = (卖出价 - 持仓均价) × 卖出数量
                trade.close_profit = round((exec_price - avg_cost_before_sell) * sell_amount, 2)
                # 收益率 = (卖出价 - 持仓均价) / 持仓均价 × 100
                if avg_cost_before_sell > 0:
                    trade.return_rate = round((exec_price - avg_cost_before_sell) / avg_cost_before_sell * 100, 2)
                try:
                    from quantia.core.backtest import trade_decision as _td
                    _derived = self._derive_reason_from_logs(date, code, 'sell')
                    _r = _td.resolve_reason('sell', order_info.get('reason'),
                                            derived_reason=_derived)
                    trade.reason = _r.get('reason', '')
                    trade.reason_source = _r.get('reason_source', '')
                except Exception:
                    trade.reason = order_info.get('reason') or ''
                self._trade_records.append(trade)

        self._pending_orders.clear()

    # ── 数据管理 ──

    def _discover_and_load_stocks(self, pre_start, end_date):
        """
        发现策略涉及的股票并预加载数据。
        初始化时从 context 和 g 的属性中提取股票代码。
        支持6位纯数字代码和聚宽风格（如 '000001.XSHE'）。
        """
        codes = set()

        def _try_extract(val):
            """尝试从值中提取股票代码"""
            if isinstance(val, str):
                # 纯6位数字
                if len(val) == 6 and val.isdigit():
                    codes.add(val)
                # 聚宽格式: 000001.XSHE / 600036.XSHG
                elif '.' in val:
                    prefix = val.split('.')[0]
                    if len(prefix) == 6 and prefix.isdigit():
                        codes.add(prefix)
            elif isinstance(val, (list, tuple, set)):
                for item in val:
                    _try_extract(item)

        # 从 context 中发现股票代码
        for attr in dir(self.context):
            _try_extract(getattr(self.context, attr, None))

        # 也从 g 对象中发现
        for attr in dir(self.g):
            if attr.startswith('_'):
                continue
            _try_extract(getattr(self.g, attr, None))

        if codes:
            index_codes = {code for code in codes if code in self._INDEX_CODES or code.startswith('399')}
            stock_codes = sorted(codes - index_codes)
            self._all_codes = codes

            # 预加载数量上限：票池过大时只预热前 N 只，其余在访问时按需
            # 加载（_ensure_stock_loaded + LRU），把全市场加载改为流式 + 有界常驻。
            cap = self._MAX_STOCKS_IN_MEM
            preload_codes = stock_codes
            if len(stock_codes) > cap:
                preload_codes = stock_codes[:cap]
                logging.info(
                    f"[回测引擎] 候选股票 {len(stock_codes)} 只 > 常驻上限 {cap}，"
                    f"仅预热前 {cap} 只，其余按需流式加载")
            else:
                logging.info(f"[回测引擎] 预加载 {len(stock_codes)} 只股票数据")

            # 重置为有界 LRU，分批拉取以降低加载峰值内存
            self._stock_data = _LRUStockData(cap)
            batch = max(1, self._PRELOAD_BATCH_SIZE)
            for start in range(0, len(preload_codes), batch):
                chunk = preload_codes[start:start + batch]
                raw_chunk = load_multiple_stocks(chunk, pre_start, end_date)
                for code, df in raw_chunk.items():
                    self._stock_data[code] = self._to_indexed_df(df)
                del raw_chunk  # 立即释放本批原始数据

            # 指数数据始终全部加载并固定常驻（数量少、需全程可用）
            for code in index_codes:
                df = load_benchmark_data(code, pre_start, end_date)
                if df is not None and len(df) > 0:
                    self._stock_data[code] = self._to_indexed_df(df)
                    self._stock_data.pin(code)

            # 内存估算与警告
            total_mem = sum(df.memory_usage(deep=True).sum() for df in self._stock_data.values())
            mem_mb = total_mem / 1024 / 1024
            logging.info(f"[回测引擎] 股票数据内存: {mem_mb:.0f} MB ({len(self._stock_data)} 只常驻)")
            if mem_mb > 500:
                logging.warning(f"[回测引擎] 股票数据占用 {mem_mb:.0f}MB，低内存服务器可能出现 OOM")

            # 批量加载股票名称
            self._load_stock_names_batch(codes)

    def _load_single_stock(self, code):
        """延迟加载单只股票或指数（被 LRU 淘汰后会再次触发此重载，数据一致）"""
        if code in self._stock_data:
            return
        # 使用更早的开始日期来提供多周期 history() 数据
        pre_start = None
        if self.context.current_dt:
            pre_start = (pd.Timestamp(self.context.current_dt) - pd.Timedelta(days=750)).strftime('%Y-%m-%d')

        # 指数代码使用指数数据源
        if code in self._INDEX_CODES or code.startswith('399'):
            df = load_benchmark_data(code, start_date=pre_start)
        else:
            df = load_stock_data(code, start_date=pre_start)
        if df is not None:
            self._stock_data[code] = self._to_indexed_df(df)

    # 聚宽兼容别名
    _ensure_stock_loaded = _load_single_stock

    @staticmethod
    def _to_indexed_df(df):
        """将 DataFrame 转为 DatetimeIndex 格式并降低内存占用"""
        idx_df = df.set_index('date').sort_index()
        # 降精度：float64 → float32（节省约 50% 内存）
        float_cols = idx_df.select_dtypes(include=['float64']).columns
        if len(float_cols) > 0:
            idx_df[float_cols] = idx_df[float_cols].astype(np.float32)
        int_cols = idx_df.select_dtypes(include=['int64']).columns
        if len(int_cols) > 0:
            idx_df[int_cols] = idx_df[int_cols].astype(np.int32)
        return idx_df

    def _build_date_index(self, code, df):
        """将原始 DataFrame 转为 DatetimeIndex 格式并存入 _stock_data"""
        self._stock_data[code] = self._to_indexed_df(df)

    def _load_day_prices(self, date):
        """加载当日所有股票的收盘价，更新 data_proxy"""
        prices = {}
        ts_date = pd.Timestamp(date)

        for code, idx_df in self._stock_data.items():
            if ts_date in idx_df.index:
                row = idx_df.loc[ts_date]
                close = float(row['close'])
                prices[code] = close
                bar = {
                    'open': float(row.get('open', close)),
                    'high': float(row.get('high', close)),
                    'low': float(row.get('low', close)),
                    'close': close,
                    'volume': int(row.get('volume', 0)),
                    'pre_close': float(row.get('pre_close', close)),
                }
                self.data_proxy._set_current(code, bar)

        # 确保所有持仓都有当日价格：被 LRU 淘汰的持仓需重载后再估值，
        # 否则市值会停留在旧价格导致净值计算错误。
        try:
            held = list(self.context.portfolio.positions.keys()) if self.context and self.context.portfolio else []
        except Exception:
            held = []
        for code in held:
            if code in prices:
                continue
            if code not in self._stock_data:
                self._load_single_stock(code)
            idx_df = self._stock_data.get(code)
            if idx_df is None or ts_date not in idx_df.index:
                continue
            row = idx_df.loc[ts_date]
            close = float(row['close'])
            prices[code] = close
            self.data_proxy._set_current(code, {
                'open': float(row.get('open', close)),
                'high': float(row.get('high', close)),
                'low': float(row.get('low', close)),
                'close': close,
                'volume': int(row.get('volume', 0)),
                'pre_close': float(row.get('pre_close', close)),
            })

        return prices


def run_backtest(strategy_code, start_date, end_date,
                 initial_cash=1000000, benchmark='000300',
                 commission=0.0003, tax=0.001, slippage=0.002):
    """
    便捷函数：运行回测并返回结果。

    用法：
        from quantia.core.backtest.portfolio_engine import run_backtest
        result = run_backtest(strategy_code, '2024-01-01', '2025-01-01')
    """
    engine = PortfolioBacktestEngine()
    return engine.run(strategy_code, start_date, end_date,
                      initial_cash, benchmark, commission, tax, slippage)

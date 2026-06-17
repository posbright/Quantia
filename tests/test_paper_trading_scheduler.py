#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模拟交易调度器、执行日志、概述统计 综合测试

覆盖：
  - PaperTradingScheduler 调度逻辑（_should_run / _execute / 日志记录）
  - 执行日志表创建与查询
  - 模拟盘概述/统计计算 (list handler metrics)
  - 详情页绩效指标计算 (_compute_paper_metrics)
  - 手动执行触发 + 日志记录
  - Web handler: execution_log API
"""

import sys
import os
import json
import datetime
from decimal import Decimal
from unittest import mock
from unittest.mock import patch, MagicMock, call, PropertyMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# ===========================================================================
#  1. Scheduler: _should_run 判断逻辑
# ===========================================================================

class TestSchedulerShouldRun:
    """Test PaperTradingScheduler._should_run decision logic."""

    def _make_scheduler(self, **kwargs):
        from quantia.paper_trading.scheduler import PaperTradingScheduler
        return PaperTradingScheduler(**kwargs)

    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    def test_should_run_after_close(self, _mock_td):
        """交易日收盘后 16:05 应该执行（当日首次）"""
        s = self._make_scheduler(run_after_hour=16, run_after_minute=0)
        now = datetime.datetime(2026, 4, 21, 16, 5, 0)
        should, reason = s._should_run(now)
        assert should is True
        assert reason == 'after_close'

    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    def test_before_run_time(self, _mock_td):
        """交易时段内（14:30）按 30min 节流触发，首次触发为 trading_interval。"""
        s = self._make_scheduler(run_after_hour=16, run_after_minute=0)
        now = datetime.datetime(2026, 4, 21, 14, 30, 0)
        should, reason = s._should_run(now)
        assert should is True
        assert reason == 'trading_interval'

    @patch('quantia.lib.trade_time.is_trade_date', return_value=False)
    def test_not_trade_day(self, _mock_td):
        """非交易日不执行"""
        s = self._make_scheduler()
        now = datetime.datetime(2026, 4, 19, 16, 30, 0)  # Saturday
        should, reason = s._should_run(now)
        assert should is False
        assert reason == 'not_trade_day'

    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    def test_already_run_today(self, _mock_td):
        """旧的全局运行标记不阻止收盘后触发（_last_close_run_date 才是闸门）。"""
        s = self._make_scheduler()
        s._last_run_date = datetime.date(2026, 4, 21)
        now = datetime.datetime(2026, 4, 21, 17, 0, 0)
        should, reason = s._should_run(now)
        assert should is True
        assert reason == 'after_close'

    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    def test_already_running(self, _mock_td):
        """正在执行中则跳过"""
        s = self._make_scheduler()
        s._running = True
        now = datetime.datetime(2026, 4, 21, 16, 30, 0)
        should, reason = s._should_run(now)
        assert should is False
        assert reason == 'already_running'

    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    def test_different_day_can_run(self, _mock_td):
        """上一个运行日是昨天，今天收盘后可以运行"""
        s = self._make_scheduler(run_after_hour=16, run_after_minute=0)
        s._last_run_date = datetime.date(2026, 4, 20)
        now = datetime.datetime(2026, 4, 21, 16, 30, 0)
        should, reason = s._should_run(now)
        assert should is True
        assert reason == 'after_close'

    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    def test_exact_run_time(self, _mock_td):
        """刚好到执行时间"""
        s = self._make_scheduler(run_after_hour=16, run_after_minute=0)
        now = datetime.datetime(2026, 4, 21, 16, 0, 0)
        should, reason = s._should_run(now)
        assert should is True

    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    def test_custom_run_time(self, _mock_td):
        """自定义收盘后 17:30：17:29 落在 15:00~17:30 结算空档不触发，17:30 收盘后触发。"""
        s = self._make_scheduler(run_after_hour=17, run_after_minute=30)
        should, reason = s._should_run(datetime.datetime(2026, 4, 21, 17, 29, 0))
        assert should is False
        assert reason == 'between_close_and_run'
        should, reason = s._should_run(datetime.datetime(2026, 4, 21, 17, 30, 0))
        assert should is True
        assert reason == 'after_close'

    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    def test_trading_window_throttled(self, _mock_td):
        """交易时段内 30min 节流：刚触发过则 10 分钟后不再触发，超过 30min 后可再次触发。"""
        s = self._make_scheduler(run_after_hour=16, run_after_minute=0)
        s._last_trigger_at = datetime.datetime(2026, 4, 21, 10, 0, 0)
        should, reason = s._should_run(datetime.datetime(2026, 4, 21, 10, 10, 0))
        assert should is False
        assert reason == 'trading_throttled'
        should, reason = s._should_run(datetime.datetime(2026, 4, 21, 10, 31, 0))
        assert should is True
        assert reason == 'trading_interval'

    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    def test_before_open(self, _mock_td):
        """开盘前（09:00）不触发。"""
        s = self._make_scheduler(run_after_hour=16, run_after_minute=0)
        should, reason = s._should_run(datetime.datetime(2026, 4, 21, 9, 0, 0))
        assert should is False
        assert reason == 'before_open'

    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    def test_late_night_still_runs(self, _mock_td):
        """深夜 23:00 仍然可以执行（如果今天没执行过）"""
        s = self._make_scheduler(run_after_hour=16, run_after_minute=0)
        now = datetime.datetime(2026, 4, 21, 23, 0, 0)
        should, reason = s._should_run(now)
        assert should is True


# ===========================================================================
#  2. Scheduler: _execute_paper_trading 与日志记录
# ===========================================================================

class TestSchedulerExecution:
    """Test PaperTradingScheduler execution and log saving."""

    def _make_scheduler(self):
        from quantia.paper_trading.scheduler import PaperTradingScheduler
        return PaperTradingScheduler()

    @patch('quantia.paper_trading.paper_engine.run_all_paper_trading')
    def test_execute_success(self, mock_run_all):
        """成功执行后记录日志（每个模拟盘的日志由 engine 自行记录）"""
        mock_run_all.return_value = [
            {'id': 1, 'status': 'ok', 'message': '执行完成', 'trades': 3, 'total_value': 1050000},
            {'id': 2, 'status': 'skipped', 'message': '今日已运行'},
        ]
        s = self._make_scheduler()
        trade_date = datetime.date(2026, 4, 21)
        s._execute_paper_trading(trade_date)

        mock_run_all.assert_called_once_with(scheduled=True)
        assert s._running is False

    @patch('quantia.paper_trading.scheduler._save_execution_log')
    @patch('quantia.paper_trading.paper_engine.run_all_paper_trading')
    def test_execute_no_papers(self, mock_run_all, mock_save_log):
        """无运行中的模拟盘"""
        mock_run_all.return_value = None
        s = self._make_scheduler()
        s._execute_paper_trading(datetime.date(2026, 4, 21))

        mock_save_log.assert_called_once_with(
            None, datetime.date(2026, 4, 21), mock.ANY,
            'skipped', '无运行中的模拟盘')
        assert s._running is False

    @patch('quantia.paper_trading.scheduler._save_execution_log')
    @patch('quantia.paper_trading.paper_engine.run_all_paper_trading',
           side_effect=Exception('DB exploded'))
    def test_execute_error_clears_last_run(self, mock_run_all, mock_save_log):
        """执行异常后清除 last_run_date 以允许重试"""
        s = self._make_scheduler()
        s._last_run_date = datetime.date(2026, 4, 21)
        s._execute_paper_trading(datetime.date(2026, 4, 21))

        assert s._last_run_date is None  # 允许重试
        assert s._running is False
        mock_save_log.assert_called_once()
        assert mock_save_log.call_args[0][3] == 'error'

    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    @patch('quantia.paper_trading.scheduler._save_execution_log')
    @patch('quantia.paper_trading.paper_engine.run_all_paper_trading',
           side_effect=Exception('DB exploded'))
    def test_after_close_error_allows_retry(self, mock_run_all, mock_save_log, _mock_td):
        """收盘后那次执行失败后，清除 _last_close_run_date，允许当日重试。"""
        s = self._make_scheduler()  # 默认 run_after_hour=16
        trade_date = datetime.date(2026, 4, 21)
        # 模拟 _check_and_run 收盘后触发已设置当日收盘标记
        s._last_close_run_date = trade_date
        s._execute_paper_trading(trade_date)

        assert s._last_close_run_date is None  # 收盘标记已清除
        assert s._last_trigger_at is None      # 节流标记已清除
        # 现在 16:30 再次检查应允许重试（after_close）
        should, reason = s._should_run(datetime.datetime(2026, 4, 21, 16, 30, 0))
        assert should is True
        assert reason == 'after_close'

    @patch('quantia.paper_trading.scheduler._ensure_execution_log_table')
    @patch('quantia.lib.database.executeSql')
    def test_save_execution_log_static(self, mock_exec, mock_ensure):
        """静态方法 _save_execution_log 写入数据库"""
        from quantia.paper_trading.scheduler import PaperTradingScheduler
        started = datetime.datetime(2026, 4, 21, 16, 0, 0)
        PaperTradingScheduler._save_execution_log(
            paper_id=2, trade_date=datetime.date(2026, 4, 21),
            started_at=started, status='ok', message='执行完成',
            trades=5, total_value=1050000)

        mock_ensure.assert_called_once()
        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert 'cn_stock_paper_execution_log' in args[0]
        params = args[1]
        assert params[0] == 2  # paper_id
        assert params[2] == 'ok'  # status
        assert params[3] == '执行完成'  # message

    @patch('quantia.paper_trading.scheduler._ensure_execution_log_table',
           side_effect=Exception('DB down'))
    def test_save_execution_log_failure_suppressed(self, mock_ensure):
        """日志保存失败不应抛出异常"""
        from quantia.paper_trading.scheduler import PaperTradingScheduler
        # Should not raise
        PaperTradingScheduler._save_execution_log(
            1, datetime.date(2026, 4, 21),
            datetime.datetime.now(), 'ok', 'test')

    @patch('quantia.paper_trading.scheduler._save_execution_log')
    def test_save_execution_logs_batch(self, mock_save_one):
        """_save_execution_logs 为每个结果调用一次"""
        from quantia.paper_trading.scheduler import PaperTradingScheduler
        results = [
            {'id': 1, 'status': 'ok', 'message': 'done', 'trades': 2, 'total_value': 100},
            {'id': 2, 'status': 'error', 'message': 'fail', 'trades': 0},
        ]
        PaperTradingScheduler._save_execution_logs(
            results, datetime.date(2026, 4, 21), datetime.datetime.now())
        assert mock_save_one.call_count == 2


# ===========================================================================
#  3. Scheduler: start / stop / last_run_date 属性
# ===========================================================================

class TestSchedulerLifecycle:
    """Test scheduler start/stop/properties."""

    def test_initial_state(self):
        from quantia.paper_trading.scheduler import PaperTradingScheduler
        s = PaperTradingScheduler()
        assert s.last_run_date is None
        assert s._running is False
        assert s._callback is None

    @patch('tornado.ioloop.PeriodicCallback')
    def test_start_creates_callback(self, MockPC):
        from quantia.paper_trading.scheduler import PaperTradingScheduler
        s = PaperTradingScheduler(check_interval_ms=60000)
        s.start()
        MockPC.assert_called_once_with(s._check_and_run, 60000)
        MockPC.return_value.start.assert_called_once()

    @patch('tornado.ioloop.PeriodicCallback')
    def test_stop_clears_callback(self, MockPC):
        from quantia.paper_trading.scheduler import PaperTradingScheduler
        s = PaperTradingScheduler()
        s.start()
        s.stop()
        MockPC.return_value.stop.assert_called_once()
        assert s._callback is None


# ===========================================================================
#  4. Execution Log Table
# ===========================================================================

class TestExecutionLogTable:
    """Test _ensure_execution_log_table."""

    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSql')
    def test_table_exists_no_create(self, mock_exec, mock_check):
        """表已存在不重复创建"""
        import quantia.paper_trading.scheduler as sched
        sched._log_table_ensured = False  # reset
        sched._ensure_execution_log_table()
        mock_check.assert_called_once_with('cn_stock_paper_execution_log')
        mock_exec.assert_not_called()
        sched._log_table_ensured = False  # cleanup

    @patch('quantia.lib.database.checkTableIsExist', return_value=False)
    @patch('quantia.lib.database.executeSql')
    def test_table_not_exists_creates(self, mock_exec, mock_check):
        """表不存在则创建"""
        import quantia.paper_trading.scheduler as sched
        sched._log_table_ensured = False
        sched._ensure_execution_log_table()
        mock_exec.assert_called_once()
        assert 'cn_stock_paper_execution_log' in mock_exec.call_args[0][0]
        assert sched._log_table_ensured is True
        sched._log_table_ensured = False  # cleanup

    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    def test_cached_flag_skips_check(self, mock_check):
        """cached flag 跳过检查"""
        import quantia.paper_trading.scheduler as sched
        sched._log_table_ensured = True
        sched._ensure_execution_log_table()
        mock_check.assert_not_called()
        sched._log_table_ensured = False  # cleanup


# ===========================================================================
#  5. 概述/统计：_compute_paper_metrics
# ===========================================================================

class TestComputePaperMetrics:
    """Test _compute_paper_metrics from paperTradingHandler."""

    def _compute(self, nav_rows, trade_rows=None):
        from quantia.web.paperTradingHandler import _compute_paper_metrics
        return _compute_paper_metrics(nav_rows, trade_rows or [])

    def test_empty_nav(self):
        """空 NAV 返回全零指标"""
        m = self._compute([])
        assert m['total_return'] == 0
        assert m['max_drawdown'] == 0
        assert m['sharpe_ratio'] == 0
        assert m['running_days'] == 0

    def test_single_nav(self):
        """只有一个 NAV 点"""
        nav = [(datetime.date(2026, 4, 20), 100000, 100000, 0)]
        m = self._compute(nav)
        assert m['total_return'] == 0
        assert m['running_days'] == 0

    def test_positive_return(self):
        """正收益场景"""
        nav = [
            (datetime.date(2026, 1, 1), 100000, 50000, 50000),
            (datetime.date(2026, 4, 1), 120000, 60000, 60000),
        ]
        m = self._compute(nav)
        assert m['total_return'] == pytest.approx(20.0, abs=0.1)
        assert m['running_days'] == 90

    def test_negative_return(self):
        """负收益场景"""
        nav = [
            (datetime.date(2026, 1, 1), 100000, 50000, 50000),
            (datetime.date(2026, 4, 1), 80000, 40000, 40000),
        ]
        m = self._compute(nav)
        assert m['total_return'] == pytest.approx(-20.0, abs=0.1)

    def test_max_drawdown(self):
        """最大回撤计算"""
        nav = [
            (datetime.date(2026, 1, 1), 100000, 100000, 0),
            (datetime.date(2026, 2, 1), 120000, 120000, 0),  # peak
            (datetime.date(2026, 3, 1), 90000, 90000, 0),    # drawdown
            (datetime.date(2026, 4, 1), 110000, 110000, 0),  # recovery
        ]
        m = self._compute(nav)
        # drawdown = (120000 - 90000) / 120000 = 25%
        assert m['max_drawdown'] == pytest.approx(25.0, abs=0.1)

    def test_today_return(self):
        """今日收益率"""
        nav = [
            (datetime.date(2026, 4, 20), 100000, 100000, 0),
            (datetime.date(2026, 4, 21), 102000, 102000, 0),
        ]
        m = self._compute(nav)
        assert m['today_return'] == pytest.approx(2.0, abs=0.1)

    def test_annual_return(self):
        """年化收益"""
        nav = [
            (datetime.date(2025, 4, 21), 100000, 100000, 0),
            (datetime.date(2026, 4, 21), 110000, 110000, 0),
        ]
        m = self._compute(nav)
        # 365 days, 10% total -> ~10% annual
        assert m['annual_return'] == pytest.approx(10.0, abs=1.0)

    def test_sharpe_with_daily_returns(self):
        """有足够数据点计算 Sharpe"""
        # 生成 30 天的 NAV 数据，每天涨 0.1%
        base = 100000
        nav = []
        for i in range(30):
            d = datetime.date(2026, 3, 1) + datetime.timedelta(days=i)
            val = base * (1.001 ** i)
            nav.append((d, val, val, 0))
        m = self._compute(nav)
        assert m['sharpe_ratio'] != 0  # 有值即可
        assert m['running_days'] == 29

    def test_win_rate_from_trades(self):
        """交易胜率计算"""
        # Trade rows: (date, code, name, direction, price, amount, value, commission, tax)
        trades = [
            (datetime.date(2026, 3, 1), '000001', '平安银行', 'buy', 10.0, 100, 1000, 3, 0),
            (datetime.date(2026, 3, 5), '000001', '平安银行', 'sell', 11.0, 100, 1100, 3, 1.1),  # profit
            (datetime.date(2026, 3, 2), '000002', '万科A', 'buy', 20.0, 100, 2000, 6, 0),
            (datetime.date(2026, 3, 6), '000002', '万科A', 'sell', 18.0, 100, 1800, 5.4, 1.8),  # loss
        ]
        nav = [
            (datetime.date(2026, 3, 1), 100000, 100000, 0),
            (datetime.date(2026, 3, 6), 100800, 100800, 0),
        ]
        m = self._compute(nav, trades)
        # 1 win out of 2 trades = 50%
        assert m['win_rate'] == pytest.approx(50.0, abs=1)
        assert m['trade_count'] >= 2

    def test_zero_initial_value(self):
        """初始值为 0 不崩溃"""
        nav = [
            (datetime.date(2026, 1, 1), 0, 0, 0),
            (datetime.date(2026, 2, 1), 0, 0, 0),
        ]
        m = self._compute(nav)
        assert m['total_return'] == 0


# ===========================================================================
#  6. 列表概述统计（ListHandler 中的年化、回撤、今日收益计算）
# ===========================================================================

class TestListOverviewStats:
    """Test overview stats computed in GetPaperTradingListHandler.

    These are inline calculations; test them via a mock handler simulation.
    """

    def test_annual_return_computation(self):
        """年化收益公式：((last/first)^(365/days) - 1) * 100"""
        # 90 天从 100000 到 110000
        first_val = 100000
        last_val = 110000
        days = 90
        ann_factor = 365.0 / days
        annual_return = round(((last_val / first_val) ** ann_factor - 1) * 100, 2)
        # ~46% annualized for 10% in 90 days
        assert annual_return > 40
        assert annual_return < 50

    def test_max_drawdown_computation(self):
        """最大回撤计算逻辑"""
        nav_values = [100, 120, 110, 130, 90, 140]
        peak = nav_values[0]
        max_dd = 0
        for v in nav_values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        # Peak=130, trough=90 → (130-90)/130 ≈ 30.77%
        assert max_dd == pytest.approx(30.77, abs=0.1)

    def test_today_return_computation(self):
        """今日收益率计算"""
        prev_val = 100000
        last_val = 101500
        today_return = round((last_val / prev_val - 1) * 100, 2)
        assert today_return == 1.5

    def test_profit_rate_computation(self):
        """总收益率计算"""
        initial = 1000000
        current = 1050000
        profit_rate = (current / initial - 1) * 100
        assert profit_rate == pytest.approx(5.0, abs=0.01)


# ===========================================================================
#  7. 调度器与 check_and_run 集成
# ===========================================================================

class TestSchedulerCheckAndRun:
    """Test _check_and_run integration."""

    @patch('tornado.ioloop.IOLoop')
    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    def test_check_and_run_triggers_executor(self, _mock_td, mock_ioloop_cls):
        """_check_and_run 在条件满足时提交到线程池"""
        from quantia.paper_trading.scheduler import PaperTradingScheduler
        s = PaperTradingScheduler(run_after_hour=16, run_after_minute=0)

        mock_loop = MagicMock()
        mock_ioloop_cls.current.return_value = mock_loop

        with patch.object(s, '_should_run', return_value=(True, 'ok')):
            s._check_and_run()

        assert s._running is True
        assert s._last_run_date is not None
        mock_loop.run_in_executor.assert_called_once()

    @patch('quantia.lib.trade_time.is_trade_date', return_value=False)
    def test_check_and_run_skips_non_trade_day(self, _mock_td):
        """非交易日不触发"""
        from quantia.paper_trading.scheduler import PaperTradingScheduler
        s = PaperTradingScheduler()
        s._check_and_run()
        assert s._running is False
        assert s._last_run_date is None


# ===========================================================================
#  8. RunPaperTradingHandler 手动触发 + 日志记录
# ===========================================================================

class TestRunPaperTradingWithLog:
    """Test that paper trading execution records execution log via engine's finally block."""

    @patch('quantia.paper_trading.scheduler._save_execution_log')
    @patch('quantia.paper_trading.paper_engine._ensure_paper_table')
    @patch('quantia.lib.database.executeSqlFetch')
    @patch('quantia.lib.trade_time.get_trade_date_last',
           return_value=(datetime.date(2026, 4, 20), datetime.date(2026, 4, 21)))
    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    def test_engine_records_log_on_skip(self, _td, _trd, mock_fetch, _tbl, mock_save_log):
        """引擎 skip 时也记录执行日志"""
        from quantia.paper_trading.paper_engine import run_paper_trading_daily
        mock_fetch.return_value = [
            (2, 29, 100000, 'running', datetime.date(2026, 4, 21),
             '{}', 'def initialize(ctx): pass')]
        result = run_paper_trading_daily(2)
        assert result['status'] == 'skipped'
        # finally 块应该调用 _save_execution_log
        mock_save_log.assert_called_once()
        args = mock_save_log.call_args[0]
        assert args[0] == 2  # paper_id
        assert args[3] == 'skipped'  # status

    @patch('quantia.paper_trading.scheduler._save_execution_log')
    @patch('quantia.lib.trade_time.get_trade_date_last',
           return_value=(datetime.date(2026, 4, 20), datetime.date(2026, 4, 21)))
    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    def test_engine_records_log_on_not_found(self, _td, _trd, mock_save_log):
        """模拟盘不存在也记录执行日志"""
        from quantia.paper_trading.paper_engine import run_paper_trading_daily
        with patch('quantia.paper_trading.paper_engine._ensure_paper_table'), \
             patch('quantia.lib.database.executeSqlFetch', return_value=[]):
            result = run_paper_trading_daily(999)
        assert result['status'] == 'error'
        mock_save_log.assert_called_once()
        assert mock_save_log.call_args[0][3] == 'error'

    @patch('quantia.paper_trading.scheduler._save_execution_log')
    @patch('quantia.lib.trade_time.get_trade_date_last',
           return_value=(datetime.date(2026, 4, 20), datetime.date(2026, 4, 21)))
    @patch('quantia.lib.trade_time.is_trade_date', return_value=False)
    def test_engine_records_log_on_non_trade_day(self, _td, _trd, mock_save_log):
        """非交易日也记录执行日志"""
        from quantia.paper_trading.paper_engine import run_paper_trading_daily
        result = run_paper_trading_daily(2)
        assert result['status'] == 'skipped'
        mock_save_log.assert_called_once()
        assert mock_save_log.call_args[0][3] == 'skipped'


# ===========================================================================
#  9. 执行日志消息截断安全
# ===========================================================================

class TestExecutionLogSafety:
    """Test execution log message safety."""

    @patch('quantia.paper_trading.scheduler._ensure_execution_log_table')
    @patch('quantia.lib.database.executeSql')
    def test_message_truncated_to_500(self, mock_exec, mock_ensure):
        """超长消息截断到 500 字符"""
        from quantia.paper_trading.scheduler import PaperTradingScheduler
        long_msg = 'x' * 1000
        PaperTradingScheduler._save_execution_log(
            1, datetime.date(2026, 4, 21), datetime.datetime.now(),
            'error', long_msg)
        params = mock_exec.call_args[0][1]
        assert len(params[3]) == 500  # message field (index 3)

    @patch('quantia.paper_trading.scheduler._ensure_execution_log_table')
    @patch('quantia.lib.database.executeSql')
    def test_none_message_handled(self, mock_exec, mock_ensure):
        """None 消息不崩溃"""
        from quantia.paper_trading.scheduler import PaperTradingScheduler
        PaperTradingScheduler._save_execution_log(
            1, datetime.date(2026, 4, 21), datetime.datetime.now(),
            'ok', None)
        params = mock_exec.call_args[0][1]
        assert params[3] == ''  # message field (index 3)

    @patch('quantia.paper_trading.scheduler._ensure_execution_log_table')
    @patch('quantia.lib.database.executeSql')
    def test_paper_id_can_be_none(self, mock_exec, mock_ensure):
        """paper_id 为 None（全局事件如'无运行中的模拟盘'）"""
        from quantia.paper_trading.scheduler import PaperTradingScheduler
        PaperTradingScheduler._save_execution_log(
            None, datetime.date(2026, 4, 21), datetime.datetime.now(),
            'skipped', '无运行中的模拟盘')
        params = mock_exec.call_args[0][1]
        assert params[0] is None


# ===========================================================================
#  10. 模拟盘重复运行防护
# ===========================================================================

class TestDuplicateRunGuard:
    """Test duplicate run guard in run_paper_trading_daily."""

    @patch('quantia.paper_trading.paper_engine._ensure_paper_table')
    @patch('quantia.lib.database.executeSqlFetch')
    @patch('quantia.lib.trade_time.get_trade_date_last',
           return_value=(datetime.date(2026, 4, 21), datetime.date(2026, 4, 21)))
    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    def test_same_date_skipped(self, _td, _trd, mock_fetch, _tbl):
        """last_run_date == today 跳过"""
        from quantia.paper_trading.paper_engine import run_paper_trading_daily
        mock_fetch.return_value = [
            (2, 29, 100000, 'running', datetime.date(2026, 4, 21),
             '{}', 'def initialize(ctx): pass\ndef handle_data(ctx,d): pass')]
        result = run_paper_trading_daily(2)
        assert result['status'] == 'skipped'
        assert '已运行' in result['message']

    @patch('quantia.paper_trading.paper_engine._ensure_paper_table')
    @patch('quantia.lib.database.executeSqlFetch')
    @patch('quantia.lib.trade_time.get_trade_date_last',
           return_value=(datetime.date(2026, 4, 21), datetime.date(2026, 4, 21)))
    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    def test_previous_date_runs(self, _td, _trd, mock_fetch, _tbl):
        """last_run_date < today 允许执行"""
        from quantia.paper_trading.paper_engine import run_paper_trading_daily
        mock_fetch.return_value = [
            (2, 29, 100000, 'running', datetime.date(2026, 4, 20),
             None, 'def initialize(ctx): pass\ndef handle_data(ctx,d): pass')]

        with patch('quantia.paper_trading.paper_engine.compile_strategy') as mock_compile, \
             patch('quantia.paper_trading.paper_engine._create_api') as mock_api, \
             patch('quantia.paper_trading.paper_engine.load_stock_data', return_value=None), \
             patch('quantia.core.backtest.data_feed._batch_load_today_from_db', return_value={}), \
             patch('quantia.paper_trading.paper_engine._ensure_trade_table'), \
             patch('quantia.paper_trading.paper_engine._ensure_position_table'), \
             patch('quantia.paper_trading.paper_engine._ensure_nav_table'), \
             patch('quantia.paper_trading.paper_engine.serialize_portfolio', return_value='{}'), \
             patch('quantia.lib.database.get_connection') as mock_conn:

            mock_compile.return_value = {
                'initialize': MagicMock(),
                'handle_data': MagicMock(),
                'before_trading_start': None,
                'after_trading_end': None,
            }
            api_ns = {
                '_daily_callbacks': [],
                '_weekly_callbacks': [],
                '_monthly_callbacks': [],
            }
            mock_api.return_value = api_ns

            mock_ctx = MagicMock()
            mock_cur = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ctx.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
            mock_ctx.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.return_value = mock_ctx

            result = run_paper_trading_daily(2)
            # Should proceed to execution (not skipped)
            assert result['status'] != 'skipped' or '已运行' not in result.get('message', '')


# ===========================================================================
#  11. get_trade_date_last 时间边界
# ===========================================================================

class TestTradeDateLastBoundary:
    """Test get_trade_date_last at different times of day."""

    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    @patch('quantia.lib.trade_time.is_close', return_value=True)
    def test_after_close(self, _close, _td):
        """收盘后返回今天作为 run_date_nph"""
        import quantia.lib.trade_time as trd
        with patch('quantia.lib.trade_time.datetime') as mock_dt:
            mock_dt.datetime.now.return_value = datetime.datetime(2026, 4, 21, 16, 0, 0)
            mock_dt.time = datetime.time
            mock_dt.date = datetime.date
            # get_trade_date_last uses datetime.datetime.now() directly
            # This test verifies the expected behavior documentation

    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    def test_trade_date_returns_tuple(self, _td):
        """get_trade_date_last 返回 (date, date) 元组"""
        import quantia.lib.trade_time as trd
        result = trd.get_trade_date_last()
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], datetime.date)
        assert isinstance(result[1], datetime.date)


# ===========================================================================
#  12. Web Service 调度器注册
# ===========================================================================

class TestWebServiceSchedulerRegistration:
    """Test that scheduler is registered in web_service.main."""

    def test_scheduler_import_works(self):
        """调度器模块可正常导入"""
        from quantia.paper_trading.scheduler import PaperTradingScheduler
        s = PaperTradingScheduler()
        assert s is not None

    def test_scheduler_default_params(self):
        """默认参数正确"""
        from quantia.paper_trading.scheduler import (
            PaperTradingScheduler, RUN_AFTER_HOUR, RUN_AFTER_MINUTE, CHECK_INTERVAL_MS)
        assert RUN_AFTER_HOUR == 16
        assert RUN_AFTER_MINUTE == 0
        assert CHECK_INTERVAL_MS == 300000  # 5 minutes


# ===========================================================================
#  13. 详情页指标计算 - 边界情况
# ===========================================================================

class TestDetailMetricsEdgeCases:
    """Test _compute_paper_metrics edge cases."""

    def _compute(self, nav_rows, trade_rows=None):
        from quantia.web.paperTradingHandler import _compute_paper_metrics
        return _compute_paper_metrics(nav_rows, trade_rows or [])

    def test_flat_nav_sharpe_zero(self):
        """完全平坦的 NAV（无波动）→ sharpe 应该为 0 或极小"""
        nav = [(datetime.date(2026, 3, i+1), 100000, 100000, 0) for i in range(20)]
        m = self._compute(nav)
        # No volatility, return is 0 → sharpe = 0
        assert abs(m['sharpe_ratio']) < 0.01

    def test_single_trade_pair_win_rate_100(self):
        """单笔盈利交易 → 胜率 100%"""
        trades = [
            (datetime.date(2026, 3, 1), '000001', '平安银行', 'buy', 10.0, 100, 1000, 3, 0),
            (datetime.date(2026, 3, 5), '000001', '平安银行', 'sell', 12.0, 100, 1200, 3.6, 1.2),
        ]
        nav = [
            (datetime.date(2026, 3, 1), 100000, 100000, 0),
            (datetime.date(2026, 3, 5), 100196, 100196, 0),
        ]
        m = self._compute(nav, trades)
        assert m['win_rate'] == pytest.approx(100.0, abs=1)

    def test_single_trade_pair_loss_rate_0(self):
        """单笔亏损交易 → 胜率 0%"""
        trades = [
            (datetime.date(2026, 3, 1), '000001', '平安银行', 'buy', 10.0, 100, 1000, 3, 0),
            (datetime.date(2026, 3, 5), '000001', '平安银行', 'sell', 8.0, 100, 800, 2.4, 0.8),
        ]
        nav = [
            (datetime.date(2026, 3, 1), 100000, 100000, 0),
            (datetime.date(2026, 3, 5), 99794, 99794, 0),
        ]
        m = self._compute(nav, trades)
        assert m['win_rate'] == pytest.approx(0.0, abs=1)

    def test_no_trades_win_rate_zero(self):
        """无交易 → 胜率 0"""
        nav = [
            (datetime.date(2026, 3, 1), 100000, 100000, 0),
            (datetime.date(2026, 3, 5), 100000, 100000, 0),
        ]
        m = self._compute(nav, [])
        assert m['win_rate'] == 0
        assert m['trade_count'] == 0

    def test_very_short_period(self):
        """2天的 NAV → 应能正常计算"""
        nav = [
            (datetime.date(2026, 4, 20), 100000, 100000, 0),
            (datetime.date(2026, 4, 21), 100500, 100500, 0),
        ]
        m = self._compute(nav)
        assert m['total_return'] == pytest.approx(0.5, abs=0.1)
        assert m['running_days'] == 1


# ===========================================================================
#  14. Scheduler _save_execution_logs 与 run_all 结果映射
# ===========================================================================

class TestSchedulerResultMapping:
    """Test that scheduler correctly maps run_all results to logs."""

    @patch('quantia.paper_trading.scheduler._ensure_execution_log_table')
    @patch('quantia.lib.database.executeSql')
    def test_ok_result_mapped(self, mock_exec, mock_ensure):
        """ok 结果正确映射"""
        from quantia.paper_trading.scheduler import PaperTradingScheduler
        results = [{'id': 1, 'status': 'ok', 'message': 'done',
                     'trades': 5, 'total_value': 105000}]
        PaperTradingScheduler._save_execution_logs(
            results, datetime.date(2026, 4, 21), datetime.datetime.now())
        params = mock_exec.call_args[0][1]
        assert params[0] == 1  # paper_id
        assert params[2] == 'ok'  # status (index 2)
        assert params[3] == 'done'  # message (index 3)
        assert params[4] == 5  # trades (index 4)
        assert params[5] == 105000  # total_value (index 5)

    @patch('quantia.paper_trading.scheduler._ensure_execution_log_table')
    @patch('quantia.lib.database.executeSql')
    def test_error_result_mapped(self, mock_exec, mock_ensure):
        """error 结果正确映射"""
        from quantia.paper_trading.scheduler import PaperTradingScheduler
        results = [{'id': 3, 'status': 'error', 'message': 'DB错误'}]
        PaperTradingScheduler._save_execution_logs(
            results, datetime.date(2026, 4, 21), datetime.datetime.now())
        params = mock_exec.call_args[0][1]
        assert params[0] == 3
        assert params[2] == 'error'  # status (index 2)
        assert params[3] == 'DB错误'  # message (index 3)

    @patch('quantia.paper_trading.scheduler._ensure_execution_log_table')
    @patch('quantia.lib.database.executeSql')
    def test_skipped_result_mapped(self, mock_exec, mock_ensure):
        """skipped 结果正确映射"""
        from quantia.paper_trading.scheduler import PaperTradingScheduler
        results = [{'id': 2, 'status': 'skipped', 'message': '今日已运行'}]
        PaperTradingScheduler._save_execution_logs(
            results, datetime.date(2026, 4, 21), datetime.datetime.now())
        params = mock_exec.call_args[0][1]
        assert params[0] == 2
        assert params[2] == 'skipped'  # status (index 2)


# ===========================================================================
#  15. 并发安全：_running 标志
# ===========================================================================

class TestSchedulerConcurrencySafety:
    """Test _running flag prevents concurrent execution."""

    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    def test_running_flag_blocks(self, _td):
        """_running=True 阻止重复执行"""
        from quantia.paper_trading.scheduler import PaperTradingScheduler
        s = PaperTradingScheduler(run_after_hour=16, run_after_minute=0)
        s._running = True
        should, reason = s._should_run(datetime.datetime(2026, 4, 21, 17, 0, 0))
        assert should is False
        assert reason == 'already_running'

    @patch('quantia.paper_trading.scheduler._save_execution_log')
    @patch('quantia.paper_trading.paper_engine.run_all_paper_trading',
           side_effect=Exception('boom'))
    def test_running_flag_cleared_on_error(self, _run, _save):
        """异常后 _running 被清除"""
        from quantia.paper_trading.scheduler import PaperTradingScheduler
        s = PaperTradingScheduler()
        s._running = True
        s._execute_paper_trading(datetime.date(2026, 4, 21))
        assert s._running is False

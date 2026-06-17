#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模拟交易自动调度器

在 web 服务启动时注册，每个交易日收盘后自动执行所有运行中的模拟盘。
使用 Tornado IOLoop PeriodicCallback 实现定时检查。

调度逻辑：
1. 每 CHECK_INTERVAL 分钟检查一次
2. 交易日内持续触发；每个模拟盘是否到期由 paper_engine 按自身频率判断
3. 在线程池中执行，不阻塞 IOLoop
4. 执行结果写入 cn_stock_paper_execution_log 表
"""

import datetime
import logging
import os

import tornado.ioloop

log = logging.getLogger(__name__)

# 收盘后多久执行（给数据源留更新时间）；与 paper_engine 同源 env，便于联调
try:
    RUN_AFTER_HOUR = int(os.environ.get('QUANTIA_PAPER_DAILY_AFTER_HOUR', '16'))
except (TypeError, ValueError):
    RUN_AFTER_HOUR = 16
RUN_AFTER_MINUTE = 0
# 检查间隔（毫秒）—— _should_run 是纯计算（不访 DB），保持 5 分钟足够
CHECK_INTERVAL_MS = 5 * 60 * 1000  # 5 分钟
# 交易时段触发间隔（分钟）：交易时间内每 N 分钟触发一次 run_all，
# 砂掉旧的“交易日全天每 5 分钟空跑”（~288 次/天 → ~12 次/天）。
TRADING_TRIGGER_INTERVAL_MIN = 30
# 交易时段窗口（用于节流触发；收盘后另外单独触发一次）
_MARKET_OPEN = (9, 30)
_MARKET_CLOSE = (15, 0)


class PaperTradingScheduler:
    """模拟交易每日自动执行调度器"""

    def __init__(self, run_after_hour=None, run_after_minute=None,
                 check_interval_ms=None):
        self._run_after_hour = run_after_hour if run_after_hour is not None else RUN_AFTER_HOUR
        self._run_after_minute = run_after_minute if run_after_minute is not None else RUN_AFTER_MINUTE
        self._check_interval_ms = check_interval_ms or CHECK_INTERVAL_MS
        self._last_run_date = None
        self._last_trigger_at = None          # 上次触发时间（交易时段 30min 节流）
        self._last_close_run_date = None      # 上次收盘后触发的日期（每日一次）
        self._trading_interval_min = TRADING_TRIGGER_INTERVAL_MIN
        self._running = False
        self._callback = None

    def start(self):
        """启动调度器"""
        self._callback = tornado.ioloop.PeriodicCallback(
            self._check_and_run, self._check_interval_ms)
        self._callback.start()
        log.info("[模拟交易调度] 调度器已启动，每 %d 分钟检查一次，"
                 "收盘后 %02d:%02d 执行",
                 self._check_interval_ms // 60000,
                 self._run_after_hour, self._run_after_minute)

    def stop(self):
        """停止调度器"""
        if self._callback:
            self._callback.stop()
            self._callback = None

    @property
    def last_run_date(self):
        return self._last_run_date

    def _should_run(self, now=None):
        """判断当前是否应该触发 run_all_paper_trading（可注入 now 用于测试）。

        触发策略（砂掉旧的“交易日全天每 5 分钟空跑”）：
          - 交易时段（09:30~15:00）：每 TRADING_TRIGGER_INTERVAL_MIN 分钟触发一次；
          - 收盘后（>= run_after_hour:run_after_minute）：当日触发一次；
          - 15:00~收盘时间之间的结算空档、开盘前、非交易日：不触发。
        具体某个模拟盘是否真正下单，仍由 paper_engine 按自身频率判断。
        """
        import quantia.lib.trade_time as trd

        now = now or datetime.datetime.now()
        if not isinstance(now, datetime.datetime):
            now = datetime.datetime.combine(now, datetime.time())
        today = now.date()

        # 非交易日，跳过
        if not trd.is_trade_date(today):
            return False, 'not_trade_day'

        # 正在运行中，跳过
        if self._running:
            return False, 'already_running'

        close_dt = now.replace(hour=self._run_after_hour,
                               minute=self._run_after_minute,
                               second=0, microsecond=0)
        # 收盘后：当日仅触发一次
        if now >= close_dt:
            if self._last_close_run_date == today:
                return False, 'after_close_done'
            return True, 'after_close'

        # 交易时段（09:30~15:00）：每 N 分钟触发一次
        open_dt = now.replace(hour=_MARKET_OPEN[0], minute=_MARKET_OPEN[1],
                              second=0, microsecond=0)
        market_close_dt = now.replace(hour=_MARKET_CLOSE[0], minute=_MARKET_CLOSE[1],
                                      second=0, microsecond=0)
        if now < open_dt:
            return False, 'before_open'
        if now > market_close_dt:
            # 15:00~收盘时间（默认16:00）之间的结算空档，不触发
            return False, 'between_close_and_run'
        if (self._last_trigger_at is not None
                and self._last_trigger_at.date() == today
                and (now - self._last_trigger_at)
                < datetime.timedelta(minutes=self._trading_interval_min)):
            return False, 'trading_throttled'
        return True, 'trading_interval'

    def _check_and_run(self):
        """检查是否需要执行模拟交易（由 PeriodicCallback 调用）"""
        should, reason = self._should_run()
        if not should:
            return

        now = datetime.datetime.now()
        self._running = True
        today = now.date()
        self._last_run_date = today
        self._last_trigger_at = now
        if reason == 'after_close':
            self._last_close_run_date = today

        # 在线程池中执行，不阻塞 IOLoop
        tornado.ioloop.IOLoop.current().run_in_executor(
            None, self._execute_paper_trading, today)

    def _execute_paper_trading(self, trade_date):
        """在线程池中执行模拟交易"""
        started_at = datetime.datetime.now()
        try:
            log.info("[模拟交易调度] 开始执行每日模拟交易 (%s)", trade_date)
            from quantia.paper_trading.paper_engine import run_all_paper_trading
            results = run_all_paper_trading(scheduled=True)
            if results:
                ok = sum(1 for r in results if r.get('status') == 'ok')
                skipped = sum(1 for r in results if r.get('status') == 'skipped')
                errors = sum(1 for r in results if r.get('status') == 'error')
                log.info("[模拟交易调度] 完成: %d 成功, %d 跳过, %d 错误 (共 %d 个)",
                         ok, skipped, errors, len(results))
                # 每个模拟盘的执行日志已由 run_paper_trading_daily 自行记录
            else:
                log.info("[模拟交易调度] 无运行中的模拟盘")
                _save_execution_log(
                    None, trade_date, started_at, 'skipped', '无运行中的模拟盘')
        except Exception as e:
            log.error("[模拟交易调度] 执行异常", exc_info=True)
            # 出错后清除触发标记，允许下次检查（5min 后）重试：
            #   - _last_trigger_at 置空 → 交易时段节流解除，可立即重试；
            #   - 若失败的是当日收盘后那次，清掉 _last_close_run_date，否则当日不再重试。
            self._last_run_date = None
            self._last_trigger_at = None
            if self._last_close_run_date == trade_date:
                self._last_close_run_date = None
            _save_execution_log(
                None, trade_date, started_at, 'error', str(e))
        finally:
            self._running = False
            # 调度执行器线程跑完即回收本线程 DB 连接，避免在两次触发之间（最长 30min）
            # 长期占用服务端连接槽（连接泄漏 → max_connections 打满的诱因之一）。
            try:
                import quantia.lib.database as mdb
                mdb.close_thread_connection()
            except Exception:
                log.debug("[模拟交易调度] 回收线程 DB 连接失败（已忽略）", exc_info=True)

    @staticmethod
    def _save_execution_logs(results, trade_date, started_at):
        """批量保存执行日志"""
        for r in results:
            paper_id = r.get('id')
            status = r.get('status', 'unknown')
            message = r.get('message', '')
            trades = r.get('trades', 0)
            total_value = r.get('total_value')
            _save_execution_log(
                paper_id, trade_date, started_at, status, message,
                trades=trades, total_value=total_value)

    # 保持类方法兼容（已有测试引用）
    _save_execution_log = staticmethod(lambda *a, **kw: _save_execution_log(*a, **kw))


def _save_execution_log(paper_id, trade_date, started_at, status, message,
                        trades=0, total_value=None):
    """保存单条执行日志到数据库（模块级函数，供 paper_engine 等外部调用）"""
    try:
        import quantia.lib.database as mdb
        _ensure_execution_log_table()
        finished_at = datetime.datetime.now()
        mdb.executeSql(
            'INSERT INTO cn_stock_paper_execution_log '
            '(paper_id, trade_date, status, message, trade_count, '
            'total_value, started_at, finished_at) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
            (paper_id, str(trade_date), status,
             (message or '')[:500], trades, total_value,
             started_at, finished_at))
    except Exception as e:
        log.warning("[模拟交易调度] 保存执行日志失败: %s", e)


_log_table_ensured = False


def _ensure_execution_log_table():
    """确保执行日志表存在"""
    global _log_table_ensured
    if _log_table_ensured:
        return
    import quantia.lib.database as mdb
    if mdb.checkTableIsExist('cn_stock_paper_execution_log'):
        _log_table_ensured = True
        return
    mdb.executeSql('''
        CREATE TABLE IF NOT EXISTS `cn_stock_paper_execution_log` (
            `id` INT AUTO_INCREMENT PRIMARY KEY,
            `paper_id` INT DEFAULT NULL,
            `trade_date` DATE NOT NULL,
            `status` VARCHAR(20) NOT NULL,
            `message` VARCHAR(500),
            `trade_count` INT DEFAULT 0,
            `total_value` DECIMAL(15,2) DEFAULT NULL,
            `started_at` DATETIME,
            `finished_at` DATETIME,
            INDEX `idx_paper_date` (`paper_id`, `trade_date`),
            INDEX `idx_date` (`trade_date`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''')
    _log_table_ensured = True

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模拟交易 API Handler

提供模拟盘的创建、暂停、恢复、停止、状态查询等 API。
"""

import json
import logging
import datetime
from abc import ABC
from tornado import gen
import quantia.web.base as webBase
import quantia.lib.database as mdb

__author__ = 'Quantia'
__date__ = '2026/03/13'


_BENCHMARK_NAME_MAP = {
    '000001': '上证指数',
    '000016': '上证50',
    '000300': '沪深300',
    '000688': '科创50',
    '000852': '中证1000',
    '000905': '中证500',
    '000985': '中证全指',
    '399001': '深证成指',
    '399005': '中小综指',
    '399006': '创业板指',
}

_RUN_FREQUENCIES = ('daily', 'hourly', '15m')


class CreatePaperTradingHandler(webBase.BaseHandler, ABC):
    """创建模拟盘"""

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body)
            strategy_id = body.get('strategy_id')
            requested_backtest_id = _parse_optional_int(body.get('backtest_id'))
            name = body.get('name', '')
            initial_cash = body.get('initial_cash', 1000000)
            run_frequency = body.get('run_frequency', 'daily')
            start_at = body.get('start_at')

            if not strategy_id:
                self.write(json.dumps({'code': -1, 'msg': '缺少 strategy_id'}))
                return
            if run_frequency not in _RUN_FREQUENCIES:
                self.write(json.dumps({'code': -1, 'msg': '运行频率参数错误'}))
                return

            start_dt = _parse_datetime(start_at) if start_at else datetime.datetime.now()
            if start_dt is None:
                self.write(json.dumps({'code': -1, 'msg': '开始时间格式错误'}))
                return

            from quantia.paper_trading.paper_engine import _ensure_paper_table
            _ensure_paper_table()
            _ensure_backtest_table_if_available()

            backtest_id = _resolve_backtest_id(strategy_id, requested_backtest_id)
            if backtest_id is None:
                self.write(json.dumps({'code': -1, 'msg': '该策略暂无已完成回测，请先运行一次组合回测'}))
                return

            with mdb.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        'INSERT INTO cn_stock_paper_trading '
                        '(strategy_id, backtest_id, name, initial_cash, current_cash, '
                        'current_value, status, run_frequency, start_at) '
                        'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
                        (strategy_id, backtest_id, name or f'模拟盘-{strategy_id}',
                         initial_cash, initial_cash, initial_cash, 'running',
                         run_frequency, start_dt))
                    cur.execute('SELECT LAST_INSERT_ID()')
                    row = cur.fetchone()
                    paper_id = row[0] if row is not None else None

            if paper_id is None:
                self.write(json.dumps({'code': -1, 'msg': '创建模拟盘失败'}))
                return
            self.write(json.dumps({'code': 0, 'data': {'id': paper_id, 'backtest_id': backtest_id}}, ensure_ascii=False))
        except Exception as e:
            mdb._invalidate_shared_conn()  # 废弃可能损坏的连接
            logging.error("CreatePaperTrading异常", exc_info=True)
            self.write(json.dumps({'code': -1, 'msg': str(e)}))


def _parse_datetime(value):
    """Parse frontend datetime/date strings into datetime, returning None on invalid input."""
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.date):
        return datetime.datetime.combine(value, datetime.time.min)
    if not value:
        return None
    text = str(value).strip()
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
        try:
            parsed = datetime.datetime.strptime(text[:19] if 'T' in text else text, fmt)
            return parsed
        except ValueError:
            continue
    return None


def _parse_optional_int(value):
    if value is None or value == '':
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_initial_cash(value):
    try:
        initial_cash = float(value)
    except (TypeError, ValueError):
        return None
    return initial_cash if initial_cash >= 10000 else None


def _paper_has_started(last_run_date=None, nav_count=0, trade_count=0):
    return bool(last_run_date or (nav_count or 0) > 0 or (trade_count or 0) > 0)


def _build_paper_update_fields(body, can_update_initial_cash):
    fields = []
    params = []

    if 'name' in body:
        name = str(body.get('name') or '').strip()
        if not name:
            return None, None, '模拟盘名称不能为空'
        fields.append('name=%s')
        params.append(name[:100])

    if 'run_frequency' in body:
        run_frequency = body.get('run_frequency')
        if run_frequency not in _RUN_FREQUENCIES:
            return None, None, '运行频率参数错误'
        fields.append('run_frequency=%s')
        params.append(run_frequency)

    if 'start_at' in body:
        start_dt = _parse_datetime(body.get('start_at'))
        if start_dt is None:
            return None, None, '开始时间格式错误'
        fields.append('start_at=%s')
        params.append(start_dt)

    if 'initial_cash' in body:
        if not can_update_initial_cash:
            return None, None, '模拟盘已开始运行，不能修改初始资金'
        initial_cash = _parse_initial_cash(body.get('initial_cash'))
        if initial_cash is None:
            return None, None, '初始资金不能低于 10000'
        fields.extend(['initial_cash=%s', 'current_cash=%s', 'current_value=%s'])
        params.extend([initial_cash, initial_cash, initial_cash])

    if not fields:
        return None, None, '没有可更新的字段'
    return fields, params, None


def _json_int(value):
    return int(value) if value is not None else None


def _normalize_benchmark_code(code):
    text = str(code or '000300').strip().upper()
    if '.' in text:
        text = text.split('.', 1)[0]
    if len(text) > 6 and text[:6].isdigit():
        text = text[:6]
    return text or '000300'


def _get_benchmark_name(code):
    clean_code = _normalize_benchmark_code(code)
    return _BENCHMARK_NAME_MAP.get(clean_code, clean_code)


def _get_benchmark_return_label(code):
    name = _get_benchmark_name(code)
    return f'基准收益（{name}）' if name else '基准收益'


def _resolve_backtest_id(strategy_id, requested_backtest_id=None):
    strategy_id = _parse_optional_int(strategy_id)
    if strategy_id is None:
        return None

    if requested_backtest_id is not None:
        rows = mdb.executeSqlFetch(
            'SELECT id FROM cn_stock_backtest_portfolio '
            'WHERE id=%s AND strategy_id=%s AND status=%s',
            (requested_backtest_id, strategy_id, 'completed'))
        return int(rows[0][0]) if rows else None

    rows = mdb.executeSqlFetch(
        'SELECT id FROM cn_stock_backtest_portfolio '
        'WHERE strategy_id=%s AND status=%s '
        'ORDER BY completed_at DESC, id DESC LIMIT 1',
        (strategy_id, 'completed'))
    return int(rows[0][0]) if rows else None


def _ensure_backtest_table_if_available():
    try:
        from quantia.web.portfolioBacktestHandler import _ensure_backtest_table
        _ensure_backtest_table()
    except Exception:
        logging.debug("确保组合回测表存在失败", exc_info=True)


def _get_stock_name_map(codes):
    clean_codes = sorted({str(code).strip() for code in codes if str(code or '').strip()})
    if not clean_codes:
        return {}
    try:
        import quantia.core.tablestructure as tbs
        table = tbs.TABLE_CN_STOCK_SPOT['name']
        if not mdb.checkTableIsExist(table):
            return {}
        lookup_codes = sorted(set(clean_codes + [code[:6] for code in clean_codes if len(code) >= 6]))
        placeholders = ','.join(['%s'] * len(lookup_codes))
        rows = mdb.executeSqlFetch(
            f'SELECT code, name FROM `{table}` WHERE code IN ({placeholders})',
            tuple(lookup_codes))
        result = {}
        for row in rows or []:
            code = str(row.get('code') if isinstance(row, dict) else row[0]).strip()
            name = str((row.get('name') if isinstance(row, dict) else row[1]) or '').strip()
            if code and name:
                result[code] = name
                if len(code) >= 6:
                    result[code[:6]] = name
        return result
    except Exception:
        logging.debug("查询股票名称失败", exc_info=True)
        return {}


def _date_text(value):
    if value is None:
        return ''
    if hasattr(value, 'strftime'):
        return value.strftime('%Y-%m-%d')
    text = str(value).strip()
    return text[:10]


def _build_benchmark_values(benchmark_code, date_values, base_date=None):
    dates = [_date_text(value) for value in date_values]
    dates = [value for value in dates if value]
    if not dates:
        return {}
    start_date = _date_text(base_date) or min(dates)
    end_date = max(dates)
    try:
        from quantia.core.backtest.data_feed import load_benchmark_data
        df = load_benchmark_data(benchmark_code or '000300', start_date, end_date)
        if df is None or len(df) == 0:
            return {}
        df = df.copy()
        df['date_key'] = df['date'].apply(_date_text)
        df = df.sort_values('date_key')
        base_rows = df[df['date_key'] >= start_date]
        if len(base_rows) == 0:
            return {}
        base_price = float(base_rows.iloc[0]['close'])
        if base_price <= 0:
            return {}
        result = {}
        for date_key in dates:
            rows = df[df['date_key'] <= date_key]
            if len(rows) > 0:
                result[date_key] = round(float(rows.iloc[-1]['close']) / base_price, 6)
        return result
    except Exception:
        logging.debug("模拟盘基准曲线补算失败", exc_info=True)
        return {}


def _should_rebuild_benchmark_values(values):
    clean_values = []
    for value in values or []:
        try:
            clean_values.append(float(value or 1))
        except (TypeError, ValueError):
            clean_values.append(1.0)
    if not clean_values:
        return True
    return all(abs(value - 1.0) < 1e-9 for value in clean_values)


def _latest_nav_snapshot(nav_rows):
    if not nav_rows:
        return None
    row = nav_rows[-1]
    if len(row) < 2 or row[1] is None:
        return None
    return {
        'date': _date_text(row[0]),
        'total_value': float(row[1] or 0),
        'cash': float(row[2] or 0) if len(row) >= 3 else None,
        'position_value': float(row[3] or 0) if len(row) >= 4 else None,
    }


def _apply_nav_snapshot(info, snapshot):
    if not snapshot:
        return info
    initial = float(info.get('initial_cash') or 0)
    total_value = float(snapshot.get('total_value') or 0)
    info['current_value'] = total_value
    if snapshot.get('cash') is not None:
        info['current_cash'] = float(snapshot.get('cash') or 0)
    if snapshot.get('position_value') is not None:
        info['position_value'] = float(snapshot.get('position_value') or 0)
    info['current_value_date'] = snapshot.get('date') or ''
    info['profit_rate'] = round((total_value / initial - 1) * 100, 2) if initial > 0 else 0
    return info


class PaperTradingActionHandler(webBase.BaseHandler, ABC):
    """暂停/恢复/停止模拟盘"""

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body)
            paper_id = body.get('id')
            action = body.get('action')  # pause / resume / stop

            if not paper_id or action not in ('pause', 'resume', 'stop'):
                self.write(json.dumps({'code': -1, 'msg': '参数错误'}))
                return

            status_map = {'pause': 'paused', 'resume': 'running', 'stop': 'stopped'}
            new_status = status_map[action]

            mdb.executeSql(
                'UPDATE cn_stock_paper_trading SET status=%s WHERE id=%s',
                (new_status, paper_id))

            self.write(json.dumps({'code': 0}))
        except Exception as e:
            self.write(json.dumps({'code': -1, 'msg': str(e)}))


class UpdatePaperTradingHandler(webBase.BaseHandler, ABC):
    """更新模拟盘设置"""

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body)
            paper_id = body.get('id')
            if not paper_id:
                self.write(json.dumps({'code': -1, 'msg': '缺少 id'}, ensure_ascii=False))
                return

            from quantia.paper_trading.paper_engine import _ensure_paper_table
            _ensure_paper_table()

            rows = mdb.executeSqlFetch(
                'SELECT last_run_date FROM cn_stock_paper_trading WHERE id=%s',
                (paper_id,))
            if not rows:
                self.write(json.dumps({'code': -1, 'msg': '模拟盘不存在'}, ensure_ascii=False))
                return

            nav_count = 0
            if mdb.checkTableIsExist('cn_stock_paper_nav'):
                count_rows = mdb.executeSqlFetch(
                    'SELECT COUNT(1) FROM cn_stock_paper_nav WHERE paper_id=%s',
                    (paper_id,))
                nav_count = int(count_rows[0][0] or 0) if count_rows else 0

            trade_count = 0
            if mdb.checkTableIsExist('cn_stock_backtest_trade'):
                count_rows = mdb.executeSqlFetch(
                    'SELECT COUNT(1) FROM cn_stock_backtest_trade WHERE paper_id=%s',
                    (paper_id,))
                trade_count = int(count_rows[0][0] or 0) if count_rows else 0

            has_started = _paper_has_started(rows[0][0], nav_count, trade_count)
            fields, params, error_msg = _build_paper_update_fields(body, not has_started)
            if error_msg:
                self.write(json.dumps({'code': -1, 'msg': error_msg}, ensure_ascii=False))
                return

            params.append(paper_id)
            mdb.executeSql(
                f"UPDATE cn_stock_paper_trading SET {', '.join(fields)} WHERE id=%s",
                tuple(params))

            self.write(json.dumps({'code': 0}, ensure_ascii=False))
        except Exception as e:
            mdb._invalidate_shared_conn()
            logging.error("UpdatePaperTrading异常", exc_info=True)
            self.write(json.dumps({'code': -1, 'msg': str(e)}, ensure_ascii=False))


class GetPaperTradingListHandler(webBase.BaseHandler, ABC):
    """获取模拟盘列表"""

    @gen.coroutine
    def get(self):
        try:
            from quantia.paper_trading.paper_engine import _ensure_paper_table
            _ensure_paper_table()
            _ensure_backtest_table_if_available()

            rows = mdb.executeSqlFetch(
                'SELECT pt.id, sc.name as strategy_name, pt.name, '
                'pt.initial_cash, pt.current_cash, pt.current_value, '
                'pt.status, pt.started_at, pt.last_run_date, '
                'pt.run_frequency, pt.start_at, pt.backtest_id, '
                'bp.total_return, bp.strategy_name as backtest_name '
                'FROM cn_stock_paper_trading pt '
                'LEFT JOIN cn_stock_strategy_code sc ON pt.strategy_id = sc.id '
                'LEFT JOIN cn_stock_backtest_portfolio bp ON pt.backtest_id = bp.id '
                'ORDER BY pt.id DESC LIMIT 50')

            data = []
            if rows:
                # 批量获取所有模拟盘的 NAV 数据，用于计算年化收益、最大回撤、今日收益
                paper_ids = [r[0] for r in rows]
                nav_map = {}  # paper_id -> [(date, total_value, cash, position_value), ...]
                if mdb.checkTableIsExist('cn_stock_paper_nav') and paper_ids:
                    placeholders = ','.join(['%s'] * len(paper_ids))
                    nav_rows = mdb.executeSqlFetch(
                        f'SELECT paper_id, date, total_value, cash, position_value '
                        f'FROM cn_stock_paper_nav '
                        f'WHERE paper_id IN ({placeholders}) '
                        f'ORDER BY paper_id, date ASC', tuple(paper_ids))
                    if nav_rows:
                        for nr in nav_rows:
                            nav_map.setdefault(nr[0], []).append(nr[1:])

                for r in rows:
                    initial = float(r[3]) if r[3] else 1000000
                    current = float(r[5]) if r[5] else initial
                    current_cash = float(r[4]) if r[4] else initial

                    # 从 NAV 序列计算年化收益、最大回撤、今日收益
                    annual_return = 0
                    max_drawdown = 0
                    today_return = 0
                    nav_list = nav_map.get(r[0], [])
                    latest_snapshot = _latest_nav_snapshot(nav_list)
                    if latest_snapshot:
                        current = latest_snapshot['total_value']
                        current_cash = latest_snapshot['cash'] if latest_snapshot['cash'] is not None else current_cash
                    profit_rate = (current / initial - 1) * 100 if initial > 0 else 0
                    if len(nav_list) >= 2:
                        first_val = float(nav_list[0][1] or 0)
                        last_val = float(nav_list[-1][1] or 0)
                        first_date = nav_list[0][0]
                        last_date = nav_list[-1][0]
                        days = (last_date - first_date).days if hasattr(first_date, '__sub__') else 0

                        # 年化收益
                        if days > 0 and initial > 0:
                            ann_factor = 365.0 / days
                            annual_return = round(((last_val / initial) ** ann_factor - 1) * 100, 2)

                        # 最大回撤
                        peak = initial if initial > 0 else first_val
                        for nav_row in nav_list:
                            v = float(nav_row[1] or 0)
                            if v > peak:
                                peak = v
                            dd = (peak - v) / peak * 100 if peak > 0 else 0
                            if dd > max_drawdown:
                                max_drawdown = dd
                        max_drawdown = round(max_drawdown, 2)

                        # 今日收益（最近两个 NAV 的变化率）
                        prev_val = float(nav_list[-2][1] or 0)
                        if prev_val > 0:
                            today_return = round((last_val / prev_val - 1) * 100, 2)

                    data.append({
                        'id': r[0],
                        'strategy_name': r[1] or '未知策略',
                        'name': r[2] or f'模拟盘-{r[0]}',
                        'initial_cash': initial,
                        'current_cash': current_cash,
                        'current_value': current,
                        'profit_rate': round(profit_rate, 2),
                        'annual_return': annual_return,
                        'max_drawdown': max_drawdown,
                        'today_return': today_return,
                        'status': r[6],
                        'started_at': r[7].strftime('%Y-%m-%d') if r[7] else '',
                        'last_run_date': str(r[8]) if r[8] else '未运行',
                        'run_frequency': r[9] or 'daily',
                        'start_at': r[10].strftime('%Y-%m-%d %H:%M:%S') if r[10] else '',
                        'backtest_id': _json_int(r[11]),
                        'backtest_return': float(r[12]) if r[12] is not None else None,
                        'backtest_name': r[13] or '',
                    })
            self.write(json.dumps({'code': 0, 'data': data}, ensure_ascii=False))
        except Exception as e:
            self.write(json.dumps({'code': -1, 'msg': str(e)}))


def _compute_paper_metrics(nav_rows, trade_rows, initial_cash=None):
    """
    从 NAV 序列和交易记录计算模拟盘绩效指标。

    Args:
        nav_rows: [(date, total_value, cash, position_value), ...]  按日期升序
        trade_rows: [(date, code, direction, price, amount, value, commission, tax), ...] 或
                    [(date, code, name, direction, price, amount, value, commission, tax), ...]

    Returns:
        dict 绩效指标
    """
    metrics = {
        'total_return': 0, 'annual_return': 0, 'max_drawdown': 0,
        'sharpe_ratio': 0, 'sortino_ratio': 0, 'win_rate': 0,
        'profit_loss_ratio': 0, 'trade_count': 0, 'running_days': 0,
        'today_return': 0, 'benchmark_return': 0, 'excess_return': 0,
    }

    if not nav_rows or len(nav_rows) < 2:
        return metrics

    values = [float(r[1]) for r in nav_rows]
    try:
        initial = float(initial_cash) if initial_cash else values[0]
    except (TypeError, ValueError):
        initial = values[0]
    final = values[-1]
    metrics['total_return'] = round((final / initial - 1) * 100, 2) if initial > 0 else 0

    if len(nav_rows[0]) >= 5:
        benchmarks = [float(r[4] or 1) for r in nav_rows]
        bm_final = benchmarks[-1] or 1
        metrics['benchmark_return'] = round((bm_final - 1) * 100, 2)
        metrics['excess_return'] = round(metrics['total_return'] - metrics['benchmark_return'], 2)

    first_date = nav_rows[0][0]
    last_date = nav_rows[-1][0]
    days = (last_date - first_date).days if hasattr(first_date, '__sub__') else 0
    metrics['running_days'] = days
    if days > 0 and initial > 0:
        ann_factor = 365.0 / days
        metrics['annual_return'] = round(((final / initial) ** ann_factor - 1) * 100, 2)

    # 最大回撤：以初始资金作为生命周期基准，避免第一条 NAV 已亏损时低估回撤。
    peak = initial if initial > 0 else values[0]
    max_dd = 0
    for v in values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    metrics['max_drawdown'] = round(max_dd, 2)

    # 今日收益（最近两个 NAV 的变化率）
    prev_val = values[-2]
    if prev_val > 0:
        metrics['today_return'] = round((final / prev_val - 1) * 100, 2)

    # 日收益率
    daily_returns = []
    for i in range(1, len(values)):
        if values[i - 1] > 0:
            daily_returns.append(values[i] / values[i - 1] - 1)

    # 夏普比率
    if len(daily_returns) >= 5:
        rf_daily = 0.03 / 252
        mean_r = sum(daily_returns) / len(daily_returns)
        std_r = (sum((r - mean_r) ** 2 for r in daily_returns) / len(daily_returns)) ** 0.5
        if std_r > 0:
            metrics['sharpe_ratio'] = round((mean_r - rf_daily) / std_r * (252 ** 0.5), 2)
        downside = [r for r in daily_returns if r < rf_daily]
        if len(downside) >= 2:
            down_std = (sum((r - rf_daily) ** 2 for r in downside) / len(downside)) ** 0.5
            if down_std > 0:
                metrics['sortino_ratio'] = round((mean_r - rf_daily) / down_std * (252 ** 0.5), 2)

    # 胜率 & 盈亏比
    if trade_rows:
        metrics['trade_count'] = len(trade_rows)
        buys = {}
        wins = 0
        losses = 0
        total_profit = 0
        total_loss = 0
        for t in trade_rows:
            # 兼容两种元组格式
            if len(t) >= 9:
                code, direction, price, amount = t[1], t[3], float(t[4]), int(t[5])
            else:
                code, direction, price, amount = t[1], t[2], float(t[3]), int(t[4])
            if direction == 'buy':
                buys.setdefault(code, []).append((price, amount))
            elif direction == 'sell' and code in buys and buys[code]:
                buy_price = buys[code][0][0]
                pnl = (price - buy_price) * amount
                if pnl >= 0:
                    wins += 1
                    total_profit += pnl
                else:
                    losses += 1
                    total_loss += abs(pnl)
                buys[code].pop(0)
        total_trades = wins + losses
        if total_trades > 0:
            metrics['win_rate'] = round(wins / total_trades * 100, 1)
        if losses > 0 and total_loss > 0:
            avg_win = total_profit / wins if wins > 0 else 0
            avg_loss = total_loss / losses
            metrics['profit_loss_ratio'] = round(avg_win / avg_loss, 2) if avg_loss > 0 else 0

    return metrics


class GetPaperTradingDetailHandler(webBase.BaseHandler, ABC):
    """获取模拟盘详情（含持仓、交易、NAV 曲线和绩效指标）"""

    @gen.coroutine
    def get(self):
        try:
            paper_id = self.get_argument('id', None)
            pos_date = self.get_argument('pos_date', None)
            benchmark_start_mode = self.get_argument('benchmark_start_mode', 'paper_start')
            if benchmark_start_mode not in ('paper_start', 'first_trade'):
                benchmark_start_mode = 'paper_start'
            if not paper_id:
                self.write(json.dumps({'code': -1, 'msg': '缺少 id'}))
                return

            _ensure_backtest_table_if_available()

            rows = mdb.executeSqlFetch(
                'SELECT pt.id, sc.name, pt.name, pt.initial_cash, '
                'pt.current_cash, pt.current_value, pt.status, '
                'pt.started_at, pt.last_run_date, pt.run_frequency, '
                'pt.start_at, pt.backtest_id, bp.total_return, '
                'bp.strategy_name as backtest_name, bp.benchmark, '
                'pt.strategy_id '
                'FROM cn_stock_paper_trading pt '
                'LEFT JOIN cn_stock_strategy_code sc ON pt.strategy_id = sc.id '
                'LEFT JOIN cn_stock_backtest_portfolio bp ON pt.backtest_id = bp.id '
                'WHERE pt.id = %s', (paper_id,))

            if not rows:
                self.write(json.dumps({'code': -1, 'msg': '模拟盘不存在'}))
                return

            r = rows[0]
            initial = float(r[3]) if r[3] else 1000000
            current = float(r[5]) if r[5] else initial
            benchmark_code = _normalize_benchmark_code(r[14] or '000300')
            paper_start_date = r[10] or r[7]

            info = {
                'id': r[0],
                'strategy_name': r[1] or '未知',
                'name': r[2],
                'initial_cash': initial,
                'current_cash': float(r[4]) if r[4] else initial,
                'current_value': current,
                'profit_rate': round((current / initial - 1) * 100, 2) if initial > 0 else 0,
                'status': r[6],
                'started_at': r[7].strftime('%Y-%m-%d') if r[7] else '',
                'last_run_date': str(r[8]) if r[8] else '',
                'run_frequency': r[9] or 'daily',
                'start_at': r[10].strftime('%Y-%m-%d %H:%M:%S') if r[10] else '',
                'backtest_id': _json_int(r[11]),
                'backtest_return': float(r[12]) if r[12] is not None else None,
                'backtest_name': r[13] or '',
                'benchmark_code': benchmark_code,
                'benchmark_name': _get_benchmark_name(benchmark_code),
                'benchmark_return_label': _get_benchmark_return_label(benchmark_code),
                'benchmark_start_mode': benchmark_start_mode,
                'benchmark_start_mode_label': '首次成交' if benchmark_start_mode == 'first_trade' else '模拟开始',
                'benchmark_start_date': '',
                'first_trade_date': '',
                'strategy_id': _json_int(r[15]),
            }

            # 当前持仓（支持按日期查询历史持仓）
            positions = []
            if mdb.checkTableIsExist('cn_stock_backtest_position'):
                position_date = pos_date
                if not position_date:
                    latest_rows = mdb.executeSqlFetch(
                        'SELECT MAX(date) FROM cn_stock_backtest_position WHERE paper_id = %s',
                        (paper_id,))
                    position_date = str(latest_rows[0][0]) if latest_rows and latest_rows[0] and latest_rows[0][0] else None
                if position_date:
                    pos_rows = mdb.executeSqlFetch(
                        'SELECT p.code, p.name, p.amount, p.avg_cost, p.close_price, '
                        'p.market_value, p.profit, p.profit_rate, p.weight '
                        'FROM cn_stock_backtest_position p '
                        'INNER JOIN ('
                        '  SELECT code, MAX(id) AS id '
                        '  FROM cn_stock_backtest_position '
                        '  WHERE paper_id = %s AND date = %s '
                        '  GROUP BY code'
                        ') latest ON latest.id = p.id '
                        'ORDER BY p.market_value DESC', (paper_id, position_date))
                else:
                    pos_rows = []
                if pos_rows:
                    stock_name_map = _get_stock_name_map([p[0] for p in pos_rows])
                    for p in pos_rows:
                        code = str(p[0] or '').strip()
                        name = (p[1] or stock_name_map.get(code) or '')
                        positions.append({
                            'code': code, 'name': name,
                            'amount': p[2],
                            'avg_cost': float(p[3]) if p[3] else 0,
                            'price': float(p[4]) if p[4] else 0,
                            'value': float(p[5]) if p[5] else 0,
                            'profit': float(p[6]) if p[6] else 0,
                            'profit_rate': round(float(p[7]) * 100, 2) if p[7] else 0,
                            'weight': round(float(p[8]), 2) if p[8] else 0,
                        })

            # 最近交易
            # Phase 3 扩展：LEFT JOIN cn_stock_trade_signal 拉出策略真实理由 / 决策来源 / AI 评分摘要 /
            # signal_id（前端用于点击查看完整决策），让 paper-trading 详情页与 backtest-detail 行为一致。
            trades = []
            trade_rows_raw = []
            first_trade_date = ''
            if mdb.checkTableIsExist('cn_stock_backtest_trade'):
                _has_signal_tbl = False
                try:
                    _has_signal_tbl = bool(mdb.checkTableIsExist('cn_stock_trade_signal'))
                except Exception:
                    _has_signal_tbl = False
                if _has_signal_tbl:
                    trade_rows_raw = mdb.executeSqlFetch(
                        'SELECT t.date, t.code, t.name, t.direction, t.price, t.amount, t.value, '
                        '       t.commission, t.tax, t.id, '
                        '       s.id, s.reason, s.reason_source, s.ai_score, s.ai_action, s.ai_gate_result, '
                        '       t.close_profit, t.return_rate, t.slippage_cost, '
                        '       t.reason, t.reason_source '
                        'FROM cn_stock_backtest_trade t '
                        'LEFT JOIN cn_stock_trade_signal s '
                        '       ON s.trade_id = t.id AND s.source_type = %s AND s.source_id = %s '
                        'WHERE t.paper_id = %s '
                        'ORDER BY t.date DESC, t.id DESC LIMIT 200',
                        ('paper', paper_id, paper_id))
                else:
                    trade_rows_raw = mdb.executeSqlFetch(
                        'SELECT date, code, name, direction, price, amount, value, commission, tax, id, '
                        '       close_profit, return_rate, slippage_cost, reason, reason_source '
                        'FROM cn_stock_backtest_trade '
                        'WHERE paper_id = %s ORDER BY date DESC, id DESC LIMIT 200',
                        (paper_id,))
                if trade_rows_raw:
                    stock_name_map = _get_stock_name_map([t[1] for t in trade_rows_raw])
                    for t in trade_rows_raw:
                        code = str(t[1] or '').strip()
                        name = (t[2] or stock_name_map.get(code) or '')
                        item = {
                            'date': str(t[0]) if t[0] else '',
                            'code': code, 'name': name,
                            'direction': t[3],
                            'price': float(t[4]) if t[4] else 0,
                            'amount': t[5],
                            'value': float(t[6]) if t[6] else 0,
                            'commission': float(t[7]) if t[7] else 0,
                            'tax': float(t[8]) if t[8] else 0,
                            'trade_id': int(t[9]) if t[9] is not None else None,
                        }
                        if _has_signal_tbl and len(t) >= 21:
                            # 优先使用 trade 表的 reason / reason_source（撮合阶段写入，
                            # 反映 derived/strategy/generated 的真实来源）；trade 表为空才回退
                            # 到 signal.reason（向后兼容旧数据）。
                            t_reason = (t[19] or '').strip()
                            t_source = (t[20] or '').strip()
                            s_reason = (t[11] or '').strip()
                            s_source = (t[12] or '').strip()
                            final_reason = t_reason or s_reason
                            final_source = t_source or s_source
                            item.update({
                                'signal_id': int(t[10]) if t[10] is not None else None,
                                'reason': final_reason,
                                'reason_source': final_source,
                                'ai_score': float(t[13]) if t[13] is not None else None,
                                'ai_action': t[14] or '',
                                'ai_gate_result': t[15] or '',
                                'close_profit': float(t[16]) if t[16] is not None else None,
                                'return_rate': float(t[17]) if t[17] is not None else None,
                                'slippage_cost': float(t[18]) if t[18] is not None else None,
                            })
                        elif (not _has_signal_tbl) and len(t) >= 15:
                            item.update({
                                'close_profit': float(t[10]) if t[10] is not None else None,
                                'return_rate': float(t[11]) if t[11] is not None else None,
                                'slippage_cost': float(t[12]) if t[12] is not None else None,
                                'reason': t[13] or '',
                                'reason_source': t[14] or '',
                            })
                        trades.append(item)
                    trade_dates = [_date_text(t[0]) for t in trade_rows_raw]
                    trade_dates = [value for value in trade_dates if value]
                    first_trade_date = min(trade_dates) if trade_dates else ''

            effective_start_mode = benchmark_start_mode if benchmark_start_mode != 'first_trade' or first_trade_date else 'paper_start'
            benchmark_base_date = first_trade_date if effective_start_mode == 'first_trade' else paper_start_date
            benchmark_start_date = _date_text(benchmark_base_date)
            info.update({
                'benchmark_start_mode': effective_start_mode,
                'benchmark_start_mode_label': '首次成交' if effective_start_mode == 'first_trade' else '模拟开始',
                'benchmark_start_date': benchmark_start_date,
                'first_trade_date': first_trade_date,
            })

            # NAV 曲线
            nav = []
            nav_rows_raw = []
            daily_benchmark_by_date = {}
            if mdb.checkTableIsExist('cn_stock_paper_nav'):
                benchmark_cols = mdb.executeSqlFetch(
                    "SHOW COLUMNS FROM cn_stock_paper_nav LIKE 'benchmark_value'")
                benchmark_expr = 'benchmark_value' if benchmark_cols else '1.0 AS benchmark_value'
                nav_rows_raw = mdb.executeSqlFetch(
                    f'SELECT date, total_value, cash, position_value, {benchmark_expr} '
                    'FROM cn_stock_paper_nav '
                    'WHERE paper_id = %s ORDER BY date ASC', (paper_id,))
                if nav_rows_raw:
                    raw_benchmark_values = [n[4] if len(n) >= 5 else 1 for n in nav_rows_raw]
                    rebuilt_benchmark = {}
                    if effective_start_mode == 'first_trade' or (not benchmark_cols) or _should_rebuild_benchmark_values(raw_benchmark_values):
                        rebuilt_benchmark = _build_benchmark_values(
                            benchmark_code, [n[0] for n in nav_rows_raw], benchmark_base_date)
                    enriched_nav_rows = []
                    display_strategy_base = None
                    for n in nav_rows_raw:
                        total_value = float(n[1]) if n[1] else 0
                        date_key = _date_text(n[0])
                        stored_benchmark = float(n[4]) if len(n) >= 5 and n[4] else 1
                        benchmark_value = rebuilt_benchmark.get(date_key, stored_benchmark) if date_key else stored_benchmark
                        if date_key:
                            daily_benchmark_by_date[date_key] = benchmark_value
                        enriched_nav_rows.append((n[0], n[1], n[2], n[3], benchmark_value))
                        if effective_start_mode == 'first_trade' and benchmark_start_date and date_key < benchmark_start_date:
                            continue
                        if effective_start_mode == 'first_trade':
                            display_strategy_base = display_strategy_base or total_value or initial
                            strategy_base = display_strategy_base
                        else:
                            strategy_base = initial
                        strategy_return = round((total_value / strategy_base - 1) * 100, 2) if strategy_base > 0 else 0
                        benchmark_return = round((benchmark_value - 1) * 100, 2)
                        nav.append({
                            'date': str(n[0]) if n[0] else '',
                            'total_value': total_value,
                            'cash': float(n[2]) if n[2] else 0,
                            'position_value': float(n[3]) if n[3] else 0,
                            'benchmark_value': benchmark_value,
                            'strategy_return': strategy_return,
                            'benchmark_return': benchmark_return,
                            'excess_return': round(strategy_return - benchmark_return, 2),
                        })
                    nav_rows_raw = enriched_nav_rows
            if len(nav) < 2 and mdb.checkTableIsExist('cn_stock_paper_nav_intraday'):
                intraday_rows = mdb.executeSqlFetch(
                    'SELECT datetime, total_value, cash, position_value '
                    'FROM cn_stock_paper_nav_intraday '
                    'WHERE paper_id = %s ORDER BY datetime ASC', (paper_id,))
                if intraday_rows and len(intraday_rows) > len(nav):
                    enriched_intraday_rows = []
                    nav = []
                    if not daily_benchmark_by_date:
                        daily_benchmark_by_date = _build_benchmark_values(
                            benchmark_code, [n[0] for n in intraday_rows], benchmark_base_date)
                    display_strategy_base = None
                    for n in intraday_rows:
                        dt_value = n[0]
                        nav_date = str(dt_value.date()) if hasattr(dt_value, 'date') else str(dt_value or '')[:10]
                        total_value = float(n[1]) if n[1] else 0
                        benchmark_value = daily_benchmark_by_date.get(nav_date, 1) or 1
                        enriched_intraday_rows.append((n[0], n[1], n[2], n[3], benchmark_value))
                        if effective_start_mode == 'first_trade' and benchmark_start_date and nav_date < benchmark_start_date:
                            continue
                        if effective_start_mode == 'first_trade':
                            display_strategy_base = display_strategy_base or total_value or initial
                            strategy_base = display_strategy_base
                        else:
                            strategy_base = initial
                        strategy_return = round((total_value / strategy_base - 1) * 100, 2) if strategy_base > 0 else 0
                        benchmark_return = round((benchmark_value - 1) * 100, 2)
                        nav.append({
                            'date': dt_value.strftime('%Y-%m-%d %H:%M:%S') if hasattr(dt_value, 'strftime') else str(dt_value or ''),
                            'total_value': total_value,
                            'cash': float(n[2]) if n[2] else 0,
                            'position_value': float(n[3]) if n[3] else 0,
                            'benchmark_value': benchmark_value,
                            'strategy_return': strategy_return,
                            'benchmark_return': benchmark_return,
                            'excess_return': round(strategy_return - benchmark_return, 2),
                        })
                    nav_rows_raw = enriched_intraday_rows

            # 当前资产展示以最新 NAV 为准，避免主表旧值与收益曲线分叉。
            _apply_nav_snapshot(info, _latest_nav_snapshot(nav_rows_raw))

            # 绩效指标
            metrics = _compute_paper_metrics(nav_rows_raw, trade_rows_raw, initial)
            info.update(metrics)

            # 执行日志
            execution_logs = []
            if mdb.checkTableIsExist('cn_stock_paper_execution_log'):
                elog_rows = mdb.executeSqlFetch(
                    'SELECT trade_date, status, message, trade_count, '
                    'total_value, started_at, finished_at '
                    'FROM cn_stock_paper_execution_log '
                    'WHERE paper_id = %s ORDER BY trade_date DESC, id DESC '
                    'LIMIT 50', (paper_id,))
                if elog_rows:
                    for el in elog_rows:
                        execution_logs.append({
                            'trade_date': str(el[0]) if el[0] else '',
                            'status': el[1] or '',
                            'message': el[2] or '',
                            'trade_count': el[3] or 0,
                            'total_value': float(el[4]) if el[4] else None,
                            'started_at': el[5].strftime('%Y-%m-%d %H:%M:%S') if el[5] else '',
                            'finished_at': el[6].strftime('%Y-%m-%d %H:%M:%S') if el[6] else '',
                        })

            self.write(json.dumps({
                'code': 0,
                'data': {
                    'info': info, 'positions': positions,
                    'trades': trades, 'nav': nav,
                    'execution_logs': execution_logs,
                }
            }, ensure_ascii=False))
        except Exception as e:
            logging.error("GetPaperTradingDetail异常", exc_info=True)
            self.write(json.dumps({'code': -1, 'msg': str(e)}))


class DeletePaperTradingHandler(webBase.BaseHandler, ABC):
    """删除模拟盘及其关联数据"""

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body)
            paper_id = body.get('id')
            if not paper_id:
                self.write(json.dumps({'code': -1, 'msg': '缺少 id'}))
                return

            with mdb.get_connection() as conn:
                with conn.cursor() as cur:
                    if mdb.checkTableIsExist('cn_stock_paper_nav'):
                        cur.execute('DELETE FROM cn_stock_paper_nav WHERE paper_id=%s', (paper_id,))
                    if mdb.checkTableIsExist('cn_stock_backtest_position'):
                        cur.execute('DELETE FROM cn_stock_backtest_position WHERE paper_id=%s', (paper_id,))
                    if mdb.checkTableIsExist('cn_stock_backtest_trade'):
                        cur.execute('DELETE FROM cn_stock_backtest_trade WHERE paper_id=%s', (paper_id,))
                    cur.execute('DELETE FROM cn_stock_paper_trading WHERE id=%s', (paper_id,))
                conn.commit()

            self.write(json.dumps({'code': 0}))
        except Exception as e:
            logging.error("DeletePaperTrading异常", exc_info=True)
            self.write(json.dumps({'code': -1, 'msg': str(e)}))


class RunPaperTradingHandler(webBase.BaseHandler, ABC):
    """手动触发模拟盘执行（测试用）"""

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body)
            paper_id = body.get('id')
            if not paper_id:
                self.write(json.dumps({'code': -1, 'msg': '缺少 id'}))
                return

            from quantia.paper_trading.paper_engine import run_paper_trading_daily
            result = run_paper_trading_daily(paper_id)
            # 执行日志已由 paper_engine 的 finally 块自动记录
            self.write(json.dumps({'code': 0, 'data': result}, ensure_ascii=False, default=str))
        except Exception as e:
            self.write(json.dumps({'code': -1, 'msg': str(e)}))


class GetPaperExecutionLogHandler(webBase.BaseHandler, ABC):
    """查询模拟盘执行日志"""

    @gen.coroutine
    def get(self):
        try:
            paper_id = self.get_argument('id', None)
            limit = int(self.get_argument('limit', '50'))
            limit = min(limit, 200)

            from quantia.paper_trading.scheduler import _ensure_execution_log_table
            _ensure_execution_log_table()

            if paper_id:
                rows = mdb.executeSqlFetch(
                    'SELECT id, paper_id, trade_date, status, message, '
                    'trade_count, total_value, started_at, finished_at '
                    'FROM cn_stock_paper_execution_log '
                    'WHERE paper_id = %s ORDER BY trade_date DESC, id DESC '
                    'LIMIT %s', (paper_id, limit))
            else:
                rows = mdb.executeSqlFetch(
                    'SELECT id, paper_id, trade_date, status, message, '
                    'trade_count, total_value, started_at, finished_at '
                    'FROM cn_stock_paper_execution_log '
                    'ORDER BY trade_date DESC, id DESC LIMIT %s', (limit,))

            data = []
            if rows:
                for r in rows:
                    data.append({
                        'id': r[0],
                        'paper_id': r[1],
                        'trade_date': str(r[2]) if r[2] else '',
                        'status': r[3],
                        'message': r[4] or '',
                        'trade_count': r[5] or 0,
                        'total_value': float(r[6]) if r[6] else None,
                        'started_at': r[7].strftime('%Y-%m-%d %H:%M:%S') if r[7] else '',
                        'finished_at': r[8].strftime('%Y-%m-%d %H:%M:%S') if r[8] else '',
                    })

            self.write(json.dumps({'code': 0, 'data': data}, ensure_ascii=False))
        except Exception as e:
            self.write(json.dumps({'code': -1, 'msg': str(e)}))


class GetPaperCompareHandler(webBase.BaseHandler, ABC):
    """模拟盘多策略对比：NAV 曲线 + 绩效指标"""

    @gen.coroutine
    def get(self):
        try:
            ids_str = self.get_argument('ids', '')
            if not ids_str:
                self.write(json.dumps({'code': -1, 'msg': '缺少 ids 参数'}))
                return

            paper_ids = []
            for s in ids_str.split(','):
                s = s.strip()
                if s.isdigit():
                    paper_ids.append(int(s))
            if len(paper_ids) < 1 or len(paper_ids) > 10:
                self.write(json.dumps({'code': -1, 'msg': 'ids 数量需在 1-10 之间'}))
                return

            from quantia.paper_trading.paper_engine import _ensure_paper_table, _ensure_nav_table
            _ensure_paper_table()
            _ensure_nav_table()
            _ensure_backtest_table_if_available()

            placeholders = ','.join(['%s'] * len(paper_ids))

            info_rows = mdb.executeSqlFetch(
                f'SELECT pt.id, sc.name as strategy_name, pt.name, '
                f'pt.initial_cash, pt.current_value, pt.status, pt.started_at, '
                f'pt.last_run_date, pt.run_frequency, pt.start_at '
                f'FROM cn_stock_paper_trading pt '
                f'LEFT JOIN cn_stock_strategy_code sc ON pt.strategy_id = sc.id '
                f'WHERE pt.id IN ({placeholders})', tuple(paper_ids))

            papers = {}
            if info_rows:
                for r in info_rows:
                    pid = r[0]
                    initial = float(r[3]) if r[3] else 1000000
                    current = float(r[4]) if r[4] else initial
                    papers[pid] = {
                        'id': pid,
                        'strategy_name': r[1] or '未知',
                        'name': r[2] or f'模拟盘-{pid}',
                        'initial_cash': initial,
                        'current_value': current,
                        'profit_rate': round((current / initial - 1) * 100, 2) if initial > 0 else 0,
                        'status': r[5],
                        'started_at': r[6].strftime('%Y-%m-%d') if r[6] else '',
                        'last_run_date': str(r[7]) if r[7] else '',
                        'run_frequency': r[8] or 'daily',
                        'start_at': r[9].strftime('%Y-%m-%d %H:%M:%S') if r[9] else '',
                        'nav': [],
                        'metrics': {},
                    }

            # NAV 曲线 + 绩效指标
            nav_by_paper = {}
            if mdb.checkTableIsExist('cn_stock_paper_nav'):
                nav_rows = mdb.executeSqlFetch(
                    f'SELECT paper_id, date, total_value, cash, position_value '
                    f'FROM cn_stock_paper_nav WHERE paper_id IN ({placeholders}) '
                    f'ORDER BY paper_id, date ASC', tuple(paper_ids))
                if nav_rows:
                    for n in nav_rows:
                        pid = n[0]
                        nav_by_paper.setdefault(pid, []).append(n[1:])
                        if pid in papers:
                            papers[pid]['nav'].append({
                                'date': str(n[1]),
                                'total_value': float(n[2]) if n[2] else 0,
                            })

            trade_by_paper = {}
            if mdb.checkTableIsExist('cn_stock_backtest_trade'):
                trade_rows = mdb.executeSqlFetch(
                    f'SELECT paper_id, date, code, direction, price, amount, value, commission, tax '
                    f'FROM cn_stock_backtest_trade WHERE paper_id IN ({placeholders}) '
                    f'ORDER BY paper_id, date ASC', tuple(paper_ids))
                if trade_rows:
                    for t in trade_rows:
                        trade_by_paper.setdefault(t[0], []).append(t[1:])

            for pid in paper_ids:
                if pid in papers:
                    _apply_nav_snapshot(papers[pid], _latest_nav_snapshot(nav_by_paper.get(pid, [])))
                    papers[pid]['metrics'] = _compute_paper_metrics(
                        nav_by_paper.get(pid, []),
                        trade_by_paper.get(pid, []),
                        papers[pid].get('initial_cash'))

            result = [papers[pid] for pid in paper_ids if pid in papers]
            self.write(json.dumps({'code': 0, 'data': result}, ensure_ascii=False))
        except Exception as e:
            logging.error("GetPaperCompare异常", exc_info=True)
            self.write(json.dumps({'code': -1, 'msg': str(e)}))

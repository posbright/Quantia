#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import datetime
import unittest
from unittest.mock import MagicMock, patch


def _make_conn_ctx(mock_db):
    cursor_ctx = MagicMock()
    cursor_ctx.__enter__.return_value = mock_db
    cursor_ctx.__exit__.return_value = False

    conn = MagicMock()
    conn.cursor.return_value = cursor_ctx

    conn_ctx = MagicMock()
    conn_ctx.__enter__.return_value = conn
    conn_ctx.__exit__.return_value = False
    return conn_ctx


class TestExecuteSqlFetchQueryTimeout(unittest.TestCase):

    @patch('quantia.lib.database.get_connection')
    def test_execute_sql_fetch_without_timeout(self, mock_get_connection):
        from quantia.lib.database import executeSqlFetch

        mock_db = MagicMock()
        mock_db.fetchall.return_value = [(1,)]
        mock_get_connection.return_value = _make_conn_ctx(mock_db)

        result = executeSqlFetch('SELECT 1')

        self.assertEqual(result, [(1,)])
        called_sql = [c.args[0] for c in mock_db.execute.call_args_list]
        self.assertEqual(called_sql, ['SELECT 1'])

    @patch('quantia.lib.database.get_connection')
    def test_execute_sql_fetch_with_mysql_timeout(self, mock_get_connection):
        from quantia.lib.database import executeSqlFetch

        mock_db = MagicMock()
        mock_db.fetchall.return_value = [(1,)]
        mock_get_connection.return_value = _make_conn_ctx(mock_db)

        result = executeSqlFetch('SELECT 1', query_timeout_ms=1500)

        self.assertEqual(result, [(1,)])
        called_sql = [c.args[0] for c in mock_db.execute.call_args_list]
        self.assertIn('SET SESSION MAX_EXECUTION_TIME = %s', called_sql)
        self.assertIn('SELECT 1', called_sql)
        self.assertIn('SET SESSION MAX_EXECUTION_TIME = 0', called_sql)

    @patch('quantia.lib.database.get_connection')
    def test_execute_sql_fetch_timeout_fallback_to_mariadb(self, mock_get_connection):
        from quantia.lib.database import executeSqlFetch

        calls = []

        def execute_side_effect(sql, params=()):
            calls.append((sql, params))
            if sql == 'SET SESSION MAX_EXECUTION_TIME = %s':
                raise Exception('unsupported variable')
            return None

        mock_db = MagicMock()
        mock_db.execute.side_effect = execute_side_effect
        mock_db.fetchall.return_value = [(1,)]
        mock_get_connection.return_value = _make_conn_ctx(mock_db)

        result = executeSqlFetch('SELECT 1', query_timeout_ms=2000)

        self.assertEqual(result, [(1,)])
        called_sql = [sql for sql, _ in calls]
        self.assertIn('SET SESSION max_statement_time = %s', called_sql)
        self.assertIn('SET SESSION max_statement_time = 0', called_sql)


class TestFundamentalsDbTimeoutHook(unittest.TestCase):

    @patch('quantia.lib.database.executeSqlFetch')
    def test_fetch_stock_info_from_db_uses_query_timeout(self, mock_fetch):
        from quantia.core.backtest import fundamentals as fund_mod

        max_date = datetime.date(2026, 6, 10)
        mock_fetch.side_effect = [
            [(max_date,)],
            [('000001', '平安银行', 12.3, 1000000.0, 1.2)],
        ]

        engine = MagicMock()
        engine.context = MagicMock()
        provider = fund_mod.FundamentalDataProvider(engine)

        with patch.object(fund_mod, '_FUND_DB_QUERY_TIMEOUT_MS', 4321):
            provider._fetch_stock_info_from_db()

        self.assertEqual(mock_fetch.call_count, 2)
        self.assertEqual(mock_fetch.call_args_list[0].kwargs.get('query_timeout_ms'), 4321)
        self.assertEqual(mock_fetch.call_args_list[1].kwargs.get('query_timeout_ms'), 4321)


if __name__ == '__main__':
    unittest.main()

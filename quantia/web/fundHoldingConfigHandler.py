#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基金重仓股「全覆盖（方案C）」开关 + 覆盖统计 API Handler。

只读 MySQL + 读写 cn_system_config（普通 MySQL，非外部 API，遵守 Fetch/Analysis/Web 分离）。
开关由 quantia.lib.sysconfig 持久化到 cn_system_config，cron 的 fetch_fund_holding_job
启动时读取该开关决定是否分层分批全量抓取；前端可运行时切换，无需重启/改环境变量。

端点：
- GET  /quantia/api/fund/holding/config   返回当前开关 + 覆盖统计
- POST /quantia/api/fund/holding/config    body {enabled: bool} 切换开关
"""
import datetime
import json
import logging
from abc import ABC

import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
import quantia.lib.sysconfig as sysconfig
import quantia.lib.envconfig as _cfg
import quantia.web.base as webBase
from quantia.job.fetch_fund_holding_job import (
    FULL_COVERAGE_KEY, _count_remaining_full_coverage, _ATTEMPT_TABLE,
)

__author__ = 'Quantia'
__date__ = '2026/06/30'

logger = logging.getLogger(__name__)

_RANK_TABLE = tbs.TABLE_CN_FUND_RANK['name']
_HOLDING_TABLE = tbs.TABLE_CN_FUND_HOLDING['name']
_EQUITY_TYPES = ['股票型', '混合型', '指数型']


def _write_json(handler, data):
    handler.set_header('Content-Type', 'application/json;charset=UTF-8')
    handler.write(json.dumps(data, ensure_ascii=False))


def _coverage_stats():
    """统计权益基金总数、已有持仓数、本周期(本月)已覆盖/已尝试数、剩余、最新更新日。"""
    stats = {
        'total_equity_funds': 0,
        'funds_with_holdings': 0,
        'covered_this_cycle': 0,
        'attempted_this_cycle': 0,
        'remaining_this_cycle': 0,
        'last_update_date': None,
        'batch_per_type': _cfg.get_int('QUANTIA_FUND_HOLDING_BATCH', 1000),
    }
    if not mdb.checkTableIsExist(_RANK_TABLE):
        return stats
    placeholders = ','.join(['%s'] * len(_EQUITY_TYPES))
    cycle_floor = datetime.date.today().replace(day=1)

    rows = mdb.executeSqlFetch(
        f"SELECT COUNT(*) FROM `{_RANK_TABLE}` "
        f"WHERE `date` = (SELECT MAX(`date`) FROM `{_RANK_TABLE}`) "
        f"  AND fund_type IN ({placeholders})", (*_EQUITY_TYPES,))
    stats['total_equity_funds'] = int(rows[0][0]) if rows and rows[0] else 0

    if mdb.checkTableIsExist(_HOLDING_TABLE):
        rows = mdb.executeSqlFetch(
            f"SELECT COUNT(DISTINCT `code`) FROM `{_HOLDING_TABLE}`")
        stats['funds_with_holdings'] = int(rows[0][0]) if rows and rows[0] else 0

        rows = mdb.executeSqlFetch(
            f"SELECT COUNT(DISTINCT `code`) FROM `{_HOLDING_TABLE}` "
            f"WHERE `update_date` >= %s", (cycle_floor,))
        stats['covered_this_cycle'] = int(rows[0][0]) if rows and rows[0] else 0

        rows = mdb.executeSqlFetch(
            f"SELECT MAX(`update_date`) FROM `{_HOLDING_TABLE}`")
        if rows and rows[0] and rows[0][0] is not None:
            d = rows[0][0]
            stats['last_update_date'] = d.isoformat() if hasattr(d, 'isoformat') else str(d)

    if mdb.checkTableIsExist(_ATTEMPT_TABLE):
        rows = mdb.executeSqlFetch(
            f"SELECT COUNT(*) FROM `{_ATTEMPT_TABLE}` WHERE `attempt_date` >= %s", (cycle_floor,))
        stats['attempted_this_cycle'] = int(rows[0][0]) if rows and rows[0] else 0

    # 与 job 同口径：本周期尚未抓且尚未尝试的权益基金数
    stats['remaining_this_cycle'] = _count_remaining_full_coverage(cycle_floor)
    return stats


class FundHoldingConfigHandler(webBase.BaseHandler, ABC):
    """GET/POST /quantia/api/fund/holding/config —— 全覆盖开关 + 覆盖统计。"""

    def get(self):
        try:
            enabled = sysconfig.get_bool(FULL_COVERAGE_KEY, False)
            _write_json(self, {
                'code': 0,
                'data': {
                    'enabled': enabled,
                    'stats': _coverage_stats(),
                },
            })
        except Exception:
            logger.error("基金全覆盖开关查询异常", exc_info=True)
            self.set_status(500)
            _write_json(self, {'code': -1, 'msg': '服务器内部错误'})

    def post(self):
        try:
            body = json.loads(self.request.body) if self.request.body else {}
            enabled = bool(body.get('enabled', False))
            ok = sysconfig.set(FULL_COVERAGE_KEY, enabled)
            if not ok:
                self.set_status(500)
                _write_json(self, {'code': -1, 'msg': '写入开关失败'})
                return
            _write_json(self, {
                'code': 0,
                'msg': '已开启全覆盖（方案C），下次重仓股采集任务将分层分批全量抓取' if enabled
                       else '已关闭全覆盖，恢复默认 Top-N 抓取',
                'data': {
                    'enabled': enabled,
                    'stats': _coverage_stats(),
                },
            })
        except Exception:
            logger.error("基金全覆盖开关设置异常", exc_info=True)
            self.set_status(500)
            _write_json(self, {'code': -1, 'msg': '服务器内部错误'})

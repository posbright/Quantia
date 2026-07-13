#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基金当前申购/赎回状态 API（只读 MySQL）。"""

import datetime
import json
import logging
import math

import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
import quantia.web.base as webBase
from quantia.core.fund import purchase_status

logger = logging.getLogger(__name__)
_TABLE = tbs.TABLE_CN_FUND_PURCHASE_STATUS['name']


def _json_default(value):
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def load_purchase_status(code, as_of=None):
    base = {
        'code': code, 'data_available': False,
        'purchase_status': None, 'redemption_status': None,
        'next_open_date': None, 'min_purchase': None, 'daily_limit': None,
        'fee': None, 'availability': purchase_status.UNKNOWN, 'fetched_at': None,
        'note': '申购状态来自公开基金销售数据，可能随基金公司公告变化，请以下单页面为准。',
    }
    if not mdb.checkTableIsExist(_TABLE):
        return base
    rows = mdb.executeSqlFetch(
        f"SELECT `purchase_status`, `redemption_status`, `next_open_date`, "
        f"`min_purchase`, `daily_limit`, `fee`, `fetched_at` "
        f"FROM `{_TABLE}` WHERE `code` = %s LIMIT 1", (str(code),))
    if not rows:
        return base
    raw, redemption, next_open, minimum, daily_limit, fee, fetched_at = rows[0]
    base.update({
        'data_available': True,
        'purchase_status': raw,
        'redemption_status': redemption,
        'next_open_date': next_open,
        'min_purchase': minimum,
        'daily_limit': daily_limit,
        'fee': fee,
        'availability': purchase_status.classify(
            raw, fetched_at, as_of or datetime.date.today()),
        'fetched_at': fetched_at,
    })
    return base


class FundPurchaseStatusHandler(webBase.BaseHandler):
    def get(self):
        try:
            code = (self.get_argument('code', default='') or '').strip()
            if not code:
                self.set_status(400)
                self.write({'error': '缺少 code 参数'})
                return
            self.set_header('Content-Type', 'application/json;charset=UTF-8')
            self.write(json.dumps(load_purchase_status(code), ensure_ascii=False,
                                  default=_json_default))
        except Exception:
            logger.error('基金申购状态查询异常', exc_info=True)
            self.set_status(500)
            self.write({'error': '服务器内部错误'})
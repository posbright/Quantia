#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T6 穿透式持仓位置 API Handler（P4 选基增量，仅展示参考卡，非硬因子）。

只读（遵守 Fetch/Analysis/Web 分离，规则 1）：
- 读 cn_fund_holding 取基金最新季度前十大重仓股（code/stock_code/hold_ratio/…）。
- 逐重仓股用**本地 K 线缓存**（`load_stock_data(cache_only=True)`，不触发任何外部 API）算
  当前技术位置（距高点回撤 / 长均线位置 / RSI 超卖度），按 hold_ratio 加权得底层位置分。

严格定位（蓝图 §T6）：季报滞后 + 覆盖不足，**不进入 TimingScore**，无覆盖基金返回
`data_available=false`，不造信号；穿透不完整 → covered_ratio 透明化。

端点：GET /quantia/api/fund/look_through?code=000001
"""

import json
import logging
import math
import re

import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
import quantia.web.base as webBase
from quantia.core.backtest.data_feed import load_stock_data
from quantia.core.fund import labels, lookthrough

__author__ = 'Quantia'
__date__ = '2026/07/09'

logger = logging.getLogger(__name__)

_HOLDING_TABLE = tbs.TABLE_CN_FUND_HOLDING['name']
_RANK_TABLE = tbs.TABLE_CN_FUND_RANK['name']

_TOP_N = 10               # 前十大重仓股
_MIN_KLINE = 60           # 个股至少需要的 K 线行数（长均线窗口）
_A_SHARE_RE = re.compile(r'^\d{6}$')   # 仅 A 股 6 位纯数字有本地 K 线


def _json_default(o):
    if isinstance(o, float):
        return None if not math.isfinite(o) else o
    if hasattr(o, 'isoformat'):
        return o.isoformat()
    if hasattr(o, 'item'):
        return o.item()
    return str(o)


def _write_json(handler, data):
    handler.set_header('Content-Type', 'application/json;charset=UTF-8')
    handler.write(json.dumps(data, ensure_ascii=False, default=_json_default))


def _write_error(handler, msg, code=400):
    handler.set_status(code)
    _write_json(handler, {'error': msg})


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(f) else f


def _round(v, nd=1):
    return None if v is None else round(float(v), nd)


class FundLookThroughHandler(webBase.BaseHandler):
    """GET /quantia/api/fund/look_through?code=xxx

    返回 {code, name, fund_type, quarter, data_available, position_score,
          position_label, covered_ratio, scored_count, holdings_count,
          holdings:[{stock_code, stock_name, industry, hold_ratio,
                     position_score, dd, ma, rsi, priced}],
          disclaimer, note}。
    """

    def get(self):
        try:
            code = (self.get_argument('code', default='') or '').strip()
            if not code:
                _write_error(self, '缺少 code 参数')
                return

            base = {
                'code': code, 'name': None, 'fund_type': None, 'quarter': None,
                'data_available': False, 'position_score': None,
                'position_label': None, 'covered_ratio': 0.0,
                'scored_count': 0, 'holdings_count': 0, 'holdings': [],
                'disclaimer': labels.RISK_DISCLAIMER,
                'note': '基于季报前十大重仓股的技术位置估算，季报滞后约一季度、'
                        '穿透不完整（前十大常仅占净值 40–60%），仅作参考、非买卖建议。',
            }

            self._fill_meta(code, base)

            if not mdb.checkTableIsExist(_HOLDING_TABLE):
                _write_json(self, base)
                return

            # 最新季度前十大重仓股（按持仓占比降序）
            rows = mdb.executeSqlFetch(
                f"SELECT `stock_code`, `stock_name`, `industry`, `hold_ratio`, `quarter` "
                f"FROM `{_HOLDING_TABLE}` WHERE `code` = %s AND `quarter` = "
                f"(SELECT MAX(`quarter`) FROM `{_HOLDING_TABLE}` WHERE `code` = %s) "
                f"ORDER BY `hold_ratio` DESC LIMIT {_TOP_N}", (code, code))
            if not rows:
                _write_json(self, base)
                return

            base['quarter'] = rows[0][4]
            base['holdings_count'] = len(rows)

            agg_items = []
            out_holdings = []
            for r in rows:
                stock_code = (r[0] or '').strip()
                hold_ratio = _num(r[3])
                item = {
                    'stock_code': stock_code, 'stock_name': r[1],
                    'industry': r[2], 'hold_ratio': _round(hold_ratio, 2),
                    'position_score': None, 'dd': None, 'ma': None,
                    'rsi': None, 'priced': False,
                }
                pos = self._stock_position(stock_code)
                if pos is not None:
                    item['priced'] = True
                    item['position_score'] = _round(pos['score'])
                    item['dd'] = _round(pos['dd'])
                    item['ma'] = _round(pos['ma'])
                    item['rsi'] = _round(pos['rsi'])
                    agg_items.append({'hold_ratio': hold_ratio, 'score': pos['score']})
                out_holdings.append(item)

            agg = lookthrough.aggregate_positions(agg_items)
            base['holdings'] = out_holdings
            base['scored_count'] = agg['n']
            base['covered_ratio'] = agg['covered_ratio']
            if agg['position_score'] is not None:
                base['data_available'] = True
                base['position_score'] = _round(agg['position_score'])
                base['position_label'] = lookthrough.position_label(agg['position_score'])

            _write_json(self, base)
        except Exception:
            logger.error("穿透式持仓位置查询异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)

    def _fill_meta(self, code, base):
        """填 name / fund_type（缺失不阻断）。"""
        try:
            if mdb.checkTableIsExist(_RANK_TABLE):
                nrows = mdb.executeSqlFetch(
                    f"SELECT `name`, `fund_type` FROM `{_RANK_TABLE}` "
                    f"WHERE `code` = %s ORDER BY `date` DESC LIMIT 1", (code,))
                if nrows and nrows[0]:
                    base['name'] = nrows[0][0]
                    base['fund_type'] = nrows[0][1]
        except Exception:
            logger.warning("读取基金名称/类型失败 code=%s", code, exc_info=True)

    def _stock_position(self, stock_code):
        """读本地 K 线缓存算个股当前位置；非 A 股 / 无缓存 / 样本不足 → None。"""
        if not stock_code or not _A_SHARE_RE.match(stock_code):
            return None
        try:
            df = load_stock_data(stock_code, cache_only=True)
        except Exception:
            logger.warning("加载 K 线失败 stock=%s", stock_code, exc_info=True)
            return None
        if df is None or len(df) < _MIN_KLINE or 'close' not in df.columns:
            return None
        pos = lookthrough.stock_position(df['close'].tolist())
        return pos if pos and pos.get('score') is not None else None

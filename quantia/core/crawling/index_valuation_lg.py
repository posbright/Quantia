#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""乐咕乐股（legulegu）宽基指数估值（PE + 历史分位）薄封装。

akshare 现成的 ``stock_index_pe_lg`` 在本环境已被上游日期格式变更打挂
（上游把 ``date`` 从 ms 时间戳改为 ``YYYY-MM-DD`` 字符串，akshare 仍按
``unit='ms'`` 解析 → ValueError）。这里复用 akshare 内部的 token / CSRF
机制直连同一端点 ``/api/stockdata/index-basic-pe``，并用「自适应日期解析」
拿到自 2005 年至今的**全历史** PE(TTM/LYR) + 历史分位，供 T3 估值分位择时。

属 fetch 管道（仅此处 + stockfetch + fetch_* 可调外部 API）。

支持指数（乐咕乐股口径，12 只宽基）：
    上证50 / 沪深300 / 上证380 / 创业板50 / 中证500 / 上证180 /
    深证红利 / 深证100 / 中证1000 / 上证红利 / 中证100 / 中证800
"""
import logging
import time
from datetime import datetime

import pandas as pd

__author__ = 'Quantia'
__date__ = '2026/07/09'

logger = logging.getLogger(__name__)

# 乐咕乐股指数名 → (纯数字代码, 带交易所后缀的 indexCode)
# 后缀用于请求 legulegu；纯数字代码用于落库主键，与 cn_index_spot 口径一致。
INDEX_SYMBOLS = {
    '上证50':   ('000016', '000016.SH'),
    '沪深300':  ('000300', '000300.SH'),
    '上证380':  ('000009', '000009.SH'),
    '创业板50': ('399673', '399673.SZ'),
    '中证500':  ('000905', '000905.SH'),
    '上证180':  ('000010', '000010.SH'),
    '深证红利': ('399324', '399324.SZ'),
    '深证100':  ('399330', '399330.SZ'),
    '中证1000': ('000852', '000852.SH'),
    '上证红利': ('000015', '000015.SH'),
    '中证100':  ('000903', '000903.SH'),
    '中证800':  ('000906', '000906.SH'),
}

_ENDPOINT = 'https://legulegu.com/api/stockdata/index-basic-pe'
_REFERER = 'https://legulegu.com/stockdata/sz50-ttm-lyr'

_FETCH_MAX_RETRIES = 3
_FETCH_BACKOFF_BASE = 1.5  # 秒


def _legu_token():
    """复用 akshare 内部 JS hash 生成 legulegu 当日 token。"""
    from akshare.stock_feature.stock_a_pe_and_pb import hash_code
    import py_mini_racer
    js = py_mini_racer.MiniRacer()
    js.eval(hash_code)
    return js.call('hex', datetime.now().date().isoformat()).lower()


def fetch_index_valuation(symbol):
    """抓取单只指数的 PE 全历史 + 历史分位，返回规范化 DataFrame。

    列（对齐 tablestructure.TABLE_CN_INDEX_VALUATION）：
        index_code, index_name, date, close, pe_ttm, pe_lyr, pe_ttm_pct, total_mv
    - date：自适应解析（兼容 ms 时间戳与 'YYYY-MM-DD' 字符串两种上游格式）。
    - pe_ttm_pct：滚动 PE 历史分位（0–1，legulegu ``ttmPeQuantile``）。
    失败或无数据 → None。
    """
    if symbol not in INDEX_SYMBOLS:
        raise ValueError(f'不支持的指数: {symbol}（见 INDEX_SYMBOLS）')
    from akshare.stock_feature.stock_a_pe_and_pb import get_cookie_csrf
    import requests

    code, index_code = INDEX_SYMBOLS[symbol]
    last_err = None
    for attempt in range(_FETCH_MAX_RETRIES):
        try:
            token = _legu_token()
            r = requests.get(
                _ENDPOINT,
                params={'token': token, 'indexCode': index_code},
                timeout=30,
                **get_cookie_csrf(url=_REFERER),
            )
            r.raise_for_status()
            payload = r.json()
            rows = payload.get('data') if isinstance(payload, dict) else None
            if not rows:
                logger.warning('index_valuation_lg: %s 返回空数据', symbol)
                return None
            df = pd.DataFrame(rows)
            return _normalize(df, code, symbol)
        except Exception as e:  # noqa: BLE001 — fetch 管道容错重试
            last_err = e
            logger.warning('index_valuation_lg: %s 第 %d 次抓取失败: %s',
                           symbol, attempt + 1, e)
            time.sleep(_FETCH_BACKOFF_BASE ** attempt)
    logger.error('index_valuation_lg: %s 抓取最终失败: %s', symbol, last_err)
    return None


def _normalize(df, code, symbol):
    """把 legulegu 原始列裁剪/改名为落库列，自适应日期解析。"""
    if df is None or df.empty or 'date' not in df.columns:
        return None
    # 自适应日期解析：上游可能是 ms 整数或 'YYYY-MM-DD' 字符串。
    dser = df['date']
    if pd.api.types.is_numeric_dtype(dser):
        parsed = pd.to_datetime(dser, unit='ms', utc=True).dt.tz_convert('Asia/Shanghai')
    else:
        parsed = pd.to_datetime(dser, errors='coerce')
    out = pd.DataFrame({
        'index_code': code,
        'index_name': symbol,
        'date': parsed.dt.date,
        'close': pd.to_numeric(df.get('close'), errors='coerce'),
        'pe_ttm': pd.to_numeric(df.get('ttmPe'), errors='coerce'),
        'pe_lyr': pd.to_numeric(df.get('lyrPe'), errors='coerce'),
        'pe_ttm_pct': pd.to_numeric(df.get('ttmPeQuantile'), errors='coerce'),
        'total_mv': pd.to_numeric(df.get('totalMv'), errors='coerce'),
    })
    out = out[out['date'].notna()].reset_index(drop=True)
    return out if len(out.index) else None

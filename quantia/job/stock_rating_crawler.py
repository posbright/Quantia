#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 4: 机构评级数据爬虫 — 从东方财富获取机构评级/研报评级。

数据来源: 东方财富 机构评级 API (EastMoney)
存储表: cn_stock_institutional_rating

本爬虫属于 Fetch 管道（见 AGENTS.md 规则 1）。

用法::

    python -m quantia.job.stock_rating_crawler --days 30
    python -m quantia.job.stock_rating_crawler --code 000001
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import time
from typing import Any, Dict, List, Optional

import requests

import quantia.lib.database as mdb

_logger = logging.getLogger(__name__)

_RATING_TABLE = 'cn_stock_institutional_rating'
_DB_INSERT_CHUNKSIZE = 500

# 东方财富机构评级 API
_EM_RATING_URL = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json',
    'Referer': 'https://data.eastmoney.com/',
}


def ensure_rating_table():
    """确保机构评级表存在。"""
    if not mdb.checkTableIsExist(_RATING_TABLE):
        mdb.executeSql(f'''
            CREATE TABLE IF NOT EXISTS `{_RATING_TABLE}` (
                `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
                `code` VARCHAR(10) NOT NULL,
                `name` VARCHAR(64) DEFAULT '',
                `rating_date` DATE NOT NULL,
                `institution` VARCHAR(128) NOT NULL COMMENT '评级机构',
                `researcher` VARCHAR(128) DEFAULT '' COMMENT '研究员',
                `rating` VARCHAR(32) NOT NULL COMMENT '评级: 买入/增持/中性/减持/卖出',
                `rating_change` VARCHAR(32) DEFAULT '' COMMENT '评级变动: 上调/维持/下调/首次',
                `target_price_low` DECIMAL(10,2) DEFAULT NULL COMMENT '目标价下限',
                `target_price_high` DECIMAL(10,2) DEFAULT NULL COMMENT '目标价上限',
                `report_title` VARCHAR(500) DEFAULT '' COMMENT '研报标题',
                `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY `uq_code_date_inst` (`code`, `rating_date`, `institution`(64)),
                INDEX `idx_code_date` (`code`, `rating_date`),
                INDEX `idx_rating` (`rating`),
                INDEX `idx_institution` (`institution`(64))
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')


def _normalize_rating(raw: str) -> str:
    """标准化评级名称。"""
    mapping = {
        '买入': '买入', '强烈推荐': '买入', '推荐': '买入',
        '增持': '增持', '谨慎推荐': '增持', '优于大市': '增持',
        '中性': '中性', '持有': '中性', '同步大市': '中性',
        '减持': '减持', '弱于大市': '减持',
        '卖出': '卖出',
    }
    return mapping.get(raw.strip(), raw.strip() or '中性')


def _normalize_rating_change(raw: str) -> str:
    """标准化评级变动。"""
    mapping = {
        '上调': '上调', '调高': '上调',
        '维持': '维持',
        '下调': '下调', '调低': '下调',
        '首次': '首次', '首次覆盖': '首次',
    }
    return mapping.get(raw.strip(), raw.strip() or '维持')


def fetch_institutional_ratings(
    stock_code: Optional[str] = None,
    days: int = 30,
    page_size: int = 50,
    max_pages: int = 5,
) -> List[Dict[str, Any]]:
    """从东方财富获取机构评级数据。

    Args:
        stock_code: 指定股票代码（可选）
        days: 获取最近 N 天
        page_size: 每页条数
        max_pages: 最大页数
    """
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=days)

    results = []

    for page in range(1, max_pages + 1):
        params = {
            'sortColumns': 'RATING_DATE',
            'sortTypes': '-1',
            'pageSize': page_size,
            'pageNumber': page,
            'reportName': 'RPT_CUSTOM_STOCK_RACE',
            'columns': 'ALL',
            'filter': f"(RATING_DATE>='{start_date.isoformat()}')",
        }

        if stock_code:
            params['filter'] += f"(SECURITY_CODE=\"{stock_code}\")"

        try:
            resp = requests.get(
                _EM_RATING_URL, params=params,
                headers=_HEADERS, timeout=15
            )
            if resp.status_code != 200:
                _logger.warning(f'[评级爬虫] HTTP {resp.status_code} page={page}')
                break

            data = resp.json()
            if not data.get('success'):
                _logger.debug(f'[评级爬虫] API 返回失败: {data.get("message", "")}')
                break

            items = (data.get('result') or {}).get('data') or []
            if not items:
                break

            for item in items:
                code = (item.get('SECURITY_CODE') or '').strip()
                if not code or len(code) != 6:
                    continue

                rating_date_str = item.get('RATING_DATE') or ''
                if rating_date_str:
                    try:
                        rating_date = datetime.date.fromisoformat(rating_date_str[:10])
                    except (ValueError, TypeError):
                        rating_date = end_date
                else:
                    rating_date = end_date

                target_low = item.get('SYL_LOW')
                target_high = item.get('SYL_HIGH')

                results.append({
                    'code': code,
                    'name': (item.get('SECURITY_NAME_ABBR') or '').strip(),
                    'rating_date': rating_date,
                    'institution': (item.get('ORG_NAME') or '').strip()[:128],
                    'researcher': (item.get('RESEARCHER') or '').strip()[:128],
                    'rating': _normalize_rating(item.get('RATING') or ''),
                    'rating_change': _normalize_rating_change(item.get('CHANGE') or ''),
                    'target_price_low': float(target_low) if target_low else None,
                    'target_price_high': float(target_high) if target_high else None,
                    'report_title': (item.get('TITLE') or '')[:500],
                })

            if len(items) < page_size:
                break

        except requests.RequestException as exc:
            _logger.warning(f'[评级爬虫] 请求异常 page={page}: {exc}')
            break
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            _logger.warning(f'[评级爬虫] 解析异常: {exc}')
            break

        time.sleep(1)

    _logger.info(f'[评级爬虫] 获取到 {len(results)} 条评级记录')
    return results


def save_rating_data(records: List[Dict[str, Any]]) -> int:
    """将评级数据批量写入数据库。"""
    if not records:
        return 0

    ensure_rating_table()
    inserted = 0

    for i in range(0, len(records), _DB_INSERT_CHUNKSIZE):
        chunk = records[i:i + _DB_INSERT_CHUNKSIZE]
        values = []
        params = []
        for r in chunk:
            values.append('(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)')
            params.extend([
                r['code'], r['name'], r['rating_date'], r['institution'],
                r['researcher'], r['rating'], r['rating_change'],
                r['target_price_low'], r['target_price_high'], r['report_title'],
            ])

        sql = f"""
            INSERT IGNORE INTO `{_RATING_TABLE}`
                (code, name, rating_date, institution, researcher,
                 rating, rating_change, target_price_low, target_price_high, report_title)
            VALUES {', '.join(values)}
        """
        try:
            mdb.executeSql(sql, tuple(params))
            inserted += len(chunk)
        except Exception as exc:
            _logger.warning(f'[评级爬虫] 批量写入失败: {exc}')

    _logger.info(f'[评级爬虫] 写入 {inserted} 条记录')
    return inserted


def get_stock_ratings(code: str, days: int = 90) -> List[Dict[str, Any]]:
    """获取某只股票的近期评级汇总（供报告使用）。"""
    ensure_rating_table()
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    sql = f"""
        SELECT rating_date, institution, rating, rating_change,
               target_price_low, target_price_high, report_title
        FROM `{_RATING_TABLE}`
        WHERE code = %s AND rating_date >= %s
        ORDER BY rating_date DESC
        LIMIT 20
    """
    rows = mdb.executeSqlFetch(sql, (code, cutoff)) or []
    return [
        {
            'date': str(r[0]), 'institution': r[1], 'rating': r[2],
            'change': r[3], 'target_low': float(r[4]) if r[4] else None,
            'target_high': float(r[5]) if r[5] else None, 'title': r[6],
        }
        for r in rows
    ]


def get_rating_consensus(code: str, days: int = 90) -> Dict[str, Any]:
    """获取评级共识（买入/增持/中性/减持/卖出 各多少家）。"""
    ensure_rating_table()
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    sql = f"""
        SELECT rating, COUNT(*) as cnt
        FROM `{_RATING_TABLE}`
        WHERE code = %s AND rating_date >= %s
        GROUP BY rating
    """
    rows = mdb.executeSqlFetch(sql, (code, cutoff)) or []
    consensus = {r[0]: r[1] for r in rows}
    total = sum(consensus.values())
    return {
        'total': total,
        'breakdown': consensus,
        'bullish_pct': round((consensus.get('买入', 0) + consensus.get('增持', 0)) / max(total, 1) * 100, 1),
    }


def run_rating_crawler(code: Optional[str] = None, days: int = 30) -> Dict[str, int]:
    """执行机构评级爬虫主流程。"""
    _logger.info(f'[评级爬虫] 开始 code={code or "全市场"} days={days}')
    records = fetch_institutional_ratings(stock_code=code, days=days)
    inserted = save_rating_data(records)
    return {'fetched': len(records), 'inserted': inserted}


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s %(message)s'
    )

    parser = argparse.ArgumentParser(description='Quantia 机构评级数据爬虫')
    parser.add_argument('--code', type=str, default=None, help='指定股票代码')
    parser.add_argument('--days', type=int, default=30, help='获取最近N天')
    args = parser.parse_args()

    result = run_rating_crawler(code=args.code, days=args.days)
    print(f'结果: {result}')

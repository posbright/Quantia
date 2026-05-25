#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 4: 专利数据爬虫 — 从巨潮公告中提取专利/知识产权相关公告。

数据来源: 巨潮信息网 公告搜索 API (http://www.cninfo.com.cn)
存储表: cn_stock_patent_info

本爬虫属于 Fetch 管道（见 AGENTS.md 规则 1），
仅负责数据获取和存储，不做分析计算。

用法::

    python -m quantia.job.stock_patent_crawler --days 30
    python -m quantia.job.stock_patent_crawler --code 000001
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

import requests

import quantia.lib.database as mdb

_logger = logging.getLogger(__name__)

_PATENT_TABLE = 'cn_stock_patent_info'
_DB_INSERT_CHUNKSIZE = 500

# 巨潮公告搜索 API
_CNINFO_SEARCH_URL = 'http://www.cninfo.com.cn/new/hisAnnouncement/query'
_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json',
    'Content-Type': 'application/x-www-form-urlencoded',
    'Referer': 'http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/search',
}

# 专利相关关键词
_PATENT_KEYWORDS = ['专利', '知识产权', '发明', '实用新型', '外观设计', '技术许可', '技术转让']


def ensure_patent_table():
    """确保专利信息表存在。"""
    if not mdb.checkTableIsExist(_PATENT_TABLE):
        mdb.executeSql(f'''
            CREATE TABLE IF NOT EXISTS `{_PATENT_TABLE}` (
                `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
                `code` VARCHAR(10) NOT NULL,
                `name` VARCHAR(64) DEFAULT '',
                `title` VARCHAR(500) NOT NULL,
                `announcement_id` VARCHAR(64) NOT NULL,
                `announcement_date` DATE NOT NULL,
                `category` VARCHAR(64) DEFAULT '' COMMENT '公告类型',
                `patent_type` VARCHAR(32) DEFAULT '' COMMENT '专利类型: invention/utility/design',
                `patent_count` INT DEFAULT NULL COMMENT '涉及专利数量(若可提取)',
                `url` VARCHAR(500) DEFAULT '',
                `summary` TEXT COMMENT '公告摘要',
                `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY `uq_ann_id` (`announcement_id`),
                INDEX `idx_code_date` (`code`, `announcement_date`),
                INDEX `idx_patent_type` (`patent_type`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')


def _classify_patent_type(title: str) -> str:
    """根据公告标题分类专利类型。"""
    if '发明' in title:
        return 'invention'
    elif '实用新型' in title:
        return 'utility'
    elif '外观设计' in title:
        return 'design'
    elif '知识产权' in title or '技术许可' in title or '技术转让' in title:
        return 'ip_transfer'
    return 'general'


def _extract_patent_count(title: str) -> Optional[int]:
    """尝试从标题中提取专利数量。"""
    # 匹配 "获得XX项专利" / "XX件发明"
    match = re.search(r'(\d+)\s*[项件个]', title)
    if match:
        return int(match.group(1))
    return None


def fetch_patent_announcements(
    stock_code: Optional[str] = None,
    days: int = 30,
    page_size: int = 30,
    max_pages: int = 5,
) -> List[Dict[str, Any]]:
    """从巨潮信息网搜索专利相关公告。

    Args:
        stock_code: 指定股票代码（可选，为空则搜索全市场）
        days: 搜索最近 N 天
        page_size: 每页条数
        max_pages: 最大页数

    Returns:
        解析后的专利公告列表
    """
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=days)
    se_date = f"{start_date.strftime('%Y-%m-%d')}~{end_date.strftime('%Y-%m-%d')}"

    results = []

    for keyword in _PATENT_KEYWORDS[:3]:  # 限制关键词数量避免过多请求
        for page in range(max_pages):
            params = {
                'pageNum': page + 1,
                'pageSize': page_size,
                'column': 'szse',  # 深圳+上海
                'tabName': 'fulltext',
                'seDate': se_date,
                'searchkey': keyword,
                'isHLtitle': 'true',
            }
            # NOTE: CNINFO stock param requires orgId which we don't have,
            # so we filter by secCode in the response instead.

            try:
                resp = requests.post(
                    _CNINFO_SEARCH_URL, data=params,
                    headers=_HEADERS, timeout=15
                )
                if resp.status_code != 200:
                    _logger.warning(f'[专利爬虫] HTTP {resp.status_code} for keyword={keyword} page={page+1}')
                    break

                data = resp.json()
                announcements = data.get('announcements') or []
                if not announcements:
                    break

                for ann in announcements:
                    code = (ann.get('secCode') or '').strip()
                    # 如果指定了股票代码，只保留匹配的
                    if stock_code and code != stock_code:
                        continue

                    title = (ann.get('announcementTitle') or '').replace('<em>', '').replace('</em>', '')
                    # 只保留确实与专利/知识产权相关的
                    if not any(kw in title for kw in _PATENT_KEYWORDS):
                        continue

                    ann_id = ann.get('announcementId') or ''
                    ann_date_ts = ann.get('announcementTime')
                    if ann_date_ts:
                        ann_date = datetime.date.fromtimestamp(ann_date_ts / 1000)
                    else:
                        ann_date = end_date

                    name = (ann.get('secName') or '').strip()

                    results.append({
                        'code': code,
                        'name': name,
                        'title': title[:500],
                        'announcement_id': str(ann_id),
                        'announcement_date': ann_date,
                        'category': ann.get('adjunctType') or '',
                        'patent_type': _classify_patent_type(title),
                        'patent_count': _extract_patent_count(title),
                        'url': f"http://www.cninfo.com.cn/new/disclosure/detail?annoId={ann_id}" if ann_id else '',
                        'summary': title[:200],
                    })

                # 如果返回数少于 page_size，说明没有更多了
                if len(announcements) < page_size:
                    break

            except requests.RequestException as exc:
                _logger.warning(f'[专利爬虫] 请求异常 keyword={keyword} page={page+1}: {exc}')
                break
            except (json.JSONDecodeError, KeyError) as exc:
                _logger.warning(f'[专利爬虫] 解析异常: {exc}')
                break

            time.sleep(1)  # 限速

        time.sleep(0.5)

    # 去重
    seen_ids = set()
    unique = []
    for item in results:
        aid = item['announcement_id']
        if aid and aid not in seen_ids:
            seen_ids.add(aid)
            unique.append(item)

    _logger.info(f'[专利爬虫] 获取到 {len(unique)} 条专利相关公告')
    return unique


def save_patent_data(records: List[Dict[str, Any]]) -> int:
    """将专利数据批量写入数据库。使用 INSERT IGNORE 去重。"""
    if not records:
        return 0

    ensure_patent_table()
    inserted = 0

    for i in range(0, len(records), _DB_INSERT_CHUNKSIZE):
        chunk = records[i:i + _DB_INSERT_CHUNKSIZE]
        values = []
        params = []
        for r in chunk:
            values.append('(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)')
            params.extend([
                r['code'], r['name'], r['title'], r['announcement_id'],
                r['announcement_date'], r['category'], r['patent_type'],
                r['patent_count'], r['url'], r.get('summary', ''),
            ])

        sql = f"""
            INSERT IGNORE INTO `{_PATENT_TABLE}`
                (code, name, title, announcement_id, announcement_date,
                 category, patent_type, patent_count, url, summary)
            VALUES {', '.join(values)}
        """
        try:
            mdb.executeSql(sql, tuple(params))
            inserted += len(chunk)
        except Exception as exc:
            _logger.warning(f'[专利爬虫] 批量写入失败: {exc}')

    _logger.info(f'[专利爬虫] 写入 {inserted} 条记录')
    return inserted


def run_patent_crawler(code: Optional[str] = None, days: int = 30) -> Dict[str, int]:
    """执行专利爬虫主流程。"""
    _logger.info(f'[专利爬虫] 开始 code={code or "全市场"} days={days}')
    records = fetch_patent_announcements(stock_code=code, days=days)
    inserted = save_patent_data(records)
    return {'fetched': len(records), 'inserted': inserted}


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s %(message)s'
    )

    parser = argparse.ArgumentParser(description='Quantia 专利数据爬虫')
    parser.add_argument('--code', type=str, default=None, help='指定股票代码')
    parser.add_argument('--days', type=int, default=30, help='搜索最近N天')
    args = parser.parse_args()

    result = run_patent_crawler(code=args.code, days=args.days)
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    print(f'结果: {result}')

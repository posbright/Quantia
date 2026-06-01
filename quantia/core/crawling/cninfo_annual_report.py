#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 3a 主源: 巨潮信息网年度报告下载器。

仅负责"查找年报公告 → 下载 PDF 到本地缓存"，不做内容解析（解析在
`annual_report_parser.py`）。属于 Fetch 管道（见 AGENTS.md 规则 1）。

巨潮 API:
- 公告查询: POST http://www.cninfo.com.cn/new/hisAnnouncement/query
- 股票元数据: GET  http://www.cninfo.com.cn/new/data/szse_stock.json
                  GET  http://www.cninfo.com.cn/new/data/sse_stock.json
- 公告下载: GET  http://static.cninfo.com.cn/{adjunctUrl}

用法::

    from quantia.core.crawling.cninfo_annual_report import download_annual_report
    pdf_path = download_annual_report('000001', 2024)
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

_logger = logging.getLogger(__name__)

_QUERY_URL = 'http://www.cninfo.com.cn/new/hisAnnouncement/query'
_STOCK_LIST_URLS = {
    'sz': 'http://www.cninfo.com.cn/new/data/szse_stock.json',
    'sh': 'http://www.cninfo.com.cn/new/data/sse_stock.json',
}
_STATIC_BASE = 'http://static.cninfo.com.cn/'

_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Content-Type': 'application/x-www-form-urlencoded',
    'X-Requested-With': 'XMLHttpRequest',
    'Referer': 'http://www.cninfo.com.cn/new/commonUrl/pageOfSearch',
}

# 年报类别 (category 字段)
_CATEGORY_ANNUAL = 'category_ndbg_szsh'

# 缓存目录
_DEFAULT_CACHE_DIR = Path(os.environ.get(
    'QUANTIA_PATENT_CACHE_DIR',
    Path.home() / '.quantia' / 'annual_reports',
))

# 限速 (秒)
_REQUEST_INTERVAL = float(os.environ.get('QUANTIA_CNINFO_INTERVAL', '3'))

_orgid_cache: Dict[str, str] = {}


def _cache_dir() -> Path:
    _DEFAULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _DEFAULT_CACHE_DIR


def _market_of(code: str) -> str:
    """根据 A 股代码判断市场。6 开头沪市；其他深市（含创业板/科创板按需扩展）。"""
    if code.startswith(('600', '601', '603', '605', '688', '689')):
        return 'sh'
    return 'sz'


def _load_orgid_map() -> Dict[str, str]:
    """加载并缓存 (code -> orgId) 映射。巨潮 API 必须组合 stock=code,orgId。"""
    if _orgid_cache:
        return _orgid_cache

    for market, url in _STOCK_LIST_URLS.items():
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=15)
            if resp.status_code != 200:
                _logger.warning('[cninfo] 获取 %s 股票列表失败: HTTP %s', market, resp.status_code)
                continue
            text = resp.text.strip()
            items: List[Dict[str, str]] = []
            # 优先按纯 JSON 解析 (常见格式: {"stockList":[...]} 或 [...] )
            try:
                obj = json.loads(text)
                if isinstance(obj, list):
                    items = obj
                elif isinstance(obj, dict):
                    items = obj.get('stockList') or obj.get('data') or []
            except json.JSONDecodeError:
                # 回退: 提取最大的 [...] 片段, 兼容 jsonp 包装
                m = re.search(r'\[.*\]', text, re.DOTALL)
                if not m:
                    continue
                try:
                    items = json.loads(m.group(0))
                except json.JSONDecodeError:
                    continue
            for item in items:
                code = item.get('code') or ''
                org = item.get('orgId') or ''
                if code and org:
                    _orgid_cache[code] = org
            time.sleep(_REQUEST_INTERVAL)
        except (requests.RequestException, json.JSONDecodeError) as exc:
            _logger.warning('[cninfo] 解析 %s 股票列表异常: %s', market, exc)
            continue

    _logger.info('[cninfo] orgId 映射已加载: %d 条', len(_orgid_cache))
    return _orgid_cache


def get_orgid(code: str) -> Optional[str]:
    """获取股票的 orgId（巨潮内部 ID）。未找到返回 None。"""
    _load_orgid_map()
    return _orgid_cache.get(code)


def search_annual_reports(
    code: str,
    year: int,
    max_pages: int = 2,
) -> List[Dict[str, str]]:
    """搜索指定股票指定年度的年报公告。

    Returns:
        公告列表: [{'announcement_id', 'title', 'adjunct_url', 'announcement_date'}, ...]
        通常包含: 年度报告、年度报告摘要、年度报告（更新版）等。
    """
    org_id = get_orgid(code)
    if not org_id:
        _logger.warning('[cninfo] 无法找到 %s 的 orgId', code)
        return []

    market = _market_of(code)
    column = 'sse' if market == 'sh' else 'szse'

    # 年报披露窗口：财年结束次年 1-6 月；放宽到 7 月以兼容延期披露
    se_date = f'{year + 1}-01-01~{year + 1}-07-31'

    results: List[Dict[str, str]] = []
    for page in range(max_pages):
        params = {
            'pageNum': page + 1,
            'pageSize': 30,
            'column': column,
            'tabName': 'fulltext',
            'plate': '',
            'stock': f'{code},{org_id}',
            'searchkey': '',
            'secid': '',
            'category': _CATEGORY_ANNUAL,
            'trade': '',
            'seDate': se_date,
            'sortName': '',
            'sortType': '',
            'isHLtitle': 'true',
        }
        try:
            resp = requests.post(_QUERY_URL, data=params, headers=_HEADERS, timeout=15)
            if resp.status_code != 200:
                _logger.warning('[cninfo] 公告查询 HTTP %s code=%s', resp.status_code, code)
                break
            data = resp.json()
        except (requests.RequestException, json.JSONDecodeError) as exc:
            _logger.warning('[cninfo] 公告查询异常 code=%s: %s', code, exc)
            break

        anns = data.get('announcements') or []
        if not anns:
            break

        for ann in anns:
            title = (ann.get('announcementTitle') or '').replace('<em>', '').replace('</em>', '')
            adjunct_url = ann.get('adjunctUrl') or ''
            # 过滤摘要 / 英文版 / 取消 等
            if any(skip in title for skip in ('摘要', '英文', '取消', '更正前', '补充')):
                continue
            if '年度报告' not in title and '年报' not in title:
                continue
            # 只保留 PDF
            if not adjunct_url.lower().endswith('.pdf'):
                continue

            ann_id = ann.get('announcementId') or ''
            ts = ann.get('announcementTime')
            import datetime
            ann_date = (
                datetime.date.fromtimestamp(ts / 1000).isoformat() if ts else ''
            )
            results.append({
                'announcement_id': str(ann_id),
                'title': title,
                'adjunct_url': adjunct_url,
                'announcement_date': ann_date,
            })

        if len(anns) < 30:
            break
        time.sleep(_REQUEST_INTERVAL)

    return results


def _pick_best_report(reports: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """从候选列表中选择最合适的年报版本。

    优先级: 更新版/修订版 > 普通正文。同档按公告日期降序取最新。
    """
    if not reports:
        return None

    def score(r: Dict[str, str]) -> tuple:
        title = r.get('title', '')
        rev_bonus = 1 if any(k in title for k in ('更新', '修订', '重新')) else 0
        return (rev_bonus, r.get('announcement_date', ''))

    return sorted(reports, key=score, reverse=True)[0]


def download_annual_report(
    code: str,
    year: int,
    cache_dir: Optional[Path] = None,
    force: bool = False,
) -> Optional[Path]:
    """下载指定股票指定年度的年报 PDF 到本地缓存。

    Args:
        code: 6位 A 股代码
        year: 财年 (例如 2024 表示 2024 年度报告, 通常在 2025 年披露)
        cache_dir: 缓存目录, 默认 ~/.quantia/annual_reports/
        force: True 时强制重新下载

    Returns:
        下载后的本地路径, 失败返回 None。
    """
    cache_dir = cache_dir or _cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f'{code}_{year}.pdf'

    if target.exists() and not force and target.stat().st_size > 1024:
        _logger.debug('[cninfo] 命中缓存 %s', target)
        return target

    reports = search_annual_reports(code, year)
    chosen = _pick_best_report(reports)
    if not chosen:
        _logger.info('[cninfo] 未找到 %s %s 年报', code, year)
        return None

    pdf_url = _STATIC_BASE + chosen['adjunct_url'].lstrip('/')
    try:
        time.sleep(_REQUEST_INTERVAL)
        resp = requests.get(pdf_url, headers=_HEADERS, timeout=60, stream=True)
        if resp.status_code != 200:
            _logger.warning('[cninfo] 下载 PDF HTTP %s url=%s', resp.status_code, pdf_url)
            return None
        tmp = target.with_suffix('.pdf.part')
        with open(tmp, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if chunk:
                    f.write(chunk)
        tmp.replace(target)
        _logger.info('[cninfo] 已下载 %s', target)
        return target
    except requests.RequestException as exc:
        _logger.warning('[cninfo] 下载异常 %s: %s', pdf_url, exc)
        return None


if __name__ == '__main__':
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(name)s %(message)s')

    p = argparse.ArgumentParser(description='巨潮年报下载器')
    p.add_argument('--code', required=True, help='股票代码, e.g. 000001')
    p.add_argument('--year', type=int, required=True, help='财年, e.g. 2024')
    p.add_argument('--force', action='store_true')
    args = p.parse_args()

    path = download_annual_report(args.code, args.year, force=args.force)
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    print(f'结果: {path}')

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 3b 备份源: Google Patents 采集器。

参考 document/ai_moat_patent_enhancement_plan.md 2.4.6 / 3.5。

职责:
- 按公司名搜索专利列表 (Google Patents XHR JSON 接口)
- 从专利列表聚合: IPC 分布 / 引用统计 / 5 年申请趋势 / PCT 数量
- 输出对齐 cn_stock_patents 的 "Google 补充字段"

设计原则:
- **纯聚合函数** (extract_*/aggregate_*) 不触网, 可离线单测
- **网络函数** (search_patents) 懒加载 requests, 任何异常优雅返回 []
- 默认走免 headless 的 XHR JSON 接口; Playwright 仅作为可选增强 (未启用)
- 反爬: 请求间隔 + 结果本地缓存 (见 _cache_*)

属于 Fetch 管道（见 AGENTS.md 规则 1）。

标准化专利 dict 结构 (search_patents 的元素 / 聚合函数的输入):
    {
        'id': 'CN112233445A',
        'title': '...',
        'assignee': '宁德时代新能源科技股份有限公司',
        'filing_year': 2022,            # int 或 None
        'ipc_codes': ['H01M10/05', ...],
        'citation_count': 3,            # 被引用次数
        'country': 'CN',
        'is_pct': False,               # 是否 PCT/WO 国际申请
    }
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from quantia.core import patent_ipc_mapping as ipc_map

_logger = logging.getLogger(__name__)

_XHR_URL = 'https://patents.google.com/xhr/query'
_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Referer': 'https://patents.google.com/',
}

_REQUEST_INTERVAL = float(os.environ.get('QUANTIA_GPATENTS_INTERVAL', '5'))
_CACHE_DAYS = int(os.environ.get('QUANTIA_GPATENTS_CACHE_DAYS', '90'))
_DEFAULT_CACHE_DIR = Path(os.environ.get(
    'QUANTIA_GPATENTS_CACHE_DIR',
    Path.home() / '.quantia' / 'google_patents',
))


# ---------------------------------------------------------------------------
# 缓存
# ---------------------------------------------------------------------------

def _cache_dir() -> Path:
    _DEFAULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _DEFAULT_CACHE_DIR


def _cache_path(assignee: str) -> Path:
    safe = re.sub(r'[^\w\u4e00-\u9fff]+', '_', assignee)[:80]
    return _cache_dir() / f'{safe}.json'


def _load_cache(assignee: str) -> Optional[List[Dict[str, Any]]]:
    path = _cache_path(assignee)
    if not path.is_file():
        return None
    try:
        age_days = (time.time() - path.stat().st_mtime) / 86400
        if age_days > _CACHE_DAYS:
            return None
        with path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _save_cache(assignee: str, patents: List[Dict[str, Any]]) -> None:
    try:
        with _cache_path(assignee).open('w', encoding='utf-8') as f:
            json.dump(patents, f, ensure_ascii=False)
    except OSError as exc:  # pragma: no cover
        _logger.debug('[gpatents] 写缓存失败 %s: %s', assignee, exc)


# ---------------------------------------------------------------------------
# XHR 响应标准化
# ---------------------------------------------------------------------------

def _to_year(value: Any) -> Optional[int]:
    """从日期字符串/数字提取 4 位年份。"""
    if value is None:
        return None
    s = str(value)
    m = re.search(r'(19|20)\d{2}', s)
    return int(m.group(0)) if m else None


def normalize_patent(raw: Dict[str, Any]) -> Dict[str, Any]:
    """将 Google Patents XHR 单条结果标准化为统一 dict。

    XHR 结果字段名可能随接口变化, 这里做容错取值。
    """
    pub = (raw.get('publication_number') or raw.get('id')
           or raw.get('patent_id') or '')
    ipc_raw = (raw.get('ipc') or raw.get('ipcr_codes')
               or raw.get('cpc') or raw.get('classifications') or [])
    if isinstance(ipc_raw, str):
        ipc_codes = [c for c in re.split(r'[;,\s]+', ipc_raw) if c]
    elif isinstance(ipc_raw, list):
        ipc_codes = []
        for item in ipc_raw:
            if isinstance(item, str):
                ipc_codes.append(item)
            elif isinstance(item, dict):
                code = item.get('code') or item.get('id')
                if code:
                    ipc_codes.append(str(code))
    else:
        ipc_codes = []

    filing_year = _to_year(
        raw.get('filing_date') or raw.get('priority_date')
        or raw.get('application_date') or raw.get('publication_date')
    )
    citation = (raw.get('cited_by_count') or raw.get('citation_count')
                or raw.get('num_cited_by') or 0)
    try:
        citation = int(citation)
    except (TypeError, ValueError):
        citation = 0

    country = (str(pub)[:2].upper() if pub else
               (raw.get('country') or '').upper())
    is_pct = bool(re.match(r'(WO|PCT)', str(pub).upper())) or country == 'WO'

    return {
        'id': str(pub),
        'title': raw.get('title') or raw.get('title_localized') or '',
        'assignee': raw.get('assignee') or raw.get('assignee_original') or '',
        'filing_year': filing_year,
        'ipc_codes': ipc_codes,
        'citation_count': citation,
        'country': country,
        'is_pct': is_pct,
    }


def _parse_xhr_results(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从 XHR JSON 提取并标准化专利列表。结构容错。"""
    results = payload.get('results') or {}
    clusters = results.get('cluster') or []
    out: List[Dict[str, Any]] = []
    for cluster in clusters:
        for entry in cluster.get('result') or []:
            patent = entry.get('patent') or entry
            if isinstance(patent, dict):
                out.append(normalize_patent(patent))
    return out


# ---------------------------------------------------------------------------
# 网络搜索 (懒加载 requests, 优雅降级)
# ---------------------------------------------------------------------------

def search_patents(
    assignee: str,
    country: str = 'CN',
    max_results: int = 1000,
    use_cache: bool = True,
) -> List[Dict[str, Any]]:
    """按申请人搜索专利。失败/不可用时返回 []（不抛错, 不阻塞主流程）。"""
    if not assignee:
        return []
    if use_cache:
        cached = _load_cache(assignee)
        if cached is not None:
            _logger.info('[gpatents] 命中缓存 %s: %d 条', assignee, len(cached))
            return cached

    try:
        import requests  # 懒加载
        from quantia.core.singleton_proxy import proxied_request  # 懒加载：经代理池请求，降低限流风险
    except ImportError:  # pragma: no cover
        _logger.warning('[gpatents] requests 不可用, 跳过')
        return []

    query = f'assignee:"{assignee}"' + (f' country:{country}' if country else '')
    params = {'url': f'q={query}&num=100', 'exp': ''}
    patents: List[Dict[str, Any]] = []
    try:
        resp = proxied_request('get', _XHR_URL, params=params, headers=_HEADERS, timeout=20)
        if resp.status_code != 200:
            _logger.warning('[gpatents] %s HTTP %s', assignee, resp.status_code)
            return []
        text = resp.text.lstrip(")]}'\n")  # 去除可能的 XSSI 前缀
        payload = json.loads(text)
        patents = _parse_xhr_results(payload)[:max_results]
        time.sleep(_REQUEST_INTERVAL)
    except (Exception) as exc:  # pragma: no cover - 网络/解析容错
        _logger.warning('[gpatents] 搜索 %s 失败: %s', assignee, exc)
        return []

    if patents and use_cache:
        _save_cache(assignee, patents)
    return patents


# ---------------------------------------------------------------------------
# 纯聚合函数 (离线可测)
# ---------------------------------------------------------------------------

def extract_ipc_distribution(patents: List[Dict[str, Any]]) -> Dict[str, int]:
    """聚合专利列表的 IPC 大类分布。"""
    all_codes: List[str] = []
    for p in patents or []:
        all_codes.extend(p.get('ipc_codes') or [])
    return ipc_map.build_ipc_distribution(all_codes)


def extract_citation_stats(patents: List[Dict[str, Any]]) -> Dict[str, float]:
    """计算平均/最大被引用次数。"""
    counts = [int(p.get('citation_count') or 0) for p in (patents or [])]
    if not counts:
        return {'avg_citation_count': None, 'max_citation_count': None}
    return {
        'avg_citation_count': round(sum(counts) / len(counts), 2),
        'max_citation_count': max(counts),
    }


def extract_yearly_trend(
    patents: List[Dict[str, Any]],
    years: int = 5,
    end_year: Optional[int] = None,
) -> List[Dict[str, int]]:
    """统计近 N 年专利申请数, 返回 [{'year', 'count'}] (年份升序, 含 0 的年份)。"""
    end_year = end_year or datetime.date.today().year
    start_year = end_year - years + 1
    counter: Dict[int, int] = {y: 0 for y in range(start_year, end_year + 1)}
    for p in patents or []:
        y = p.get('filing_year')
        if y is not None and start_year <= y <= end_year:
            counter[y] += 1
    return [{'year': y, 'count': counter[y]} for y in range(start_year, end_year + 1)]


def calculate_pct_count(patents: List[Dict[str, Any]]) -> int:
    """统计 PCT/WO 国际申请数量。"""
    return sum(1 for p in (patents or []) if p.get('is_pct'))


def aggregate_google_patents(
    patents: List[Dict[str, Any]],
    years: int = 5,
    end_year: Optional[int] = None,
) -> Dict[str, Any]:
    """将专利列表聚合为对齐 cn_stock_patents 的 Google 补充字段 dict。

    仅产出 Google 擅长的维度 (IPC/引用/趋势/PCT/总数), 不产出年报权威字段。
    """
    if not patents:
        return {}
    ipc = ipc_map.primary_ipc(
        [c for p in patents for c in (p.get('ipc_codes') or [])]
    )
    citation = extract_citation_stats(patents)
    trend = extract_yearly_trend(patents, years=years, end_year=end_year)
    return {
        'total_patents': len(patents),
        'avg_citation_count': citation['avg_citation_count'],
        'pct_international': calculate_pct_count(patents),
        'ipc_primary': ipc['ipc_primary'],
        'ipc_primary_desc': ipc['ipc_primary_desc'],
        'ipc_distribution': ipc['ipc_distribution'],
        'tech_domain': ipc['tech_domain'],
        'trend_5y': trend,
        'data_source': 'google_patents',
        'confidence_score': 80,
    }


def fetch_and_aggregate(
    assignee_names: List[str],
    country: str = 'CN',
    years: int = 5,
) -> Dict[str, Any]:
    """对多个候选公司名搜索并合并去重, 返回聚合结果。

    多个名称 (全称/简称/子公司) 的专利按 id 去重后统一聚合。
    """
    seen: Dict[str, Dict[str, Any]] = {}
    for name in assignee_names or []:
        for p in search_patents(name, country=country):
            pid = p.get('id')
            if pid and pid not in seen:
                seen[pid] = p
    return aggregate_google_patents(list(seen.values()), years=years)

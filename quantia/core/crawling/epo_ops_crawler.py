#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IPC 替代/主备源: EPO OPS (Open Patent Services) 采集器。

背景见 document/patent_data_coverage_and_pipeline.md §6 "IPC 数据来源对比"：
Google Patents 的 xhr/query 易被 503 限流，EPO OPS 是官方、免费(注册 OAuth)、
DOCDB 全球库含中国(CN)专利且带 IPC/CPC 的结构化源，作为 IPC 饼图/趋势的
**主源或主备选**。

职责:
- OAuth2 client_credentials 取 access_token (内存缓存, 含过期)
- 按申请人(assignee) 检索 biblio, 解析 IPC 代码 / 国别 / 公开年
- 聚合为对齐 cn_stock_patents 的 IPC 补充字段 (ipc_primary/distribution/tech_domain/trend)

设计原则 (对齐 google_patents_crawler):
- **纯聚合/解析函数** (parse_*/aggregate_*) 不触网, 可离线单测
- **网络函数** (get_access_token/search_patents) 懒加载 requests + proxied_request,
  任何异常或**缺少凭证**时优雅返回 [] / None — 不抛出, 不影响主链路
- 反爬/配额: 请求间隔 + 结果本地缓存

凭证 (任一缺失则整源静默禁用, 不影响年报源与行业保底):
    QUANTIA_EPO_OPS_KEY      OPS consumer key
    QUANTIA_EPO_OPS_SECRET   OPS consumer secret

属于 Fetch 管道（见 AGENTS.md 规则 1）。

标准化专利 dict (与 google_patents_crawler 对齐):
    {
        'id': 'CN112233445A', 'title': None,
        'assignee': '<查询名>', 'filing_year': 2022 或 None,
        'ipc_codes': ['H01M10/05', ...], 'citation_count': 0,
        'country': 'CN', 'is_pct': False,
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
from typing import Any, Dict, List, Optional, Tuple

from quantia.core import patent_ipc_mapping as ipc_map

_logger = logging.getLogger(__name__)

_AUTH_URL = 'https://ops.epo.org/3.2/auth/accesstoken'
_SEARCH_URL = 'https://ops.epo.org/3.2/rest-services/published-data/search/biblio'

_REQUEST_INTERVAL = float(os.environ.get('QUANTIA_EPO_OPS_INTERVAL', '2'))
_CACHE_DAYS = int(os.environ.get('QUANTIA_EPO_OPS_CACHE_DAYS', '90'))
_DEFAULT_CACHE_DIR = Path(os.environ.get(
    'QUANTIA_EPO_OPS_CACHE_DIR',
    Path.home() / '.quantia' / 'epo_ops',
))

# IPC 文本形如 "H01M  10/0525  20100101 ..."；取前导分类号部分
_IPC_TEXT_RE = re.compile(r'([A-H])\s*(\d{2})\s*([A-Z])\s*(\d{1,4}/\d{1,6})?')

# 内存级 token 缓存
_token_cache: Dict[str, Any] = {'token': None, 'expires_at': 0.0}


# ---------------------------------------------------------------------------
# 凭证 / Token
# ---------------------------------------------------------------------------

def get_credentials() -> Optional[Tuple[str, str]]:
    """读取 OPS 凭证；任一缺失返回 None（整源静默禁用）。"""
    key = (os.environ.get('QUANTIA_EPO_OPS_KEY') or '').strip()
    secret = (os.environ.get('QUANTIA_EPO_OPS_SECRET') or '').strip()
    if key and secret:
        return key, secret
    return None


def is_enabled() -> bool:
    """是否配置了凭证（供上层决定是否走 EPO 源）。"""
    return get_credentials() is not None


def get_access_token(force_refresh: bool = False) -> Optional[str]:
    """OAuth2 client_credentials 取 token（内存缓存, 提前 60s 过期）。

    缺凭证 / 网络异常 / 非 200 → 返回 None（调用方据此跳过）。
    """
    if not force_refresh:
        tok = _token_cache.get('token')
        if tok and time.time() < float(_token_cache.get('expires_at', 0)):
            return tok

    creds = get_credentials()
    if not creds:
        return None
    key, secret = creds

    try:
        import base64
        from quantia.core.singleton_proxy import proxied_request
    except Exception:  # pragma: no cover - requests 不可用
        _logger.warning('[epo] requests/proxy 不可用, 跳过')
        return None

    basic = base64.b64encode(f'{key}:{secret}'.encode('utf-8')).decode('ascii')
    headers = {
        'Authorization': f'Basic {basic}',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
    }
    try:
        resp = proxied_request('post', _AUTH_URL, headers=headers,
                               data={'grant_type': 'client_credentials'}, timeout=20)
        if resp.status_code != 200:
            _logger.warning('[epo] 取 token 失败 HTTP %s', resp.status_code)
            return None
        payload = resp.json()
        token = payload.get('access_token')
        if not token:
            return None
        try:
            ttl = int(payload.get('expires_in', 1200))
        except (TypeError, ValueError):
            ttl = 1200
        _token_cache['token'] = token
        _token_cache['expires_at'] = time.time() + max(60, ttl) - 60
        return token
    except Exception as exc:  # pragma: no cover - 网络容错
        _logger.warning('[epo] 取 token 异常: %s', exc)
        return None


# ---------------------------------------------------------------------------
# 缓存
# ---------------------------------------------------------------------------

def _cache_dir() -> Path:
    _DEFAULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _DEFAULT_CACHE_DIR


def _cache_path(assignee: str, country: str) -> Path:
    safe = re.sub(r'[^\w\u4e00-\u9fff]+', '_', f'{assignee}_{country}')[:80]
    return _cache_dir() / f'{safe}.json'


def _load_cache(assignee: str, country: str) -> Optional[List[Dict[str, Any]]]:
    path = _cache_path(assignee, country)
    if not path.is_file():
        return None
    try:
        if (time.time() - path.stat().st_mtime) / 86400 > _CACHE_DAYS:
            return None
        with path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _save_cache(assignee: str, country: str, patents: List[Dict[str, Any]]) -> None:
    try:
        with _cache_path(assignee, country).open('w', encoding='utf-8') as f:
            json.dump(patents, f, ensure_ascii=False)
    except OSError as exc:  # pragma: no cover
        _logger.debug('[epo] 写缓存失败 %s: %s', assignee, exc)


# ---------------------------------------------------------------------------
# 纯解析函数 (离线可测) —— 对 OPS JSON 做"防御式递归"提取, 不假定精确嵌套层级
# ---------------------------------------------------------------------------

def _iter_key(obj: Any, key: str):
    """递归 yield 结构中所有名为 key 的值（dict/list 任意嵌套）。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                yield v
            yield from _iter_key(v, key)
    elif isinstance(obj, list):
        for it in obj:
            yield from _iter_key(it, key)


def _text_of(node: Any) -> Optional[str]:
    """OPS 文本节点常为 {'$': 'value'} 或直接字符串。"""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        v = node.get('$')
        if isinstance(v, str):
            return v
    return None


def _normalize_ipc(text: str) -> Optional[str]:
    """OPS IPC 文本 → 紧凑分类号 (如 'H01M  10/0525' → 'H01M10/0525')。"""
    if not text:
        return None
    m = _IPC_TEXT_RE.match(text.strip().upper())
    if not m:
        return None
    section, cls, subclass, group = m.group(1), m.group(2), m.group(3), m.group(4)
    code = f'{section}{cls}{subclass}'
    if group:
        code += group
    return code


def parse_exchange_document(doc: Any) -> Optional[Dict[str, Any]]:
    """从单个 exchange-document(dict) 提取标准化专利 dict。无 IPC 则返回 None。"""
    if not isinstance(doc, dict):
        return None
    country = doc.get('@country') or doc.get('country')

    # IPC: classification-ipcr / classifications-ipcr 下的 text 节点
    ipc_codes: List[str] = []
    for ipcr in _iter_key(doc, 'classification-ipcr'):
        for txt_node in _iter_key(ipcr, 'text'):
            norm = _normalize_ipc(_text_of(txt_node) or '')
            if norm:
                ipc_codes.append(norm)
    # 兜底: 直接找 'text' 里像 IPC 的
    if not ipc_codes:
        for txt_node in _iter_key(doc, 'text'):
            norm = _normalize_ipc(_text_of(txt_node) or '')
            if norm:
                ipc_codes.append(norm)
    if not ipc_codes:
        return None

    # 公开年: publication-reference 下 date(YYYYMMDD) 取最早一个的年份
    year: Optional[int] = None
    for pref in _iter_key(doc, 'publication-reference'):
        for date_node in _iter_key(pref, 'date'):
            ds = _text_of(date_node)
            if ds and len(ds) >= 4 and ds[:4].isdigit():
                y = int(ds[:4])
                year = y if year is None else min(year, y)
    doc_id = None
    for dn in _iter_key(doc, 'doc-number'):
        doc_id = _text_of(dn) or doc_id
        if doc_id:
            break

    return {
        'id': f'{country or ""}{doc_id or ""}' or None,
        'title': None,
        'filing_year': year,
        'ipc_codes': sorted(set(ipc_codes)),
        'citation_count': 0,
        'country': country,
        'is_pct': bool(country and str(country).upper() in ('WO',)),
    }


def parse_ops_response(payload: Any) -> List[Dict[str, Any]]:
    """解析 OPS biblio 检索 JSON → 标准化专利 list（防御式, 任意异常返回 []）。"""
    out: List[Dict[str, Any]] = []
    try:
        for doc in _iter_key(payload, 'exchange-document'):
            # exchange-document 可能是 dict 或 list
            docs = doc if isinstance(doc, list) else [doc]
            for d in docs:
                rec = parse_exchange_document(d)
                if rec:
                    out.append(rec)
    except Exception as exc:  # pragma: no cover - 容错
        _logger.warning('[epo] 解析响应异常: %s', exc)
        return []
    return out


# ---------------------------------------------------------------------------
# 聚合 (复用 patent_ipc_mapping; 与 google 同结构, data_source/confidence 不同)
# ---------------------------------------------------------------------------

def aggregate_epo_patents(
    patents: List[Dict[str, Any]],
    years: int = 5,
    end_year: Optional[int] = None,
) -> Dict[str, Any]:
    """专利列表 → 对齐 cn_stock_patents 的 IPC 补充字段 dict。空列表返回 {}。"""
    if not patents:
        return {}
    ipc = ipc_map.primary_ipc(
        [c for p in patents for c in (p.get('ipc_codes') or [])]
    )
    end_year = end_year or datetime.date.today().year
    start_year = end_year - years + 1
    counter = {y: 0 for y in range(start_year, end_year + 1)}
    for p in patents:
        y = p.get('filing_year')
        if y is not None and start_year <= y <= end_year:
            counter[y] += 1
    trend = [{'year': y, 'count': counter[y]} for y in range(start_year, end_year + 1)]
    pct = sum(1 for p in patents if p.get('is_pct'))
    return {
        'total_patents': len(patents),
        'pct_international': pct,
        'ipc_primary': ipc['ipc_primary'],
        'ipc_primary_desc': ipc['ipc_primary_desc'],
        'ipc_distribution': ipc['ipc_distribution'],
        'tech_domain': ipc['tech_domain'],
        'trend_5y': trend,
        'data_source': 'epo_ops',
        'confidence_score': 85,
    }


# ---------------------------------------------------------------------------
# 网络检索
# ---------------------------------------------------------------------------

def search_patents(
    assignee: str,
    country: str = 'CN',
    max_results: int = 100,
    use_cache: bool = True,
) -> List[Dict[str, Any]]:
    """按申请人检索 OPS biblio，返回标准化专利 list。

    缺凭证 / 取 token 失败 / 非 200 / 解析失败 → 返回 []（不抛出）。
    """
    if not assignee:
        return []
    if use_cache:
        cached = _load_cache(assignee, country)
        if cached is not None:
            return cached[:max_results]

    token = get_access_token()
    if not token:
        return []

    try:
        from quantia.core.singleton_proxy import proxied_request
    except Exception:  # pragma: no cover
        return []

    # CQL: pa=申请人 [and pn=国别前缀]; OPS biblio 单页上限 100 (Range)
    cql = f'pa="{assignee}"'
    if country:
        cql += f' and pn={country}'
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json',
        'X-OPS-Range': f'1-{min(100, max_results)}',
    }
    params = {'q': cql, 'Range': f'1-{min(100, max_results)}'}
    patents: List[Dict[str, Any]] = []
    try:
        resp = proxied_request('get', _SEARCH_URL, headers=headers,
                               params=params, timeout=25)
        if resp.status_code == 401:  # token 过期, 强制刷新重试一次
            token = get_access_token(force_refresh=True)
            if not token:
                return []
            headers['Authorization'] = f'Bearer {token}'
            resp = proxied_request('get', _SEARCH_URL, headers=headers,
                                   params=params, timeout=25)
        if resp.status_code != 200:
            _logger.warning('[epo] 检索 %s HTTP %s', assignee, resp.status_code)
            return []
        patents = parse_ops_response(resp.json())[:max_results]
        time.sleep(_REQUEST_INTERVAL)
    except Exception as exc:  # pragma: no cover - 网络/解析容错
        _logger.warning('[epo] 检索 %s 失败: %s', assignee, exc)
        return []

    if patents and use_cache:
        _save_cache(assignee, country, patents)
    return patents


def fetch_and_aggregate(
    assignee_names: List[str],
    country: str = 'CN',
    years: int = 5,
) -> Dict[str, Any]:
    """对多个候选公司名检索合并去重并聚合。缺凭证/无结果返回 {}。"""
    if not is_enabled():
        return {}
    seen: Dict[str, Dict[str, Any]] = {}
    for name in assignee_names or []:
        for p in search_patents(name, country=country):
            pid = p.get('id') or f'{name}:{len(seen)}'
            if pid not in seen:
                seen[pid] = p
    return aggregate_epo_patents(list(seen.values()), years=years)

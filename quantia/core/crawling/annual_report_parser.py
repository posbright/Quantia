#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 3a: 年度报告文本解析 — 从巨潮年报提取专利与研发指标。

设计要点 (参考 document/ai_moat_patent_enhancement_plan.md 2.4.7):
- 输入: PDF 文件路径 或 已抽取的文本字符串
- 输出: 扁平 dict, 字段对齐 cn_stock_patents 表
- PDF 提取依赖 pdfplumber (可选), 不可用时仅支持文本输入
- 提取均为正则 + 关键词定位, 失败字段返回 None 而非抛错

本模块属于 Compute 管道（见 AGENTS.md 规则 1），不发起网络请求。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_logger = logging.getLogger(__name__)

# 研发投入 / 知识产权 章节定位关键词
_SECTION_ANCHORS = (
    '研发投入', '研发情况', '核心技术', '知识产权', '专利情况', '研究开发',
)

# IPC 标准格式: 一位大写字母 + 两位数字 + 一位大写字母 (可选+数字/斜线)
_IPC_PATTERN = re.compile(r'\b([A-H]\d{2}[A-Z](?:\s*\d{1,3}/\d{1,3})?)\b')

# IPC 大类 → 技术领域中文 (用于 tech_domain / ipc_primary_desc)
IPC_SECTION_DESC = {
    'A': '人类生活必需品',
    'B': '作业/运输',
    'C': '化学/冶金',
    'D': '纺织/造纸',
    'E': '固定建筑物',
    'F': '机械工程/照明/加热',
    'G': '物理/仪器',
    'H': '电学/通信',
}
IPC_TECH_DOMAIN = {
    'A': '生物医药/消费',
    'B': '机械/运输',
    'C': '材料/化工',
    'D': '轻工/纺织',
    'E': '建筑/建材',
    'F': '机械/能源',
    'G': '电子/仪器',
    'H': '通信/电子',
}


# ---------------------------------------------------------------------------
# PDF / 文本读取
# ---------------------------------------------------------------------------

def extract_text_from_pdf(pdf_path: Path, max_pages: int = 80) -> str:
    """从年报 PDF 抽取纯文本。需要 pdfplumber, 缺失时抛 ImportError。

    Args:
        pdf_path: PDF 文件路径
        max_pages: 仅解析前 N 页（年报通常较长, 研发章节多在中前部）
    """
    try:
        import pdfplumber  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            'PDF 解析需要安装 pdfplumber: pip install pdfplumber'
        ) from exc

    pages_text: List[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages):
            if i >= max_pages:
                break
            try:
                pages_text.append(page.extract_text() or '')
            except Exception as exc:  # pragma: no cover
                _logger.debug('[parser] PDF 第 %d 页提取失败: %s', i + 1, exc)
    return '\n'.join(pages_text)


def locate_rd_section(text: str, window: int = 4000) -> str:
    """定位"研发投入"等章节, 返回该段落附近的窗口文本。

    若未找到任何锚点, 返回原文（让正则在全文中搜索）。
    """
    if not text:
        return ''
    for anchor in _SECTION_ANCHORS:
        idx = text.find(anchor)
        if idx >= 0:
            start = max(0, idx - 200)
            end = min(len(text), idx + window)
            return text[start:end]
    return text


# ---------------------------------------------------------------------------
# 字段提取
# ---------------------------------------------------------------------------

_NUM = r'([\d,]+(?:\.\d+)?)'


def _to_int(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    try:
        return int(float(s.replace(',', '')))
    except (ValueError, AttributeError):
        return None


def _to_float(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    try:
        return float(s.replace(',', ''))
    except (ValueError, AttributeError):
        return None


def _first_match(pattern: str, text: str) -> Optional[str]:
    m = re.search(pattern, text)
    return m.group(1) if m else None


def _coalesce(*values):
    """返回第一个非 None 的值 (0 也算有效值)。"""
    for v in values:
        if v is not None:
            return v
    return None


def extract_patent_counts(text: str) -> Dict[str, Optional[int]]:
    """从文本中提取专利数量字段。"""
    return {
        'total_patents': _coalesce(
            _to_int(_first_match(
                r'(?:累计|拥有|共有|已获得).{0,10}?专利\s*' + _NUM + r'\s*[项件个]', text
            )),
            # 大型公司常用表述: "拥有专利及专利申请合计达 43,354 项"(宁德时代)、
            # "持有专利及专利申请 N 项"。前一条 \s* 在"专利"后立即要求数字, 被
            # "及专利申请合计达"截断而漏匹配; 此处放开中间的"及专利申请/合计/达"修饰词。
            _to_int(_first_match(
                r'(?:拥有|持有|累计).{0,4}?专利(?:及专利申请)?\s*(?:合计)?\s*(?:达)?\s*'
                + _NUM + r'\s*[项件]', text
            )),
            # "累计申请专利 129,524 件"(格力)：累计申请量口径; 超大值仍由
            # validate_patent_data 的 50000 上限兜底拦截, 避免把申请量当授权量。
            _to_int(_first_match(
                r'累计.{0,4}?申请专利\s*' + _NUM + r'\s*[项件]', text
            )),
            _to_int(_first_match(
                r'专利\s*总数.{0,5}?' + _NUM + r'\s*[项件个]', text
            )),
            # 表格式表述: "报告期末专利证书数量 281" / "专利证书数量：281"
            # （数量在关键词之后, 单位另起"单位：个", 数字后无量词）。
            # 优先报告期末/期末, 避免误取"去年同期"列。
            _to_int(_first_match(
                r'(?:报告期末|期末)\s*专利\s*(?:证书)?\s*(?:数量|总数|总量)\s*[:：]?\s*' + _NUM,
                text,
            )),
            _to_int(_first_match(
                r'专利\s*(?:证书)?\s*(?:数量|总数|总量)\s*[:：]?\s*' + _NUM, text
            )),
        ),
        'invention_patents': _to_int(_first_match(
            r'发明专利\s*' + _NUM + r'\s*[项件个]', text
        )),
        'utility_patents': _to_int(_first_match(
            r'实用新型(?:专利)?\s*' + _NUM + r'\s*[项件个]', text
        )),
        'design_patents': _to_int(_first_match(
            r'外观设计(?:专利)?\s*' + _NUM + r'\s*[项件个]', text
        )),
        'new_patents_year': _to_int(_first_match(
            r'(?:报告期内|本年度|当年).{0,15}?新?[增获].{0,5}?专利\s*' + _NUM + r'\s*[项件个]',
            text,
        )),
        'pct_international': _to_int(_first_match(
            r'(?:PCT|国际)\s*(?:国际)?\s*(?:申请|专利).{0,5}?' + _NUM + r'\s*[项件个]', text
        )),
    }


def extract_rd_staff(text: str) -> Dict[str, Any]:
    """提取研发人员数量与占比。"""
    count = _to_int(_first_match(
        r'研发人员.{0,10}?(?:共|为|有)?\s*' + _NUM + r'\s*[人名]', text
    ))
    ratio = _to_float(_first_match(
        r'研发人员.{0,30}?占.{0,15}?' + _NUM + r'\s*%', text
    ))
    return {'rd_staff_count': count, 'rd_staff_ratio': ratio}


def extract_ipc_info(text: str) -> Dict[str, Any]:
    """提取 IPC 分类与技术领域。

    年报中 IPC 出现频率不高, 找不到时返回 None。
    """
    matches = _IPC_PATTERN.findall(text)
    if not matches:
        return {
            'ipc_primary': None,
            'ipc_primary_desc': None,
            'ipc_distribution': None,
            'tech_domain': None,
        }

    # 统计大类频次
    from collections import Counter
    code_counter: Counter[str] = Counter()
    for m in matches:
        normalized = re.sub(r'\s+', '', m)
        code_counter[normalized] += 1

    primary_code = code_counter.most_common(1)[0][0]
    # 描述与领域应与 primary_code 一致, 而非全局最常见section
    primary_section = primary_code[0]

    distribution = {code: cnt for code, cnt in code_counter.most_common(10)}

    return {
        'ipc_primary': primary_code,
        'ipc_primary_desc': IPC_SECTION_DESC.get(primary_section),
        'ipc_distribution': distribution,
        'tech_domain': IPC_TECH_DOMAIN.get(primary_section),
    }


def extract_key_tech_desc(text: str, max_len: int = 500) -> Optional[str]:
    """提取"核心技术"段落首句, 截断到 max_len 字符。"""
    # 长前缀优先: 避免 '核心技术' 抢占 '核心技术及其先进性' 的匹配
    for anchor in ('核心技术及其先进性', '关键技术', '主要技术', '核心技术'):
        idx = text.find(anchor)
        if idx >= 0:
            snippet = text[idx:idx + max_len + 100]
            # 取最早出现的终止符 (句号或双换行), 两者都不存在时 end=-1
            candidates = [snippet.find('。'), snippet.find('\n\n')]
            positives = [i for i in candidates if i > 0]
            end = min(positives) if positives else -1
            if end > 0:
                snippet = snippet[:end + 1]
            return snippet.strip()[:max_len]
    return None


def parse_annual_report(
    source: Any,
    code: Optional[str] = None,
    year: Optional[int] = None,
) -> Dict[str, Any]:
    """解析年报, 返回扁平 dict, 字段对齐 cn_stock_patents 表。

    Args:
        source: PDF 文件路径 (Path/str) 或已抽取的文本字符串
        code: 股票代码 (写入返回 dict)
        year: 财年

    Returns:
        dict 含字段: code, year, total_patents, invention_patents, ...
                   解析失败的字段值为 None。
    """
    if isinstance(source, Path):
        text = extract_text_from_pdf(source)
    elif isinstance(source, str):
        # 区分文件路径与纯文本: 路径通常较短且不含换行/NUL
        is_path_like = (
            len(source) < 1024 and '\n' not in source and '\x00' not in source
        )
        if is_path_like:
            try:
                p = Path(source)
                if p.is_file():
                    text = extract_text_from_pdf(p)
                else:
                    text = source
            except (OSError, ValueError):
                text = source
        else:
            text = source
    else:
        raise TypeError(f'source 必须是文件路径或文本, 收到: {type(source).__name__}')

    section_text = locate_rd_section(text)

    result: Dict[str, Any] = {'code': code, 'year': year}
    # 专利数量 / 研发人员：用全文匹配。专利统计表常位于"知识产权"等章节，
    # 可能落在 locate_rd_section 单一锚点窗口之外（见 300406 年报）；这些字段
    # 的正则前导词足够特异（累计/拥有/专利证书数量/研发人员…），全文匹配不易误命中。
    result.update(extract_patent_counts(text))
    result.update(extract_rd_staff(text))
    # IPC 分类 / 核心技术描述：仍限定在研发章节窗口，降低全文噪声。
    result.update(extract_ipc_info(section_text))
    result['key_tech_desc'] = extract_key_tech_desc(section_text)

    # 衍生字段
    total = result.get('total_patents') or 0
    inv = result.get('invention_patents') or 0
    if total > 0:
        result['invention_ratio'] = round(inv / total * 100, 2)
    else:
        result['invention_ratio'] = None

    result['data_source'] = 'annual_report'
    result['confidence_score'] = 95
    return result


if __name__ == '__main__':
    import argparse
    import json
    import sys

    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(name)s %(message)s')

    p = argparse.ArgumentParser(description='年报解析器')
    p.add_argument('--file', required=True, help='年报 PDF 路径')
    p.add_argument('--code', default=None)
    p.add_argument('--year', type=int, default=None)
    args = p.parse_args()

    data = parse_annual_report(args.file, code=args.code, year=args.year)
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))

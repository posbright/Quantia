#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 3b: WIPO IPC 分类映射 — IPC 代码 → 中文描述 / 技术领域归类。

设计参考: document/ai_moat_patent_enhancement_plan.md 2.4.4 / 3.5.2。

本模块属于 Compute 管道（见 AGENTS.md 规则 1），纯查表/字符串处理，
不发起任何网络请求，无第三方依赖。

IPC 结构: 部(Section, 1 字母) → 大类(Class, 2 数字) → 小类(Subclass, 1 字母)
    例: H04L  →  H=电学, 04=电通信技术, L=数字信息传输
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Optional, Tuple

# --- 部 (Section) ---------------------------------------------------------
IPC_SECTIONS: Dict[str, str] = {
    'A': '人类生活必需品',
    'B': '作业/运输',
    'C': '化学/冶金',
    'D': '纺织/造纸',
    'E': '固定建筑物',
    'F': '机械工程/照明/加热/武器/爆破',
    'G': '物理/仪器',
    'H': '电学',
}

# --- 部 → 技术领域归类 (tech_domain) --------------------------------------
TECH_DOMAIN_BY_SECTION: Dict[str, str] = {
    'A': '生物医药/消费',
    'B': '机械/运输',
    'C': '材料/化工',
    'D': '轻工/纺织',
    'E': '建筑/建材',
    'F': '机械/能源',
    'G': '电子/仪器',
    'H': '通信/电子',
}

# --- 常见大类 (3 字符, Section+Class) → 中文描述 --------------------------
# 覆盖 A 股高频技术领域, 缺失时回退到部级描述。
IPC_CLASS_DESC: Dict[str, str] = {
    'A01': '农业/林业/畜牧',
    'A23': '食品/食料',
    'A61': '医学/兽医/卫生',
    'A62': '救生/消防',
    'B01': '物理或化学的方法/装置',
    'B23': '机床/金属加工',
    'B25': '手工工具/便携式机动工具',
    'B29': '塑料加工',
    'B32': '层状产品',
    'B60': '一般车辆',
    'B62': '无轨陆用车辆',
    'B65': '输送/包装/储存',
    'C01': '无机化学',
    'C02': '水/废水处理',
    'C07': '有机化学',
    'C08': '有机高分子化合物',
    'C09': '染料/涂料/胶粘剂',
    'C12': '生物化学/微生物/基因工程',
    'C22': '冶金/铁合金',
    'C23': '金属镀覆/表面处理',
    'D01': '天然或人造的丝/纤维',
    'D06': '纺织品处理',
    'D21': '造纸/纤维素',
    'E01': '道路/铁路/桥梁',
    'E04': '建筑物',
    'E21': '土层或岩石的钻进/采矿',
    'F01': '发动机/泵',
    'F02': '内燃机',
    'F03': '液力/风力/弹力机械',
    'F16': '工程元件/部件',
    'F21': '照明',
    'F24': '供热/供暖/通风',
    'F25': '制冷/冷却',
    'G01': '测量/测试',
    'G02': '光学',
    'G03': '摄影/电影/光学照相',
    'G05': '控制/调节',
    'G06': '计算/推算/计数（含计算机）',
    'G08': '信号/信号装置',
    'G09': '教育/广告/显示',
    'G10': '乐器/声学',
    'G11': '信息存储',
    'G16': '特定应用领域的信息通信技术',
    'H01': '基本电气元件',
    'H02': '发电/变电/配电',
    'H03': '基本电子电路',
    'H04': '电通信技术',
    'H05': '其他电技术',
}

# --- 大类 → 技术领域 (覆盖部级以外的细分, 优先级高于部级) -----------------
TECH_DOMAIN_BY_CLASS: Dict[str, str] = {
    'A61': '生物医药',
    'C12': '生物医药',
    'C07': '化工/材料',
    'C08': '化工/材料',
    'H01': '电子元件',
    'H02': '电力/新能源',
    'H04': '通信',
    'G06': '计算机/AI',
    'G16': '计算机/AI',
    'G11': '半导体/存储',
    'G01': '仪器仪表',
    'G02': '光学/光电',
    'B60': '汽车/交通',
    'B62': '汽车/交通',
}

_IPC_RE = re.compile(r'([A-H])\s*(\d{2})\s*([A-Z])?')


def parse_ipc_code(code: str) -> Optional[Tuple[str, str, Optional[str]]]:
    """解析 IPC 代码, 返回 (section, class3, subclass)。无法识别返回 None。

    Args:
        code: 如 'H04L', 'H04L 29/06', 'g06f', 'H 04 L'

    Returns:
        ('H', 'H04', 'L')  或  ('H', 'H04', None)
    """
    if not code or not isinstance(code, str):
        return None
    m = _IPC_RE.match(code.strip().upper())
    if not m:
        return None
    section = m.group(1)
    class3 = f'{section}{m.group(2)}'
    subclass = f'{class3}{m.group(3)}' if m.group(3) else None
    return section, class3, subclass


def ipc_to_desc(code: str) -> Optional[str]:
    """IPC 代码 → 中文描述。优先大类级, 回退到部级。"""
    parsed = parse_ipc_code(code)
    if not parsed:
        return None
    section, class3, _ = parsed
    return IPC_CLASS_DESC.get(class3) or IPC_SECTIONS.get(section)


def ipc_to_tech_domain(code: str) -> Optional[str]:
    """IPC 代码 → 技术领域归类。优先大类级映射, 回退到部级。"""
    parsed = parse_ipc_code(code)
    if not parsed:
        return None
    section, class3, _ = parsed
    return TECH_DOMAIN_BY_CLASS.get(class3) or TECH_DOMAIN_BY_SECTION.get(section)


def build_ipc_distribution(codes: List[str], top_n: int = 10) -> Dict[str, int]:
    """统计一组 IPC 代码的大类(3 字符)分布, 返回 {class3: count} (按频次降序)。"""
    counter: Counter[str] = Counter()
    for code in codes or []:
        parsed = parse_ipc_code(code)
        if parsed:
            counter[parsed[1]] += 1
    return dict(counter.most_common(top_n))


def primary_ipc(codes: List[str]) -> Dict[str, Optional[str]]:
    """从一组 IPC 代码计算主分类及描述/领域。

    Returns:
        {'ipc_primary', 'ipc_primary_desc', 'tech_domain', 'ipc_distribution'}
    """
    distribution = build_ipc_distribution(codes)
    if not distribution:
        return {
            'ipc_primary': None, 'ipc_primary_desc': None,
            'tech_domain': None, 'ipc_distribution': None,
        }
    primary_class = next(iter(distribution))
    return {
        'ipc_primary': primary_class,
        'ipc_primary_desc': ipc_to_desc(primary_class),
        'tech_domain': ipc_to_tech_domain(primary_class),
        'ipc_distribution': distribution,
    }

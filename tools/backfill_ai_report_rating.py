#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回填历史 AI 报告中缺失的 rating / rating_score。

背景：cn_stock_ai_report 早期由旧版 report_parser._extract_rating 解析，
该逻辑仅在固定"六、"小节或正文前 1200 字内查找评级，导致结论小节序号不固定
（五/六/七）或结论行靠后的报告 rating / rating_score 全部落库为 NULL，
关注列表与个股页因此不显示 AI 评级 / 评分。

本脚本对 rating 为 NULL 的历史报告重新运行（已修复的）解析逻辑，仅当能解析出
评级时才回填 rating 与 rating_score，不触碰其它字段。

用法：
    python tools/backfill_ai_report_rating.py            # 干跑（只打印将更新的内容）
    python tools/backfill_ai_report_rating.py --apply    # 实际写库
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quantia.lib.database as mdb  # noqa: E402
from quantia.lib.ai.report_parser import (  # noqa: E402
    _extract_rating,
    _extract_rating_score,
)

APPLY = '--apply' in sys.argv


def main() -> int:
    rows = mdb.executeSqlFetch(
        "SELECT id, code, report_md FROM cn_stock_ai_report WHERE rating IS NULL"
    )
    rows = rows or []
    to_update = []
    for rid, code, md in rows:
        rating = _extract_rating(md or '')
        if rating is None:
            continue  # 确无评级（降级版 / 生成失败报告），保持 NULL
        score = _extract_rating_score(md or '')
        to_update.append((rid, code, rating, score))

    print(f"扫描 rating=NULL 报告 {len(rows)} 条，可回填 {len(to_update)} 条：")
    for rid, code, rating, score in to_update:
        print(f"  id={rid} code={code} -> rating={rating} rating_score={score}")

    if not to_update:
        print("无需回填。")
        return 0

    if not APPLY:
        print("\n[干跑] 未写库。加 --apply 实际执行。")
        return 0

    for rid, code, rating, score in to_update:
        mdb.executeSql(
            "UPDATE cn_stock_ai_report SET rating=%s, rating_score=%s WHERE id=%s",
            (rating, score, rid),
        )
    print(f"\n[已写库] 更新 {len(to_update)} 条。")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""
A股公告事件采集（东方财富数据中心）
数据来源：AkShare — stock_notice_report (东方财富公告大全)
目标数据库：quantiadb.cn_stock_announcement

采集类别：
  重大事项 / 财务报告 / 融资公告 / 风险提示 / 资产重组 / 信息变更 / 持股变动

风险标签自动分类：
  risk    — ST预警/处罚/退市/违规/诉讼/业绩预亏
  opportunity — 专利/中标/重大合同/增持/回购
  neutral — 其他一般公告

用法：
  python stock_announcement_em.py                    # 采集今日
  python stock_announcement_em.py --date 20260520   # 采集指定日期
  python stock_announcement_em.py --days 7          # 采集最近7天
  python stock_announcement_em.py --test            # 测试模式(仅打印不入库)
"""

import logging
import time
import argparse
import os
import sys
from datetime import datetime, timedelta

import akshare as ak
import pandas as pd

# 确保项目根目录在 sys.path 中
cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)

import quantia.lib.database as mdb

__author__ = 'Quantia'
__date__ = '2026/05/25'

log = logging.getLogger(__name__)

# ─── 公告类别 ─────────────────────────────────────────────────────────────────
NOTICE_CATEGORIES = [
    "重大事项", "财务报告", "融资公告",
    "风险提示", "资产重组", "信息变更", "持股变动",
]

# ─── 风险标签关键词 ─────────────────────────────────────────────────────────────
_RISK_KEYWORDS = [
    'ST', '*ST', '退市', '处罚', '违规', '立案', '调查', '诉讼',
    '仲裁', '冻结', '预亏', '预减', '首亏', '续亏', '暂停上市',
    '终止上市', '行政监管', '警示函', '风险提示',
]

_OPPORTUNITY_KEYWORDS = [
    '专利', '中标', '重大合同', '增持', '回购', '利好',
    '预增', '扭亏', '略增', '续盈', '授权', '突破',
    '政策', '补贴', '激励', '战略合作', '签约',
]


def classify_tag(title: str, ann_type: str) -> str:
    """根据标题和公告类型自动分类风险标签。"""
    text = f"{title} {ann_type}"
    for kw in _RISK_KEYWORDS:
        if kw in text:
            return 'risk'
    for kw in _OPPORTUNITY_KEYWORDS:
        if kw in text:
            return 'opportunity'
    return 'neutral'


# ─── 建表 DDL ──────────────────────────────────────────────────────────────────
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS cn_stock_announcement (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    code        VARCHAR(6) NOT NULL,
    ann_date    DATE NOT NULL,
    title       VARCHAR(200) NOT NULL,
    ann_type    VARCHAR(30) DEFAULT '',
    tag         VARCHAR(20) DEFAULT 'neutral',
    url         VARCHAR(300) DEFAULT '',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_code_date_title (code, ann_date, title(100)),
    KEY idx_code_date (code, ann_date),
    KEY idx_tag_date (tag, ann_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
"""


def create_announcement_table():
    """创建公告事件表（幂等）。"""
    mdb.executeSql(_CREATE_TABLE_SQL)
    log.info("cn_stock_announcement 表已就绪")


# ─── 数据采集 ──────────────────────────────────────────────────────────────────
def fetch_announcements_for_date(date_str: str) -> pd.DataFrame:
    """采集指定日期的所有公告（按类别分批拉取）。

    Args:
        date_str: 日期字符串 'YYYYMMDD'

    Returns:
        合并后的 DataFrame，含 code/ann_date/title/ann_type/tag/url 列
    """
    all_dfs = []
    for cat in NOTICE_CATEGORIES:
        try:
            df = ak.stock_notice_report(symbol=cat, date=date_str)
            if df is not None and not df.empty:
                df = df.rename(columns={
                    '代码': 'code', '名称': 'name',
                    '公告标题': 'title', '公告类型': 'ann_type',
                    '公告日期': 'ann_date', '网址': 'url',
                })
                df['ann_type_cat'] = cat
                all_dfs.append(df)
            time.sleep(0.5)
        except Exception as e:
            log.warning(f"采集 {date_str} {cat} 失败: {e}")
            time.sleep(1)

    if not all_dfs:
        return pd.DataFrame()

    merged = pd.concat(all_dfs, ignore_index=True)
    # 去重（同一公告可能出现在多个类别中）
    merged = merged.drop_duplicates(subset=['code', 'ann_date', 'title'])

    # 分类标签
    merged['tag'] = merged.apply(
        lambda row: classify_tag(row.get('title', ''), row.get('ann_type', '')),
        axis=1,
    )

    # 仅保留 A 股（6位纯数字代码）
    merged = merged[merged['code'].str.match(r'^\d{6}$', na=False)]

    return merged[['code', 'ann_date', 'title', 'ann_type', 'tag', 'url']]


# ─── 入库 ────────────────────────────────────────────────────────────────────
_UPSERT_SQL = """
INSERT IGNORE INTO cn_stock_announcement (code, ann_date, title, ann_type, tag, url)
VALUES (%s, %s, %s, %s, %s, %s)
"""


def save_announcements(df: pd.DataFrame) -> int:
    """批量入库公告数据，返回新增行数。"""
    if df.empty:
        return 0

    rows = []
    for _, row in df.iterrows():
        ann_date = row['ann_date']
        if isinstance(ann_date, str):
            ann_date = ann_date[:10]  # '2026-05-20' or '2026-05-20 00:00:00'
        rows.append((
            str(row['code']),
            ann_date,
            str(row['title'])[:200],
            str(row.get('ann_type', ''))[:30],
            str(row.get('tag', 'neutral'))[:20],
            str(row.get('url', ''))[:300],
        ))

    # 批量 INSERT IGNORE（每批最多 200 条，一条 SQL 语句）
    count = 0
    batch_size = 200
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        placeholders = ', '.join(['(%s, %s, %s, %s, %s, %s)'] * len(batch))
        flat_params = [v for r in batch for v in r]
        batch_sql = (
            "INSERT IGNORE INTO cn_stock_announcement "
            "(code, ann_date, title, ann_type, tag, url) VALUES "
            + placeholders
        )
        try:
            mdb.executeSql(batch_sql, flat_params)
            count += len(batch)
        except Exception as e:
            log.warning(f"批量插入公告失败(batch={len(batch)}): {e}")
            # 降级为逐条插入
            for r in batch:
                try:
                    mdb.executeSql(_UPSERT_SQL, r)
                    count += 1
                except Exception as e2:
                    if 'Duplicate' not in str(e2):
                        log.debug(f"插入公告失败: {e2}")
    return count


# ─── 主流程 ──────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='A股公告事件采集')
    parser.add_argument('--date', type=str, default=None, help='指定日期 YYYYMMDD')
    parser.add_argument('--days', type=int, default=1, help='采集最近N天 (默认1)')
    parser.add_argument('--test', action='store_true', help='测试模式(仅打印不入库)')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

    # 建表
    if not args.test:
        create_announcement_table()

    # 确定要采集的日期列表
    if args.date:
        dates = [args.date]
    else:
        today = datetime.now()
        dates = [(today - timedelta(days=i)).strftime('%Y%m%d') for i in range(args.days)]

    total_saved = 0
    for d in dates:
        log.info(f"采集 {d} 公告...")
        df = fetch_announcements_for_date(d)
        log.info(f"  获取 {len(df)} 条公告 (risk={len(df[df['tag']=='risk']) if not df.empty else 0}, "
                 f"opportunity={len(df[df['tag']=='opportunity']) if not df.empty else 0})")

        if args.test:
            if not df.empty:
                filtered = df[df['tag'] != 'neutral'].head(20)
                print(filtered[['code', 'ann_date', 'tag', 'title']].to_string(max_colwidth=40))
        else:
            n = save_announcements(df)
            total_saved += n
            log.info(f"  入库 {n} 条")
        time.sleep(1)

    if not args.test:
        log.info(f"完成，共入库 {total_saved} 条公告")


if __name__ == '__main__':
    main()

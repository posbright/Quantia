#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
综合选股评分结果 Job（M2）。

职责：
- 读取 cn_stock_selection 最新交易日快照
- 调用 core.selection_scoring 生成评分结果
- 幂等写入 cn_stock_selection_score（按 date 全量覆盖）
"""
from __future__ import annotations

import logging
import os.path
import sys

import pandas as pd

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)

import quantia.core.tablestructure as tbs
import quantia.core.selection_scoring as scoring
import quantia.lib.database as mdb
import quantia.lib.run_template as runt


__author__ = 'Quantia'
__date__ = '2026/06/02'


def _load_latest_selection_panel() -> pd.DataFrame:
    table_name = tbs.TABLE_CN_STOCK_SELECTION['name']
    sql = f"""
        SELECT * FROM `{table_name}`
        WHERE `date` = (SELECT MAX(`date`) FROM `{table_name}`)
        ORDER BY `code`
    """
    df = pd.read_sql(sql=sql, con=mdb.engine())
    if not df.empty and 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'])
    return df


def _load_prev_scores(score_date: pd.Timestamp) -> pd.DataFrame:
    if not mdb.checkTableIsExist(scoring.SELECTION_SCORE_TABLE):
        return pd.DataFrame()
    sql = f"""
        SELECT `code`, `industry`, `total_score`, `industry_rank`
        FROM `{scoring.SELECTION_SCORE_TABLE}`
        WHERE `date` = (
            SELECT MAX(`date`) FROM `{scoring.SELECTION_SCORE_TABLE}`
            WHERE `date` < %s
        )
    """
    df = pd.read_sql(sql=sql, con=mdb.engine(), params=(pd.to_datetime(score_date).date(),))
    if not df.empty:
        df['code'] = df['code'].astype(str)
    return df


def save_nph_selection_score(date, before=True):
    """run_template 入口。before 阶段不执行，after 阶段落库评分。

    命名以 ``save_nph_`` 开头是刚需：run_template.run_with_args 仅对该前缀的
    入口函数在"当前/批量"模式下显式传入 before=False；否则 before 取默认 True
    → 直接 return，导致评分表永不创建。
    """
    if before:
        return

    try:
        panel = _load_latest_selection_panel()
        if panel.empty:
            logging.warning('selection_score_job: cn_stock_selection 最新快照为空，跳过')
            return

        scoring.ensure_selection_score_table(mdb)

        result = scoring.build_daily_selection_scores(panel, weight_template='balanced', alpha=0.6)
        if result.empty:
            logging.warning('selection_score_job: 评分结果为空，跳过')
            return

        score_date = pd.to_datetime(result['date']).max()
        prev_scores = _load_prev_scores(score_date)
        result = scoring.apply_ema_and_rank_change(result, prev_scores=prev_scores, ema_span=5)

        score_date = pd.to_datetime(result['date']).max().date()
        del_sql = f"DELETE FROM `{scoring.SELECTION_SCORE_TABLE}` WHERE `date` = %s"
        mdb.executeSql(del_sql, (score_date,))

        # 表已由 ensure 创建，cols_type 置 None 走 append/upsert。
        mdb.insert_db_from_df(result, scoring.SELECTION_SCORE_TABLE, None, False, '`date`,`code`')
        logging.info(f'selection_score_job: 写入 {len(result)} 条评分结果，date={score_date}')
    except Exception:
        logging.error('selection_score_job 处理异常', exc_info=True)


def main():
    runt.run_with_args(save_nph_selection_score)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPT综合选股作业

基于 cn_stock_selection 表中的财务数据，执行基本面筛选策略。
筛选条件基于 ChatGP选股策略文档.md 定义的标准。
"""

import logging
import pandas as pd
import os.path
import sys

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
import quantia.lib.run_template as runt
import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
from quantia.core.strategy.gpt_value_strategy import filter_gpt_value_stocks, GPT_INDICATOR_FIELDS

__author__ = 'Quantia'
__date__ = '2026/02/14'


def prepare(date):
    """
    执行GPT综合选股

    从 cn_stock_selection 表读取数据，执行基本面筛选，
    将结果保存到 cn_stock_strategy_gpt_value 表。

    如果指定日期无数据，会自动回退到最近7天内有数据的交易日。
    """
    try:
        date_str = date.strftime("%Y-%m-%d")
        table_name = tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE['name']
        source_table = 'cn_stock_selection'

        # 检查源表是否存在
        if not mdb.checkTableIsExist(source_table):
            logging.warning(f"源表 {source_table} 不存在，跳过GPT综合选股。"
                            f"请确认 fetch_daily_job（或 execute_daily_job）已执行 selection_data_daily_job")
            return

        # 从 cn_stock_selection 读取数据
        selection_data, actual_date_str = _load_selection_data(source_table, date_str)

        if selection_data is None or len(selection_data) == 0:
            logging.warning(f"GPT综合选股：{date_str} 无选股数据（近7天均无）。"
                            f"请检查 selection_data_daily_job 是否正常执行，"
                            f"或 fetch_stock_selection() 是否因网络/代理问题获取失败")
            return

        logging.info(f"GPT综合选股：使用 {actual_date_str} 的选股数据"
                     f"{'（回退日期）' if actual_date_str != date_str else ''}"
                     f"，共 {len(selection_data)} 条")

        # 执行基本面筛选
        filtered = filter_gpt_value_stocks(selection_data)

        if filtered is None or len(filtered) == 0:
            logging.info(f"GPT综合选股：{actual_date_str} 无符合条件的股票")
            return

        logging.info(f"GPT综合选股：{actual_date_str} 筛选出 {len(filtered)} 只股票")

        # 如果使用了回退日期，把 date 列统一为请求日期，
        # 避免结果表存入旧日期导致前端按当日查不到
        if actual_date_str != date_str:
            filtered = filtered.copy()
            filtered['date'] = date_str

        # 准备结果数据（基础字段 + 评分 + 指标值）
        result_columns = ['date', 'code', 'name'] + GPT_INDICATOR_FIELDS
        result_data = filtered[['date', 'code', 'name']].copy()
        # 确保所有指标列都存在（缺失的填 None），避免建表时缺列导致反复 DROP
        for col in GPT_INDICATOR_FIELDS:
            result_data[col] = filtered[col] if col in filtered.columns else None

        # 按综合评分降序排序
        if 'gpt_score' in result_data.columns:
            result_data = result_data.sort_values('gpt_score', ascending=False, na_position='last')

        # 删除老数据，检查表 schema
        if mdb.checkTableIsExist(table_name):
            # 检查表列数是否匹配（旧表可能缺少 gpt_score 等列）
            _check_and_rebuild_table(table_name)

        if mdb.checkTableIsExist(table_name):
            del_sql = f"DELETE FROM `{table_name}` WHERE `date` = %s"
            mdb.executeSql(del_sql, (date_str,))
            cols_type = None
        else:
            # 表不存在（首次或刚被重建），获取列类型定义
            cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE['columns'])

        # 添加回测字段（空值）
        _columns_backtest = list(tbs.TABLE_CN_STOCK_BACKTEST_DATA['columns'])
        result_data = result_data.reindex(columns=list(result_data.columns) + _columns_backtest)

        # 插入数据
        mdb.insert_db_from_df(result_data, table_name, cols_type, False, "`date`,`code`")

        logging.info(f"GPT综合选股：{date_str} 成功保存 {len(result_data)} 条记录"
                     f"{'（源数据日期: ' + actual_date_str + '）' if actual_date_str != date_str else ''}")

    except Exception as e:
        logging.error(f"gpt_value_data_job.prepare 处理异常", exc_info=True)


def _load_selection_data(source_table, date_str):
    """
    从 cn_stock_selection 加载数据，支持日期回退。

    如果 date_str 当天无数据，自动查找最近7天内最新的有数据日期。
    这样即使 selection_data_daily_job 某天失败，GPT选股仍可使用前一天的数据。

    Returns:
        (DataFrame, actual_date_str) 或 (None, date_str)
    """
    # 先尝试精确日期
    sql = f"SELECT * FROM `{source_table}` WHERE `date` = %s"
    data = pd.read_sql(sql, mdb.engine(), params=(date_str,))
    if data is not None and len(data) > 0:
        return data, date_str

    # 当天无数据 → 查最近7天内最新的日期
    fallback_sql = (
        f"SELECT MAX(`date`) AS latest FROM `{source_table}` "
        f"WHERE `date` >= DATE_SUB(%s, INTERVAL 7 DAY) AND `date` < %s"
    )
    try:
        result = pd.read_sql(fallback_sql, mdb.engine(), params=(date_str, date_str))
        if result is not None and len(result) > 0 and result.iloc[0]['latest'] is not None:
            latest = result.iloc[0]['latest']
            if hasattr(latest, 'strftime'):
                fallback_date = latest.strftime("%Y-%m-%d")
            else:
                fallback_date = str(latest)
            logging.info(f"GPT综合选股：{date_str} 无数据，回退到最近有数据的日期 {fallback_date}")
            data = pd.read_sql(sql, mdb.engine(), params=(fallback_date,))
            if data is not None and len(data) > 0:
                return data, fallback_date
    except Exception as e:
        logging.warning(f"GPT综合选股：日期回退查询异常: {e}")

    # 记录诊断信息：表中最新日期
    try:
        diag_sql = f"SELECT MAX(`date`) AS latest, COUNT(DISTINCT `date`) AS days FROM `{source_table}`"
        diag = pd.read_sql(diag_sql, mdb.engine())
        if diag is not None and len(diag) > 0:
            latest = diag.iloc[0]['latest']
            days = diag.iloc[0]['days']
            logging.warning(f"GPT综合选股诊断：{source_table} 表最新日期={latest}，共有 {days} 个交易日数据")
    except Exception:
        logging.debug("GPT综合选股诊断查询异常", exc_info=True)

    return None, date_str


def _check_and_rebuild_table(table_name):
    """检查表结构，缺少列时删除重建"""
    try:
        import pymysql
        expected_cols = set(tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE['columns'].keys())
        with pymysql.connect(**mdb.MYSQL_CONN_DBAPI) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COLUMN_NAME FROM information_schema.columns "
                    "WHERE table_schema=%s AND table_name=%s",
                    (mdb.db_database, table_name)
                )
                db_cols = set(row[0] for row in cur.fetchall())
        missing = expected_cols - db_cols
        if missing:
            logging.info(f"GPT选股表缺少 {len(missing)} 列（如 {list(missing)[:5]}），删除重建")
            mdb.executeSql(f"DROP TABLE `{table_name}`")
    except Exception as e:
        logging.warning(f"检查GPT选股表结构异常：{e}")


def main():
    """执行GPT综合选股作业"""
    runt.run_with_args(prepare)


if __name__ == '__main__':
    main()

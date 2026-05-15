#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复 cn_stock_selection 表: 重建完整schema并填充数据

问题: 现有表只有15个基础价格列,缺少200+个财务指标列
解决: 删除旧表 → 重新从API获取完整数据 → 分批插入 → 复制到目标日期
"""
import sys
import os
import time
import logging
import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
logging.basicConfig(format='%(asctime)s [%(levelname)s] %(message)s', level=logging.INFO)

import quantia.lib.database as mdb
import quantia.core.tablestructure as tbs

TARGET_DATES = ['2026-03-02', '2026-03-03']


def count_rows(table, date_str):
    try:
        r = mdb.executeSqlFetch(f"SELECT COUNT(*) FROM `{table}` WHERE `date` = %s", (date_str,))
        return r[0][0] if r else 0
    except:
        return -1


def step1_rebuild_selection_table():
    """Drop old table and fetch fresh data with full schema"""
    print("\n" + "=" * 60)
    print("[Step 1] 重建 cn_stock_selection 表")
    print("=" * 60)

    table_name = tbs.TABLE_CN_STOCK_SELECTION['name']

    # Drop old table with wrong schema
    print("  删除旧表(只有15列)...")
    try:
        mdb.executeSql(f"DROP TABLE IF EXISTS `{table_name}`")
        print("  [OK] 旧表已删除")
    except Exception as e:
        print(f"  [WARN] 删表失败: {e}")

    # Fetch fresh data from API
    print("  从东方财富API获取选股数据...")
    import quantia.core.stockfetch as stf
    start = time.time()
    data = stf.fetch_stock_selection()
    elapsed = time.time() - start

    if data is None or len(data) == 0:
        print(f"  [FAIL] 未获取到数据, 耗时 {elapsed:.1f}s")
        return None

    api_date = str(data.iloc[0]['date']) if 'date' in data.columns else datetime.date.today().strftime("%Y-%m-%d")
    print(f"  [OK] 获取到 {len(data)} 条, {len(data.columns)} 列, date={api_date}, 耗时 {elapsed:.1f}s")

    # Insert in chunks using pandas to_sql directly (no upsert needed for new table)
    print(f"  分批写入数据库(每批200行)...")
    cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_SELECTION['columns'])
    engine_mysql = mdb.engine()

    try:
        data.to_sql(
            name=table_name,
            con=engine_mysql,
            if_exists='append',  # table doesn't exist, will create
            index=False,
            dtype=cols_type,
            chunksize=200
        )
        # Add primary key
        mdb.executeSql(f"ALTER TABLE `{table_name}` ADD PRIMARY KEY (`date`,`code`)")
        count = count_rows(table_name, api_date)
        print(f"  [OK] 写入 {count} 条到 {table_name} (date={api_date}), 共 {len(data.columns)} 列")
        return api_date
    except Exception as e:
        print(f"  [FAIL] 写入失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def step2_copy_to_dates(source_date):
    """Copy selection data to target dates using SQL"""
    print("\n" + "=" * 60)
    print("[Step 2] 复制数据到目标日期")
    print("=" * 60)

    table_name = 'cn_stock_selection'

    if source_date is None:
        r = mdb.executeSqlFetch(f"SELECT MAX(date) FROM `{table_name}`")
        if r and r[0][0]:
            source_date = str(r[0][0])
        else:
            print("  [FAIL] 无可用数据")
            return False

    source_count = count_rows(table_name, source_date)
    print(f"  源数据: {source_date}, {source_count} 条")

    # Get columns
    col_result = mdb.executeSqlFetch(
        "SELECT COLUMN_NAME FROM information_schema.columns "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION",
        (mdb.db_database, table_name)
    )
    columns = [row[0] for row in col_result]
    print(f"  表有 {len(columns)} 列")

    for td in TARGET_DATES:
        if td == source_date:
            print(f"  {td}: 跳过(与源日期相同)")
            continue

        existing = count_rows(table_name, td)
        if existing > 0:
            mdb.executeSql(f"DELETE FROM `{table_name}` WHERE `date` = %s", (td,))

        sel = []
        for col in columns:
            if col == 'date':
                sel.append(f"'{td}' AS `date`")
            else:
                sel.append(f"`{col}`")

        insert_sql = (
            f"INSERT INTO `{table_name}` ({', '.join('`' + c + '`' for c in columns)}) "
            f"SELECT {', '.join(sel)} FROM `{table_name}` WHERE `date` = %s"
        )
        mdb.executeSql(insert_sql, (source_date,))
        new_count = count_rows(table_name, td)
        print(f"  [OK] {td}: 复制 {new_count} 条")

    return True


def step3_gpt_value():
    """Run GPT value filter"""
    print("\n" + "=" * 60)
    print("[Step 3] GPT综合选股")
    print("=" * 60)

    import quantia.job.gpt_value_data_job as gptj

    for date_str in TARGET_DATES:
        sel_count = count_rows('cn_stock_selection', date_str)
        if sel_count <= 0:
            print(f"  {date_str}: 无选股数据, 跳过")
            continue

        print(f"  {date_str}: {sel_count} 条选股数据, 执行GPT筛选...")
        try:
            run_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
            gptj.prepare(run_date)
            cnt = count_rows('cn_stock_strategy_gpt_value', date_str)
            print(f"  [OK] {date_str}: {cnt} 条GPT选股")
        except Exception as e:
            print(f"  [FAIL] {date_str}: {e}")
            import traceback
            traceback.print_exc()


def step4_spot_buy():
    """Copy spot_buy data from available date"""
    print("\n" + "=" * 60)
    print("[Step 4] 基本面选股")
    print("=" * 60)

    table_name = 'cn_stock_spot_buy'
    source_date = '2026-02-13'
    source_count = count_rows(table_name, source_date)

    if source_count <= 0:
        print(f"  [SKIP] {source_date} 无 {table_name} 数据")
        return

    print(f"  注: cn_stock_spot 3/2~3/3 财务指标(pe9/roe_weight)全为0, 正常筛选无结果")
    print(f"  从 {source_date} ({source_count}条) 复制")

    for td in TARGET_DATES:
        existing = count_rows(table_name, td)
        if existing > 0:
            print(f"  {td}: 已有 {existing} 条 [OK]")
            continue

        col_result = mdb.executeSqlFetch(
            "SELECT COLUMN_NAME FROM information_schema.columns "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION",
            (mdb.db_database, table_name)
        )
        columns = [row[0] for row in col_result]
        sel = []
        for col in columns:
            if col == 'date':
                sel.append(f"'{td}' AS `date`")
            else:
                sel.append(f"`{col}`")

        insert_sql = (
            f"INSERT INTO `{table_name}` ({', '.join('`' + c + '`' for c in columns)}) "
            f"SELECT {', '.join(sel)} FROM `{table_name}` WHERE `date` = %s"
        )
        mdb.executeSql(insert_sql, (source_date,))
        cnt = count_rows(table_name, td)
        print(f"  [OK] {td}: {cnt} 条")


def step5_verify():
    """Verify all data"""
    print("\n" + "=" * 60)
    print("[Step 5] 数据验证")
    print("=" * 60)

    tables = [
        ('cn_stock_selection', '综合选股'),
        ('cn_stock_strategy_gpt_value', 'GPT综合选股'),
        ('cn_stock_spot_buy', '基本面选股'),
    ]

    all_ok = True
    for tbl, cn in tables:
        print(f"\n  [{cn}] ({tbl}):")
        for ds in TARGET_DATES:
            cnt = count_rows(tbl, ds)
            status = "OK" if cnt > 0 else "MISSING"
            if cnt <= 0:
                all_ok = False
            print(f"    {ds}: {cnt} 条 [{status}]")

    # Also check column count for selection table
    r = mdb.executeSqlFetch(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'cn_stock_selection'",
        (mdb.db_database,)
    )
    col_count = r[0][0] if r else 0
    print(f"\n  cn_stock_selection 列数: {col_count}")

    if all_ok:
        print("\n  === 所有数据完整! ===")
    else:
        print("\n  === 部分数据缺失 ===")
    return all_ok


if __name__ == '__main__':
    start = time.time()

    try:
        mdb.executeSqlFetch("SELECT 1")
        print("[OK] 数据库连接正常")
    except Exception as e:
        print(f"[FAIL] 数据库连接失败: {e}")
        sys.exit(1)

    api_date = step1_rebuild_selection_table()
    step2_copy_to_dates(api_date)
    step3_gpt_value()
    step4_spot_buy()
    step5_verify()

    print(f"\n总耗时: {time.time() - start:.1f}s")

---
description: "Use when writing Python code that persists DataFrames to MySQL via to_sql, df.to_sql, _mysql_upsert, or any insert/upsert into the Quantia MySQL database. Enforces chunksize=500, NaN/inf sanitation, finite-at-source ratios."
applyTo: "quantia/**/*.py, tests/**/*.py"
---
# DB 写入规范（MySQL/PyMySQL）

## chunksize 强制要求
- 任何 `df.to_sql(...)` 调用都**必须**带 `chunksize=_DB_INSERT_CHUNKSIZE`（=500，定义在 [quantia/lib/database.py](../../quantia/lib/database.py)）。
- 缺失 chunksize 会让 `_mysql_upsert` 把所有行拼成单条巨型 INSERT，触发 1.6 GB 远程服务器 OOM（回归历史：commit `bba51731`，2026-04-23 修复）。
- 标准写法：

  ```python
  from quantia.lib.database import _DB_INSERT_CHUNKSIZE
  df.to_sql(table_name, conn, if_exists="append", index=False,
            chunksize=_DB_INSERT_CHUNKSIZE, method=_mysql_upsert)
  ```

## NaN / Inf 处理
- MySQL/PyMySQL 拒绝 `NaN`、`+inf`、`-inf`（错误信息：`inf can not be used with MySQL`）。
- **在源头**保证有限：策略比率、指标除法计算时就用安全除法（`np.where(denom==0, np.nan, num/denom)`，再决定 fillna 还是丢弃），**不要**把任务推给 DB 层。
- [quantia/lib/database.py](../../quantia/lib/database.py) 中已有写前 guard，但只是兜底——绕过它（直接 raw SQL、绕开统一入口）就会再次踩雷。
- **不要**在 handler 里悄悄 `fillna(0)` 把比率类列变成 0——会污染下游回测结果。

## 上下文常见反例
```python
# ❌ 缺 chunksize
df.to_sql("cn_stock_xxx", conn, if_exists="append", index=False)

# ❌ 用 0 填充比率（污染回测）
df["ratio"] = df["ratio"].replace([np.inf, -np.inf], 0)

# ❌ 让 DB 层吞掉无穷
df.to_sql(..., chunksize=500)  # 调用前未 sanitize，触发 PyMySQL 报错
```

## 测试参考
- [tests/test_mysql_nonfinite_guard.py](../../tests/test_mysql_nonfinite_guard.py) 覆盖 NaN/inf guard 行为；新增写入路径时同步补例。

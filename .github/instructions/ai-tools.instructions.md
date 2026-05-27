---
description: "Use when editing AI agent tools (quantia/lib/ai/tools/*.py), agent prompts (quantia/lib/ai/prompt/*.md), or the agent runtime (quantia/lib/ai/agent.py). Enforces validate-first principle, schema-aware SQL, prompt anti-hallucination patterns, and tool output contracts."
applyTo: "quantia/lib/ai/tools/**/*.py, quantia/lib/ai/prompt/**/*.md, quantia/lib/ai/agent.py, quantia/lib/ai/providers/**/*.py"
---
# AI 工具与 Agent 开发规范

## 核心原则：先验证，后执行

所有数据来源、字段映射、表结构访问必须经过真实验证，**不允许**猜测或估计。

### 在 sql_query 工具中
- `sql_query.py` 执行任何 SQL 前，先通过 `INFORMATION_SCHEMA.COLUMNS` 校验引用列名是否在目标表中存在。
- 列名不存在时，返回包含**实际可用列名**的错误信息，引导 LLM 自行修正。
- **不要**用 try/except + 事后修补的方式处理列错误（如旧的 `_strip_concept_column`）——这把问题推迟到执行阶段并浪费 DB round-trip。
- schema 缓存在进程生命周期内有效（`_SCHEMA_CACHE`），重启即刷新。

### 在其他工具中
- 工具的 SQL 查询使用**显式列列表**（如 `_query_latest_spot` 里的 SELECT），不要用 `SELECT *`。
- 列名变更时，对应的 `keys` 列表必须同步修改。
- 对于可能不存在的表/列（如 `cn_stock_patent_info`），使用 try/except 优雅降级，返回空字典而非报错。

## 提示词（Prompt）防幻觉规则

### 必须做
1. 凡提示词中提到 `sql_query` 可查的表，**必须**附带完整列名清单 + 明确排除的常见猜测列名。
2. 使用"**没有** `xxx`/`yyy` 列"的负面约束句式，比正面列举更能抑制幻觉。
3. 列名表用 `code, name, new_price, ...` 格式（逗号分隔），括号注释中文含义。
4. 添加"验证优先"说明：告知 LLM 系统会预校验列名，猜测会导致查询被拒绝。

### 禁止做
- 不要在提示词中出现"等表"这类模糊引导——LLM 会推断出不存在的表/列。
- 不要只写"查询 cn_stock_fund_flow"而不给列名——LLM 会猜 `main_inflow`/`net_flow` 等不存在的列名。
- 不要用"板块数据"等需要 LLM 映射到具体表/列的模糊术语——要么给出精确表名+列名，要么不提。
- 不要假设 `tablestructure.py` 定义的列在实际部署的 DB 中都存在——`concept` 列就是反例。

## 工具输出契约

### sql_query
```python
{
    'sql': str,        # 实际执行的（可能被 LIMIT 修改的）SQL
    'row_count': int,  # 返回行数
    'rows': list,      # list[dict]，列名为键
}
```
- 错误时抛 `ToolError`，message 里包含可用列名提示。

### stock_profile
- 字段名是**重映射后的**中间名（如 `pe` 不是 DB 中的 `pe9`），提示词里要用工具返回的实际字段名。
- `_字段说明` 子字典提供中文对照，LLM 在报告中必须用中文名称。

### kline_fetch
- 返回 `bars: list[{date, open, high, low, close, volume}]`。
- NaN/None 已被剔除，LLM 不会收到无效值。

## Agent Runtime 约束
- `max_rounds=4`：超过 4 轮工具调用后强制终止并输出现有内容。
- 工具调用失败时，agent 可重试（自动），但同一工具+同一参数不应重试超过 1 次。
- 空内容兜底：`stockReportHandler` 已有 fallback 从工具结果构建报告。

## 新增工具的清单
1. 在 `quantia/lib/ai/tools/` 新建 `<name>.py`，继承 `Tool`。
2. 工具的 `parameters` schema 用 JSON Schema 格式。
3. 内部 SQL 用**参数化查询**（`%s` 占位符），不要拼接用户输入。
4. 输出 dict 必须可 JSON 序列化；日期用 str、NaN 替换为 None、大数据截断。
5. 在 `quantia/lib/ai/tools/__init__.py` 的 `_ALL_TOOLS` 注册。
6. 对应 prompt 文件里补充工具说明和列名白名单。
7. 补单元测试（mock DB，覆盖正常/异常/边界路径）。

## 常见反模式
```python
# ❌ 执行后才发现列不存在，浪费 round-trip
try:
    rows = executeSqlFetch(sql)
except Exception as e:
    if "Unknown column" in str(e):
        patched = strip_bad_column(sql)
        rows = executeSqlFetch(patched)

# ✅ 执行前验证
_validate_columns(sql, tables)  # 不通过直接 ToolError
rows = executeSqlFetch(sql)

# ❌ 提示词模糊引导
"使用 sql_query 查询 cn_stock_spot 或 cn_stock_fund_flow 等表"

# ✅ 提示词精确约束
"使用 sql_query 查询以下表（只使用下列列名，禁止猜测）：
 - cn_stock_spot: code, name, new_price, ...。没有 concept/sector 列。"
```

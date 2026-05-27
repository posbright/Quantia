---
name: ai-agent-debug
description: "Use when debugging AI agent issues: empty reports, tool call failures, LLM hallucinated columns, SSE streaming errors, max_rounds exhaustion, or provider connectivity. Covers diagnostic steps, common root causes, and fix patterns for the stock_analyst/market_summarizer/strategy_coder agents."
---

# AI Agent 调试与诊断

## 何时使用
- AI 分析报告返回"空正文"或内容不完整
- 工具调用报错（sql_query 列不存在、kline_fetch 超时、web_search 503）
- SSE 流中出现异常事件或连接中断
- 前端显示"AI 已返回完成状态，但报告正文为空"
- Agent 运行超过 max_rounds 仍未生成有效内容
- 日志中反复出现 `Unknown column` 类错误

## 诊断流程

### Step 1: 确认错误层级

```
前端 → SSE 事件 → Handler → AgentRuntime → Provider → Tool
```

| 症状 | 定位层 | 诊断方法 |
|------|--------|----------|
| 前端显示"空正文" | Handler | 查看 SSE `done` 事件中 content 是否为空 |
| 前端无任何响应 | SSE 连接 | 浏览器 DevTools Network 看 EventSource |
| 工具报错 3 次/请求 | Tool | 查 agent 的 max_rounds，每轮可能都调同一工具 |
| "Unknown column" | sql_query | LLM 幻觉了不存在的列名 |
| Provider 超时 | providers | 查 `QUANTIA_AI_PROVIDER_*` 环境变量与 API 可达性 |

### Step 2: 复现

```bash
# 直接调用 AI 报告接口（绕过前端）
curl -N "http://localhost:9988/quantia/api/ai/report/generate?code=600000" \
  -H "Accept: text/event-stream"
```

观察 SSE 事件序列：
- 正常：`progress` → (多个) `chunk` → `done`
- 异常 A：`progress` → `done`（content 为空）→ 空报告
- 异常 B：`progress` → `error` → 前端报错
- 异常 C：无事件 → 连接超时 → Provider 不可达

### Step 3: 检查 Agent 日志

```python
# 关键日志点（quantia/lib/ai/agent.py）
logging.info(f"[Agent] round={round}, tool_calls={len(calls)}")
logging.warning(f"[Agent] tool {name} error: {err}")
logging.info(f"[Agent] final content length: {len(content)}")
```

## 常见问题与修复

### 问题 1：报告空正文

**根因分布**：
1. Provider 返回空 content（60%）— API 限流 / 模型输出被截断
2. max_rounds 耗尽（25%）— 工具调用轮次花完但没生成正文
3. 工具全部失败（15%）— DB 不可达或 schema 不一致

**修复路径**：
- 已有兜底：`stockReportHandler._build_fallback_report_from_tools()` 从工具结果构建 markdown
- Provider 问题：检查 `QUANTIA_AI_PROVIDER_*` 配置，切换备用模型
- max_rounds：当前默认 4，可通过 `AgentRuntime(max_rounds=6)` 增加（但注意 token 消耗）

### 问题 2：LLM 反复查询不存在的列

**根因**：prompt 中使用了模糊描述（如"板块数据"），LLM 推断出不存在的列名。

**修复路径**：
1. 更新 `quantia/lib/ai/prompt/stock_analyst.md`，添加精确列名白名单
2. 使用负面约束："**没有** `concept`/`sector` 列"
3. `sql_query.py` 已有预执行 schema 验证（`_validate_columns`），验证失败直接返回可用列名
4. 验证错误会被 LLM 看到并自动修正（下一轮不会再犯同一个错）

### 问题 3：同一错误重复 3 次

**根因**：Agent 4 轮中有 3 轮调用了 sql_query（分别为 spot + fund_flow + financial 三次查询），每次都幻觉了 `concept` 列。

**修复路径**：
- 根本修复：prompt 列名白名单 + 预执行验证
- 如果仍出现：检查 `_SCHEMA_CACHE` 是否正确填充（首次查询需要 DB 连接）
- 极端情况：schema 验证获取失败（DB 断连），会跳过验证让 SQL 执行后报错——此时应排查 DB 连接

### 问题 4：web_vitals / 前端噪音 405

**根因**：前端代码调用了后端未注册的路由。

**修复路径**：
- 查找前端 `src/api/` 和 `src/lib/` 中所有 URL 常量
- 交叉比对 `web_service.py` 路由表
- 缺失的路由：添加 no-op handler（如 `WebVitalsHandler` 返回 204）

### 问题 5：SSE 连接中断

**根因**：Nginx 超时（生产）/ 浏览器 EventSource 自动重连

**修复路径**：
- Nginx：设置 `proxy_read_timeout 300s` + `proxy_buffering off`
- 前端：`EventSource.onerror` 中检查 `readyState`，避免重复连接

## 验证 checklist

修复 AI agent 问题后，按以下顺序验证：

1. **单元测试**：`pytest tests/test_ai_m6_tools_agent.py -q`
2. **语法检查**：`python -c "import quantia.lib.ai.tools.sql_query; print('OK')"`
3. **重启服务**：杀端口 9988 → 启动 `web_service.py`
4. **黑盒验证**：
   ```bash
   curl -N "http://localhost:9988/quantia/api/ai/report/generate?code=600000" \
     -H "Accept: text/event-stream" 2>&1 | head -20
   ```
5. **前端验证**：浏览器访问 http://localhost:9988/ai-report/analysis，选一只股票生成报告

## 关键文件索引

| 文件 | 职责 |
|------|------|
| `quantia/lib/ai/agent.py` | AgentRuntime：tool-calling 循环 |
| `quantia/lib/ai/tools/sql_query.py` | 只读 SQL + 列验证 |
| `quantia/lib/ai/tools/stock_profile.py` | 个股综合画像聚合 |
| `quantia/lib/ai/tools/kline_fetch.py` | K 线数据读取 |
| `quantia/lib/ai/prompt/stock_analyst.md` | 股票分析师 system prompt |
| `quantia/web/stockReportHandler.py` | SSE 报告生成 handler |
| `quantia/fontWeb/src/views/stock/analysis.vue` | 前端报告页面 |

## Schema 验证机制说明

`sql_query.py` 的列验证流程：
```
LLM 生成 SQL
  → _check_safety() 校验表名白名单
  → _validate_columns() 查 INFORMATION_SCHEMA 校验列名
    → 通过 → _inject_limit() → executeSqlFetch()
    → 不通过 → ToolError("列验证失败——表 X 中不存在列: Y。可用列: ...")
```

LLM 收到 ToolError 后会在下一轮自动修正 SQL（使用提示的可用列名）。

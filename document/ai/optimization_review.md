# 优化审核清单

> 对集成方案的最终审核记录

## 审核结论：通过，附 6 项优化建议已纳入方案

---

## 已纳入的优化点

### 1. Agent 自主调度 vs Handler 硬编码 ✅

**原始思路**: Handler 中按固定顺序调用每个 tool  
**优化后**: 用 `run_agent` 让 LLM 自主决定调用哪些 tool，顺序由 prompt 引导

**收益**:
- 某些股票可能不需要 web_search（停牌、无新闻）
- 某些场景需要额外 sql_query（查板块对比）
- Agent 有 4 轮工具调用机会，足够覆盖复杂分析

### 2. 新增 `stock_profile` 聚合 Tool ✅

**问题**: 单独用 kline_fetch + sql_query 需要 2-3 轮工具调用才能获取完整画像  
**优化**: 一个 stock_profile 返回 5 维数据（行情+指标+资金+形态+K线摘要）  
**收益**: 工具轮次从 3 轮减到 1-2 轮，总延迟减少 2-4 秒

### 3. 两阶段输出策略 ✅

**方案**: Agent 工具调用阶段同步执行（用户看到 "正在获取数据..."），最终报告阶段 SSE 流式输出

**优于纯流式**: 
- Agent 工具调用产生的中间 token 对用户无意义
- 最终报告直接流式呈现，无中间噪声

### 4. 缓存策略 ✅

**10 分钟 TTL 缓存**（key = code + date）:
- 避免用户反复点击浪费 token
- 不影响数据时效性（交易时段内数据本身也是分钟级延迟）
- 收盘后缓存价值更大（数据不再变化）

### 5. 报告历史持久化 ✅

**`cn_stock_ai_report` 表**:
- 支持回看、收藏
- 记录模型/token 消耗用于成本监控
- INDEX (code, created_at DESC) 支持"某只股票的历史报告"查询

### 6. 多入口设计 ✅

**三个入口**:
- 导航菜单直接进入报告页 → 搜索生成
- 任意股票数据表行操作 → 一键跳转 (`router.push`)
- 模拟交易/回测详情 → 分析持仓股

---

## 潜在风险与缓解措施

| 风险 | 影响 | 缓解 |
|------|------|------|
| LLM 编造数据 | 报告不可信 | prompt 强制"禁止编造" + 工具返回空时标注"数据暂缺" |
| web_search 不可用 | 报告缺少新闻段 | prompt 规定"跳过该节"而非 fallback 编造 |
| 生成耗时 >15s | 用户等待焦虑 | SSE 流式 + "正在分析..." 骨架屏 |
| Token 成本高 | 运营压力 | 缓存 + 限频 + cn_stock_ai_report 记录消耗 |
| Agent 4 轮用完没获取关键数据 | 报告不完整 | stock_profile 一次返回核心数据，降低对多轮的依赖 |

---

## 未采纳的备选方案（记录供后续参考）

1. **RAG 方式**: 先 embed 所有指标到向量库 → 检索 → 生成。过于重型，当前 stock_profile 直查 MySQL 更快更准。
2. **多 Agent 协作**: 独立技术面 agent + 基本面 agent + 汇总 agent。增加复杂度，单 agent 4 轮已够。
3. **前端 Canvas 截图 + 多模态分析**: 像 SKILL 那样截 K 线图给 VLM 看。结构化数据输入精度远高于图片描述，且省 token。
4. **后端 Markdown→HTML**: 用 Python markdown 库在后端渲染，返回 HTML。不如前端 markdown-it 灵活（可做交互高亮）。

---

## 与现有 AI 模块的兼容性确认

| 现有模块 | 是否冲突 | 说明 |
|---------|----------|------|
| AiChatDrawer (4模式) | ❌ 不冲突 | 报告页独立，不复用 drawer |
| Agent CRUD (M7) | ❌ 兼容 | stock_analyst 作为 is_builtin=1 注册 |
| rate_limiter | ❌ 兼容 | 报告生成走 run_agent → 自动受限 |
| audit 审计 | ❌ 兼容 | run_agent 内部已记审计 |
| prompt_loader | ❌ 兼容 | agent 的 system_prompt 从 DB 读取 |
| 现有 6 个 Tools | ❌ 兼容 | stock_profile 是新增，不影响已有 |

---

*审核人: AI Assistant | 日期: 2026-05-23*

---

## 附录：数据差距与增量策略审核

### A. 财务数据覆盖率评估

| 维度 | 覆盖率 | 数据来源 | 备注 |
|------|--------|---------|------|
| 估值 (PE/PB/PS/PCF) | ✅ 100% | cn_stock_selection | 含 TTM 和扣非 |
| 盈利能力 (ROE/ROA/ROIC/毛利/净利) | ✅ 100% | cn_stock_selection + cn_stock_financial | |
| 成长性 (营收/利润增速, 3年CAGR) | ✅ 100% | cn_stock_selection | |
| 安全性 (负债率/流动/速动) | ✅ 100% | cn_stock_financial | |
| 资金流向 (主力/大单/中小单) | ✅ 100% | cn_stock_fund_flow | 5 个时间窗口 |
| 技术面 (MACD/KDJ/RSI/BOLL等) | ✅ 100% | cn_stock_indicators (32项) | |
| 研发投入 | ❌ 0% | 未采集 | AkShare 可扩展 |
| 专利/IP | ❌ 0% | 未采集 | 需新数据源 |
| 新闻/公告 | 🔶 50% | web_search 可搜索，但无结构化存储 | |
| 机构评级 | ❌ 0% | 未采集 | 东方财富有API |

### B. 缓存策略合理性

**结论**: 三层缓存设计合理，关键点：
1. DB 数据层由 cron 维护，与报告生成解耦 ✅
2. TTL 区分盘中/盘后 ✅（盘中价格变化快，需更短 TTL）
3. 数据变更检测用 `report_date` / `date` 字段比较 ✅（精确到天，足够）
4. 增量报告注入历史结论 ✅（AI 可做前后对比分析）

**风险点**: 盘中 30min TTL 可能导致快速变盘时报告过时 → 建议增加"实时价格"标注（从 cn_stock_spot 取最新价，不受报告缓存限制）

### C. AI Gate 与 ai_decision 模块兼容性

**现有 ai_decision 架构已为本方案预留接口**:
- `build_input_summary()` 支持 `extra` dict → 可注入 `event_context`
- `score_trade()` 返回标准化 dict → 可直接与 paper_trading 对接
- `_persist_score_row()` 自动记录评分 → 事后审计"AI 过滤了什么"
- `cn_stock_trade_ai_score` 表已有 `risk_flags` JSON 字段 → 存放事件风险

**需要扩展的点**:
- `context_builder.py` 增加 `event_context` 参数 (~30行)
- `prompt_renderer.py` 模板增加事件段落 (~20行)
- Gate prompt 增加事件敏感规则 (仅修改 DB 中的 system_prompt)

---

## 附录 B：补充优化点（第二轮审核 2026-05-23）

### 7. 生成过程可视化 ✅ (已纳入 §10.1)

**问题**: AI 报告 5-15s 生成期间用户无进度感知
**方案**: SSE `event: progress` 分步推送 + 前端实时更新步骤状态
**优先级**: Phase 1 必须（影响首次使用留存率）

### 8. 错误降级 fallback ✅ (已纳入 §10.3)

**问题**: AI 不可用时页面空白
**方案**: 三级降级（工具失败→标注暂缺 / AI 失败→展示数据面板 / 缓存过期→展示旧报告+提示）

### 9. 追问能力 ✅ (已纳入 §10.5)

**问题**: 用户看完报告对某个结论有疑问，只能重新生成
**方案**: 报告下方追问框，复用 agent context，补充回答追加到报告末尾

### 10. 并发控制与成本 ✅ (新增)

**问题**: 多用户同时请求同一股票报告 → 重复 LLM 调用
**方案**:
- 同一 code 的并发请求合并：第一个触发生成，后续等待同一结果（`asyncio.Event` 锁）
- 已有 rate_limiter (`60 calls/h`) 自动限频，报告生成无需额外限制
- Token 预算：stock_profile 返回控制在 2000 token 以内（JSON 精简），总报告 ~4000 output token

### 11. 安全性 ✅ (新增)

**问题**: stock_profile / sql_query 可能泄露敏感数据
**方案**:
- `stock_profile` 仅返回公开市场数据（无用户信息/交易记录）
- `sql_query` Tool 已有 read-only + LIMIT + 白名单表限制
- 报告中不包含用户持仓/账户信息（除非用户主动传入 portfolio_snapshot）
- 分享链接报告不含个人数据

### 12. 报告质量一致性 ✅ (新增)

**问题**: 不同 LLM 模型输出格式差异大，部分模型可能不遵循 7 节结构
**方案**:
- Agent system_prompt 中用 `## 报告结构（严格遵循）` 强制格式
- 后端对生成结果做 **结构校验**：检测是否包含 7 个 `####` 标题、多空对比表是否存在
- 不通过校验 → 重试 1 次（不同 temperature）；仍不过 → 返回 fallback 数据面板 + 原始文本
- 记录校验通过率到 `cn_stock_ai_report.quality_score` 字段，用于后续 prompt 迭代

### 13. 热门股票预生成 ✅ (新增)

**问题**: 高频查看的股票（如沪深300成分股）每次都等 5-15s 不理想
**方案**:
- 每日 16:00 收盘后，对"今日成交额 Top 50"自动触发报告生成（后台 cron）
- 用户查看时直接命中缓存，毫秒级响应
- 非热门股票仍走实时生成流程
- 实现简单：`cron.workdayly/` 新增一个 15 行脚本

### 14. 报告满意度反馈 ✅ (新增)

**问题**: 无法评估报告质量和用户满意度
**方案**:
- 报告底部增加 👍/👎 反馈按钮
- 存入 `cn_stock_ai_report.user_feedback` 字段 (1=满意, -1=不满意, NULL=未评)
- 统计满意率 → 指导 prompt 迭代和模型选择
- 不满意时可选择性填写原因（可选，不强制）



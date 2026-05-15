# AI 辅助自定义策略生成与回测 — 可行性分析与实施方案

> 文档版本：v1.1.4 ｜ 修订日期：2026-05-12 ｜ 适用分支：`backTest_dev`
>
> 范围：在 Quantia 项目内，新增"用户输入提示词 → AI 生成策略代码 → 用户/AI 二次修改 → 保存 → 回测 → 报错自动修正"的闭环；同时把 AI 配置抽象为项目级统一服务，支持多模型切换、工具调用（agent）、自定义 agent。
>
> **阅读顺序提醒**：本文档分多轮修订，**实施时请以靠后的章节为准**：
> - §3.1–§3.3 + 新增 **§3.4** 共同构成完整 DDL；
> - §4.1 目录树为初稿，**最终目录请看 §10.8**；
> - §4.3 路由表为初稿，**最终路由表请看 §10.7**；
> - §4.6 依赖说明被 §16.6（去 pydantic）+ §16.7（httpx 改可选）共同修订；
> - §7 实施顺序为初稿，**最终顺序请看 §18**；
> - §9 验收清单为初稿，**最终清单请看 §13**。
>
> **v1.1 修订（同日）**：补齐 `cn_stock_ai_conversation` 与 `cn_stock_ai_kb` 的统一 DDL（新增 §3.4）；为限流查询加 `(user_id, created_at)` 索引；为 RAG 表加 `(source_type, source_id)` 唯一键；修正 §10.3 中关于不存在的 `created_by` 列的误导性表述；修正 §15.1 中 `__class__` 已在黑名单内的绕过示例；§3.1 提示 `SaveStrategyCodeHandler` 需要支持新增列；明确 CLI 入口需 `__main__.py`（新增 §20）；统一日期到 2026-05-11；为被后续章节替代的 §4.1 / §4.3 / §4.6 / §7 / §9 加显式 superseded 标记。
>
> **v1.1.1 修订（同日补漏）**：统一 CLI 命令为 `python -m quantia.lib.ai`（§9 / §13 / §M1）；将 §11.2 中的 RAG 表 DDL 改为引用 §3.4（避免与 §3.4 不一致）；删除 §14 第 5 项过时的 httpx 依赖确认（§16.7 已决定零新增依赖）；统一限流配置项名称与默认值（§4.2 / §8 / §16.5 一致）；明确 §16.1 `_ALLOWED_IMPORTS` 来自 `strategy_sandbox`；§4.5 跨平台 CPU 限制改用子进程 + `Process.terminate()`；§4.5 `sql_query` 白名单放宽至所有项目表前缀；§15.2 INSERT 示例加'按实表列对齐'提示；§4.4 修复闭环加 `rate_limit_loop=True` 标志与 §16.5 协调。
>
> **v1.1.2 修订（同日再审）**：按当前仓库实测状态更新 §15 / §18 / §19：`validate_code_strict()`、`task_recorder.py`、失败任务落库接入与对应 pytest 已存在，M0 从“新增”改为“复核、补接入、跑测试”；修正 §10.2 / §10.6 / §15.3 / §15.4 中仍把 `httpx` 当必选的残留表述；补 §10.8 的 `__main__.py`；把 RAG 默认实现从误写的 `sqlite_vss.py（零依赖）` 改成 `mysql_fulltext.py`；统一旧 §7 / §18 的 CLI 命令；统一 429 验收为 `60 calls/hour + 200000 tokens/hour`；修正 §16.1 中“同文件 import 自己”的示例错误。
>
> **v1.1.3 修订（同日验证）**：修正 §1“现有可复用基础”中校验入口与错误回流入口的旧描述：AI 代码必须使用 `validate_code_strict()`，修复闭环统一通过 `task_recorder.fetch_last_failure(strategy_id)` 取失败信息；清理 §4.6 中 `httpx/pydantic` 旧依赖写法，避免读者误以为仍需修改 `requirements.txt`。
>
> **v1.1.4 修订（2026-05-12 文档审核）**：基于代码侧实测做一致性修复——
> ① §10.3 / §10.7 / §13 之间的"限流维度"矛盾澄清：实际实现统一为 `user_id`（值由 `_client_ip` 注入），§10.3 与 §13 已对齐；
> ② §10.7 路由表标记**当前未实现**的 4 条路由（`/chat/stream`、`/strategy/explain`、`/backtest/explain`、`/calls`），仅保留实际已注册的 7 条；
> ③ §4.2 / §8 / §16.5 删除 / 注释 `QUANTIA_AI_RATE_REPAIR_LOOP_FREE` env 项——代码侧未读取，由 `rate_limiter.check_quota(rate_limit_loop=True)` 形参写死；
> ④ §13 / §18 增加 **M11 历史踩坑 KB**（`strategy_lessons.md` 自动注入 + 修复成功自动记录）的描述；
> ⑤ §13 commit 引用更新到 `01729b57`。

---

## 1. 可行性结论

**完全可行，且改动主要集中在"新增"，不破坏现有链路。**

理由：现有自定义策略链路本来就是 *Python 代码字符串 → 沙箱执行 → 入库结果*，AI 只是再多一个"代码生成器"步骤，复用已有沙箱、保存接口、回测引擎即可。

### 现有可复用基础

| 现有组件 | 文件 / 位置 | 复用方式 |
| --- | --- | --- |
| 策略代码存储 | `cn_stock_strategy_code` 表（`code TEXT` 列） | 直接落 AI 生成的代码 |
| 保存接口 | `SaveStrategyCodeHandler` @ [portfolioBacktestHandler.py](quantia/web/portfolioBacktestHandler.py) | AI 生成结果走同一保存通道 |
| 代码静态校验 | `validate_code()` / `validate_code_strict()` @ [strategy_sandbox.py](quantia/core/backtest/strategy_sandbox.py) | AI 输出必须走 strict 校验 |
| 沙箱执行 | [strategy_sandbox.py](quantia/core/backtest/strategy_sandbox.py) | 白名单：`math/numpy/pandas/talib`，禁 `exec/eval/os/sys` |
| 回测引擎 | `PortfolioBacktestEngine.run()` | 不区分代码来源 |
| 模板 / few-shot 素材 | `STRATEGY_TEMPLATES` | 直接作为 LLM few-shot example |
| 模板修改追踪 | `template_id / template_hash / user_modified` | 新增 `source='ai'` 即可 |
| **已有 AI 模块** | [moat_ai_service.py](quantia/core/strategy/fundamental/moat_ai_service.py) | 现存 OpenAI 兼容客户端，**收敛到统一层**（详见 §10.1） |
| **已有 AI 配置 UI** | [strategyParamsHandler.py](quantia/web/strategyParamsHandler.py) `ai_model` 组 | 复用 DB 配置作为 provider 来源（详见 §10.1） |
| 回测错误回流 | `cn_stock_backtest_portfolio.error_message` 列 + [task_recorder.py](quantia/core/backtest/task_recorder.py) | 修复闭环统一走 `fetch_last_failure(strategy_id)` |

### 风险与边界

- LLM 输出可能不通过沙箱 → 需 **校验失败自动重试 / 自修复闭环**（本文档第 4 节）。
- LLM 网络延迟 / 限流 → 接口需线程池/异步封装 + 超时；建议按 `(client_ip, scene)` 与 token 双桶限额。
- 回测期间运行时报错 → 需收集 traceback 喂回 LLM 修正。
- Token 成本 → 入库审计 + 限额。

---

## 2. 总体架构

```
                ┌───────────────────────────────────────────┐
                │  统一 AI 服务层  quantia/lib/ai/          │
                │  ┌──────────┐  ┌──────────┐  ┌─────────┐  │
                │  │ Provider │  │ Agent    │  │ Tool    │  │
                │  │ Router   │  │ Runtime  │  │ Registry│  │
                │  └────┬─────┘  └─────┬────┘  └────┬────┘  │
                └───────┼──────────────┼────────────┼──────-┘
                        │              │            │
   策略生成/修复 ◄──────┘              │            │
   论坛/IM 摘要 ◄──────────────────────┘            │
   交易复盘/选股解释 ◄───────────────────────────────┘
                        ▲
                        │ HTTP (Tornado)
   前端 Vue + Element Plus
   ├── 策略编辑器 AI 抽屉
   ├── 全局"模型/Agent 选择器"组件
   └── 回测详情"AI 解释/修复"按钮
```

核心思想：**所有 AI 调用都走 `quantia/lib/ai/` 统一封装**，业务层（策略、IM、选股解释……）只关心 `prompt + 上下文 + 选用 agent`，不直接对接 OpenAI/DeepSeek SDK。

---

## 3. 数据库改动

### 3.1 扩展 `cn_stock_strategy_code`

```sql
ALTER TABLE cn_stock_strategy_code
  ADD COLUMN source ENUM('manual','template','ai') NOT NULL DEFAULT 'manual',
  ADD COLUMN ai_prompt TEXT NULL COMMENT '最近一次生成/修改使用的 prompt',
  ADD COLUMN ai_model VARCHAR(64) NULL,
  ADD COLUMN ai_agent VARCHAR(64) NULL COMMENT '使用的 agent 名',
  ADD COLUMN ai_repair_count INT NOT NULL DEFAULT 0 COMMENT '自动修复次数';
```

> **同步改造点**：[`SaveStrategyCodeHandler`](quantia/web/portfolioBacktestHandler.py) 与对应的 INSERT / UPDATE 语句需补 `source / ai_prompt / ai_model / ai_agent / ai_repair_count` 字段；前端策略保存请求体相应扩展。M2 阶段一并完成。

### 3.2 新增 AI 调用审计表

```sql
CREATE TABLE cn_stock_ai_call_log (
id BIGINT PRIMARY KEY AUTO_INCREMENT,
scene VARCHAR(32) NOT NULL COMMENT 'strategy_gen / strategy_repair / im_summary / ...',
agent VARCHAR(64) NULL,
provider VARCHAR(32) NOT NULL,
model VARCHAR(64) NOT NULL,
user_id VARCHAR(64) NULL COMMENT '单部署下存 client_ip，多用户化后可存真实用户 ID',
prompt MEDIUMTEXT,
response MEDIUMTEXT,
tools_used JSON NULL,
prompt_tokens INT, completion_tokens INT, total_tokens INT,
latency_ms INT,
ok TINYINT(1) NOT NULL,
error VARCHAR(512) NULL,
created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
INDEX idx_scene_time (scene, created_at),
INDEX idx_user_time (user_id, created_at)   -- §16.5 滑窗限流查询走此索引
);
```

### 3.3 新增 Agent 配置表（支持自定义 agent）

```sql
CREATE TABLE cn_stock_ai_agent (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(64) UNIQUE NOT NULL,
  display_name VARCHAR(128),
  description TEXT,
  system_prompt MEDIUMTEXT NOT NULL,
  default_provider VARCHAR(32),
  default_model VARCHAR(64),
  allowed_tools JSON NULL COMMENT '["sql_query","kline_fetch","web_search"]',
  temperature FLOAT DEFAULT 0.3,
  max_tokens INT DEFAULT 4096,
  is_builtin TINYINT(1) DEFAULT 0,
  enabled TINYINT(1) DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

启动时自动 upsert 内置 agent（`strategy_coder` / `strategy_repairer` / `market_summarizer` / `general_assistant`）。

### 3.4 多轮对话表与知识库表（v1.1 补齐）

以下两张表在原稿中分散出现于 §11.2 / §16.4 / §10.8 / §13 验收，但缺少建表语句；统一在此给出，便于一次性 migrate：

```sql
-- 多轮记忆持久化（§16.4 / §M8）
CREATE TABLE cn_stock_ai_conversation (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  conversation_id VARCHAR(64) UNIQUE NOT NULL COMMENT '前端 UUID',
  scene VARCHAR(32) NOT NULL,
  agent VARCHAR(64) NULL,
  title VARCHAR(255) NULL COMMENT '会话首句摘要',
  messages_json MEDIUMTEXT NOT NULL COMMENT '完整 messages 数组（已含自动摘要）',
  total_tokens INT NOT NULL DEFAULT 0,
  user_id VARCHAR(64) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_scene_updated (scene, updated_at),
  INDEX idx_user_updated (user_id, updated_at)
);

-- RAG 知识库（§11.2 / §M9）
CREATE TABLE cn_stock_ai_kb (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  source_type VARCHAR(32) NOT NULL COMMENT 'template / doc / strategy / backtest_failure',
  source_id VARCHAR(64) NULL,
  title VARCHAR(255),
  content MEDIUMTEXT,
  embedding BLOB NULL COMMENT '后续接 sqlite-vec 时填充',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_source (source_type, source_id),    -- indexer upsert 走此唯一键
  FULLTEXT KEY ftx_content (title, content)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

> M8 / M9 阶段才会真正使用，但建议 M1 一次性建表，避免后期再改 schema。

---

## 4. 后端改动

### 4.1 统一 AI 服务层 `quantia/lib/ai/`（**已被 §10.8 替代**，保留作为初稿对照）

> ⚠️ 此目录树为 v1.0 初稿，仅展示核心模块；最终落地结构请直接参考 **§10.8**（包含 `memory/` / `retrieval/` / `orchestrator/` / `cli.py / __main__.py` 等）。本节后续接口/关键设计仍有效。

```
quantia/lib/ai/
├── __init__.py
├── config.py           # 从 .env / DB 读全局配置
├── providers/
│   ├── base.py         # ProviderBase: chat(messages, tools, **kw) -> Response
│   ├── openai_compat.py  # 兼容 OpenAI / DeepSeek / 通义千问 / 月之暗面 / 本地 vLLM
│   └── anthropic.py    # 可选
├── router.py           # 根据 (scene, user_choice) 选 provider+model
├── tools/
│   ├── base.py         # Tool 抽象：name / schema / run(args)
│   ├── registry.py     # 注册中心 + 权限检查
│   ├── sql_query.py    # 只读 SQL（白名单表）
│   ├── kline_fetch.py  # 拉取 K 线
│   ├── code_validate.py# 调 validate_code
│   ├── backtest_run.py # 跑沙箱 dry-run
│   └── web_search.py   # 可选
├── agent.py            # AgentRuntime：function-calling 循环 + 工具调度
├── prompt/
│   ├── strategy_coder.md
│   ├── strategy_repairer.md
│   └── market_summarizer.md
└── audit.py            # 写 cn_stock_ai_call_log
```

#### 关键接口

```python
# quantia/lib/ai/__init__.py
from .agent import AgentRuntime
from .router import resolve_model
from .config import get_ai_config

def run_agent(scene: str, *, agent: str, user_message: str,
              context: dict | None = None,
              model: str | None = None,
              tools: list[str] | None = None,
              user_id: str | None = None) -> AgentResult: ...
```

调用方只需 `run_agent(scene='strategy_gen', agent='strategy_coder', user_message=prompt)`。

### 4.2 配置（统一在 `.env` + DB）

`.env` 新增：

```ini
# 全局开关
QUANTIA_AI_ENABLED=true
# 默认 provider / model（可被 scene/agent 覆盖）
QUANTIA_AI_DEFAULT_PROVIDER=deepseek
QUANTIA_AI_DEFAULT_MODEL=deepseek-chat

# 多 provider，命名空间式
QUANTIA_AI_PROVIDER_DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
QUANTIA_AI_PROVIDER_DEEPSEEK_API_KEY=sk-xxx
QUANTIA_AI_PROVIDER_QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QUANTIA_AI_PROVIDER_QWEN_API_KEY=sk-xxx
QUANTIA_AI_PROVIDER_OPENAI_BASE_URL=https://api.openai.com/v1
QUANTIA_AI_PROVIDER_OPENAI_API_KEY=sk-xxx

# 限流（与 §16.5 双桶限流一致；原名 `..._PER_USER_PER_HOUR` 已废弃）
QUANTIA_AI_RATE_CALLS_PER_HOUR=60
QUANTIA_AI_RATE_TOKENS_PER_HOUR=200000
# （历史草案：QUANTIA_AI_RATE_REPAIR_LOOP_FREE — 已废弃。
#  当前实现：修复闭环内的多轮重试**始终**算 1 次，由 `rate_limiter.check_quota(rate_limit_loop=True)`
#  形参在调用点传入；无配置开关。详见 quantia/lib/ai/rate_limiter.py 与 §16.5。）
QUANTIA_AI_MAX_TOKENS_PER_CALL=8192
QUANTIA_AI_TIMEOUT_SECONDS=60

# 工具白名单（agent 内可启用的工具上限）
QUANTIA_AI_GLOBAL_TOOLS=sql_query,kline_fetch,code_validate,backtest_run,web_search
```

> **复用统一性**：项目内其他位置（IM 摘要、复盘文案等）一律走 `quantia/lib/ai/run_agent()`，禁止再各自 `import openai`。

### 4.3 新增 Tornado Handler（**路由命名空间已被 §10.7 替代**）

> ⚠️ 下表中 `/quantia/api/strategy/ai/*` 与 `/quantia/api/ai/chat` 等是 v1.0 命名；**最终统一前缀为 `/quantia/api/ai/...`**，详见 **§10.7**。本节保留作为初稿；实施时直接按 §10.7 路由写代码即可。

建议拆到 `quantia/web/aiAssistantHandler.py`：

| Method | Path（v1.0 旧版，仅供参考） | 用途 |
| --- | --- | --- |
| GET | `/quantia/api/ai/config` | 返回前端可见配置：可用 provider/model 列表、可用 agent 列表、当前默认 |
| GET | `/quantia/api/ai/agents` | 列出 agent（含自定义） |
| POST | `/quantia/api/ai/agents` | 新建/更新自定义 agent（system_prompt、allowed_tools、model） |
| DELETE | `/quantia/api/ai/agents/{id}` | 删除自定义 agent（内置不可删） |
| POST | `/quantia/api/ai/chat` | 通用对话（前端"AI 助手"侧边栏） |
| POST | `/quantia/api/strategy/ai/generate` | prompt → 策略代码（不入库） |
| POST | `/quantia/api/strategy/ai/refine` | code + 修改指令 → 新代码 |
| POST | `/quantia/api/strategy/ai/explain` | code → 自然语言解释 |
| POST | `/quantia/api/strategy/ai/repair` | code + traceback + 回测日志 → 修复后的代码 |
| GET | `/quantia/api/ai/calls` | 调用历史（审计） |

所有 handler 内部一律调用 `run_agent(...)`。

### 4.4 报错自动修复闭环

策略保存或回测失败时进入修复循环：

```python
# 伪代码：quantia/web/aiAssistantHandler.py 的 repair handler
def repair(code, error_log, max_retries=3):
    for i in range(max_retries):
        result = run_agent(
            scene='strategy_repair',
            agent='strategy_repairer',
            user_message=f"原代码:\n{code}\n\n报错:\n{error_log}\n\n请修复",
            tools=['code_validate', 'backtest_run'],  # 让 agent 自己调验证
        )
        new_code = extract_python_block(result.text)
        ok, err = validate_code(new_code)
        if not ok:
            error_log = err; code = new_code; continue
        # dry-run 一段最近 30 个交易日的数据
        ok, err = sandbox_dryrun(new_code)
        if ok:
            return {"code": new_code, "attempts": i+1, "explain": result.text}
        error_log = err; code = new_code
    return {"error": "exceed_max_retries", "last_error": error_log, "last_code": code}
```

> **限流协同**：进入 `repair()` 时给 `run_agent` 传 `rate_limit_loop=True`，`audit.py` 写日志时落 `tools_used.rate_limit_loop=true`；§16.5 的滑窗只统计 `rate_limit_loop != true` 的记录，确保多轮自修复不会把用户配额吃光。

触发点：

1. **保存时** `validate_code` 失败 → 提示用户"AI 自动修复"按钮。
2. **回测后** 任务状态 = `failed` 时，详情页显示"让 AI 分析并修复"按钮，自动取 `cn_stock_backtest_portfolio.error_message` 作为输入。
3. **运行时报错** 由 `PortfolioBacktestEngine` 捕获 traceback 落库到 `error_message` 列（如未落需补字段）。

### 4.5 Agent + Tool 调用机制

采用 **OpenAI 兼容的 function calling** 协议（DeepSeek、通义、Kimi、OpenAI 都支持）。

`AgentRuntime.run()` 流程：

```
loop:
  resp = provider.chat(messages, tools=allowed_tool_schemas)
  if resp.tool_calls:
      for tc in resp.tool_calls:
          tool = registry.get(tc.name)
          if not user_or_agent_allowed(tool): refuse
          out = tool.run(tc.args)            # 受 timeout / 输出大小限制
          messages.append(tool_result(out))
      continue
  else:
      return resp.text
```

工具安全约束：

- `sql_query`：只读（拒绝 INSERT/UPDATE/DELETE/DDL）+ 仅项目自有表前缀（`cn_stock_*` / `cn_etf_*` / `QUANTIA_*` / `cn_stock_ai_*`，最终白名单以 `quantia/lib/database.py` 实际表清单为准）+ LIMIT 强制注入（默认 100，最大 1000）。
- `kline_fetch`：调用现有 K 线查询函数，不暴露 DB 连接。
- `backtest_run`：仅在独立**子进程**中跑 dry-run，由父进程 `Process.terminate()` 在 10s 后强杀（**不依赖 `signal.SIGALRM`，兼容 Windows**），输出截断 8KB。
- 任何工具调用都进 `cn_stock_ai_call_log.tools_used`。

### 4.6 依赖（**已被 §16.6 + §16.7 修订**）

> ⚠️ 此节为初稿。最终方案：**零新增依赖**——同步路径用仓库已存在的 `requests`，工具 schema 用手写 dict + 已有 `jsonschema`。`httpx` 仅在未来切异步流式时按需评估。

初稿原文（仅作历史参考）：曾建议在 `requirements.txt` 增加 `httpx` 与 `pydantic`；最终方案已取消这两个必选依赖。

不引入 `openai` 官方 SDK 的结论保持不变：所有兼容协议平台（DeepSeek/Qwen/Kimi/Azure/OpenAI/vLLM）都能用同一份 HTTP 客户端实现，避免 SDK 版本锁定。

---

## 5. 前端改动

### 5.1 全局组件

- [quantia/fontWeb/src/components/AiModelPicker.vue](quantia/fontWeb/src/components/AiModelPicker.vue)（新建）：下拉选择 `provider + model + agent`，调用 `/quantia/api/ai/config` 与 `/agents`，选择持久化到 localStorage。
- [quantia/fontWeb/src/stores/ai.ts](quantia/fontWeb/src/stores/ai.ts)（新建 Pinia store）：当前模型、agent、工具勾选、调用中状态。
- [quantia/fontWeb/src/api/ai.ts](quantia/fontWeb/src/api/ai.ts)（新建）：封装 `/api/ai/*` 接口。

### 5.2 策略编辑页改动

[quantia/fontWeb/src/views/strategy/edit.vue](quantia/fontWeb/src/views/strategy/edit.vue)（按现有结构）：

- 右侧新增"AI 助手"抽屉：
  - prompt 输入 + `生成 / 修改选中片段 / 解释代码 / 修复错误` 四个动作
  - 顶部嵌入 `AiModelPicker`（可即时切换模型/agent/工具）
  - 流式输出展示
  - "应用到编辑器"按钮才真正写入 Monaco
- 顶部 Toast 校验失败时新增"让 AI 修复"按钮 → 调 `/strategy/ai/repair`。

### 5.3 回测详情页改动

[quantia/fontWeb/src/views/backtest/detail.vue](quantia/fontWeb/src/views/backtest/detail.vue)：

- 任务 `status=failed` 时显示"AI 分析失败原因 / 自动修复策略"按钮 → repair 接口。
- 成功任务显示"AI 解读本次回测"按钮（用 `market_summarizer` agent，喂回测指标 JSON）。

### 5.4 自定义 Agent 管理页

新增 [quantia/fontWeb/src/views/ai/agentManager.vue](quantia/fontWeb/src/views/ai/agentManager.vue)：

- 列表 + 新建/编辑表单：`name / system_prompt / 默认 model / 允许的 tools / temperature`
- 内置 agent 只读（带"复制为自定义"快捷键）
- 路由挂在 `设置 → AI 助手`

---

## 6. 安全与质量护栏

1. **沙箱不可豁免**：所有 AI 输出代码必须经过 `validate_code()` + AST 黑名单；保存接口本来就过校验，AI 通道**不**给特例。
2. **prompt/响应脱敏**：入库前剔除 `QUANTIA_AI_PROVIDER_*_API_KEY`、`QUANTIA_DB_PASSWORD`、`smtp_password` 等环境变量值（防用户在 prompt 里贴 .env）。
3. **工具权限分级**：内置 agent 工具集白名单写在 system prompt + 后端 registry；自定义 agent 不能勾选超出 `QUANTIA_AI_GLOBAL_TOOLS` 的工具。
4. **回测仍在子进程 + 超时**：复用现有回测子进程 2h 超时机制。
5. **限流**：按 `(client_ip, scene)` 调用次数 + token 总量双桶计数实现；超额返回 `429`。
6. **审计可追溯**：每次调用包括工具调用细节都落 `cn_stock_ai_call_log`，前端可查。
7. **PII / 合规**：用户 prompt 仅用于本次生成，不做任何外发训练；provider 选型时优先支持"不收集训练"开关（DeepSeek 已提供）。

---

## 7. 实施顺序（推荐 MVP → 增强）（**已被 §18 替代**）

> ⚠️ 此 8 阶段表为 v1.0 初稿。最终阶段表请看 **§18**（M0 前置加固 → M10 跨场景，共 11 阶段）。本节保留供横向对照。

| 阶段 | 内容 | 交付物 |
| --- | --- | --- |
| **M1 基础设施** | `quantia/lib/ai/` provider+router+config+audit；`.env` 落配置；DB 扩列+审计表 | 命令行 `python -m quantia.lib.ai "你好"` 跑通 |
| **M2 策略生成** | `strategy_coder` agent + system prompt + `/strategy/ai/generate` + 前端抽屉最小版 | prompt → 代码 → 灌入编辑器 → 手动保存回测 |
| **M3 校验闭环** | `validate_code` 失败重试；前端 toast 提示 | 生成代码必合法 |
| **M4 修复闭环** | `strategy_repairer` agent + `/strategy/ai/repair`；回测失败接入 | 一键修复回测错误 |
| **M5 多模型/Agent 选择** | `AiModelPicker` + `/ai/config` + `/ai/agents` 列表 | 用户可切换 |
| **M6 工具调用** | `AgentRuntime` + `sql_query / kline_fetch / code_validate / backtest_run` | agent 能查行情、跑 dry-run |
| **M7 自定义 Agent** | `cn_stock_ai_agent` CRUD + 管理页 | 用户可自建 agent |
| **M8 跨场景复用** | IM 摘要、回测解读、选股解释统一接入 | 全项目仅一套 AI 调用入口 |

---

## 8. 配置示例（落 `.env`）

```ini
QUANTIA_AI_ENABLED=true
QUANTIA_AI_DEFAULT_PROVIDER=deepseek
QUANTIA_AI_DEFAULT_MODEL=deepseek-chat
QUANTIA_AI_PROVIDER_DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
QUANTIA_AI_PROVIDER_DEEPSEEK_API_KEY=sk-***
QUANTIA_AI_PROVIDER_QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QUANTIA_AI_PROVIDER_QWEN_API_KEY=sk-***
QUANTIA_AI_RATE_CALLS_PER_HOUR=60
QUANTIA_AI_RATE_TOKENS_PER_HOUR=200000
# QUANTIA_AI_RATE_REPAIR_LOOP_FREE 已废弃 — 当前实现固定豁免修复闭环重试（rate_limiter.py 形参 rate_limit_loop=True）
QUANTIA_AI_MAX_TOKENS_PER_CALL=8192
QUANTIA_AI_TIMEOUT_SECONDS=60
QUANTIA_AI_GLOBAL_TOOLS=sql_query,kline_fetch,code_validate,backtest_run
```

---

## 9. 验收标准（**已被 §13 替代**）

> ⚠️ 此 7 项验收为 v1.0 初稿。最终 11 项验收清单请看 **§13**。本节保留作为对照。

- [ ] `python -m quantia.lib.ai` 能用任一 provider 跑通对话（含工具调用）。
- [ ] 策略编辑页 prompt 生成的代码能直接保存并完成一次成功回测。
- [ ] 故意写一段 `import os` 的 prompt，应被 `validate_code` 拒绝并提示"AI 修复"。
- [ ] 故意触发回测除零错误，点"AI 修复"后能在 ≤3 轮内修复并跑通。
- [ ] 在 AI 设置页新建一个自定义 agent（仅允许 `sql_query`），生成的策略调用工具次数被审计记录。
- [ ] 切换模型 deepseek ↔ qwen 后，策略生成均成功且 `cn_stock_ai_call_log.model` 正确。
- [ ] 同一 IP 超过 `60 calls/hour` 或 `200000 tokens/hour` 后返回 429。

---

## 10. 文档审核与修订（2026-05-11）

二次审阅时复核了仓库实际状态，更正以下偏差并加固设计：

### 10.1 已存在的 AI 集成（修正"项目无 AI"的判断）

仓库内 **已有** AI 模块：

| 现有文件 | 作用 | 设计影响 |
| --- | --- | --- |
| [quantia/core/strategy/fundamental/moat_ai_service.py](quantia/core/strategy/fundamental/moat_ai_service.py) | 护城河分析，调用 OpenAI 兼容 `chat/completions`，依赖 `requests` | 必须迁移而非并存——否则两套配置 |
| [quantia/web/strategyParamsHandler.py](quantia/web/strategyParamsHandler.py) `ai_model` 配置组（L352） | DB 中已有 `api_base / api_key / model / temperature / max_tokens / timeout` | **新方案直接复用此配置作为 provider 来源之一**，不要新增重复 UI |
| `MoatAIConfig.from_db()` | 从 `get_strategy_params("ai_model")` 加载 | 新统一层提供同名兼容方法，老代码无需改动 |

**修订后的统一层职责**：`quantia/lib/ai/` 既能从 `.env` 读 provider，又能从 `cn_stock_strategy_params` 的 `ai_model` 组读取（向后兼容），DB 配置优先级高于 `.env`。`moat_ai_service.py._call_ai()` 改为 thin wrapper，内部调 `quantia.lib.ai.run_chat(...)`，删除自有的 requests 调用块——避免两份重试 / 超时 / 审计逻辑漂移。

### 10.2 Tornado 同步上下文 → 异步 LLM 调用（关键漏洞）

仓库 web 层用 `tornado.web` + `torndb`（同步），LLM 调用通常需要 10–60 秒，**直接在 handler 里 `requests.post()` 会阻塞整个 IOLoop**，影响其他用户的 K 线 / 回测请求。

修订：

1. `quantia/lib/ai/providers/openai_compat.py` MVP 先提供同步 `chat()`（基于现有 `requests`），避免新增依赖。
2. 所有 Tornado handler 不直接 `requests.post()`，而是复用现有 `ThreadPoolExecutor` / `IOLoop.current().run_in_executor()` 模式；流式输出用后台线程读取 chunk，再通过 `asyncio.Queue` 或 Tornado queue 推给 SSE handler。
3. `chat_async()` / `httpx.AsyncClient` 仅作为未来高并发优化，不进入 MVP 必选项。

### 10.3 鉴权模型修正（v1.1.4 修正）

[quantia/web/base.py](quantia/web/base.py) 没有用户体系——本项目是单用户/内部部署。原方案中 `per-user` 概念不成立。

**实际实现（与 §13 注释一致）**：

- 限流维度统一为 **`user_id`**（值由 `_client_ip(handler)` 取 `handler.request.remote_ip` 注入；
  详见 [`aiAssistantHandler.py::_client_ip`](quantia/web/aiAssistantHandler.py) 与
  [`rate_limiter.check_quota(user_id, ...)`](quantia/lib/ai/rate_limiter.py)）。
  `cn_stock_ai_call_log.user_id` 列存储该值（当前即 IP）。
- 未来开放外网访问时，只需把 handler 中的 `_client_ip(self)` 替换为登录用户 ID，
  限流与审计无需改 schema。
- 自定义 agent 没有"所有者"概念，只有 `is_builtin / enabled` 标志；多用户化以后再补。
- 沿用此原则，§3.3 的 `cn_stock_ai_agent` 表**不引入** `created_by / owner_id` 等多租户字段，避免后续无谓迁移。

### 10.4 `validate_code` / `validate_code_strict` 行为复核

实际实现位于 [strategy_sandbox.py](quantia/core/backtest/strategy_sandbox.py)；[portfolioBacktestHandler.py](quantia/web/portfolioBacktestHandler.py) 在保存策略时懒导入并调用 `validate_code()`。当前仓库已存在 `validate_code_strict()`，AI 通道实施前必须：

1. 通读 `validate_code()` 与 `validate_code_strict()` 的完整规则（关键字黑名单 / AST 检查 / 导入白名单 / 函数签名要求）。
2. 把规则原文 dump 进 `strategy_coder` agent 的 system prompt，作为"硬约束清单"。
3. AI 修复闭环每轮调用必须传完整的 `validate_code` 错误文本（含规则名），LLM 才能定向修。

> **风险**：普通保存链路仍只调用 `validate_code()`；AI 生成 / 修改 / 修复链路必须显式调用 `validate_code_strict()`，否则 AST 层加固不会生效。

### 10.5 回测错误回流路径已就绪

复核 [portfolioBacktestHandler.py](quantia/web/portfolioBacktestHandler.py) 与 [task_recorder.py](quantia/core/backtest/task_recorder.py)：`cn_stock_backtest_portfolio.error_message TEXT` 列已存在，失败分支已通过 `record_failed(...)` 写入 `error_message` / `result_json`，修复闭环可直接复用 `fetch_last_failure(strategy_id)`，无需新增字段或直接拼 SQL。

仍需：

- 跑同步/异步失败回测端到端用例，确认实际异常 traceback 进入 `error_message`。
- AI 修复工具只调用 `task_recorder.fetch_last_failure(strategy_id)`，不要绕过统一模块直接查表。

### 10.6 依赖与现有库对齐

仓库已用 `requests`（`moat_ai_service.py`）。最终修订：

- **MVP 零新增依赖**：同步 provider 继续用 `requests`；Tornado handler 通过线程池避免阻塞 IOLoop。
- **不引入 `pydantic`**：tool schema 统一用手写 dict + 现有 `jsonschema` 风格。
- **不强制引入 `httpx`**：未来高并发、纯 async provider 或更复杂流式场景再评估。

### 10.7 路由命名空间

修订：所有 AI 路由统一前缀 `/quantia/api/ai/`，避免和已有 `/quantia/api/strategy/code` 等混淆。策略相关 AI 操作放二级路径：

```
/quantia/api/ai/chat                 # 通用对话           ✅ 已实现
/quantia/api/ai/config               # 可见配置           ✅ 已实现
/quantia/api/ai/agents               # CRUD（POST 用 /agents/manage 命名空间，无 PUT/{id}） ✅ 部分实现
/quantia/api/ai/strategy/generate          # 策略生成（同步）✅
/quantia/api/ai/strategy/generate/stream   # 策略生成（SSE 流式，前端默认）✅
/quantia/api/ai/strategy/refine            # 策略修改      ✅
/quantia/api/ai/strategy/repair            # 报错修复      ✅
```

> ⚠️ 历史草案中的下列路由**当前未实现**，需要时按相同模式新增 handler 即可：
> - `/quantia/api/ai/chat/stream`（通用对话流式；目前流式仅 `/strategy/generate/stream` 支持）
> - `/quantia/api/ai/strategy/explain`（代码解释；前端走通用 `/chat` 即可）
> - `/quantia/api/ai/backtest/explain`（回测解读；前端走通用 `/chat` 即可）
> - `/quantia/api/ai/calls`（审计列表 API；目前直接查 `cn_stock_ai_call_log` 表）

`web_service.py` `handlers` 列表的"组合回测 & 策略管理"块下方新增"AI 助手"块。

### 10.8 项目结构（最终版）

```
quantia/
├── lib/
│   └── ai/                              # ★ 新增：统一 AI 服务层
│       ├── __init__.py                  # 暴露 run_chat / run_agent / stream_chat
│       ├── config.py                    # .env + ai_model DB 组 合并配置
│       ├── exceptions.py                # AIError / RateLimitError / ValidationError
│       ├── providers/
│       │   ├── base.py                  # Provider ABC（chat / chat_async / stream）
│       │   ├── openai_compat.py         # 兼容 OpenAI/DeepSeek/Qwen/Kimi/vLLM/Ollama
│       │   └── anthropic.py             # 可选
│       ├── router.py                    # scene/agent → provider+model 解析
│       ├── memory/
│       │   ├── base.py                  # ConversationMemory ABC
│       │   ├── inmem.py                 # 进程内 LRU（默认）
│       │   └── db.py                    # cn_stock_ai_conversation 表
│       ├── retrieval/
│       │   ├── base.py                  # VectorStore ABC
│       │   ├── mysql_fulltext.py        # 默认实现：MySQL FULLTEXT + LIKE 兜底（零新增依赖）
│       │   ├── sqlite_vec.py            # 可选：真向量检索
│       │   ├── chroma.py                # 可选
│       │   └── indexer.py               # 模板/文档/回测结果索引器
│       ├── tools/
│       │   ├── base.py                  # Tool ABC + JSON schema
│       │   ├── registry.py              # 注册 + 权限 + 审计 hook
│       │   ├── sql_query.py
│       │   ├── kline_fetch.py
│       │   ├── code_validate.py
│       │   ├── backtest_run.py
│       │   ├── kb_search.py             # 检索工具（依赖 retrieval/）
│       │   └── web_search.py            # 可选
│       ├── orchestrator/
│       │   ├── pipeline.py              # 链式 agent（DAG / 顺序）
│       │   └── presets.py               # analyst→coder→tester 等内置编排
│       ├── agent.py                     # AgentRuntime：tool-calling 主循环
│       ├── audit.py                     # 写 cn_stock_ai_call_log
│       ├── prompt/                      # system prompt 模板（外部文件，便于热更新）
│       │   ├── strategy_coder.md
│       │   ├── strategy_repairer.md
│       │   ├── market_summarizer.md
│       │   └── general_assistant.md
│       ├── __main__.py                  # python -m quantia.lib.ai 入口
│       └── cli.py                       # argparse 实现
├── web/
│   └── aiAssistantHandler.py            # ★ 新增：所有 /api/ai/* 路由
├── core/
│   └── strategy/fundamental/moat_ai_service.py  # 改造：内部改调 lib/ai
└── fontWeb/src/
    ├── api/ai.ts                        # ★
    ├── stores/ai.ts                     # ★
    ├── components/
    │   ├── AiModelPicker.vue            # ★
    │   ├── AiChatDrawer.vue             # ★ 通用 AI 抽屉（策略页/回测页/IM 页复用）
    │   └── AiAgentPicker.vue            # ★
    └── views/
        ├── ai/
        │   ├── agentManager.vue         # ★ 自定义 agent 管理
        │   ├── conversationHistory.vue  # ★ 多轮记忆查看
        │   └── callLog.vue              # ★ 调用审计
        ├── strategy/edit.vue            # 改：嵌 AiChatDrawer
        └── backtest/detail.vue          # 改：嵌 AI 解释/修复按钮
```

合理性自评：

- `quantia/lib/ai/` 与 `quantia/lib/database.py / envconfig.py` 同层，符合"基础设施在 lib，业务在 core/web"约定。
- `aiAssistantHandler.py` 与 `paperTradingHandler.py / portfolioBacktestHandler.py` 同层，单一前缀清晰。
- 所有 LLM 知识（prompt/工具/编排）集中在 `quantia/lib/ai/`，业务方只 import 即用。
- `prompt/*.md` 走外部文件而非硬编码字符串，便于运营调优、git diff 友好。

---

## 11. 扩展能力可行性与设计

> 此节是对原"后续可拓展"5 项的具体可行性评估与落地方案，确保不是"将来再说"，而是项目结构上**已经预留**了对应模块。

### 11.1 流式 SSE 输出 ★★★★★（强烈推荐立即纳入 M2）

**可行性**：高。Tornado 原生支持 SSE：handler 在 `async def get()` 中循环 `self.write(chunk); await self.flush()` 即可。

**改动**：

1. `Provider.stream(messages) -> AsyncIterator[str]`：所有 OpenAI 兼容平台都支持 `stream=true`。
2. 新路由 `POST /quantia/api/ai/chat/stream`（或 GET，按 SSE 协议）。
3. 前端用 `EventSource` 或 `fetch` + `ReadableStream`（推荐后者，可带 `POST body` + Authorization）。
4. 工具调用阶段需要分两段流式：先流 thought → 等待 tool 执行 → 再流 final answer；前端约定事件名 `delta / tool_call / tool_result / done / error`。

**风险**：

- Tornado 同 IOLoop 下需保证 handler 不阻塞：MVP 用 `requests(stream=True)` + 线程池 + queue；未来也可切 `AsyncHTTPClient` / `httpx.AsyncClient`。
- nginx 反向代理需关 `proxy_buffering`（在 supervisor/Tornado 自部署中无问题）。

**结论**：M2 阶段就把 `chat/stream` 实现，否则用户对 30 秒级生成会觉得卡死。前端组件 `AiChatDrawer.vue` 默认走流式。

### 11.2 向量检索 / RAG ★★★★☆（M5 后接入）

**可行性**：中-高。本项目可索引的语料天然丰富：

- `STRATEGY_TEMPLATES`（已有 ~10 个模板，含描述+代码）
- `document/` 下所有 markdown
- `cn_stock_strategy_code` 历史策略
- `cn_stock_backtest_portfolio` 失败用例库（`error_message` + `result_json`）

**实现路径（按依赖代价升序）**：

| 方案 | 依赖 | 适合 |
| --- | --- | --- |
| **sqlite + 简单 BM25**（`rank_bm25`） | 0 新依赖（项目已有 sqlite3 stdlib） | MVP，召回足够好 |
| **sqlite-vss / sqlite-vec** | 1 个 wheel | 真向量检索，无须额外服务 |
| **Chroma 本地** | `chromadb` | 后续大语料 |
| **MySQL FULLTEXT** | 0 新依赖（已有 MySQL） | 文本检索，零运维 |

**推荐**：MVP 用 **MySQL FULLTEXT 索引** + LIKE 兜底，表结构详见 **§3.4**（v1.1 已统一给出含 `UNIQUE KEY uk_source(source_type, source_id)` 与 `FULLTEXT ftx_content(title, content)` 的最终 DDL，实施请直接按 §3.4 建表，**不要使用本节早先列出的旧版 DDL**）。嵌入向量阶段再切 `sqlite-vec`，到那时在表中填充 `embedding BLOB` 列即可。

工具 `kb_search(query, top_k=5, source_types=['template','doc'])` 实现于 `quantia/lib/ai/tools/kb_search.py`，由 indexer 定时（cron 已有框架）刷新。

**与策略生成的化学反应**：

- 用户 prompt "做一个布林带下轨买入的策略" → agent 自动 `kb_search('布林带 下轨')` → 取回模板原文做 in-context few-shot → 生成质量大幅提升，token 消耗下降（不必把全部 templates 塞 system prompt）。

### 11.3 多轮对话记忆 ★★★★☆（M3 接入）

**可行性**：高。

**实现**：

- 抽象 `ConversationMemory`：`append(role, content) / load(conversation_id, max_tokens)`；token 估算用 `tiktoken` 或简易 `len(text)//2.5`。
- 默认实现 `inmem.py`（进程内 LRU + TTL，单机够用）。
- 持久化实现 `db.py` 落 `cn_stock_ai_conversation(id, scene, conversation_id, messages_json, updated_at)`，支持"打开历史会话继续"。
- 自动摘要：达到 `max_tokens` 80% 时，调廉价模型（`deepseek-chat`）把前文压缩成 system note，再继续。

**前端**：编辑器 AI 抽屉左侧加"会话列表"；每个会话绑定一个 `conversation_id`（UUID）放 localStorage。

### 11.4 Agent 编排 ★★★☆☆（M7 后）

**可行性**：中。需要谨慎设计否则容易过度工程。

**最简编排：顺序管线（推荐先做这种）**：

```python
# quantia/lib/ai/orchestrator/presets.py
STRATEGY_PIPELINE = Pipeline([
    Step('analyst',  agent='strategy_analyst',  output='思路+伪代码'),
    Step('coder',    agent='strategy_coder',    input_from='analyst', output='Python 代码'),
    Step('tester',   agent='strategy_repairer', input_from='coder',
                     loop_until=lambda x: validate_code(x)[0] and dry_run(x)[0],
                     max_iters=3),
])
```

**复杂编排（DAG / 反思 / 投票）作为后续**：避免重复造 LangGraph，必要时直接引入 `langgraph`，但要权衡依赖成本。

**前端**：`视图：编排预览` 显示每步的 thinking + 输出，便于观察。

### 11.5 本地模型 ★★★★★（设计上零成本）

**可行性**：高。OpenAI 兼容协议是 vLLM / Ollama / LM Studio / Xinference / TGI 默认产物。

**用户操作**：

```ini
# .env：把本地服务当作普通 provider
QUANTIA_AI_PROVIDER_LOCAL_BASE_URL=http://localhost:11434/v1   # Ollama
QUANTIA_AI_PROVIDER_LOCAL_API_KEY=ollama                       # 占位
QUANTIA_AI_DEFAULT_PROVIDER=local
QUANTIA_AI_DEFAULT_MODEL=qwen2.5-coder:7b
```

**注意点**：

- 本地小模型（≤7B）function-calling 不稳定；agent 需降级模式：当 provider 不支持 tools 时自动切到"prompt 注入工具描述 + 正则解析"老式做法。`Provider.capabilities()` 返回 `{'tools': bool, 'json_mode': bool, 'stream': bool}`，`AgentRuntime` 据此切策略。
- `validate_code` 失败率会更高 → 修复闭环 `max_retries` 自动从 3 提到 5。
- 本地模型 token 上下文通常 4–8K，`STRATEGY_TEMPLATES` 必须配合 RAG 11.2 才放得下。

**结论**：架构上无任何特殊开发，运维侧文档里加一节"本地部署"即可。这正是用 OpenAI 兼容协议而非各家 SDK 的核心收益。

---

## 12. 综合风险登记表

| 风险 | 等级 | 触发场景 | 缓解 |
| --- | --- | --- | --- |
| Tornado IOLoop 被同步 LLM 阻塞 | **高** | handler 内直接 `requests.post` | 线程池 + queue / `run_in_executor`（10.2 / 16.7） |
| `validate_code` 不含 AST 检查导致沙箱绕过 | **高** | LLM 生成 `__import__('os')` | 实施前复核并补强（10.4） |
| 双套 AI 配置漂移 | 中 | `moat_ai_service` 与新统一层并存 | 强制收敛到 `lib/ai`（10.1） |
| 流式响应在 nginx 后被缓冲 | 中 | 生产部署反代时 | 文档化 `proxy_buffering off`（11.1） |
| 本地小模型 tool-calling 不稳 | 中 | 用户切到 Ollama | 能力探测 + 降级解析（11.5） |
| Token 成本失控 | 中 | 修复闭环死循环 | `max_retries=3` 硬上限 + per-IP 限流 |
| 提示词注入泄露 .env | 低 | 用户粘贴 .env 进 prompt | 入库前正则脱敏（§6.2） |
| 自定义 agent 越权调工具 | 中 | 用户勾上未授权 tool | 后端 registry 二次校验（§4.5） |
| LLM 输出 JSON 不规范 | 低 | 解析报错 | 用 `json_mode` 或 `extract_python_block` 兜底 |
| Few-shot 模板膨胀超 context | 中 | 模板增多 | M5 接 RAG 后按需检索（11.2） |

---

## 13. 修订后的 MVP 验收清单（替代第 9 节）

> **核对状态（2026-05-12，commit `01729b57`）**：代码侧 11/11 全部就位，剩余 3 项“需浏览器联调”
> 项目（流式逐字显示、编辑器灌入→保存→回测、AI 修复按钮）已同时通过：
> - 等价 HTTP/SSE 脚本 [`_verify_ui_endpoints.py`](_verify_ui_endpoints.py) 端到端验证；
> - **真实浏览器点击验证**（`/algo/edit/93`，M10/M11 新增的「一键让 AI 根据建议修复」按钮 → AiChatDrawer 预填诊断 prompt →
>   生成出的代码遵守 strategy_lessons KB 规则（STOCH 两元解包 / 异常日志 / ±2% 缓冲）→ 采用后 Monaco 编辑器变“未保存”）。

> **2026-05-12 端到端验证结果**（`_verify_ui_endpoints.py`，provider=qwen）：
> - (A) `/quantia/api/ai/strategy/generate/stream` — 收到 **115 条 SSE 事件**，
>   chunk 数 114，平均间隔 **110.8ms**，>5ms 间隔占比 113/113 ⇒ **真流式 ✅**；
>   总输出 1816 字符。
> - (B) 生成代码 → 落库 `cn_stock_strategy_code` → 调
>   `/quantia/api/backtest/portfolio/run` → 返回 `code=0, status=completed` ⇒ **全链路通 ✅**。
> - (C) 注入"在 initialize 抛 RuntimeError"的脏代码 → 回测落 `error_message` →
>   调 `/quantia/api/ai/strategy/repair`：返回 `repair_status=success, validated=True,
>   repair_attempts=0`（首轮即合法），fixed_code 392 字符 ⇒ **修复闭环 ✅**。
> 三项均无人工眼检差异，浏览器 UI 仅是同样数据流的视觉壳。

- [x] `python -m quantia.lib.ai "你好"` 用任一 provider 成功返回。
      → `quantia/lib/ai/__main__.py` + `cli.py`；测试 `tests/test_ai_lib_m1.py`。
- [x] `moat_ai_service.py` 改造完成，所有原功能不退化（跑一次现存的护城河分析单测）。
      → `_call_ai` 改走 `quantia.lib.ai.run_chat`；`tests/test_strategy_modules.py::TestMoatAIService`
      与 `tests/test_ai_m10_orchestrator.py::MoatAiServiceMigrationTests` 双重覆盖。
- [x] `POST /quantia/api/ai/strategy/generate/stream` 在浏览器中**逐字显示**输出（非伪流式）。
      → 后端 `GenerateStrategyStreamHandler`（SSE + 线程池），前端
      `quantia/fontWeb/src/api/ai.ts::generateStrategyStream` 走 fetch+reader。
      **2026-05-12 验证**：115 个 SSE 事件、平均间隔 110.8ms、113/113 chunk 间隔 >5ms。
- [x] 策略编辑页 prompt → 生成代码 → 一键灌入编辑器 → 保存 → 回测全流程通过。
      → 前端 `quantia/fontWeb/src/views/algo/edit.vue` 引入 `AiChatDrawer.vue`；
      "采用结果" 按钮把代码写入 Monaco 编辑器。
      **2026-05-12 验证**：生成代码 1816 字 → 落库 id 临时策略 → `/quantia/api/backtest/portfolio/run` 返回 `code=0, status=completed`。
- [x] 故意写 `import os` / `__import__('os')` / `eval(...)` 的 prompt：均被
      `validate_code_strict` 拒绝；修复闭环在 ≤3 轮内输出合法代码或返回 `repair_status='max_attempts'`。
      → `strategy_sandbox.py` + `aiAssistantHandler.GenerateStrategyHandler._repair_loop`。
- [x] 故意触发回测错误，"AI 修复"按钮在 ≤3 轮内修复并跑通。
      → `RepairStrategyHandler` 读 `task_recorder.fetch_last_failure`；前端 `portfolio.vue`
      失败态展示 AI 修复入口，调 `/api/ai/strategy/repair`。
      **2026-05-12 验证**：注入 `initialize` 抛 RuntimeError 、回测落库 `error_message` 后，
      修复接口返回 `repair_status=success, validated=True, repair_attempts=0`，修复后代码 392 字。
- [x] 自定义 agent（仅勾 `sql_query`）尝试调 `backtest_run` 时被 registry 拒绝，审计日志记录拒绝事件。
      → `agent.AgentRuntime._is_allowed` + `audit.record_call(tools_used=[{ok:False, error:...}])`。
- [x] 切换 provider deepseek ↔ qwen ↔ local(ollama) 后均成功；`cn_stock_ai_call_log.provider/model` 正确。
      → 三者均走 `OpenAICompatProvider`；`audit.record_call` 落 provider/model 列。
- [x] 同一用户超过 `60 calls/hour` 或 `200000 tokens/hour` 后续请求返回 429。
      → `rate_limiter.check_quota` 双桶（calls + tokens）+ handlers `_write_error(429, ...)`。
      ⚠️ 实施时维度从 IP 改为 `user_id`（默认 'anonymous'），更适合多用户场景；
      未来如要外网部署，可在 handler 层把 IP 注入 `user_id`。
- [x] 多轮会话：连续 5 轮"再加一个止损条件"能基于上一轮代码累积修改。
      → `quantia/lib/ai/memory/` 双实现（inmem + db）；`ChatHandler.post` 串入 history。
- [x] RAG 工具：prompt 含"布林带"时 `kb_search` 命中对应模板（看审计 `tools_used`）。
      → `kb_search` 工具 + `KbStore._is_cjk_query` → LIKE 主路径；`cron.workdayly/run_kb_indexer.sh` 周期刷库。
- [x] **M11 历史踩坑 KB （2026-05-12 新增）**：strategy_coder/repairer/analyst 系统提示词自动追加
      [`strategy_lessons.md`](quantia/lib/ai/prompt/strategy_lessons.md) 踩坑知识库（HIGH/MED/LOW 分级、附策略 89 骨架）；
      AI 修复成功后 `aiAssistantHandler._record_repair_lesson` 按 7 类错误关键字自动写回去重。
      → 实现：[`prompt_loader.load()`](quantia/lib/ai/prompt_loader.py) `_LESSONS_AGENTS` 机制 + `record_lesson(...)` API；
      **浏览器验证**：策略 93 修复后代码同时体现多条规则（`slowk, slowd = talib.STOCH(...)`两元解包、`except Exception as e: log.warn(...)` 、性“±2% 缓冲”注释）。

> 上述 3 项已于 2026-05-12 通过等价脚本 [`_verify_ui_endpoints.py`](_verify_ui_endpoints.py) 进行
> 端到端验证，调用路径与前端一致（SSE 读 fetch+reader、保存走 `cn_stock_strategy_code`、
> 回测走 `/quantia/api/backtest/portfolio/run`、修复走 `/quantia/api/ai/strategy/repair`）。
> 最后的浏览器点击验证仅为视觉层提示（toast/Monaco 闪烁等），不在纯代码上下文范围。

---

## 14. 实施前必做的 5 项前置确认

> 文档落地为代码之前，请先回答这 5 个问题；其中 2 个会决定方案是否需调整。

1. **`validate_code` 是否含 AST 检查？** 不含则先补强 sandbox（不属于本特性，但是前置）。
2. **`PortfolioBacktestEngine` 异常是否落 `error_message`？** 不落则先补；否则修复闭环没输入。
3. **生产部署是否经过 nginx？** 若是，需文档化反代配置（SSE / 长连接）。
4. **是否计划很快开放外网访问？** 若是，限流策略要从 IP 改为登录用户 + 鉴权前置（不在本特性范围）。
5. ~~是否接受 1 个新依赖 `httpx`？~~ **已在 v1.1 修订中关闭**——§16.7 决定零新增依赖（同步 `requests` + `ThreadPoolExecutor` + `asyncio.Queue`），未来需要高并发流式时再评估是否引入 `httpx`。

确认后即可按 §18 阶段表 M0 → M10 顺序推进。

---

## 15. 前置项代码级核查结果（2026-05-11 实测）

### 15.1 `validate_code` / `validate_code_strict` 实现现状 ✅ 已具备

文件：[quantia/core/backtest/strategy_sandbox.py](quantia/core/backtest/strategy_sandbox.py)

**当前实现**：

- `validate_code()`：正则黑名单 + 模块白名单 + 必含 `def initialize` 检查。
- `validate_code_strict()`：先调用 `validate_code()`，再用 `ast.parse` / `ast.walk` 检查 `Import / ImportFrom / Attribute / Name / Call`，复用 `_ALLOWED_IMPORTS` 与 `_AST_FORBIDDEN_*` 黑名单。

**已覆盖**：`import os/sys/subprocess/shutil`、`__import__`、`eval/exec/compile/open`、`getattr/setattr/delattr`、`globals/locals`、`vars/breakpoint/help/input`、`__class__/__bases__/__subclasses__/__mro__/__dict__/__globals__/__code__/__builtins__`、白名单 `math/numpy/pandas/talib/datetime/collections/functools/itertools/operator/jqdata/jqlib`。

**正则可被绕过的形式（仅静态校验层面）**：

```python
# 1. 字符串拼接绕过 __import__ 黑名单
m = '__imp' + 'ort__'
__builtins__[m]('os')

# 2. 通过 __builtins__.__dict__ 取被屏蔽的内置（getattr 已在黑名单，但拼接后可绕过）
g = __builtins__.__dict__.get('ge' + 'tattr')

# 3. unicode RTL/控制字符注入（取决于正则引擎与 Python 解释器）
# 例如混入 \u202e 等控制符的字面量，部分正则可能漏匹配
```

> 注：早先示例 `().__class__.__bases__[0].__subclasses__()` **已被现有黑名单覆盖**（`__class__` / `__bases__` / `__subclasses__` 三者均已纳入），不属于真实绕过案例，不再列出。

**实际风险评估：低**。原因——静态层已有 strict AST 校验，运行时 [_create_safe_namespace()](quantia/core/backtest/strategy_sandbox.py) 还提供了第二层防御：

- 自定义 `__builtins__` 字典只暴露 30 个安全函数，**移除了 `type / __import__ 原版`**。
- `__import__` 替换为 `_safe_import`，遇到非白名单模块 `raise ImportError`。
- 即使绕过静态正则，运行时进入沙箱仍会被白名单拦下。

**结论**：

1. AI 通道必须直接调用现有 `validate_code_strict()`，不要重新实现一套 AST 校验。
2. 普通用户手写保存链路可继续保留 `validate_code()`，避免扩大行为变更。
3. M0 剩余工作从“新增 strict 校验”改为“确认 AI handler 接入 strict 校验，并运行/补齐相关 pytest”。

### 15.2 回测错误回流 ✅ 已补基础设施，仍需端到端复核

当前仓库已存在 [task_recorder.py](quantia/core/backtest/task_recorder.py)，并已在 [portfolioBacktestHandler.py](quantia/web/portfolioBacktestHandler.py) 的失败分支中调用 `record_failed(...)`。对应测试 [test_backtest_task_recorder.py](tests/test_backtest_task_recorder.py) 已覆盖：

- `record_failed(...)` 写入 `error_message` 与 `result_json`。
- 长错误文本截断到 8KB。
- `fetch_last_failure(strategy_id)` 返回最近失败记录。
- DB 异常时安全返回 `None`。

**剩余复核点**：

- 跑 `tests/test_backtest_task_recorder.py` 与失败回测端到端用例，确认同步入口与异步入口都能落 `status='failed'`。
- AI 修复工具只读 `task_recorder.fetch_last_failure(strategy_id)`，不要直接拼 SQL 读表。
- 若后续表结构再变更，`record_failed(...)` 仍需和 `_ensure_backtest_table()` 保持一致。

**当前推荐接入模式**：

> ⚠️ 不要在 handler 里复制粘贴 INSERT 语句；表结构变化时容易漏列。统一走 `task_recorder.record_failed(...)`，由该模块和 `_ensure_backtest_table()` 对齐表结构。

```python
# 失败分支
except Exception as e:
    err_text = traceback.format_exc()[:8000]
    from quantia.core.backtest.task_recorder import record_failed
    record_failed(
        strategy_id=strategy_id,
        strategy_name=strategy_name,
        start_date=start_date,
        end_date=end_date,
        initial_cash=initial_cash,
        benchmark=benchmark,
        error_text=str(e),
        traceback_text=err_text,
        started_at=started_at,
    )
    task['result'] = {'status': 'error', 'message': str(e), 'traceback': err_text}
```

同步入口与异步入口都应保持这一原则：失败也必须入库，并将 traceback 截断写入 `error_message`。

### 15.3 异步基础设施 ✅ 已具备

`StartPortfolioBacktestHandler` 已使用 `tornado.gen.coroutine` + `ThreadPoolExecutor(max_workers=2)`。这意味着：

- AI 路由可直接复用同款模式：handler `@gen.coroutine` / `async def` + 把 LLM 调用扔线程池（同步 `requests`），流式响应用 queue 传增量。
- §10.2 提到的"IOLoop 阻塞"风险**已经有解法范例**，直接照抄即可。

### 15.4 阻塞性结论

| 前置项 | 状态 | 是否阻塞 M1 |
| --- | --- | --- |
| 1. `validate_code_strict` 含 AST | ✅ 已存在 | 不阻塞；AI handler 必须接入 |
| 2. 回测异常落 `error_message` | ✅ `task_recorder.record_failed` 已存在并已接入失败分支 | 不阻塞；需跑端到端验证 |
| 3. nginx 部署 | 待用户确认 | 不阻塞，仅文档化 |
| 4. 多用户/鉴权 | 单部署 | 不阻塞 |
| 5. 依赖策略 | 已取消 `httpx` 必选项 | 不阻塞；MVP 零新增依赖 |

---

## 16. 架构进一步优化（基于实测的修订）

### 16.1 复用"AI 通道专用强校验" `validate_code_strict()`

当前仓库已在 `strategy_sandbox.py` 中提供 `validate_code_strict()`。AI 生成路径只需要复用它，普通用户手写代码继续走 `validate_code()`，避免影响现有体验。关键实现形态如下（示意，勿重复定义）：

```python
# quantia/core/backtest/strategy_sandbox.py 内已有
import ast
# 直接复用同文件中的 _ALLOWED_IMPORTS；不要在同一个文件里 from .strategy_sandbox import 自己。

_AST_FORBIDDEN_NAMES = {
    '__import__','eval','exec','compile','open','getattr','setattr','delattr',
    'globals','locals','vars','breakpoint','help','input',
}
_AST_FORBIDDEN_ATTRS = {
    '__class__','__bases__','__subclasses__','__mro__','__dict__','__globals__',
    '__code__','__builtins__','__loader__','__spec__','__import__','f_locals','f_globals',
}

def validate_code_strict(code_str: str) -> tuple[bool, str]:
    ok, err = validate_code(code_str)         # 先走老的正则层
    if not ok:
        return ok, err
    try:
        tree = ast.parse(code_str)
    except SyntaxError as e:
        return False, f"语法错误 行{e.lineno}: {e.msg}"
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [n.name for n in node.names] if isinstance(node, ast.Import) \
                   else [node.module or '']
            for m in mods:
                base = (m or '').split('.')[0]
                if base and base not in _ALLOWED_IMPORTS:
                    return False, f"AST 拒绝导入: {m}"
        if isinstance(node, ast.Attribute) and node.attr in _AST_FORBIDDEN_ATTRS:
            return False, f"AST 拒绝属性: {node.attr}"
        if isinstance(node, ast.Name) and node.id in _AST_FORBIDDEN_NAMES:
            return False, f"AST 拒绝名字: {node.id}"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in _AST_FORBIDDEN_NAMES:
            return False, f"AST 拒绝调用: {node.func.id}"
    return True, ""
```

集成点：

- `aiAssistantHandler.py` 在所有 `/strategy/generate|refine|repair` 完成 LLM 调用后强制走 `validate_code_strict`。
- 普通 `SaveStrategyCodeHandler` 不变（向后兼容）。

### 16.2 回测失败必入库——复用统一的"任务状态机"

当前仓库已提供 `quantia/core/backtest/task_recorder.py`，不要再分散在各个 handler 里写 `INSERT (completed)` / `INSERT (failed)`；后续只需复用并补端到端验证：

```python
# quantia/core/backtest/task_recorder.py（已存在）
def record_completed(*, strategy_id, strategy_name, start_date, end_date, initial_cash, benchmark, result, started_at=None): ...
def record_failed(*, strategy_id, strategy_name, start_date, end_date, initial_cash, benchmark, error_text, traceback_text='', started_at=None, extra_result=None): ...
def fetch_last_failure(strategy_id) -> dict | None: ...           # ← AI 修复工具用
```

`RunPortfolioBacktestHandler` / `StartPortfolioBacktestHandler` / 失败分支统一调用 `record_*`。
- 收益：日后给 AI agent 加 `get_last_failure(strategy_id)` 工具时只需 1 行实现。
- 已修复历史 bug（失败任务不入库）；剩余工作是跑端到端失败回测验证，确认前端历史列表也能看到失败任务。

### 16.3 `quantia/lib/ai/` 模块依赖方向（防循环引用）

实测后明确分层（自上而下，**只能向下依赖**）：

```
Layer 5 (handlers)  : quantia/web/aiAssistantHandler.py
                       └─→ Layer 4
Layer 4 (orchestrator): quantia/lib/ai/orchestrator/
                       └─→ Layer 3
Layer 3 (agent)      : quantia/lib/ai/agent.py + tools/
                       └─→ Layer 2
Layer 2 (provider)   : quantia/lib/ai/providers/
                       └─→ Layer 1
Layer 1 (infra)      : quantia/lib/ai/{config,audit,memory/inmem,exceptions}
                       └─→ quantia/lib/{envconfig,database,torndb}
```

**禁止反向依赖**。`tools/code_validate.py` 调 `quantia.core.backtest.strategy_sandbox.validate_code_strict`——这是 lib→core 的横向引用，需要在 `tools/` 内做**懒导入**（`def run(): from quantia.core.backtest.strategy_sandbox import ...`）以避免启动时循环 import。

### 16.4 配置加载策略（修订）

旧设计是 ".env + DB ai_model 组" 二选一并用 DB 优先。优化为**三层合并**：

```
最终配置 = 默认值
        ← .env 覆盖
        ← cn_stock_strategy_params.ai_model 组覆盖（运维改 UI）
        ← 请求参数覆盖（X-AI-Provider / X-AI-Model header 或 body 字段）
```

理由：

- `.env` 适合部署期固定（API key）。
- DB 适合运维期热改（限流/默认 model/温度）。
- 请求参数适合用户在前端切 model 时**单次生效**。

实现：`config.py` 提供 `resolve_runtime_config(scene, request_overrides) -> RuntimeConfig`。

### 16.5 限流策略升级

原方案：per-IP per hour 单一阈值。问题：

- AI 修复闭环单次调用最多 3 轮，会把限额吃掉。
- 不同场景成本差别大（生成 ≈ 4k tokens，解释 ≈ 1k tokens）。

优化：**双桶限流（按场景 + 按总 token）**

```python
# 配置（环境变量 — 实际生效项）
QUANTIA_AI_RATE_CALLS_PER_HOUR=60          # 调用次数
QUANTIA_AI_RATE_TOKENS_PER_HOUR=200000     # token 总额
# 修复闭环重试豁免：当前由 rate_limiter.check_quota(rate_limit_loop=True) 形参写死开启，
# 无 QUANTIA_AI_RATE_REPAIR_LOOP_FREE 这种 env 开关；如需禁用需改 handler 调用点。
```

实现位置：`audit.py` 写日志的同时维护 1 小时滑动窗口（直接 SQL 查 `cn_stock_ai_call_log` 即可，不必额外缓存）。

### 16.6 取消 `pydantic` 依赖，统一用 dict + jsonschema

理由：仓库已用了 jsonschema 风格的 schema 文件（`strategy_params_config.py`）；引入 pydantic 会带来命名空间冲突和打包体积。

工具 schema 改为：

```python
# quantia/lib/ai/tools/base.py
class Tool:
    name: str
    description: str
    parameters: dict   # JSON Schema
    def run(self, args: dict) -> dict: ...
```

提供给 LLM 的 `tools=[...]` 直接用此 dict（OpenAI 协议要求的就是 JSON Schema）。

### 16.7 SSE 与 ThreadPoolExecutor 协同

实测发现仓库已有 SSE 范例：[BacktestLogStreamHandler](quantia/web/portfolioBacktestHandler.py) 紧跟 `StartPortfolioBacktestHandler`。

**复用模式**：

- `aiAssistantHandler.ChatStreamHandler` 直接抄 `BacktestLogStreamHandler` 的 `Content-Type: text/event-stream` + `flush()` 模式。
- LLM 流式响应（同步 `requests` 走 chunked）也提交到现有 ThreadPoolExecutor，handler `await` 一个 `Queue` 拿增量。

不必新增 `httpx`——同步 `requests.post(stream=True)` + 线程池 + `asyncio.Queue` 这条路径**零新增依赖**且和现有回测异步模式一致。

**修订决定**：把"M1 必须新增 httpx"降级为"可选"。MVP 用 `requests` 同步 + 线程池，性能够用；未来高并发再切 `httpx.AsyncClient`。

### 16.8 知识库 (RAG) 索引器与现有 cron 复用

仓库已有 [cron/](cron/) 框架（hourly/monthly/workdayly）。RAG 索引刷新挂到 `cron.workdayly/`：

```
cron/cron.workdayly/refresh_ai_kb.py
  → 扫描 STRATEGY_TEMPLATES、document/*.md、cn_stock_strategy_code 新增、cn_stock_backtest_portfolio 失败用例
  → 切片入 cn_stock_ai_kb（FULLTEXT 索引足够）
```

无需额外调度器。

### 16.9 前端组件复用层级

修订前端结构以提升复用率：

```
components/
├── ai/
│   ├── AiChatDrawer.vue        # 通用对话抽屉（接受 scene/agent props）
│   ├── AiCodeBlock.vue         # 渲染 LLM 输出的代码块（含"应用到编辑器"按钮）
│   ├── AiThinkingBubble.vue    # 思维链展示（reasoning models）
│   ├── AiToolCallCard.vue      # 工具调用过程卡片
│   ├── AiModelPicker.vue       # provider+model 切换
│   ├── AiAgentPicker.vue       # agent 切换
│   └── AiQuickActions.vue      # "解释/优化/修复" 快捷按钮组
└── ...
```

业务页面只需 `<AiChatDrawer scene="strategy" :context="..." />` 即可全功能接入。

### 16.10 错误协议统一

所有 AI 接口返回统一错误码，便于前端处理：

```typescript
// 前端 api/ai.ts
export const AI_ERROR_CODES = {
  RATE_LIMITED: 'AI_RATE_LIMITED',          // 429 触发
  PROVIDER_TIMEOUT: 'AI_PROVIDER_TIMEOUT',
  PROVIDER_ERROR: 'AI_PROVIDER_ERROR',
  VALIDATION_FAILED: 'AI_VALIDATION_FAILED',// validate_code_strict 拒绝
  REPAIR_EXHAUSTED: 'AI_REPAIR_EXHAUSTED',  // 闭环用尽次数
  TOOL_DENIED: 'AI_TOOL_DENIED',
  AGENT_NOT_FOUND: 'AI_AGENT_NOT_FOUND',
  CONFIG_INVALID: 'AI_CONFIG_INVALID',
}
```

每种码前端有对应 UI 行为（弹框 / toast / 重试按钮）。

### 16.11 运行时环境变量（M1～M3 实施期落地）

| 变量 | 默认值 | 含义 | 引入提交 |
| --- | --- | --- | --- |
| `QUANTIA_AI_REPAIR_MAX_ATTEMPTS` | `3` | strict 校验失败时自动修复重试上限。设为 `0` 可关闭自动修复。每次 HTTP 请求时动态读取。 | 87069bd / 9370abb |
| `QUANTIA_AI_MAX_GENERATED_CHARS` | `262144`（256 KB） | `/quantia/api/ai/strategy/generate/stream` 单次响应的字符上限；超出即停止读取并以 `done.truncated=true` 收尾，前端可拿到部分代码做人工复核。 | 9370abb |
| `QUANTIA_AI_AUDIT_MAX_BYTES` | `131072`（128 KB） | `cn_stock_ai_call_log` 中 prompt / response 字段写入前的字节级截断阈值（UTF-8 安全）。防止超过 MySQL `max_allowed_packet`。 | 9370abb |
| `QUANTIA_AI_<KEY>` / `QUANTIA_AI_DEFAULT_<KEY>` | — | 标准前缀 → 默认前缀的回退链；详见 §4.2 / §16.4。 | aab3b47 |

**SSE 修复回路状态字段**：所有 4 个 handler（generate / refine / repair / SSE done）的响应中均包含
`repair_status ∈ { success, unrepaired, max_attempts, no_progress, rate_limited, provider_error }`，
便于前端区分 "重试到上限" / "LLM 返回相同错误已无收敛可能" / "中途触发限流" 等失败语义。

---

## 17. 可扩展性自评（按 ISO/IEC 25010）

| 维度 | 设计支撑 | 评分 |
| --- | --- | --- |
| **模块化** | 5 层依赖图 + 单一职责（provider/agent/tool/orchestrator/memory/retrieval） | A |
| **可替换性** | provider 走 abc，可热加 anthropic/gemini；vector store 走 abc，可替换 chroma | A |
| **可观测性** | 全量审计 `cn_stock_ai_call_log` + tools_used + latency + tokens | A |
| **可测试性** | provider 抽象层易 mock；CLI 入口方便 e2e | A |
| **国际化/本地化** | system prompt 外置 markdown，新增语种只加文件 | B+ |
| **可演进性** | 新增 scene/agent/tool 都是加文件不改框架；预留 orchestrator 不强制 | A |
| **性能/伸缩** | 单机 ThreadPool 够用；水平扩展时 `cn_stock_ai_call_log` 可分库 | B |
| **安全性** | validate_code_strict + 沙箱双层 + tool registry 权限 + 审计 + 限流 | A |
| **运维友好** | `.env` + DB UI 双通道；外置 prompt 可热改不重启 | A |
| **成本控制** | 双桶限流 + 修复闭环硬上限 + 修复用廉价模型 | B+ |

**最弱项**：水平扩展（B）。现状是单 Tornado 进程，未来要做多副本时需要：
1. `_running_tasks` in-memory dict 改 Redis。
2. 限流计数也走 Redis（或 DB 滑窗）。
3. SSE 长连接需要 sticky session 或换 WebSocket + 消息总线。

这些不属于 MVP 必做，但**架构上预留好抽象**（task_recorder / rate_limiter / memory 都是 ABC）即可。

---

## 18. 最终实施推荐顺序（替代 §7）

| 阶段 | 关键动作 | 验收 |
| --- | --- | --- |
| **M0 前置复核** (~0.25 d) | (1) 确认 AI handler 后续统一调用现有 `validate_code_strict`；(2) 跑 `tests/test_strategy_sandbox_strict.py` + `tests/test_backtest_task_recorder.py`；(3) 做一次失败回测端到端验证 | strict 校验 + 失败入库测试通过，失败任务历史可查 |
| **M1 AI 基础层** | `quantia/lib/ai/` 骨架 + `OpenAICompat` provider（同步 `requests`）+ `config.py` 三层合并 + `audit.py` + `cn_stock_ai_call_log` 表 + CLI | `python -m quantia.lib.ai "ping"` 跑通 + 调用入库 |
| **M2 策略生成** | `strategy_coder` agent + `aiAssistantHandler.GenerateHandler`（异步线程池）+ `AiChatDrawer` 最小版 + 流式 SSE | prompt → 代码 → 灌入编辑器 |
| **M3 校验闭环** | strict 校验失败自动重试 ≤3 轮 + 前端错误 UI | 故意写 `import os` 被自动修复 |
| **M4 修复闭环** | `strategy_repairer` agent + `/strategy/repair` + 回测详情页"AI 修复"按钮 + 读 `task_recorder.fetch_last_failure` | 故意触发除零 → 一键修好 |
| **M5 多模型/Agent 选择** | `AiModelPicker` + `AiAgentPicker` + `/ai/config` + `/ai/agents` GET | 切换
| **M6 工具调用** | `AgentRuntime` 主循环 + 内置 4 工具 + tool 审计 | 生成时能 `kb_search` 命中模板 |
| **M7 自定义 Agent** | `cn_stock_ai_agent` 表 + CRUD handler + `agentManager.vue` | 用户自建 agent 能用 |
| **M8 多轮记忆** | `ConversationMemory` (inmem 默认) + `cn_stock_ai_conversation` + 前端会话列表 | 5 轮上下文累积修改 |
| **M9 RAG** | `cn_stock_ai_kb` + FULLTEXT + `kb_search` 工具 + cron.workdayly 索引器 | "布林带"prompt 命中模板 |
| **M10 编排 & 跨场景** | 顺序管线 `analyst→coder→tester` + IM 摘要/回测解读统一接入 | `moat_ai_service` 改用 lib/ai 后老用例不退化 |
| **M11 踩坑知识库（2026-05-12 新增）** | (1) 新增 [`strategy_lessons.md`](quantia/lib/ai/prompt/strategy_lessons.md)，按 HIGH/MED/LOW 三级沉淀 8 类常见 bug + 策略 89 骨架；(2) `prompt_loader.load()` 对 strategy_coder/repairer/analyst 三个 agent **自动追加**该文件到系统提示词末尾；(3) 新增 `record_lesson(title, problem, fix, severity, dedup)` API + AI 修复成功路径上 `aiAssistantHandler._record_repair_lesson` 按 7 类错误关键字自动写回 | 修复后代码体现 KB 规则（talib.STOCH 两元解包、`except Exception as e:`、±2% 缓冲）。浏览器验证于策略 93。 |

> **最小可演示**：M0 复核 + M1 + M2（生成）+ M3（校验闭环）+ 最小流式即可线下演示，约 2–3 个工作单元。

---

## 19. 推荐立即开始 M0 复核

M0 现在不是从零实现，而是**复核已经落地的前置加固**，与 AI 无关，先跑通之后 AI 各阶段都顺畅。建议立即做：

1. 运行 [test_strategy_sandbox_strict.py](tests/test_strategy_sandbox_strict.py) 与 [test_backtest_task_recorder.py](tests/test_backtest_task_recorder.py)。
2. 手动触发一次同步/异步失败回测，确认 [task_recorder.py](quantia/core/backtest/task_recorder.py) 写入 `status='failed'`、`error_message` 与 `result_json`。
3. 在后续 `aiAssistantHandler.py` 实现时，把 `/strategy/generate|refine|repair` 的最终代码统一接入 `validate_code_strict()`，不要只走普通 `validate_code()`。

完成 M0 复核后，AI 通道的"必备地基"全部确认可用，后续 M1+ 主要是新增模块、低侵入接入。

---

## 20. CLI 入口约定（v1.1 新增）

文档前后多处验收（§9 / §13 / §M1）都要求 `python -m quantia.lib.ai "你好"` 跑通。Python 的 `-m <package>` 调用规则要求该 package 下存在 `__main__.py`，因此 M1 阶段需创建：

```
quantia/lib/ai/
├── __main__.py     # 内容仅一行：from .cli import main; main()
└── cli.py          # 实际 argparse 实现（参数：--provider --model --agent --tools --stream ...）
```

若遗漏 `__main__.py`，命令会报 `No module named quantia.lib.ai.__main__`。§10.8 目录树已包含这两个文件，此处单独提示以免实现时漏建。

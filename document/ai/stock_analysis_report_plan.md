# AI 个股分析报告 — 集成方案 (Final)

> **状态**: 已审核 · 待实现  
> **日期**: 2026-05-23  
> **背景**: 参考 `document/SKILL.md` (GLM-V Stock Analyst) 中结构化报告输出的设计，结合 Quantia 已有架构，设计最小代价、最大复用的集成方案。

---

## 一、需求定位

**一句话目标**: 用户输入一个股票代码，系统自动汇聚多维数据 + AI 生成结构化分析报告，在 Web 页面上展示。

**用户场景**:
- 从任意数据表的股票行点击「分析」→ 跳转报告页
- 直接在报告页搜索股票 → 一键生成
- 模拟交易/回测详情页查看某只持仓 → 快速分析

**核心价值** (借鉴 SKILL):
- 结构化报告格式（核心数据 → 走势分析 → 多空对比 → 操作建议）
- 新闻精准筛选 + 事件驱动分析
- 多角色操作建议（持仓者 / 观望者 / 短线者）
- 所有结论标注数据来源

---

## 二、架构设计

### 2.1 整体流程

```
┌─────────────┐     POST /api/ai/report/generate     ┌────────────────────┐
│  前端 Vue   │ ─────────────────────────────────→   │ StockReportHandler │
│  analysis   │ ←─── SSE stream (markdown chunks) ── │                    │
│  .vue       │                                      └────────┬───────────┘
└─────────────┘                                               │
                                                              │ run_agent()
                                                              ▼
                                                    ┌─────────────────────┐
                                                    │  AgentRuntime       │
                                                    │  (已有, 最多4轮)    │
                                                    │                     │
                                                    │  Tools 按需调用:    │
                                                    │  · kline_fetch      │
                                                    │  · sql_query        │
                                                    │  · web_search       │
                                                    │  · stock_profile ★  │
                                                    └─────────────────────┘
```

### 2.2 关键设计决策

| 决策点 | 方案 | 理由 |
|--------|------|------|
| 数据获取方式 | Agent 自主调 Tools（非 Handler 硬编码） | 更灵活、LLM 按需取数据、无需为每种股票写不同逻辑 |
| 报告生成 | `run_agent` + 报告专属 system_prompt | 复用现有 agent 基础设施，零新框架 |
| 输出传输 | SSE 流式 (先工具轮次 → 后流式输出文本) | 用户 3~5s 内看到首字节，体验好 |
| 图表渲染 | 后端返回 K线数据 JSON + 前端 ECharts | 交互性 > 静态图片；复用已有 `getKlineData` |
| Markdown 渲染 | 前端 `markdown-it` + 自定义容器 | 比 `<pre>` 好 100 倍，支持表格/加粗/列表 |
| 报告缓存 | 同一 code+date 10 分钟内复用 | 避免重复调用 LLM |
| 历史记录 | 存 `cn_stock_ai_report` 表 | 支持回看、收藏、分享 |

### 2.3 新增模块清单

| 文件 | 类型 | 行数估计 | 说明 |
|------|------|---------|------|
| `quantia/web/stockReportHandler.py` | Handler | ~250 | 生成 + 流式输出 + 历史查询 |
| `quantia/lib/ai/tools/stock_profile.py` | Tool | ~120 | 聚合指标/资金/基本面为 1 个 JSON |
| `quantia/fontWeb/src/views/stock/analysis.vue` | Page | ~450 | 报告页（搜索+K线+Markdown） |
| `quantia/fontWeb/src/api/report.ts` | API | ~40 | 前端 API 层 |
| Agent seed (DB) | 数据 | — | 内置 `stock_analyst` agent |

**不新增**: Python 依赖、独立 venv、外部脚本、图片生成管线。

---

## 二-B、数据覆盖现状 & 差距分析

### 当前已有的财务数据

| 数据表 | 核心字段 | 更新频率 | 来源 |
|--------|----------|---------|------|
| `cn_stock_selection` (70+列) | PE/PB/PS/PCF/ROE/ROA/ROIC/毛利率/净利率/资产负债率/3年复合增长 | 每交易日 | 东方财富选股器 |
| `cn_stock_financial` (20列) | EPS/BPS/营收/净利/同比增速/ROE/ROA/毛利率/净利率/负债率/周转率 | 月度增量 | AkShare 东方财富 |
| `cn_stock_spot` | PE9/PB/EPS/ROE/毛利率/负债率/营收增速/利润增速 | 实时(日内) | 多源爬虫 |
| `cn_stock_fund_flow` | 主力/超大/大/中/小单净流入(1d/3d/5d/10d) | 每交易日 | 东方财富/新浪 |
| `cn_stock_bonus` | 分红/股息率/每股收益/利润增长 | 月度 | 东方财富 |

### 当前缺失的关键数据 (用户需求)

| 缺失数据 | 重要性 | 可用数据源 | 方案 |
|----------|--------|-----------|------|
| **研发费用/占营收比** | ⭐⭐⭐ | AkShare `stock_financial_analysis_indicator_em` 扩展字段 / 财报原文 | Phase 2 扩展 `cn_stock_financial` 表 |
| **专利数据** | ⭐⭐ | 国家知识产权局 API / 巨潮资讯专利公告 | Phase 3 新增爬虫 |
| **重大技术突破/公告** | ⭐⭐⭐ | web_search (已有 Tool) + 巨潮公告爬虫 | Phase 1: web_search 覆盖；Phase 3: 结构化存储 |
| **机构评级变动** | ⭐⭐ | 东方财富研报数据 | Phase 3 新增爬虫 |
| **ESG / 合规风险** | ⭐ | 暂无合适免费源 | 远期 |

### 设计决策：对缺失数据的补偿

1. **Phase 1 (MVP)**: 通过 `web_search` Tool 让 AI 搜索"研发投入"/"专利"/"技术突破"相关新闻 → 非结构化但即时可用
2. **Phase 2**: 扩展 `stock_financial_data.py` 抓取 AkShare 更多财务字段（研发费用、管理费用、折旧摊销）
3. **Phase 3**: 新增 `stock_announcement_em.py` 爬虫，抓取重大公告 + 专利/技术相关标签

---

## 二-C、增量获取与智能缓存策略

### 问题：反复查看同一股票时不应重复获取数据

**设计原则**:
- **数据层**: DB 数据本身由定时任务更新（日频/月频），查看时不触发新抓取
- **报告层**: 同一股票短时间内多次查看 → 复用已缓存的报告
- **发现新数据时**: 标记为"有增量更新"，结合历史数据重新生成综合分析

### 三层缓存机制

```
┌─────────────────────────────────────────────────────────────────────┐
│ Layer 1: DB 数据 (由 cron 定时刷新)                                 │
│   cn_stock_selection: 每交易日 ~08:30 更新                          │
│   cn_stock_financial: 每月财报季更新 (3月/4月/8月/10月)              │
│   cn_stock_fund_flow: 每交易日 ~16:30 更新                          │
│   判断"有更新": report_date/date 字段 > 上次报告的数据截止日         │
└─────────────────────────────────────────────────────────────────────┘
          ↓ 读取（零网络开销）
┌─────────────────────────────────────────────────────────────────────┐
│ Layer 2: stock_profile Tool 返回结果缓存 (TTL = 当日收盘前有效)      │
│   key: (code, trade_date)                                           │
│   逻辑: 同一交易日内，stock_profile 对同一 code 返回相同结果         │
│         盘中实时价来自 cn_stock_spot (日内已由爬虫刷新)              │
│   存储: 内存 dict + 可选 Redis (单机用 dict 足够)                   │
└─────────────────────────────────────────────────────────────────────┘
          ↓ 喂给 Agent
┌─────────────────────────────────────────────────────────────────────┐
│ Layer 3: 报告缓存 (cn_stock_ai_report 表)                           │
│   判断复用: 同 code + created_at 在 TTL 内 + 数据截止日无变化       │
│   TTL 策略:                                                         │
│     · 盘中 (09:30-15:00): TTL = 30 分钟 (价格在变)                 │
│     · 收盘后 (15:00-次日09:30): TTL = 当日有效 (数据不再变)         │
│     · 月报更新后: 首次查看强制重新生成 (新财报 = 新结论)            │
│   有增量时: 新报告 + 引用上次报告的关键结论做对比                    │
│   显示: "数据已更新，本次报告结合了最新 Q1 财报数据"                │
└─────────────────────────────────────────────────────────────────────┘
```

### 数据变更检测逻辑

```python
def _has_data_update(code: str, last_report_date: datetime) -> tuple[bool, str]:
    """检测自上次报告后是否有新数据。
    
    Returns: (has_update, reason)
    """
    # 1. 检查财报更新
    latest_financial = query("SELECT MAX(report_date) FROM cn_stock_financial WHERE code=%s", code)
    if latest_financial > last_report_date:
        return True, f"新财报({latest_financial.strftime('%Y-Q%q')})"
    
    # 2. 检查选股数据日期
    latest_selection = query("SELECT MAX(date) FROM cn_stock_selection WHERE code=%s", code)
    if latest_selection > last_report_date.date():
        return True, f"行情数据更新至{latest_selection}"
    
    # 3. 检查资金流向
    latest_flow = query("SELECT MAX(date) FROM cn_stock_fund_flow WHERE code=%s", code)
    if latest_flow > last_report_date.date():
        return True, "资金面数据已更新"
    
    return False, ""
```

### 报告生成策略 (综合新旧数据)

```python
def generate_or_reuse(code: str) -> ReportResult:
    """智能决策：复用旧报告 / 增量更新 / 全新生成"""
    last_report = get_latest_report(code)
    
    if last_report is None:
        return _generate_fresh(code)  # 首次生成
    
    if _within_ttl(last_report):
        has_update, reason = _has_data_update(code, last_report.created_at)
        if not has_update:
            return ReportResult(report=last_report, source='cache', msg='数据无变化，复用上次分析')
        else:
            # 有增量：生成新报告，但 prompt 中注入上次结论供 AI 对比
            return _generate_with_history(code, last_report, reason)
    else:
        return _generate_fresh(code)
```

---

## 二-D、AI 综合得分交易过滤 (事件风险/机会识别)

### 需求本质

> "能够考虑后期股票的买卖能通过 AI 综合得分进行过滤，避免因为重大事项导致巨额亏损或者错过上升期的巨大盈利"

### 现有基础 (已实现但未全面启用)

系统已有 `ai_decision` 模块 (Phase 4)：
- `cn_stock_ai_decision_config` — 配置表（阈值、prompt 模板、provider）
- `cn_stock_trade_ai_score` — 评分结果表（score/action/confidence/risk_flags）
- `score_trade()` 函数 — 在模拟交易信号产生时调用，返回 pass/reject
- Gate 机制：`buy_threshold` (≥70 pass) / `sell_threshold` (≤40 pass)

### 增强方案：报告 → 交易联动

```
┌──────────────┐         ┌──────────────────┐         ┌─────────────────┐
│ 策略产生信号 │ ──────→ │ AI 综合评分      │ ──────→ │ 执行/拒绝/观望  │
│ (buy/sell)   │         │ (score_trade)    │         │ + 通知用户      │
└──────────────┘         └──────────────────┘         └─────────────────┘
                                │
                    ┌───────────┼───────────┐
                    ↓           ↓           ↓
           技术面评分     基本面评分    事件面评分
           (已有指标)    (财务+增速)   (新闻+公告)
```

### 新增：事件风险识别维度

在 `score_trade` 的 `input_summary` 中增加事件维度：

```python
# context_builder.py 扩展
def build_input_summary(..., event_context: Optional[Dict] = None):
    summary = {
        # 原有 5 维
        'indicators': {...},      # 技术指标快照
        'selection': {...},       # 基本面快照  
        'kline_window': [...],    # K线窗口
        'portfolio_snapshot': {}, # 持仓状态
        'market_context': {},     # 大盘环境
        
        # 新增: 事件维度
        'event_context': {
            'recent_announcements': [...],  # 近期重大公告
            'news_sentiment': 'positive/negative/neutral',
            'risk_events': [                # 风险事件
                {'type': 'st_warning', 'date': '2026-05-20', 'desc': '...'},
                {'type': 'major_loss', 'date': '2026-05-18', 'desc': '...'},
            ],
            'opportunity_events': [         # 机会事件
                {'type': 'patent_grant', 'desc': '获得关键专利...'},
                {'type': 'contract_win', 'desc': '中标重大项目...'},
            ]
        }
    }
```

### AI Gate Prompt 增强（事件敏感）

```
你是量化交易 AI 风控官。根据以下信息评估该交易信号的执行风险：

## 关键风险事件清单（必须优先考虑）
{risk_events}

## 重大机会事件（可适当提高评分）
{opportunity_events}

## 评分规则（0-100分）
- 70分以上：建议执行买入
- 50-70分：观望，等待确认信号
- 50分以下：建议放弃/卖出

## 以下情况直接低分（<30分）：
- ST 预警 / 退市风险
- 财务造假/重大违规公告
- 业绩大幅下修（> -50%）
- 实控人被调查/冻结
- 连续多日主力大幅流出 + 利空新闻

## 以下情况可加分（最高20分附加）：
- 突破性技术/专利（与主营强相关）
- 重大合同/政策利好（有具体金额/文件号）
- 连续超预期财报 + 机构增持
- 行业拐点确认（多公司同步受益）
```

### 集成到模拟交易/实盘流程

```python
# paper_trading 信号执行前调用
async def execute_signal_with_ai_gate(signal):
    # 1. 获取事件上下文（从最近报告或 web_search）
    event_ctx = await _build_event_context(signal.code)
    
    # 2. 调用增强版 score_trade
    result = score_trade(
        cfg=ai_config,
        code=signal.code,
        direction=signal.direction,
        indicators=signal.indicator_snapshot,
        event_context=event_ctx,
        ...
    )
    
    # 3. Gate 判断
    if result['ai_gate_result'] == 'reject':
        # 记录但不执行，通知用户
        notify_user(f"⚠️ AI 风控拒绝 {signal.code} {signal.direction}: "
                   f"评分 {result['ai_score']}/100 — {result['reason_summary']}")
        return
    
    if result['ai_gate_result'] == 'pass':
        # 正常执行 + 记录 AI 建议
        execute_trade(signal, ai_score_id=result['ai_score_id'])
```

---

## 三、后端详细设计

### 3.1 新 Tool: `stock_profile`

**为什么新增**: 现有 `kline_fetch` 只返回 OHLCV，`sql_query` 需要 LLM 写 SQL（浪费 token）。`stock_profile` 是一个"数据聚合快捷方式"，一次调用返回个股全貌。

```python
class StockProfileTool(Tool):
    name = 'stock_profile'
    description = '获取个股综合画像：最新行情+近期指标+资金流向+K线形态信号。'
    parameters = {
        'type': 'object',
        'required': ['code'],
        'properties': {
            'code': {'type': 'string', 'description': '6位股票代码'}
        }
    }
    
    def run(self, args):
        code = args['code']
        return {
            'spot': _query_latest_spot(code),        # 最新价/涨跌/市值/PE/PB
            'indicators': _query_indicators(code),   # MACD/KDJ/RSI/BOLL 最新值
            'fund_flow': _query_fund_flow(code, 5),  # 近5日主力净流入
            'patterns': _query_patterns(code),       # 今日K线形态信号
            'kline_30d': _query_kline(code, 30),     # 近30日OHLCV摘要
        }
```

**查询全部来自 MySQL** (cn_stock_spot / cn_stock_indicators / cn_stock_fund_flow / cn_stock_kline_pattern)，不调外部 API（遵守 Fetch/Analysis/Web 分离原则）。

### 3.2 Handler: `stockReportHandler.py`

```python
# 端点：POST /api/ai/report/generate (SSE 流式)
# 端点：GET  /api/ai/report/history   (历史列表)
# 端点：GET  /api/ai/report/detail    (单条报告)

class StockReportGenerateHandler(BaseHandler):
    """两阶段输出：
    1) Agent 工具轮次（非流式，~2-5s）→ 收集数据
    2) 最终报告生成（流式输出 markdown chunks）
    """
    async def post(self):
        code = self.get_argument('code')
        # 缓存检查：10分钟内同 code 有已完成报告 → 直接返回
        cached = _check_report_cache(code)
        if cached:
            self._write_sse_full(cached)
            return
        
        # 加载 agent 配置
        agent_cfg = agent_store.get('stock_analyst')
        overrides = {'provider': ..., 'model': ...}
        
        # 阶段1: Agent 工具调用（kline_fetch + stock_profile + web_search）
        # 阶段2: 流式输出最终报告
        user_msg = f"请为 A 股 {code} 生成分析报告。"
        
        for chunk in stream_agent_report(agent_cfg, user_msg, overrides):
            self._write_sse_chunk(chunk)
        
        # 持久化报告
        _save_report(code, full_text)
```

### 3.3 Agent System Prompt (核心资产)

```markdown
你是 Quantia 平台的 AI 股票分析师。基于用户指定的 A 股代码，使用工具获取数据后生成结构化分析报告。

## 报告结构（严格遵循）

### 📊 {股票名} ({代码}) 分析报告

#### 一、核心数据
- 当前价格、今日涨跌（来自 stock_profile）
- 市值、PE、PB
- 近期资金流向趋势

#### 二、技术面分析
- K线趋势判断（上涨/下跌/震荡/突破）
- 均线排列状态
- 关键指标信号（MACD金叉/死叉、KDJ超买超卖、RSI状态）
- K线形态信号（如有）
- 支撑位/压力位估算

#### 三、资金面
- 近5日主力净流入/流出趋势
- 大单/特大单方向

#### 四、近期事件（如 web_search 可用）
- 近期重大新闻/公告（仅直接相关的）
- 分析师评级变动

#### 五、多空对比

| 🟢 看多因素 | 🔴 看空因素 |
|------------|------------|
| (具体事实+数据支撑) | (具体事实+数据支撑) |

#### 六、综合判断与操作建议
- **评级**: 🟢买入 / 🟡观望 / 🔴回避（一句话理由）
- **已持仓**: 建议操作
- **观望者**: 入场条件
- **短线**: 机会与风险

#### 七、风险提示
- 核心风险因素（1-3条）

## 工具使用规则
1. 必须先调用 `stock_profile` 获取基础数据
2. 如需更长K线历史，调用 `kline_fetch`（limit=120）
3. `web_search` 用于搜索新闻（若不可用则跳过第四节，不要编造）
4. 所有数据结论必须标注来源工具，禁止编造价格/事件
5. 对高估值成长股保持中立，不因 PE 高就看空

## 输出格式
- 使用 Markdown
- 表格用标准 Markdown 语法
- 数字精确到小数点后 2 位
- 总长度 800-1500 字
```

### 3.4 数据库表

```sql
CREATE TABLE IF NOT EXISTS cn_stock_ai_report (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    code VARCHAR(10) NOT NULL,
    name VARCHAR(32),
    report_md MEDIUMTEXT NOT NULL,
    model VARCHAR(64),
    provider VARCHAR(32),
    tools_used JSON,
    tokens_used INT DEFAULT 0,
    latency_ms INT DEFAULT 0,
    quality_score TINYINT DEFAULT NULL COMMENT '结构校验通过=100, 部分=50, 失败=0',
    user_feedback TINYINT DEFAULT NULL COMMENT '1=满意, -1=不满意, NULL=未评',
    feedback_reason VARCHAR(200) DEFAULT NULL,
    data_cutoff_date DATE DEFAULT NULL COMMENT '报告依据的最新数据日期',
    source ENUM('user','cron','batch') DEFAULT 'user' COMMENT '生成来源',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_code_date (code, created_at DESC),
    INDEX idx_source (source, created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## 四、前端详细设计

### 4.1 路由

```typescript
// router/index.ts — 在 /basic 同级新增
{
  path: '/ai-report',
  component: Layout,
  redirect: '/ai-report/analysis',
  meta: { title: 'AI 分析', icon: 'ChatDotRound' },
  children: [
    {
      path: 'analysis',
      name: 'StockAnalysis',
      component: () => import('@/views/stock/analysis.vue'),
      meta: { title: '个股分析' }
    },
    {
      path: 'history',
      name: 'ReportHistory',
      component: () => import('@/views/stock/report-history.vue'),
      meta: { title: '历史报告' }
    }
  ]
}
```

**侧边栏位置**: 在"技术指标"和"K线形态识别"之间，作为一级导航。

### 4.2 页面结构 (`analysis.vue`)

```
┌──────────────────────────────────────────────────┐
│ Header: [股票搜索 🔍 autocomplete] [生成报告 ▶]  │
├──────────────────────────────────────────────────┤
│                                                  │
│ ┌──────────────────────────────────────────────┐ │
│ │  K线图 (ECharts, 内联)                       │ │
│ │  - 复用 getKlineData API                     │ │
│ │  - 日K + MA + BOLL + 成交量                  │ │
│ │  - 买卖信号标注 (若有模拟盘持仓)             │ │
│ └──────────────────────────────────────────────┘ │
│                                                  │
│ ┌──────────────────────────────────────────────┐ │
│ │  报告内容 (markdown-it 渲染)                 │ │
│ │  - 流式打字机效果                            │ │
│ │  - 表格自动高亮                              │ │
│ │  - 多空对比双列彩色                          │ │
│ └──────────────────────────────────────────────┘ │
│                                                  │
│ Footer: [复制报告 📋] [生成时间] [模型/token]    │
└──────────────────────────────────────────────────┘
```

### 4.3 技术选型

| 需求 | 方案 | 说明 |
|------|------|------|
| Markdown 渲染 | `markdown-it` + `markdown-it-container` | 轻量 (~30KB gzip)，支持自定义容器 |
| SSE 流式 | 复用已有 `fetch` + `ReadableStream` 模式 | 与 AiChatDrawer 的 streaming 一致 |
| K线图 | 复用 `getKlineData` + 已有 ECharts 配置 | 可从 backtest-detail.vue 抽取 composable |
| 股票搜索 | 新增 autocomplete，调 `cn_stock_spot` 模糊匹配 | 输入代码或名称均可 |

### 4.4 跨页面入口

在现有数据表组件 `StockData.vue` 的行操作列增加「分析」按钮：

```vue
<!-- 每行股票的操作列 -->
<el-button link @click="goAnalysis(row.code)">分析</el-button>
```

点击后 `router.push({ name: 'StockAnalysis', query: { code } })`。

---

## 五、复用盘点

| 已有模块 | 本方案复用方式 | 改动量 |
|---------|---------------|--------|
| `quantia/lib/ai/` (run_agent, stream) | 直接调用 | 0 |
| `quantia/lib/ai/tools/` (kline_fetch, sql_query, web_search) | Agent 自动调度 | 0 |
| `quantia/lib/ai/agent_store.py` | 注册新 agent | 1 条 INSERT |
| `quantia/core/crawling/` | stock_profile 工具读 DB (数据由爬虫维护) | 0 |
| `quantia/fontWeb/src/api/request.ts` | 新 API 函数复用 axios 实例 | 0 |
| `getKlineData` API + ECharts 配置 | 报告页内嵌 K线图 | 抽 composable |
| SSE streaming 模式 | 复用 AiChatDrawer 的 fetch stream | 复制模式 |

**真正新增代码**: ~860 行 (Python 370 + Vue 450 + API 40)  
**新增依赖**: `markdown-it` (npm, 前端渲染)  
**改动已有文件**: router/index.ts (+15行), web_service.py (+3行注册路由), StockData.vue (+1列按钮)

---

## 六、实现分期

### Phase 1 (MVP, 可体验) — 报告生成 + 智能缓存 + 核心体验
- [ ] `stock_profile` Tool (聚合 5 维画像)
- [ ] `stockReportHandler.py` (同步版 + 缓存逻辑)
- [ ] `analysis.vue` 基本页面 (搜索 + markdown 渲染)
- [ ] 内置 `stock_analyst` Agent
- [ ] 路由注册
- [ ] 报告缓存 + TTL + 数据变更检测
- [ ] "数据无更新，复用上次分析" 逻辑
- [ ] **AI Gate 理由可视化**: `fetch_signal_with_decision` JOIN `cn_stock_trade_ai_score`，返回 `reason_summary` / `evidence` / `risk_flags`
- [ ] **交易决策弹窗增加 AI 理由面板**: 展示评分理由 + 关键证据 + 风险提示
- [ ] **报告中多空对比必须引用具体数据源**: Prompt 强制标注来源
- [ ] **生成过程可视化** (§10.1): SSE progress events + 分步状态
- [ ] **股票搜索 Autocomplete** (§10.2): 代码/名称即时补全
- [ ] **错误降级 fallback 数据面板** (§10.3): AI 不可用时展示结构化数据
- [ ] **自动滚动 + 目录锚点** (§10.8): 流式输出跟踪 + 报告导航

### Phase 2 (数据增强 + 体验优化)
- [ ] SSE 流式输出（打字机效果 → 从同步升级）
- [ ] K线图内嵌（ECharts composable 抽取）
- [ ] 报告历史表 + 历史页面
- [ ] StockData.vue 行操作「分析」入口
- [ ] 扩展 `cn_stock_financial` 新增研发费用/管理费用字段
- [ ] `stock_financial_data.py` 抓取更多 AkShare 字段
- [ ] 报告中增量对比："对比上次分析 (5月10日)，ROE 提升1.2pp"
- [ ] **追问能力** (§10.5): 报告下方输入框，复用 agent context
- [ ] **关注列表批量分析** (§10.6): 一键生成关注股票摘要卡片
- [ ] **数字可交互 Tooltip** (§10.4): PE/ROE 等关键数字附行业分位数
- [ ] **响应式适配** (§10.9): 适配 1100px/600px 断点

### Phase 3 (AI Gate + 事件风控)
- [ ] 事件上下文构建器 (`_build_event_context`)
- [ ] `score_trade` 扩展 `event_context` 参数
- [ ] AI Gate prompt 增强（事件敏感版）
- [ ] 模拟交易/实盘信号执行前自动调用 AI Gate
- [ ] 新增 `stock_announcement_em.py` 爬虫（巨潮公告）
- [ ] 公告分类标签（技术/专利/合同/处罚/ST）
- [ ] AI 评分历史趋势图 (某只股票近30天评分变化)
- [ ] **报告版本时间线** (§10.7): 同股票评级变化轨迹
- [ ] **导出 PDF / 图片** (§10.10): html2canvas + jsPDF
- [ ] **分享链接** (§10.10): 只读公开报告页

### Phase 4 (进阶扩展)
- [ ] 报告对比（两只股票 side-by-side）
- [ ] 定时分析（关注列表每日自动生成）
- [ ] 钉钉/IM 推送报告摘要 + 风险预警
- [ ] 专利数据爬虫 (知识产权局)
- [ ] 机构评级数据
- [ ] 多语言摘要（英文版）
- [ ] 语音播报（Web Speech API）
- [ ] 自定义报告偏好（用户可选侧重维度）
- [ ] AI 评分跌破阈值自动推送预警

---

## 七、与 SKILL.md 对比总结

| SKILL 设计点 | 本方案取舍 | 理由 |
|-------------|-----------|------|
| 独立 venv + scripts/ | ❌ 不采用 | 维护两套环境无意义 |
| fetch_all.py 数据采集 | ❌ 替换为 stock_profile Tool | 100% 复用已有爬虫+DB |
| 多模态看图分析 | ❌ 替换为结构化数据输入 | OHLCV 数值 > 图片描述；前端 ECharts 交互更佳 |
| web_search 新闻 | ✅ 采用 | 通过已有 web_search Tool |
| 报告模板结构 | ✅ 采用 (7 节) | 核心价值，写入 Agent prompt |
| 多空对比表 | ✅ 采用 | 直观决策辅助 |
| 分角色操作建议 | ✅ 采用 | 实用性强 |
| 数据来源标注 | ✅ 采用 | 可信度保障 |
| PDF 导出 | ⏳ Phase 3 | MVP 先支持复制 Markdown |
| md2html.py | ❌ 不采用 | 前端 markdown-it 实时渲染 |

---

## 八、开发顺序 (Phase 1 Checklist)

```
 1. 创建 quantia/lib/ai/tools/stock_profile.py
 2. 注册到 tools/__init__.py _autoload()
 3. 创建 quantia/web/stockReportHandler.py (含缓存+增量检测+SSE progress)
 4. 新增 GET /api/ai/report/search_stock (股票搜索 autocomplete)
 5. 注册路由到 web_service.py
 6. npm install markdown-it markdown-it-container (fontWeb)
 7. 创建 quantia/fontWeb/src/views/stock/analysis.vue (含进度可视化+fallback)
 8. 创建 quantia/fontWeb/src/api/report.ts
 9. 注册路由到 router/index.ts
10. DB: INSERT stock_analyst agent record
11. 实现报告缓存 TTL + "数据无更新则复用"
12. fetch_signal_with_decision JOIN cn_stock_trade_ai_score (理由面板)
13. paper-trading/index.vue 交易决策弹窗增加 AI 理由展示
14. 测试：本地 → 服务器部署
```

---

## 九、关于用户三大需求的答复

### Q1: 研发费用/专利/技术突破是否有涉及？

**当前状态**: 数据库已有 70+ 财务字段（ROE/ROA/毛利率/净利率/增长率/负债率等），但 **不包含** 研发费用比、专利数量、技术突破。

**解决路径**:
- **Phase 1**: AI 报告通过 `web_search` 搜索 "{股票名} 研发投入/专利/技术突破"，从新闻中获取非结构化信息
- **Phase 2**: 扩展 `cn_stock_financial` 表，增加 `rd_expense`(研发费用), `rd_ratio`(研发占营收比) 字段，数据来自 AkShare 财报详情
- **Phase 3**: 专利数据需新增独立爬虫（国知局 API 或巨潮公告分类）

### Q2: 反复查看同一股票是否需要重复获取？

**答案: 不需要**。三层缓存策略：
1. DB 数据由定时任务维护，查看不触发网络请求
2. stock_profile 结果当日缓存，秒级响应
3. AI 报告有 TTL（盘中30min/收盘后当日有效），无数据更新则直接复用
4. 发现新数据时（如新财报发布），自动标记"有增量"，生成对比分析

### Q3: AI 综合得分过滤交易，避免重大亏损/捕捉机会？

**答案: 已有基础架构，需增强事件维度**：
- 已有 `ai_decision` 模块的 `score_trade()` + Gate 机制
- 增强点：新增 `event_context`（风险事件+机会事件），让 AI 对 ST/违规/大合同/专利 等敏感事件给予极端评分
- 结果：评分 <50 自动 reject + 通知用户原因；>70 pass 执行；中间观望

---

## 十、用户体验增强设计

### 10.1 生成过程可视化（Phase 1 必须）

AI 报告生成耗时 5-15s，无进度反馈会让用户以为卡死。设计分阶段进度展示：

```
┌─────────────────────────────────────────────────┐
│ 📊 分析中：000001 平安银行                       │
├─────────────────────────────────────────────────┤
│                                                 │
│  ✅ 获取基础行情数据              0.3s          │
│  ✅ 查询技术指标                  0.5s          │
│  ✅ 分析资金流向                  0.8s          │
│  🔄 搜索近期新闻...              (进行中)       │
│  ⏳ 生成分析报告                                │
│                                                 │
│  [━━━━━━━━━━━━━━━░░░░░] 68%                    │
│                                                 │
└─────────────────────────────────────────────────┘
```

**实现**: Agent 每完成一个 tool 调用，后端通过 SSE 推送 `event: progress` 事件：
```json
{"step": "stock_profile", "status": "done", "elapsed_ms": 320}
{"step": "web_search", "status": "running"}
{"step": "report", "status": "streaming"}
```
前端按 step 更新进度条 + 步骤状态图标。

### 10.2 股票搜索 Autocomplete（Phase 1 必须）

当前系统无远程搜索补全，用户需记住完整代码。新增：

```vue
<el-autocomplete
  v-model="searchCode"
  :fetch-suggestions="queryStock"
  placeholder="输入代码或名称搜索"
  :trigger-on-focus="false"
  :debounce="300"
  @select="handleSelect"
>
  <template #default="{ item }">
    <span class="code">{{ item.code }}</span>
    <span class="name">{{ item.name }}</span>
    <span class="industry">{{ item.industry }}</span>
  </template>
</el-autocomplete>
```

后端新增 `GET /api/ai/report/search_stock?q=xxx` 查询 `cn_stock_spot` 做 code/name LIKE 匹配，返回 top 8。

### 10.3 错误降级策略（Phase 1 必须）

当 AI 服务不可用或 tool 执行失败时，不展示空白页：

```
情况 A: 单个 tool 失败（如 web_search 超时）
  → 报告生成继续，对应段落标注"数据暂缺（新闻搜索超时）"
  → 灰色背景 + info 图标

情况 B: AI 服务完全不可用
  → 展示已获取的结构化数据面板（fallback 纯数据模式）：
    ┌─────────────────────────────────────────┐
    │ ⚠️ AI 分析服务暂时不可用                 │
    │                                         │
    │ 核心指标:                               │
    │   PE: 12.3 | PB: 1.8 | ROE: 18.5%     │
    │   今日: +2.3% | 成交额: 8.7亿          │
    │                                         │
    │ 资金面: 主力净流入 +1.2亿 (3日连续)     │
    │ 技术面: MACD金叉 | KDJ超买(K=86)       │
    │                                         │
    │ [重试生成报告]                           │
    └─────────────────────────────────────────┘

情况 C: 报告缓存命中但已过期
  → 展示旧报告 + 顶部横幅提示：
    "⚠️ 本报告生成于 2 小时前，数据可能已过期 [刷新分析]"
```

### 10.4 报告内数字可交互（Phase 2）

关键财务数字增加 tooltip，提供行业对比上下文：

```html
<!-- markdown-it 自定义渲染规则 -->
<span class="metric-highlight" 
      data-tippy-content="PE 38.2 在该行业(银行)中处于 Top 25%">
  PE: 38.2
</span>
```

**实现**: `stock_profile` 返回时附加行业分位数数据，markdown-it 插件对 `PE/PB/ROE` 等关键词做正则匹配 + tooltip 注入。

### 10.5 追问能力（Phase 2）

报告生成完成后，底部出现输入框，用户可追问：

```
┌──────────────────────────────────────────────────┐
│ [报告内容...]                                    │
├──────────────────────────────────────────────────┤
│ 💬 对报告有疑问？输入追问                        │
│ ┌──────────────────────────────────┐ [发送]      │
│ │ 详细解释为什么判断 MACD 背离？   │             │
│ └──────────────────────────────────┘             │
└──────────────────────────────────────────────────┘
```

**实现**: 追问时将原报告作为 history context 传给同一 agent，生成补充回答（不重新调用 tools，节省延迟）。追问结果追加到报告下方，但不覆盖原报告。

### 10.6 关注列表批量分析（Phase 2）

用户已有 `toggleAttention` 关注机制，增加"一键分析关注列表"功能：

```
┌──────────────────────────────────────────────────┐
│ [搜索框] [生成报告]  [📋 批量分析关注列表(8只)]  │
└──────────────────────────────────────────────────┘
```

点击后依次生成每只股票的摘要版报告（300字以内），以卡片网格展示，点击可展开完整报告。

### 10.7 报告版本时间线（Phase 3）

同一股票多次分析后，展示评级变化轨迹：

```
📈 分析历史
  5/10 🟢买入 (score: 82) — "MACD金叉+主力连续流入"
  5/15 🟡观望 (score: 58) — "KDJ超买+主力转流出"
  5/23 🟢买入 (score: 75) — "回调到位+新财报超预期"
```

### 10.8 自动滚动 + 目录锚点（Phase 1）

- SSE 流式输出时自动 `scrollIntoView({ behavior: 'smooth' })` 到最新内容
- 报告完成后，左侧生成 7 节目录锚点，点击跳转
- 移动端: 目录折叠为顶部下拉菜单

### 10.9 响应式适配（Phase 2）

遵循已有断点 `1100px / 600px`：

| 宽度 | 布局 |
|------|------|
| > 1100px | K线图 + 报告并排（左 40% 右 60%）|
| 600-1100px | 上下堆叠：K线图全宽 + 报告全宽 |
| < 600px | K线图可折叠 + 报告全宽 + 底部固定操作栏 |

### 10.10 导出与分享（Phase 3）

| 功能 | 实现方案 |
|------|---------|
| 复制 Markdown | `navigator.clipboard.writeText(reportMd)` (Phase 1 已含) |
| 导出 PDF | `html2canvas` + `jsPDF`，对报告容器截图 |
| 分享链接 | `GET /api/ai/report/share/{id}` 返回只读报告页（无需登录） |
| 导出图片 | `html2canvas` 对报告区域截图 → 下载 PNG |

---

## 十一、完整性检查矩阵

| 用户需求 | 方案覆盖章节 | 状态 |
|---------|-------------|------|
| 研发费用/专利/技术突破数据 | §二-B (缺失数据分析 + 补偿路径) | ✅ |
| 反复查看不重复获取 | §二-C (三层缓存 + 数据变更检测) | ✅ |
| 新旧数据综合分析 | §二-C (`_generate_with_history` + 增量对比) | ✅ |
| AI 综合得分过滤交易 | §二-D (事件风控 + Gate 增强) | ✅ |
| 避免重大亏损 | §二-D (风险事件 → 低分 reject) | ✅ |
| 捕捉上升期机会 | §二-D (机会事件 → 加分 pass) | ✅ |
| 关键数据用户可见 | §十.3 (fallback 数据面板) + §十.4 (数字可交互) | ✅ |
| 评价好坏有数据支撑 | §六 Phase 1 (AI Gate 理由面板) + Prompt 数据溯源 | ✅ |
| 生成过程用户可感知 | §十.1 (分阶段进度可视化) | ✅ |
| 搜索体验 | §十.2 (Autocomplete) | ✅ |
| 错误容忍 | §十.3 (降级策略) | ✅ |
| 深入追问 | §十.5 (追问能力) | ✅ |
| 批量分析 | §十.6 (关注列表批量) | ✅ |
| 历史对比 | §十.7 (时间线) | ✅ |
| 移动端 | §十.9 (响应式) | ✅ |
| 导出分享 | §十.10 (PDF/图片/链接) | ✅ |
| 并发控制/成本 | optimization_review §10 (请求合并 + rate_limit) | ✅ |
| 安全性 | optimization_review §11 (公开数据 + 无用户信息泄露) | ✅ |
| 报告质量一致性 | optimization_review §12 (结构校验 + 重试 + quality_score) | ✅ |
| 热门股票秒级响应 | optimization_review §13 (收盘后 cron 预生成 Top 50) | ✅ |
| 用户反馈闭环 | optimization_review §14 (👍/👎 + 满意率统计) | ✅ |
| Token 消耗可控 | §十二 (开关控制 + 场景限额) | ✅ |
| Token 用量统计展示 | §十二 (统计页面 + 模型维度 + 余量) | ✅ |

---

## 十二、Token 用量管理与统计

### 12.1 当前 Token 消耗路径审计

系统中所有消耗 AI Token 的路径如下：

| # | 消耗路径 | 触发方式 | 每次 Token 消耗 | 审计通道 | 当前可控性 |
|---|---------|---------|----------------|---------|-----------|
| 1 | 策略生成 (AI Generate) | 用户点击按钮 | 1000-3000 + 自动修复重试 ×3 | `cn_stock_ai_call_log` | ✅ 用户主动触发 |
| 2 | 策略优化 (AI Refine) | 用户点击按钮 | 1000-2000 + 重试 ×3 | `cn_stock_ai_call_log` | ✅ 用户主动触发 |
| 3 | 策略修复 (AI Repair) | 用户点击按钮 | 1000-2000 + 重试 ×3 | `cn_stock_ai_call_log` | ✅ 用户主动触发 |
| 4 | AI 聊天 (Chat) | 用户输入发送 | 500-2000 (含历史上下文) | `cn_stock_ai_call_log` | ✅ 用户主动触发 |
| 5 | 交易 AI Gate (pre_buy) | **自动** — 每笔模拟交易前 | 2000-3000 | ⚠️ `cn_stock_trade_ai_score` (无 token 字段) | ⚠️ 需配置开关 |
| 6 | 交易 AI Gate (post_signal) | **自动** — 每笔交易信号后 | 2000-3000 | ⚠️ `cn_stock_trade_ai_score` (无 token 字段) | ⚠️ 需配置开关 |
| 7 | **[新] 个股分析报告** | 用户/cron | 3000-6000 (多工具+长报告) | `cn_stock_ai_call_log` | ✅ 用户主动/cron 可关 |
| 8 | **[新] 热门股票预生成** | cron (收盘后) | 50只 × 4000 = ~200K | `cn_stock_ai_call_log` | ⚠️ 需独立开关 |

**关键发现**:
- 路径 5、6 在 AI Gate 启用后**每笔交易自动消耗**，日均交易 5-20 笔 → 每日 20K-120K tokens
- 路径 8 预生成 50 只 → 一次性 200K tokens（可能超 hourly quota）
- Cron 任务（`cron.hourly/workdayly/monthly`）**不消耗 token**（纯数据抓取+分析）

**⚠️ 必须修复的架构缺陷（Phase 1 前置依赖）**:

`ai_decision/service.py` 使用独立的 `providers/openai_compatible.py`（stdlib `urllib.request`），
**完全绕过** `quantia/lib/ai/` 统一入口：
- 不调用 `audit.record_call()` → Token 用量统计页漏掉所有 trade_gate 数据
- 不解析 OpenAI 响应中的 `usage` 字段 → token 计数直接丢弃
- 不经过 `rate_limiter.check_quota()` → 限流无效
- 仅写入 `cn_stock_trade_ai_score`（该表只有 `latency_ms`，无 token 字段）

**修复方案（Phase 1 步骤 0）**:

在 `ai_decision/service.py::score_trade()` 中，provider 调用完成后补充审计桥接：
```python
# service.py score_trade() 步骤 3 之后追加:
try:
    from quantia.lib.ai.audit import record_call as _audit
    _audit(
        scene='trade_gate',
        provider=cfg.provider or 'openai_compatible',
        model=cfg.model_name or '',
        user_id=f'paper_{source_id}',
        prompt=json.dumps(messages, ensure_ascii=False)[:4000],
        response=(result.raw_response or '')[:4000],
        ok=(result.status == STATUS_SUCCEEDED),
        prompt_tokens=_extract_prompt_tokens(raw_response_obj),
        completion_tokens=_extract_completion_tokens(raw_response_obj),
        total_tokens=_extract_total_tokens(raw_response_obj),
        latency_ms=latency_ms,
        error=result.error_message,
    )
except Exception:
    pass  # 审计失败不影响业务
```

同时修改 `providers/openai_compatible.py` 返回结构，从 `(content, usage_dict)` 中提取 token 计数：
```python
# providers/openai_compatible.py generate() 末尾
usage = obj.get("usage") or {}
return content, {
    "prompt_tokens": usage.get("prompt_tokens"),
    "completion_tokens": usage.get("completion_tokens"),
    "total_tokens": usage.get("total_tokens"),
}
```

### 12.1.1 Scene 命名映射表

`cn_stock_ai_call_log.scene` 实际使用的值与功能开关 `feature` 标识的映射关系：

| feature (开关标识) | 匹配的 scene 值 (LIKE 前缀匹配) | 说明 |
|---|---|---|
| `strategy_gen` | `strategy_gen%` | 含 `strategy_gen`, `strategy_gen_repair`, `strategy_gen_stream`, `strategy_gen_stream_repair` |
| `strategy_refine` | `strategy_refine%` | 含 `strategy_refine`, `strategy_refine_repair` |
| `strategy_repair` | `strategy_repair%` | 含 `strategy_repair`, `strategy_repair_retry` |
| `chat` | `chat` | 精确匹配 |
| `trade_gate` | `trade_gate` | 精确匹配（修复后新增的 scene） |
| `report_generate` | `report_generate` | [新] 精确匹配 |
| `report_cron_pregenerate` | `report_cron%` | [新] 含预生成变体 |

`_query_today_tokens(feature)` 实现必须用**前缀匹配**（`WHERE scene LIKE %s`），不能用精确匹配。

### 12.2 用户控制机制设计

#### A. 全局总开关

```
设置 → AI 配置 → 顶部新增：
┌──────────────────────────────────────────────────┐
│ 🔋 AI 功能总开关                                  │
│                                                  │
│ [✅ 开启] AI 策略生成/优化/修复                   │
│ [✅ 开启] AI 聊天对话                            │
│ [✅ 开启] AI 交易 Gate (模拟交易评分)             │
│ [❌ 关闭] AI 个股分析报告                        │
│ [❌ 关闭] 热门股票每日预生成 (cron)              │
│                                                  │
│ 当前小时配额: 12/60 次 · 28,000/200,000 tokens   │
└──────────────────────────────────────────────────┘
```

**实现**: 新增 `cn_stock_ai_feature_switch` 表：

```sql
CREATE TABLE IF NOT EXISTS cn_stock_ai_feature_switch (
    id INT PRIMARY KEY AUTO_INCREMENT,
    feature VARCHAR(64) UNIQUE NOT NULL COMMENT '功能标识，对应 scene 前缀',
    enabled TINYINT(1) DEFAULT 1,
    daily_token_budget INT DEFAULT NULL COMMENT '该功能每日 token 上限，NULL=不限',
    modified_by VARCHAR(64) DEFAULT 'system' COMMENT '最后修改人（与其他 config 表一致）',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 默认数据
INSERT INTO cn_stock_ai_feature_switch (feature, enabled, daily_token_budget) VALUES
('strategy_gen', 1, NULL),
('strategy_refine', 1, NULL),
('strategy_repair', 1, NULL),
('chat', 1, NULL),
('trade_gate', 1, 100000),
('report_generate', 1, 150000),
('report_cron_pregenerate', 0, 200000);
```

#### B. 单功能粒度控制

每个 AI 功能在调用前检查开关：
```python
# quantia/lib/ai/__init__.py 增加
_FEATURE_SCENE_PREFIX = {
    'strategy_gen': 'strategy_gen',
    'strategy_refine': 'strategy_refine',
    'strategy_repair': 'strategy_repair',
    'chat': 'chat',
    'trade_gate': 'trade_gate',
    'report_generate': 'report_generate',
    'report_cron_pregenerate': 'report_cron',
}

def is_feature_enabled(feature: str) -> bool:
    """检查某 AI 功能是否启用 + 日预算未超。

    日预算使用 scene 前缀匹配（LIKE 'prefix%'），覆盖所有子场景。
    """
    switch = _load_switch(feature)
    if not switch or not switch['enabled']:
        return False
    if switch['daily_token_budget']:
        prefix = _FEATURE_SCENE_PREFIX.get(feature, feature)
        used_today = _query_today_tokens_by_prefix(prefix)
        if used_today >= switch['daily_token_budget']:
            return False
    return True

def _query_today_tokens_by_prefix(scene_prefix: str) -> int:
    """查询今日某 scene 前缀下的累计 token 消耗。"""
    sql = ("SELECT COALESCE(SUM(total_tokens),0) FROM cn_stock_ai_call_log "
           "WHERE scene LIKE %s AND DATE(created_at) = CURDATE()")
    rows = mdb.executeSqlFetch(sql, (scene_prefix + '%',))
    return int(rows[0][0]) if rows else 0
```

#### B.1 双层控制关系

系统存在两层 Token 控制，独立判断、均需通过：

| 层次 | 作用 | 粒度 | 配置来源 |
|------|------|------|---------|
| **Rate Limiter** (已有) | 小时突发控制 | per user × per scene × 1h 滑窗 | env: `QUANTIA_AI_RATE_CALLS_PER_HOUR`, `QUANTIA_AI_RATE_TOKENS_PER_HOUR` |
| **Feature Switch** (新增) | 每日总量预算 | per feature × 全天 | DB: `cn_stock_ai_feature_switch.daily_token_budget` |

执行顺序：`is_feature_enabled(feature)` → `rate_limiter.check_quota(user_id, scene)` → provider call。
两者任一拒绝即阻断：Feature 关闭/超预算 → 抛 `AIError("功能已禁用/日预算已耗尽")`；Rate limit 超窗 → 抛 `RateLimitError`。

#### C. 交易 Gate 独立控制

现有 `cn_stock_ai_decision_config` 已有 `enabled` + `enabled_as_gate` 字段 → 不需改动，但在前端"AI 配置"页面中增加**显式提示**：

```
⚠️ 交易 Gate 启用后，每笔模拟交易将消耗 ~3000 tokens。
   预估日消耗: {{ dailyTrades × 3000 }} tokens / 日
   当前设置: 买入阈值 ≥{{ buyThreshold }} | 卖出阈值 ≤{{ sellThreshold }}
```

### 12.3 Token 统计展示页面

#### 新增路由

```typescript
// router/index.ts
{
  path: 'token-usage',
  name: 'TokenUsage',
  component: () => import('@/views/settings/token-usage.vue'),
  meta: { title: 'Token 用量' }
}
```

#### 页面结构

```
┌──────────────────────────────────────────────────────────────────┐
│ 🔋 AI Token 用量统计                                             │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐    │
│ │ 今日消耗   │ │ 本月消耗   │ │ 小时配额   │ │ 日预算余量 │    │
│ │ 45,200     │ │ 1,230,000  │ │ 12/60次    │ │ 154,800    │    │
│ │ tokens     │ │ tokens     │ │ 28K/200K   │ │ /200K      │    │
│ └────────────┘ └────────────┘ └────────────┘ └────────────┘    │
│                                                                  │
│ ┌─── 按模型分布 (饼图) ──┐  ┌─── 按场景分布 (饼图) ──┐        │
│ │ deepseek-chat: 65%    │  │ strategy_gen: 40%      │        │
│ │ qwen-plus: 25%        │  │ trade_gate: 35%        │        │
│ │ gpt-4o: 10%           │  │ chat: 15%              │        │
│ └────────────────────────┘  │ report: 10%            │        │
│                              └────────────────────────┘        │
│                                                                  │
│ ┌─── 每日趋势 (折线图, 近30天) ──────────────────────────────┐ │
│ │  ╭──╮                                                       │ │
│ │ ╭╯  ╰──╮  ╭──╮                                            │ │
│ │╭╯      ╰──╯  ╰──╮                     ╭──╮               │ │
│ │                   ╰─────────────────────╯  ╰──            │ │
│ │ [prompt_tokens] [completion_tokens] [total]                │ │
│ └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│ ┌─── 各功能配额状态 ─────────────────────────────────────────┐ │
│ │ 功能             │ 启用 │ 日预算  │ 已用    │ 余量   │ 状态│ │
│ │ 策略生成         │ ✅   │ 无限   │ 12,000  │ —      │ 正常│ │
│ │ AI 聊天          │ ✅   │ 无限   │ 5,200   │ —      │ 正常│ │
│ │ 交易 Gate        │ ✅   │ 100K   │ 28,000  │ 72,000 │ 正常│ │
│ │ 个股分析报告     │ ✅   │ 150K   │ 0       │ 150K   │ 正常│ │
│ │ 热门预生成(cron) │ ❌   │ 200K   │ 0       │ 200K   │ 关闭│ │
│ └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│ ┌─── 最近调用记录 (表格, 最新50条) ──────────────────────────┐ │
│ │ 时间   │ 场景      │ 模型          │ Tokens │ 耗时 │ 状态 │ │
│ │ 10:32  │ chat      │ deepseek-chat │ 1,200  │ 2.1s │ ✅   │ │
│ │ 10:28  │ trade_gate│ qwen-plus     │ 2,800  │ 3.5s │ ✅   │ │
│ │ 10:15  │ strategy  │ deepseek-chat │ 4,500  │ 8.2s │ ✅   │ │
│ └────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

#### 后端 API

```python
# quantia/web/aiTokenUsageHandler.py

# GET /api/ai/token/summary
# 返回: {today_tokens, month_tokens, hour_calls, hour_tokens, hour_limit_calls, hour_limit_tokens}

# GET /api/ai/token/by_model?days=30
# 返回: [{model, total_tokens, call_count, avg_tokens_per_call}]

# GET /api/ai/token/by_scene?days=30
# 返回: [{scene, total_tokens, call_count}]

# GET /api/ai/token/daily_trend?days=30
# 返回: [{date, prompt_tokens, completion_tokens, total_tokens, call_count}]

# GET /api/ai/token/feature_status
# 返回: [{feature, enabled, daily_budget, used_today, remaining}]

# GET /api/ai/token/recent_calls?limit=50
# 返回: [{id, scene, model, provider, total_tokens, latency_ms, ok, created_at}]

# POST /api/ai/token/update_feature
# 参数: {feature, enabled?, daily_token_budget?}
# 作用: 更新某个 AI 功能的开关和/或日预算（统一端点，取代单纯 toggle）
```

**所有查询基于 `cn_stock_ai_call_log` 表**（trade_gate 数据需完成 §12.1 修复后才可见）。

#### 余量计算

```python
def _calc_remaining():
    """计算各维度余量"""
    # 小时配额余量（注：rate_limiter._query_window 不支持通配 scene，需独立查所有 scene）
    sql = ("SELECT COUNT(*), COALESCE(SUM(total_tokens),0) "
           "FROM cn_stock_ai_call_log "
           "WHERE created_at >= NOW() - INTERVAL 1 HOUR "
           "  AND (tools_used IS NULL OR JSON_EXTRACT(tools_used, '$.rate_limit_loop') IS NULL "
           "       OR JSON_EXTRACT(tools_used, '$.rate_limit_loop') = false)")
    rows = mdb.executeSqlFetch(sql, ())
    hour_calls_used = int(rows[0][0]) if rows else 0
    hour_tokens_used = int(rows[0][1]) if rows else 0
    hour_calls_remaining = rate_limiter.calls_per_hour() - hour_calls_used
    hour_tokens_remaining = rate_limiter.tokens_per_hour() - hour_tokens_used
    
    # 各功能日预算余量（使用 scene 前缀匹配）
    features = load_all_switches()
    for f in features:
        prefix = _FEATURE_SCENE_PREFIX.get(f['feature'], f['feature'])
        used = _query_today_tokens_by_prefix(prefix)
        f['used_today'] = used
        if f['daily_token_budget']:
            f['remaining'] = max(0, f['daily_token_budget'] - used)
        else:
            f['remaining'] = None  # NULL 表示不限
```

#### 外部 API 余额查询（可选 Phase 2）

部分 AI Provider 提供余额查询接口：
- **DeepSeek**: `GET https://api.deepseek.com/user/balance` → `{balance_infos: [{currency, total_balance, granted_balance}]}`
- **Qwen/通义千问**: 无直接余额 API（按量计费，账单查询需控制台）
- **OpenAI**: `GET https://api.openai.com/dashboard/billing/credit_grants` (deprecated) / 无官方 API

**Phase 1 方案**: 仅展示本地统计（`cn_stock_ai_call_log` 聚合），不查外部余额。
**Phase 2 方案**: 对支持的 Provider（如 DeepSeek）增加余额查询按钮，定时缓存。

### 12.4 实现优先级

| 项 | 阶段 | 说明 |
|----|------|------|
| **ai_decision 审计桥接** | Phase 1 步骤 0 | 修改 `providers/openai_compatible.py` 返回 usage + `service.py` 追加 `record_call` |
| `cn_stock_ai_feature_switch` 表 + API | Phase 1 | 功能开关 + 日预算 + `modified_by` |
| Token 统计 API (6 个端点) | Phase 1 | 基于已有 audit 表聚合，scene 前缀匹配 |
| `token-usage.vue` 页面 | Phase 1 | 卡片 + 饼图 + 折线图 + 表格 |
| 各功能调用前检查开关 | Phase 1 | `is_feature_enabled()` 守卫 |
| 报告预生成 cron 独立开关 | Phase 1 | 默认关闭 |
| DeepSeek 余额查询 | Phase 2 | 可选，仅 DeepSeek 支持 |
| Token 消耗预警通知 | Phase 3 | 日用量 > 80% 时钉钉推送 |


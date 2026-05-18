# 策略融合 (多维融合) 重设计计划

> 目标：把当前"伪多维 UI + 仅技术维度真融合"的策略融合页，改造为与原型一致的**真五维融合**，覆盖加权评分 / 信号投票 / 条件树 / 环境轮动 四种模式，并提供真 Shapley 贡献、A/B 累加、信号热图三类深入诊断。

- 入口页：`/verify/fusion` → [quantia/fontWeb/src/views/verify/fusion.vue](../quantia/fontWeb/src/views/verify/fusion.vue)
- 后端：[quantia/web/verifyFusionHandler.py](../quantia/web/verifyFusionHandler.py)
- 路由：`POST /quantia/api/verify/fusion`（**保留同路径，重写 schema**，旧 schema 自动映射）

---

## 1. 现状审计（10 条 gap）

| # | Gap | 当前位置 | 严重程度 |
|---|---|---|---|
| 1 | `runFusionBacktest` 只采集"技术"维度勾选项；基本面/资金流/情绪/自定义四维**完全未传给后端** | fusion.vue:402-410 | 🔴 致命 |
| 2 | 前端 `weighted_score` → 后端 `intersection`、`condition_tree` → `union` **语义错误映射** | fusion.vue:420-425 | 🔴 |
| 3 | 后端只支持 `strategy_names`（内置策略表名列表），**没有"多维筛选 + 加权评分"通道** | verifyFusionHandler.py:36-100 | 🔴 |
| 4 | `start_date / end_date / holding_days` 前端硬编码，UI 无选择控件 | fusion.vue:441-443 | 🟠 |
| 5 | "信号重叠热图" 完全是空 placeholder | fusion.vue:567-589 | 🟠 |
| 6 | "因子贡献分析 (Shapley)" 用 `fusion.sharpe - individual.sharpe` 廉价近似，**不是真 Shapley**；非技术维度无数据 | fusion.vue:475-489 | 🟠 |
| 7 | "A/B 对比验证" 只看 `individualResults`，不是"逐维度累加" | fusion.vue:493-518 | 🟠 |
| 8 | 自定义/复合维度 items 是写死字符串，没有从后端加载用户实际策略 | fusion.vue:343-348 | 🟠 |
| 9 | `exportFusionCode` 字符串模板拼接，不能跑 | fusion.vue:610-625 | 🟡 |
| 10 | `saveFusionScheme` 仅 localStorage，不能跨设备 / 用户复用 | fusion.vue:602-608 | 🟡 |

视觉细节差异（非阻塞）：
- 技术维度原型用 chip 按钮态（active 蓝底白字），现状用 `<input type="checkbox">`。
- 5 维布局原型为"2×2 + 自定义独占第 3 行"，现状是 2 列 grid，自定义/情绪同行。
- 缺少日期 / 持仓选择控件（与买卖点优化、策略对比页不一致）。

---

## 2. 新版 API Schema

### 2.1 请求 `POST /quantia/api/verify/fusion`

```jsonc
{
  "version": 2,                 // 必填，区分新旧 schema
  "mode": "weighted_score",     // weighted_score | vote | condition_tree | rotation
  "start_date": "2025-01-01",
  "end_date": "2025-12-31",
  "holding_days": 10,           // 1..30
  "vote_threshold": 3,          // 仅 mode=vote 时使用，缺省为启用维度数的 60%
  "min_score": 0.6,             // 仅 mode=weighted_score 时使用，归一化加权和的入选阈值
  "rotation": {                 // 仅 mode=rotation 时
    "bull":   { "tech": 0.5, "fund": 0.2, "flow": 0.3, "sent": 0.0, "custom": 0.0 },
    "bear":   { "tech": 0.1, "fund": 0.5, "flow": 0.1, "sent": 0.3, "custom": 0.0 },
    "shock":  { "tech": 0.3, "fund": 0.3, "flow": 0.2, "sent": 0.2, "custom": 0.0 },
    "detector": "hs300_ma60"   // 牛/熊/震荡判定算法
  },
  "dimensions": {               // 五维同结构
    "tech": {
      "enabled": true,
      "weight": 30,             // 0..100
      "items": ["cn_stock_strategy_keep_increasing",
                "cn_stock_strategy_breakthrough_platform",
                "cn_stock_strategy_backtrace_ma250"]
    },
    "fund": {
      "enabled": true,
      "weight": 25,
      "items": ["pe9_lt_30", "pbnewmrq_lt_5", "roe_weight_gte_10",
                "gpr_gte_20", "ltgxl_lt_60"]
    },
    "flow": {
      "enabled": true,
      "weight": 20,
      "items": ["fund_amount_gt_0", "fund_amount_3d_gt_0"]
    },
    "sent": {
      "enabled": true,
      "weight": 15,
      "items": ["allcorp_ratio_gte_5", "allcorp_fund_num_gte_3"]
    },
    "custom": {
      "enabled": false,
      "weight": 10,
      "items": ["custom_93", "composite_7"]
    }
  }
}
```

### 2.2 响应

```jsonc
{
  "fusion_result": {
    "avg_return": 3.85, "win_rate": 75.2, "sharpe": 3.85,
    "max_drawdown": -6.8, "sortino": 4.12, "calmar": 0.57,
    "daily_signal_avg": 6.2, "signal_count": 1240,
    "total_return": 42.3
  },
  "daily_series": [{ "date": "2025-01-02", "cumulative": 100.0, "drawdown": 0.0, "signal_count": 5 }, ...],
  "individual_results": {
    "tech":   { "cn": "技术信号", "sharpe": 1.85, "win_rate": 60.2, "avg_return": 1.2, "signal_count": 4200, "max_drawdown": -12.3 },
    "fund":   { "cn": "基本面",  "sharpe": 1.45, ... },
    "flow":   { ... }, "sent": { ... }, "custom": { ... }
  },
  "shapley": [                  // 真 Shapley value (over 2^k 组合)
    { "dim": "tech",   "cn": "技术信号", "contribution": 0.52, "rank": 1 },
    { "dim": "fund",   "cn": "基本面",  "contribution": 0.34, "rank": 2 },
    ...
  ],
  "ab_steps": [                 // 按 Shapley 降序 / 也支持用户自定义顺序
    { "label": "①技术", "dims": ["tech"], "sharpe": 1.85, "win_rate": 60.2, "max_dd": -12.3, "signal_count": 4200, "delta_sharpe": 0 },
    { "label": "①+②基本面", "dims": ["tech","fund"], "sharpe": 2.45, ..., "delta_sharpe": 0.6 },
    ...
  ],
  "overlap": {
    "calendar": [              // 每日多维共振信号数
      { "date": "2025-01-02", "signal_count": 5, "dims_hit": 3 }, ...
    ],
    "co_occurrence": {         // 维度共现矩阵，单元 = 同时命中的标的-日数 / 任一命中数
      "labels": ["tech","fund","flow","sent","custom"],
      "matrix": [[1.0, 0.42, 0.18, 0.12, 0.03], ...]
    }
  },
  "improvement": {
    "sharpe_vs_best_single": "+24.5%",
    "drawdown_vs_worst_single": "+38.2%"
  },
  "warnings": [],              // 如降级、维度信号不足等
  "diagnostics": {
    "enabled_dims": ["tech","fund","flow","sent"],
    "rotation_regime_summary": null   // 仅 rotation 模式
  }
}
```

### 2.3 旧 schema 兼容

请求体如果**缺少 `version: 2`**，按旧逻辑跑：把 `strategy_names` 当作 `dimensions.tech.items`，`mode` 映射 `intersection→vote(threshold=N)` / `union→weighted_score(min_score=0)` / `vote→vote` / `rotation→rotation`。同时在响应里附加 `warnings: ["legacy schema, please upgrade to version=2"]`。

---

## 3. 后端管线设计

### 3.1 总体流程

```
[输入]
  ↓ 解析 + 校验（dimensions / mode / 日期 / holding_days）
[逐维度生成"日级 (date, code)"信号集]
  ├── tech:   读 cn_stock_strategy_* (按 items 列表合并)
  ├── fund:   读 cn_stock_selection  (按 items 表达式过滤)
  ├── flow:   读 cn_stock_fund_flow  (按 items 阈值过滤)
  ├── sent:   读 cn_stock_selection / cn_stock_blocktrade (情绪相关列)
  └── custom: 读 cn_stock_custom_indicator (用户自定义信号) / cn_stock_strategy_<custom_id>
[融合]
  ├── weighted_score:  归一化加权和 ≥ min_score 入选
  ├── vote:            ≥ vote_threshold 维度命中入选
  ├── condition_tree:  按维度权重降序 AND 链（前一维通过才进下一维）
  └── rotation:        根据 hs300 / 沪深300 检测当前 regime → 选用对应权重 → 走 weighted_score
[评估]
  ├── 用 cn_stock_strategy_<x>.rate_<holding_days> 反查未来收益（如果信号不在内置表则用 K 线缓存逐笔模拟）
  ├── 计算 sharpe / win_rate / avg_return / max_dd / signal_count / daily_signal_avg
  ├── 同步计算 individual_results（每维单独跑融合管线，得到该维度独立指标）
  └── Shapley value: 对启用维度的 2^k 子集逐一跑融合 → φ_i = mean_S (v(S∪{i}) − v(S))
[A/B 步进]
  按 Shapley 降序累加，记录每一步增量
[重叠分析]
  calendar: groupby(date).agg(signal_count=count, dims_hit=nunique(dim))
  co_occurrence: J(i,j) = |S_i ∩ S_j| / |S_i ∪ S_j|, 单元为 jaccard
```

### 3.2 关键代码骨架（后端伪码）

```python
class StrategyFusionHandler(webBase.BaseHandler):
    def post(self):
        body = self._parse_body()
        if body.get('version') != 2:
            body = self._upgrade_legacy(body)   # 旧 schema 自动映射
        spec = self._validate(body)             # 返回 FusionSpec dataclass

        # 1. 各维度生成 (date, code, score) DataFrame
        dim_signals = {}
        for k, dim in spec.dimensions.items():
            if not dim.enabled: continue
            dim_signals[k] = _load_dim_signals(k, dim.items, spec.start, spec.end)

        # 2. 主融合
        fused = _fuse(dim_signals, spec)        # 返回 (date, code) Index
        # 3. 评估
        fusion_result, daily_series = _evaluate(fused, spec.holding_days)

        # 4. 单维度独立指标
        individual = {k: _evaluate(_fuse({k: v}, spec)[0], spec.holding_days)[0]
                      for k, v in dim_signals.items()}

        # 5. Shapley
        shapley = _shapley(dim_signals, spec)   # 2^k 子集枚举

        # 6. A/B
        ab_steps = _ab_steps(dim_signals, shapley, spec)

        # 7. 重叠
        overlap = _overlap(dim_signals)

        # 8. improvement / warnings / diagnostics
        ...
        self._write_json({...})
```

### 3.3 维度数据源映射

| 维度 | 数据表 | item 语法 |
|---|---|---|
| `tech` | `cn_stock_strategy_<name>` | `"cn_stock_strategy_keep_increasing"`（表名直接） |
| `fund` | `cn_stock_selection` | `"<col>_<op>_<val>"`，op ∈ lt/lte/gt/gte/eq，如 `"pe9_lt_30"` |
| `flow` | `cn_stock_fund_flow` | 同上，如 `"fund_amount_gt_0"` |
| `sent` | `cn_stock_selection` 或 `cn_stock_blocktrade` | `"allcorp_ratio_gte_5"` |
| `custom` | `cn_stock_custom_indicator`（Phase 9 表）或 `cn_stock_strategy_<custom_id>` | `"custom_<id>"` / `"composite_<id>"` |

新增内部 helper `_load_dim_signals(dim, items, start, end) → DataFrame[date, code]`，统一返回 schema。

### 3.4 真 Shapley value

对 k 个启用维度，枚举 2^k - 1 个非空子集（k≤5 → ≤31 次回测），每次回测耗时由 `_evaluate` 决定。性能预算：每次回测 < 200 ms，整体 < 7 s（k=5）。
缓存 key：`(spec.holding_days, start, end, frozenset(subset_items_hash))` → 进程内 LRU(64)。

公式：

$$ \phi_i = \frac{1}{k!}\sum_{S\subseteq N\setminus\{i\}} |S|!\cdot(k-|S|-1)!\cdot[v(S\cup\{i\}) - v(S)] $$

其中 $v(S)$ = 该子集融合后的 sharpe ratio。

### 3.5 性能与降级

- k>5 在前端禁止；k=5 时上限 31 次回测，超时则返回 `warnings: ["shapley 超时, 已退化为单维度边际近似"]` 并退到现状的廉价估算。
- 日期区间 > 366 天直接拒绝（沿用旧逻辑）。
- 单维度命中数 = 0 → 该维度在 enabled_dims 里去掉，并写入 warnings。

---

## 4. 前端改造

### 4.1 组件分解（fusion.vue 拆为 4 子组件）

```
fusion.vue                       ← 主页 + 子 tab 控制
├── FusionConfigPanel.vue        ← 五维配置 + 模式 + 日期/持仓 + action bar
├── FusionResultCards.vue        ← KPI + 收益曲线
├── FusionShapleyPanel.vue       ← 真 Shapley 横向条形图 + 解读
├── FusionAbStepsPanel.vue       ← 累加表 + 增量条
└── FusionOverlapPanel.vue       ← 日历热图 + 共现矩阵
```

`fusion.vue` 主要持 state + 调 API；子组件 props 驱动。

### 4.2 关键 state（pinia / ref）

```ts
interface DimSpec {
  key: 'tech'|'fund'|'flow'|'sent'|'custom'
  cn: string; color: string
  enabled: boolean; weight: number
  items: { id: string; label: string; checked: boolean }[]
  tip: string
}
const spec = reactive({
  mode: 'weighted_score',
  startDate: '', endDate: '', holdingDays: 10,
  voteThreshold: 3, minScore: 0.6,
  dimensions: { tech: DimSpec, fund: ..., flow: ..., sent: ..., custom: ... }
})
```

`runFusionBacktest()`：直接 `apiFusion({ version: 2, mode, start_date, end_date, holding_days, dimensions: ...spec.dimensions, ...modeArgs })`。

### 4.3 自定义维度动态加载

```ts
onMounted(async () => {
  const [strategies, composites] = await Promise.all([
    getStrategyList(),       // 已有 /quantia/api/strategy/list
    getCompositeList(),      // 新 /quantia/api/composite/list（或复用已有自定义指标列表）
  ])
  spec.dimensions.custom.items = [
    ...strategies.filter(s => s.id_prefix === 'custom').map(s => ({ id: s.code, label: s.name, checked: false })),
    ...composites.map(c => ({ id: `composite_${c.id}`, label: c.name, checked: false })),
  ]
})
```

### 4.4 视觉对齐

- 技术维度信号 chip：用 `<button class="signal-chip" :class="{active: item.checked}" @click="item.checked=!item.checked">{{item.label}}</button>`。
- 5 维布局：`grid-template-areas` 显式排成 "tech fund" / "flow sent" / "custom custom"。
- 日期 / 持仓控件：放在融合模式 radio 同一行右侧。
- 权重总计：保持现状（运行按钮旁），但 ≠ 100 时按钮 disabled。

### 4.5 导出代码

改为生成可执行 Python（调用现有 `quantia.core.backtest.fusion_runner`），不再是字符串字典。

---

## 5. 测试计划

### 5.1 后端 pytest

新建 [tests/test_strategy_fusion_v2.py](../tests/test_strategy_fusion_v2.py)：

| 测试 | 描述 |
|---|---|
| `test_validate_rejects_no_dims` | 五维全 disabled → 400 |
| `test_validate_rejects_weight_total_not_100` | weighted_score 模式权重总和 ≠ 100 → 400 |
| `test_legacy_schema_auto_upgrade` | 缺 version=2 但有 strategy_names → 走 legacy 通路且 warnings 非空 |
| `test_weighted_score_basic` | tech+fund 两维，min_score=0.5，验证入选集与人工算法一致 |
| `test_vote_mode_threshold` | 三维启用，vote_threshold=2，命中数验证 |
| `test_condition_tree_chain` | 维度按权重降序 AND，验证最终命中集 = 各维度交集 |
| `test_rotation_regime_switch` | mock hs300 趋势 → 切换权重表 → 验证不同段使用不同 spec |
| `test_shapley_sum_equals_total` | 验证 Σφ_i ≈ v(N) − v(∅) |
| `test_shapley_cache_hits` | 同 spec 第二次调用，cache 命中率 = 100% |
| `test_overlap_jaccard_symmetric` | 共现矩阵对角=1，对称 |
| `test_dim_signal_empty_warning` | 某维度命中为 0 → 该维度被剔除并写入 warnings |
| `test_dim_load_fund` | fund items 解析 `"pe9_lt_30"` → 正确 SQL where clause |
| `test_dim_load_flow` | 同上 |
| `test_holding_days_clamp` | holding_days=100 被 clamp 到 30 |

### 5.2 前端 vitest

更新 [quantia/fontWeb/tests/views/verify/fusion.test.ts](../quantia/fontWeb/tests/views/verify/fusion.test.ts)：

| 测试 | 描述 |
|---|---|
| `dimensions all-five collected in payload` | 勾选 5 维各 1 项，检查 payload.dimensions.{k}.items |
| `disabled dim sends enabled=false but keeps weight` | 关闭 sent → payload.dimensions.sent.enabled=false |
| `mode passthrough` | UI weighted_score → payload.mode='weighted_score'（不再映射） |
| `weight total != 100 disables run` | 权重和 90% → run button disabled |
| `custom dim items loaded from API` | mock 返回 2 个自定义策略 + 1 个 composite，检查 items 长度=3 |
| `shapley panel renders bars` | mock 响应 shapley=[...]，检查 bar 数=维度数 |
| `ab steps cumulative delta` | mock ab_steps，检查 delta 渲染逻辑 |
| `overlap calendar renders` | mock overlap.calendar，检查 ECharts init |

### 5.3 集成 smoke

`tests/_verify.py` 增加 fusion smoke：post 一个最小 spec，断言响应包含 `fusion_result.sharpe`、`shapley.length>0`、`overlap.calendar.length>0`。

---

## 6. 分阶段任务清单

### Stage 1 — 后端真五维通路（先打通"不再撒谎"）

- [ ] 1.1 `_FusionSpec` dataclass + 校验
- [ ] 1.2 `_upgrade_legacy(body)` 旧 schema 自动映射
- [ ] 1.3 `_load_dim_signals(dim, items, start, end)` 五维统一加载器
- [ ] 1.4 `_fuse(dim_signals, spec)` 四模式融合
- [ ] 1.5 `_evaluate(signal_set, holding_days)` 评估指标
- [ ] 1.6 主 handler `_handle` 串起 1.1–1.5，返回基础响应
- [ ] 1.7 路由不变，restart + 黑盒验证返回新字段
- [ ] 1.8 后端 pytest (5.1) 前 7 条

### Stage 2 — 前端真五维

- [ ] 2.1 fusion.vue 拆分为主页 + 5 子组件
- [ ] 2.2 spec 状态结构改造
- [ ] 2.3 runFusionBacktest 收集全维度
- [ ] 2.4 日期 / 持仓选择 UI
- [ ] 2.5 mode 透传，去掉 modeMap
- [ ] 2.6 自定义维度动态加载
- [ ] 2.7 前端 vitest (5.2) 前 5 条
- [ ] 2.8 build + dist 部署

### Stage 3 — Shapley / A/B / 热图真数据

- [ ] 3.1 后端 `_shapley(dim_signals, spec)` + LRU 缓存 + 超时降级
- [ ] 3.2 后端 `_ab_steps`
- [ ] 3.3 后端 `_overlap`（calendar + jaccard 矩阵）
- [ ] 3.4 前端 Shapley/AB/Overlap 三 panel 接入真数据，移除廉价 computed
- [ ] 3.5 后端 pytest (5.1) 剩余 7 条
- [ ] 3.6 前端 vitest (5.2) 剩余 3 条

### Stage 4 — 视觉对齐原型

- [ ] 4.1 chip 化技术 / 基本面 / 资金 / 情绪维度信号
- [ ] 4.2 5 维 grid-template-areas 布局
- [ ] 4.3 导出代码改为可执行 Python
- [ ] 4.4 saveFusionScheme 改为后端 `POST /quantia/api/verify/fusion_scheme`（新表 `cn_stock_fusion_scheme`）

### Stage 5 — 测试 / 文档

- [ ] 5.1 5.3 smoke 测试
- [ ] 5.2 更新 [document/API_REFERENCE.md](API_REFERENCE.md) fusion 章节
- [ ] 5.3 更新 [AGENTS.md](../AGENTS.md) — 在 Custom-strategy parity 章节加 fusion v2 schema 一句
- [ ] 5.4 CHANGELOG / 用户公告（schema 升级，旧 schema 用户收到 warnings）

---

## 7. 依赖与风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| `cn_stock_selection` 不同年份字段名变动 (pe→pe9, pb→pbnewmrq) | fund 维度 SQL 出错 | 用 `tablestructure.py` 元数据校验，缺字段 → warnings 并跳过该 item |
| Shapley 2^5=31 次回测耗时 | 长请求 / 超时 | LRU + 进度 streaming + 5s 超时降级 |
| Rotation 模式 regime 判定算法尚未确定 | 实现不稳定 | Stage 1 仅占位返回 `weighted_score` 等效结果 + warning，Stage 3 再补 |
| 自定义维度 items 数据源（`cn_stock_custom_indicator` schema 是否包含 daily signal） | 自定义维度可能命中为 0 | Stage 1 用 enabled=false 默认值开发，Stage 2 接入真实数据并 fallback |
| 前端拆分 4 子组件可能引入 props/emit bug | 体验回归 | Stage 2 必跑 vitest + 浏览器手测一遍五维勾选 / 模式切换 |

---

## 8. 上线 / 回滚

- 改造在 master 分支按 Stage 顺序小步提交，每 Stage 一个 commit + push + 重启 + 黑盒验证。
- 若 Stage 3 Shapley 性能不达标，临时关掉 `shapley` 字段（前端容错显示"计算中"占位）。
- 旧 schema 兼容期至少保留 2 个版本。

---

## 9. 验收清单（功能侧）

完成后请逐项验收：

- [ ] 五维任一勾选都会进入后端真实评估，不再被静默丢弃。
- [ ] 4 种模式切换会改变后端处理逻辑（不再都走 intersection）。
- [ ] 日期 / 持仓可在 UI 调整并影响结果。
- [ ] 自定义维度展示当前用户实际的 `custom_*` / `composite_*`。
- [ ] Shapley 条形图各维度 contribution 之和 ≈ fusion sharpe − 0 (空集 baseline)。
- [ ] A/B 步进表的 dims 数严格按 Shapley 降序累加。
- [ ] 信号热图日历显示真实日均信号数，颜色随密度变化；维度共现矩阵对角=1.0。
- [ ] 旧前端 / 旧第三方调用仍能通过 legacy 通路得到响应（带 warnings）。
- [ ] 后端 pytest 14 条全过，前端 vitest 8 条全过。


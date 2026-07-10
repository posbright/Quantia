# 基金精选榜 + 入场择时 — 可落地开发文档（Impl WBS）

> 本文档是 [good_fund_selection_and_entry_timing_plan.md](good_fund_selection_and_entry_timing_plan.md)（设计蓝图）的**任务级实现拆解**。
> 目标：把蓝图 §4 的"落地实现方案"细化为**可直接编码的工作项**（新文件、函数签名、表 DDL、路由、测试、验收标准），并记录**比对代码后排查出的 bug/风险点**。
> 生成日期 2026-07-09。基线勘察方式：只读遍历 `quantia/core/fund/`、`quantia/job/`、`quantia/web/`、`web_service.py`、`tablestructure.py`、`notification/`。

---

## 0. 现状基线（EXISTS vs MISSING，已核实）

| 能力 | 状态 | 位置 |
|------|------|------|
| 基金多因子评分 `compute_scores` / `compute_max_drawdown` / `compute_sharpe` / `_clean_nav` | ✅ EXISTS | [scoring.py](../../quantia/core/fund/scoring.py) |
| 分批回测 `simulate_staged_buy` / `xirr` | ✅ EXISTS | [fund_backtest.py](../../quantia/core/fund/fund_backtest.py) |
| 评分批量 job → `cn_fund_rank_score` | ✅ EXISTS | [analysis_fund_score_job.py](../../quantia/job/analysis_fund_score_job.py) |
| 净值历史表 `cn_fund_nav_history`（code, nav_date, unit_nav, acc_nav, day_growth） | ✅ EXISTS（覆盖约 17.7%） | tablestructure |
| 免责/标签规则 `RISK_DISCLAIMER` / `tier_label` / `value_labels` | ✅ EXISTS | [labels.py](../../quantia/core/fund/labels.py) |
| 基金 Handler（rank/peer/composite/nav/holding/ai） | ✅ EXISTS | `quantia/web/fund*Handler.py` |
| 前端基金页 `views/fund/index.vue` + `FundDetailDrawer.vue` + `api/fund.ts` | ✅ EXISTS | fontWeb |
| 通知事件表 `cn_stock_notification_event`（含 `dedupe_key` 幂等） | ✅ EXISTS | notification |
| **择时纯函数 `timing.py`** | ✅ DONE (P1) | `quantia/core/fund/timing.py` |
| **`fundTimingHandler` + 路由** | ✅ DONE (P1) | `quantia/web/fundTimingHandler.py` |
| **前端"入场时机"卡片** | ✅ DONE (P1/P2) | `FundDetailDrawer.vue` |
| **`cn_index_valuation` 表 + 指数估值 Fetch job（T3）** | ✅ DONE (P3) | `fetch_index_valuation_job.py` + `crawling/index_valuation_lg.py` |
| **`analysis_fund_timing_job` + `cn_fund_timing_score`** | ⛔ 不新建（改由 pick_job 内联算） | 批量预计算未建独立表；`analysis_fund_pick_job._compute_timing` 逐只调 `timing.py` 算 T1+T2+**T3**，与 Handler 共用 `valuation_lookup.py` 单一事实源 |
| **T3 估值查询单一事实源 `valuation_lookup.py`** | ✅ DONE (P5 QA) | `quantia/core/fund/valuation_lookup.py`：Handler `_valuation_score` 与 pick_job 共用，消除「列表徽章 T1+T2 vs 抽屉档位 T1+T2+T3」漂移 |
| **`cn_fund_daily_pick` 表 + 精选 job + Handler** | ✅ DONE (P5) | `tablestructure.TABLE_CN_FUND_DAILY_PICK` + `analysis_fund_pick_job.py` + `fundDailyPickHandler.py` + 前端「每日精选」tab |
| **`fund_daily_pick` 钉钉推送** | ❌ MISSING | P6 |

---

## 1. 比对代码后排查出的 bug / 风险点（动手前必读）

> 以下为"文档设计 ↔ 真实代码/数据"比对后发现的、若不显式处理会导致错误或误导的点。

- **B1 截面 vs 时序口径混用（最高危）**：`scoring.cross_sectional_pct_rank` 是**桶内截面百分位**，若 timing 直接复用会导致"永远约 25% 基金被标低吸"。`timing.py` 的 `dd_score/trend_score` **必须按单基金自身时序映射到 0–100 绝对刻度**，严禁调用 `cross_sectional_pct_rank`。（对齐蓝图 §4.1、AGENTS 非重叠/绝对口径教训。）
- **B2 缺失维度处理不一致**：`scoring` 对缺失因子填 `NEUTRAL=50`；但 timing 蓝图 §3.2 要求缺失维度**丢弃并对剩余权重重归一化**（非填 50）。二者语义不同，`compose_timing_score` 必须实现"drop + renormalize"，不可照抄 scoring 的填中性。
- **B3 acc_nav 缺失（防线3）**：QDII/部分基金 `acc_nav` 为 NULL → `compute_max_drawdown` 直接 None。timing 需 `unit_nav` 兜底并回传 `acc_null=true`，前端标"缺累计/近似"。
- **B4 净值滞后（防线1）**：`cn_fund_nav_history` 仅覆盖约 17.7% 且更新不齐。Handler 必须校验 `pick_date - MAX(nav_date) > 7 天 → 不产出档位`（`stale=true`, tier=None），否则用一个月前净值判断"当前位置"会误导。
- **B5 覆盖缺失**：无净值历史的基金**不造信号**，返回 `data_available:false`，前端显示"暂无择时数据"，不得用 0 或中性分冒充。
- **B6 接飞刀**：T1 单用会在单边下跌持续给高分 → `compose_timing_score` 必须让 T2 趋势维度对"跌破长均线"扣分形成保护（trend_score 低时压制总分）。
- **B7 F13 措辞合规**：Handler/前端**禁"买/卖/加仓"**，复用 `labels.RISK_DISCLAIMER`。
- **B8 timing 单一事实源**：P1 未建批量表时，未来 pick_job 必须**调用同一 `timing.py` 纯函数**，禁止另写一套公式（防双算漂移，蓝图 §4.2）。
- **B9 路由注册对等（规则 8）**：前端新增 `getFundTiming()` 前，`web_service.py` 必须先注册 `/quantia/api/fund/timing`。
- **B10 T3 数据确认缺失**：指数 PE/PB 历史分位表不存在 → **P1 只做 T1+T2**，`compose_timing_score` 的 val 维度传 None，自动降为二维。T3 属 P3，须走 Fetch 管道新建 `cn_index_valuation`（规则 1，禁在 Handler 抓取）。
- **B11 货币型净值近似平坦（误判防护）**：货币型基金 `acc_nav` 近似单调平坦，回撤 `dd≈0 → dd_score≈0`，若照常合成会被误标"高估勿追"。Handler 必须对 `fund_type=='货币型'` 短路返回 `timing_applicable=false`（不适用点位择时），前端据此提示"货币型不做点位择时"。债券型有真实累计净值波动，照常走 timing（与前端原型 `债券型 timing:true` 一致）。
- **B12 回撤应为滚动峰值而非全史峰值（对齐蓝图 §4.1）**：蓝图 T1 签名 `drawdown_from_high(acc_nav, lookback)` 明确用"滚动峰值"，本 WBS 早期实现误用 `cummax()` 全史峰值。全史口径对"多年阴跌的价值陷阱"会永久判深回撤 → `dd_score=100` → 长期误标"低吸"（仅靠 T2 趋势部分抵消）。已修复为滚动窗口 `peak = nav.iloc[-lookback:].max()`，`DD_LOOKBACK=500`（≈2 年）；`lookback=None` 或 ≥样本长回退全史（保证少净值基金/短序列可算，18 项旧单测因序列 <500 全部回退全史 → 不回归）。Handler 默认取 `DD_LOOKBACK`。

### P5 QA 复审修复（2026-07-10，二次对照文档 ↔ 代码）

- **B13 pick_job 丢 T3 → 列表徽章与抽屉档位漂移**：`analysis_fund_pick_job._compute_timing` 早期传 `compose_timing_score(dd, trend, None)`，而抽屉 Handler 算 T3，导致有估值覆盖的 25/70 只基金"列表(T1+T2) vs 抽屉(T1+T2+T3)"档位不符（违反蓝图 §4.2 单一事实源）。已抽出 **`quantia/core/fund/valuation_lookup.py`** 供 Handler `_valuation_score` 与 pick_job 共用；pick_job 纳入 T3（货币/滞后/样本不足短路跳过），黑盒核对逐只一致。
- **B14 benchmark 映射无权重感知 → QDII 错套境内估值（逻辑 bug，根因）**：`benchmark_map.map_benchmark_to_index` 早期取首个字面命中的境内宽基，**忽略权重**。如"MSCI全球×75%＋沪深300×20%"被映射为 `000300`，给以海外资产为主的 QDII 套沪深300 PE 分位，属误导信号（违背模块自身"宁缺毋滥"约束）。已改为**权重主导**：按 `＋/+` 拆成分取"最大权重成分"定锚；主导成分不可映射（全球/海外/债券）→ None。修复后 017730/018230（MSCI 主导 QDII）、018304（中债 50% 主导 FOF）不再套境内估值；020795（沪深300 55.2%）、015084（中证800 75%）仍正确映射。新增 6 例单测覆盖真实 QDII/FOF 基准；Handler 与 pick_job 因共用同一函数一并修正。
- **B15 净值滞后未在榜单前端展示（完成性缺口，§7.1bis/§7.2bis）**：榜单接口已返回 `data_lag_days/nav_as_of` 但前端 `FundDailyPickTab.vue` 未渲染。已加"净值滞后 N 天"标签：QDII 桶必须展示（§7.1bis），其余桶仅在 `data_lag_days ≥ 5` 自然日时以警示色提示（§7.2bis），`nav_as_of` 作 title 悬浮。

---

## 2. P1 详细实现（零外部依赖，纯净值 T1+T2）

### 2.1 新增纯函数模块 `quantia/core/fund/timing.py`

**设计约束**：纯函数、无 I/O、可合成数据测试；绝对时序刻度（B1）；缺失维度 drop+renormalize（B2）。

```python
# 档位阈值（对齐蓝图 §3.2 与前端原型 tierOf）
TIER_LOW  = 75   # 低吸 ≥75
TIER_DCA  = 50   # 定投 50–75
TIER_WAIT = 30   # 观望 30–50
#                高估勿追 <30

# 默认权重（三维；缺维时对剩余重归一化到 1）
DEFAULT_WEIGHTS = {'dd': 0.5, 'trend': 0.3, 'val': 0.2}

def drawdown_from_high(acc_nav, cap=0.30, lookback=500) -> float|None
    """T1：dd = last/peak - 1（≤0），peak 取最近 lookback 个点的最大值（滚动峰值，
       对齐蓝图 §4.1「相对自身近期高点」；lookback=None 或 ≥样本长 → 全史峰值）。
       映射到 0–100 绝对分：跌幅 m=-dd，score = clip(m/cap*100, 0, 100)。m≥cap(默认30%)→100。
       样本<2 或全非正 → None。复用 scoring._clean_nav 口径。"""

def nav_trend_score(acc_nav, ma_window=60) -> float|None
    """T2：站上自身长均线 + 斜率确认。
       r = last/ma - 1；slope = ma 近端斜率符号。
       score = clip(50 + r*250 + (slope>0 ? 10 : -10), 0, 100)。
       样本<ma_window → None（不足则该维缺失，交由 compose 重归一化）。"""

def valuation_percentile_score(pe_or_pb_series) -> float|None
    """T3（P1 传 None）：指数 PE/PB 历史时序分位。低分位→高分（便宜）。
       score = clip((1 - percentile)*100, 0, 100)。序列缺失→None。"""

def compose_timing_score(dd, trend, val, weights=DEFAULT_WEIGHTS) -> dict
    """缺失维度 drop + 对剩余权重重归一化（B2）。
       返回 {score:0-100|None, tier:str|None, components:{dd,trend,val}, dims_used:[...]}。
       全维缺失 → score=None, tier=None。"""

def tier_of(score) -> str|None
    """score→档位中文：低吸/定投/观望/高估勿追；None→None。"""
```

**验收（单测 `tests/test_fund_timing.py`）**：
- `drawdown_from_high`：单调净值上升（无回撤）→ 低分；深跌 30% → 100；样本<2 → None；cap 边界。
- `nav_trend_score`：站上均线且上行 → >50；跌破均线 → <50；样本不足 → None。
- `compose_timing_score`：三维齐全加权正确；val 缺失时 dd/trend 权重重归一化到 (0.625/0.375) 且 score 落在 0–100；全缺 → None。
- `tier_of`：79→低吸 / 60→定投 / 40→观望 / 20→高估勿追 / None→None。
- **绝对刻度不变性**：把同一 fund 的净值整体缩放常数倍，dd/trend score 不变（证明非截面）。

### 2.2 新增 Handler `quantia/web/fundTimingHandler.py`

- 路由：`GET /quantia/api/fund/timing?code=xxx`
- 只读 `cn_fund_nav_history`（acc_nav，缺则 unit_nav 兜底 B3）+ `cn_fund_rank`（name/fund_type）+ `cn_fund_rank_score`（score/fund_type 求 quality_pass）。
- 逻辑：
  1. 取名称/类型/质量分（best-effort，缺失不阻断）。
  2. `fund_type=='货币型' → timing_applicable=false` 短路返回（B11）。
  3. 取该基金全部净值（按 nav_date 升序），显式列 SELECT（规则 7）。
  4. `MAX(nav_date)` 与"今日"比对，`> 7 天 → stale=true, tier=None`（B4，滞后时仍回传分量供透明展示）。
  5. 样本不足 / 无净值 → `data_available:false`（B5）。
  6. 调 `timing.drawdown_from_high` + `nav_trend_score` + `compose_timing_score(val=None)`（P1 二维）。
  7. quality_pass = `cn_fund_rank_score.score >= 70`（缺则 None，不硬判）。
- 返回：
  ```json
  {"code","name","fund_type","as_of","data_available":true,"timing_applicable":true,
   "stale":false,"acc_null":false,
   "timing_score":78,"tier":"低吸","components":{"dd":82,"trend":66,"val":null},
   "dims_used":["dd","trend"],"quality_pass":true,"quality_score":92,
   "disclaimer":"...F13 免责..."}
  ```
- **禁买卖措辞**，`disclaimer` 用 `labels.RISK_DISCLAIMER`（B7）。
- 在 [web_service.py](../../quantia/web/web_service.py) 基金路由段注册（B9，规则 8）。

### 2.3 前端"入场时机"卡片（增量）

- `api/fund.ts` 新增 `getFundTiming(code)`。
- `FundDetailDrawer.vue` 新增"🎯 入场时机"卡：档位徽章（低吸/定投/观望/高估）+ 三维分量条 + `stale/data_available/timing_applicable` 占位文案 + 免责。
- 占位优先级：`timing_applicable=false`（货币型）→"货币型不做点位择时"；`data_available=false`→"暂无择时数据"；`stale=true`→"净值滞后，暂不产出档位"（仍可展示分量条）。
- 移动端卡片式适配（AGENTS 移动端规范，`useResponsive`）。
- **零桌面回归**；条件只判断数据本身（`data_available`/`timing_applicable`），不 gate 在其它无关状态后。

### 2.4 P1 验收流程

1. `pytest tests/test_fund_timing.py -q` 全绿。
2. 重启 `web_service.py`，黑盒 `Invoke-RestMethod /quantia/api/fund/timing?code=<有净值历史的code>` 返回 200 + 预期字段。
3. 取一个净值滞后基金验证 `stale=true, tier=null`；取无净值历史基金验证 `data_available=false`。
4. 前端抽屉桌面 + 移动端渲染正常，档位与后端一致。

---

## 3. 后续期次 WBS（P2–P6，依赖递增，逐期交付）

| 期 | 工作项 | 新建物 | 前置/风险 |
|----|--------|--------|-----------|
| **P2** | 回测对照：择时买入 vs 定投 vs 一次性 | 复用 `fund_backtest.simulate_staged_buy` + 择时择点；实验结论落 `document/fund/` | 用真实 acc_nav 切样本内外，禁固定系数造伪 OOS |
| **P3** | T3 估值维度 | ✅ Fetch：`fetch_index_valuation_job.py` + `crawling/index_valuation_lg.py` + `cn_index_valuation` 表（规则1，chunksize=500）；`benchmark_map.py` 基准→指数映射（**边界校验**：以宽基名开头的风格/行业子指数如「沪深300成长」「中证500信息技术」判定无覆盖→None，生产实测 10 例，不错套宽基估值）；Handler 接入 val 维 | 指数估值源：legulegu 全历史（akshare `stock_index_pe_lg` 已被上游日期格式变更打挂，改直连端点 + 自适应日期解析）；仅 12 只宽基有覆盖，非宽基/无 profile 基金 val=None 自动降维 | 
| **P4** | 选基增量：**T6 穿透式持仓位置参考卡（✅ 已交付）**、**权益持仓风格暴露卡 + 前向兼容漂移（✅ 已交付）**、**经理经验弱因子（✅ 已交付）** | ✅ **T6**：`core/fund/lookthrough.py`（纯函数：距高点回撤 / 长均线位置 / RSI 超卖，等权→个股位置分，hold_ratio 加权→底层位置分，复用 `timing.drawdown_from_high` 含 B12 全期滚动峰值修复）+ `fundLookThroughHandler.py`（读 `cn_fund_holding` 最新季度前十大重仓股，逐股用**本地 K 线缓存** `load_stock_data(cache_only=True)` 算位置，规则1 只读不触外部 API；仅 A 股 6 位纯数字有行情，QDII/港股 `priced=false`）+ `/api/fund/look_through` + 前端 T6 卡（条形天然适配移动端）。✅ **风格暴露**：`core/fund/style_drift.py`（`industry_exposure` 按 hold_ratio 加权行业分布 + 集中度 HHI + `未分类`透明化；`style_drift` 相邻季 L1 漂移，前向兼容）+ `fundStyleHandler.py`（读 `cn_fund_holding` 各季，最新季算暴露、≥2 季自动算漂移）+ `/api/fund/style` + 前端风格卡。**实测生产库每基金仅 1 季 → `drift_available=false`，历史累积后自动点亮**（非伪造）。✅ **经理经验**：Fetch `crawling/fund_em.py::fund_manager_all`（`akshare.fund_manager_em` 全量→英文列 + 计算每位经理在管基金数 fund_count）+ `fetch_fund_manager_job.py`（按 `cn_fund_rank` 全集过滤 upsert `cn_fund_manager`，主键 (code,manager)，规则1 只读回填、chunksize=500）+ 纯函数 `core/fund/manager_factor.py`（团队最大/平均从业年限、经验档位、最佳回报、一拖多 max_fund_count≥15 提示）+ `fundManagerHandler.py` `/api/fund/manager` + 前端经理卡。**实测生产库 26515 条 / 20449 只基金覆盖**（黑盒 015495 资深12.7y 一拖多25、001092 一拖多57、011251/012466 成熟）| 不得影响无覆盖基金（无覆盖/全 `未分类`/无经理→`data_available=false` 前端不渲染卡）；风格暴露/漂移/经理经验**均仅风控辅助/弱因子展示、不硬拦截、不进入 TimingScore**（蓝图 §9.2）；`未分类`（科创板断层）仅透明化占比、不计入集中度/漂移；「累计从业时间」是经理全市场累计从业、**非本基金任职起始日**；`disclosed_ratio` 透明化穿透覆盖；季报滞后约一季度 |
| **P5** | 每日精选榜 | `cn_fund_daily_pick` 表 + `analysis_fund_pick_job.py`（AC 去重→先 TopN 后截 Top10；时钟看门狗 90%）+ `/api/fund/daily_pick` Handler + 前端榜单页 | 复用 `timing.py`（B8）；申购状态需 P 前置补表 |

> **P5 已交付（2026-07-09）**：① `tablestructure.TABLE_CN_FUND_DAILY_PICK`（PK `(date,fund_type,code)`，15 列，NaN/inf 源头清洗、`chunksize=500`）。② `quantia/core/fund/pick_selection.py` 纯函数（`normalize_fund_name` 份额正规化、`dedup_ac` AC 去重保留主份额、`select_bucket_top` **先 Top-N(25) by quality → 去重 → 重排 → 截 Top10**，并写 `rank_in_type`）+ 19 单测。③ `quantia/job/analysis_fund_pick_job.py`（Analysis 只读：读 `cn_fund_rank_score`(quality/max_drawdown) 与 `cn_fund_rank`(name/rate_1y) 对齐 as-of 截面，逐桶选 Top10，批量读 `cn_fund_nav_history` 用 `timing.py` 纯函数算弱标签，NULL 容忍：货币型/债券型无净值→timing 空、滞后>7 天→档位空；`final_score` V1=quality_score；删当日旧榜后写入）。④ `quantia/web/fundDailyPickHandler.py` + 路由 `/quantia/api/fund/daily_pick`（读最新运行日、按 fund_type 分桶 Top10、`timing_applicable`/`has_timing` 供前端抑制徽章）。⑤ 前端 `FundDailyPickTab.vue`（桶胶囊 + 条形质量分 + 入场档位徽章 + 回撤/近1年，移动端网格自适应，点击行开详情抽屉）挂载到 `views/fund/index.vue` 「每日精选」tab；`?pick=1` 深链切 tab、`?code=xxx` 自动开详情抽屉。**验证**：作业落库 70 行/7 桶（2026-07-09，score_as_of 2026-07-08），黑盒 `/api/fund/daily_pick` 200，7 桶有序、股票/混合/指数/QDII/FOF has_timing=true、债券 has_timing=false、货币 timing_applicable=false；混合型质量分严格降序；`npm run build`(vue-tsc) 通过；53 基金纯函数单测通过。
| **P6** | 钉钉推送 | 复用 `cn_stock_notification_event` dedupe（`hash('fund_daily_pick',pick_date)`）；深链公网可达 + 免登 token | 内网地址/登录墙硬前提（蓝图 §5.12） |

---

## 4. 落地顺序与本次范围

**本次（P1 核心）落地顺序**：`timing.py` → 单测跑绿 → `fundTimingHandler` + 路由 → 黑盒验证 → 前端卡片。
后续期次每期单独提交并验证，不一次性铺开。

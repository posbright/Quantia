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
| **择时纯函数 `timing.py`** | ❌ MISSING | 本文档 P1 |
| **`fundTimingHandler` + 路由** | ❌ MISSING | 本文档 P1 |
| **前端"入场时机"卡片** | ❌ MISSING | 本文档 P1 |
| **`cn_index_valuation` 表 + 指数估值 Fetch job（T3）** | ❌ MISSING | P3 |
| **`analysis_fund_timing_job` + `cn_fund_timing_score`** | ❌ MISSING | P3 |
| **`cn_fund_daily_pick` 表 + 精选 job + Handler** | ❌ MISSING | P5 |
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

def drawdown_from_high(acc_nav, cap=0.30) -> float|None
    """T1：dd = last/peak - 1（≤0）。映射到 0–100 绝对分：
       跌幅 m=-dd，score = clip(m/cap*100, 0, 100)。m≥cap(默认30%)→100。
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
- 只读 `cn_fund_nav_history`（acc_nav，缺则 unit_nav 兜底 B3）+ `cn_fund_rank_score`（score/fund_type 求 quality_pass）。
- 逻辑：
  1. 取该基金全部净值（按 nav_date 升序），显式列 SELECT（规则 7）。
  2. `MAX(nav_date)` 与"评分快照日/今日"比对，`> 7 天 → stale=true, tier=None`（B4）。
  3. 样本不足 → `data_available:false`（B5）。
  4. 调 `timing.drawdown_from_high` + `nav_trend_score` + `compose_timing_score(val=None)`（P1 二维）。
  5. quality_pass = `cn_fund_rank_score.score >= 70`（缺则 None，不硬判）。
- 返回：
  ```json
  {"code","name","as_of","data_available":true,"stale":false,"acc_null":false,
   "timing_score":78,"tier":"低吸","components":{"dd":82,"trend":66,"val":null},
   "dims_used":["dd","trend"],"quality_pass":true,"quality_score":92,
   "disclaimer":"...F13 免责..."}
  ```
- **禁买卖措辞**，`disclaimer` 用 `labels.RISK_DISCLAIMER`（B7）。
- 在 [web_service.py](../../quantia/web/web_service.py) 基金路由段注册（B9，规则 8）。

### 2.3 前端"入场时机"卡片（增量）

- `api/fund.ts` 新增 `getFundTiming(code)`。
- `FundDetailDrawer.vue` 新增"🎯 入场时机"卡：档位徽章（低吸/定投/观望/高估）+ 三维分量条 + `stale/data_available` 占位文案 + 免责。
- 移动端卡片式适配（AGENTS 移动端规范，`useResponsive`）。
- **零桌面回归**；条件只判断 `data_available`，不 gate 在其它状态后。

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
| **P3** | T3 估值维度 | Fetch：`fetch_index_valuation_job.py` + `cn_index_valuation` 表（规则1）；`analysis_fund_timing_job` 落 `cn_fund_timing_score`（chunksize=500） | 指数估值确认缺失；基准文本解析噪声 |
| **P4** | 选基增量：经理经验弱因子、权益持仓风格漂移提示、T6 穿透式持仓位置参考卡 | 复用 `cn_fund_holding`（覆盖不足→仅有覆盖基金） | 不得影响无覆盖基金；季报滞后仅作参考 |
| **P5** | 每日精选榜 | `cn_fund_daily_pick` 表 + `analysis_fund_pick_job.py`（AC 去重→先 TopN 后截 Top10；时钟看门狗 90%）+ `/api/fund/daily_pick` Handler + 前端榜单页 | 复用 `timing.py`（B8）；申购状态需 P 前置补表 |
| **P6** | 钉钉推送 | 复用 `cn_stock_notification_event` dedupe（`hash('fund_daily_pick',pick_date)`）；深链公网可达 + 免登 token | 内网地址/登录墙硬前提（蓝图 §5.12） |

---

## 4. 落地顺序与本次范围

**本次（P1 核心）落地顺序**：`timing.py` → 单测跑绿 → `fundTimingHandler` + 路由 → 黑盒验证 → 前端卡片。
后续期次每期单独提交并验证，不一次性铺开。

# 选股验证中心 — 重构计划

> **版本**: v5.0
> **日期**: 2026-05-14
> **目标**: 构建策略对比优化中心 + 多维融合 + 因子实验室，直观对比数据，辅助优化策略买卖点、提升收益率、降低回撤、提高夏普比
> **原则**: 增量开发、不影响现有功能、不引入新 bug

---

## 一、v2 设计审查 — 问题与改进

### 1.1 已有设计优点

| Tab | 优点 |
|-----|------|
| 多策略对比 | 指标矩阵覆盖面广（收益/风险/风险调整后/交易质量），雷达图+综合评分直观 |
| 买卖点优化 | 持仓天数扫描+买入条件诊断是核心亮点，AI建议卡片实用 |
| 风险控制 | 止盈止损矩阵热力图思路好，市场环境适应性分析有独特价值 |
| 策略融合 | 信号交集/并集/投票/轮动四种模式覆盖主流组合方法 |

### 1.2 前端布局 & 可视化审查 (v2 → v3 修正)

#### 🔴 布局结构问题

| # | 问题 | 详细说明 | 修正方案 |
|---|------|----------|----------|
| L1 | **Tab 2 内容过载** | "买卖点优化"一个 Tab 塞入了持仓天数分析 + 买入信号诊断 + AI 建议三块独立分析，滚动深度过长(>3 屏)，用户容易迷失 | 改为 Sub-Tabs: `[持仓优化] [信号诊断] [止盈止损] [风控]`，每个 Sub-Tab 控制在 1.5 屏以内 |
| L2 | **Tab 2 和 Tab 3 职责重叠** | "止盈止损矩阵"从逻辑上属于卖出时机优化(Tab 2 范畴)，但放在了"风险控制(Tab 3)"。"市场环境"本质是策略选择(Tab 1)而非风控 | Tab 3 取消独立 Tab → 止盈止损移入 Tab 2 的子面板；市场环境移入 Tab 1 作为"适用场景"对比维度 |
| L3 | **Tab 1 雷达图 + 指标矩阵信息重复** | 两者展示基本相同的维度(收益/夏普/胜率/回撤...)，并排放置时用户难以确定看哪个 | 明确分工: 矩阵表 = 精确数据对比(主)，雷达图 = 综合概览(辅)。雷达图缩小放在综合评分卡片上方作为视觉引导，不独占半屏 |
| L4 | **策略选择器缺少搜索和分组** | 14 个策略仅用 Chip 平铺，无法快速定位；随策略增多将溢出 | 改为 `el-select` 多选 + 下拉分组(技术/量价/形态/AI)，保留已选 Chip 标签区 |

#### 🟡 可视化逻辑问题

| # | 问题 | 详细说明 | 修正方案 |
|---|------|----------|----------|
| V1 | **持仓表"交易笔数"列全部相同(856)** | 信号数不随持仓天数变化，该列占位但无对比价值，造成视觉噪声 | 移除"交易笔数"列，改为在表头统一展示"共 856 个信号" |
| V2 | **止盈止损矩阵用黄色单色阶** | 浅黄→深黄在屏幕上对比度不够，难以快速辨别优劣 | 改为发散色阶: 蓝(低夏普) → 白(中) → 红(高夏普)，与 ECharts heatmap 原生色阶一致 |
| V3 | **"持仓天数 vs 回撤"用面积图不合适** | 面积图暗示连续累积关系，但各持仓天数是离散的独立实验 | 改为**柱状图**(X=离散持仓天数, Y=回撤)，叠加散点(每笔交易的个别回撤)看分布 |
| V4 | **双 Y 轴图风险** | "持仓天数 vs 夏普"左轴=夏普比率，右轴=平均收益率。两个量纲不同的指标共用 X 轴容易让用户误读交叉点 | 拆为两个并排小图，或用 tooltip 联动代替双 Y 轴 |
| V5 | **信号诊断表同时展示 3 个指标(RSI/vol/MACD)** | 表格行数过多(3×4=12 行)，且用户一般一次只关注一个指标 | 改为**指标选择下拉** + 单指标分桶表。增加散点图(X=指标值, Y=后续收益)作为辅助可视化 |
| V6 | **缺少分布可视化** | 持仓天数表只有 avg/胜率等统计值，看不到分布形态(是正偏还是负偏? 有没有厚尾?) | 每个持仓天数行增加**迷你箱线图**(miniBoxPlot): P10/P25/P50/P75/P90，一眼看出分布形态 |
| V7 | **融合结果走势图缺少置信区间** | 融合策略收益曲线只有均值线，无法感知不确定性 | 添加半透明区间(如 Bootstrap 重抽样 95% CI)包裹均值线 |

#### 🟢 颜色语义问题 (A 股红涨绿跌)

| # | 问题 | 修正 |
|---|------|------|
| C1 | **`optimize-badge` 颜色反直觉** | `ob-up`(🔺 黄金区间)用红底 → 在 A 股语境下红=涨=正面，**语义正确**但与通用 UI "红=警告"冲突 | 统一规则: 收益/胜率相关用 A 股色(红正绿负)；风控/回撤用通用色(绿好红坏)。避免混淆 |
| C2 | **风险指标"最优"标绿** | 最大回撤 -8.2% 标为 `--down` 绿色 (表示好)，但用户直觉"绿=下跌=不好"(A 股) | 风险指标最优用**蓝色**高亮(中性/专业色)，不用红绿，避免歧义 |
| C3 | **综合评分排名末位用红底** | 海龟交易 58.8 分用 `#fff1f0` 红底，在 A 股语境红=好，但此处红=差 | 末位用灰底 `#f5f5f5`，避免红绿在评分上下文中的歧义 |

#### 🔵 与现有系统一致性问题

| # | 问题 | 修正 |
|---|------|------|
| S1 | **v2 原型用自定义侧边栏** | 现有系统用 `el-aside(#304156)` + `el-menu` + 路由驱动。v2 原型侧边栏只是展示 | 实际开发时复用 `layout/Sidebar.vue`，仅追加菜单项，不自定义侧边栏 |
| S2 | **v2 原型用原生 `<table>`** | 现有系统的回测对比页(`backtest-compare.vue`)也用原生 `<table class="cmp-table">`，**这一点一致** | ✅ 保持原生 table（不强制用 el-table），但复用 `.cmp-table` 样式类 |
| S3 | **v2 原型 Tab 用自定义 CSS** | 现有系统统一用 `el-tabs` + `el-tab-pane` | 改用 `el-tabs` 组件，与 dashboard.vue / backtest-compare.vue 保持一致 |
| S4 | **v2 原型用自定义按钮组** | 现有系统用 `el-button` / `el-button-group` | 改用 Element Plus 组件: `el-button`、`el-radio-group`(周期切换)、`el-select`(策略/基准选择) |
| S5 | **图表占位符需替换** | v2 用 `<div class="chart-ph">` 文字描述代替图表 | 实际开发用 `echarts.init()` + `setOption()`，参考 `dashboard.vue` 的图表初始化模式 |

### 1.3 数据来源可行性问题 (原 1.2A)

| 问题 | 详情 | 影响 |
|------|------|------|
| **买入条件诊断缺乏数据支撑** | v2 设计按 RSI/vol_ratio/MACD 区间分桶统计收益，但当前 `cn_stock_backtest_data` 表只存了 rate_1..rate_100 和基础价量，**没有存买入时刻的技术指标快照** | Tab 2 核心功能无法实现 |
| **市场环境分类无后端实现** | v2 设计按"沪深300 MA20 > MA60"判定牛熊，这需要一个专门的 regime detector，当前不存在 | Tab 3 环境适应性无法落地 |
| **策略融合运算量巨大** | 信号交集/并集需要在同一时间窗口内运行多个策略，当前 batch backtest 是串行的 | Tab 4 性能风险 |
| **持仓天数 vs 夏普计算方式模糊** | rate_1..rate_120 是平均收益率，但夏普比率需要 **日频 NAV 序列**，不能简单用 avg_rate 除以 σ | Tab 2 核心指标不准确 |

#### B. 设计缺失项

| 缺失项 | 说明 | 优先级 |
|--------|------|--------|
| **策略参数敏感性分析** | 如海龟交易的 N 日突破参数从 10→30 对收益的影响，是优化策略的关键手段 | P1 |
| **信号衰减分析** | 策略 Alpha 是否随时间衰减？近 3 个月 vs 近 1 年的夏普差异 | P1 |
| **样本外验证** | 优化后的参数必须在样本外数据上验证，否则过拟合 | P0 |
| **交易成本敏感性** | 不同佣金/滑点假设下的收益变化（当前固定 0.20%） | P2 |
| **持仓集中度/相关性** | 策略选出的股票是否高度相关？分散化程度如何？ | P2 |
| **数据质量诊断** | 回测前检查: 停牌/涨跌停/数据缺失比例，避免"幸存者偏差" | P1 |

#### C. 交互设计问题

| 问题 | 改进建议 |
|------|----------|
| 对比策略选择器没有搜索/分组功能 | 添加策略分类标签（技术/量价/形态/AI）+ 搜索框 |
| 止盈止损矩阵只有色阶无数字交互 | 点击单元格弹出该组合的详细指标（收益分布、交易笔数等） |
| 融合实验没有进度反馈 | 多策略回测耗时长，需要 WebSocket 进度条 |
| 缺少"导出/保存为新策略"功能 | 优化后的参数应可一键保存为新的策略配置 |

---

## 二、改进后的功能架构

### 2.1 整体页面结构（v3 修正版）

```
选股验证中心 (路由: /verify, 追加至 el-menu 侧边栏)
├── /verify/compare           ← 多策略对比（包含市场环境适配维度）
│   ├── 核心指标矩阵（主表）
│   ├── 综合评分 + 雷达图缩略（辅）
│   ├── 累计收益走势 + 水下回撤
│   ├── 信号衰减分析（月度趋势）
│   └── 市场环境适应性对比（从 Tab 3 迁入）
│
├── /verify/optimize          ← 买卖点优化（Sub-Tabs 拆分，原 Tab 2+3 合并）
│   ├── [持仓优化] 持仓天数扫描 + 夏普曲线 + 迷你箱线图
│   ├── [信号诊断] 单指标选择 → 分桶表 + 散点图
│   ├── [止盈止损] 热力图矩阵(发散色阶) + 点击弹窗详情
│   ├── [风险控制] 回撤分析 + 成本敏感性
│   ├── [样本外验证] 70/30 拆分 + 过拟合风险标注
│   └── AI 优化建议卡片（固定在底部）
│
└── /verify/fusion            ← 策略融合实验
    ├── 融合配置器（模式/策略/过滤）
    ├── 融合 vs 原始对比表 + KPI 卡片
    └── 收益走势（粗线+CI区间）
```

> **与 v2 的关键布局差异**:
> - 取消独立 Tab 3 "风险控制"，止盈止损/回撤分析并入 optimize 的 Sub-Tab
> - 市场环境适应性从 Tab 3 迁到 Tab 1（compare 页底部），因为它本质是"策略在不同场景下的对比"
> - Tab 2 拆为 5 个 Sub-Tab 避免超长滚动
> - 雷达图降级为综合评分卡片的辅助图而非独占半屏

### 2.2 新增 & 增强的功能模块

#### 模块 A: 多策略对比 (`/verify/compare`)

| 子功能 | 数据来源 | 新增后端 | 说明 |
|--------|----------|----------|------|
| 核心指标矩阵 | `cn_stock_backtest` 表 avg_rate_N + portfolio 回测 metrics | ✗ 复用 `GetBacktestCompareHandler` | 按 rate_1/3/5/10/20 + 夏普/回撤/胜率/盈亏比横向对比 |
| 雷达图 | 上述数据归一化 | ✗ 前端计算 | 6 维: 收益率·夏普·胜率·盈亏比·回撤控制·信号稳定性 |
| 综合评分 | 上述数据加权 | ✗ 前端计算 | 可配置权重（默认: 夏普40%+收益30%+回撤20%+胜率10%） |
| 累计收益走势 | `nav_series` JSON from `cn_stock_backtest_portfolio` | ✗ 复用 | 多策略叠加+水下回撤曲线 |
| ⭐ **信号衰减分析** | `cn_stock_backtest` 按月分组统计 | ✓ 新增 API | 按月展示策略胜率/收益率趋势，检测 Alpha 是否衰减 |

#### 模块 B: 买卖点优化 (`/verify/optimize`)

| 子功能 | 数据来源 | 新增后端 | 说明 |
|--------|----------|----------|------|
| ⭐ **持仓天数扫描** | `cn_stock_backtest_data.rate_1..rate_100` | ✓ 新增 API | 对每个持仓天数统计: 平均收益、胜率、收益标准差、夏普(rate/σ)、P10/P90 |
| ⭐ **买入指标快照诊断** | `cn_stock_trade_indicator_snapshot` (Phase 2 表) | ✓ 新增 API | 按 RSI/MACD/vol_ratio 分桶，关联后续 rate_5 收益，找出高质量信号区间 |
| ⭐ **止盈止损矩阵扫描** | `cn_stock_backtest_data.rate_1..rate_100` 逐日模拟 | ✓ 新增 API | 对每笔交易遍历 (SL, TP) 网格，在触达止盈/止损/到期三者中取先触发者，计算各组合的夏普/回撤/胜率 |
| ⭐ **卖出方式对比** | rate_stats.get_rates_with_exit() + 新增逻辑 | ✓ 增强 API | 对比: 固定持有N日 vs 指标反转卖出 vs 跟踪止盈 vs 止盈止损 |
| AI 优化建议 | 上述分析结果 | ✓ 新增 API | 基于分析结果自动生成: 最优持仓期、建议过滤条件、止盈止损参数 |
| ⭐ **样本外验证** | 拆分数据 70%/30% | ✓ 新增逻辑 | 优化参数在训练集上确定，在测试集上验证，标注过拟合风险 |

#### 模块 C: 风险控制分析（合并至 optimize 页面的子 Tab）

| 子功能 | 数据来源 | 新增后端 | 说明 |
|--------|----------|----------|------|
| 回撤深度分析 | portfolio `nav_series` | ✗ 前端计算 | 水下曲线 + Top-5 回撤标注 |
| 回撤恢复时间 | 同上 | ✗ 前端计算 | 统计 >5%/>10% 回撤次数 + 平均恢复天数 |
| ⭐ **市场环境适应性** | 基准指数 K 线 + 策略 backtest 数据 | ✓ 新增 API | 用 MA20/MA60 交叉 + ATR 中位数分类牛/熊/震荡，分环境统计策略表现 |
| ⭐ **交易成本敏感性** | 重新计算不同 cost 下的 rate | ✓ 新增 API | 展示佣金 0.1%/0.2%/0.3% 下的净收益变化 |

#### 模块 D: 策略融合实验 (`/verify/fusion`)

| 子功能 | 数据来源 | 新增后端 | 说明 |
|--------|----------|----------|------|
| ⭐ **信号交集/并集** | 多策略选股结果表 | ✓ 新增 API | 取同一日期同时被 N 个策略选中的股票，计算合集收益 |
| ⭐ **投票制** | 同上 | ✓ 新增 API | ≥ K/N 策略选中才纳入，可调 K 阈值 |
| ⭐ **环境轮动** | 市场环境分类 + 各策略环境表现 | ✓ 复用环境 API | 牛市用策略 A、熊市用策略 B 的组合收益 |
| 融合 vs 原始对比表 | 上述结果 | ✗ 前端计算 | 展示融合策略与各原始策略的全量指标差异 |

---

## 三、后端新增 API 设计

> **所有新 API 均为只读 GET 请求**，不写入数据库，不影响现有功能。
> **数据来源**: 仅从 MySQL + `cache/hist/` 读取，遵守 Fetch/Analysis/Web 分离原则。

### 3.1 API 清单

| # | 端点 | Handler 类 | 文件 | 说明 |
|---|------|-----------|------|------|
| 1 | `GET /quantia/api/verify/holding_period` | `HoldingPeriodAnalysisHandler` | `verifyOptimizeHandler.py` (新建) | 持仓天数扫描 |
| 2 | `GET /quantia/api/verify/signal_quality` | `SignalQualityHandler` | 同上 | 买入信号质量诊断 |
| 3 | `GET /quantia/api/verify/sl_tp_matrix` | `StopLossTakeProfitMatrixHandler` | 同上 | 止盈止损矩阵 |
| 4 | `GET /quantia/api/verify/market_regime` | `MarketRegimeHandler` | 同上 | 市场环境分类+适应性 |
| 5 | `GET /quantia/api/verify/signal_decay` | `SignalDecayHandler` | 同上 | 信号衰减趋势 |
| 6 | `GET /quantia/api/verify/exit_compare` | `ExitCompareHandler` | 同上 | 卖出方式对比 |
| 7 | `GET /quantia/api/verify/cost_sensitivity` | `CostSensitivityHandler` | 同上 | 交易成本敏感性 |
| 8 | `POST /quantia/api/verify/fusion` | `StrategyFusionHandler` | `verifyFusionHandler.py` (新建) | 策略融合回测 |
| 9 | `GET /quantia/api/verify/optimize_suggest` | `OptimizeSuggestHandler` | `verifyOptimizeHandler.py` | AI 优化建议 |

### 3.2 核心 API 详细设计

#### API 1: 持仓天数扫描

```
GET /quantia/api/verify/holding_period
    ?strategy_name=keep_increasing
    &start_date=2025-01-01
    &end_date=2025-12-31
    &holding_days=1,3,5,7,10,15,20,30,60   # 可选，默认全量

Response:
{
  "strategy_name": "keep_increasing",
  "period": "2025-01-01 ~ 2025-12-31",
  "total_signals": 856,
  "analysis": [
    {
      "holding_days": 5,
      "avg_return": 3.52,          // %
      "median_return": 2.85,       // %
      "win_rate": 62.3,            // %
      "return_std": 5.88,          // %
      "sharpe_approx": 2.35,       // avg_return / return_std * sqrt(252/holding_days)
      "sortino_approx": 3.12,      // avg_return / downside_std * sqrt(252/holding_days)
      "max_single_loss": -12.5,    // %
      "max_single_gain": 18.2,     // %
      "percentile_10": -3.2,       // % (P10)
      "percentile_90": 10.5,       // % (P90)
      "signal_count": 856
    },
    // ... 其他 holding_days
  ],
  "best_holding_days": 5,          // 夏普最高的持仓天数
  "best_sharpe": 2.35
}
```

**实现逻辑** (伪代码):
```python
# 从 cn_stock_backtest_data 读取 rate_N 列
# 对每个 holding_days:
#   rates = backtest_data[f'rate_{holding_days}'].dropna()
#   avg = rates.mean()
#   std = rates.std()
#   sharpe = avg / std * sqrt(252 / holding_days) if std > 0 else 0
#   downside_std = rates[rates < 0].std()
#   sortino = avg / downside_std * sqrt(252 / holding_days)
#   win_rate = (rates > 0).mean() * 100
```

**数据来源**: `cn_stock_backtest_data` 表，已有 rate_1..rate_100 字段。
**新增代码量**: ~80 行 Python。
**风险**: 无——只读查询现有数据。

---

#### API 2: 买入信号质量诊断

```
GET /quantia/api/verify/signal_quality
    ?strategy_name=keep_increasing
    &start_date=2025-01-01
    &end_date=2025-12-31
    &indicator=rsi_6          # 诊断哪个指标
    &holding_days=5           # 用哪个持仓期计算收益
    &buckets=0-30,30-50,50-70,70-100  # 可选，默认自动分桶

Response:
{
  "strategy_name": "keep_increasing",
  "indicator": "rsi_6",
  "holding_days": 5,
  "buckets": [
    {
      "range": "0-30",
      "label": "超卖区",
      "signal_count": 125,
      "pct": 14.6,
      "avg_return": 5.82,
      "win_rate": 72.8,
      "sharpe": 3.15,
      "max_drawdown": -6.5,
      "quality": "golden"      // golden / good / neutral / filter
    },
    // ...
  ],
  "recommendation": {
    "filter_ranges": ["70-100"],
    "expected_improvement": {
      "win_rate_delta": 5.9,
      "sharpe_delta": 0.53
    }
  }
}
```

**实现逻辑**:
```python
# 方案 A (优先): 从 cn_stock_trade_indicator_snapshot 读取信号时刻的指标值
#   JOIN cn_stock_backtest_data 获取 rate_N
#   按指标值分桶统计

# 方案 B (降级): 从 cn_stock_backtest_data 关联当日 indicators 表
#   需要 JOIN cn_stock_indicators 表 (date, code, rsi_6, ...)
#   按指标值分桶统计
```

**依赖**: `cn_stock_trade_indicator_snapshot` 表 (Phase 2) 或 `cn_stock_indicators` 表。
**新增代码量**: ~120 行 Python。
**风险**: 低——Phase 2 表可能数据不完整，需要降级到方案 B。

---

#### API 3: 止盈止损矩阵

```
GET /quantia/api/verify/sl_tp_matrix
    ?strategy_name=keep_increasing
    &start_date=2025-01-01
    &end_date=2025-12-31
    &sl_range=-2,-3,-5,-8,-10,0    # 止损%(0=不止损)
    &tp_range=3,5,8,10,15,0        # 止盈%(0=不止盈)
    &max_hold_days=20              # 最长持仓天数

Response:
{
  "strategy_name": "keep_increasing",
  "max_hold_days": 20,
  "matrix": [
    {
      "stop_loss": -5,
      "take_profit": 5,
      "sharpe": 2.68,
      "avg_return": 3.85,
      "win_rate": 65.2,
      "max_drawdown": -5.0,
      "avg_hold_days": 4.2,
      "trades_hit_sl": 128,
      "trades_hit_tp": 356,
      "trades_expired": 372
    },
    // ... 每个 (SL, TP) 组合一行
  ],
  "best_combo": {
    "stop_loss": -5,
    "take_profit": 5,
    "sharpe": 2.68
  }
}
```

**实现逻辑**:
```python
# 从 cn_stock_backtest_data 读取 rate_1..rate_max_hold_days
# 对每笔交易 (每行):
#   遍历 day=1..max_hold_days:
#     if rate_day <= stop_loss: 锁定收益=stop_loss, break
#     if rate_day >= take_profit: 锁定收益=take_profit, break
#     if day == max_hold_days: 锁定收益=rate_max_hold_days
# 对每个 (SL,TP) 组合计算: avg_return, win_rate, std, sharpe
```

**数据来源**: `cn_stock_backtest_data` 表 rate_1..rate_100。
**新增代码量**: ~150 行 Python (核心为向量化 NumPy 运算)。
**风险**: 低——纯计算，不写入数据，但需注意大数据量下的内存 (使用 chunk 读取)。

---

#### API 4: 市场环境分类

```
GET /quantia/api/verify/market_regime
    ?strategy_name=keep_increasing
    &start_date=2025-01-01
    &end_date=2025-12-31
    &benchmark=000300

Response:
{
  "regimes": [
    {"start": "2025-01-02", "end": "2025-02-15", "type": "bull", "days": 32},
    {"start": "2025-02-16", "end": "2025-03-10", "type": "bear", "days": 18},
    {"start": "2025-03-11", "end": "2025-03-28", "type": "sideways", "days": 15},
    // ...
  ],
  "strategy_by_regime": {
    "bull":     {"avg_return": 5.85, "sharpe": 3.52, "win_rate": 72.1, "signal_count": 320},
    "bear":     {"avg_return": -1.25, "sharpe": -0.55, "win_rate": 42.3, "signal_count": 180},
    "sideways": {"avg_return": 1.52, "sharpe": 1.28, "win_rate": 55.8, "signal_count": 356}
  },
  "classification_method": "MA20/MA60 crossover + ATR median"
}
```

**分类算法**:
```python
# 1. 加载基准指数日线 (load_benchmark_data)
# 2. 计算 MA20, MA60, ATR(20)
# 3. 分类规则:
#    - bull:     MA20 > MA60 且 ATR > median(ATR)
#    - bear:     MA20 < MA60 且 ATR > median(ATR)
#    - sideways: ATR <= median(ATR)
# 4. 对每个 regime 窗口，筛选该时段内的策略信号
# 5. 计算分环境指标
```

**数据来源**: `cache/hist/index/{code}.gzip.pickle` (基准) + `cn_stock_backtest` 表。
**新增代码量**: ~100 行 Python。
**风险**: 低——只读取缓存和数据库，不修改。

---

#### API 8: 策略融合

```
POST /quantia/api/verify/fusion
Body:
{
  "strategy_names": ["keep_increasing", "breakout_confirm", "trend_pullback"],
  "mode": "intersection",    // intersection / union / vote / rotation
  "vote_threshold": 2,       // 投票制阈值 (mode=vote 时有效)
  "start_date": "2025-01-01",
  "end_date": "2025-12-31",
  "holding_days": 5,
  "filters": {
    "rsi_6_max": 70,         // 可选过滤条件
    "vol_ratio_min": 1.0
  }
}

Response:
{
  "fusion_mode": "intersection",
  "fusion_result": {
    "avg_return": 4.85,
    "win_rate": 71.2,
    "sharpe": 3.25,
    "max_drawdown": -5.8,
    "calmar": 6.85,
    "signal_count": 186,
    "daily_signal_avg": 6.2
  },
  "individual_results": {
    "keep_increasing":  {"avg_return": 3.52, "win_rate": 62.3, "sharpe": 2.35, ...},
    "breakout_confirm": {"avg_return": 2.88, "win_rate": 58.1, "sharpe": 2.68, ...},
    "trend_pullback":   {"avg_return": 1.85, "win_rate": 55.8, "sharpe": 1.88, ...}
  },
  "improvement": {
    "sharpe_vs_best": "+21.3%",
    "drawdown_vs_best": "-29.3%"
  }
}
```

**实现逻辑**:
```python
# 1. 对每个策略，读取指定日期范围内的选股结果 (cn_stock_backtest_data)
# 2. 按日期分组:
#    - intersection: 取当日被所有策略同时选中的股票
#    - union: 取当日被任一策略选中的股票(去重)
#    - vote: 取当日被 >= vote_threshold 个策略选中的股票
#    - rotation: 根据市场环境选择对应策略的选股结果
# 3. 应用 filters (如 RSI < 70)
# 4. 计算融合结果的 rate_N 统计指标
```

**数据来源**: `cn_stock_backtest_data` 表 + `cn_stock_indicators` 表 (过滤条件)。
**新增代码量**: ~200 行 Python。
**风险**: 中——需要注意多策略 JOIN 的查询性能，添加日期范围索引。

---

## 四、前端页面设计（v3 修正版）

> 所有组件使用 Element Plus (`el-tabs`, `el-button`, `el-select`, `el-form` 等)，
> 图表使用 ECharts (按需引入)，与现有 `dashboard.vue` / `backtest-compare.vue` 保持一致。
> 不自定义侧边栏/布局——复用 `layout/index.vue` + `Sidebar.vue`。

### 4.1 新增文件清单

```
quantia/fontWeb/src/
├── views/verify/                          # 新增目录
│   ├── compare.vue                        # 多策略对比页
│   ├── optimize.vue                       # 买卖点优化页 (含 Sub-Tabs)
│   └── fusion.vue                         # 策略融合实验页
├── api/
│   └── verify.ts                          # 新增 API 文件
└── router/index.ts                        # 追加路由 (不修改现有路由)
```

### 4.2 路由配置 (追加至现有路由末尾)

```typescript
// 追加至 router/index.ts 的 routes 数组中
{
  path: '/verify',
  component: Layout,  // 复用现有 layout/index.vue
  redirect: '/verify/compare',
  meta: { title: '选股验证', icon: 'Compass' },
  children: [
    { path: 'compare', name: 'VerifyCompare',
      component: () => import('../views/verify/compare.vue'),
      meta: { title: '策略对比' } },
    { path: 'optimize', name: 'VerifyOptimize',
      component: () => import('../views/verify/optimize.vue'),
      meta: { title: '买卖点优化' } },
    { path: 'fusion', name: 'VerifyFusion',
      component: () => import('../views/verify/fusion.vue'),
      meta: { title: '策略融合' } },
  ]
}
```

> 侧边栏自动从路由 meta 生成菜单项（参见 `Sidebar.vue` 的 `menuList` computed），无需手动修改侧边栏。

### 4.3 各页面布局规范（v3 修正）

#### compare.vue — 多策略对比

```
┌─────────────────────────────────────────────────────┐
│ 工具栏: el-select(多选策略+分组) | el-radio-group    │
│         (周期切换) | el-select(基准) | el-button     │
├──────────────────────┬──────────────────────────────┤
│                      │ 综合评分排名列表              │
│   核心指标矩阵        │ + 雷达图缩略(inline 180px)   │
│   (原生 table,        │   占 1/3 宽度                │
│    .cmp-table 样式,   │                              │
│    占 2/3 宽度)       │                              │
├──────────────────────┴──────────────────────────────┤
│ 累计收益走势 (ECharts line, 双面板: 上=收益 下=回撤)  │
│ 图例: 各策略彩色线 + 基准虚线                         │
├─────────────────────────────────────────────────────┤
│ 信号衰减分析: el-tabs 内嵌 (月度胜率/收益/夏普趋势)   │
├─────────────────────────────────────────────────────┤
│ 市场环境适应性 (从 Tab 3 迁入): 牛/熊/震荡分环境表    │
└─────────────────────────────────────────────────────┘

颜色规则:
  - 收益类指标最优: 红色加粗(A股红=涨=好)
  - 风险类指标最优: 蓝色加粗(中性专业色，避免红绿歧义)
  - 综合评分末位: 灰底(不用红底)
```

#### optimize.vue — 买卖点优化

```
┌─────────────────────────────────────────────────────┐
│ 工具栏: el-select(策略) | el-radio-group(周期)       │
├─────────────────────────────────────────────────────┤
│ el-tabs (Sub-Tabs, type="card")                     │
│ ┌───────┬───────┬───────┬───────┬───────┐           │
│ │持仓优化│信号诊断│止盈止损│风险控制│样本外  │           │
│ └───────┴───────┴───────┴───────┴───────┘           │
├─────────────────────────────────────────────────────┤
│ [持仓优化]                                           │
│   持仓天数表(无"交易笔数"列, 表头显示"共N个信号")      │
│   每行追加迷你箱线图(P10/P25/P50/P75/P90)            │
│   ┌──────────────┬──────────────┐                   │
│   │持仓天数vs夏普 │持仓天数vs回撤 │ ← 拆为两个图,     │
│   │(ECharts line) │(ECharts bar  │   不用双Y轴        │
│   │               │ +散点叠加)   │                   │
│   └──────────────┴──────────────┘                   │
├─────────────────────────────────────────────────────┤
│ [信号诊断]                                           │
│   el-select(指标: RSI_6 / vol_ratio / MACD / ...)   │
│   单指标分桶表(4-5行, 不展示所有指标)                  │
│   ┌──────────────┬──────────────┐                   │
│   │散点图: 指标值 │条形图: 各区间 │                   │
│   │  vs 后续收益  │  信号数+胜率  │                   │
│   └──────────────┴──────────────┘                   │
├─────────────────────────────────────────────────────┤
│ [止盈止损]                                           │
│   ECharts heatmap (发散色阶: 蓝→白→红)               │
│   X=止盈% Y=止损% 色值=夏普比率                       │
│   点击单元格 → el-dialog 弹窗:                       │
│     该(SL,TP)组合的收益分布/胜率/回撤/盈亏比/交易笔数  │
├─────────────────────────────────────────────────────┤
│ [风险控制]                                           │
│   回撤水下曲线 + 恢复时间统计表                       │
│   交易成本敏感性(佣金 0.1%/0.2%/0.3% 对比)           │
├─────────────────────────────────────────────────────┤
│ [样本外]                                             │
│   自动 70/30 拆分, 分别展示训练集/测试集指标           │
│   过拟合警告标签: Sharpe 衰减 > 30% 则标红            │
├─────────────────────────────────────────────────────┤
│ ── AI 优化建议卡片 (固定底部, 不随 Sub-Tab 切换) ──   │
│ ┌────────────┬────────────┬────────────┐            │
│ │ 🎯买入过滤  │ 🛡️止盈止损  │ ⏱持仓周期   │            │
│ │   建议      │   建议      │   建议      │            │
│ └────────────┴────────────┴────────────┘            │
└─────────────────────────────────────────────────────┘
```

#### fusion.vue — 策略融合实验

```
┌─────────────────────────────────────────────────────┐
│ 配置器 (三列 el-row > el-col):                       │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐             │
│ │ 融合模式  │ │ 参与策略  │ │ 过滤条件  │  el-button  │
│ │el-radio   │ │el-checkbox│ │el-checkbox│  [运行]    │
│ │           │ │+权重slider│ │           │             │
│ └──────────┘ └──────────┘ └──────────┘             │
├─────────────────────────────────────────────────────┤
│ KPI 卡片 (el-row > el-col, 5列):                    │
│ 融合夏普 | 各策略夏普 | 提升幅度                      │
├─────────────────────────────────────────────────────┤
│ 对比表(.cmp-table): 融合 vs 各原始策略全量指标+提升%   │
├─────────────────────────────────────────────────────┤
│ 收益走势图 (ECharts):                                │
│ 融合策略粗线(3px) + 各策略细线(1px) + 基准虚线        │
│ 半透明区间 = 95% CI (Bootstrap 重抽样)               │
└─────────────────────────────────────────────────────┘
```

### 4.4 ECharts 图表规范

| 图表 | 类型 | 关键配置 | 所在页面 |
|------|------|----------|----------|
| 累计收益走势 | `line` (双面板) | `grid: [{height:'55%'},{top:'75%',height:'20%'}]`, `dataZoom`, `tooltip.trigger:'axis'` | compare |
| 雷达图缩略 | `radar` | `radius: 80`, `indicator` 6 维, 半透明 `areaStyle` | compare |
| 信号衰减月度 | `line` + `bar` | 双 Y 轴: 左=胜率/收益(line), 右=信号数(bar) | compare |
| 持仓天数 vs 夏普 | `line` | `markPoint` 标注峰值, `markLine` 标注当前默认持仓期 | optimize |
| 持仓天数 vs 回撤 | `bar` + `scatter` | `bar`=平均回撤, `scatter`=个别回撤散点(半透明) | optimize |
| 指标 vs 收益散点 | `scatter` | `X=指标值, Y=rate_5`, 回归线 `markLine`, 颜色=盈亏 | optimize |
| 止盈止损矩阵 | `heatmap` | `visualMap` 发散色阶(蓝→白→红), X=TP%, Y=SL% | optimize |
| 回撤水下曲线 | `line` (areaStyle) | `areaStyle.color: 'rgba(255,77,79,0.3)'`, Top-5 `markArea` | optimize |
| 融合收益走势 | `line` | 粗线+半透明 `areaStyle` CI 区间, `legend.selected` 可切换 | fusion |

### 4.5 颜色系统规范

```scss
// 收益类指标 (涨跌方向) — A 股红涨绿跌
$rate-positive: #cf1322;    // 红, 正收益 / 涨
$rate-negative: #389e0d;    // 绿, 负收益 / 跌

// 风险类指标 (好坏方向) — 避免红绿歧义, 用蓝灰
$risk-good: #1890ff;        // 蓝, 低回撤/低波动 = 好
$risk-bad: #8c8c8c;         // 灰, 高回撤/高波动 = 差

// 评分/等级
$rank-1: #cf1322;           // 金
$rank-2: #d46b08;           // 银
$rank-3: #096dd9;           // 铜
$rank-last: #bfbfbf;        // 末位 (灰, 不用红)

// 优化建议
$suggest-positive: #f6ffed;  // 浅绿底, 正面改进
$suggest-negative: #fff7e6;  // 浅橙底, 待优化
$suggest-neutral: #f5f5f5;   // 灰底, 无明显变化

// 热力图色阶 (发散)
$heatmap-low: #3060cf;      // 蓝, 低夏普
$heatmap-mid: #ffffff;      // 白, 中
$heatmap-high: #cf1322;     // 红, 高夏普
```

---

## 五、实现阶段划分

### Phase 1: 基础数据 API (后端, 预计 3 个 Sprint)

| 步骤 | 任务 | 文件 | 依赖 |
|------|------|------|------|
| 1.1 | 新建 `verifyOptimizeHandler.py` 骨架 | `quantia/web/verifyOptimizeHandler.py` | 无 |
| 1.2 | 实现 `HoldingPeriodAnalysisHandler` | 同上 | `cn_stock_backtest_data` 表 |
| 1.3 | 实现 `SignalQualityHandler` | 同上 | `cn_stock_trade_indicator_snapshot` 或 `cn_stock_indicators` |
| 1.4 | 实现 `StopLossTakeProfitMatrixHandler` | 同上 | `cn_stock_backtest_data` 表 |
| 1.5 | 实现 `MarketRegimeHandler` | 同上 | `cache/hist/index/` + `cn_stock_backtest` |
| 1.6 | 实现 `SignalDecayHandler` | 同上 | `cn_stock_backtest` 按月分组 |
| 1.7 | 实现 `CostSensitivityHandler` | 同上 | `cn_stock_backtest_data` |
| 1.8 | 在 `web_service.py` 注册路由 | `quantia/web/web_service.py` | 1.1-1.7 |
| 1.9 | 单元测试 | `tests/test_verify_optimize_handler.py` | 1.1-1.8 |

### Phase 2: 策略融合 API (后端)

| 步骤 | 任务 | 文件 | 依赖 |
|------|------|------|------|
| 2.1 | 新建 `verifyFusionHandler.py` | `quantia/web/verifyFusionHandler.py` | 无 |
| 2.2 | 实现信号交集/并集/投票逻辑 | 同上 | `cn_stock_backtest_data` 多策略 JOIN |
| 2.3 | 实现环境轮动逻辑 | 同上 | Phase 1 的 MarketRegimeHandler |
| 2.4 | 实现 `OptimizeSuggestHandler` | `verifyOptimizeHandler.py` | Phase 1 全部 |
| 2.5 | 在 `web_service.py` 注册路由 | `quantia/web/web_service.py` | 2.1-2.4 |
| 2.6 | 单元测试 | `tests/test_verify_fusion_handler.py` | 2.1-2.5 |

### Phase 3: 前端页面 (前端)

| 步骤 | 任务 | 文件 | 依赖 |
|------|------|------|------|
| 3.1 | 新建 `api/verify.ts` | `quantia/fontWeb/src/api/verify.ts` | Phase 1+2 |
| 3.2 | 新建 `views/verify/compare.vue` | `quantia/fontWeb/src/views/verify/compare.vue` | 3.1 |
| 3.3 | 新建 `views/verify/optimize.vue` | `quantia/fontWeb/src/views/verify/optimize.vue` | 3.1 |
| 3.4 | 新建 `views/verify/fusion.vue` | `quantia/fontWeb/src/views/verify/fusion.vue` | 3.1 |
| 3.5 | 追加路由配置 | `quantia/fontWeb/src/router/index.ts` | 3.2-3.4 |
| 3.6 | 追加侧边栏导航项 | 现有 layout 组件 | 3.5 |
| 3.7 | 前端单元测试 | `quantia/fontWeb/src/__tests__/verify/` | 3.2-3.4 |

### Phase 4: 集成测试 & 优化

| 步骤 | 任务 | 说明 |
|------|------|------|
| 4.1 | 端到端测试 | 确保所有新 API 在有数据/无数据/边界情况下正常工作 |
| 4.2 | 性能测试 | 止盈止损矩阵大数据量下的耗时 (<5s for 1000 交易 × 36 组合) |
| 4.3 | 构建 + 部署 | `npm run build` → dist → `quantia/web/static/` |
| 4.4 | 回归测试 | 运行 `pytest -q` 确保所有现有 1700+ 测试通过 |

---

## 六、安全保障 — 不影响现有功能

### 6.1 文件影响矩阵

| 文件 | 操作 | 影响范围 | 风险 |
|------|------|----------|------|
| `quantia/web/verifyOptimizeHandler.py` | **新建** | 无 | 零 |
| `quantia/web/verifyFusionHandler.py` | **新建** | 无 | 零 |
| `quantia/web/web_service.py` | **追加路由** | 仅在 URL 列表末尾添加，不修改现有路由 | 极低 |
| `quantia/fontWeb/src/api/verify.ts` | **新建** | 无 | 零 |
| `quantia/fontWeb/src/views/verify/*.vue` | **新建** | 无 | 零 |
| `quantia/fontWeb/src/router/index.ts` | **追加路由** | 新增 `/verify/*` 路由，不修改现有路由 | 极低 |
| `tests/test_verify_*.py` | **新建** | 无 | 零 |

### 6.2 不修改的文件 (保护清单)

以下文件 **绝对不修改**:

- `quantia/core/backtest/portfolio_engine.py` — 回测引擎核心
- `quantia/core/backtest/risk_metrics.py` — 风险指标计算
- `quantia/core/backtest/rate_stats.py` — 收益率计算
- `quantia/core/backtest/data_feed.py` — 数据加载
- `quantia/core/strategy/*.py` — 策略定义
- `quantia/core/indicator/*.py` — 指标计算
- `quantia/core/tablestructure.py` — 表结构定义
- `quantia/web/backtestHandler.py` — 现有回测接口
- `quantia/web/portfolioBacktestHandler.py` — 现有组合回测接口
- `quantia/web/backtestDashboardHandler.py` — 现有看板接口
- `quantia/lib/database.py` — 数据库工具层
- 所有现有测试文件

### 6.3 数据库安全

- **不新增表**: 所有新 API 仅查询现有表 (`cn_stock_backtest`, `cn_stock_backtest_data`, `cn_stock_indicators`, `cn_stock_trade_indicator_snapshot`)
- **不修改表结构**: 不执行 ALTER TABLE
- **只读操作**: 所有新 API 均为 SELECT 查询，无 INSERT/UPDATE/DELETE
- **查询优化**: 使用 `LIMIT` + 日期范围 WHERE 条件避免全表扫描
- **内存安全**: 大数据量查询使用 `chunksize` 分批读取 (遵守 `_DB_INSERT_CHUNKSIZE = 500` 惯例)

### 6.4 防止 Bug 的措施

| 措施 | 说明 |
|------|------|
| **输入校验** | 所有 Handler 的 `get_argument()` 做白名单校验 (strategy_name 必须在 14 个内置策略中) |
| **SQL 注入防护** | 使用 SQLAlchemy ORM / 参数化查询，不拼接 SQL 字符串 |
| **除零保护** | 所有除法运算前检查分母 ≠ 0，std = 0 时返回 sharpe = 0 |
| **NaN/Inf 防护** | 使用 `np.isfinite()` 过滤，遵守 MySQL NaN/Inf 防护规则 |
| **空数据处理** | 查询无数据时返回 `{"analysis": [], "message": "该时间范围内无策略信号"}` |
| **超时保护** | 止盈止损矩阵等计算密集型 API 添加 `asyncio.wait_for(timeout=30)` |
| **单元测试覆盖** | 每个新 Handler 至少 5 个测试用例 (正常/空数据/边界/非法参数/大数据量) |
| **回归测试** | 每次提交前运行 `pytest -q` 确保 1700+ 现有测试全部通过 |

### 6.5 前端安全

| 措施 | 说明 |
|------|------|
| **路由懒加载** | 所有新页面使用 `() => import(...)` 动态导入，不增加首屏包体积 |
| **独立 API 文件** | `verify.ts` 独立于现有 `strategy.ts`，不修改现有 API 配置 |
| **ECharts 按需引入** | 仅在 verify 页面内引入 radar/heatmap/line 组件 |
| **错误边界** | 每个图表组件包裹 `v-if="data.length"` + loading/empty 状态 |

---

## 七、关键技术方案

### 7.1 持仓天数夏普比率的正确计算

v2 设计中 "持仓天数 vs 夏普" 的计算方式需要修正:

```python
# ❌ 错误: 直接用 avg_rate / std
sharpe = avg_rate / std  # 无意义，因为持仓期不同

# ✅ 正确: 年化夏普比率
# 对于持仓 N 天的策略:
#   年化因子 = sqrt(252 / N)  (假设一年 252 个交易日)
#   期间无风险利率 = 1.5% * N / 252
#   sharpe = (avg_rate - rf_period) / std * annualization_factor
annualization_factor = math.sqrt(252 / holding_days)
rf_period = 0.015 * holding_days / 252
sharpe = (avg_rate - rf_period) / std * annualization_factor
```

### 7.2 止盈止损矩阵的向量化计算

避免 Python 循环，使用 NumPy 向量化:

```python
import numpy as np

def compute_sl_tp_matrix(rates_matrix, sl_levels, tp_levels):
    """
    rates_matrix: shape (N_trades, max_hold_days), 每行是一笔交易的逐日收益
    sl_levels: [-2, -3, -5, -8, -10, None]
    tp_levels: [3, 5, 8, 10, 15, None]
    返回: dict[(sl, tp)] → {sharpe, win_rate, avg_return, max_dd}
    """
    results = {}
    for sl in sl_levels:
        for tp in tp_levels:
            # 向量化: 对每笔交易找第一个触发 SL/TP 的日期
            if sl is not None:
                sl_hit = rates_matrix <= sl  # bool matrix
            else:
                sl_hit = np.zeros_like(rates_matrix, dtype=bool)
            if tp is not None:
                tp_hit = rates_matrix >= tp
            else:
                tp_hit = np.zeros_like(rates_matrix, dtype=bool)

            # 找第一个触发日
            any_hit = sl_hit | tp_hit
            # ... (argmax 逻辑)

            final_rates = ...  # 每笔交易的最终收益
            results[(sl, tp)] = {
                'sharpe': _calc_sharpe(final_rates),
                'win_rate': (final_rates > 0).mean() * 100,
                'avg_return': final_rates.mean(),
            }
    return results
```

### 7.3 市场环境分类算法

```python
def classify_market_regime(benchmark_df):
    """
    输入: 基准指数日线 DataFrame (date, close)
    输出: DataFrame 增加 'regime' 列 ('bull', 'bear', 'sideways')
    """
    df = benchmark_df.copy()
    df['ma20'] = df['close'].rolling(20).mean()
    df['ma60'] = df['close'].rolling(60).mean()
    df['atr20'] = calculate_atr(df, period=20)
    atr_median = df['atr20'].median()

    conditions = [
        (df['ma20'] > df['ma60']) & (df['atr20'] > atr_median),  # 上涨趋势
        (df['ma20'] < df['ma60']) & (df['atr20'] > atr_median),  # 下跌趋势
    ]
    choices = ['bull', 'bear']
    df['regime'] = np.select(conditions, choices, default='sideways')
    return df
```

### 7.4 策略融合信号合并

```python
def merge_strategy_signals(strategy_signals, mode, vote_threshold=2):
    """
    strategy_signals: dict[strategy_name → set of (date, stock_code)]
    mode: 'intersection' / 'union' / 'vote'
    返回: set of (date, stock_code) — 融合后的信号集合
    """
    all_signals = list(strategy_signals.values())

    if mode == 'intersection':
        return set.intersection(*all_signals) if all_signals else set()
    elif mode == 'union':
        return set.union(*all_signals) if all_signals else set()
    elif mode == 'vote':
        from collections import Counter
        counter = Counter()
        for signals in all_signals:
            counter.update(signals)
        return {sig for sig, count in counter.items() if count >= vote_threshold}
```

---

## 八、测试计划

### 8.1 后端测试

| 测试文件 | 测试用例 | 覆盖模块 |
|----------|---------|----------|
| `test_verify_optimize_handler.py` | | |
| | `test_holding_period_normal` | 正常持仓天数扫描 |
| | `test_holding_period_no_data` | 无数据时返回空 |
| | `test_holding_period_boundary` | 边界: 只有 1 笔交易 |
| | `test_signal_quality_rsi` | RSI 分桶诊断 |
| | `test_signal_quality_macd` | MACD 状态诊断 |
| | `test_signal_quality_invalid_indicator` | 非法指标名返回 400 |
| | `test_sl_tp_matrix_normal` | 正常矩阵计算 |
| | `test_sl_tp_matrix_no_sl` | 不止损场景 |
| | `test_sl_tp_matrix_large_data` | 1000+ 交易量性能 (<5s) |
| | `test_market_regime_classification` | 市场分类正确性 |
| | `test_market_regime_no_benchmark` | 基准不存在返回错误 |
| | `test_signal_decay_monthly` | 月度衰减统计 |
| | `test_cost_sensitivity` | 不同成本参数 |
| | `test_optimize_suggest` | AI 建议生成 |
| `test_verify_fusion_handler.py` | | |
| | `test_fusion_intersection` | 信号交集 |
| | `test_fusion_union` | 信号并集 |
| | `test_fusion_vote` | 投票制 (threshold=2/3) |
| | `test_fusion_rotation` | 环境轮动 |
| | `test_fusion_with_filters` | 带过滤条件的融合 |
| | `test_fusion_single_strategy` | 只有 1 个策略时 = 原策略 |
| | `test_fusion_invalid_strategy` | 非法策略名返回 400 |

### 8.2 前端测试

| 测试文件 | 测试用例 |
|----------|---------|
| `verify.test.ts` | |
| | API 函数导出正确 |
| | 请求参数序列化正确 |
| `compare.test.ts` | |
| | 策略选择器多选 + 移除 |
| | 指标矩阵排序切换 |
| | 雷达图数据归一化 |
| `optimize.test.ts` | |
| | 持仓天数表排序高亮 |
| | 热力图点击弹出详情 |
| | 空数据 empty 状态 |
| `fusion.test.ts` | |
| | 融合模式切换 |
| | 权重输入校验 (和=100) |
| | 过滤条件联动 |

### 8.3 回归测试

```bash
# 每次提交前必须运行:
pytest -q                          # 全部 1700+ 测试
cd quantia/fontWeb && npm test     # 前端单元测试
cd quantia/fontWeb && npm run build # 类型检查 + 构建
```

---

## 九、风险评估与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| `cn_stock_trade_indicator_snapshot` 表无数据 | 中 | 信号质量诊断功能不可用 | 提供降级方案 B (JOIN indicators 表) |
| 止盈止损矩阵计算超时 | 低 | 用户体验差 | 限制最大查询范围 3 个月 + 添加 loading 动画 |
| 多策略 JOIN 查询慢 | 中 | 融合功能响应慢 | 添加 `(date, strategy_name)` 复合索引 |
| 新路由与现有路由冲突 | 极低 | 页面 404 | `/verify/*` 命名空间独立，不与 `/backtest/*` 冲突 |
| ECharts 包体积增加 | 低 | 首屏变慢 | 按需引入 + 路由级懒加载 |
| 过拟合风险 (用户调参) | 高 | 用户在生产中亏钱 | 样本外验证模块 + 过拟合警告标签 |

---

## 十、验收标准

| # | 验收项 | 标准 |
|---|--------|------|
| 1 | 现有功能无回归 | `pytest -q` 全部通过 (1700+ tests) |
| 2 | 前端构建成功 | `npm run build` 无 error |
| 3 | 新 API 响应时间 | 所有 API < 5s (1000 条交易数据量) |
| 4 | 持仓天数扫描 | 能正确展示 1-60 日的夏普/收益/胜率，标注最优天数 |
| 5 | 止盈止损矩阵 | 6×6 矩阵正确计算，色阶与数值一致 |
| 6 | 信号质量诊断 | 至少支持 RSI/vol_ratio/MACD 三个指标的分桶分析 |
| 7 | 市场环境分类 | 能区分牛/熊/震荡，分环境展示策略表现 |
| 8 | 策略融合 | 4 种模式 (交集/并集/投票/轮动) 均可运行并返回结果 |
| 9 | 样本外验证 | 展示训练集/测试集的指标差异，标注过拟合风险 |
| 10 | 空数据处理 | 无策略信号时展示友好提示，不崩溃 |

---

## 十一、v4 多维融合设计 (新增)

> 对应原型: `strategy-optimize-v4.html`

### 11.1 设计目标

在 v3 的策略融合基础上，从单一"技术策略信号交叉"升级为 **五维融合分析**:

| 维度 | 默认权重 | 数据来源 | 可用因子 |
|------|---------|---------|---------|
| 技术策略 | 30% | `cn_stock_strategy_*` (14 表) | 均线多头/突破确认/趋势回调 等 13+1(GPT) |
| 基本面 | 25% | `cn_stock_selection` (PE/PB/ROE/ROIC 等) | 35+ 指标 |
| 资金流 | 20% | `cn_stock_fund_flow` + `cn_stock_selection` | 当日/3日/5日/10日主力净流入, DDX, 沪深股通 |
| 市场情绪 | 15% | `cn_stock_selection` + `cn_stock_lhb/blocktrade` | 机构持股/股东户数/龙虎榜/大宗交易/质押比例 |
| 自定义 | 10% | `cn_stock_custom_indicator` + `cn_stock_strategy_code` | 用户自定义策略/Phase 9 复合指标 |

### 11.2 前端页面结构

Tab "多维融合" 包含 4 个子面板:

1. **融合配置器** — 维度权重雷达图 + 每维度因子选择器(复选框)
2. **因子贡献分析** — 水平柱状图，展示每个因子对整体夏普的边际贡献
3. **A/B 对比验证** — 9 组实验表格，对比加减因子的效果
4. **信号重叠热图** — 策略间信号交集可视化

### 11.3 新增 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/quantia/api/verify/fusion_multi` | 多维融合回测 (含维度权重) |
| GET | `/quantia/api/verify/factor_contribution` | 因子贡献分析 (逐因子剔除法) |
| GET | `/quantia/api/verify/dimension_overlap` | 维度间信号重叠统计 |

### 11.4 数据可行性说明

| 数据源 | 是否历史存储 | JOIN 方式 | 注意事项 |
|--------|------------|----------|---------|
| `cn_stock_strategy_*` | ✅ 按日累积 | `(date, code)` | — |
| `cn_stock_indicators` | ✅ 按日累积 | `(date, code)` | — |
| `cn_stock_fund_flow` | ✅ 按日累积 (每日 DELETE+INSERT 当日) | `(date, code)` | 当日数据盘中更新 |
| `cn_stock_selection` | ⚠️ 需确认历史深度 | `(date, code)` | 部分字段可能仅最近数据可靠 |
| `cn_stock_financial` | ✅ 按季度报告 | `(code, report_date)` 需 window-JOIN | 取最近一期财报 |
| `cn_stock_lhb` | ✅ 按日累积 | `(date, code)` | 非每日有数据 |

---

## 十二、v5 因子实验室设计 (新增)

> 对应原型: `strategy-optimize-v5.html`

### 12.1 设计目标

让用户**交互式**自由组合多维因子，实时查看回测结果，并通过 AI 辅助优化。

### 12.2 三栏布局

| 区域 | 宽度 | 内容 |
|------|------|------|
| 左栏: 因子面板 | 260px | 可搜索、按分类折叠的因子列表，拖拽/点击添加 |
| 中栏: 活跃因子 | 自适应 | 已添加因子的参数编辑、权重调节、开关、排序 |
| 右栏: 结果面板 | 340px | 6 KPI 卡片 + 收益曲线 + 因子贡献排名 + 对比表 + 操作日志 + AI 面板 |

### 12.3 因子类型与配置

| 因子类型 | 参数 | 示例 |
|----------|------|------|
| **策略信号** (二值) | 权重 | 均线多头: 在/不在 → weight=30% |
| **连续指标** | 条件运算符 + 阈值 + 权重 | RSI(6) < 70, weight=15% |
| **区间指标** | 上下界 + 权重 | PE: 0 < x ≤ 30, weight=12% |

### 12.4 融合规则

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| **全部满足 (AND)** | 所有启用因子条件同时满足 | 高精选、低信号量 |
| **满足N项 (投票)** | 至少 N 个因子满足，N 可调 | 平衡信号量与质量 |
| **加权评分 (Score)** | 各因子标准化后加权求和，取 Top-K | 连续排名，充分利用权重 |
| **条件树 (Pipeline)** | 先用硬条件过滤，再在剩余集上评分排序 | 先排雷后选优 |

### 12.5 新增 API

| 方法 | 路径 | 请求体/参数 | 说明 |
|------|------|------------|------|
| POST | `/quantia/api/factor_lab/run` | `{factors: [{type, name, table, column, operator, value, weight, enabled}], fusion_mode, holding_days, period}` | 运行因子组合回测 |
| POST | `/quantia/api/factor_lab/factor_impact` | `{factors, target_factor_index}` | 单因子边际贡献 (全组合 vs 剔除该因子) |
| GET | `/quantia/api/factor_lab/presets` | — | 获取预设模板列表 |
| POST | `/quantia/api/factor_lab/save` | `{name, factors, fusion_mode, ...}` | 保存因子配置方案 |
| POST | `/quantia/api/factor_lab/export_code` | `{factors, fusion_mode}` | 导出为 Backtrader 策略 Python 代码 |
| POST | `/quantia/api/factor_lab/ai_suggest` | `{factors, metrics, question?}` | AI 分析当前因子组合并给出优化建议 |

### 12.6 因子标准化算法

混合二值信号与连续指标时需统一量纲:

```python
def normalize_factor(values, factor_type):
    """
    策略信号: 0/1 → 直接作为得分
    连续指标 (方向=越大越好): min-max 归一化到 [0, 1]
    连续指标 (方向=越小越好): 1 - min-max
    区间指标: 满足区间=1, 不满足=0 (硬过滤模式) 或 高斯衰减 (评分模式)
    """
    if factor_type == 'signal':
        return values.astype(float)
    elif factor_type == 'continuous_asc':
        vmin, vmax = values.quantile(0.02), values.quantile(0.98)
        return ((values - vmin) / (vmax - vmin)).clip(0, 1)
    elif factor_type == 'continuous_desc':
        vmin, vmax = values.quantile(0.02), values.quantile(0.98)
        return (1 - (values - vmin) / (vmax - vmin)).clip(0, 1)
    elif factor_type == 'range':
        # 评分模式: 在范围内=1, 范围外按距离衰减
        return ...
```

### 12.7 查询模式 — 策略因子的 LEFT JOIN

策略表 (`cn_stock_strategy_*`) 仅包含被选中的股票行（稀疏）。要计算"某股票 NOT 被策略选中"，需从 **全量宇宙表** LEFT JOIN:

```sql
-- cn_stock_spot 提供每日全市场 ~5000 股票
SELECT
    spot.date, spot.code,
    CASE WHEN strat.code IS NULL THEN 0 ELSE 1 END AS selected,
    strat.rate_5, strat.rate_10
FROM cn_stock_spot spot
LEFT JOIN cn_stock_strategy_keep_increasing strat
    ON spot.date = strat.date AND spot.code = strat.code
WHERE spot.date BETWEEN '2025-01-01' AND '2025-03-31'
```

> **注意**: 已选中股票有 rate_N 数据，未选中股票的 rate 为 NULL（无交易信号，不参与收益计算）。

### 12.8 性能优化策略

| 场景 | 方案 |
|------|------|
| 多表 JOIN (5000+ 股 × 60 日 × 5 表) | 分步查询 + pandas merge，避免 MySQL 5 表 JOIN |
| 全量宇宙 + 策略因子 | 先查 cn_stock_spot 获取 universe，再 LEFT JOIN 各策略表 |
| 重复运行 (调参后再跑) | 缓存基础数据 (indicators/selection/fund_flow)，仅重新计算因子条件 |
| 因子贡献 (N 次剔除实验) | 批量计算，复用已有信号集的子集操作 |
| 前端实时交互 | debounce 300ms + 取消前一次请求 |

### 12.9 安全规则

| 规则 | 说明 |
|------|------|
| 因子上限 | 最多 15 个活跃因子，避免过拟合 |
| 权重自动归一化 | 前端切换融合规则为 Score 模式时，自动将权重归一化到 100% |
| 信号稀疏警告 | 日均信号 < 3 时在结果面板显示橙色警告 |
| 样本外提示 | 当统计周期 > 3 月时，自动划分 70/30 训练/测试集并标注过拟合指标差 |
| 导出代码审查 | 生成的 Python 代码带注释标明因子来源和参数，方便人工审阅 |

### 12.10 预设模板

| 模板名 | 包含因子 | 融合模式 |
|--------|---------|---------|
| 空白 | — | AND |
| 技术+基本面 (推荐) | 均线多头 + 突破确认 + 趋势回调 + RSI<70 + PE 0~30 + ROE≥10% + 主力净流入>0 + 3日净流入>0 | Score |
| 纯技术多因子 | 均线多头 + 突破确认 + 海龟 + RSI<50 + MACD>0 + KDJ金叉 | AND |
| 价值投资 | PE 0~20 + PB<3 + ROE≥15% + 毛利率≥30% + 负债率<50% + 股息率≥2% | AND |
| 资金驱动 | 3日/5日/10日主力净流入>0 + DDX>0 + 沪深股通净买入>0 | 投票(≥3) |
| 全维度融合 | 均线多头 + RSI<70 + PE 0~30 + ROE≥10% + 主力净流入>0 + 机构持股≥5% | Pipeline |

---

## 十三、v5 审核补充 — 已发现问题与修正 (新增)

### 13.1 v5 原型已修复的问题

| # | 问题 | 修正 |
|---|------|------|
| P1 | RSI 条件下拉有两个重复 `<` 选项 | 修正为 `<, ≤, >, ≥, 介于` |
| P2 | 权重之和 135% 超过 100%，无警告 | 添加权重超限警告条 + "一键归一化"按钮 |
| P3 | 缺少移动端断点 (<960px / <768px) | 添加 960px 单列堆叠 + 768px 隐藏侧边栏 |
| P4 | 因子分类全部展开，80+ 指标列表过长 | 改为折叠分组，默认折叠"技术指标"和"市场情绪"大类 |
| P5 | 信号过少时无警告 | 添加信号稀疏警告 (日均 < 3 时红色提示) |
| P6 | 因子数量无限制提示 | 添加"已添加 8 个 · 建议不超过 15 个以避免过拟合"提示 |
| P7 | 搜索时折叠的分类不会自动展开 | 搜索时自动展开匹配分类 |

### 13.2 仍需在开发阶段解决的问题

| # | 问题 | 优先级 | 解决方案 |
|---|------|--------|---------|
| D1 | **运行回测无 loading 状态** | P0 | 点击后按钮禁用 + 旋转图标 + KPI 区 skeleton 加载态 |
| D2 | **首次进入无结果空状态** | P0 | 右栏首次显示空状态占位 "请添加因子并运行回测" |
| D3 | **保存/加载方案 UI 缺失** | P1 | "保存方案"弹窗 + 预设模板区增加"我的模板"列表 |
| D4 | **因子间相关性警告** | P1 | 添加高度相关因子时弹出提示 (如同时加 3日/5日净流入) |
| D5 | **Undo/Redo** | P2 | 基于操作日志实现一步撤销 (因子配置快照栈) |
| D6 | **条件树 Pipeline 可视化** | P2 | Pipeline 模式下中栏显示流程图: 硬过滤 → 评分 → Top-K |
| D7 | ~~cn_stock_selection 历史数据深度验证~~ | ✅ 已验证 | **已确认**该表按 `(date, code)` 主键累积历史数据（每日 DELETE+INSERT 当日行，历史行保留）。基本面因子**可用于**历史回测。`cn_stock_indicators` 同理。 |
| D8 | **导出代码可读性** | P2 | 生成代码需带因子来源注释、参数说明、数据要求文档 |

### 13.3 风险补充

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| ~~cn_stock_selection 仅存最新快照~~ | ✅ 已排除 | — | 已验证: 按 `(date, code)` 主键累积，基本面因子可历史回测 |
| 因子组合爆炸 (15 因子 × 参数) | 中 | 用户过拟合 | 强制样本外测试 + 训练/测试集指标差 > 20% 时红色警告 |
| AI 建议误导 | 中 | 用户盲信 AI 建议亏钱 | AI 建议附带"仅供参考"声明 + 显示置信度 |
| 导出代码无法直接运行 | 低 | 用户体验差 | 生成代码附带 requirements + 数据加载模板 |

---

## 十四、完整 API 汇总 (v5 更新)

### 14.1 验证优化 API (verifyOptimizeHandler.py)

| # | 方法 | 路径 | 说明 |
|---|------|------|------|
| 1 | GET | `/quantia/api/verify/holding_period` | 持仓天数扫描 |
| 2 | GET | `/quantia/api/verify/signal_quality` | 信号质量诊断 (RSI/vol/MACD 分桶) |
| 3 | GET | `/quantia/api/verify/sl_tp_matrix` | 止盈止损矩阵 |
| 4 | GET | `/quantia/api/verify/market_regime` | 市场环境分类 |
| 5 | GET | `/quantia/api/verify/signal_decay` | 信号衰减分析 |
| 6 | GET | `/quantia/api/verify/exit_compare` | 退出策略对比 |
| 7 | GET | `/quantia/api/verify/cost_sensitivity` | 交易成本敏感性 |
| 8 | GET | `/quantia/api/verify/optimize_suggest` | AI 优化建议 |

### 14.2 融合 API (verifyFusionHandler.py)

| # | 方法 | 路径 | 说明 |
|---|------|------|------|
| 9 | POST | `/quantia/api/verify/fusion` | 简单策略融合 (v3) |
| 10 | POST | `/quantia/api/verify/fusion_multi` | 多维融合 (v4) |
| 11 | GET | `/quantia/api/verify/factor_contribution` | 因子贡献分析 |
| 12 | GET | `/quantia/api/verify/dimension_overlap` | 维度信号重叠 |

### 14.3 因子实验室 API (factorLabHandler.py — 新增)

| # | 方法 | 路径 | 说明 |
|---|------|------|------|
| 13 | POST | `/quantia/api/factor_lab/run` | 运行因子组合回测 |
| 14 | POST | `/quantia/api/factor_lab/factor_impact` | 单因子边际贡献 |
| 15 | GET | `/quantia/api/factor_lab/presets` | 预设模板列表 |
| 16 | POST | `/quantia/api/factor_lab/save` | 保存因子配置方案 |
| 17 | POST | `/quantia/api/factor_lab/export_code` | 导出 Backtrader 代码 |
| 18 | POST | `/quantia/api/factor_lab/ai_suggest` | AI 优化建议 |

---

## 十五、完整前端文件清单 (v5 更新)

| 文件 | 路由 | 说明 |
|------|------|------|
| `views/verify/compare.vue` | `/verify/compare` | 多策略对比 (v3) |
| `views/verify/optimize.vue` | `/verify/optimize` | 买卖点优化 (v3) |
| `views/verify/fusion.vue` | `/verify/fusion` | 多维融合配置 (v4) |
| `views/verify/factorLab.vue` | `/verify/factor-lab` | 因子实验室 (v5) |
| `api/verify.ts` | — | 验证 API 封装 |
| `api/factorLab.ts` | — | 因子实验室 API 封装 |
| `components/verify/FactorCard.vue` | — | 可复用因子配置卡片组件 |
| `components/verify/AiSuggestPanel.vue` | — | AI 建议面板 (复用 AiChatDrawer 模式) |

---

## 十六、开发阶段更新 (v5 更新)

### 原 4 阶段保持不变 (v3 scope)，新增:

| 阶段 | 内容 | 依赖 |
|------|------|------|
| Phase 5 | 多维融合 API + 前端 (v4 scope) | Phase 1-2 完成 |
| Phase 6 | 因子实验室 API + 前端 (v5 scope) | Phase 1 完成 |
| Phase 7 | AI 优化集成 (因子建议/模型选择) | Phase 6 完成 + AI 模块可用 |
| Phase 8 | 导出策略代码 + 预设模板管理 | Phase 6 完成 |

### 验收标准补充

| # | 验收项 | 标准 |
|---|--------|------|
| 11 | 因子实验室核心流程 | 添加 3+ 因子 → 运行回测 → 查看 KPI → 因子贡献排名，全流程 < 10s |
| 12 | 因子标准化 | 混合二值信号+连续指标时评分归一化正确 |
| 13 | 权重归一化 | Score 模式下权重自动/手动归一化到 100% |
| 14 | AI 建议 | AI 能给出具体、可操作的因子调整建议 |
| 15 | 导出代码 | 导出的 Python 代码可直接在 Backtrader 框架中运行 |
| 16 | 预设模板 | 6 个预设模板均可一键加载并运行 |
| 17 | 信号稀疏警告 | 日均信号 < 3 时显示醒目警告 |

# 选股验证中心 — 开发计划

> **版本**: v6.0
> **日期**: 2026-05-16
> **状态**: Phase 1-6 已实现 ✅ | Phase 7-9 规划中
> **目标**: 构建策略对比优化中心 + 多维融合 + 因子实验室，直观对比数据，辅助优化策略买卖点、提升收益率、降低回撤、提高夏普比
> **原则**: 增量开发、不影响现有功能、不引入新 bug
> **UI 参考**: [mockup-interactive.html](mockup-interactive.html) (v6 综合版，可直接浏览器打开)

---

## 一、当前实现总览 (Phase 1-6 已完成 ✅)

### 1.1 系统架构 (已落地)

```
选股验证中心 (路由: /verify, 侧边栏已注册)
├── /verify/compare        ✅  多策略对比（指标矩阵 + 雷达图 + 累计收益 + 信号衰减 + 市场环境）
├── /verify/optimize       ✅  买卖点优化（4 Sub-Tabs: 持仓/信号诊断/止盈止损/风险控制）
├── /verify/fusion         ✅  策略融合实验（交集/并集/投票/轮动 4 模式）
└── /verify/factor-lab     ✅  因子实验室（三栏布局: 因子库/参数配置/实时结果）
```

### 1.2 后端 API (14 个端点, 3 个 Handler 文件)

| # | 方法 | 路径 | Handler | 文件 | 状态 |
|---|------|------|---------|------|------|
| 1 | GET | `/api/verify/holding_period` | `HoldingPeriodAnalysisHandler` | `verifyOptimizeHandler.py` | ✅ |
| 2 | GET | `/api/verify/signal_quality` | `SignalQualityHandler` | 同上 | ✅ |
| 3 | GET | `/api/verify/sl_tp_matrix` | `StopLossTakeProfitMatrixHandler` | 同上 | ✅ |
| 4 | GET | `/api/verify/market_regime` | `MarketRegimeHandler` | 同上 | ✅ |
| 5 | GET | `/api/verify/signal_decay` | `SignalDecayHandler` | 同上 | ✅ |
| 6 | GET | `/api/verify/cost_sensitivity` | `CostSensitivityHandler` | 同上 | ✅ |
| 7 | GET | `/api/verify/exit_compare` | `ExitCompareHandler` | 同上 | ✅ |
| 8 | GET | `/api/verify/return_series` | `SignalReturnSeriesHandler` | 同上 | ✅ |
| 9 | POST | `/api/verify/fusion` | `StrategyFusionHandler` | `verifyFusionHandler.py` | ✅ |
| 10 | GET | `/api/verify/optimize_suggest` | `OptimizeSuggestHandler` | 同上 | ✅ |
| 11 | GET | `/api/factor_lab/factors` | `FactorCatalogHandler` | `factorLabHandler.py` | ✅ |
| 12 | POST | `/api/factor_lab/run` | `FactorLabRunHandler` | 同上 | ✅ |
| 13 | GET/POST | `/api/factor_lab/factor_impact` | `FactorImpactHandler` | 同上 | ✅ |
| 14 | GET | `/api/factor_lab/presets` | `FactorPresetsHandler` | 同上 | ✅ |

### 1.3 前端文件 (已实现)

| 文件 | 用途 |
|------|------|
| `views/verify/compare.vue` | 多策略对比页: 指标矩阵 + 雷达图 + 累计收益 + 回撤 + 信号衰减 + 市场环境 |
| `views/verify/optimize.vue` | 买卖点优化: 持仓扫描(箱线图) + 信号诊断(散点) + 止盈止损(热力图) + 风险控制 |
| `views/verify/fusion.vue` | 策略融合: 交集/并集/投票/轮动, KPI 对比, 累计收益图 |
| `views/verify/factorLab.vue` | 因子实验室: 三栏布局, 因子分类树 + 参数编辑 + 结果面板, ≤15 因子, 3 融合模式 |
| `api/verify.ts` | 10 个 API 函数 + TypeScript 接口 |
| `api/factorLab.ts` | 3 个 API 函数 + 类型定义 |
| `router/index.ts` | `/verify/*` 路由组 (lines 388-420) |

### 1.4 测试覆盖

| 测试文件 | 覆盖 |
|----------|------|
| `tests/test_verify_optimize_handler.py` | 持仓/信号质量/止盈止损/市场环境/衰减/成本 |
| `tests/test_verify_fusion_handler.py` | 融合 4 模式 + 边界 + 错误参数 |
| `tests/test_factor_lab_handler.py` | 因子库/运行/贡献/预设 |

---

## 二、历史设计审查总结 (v2→v5 已修复)

以下是 v2-v5 迭代中发现并已解决的设计问题，供后续维护参考：

### 2.1 布局问题 (已修复)

| 问题 | 解决方案 |
|------|----------|
| Tab 2 内容过载 (>3 屏滚动) | 拆为 4 Sub-Tabs: 持仓优化/信号诊断/止盈止损/风险控制 |
| Tab 2 和 Tab 3 职责重叠 | Tab 3 取消, 止盈止损移入 optimize 子面板; 市场环境移入 compare 底部 |
| 雷达图+矩阵信息重复 | 矩阵=主, 雷达图=辅(缩小至综合评分区, 不独占半屏) |
| 策略选择器缺搜索分组 | 改为 el-select 多选 + 分组(技术/量价/形态/AI/自定义) |
| 双 Y 轴误读风险 | 拆为两个并排图 + tooltip 联动 |

### 2.2 可视化改进 (已修复)

| 问题 | 解决方案 |
|------|----------|
| 止盈止损用黄色单色阶 | 改为发散色阶 蓝→白→红 |
| 面积图暗示连续关系 | 改为柱状图+散点叠加 |
| 信号诊断展示 3 指标 12 行 | 改为指标下拉 + 单指标分桶 + 散点图 |
| 缺少分布可视化 | 每行增加迷你箱线图 P10/P25/P50/P75/P90 |
| 融合走势无置信区间 | 添加 Bootstrap 95% CI 半透明区间 |

### 2.3 颜色语义 (已确定规范)

```scss
// A 股收益方向: 红涨绿跌
$rate-positive: #cf1322;    // 红 = 正收益/涨
$rate-negative: #389e0d;    // 绿 = 负收益/跌

// 风险质量方向: 蓝好灰差 (避免红绿歧义)
$risk-good: #1890ff;        // 蓝 = 低回撤/低波动 = 好
$risk-bad: #8c8c8c;         // 灰 = 差

// 排名: 红→橙→蓝→灰
$rank-1: #cf1322;  $rank-2: #d46b08;  $rank-3: #096dd9;  $rank-last: #bfbfbf;
```

### 2.4 数据可行性 (已验证/已解决)

| 原始担忧 | 实际情况 |
|----------|----------|
| cn_stock_selection 仅最新快照? | ✅ 已确认按 (date,code) 累积, 可历史回测 |
| 买入指标快照缺失? | ✅ 使用 JOIN cn_stock_indicators 降级方案 |
| 市场环境分类无实现? | ✅ MarketRegimeHandler 已实现 MA20/MA60+ATR |
| 夏普计算方式模糊? | ✅ 年化公式: `(avg - rf) / std * sqrt(252/N)` |
| 融合性能风险? | ✅ 分步查询+pandas merge, 避免多表 JOIN |

---

## 三、v6 交互原型设计规范

> 参考文件: [mockup-interactive.html](mockup-interactive.html) — 可直接浏览器打开

### 3.1 四页面结构

| Tab | 路由 | 核心交互 | 数据维度 |
|-----|------|---------|---------|
| ⚖️ 策略对比 | /verify/compare | Chip 多选策略 + 周期/基准切换 → 矩阵+雷达+曲线 | 收益/风险/风险调整/交易质量 4 类 13 指标 |
| 🎯 买卖点优化 | /verify/optimize | 单策略选择 → 4 Sub-Tab 深度分析 | 持仓/信号/止盈止损/风控 |
| 🧬 多维融合 | /verify/fusion | 五维配置器(技术/基本面/资金流/情绪/自定义) + 4 模式 | Shapley贡献 + A/B验证 + 信号热图 |
| 🔬 因子实验室 | /verify/factor-lab | 三栏: 因子库/参数编辑/实时结果 + AI助手 | 42 因子 × 6 预设 × 3 融合模式 |

### 3.2 多维融合配置器 (v4 新增, 已实现基础版)

五个维度:

| 维度 | 默认权重 | 数据源 |
|------|---------|--------|
| 技术策略 | 30% | `cn_stock_strategy_*` (14 表) |
| 基本面 | 25% | `cn_stock_selection` (PE/PB/ROE...) |
| 资金流 | 20% | `cn_stock_fund_flow` + `cn_stock_selection` |
| 市场情绪 | 15% | `cn_stock_selection` (机构/股东户数...) |
| 自定义 | 10% | `cn_stock_custom_indicator` + 用户策略 |

融合模式: 加权评分 (默认) | 信号投票 | 条件树 | 环境轮动

### 3.3 因子实验室核心交互

三栏布局:
- **左栏 (260px)**: 因子库面板 — 搜索 + 分类折叠 + 快速预设 + 拖拽/点击添加
- **中栏 (自适应)**: 活跃因子卡片 — 参数编辑 + 权重滑块 + 开关 + 排序 + 归一化警告
- **右栏 (340px)**: 实时结果 — 6 KPI + 收益曲线 + 因子贡献 + 对比表 + 操作日志 + AI面板

因子类型:
| 类型 | 配置参数 | 示例 |
|------|---------|------|
| 策略信号 (二值) | 权重 | 均线多头: 在/不在, weight=30% |
| 连续指标 | 条件+阈值+权重 | RSI(6) < 30, weight=15% |
| 区间指标 | 上下界+权重 | PE: 0 < x ≤ 30, weight=12% |

### 3.4 交互逻辑清单 (v6 原型已实现)

| 交互 | 说明 | 实现方式 |
|------|------|---------|
| 主 Tab 切换 | 4 页面联动侧边栏高亮 + header 面包屑 | `swMain()` |
| Sub-Tab (optimize) | 4 子面板 (实现) / 5 子面板 (原型含样本外验证→Phase 8) | `swSub()` |
| Sub-Tab (fusion) | 4 子面板: 配置器/因子贡献/A-B/热图 | `swFusion()` |
| 因子分类折叠 | 点击展开/收起 + 搜索自动展开匹配项 | `toggleCat()` + `filterFactors()` |
| 因子卡片展开 | 点击 head 展开/收起参数编辑区 | `toggleFactorBody()` |
| 维度开关 | ON/OFF 切换 + 灰化视觉反馈 | `toggleDim()` + `.dim-off` class |
| 预设模板 | 一键加载预设因子组合 | `applyPreset()` |
| 融合模式单选 | 4 模式互斥高亮 | radio + label style |
| 策略对比结果 | 点击"开始对比"后显示 | compare-result toggle |
| Radio 周期切换 | 互斥选中样式 | `.radio-g.a` class |
| 响应式 | 1200px 侧边栏收缩; 960px 三栏→双栏; 768px 单栏 | CSS media queries |

---

## 四、Phase 7-9 未来开发计划

### Phase 7: 因子实验室增强 (P1 高优先)

| # | 功能 | 说明 | 新增 API |
|---|------|------|---------|
| 7.1 | **保存/加载方案** | 用户保存因子配置到 DB, 加载历史方案 | `POST /api/factor_lab/save` + `GET /api/factor_lab/my_configs` |
| 7.2 | **导出 Python 代码** | 导出因子组合为 Backtrader 策略代码 | `POST /api/factor_lab/export_code` |
| 7.3 | **AI 优化建议** | 分析当前因子组合, 给出增减因子建议 | `POST /api/factor_lab/ai_suggest` |
| 7.4 | **因子相关性警告** | 高度相关因子(如 3日/5日净流入)添加时弹出提示 | 前端计算 (Pearson > 0.8) |
| 7.5 | **拖拽排序** | 中栏因子卡片支持拖拽重排 | 前端 (vuedraggable / sortablejs) |
| 7.6 | **Undo/Redo** | 基于操作日志的一步撤销 | 前端状态快照栈 |

### Phase 8: 多维融合深化 (P1)

| # | 功能 | 说明 | 新增 API |
|---|------|------|---------|
| 8.1 | **多维融合 API** | 含维度权重的回测 (v4 扩展) | `POST /api/verify/fusion_multi` |
| 8.2 | **因子贡献分析** | 逐因子剔除法 Shapley 近似 | `GET /api/verify/factor_contribution` |
| 8.3 | **信号重叠可视化** | 日历热力图 + 行业 Treemap | `GET /api/verify/dimension_overlap` |
| 8.4 | **环境轮动自动切配** | 牛/熊/震荡自动选择最优权重配比 | 复用 MarketRegimeHandler |
| 8.5 | **条件树 Pipeline** | 先硬过滤 → 再评分排序 → Top-K | 融合模式扩展 |
| 8.6 | **样本外验证集成** | 70/30 拆分 + 过拟合风险标注 (≥30% 衰减红色警告) | `GET /api/verify/oos_validation` |

### Phase 9: 进阶分析 (P2)

| # | 功能 | 说明 |
|---|------|------|
| 9.1 | **策略参数敏感性** | N 日突破参数 10→30 对收益影响的曲面图 |
| 9.2 | **持仓集中度/相关性** | 策略选股的行业集中度 + 个股相关性矩阵 |
| 9.3 | **数据质量诊断** | 停牌/涨跌停/缺失比例, 幸存者偏差检测 |
| 9.4 | **WebSocket 进度** | 长时间融合回测实时进度反馈 |
| 9.5 | **信号衰减预警** | Alpha 衰减 > 20% 自动通知 (接入 notification 模块) |

---

## 五、关键技术方案 (已实现参考)

### 5.1 持仓天数夏普比率计算

```python
# 年化夏普比率 (已实现于 verifyOptimizeHandler.py)
annualization_factor = math.sqrt(252 / holding_days)
rf_period = 0.015 * holding_days / 252  # 年化无风险 1.5%
sharpe = (avg_rate - rf_period) / std * annualization_factor
```

### 5.2 止盈止损矩阵向量化

```python
# NumPy 向量化 (已实现于 verifyOptimizeHandler.py)
# rates_matrix: shape (N_trades, max_hold_days)
for sl in sl_levels:
    for tp in tp_levels:
        sl_hit = rates_matrix <= sl  # bool matrix
        tp_hit = rates_matrix >= tp
        # argmax 找第一个触发日 → 锁定收益 → 计算 sharpe/win_rate
```

### 5.3 市场环境分类

```python
# MA20/MA60 交叉 + ATR 分类 (已实现于 verifyOptimizeHandler.py)
# bull:     MA20 > MA60 且 ATR > median
# bear:     MA20 < MA60 且 ATR > median
# sideways: ATR <= median
```

### 5.4 因子标准化算法 (factorLabHandler.py)

```python
# 策略信号: 0/1 直接作为得分
# 连续指标 (越大越好): min-max 归一化 [0,1], 用 P2/P98 截断
# 连续指标 (越小越好): 1 - min-max
# 区间指标: 满足=1, 不满足=0 (AND 模式) 或高斯衰减 (Score 模式)
```

### 5.5 策略因子 LEFT JOIN

```sql
-- 策略表为稀疏(仅选中股票), 需 LEFT JOIN 全量宇宙
SELECT spot.date, spot.code,
       CASE WHEN strat.code IS NULL THEN 0 ELSE 1 END AS selected
FROM cn_stock_spot spot
LEFT JOIN cn_stock_strategy_keep_increasing strat
    ON spot.date = strat.date AND spot.code = strat.code
WHERE spot.date BETWEEN ? AND ?
```

---

## 六、安全规范 (不变, 持续遵守)

### 6.1 不修改的文件 (保护清单)

- `quantia/core/backtest/portfolio_engine.py` — 回测引擎核心
- `quantia/core/backtest/risk_metrics.py` — 风险指标计算
- `quantia/core/backtest/data_feed.py` — 数据加载
- `quantia/core/strategy/*.py` — 策略定义
- `quantia/core/indicator/*.py` — 指标计算
- `quantia/core/tablestructure.py` — 表结构定义
- `quantia/web/backtestHandler.py` — 现有回测接口
- `quantia/lib/database.py` — 数据库工具层

### 6.2 API 安全规则

| 规则 | 说明 |
|------|------|
| 只读查询 | 所有 verify/factor_lab API 仅 SELECT, 无 INSERT/UPDATE/DELETE |
| 输入校验 | strategy_name 白名单; 日期范围限制; 因子数≤15 |
| SQL 注入防护 | SQLAlchemy 参数化查询, 不拼接 SQL |
| NaN/Inf 防护 | `np.isfinite()` 过滤 + JSON 序列化前清洗 |
| 除零保护 | std = 0 → sharpe = 0 |
| 超时保护 | 计算密集 API 添加 30s 超时 |
| 内存安全 | 大数据量 chunk 读取 |

### 6.3 因子实验室安全规则

| 规则 | 说明 |
|------|------|
| 因子上限 15 | 避免过拟合 + 计算爆炸 |
| 权重自动归一化 | Score 模式下权重和必须=100% |
| 信号稀疏警告 | 日均信号 < 3 → 橙色提示 |
| 样本外验证 | 周期 > 3月 自动 70/30 拆分 |
| AI 建议免责 | 附带"仅供参考"声明 + 置信度 |

---

## 七、验收标准

| # | 验收项 | 标准 | 状态 |
|---|--------|------|------|
| 1 | 现有功能无回归 | `pytest -q` 全部通过 (1700+ tests) | ✅ |
| 2 | 前端构建成功 | `npm run build` 无 error | ✅ |
| 3 | 新 API 响应时间 | 所有 API < 5s (1000 条数据量) | ✅ |
| 4 | 持仓天数扫描 | 展示 1-60 日夏普/收益/胜率, 标注最优 | ✅ |
| 5 | 止盈止损矩阵 | 6×6 矩阵正确计算, 发散色阶 | ✅ |
| 6 | 信号质量诊断 | 支持 RSI/vol/MACD 三指标分桶 | ✅ |
| 7 | 市场环境分类 | 牛/熊/震荡分环境展示 | ✅ |
| 8 | 策略融合 4 模式 | 交集/并集/投票/轮动均可运行 | ✅ |
| 9 | 因子实验室核心 | 42 因子 + 6 预设 + 3 融合模式 + KPI 实时刷新 | ✅ |
| 10 | 空数据处理 | 无信号时友好提示, 不崩溃 | ✅ |
| 11 | 保存/加载方案 | 因子配置持久化 | ⬜ Phase 7 |
| 12 | 导出代码 | 生成可运行的 Backtrader 策略 | ⬜ Phase 7 |
| 13 | AI 优化建议 | 基于当前因子分析给出建议 | ⬜ Phase 7 |
| 14 | 多维融合回测 | 五维权重配置 + 环境轮动 | ⬜ Phase 8 |
| 15 | 样本外验证 | 过拟合检测 + 训练/测试集指标差 | ⬜ Phase 8 |

---

## 八、风险评估

| 风险 | 概率 | 影响 | 缓解 | 状态 |
|------|------|------|------|------|
| ~~cn_stock_selection 仅最新快照~~ | — | — | ✅ 已验证: 按日累积 | 已排除 |
| ~~止盈止损计算超时~~ | — | — | ✅ NumPy 向量化 + chunk | 已解决 |
| 因子组合爆炸 (15 因子 × 参数) | 中 | 用户过拟合 | 强制样本外 + 衰减警告 | Phase 8 |
| AI 建议误导 | 中 | 用户盲信亏钱 | 免责声明 + 置信度标注 | Phase 7 |
| 多维融合查询慢 | 中 | 用户体验差 | 分步查询 + 缓存 + debounce | Phase 8 |
| 导出代码无法运行 | 低 | 体验差 | 附带 requirements + 数据模板 | Phase 7 |

---

## 九、附录: 文件清单

### 后端 (已存在)
```
quantia/web/verifyOptimizeHandler.py    — 8 个 Handler
quantia/web/verifyFusionHandler.py      — 2 个 Handler
quantia/web/factorLabHandler.py         — 4 个 Handler
quantia/web/web_service.py              — 路由注册 (lines 200-215)
```

### 前端 (已存在)
```
quantia/fontWeb/src/views/verify/compare.vue
quantia/fontWeb/src/views/verify/optimize.vue
quantia/fontWeb/src/views/verify/fusion.vue
quantia/fontWeb/src/views/verify/factorLab.vue
quantia/fontWeb/src/api/verify.ts
quantia/fontWeb/src/api/factorLab.ts
quantia/fontWeb/src/router/index.ts     — /verify/* 路由组
```

### 测试 (已存在)
```
tests/test_verify_optimize_handler.py
tests/test_verify_fusion_handler.py
tests/test_factor_lab_handler.py
```

### 文档/原型
```
document/ChooseVerify/REFACTOR_PLAN.md  — 本文件
document/ChooseVerify/mockup-interactive.html  — v6 综合版交互原型
document/ChooseVerify/strategy-optimize-v2.html ~ v5.html  — 历史版本 (存档)
```


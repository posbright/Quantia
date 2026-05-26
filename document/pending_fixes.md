# 待修复 Bug 与未实现功能登记

> 记录在进行中的开发里发现、但暂未修复的 bug 或未实现的功能。完成后请把对应条目移到底部"已修复"或直接删除。

---

## 1. 待修复 Bug

_暂无。_

---

## 2. 未实现功能（按文档登记）

_所有 M3 移动适配条目（PR-09 / PR-10 / PR-05-extra / PR-07-extra）已全部完成，详见 §3 已修复归档。_

### [Feat-M3-PR07-extra] paper-trading 拆分（已完成）

M3 仅做样式与弹窗宽度适配，未拆分 128KB 单文件。已完成全部 3 个子组件抽出，主文件 128KB → 94.5KB（−27%）。

- [x] 2026-05-26 抽出 `TradeDecisionDialog.vue`（交易决策依据弹窗）
- [x] 2026-05-26 抽出 `CreatePaperDialog.vue`（新建模拟盘弹窗）
- [x] 2026-05-26 抽出 `StockDialog.vue` 子组件（K 线弹窗 + ECharts 渲染逻辑；3 个 chart refs + render/dispose/indicator snapshot/trade markers/ciOverlay 全部内聚）；父组件 `openPaperStock` 仅设置 `selectedStock + visible`，子组件 watch 加载 3 周期 K 线并渲染

---

## 3. 已修复（归档）

### 2026-05-26 — M3 移动适配补完（PR-09 / PR-10 / PR-05-extra）

- ✅ **[Feat-M3-PR09]** `indicator/index.vue`：DPR ≤2.5 + `useDirtyRect`；断点感知 chartHeight（xs280/sm380/md520/lg680，副图/CI 子面板 +100）；副指标选择器移动端切 `<el-segmented>`；dataZoom inside 已存在 + 移动端默认 `start≈40` 展示最近段；横屏 landscape (`max-width:991.98 & orientation:landscape & max-height:540`) 隐藏 top-bar/toolbar；轴字号 `axisFs=9/10`、`volAxisFs=8/9`；所有 grid/title/divider 用 `sc()` 因子缩放。
- ✅ **[Feat-M3-PR10]** `algo/backtest-detail.vue`：3 处 ECharts grid `left/right` 响应式；`@media (max-width:767.98)` 添加 detail-header wrap、jq-table 12/6 padding、tabs compact、chart-box 280、stock-chart-box 360/460、stock-summary 2 列、decision-summary 紧凑。
- ✅ **[Feat-M3-PR10]** `algo/edit.vue`：`@media (max-width:991.98)` editor-main 切纵向（code 45dvh / right ≥55dvh）、toolbar 纵排、metrics 2 列、nav-chart 220、log-panel 160；`@media (max-width:575.98)` date-editor 130 / input-number 110。
- ✅ **[Feat-M3-PR10]** `algo/backtest-compare.vue`：ECharts grid 响应式、code-panels minmax 320 → 1col、cmp-table 11px + 首列 sticky。
- ✅ **[Feat-M3-PR05-extra]** `stock/StockData.vue`：`v-if="!isMobile"` 走 el-table，`v-else` 渲染卡片列表；`mobileCardColumns` 优先 indicator + rate 取前 6；卡片含代码/名称/字段网格/关注/分析/看板/时序/明细按钮；移动端 CSS（`.card-list`/`.stock-card`/`.card-body grid-cols:2`/`.card-actions` 等）已补全。

构建：`npm run build`（vue-tsc + vite build）通过，仅剩 dynamic-import 分包警告（与本次无关）。

### 2026-05-26 — Bug-001 & backtest-compare 行编辑器折叠

- ✅ **[Bug-001]** `home/index.vue::loadStrategy`：用 `Array.isArray()` 守卫每个回退源（`items` / `data` / `rows` / `data.items` / `data.strategies` / `strategies`），并用 `String(items.length)` 避免 `undefined.toString()`。修复进入 `/home` 时的 TypeError 控制台告警。
- ✅ **[Feat-M3-PR10]** `algo/backtest-compare.vue`：`isMobile` 分支用 `<el-collapse>` 包裹行参数（开始/结束/资金/基准），桁额位默认收起，title 显示当前日期区间；桌面端保留原 `<el-form :inline>`。新增 mobile-only `.code-params-collapse` / `.code-params-form-mobile` 样式。

### 2026-05-26 — M4 / PR-11 弹窗与表单统一

- ✅ **[Feat-M4-PR11]** 全项目 `el-dialog width` 统一改为 CSS `min(<desktop>px, 92vw)`：`strategy/StrategyConfig.vue` `800px`、`verify/factorLab.vue` `420px`/`680px`、`verify/optimize.vue` `400px`、`settings/{ai-config,im-commands,users,im-operator,token-usage,notification}.vue` `400~780`、`algo/agent-manager.vue` `640px`、`stock/report-history.vue`（`70%` → `min(900px, 92vw)`）、`paper-trading/index.vue` 模拟盘对比（`90%` → `min(1200px, 92vw)`）、`paper-trading/components/{CreatePaperDialog,TradeDecisionDialog}.vue`（消除 isMobile 三元条件 width，保留 isMobile 仅控 `:top`）。
- ✅ **[Feat-M4-PR11]** `el-popover :width` 改 CSS clamp：`verify/compare.vue` `:width="280"` → `width="min(280px, 90vw)"`；`paper-trading/index.vue` `:width="320"` → `width="min(320px, 90vw)"`。
- ✅ **[Feat-M4-PR11]** `login.vue` / `register.vue` 移动端补 `@media (max-width:575.98px)`：卡片宽 `calc(100vw - 32px)`、`padding: 24px 20px`、保留桌面 360/420px。

构建：`npm run build` 通过；vitest 87/88（2 个失败为预先存在的 `tests/utils/index.test.ts` 导入缺失与 `factorLab.test.ts` 老 stub，与本轮无关）。

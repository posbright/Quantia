# 待修复 Bug 与未实现功能登记

> 记录在进行中的开发里发现、但暂未修复的 bug 或未实现的功能。完成后请把对应条目移到底部"已修复"或直接删除。

---

## 1. 待修复 Bug

### [Bug-001] home/index.vue `loadStrategy` TypeError
- **发现于**：2026-05-26 M3 审查
- **现象**：进入首页 `/home` 时控制台告警
  ```
  [home] loadStrategy failed TypeError: Cannot read properties of undefined (reading 'toString')
      at loadStrategy (quantia/fontWeb/src/views/home/index.vue:207-262 区间)
  ```
- **复现**：访问 `http://localhost:3000/home`，打开控制台。
- **代码位置**：[quantia/fontWeb/src/views/home/index.vue](quantia/fontWeb/src/views/home/index.vue#L252-L266) `async function loadStrategy()`
  ```ts
  const r: any = await getStrategyCodeList({})
  const items: any[] = r?.items || r?.data || r?.rows || []
  kpi.value = items.length.toString()
  ```
- **根因推测**：
  - `getStrategyCodeList({})` 返回的 `r` 不是数组也没有 `items/data/rows` 字段时，回退到 `[]` 应该 OK
  - 但若 `r?.items` 是非数组对象（例如 `{ count: 0 }`），`items.length` 是 `undefined`，`undefined.toString()` 抛错
- **修复建议**：
  ```ts
  const items: any[] = Array.isArray(r?.items) ? r.items
    : Array.isArray(r?.data) ? r.data
    : Array.isArray(r?.rows) ? r.rows
    : []
  kpi.value = String(items.length)
  ```
- **影响**：首页"我的策略"卡片始终显示 `--`，但 UI 不崩溃；仅控制台告警。
- **优先级**：低（不阻断功能）
- **关联**：与 M3 移动适配无关，M3 仅修改了该文件 `<style>` 块。

---

## 2. 未实现功能（按文档登记）

### [Feat-M3-PR09] indicator/index.vue 未完成项（v.s. mobile_adaptation_plan.md §阶段 3 PR-09）

本次 M3 仅完成「ECharts grid 左右内边距按断点切换」+「visualViewport resize」+「断点变化重渲」+「移动端 top-bar/toolbar/sub-tab 紧凑样式」。以下仍未实现：

- [ ] **ECharts DPR 与脏矩形**：`echarts.init(el, null, { devicePixelRatio: Math.min(window.devicePixelRatio, 2.5), useDirtyRect: true })`
- [ ] **断点感知的图表高度**：当前固定 680 / 780px。计划：`xs 280 / sm 380 / md 520 / lg 680`，启用副指标时统一 +100
- [ ] **移动端副指标选择器**：MACD/KDJ/RSI/WR/多空趋势 改 `<el-segmented>` 单选（当前是 flex bar）
- [ ] **dataZoom inside 触屏支持**：增加 `{ type: 'inside' }` 让手指可在主图内捏合 / 拖动；桌面保留 slider
- [ ] **移动端默认 zoom 起点**：手机端 `dataZoom.start: 70`（展示最近 30% 数据），桌面端 0
- [ ] **横屏专属布局**：`@include landscape-phone` 隐藏 Sidebar/Navbar/info 行，图表 `height: calc(100dvh - 40px)`
- [ ] **轴标签字号自适应**：`xs:10 / sm:11 / md:12 / lg:12`，避免跟随用户系统缩放

### [Feat-M3-PR10] 回测详情 / Compare / Edit 移动适配（v.s. §阶段 3 PR-10）

M3 完全未触及以下页面：

- [ ] `algo/backtest-detail.vue` (66KB)：
  - 4 个 tab 在 `<md` 改 `<el-segmented>` 或 collapse
  - 内部 ECharts `grid.left/right` 响应式（`left: isMobile? 36 : 58`）
  - 持仓表迁移到 `ResponsiveDataView` 卡片视图
- [ ] `algo/edit.vue` (34KB)：
  - 分屏布局在 `<md` 改 tab 切换（代码 / 回测结果）
  - 工具栏 `<el-button-group>` 移动端竖排
- [ ] `algo/backtest-compare.vue` (35KB)：
  - 行编辑器（每行 4 输入）移动端改 `<el-collapse>` 折叠

### [Feat-M3-PR05-extra] StockData.vue 卡片视图

M3 已完成工具栏 / 分页移动适配，但 plan §PR-05 计划的「`<md` 改卡片视图（每只股票一张卡片）」未做：

- [ ] 接入 `ResponsiveDataView` 组件（或新建），`isMobile ? 'card' : 'table'`
- [ ] 卡片字段：代码 / 名称 / 最新价 / 涨跌幅 / 关注按钮 / 分析按钮

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

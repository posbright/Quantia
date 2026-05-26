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

### 2026-05-26 — M4 / PR-11b AI 聊天抽屉移动适配

- ✅ **[Feat-M4-PR11b]** `components/AiChatDrawer.vue`：移动端 `@media (max-width:768px)` 块扩展：
  - `.chat-history` 用 dvh-based 高度（`min-height: calc(100dvh - 380px); max-height: calc(100dvh - 320px)`）撑满抽屉空间，避免移动端只显 320~420px 固定高度
  - `.failure-block pre` / `.code-preview` / `.tb-preview` / `.stream-preview` `max-height: calc(100dvh - 280px)`，长代码可一屏读完
  - `.ai-pickers` 内 AiModelPicker 整行铺开两个 select `flex:1 1 0`；AiAgentPicker（裸 el-select）`flex:1 1 100%` 单独一行
  - `.ai-actions` 按钮 `flex:1 1 calc(50%-4px)` 两列布局，不再溢出
- 现状已具备桌面/移动两端的 drawer size（55%/100%）、`pre-wrap + word-break: break-word` 防代码块溢出、`scrollChatToBottom` 自动追底，无需额外改动。

### 2026-05-26 — M4 / PR-11b 收尾：底部 sheet picker + useVirtualKeyboard

- ✅ **[Feat-M4-PR11b]** 新增 `composables/useVirtualKeyboard.ts`：基于 `visualViewport` 检测软键盘弹起，暴露 `visible` / `heightShift`，同时写入 `--kb-shift` 到 `<html>` 供样式侧 `calc(... - var(--kb-shift, 0px))` 使用。
- ✅ **[Feat-M4-PR11b]** `components/AiAgentPicker.vue` 改造为响应式双形态：桌面端原 `el-select`；`useResponsive().isMobile` 为 true 时改为触发按钮 + `el-drawer direction="btt" size="60%"` 底部 sheet 列表（含 `内置` 标签、当前项 `Check` 高亮）。
- ✅ **[Feat-M4-PR11b]** `components/AiModelPicker.vue` 同样改造：移动端用一个触发按钮显示 `provider / model` 摘要 → `el-drawer direction="btt" size="70%"` sheet，内部分两段 `Provider` / `模型`，点 provider 自动重置 model 到该 provider 的 default_model。
- ✅ **[Feat-M4-PR11b]** `views/login.vue` / `views/register.vue` 接入 `useVirtualKeyboard`：键盘弹起时 `document.activeElement.scrollIntoView({ block: 'center' })`，修复 Android 默认 `pan` 模式下提交按钮被键盘压住的问题。
- 不做：`useBodyScrollLock`（`el-drawer` 默认 `lock-scroll`，无背景穿透）。

构建：`npm run build` 通过；vitest 87/88（同上 2 个预先存在失败）。

### 2026-05-26 — M5 / PR-12 性能 + 文档收尾

- ✅ **[Docs-PR12]** `README.md` 新增"移动端 / 平板使用"章节：支持浏览器矩阵（iOS 16+ / Android 11+ / X5 TBS ≥ 6013）、6 个响应式断点表、移动端体验要点、`localStorage.quantia.forceDesktop` / `QUANTIA_FORCE_DESKTOP` 强制桌面端开关。
- ✅ **[Feat-PR12]** `vite.config.ts` manualChunks 二调：新增 `vendor-markdown`（markdown-it），把 `@vueuse/core` / `web-vitals` 也归入 `vendor-utils`，避免 markdown-it 等不常用库污染 initial chunk。
- ✅ **[Feat-PR12]** 接入 [web-vitals](https://github.com/GoogleChrome/web-vitals)：新增 `src/lib/webVitals.ts` 采集 LCP / CLS / INP / FCP / TTFB，生产环境通过 `navigator.sendBeacon` 异步上报到 `/quantia/api/metric/web_vitals`（后端可后续实现），开发环境只 `console.debug`，`<html data-disable-vitals>` 可强制关闭。
- ✅ **[Feat-PR12]** 接入 [size-limit](https://github.com/ai/size-limit) 性能预算：新增 `.size-limit.json` 配置（initial 100kB / vendor-vue 60kB / vendor-element 320kB / vendor-echarts 360kB / vendor-utils 40kB，gzip 口径），`package.json` 新增 `npm run size` / `npm run size:why`。当前实测：initial 55.51kB、vendor-vue 43.43kB、vendor-element 290.53kB、vendor-echarts 342.06kB、vendor-utils 32.37kB，**全部在预算内**。
- 不做：`@vitejs/plugin-legacy`（按用户要求只考虑主流版本，老 X5 / Android 9- 不再补 Babel + corejs polyfill）；Playwright 视觉回归 baseline（需下 ~300MB 浏览器 binary，可后续单独立项）。

构建：`npm run build` 通过；`npx size-limit` 全部通过；vitest 87/88（同上 2 个预先存在失败）。

### 2026-05-26 — PR-12 配套：移动端布局冒烟脚本

- ✅ **[Test-PR12]** 新增 `quantia/fontWeb/scripts/smoke-mobile.mjs`：启动 Playwright chromium headless，按 `375×667`（iPhone SE）/ `768×1024`（iPad portrait）两套视口巡检 `/home` / `/login` / `/register` / `/verify/compare` / `/strategy/list` 5 个关键路由，校验：
  - 视口生效（`window.innerWidth` 等于设定值）
  - 无横向溢出（`body.scrollWidth ≤ clientWidth + 2`）
  - `< 992` 时侧边栏折叠（`asideW === 0`）
  - 无 console.error / pageerror（过滤 favicon / 405 / web_vitals 噪音）
- ✅ **[Test-PR12]** `package.json` 新增 `npm run smoke:mobile` 一键入口；依赖 `web_service.py` 在 9988 运行，可通过 `QUANTIA_BASE` 改 base url。
- 实测：iPhone SE 5/5 通过，iPad portrait 5/5 通过，无 console error。

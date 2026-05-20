# Quantia 前端移动端适配方案 v2.0

> 文档版本：v2.0 ｜ 修订日期：2026-05-20 ｜ 适用分支：`backTest_dev`
> 范围：`quantia/fontWeb/`（Vue 3.4.21 + Element Plus 2.6.1 + Vite 5.1.6 + echarts 5.5.0）
> 目标设备：手机（≥360px）/ 平板（≥768px）/ 横竖屏自适应；零桌面端回归
>
> **v2.0 修订要点（第六轮：实施状态追踪 / 新功能覆盖 / 依赖规划 / 优先级重排）**：
> - 新增 §0.1 **实施状态追踪表**：截至 2026-05-20，零实施进展，全部 14 PR 仍处于规划阶段
> - 新增 §1.18 **第六轮审查补遗**（8 项）：覆盖验证中心 4 页面（compare/factorLab/fusion/optimize）+ AI Agent 管理页、AI 聊天抽屉、首页响应式已有断点修正（1100px/600px 而非文档前述 768px）、Playwright 已入 devDeps 但未配置、新增 utils 文件对移动适配的影响
> - 更新 §1.6 媒体查询审计结论：**6 处** @media 跨 5 文件（home 1100/600、optimize 1200、factorLab 960、fusion 960、paper-trading 900）
> - 新增 §3.1 **阶段 2.5 — 验证中心适配**（新增 PR-08b，覆盖 5 页面含 agent-manager）
> - 更新 §7 文件清单：补充已存在的 `utils/columnTooltips.ts`、`utils/backtestDashboardLinks.ts`、`composables/useCustomIndicatorOverlay.ts`
> - 更新 §12 **依赖安装计划**：明确各 PR 需安装的 npm 包及版本约束
> - 更新 §13 **实施优先级矩阵**：基于用户价值 × 技术风险重排 PR 顺序
> - 修正 AI 抽屉 `size="55%"` 百分比宽度（非硬编码 px）+ 220px sidebar 溢出问题
> - 移动端可用度上调至 **22%**（factorLab/fusion/paper-trading 已有初步断点）
> - 风险登记册扩展至 R75（+6 项新风险覆盖验证中心/AI 抽屉/首页已有断点冲突）
>
> **v1.1–1.5.2 历史修订摘要**（总计 R1–R69 / §1.10–1.17）：
> - v1.1–1.4：字号系统、国产浏览器碎片化、安全区、软键盘、弱网、ChunkLoadError 等
> - v1.5：时区交易时钟、rAF 调度、并发竞态、HEIC 上传、性能预算、合规
> - v1.5.1–1.5.2：代码勘误与错别字修正

---

## 0. TL;DR（执行摘要）

- **可行性**：✅ 可行。技术栈 Vue 3.4.21 + Element Plus 2.6.1 + Vite 5.1.6 + echarts 5.5.0 全部原生支持响应式，路由已 100% 动态 import，前端测试基础设施（Vitest 1.3 + Playwright 1.59）已就位。
- **当前移动端可用度**：约 **22%**（v2.0 二次上调）。viewport meta 可用、Element Plus 内置响应能力可用、首页已有 1100px/600px 断点、验证中心 3 页已有 960px/1200px 断点（grid 单列化）、模拟盘已有 900px 断点。其余页面无断点系统/响应式表格/触屏优化。
- **改造规模**：6 个阶段、约 **14 个 PR**、影响 **50+ 文件**、新增 **40+ 文件**。
- **实施进展**（截至 2026-05-20）：⚠️ **0/14 PR 已完成，0% 实施率**。全部仍处于规划阶段。
- **零桌面端回归保证**：通过「断点门禁 + CSS 媒体查询包裹 + Playwright 视觉回归」三重锁实现。
- **预期收益**：手机端可完成 70% 高频操作（看盘、回测列表、模拟盘持仓、登录注册、验证中心）；平板端可达 95%。
- **目标设备基线**（**v1.1 收紧**）：iOS 16+（含 Safari / WKWebView）、Android 11+（含 Chrome / 微信 X5 / 各国产浏览器，统一基于 Chromium 90+）。**不再支持** iOS ≤ 15、Android ≤ 10。

---

## 0.1 实施状态追踪（**v2.0 新增**）

> 上次更新：2026-05-20

### 总体进度

```
已完成: ░░░░░░░░░░░░░░░░░░░░ 0%
进行中: ░░░░░░░░░░░░░░░░░░░░ 0%
未开始: ████████████████████ 100%
```

### 各 PR 状态

| PR | 标题 | 阶段 | 状态 | 阻塞项 |
|---|---|---|---|---|
| PR-01 | 响应式基础（composables + SCSS） | 0 | ❌ 未开始 | 需先安装 `@vueuse/core` |
| PR-02 | Element Plus 按需引入 | 0 | ❌ 未开始 | 需安装 `unplugin-auto-import` + `unplugin-vue-components` |
| PR-03 | Layout / Sidebar / Navbar 响应式 | 1 | ❌ 未开始 | 依赖 PR-01 |
| PR-04 | 全局 ConfigProvider + dvh + 字号系统 | 1 | ❌ 未开始 | 依赖 PR-01 |
| PR-05 | StockData.vue 卡片视图 | 2 | ❌ 未开始 | 依赖 PR-01/03 |
| PR-06 | 回测列表与 Dashboard | 2 | ❌ 未开始 | 依赖 PR-01/03 |
| PR-07 | 模拟盘 | 2 | ❌ 未开始 | 依赖 PR-01/03 |
| PR-08 | 设置页面 | 2 | ❌ 未开始 | 依赖 PR-01/03 |
| **PR-08b** | **验证中心 4 页面**（v2.0 新增） | 2.5 | ❌ 未开始 | 依赖 PR-01/03 |
| PR-09 | K 线与指标图表 | 3 | ❌ 未开始 | 依赖 PR-01 |
| PR-10 | 回测详情 / Compare / Edit | 3 | ❌ 未开始 | 依赖 PR-01/09 |
| PR-11 | 弹窗与表单统一 | 4 | ❌ 未开始 | 依赖 PR-01 |
| **PR-11b** | **AI 聊天抽屉移动适配**（v2.0 新增） | 4 | ❌ 未开始 | 依赖 PR-01/03 |
| PR-12 | 性能 / 测试 / 文档收尾 | 5 | ❌ 未开始 | 依赖所有前置 PR |

### 依赖安装状态

| 包名 | 计划版本 | 已安装 | 所需 PR |
|---|---|---|---|
| `@vueuse/core` | ^10.9+ | ❌ | PR-01 |
| `unplugin-auto-import` | ^0.17+ | ❌ | PR-02 |
| `unplugin-vue-components` | ^0.27+ | ❌ | PR-02 |
| `decimal.js-light` | ^2.5+ | ❌ | PR-05 |
| `@vitejs/plugin-legacy` | ^5.3+ | ❌ | PR-12 |
| `size-limit` | ^11+ | ❌ | PR-12 |
| `web-vitals` | ^4+ | ❌ | PR-12 |
| `vue-virtual-scroller` 或 `@tanstack/vue-virtual` | latest | ❌ | PR-05（可选） |
| `heic2any` | ^0.0.4 | ❌ | PR-11（可选） |

### 已有基础设施（可直接利用）

| 资产 | 状态 | 说明 |
|---|---|---|
| Playwright | ✅ devDeps `^1.59.1` | 已安装但无 `playwright.config.ts`，无测试文件 |
| Vitest | ✅ `^1.3.1` | 已有 8 个测试文件，可扩展移动端测试 |
| 首页响应式 CSS | ✅ 部分 | `home/index.vue` 已有 1100px/600px 断点（网格适配） |
| 验证中心 optimize.vue | ✅ 部分 | 已有 1200px 断点（侧面板折叠） |
| 验证中心 factorLab.vue | ✅ 部分 | 已有 960px 断点（grid→单列） |
| 验证中心 fusion.vue | ✅ 部分 | 已有 960px 断点（dim-grid + kpi 两列） |
| 路由懒加载 | ✅ 100% | 所有路由已 `() => import(...)` |
| TypeScript strict | ✅ | `tsconfig.json` target ES2020 |
| MSW (Mock Service Worker) | ✅ devDeps `^2.2.3` | 可用于移动端集成测试 mock |

---

## 1. 当前代码深度审计（新增 / 修正既往结论）

### 1.1 资源 & 版本（无版本风险）

| 项 | 版本 | 状态 |
|---|---|---|
| Vue | 3.4.21 | ✅ |
| Element Plus | 2.6.1 | ✅ 原生支持 `:xs/:sm/:md/:lg` |
| Vite | 5.1.6 | ✅ |
| echarts | 5.5.0 | ✅ 内置 DPR 处理、`resize()` API |
| TS target | ES2020 | ✅ 不支持 IE11（无影响） |
| browserslist | 未配置 | ⚠️ 需补，autoprefixer 默认目标可能过窄 |
| viewport meta | 已配置 | ✅ `width=device-width, initial-scale=1.0` |

### 1.2 视口高度（vh / dvh）问题（**v1.1 简化**）

iOS Safari / Android Chrome 的 `100vh` 都不会响应地址栏折叠。我们的最低基线 iOS 16 / Android 11 + Chromium 108 已**全部支持 `dvh`**，因此**直接用 `100dvh` 替换**，不再需要 JS `--vh` 兜底。仅在 §1.13 处理 Android 软键盘弹起时单独使用 `visualViewport`。

当前需要替换的 7+ 处：

| 文件 | 行 | 当前代码 | 替换为 |
|---|---|---|---|
| [quantia/fontWeb/src/App.vue](quantia/fontWeb/src/App.vue#L13) | L13 | `height: 100%` | `height: 100dvh`（仅 root） |
| [quantia/fontWeb/src/views/algo/edit.vue](quantia/fontWeb/src/views/algo/edit.vue#L554) | L554 | `height: 100vh` | `height: 100dvh` |
| [quantia/fontWeb/src/views/backtest/portfolio.vue](quantia/fontWeb/src/views/backtest/portfolio.vue#L648) | L648 | `min-height: calc(100vh - 200px)` | `min-height: calc(100dvh - 200px)` |
| [quantia/fontWeb/src/views/backtest/portfolio.vue](quantia/fontWeb/src/views/backtest/portfolio.vue#L651) | L651-L657 | `height: calc(100vh - 200px)` | 同上 |
| [quantia/fontWeb/src/views/customIndicator/index.vue](quantia/fontWeb/src/views/customIndicator/index.vue#L598) | L598 | `min-height: calc(100vh - 110px)` | `min-height: calc(100dvh - 110px)` |
| [quantia/fontWeb/src/views/stock/StockData.vue](quantia/fontWeb/src/views/stock/StockData.vue#L446) | L446 | `height="calc(100vh - 280px)"` | `calc(100dvh - 280px)` |
| [quantia/fontWeb/src/views/login.vue](quantia/fontWeb/src/views/login.vue#L103) | L103 | `min-height: 100vh` | `min-height: 100dvh` |
| [quantia/fontWeb/src/views/register.vue](quantia/fontWeb/src/views/register.vue#L210) | L210 | `min-height: 100vh` | `min-height: 100dvh` |

**轻量保护层**（仅给少数仍漏 `dvh` 的国产 WebView 兜底）：

```scss
// src/styles/_mobile-vh.scss —— 仅为 5 个常用尺度提供别名
@supports not (height: 100dvh) {
  // 极少数老旧 Android 国产浏览器：退回 100vh，接受地址栏抖动
  :root { --dvh-fallback: 1vh; }
  .h-screen { height: calc(var(--dvh-fallback) * 100); }
}
```

> ⚠️ **不要**在桌面端 CSS 用 `100dvh`：桌面无地址栏抖动，dvh ≡ vh，不会有差异；但保持「只在断点内使用」的纪律可以让回归更可控。

### 1.3 echarts 容器尺寸与 resize 缺陷（**v1.1 增补 DPR / 触摸）**

#### 缺陷 1：K 线图高度硬编码
[quantia/fontWeb/src/views/indicator/index.vue#L39](quantia/fontWeb/src/views/indicator/index.vue#L39)：

```ts
const chartHeight = computed(() => (ciOverlay.extension.value?.subPanel ? 780 : 680))
```

在 iPhone（414×896）上 780px K 线占满整屏且无标尺。

#### 缺陷 2：resize 监听重复 + 无节流
[quantia/fontWeb/src/views/indicator/index.vue#L507-L512](quantia/fontWeb/src/views/indicator/index.vue#L507-L512)：onMounted + onActivated 各注册一次 `window.addEventListener('resize')`，**离开时只 cleanup 一次**，造成 keep-alive 切换后的内存泄漏。

#### 缺陷 3：缺少 `ResizeObserver`
所有图表都监听 `window.resize`，但容器被侧栏抽屉/对话框影响时不触发；横竖屏切换 Android Chrome 上 `resize` 触发时机也不稳（部分国产浏览器只在地址栏完全隐藏后才发一次，导致中间过渡帧布局抖动）。

#### 缺陷 4：echarts grid 内部硬编码
[quantia/fontWeb/src/views/algo/backtest-detail.vue#L1148](quantia/fontWeb/src/views/algo/backtest-detail.vue#L1148)：

```ts
grid: [{ left: 58, right: 62, top: 550, height: 60 }]   // px 硬编码
```

竖屏手机上 `left: 58` 占容器 14%，子图被压成 1cm 高。

#### 缺陷 5：echarts 未显式指定 `devicePixelRatio`（**v1.1 新增**）

`echarts.init(el)` 默认读 `window.devicePixelRatio`。Android 设备 DPR 离散值常见为 **1.5 / 2 / 2.625 / 3 / 3.5 / 4**（如三星 S24 = 3.0、华为 P60 = 3.5、Redmi Note 12 = 2.625）。当 DPR 为非整数时，canvas 的 K 线蜡烛会出现亚像素模糊：

```ts
const chart = echarts.init(el, undefined, {
  renderer: 'canvas',
  devicePixelRatio: Math.min(window.devicePixelRatio || 1, 2.5), // 截断防超大 canvas
  useDirtyRect: true, // 局部重绘，移动端 GPU 占用降 40%
})
```

> ⚠️ DPR > 3 时 canvas 像素 = 容器宽 × DPR²，1080px K 线在 DPR=4 设备上会创建 16M 像素的 canvas，触发部分 Android 的 GPU 内存上限（~256 MB），出现白屏。**必须截断到 ≤ 2.5**。

#### 缺陷 6：触屏 dataZoom 不可用（**v1.1 新增**）

现有 K 线 / 回测图全部使用默认 `slider` 型 dataZoom（带拖拽手柄）。在小屏上：
- 手柄 ~12px 宽，触屏命中率低于 50%
- 横屏切换后手柄位置错位（依赖 grid.bottom）

**移动端必须额外加 `inside` 型 dataZoom**：

```ts
dataZoom: [
  { type: 'inside', xAxisIndex: [0, 1], throttle: 50 },          // 双指捏合 / 单指拖拽
  ...(isDesktop ? [{ type: 'slider', bottom: 0, height: 18 }] : []), // 桌面才显示滑块
]
```

#### 缺陷 7：多副指标在小屏不可读（**v1.1 新增**）

指标页可同时叠加 MACD/KDJ/RSI/WR/多空趋势 5 个副图。在 414×280 移动 K 线区域内，每个副图仅剩约 30px 高，已无法读数。

**策略**：移动端启用「**单选**」模式，同一时刻只显示 1 个副指标（默认 MACD），通过 `<el-segmented>` 切换。

#### 修复策略
新建 [quantia/fontWeb/src/composables/useChartResponsive.ts](quantia/fontWeb/src/composables/useChartResponsive.ts)：

```ts
import { onMounted, onUnmounted, watch, type Ref } from 'vue'
import type { ECharts, EChartsOption } from 'echarts'
import { currentBp } from './useResponsive'

interface Options {
  el: Ref<HTMLElement | null>
  chart: Ref<ECharts | null>
  /** 不同断点下的容器高度（px） */
  height: { xs: number; sm: number; md: number; lg: number }
  /** 不同断点下的 grid 配置（px，同 echarts grid） */
  grid?: Partial<Record<'xs' | 'sm' | 'md' | 'lg', any>>
  /** 不同断点下的字号 */
  fontSize?: { xs: number; sm: number; md: number; lg: number }
}

export function useChartResponsive(opts: Options) {
  let ro: ResizeObserver | null = null
  let raf = 0

  const apply = () => {
    cancelAnimationFrame(raf)
    raf = requestAnimationFrame(() => {
      const { chart, el, height, grid, fontSize } = opts
      if (!chart.value || !el.value) return
      const bp = currentBp.value
      el.value.style.height = `${height[bp]}px`
      const patch: EChartsOption = {}
      if (grid?.[bp]) patch.grid = grid[bp]
      if (fontSize?.[bp]) {
        patch.textStyle = { fontSize: fontSize[bp] }
        patch.xAxis = [{ axisLabel: { fontSize: fontSize[bp] } } as any]
        patch.yAxis = [{ axisLabel: { fontSize: fontSize[bp] } } as any]
      }
      chart.value.setOption(patch, { lazyUpdate: true })
      chart.value.resize({ animation: { duration: 0 } })
    })
  }

  onMounted(() => {
    if (typeof ResizeObserver !== 'undefined' && opts.el.value) {
      ro = new ResizeObserver(apply)
      ro.observe(opts.el.value)
    }
    // orientationchange 是部分国产 Android 唯一可靠信号
    window.addEventListener('orientationchange', apply, { passive: true })
    apply()
  })
  onUnmounted(() => {
    ro?.disconnect()
    cancelAnimationFrame(raf)
    window.removeEventListener('orientationchange', apply)
  })

  // 断点变化即时响应（useBreakpoints 底层也是 matchMedia）
  watch(currentBp, apply)
}
```

**初始化调用例**（`indicator/index.vue` 重写后）：

```ts
const chart = echarts.init(el, undefined, {
  renderer: 'canvas',
  devicePixelRatio: Math.min(window.devicePixelRatio || 1, 2.5),
  useDirtyRect: true,
})
useChartResponsive({
  el: containerRef,
  chart: shallowRef(chart),
  height:    { xs: 280, sm: 380, md: 520, lg: 680 },
  grid:      {
    xs: { left: 36, right: 12, top: 24, bottom: 28 },
    sm: { left: 44, right: 16, top: 28, bottom: 32 },
    md: { left: 52, right: 24, top: 30, bottom: 36 },
    lg: { left: 58, right: 62, top: 30, bottom: 60 },
  },
  fontSize:  { xs: 10, sm: 11, md: 12, lg: 12 },
})
```

### 1.4 弹窗宽度风格不统一（**新发现**）

| 文件 | 行 | 宽度 | 问题 |
|---|---|---|---|
| [paper-trading/index.vue](quantia/fontWeb/src/views/paper-trading/index.vue#L520) | L520 | `width="90%"` | ✅ 响应式 |
| [paper-trading/index.vue](quantia/fontWeb/src/views/paper-trading/index.vue#L540) | L540 | `width="92vw" top="4vh"` | ⚠️ iOS Safari 滚动条占位 |
| [paper-trading/index.vue](quantia/fontWeb/src/views/paper-trading/index.vue#L626) | L626 | `width="520px"` | ❌ 360px 屏溢出 |
| [paper-trading/index.vue](quantia/fontWeb/src/views/paper-trading/index.vue#L180) | L180 | `el-popover :width="320"` | ❌ 同上 |
| [algo/backtest-detail.vue](quantia/fontWeb/src/views/algo/backtest-detail.vue#L230) | L230 | `width="92vw" top="4vh"` | ⚠️ |
| [settings/ai-config.vue](quantia/fontWeb/src/views/settings/ai-config.vue#L57) | L57 | `width="780"` | ❌ |

**统一规则**（在全局 mixin 中暴露）：

```scss
@function dialog-width($desktop) {
  @return min(#{$desktop}, 92vw);
}
// 用法：<el-dialog :width="$mobile? '92vw' : '520px'">
//      或直接 width="min(520px, 92vw)"
```

### 1.5 Element Plus 全量加载（**新发现**）

[quantia/fontWeb/src/main.ts#L23](quantia/fontWeb/src/main.ts#L23)：

```ts
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
app.use(ElementPlus, { locale: zhCn })
```

全量 ~1.2 MB JS + 全部 CSS。移动端 4G 加载明显感知慢。**改为按需引入**：

```ts
// vite.config.ts
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

plugins: [
  vue(),
  AutoImport({ resolvers: [ElementPlusResolver()] }),
  Components({ resolvers: [ElementPlusResolver()] }),
]
```

预估减重：JS ~600KB（gzip 后 ~180KB）。

### 1.6 既有媒体查询不一致（**v2.0 修正审计结论**）

经 v2.0 重新扫描，当前项目实际有 **3 处** 媒体查询（前版本遗漏了 verify/optimize.vue）：

- [home/index.vue](quantia/fontWeb/src/views/home/index.vue#L982): `@media (max-width: 1100px)` + `@media (max-width: 600px)` — 网格布局 4→2→1 列适配
- [verify/optimize.vue](quantia/fontWeb/src/views/verify/optimize.vue): `@media (max-width: 1200px)` — 侧面板折叠
- [paper-trading/index.vue#L1975](quantia/fontWeb/src/views/paper-trading/index.vue#L1975): `@media (max-width: 900px)` — 表格简化

**评估**：
- ✅ `home/index.vue` 的 1100px/600px 断点实际上已提供了基础移动适配（首页可用度 ~40%），这是项目中**唯一一个**在手机上基本可用的页面
- ⚠️ 三处断点来源不统一（600/900/1100/1200px），各自独立定义，无法复用
- ❌ 11 个其他路由区域（algo/backtest/customIndicator/indicator/paper-trading/settings/stock/strategy/verify 其他 3 页/login/register）完全无断点

**全部统一到 Element Plus 官方断点**：

| Breakpoint | 范围 | 设备 |
|---|---|---|
| `xs` | <768px | 手机 |
| `sm` | 768–991px | 竖向平板 |
| `md` | 992–1199px | 横向平板 / 小桌面 |
| `lg` | 1200–1919px | **当前默认桌面** |
| `xl` | ≥1920px | 大显示器 |

### 1.7 触摸事件覆盖（**新发现，风险可控**）

| 事件 | 触屏行为 | 处理方式 |
|---|---|---|
| `@row-click` | ✅ touch tap 自动映射 | 无需改 |
| `show-overflow-tooltip` | ⚠️ 触屏无 hover | 单元格点击展开 popover；或保留（影响小）|
| `@dblclick` | ❌ iOS 需 300ms 延迟 | 改 longpress 或单击双态 |
| `mouseenter` | ❌ 不触发 | 用 `@touchstart` 双绑 |
| `contextmenu` | ❌ 触屏触发被浏览器截获 | 改 longpress |

代码扫描结果：当前**无 `dblclick` / `mouseenter` 业务代码**，风险点仅 `show-overflow-tooltip`（20+ 处），可保留作为桌面端体验。

### 1.8 路由守卫的潜在阻塞（**新发现**）

[quantia/fontWeb/src/router/index.ts#L469](quantia/fontWeb/src/router/index.ts#L469)：

```ts
router.beforeEach(async (to) => {
  if (to.meta?.public) return true
  await authStore.bootstrap()  // 慢网下阻塞页面切换
  // ...
})
```

**iOS Safari 后台 5–10 分钟后会丢内存态**，每次切页都会重新调用 `/api/auth/me`。建议：
1. `bootstrap()` 设 3s 超时 + 失败缓存（localStorage）；
2. `enabled=false` 场景下完全跳过 `bootstrap()`。

### 1.9 测试设施（**新发现，可复用**）

- ✅ 已有 [quantia/fontWeb/vitest.config.ts](quantia/fontWeb/vitest.config.ts) + 8 个测试文件
- ❌ 无 Playwright / Cypress 视觉回归
- ❌ 无移动断点测试

需新增：`tests/responsive/` 目录 + Playwright 视觉回归（3 个视口：375×667 / 768×1024 / 1920×1080）

---

### 1.10 字号与用户缩放系统（**v1.1 新增**）

#### 问题 1：PingFang SC 字体在 Android 上不存在
[quantia/fontWeb/src/styles/index.scss](quantia/fontWeb/src/styles/index.scss)（示意）的 `'Helvetica Neue', Helvetica, 'PingFang SC', ...` 在安卓上会退回到「系统默认 sans-serif」，各厂商不一（华为 HarmonyOS Sans 、小米 MiSans、OPPO Sans、Vivo Sans、三星 Roboto）。

**修正**：补全安卓同源系统字体名：

```scss
$font-stack-cn:
  -apple-system, BlinkMacSystemFont,           // iOS / macOS 原生渲染
  'PingFang SC',                                // iOS 中文
  'HarmonyOS Sans SC', 'HarmonyOS_Sans_SC',     // 鸿蒙 / 华为 EMUI
  'MiSans', 'MI LANTING', 'Mi Lanting',         // 小米 MIUI
  'Source Han Sans CN', 'Noto Sans CJK SC',     // 安卓原生思源
  'Microsoft YaHei UI', 'Microsoft YaHei',      // Windows
  Arial, sans-serif;                             // 兜底
```

#### 问题 2：用户缩放破坏布局
Android 「设置 → 显示 → 字号大小」可调到 1.3× / 1.5× / 2.0×。Element Plus 默认 14px，被放大到 28px 后，各种响应式高度计算（`label-position`/对话框头部）会被顶破。微信 X5 内核也有「全局字号」设置。

**修正策略**：

1. **不要**在 `<meta viewport>` 上设 `maximum-scale=1, user-scalable=no` 去禁用所有缩放（违反 WCAG）。
2. 全局 root `font-size` 改用 `clamp()` 限定上下限：
   ```scss
   html { font-size: clamp(13px, 0.875rem, 17px); }
   ```
   这样 200% 缩放下不会超过 17px，布局仍可读。
3. **echarts 内部字号走独立通道**（不跟随用户缩放）： `useChartResponsive.fontSize` 已预留。
4. 表格在 ≥ 1.5× 缩放下自动切到卡片视图（在 `useResponsive.ts` 加 `useMediaQuery('(min-resolution: 1.5dppx)')` 检测，作为 `isMobile` 的 OR 条件之一）。

#### 问题 3：Element Plus `size="small"` 在 320px 屏仍超出
Element Plus 的「small」高度仍为 24px+，多个按钮、下拉、输入并排依然会被挤出容器。
**修正**：
- 手机端表单一律单列排列（`<el-col :xs="24">`）；
- 不要使用横向 `<el-button-group>`，改为 `<el-segmented>` 或垂直排列。

#### 问题 4：iOS Safari 输入框自动放大页面
WebKit 默认在 `<input>` 字号 < 16px 时会强制放大页面（3x scale-up）。
现代码未显式设输入框字号，Element Plus 默认 14px → 会触发 zoom。
**修正**：
```scss
@include xs-only {
  .el-input__inner, .el-select__inner, .el-textarea__inner { font-size: 16px !important; }
}
```

---

### 1.11 Android WebView / 各国产浏览器碎片化（**v1.1 新增重点**）

以 2026 年 5 月实际安装量为准，重点关注下表中的 WebView/浏览器：

| 宿主 / 浏览器 | 内核 | 状态 | 已知问题 |
|---|---|---|---|
| Android Chrome ≥ 108 | Chromium 108+ | ✅ 全面支持 | — |
| **微信内置浏览器（X5 内核）** | Chromium 86–107 变动 | ⚠️ 主要重点 | iOS 上走 WKWebView（OK）；Android 2024 起部分机型已升级为 Chromium 122，但老机仍是 86。**`dvh` 在 ≤ 107 不支持**——需 `_mobile-vh.scss` 兜底。 |
| QQ内置浏览器 | Chromium 100+ | ✅ 可用 | `position: sticky` 在部分版本下失效。 |
| 钉钉内置浏览器 | Chromium 109+ | ✅ | — |
| 小红书 / 抖音 / 快手 WebView | Chromium 100–122 | ✅ | 部分版本 `overscroll-behavior` 被重写。 |
| 华为 Petal Browser（HarmonyOS） | Chromium 119+ | ✅ | `ResizeObserver.entries[i].contentRect` 偶返 0，需以 `el.clientHeight` 为准。 |
| 小米 MIUI 浏览器 | Chromium 120+ | ✅ | 默认开启「提示隐藏地址栏」可能多发 1–2 次 resize。 |
| Vivo / OPPO ColorOS 浏览器 | Chromium 100+ | ✅ | iframe 嵌套时 viewport 偏移 4px（本项目不嵌套）。 |
| UC 浏览器 | U4 内核（Chromium-fork） | ⚠️ 谨慎兼容 | `dvh` 不支持；autoplay 被拦截；canvas DPR 被强制 1。 |
| 夸克 / 其他国产主流浏览器 | Chromium 122+ | ✅ | — |
| 三星 Samsung Internet | Chromium 122+ | ✅ | 默认开启「云端高对比」会调升颜色饱和度，涨跌颜色需验收。 |

#### 问题 1：WebView 检测 & 温和降级

```ts
// composables/useUserAgent.ts
export function detectWebView() {
  const ua = navigator.userAgent
  return {
    isWeChat:    /MicroMessenger/i.test(ua),
    isQQ:        /\bQQ\//i.test(ua),
    isDingTalk:  /DingTalk/i.test(ua),
    isUC:        /UCBrowser/i.test(ua),
    isHarmony:   /HarmonyOS/i.test(ua),
    isOldX5:     /TBS\/04\d{4}|TBS\/05\d{4}/.test(ua),  // X5 老版本需降级
  }
}
```

#### 问题 2：微信内置浏览器独有的怪异行为
- 返回手势不可拦截（不要依赖 `beforeunload` 阻止离开）；
- `localStorage` 在部分版本上仅 5 MB（桌面端 10 MB）；
- HTTPS 必要（X5 低版本会拦截混合内容）。

---

### 1.12 不同屏幕与 DPR 下的图表处理详解（**v1.1 新增**）

#### A. 高度映射表（嵌入 `useChartResponsive.height`）

| 场景 | xs （手机竖） | sm （手机横 / 平板竖） | md （平板横） | lg （桌面） |
|---|---|---|---|---|
| K 线主图 | 280 | 360 | 480 | 680 |
| K 线 + 1 个副图 | 360 | 460 | 600 | 780 |
| 回测资产曲线 | 220 | 300 | 380 | 480 |
| 回测日盈亏柱 | 180 | 240 | 300 | 360 |
| Dashboard 指标分布 | 200 | 260 | 320 | 380 |

#### B. grid（内块边距）映射表

| 字段 | xs | sm | md | lg |
|---|---|---|---|---|
| `left` | 36 | 44 | 52 | 58 |
| `right` | 12 | 16 | 24 | 62 |
| `top` | 24 | 28 | 30 | 30 |
| `bottom` | 28 | 32 | 36 | 60 |

> 桌面 `right=62` 是为了收纳右侧 dataZoom 指标浮层；手机上隐藏该浮层，可紧贴边。

#### C. DPR 与渲染器选择

| DPR | 设备举例 | 设置建议 |
|---|---|---|
| 1 | 笔记本 | 默认 canvas，无需特殊 |
| 2 | iPhone SE / Pixel | canvas + DPR=2 |
| 2.625 | Redmi Note 12 | canvas + DPR=2.5（截断） |
| 3 | iPhone 15 / S24 | canvas + DPR=2.5 |
| 3.5 | 华为 P60 | canvas + DPR=2.5 |
| 4 | 个别旗舰 | canvas + DPR=2.5（避免 16M 像素） |

**统一代码**（PR-09 中应用）：

```ts
const dpr = Math.min(window.devicePixelRatio || 1, 2.5)
const chart = echarts.init(el, undefined, { renderer: 'canvas', devicePixelRatio: dpr, useDirtyRect: true })
```

#### D. 横竖屏切换三阶段处理

```
[orientationchange] → 50ms 后调 apply（visualViewport 尚未汇报）
         → ResizeObserver entries（真正的最终尺寸）二次 apply
         → chart.resize({ animation: { duration: 0 } })
```

避免动画是为了防止 Android 上双阶段动画耗费 200ms。

#### E. 不同尺寸下的蜡烛宽度自适应
echarts `barCategoryGap` 可以动态调节，但手机上蜡烛过细点击不准。**补充**：手机默认 dataZoom `start: 70`（仅看近期 30%），桌面 `start: 0`。

---

### 1.13 Android 软键盘：visualViewport（**v1.1 新增**）

Android 软键盘弹起后，**不会**动态调整 `window.innerHeight`（默认 resize 模式为 `pan` 而非 `resize`），造成输入框被键盘遮挡。**只有 `visualViewport` API 是可靠信号**。

```ts
// composables/useVirtualKeyboard.ts
import { ref, onMounted, onUnmounted } from 'vue'

export function useVirtualKeyboard() {
  const visible = ref(false)
  const heightShift = ref(0)
  if (typeof window === 'undefined' || !window.visualViewport) return { visible, heightShift }
  const vv = window.visualViewport
  const onChange = () => {
    const shift = window.innerHeight - vv.height
    heightShift.value = shift
    visible.value = shift > 80   // > 80px 认为键盘弹起
  }
  onMounted(() => {
    vv.addEventListener('resize', onChange)
    vv.addEventListener('scroll', onChange)
  })
  onUnmounted(() => {
    vv.removeEventListener('resize', onChange)
    vv.removeEventListener('scroll', onChange)
  })
  return { visible, heightShift }
}
```

**用法**：在 `RegisterHandler` / `LoginHandler` / `paper-trading` 表单页中，键盘弹起时调整聚焦输入框位置：

```ts
const { visible, heightShift } = useVirtualKeyboard()
watch(visible, (v) => {
  if (v) document.activeElement?.scrollIntoView({ block: 'center', behavior: 'smooth' })
})
// 样式侧可加：.dialog-body { max-height: calc(100dvh - 120px - var(--kb-shift, 0px)); }
```

**代码逻辑错误**。现代码 [register.vue](quantia/fontWeb/src/views/register.vue#L210) 的 `min-height: 100vh` 在 Android 键盘弹起时会造成「提交」按钮被键盘遮挡，接入 `useVirtualKeyboard` 后会自动滚动。

---

### 1.14 国产设备 / 国产浏览器深度风险（**v1.1 二轮审查新增**）

经过对 2025–2026 年主流国产设备（华为 Mate60/P70、小米 14/15、vivo X100、OPPO Find X7、荣耀 Magic6、一加 12、真我 GT、红魔、努比亚、iQOO、中兴、传音）和国产 WebView（X5/U4/MIUI/HarmonyOS Petal/Quark/Vivo Internet/OPPO Internet）的代码审计与社区缺陷追踪，下列**先前未覆盖**的风险需要在 PR 计划中予以解决。

#### 1.14.1 安全区适配（刘海 / 挖孔 / 全面屏手势条 / Dynamic Island）

**问题**：iPhone 14 Pro+（灵动岛 59px）、华为 Mate60 Pro 居中挖孔、小米 14 居左挖孔、Galaxy Fold 内屏铰链折痕、几乎所有 2024+ 安卓机底部 16–34px 全面屏手势条 —— 当前 [App.vue](quantia/fontWeb/src/App.vue) 与 [login.vue](quantia/fontWeb/src/views/login.vue#L103) 均**未使用** `env(safe-area-inset-*)`，会导致：
- 顶栏「钟表」被挖孔遮挡；
- 底部 fixed 操作栏（如「立即下单」）被手势条压住，点击穿透到系统返回。

**修正**：

```html
<!-- index.html -->
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
```

```scss
// _safe-area.scss（PR-04 引入）
:root {
  --sa-top:    env(safe-area-inset-top, 0px);
  --sa-bottom: env(safe-area-inset-bottom, 0px);
  --sa-left:   env(safe-area-inset-left, 0px);
  --sa-right:  env(safe-area-inset-right, 0px);
}
.app-header   { padding-top:    max(8px, var(--sa-top)); }
.app-footer,
.fixed-action { padding-bottom: max(8px, var(--sa-bottom)); }
.app-shell    { padding-left:   var(--sa-left); padding-right: var(--sa-right); }
```

> ⚠️ 必须配合 `viewport-fit=cover`，否则 `env()` 永远返回 0。

#### 1.14.2 状态栏 / 主题色（沉浸式与暗黑模式）

**问题**：
- 当前 [index.html](quantia/fontWeb/index.html) 无 `<meta name="theme-color">`，安卓状态栏会显示默认黑色 / 白色，与 K 线红绿背景割裂；
- 用户系统暗黑模式下，K 线、表格仍是亮色 → 夜间炫光。
- 微信 X5 / MIUI / EMUI 自带「自动暗黑」会反转页面颜色，把红涨绿跌反成绿涨红跌，严重误导金融用户。

**修正**：

```html
<meta name="theme-color" content="#1f2937" media="(prefers-color-scheme: dark)" />
<meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)" />
<!-- 关键：明确告知系统不要强制反色 -->
<meta name="color-scheme" content="light dark" />
<meta name="force-rendering" content="webkit" />
<!-- 微信/QQ 关闭自动暗黑反色 -->
<meta name="darkmode" content="false" />
```

并在 [styles/_dark.scss](quantia/fontWeb/src/styles/_dark.scss) 中显式禁用反色：

```scss
@media (prefers-color-scheme: dark) {
  /* 红涨绿跌不可被翻转 */
  .candle-up, .price-up   { color: #f56c6c !important; }
  .candle-down, .price-down { color: #67c23a !important; }
}
/* MIUI / EMUI 强制反色防御 */
html { -webkit-text-size-adjust: 100%; forced-color-adjust: none; }
```

#### 1.14.3 微信 X5 / QQ 浏览器特有 API 与陷阱

| 行为 | X5 现状 | 处理 |
|---|---|---|
| 右上角「···」分享菜单 | 默认显示「在浏览器打开」可能让用户登出 | `WeixinJSBridge.invoke('hideOptionMenu')` |
| 点击页内链接强制顶部跳转 | 一些版本不响应 SPA `history.pushState` | 使用 `router.replace` 替代 `router.push` 时降级 |
| 视频/音频自动播放 | 必须 `WeixinJSBridge.invoke('getNetworkType', {}, cb)` 后才能播放 | 项目无音视频，**忽略** |
| 文件下载 | `<a download>` 不生效，会跳到「请用浏览器打开」 | 调用 `wx.miniProgram.navigateTo` 或显示二维码 |
| 内置相机权限 | `<input type="file" capture>` 在低版本 X5 失效 | 提示用户切换浏览器 |
| 复制到剪贴板 | `navigator.clipboard` 在 X5 < TBS 6800 不可用 | 降级到 `document.execCommand('copy')` |

**实现**：在 PR-04 加 [composables/useWeChatBridge.ts](quantia/fontWeb/src/composables/useWeChatBridge.ts)：

```ts
export function readyWeChat(cb: () => void) {
  if (!/MicroMessenger/.test(navigator.userAgent)) return cb()
  if ((window as any).WeixinJSBridge) cb()
  else document.addEventListener('WeixinJSBridgeReady', cb, { once: true })
}
export async function copyText(text: string) {
  try { await navigator.clipboard.writeText(text); return true }
  catch {
    const ta = document.createElement('textarea'); ta.value = text
    ta.style.cssText = 'position:fixed;top:-9999px;'
    document.body.appendChild(ta); ta.select()
    const ok = document.execCommand('copy'); ta.remove(); return ok
  }
}
```

#### 1.14.4 中文输入法合成事件（IME composition）

**问题**：搜索框 `@input` 监听会在用户**还没敲完拼音**时就触发查询，造成：
- 搜索请求空打 5–10 次；
- 在小米 / vivo 自带输入法上首拼音被吃。

当前 [stock/StockData.vue](quantia/fontWeb/src/views/stock/StockData.vue)（搜索）和投资组合编辑器都**未处理 composition**。

**修正**（标准模式）：

```vue
<script setup lang="ts">
import { ref } from 'vue'
const query = ref('')
const composing = ref(false)
function onSearch(v: string) { /* 发起接口 */ }
</script>

<template>
  <el-input v-model="query"
    @compositionstart="composing = true"
    @compositionend="e => { composing = false; onSearch((e.target as HTMLInputElement).value) }"
    @input="v => { if (!composing) onSearch(v) }" />
</template>
```

或封装 [composables/useImeAwareInput.ts](quantia/fontWeb/src/composables/useImeAwareInput.ts) 复用。

#### 1.14.5 数字键盘类型与金融输入优化

**问题**：手数 / 价格 / 止损位是数字，但当前模拟盘 [paper-trading](quantia/fontWeb/src/views/paper-trading) 全部用默认 `<el-input>`（type=text），用户在手机上要切到数字键盘多按 1 次。Android 数字键盘还会少负号 `-` 与小数点。

**修正**：

```vue
<el-input :inputmode="'decimal'" pattern="[0-9.]*" v-model="price" />   <!-- 价格 -->
<el-input :inputmode="'numeric'" pattern="\d*"     v-model="shares" />  <!-- 股数 -->
<el-input :inputmode="'tel'"                       v-model="phone"  />  <!-- 手机 -->
<el-input :inputmode="'email'" autocomplete="email" v-model="email" />  <!-- 邮箱 -->
<el-input :inputmode="'search'"                    v-model="query"  />  <!-- 搜索（弹收起按钮）-->
```

> `inputmode="decimal"` 在 iOS / 国产安卓输入法上会出 **9 键带小数点**，比 `type="number"` 更友好（不会出 spinner、不会 reject 前导 0）。

#### 1.14.6 移动端长列表性能（千级股票列表 + K 线 tooltip）

**问题**：[StockData.vue](quantia/fontWeb/src/views/stock/StockData.vue) 一次渲染 500–5000 行，桌面 OK，手机：
- 中端机 (骁龙 7 Gen 3) 滚动 jank 至 25fps；
- 微信 X5 上首屏 LCP > 4s；
- 滚动时 echarts tooltip 与表格滚动事件互相阻塞。

**修正**：

1. 引入 `vue-virtual-scroller` 或 `@tanstack/vue-virtual`，仅手机端启用：
   ```vue
   <RecycleScroller v-if="isMobile" :items="rows" :item-size="60" key-field="code">...</RecycleScroller>
   <el-table v-else :data="rows">...</el-table>
   ```
2. echarts 大数据集启用 `progressive: 4000`、`large: true`、`largeThreshold: 2000`。
3. 表格 `scroll` 监听加 `passive: true`，避免阻塞渲染线程。
4. 列表项图片 `loading="lazy" decoding="async"`。

#### 1.14.7 弹窗背景滚动锁定（iOS / X5 经典缺陷）

**问题**：iOS Safari / X5 在 `<el-dialog>` 打开时，**dialog 内部滚动会穿透**到 body，导致：
- 用户滑 K 线工具条，结果整页跟着滚；
- 下拉刷新被误触发。

**修正**：在 PR-04 全局引入 [body-scroll-lock](https://github.com/willmcpo/body-scroll-lock)（4KB）或自实现：

```ts
// composables/useBodyScrollLock.ts
let locks = 0; let savedScrollY = 0
export function lockBody() {
  if (locks++ === 0) {
    savedScrollY = window.scrollY
    document.body.style.cssText = `position:fixed;top:-${savedScrollY}px;left:0;right:0;overflow:hidden;`
  }
}
export function unlockBody() {
  if (--locks === 0) {
    document.body.style.cssText = ''
    window.scrollTo(0, savedScrollY)
  }
}
```

挂到 `el-dialog` 的 `@open` / `@close`。

#### 1.14.8 折叠屏（Galaxy Fold5 / Mate X5 / Pixel Fold / OPPO Find N3）

**问题**：折叠屏内屏 / 外屏 fold 切换时会触发 **3–5 次 resize + viewport 改变**，echarts 多次重渲染卡顿；铰链区不可点击但布局未避让。

**修正**：

```ts
// composables/useFoldable.ts
import { ref, onMounted, onUnmounted } from 'vue'

interface VVWithSegments extends VisualViewport { segments?: DOMRect[] }

export function useFoldable() {
  const isFolded = ref(false)
  const vv = window.visualViewport as VVWithSegments | null
  if (!vv || !('segments' in vv)) return { isFolded }
  const check = () => {
    const segs = vv.segments
    isFolded.value = !!segs && segs.length > 1
  }
  onMounted(() => { vv.addEventListener('resize', check); check() })
  onUnmounted(() => vv.removeEventListener('resize', check))
  return { isFolded }
}
```

CSS 上提供铰链避让：

```scss
@media (horizontal-viewport-segments: 2) {
  .app-shell { padding: 0 env(viewport-segment-right 0 0) 0 env(viewport-segment-left 1 0); }
}
```

手动节流 echarts resize 至 200ms，避免 fold 动画期间冗余渲染。

#### 1.14.9 弱网 / 断网 / 后台恢复

**问题**：金融数据实时性高，但当前 [api/index.ts](quantia/fontWeb/src/api/index.ts) 无：
- 网络状况感知；
- 切到后台再回来时刷新策略；
- 5G/Wi-Fi/2G 自适应轮询频率。

**修正**（PR-08 中追加）：

```ts
// composables/useNetwork.ts
import { computed, watch, watchEffect, onUnmounted } from 'vue'
import { useNetwork, useDocumentVisibility } from '@vueuse/core'

export function useAdaptivePolling(refresh: () => void) {
  const { isOnline, effectiveType } = useNetwork()
  const visibility = useDocumentVisibility()
  const interval = computed(() => {
    if (!isOnline.value || visibility.value !== 'visible') return 0
    return ({ 'slow-2g': 0, '2g': 60_000, '3g': 30_000, '4g': 5_000, '5g': 3_000 } as Record<string, number>)
      [effectiveType.value as string] ?? 10_000
  })
  let timer: ReturnType<typeof setInterval> | null = null
  const clear = () => { if (timer) { clearInterval(timer); timer = null } }
  watchEffect(() => { clear(); if (interval.value > 0) timer = setInterval(refresh, interval.value) })
  // 切回前台立即刷新一次
  watch(visibility, v => { if (v === 'visible') refresh() })
  onUnmounted(clear)
}
```

配合 axios 全局 retry：5xx 与超时 1 次重试，2xx 不重试。

#### 1.14.10 触屏点击高亮 / 长按选择 / 橡皮筋滚动

**问题**：未做 `tap-highlight` 移除，按钮被点击后会出现一坨灰色块（X5/Quark 上尤其难看）；表格行长按会弹出系统翻译菜单。

**修正**（PR-04 全局）：

```scss
html {
  -webkit-tap-highlight-color: transparent;
  -webkit-touch-callout: none;          /* 长按不弹 iOS 菜单（输入框除外）*/
  overscroll-behavior-y: contain;        /* 阻止橡皮筋外溢到根 */
}
input, textarea, [contenteditable], .selectable { -webkit-touch-callout: default; user-select: text; }
.app-scroll { overscroll-behavior: contain; -webkit-overflow-scrolling: touch; }
```

#### 1.14.11 中文 Web 字体加载（FOIT 闪烁）

**问题**：项目目前未自加载中文字体，但**可能**未来引入 PingFang Web / Source Han。中文字体 4–7MB，国产运营商 4G 加载耗时 8–15s，期间出现：
- iOS：FOIT（不可见文字）— 用户看不到任何字 8 秒；
- 安卓：FOUT（无样式文字闪烁）。

**预防性策略**（即使现在不引入也写入文档）：

```css
@font-face {
  font-family: 'AppFont';
  src: url('/fonts/AppFont-subset.woff2') format('woff2');
  font-display: swap;            /* iOS 14+ 已支持，杜绝 FOIT */
  unicode-range: U+4E00-9FFF, U+3000-303F, U+FF00-FFEF;  /* 仅加载常用中文+标点 */
}
```

并使用 [chinese-font-split](https://github.com/aliyun/chinese-font-split) 把字体切成 50 个 ~200KB 子集，按 `unicode-range` 按需下载。

#### 1.14.12 表单自动填充与凭证管理

**问题**：当前 [login.vue](quantia/fontWeb/src/views/login.vue) / [register.vue](quantia/fontWeb/src/views/register.vue) 缺 `autocomplete` / `name` 属性，导致：
- iOS 钥匙串 / Android 自动填充 / 微信「常用密码」无法识别；
- 注册成功后浏览器**不会**保存密码。

**修正**：

```vue
<form name="login" autocomplete="on">
  <el-input name="username" autocomplete="username"      v-model="u" />
  <el-input name="current-password" autocomplete="current-password" type="password" v-model="p" />
</form>
<!-- 注册页改用 new-password -->
<el-input autocomplete="new-password" type="password" />
<!-- 验证码使用 one-time-code 让 iOS 自动从短信抓取 -->
<el-input autocomplete="one-time-code" inputmode="numeric" v-model="code" />
```

#### 1.14.13 鸿蒙 NEXT (HarmonyOS 5) ArkWeb 兼容

**新设备**：2025 H2 起华为系全部切到 HarmonyOS NEXT，使用 **ArkWeb** 而非 Chromium。已知差异：
- `IntersectionObserver.thresholds` 数组 > 5 时被忽略；
- `ResizeObserver.contentRect.width` 在容器 `display:none → block` 切换瞬间为 0；
- `localStorage` 跨域 iframe 不通；
- `<dialog>` 元素不支持，`backdrop` 缺失（项目用的是 Element Plus 自绘 dialog，**无影响**）。

**对策**：UA 检测到 `ArkWeb` 时降级 `IntersectionObserver` 阈值到 [0, 0.5, 1]；ResizeObserver 回调读 0 时跳过这次（等下一帧）。

#### 1.14.14 国产桌面浏览器「IE 内核」陷阱

**问题**：360 安全 / 360 极速 / QQ 浏览器 / 搜狗 / 2345 在桌面端**默认双内核**，部分用户公司策略下被强制 IE / Trident 内核。本项目用 Vue 3 + ESM，**完全不支持** IE。

**对策**：在 `<head>` 显式声明：

```html
<meta http-equiv="X-UA-Compatible" content="IE=edge,chrome=1" />
<meta name="renderer" content="webkit" />
<meta name="force-rendering" content="webkit" />
<!-- 国产双核浏览器看到此即切到极速内核 -->
```

并在 [main.ts](quantia/fontWeb/src/main.ts) 启动时检测，IE 直接跳错误页：

```ts
if (!('noModule' in HTMLScriptElement.prototype) || !('Promise' in window)) {
  location.replace('/browser-upgrade.html')
}
```

#### 1.14.15 PWA / Service Worker 在国产 WebView 的不可用

- 微信 X5：**禁用** Service Worker；`navigator.serviceWorker` 为 undefined。
- UC / QQ 部分版本：注册 SW 抛 SecurityError。
- 决策表已选择 ❌ 不做 PWA（§10 #2），但**仍需**在引入任何 SW 代码前先 `if ('serviceWorker' in navigator && !/MicroMessenger|UCBrowser/.test(navigator.userAgent))` 判断，避免控制台报错。

#### 1.14.16 触觉反馈与点击声（提升金融操作仪式感）

非必须，但「下单」「确认平仓」可加触觉反馈，国产手机几乎全部支持：

```ts
function haptic(pattern: number | number[] = 10) {
  if ('vibrate' in navigator) navigator.vibrate(pattern)
}
// 下单成功
haptic([20, 40, 20])
```

微信 X5 上 `vibrate` 被禁，try/catch 即可。

---

### 1.15 第三轮审查补遗（**v1.3 新增**）

以下 15 个问题是前两轮遗漏，涵盖无障碍、资源加载失败、实时通讯、存储超限、CSP / Cookie 平台差异、用户体验仪式感。

#### 1.15.1 ChunkLoadError（镜像更新后老页面跳路由白屏）

**问题**：项目路由 100% 动态 import，Vite 打包后产生 hash 文件名（如 `views-stock-StockData.a8f3c2.js`）。发布后老 chunk 被删除，用户手机页面**在后台同位超过几小时**，重新切路由时 fetch 404，抛 `ChunkLoadError`，页面完全白屏。移动端会话保持时间远远长于桌面，严重。

**修正**：在 [src/router/index.ts](quantia/fontWeb/src/router/index.ts) 加全局 onError：

```ts
// router/index.ts
let lastChunkReloadAt = 0
router.onError((err, to) => {
  if (!/Loading chunk .* failed|Failed to fetch dynamically imported module/i.test(err.message)) return
  // 防微循环：同一分钟内超过 1 次刷新，跳错误页
  const last = Number(sessionStorage.getItem('chunkReloadAt') || 0)
  if (Date.now() - last < 60_000) {
    router.replace('/error/runtime?code=CHUNK_LOOP')
    return
  }
  sessionStorage.setItem('chunkReloadAt', Date.now().toString())
  location.replace(to.fullPath)
})
```

且 [vite.config.ts](quantia/fontWeb/vite.config.ts) 补上：

```ts
build: {
  rollupOptions: { output: { entryFileNames: 'assets/[name]-[hash].js', chunkFileNames: 'assets/[name]-[hash].js' } },
  // 保留老 chunk 不删（上传到 CDN 后保留 30 天，运维调）
}
```

#### 1.15.2 WebSocket / SSE 在移动后台被切断

**问题**：若后期为行情推送引入 WebSocket，iOS 锁屏 / 安卓切后台 30s 后连接被系统强制关闭，但 `WebSocket.onclose` 不会立即触发，切回前台后需 30–60s 才能错误重连，期间用户以为行情仍实时。

**修正**（即使现在未引入 WS 也写入约定）：

```ts
// composables/useStableSocket.ts
import { watch, onUnmounted } from 'vue'
import { useDocumentVisibility } from '@vueuse/core'

export function useStableSocket(url: string, onMsg: (e: MessageEvent) => void) {
  let ws: WebSocket | null = null
  let heartbeat: ReturnType<typeof setInterval> | null = null
  let reconnect: ReturnType<typeof setTimeout> | null = null
  let backoff = 1500
  let manualClose = false
  const visibility = useDocumentVisibility()

  const cleanup = () => {
    if (heartbeat) { clearInterval(heartbeat); heartbeat = null }
    if (reconnect) { clearTimeout(reconnect); reconnect = null }
  }
  const open = () => {
    cleanup()
    if (visibility.value !== 'visible' || manualClose) return
    ws = new WebSocket(url)
    ws.onmessage = onMsg
    ws.onopen = () => {
      backoff = 1500
      heartbeat = setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send('ping'), 25_000)
    }
    ws.onclose = () => {
      cleanup()
      if (manualClose || visibility.value !== 'visible') return
      // 指数退避：1.5s → 3s → 6s → … → 上限 30s
      reconnect = setTimeout(open, backoff)
      backoff = Math.min(backoff * 2, 30_000)
    }
    ws.onerror = () => ws?.close()
  }

  watch(visibility, v => {
    if (v === 'visible' && (!ws || ws.readyState !== WebSocket.OPEN)) open()
    if (v === 'hidden' && ws) { cleanup(); ws.close(); ws = null }   // 主动关避免幽灵连接
  })

  open()
  onUnmounted(() => { manualClose = true; cleanup(); ws?.close(); ws = null })
  return { send: (m: string) => ws?.readyState === WebSocket.OPEN && ws.send(m) }
}
```

#### 1.15.3 el-message / el-notification 被刘海 / 灵动岛遮挡

**问题**：Element Plus 默认 `el-message` `top: 20px` 在 iPhone 14 Pro 上被灵动岛遮挡；`el-notification position="top-right"` 在 `xs` 下超宽。

**修正**：在全局初始化包装：

```ts
// utils/messageMobile.ts
import { ElMessage, ElNotification } from 'element-plus'
import { isMobile } from '@/composables/useResponsive'

function safeAreaTop(): number {
  if (typeof window === 'undefined') return 0
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--sa-top').trim()
  const n = parseInt(raw, 10)
  return Number.isFinite(n) ? n : 0
}

export function showMessage(opts: Parameters<typeof ElMessage>[0]) {
  return ElMessage({
    ...(typeof opts === 'string' ? { message: opts } : opts),
    offset: isMobile.value ? Math.max(60, safeAreaTop() + 12) : 20,
    customClass: isMobile.value ? 'msg-mobile' : '',
  })
}
```

```scss
.msg-mobile { max-width: 92vw !important; min-width: 0 !important; }
.el-notification.right { @include xs-only { left: 4vw !important; right: 4vw !important; width: 92vw !important; } }
```

#### 1.15.4 无障碍（a11y）与读屏器

**问题**：
- Sidebar 抽屉打开后焦点**未陷入抽屉**，Tab 跳出到背后隐藏元素；
- 图标按钮（`<el-button :icon="Refresh">`）无 `aria-label`，VoiceOver / TalkBack 读为「按钮」。
- K 线 canvas 无任何读屏替代。

**修正**：

1. 全局插件 [`focus-trap`](https://github.com/focus-trap/focus-trap)，抽屉 / dialog 打开时应用；
2. 所有图标按钮补 `aria-label`： `<el-button :icon="Refresh" aria-label="刷新数据" />`；
3. K 线容器加 `role="img"` 与动态 `aria-label`（例如 `` :aria-label="`${code} ${name} 近期走势图`" ``），供读屏器读出股名。

#### 1.15.5 CSS @container 查询：表格↔卡片需依容器宽而非视口

**问题**：抽屉打开后主区变窄到 320px，但视口仍是 768px，现有「表格 → 卡片」判断依赖 `useBreakpoints` 看不到。

**修正**：在容器上加：

```scss
.data-zone { container-type: inline-size; container-name: data; }
@container data (max-width: 600px) {
  .data-table { display: none; }
  .data-cards { display: block; }
}
```

iOS 16+ / Chromium 105+ 均支持。不支持时可通过 `@supports (container-type: inline-size)` 退化到视口断点。

#### 1.15.6 顶部下拉刷新与浏览器原生手势冲突

**问题**：iOS Safari / X5 / MIUI 都有「下拉刷新」或「下拉请求中心」原生手势。如果项目自定义下拉刷新，两者冲突。

**修正**：不做自定义 PtR。顶部加 `overscroll-behavior-y: contain` 防止提示出现；用户请使用页面内的刷新按钮。下拉加载仅用于长列表**底部上拉**（`IntersectionObserver` 哨兵元素）。

#### 1.15.7 滚动条样式在桌面/移动不一致

**问题**：现有 [styles/index.scss](quantia/fontWeb/src/styles/index.scss) 可能自定 `::-webkit-scrollbar` 6px，桌面 OK，但 iOS / 安卓上原本就不显示滚动条，但项目全局设 `overflow:auto` 容器会使用该 6px 条，可能在 X5 上占据宽度，表格右侧被遮。

**修正**：

```scss
@include xs-only {
  ::-webkit-scrollbar { width: 0; height: 0; }       // 移动端隐藏
  * { scrollbar-width: none; -ms-overflow-style: none; }
}
```

#### 1.15.8 骨架屏 & 首屏优化

**问题**：移动端首屏 LCP 在 4G 下 3–5s，期间仅看到空白 / `<el-loading>` 转圈。金融类用户信心不足。

**修正**：在 [index.html](quantia/fontWeb/index.html) 的 `<div id="app">` 内**内嵌 SSR-like 骨架**：

```html
<div id="app">
  <div class="app-skeleton">
    <div class="sk-header"></div>
    <div class="sk-row" v-for="i in 8"></div>
  </div>
</div>
<style>
  .app-skeleton { padding: 16px; }
  .sk-header, .sk-row { background: linear-gradient(90deg, #f0f0f0 0%, #e0e0e0 50%, #f0f0f0 100%);
    background-size: 200% 100%; animation: sk 1.4s ease-in-out infinite; border-radius: 4px; }
  .sk-header { height: 50px; margin-bottom: 16px; }
  .sk-row { height: 28px; margin-bottom: 12px; }
  @keyframes sk { 0%{background-position: 200% 0} 100%{background-position: -200% 0} }
</style>
```

Vue 挂载后自动覆盖，FCP 提前到 200ms。

#### 1.15.9 viewport interactive-widget（Chrome 108+ 软键盘优化）

**问题**：安卓 Chrome 108+ / Edge 可通过 viewport 元标签控制软键盘是否压缩 viewport。默认为 `resizes-visual`，与 §1.13 visualViewport 逻辑完美契合。

**修正**：[index.html](quantia/fontWeb/index.html) 优化 viewport：

```html
<meta name="viewport"
  content="width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content" />
```

> `interactive-widget=resizes-content` = 软键盘弹起时压缩 layout viewport，表单底部按钮自动上移，不需 useVirtualKeyboard 手动调整。 iOS / 老 X5 不识别该 token 会忽略，不冲突。

#### 1.15.10 复制股票代码 / 资金账号

**问题**：现有表格单元格股票代码只能全选复制，手机上双击 → 选中 1 个字。金融 App 标配是「点击即复制」。

**修正**：股票代码列加 `.copyable` 类：

```vue
<span class="copyable" @click="copy(row.code)">{{ row.code }}</span>
<!-- copy() 复用 §1.14.3 useWeChatBridge.copyText 并 ElMessage.success('已复制') -->
```

#### 1.15.11 Vue 错误边界与移动端崩溃报告

**问题**：现代码未设 `app.config.errorHandler`。移动端一旦崩溃页面变白，用户不会主动报错，研发无感。

**修正**：在 [main.ts](quantia/fontWeb/src/main.ts)：

```ts
import axios from 'axios'

const MAX_REPORTS = 5
let reportCount = 0
function reportError(payload: Record<string, unknown>) {
  if (reportCount++ >= MAX_REPORTS) return       // 同会话限流
  // navigator.sendBeacon 在卸载页面时也能成功递交
  const body = new Blob([JSON.stringify(payload)], { type: 'application/json' })
  if (navigator.sendBeacon?.('/api/client-error', body)) return
  axios.post('/api/client-error', payload).catch(() => {})
}

app.config.errorHandler = (err, _vm, info) => {
  console.error('[vue]', err, info)
  reportError({ msg: String(err), info, ua: navigator.userAgent, url: location.href })
}
window.addEventListener('unhandledrejection', e =>
  reportError({ msg: 'unhandledrejection: ' + (e.reason?.message ?? e.reason), ua: navigator.userAgent, url: location.href }))
```

后端补 `POST /api/client-error` 接收即可，不引入 Sentry 三方（避免 X5 CSP 问题）。

#### 1.15.12 localStorage QuotaExceededError

**问题**：微信 X5 老版 `localStorage` 仅 5MB；Safari 隐私模式下为 0。用户设置 / 后续写入存在被拒的可能，**现代码未作任何 try/catch**，会崩。

**修正**：统一走轻量包装层：

```ts
// utils/safeStorage.ts
export const safeStorage = {
  set(k: string, v: any) {
    try { localStorage.setItem(k, JSON.stringify(v)) }
    catch (e: any) {
      if (/quota/i.test(e?.name || '')) {
        // 清除非必要缓存
        ['kline-cache', 'chart-snapshot'].forEach(p => {
          for (const k of Object.keys(localStorage)) if (k.startsWith(p)) localStorage.removeItem(k)
        })
        try { localStorage.setItem(k, JSON.stringify(v)) } catch {}
      }
    }
  },
  get(k: string, fb: any = null) {
    try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : fb } catch { return fb }
  },
}
```

#### 1.15.13 Cookie SameSite 与跨域 / WKWebView

**问题**：
- `csrf_token` cookie 默认 SameSite=Lax，微信内项目被从微信网页跳转进来时是跨站，**首次 GET 会丢 cookie**；
- iOS WKWebView 从 App 内跳出后再返回，部分会话 cookie 丢失。

**修正**（后端补 cookie 字段）：

```
Set-Cookie: csrf_token=xxx; Path=/; Secure; SameSite=None; Max-Age=86400
Set-Cookie: csrf_token_lax=xxx; Path=/; Secure; SameSite=Lax; Max-Age=86400  # 备份
```

前端 [api/index.ts](quantia/fontWeb/src/api/index.ts) 优先读 `csrf_token`，丢失时读 `csrf_token_lax` 并手动 POST `/api/auth/refresh-csrf` 重新拿一次。**HTTPS 必须**，微信官方 2025 起全量 HTTPS，不再提供明文。

#### 1.15.14 CSP（内容安全策略）与移动端 inline 脚本

**问题**：若后端添加严格 CSP（`script-src 'self'`），§1.15.8 骨架屏中的 inline `<style>` 会被拦截。

**修正**：

1. 骨架屏样式提取到独立 [public/skeleton.css](quantia/fontWeb/public/skeleton.css)；
2. 后端在 RegisterHandler / LoginHandler 返回页面时设 `Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; connect-src 'self' wss:`，**不含** `script-src 'unsafe-inline'`；
3. Vite 生成产物已为外联 hash 文件，天然兼容。

#### 1.15.15 modulepreload 在老 X5 不支持

**问题**：Vite 默认生成 `<link rel="modulepreload">`，老版本 X5 (TBS ≤ 6500) 识为未知 link 类型并忽略。需启用 polyfill。

**修正**： [vite.config.ts](quantia/fontWeb/vite.config.ts) 加：

```ts
export default {
  build: { modulePreload: { polyfill: true } },
}
```

在加 [@vitejs/plugin-legacy](https://www.npmjs.com/package/@vitejs/plugin-legacy)：

```ts
import legacy from '@vitejs/plugin-legacy'
plugins: [
  vue(),
  legacy({ targets: ['Android >= 11', 'iOS >= 16', 'Chrome >= 100'], modernPolyfills: true }),
]
```

合计额外 +30KB 作为老版 X5 的保底。

---

### 1.16 第四轮审查补遗（**v1.4 新增**）

本轮重点扫描「内存泄漏、跨标签页同步、金融数字精度、a11y 偏好、原生交互、分享/打印」，填充剩余 12 个高价值盲区。

#### 1.16.1 echarts 实例未释放：路由切换内存泄漏

**问题**：[indicator/index.vue](quantia/fontWeb/src/views/indicator/index.vue)、[backtest-detail.vue](quantia/fontWeb/src/views/algo/backtest-detail.vue)、Dashboard 多个页面的 `echarts.init(el)` **都没有在 `onBeforeUnmount` 调 `chart.dispose()`**。桌面 GC 可以延后清理，但手机上：
- 手机 Chrome 单页 JS 堆上限 ~256 MB；
- keep-alive 缓存 + 前后台调度会让 GC 延迟；
- 用户连续在 5 只股票之间切换查看后，Android Chrome 会自动「重载 Tab」，重载后状态全失。

**修正**（PR-09 并作为全局约定写入 useChartResponsive）：

```ts
import { onBeforeUnmount, onDeactivated } from 'vue'

function safeDispose(chart: ECharts | null) {
  if (chart && !chart.isDisposed()) {
    chart.clear()           // 先释放 Series
    chart.dispose()         // 再释放 canvas + WebGL context
  }
}

onBeforeUnmount(() => safeDispose(chart.value))
onDeactivated(() => safeDispose(chart.value))   // keep-alive 也要释放
```

> ⚠️ keep-alive 页面需同时在 `onActivated` 重建 chart 实例。可以在 useChartResponsive 中封装 `recreate(el)` 方法统一。

#### 1.16.2 prefers-reduced-motion / prefers-reduced-data

**问题**：
- iOS / 安卓均提供「减少动画」辅助选项（老人/前庭症用户使用）。项目现有过渡、echarts 动画、Sidebar 抽屉动画不尊重该设置——严重会引发头晕 / 电池耗尽。
- Save Data（`prefers-reduced-data`）是「节流」信号，国内运营商路由在资费紧缩时会开启。项目不应主动轮询及预加载。

**修正**：

```scss
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
  .el-drawer, .el-dialog { transition: none !important; }
}
```

```ts
// composables/usePrefers.ts
export const reducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)')
export const reducedData   = useMediaQuery('(prefers-reduced-data: reduce)')
export const prefersDark   = useMediaQuery('(prefers-color-scheme: dark)')

// echarts 初始化时读取
const opt: EChartsOption = { animation: !reducedMotion.value, ... }
```

配合 `useAdaptivePolling`（§1.14.9）作「打折」：reduced-data 下轮询间隔 ×2。

#### 1.16.3 Pinia / 登录状态 跨标签页同步

**问题**：用户在标签页 A 退出登录，标签页 B 仍在「已登录」状态发交易请求→ 全部 401，但错误提示不准确；反之在 B 登录 A 仍为未登录。

**修正**：使用 `BroadcastChannel`（iOS 15.4+/Chrome 54+均支持）：

```ts
// stores/auth.ts
const chan = 'BroadcastChannel' in window ? new BroadcastChannel('auth') : null
chan?.addEventListener('message', e => {
  if (e.data?.type === 'logout') authStore.$reset()
  if (e.data?.type === 'login')  authStore.bootstrap()
})
function logout() { /* ... */ chan?.postMessage({ type: 'logout' }) }
function login()  { /* ... */ chan?.postMessage({ type: 'login'  }) }
```

同时后端在 `/api/auth/me` 401 时，前端 axios 拦截器**广播一次 logout** 避免多标签页错位。

#### 1.16.4 金融数字精度：浮点误差 + 人民币格式化

**问题**：
- `0.1 + 0.2 === 0.30000000000000004`——平仓盈亏 / 费率累加 / 手续费计算可能出现「0.01 差」，是金融场景的严重问题。
- 中文金额习惯「万/亿」单位（「市值 1.23 亿」），现有代码可能直接显「123,456,789」手机上超宽。
- 负零 `-0.00` 出现在 `Number.toFixed(2)` 后（原始值为 -0.0001）。

**修正**：

```ts
// utils/decimal.ts
import Decimal from 'decimal.js-light'    // 11KB gzip

export const D = (v: any) => new Decimal(v ?? 0)
export const dAdd  = (a: any, b: any) => D(a).plus(b)
export const dMul  = (a: any, b: any) => D(a).times(b)
export const dDiv  = (a: any, b: any, dp = 4) => D(a).div(b || 1).toDecimalPlaces(dp)

// utils/format.ts
const CN_UNITS: [number, string][] = [[1e8, '亿'], [1e4, '万']]
export function fmtMoneyCn(v: number, digits = 2) {
  const abs = Math.abs(v)
  for (const [u, name] of CN_UNITS) if (abs >= u) return (v / u).toFixed(digits) + name
  return v.toFixed(digits)
}
export function fmtPct(v: number, dp = 2) {
  if (Object.is(v, -0) || Math.abs(v) < 10 ** -dp / 2) v = 0   // 除负零
  return (v * 100).toFixed(dp) + '%'
}
export function fmtThousand(v: number, dp = 2) {
  return new Intl.NumberFormat('zh-CN', { minimumFractionDigits: dp, maximumFractionDigits: dp }).format(v)
}
```

表格列使用 `:formatter` 接入，手机端优先 `fmtMoneyCn`，桌面端 `fmtThousand`。

#### 1.16.5 色盲友好：红绿色盲占中国男性 ~6%

**问题**：红涨绿跌是中国习惯，但对红绿色盲用户（中国男性 4-6%）饱和度接近平均，仅靠颜色不能辨别。

**修正**：

```ts
// settings store
state: () => ({ colorMode: 'rg' as 'rg' | 'colorblind' | 'mono' })
```

```scss
// _candle-color.scss
html[data-color=rg]         { --c-up:#f56c6c; --c-down:#67c23a; }
html[data-color=colorblind] { --c-up:#d62728; --c-down:#1f77b4; }   /* 红 vs 蓝，色盲可辨 */
html[data-color=mono]       { --c-up:#000;    --c-down:#fff;     border:1px solid #999; }
```

并在 ± 变化旁加**箭头符号**：`+1.23%▲` / `-0.45%▼`，股价背景加微纹理（CSS `background-image: repeating-linear-gradient`），即使纯黑白也可辨。

#### 1.16.6 Element Plus 原生日期 / 选择器在移动端不友好

**问题**：`<el-date-picker>` / `<el-time-picker>` 在手机上是「桌面面板」风格：
- 数字不能滑动选择，只能点月历格子；
- 平板横屏上面板被软键盘压住。

同样，`<el-select>` 在 360×640 屏上下拉被裁切或超出。

**修正**：

1. **日期**：手机端切换为原生输入（iOS Safari/安卓 Chrome 原生日期选择器 UX 优于任何 H5 面板）：
   ```vue
   <input v-if="isMobile" type="date" v-model="date" :min="min" :max="max" class="native-date" />
   <el-date-picker v-else v-model="date" />
   ```
   ```scss
   .native-date { height: 40px; padding: 0 12px; border: 1px solid var(--el-border-color); border-radius: 4px; font-size: 16px; }
   ```
2. **选择器**：`<el-select :teleported="true">` + 加全局：
   ```scss
   .el-select__popper.el-popper { @include xs-only { max-width: 92vw !important; } }
   ```
3. 在抽屉里装 select 要加 `popper-options="{ strategy: 'fixed' }"` 否则被抽屉 transform 创建的新定位上下文裁切。

#### 1.16.7 ResizeObserver loop limit exceeded

**问题**：使用 ResizeObserver 后，控制台会看到 `ResizeObserver loop limit exceeded`，部分后端 Sentry 会误报警。实际不会崩但发送 1000+ 错误/小时。

**修正**：在 §1.15.11 错误上报里过滤：

```ts
window.addEventListener('error', (e) => {
  if (/ResizeObserver loop/.test(e.message)) { e.stopImmediatePropagation(); return }
})
```

#### 1.16.8 微信分享与预览卡片

**问题**：用户在微信里点「发送给朋友」传 Quantia 面板链接，默认生成：
- 标题：`<title>` 原文（可能是「Quantia」）；
- 描述：空；
- 缩略图：微信默认 favicon。

金融产品需「成交预览」「资产曲线预览」。

**修正**：

1. 静态全局 meta（index.html）：
   ```html
   <meta property="og:title" content="Quantia量化选股" />
   <meta property="og:description" content="个人量化回测与模拟交易平台" />
   <meta property="og:image" content="https://your-domain/share-cover.png" />
   <meta name="description" content="个人量化回测与模拟交易平台" />
   <link rel="icon" href="/favicon.ico" sizes="any" />
   <link rel="apple-touch-icon" href="/apple-touch-icon.png" />   <!-- iOS 加到主屏图标 -->
   ```
2. 路由动态设标题（PR-04）：
   ```ts
   router.afterEach((to) => { document.title = (to.meta?.title as string ?? 'Quantia') + ' - Quantia' })
   ```
3. 微信定制分享（可选，需后端走微信 JS-SDK 签名）补入 [composables/useWeChatShare.ts](quantia/fontWeb/src/composables/useWeChatShare.ts)，在 `useWeChatBridge` 的 `wx.ready` 后调 `wx.updateAppMessageShareData` / `wx.updateTimelineShareData`。

#### 1.16.9 打印样式（回测报告 / 资产快照）

**问题**：用户会「调用浏览器打印 → 另存为 PDF」输出回测报告，但现代码无 `@media print` 适配：Sidebar/Navbar 也会被打印、K 线背景色丢失、表格顶部不重复、fixed 按钮遮挡。

**修正**：[styles/_print.scss](quantia/fontWeb/src/styles/_print.scss)：

```scss
@media print {
  .app-sidebar, .app-navbar, .el-pagination, .no-print, .fixed-action { display: none !important; }
  .app-main { margin: 0 !important; padding: 0 !important; }
  .el-table { page-break-inside: avoid; }
  .el-table thead { display: table-header-group; }    /* 表头逐页重复 */
  .el-card { box-shadow: none; border: 1px solid #ccc; }
  body { color: #000; background: #fff; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  a[href]::after { content: ' (' attr(href) ')'; font-size: 10px; color: #666; }
}
```

在要打印区加 `class="printable"`，其他元素加 `no-print`。

#### 1.16.10 路由滚动还原 / 双击顶部回顺

**问题**：
- iOS Safari 顶栏双击会滚动到页顶（原生手势），但项目 SPA 路由入后可能滚动在 `app-main` 内部，该手势失效。
- Vue Router 默认跳路由后不回顶，手机上从长页跳到新页仍在底部，用户容易迷失。

**修正**：

```ts
// router/index.ts
const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, saved) {
    if (saved) return saved
    if (to.hash) return { el: to.hash, behavior: 'smooth', top: 60 }
    return { top: 0, behavior: 'instant' }
  },
})
```

顶栏「Logo」加 `@click` 手动滚到顶： `document.querySelector('.app-main')?.scrollTo({ top: 0, behavior: 'smooth' })`。

#### 1.16.11 表单「Enter 提交 / Tab 跳下一项」与手机键盘「下一项」按钮

**问题**：手机软键盘右下角默认是「下一项」。Element Plus `<el-form>` 需**多个 `<el-input>`** 且都在表单内，并在最后一个输入按「提交」。单输入表单下 Enter 默认会刷新页面（历史项目 bug）。

**修正**：

```vue
<el-form @submit.prevent="handleSubmit">
  <!-- 必须加 native-type="submit" 让手机键盘出「提交」「搜索」 -->
  <el-input v-model="q" :inputmode="'search'" enterkeyhint="search" />
  <el-button native-type="submit" v-show="false" />
</el-form>
```

`enterkeyhint` 取值：send / search / done / next / go，手机软键盘会变色。

#### 1.16.12 错误边界 + Suspense 路由加载失败

**问题**：动态路由 chunk 加载中遇到网络错误，页面底层会留「上一页」但实际路由已变，URL 与内容不一致，用户点「返回」到丢失位。

**修正**：除 §1.15.1 ChunkLoadError onError 外，在主路由外层加 Suspense + Error 兜底捕获：

```vue
<!-- App.vue -->
<router-view v-slot="{ Component, route }">
  <suspense :timeout="3000">
    <component :is="Component" :key="route.fullPath" />
    <template #fallback>
      <div class="app-skeleton"><!-- 复用 §1.15.8 --></div>
    </template>
  </suspense>
</router-view>
```

另加**全局错误页面** [views/error/runtime.vue](quantia/fontWeb/src/views/error/runtime.vue)，在 `app.config.errorHandler`（§1.15.11）中，连续 3 次同一路由报错时 `router.replace('/error/runtime')`。

---

### 1.17 第五轮审查补遗（**v1.5 新增**）

本轮重点扫描「时区与交易时钟、定时器漂移、并发竞态、上传下载、性能预算、CLS 布局偏移、反调试、反被静默劫持」，填充剩余 12 个金融产品独有面向。

#### 1.17.1 时区与 A 股交易日历处理

**问题**：
- A 股交易时间是 **Asia/Shanghai 9:30–11:30 / 13:00–15:00**。在境外资产账户的海外用户 / IT 运维（服务器 UTC）可能看到 K 线 X 轴是 UTC，与「开盘」提示不同步；
- `new Date('2025-11-15')` 在 iOS 上**被解析为 UTC**，安卓部分版本解析为本地，同一个股票在境外手机上 K 线**偏一天**；
- 交易节假日（十一、春节）未在前端隔离，回测可能在非交易日生成模拟订单。

**修正**：

```ts
// utils/tz.ts
import { fromZonedTime, toZonedTime, format } from 'date-fns-tz'
import { parseISO } from 'date-fns'
export const TZ = 'Asia/Shanghai'

export function parseDateCN(s: string): Date {
  // 'YYYY-MM-DD' 按上海时区解析，避免 iOS UTC 偏移
  return fromZonedTime(s.length === 10 ? `${s}T00:00:00` : s, TZ)
}
export function fmtCN(d: Date | string, p = 'yyyy-MM-dd HH:mm') {
  const dt = typeof d === 'string' ? parseISO(d) : d
  return format(toZonedTime(dt, TZ), p, { timeZone: TZ })
}
// 交易时钟
export function isTradingTime(now = new Date()) {
  const z = toZonedTime(now, TZ)
  const m = z.getHours() * 60 + z.getMinutes()
  const day = z.getDay()
  if (day === 0 || day === 6) return false
  return (m >= 570 && m <= 690) || (m >= 780 && m <= 900)   // 9:30-11:30, 13:00-15:00
}
```

A 股交易日历从后端 `/api/calendar/sse` 拉一次（项目已有后端交易日历），前端 [composables/useTradingClock.ts](quantia/fontWeb/src/composables/useTradingClock.ts) 缓存 6 小时，驱动顶栏「距开盘 X 分钟」及轮询闸门。

#### 1.17.2 定时器后台漂移与重叠

**问题**：
- 手机锁屏 / 后台 5 分钟 → setInterval 丢帧 → 回前台后一口气补 50 次调用，股价闪烁。
- 多个页面同时 setInterval 调同一 API → 重复请求、限流。
- `setTimeout(fn, 0)` 在 keep-alive 页面被重复注册、未清，漏。

**修正**：统一调度器 [composables/useScheduler.ts](quantia/fontWeb/src/composables/useScheduler.ts)：

```ts
// composables/useScheduler.ts
interface Task { fn: () => void; intv: number; last: number }
const tasks = new Map<string, Task>()
let rafId = 0

function tick() {
  rafId = 0
  const now = performance.now()
  for (const t of tasks.values()) {
    if (now - t.last < t.intv) continue
    t.last = now
    try { t.fn() } catch (e) { console.error('[scheduler]', e) }   // 单个失败不影响其它任务
  }
  if (tasks.size) rafId = requestAnimationFrame(tick)
}

export function schedule(key: string, fn: () => void, intv: number) {
  tasks.set(key, { fn, intv, last: performance.now() })
  if (!rafId && document.visibilityState === 'visible') rafId = requestAnimationFrame(tick)
}
export function unschedule(key: string) {
  tasks.delete(key)
  if (!tasks.size && rafId) { cancelAnimationFrame(rafId); rafId = 0 }
}

// 后台 → 暂停；前台 → 重起并立即跑一次
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') {
    if (rafId) { cancelAnimationFrame(rafId); rafId = 0 }
  } else if (tasks.size && !rafId) {
    // 立即跑一次（不等 rAF），保证回前台即刷新
    for (const t of tasks.values()) t.last = 0
    rafId = requestAnimationFrame(tick)
  }
})
```

rAF 被后台自动限为 1Hz 甚至暂停，天然避免后台补帧连发请求；可见性变更后强制 `t.last=0` 让所有任务下一帧立即触发一次。

#### 1.17.3 并发竞态：后发请求覆盖先发结果

**问题**：用户连击股票 `000001 → 000002 → 000003`。3 个 `/api/kline?code=...` 并发发出，响应顺序可能是 1→32，最后后请求到达者被老响应覆盖，K 线显示「000001 但头部写着 000003」。桌面网络好隐蔽，手机频发。

**修正**：请求 ID 递增 + 丢弃过期响应 + AbortController：

```ts
// composables/useLatest.ts
import { ref, onUnmounted } from 'vue'

export function useLatest<T>(load: (sig: AbortSignal) => Promise<T>) {
  let seq = 0
  let ctrl: AbortController | null = null
  const data = ref<T | null>(null)
  const loading = ref(false)

  async function run() {
    const my = ++seq
    ctrl?.abort()
    ctrl = new AbortController()
    loading.value = true
    try {
      const r = await load(ctrl.signal)
      if (my === seq) data.value = r            // 判断是否仍是最新
    } catch (e: unknown) {
      if ((e as Error)?.name !== 'AbortError') throw e
    } finally {
      if (my === seq) loading.value = false
    }
  }

  onUnmounted(() => { seq++; ctrl?.abort() })   // 组件卸载时中断未完请求
  return { data, loading, run }
}
```

KLine / 价格 / 财务指标等所有「跟随选股」接口全部包 useLatest。

#### 1.17.4 表单重复提交与闲置超时

**问题**：手机下单按钮点击后响应 800ms，用户以为没点到再点一次 → 重复下单。项目现有 `el-button :loading` 但**并未全面使用**。另：用户填完表单中途手机锁屏 30 分钟后回来 → csrf token 过期 → 一提交 403。

**修正**：

1. 提供 `useLock`（复用于下单 / 平仓 / 提交 case）：
   ```ts
   // composables/useLock.ts
   import { ref, onUnmounted } from 'vue'
   export function useLock<F extends (...a: any[]) => Promise<any>>(fn: F, ms = 1000) {
     const locked = ref(false)
     let timer: ReturnType<typeof setTimeout> | null = null
     const wrapped = (async (...a: any[]) => {
       if (locked.value) return
       locked.value = true
       try { return await fn(...a) }
       finally {
         if (timer) clearTimeout(timer)
         timer = setTimeout(() => { locked.value = false; timer = null }, ms)
       }
     }) as F
     onUnmounted(() => { if (timer) clearTimeout(timer); timer = null })
     return [wrapped, locked] as const
   }
   ```
2. 闲置检测： [composables/useIdle.ts](quantia/fontWeb/src/composables/useIdle.ts) 用 `useIdle`（vueuse）15 分钟未操作则弹出提示「资料已过时，请刷新」按钮。
3. csrf 过期后 axios 拦截器自动调 `/api/auth/refresh-csrf` 重试 1 次，仍败则弹 §1.16.3 BroadcastChannel logout。

#### 1.17.5 文件上传：HEIC / 大图 / 微信限制

**问题**：头像 / 资金证明等上传：
- iPhone 默认拍照为 **HEIC**，后端 Pillow / 浏览器展示不了；
- 安卓旗舰机拍照 50MB JPEG，上传超时；
- 微信内项目「从相册选择」在部分机型上 `accept="image/*"` 被忽略 → 会混入视频。

**修正**： [composables/useImageUpload.ts](quantia/fontWeb/src/composables/useImageUpload.ts)：

```ts
// composables/useImageUpload.ts
// heic2any 仅在用户选中 HEIC 文件后动态 import，避免 80KB gzip 进首屏

export async function preprocessImage(file: File, opts = { maxW: 1600, q: 0.82 }): Promise<Blob> {
  let blob: Blob = file
  if (/heic|heif/i.test(file.type) || /\.heic$/i.test(file.name)) {
    const m = await import('heic2any')
    blob = (await m.default({ blob: file, toType: 'image/jpeg', quality: 0.85 })) as Blob
  }
  const bmp = await createImageBitmap(blob)
  const scale = Math.min(1, opts.maxW / bmp.width)
  const cv = document.createElement('canvas')
  cv.width = Math.round(bmp.width * scale); cv.height = Math.round(bmp.height * scale)
  cv.getContext('2d')!.drawImage(bmp, 0, 0, cv.width, cv.height)
  bmp.close()
  return new Promise(r => cv.toBlob(b => r(b!), 'image/jpeg', opts.q))
}
```

上传元素： `<input type="file" accept="image/jpeg,image/png,image/heic" capture="environment">`。`accept` 必须列举具体 mime，避免微信选到视频等其他类型。

#### 1.17.6 文件下载与导出 CSV（回测报告 / 交易流水）

**问题**：手机上 `<a download>` 在微信 / iOS Safari 上会「在当前页打开」而非下载；大 CSV 在手机上被 Excel 映射为其它 mime 占用 RAM。

**修正**：

```ts
// utils/download.ts
export function downloadBlob(blob: Blob, filename: string) {
  // iOS Safari 不支持 a.download，走「新开窗 + saveAs」温和提示
  const ua = navigator.userAgent
  if (/iPad|iPhone|iPod/.test(ua) && /Safari/.test(ua) && !/CriOS|FxiOS/.test(ua)) {
    const reader = new FileReader()
    reader.onload = () => { window.location.href = reader.result as string }
    reader.readAsDataURL(blob)
    return
  }
  const url = URL.createObjectURL(blob)
  const a = Object.assign(document.createElement('a'), { href: url, download: filename })
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 4000)
}
```

CSV 导出加 BOM，防 Excel 中文乱码： `new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' })`。

#### 1.17.7 性能预算与指标项量

**问题**：现代码无 perf budget；bundle 坐指会随时间增加，上线后才发现首屏慢。

**修正**：

1. [vite.config.ts](quantia/fontWeb/vite.config.ts) 加：
   ```ts
   build: { chunkSizeWarningLimit: 500, rollupOptions: { /* manualChunks */ } }
   ```
2. CI 加一步 `pnpm size`，使用 [size-limit](https://github.com/ai/size-limit) 限制：
   ```json
   // .size-limit.json
   [{"path":"dist/assets/index-*.js","limit":"260 KB"},
    {"path":"dist/assets/echarts-*.js","limit":"320 KB"}]
   ```
3. 收集真实用户指标： [utils/rum.ts](quantia/fontWeb/src/utils/rum.ts) 使用 [web-vitals](https://github.com/GoogleChrome/web-vitals)（3KB）上报 LCP/INP/CLS/TTFB 到 `/api/rum`，手机与桌面分别统计。

#### 1.17.8 CLS（累积布局偏移）与骨架到内容跳变

**问题**：Google CWV 要求 CLS ≤ 0.1。项目多处跳变源：
- 骨架屏 → 真实表格高度不一；
- echarts 初始为 0 高 → mounted 后占 280px；
- 图片（股票股名logo）未设 `width/height` → 加载后后捏。

**修正**：

```scss
// 骨架占位与真实高度一致
.kline-placeholder { aspect-ratio: 16 / 9; min-height: 280px; }
img.stock-logo { aspect-ratio: 1 / 1; width: 28px; height: auto; }
.el-table { min-height: calc(40px + 60px * var(--initial-rows, 10)); }
```

echarts 容器**在 mount 前就有明确高度**。纯脚本创建的 DOM 千万不要「先 0 后填充」。

#### 1.17.9 INP（交互下一帧延迟）——echarts setOption 冻主线程

**问题**：`chart.setOption(big)` 同步 60–200ms，用户打字 / 点击手感卡顿。Chrome 2024 起将 INP 作为 CWV。

**修正**：

1. 调用加 `lazyUpdate: true` + 拆成多次 `setOption({ series: ... }, { replaceMerge: ... })`；
2. 阅读量计算 / 大表计算下沉 Web Worker（vite-plugin-comlink）；
3. 点击后先反馈（骨架 / 占位符）再加载数据；
4. 重业务交互加 `requestIdleCallback`（iOS 16.4+ 已支持，其余场景 polyfill 为 `setTimeout 1ms`）。

#### 1.17.10 备案 / 合规提示 / Cookie 提示条

**问题**：工信部 ICP 备案号应在 footer 显示，金融产品同时需**「投资有风险」**提示。手机顶部 / 底部 fixed 布局下需手动预留位置。

**修正**：全局 [components/AppFooter.vue](quantia/fontWeb/src/components/AppFooter.vue) 在默认布局下根部。手机端折叠到 `<details>`，抽屉 / 设置 中永久可见。

```html
<footer class="app-footer">
  【风险提示】本产品仅供量化研究使用，不构成投资建议。市场有风险，投资需谨慎。
  <span>© 2026 Quantia</span>
  <a href="https://beian.miit.gov.cn">京ICP备00000000号</a>
</footer>
```

#### 1.17.11 用户隐私与 PIPL《个人信息保护法》交互

**问题**：项目可能记录用户设备信息、IP、访问日志用于风控。**PIPL** 要求：首次访问需咨询同意，且提供「查询 / 删除」接口。

**修正**：首次访问弹 [components/PrivacyConsent.vue](quantia/fontWeb/src/components/PrivacyConsent.vue) 底部提示条，仅在 「同意」后写入 `localStorage.privacyConsentVersion`；未同意前**不加载**任何第三方设备指纹 / 打点。

```ts
if (!localStorage.getItem('privacyConsentVersion=2026-05')) {
  // 仅加载必要资源，不发送 RUM，不收集设备指纹
}
```

#### 1.17.12 反静默接管 / 反被隐藏起股价

**问题**：个别微信插件 / 广告屏蔽插件会注入 CSS 隐藏 `.price`/`.candle-up` 类，导致股价空白。另：部分国产手机被静默代理注入「中间层 toolbar」 压住底部 50px。

**修正**：
- 不要使用「语义名」类名（如 `.ad`、`.price`）作为**唯一**显示控制；加一个稳定哈希后缀（Vite 已为 CSS module hash）。
- 业务不应依赖语义化类名。 不要选 `.ad-card` `.banner` 这种词。
- 底部 fixed 到 `bottom: max(8px, env(safe-area-inset-bottom))` 同时加 `min-height` 并做遮挡检测：
  ```ts
  // 启动后检测底部裁切
  const test = document.querySelector('.app-footer-sentinel')
  if (test && test.getBoundingClientRect().bottom > window.innerHeight) {
    document.documentElement.style.setProperty('--proxy-pad', '50px')
  }
  ```

---

### 1.18 第六轮审查补遗（**v2.0 新增**）

本轮针对 2026-05-11 至 2026-05-20 期间新增的功能模块、已有响应式代码的评估修正、以及被前五轮遗漏的技术债务进行扫描。

#### 1.18.1 验证中心 4 页面 + AI Agent 管理移动端适配需求

[quantia/fontWeb/src/views/verify/](quantia/fontWeb/src/views/verify/) 目录包含 4 个高复杂度分析页面，均为近期新增。其中 **3 个已有初步响应式 CSS**（grid 单列化），但仍不足以支撑完整移动端体验；另有 [algo/agent-manager.vue](quantia/fontWeb/src/views/algo/agent-manager.vue) 是 AI Agent CRUD 管理页（7 列表格），完全无响应式：

| 页面 | 文件 | 核心布局 | 已有响应式 | 移动问题 |
|---|---|---|---|---|
| 策略对比 | `verify/compare.vue` | 多策略并排表 + echarts NAV 对比图 | ❌ 无 | 并排列数溢出；图表硬编码高度 |
| 因子实验室 | `verify/factorLab.vue` | 3 维参数面板 + 收益热力图 + Shapley 柱图 | ✅ 960px grid→单列 | 参数面板折叠后仍 400px 高；热力图方块过小 |
| 策略融合 | `verify/fusion.vue` | 5 维选择 + 4 模式切换 + co_occurrence 矩阵 | ✅ 960px dim-grid→单列 + kpi 两列 | 5 维选择器文字溢出；矩阵不可横向滑动 |
| 买卖点优化 | `verify/optimize.vue` | 左右分栏（参数+结果） + echarts 滚动 NAV | ✅ 1200px 侧面板折叠 | echarts 未接入 responsive hook |
| AI Agent 管理 | `algo/agent-manager.vue` | 7 列表格 + CRUD 弹窗 | ❌ 无 | 表格在 <768px 完全溢出 |

**修正策略**：

1. **optimize.vue**：已有 `@media (max-width: 1200px)` 将左侧面板折叠为顶部 collapse，✅ 方向正确。移动端追加：
   - 参数表单单列化（`<el-col :xs="24">`）
   - echarts 图表接入 `useChartResponsive`

2. **compare.vue**：
   - `xs`/`sm` 下策略对比改为**上下堆叠**（而非左右）
   - NAV 对比图接入响应式高度
   - 使用 `<el-tabs>` 切换不同策略指标，而非全部平铺

3. **factorLab.vue**：
   - ✅ 已有 960px grid→单列，保留并迁移到 `@include md-down` mixin
   - 但 `max-height: 400px` 在手机竖屏（667px）仍过高——改为 `max-height: min(400px, 50vh)`
   - 参数面板改 `<el-collapse>` 折叠（默认展开第一组）
   - 热力图在 `xs` 下切到 **数据表格视图**（热力图在 360px 下不可读）
   - Shapley 柱图高度跟 `useChartResponsive`

4. **fusion.vue**：
   - ✅ 已有 960px dim-grid 单列 + kpi 两列，保留并迁移到 mixin
   - 5 维选择器改为 `<el-steps :direction="isMobile? 'vertical' : 'horizontal'">` 分步引导
   - co_occurrence 矩阵在 `xs` 下支持 `overflow-x: auto` 横向滚动
   - 4 模式切换从 `<el-radio-group>` 改 `<el-segmented>` 防溢出

5. **agent-manager.vue**（v2.0 新增覆盖）：
   - 7 列 el-table 在 <768px 完全溢出
   - 改为 `<ResponsiveDataView>`：`primary=['name','display_name']`、`secondary=['provider','model','enabled']`
   - CRUD 弹窗改 `<ResponsiveDialog>`

#### 1.18.2 AI 聊天抽屉移动适配

[quantia/fontWeb/src/components/AiChatDrawer.vue](quantia/fontWeb/src/components/AiChatDrawer.vue) 是全局 AI 助手抽屉，从右侧滑出。当前配置 `size="55%"`（百分比宽度），含 220px 固定左侧会话列表。**移动端问题**：

| 问题 | 严重度 | 修正 |
|---|---|---|
| 抽屉 55% 宽度 + 220px sidebar 在手机上无法并排 | 🔴 高 | 移动端：`size="100%"` + sidebar 改为顶部 collapse 或 sheet |
| 内部 sidebar 220px 在 <400px 设备占满无留余内容区 | 🔴 高 | xs 下隐藏 sidebar，改为顶部 `<el-button>` 切换会话列表 |
| 输入框在键盘弹起后被遮挡 | 🟡 中 | 接入 `useVirtualKeyboard`，键盘弹起时 sticky 底部 |
| 消息列表滚动穿透到背景 | 🟡 中 | 接入 `useBodyScrollLock` |
| 长代码块不换行导致横向溢出 | 🟡 中 | `pre { white-space: pre-wrap; word-break: break-all; max-width: 100%; }` |
| AI 推荐股票列表不可点击跳转 | 🟠 低 | 点击股票代码跳 StockData 路由 |

**修正**：PR-11b 新增，专门处理 AI 抽屉 + `AiAgentPicker.vue` + `AiModelPicker.vue` 在移动端的交互。

#### 1.18.3 首页响应式代码评估（v2.0 修正）

前版本认为「首页无任何移动端适配」，实际 [home/index.vue](quantia/fontWeb/src/views/home/index.vue) 已有较完善的网格自适应：

```scss
@media (max-width: 1100px) { /* 4-col → 2-col grids */ }
@media (max-width: 600px)  { /* 2-col → 1-col; hero padding shrink */ }
```

**评估**：
- ✅ 首页是项目中移动端可用度最高的页面（~40%）
- ⚠️ 断点值（1100/600）与计划使用的 Element Plus 官方断点（768/992/1200）不对齐
- ⚠️ 仅处理了网格布局，未处理字号、间距、图表高度
- ❌ 首页大盘指数 echarts 卡片未做响应式高度

**决策**：PR-04 统一断点时**不要破坏**首页已有的适配——而是将 1100px 迁移到最近的官方断点 `992px (md)`，600px 迁移到 `768px (sm)`。迁移后做视觉回归确认。

#### 1.18.4 现有 composables/utils 对适配计划的影响

当前已存在的代码资产：

| 文件 | 作用 | 对移动适配的影响 |
|---|---|---|
| `composables/useCustomIndicatorOverlay.ts` | K 线图上叠加自定义指标信号 | 需与 `useChartResponsive` 协同——移动端 overlay 标记应缩小/简化 |
| `utils/columnTooltips.ts` | 表格列 tooltip 文案 | 移动端 `show-overflow-tooltip` 不触发 hover → 需改 click-to-expand |
| `utils/backtestDashboardLinks.ts` | 仪表盘跳转链接工具 | 无影响 |
| `utils/index.ts` | 通用工具函数 | 可在此扩展 `fmtMoneyCn` / `fmtPct` 等格式化函数 |

#### 1.18.5 Playwright 已安装但未配置

`playwright` 已在 `devDependencies`（`^1.59.1`），但项目中：
- ❌ 无 `playwright.config.ts`
- ❌ 无 `tests/visual/` 目录
- ❌ 未运行过 `npx playwright install`（浏览器二进制可能未下载）

**PR-01 前置步骤**（新增）：
```bash
cd quantia/fontWeb
npx playwright install chromium webkit  # 仅安装需要的引擎
```

并在 PR-01 中创建 `playwright.config.ts` + 桌面 baseline 截图，而非等到 PR-12。**提前建立 baseline 是零回归保障的前提**。

#### 1.18.6 Vite 配置极简——缺失的构建优化

当前 `vite.config.ts` 仅有：
- `@vitejs/plugin-vue` 插件
- `@` 别名
- dev 代理
- `outDir` / `assetsDir`

**缺失项**（按 PR 补充）：

| 缺失配置 | 影响 | 补充 PR |
|---|---|---|
| `build.target` 未指定 | 默认 `modules`（ES2020），可能包含不必要的转译 | PR-01 |
| `manualChunks` 未配置 | echarts 1.2MB 与业务代码打在同一 chunk | PR-01 |
| `chunkSizeWarningLimit` 默认 500KB | 超大 chunk 无警告 | PR-01 |
| `css.preprocessorOptions` 无全局注入 | SCSS mixin 需每个文件手动 import | PR-01 |
| 无 PostCSS / autoprefixer | 低版本浏览器 CSS 兼容性不保证 | PR-04 |
| 无 `build.modulePreload.polyfill` | 老 X5 不支持 modulepreload | PR-12 |

#### 1.18.7 路由无 scrollBehavior 与错误处理

[quantia/fontWeb/src/router/index.ts](quantia/fontWeb/src/router/index.ts) 当前配置：
- ✅ 有 Phase 8 auth guard（`beforeEach`）
- ✅ 有 404 catch-all route
- ❌ **无 `scrollBehavior`** — 路由切换后不回顶
- ❌ **无 `router.onError`** — ChunkLoadError 未捕获

这两项在 PR-04 中必须一并补上。

#### 1.18.8 全局 Icon 注册的移动端体积影响

[main.ts](quantia/fontWeb/src/main.ts) 中循环注册了**全部** `@element-plus/icons-vue`（约 280+ 图标组件），即使大部分页面只用 5-10 个。在桌面端不敏感（~50KB gzip），但在移动 4G 下构成**首屏 JS 增量**。

**修正**（PR-02 一并处理）：
- 改为按需 import：`import { Refresh, Search, Plus } from '@element-plus/icons-vue'`
- 或使用 `unplugin-icons` 自动按需加载
- 预估减重：gzip -15KB

---

## 2. 平板与手机的差异点（横竖屏 × DPR × 字号）

### 2.1 设备矩阵（**v1.1 扩充**）

| 维度 | 手机竖 (375×667) | 手机横 (667×375) | 平板竖 (768×1024) | 平板横 (1024×768) |
|---|---|---|---|---|
| 断点 | xs | xs (重要：另需 max-height 处理) | sm | md |
| Sidebar | 抽屉 | 抽屉 + 隐藏顶栏 | 抽屉 | **保留固定**（窄版 180px） |
| 顶栏高度 | 50px | **36px**（max-height≤480 起作用） | 50px | 50px |
| 列数 | 1 列 | 1 列 | 2 列 | 2–3 列 |
| 表格 | 卡片 | 卡片 + 横向滚动 | 表格（隐藏次要列） | 表格（完整列） |
| K 线高度 | 280px | **计算 = 100dvh - 50** | 380px | 480px |
| 弹窗 | min(桌面宽, 92vw) | min(桌面宽, 88vw) | 80vw | 60vw |
| 字号基准 | 14px | 14px | 14px | 15px |
| 表单标签 | top | top | top | right (label-width=120) |
| dataZoom | inside | inside | inside + slider | slider |

### 2.2 DPR 与设备可读性关系

| DPR 范围 | 代表设备 | 字号默认表现 | 需要采取的动作 |
|---|---|---|---|
| < 1.5 | 桌面、老平板 | 清晰 | 不动作 |
| 1.5–2 | iPad mini、iPhone SE | 清晰 | 不动作 |
| 2.5–3.5 | 中高端 Android 手机 | 文本偏细 | echarts 纯 canvas + DPR 截断 2.5 |
| > 3.5 | 旗舰上限 | 文本偏细，canvas 超出 GPU 限制 | DPR 截断 2.5，隐藏复杂叠加层 |

### 2.3 横屏特殊处理（**重点**）

```scss
// _mobile-mixins.scss
@mixin landscape-phone { @media (orientation: landscape) and (max-height: 480px) { @content; } }
@mixin portrait-phone { @media (orientation: portrait) and (max-width: 767px) { @content; } }
```

- **手机横屏键盘弹起**：viewport 高度极短（约 200px）。需 `@include landscape-phone` 压缩头部到 36px、表单取消边距。
- **K 线横屏全屏手势**（仅手机）：双击 K 线区进入“全屏阅读”模式（隐藏 Sidebar / Navbar）；横跳时自动恢复。
- **平板横屏**：视为小桌面 (md)，不走抽屉、不走卡片，仅压缩字号 1px。

### 2.4 字号映射（`clamp()` 统一策略）

| 区域 | 全部断点公式 |
|---|---|
| 根字号 (`html`) | `clamp(13px, 0.875rem + 0.1vw, 17px)` |
| 表格表头 | `clamp(12px, 0.8rem, 14px)` |
| K 线轴标签 | xs:10 / sm:11 / md:12 / lg:12 （不跟 html font-size） |
| 主按钮 | xs:14 / md:14 / lg:14 （不变，保证点击区⍥2×2mm） |
| 对话框标题 | xs:16 / md:18 |

---

## 3. 改造方案（6 阶段 / 14 PR）

### 阶段 0 — 基础设施（**先决条件**，2 PR）

#### PR-01：响应式基础（**桌面端零改动**）

**新增文件**：

```
quantia/fontWeb/src/composables/useResponsive.ts        # 断点 hook
quantia/fontWeb/src/composables/useChartResponsive.ts   # 图表 hook
quantia/fontWeb/src/styles/_breakpoints.scss            # SCSS 变量 + mixin
quantia/fontWeb/src/styles/_mobile-vh.scss              # 100dvh 兼容层
```

```ts
// useResponsive.ts
import { computed } from 'vue'
import { useBreakpoints, useMediaQuery } from '@vueuse/core'
const bps = useBreakpoints({ xs: 0, sm: 768, md: 992, lg: 1200, xl: 1920 })

// 如果设备为高 DPR（调用者使用「全局字号」放大）也计为移动端。
export const isLargeText = useMediaQuery('(min-resolution: 1.5dppx) and (max-width: 1024px)')

export const isMobile = computed(() => bps.smaller('sm').value || isLargeText.value)
export const isTablet = computed(() => bps.between('sm', 'lg').value && !isLargeText.value)
export const isDesktop = computed(() => bps.greater('md').value && !isLargeText.value)

export const currentBp = computed<'xs' | 'sm' | 'md' | 'lg'>(() =>
  isMobile.value ? 'xs'
    : bps.between('sm', 'md').value ? 'sm'
      : bps.between('md', 'lg').value ? 'md'
        : 'lg'
)
```

**修改文件**：
- [main.ts](quantia/fontWeb/src/main.ts)：仅注入 `<html data-bp="...">` 属性（基于 `currentBp` watch），不再需要 `--vh` JS 注入
- [vite.config.ts](quantia/fontWeb/vite.config.ts)：`manualChunks` 拆 echarts/element-plus/vendor
- `package.json`：新增 `@vueuse/core`（若未在）

**桌面端影响**：⚠️ 0%。仅新文件 + 全局变量注入，不修改任何现有组件。

#### PR-02：Element Plus 按需引入（**预计 bundle -50%**）

- 引入 `unplugin-auto-import` + `unplugin-vue-components`
- 移除 [main.ts#L18](quantia/fontWeb/src/main.ts#L18) 的全量 `import ElementPlus`
- 保留全局 CSS（避免按需引入的样式抖动）
- 跑 Vitest 单测 + 启动 dev 服 + Playwright 截图比对

**风险**：Element Plus 全局组件（如 `ElMessage` / `ElMessageBox` / `ElLoading`）需显式注册。

### 阶段 1 — Layout 自适应（2 PR）

#### PR-03：Layout / Sidebar / Navbar

- [layout/index.vue](quantia/fontWeb/src/layout/index.vue)：`<md` 时 Sidebar 改为 `<el-drawer direction="ltr" :size="240">`
- [Sidebar.vue](quantia/fontWeb/src/layout/components/Sidebar.vue)：内部 menu 不变；移动端关闭后自动 collapse 菜单
- [Navbar.vue](quantia/fontWeb/src/layout/components/Navbar.vue)：
  - 移动端隐藏 GitHub link + Refresh icon
  - 保留汉堡菜单 + breadcrumb（仅最后一级）+ 用户头像
- 全局 padding：`md+ 20px / sm 16px / xs 12px`

#### PR-04：全局 ConfigProvider + 100dvh 替换 + 字号系统（**v1.1**）

- [App.vue](quantia/fontWeb/src/App.vue)：`<el-config-provider :size="isMobile? 'small' : 'default'">`
- 全项目 `100vh` → `100dvh`（代码中 7+ 处，见 §1.2 表格）
- 新增 [src/styles/_mobile-vh.scss](quantia/fontWeb/src/styles/_mobile-vh.scss) 作为 `@supports not (height: 100dvh)` 兜底
- 新增 [src/styles/_typography.scss](quantia/fontWeb/src/styles/_typography.scss)：
  - `html { font-size: clamp(13px, 0.875rem + 0.1vw, 17px); }`
  - 全局字体栈补全安卓同源字体（见 §1.10 问题 1）
  - `xs` 下输入框字号 ≥ 16px（防止页面缩放）（见 §1.10 问题 4）
- 表单 label-position：`isMobile? 'top' : 'right'`（通过 ConfigProvider 或单组件）
- 新增 [src/composables/useVirtualKeyboard.ts](quantia/fontWeb/src/composables/useVirtualKeyboard.ts)（见 §1.13），在 `register.vue` / `login.vue` / `paper-trading` 表单开启

### 阶段 2 — 表格与卡片视图（最大工作量，4 PR）

#### 通用组件设计：`<ResponsiveDataView>`

```vue
<!-- src/components/ResponsiveDataView.vue -->
<template>
  <template v-if="isDesktop">
    <el-table v-bind="$attrs"> <slot /> </el-table>
  </template>
  <template v-else>
    <div class="rdv-cards">
      <div v-for="row in data" :key="row[rowKey]" class="rdv-card"
           @click="$emit('row-click', row)">
        <div class="rdv-card-primary">
          <span v-for="k in primary" :key="k">{{ row[k] }}</span>
        </div>
        <div class="rdv-card-secondary">
          <span v-for="k in secondary" :key="k">
            <i>{{ columnLabel(k) }}</i>{{ row[k] }}
          </span>
        </div>
        <el-button v-if="detail?.length" link @click.stop="toggle(row)">
          {{ expanded[row[rowKey]] ? '收起' : '详情' }}
        </el-button>
        <div v-if="expanded[row[rowKey]]" class="rdv-card-detail">
          <span v-for="k in detail" :key="k">
            <i>{{ columnLabel(k) }}</i>{{ row[k] }}
          </span>
        </div>
      </div>
    </div>
  </template>
</template>
```

#### PR-05：StockData.vue（影响 20+ 路由）
[quantia/fontWeb/src/views/stock/StockData.vue](quantia/fontWeb/src/views/stock/StockData.vue)：
- `primary=['name','code']`、`secondary=['change_pct','close']`、其余进入详情展开
- 分页栏移动端 `:small="true" :pager-count="5"`

#### PR-06：回测列表与 Dashboard
- [algo/backtest-list.vue](quantia/fontWeb/src/views/algo/backtest-list.vue)：16 列 → 卡片
- [backtest/dashboard.vue](quantia/fontWeb/src/views/backtest/dashboard.vue)：4 个 inline form 改 `<el-form label-position="top">`；4 张表格 → `ResponsiveDataView`

#### PR-07：模拟盘
- [paper-trading/index.vue](quantia/fontWeb/src/views/paper-trading/index.vue)：
  - 指标条 → `<el-row :gutter="8"><el-col :xs="12" :sm="6">`
  - 主表 11 列 / 持仓 12 列 → 卡片
  - 整理 3 个 dialog 宽度统一规则

#### PR-08：设置页面
- [settings/users.vue](quantia/fontWeb/src/views/settings/users.vue)
- [settings/audit.vue](quantia/fontWeb/src/views/settings/audit.vue)
- [settings/im-commands.vue](quantia/fontWeb/src/views/settings/im-commands.vue)
- [settings/im-operator.vue](quantia/fontWeb/src/views/settings/im-operator.vue)
- [settings/ai-config.vue](quantia/fontWeb/src/views/settings/ai-config.vue)
- [settings/notification.vue](quantia/fontWeb/src/views/settings/notification.vue)
- [settings/live-trading.vue](quantia/fontWeb/src/views/settings/live-trading.vue)

### 阶段 2.5 — 验证中心适配（**v2.0 新增**，1 PR）

#### PR-08b：验证中心 4 页面（**v2.0 新增**）

验证中心是 Phase 7–8 新增的高价值区域，需单独 PR 确保覆盖。

- [verify/optimize.vue](quantia/fontWeb/src/views/verify/optimize.vue)：
  - 保留已有 1200px 断点；统一迁移到 `@include md-down` mixin
  - 参数表单 `<el-col :xs="24" :sm="12">`
  - 结果 echarts 接入 `useChartResponsive`
- [verify/compare.vue](quantia/fontWeb/src/views/verify/compare.vue)：
  - 策略对比表：`xs` 下用 `<el-tabs>` 切换不同策略（而非并排）
  - NAV 对比图：移动高度 220px、桌面 400px
  - 统计指标卡改 `<el-row :gutter="8"><el-col :xs="12" :sm="6">`
- [verify/factorLab.vue](quantia/fontWeb/src/views/verify/factorLab.vue)：
  - 已有 960px grid→单列，保留并迁移到 `@include md-down` mixin
  - 参数三组（tech/fund/flow）改 `<el-collapse>`，移动端默认折叠
  - 热力图：`xs` 下切到排序表格视图（热力图 <360px 不可读）
  - Shapley 柱图高度 `xs:180 / sm:260 / lg:360`
- [verify/fusion.vue](quantia/fontWeb/src/views/verify/fusion.vue)：
  - 已有 960px dim-grid/kpi 响应式，保留并迁移到 mixin
  - 5 维选择器 `xs` 下改 `<el-steps direction="vertical">` 分步填写
- [algo/agent-manager.vue](quantia/fontWeb/src/views/algo/agent-manager.vue)：
  - 7 列表格无任何响应式，`xs` 下改 `<ResponsiveDataView>`
  - CRUD 弹窗宽度统一为 `min(桌面宽, 92vw)`
  - 4 模式切换改 `<el-segmented>`
  - co_occurrence 热力图容器加 `overflow-x: auto; -webkit-overflow-scrolling: touch;`
  - vote_threshold 等参数表单单列化

### 阶段 3 — 图表与详情页（2 PR）

#### PR-09：K 线与指标（**v1.1 深化**）
- [indicator/index.vue](quantia/fontWeb/src/views/indicator/index.vue)：
  - 引入 `useChartResponsive`，移除手动 resize 监听（修复 §1.3 缺陷 2）
  - `echarts.init` 加 `devicePixelRatio: Math.min(window.devicePixelRatio, 2.5)` + `useDirtyRect: true`（修复 §1.3 缺陷 5）
  - 高度规则：`xs 280 / sm 380 / md 520 / lg 680`，启用副指标时 +100
  - 副指标选择器移动端改 `<el-segmented>` **单选**（修复 §1.3 缺陷 7）
  - 加 `dataZoom: [{ type: 'inside' }, ...isDesktop && [{ type: 'slider' }]]`（修复 缺陷 6）
  - 手机默认 `dataZoom.start: 70`，桌面 0
  - 横屏专属：`@include landscape-phone` 隐藏所有非图表元素 + Sidebar/Navbar 隐藏 + chart `height: calc(100dvh - 40px)`
  - 在 `useChartResponsive.fontSize` 下传 `xs: 10 / sm: 11 / md: 12 / lg: 12`（轴标签不跟随用户缩放，见 §1.10 问题 2）

#### PR-10：回测详情 / Compare / Edit
- [algo/backtest-detail.vue](quantia/fontWeb/src/views/algo/backtest-detail.vue)：
  - 4 tabs 保留，移动端改 `<el-segmented>` 或简化为 collapse
  - 内部 echarts `grid.left/right` 改为响应式（`left: isMobile? 36 : 58`）
  - 持仓表 → `ResponsiveDataView`
- [algo/edit.vue](quantia/fontWeb/src/views/algo/edit.vue)：
  - 分屏在 `<md` 改 tab 切换（代码 / 结果）
  - 工具栏 `<el-button-group>` 移动端竖排
- [algo/backtest-compare.vue](quantia/fontWeb/src/views/algo/backtest-compare.vue)：
  - 行编辑器（每行 4 个输入）移动端改 `<el-collapse>` 折叠

### 阶段 4 — 表单 / 弹窗收尾（1 PR）

#### PR-11：弹窗与表单统一
- 所有 `el-dialog width` 改为 `min(<desktop>, 92vw)` 风格；删除残留 `92vw` 单独写法
- 所有 `el-popover :width=` 改为 `Math.min(<desktop>, window.innerWidth * 0.9)`
- 所有 `label-width="..."` 在移动端 `label-position="top"` 后自动失效（无需逐个改）
- 登录页 / 注册页 padding 调整

#### PR-11b：AI 聊天抽屉移动适配（**v2.0 新增**）
- [components/AiChatDrawer.vue](quantia/fontWeb/src/components/AiChatDrawer.vue)：
  - 抽屉宽度：`min(480px, 100vw)`（手机全屏展开）
  - 消息列表 `max-height: calc(100dvh - 140px)`
  - 输入框接入 `useVirtualKeyboard`，键盘弹起时 sticky 定位
  - 代码块 `pre { white-space: pre-wrap; overflow-x: auto; }`
  - 接入 `useBodyScrollLock` 防背景穿透
- [components/AiAgentPicker.vue](quantia/fontWeb/src/components/AiAgentPicker.vue)：
  - `xs` 下改为底部 sheet（`<el-drawer direction="btt" :size="'60%'">`）
- [components/AiModelPicker.vue](quantia/fontWeb/src/components/AiModelPicker.vue)：
  - 同上，底部 sheet 展示模型列表

### 阶段 5 — 性能 / 测试 / 文档（1 PR）

#### PR-12：收尾
- vite manualChunks 配置最终调优：
  ```ts
  manualChunks: {
    'vendor-vue': ['vue', 'vue-router', 'pinia'],
    'vendor-element': ['element-plus', '@element-plus/icons-vue'],
    'vendor-echarts': ['echarts'],
    'vendor-utils': ['axios', 'dayjs', '@vueuse/core'],
  }
  ```
- ~~新增 [quantia/fontWeb/playwright.config.ts](quantia/fontWeb/playwright.config.ts)~~ → **已提前至 PR-01**
- 新增 `tests/visual/desktop.spec.ts`、`tests/visual/mobile.spec.ts`、`tests/visual/tablet.spec.ts`
- 视觉回归 baseline：1920×1080 / 1024×768 / 768×1024 / 375×667 / 667×375
- [README.md](README.md) 增加移动端使用说明
- `@vitejs/plugin-legacy` 配置老 X5 兼容
- `size-limit` + `web-vitals` 性能预算集成

---

## 4. 零桌面端回归保障（**三重锁**）

### 锁 1：CSS 媒体查询「只增不改」
- 全项目当前有 **6 处** `@media`（跨 5 个文件），将统一替换为 `@include mobile-only { ... }` mixin：
  - `home/index.vue`：1100px / 600px（网格 4→2→1 列）
  - `verify/optimize.vue`：1200px（侧面板折叠）
  - `verify/factorLab.vue`：960px（grid → 单列）
  - `verify/fusion.vue`：960px（dim-grid 单列 + kpi 两列）
  - `paper-trading/index.vue`：900px（布局简化）
- 所有新增样式必须包裹在 `@include xs-only / sm-only / md-down / lg-up` 中。
- ESLint stylelint 规则禁止直接写 `@media (max-width: xxx)`，强制走 mixin。

### 锁 2：组件级 `v-if="isDesktop"` 隔离
- 表格 / 表单 / 图表均通过 `<ResponsiveDataView>` 等包装器；
- 桌面分支与移动分支为**两套独立模板**，移动端 bug 不会渗透到桌面端模板。

### 锁 3：Playwright 视觉回归
- 每个 PR 必须通过 1920×1080 桌面端截图对比，pixelmatch 误差 ≤ 1%；
- baseline 在 PR-01 之前生成（即"当前桌面端"），后续所有 PR 必须保持此 baseline 不变。

### 紧急回滚机制
- 新增前端配置 `localStorage.setItem('quantia.forceDesktop', '1')`，强制走桌面端布局；
- 后端注入环境变量 `QUANTIA_FORCE_DESKTOP=1` 时通过 `<html data-force-desktop>` 全局短路所有 `@include mobile-only`。

---

## 5. 兼容性矩阵（**v1.1 收紧**）

| 浏览器 / WebView | 最低版本 | 验证项 |
|---|---|---|
| iOS Safari / WKWebView | **iOS 16.0+** | dvh / ResizeObserver / visualViewport / `:has()` |
| Android Chrome | **Android 11 + Chromium 108+** | 同上 |
| 微信内置 (X5) Android | TBS ≥ 6013（等同 Chromium 86） | dvh 退化到 vh；visualViewport 可用 |
| QQ 内置 Android | Chromium 100+ | 同上 |
| 钉钉 / 抖音 / 快手 WebView | Chromium 100+ | 同上 |
| 华为 Petal Browser (HarmonyOS 4+) | Chromium 119+ | 全部 |
| 小米 MIUI 浏览器 | Chromium 120+ | 全部 |
| Vivo / OPPO / 三星 Internet | Chromium 122+ | 全部 |
| UC 浏览器（U4 内核） | ⚠️ 全面不保证 | 仅限于 dvh / canvas DPR 弱兼容 |
| 桌面 Chrome / Edge / Firefox / Safari | 当前-2 版本 | 视觉回归 ≤ 1% |

**不再支持**（明确退包）：
- iOS ≤ 15.x（需要 `--vh` JS 兜底的场景）
- Android ≤ 10（Chromium ≤ 87 不支持 `:focus-visible` 例外、`logical CSS`）
- 任何 IE / 老版 EdgeHTML

**遇上不支持的设备的产品定义**：提示「建议升级浏览器」，不保证体验但不会白屏（`@supports` 退化布局）。

### 验证设备参考（**v1.1 新增**）

最低要覆盖以下设备（手动 × BrowserStack × Playwright Emulation）：

| 设备 | 屏幕 | DPR | 系统 | 浏览器 |
|---|---|---|---|---|
| iPhone 13/14 mini | 360×780 | 3 | iOS 16+ | Safari + 微信 |
| iPhone 15 Pro | 393×852 | 3 | iOS 17+ | Safari + 微信 |
| iPad mini 6 | 744×1133 | 2 | iOS 16+ | Safari |
| Pixel 7 | 412×915 | 2.625 | Android 13+ | Chrome + 微信 |
| Galaxy S23 | 412×915 | 3 | Android 13+ | Samsung Internet + 微信 |
| HUAWEI P60 | 393×820 | 3.5 | HarmonyOS 4 | Petal + 微信 |
| Xiaomi 14 | 393×873 | 3 | HyperOS 1 | MIUI + 微信 |
| iPad Pro 11 | 834×1194 | 2 | iPadOS 16+ | Safari |

---

## 6. 风险登记册（**v1.1 重排 + 新增 Android / 字号 / 图表项**）

| # | 风险 | 等级 | 影响 | 缓解 |
|---|---|---|---|---|
| R1 | StockData.vue 是 20+ 路由的核心，改动易回归 | 🔴 高 | 整套综合选股不可用 | 单测 + Playwright 截图全部 20 路由 |
| R2 | iOS / Android 老 X5 100vh 散布 7+ 处 | 🔴 高 | 关键页面顶/底部错位 | PR-04 统一 `100dvh` 替换 + `_mobile-vh.scss` 补丁 |
| R3 | echarts grid `left/right` px 硬编码 | 🟡 中 | 子图被压扁 | useChartResponsive 重写 grid |
| R4 | echarts canvas 在 DPR≥3 设备上独佔 256MB GPU | 🔴 高 | Android 白屏 / 崩溃 | DPR 截断 2.5，ulpDirtyRect=true |
| R5 | Android `visualViewport` 不被处理 | 🔴 高 | 表单输入被键盘遮挡 | useVirtualKeyboard 创建与应用 |
| R6 | Element Plus 按需引入触发样式抖动 | 🟡 中 | 主题色变 | 保留全局 CSS 入口 |
| R7 | 横屏键盘弹起 viewport 紊乱 | 🟡 中 | 表单错位 | `landscape-phone` mixin + visualViewport |
| R8 | Element Plus `el-table-column fixed` 在移动端 bug | 🟡 中 | 列错位 | 移动端禁用 `fixed`（走卡片视图） |
| R9 | 安卓用户系统字号缩放 200% 破坏布局 | 🟡 中 | 顶栏、对话框溢出 | `clamp()` 限定 + DPR 作为 `isMobile` 补充信号 |
| R10 | UC / U4 内核强制 DPR=1 | 🟠 低 | 高分辨率浏览器上 K 线模糊 | 提示升级浏览器；不专项优化 |
| R11 | 微信内置浏览器各版本 X5 差异 | 🟡 中 | 部分页面不一致 | UA 判断 + dvh fallback + 手机 + iPad 实机验收 |
| R12 | iOS 输入框字号 < 16px 自动页面缩放 | 🟡 中 | 输入体验烂 | 全局输入框字号 ≥ 16px |
| R13 | Pinia store 后台丢失 | 🟠 低 | 重新登录 | bootstrap 失败缓存 + 静默续登 |
| R14 | autoprefixer 默认 target 偏严 | 🟠 低 | 部分 CSS 不生效 | `.browserslistrc`: `last 2 versions, iOS >= 16, Android >= 11, not dead` |
| R15 | 路由 beforeEach 阻塞慢网 | 🟠 低 | 切页转圈 | bootstrap 3s 超时 |
| R16 | 视觉回归 baseline 体积大 | 🟠 低 | 仓库膨胀 | Git LFS 或 CI 存储，不入仓 |
| R17 | unplugin-vue-components 与现有手动 import 冲突 | 🟠 低 | 编译错误 | PR-02 单独验证 |
| R18 | Playwright 在 Windows 上不稳定 | 🟠 低 | CI 偶发 fail | 走 Linux runner |
| R19 | HarmonyOS Petal `ResizeObserver.contentRect` 偶返 0 | 🟠 低 | 首帧图表不渲染 | 代码里 fallback `el.clientHeight` / `clientWidth` |
| R20 | 三星 Samsung Internet 默认调高颜色饱和度 | 🟠 低 | 涨跌颜色偏艳 | 使用 P3 色域 + 颜色不作为唯一区分信号（加箭头/纹理） |
| R21 | 未适配 safe-area-inset，底部手势条/刘海/灵动岛遮挡 | 🔴 高 | 头部被遮挡、底部按钮点击穿透 | §1.14.1 `viewport-fit=cover` + `env(safe-area-*)` |
| R22 | 微信/MIUI/EMUI 自动暗黑反色倒转红涨绿跌 | 🔴 高 | 金融色表严重误导 | `<meta name="darkmode">` + `forced-color-adjust:none` + 主色强制 `!important` |
| R23 | 中文输入法合成期间误触发 @input | 🟡 中 | 搜索空打、首拼被吃 | composition events 处理（§1.14.4） |
| R24 | iOS / X5 dialog 背景滚动穿透 | 🟡 中 | 体验烂、误触下拉刷新 | useBodyScrollLock（§1.14.7） |
| R25 | 折叠屏 fold 切换重渲染4–5 次卡顿 | 🟠 低 | 动画闪烁 | useFoldable 节流 + horizontal-viewport-segments |
| R26 | 弱网 / 后台轮询不适配 | 🟡 中 | 弱网用户费流量、后台不刷新 | useNetwork + visibility 自适应轮询（§1.14.9） |
| R27 | 未加 `inputmode`，数字表单出全键盘 | 🟡 中 | 输入效率低 | 统一按 §1.14.5 表补全 |
| R28 | 未设 `autocomplete`，钥匙串 / 短信验证码 OTP 不生效 | 🟡 中 | 登录重复输入 | §1.14.12 补上 `username` / `current-password` / `one-time-code` |
| R29 | 鸿蒙 NEXT ArkWeb 不是 Chromium，IO/RO 偏差 | 🟡 中 | P70/Mate60 实机崩 | UA 检测后降级阈值与 fallback contentRect |
| R30 | 360/QQ/搜狗 桌面双核在 IE 模式下打开项目 | 🟠 低 | 白屏 | `<meta renderer=webkit>` + ESM 能力检测跳升级页 |
| R31 | ChunkLoadError（镜像更新后老会话跳路由白屏） | 🔴 高 | 移动端会话保持长，严重影响 | router.onError + location.replace + CDN 保留老 chunk |
| R32 | WebSocket 后台被切后不重连 | 🟡 中 | 行情假实时 | useStableSocket + visibility 控制 + 25s heartbeat |
| R33 | el-message 被刘海/灵动岛/状态栏遮挡；el-notification 超屏 | 🟡 中 | 提示看不到 | offset 动态 + msg-mobile 全局样式 |
| R34 | a11y / 读屏器焦点陷阱 / icon 按钮无 aria-label | 🟡 中 | 安卓 TalkBack 不可用 | focus-trap + aria-label + canvas role=img |
| R35 | 抽屉打开后主区变窄但视口未变，表格不切卡片 | 🟠 低 | 布局不佳 | @container 查询代替视口断点 |
| R36 | 自定义下拉刷新与原生手势冲突 | 🟠 低 | 双重刷新 | 不做自定义 PtR，仅底部上拉加载 |
| R37 | 桌面自定义 6px 滚动条在 X5 占据表格右侧 | 🟠 低 | 右列被遮 | xs 下隐藏 scrollbar |
| R38 | 首屏 LCP 3-5s 期间白屏，金融不友好 | 🟡 中 | 用户流失 | inline 骨架屏 index.html 中内嵌 |
| R39 | 软键盘弹起时 fixed 表单不上移 | 🟡 中 | 用户体验 | viewport interactive-widget=resizes-content + visualViewport |
| R40 | 股票代码复制需双击选中，手机上体验差 | 🟠 低 | 操作不便 | .copyable + 点击复制提示 |
| R41 | Vue 未设 errorHandler，移动端崩溃无从考查 | 🟡 中 | 后果未知 | app.config.errorHandler + 限流上报 |
| R42 | localStorage QuotaExceededError，老 X5 5MB、隐私模式 0 | 🟡 中 | 设置保存失败报错 | safeStorage 包装层 + 自动清理缓存 |
| R43 | 微信跳转进来 SameSite=Lax cookie 丢 | 🟡 中 | 首次请求失败 | 后端 Set-Cookie SameSite=None+Secure + Lax 双份 |
| R44 | 严格 CSP 下骨架屏 inline style 被拦 | 🟠 低 | 首屏无骨架屏 | 骨架屏提取到 public/skeleton.css |
| R45 | 老 X5 不支持 modulepreload | 🟠 低 | 首屏多一轮 RTT | vite modulePreload.polyfill + plugin-legacy |
| R46 | echarts 路由切换未 dispose，手机连续看股 OOM | 🔴 高 | Tab 被重载 / 崩溃 | onBeforeUnmount + onDeactivated 中 safeDispose |
| R47 | 不尊重 prefers-reduced-motion / data | 🟡 中 | 老人眩晕、费流量 | 全局 @media + echarts animation 开关 + 轮询打折 |
| R48 | 多标签页登录状态不同步 | 🟡 中 | A 退出 B 仍发请求 | BroadcastChannel 广播 login/logout |
| R49 | 浮点误差 + 万亿单位未适配 | 🔴 高 | 金额误差 0.01 | decimal.js-light + fmtMoneyCn / fmtPct 除负零 |
| R50 | 红绿色盲不能辨别涨跌 | 🟡 中 | 4-6% 男性用户 | colorMode 三选 + 箭头符号 + 微纹理 |
| R51 | el-date-picker / el-select 在手机上不友好 | 🟡 中 | 交互低效 | 手机切原生 input type=date + popper strategy:fixed |
| R52 | ResizeObserver loop 全局错误上报 | 🟠 低 | Sentry 警报 | window.error 手动 stopImmediatePropagation |
| R53 | 微信分享无标题/描述/封面 | 🟠 低 | 传播差 | og:* meta + router.afterEach title + wx-share |
| R54 | 无打印样式，输出 PDF 含 Sidebar | 🟠 低 | 报告奇丑 | _print.scss + .printable / .no-print |
| R55 | 路由后页面不回顶，手机从底部跳新页 | 🟠 低 | 迷失方向 | scrollBehavior 回顶 + Logo 双击顶回 |
| R56 | 表单 Enter 默认刷新，手机键盘不出「搜索」 | 🟠 低 | 体验不佳 | @submit.prevent + native-type=submit + enterkeyhint |
| R57 | 动态路由加载失败 URL 与内容不一致 | 🟡 中 | 返回丢位 | App.vue Suspense + 连续错误跳错误页 |
| R58 | iOS `new Date('YYYY-MM-DD')` 被解为 UTC，K 线偏一天 | 🔴 高 | 跨时区用户数据错 | parseDateCN + Asia/Shanghai 统一 |
| R59 | setInterval 后台丢帧 / 多页重复调同一 API | 🟡 中 | 股价闪烁、限流 | useScheduler 全局 rAF + visibility 暂停 |
| R60 | 连击股票后发的响应被先发覆盖 | 🔴 高 | 股名与 K 线不匹配 | useLatest seq + AbortController |
| R61 | 微信/iOS 下单重复提交 + csrf 待机过期 | 🟡 中 | 重复交易 / 403 | useLock + useIdle + axios 重试 refresh-csrf |
| R62 | iPhone HEIC / 安卓大图 / 微信 accept | 🟡 中 | 上传失败 | useImageUpload heic2any + canvas 压缩 + accept 明确 mime |
| R63 | iOS Safari `<a download>` 在微信不生效 | 🟠 低 | 导出失效 | utils/download FileReader 化 dataURL fallback |
| R64 | 无性能预算 / RUM，bundle 静默膨胀 | 🟡 中 | 首屏逐渐变慢 | size-limit + web-vitals 上报 |
| R65 | CLS 偏移（骨架到真实、图片、表格） | 🟡 中 | 误点击 | aspect-ratio + min-height 占位 |
| R66 | INP > 200ms（echarts setOption 大场景） | 🟡 中 | 打字卡 | lazyUpdate + Worker + requestIdleCallback |
| R67 | 未显示 ICP 备案 / 风险提示违反金融合规 | 🔴 高 | 法律风险 | AppFooter 置底固定 + 抽屉内永久可见 |
| R68 | PIPL 未同意之前上报设备指纹 | 🟡 中 | 合规风险 | PrivacyConsent 控 RUM/指纹 开关 |
| R69 | 广告过滤 / 静默代理隐藏 .price / 压住底部 | 🟠 低 | 股价丢 / 按钮被压 | hash CSS 名 + 底部哨兵 + --proxy-pad 动态 |
| **R70** | **验证中心 fusion.vue 5 维选择器在 360px 下完全溢出** | 🔴 高 | 策略融合不可用 | 手机改垂直 steps 分步（§1.18.1）|
| **R71** | **验证中心 factorLab 热力图在小屏不可读** | 🟡 中 | 因子分析体验差 | xs 切到数据表格视图 |
| **R72** | **AI 聊天抽屉宽度超出手机屏** | 🟡 中 | 抽屉无法关闭 | min(480px, 100vw) |
| **R73** | **首页已有 1100px/600px 断点与新 mixin 断点冲突** | 🟡 中 | 首页回归 | 迁移到 992px/768px 后视觉回归验证 |
| **R74** | **全量 icons 注册 +50KB gzip 拖慢首屏** | 🟠 低 | 移动首屏多 0.3s | PR-02 改按需 import |
| **R75** | **路由无 scrollBehavior + 无 onError** | 🟡 中 | 手机切页不回顶 + ChunkLoadError 白屏 | PR-04 补上 |

---

## 7. 文件清单（**完整改动面，v2.0 更新**）

### 已存在的资产（可直接利用）

```
quantia/fontWeb/src/composables/useCustomIndicatorOverlay.ts  # K 线叠加层（需与 useChartResponsive 协同）
quantia/fontWeb/src/utils/index.ts                            # 通用工具（可扩展格式化函数）
quantia/fontWeb/src/utils/columnTooltips.ts                   # 表格列 tooltip（移动端需改 click 展开）
quantia/fontWeb/src/utils/backtestDashboardLinks.ts           # 仪表盘链接
quantia/fontWeb/src/views/verify/optimize.vue                 # 已有 1200px 断点 ✅
quantia/fontWeb/src/views/verify/factorLab.vue                # 已有 960px 断点 ✅
quantia/fontWeb/src/views/verify/fusion.vue                   # 已有 960px 断点 ✅
quantia/fontWeb/src/views/home/index.vue                      # 已有 1100px/600px 断点 ✅
```

### 新增（40+ 个，v2.0 扩展）

```
quantia/fontWeb/src/composables/useResponsive.ts          # 断点 hook（含 DPR 信号）
quantia/fontWeb/src/composables/useChartResponsive.ts     # 图表 hook
quantia/fontWeb/src/composables/useVirtualKeyboard.ts     # Android 软键盘
quantia/fontWeb/src/composables/useUserAgent.ts           # WebView 检测
quantia/fontWeb/src/composables/useWeChatBridge.ts        # X5 hook + 剪贴板降级
quantia/fontWeb/src/composables/useImeAwareInput.ts       # 中文输入法合成事件
quantia/fontWeb/src/composables/useBodyScrollLock.ts      # 弹窗背景锁定
quantia/fontWeb/src/composables/useFoldable.ts            # 折叠屏
quantia/fontWeb/src/composables/useNetwork.ts             # 自适应轮询
quantia/fontWeb/src/composables/useStableSocket.ts        # WS 后台重连（§1.15.2）
quantia/fontWeb/src/composables/usePrefers.ts             # reduced-motion / reduced-data / dark（§1.16.2）
quantia/fontWeb/src/composables/useWeChatShare.ts         # 微信分享 JS-SDK（§1.16.8）
quantia/fontWeb/src/composables/useTradingClock.ts        # A 股交易时钟（§1.17.1）
quantia/fontWeb/src/composables/useScheduler.ts           # rAF 统一调度（§1.17.2）
quantia/fontWeb/src/composables/useLatest.ts              # 请求 seq + Abort（§1.17.3）
quantia/fontWeb/src/composables/useIdle.ts                # 闲置提示（§1.17.4）
quantia/fontWeb/src/composables/useImageUpload.ts         # HEIC + 压缩（§1.17.5）
quantia/fontWeb/src/components/ResponsiveDataView.vue     # 表格↔卡片切换
quantia/fontWeb/src/components/ResponsiveDialog.vue       # 统一弹窗
quantia/fontWeb/src/components/AppFooter.vue              # §1.17.10 静态 footer + 风险提示 + ICP
quantia/fontWeb/src/components/PrivacyConsent.vue         # §1.17.11 PIPL 同意条
quantia/fontWeb/src/utils/safeStorage.ts                  # §1.15.12 quota 安全封装
quantia/fontWeb/src/utils/messageMobile.ts                # §1.15.3 适配刘海/灵动岛的提示
quantia/fontWeb/src/utils/decimal.ts                      # §1.16.4 decimal.js 包装
quantia/fontWeb/src/utils/format.ts                       # §1.16.4 fmtMoneyCn / fmtPct / fmtThousand
quantia/fontWeb/src/utils/tz.ts                           # §1.17.1 上海时区 + 交易时钟
quantia/fontWeb/src/utils/download.ts                     # §1.17.6 iOS 安全下载 / CSV BOM
quantia/fontWeb/src/utils/rum.ts                          # §1.17.7 web-vitals 上报
quantia/fontWeb/src/views/error/runtime.vue               # §1.16.12 连续错误页
quantia/fontWeb/src/styles/_breakpoints.scss              # SCSS mixin
quantia/fontWeb/src/styles/_mobile-vh.scss                # @supports not (dvh) 兜底
quantia/fontWeb/src/styles/_mobile-mixins.scss            # landscape-phone / portrait-phone 等
quantia/fontWeb/src/styles/_typography.scss               # 字体栈 + clamp 根字号
quantia/fontWeb/src/styles/_safe-area.scss                # §1.14.1 安全区变量
quantia/fontWeb/src/styles/_dark.scss                     # §1.14.2 防反色
quantia/fontWeb/src/styles/_touch.scss                    # §1.14.10 tap-highlight 等
quantia/fontWeb/src/styles/_candle-color.scss             # §1.16.5 色盲三选主题
quantia/fontWeb/src/styles/_print.scss                    # §1.16.9 打印样式
quantia/fontWeb/public/skeleton.css                       # §1.15.8 / 1.15.14 骨架屏外联
quantia/fontWeb/public/browser-upgrade.html               # §1.14.14 IE 检测退入页
quantia/fontWeb/.browserslistrc
quantia/fontWeb/playwright.config.ts
quantia/fontWeb/tests/visual/desktop.spec.ts
quantia/fontWeb/tests/visual/mobile.spec.ts
quantia/fontWeb/tests/visual/tablet.spec.ts
```

### 修改（25+ 个，按 PR 分组）

| PR | 文件 |
|---|---|
| PR-01 | `main.ts`、`vite.config.ts`、`package.json`、`styles/index.scss` |
| PR-02 | `main.ts`、`vite.config.ts` |
| PR-03 | `layout/index.vue`、`layout/components/Sidebar.vue`、`layout/components/Navbar.vue` |
| PR-04 | `App.vue`、`views/login.vue`、`views/register.vue`、`views/algo/edit.vue`、`views/backtest/portfolio.vue`、`views/stock/StockData.vue`、`views/customIndicator/index.vue` |
| PR-05 | `views/stock/StockData.vue` |
| PR-06 | `views/algo/backtest-list.vue`、`views/backtest/dashboard.vue` |
| PR-07 | `views/paper-trading/index.vue` |
| PR-08b | `views/verify/compare.vue`、`views/verify/factorLab.vue`、`views/verify/fusion.vue`、`views/verify/optimize.vue`、`views/algo/agent-manager.vue` |
| PR-08 | `views/settings/*.vue`（7 个） |
| PR-09 | `views/indicator/index.vue` |
| PR-10 | `views/algo/backtest-detail.vue`、`views/algo/edit.vue`、`views/algo/backtest-compare.vue` |
| PR-11 | 全项目 `el-dialog`/`el-popover` 宽度 |
| PR-12 | `vite.config.ts`、`README.md`、`tests/visual/*` |

---

## 8. 实施排期（仅作参考，无时间承诺）

```
PR-01 → PR-04 → PR-03 → Baseline 视觉回归
                  ↓
      PR-09  +  PR-05  +  PR-07  ← 高优先并行
                  ↓
      PR-02  +  PR-06  +  PR-08b  +  PR-10  ← 中优先并行
                  ↓
      PR-11  +  PR-11b  +  PR-08  ← 收尾并行
                  ↓
              PR-12 (收尾)
```

> **v2.0 修订**：PR-02（按需引入）从阻塞路径移出——它不阻塞任何功能 PR，可在后期并行做。PR-04 提前到 PR-03 之前（安全区/字号是最小可见效果）。Playwright baseline 从 PR-12 提前到 PR-01（零回归保障前提）。

每个 PR 必须满足：
- ✅ Vitest 全绿（现有 + 新增）
- ✅ Playwright 桌面端视觉回归 diff ≤ 1%
- ✅ Playwright 移动端 / 平板端截图入库（不验收 diff，仅作 baseline）
- ✅ 手工三机型走查（小米 / iPhone / iPad）
- ✅ `npm run build`（`vue-tsc --noEmit && vite build`）必须通过

---

## 9. 验收清单（DoD）

### 桌面端（**必须零回归**）
- [ ] 1920×1080、1366×768 视觉回归 diff ≤ 1%
- [ ] 现有 8 个 Vitest 文件全绿
- [ ] 主 bundle 体积**不增**（理想减少 30%+）
- [ ] 鼠标 hover 行为不变（tooltip / 表格悬浮高亮）

### 平板端（≥ 768px）
- [ ] Sidebar 显示完整（横屏）或抽屉（竖屏）
- [ ] 所有表格列完整显示
- [ ] K 线图高度 380–480px
- [ ] 弹窗宽度 ≤ 80vw
- [ ] 无横向滚动条（首页 / 选股 / 回测列表）

### 手机端（≥ 360px）
- [ ] Sidebar 默认抽屉模式
- [ ] 主表格走卡片视图
- [ ] K 线图高度 280–360px，横屏全屏
- [ ] echarts canvas DPR 在 ≥3 设备上不崩溃（实机验收小米 14 / Pixel 7 / S23 / P60）
- [ ] 弹窗宽度 ≤ 92vw
- [ ] 登录 / 注册可在 360×640 顺利完成，软键盘弹起后表单不被遮挡（visualViewport 生效）
- [ ] 模拟盘指标条 2 列展示
- [ ] 横屏键盘弹起时表单可滚动
- [ ] iOS Safari 输入框不触发页面自动缩放（输入框字号 ≥ 16px）
- [ ] 用户系统字号 200% 下所有页面仍可读且不顶破头部 / 对话框
- [ ] iPhone 14 Pro / Mate60 / 小米 14 上头部不被刹海 / 挖孔遮挡，底部 fixed 按钮不被手势条压住（safe-area-inset 生效）
- [ ] 微信 / MIUI / EMUI 自动暗黑下，K 线红涨绿跌颜色**不被反转**
- [ ] 中文拼音输入过程中不发起搜索请求（compositionend 后才发）
- [ ] 下单 / 重设密码弹窗打开后，背景页面不跟随滚动
- [ ] 资产、价格、股数输入框弹出数字键盘，手机号弹出电话键盘，验证码可从短信自动填入（iOS）
- [ ] 折叠屏 Mate X3 / Galaxy Fold5 展开合拢不出现白屏或布局错位
- [ ] 弱网 / 3G 下轮询频率自动降为 30–60s，Wi-Fi 下 5s；后台切回立即刷一次
- [ ] 顶栏在 iPhone X / 全面屏上与状态栏同色（theme-color 生效）
- [ ] 镜像发布后，手机后台会话返回切路由不出现白屏（ChunkLoadError 被捕获且 location.replace）
- [ ] el-message / el-notification 在 iPhone 14 Pro 不被灵动岛遮挡；xs 下 notification 宽 ≤ 92vw
- [ ] TalkBack / VoiceOver 可读出所有 icon 按钮中文含义，抽屉打开后焦点陷入抽屉中
- [ ] 股票代码点击即复制（实机微信内项目与 Safari 都验证）
- [ ] localStorage 超限不崩（隐私模式下仍可使用，崩溃时自动清理 kline-cache）
- [ ] 骨架屏首屏出现 ≤ 200ms
- [ ] 镜像发布后 Vue 未捕获错误会 POST `/api/client-error` 上报（同会话 ≤ 5 次）
- [ ] **传 echarts 页面**：连续路由切换 20 次后，Chrome DevTools Memory 稳定在同一量级（无泄漏）
- [ ] 系统「减少动画」开启后，抽屉 / 弹窗 / echarts 动画均被禁用
- [ ] A 标签页退出后，B 标签页自动同步到未登录状态（BroadcastChannel）
- [ ] 金额计算不存在 0.01 浮点误差；中文「万/亿」标记在手机表格中生效
- [ ] 「色盲」模式开启后，K 线、股价背景、涨跌箭头仍可辨识
- [ ] 手机端日期输入调出原生日期选择器（可滑动选择）
- [ ] 跨时区（将手机调为 UTC）访问 K 线日期仍为实际交易日，顶部「距开盘 X 分钟」准确
- [ ] 手机锁屏 5 分钟后回前台，不出现后台补帧连发 N 次请求（useScheduler 生效）
- [ ] 连击 5 只股票，K 线不会出现「股名 ≠ 数据」的错误调度（useLatest 生效）
- [ ] 下单按钮连点仅生成一笔订单，15 分钟闲置后提交提示「资料过期请刷新」
- [ ] iPhone HEIC 照片上传后后端能展示（已转 JPEG），上传 ≤ 1MB
- [ ] iOS Safari 上「导出 CSV」不退出页面，中文不乱码
- [ ] CI 中 size-limit 不超限；web-vitals LCP ≤ 2.5s / INP ≤ 200ms / CLS ≤ 0.1（手机 4G 中位）
- [ ] AppFooter 「投资有风险」与 ICP 备案在手机 / 桌面都可见
- [ ] 首次访问未同意隐私前，不发送 RUM / 设备指纹

### 验证中心（**v2.0 新增**）
- [ ] 策略对比页在 360px 手机上不溢出，策略指标通过 tabs 切换可见
- [ ] 因子实验室参数面板在手机上可折叠展开，热力图在 xs 切到表格视图
- [ ] 策略融合 5 维选择器在手机上以垂直步骤方式展示，不超出屏幕
- [ ] co_occurrence 矩阵支持横向滚动查看
- [ ] 买卖点优化已有侧面板折叠在 1200px 下生效，手机上参数表单单列显示

### AI 功能（**v2.0 新增**）
- [ ] AI 聊天抽屉在手机上全屏展开（宽度 100vw），消息列表可正常滚动
- [ ] AI 输入框在键盘弹起时不被遮挡
- [ ] 长代码块不导致抽屉横向溢出
- [ ] Agent/Model 选择器在手机上以底部 sheet 方式展示

### 性能
- [ ] Lighthouse Mobile Performance ≥ 70（首页）
- [ ] 首屏 JS（gzip）≤ 250 KB
- [ ] FCP ≤ 2.5s @ Slow 4G

### 安全
- [ ] 触屏长按不会触发上下文菜单（除文本可选区）
- [ ] iOS Safari 双指缩放不破坏布局（保留 user-scalable）
- [ ] 移动端 localStorage 缓存不泄露 csrf_token（已通过 cookie）

---

## 10. 决策点（需用户确认）

1. **是否启用 user-scalable=1**（允许双指缩放）？
   - 推荐：✅ 启用（K 线图阅读）+ `viewport-fit=cover`（iPhone 刘海适配）。
2. **是否支持 PWA**（离线缓存 / 添加到主屏幕）？
   - 推荐：❌ 暂不（金融数据实时性要求高，缓存反而误导）。
3. **是否引入移动端专属导航（底部 TabBar）**？
   - 推荐：⚠️ 二期。先抽屉 Sidebar 验证用户接受度。
4. **是否做 i18n**？
   - 推荐：❌ 不在本次范围（当前 zh-only）。
5. **横屏 K 线全屏手势**？
   - 推荐：✅ PR-09 一并实现（仅手机端）。
6. **微信内置浏览器（X5）老版本降级策略**？（v1.1 新增）
   - 推荐：✅ 检测 `TBS/04xxxxx | TBS/05xxxxx` 时显示一次性提示「为获得更好体验请用浏览器打开」，但仍然渲染（不强制阻断）。
7. **Android 系统字号 ≥ 1.5× 时是否强制切到「卡片视图」**？（v1.1 新增）
   - 推荐：✅ 通过 `useResponsive.isLargeText` 触发，与 `isMobile` 等价处理。

---

## 11. 立即可启动的下一步

按用户偏好，从以下选项中挑选启动：

| 方案 | 内容 | 估计 PR 数 |
|---|---|---|
| **A** | 仅 PR-01 + PR-02（基础设施）| 2 |
| **B** | A + PR-03 + PR-04（Layout 完成）| 4 |
| **C** | 完整执行至阶段 2.5（表格卡片化 + 验证中心）| 10 |
| **D** | 全 14 PR 一次性完成（不推荐，回归面太大）| 14 |

**强烈推荐方案 B 起步**：可以让用户在手机上"看到效果"，但还没触及业务表格，回滚成本最低。

**v2.0 调整建议**：鉴于 9 天过去仍无实施进展，如果资源有限，建议**最小可行路径（MVP）**：

| MVP 步骤 | 内容 | 用户感知 |
|---|---|---|
| Step 1 | PR-01 中仅 `useResponsive.ts` + `_breakpoints.scss` + `.browserslistrc` + `playwright.config.ts` | 零用户感知，但解锁后续所有 PR |
| Step 2 | PR-04 中仅 `100vh→100dvh` + `viewport-fit=cover` + 字号 ≥16px | iOS 用户不再被键盘顶破、不再自动缩放 |
| Step 3 | PR-03 Layout 响应式 | 手机可打开导航 |

以上 3 步可在 **1 个合并 PR** 内完成，作为最小可交付成果。

---

## 12. 依赖安装计划（**v2.0 新增**）

### PR-01 必装

```bash
cd quantia/fontWeb
npm install @vueuse/core@^10.9.0
# devDeps
npm install -D autoprefixer postcss
```

### PR-02 必装

```bash
npm install -D unplugin-auto-import@^0.17.5 unplugin-vue-components@^0.27.0
```

### PR-05 可选（金融精度）

```bash
npm install decimal.js-light@^2.5.1
```

### PR-12 必装（性能监控 + 兼容）

```bash
npm install -D @vitejs/plugin-legacy@^5.3.0 size-limit@^11.0.0 @size-limit/preset-app@^11.0.0
npm install web-vitals@^4.0.0
```

### 按需安装（功能相关）

```bash
# 虚拟滚动（如果 StockData 列表 > 500 行需要）
npm install @tanstack/vue-virtual@^3.2.0
# HEIC 转码（如果有头像/证件上传）
npm install heic2any@^0.0.4
# 日期时区（如果需要跨时区支持）
npm install date-fns-tz@^3.1.0
```

### 版本约束

| 依赖 | 最低版本 | 原因 |
|---|---|---|
| `@vueuse/core` | 10.9+ | 需要 `useBreakpoints` + `useNetwork` + `useDocumentVisibility` |
| `unplugin-auto-import` | 0.17+ | 支持 Element Plus 2.6 resolver |
| `autoprefixer` | 10.4+ | 支持 `:has()` / `dvh` / `@container` |
| `@vitejs/plugin-legacy` | 5.3+ | 兼容 Vite 5.1 |
| `web-vitals` | 4.0+ | 支持 INP 指标（替代 FID） |

---

## 13. 实施优先级矩阵（**v2.0 新增**）

基于「用户价值 × 技术风险 × 依赖关系」重新排序实施优先级：

### Tier 1：基础解锁（必须先做，其他 PR 全部依赖）

| PR | 用户价值 | 技术风险 | 说明 |
|---|---|---|---|
| PR-01 | ⭐ | 🟢 低 | 零用户感知但解锁一切 |

### Tier 2：立即可见效果（用户最先感知）

| PR | 用户价值 | 技术风险 | 说明 |
|---|---|---|---|
| PR-04 | ⭐⭐⭐ | 🟢 低 | dvh + safe-area + 字号 = iOS 不再破布局 |
| PR-03 | ⭐⭐⭐⭐ | 🟡 中 | 手机能打开导航 = 从不可用→可用的质变 |

### Tier 3：核心体验提升（高频页面）

| PR | 用户价值 | 技术风险 | 说明 |
|---|---|---|---|
| PR-09 | ⭐⭐⭐⭐ | 🟡 中 | K 线是看盘核心 |
| PR-05 | ⭐⭐⭐ | 🟡 中 | 选股列表高频 |
| PR-07 | ⭐⭐⭐ | 🟡 中 | 模拟盘操作页 |

### Tier 4：完善覆盖

| PR | 用户价值 | 技术风险 | 说明 |
|---|---|---|---|
| PR-06 | ⭐⭐ | 🟢 低 | 回测列表 |
| PR-08b | ⭐⭐ | 🟢 低 | 验证中心（高级用户使用） |
| PR-10 | ⭐⭐ | 🟡 中 | 回测详情 |
| PR-11 | ⭐⭐ | 🟢 低 | 弹窗统一 |
| PR-11b | ⭐ | 🟢 低 | AI 抽屉 |

### Tier 5：优化与兜底

| PR | 用户价值 | 技术风险 | 说明 |
|---|---|---|---|
| PR-02 | ⭐⭐ | 🟡 中 | bundle 减重（体感加速但非功能） |
| PR-08 | ⭐ | 🟢 低 | 设置页面（低频） |
| PR-12 | ⭐ | 🟢 低 | 性能预算 + 测试 + 文档 |

### 推荐实施顺序（v2.0 修订）

```
PR-01 → PR-04 → PR-03 → PR-09 → PR-05 → PR-07
  → PR-02 → PR-06 → PR-08b → PR-10 → PR-11 → PR-11b → PR-08 → PR-12
```

---

## 14. 变更日志（**v2.0 新增**）

| 版本 | 日期 | 变更要点 |
|---|---|---|
| v1.0 | 2026-05-11 | 初始深度审计 + 5 阶段 12 PR 方案 |
| v1.1 | 2026-05-11 | DPR 截断、国产浏览器、字号系统、软键盘 |
| v1.2 | 2026-05-11 | 安全区、暗黑模式、IME、折叠屏、弱网 |
| v1.3 | 2026-05-11 | ChunkLoadError、WebSocket、a11y、骨架屏 |
| v1.4 | 2026-05-11 | 内存泄漏、金融精度、色盲、打印 |
| v1.5 | 2026-05-11 | 时区、调度器、并发竞态、上传下载、性能预算、合规 |
| v1.5.1–1.5.2 | 2026-05-11 | 代码勘误 + 错别字修正 |
| **v2.0** | **2026-05-20** | 实施状态追踪；验证中心/AI Agent 管理/AI 抽屉覆盖；媒体查询审计修正（6 处@media 跨 5 文件）；AI 抽屉 size=55% 问题定位；factorLab/fusion 已有 960px 断点纳入；依赖安装计划；优先级重排；MVP 路径；移动端可用度 22% |

---

> **附：实施期间常用命令速查**
>
> ```powershell
> # 安装基础依赖（PR-01 前置）
> cd quantia\fontWeb
> npm install @vueuse/core
> npx playwright install chromium webkit
>
> # 启动 dev + Playwright 录制
> npm run dev
> npx playwright codegen http://localhost:3000
>
> # 视觉回归
> npx playwright test --update-snapshots   # 更新 baseline（谨慎）
> npx playwright test tests\visual         # 跑回归
>
> # Bundle 分析
> npx vite-bundle-visualizer
>
> # 三视口快速预览
> # Chrome DevTools → Toggle device toolbar → iPhone SE / iPad / Desktop
>
> # 移动端真机调试
> # Android: chrome://inspect → USB debugging
> # iOS: Safari → Develop → <device>
> ```

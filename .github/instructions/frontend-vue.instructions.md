---
description: "Use when editing Vue 3 frontend code under quantia/fontWeb/src/. Covers component conventions, API layer patterns, routing, Pinia stores, Element Plus usage, composables, and testing/build workflow."
applyTo: "quantia/fontWeb/src/**/*.ts, quantia/fontWeb/src/**/*.vue, quantia/fontWeb/tests/**/*.ts"
---
# 前端 Vue 3 开发规范

## 项目结构
- `src/api/` — Axios 封装，按领域一个模块（stock.ts、strategy.ts、ai.ts 等）
- `src/router/` — Vue Router，所有路由懒加载，`meta.tableName` 驱动数据源
- `src/stores/` — Pinia Composition API 风格（auth、stock、index）
- `src/views/` — 页面组件；`StockData.vue` 通过 `route.meta.tableName` 渲染 10+ 不同数据表
- `src/layout/` — 主布局：Sidebar + Navbar + `<keep-alive>` 包裹的 RouterView
- `src/composables/` — Vue 3 组合式函数（如 `useCustomIndicatorOverlay`）
- `src/mock/` — MSW (Mock Service Worker)，`npm run dev:mock` 启用无后端开发
- `src/types/` — TypeScript 类型定义
- `src/utils/` — 工具函数（columnTooltips、backtestDashboardLinks）

## 组件规范
- 统一使用 `<script setup lang="ts">` Composition API。
- Element Plus 组件全局注册（main.ts），国际化用 `zhCn`。
- 日期处理统一用 `dayjs`。
- 布局用 `<keep-alive>`，因此组件状态在路由切换间持久化——需要刷新数据时用 `onActivated()` 而不是 `onMounted()`。

## API 调用
- **所有** HTTP 请求必须经过 `src/api/` 模块，不要在组件里直接用 axios。
- 基础路径：`/quantia`，Vite dev 代理到 `http://localhost:9988`。
- Phase 8 CSRF 自动注入：从 cookie 读 `csrf_token` → 写入 `X-CSRF-Token` header（写操作自动处理，无需手动）。
- 401 自动跳转 `/login?redirect=<当前路径>`。

## 路由约定
- 路由懒加载：`component: () => import('@/views/...')`
- meta 字段：`title`（页面标题）、`tableName`（数据源）、`isRealtime`、`hidden`（侧边栏隐藏）、`public`（无需鉴权）、`icon`。
- 新增数据表页面时，复用 `StockData.vue`，只需在 router 加路由 + 设 `meta.tableName`。

## 状态管理
- Pinia Composition API 风格：`defineStore('name', () => { ... })`，直接操作 ref，不走 mutation。
- 测试中每个 `beforeEach` 重建 Pinia：`setActivePinia(createPinia())`。

## 列定义（动态列）
- 后端返回数据 **和** 列元数据，前端动态渲染——**不要**硬编码列。
- 列元信息字段：`value`、`caption`、`width`、`dataType`、`format`（pct/price/vol/money/ratio/int）、`color`（涨跌着色）、`group`。
- 保留列（`date`、`code`、`name`、`cdatetime`）固定位置。

## 测试
- Vitest + @vue/test-utils + MSW。
- 测试文件位于 `quantia/fontWeb/tests/` 或 `src/**/*.test.ts`。
- setup 文件：`tests/setup.ts`（Pinia、Element Plus、window mock）。
- 运行：`npm test`（Vitest watch 模式）或 CI 中 `npx vitest run`。

## 构建与部署
- `npm run build`（vue-tsc 类型检查 + vite build）→ 输出到 `dist/`。
- 生产部署须把 `dist/**` 拷贝到 [quantia/web/static/](../../quantia/web/static)，Tornado 从该目录提供静态文件。
- Vite config 中 `base` 路径须与 Tornado 静态挂载点一致，否则 build 后白屏。

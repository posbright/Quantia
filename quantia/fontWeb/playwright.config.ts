// 占位 Playwright 配置：当前视觉回归走 scripts/visual.mjs（零额外依赖直接调 playwright API）。
// 本文件仅供未来迁移到 @playwright/test 时参考；当前未安装 @playwright/test，故不导入其类型。
//
// 启用步骤：
//   npm i -D @playwright/test
//   npx playwright install chromium
//   npx playwright test
//
// 注：本文件不在 tsconfig include 范围内，不会进入 vue-tsc 类型检查。

export default {
  testDir: './tests/visual',
  timeout: 30_000,
  retries: 0,
  use: {
    baseURL: process.env.QUANTIA_BASE || 'http://localhost:9988',
    viewport: { width: 1280, height: 800 },
    deviceScaleFactor: 1,
    headless: true,
  },
  projects: [
    { name: 'desktop-chromium', use: { browserName: 'chromium' } },
  ],
}

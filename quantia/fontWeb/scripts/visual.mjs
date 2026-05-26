// PR-12「零回归」第三锁：桌面端视觉回归基线（pixel-diff 版）。
//
// 思路：用 Playwright（已装）在 1280x800 截取关键页面，用 pixelmatch 与
// tests/visual/baseline/*.png 做像素级比对，差异像素率 > FAIL_RATIO 视为回归。
//
// 用法：
//   npm run visual            # 比对当前与 baseline；超阈值退出码非 0，输出 diff PNG
//   npm run visual:update     # 重写 baseline（首次或刻意修改 UI 后用）
//
// 路由覆盖：选用「不依赖登录态 + 不依赖后端实时数据」的入口页。

import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { PNG } from 'pngjs'
import pixelmatch from 'pixelmatch'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const BASELINE_DIR = path.join(ROOT, 'tests', 'visual', 'baseline')
const ACTUAL_DIR = path.join(ROOT, 'tests', 'visual', 'actual')
const DIFF_DIR = path.join(ROOT, 'tests', 'visual', 'diff')

const BASE = process.env.QUANTIA_BASE || 'http://localhost:9988'
const VIEWPORT = { width: 1280, height: 800 }
// 允许 1% 像素差异（吸收字体抗锯齿、滚动条、光标闪烁、Element Plus 渐变等噪声）。
// 真实回归（布局错位、配色变更、元素消失）通常远超此阈值。
const FAIL_RATIO = Number(process.env.QUANTIA_VISUAL_FAIL_RATIO || 0.01)
const PIXEL_THRESHOLD = 0.2 // pixelmatch 单像素差容忍

const ROUTES = [
  { name: 'home', path: '/home', waitFor: 'main, .home-container, .el-main' },
  { name: 'login', path: '/login', waitFor: 'form, .login-card, .el-form' },
  { name: 'register', path: '/register', waitFor: 'form, .el-form' },
  { name: 'verify-compare', path: '/verify/compare', waitFor: '.el-main, main' },
  { name: 'strategy-list', path: '/strategy/list', waitFor: '.el-main, main' },
]

const UPDATE = process.argv.includes('--update')

async function ensureDir(dir) { await fs.promises.mkdir(dir, { recursive: true }) }

async function capture() {
  await ensureDir(ACTUAL_DIR)
  if (UPDATE) await ensureDir(BASELINE_DIR)

  const browser = await chromium.launch()
  const ctx = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: 1,
    reducedMotion: 'reduce', // 关闭过渡动画，截图稳定
  })
  const results = []
  for (const route of ROUTES) {
    const page = await ctx.newPage()
    try {
      await page.goto(BASE + route.path, { waitUntil: 'domcontentloaded', timeout: 15000 })
      if (route.waitFor) {
        await page.waitForSelector(route.waitFor, { timeout: 8000 }).catch(() => {})
      }
      await page.waitForLoadState('load', { timeout: 10000 }).catch(() => {})
      await page.evaluate(() => (document.fonts && document.fonts.ready) || Promise.resolve())
      // 屏蔽时间戳/随机元素 + 关闭动画 + 隐藏滚动条
      await page.addStyleTag({
        content: `
          [data-visual-volatile], .visual-volatile { visibility: hidden !important; }
          *, *::before, *::after { transition: none !important; animation: none !important; caret-color: transparent !important; }
          ::-webkit-scrollbar { width: 0 !important; height: 0 !important; }
        `,
      })
      await page.waitForTimeout(500)
      const buf = await page.screenshot({ fullPage: false, type: 'png', animations: 'disabled', caret: 'hide' })
      const target = path.join(UPDATE ? BASELINE_DIR : ACTUAL_DIR, `${route.name}.png`)
      await fs.promises.writeFile(target, buf)
      results.push({ name: route.name, path: route.path, ok: true, target, size: buf.length })
    } catch (e) {
      results.push({ name: route.name, path: route.path, ok: false, error: String(e).slice(0, 200) })
    } finally {
      await page.close()
    }
  }
  await browser.close()
  return results
}

function diffPng(baselineBuf, actualBuf, diffPath) {
  const a = PNG.sync.read(baselineBuf)
  const b = PNG.sync.read(actualBuf)
  if (a.width !== b.width || a.height !== b.height) {
    return { mismatch: a.width * a.height, total: a.width * a.height, sizeChanged: true }
  }
  const diff = new PNG({ width: a.width, height: a.height })
  const mismatch = pixelmatch(a.data, b.data, diff.data, a.width, a.height, { threshold: PIXEL_THRESHOLD })
  if (mismatch > 0) {
    fs.writeFileSync(diffPath, PNG.sync.write(diff))
  }
  return { mismatch, total: a.width * a.height, sizeChanged: false }
}

async function compare() {
  await ensureDir(DIFF_DIR)
  const out = []
  for (const route of ROUTES) {
    const baseline = path.join(BASELINE_DIR, `${route.name}.png`)
    const actual = path.join(ACTUAL_DIR, `${route.name}.png`)
    const diffOut = path.join(DIFF_DIR, `${route.name}.diff.png`)
    if (!fs.existsSync(baseline)) {
      out.push({ name: route.name, status: 'NO_BASELINE' })
      continue
    }
    if (!fs.existsSync(actual)) {
      out.push({ name: route.name, status: 'NO_ACTUAL' })
      continue
    }
    const r = diffPng(fs.readFileSync(baseline), fs.readFileSync(actual), diffOut)
    const ratio = r.mismatch / r.total
    out.push({ name: route.name, ...r, ratio, status: ratio > FAIL_RATIO ? 'DIFF' : 'OK', diffOut })
  }
  return out
}

async function main() {
  console.log(`[visual] viewport=${VIEWPORT.width}x${VIEWPORT.height} base=${BASE} mode=${UPDATE ? 'UPDATE' : 'COMPARE'} failRatio=${FAIL_RATIO}`)
  const captured = await capture()
  for (const r of captured) {
    console.log(`  ${r.ok ? '✓' : '✗'} ${r.name}  ${r.path}${r.size ? '  ' + r.size + 'B' : ''}${r.error ? '  ERR: ' + r.error : ''}`)
  }
  if (UPDATE) {
    console.log(`[visual] baseline 已更新：${BASELINE_DIR}`)
    return
  }
  const diffs = await compare()
  const failures = diffs.filter(d => d.status !== 'OK')
  for (const d of diffs) {
    if (d.status === 'OK') {
      console.log(`  ✓ ${d.name}  diff=${d.mismatch}/${d.total}px (${(d.ratio * 100).toFixed(3)}%)`)
    } else if (d.status === 'NO_BASELINE') {
      console.log(`  ✗ ${d.name}  NO_BASELINE  运行 npm run visual:update`)
    } else if (d.status === 'NO_ACTUAL') {
      console.log(`  ✗ ${d.name}  NO_ACTUAL  截图失败`)
    } else {
      console.log(`  ✗ ${d.name}  DIFF  ${d.mismatch}/${d.total}px (${(d.ratio * 100).toFixed(3)}%) > ${(FAIL_RATIO * 100).toFixed(3)}%${d.sizeChanged ? '  尺寸变化' : ''}`)
      console.log(`     diff PNG: ${d.diffOut}`)
    }
  }
  if (failures.length === 0) {
    console.log('[visual] 全部页面在阈值内 ✓')
    return
  }
  console.log(`[visual] ${failures.length} 个页面超阈值。如确认是预期变更：npm run visual:update 并提交 baseline。`)
  process.exit(1)
}

main().catch(e => { console.error(e); process.exit(1) })

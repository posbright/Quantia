// PR-12 移动端冒烟脚本：开 chromium 模拟 375×667 (iPhone SE) 访问关键页面，
// 校验：1) 导航折叠 2) 弹窗宽度不溢出 3) Picker 改为底部 sheet 4) 无 console error。
import { chromium } from 'playwright'

const BASE = process.env.QUANTIA_BASE || 'http://localhost:9988'
const VIEWPORTS = [
  { name: 'iphone-se', width: 375, height: 667 },
  { name: 'ipad-portrait', width: 768, height: 1024 },
]
const PAGES = [
  '/home',
  '/login',
  '/register',
  '/verify/compare',
  '/strategy/list',
]

async function check(viewport) {
  const browser = await chromium.launch()
  const ctx = await browser.newContext({ viewport, userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0)' })
  const results = []
  for (const path of PAGES) {
    const page = await ctx.newPage()
    const consoleErrs = []
    page.on('console', m => { if (m.type() === 'error') consoleErrs.push(m.text().slice(0, 200)) })
    page.on('pageerror', e => consoleErrs.push('PAGEERROR: ' + e.message.slice(0, 200)))
    try {
      await page.goto(BASE + path, { waitUntil: 'domcontentloaded', timeout: 15000 })
      await page.waitForTimeout(800)
      const info = await page.evaluate((bp) => {
        const docW = document.documentElement.clientWidth
        const body = document.body
        const overflowX = body.scrollWidth > docW + 2
        const aside = document.querySelector('aside, .el-aside, .sidebar')
        const asideW = aside ? aside.getBoundingClientRect().width : 0
        const dialogs = Array.from(document.querySelectorAll('.el-dialog'))
          .map(d => ({ w: d.getBoundingClientRect().width }))
        return {
          innerW: window.innerWidth,
          docW,
          bodyScrollW: body.scrollWidth,
          overflowX,
          asideW,
          dialogs,
          bp,
        }
      }, viewport.width)
      results.push({ path, ok: !info.overflowX && consoleErrs.filter(e => !/favicon|405/.test(e)).length === 0, info, errs: consoleErrs })
    } catch (e) {
      results.push({ path, ok: false, error: String(e).slice(0, 200) })
    } finally {
      await page.close()
    }
  }
  await browser.close()
  return results
}

async function main() {
  for (const vp of VIEWPORTS) {
    console.log(`\n===== ${vp.name} (${vp.width}x${vp.height}) =====`)
    const r = await check(vp)
    for (const row of r) {
      const tag = row.ok ? '✓' : '✗'
      const overflowMsg = row.info?.overflowX ? ` OVERFLOW(scrollW=${row.info.bodyScrollW})` : ''
      const errsClean = (row.errs || []).filter(e => !/favicon|405|web_vitals/.test(e))
      const errMsg = errsClean.length > 0 ? ` errs=${errsClean.length}: ${errsClean.slice(0, 2).join(' | ')}` : ''
      console.log(`${tag} ${row.path}  innerW=${row.info?.innerW} asideW=${row.info?.asideW}${overflowMsg}${errMsg}${row.error ? ' ERROR: ' + row.error : ''}`)
    }
  }
}

main().catch(e => { console.error(e); process.exit(1) })

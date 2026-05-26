/**
 * 前端通用工具函数。
 *
 * 由 [tests/utils/index.test.ts](../../tests/utils/index.test.ts) 锁定 API 契约。
 * 业务组件请优先 import 这里的函数，避免重复实现散落各处。
 */
import dayjs from 'dayjs'

type Nullish<T> = T | null | undefined

function isInvalidNumber(v: any): boolean {
  return v === null || v === undefined || (typeof v === 'number' && Number.isNaN(v))
}

/**
 * 日期格式化，默认 `YYYY-MM-DD`。接受 Date / 字符串 / 数字。
 */
export function formatDate(date: Date | string | number, fmt = 'YYYY-MM-DD'): string {
  if (date === null || date === undefined || date === '') return '-'
  const d = dayjs(date)
  if (!d.isValid()) return '-'
  return d.format(fmt)
}

/**
 * 千分位 + 固定小数位的数字格式化。null/undefined/NaN → '-'。
 */
export function formatNumber(value: Nullish<number>, decimals = 2): string {
  if (isInvalidNumber(value)) return '-'
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  return n.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

/**
 * 涨跌百分比格式化，正数带 `+` 号，统一保留小数位。`5.23` → `+5.23%`。
 * null/undefined/NaN → '-'。
 */
export function formatPercent(value: Nullish<number>, decimals = 2): string {
  if (isInvalidNumber(value)) return '-'
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  const sign = n < 0 ? '' : '+' // 负号本身由 toFixed 提供，零和正数补 '+'
  return `${sign}${n.toFixed(decimals)}%`
}

/**
 * 金额自动单位（不带"元"后缀）：≥1 亿 → `X.XX亿`，≥1 万 → `X.XX万`，其余原样保留 2 位小数。
 */
export function formatAmount(value: Nullish<number>): string {
  if (isInvalidNumber(value)) return '-'
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  const abs = Math.abs(n)
  if (abs >= 1e8) return `${(n / 1e8).toFixed(2)}亿`
  if (abs >= 1e4) return `${(n / 1e4).toFixed(2)}万`
  return n.toFixed(2)
}

/**
 * 成交量格式化（带"手"后缀）：≥1 亿 → `X.XX亿手`，≥1 万 → `X.XX万手`，其余整数 `X手`。
 */
export function formatVolume(value: Nullish<number>): string {
  if (isInvalidNumber(value)) return '-'
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  const abs = Math.abs(n)
  if (abs >= 1e8) return `${(n / 1e8).toFixed(2)}亿手`
  if (abs >= 1e4) return `${(n / 1e4).toFixed(2)}万手`
  return `${Math.round(n)}手`
}

/**
 * 涨跌方向 → 类名映射。正 `text-up`，负 `text-down`，零或非数 `''`。
 */
export function getChangeClass(value: Nullish<number>): string {
  if (isInvalidNumber(value)) return ''
  const n = Number(value)
  if (!Number.isFinite(n) || n === 0) return ''
  return n > 0 ? 'text-up' : 'text-down'
}

/**
 * 仅按星期判断交易日（不考虑节假日 / 临时停盘）。需要完整交易日历请走后端接口。
 */
export function isTradeDay(date: Date | string | number): boolean {
  const d = dayjs(date)
  if (!d.isValid()) return false
  const dow = d.day() // 0=Sun, 6=Sat
  return dow >= 1 && dow <= 5
}

/**
 * 返回上一个交易日（仅按星期跳过周末，不查节假日）。返回 `YYYY-MM-DD`。
 */
export function getLastTradeDay(date: Date | string | number): string {
  let d = dayjs(date)
  if (!d.isValid()) return '-'
  do {
    d = d.subtract(1, 'day')
  } while (!isTradeDay(d.toDate()))
  return d.format('YYYY-MM-DD')
}

/**
 * 防抖：在 `wait` ms 内重复调用只在最后一次后执行。
 */
export function debounce<T extends (...args: any[]) => any>(fn: T, wait: number) {
  let t: ReturnType<typeof setTimeout> | null = null
  return function (this: any, ...args: Parameters<T>) {
    if (t) clearTimeout(t)
    t = setTimeout(() => {
      t = null
      fn.apply(this, args)
    }, wait)
  }
}

/**
 * 节流（leading-edge）：首次立即执行，`wait` ms 内的后续调用被丢弃。
 */
export function throttle<T extends (...args: any[]) => any>(fn: T, wait: number) {
  let last = 0
  return function (this: any, ...args: Parameters<T>) {
    const now = Date.now()
    if (now - last >= wait) {
      last = now
      fn.apply(this, args)
    }
  }
}

import dayjs from 'dayjs'

/**
 * 格式化日期
 */
export function formatDate(date: string | Date, format = 'YYYY-MM-DD'): string {
  return dayjs(date).format(format)
}

/**
 * 格式化数字（千分位）
 */
export function formatNumber(num: number, decimals = 2): string {
  if (num === null || num === undefined || isNaN(num)) return '-'
  return num.toLocaleString('zh-CN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals
  })
}

/**
 * 格式化百分比（后端返回的已是百分比形式，如 -7 表示 -7%）
 */
export function formatPercent(value: number, decimals = 2): string {
  if (value === null || value === undefined || isNaN(value)) return '-'
  const formatted = value.toFixed(decimals)
  return value >= 0 ? `+${formatted}%` : `${formatted}%`
}

/**
 * 格式化金额（亿/万）
 */
export function formatAmount(amount: number): string {
  if (amount === null || amount === undefined || isNaN(amount)) return '-'
  if (amount >= 100000000) {
    return (amount / 100000000).toFixed(2) + '亿'
  } else if (amount >= 10000) {
    return (amount / 10000).toFixed(2) + '万'
  }
  return amount.toFixed(2)
}

/**
 * 格式化成交量
 */
export function formatVolume(volume: number): string {
  if (volume === null || volume === undefined || isNaN(volume)) return '-'
  if (volume >= 100000000) {
    return (volume / 100000000).toFixed(2) + '亿手'
  } else if (volume >= 10000) {
    return (volume / 10000).toFixed(2) + '万手'
  }
  return volume.toFixed(0) + '手'
}

/**
 * 获取涨跌颜色类名
 */
export function getChangeClass(value: number): string {
  if (value > 0) return 'text-up'
  if (value < 0) return 'text-down'
  return ''
}

/**
 * 判断是否是交易日（简单判断，不考虑节假日）
 */
export function isTradeDay(date: string | Date): boolean {
  const day = dayjs(date).day()
  return day !== 0 && day !== 6
}

/**
 * 获取上一个交易日
 */
export function getLastTradeDay(date?: string | Date): string {
  let d = dayjs(date)
  do {
    d = d.subtract(1, 'day')
  } while (!isTradeDay(d.toDate()))
  return d.format('YYYY-MM-DD')
}

/**
 * 防抖函数
 */
export function debounce<T extends (...args: any[]) => any>(
  fn: T,
  delay: number
): (...args: Parameters<T>) => void {
  let timer: ReturnType<typeof setTimeout> | null = null
  return function (this: any, ...args: Parameters<T>) {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      fn.apply(this, args)
    }, delay)
  }
}

/**
 * 节流函数
 */
export function throttle<T extends (...args: any[]) => any>(
  fn: T,
  delay: number
): (...args: Parameters<T>) => void {
  let lastTime = 0
  return function (this: any, ...args: Parameters<T>) {
    const now = Date.now()
    if (now - lastTime >= delay) {
      lastTime = now
      fn.apply(this, args)
    }
  }
}

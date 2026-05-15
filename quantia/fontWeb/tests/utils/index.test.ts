import { describe, it, expect } from 'vitest'
import {
  formatDate,
  formatNumber,
  formatPercent,
  formatAmount,
  formatVolume,
  getChangeClass,
  isTradeDay,
  getLastTradeDay,
  debounce,
  throttle
} from '@/utils'

describe('Utils 工具函数测试', () => {
  describe('formatDate 日期格式化', () => {
    it('应该正确格式化日期字符串', () => {
      expect(formatDate('2026-01-20')).toBe('2026-01-20')
      expect(formatDate('2026-01-20', 'YYYY/MM/DD')).toBe('2026/01/20')
      expect(formatDate('2026-01-20', 'MM-DD')).toBe('01-20')
    })

    it('应该正确格式化 Date 对象', () => {
      const date = new Date('2026-01-20')
      expect(formatDate(date)).toBe('2026-01-20')
    })
  })

  describe('formatNumber 数字格式化', () => {
    it('应该正确格式化数字', () => {
      expect(formatNumber(1234.5678)).toBe('1,234.57')
      expect(formatNumber(1234.5678, 0)).toBe('1,235')
      expect(formatNumber(1234.5678, 4)).toBe('1,234.5678')
    })

    it('应该处理 null 和 undefined', () => {
      expect(formatNumber(null as any)).toBe('-')
      expect(formatNumber(undefined as any)).toBe('-')
      expect(formatNumber(NaN)).toBe('-')
    })
  })

  describe('formatPercent 百分比格式化', () => {
    it('应该正确格式化正数百分比', () => {
      expect(formatPercent(5.23)).toBe('+5.23%')
      expect(formatPercent(10)).toBe('+10.00%')
    })

    it('应该正确格式化负数百分比', () => {
      expect(formatPercent(-2.34)).toBe('-2.34%')
      expect(formatPercent(-10)).toBe('-10.00%')
    })

    it('应该正确格式化零', () => {
      expect(formatPercent(0)).toBe('+0.00%')
    })

    it('应该处理无效值', () => {
      expect(formatPercent(null as any)).toBe('-')
      expect(formatPercent(undefined as any)).toBe('-')
      expect(formatPercent(NaN)).toBe('-')
    })
  })

  describe('formatAmount 金额格式化', () => {
    it('应该正确格式化亿级金额', () => {
      expect(formatAmount(1234567890)).toBe('12.35亿')
      expect(formatAmount(100000000)).toBe('1.00亿')
    })

    it('应该正确格式化万级金额', () => {
      expect(formatAmount(12345678)).toBe('1234.57万')
      expect(formatAmount(10000)).toBe('1.00万')
    })

    it('应该正确格式化小额', () => {
      expect(formatAmount(1234.56)).toBe('1234.56')
    })

    it('应该处理无效值', () => {
      expect(formatAmount(null as any)).toBe('-')
      expect(formatAmount(undefined as any)).toBe('-')
    })
  })

  describe('formatVolume 成交量格式化', () => {
    it('应该正确格式化亿级成交量', () => {
      expect(formatVolume(123456789)).toBe('1.23亿手')
    })

    it('应该正确格式化万级成交量', () => {
      expect(formatVolume(1234567)).toBe('123.46万手')
    })

    it('应该正确格式化小额成交量', () => {
      expect(formatVolume(1234)).toBe('1234手')
    })
  })

  describe('getChangeClass 涨跌样式', () => {
    it('应该返回正确的涨跌类名', () => {
      expect(getChangeClass(0.05)).toBe('text-up')
      expect(getChangeClass(-0.03)).toBe('text-down')
      expect(getChangeClass(0)).toBe('')
    })
  })

  describe('isTradeDay 交易日判断', () => {
    it('应该正确判断工作日', () => {
      expect(isTradeDay('2026-01-20')).toBe(true)  // 周二
      expect(isTradeDay('2026-01-21')).toBe(true)  // 周三
    })

    it('应该正确判断周末', () => {
      expect(isTradeDay('2026-01-18')).toBe(false) // 周日
      expect(isTradeDay('2026-01-17')).toBe(false) // 周六
    })
  })

  describe('getLastTradeDay 获取上一交易日', () => {
    it('应该返回上一个交易日', () => {
      const lastDay = getLastTradeDay('2026-01-20')
      expect(lastDay).toBe('2026-01-19')
    })

    it('周一应该返回上周五', () => {
      const lastDay = getLastTradeDay('2026-01-19')  // 周一
      expect(lastDay).toBe('2026-01-16')  // 上周五
    })
  })

  describe('debounce 防抖函数', () => {
    it('应该在延迟后执行', async () => {
      let count = 0
      const fn = debounce(() => count++, 100)
      
      fn()
      fn()
      fn()
      
      expect(count).toBe(0)
      
      await new Promise(resolve => setTimeout(resolve, 150))
      
      expect(count).toBe(1)
    })
  })

  describe('throttle 节流函数', () => {
    it('应该限制执行频率', async () => {
      let count = 0
      const fn = throttle(() => count++, 100)
      
      fn() // 执行
      fn() // 跳过
      fn() // 跳过
      
      expect(count).toBe(1)
      
      await new Promise(resolve => setTimeout(resolve, 150))
      
      fn() // 执行
      expect(count).toBe(2)
    })
  })
})

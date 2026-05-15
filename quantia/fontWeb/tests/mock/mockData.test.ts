import { describe, it, expect } from 'vitest'
import { mockStockSpotData, mockIndicatorsData, mockKlinePatternData } from '@/mock/stockData'

describe('Mock Data 测试数据验证', () => {
  describe('mockStockSpotData 股票行情数据', () => {
    it('应该包含必要的字段', () => {
      const stock = mockStockSpotData[0]
      
      expect(stock).toHaveProperty('date')
      expect(stock).toHaveProperty('code')
      expect(stock).toHaveProperty('name')
      expect(stock).toHaveProperty('new_price')
      expect(stock).toHaveProperty('change_rate')
      expect(stock).toHaveProperty('volume')
      expect(stock).toHaveProperty('turnover')
    })

    it('应该有足够的测试数据', () => {
      expect(mockStockSpotData.length).toBeGreaterThanOrEqual(5)
    })

    it('股票代码格式应该正确', () => {
      mockStockSpotData.forEach(stock => {
        expect(stock.code).toMatch(/^\d{6}$/)
      })
    })

    it('涨跌幅应该在合理范围内', () => {
      mockStockSpotData.forEach(stock => {
        expect(stock.change_rate).toBeGreaterThanOrEqual(-0.2)
        expect(stock.change_rate).toBeLessThanOrEqual(0.2)
      })
    })

    it('应该包含已关注和未关注的股票', () => {
      const hasAttention = mockStockSpotData.some(s => s.cdatetime !== null)
      const hasNoAttention = mockStockSpotData.some(s => s.cdatetime === null)
      
      expect(hasAttention).toBe(true)
      expect(hasNoAttention).toBe(true)
    })
  })

  describe('mockIndicatorsData 指标数据', () => {
    it('应该包含技术指标字段', () => {
      const indicator = mockIndicatorsData[0]
      
      expect(indicator).toHaveProperty('macd')
      expect(indicator).toHaveProperty('kdj_k')
      expect(indicator).toHaveProperty('kdj_d')
      expect(indicator).toHaveProperty('kdj_j')
      expect(indicator).toHaveProperty('rsi_6')
      expect(indicator).toHaveProperty('cci')
    })

    it('KDJ 值应该在 0-100 范围内（J值可超出）', () => {
      mockIndicatorsData.forEach(ind => {
        expect(ind.kdj_k).toBeGreaterThanOrEqual(0)
        expect(ind.kdj_k).toBeLessThanOrEqual(100)
        expect(ind.kdj_d).toBeGreaterThanOrEqual(0)
        expect(ind.kdj_d).toBeLessThanOrEqual(100)
      })
    })

    it('RSI 值应该在 0-100 范围内', () => {
      mockIndicatorsData.forEach(ind => {
        expect(ind.rsi_6).toBeGreaterThanOrEqual(0)
        expect(ind.rsi_6).toBeLessThanOrEqual(100)
      })
    })
  })

  describe('mockKlinePatternData K线形态数据', () => {
    it('应该包含K线形态字段', () => {
      const pattern = mockKlinePatternData[0]
      
      expect(pattern).toHaveProperty('date')
      expect(pattern).toHaveProperty('code')
      expect(pattern).toHaveProperty('name')
      expect(pattern).toHaveProperty('CDL2CROWS')
      expect(pattern).toHaveProperty('CDLMORNINGSTAR')
    })

    it('形态值应该是 -100、0 或 100', () => {
      mockKlinePatternData.forEach(pattern => {
        const values = [
          pattern.CDL2CROWS,
          pattern.CDL3BLACKCROWS,
          pattern.CDL3INSIDE,
          pattern.CDLMORNINGSTAR,
          pattern.CDLEVENINGSTAR
        ]
        
        values.forEach(v => {
          expect([-100, 0, 100]).toContain(v)
        })
      })
    })
  })
})

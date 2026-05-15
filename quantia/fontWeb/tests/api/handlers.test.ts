import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { handlers } from '@/mock/handlers'
import axios from 'axios'

// 设置 MSW 服务器
const server = setupServer(...handlers)

describe('API Mock Handlers 测试', () => {
  beforeEach(() => {
    server.listen()
  })

  afterEach(() => {
    server.resetHandlers()
  })

  afterAll(() => {
    server.close()
  })

  describe('GET /quantia/api_data', () => {
    it('应该返回股票数据', async () => {
      const response = await axios.get('/quantia/api_data', {
        params: { name: 'cn_stock_spot' }
      })

      expect(response.status).toBe(200)
      expect(Array.isArray(response.data)).toBe(true)
      expect(response.data.length).toBeGreaterThan(0)
    })

    it('应该返回指标数据', async () => {
      const response = await axios.get('/quantia/api_data', {
        params: { name: 'cn_stock_indicators' }
      })

      expect(response.status).toBe(200)
      expect(Array.isArray(response.data)).toBe(true)
    })

    it('应该返回 K线形态数据', async () => {
      const response = await axios.get('/quantia/api_data', {
        params: { name: 'cn_stock_kline_pattern' }
      })

      expect(response.status).toBe(200)
      expect(Array.isArray(response.data)).toBe(true)
    })

    it('应该支持日期过滤', async () => {
      const response = await axios.get('/quantia/api_data', {
        params: {
          name: 'cn_stock_spot',
          date: '2026-01-20'
        }
      })

      expect(response.status).toBe(200)
      if (response.data.length > 0) {
        expect(response.data[0].date).toBe('2026-01-20')
      }
    })
  })

  describe('GET /quantia/control/attention', () => {
    it('应该支持添加关注', async () => {
      const response = await axios.get('/quantia/control/attention', {
        params: { code: '000001', otype: '0' }
      })

      expect(response.status).toBe(200)
      expect(response.data).toHaveProperty('data')
    })

    it('应该支持取消关注', async () => {
      const response = await axios.get('/quantia/control/attention', {
        params: { code: '000001', otype: '1' }
      })

      expect(response.status).toBe(200)
      expect(response.data).toHaveProperty('data')
    })
  })
})

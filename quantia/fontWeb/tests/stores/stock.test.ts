import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useStockStore } from '@/stores/stock'

describe('Stock Store 状态管理', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  describe('关注功能', () => {
    it('应该能添加股票到关注列表', () => {
      const store = useStockStore()
      
      store.addAttention({ code: '000001', name: '平安银行' })
      
      expect(store.attentionList.length).toBe(1)
      expect(store.attentionList[0].code).toBe('000001')
      expect(store.attentionList[0].name).toBe('平安银行')
    })

    it('不应该重复添加相同股票', () => {
      const store = useStockStore()
      
      store.addAttention({ code: '000001', name: '平安银行' })
      store.addAttention({ code: '000001', name: '平安银行' })
      
      expect(store.attentionList.length).toBe(1)
    })

    it('应该能取消关注股票', () => {
      const store = useStockStore()
      
      store.addAttention({ code: '000001', name: '平安银行' })
      store.addAttention({ code: '000002', name: '万科A' })
      
      store.removeAttention('000001')
      
      expect(store.attentionList.length).toBe(1)
      expect(store.attentionList[0].code).toBe('000002')
    })

    it('应该正确判断股票是否已关注', () => {
      const store = useStockStore()
      
      store.addAttention({ code: '000001', name: '平安银行' })
      
      expect(store.isAttention('000001')).toBe(true)
      expect(store.isAttention('000002')).toBe(false)
    })
  })

  describe('最近查看功能', () => {
    it('应该能添加到最近查看列表', () => {
      const store = useStockStore()
      
      store.addRecent({ code: '000001', name: '平安银行' })
      
      expect(store.recentList.length).toBe(1)
      expect(store.recentList[0].code).toBe('000001')
    })

    it('重复查看应该移动到列表顶部', () => {
      const store = useStockStore()
      
      store.addRecent({ code: '000001', name: '平安银行' })
      store.addRecent({ code: '000002', name: '万科A' })
      store.addRecent({ code: '000001', name: '平安银行' })
      
      expect(store.recentList.length).toBe(2)
      expect(store.recentList[0].code).toBe('000001')
      expect(store.recentList[1].code).toBe('000002')
    })

    it('最近查看列表应该限制为20条', () => {
      const store = useStockStore()
      
      for (let i = 0; i < 25; i++) {
        store.addRecent({ code: `00000${i}`, name: `股票${i}` })
      }
      
      expect(store.recentList.length).toBe(20)
    })
  })

  describe('当前日期', () => {
    it('应该能设置当前日期', () => {
      const store = useStockStore()
      
      store.setCurrentDate('2026-01-20')
      
      expect(store.currentDate).toBe('2026-01-20')
    })
  })
})

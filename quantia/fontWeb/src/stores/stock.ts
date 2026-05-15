import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface StockItem {
  code: string
  name: string
  date?: string
}

export const useStockStore = defineStore('stock', () => {
  // 关注的股票列表
  const attentionList = ref<StockItem[]>([])
  
  // 最近查看的股票
  const recentList = ref<StockItem[]>([])
  
  // 当前选中的日期
  const currentDate = ref('')
  
  // 添加关注
  const addAttention = (stock: StockItem) => {
    const index = attentionList.value.findIndex(item => item.code === stock.code)
    if (index === -1) {
      attentionList.value.unshift(stock)
    }
  }
  
  // 取消关注
  const removeAttention = (code: string) => {
    const index = attentionList.value.findIndex(item => item.code === code)
    if (index !== -1) {
      attentionList.value.splice(index, 1)
    }
  }
  
  // 检查是否已关注
  const isAttention = (code: string) => {
    return attentionList.value.some(item => item.code === code)
  }
  
  // 添加到最近查看
  const addRecent = (stock: StockItem) => {
    const index = recentList.value.findIndex(item => item.code === stock.code)
    if (index !== -1) {
      recentList.value.splice(index, 1)
    }
    recentList.value.unshift(stock)
    // 只保留最近 20 条
    if (recentList.value.length > 20) {
      recentList.value.pop()
    }
  }
  
  // 设置当前日期
  const setCurrentDate = (date: string) => {
    currentDate.value = date
  }
  
  return {
    attentionList,
    recentList,
    currentDate,
    addAttention,
    removeAttention,
    isAttention,
    addRecent,
    setCurrentDate
  }
})

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { getStockData } from '@/api/stock'

interface FundFlowRow {
  name: string
  changeRate: number | null
  netInflow: number | null
  sampleStocks: string[]
}

interface IndustrySampleStock {
  code: string
  name: string
  date: string
  price: number | null
  changeRate: number | null
  fundAmount: number | null
}

const props = defineProps<{
  modelValue: boolean
  industry: FundFlowRow | null
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'open-industry-detail', industryName: string): void
  (e: 'open-stock-flow', payload: { code: string; name: string }): void
  (e: 'open-stock-kline', payload: IndustrySampleStock): void
}>()

const loading = ref(false)
const topStocks = ref<IndustrySampleStock[]>([])

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v)
})

function fmtNum(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '--'
  return Number(n).toFixed(digits)
}
function fmtPct(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '--'
  const sign = n > 0 ? '+' : ''
  return `${sign}${Number(n).toFixed(2)}%`
}
function fmtMoney(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '--'
  const abs = Math.abs(n)
  if (abs >= 1e8) return `${(n / 1e8).toFixed(2)} 亿`
  if (abs >= 1e4) return `${(n / 1e4).toFixed(2)} 万`
  return n.toFixed(0)
}
function trendColor(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n) || n === 0) return '#909399'
  return n > 0 ? '#f56c6c' : '#52c41a'
}
function normStockName(s: string): string {
  return String(s || '').replace(/\s+/g, '').trim()
}

async function loadIndustryTopStocks(industry: FundFlowRow) {
  loading.value = true
  topStocks.value = []
  try {
    const ir: any = await getStockData({
      name: 'cn_stock_fund_flow_industry',
      keyword: industry.name,
      page: 1,
      page_size: 200
    })
    const irows: any[] = ir?.data || ir?.rows || []
    const nameSet = new Set<string>()
    irows.forEach((row) => {
      const vals = [row?.stock_name, row?.stock_name_5, row?.stock_name_10]
      vals.forEach((v) => {
        const raw = String(v || '').trim()
        if (raw) nameSet.add(normStockName(raw))
      })
    })

    const candidates = Array.from(nameSet).slice(0, 24)
    if (candidates.length === 0) {
      topStocks.value = industry.sampleStocks.map((name) => ({
        code: '',
        name,
        date: '',
        price: null,
        changeRate: null,
        fundAmount: null
      }))
      return
    }

    const rows = await Promise.all(candidates.map(async (n) => {
      try {
        const r: any = await getStockData({
          name: 'cn_stock_fund_flow',
          keyword: n,
          page: 1,
          page_size: 1
        })
        const row = (r?.data || r?.rows || [])[0]
        if (!row) return null
        return {
          code: String(row.code || ''),
          name: String(row.name || n),
          date: String(row.date || ''),
          price: row.new_price === null || row.new_price === undefined ? null : Number(row.new_price),
          changeRate: row.change_rate === null || row.change_rate === undefined ? null : Number(row.change_rate),
          fundAmount: row.fund_amount === null || row.fund_amount === undefined ? null : Number(row.fund_amount)
        } as IndustrySampleStock
      } catch {
        return null
      }
    }))

    const merged = rows.filter((x): x is IndustrySampleStock => Boolean(x && x.name))
    merged.sort((a, b) => Math.abs(b.fundAmount || 0) - Math.abs(a.fundAmount || 0))
    topStocks.value = merged.slice(0, 10)
  } finally {
    loading.value = false
  }
}

watch(
  () => [visible.value, props.industry?.name] as const,
  async ([v]) => {
    if (!v || !props.industry) return
    await loadIndustryTopStocks(props.industry)
  },
  { immediate: true }
)

function handleOpenFlow(s: IndustrySampleStock) {
  emit('open-stock-flow', { code: s.code, name: s.name })
  visible.value = false
}

function handleOpenKline(s: IndustrySampleStock) {
  emit('open-stock-kline', s)
  visible.value = false
}

function handleOpenIndustryDetail() {
  if (!props.industry?.name) return
  emit('open-industry-detail', props.industry.name)
  visible.value = false
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="`${industry?.name || ''} · 行业参考成分`"
    width="520px"
    destroy-on-close
  >
    <div v-if="industry" class="industry-dialog-body">
      <div class="industry-brief">
        <span>行业涨跌：<strong :style="{ color: trendColor(industry.changeRate) }">{{ fmtPct(industry.changeRate) }}</strong></span>
        <span>净流入：<strong :style="{ color: trendColor(industry.netInflow) }">{{ fmtMoney(industry.netInflow) }}</strong></span>
      </div>
      <el-skeleton v-if="loading" :rows="4" animated />
      <template v-else>
        <div class="industry-stock-head">
          <span>样本股 Top 10（按主力净流入绝对值）</span>
          <span class="industry-tip">可查看资金流 / K线</span>
        </div>
        <div v-if="topStocks.length > 0" class="industry-stock-list">
          <div v-for="(s, idx) in topStocks" :key="`${s.code}-${s.name}-${idx}`" class="industry-stock-item">
            <div class="stock-left">
              <div class="stock-rank">{{ idx + 1 }}</div>
              <div class="stock-meta">
                <div class="stock-name">{{ s.name }}</div>
                <div class="stock-code">{{ s.code || '--' }}</div>
              </div>
            </div>
            <div class="stock-right">
              <div class="stock-metrics">
                <span :style="{ color: trendColor(s.changeRate) }">{{ fmtPct(s.changeRate) }}</span>
                <span>{{ fmtNum(s.price) }}</span>
                <span :style="{ color: trendColor(s.fundAmount) }">{{ (s.fundAmount ?? 0) >= 0 ? '+' : '' }}{{ fmtMoney(s.fundAmount) }}</span>
              </div>
              <div class="stock-actions">
                <el-button text size="small" @click="handleOpenFlow(s)">资金流</el-button>
                <el-button text size="small" @click="handleOpenKline(s)">K线</el-button>
              </div>
            </div>
          </div>
        </div>
        <span v-else class="empty-mini">暂无样本股</span>
      </template>
    </div>
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <el-button type="primary" @click="handleOpenIndustryDetail">查看行业资金详情</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.industry-dialog-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.industry-brief {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  font-size: 13px;
  color: #4b5563;
}
.industry-stock-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: #6b7280;
}
.industry-stock-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.industry-stock-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border: 1px solid #eef2f7;
  border-radius: 8px;
  padding: 8px;
  gap: 8px;
}
.stock-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.stock-rank {
  width: 20px;
  height: 20px;
  border-radius: 6px;
  background: #f4f6fa;
  color: #6b7280;
  font-size: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.stock-meta {
  min-width: 0;
}
.stock-name {
  font-size: 13px;
  color: #1a1f36;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.stock-code {
  font-size: 11px;
  color: #909399;
}
.stock-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.stock-metrics {
  display: flex;
  gap: 8px;
  font-size: 12px;
  color: #4b5563;
}
.stock-actions {
  display: flex;
  gap: 2px;
}
.industry-tip,
.empty-mini {
  font-size: 12px;
  color: #909399;
}
</style>

<template>
  <el-dialog
    v-model="visible"
    :title="stockDialogTitle"
    :width="isMobile ? '100vw' : '92vw'"
    :top="isMobile ? '0' : '4vh'"
    :fullscreen="isMobile"
    destroy-on-close
    @closed="onDialogClosed"
  >
    <div class="stock-dialog" v-loading="stockLoading">
      <div class="stock-summary" v-if="selectedStock">
        <div class="summary-item"><span>代码</span><b>{{ selectedStock.code }}</b></div>
        <div class="summary-item"><span>名称</span><b>{{ stockDisplayName(selectedStock) }}</b></div>
        <div class="summary-item"><span>持仓日期</span><b>{{ anchorDate || '--' }}</b></div>
        <div class="summary-item"><span>相关交易</span><b>{{ selectedStockTrades.length }} 笔</b></div>
        <div class="summary-item wide" v-if="selectedPaperTrade">
          <span>当前标记</span>
          <b :class="selectedPaperTrade.direction === 'buy' ? 'val-red' : 'val-green'">
            {{ selectedPaperTrade.date }} {{ directionLabel(selectedPaperTrade) }} {{ fmtMaybe(selectedPaperTrade.price) }}
          </b>
        </div>
      </div>

      <div class="stock-toolbar">
        <span class="toolbar-label">主图叠加</span>
        <el-checkbox-group v-model="stockOverlayIndicators" size="small" @change="renderActiveStockChart">
          <el-checkbox-button label="MA5">MA5</el-checkbox-button>
          <el-checkbox-button label="MA20">MA20</el-checkbox-button>
          <el-checkbox-button label="MA30">MA30</el-checkbox-button>
          <el-checkbox-button label="MA60">MA60</el-checkbox-button>
          <el-checkbox-button label="BOLL">BOLL</el-checkbox-button>
        </el-checkbox-group>
        <span class="toolbar-hint">指标基于完整历史K线计算，模拟买卖点来自当前模拟盘交易记录。</span>
      </div>

      <CustomIndicatorOverlayBar :state="ciOverlay" />

      <el-tabs v-model="stockActivePeriod" @tab-change="renderActiveStockChart">
        <el-tab-pane label="日K" name="daily">
          <div ref="stockDailyEl" class="stock-chart-box" :class="{ 'has-sub': hasCiSubPanel }"></div>
        </el-tab-pane>
        <el-tab-pane label="周K" name="weekly">
          <div ref="stockWeeklyEl" class="stock-chart-box" :class="{ 'has-sub': hasCiSubPanel }"></div>
        </el-tab-pane>
        <el-tab-pane label="月K" name="monthly">
          <div ref="stockMonthlyEl" class="stock-chart-box" :class="{ 'has-sub': hasCiSubPanel }"></div>
        </el-tab-pane>
      </el-tabs>

      <div class="indicator-panel" v-if="selectedPaperTrade">
        <div class="panel-title">{{ stockPeriodLabel }}指标快照</div>
        <el-descriptions :column="4" size="small" border>
          <el-descriptions-item label="K线日期">{{ activeIndicatorSnapshot.date || '--' }}</el-descriptions-item>
          <el-descriptions-item label="开盘">{{ fmtMaybe(activeIndicatorSnapshot.open) }}</el-descriptions-item>
          <el-descriptions-item label="最高">{{ fmtMaybe(activeIndicatorSnapshot.high) }}</el-descriptions-item>
          <el-descriptions-item label="最低">{{ fmtMaybe(activeIndicatorSnapshot.low) }}</el-descriptions-item>
          <el-descriptions-item label="收盘">{{ fmtMaybe(activeIndicatorSnapshot.close) }}</el-descriptions-item>
          <el-descriptions-item label="MA5">{{ fmtMaybe(activeIndicatorSnapshot.ma5) }}</el-descriptions-item>
          <el-descriptions-item label="MA20">{{ fmtMaybe(activeIndicatorSnapshot.ma20) }}</el-descriptions-item>
          <el-descriptions-item label="MA30">{{ fmtMaybe(activeIndicatorSnapshot.ma30) }}</el-descriptions-item>
          <el-descriptions-item label="MA60">{{ fmtMaybe(activeIndicatorSnapshot.ma60) }}</el-descriptions-item>
          <el-descriptions-item label="BOLL上轨">{{ fmtMaybe(activeIndicatorSnapshot.bollUpper) }}</el-descriptions-item>
          <el-descriptions-item label="BOLL中轨">{{ fmtMaybe(activeIndicatorSnapshot.bollMiddle) }}</el-descriptions-item>
          <el-descriptions-item label="BOLL下轨">{{ fmtMaybe(activeIndicatorSnapshot.bollLower) }}</el-descriptions-item>
          <el-descriptions-item label="RSI14">{{ fmtMaybe(activeIndicatorSnapshot.rsi) }}</el-descriptions-item>
          <el-descriptions-item label="MACD DIF">{{ fmtMaybe(activeIndicatorSnapshot.macdDif) }}</el-descriptions-item>
          <el-descriptions-item label="MACD DEA">{{ fmtMaybe(activeIndicatorSnapshot.macdDea) }}</el-descriptions-item>
          <el-descriptions-item label="MACD柱">{{ fmtMaybe(activeIndicatorSnapshot.macdHist) }}</el-descriptions-item>
          <el-descriptions-item label="成交量">{{ Number(activeIndicatorSnapshot.volume || 0).toLocaleString() }}</el-descriptions-item>
        </el-descriptions>
      </div>

      <el-table
        :data="selectedStockTrades"
        size="small"
        max-height="220"
        stripe
        class="stock-trade-table"
        @row-click="selectTradeInDialog"
      >
        <el-table-column prop="date" label="日期" width="100" />
        <el-table-column label="方向" width="70">
          <template #default="{ row }">
            <span :class="row.direction === 'buy' ? 'val-red' : 'val-green'">{{ directionLabel(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="code" label="代码" width="75" />
        <el-table-column label="名称" width="110" show-overflow-tooltip>
          <template #default="{ row }">{{ stockDisplayName(row) }}</template>
        </el-table-column>
        <el-table-column label="价格" width="85" align="right"><template #default="{ row }">{{ fmtMaybe(row.price) }}</template></el-table-column>
        <el-table-column label="数量" width="95" align="right"><template #default="{ row }">{{ Number(row.amount || 0).toLocaleString() }}</template></el-table-column>
        <el-table-column label="成交额" width="120" align="right"><template #default="{ row }">{{ formatMoneyFull(row.value) }}</template></el-table-column>
        <el-table-column label="手续费" width="90" align="right"><template #default="{ row }">{{ fmtMaybe((row.commission || 0) + (row.tax || 0)) }}</template></el-table-column>
      </el-table>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import * as echarts from 'echarts'
import { getKlineData } from '@/api/stock'
import { useCustomIndicatorOverlay } from '@/composables/useCustomIndicatorOverlay'
import CustomIndicatorOverlayBar from '@/components/CustomIndicatorOverlayBar.vue'

interface SelectedStock { code: string; name?: string }

const props = defineProps<{
  selectedStock: SelectedStock | null
  trades: any[]
  positions: any[]
  anchorDate: string
  isMobile: boolean
  formatMoneyFull: (v: number) => string
}>()

const visible = defineModel<boolean>('visible', { required: true })

// ── DOM refs / chart instances ──
const stockDailyEl = ref<HTMLElement | null>(null)
const stockWeeklyEl = ref<HTMLElement | null>(null)
const stockMonthlyEl = ref<HTMLElement | null>(null)
let stockDailyChart: echarts.ECharts | null = null
let stockWeeklyChart: echarts.ECharts | null = null
let stockMonthlyChart: echarts.ECharts | null = null
let resizeDebounceTimer: number | null = null
let stockRenderTimer: number | null = null

// ── 内部状态 ──
const stockLoading = ref(false)
const stockActivePeriod = ref<'daily' | 'weekly' | 'monthly'>('daily')
const selectedPaperTrade = ref<any>(null)
const stockKlines = ref<Record<string, any>>({})
const stockOverlayIndicators = ref(['MA5', 'MA20', 'MA30', 'MA60', 'BOLL'])

// ── 自定义指标叠加 ──
const ciCodeRef = computed(() => {
  const c = props.selectedStock?.code
  return c ? String(c).padStart(6, '0') : ''
})
const ciDatesRef = computed<string[]>(() => stockKlines.value[stockActivePeriod.value]?.dates || [])
const ciOverlay = useCustomIndicatorOverlay(
  ciCodeRef as any,
  stockActivePeriod as any,
  ciDatesRef as any,
)
const hasCiSubPanel = computed(() => !!ciOverlay.extension.value.subPanel)
watch(
  () => ciOverlay.extension.value,
  async () => {
    await nextTick()
    renderActiveStockChart()
  },
  { deep: true },
)

// ── 名称映射 / 显示工具 ──
const stockNameMap = computed(() => {
  const map = new Map<string, string>()
  const add = (row: any) => {
    const code = String(row?.code || '').trim()
    const name = String(row?.name || '').trim()
    if (code && name) map.set(code, name)
  }
  props.positions.forEach(add)
  props.trades.forEach(add)
  return map
})
function stockDisplayName(row: any) {
  const code = String(row?.code || '').trim()
  const name = String(row?.name || '').trim() || stockNameMap.value.get(code) || ''
  return name || code || '--'
}
function directionLabel(trade: any) {
  return trade?.direction === 'buy' ? '买入' : '卖出'
}
function fmtMaybe(v: any, digits = 2) {
  const num = Number(v)
  if (!Number.isFinite(num)) return '--'
  return num.toFixed(digits)
}

// ── 派生 computed ──
const selectedStockTrades = computed(() => {
  const code = props.selectedStock?.code
  if (!code) return []
  return props.trades
    .filter((t: any) => t.code === code)
    .sort((a: any, b: any) => String(a.date).localeCompare(String(b.date)))
})

const stockDialogTitle = computed(() => {
  if (!props.selectedStock) return '个股模拟买卖点与技术指标'
  const name = stockDisplayName(props.selectedStock)
  return `${props.selectedStock.code}${name && name !== props.selectedStock.code ? ' ' + name : ''} - 模拟买卖点与技术指标`
})

const stockPeriodLabel = computed(() => {
  const map: Record<string, string> = { daily: '日K', weekly: '周K', monthly: '月K' }
  return map[stockActivePeriod.value] || '日K'
})

const activeIndicatorSnapshot = computed<any>(() => {
  if (!selectedPaperTrade.value) return {}
  return indicatorSnapshot(stockActivePeriod.value, selectedPaperTrade.value)
})

// ── 触发：visible + selectedStock 变化时加载数据 ──
watch(
  () => [visible.value, props.selectedStock?.code] as const,
  async ([isOpen, code], _old) => {
    if (!isOpen || !code) return
    stockActivePeriod.value = 'daily'
    stockKlines.value = {}
    disposeStockCharts()
    stockLoading.value = true
    await nextTick()
    const related = selectedStockTrades.value
    selectedPaperTrade.value = pickNearestTrade(related) || related[related.length - 1] || null
    try {
      const periods: Array<'daily' | 'weekly' | 'monthly'> = ['daily', 'weekly', 'monthly']
      const results = await Promise.all(periods.map(period => getKlineData({
        code,
        name: stockDisplayName(props.selectedStock),
        period,
      }) as Promise<any>))
      periods.forEach((period, index) => {
        stockKlines.value[period] = results[index]?.data || results[index]
      })
      await nextTick()
      renderActiveStockChart()
    } finally {
      stockLoading.value = false
    }
  },
  { immediate: false },
)

function onDialogClosed() {
  disposeStockCharts()
  stockKlines.value = {}
  selectedPaperTrade.value = null
}

// ── 图表管理 ──
function disposeStockCharts() {
  stockDailyChart?.dispose(); stockDailyChart = null
  stockWeeklyChart?.dispose(); stockWeeklyChart = null
  stockMonthlyChart?.dispose(); stockMonthlyChart = null
}
function getStockChartRef(period: string) {
  if (period === 'weekly') return stockWeeklyEl.value
  if (period === 'monthly') return stockMonthlyEl.value
  return stockDailyEl.value
}
function getStockChart(period: string) {
  if (period === 'weekly') return stockWeeklyChart
  if (period === 'monthly') return stockMonthlyChart
  return stockDailyChart
}
function setStockChart(period: string, instance: echarts.ECharts | null) {
  if (period === 'weekly') stockWeeklyChart = instance
  else if (period === 'monthly') stockMonthlyChart = instance
  else stockDailyChart = instance
}

function pickNearestTrade(trades: any[]) {
  if (!trades.length) return null
  const anchor = props.anchorDate || ''
  if (!anchor) return trades[trades.length - 1]
  const before = trades.filter((trade: any) => String(trade.date) <= anchor)
  return before[before.length - 1] || trades[trades.length - 1]
}

function selectTradeInDialog(row: any) {
  selectedPaperTrade.value = row
  renderActiveStockChart()
}

function renderActiveStockChart() {
  if (stockRenderTimer !== null) window.clearTimeout(stockRenderTimer)
  stockRenderTimer = window.setTimeout(() => {
    stockRenderTimer = null
    renderStockChart(stockActivePeriod.value)
  }, 80)
}

function renderStockChart(period: 'daily' | 'weekly' | 'monthly') {
  const el = getStockChartRef(period)
  const kline = stockKlines.value[period]
  if (!el || !kline?.dates?.length) return
  if (el.clientWidth === 0) { setTimeout(() => renderStockChart(period), 120); return }
  getStockChart(period)?.dispose()
  const instance = echarts.init(el, undefined, {
    devicePixelRatio: Math.min(window.devicePixelRatio || 1, 2.5),
    useDirtyRect: false,
  })
  setStockChart(period, instance)

  const dates = kline.dates as string[]
  const ohlc = kline.ohlc || []
  const volumes = kline.volumes || []
  const ma = kline.ma || {}
  const boll = kline.boll || {}
  const macd = kline.macd || {}
  const range = stockDataZoomRange(dates)
  const tradeMarkers = buildStockTradeMarkers(kline)
  const overlaySeries = buildOverlaySeries(ma, boll)
  const legendData = ['K线', ...overlaySeries.map(s => s.name), '买入', '卖出']

  const ext = (period === stockActivePeriod.value) ? ciOverlay.extension.value
    : { mainSignalSeries: null, subPanel: null, extraXAxisCount: 0 }

  instance.on('click', (params: any) => {
    const trade = params?.data?.trade
    if (trade) selectedPaperTrade.value = trade
  })

  instance.clear()
  instance.setOption({
    animation: false,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter(params: any[]) {
        const points = Array.isArray(params) ? params : [params]
        const scatter = points.find(p => p.seriesType === 'scatter' && p.data?.trade)
        if (scatter) return tradeDetailHtml(scatter.data.trade)
        const first = points[0]
        const index = first?.dataIndex ?? dates.indexOf(first?.axisValue)
        const candle = ohlc[index] || []
        let html = `<b>${first?.axisValue || ''}</b><br/>开: ${fmtMaybe(candle[0])} 收: ${fmtMaybe(candle[1])} 低: ${fmtMaybe(candle[2])} 高: ${fmtMaybe(candle[3])}`
        html += `<br/>MA5: ${fmtMaybe(ma.ma5?.[index])} MA20: ${fmtMaybe(ma.ma20?.[index])} MA30: ${fmtMaybe(ma.ma30?.[index])} MA60: ${fmtMaybe(ma.ma60?.[index])}`
        html += `<br/>BOLL: 上 ${fmtMaybe(boll.upper?.[index])} 中 ${fmtMaybe(boll.middle?.[index])} 下 ${fmtMaybe(boll.lower?.[index])}`
        html += `<br/>RSI14: ${fmtMaybe(kline.rsi?.[index])} MACD柱: ${fmtMaybe(macd.histogram?.[index])}`
        html += `<br/>成交量: ${Number(volumes[index] || 0).toLocaleString()}`
        return html
      },
    },
    legend: { data: legendData, top: 2, textStyle: { fontSize: 11 } },
    title: [
      { text: 'K线主图', subtext: '蜡烛+MA/BOLL叠加，散点为模拟交易记录', left: 60, top: 20, textStyle: { fontSize: 11, color: '#303133', fontWeight: 'bold' as const }, subtextStyle: { fontSize: 9, color: '#909399' }, triggerEvent: true },
      { text: '成交量', subtext: '红涨绿跌·按当日K线方向上色', left: 60, top: 312, textStyle: { fontSize: 11, color: '#303133', fontWeight: 'bold' as const }, subtextStyle: { fontSize: 9, color: '#909399' }, triggerEvent: true },
      { text: 'MACD', subtext: 'DIF/DEA交叉+柱状能量，判趋势强弱', left: 60, top: 402, textStyle: { fontSize: 11, color: '#303133', fontWeight: 'bold' as const }, subtextStyle: { fontSize: 9, color: '#909399' }, triggerEvent: true },
      ...(ext.subPanel ? [{ text: '自定义指标', subtext: '快慢线EMA交叉+策略买卖点(点击查看理由)', left: 60, top: 492, textStyle: { fontSize: 11, color: '#303133', fontWeight: 'bold' as const }, subtextStyle: { fontSize: 9, color: '#909399' }, triggerEvent: true }] : []),
    ],
    grid: [
      { left: 58, right: 38, top: 60, height: 248 },
      { left: 58, right: 38, top: 350, height: 40 },
      { left: 58, right: 38, top: 440, height: 40 },
      ...(ext.subPanel ? [{ left: 58, right: 38, top: 530, height: 60 }] : []),
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: ext.subPanel ? [0, 1, 2, 3] : [0, 1, 2], start: range.start, end: range.end, throttle: 80 },
      { type: 'slider', xAxisIndex: ext.subPanel ? [0, 1, 2, 3] : [0, 1, 2], start: range.start, end: range.end, bottom: 4, height: 20, realtime: false },
    ],
    xAxis: [
      { type: 'category', data: dates, boundaryGap: true, axisLabel: { fontSize: 10 } },
      { type: 'category', data: dates, gridIndex: 1, axisLabel: { show: false } },
      { type: 'category', data: dates, gridIndex: 2, axisLabel: { fontSize: 10 } },
      ...(ext.subPanel ? [{ type: 'category' as const, data: dates, gridIndex: 3, axisLabel: { fontSize: 10 } }] : []),
    ],
    yAxis: [
      { scale: true, axisLabel: { fontSize: 10 }, splitLine: { lineStyle: { type: 'dashed', color: '#eee' } } },
      {
        scale: true,
        gridIndex: 1,
        axisLabel: {
          fontSize: 10,
          formatter: (value: number) => {
            if (Math.abs(value) >= 1e8) return (value / 1e8).toFixed(1) + '亿'
            if (Math.abs(value) >= 1e4) return (value / 1e4).toFixed(0) + '万'
            return String(value)
          },
        },
        splitLine: { show: false },
      },
      { scale: true, gridIndex: 2, axisLabel: { fontSize: 10 }, splitLine: { show: false } },
      ...(ext.subPanel ? [{ scale: true, gridIndex: 3, min: 0, max: 100, splitNumber: 3, axisLabel: { fontSize: 10 } }] : []),
    ],
    series: [
      { name: 'K线', type: 'candlestick', data: ohlc, itemStyle: { color: '#f56c6c', color0: '#67c23a', borderColor: '#f56c6c', borderColor0: '#67c23a' } },
      ...overlaySeries,
      { name: '买入', type: 'scatter', data: tradeMarkers.buy, symbol: 'triangle', symbolSize: 18, itemStyle: { color: '#f56c6c', borderColor: '#8a1f11', borderWidth: 1 }, label: tradeMarkerLabel('buy'), emphasis: { scale: 1.5 } },
      { name: '卖出', type: 'scatter', data: tradeMarkers.sell, symbol: 'diamond', symbolSize: 17, itemStyle: { color: '#67c23a', borderColor: '#2f6f1f', borderWidth: 1 }, label: tradeMarkerLabel('sell'), emphasis: { scale: 1.5 } },
      { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volumes.map((v: any, i: number) => ({
        value: v,
        itemStyle: { color: (ohlc[i] && Number(ohlc[i][1]) >= Number(ohlc[i][0])) ? '#f56c6c' : '#67c23a' },
      })), barMaxWidth: 8 },
      { name: 'MACD柱', type: 'bar', xAxisIndex: 2, yAxisIndex: 2, data: macd.histogram || [], itemStyle: { color: (p: any) => p.value >= 0 ? '#f56c6c' : '#67c23a' }, barMaxWidth: 8 },
      { name: 'DIF', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: macd.dif || [], symbol: 'none', lineStyle: { width: 1, color: '#e6a23c' } },
      { name: 'DEA', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: macd.dea || [], symbol: 'none', lineStyle: { width: 1, color: '#409eff' } },
      ...(ext.mainSignalSeries ? [{ ...ext.mainSignalSeries, xAxisIndex: 0, yAxisIndex: 0 }] : []),
      ...(ext.subPanel ? ext.subPanel.series.map(s => ({ ...s, xAxisIndex: 3, yAxisIndex: 3 })) : []),
    ],
  }, { notMerge: true, lazyUpdate: false })
}

function onResize() {
  if (resizeDebounceTimer !== null) window.clearTimeout(resizeDebounceTimer)
  resizeDebounceTimer = window.setTimeout(() => {
    resizeDebounceTimer = null
    stockDailyChart?.resize()
    stockWeeklyChart?.resize()
    stockMonthlyChart?.resize()
  }, 120)
}

onMounted(() => {
  window.addEventListener('resize', onResize, { passive: true })
  ;(window as any).visualViewport?.addEventListener?.('resize', onResize, { passive: true })
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  ;(window as any).visualViewport?.removeEventListener?.('resize', onResize)
  if (resizeDebounceTimer !== null) window.clearTimeout(resizeDebounceTimer)
  if (stockRenderTimer !== null) window.clearTimeout(stockRenderTimer)
})

function stockDataZoomRange(dates: string[]) {
  if (!dates.length) return { start: 0, end: 100 }
  const tradeDates = selectedStockTrades.value.map((trade: any) => String(trade.date)).filter(Boolean)
  if (!tradeDates.length) return { start: 0, end: 100 }
  const firstTrade = tradeDates[0]
  const lastTrade = tradeDates[tradeDates.length - 1]
  const firstIdx = dates.findIndex(date => date >= firstTrade)
  const lastRaw = dates.findIndex(date => date >= lastTrade)
  const startIdx = Math.max(0, (firstIdx >= 0 ? firstIdx : 0) - 20)
  const endIdx = Math.min(dates.length - 1, (lastRaw >= 0 ? lastRaw : dates.length - 1) + 20)
  return {
    start: Math.max(0, Math.min(100, startIdx / dates.length * 100)),
    end: Math.max(0, Math.min(100, (endIdx + 1) / dates.length * 100)),
  }
}

function buildOverlaySeries(ma: any, boll: any) {
  const selected = new Set(stockOverlayIndicators.value)
  const series: any[] = []
  if (selected.has('MA5')) series.push({ name: 'MA5', type: 'line', data: ma.ma5 || [], symbol: 'none', lineStyle: { width: 1, color: '#e6a23c' } })
  if (selected.has('MA20')) series.push({ name: 'MA20', type: 'line', data: ma.ma20 || [], symbol: 'none', lineStyle: { width: 1, color: '#409eff' } })
  if (selected.has('MA30')) series.push({ name: 'MA30', type: 'line', data: ma.ma30 || [], symbol: 'none', lineStyle: { width: 1, color: '#7f56d9' } })
  if (selected.has('MA60')) series.push({ name: 'MA60', type: 'line', data: ma.ma60 || [], symbol: 'none', lineStyle: { width: 1, color: '#909399' } })
  if (selected.has('BOLL')) {
    series.push(
      { name: 'BOLL上轨', type: 'line', data: boll.upper || [], symbol: 'none', lineStyle: { width: 1, type: 'dashed', color: '#c45656' } },
      { name: 'BOLL中轨', type: 'line', data: boll.middle || [], symbol: 'none', lineStyle: { width: 1, type: 'dashed', color: '#909399' } },
      { name: 'BOLL下轨', type: 'line', data: boll.lower || [], symbol: 'none', lineStyle: { width: 1, type: 'dashed', color: '#529b2e' } },
    )
  }
  return series
}

function buildStockTradeMarkers(kline: any) {
  const dates = kline.dates || []
  const closeValues = (kline.ohlc || []).map((item: any[]) => item?.[1])
  const buy: any[] = []
  const sell: any[] = []
  selectedStockTrades.value.forEach((trade: any) => {
    const idx = findTradeBarIndex(dates, trade.date)
    if (idx < 0) return
    const point = {
      value: [dates[idx], closeValues[idx]],
      trade,
      name: `${directionLabel(trade)} ${trade.code}`,
    }
    if (trade.direction === 'buy') buy.push(point)
    else sell.push(point)
  })
  return { buy, sell }
}

function findTradeBarIndex(dates: string[], tradeDate: string) {
  if (!dates.length) return -1
  const exact = dates.indexOf(tradeDate)
  if (exact >= 0) return exact
  const idx = dates.findIndex(date => date >= tradeDate)
  return idx >= 0 ? idx : dates.length - 1
}

function tradeMarkerLabel(direction: 'buy' | 'sell') {
  return {
    show: true,
    position: direction === 'buy' ? 'bottom' : 'top',
    distance: 6,
    color: direction === 'buy' ? '#a82116' : '#2f6f1f',
    fontSize: 10,
    fontWeight: 600,
    formatter(params: any) {
      const trade = params?.data?.trade
      if (!trade) return direction === 'buy' ? '买' : '卖'
      return `${direction === 'buy' ? '买' : '卖'} ${fmtMaybe(trade.price)}`
    },
  }
}

function indicatorSnapshot(period: string, trade: any) {
  const kline = stockKlines.value[period]
  if (!kline?.dates?.length || !trade) return {}
  const idx = findTradeBarIndex(kline.dates, trade.date)
  if (idx < 0) return {}
  const candle = kline.ohlc?.[idx] || []
  return {
    date: kline.dates[idx],
    open: candle[0],
    close: candle[1],
    low: candle[2],
    high: candle[3],
    volume: kline.volumes?.[idx],
    ma5: kline.ma?.ma5?.[idx],
    ma20: kline.ma?.ma20?.[idx],
    ma30: kline.ma?.ma30?.[idx],
    ma60: kline.ma?.ma60?.[idx],
    bollUpper: kline.boll?.upper?.[idx],
    bollMiddle: kline.boll?.middle?.[idx],
    bollLower: kline.boll?.lower?.[idx],
    rsi: kline.rsi?.[idx],
    macdDif: kline.macd?.dif?.[idx],
    macdDea: kline.macd?.dea?.[idx],
    macdHist: kline.macd?.histogram?.[idx],
  }
}

function tradeDetailHtml(trade: any) {
  const fee = Number(trade.commission || 0) + Number(trade.tax || 0)
  return `<b>${trade.date} ${directionLabel(trade)} ${trade.code} ${stockDisplayName(trade)}</b>`
    + `<br/>成交价: ${fmtMaybe(trade.price)}`
    + `<br/>数量: ${Number(trade.amount || 0).toLocaleString()}`
    + `<br/>成交额: ${props.formatMoneyFull(trade.value)}`
    + `<br/>费用: ${fmtMaybe(fee)}`
}
</script>

<style scoped>
.val-red { color: #f56c6c !important; }
.val-green { color: #67c23a !important; }
.stock-dialog { min-height: 620px; }
.stock-summary {
  display: grid; grid-template-columns: repeat(5, minmax(120px, 1fr)); gap: 8px;
  margin-bottom: 12px;
}
.summary-item {
  display: flex; flex-direction: column; gap: 3px;
  padding: 8px 10px; border: 1px solid #ebeef5; border-radius: 6px; background: #f9fafb;
  min-width: 0;
}
.summary-item.wide { grid-column: span 2; }
.summary-item span { color: #909399; font-size: 12px; }
.summary-item b { color: #303133; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.stock-toolbar {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  padding: 10px 0; border-top: 1px solid #f0f0f0; border-bottom: 1px solid #f0f0f0;
  margin-bottom: 10px;
}
.toolbar-label { font-size: 12px; color: #606266; font-weight: 600; }
.toolbar-hint { color: #909399; font-size: 12px; }
.stock-chart-box { height: 520px; width: 100%; }
.stock-chart-box.has-sub { height: 640px; }
.indicator-panel { margin: 12px 0; }
.panel-title { font-size: 13px; font-weight: 600; color: #303133; margin-bottom: 8px; }
.stock-trade-table { margin-top: 12px; }

@media (max-width: 900px) {
  .stock-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .summary-item.wide { grid-column: span 2; }
}

@media (max-width: 767.98px) {
  .stock-dialog { min-height: 0; }
  .stock-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .summary-item.wide { grid-column: span 2; }
  .stock-chart-box { height: 360px; }
  .stock-chart-box.has-sub { height: 480px; }
  .stock-toolbar {
    gap: 8px;
  }
  .stock-toolbar .toolbar-hint { display: none; }
}
</style>

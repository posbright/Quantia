<template>
  <div class="kline-backtest-chart">
    <div class="overlay-toolbar">
      <div class="overlay-group">
        <span class="group-label">主图叠加</span>
        <el-checkbox-group v-model="mainOverlays" size="small" @change="renderChart">
          <el-checkbox-button v-for="o in mainOptions" :key="o.key" :label="o.key">{{ o.label }}</el-checkbox-button>
        </el-checkbox-group>
      </div>
      <div class="overlay-group">
        <span class="group-label">副图指标</span>
        <el-checkbox-group v-model="subOverlays" size="small" @change="renderChart">
          <el-checkbox-button v-for="o in subOptions" :key="o.key" :label="o.key">{{ o.label }}</el-checkbox-button>
        </el-checkbox-group>
      </div>
    </div>
    <div ref="chartRef" class="chart-canvas" :style="{ height: chartHeight + 'px' }"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onActivated, onBeforeUnmount, nextTick } from 'vue'
import * as echarts from 'echarts'

interface KlinePoint {
  date: string
  open: number
  close: number
  low: number
  high: number
  volume: number
}
interface Indicators {
  recommended?: string[]
  available?: string[]
  ma?: Record<string, (number | null)[]>
  boll?: { up: (number | null)[]; mid: (number | null)[]; dn: (number | null)[] }
  macd?: { dif: (number | null)[]; dea: (number | null)[]; hist: (number | null)[] }
  kdj?: { k: (number | null)[]; d: (number | null)[]; j: (number | null)[] }
  rsi?: Record<string, (number | null)[]>
}
interface Trade {
  no: number
  buy_date: string
  buy_price: number
  sell_date: string | null
  sell_price: number | null
  rate: number
  status: string
}

const props = defineProps<{
  kline: KlinePoint[]
  indicators: Indicators
  trades: Trade[]
}>()

const chartRef = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null
let resizeDebounceTimer: number | null = null
let renderDebounceTimer: number | null = null

const mainOptions = [
  { key: 'ma5', label: 'MA5' },
  { key: 'ma10', label: 'MA10' },
  { key: 'ma20', label: 'MA20' },
  { key: 'ma30', label: 'MA30' },
  { key: 'ma60', label: 'MA60' },
  { key: 'ma250', label: '年线' },
  { key: 'boll', label: 'BOLL' },
]
const subOptions = [
  { key: 'vol', label: '成交量' },
  { key: 'macd', label: 'MACD' },
  { key: 'kdj', label: 'KDJ' },
  { key: 'rsi', label: 'RSI' },
]

const maColors: Record<string, string> = {
  ma5: '#e6a23c', ma10: '#409eff', ma20: '#f56c6c', ma30: '#67c23a', ma60: '#909399', ma250: '#9c27b0',
}

const mainOverlays = ref<string[]>([])
const subOverlays = ref<string[]>([])

const chartHeight = computed(() => 380 + subOverlays.value.length * 130)

// 按后端推荐初始化勾选
const applyRecommended = () => {
  const rec = props.indicators?.recommended || []
  mainOverlays.value = rec.filter(k => k.startsWith('ma') || k === 'boll')
  subOverlays.value = rec.filter(k => ['vol', 'macd', 'kdj', 'rsi'].includes(k))
  if (mainOverlays.value.length === 0 && subOverlays.value.length === 0) {
    mainOverlays.value = ['ma20']
  }
}

const buildOption = (): echarts.EChartsOption => {
  const kl = props.kline || []
  const dates = kl.map(k => k.date)
  const candle = kl.map(k => [k.open, k.close, k.low, k.high])
  const ind = props.indicators || {}

  // 网格布局：主图 + N 个副图
  const subs = subOverlays.value
  const grids: any[] = []
  const xAxes: any[] = []
  const yAxes: any[] = []
  const series: any[] = []

  const mainTop = 8
  const mainHeightPct = subs.length === 0 ? 78 : 56 - subs.length * 2
  const subHeightPct = 14
  const gap = 5

  grids.push({ left: 55, right: 20, top: mainTop + '%', height: mainHeightPct + '%' })
  xAxes.push({ type: 'category', data: dates, gridIndex: 0, boundaryGap: true, axisLine: { onZero: false }, axisLabel: { show: subs.length === 0 } })
  yAxes.push({ scale: true, gridIndex: 0, splitArea: { show: true } })

  // 主图蜡烛
  series.push({
    name: 'K线', type: 'candlestick', data: candle, xAxisIndex: 0, yAxisIndex: 0,
    itemStyle: { color: '#ef232a', color0: '#14b143', borderColor: '#ef232a', borderColor0: '#14b143' },
    markPoint: { symbolSize: 38, label: { fontSize: 10, color: '#fff' }, data: buildMarkPoints() },
  })

  // 主图均线
  mainOverlays.value.filter(k => k.startsWith('ma')).forEach(k => {
    const p = k.replace('ma', '')
    const arr = ind.ma?.[p]
    if (arr) series.push({ name: k.toUpperCase(), type: 'line', data: arr, xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false, lineStyle: { width: 1, color: maColors[k] } })
  })
  // BOLL
  if (mainOverlays.value.includes('boll') && ind.boll) {
    series.push({ name: 'BOLL上轨', type: 'line', data: ind.boll.up, xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, lineStyle: { width: 1, color: '#c0c4cc', type: 'dashed' } })
    series.push({ name: 'BOLL中轨', type: 'line', data: ind.boll.mid, xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, lineStyle: { width: 1, color: '#909399' } })
    series.push({ name: 'BOLL下轨', type: 'line', data: ind.boll.dn, xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, lineStyle: { width: 1, color: '#c0c4cc', type: 'dashed' } })
  }

  // 副图
  let curTop = mainTop + mainHeightPct + gap
  subs.forEach((sub, si) => {
    const gi = si + 1
    grids.push({ left: 55, right: 20, top: curTop + '%', height: subHeightPct + '%' })
    const isLast = si === subs.length - 1
    xAxes.push({ type: 'category', data: dates, gridIndex: gi, boundaryGap: true, axisLine: { onZero: false }, axisLabel: { show: isLast }, axisTick: { show: isLast } })
    yAxes.push({ scale: true, gridIndex: gi, splitNumber: 2, axisLabel: { fontSize: 10 } })

    if (sub === 'vol') {
      series.push({
        name: '成交量', type: 'bar', xAxisIndex: gi, yAxisIndex: gi,
        data: kl.map(k => ({ value: k.volume, itemStyle: { color: k.close >= k.open ? '#ef232a' : '#14b143' } })),
      })
    } else if (sub === 'macd' && ind.macd) {
      series.push({
        name: 'MACD', type: 'bar', xAxisIndex: gi, yAxisIndex: gi,
        data: (ind.macd.hist || []).map(v => ({ value: v, itemStyle: { color: (v ?? 0) >= 0 ? '#ef232a' : '#14b143' } })),
      })
      series.push({ name: 'DIF', type: 'line', data: ind.macd.dif, xAxisIndex: gi, yAxisIndex: gi, showSymbol: false, lineStyle: { width: 1, color: '#e6a23c' } })
      series.push({ name: 'DEA', type: 'line', data: ind.macd.dea, xAxisIndex: gi, yAxisIndex: gi, showSymbol: false, lineStyle: { width: 1, color: '#409eff' } })
    } else if (sub === 'kdj' && ind.kdj) {
      series.push({ name: 'K', type: 'line', data: ind.kdj.k, xAxisIndex: gi, yAxisIndex: gi, showSymbol: false, lineStyle: { width: 1, color: '#e6a23c' } })
      series.push({ name: 'D', type: 'line', data: ind.kdj.d, xAxisIndex: gi, yAxisIndex: gi, showSymbol: false, lineStyle: { width: 1, color: '#409eff' } })
      series.push({ name: 'J', type: 'line', data: ind.kdj.j, xAxisIndex: gi, yAxisIndex: gi, showSymbol: false, lineStyle: { width: 1, color: '#f56c6c' } })
    } else if (sub === 'rsi' && ind.rsi) {
      series.push({ name: 'RSI6', type: 'line', data: ind.rsi['6'], xAxisIndex: gi, yAxisIndex: gi, showSymbol: false, lineStyle: { width: 1, color: '#e6a23c' } })
      series.push({ name: 'RSI12', type: 'line', data: ind.rsi['12'], xAxisIndex: gi, yAxisIndex: gi, showSymbol: false, lineStyle: { width: 1, color: '#409eff' } })
      series.push({ name: 'RSI24', type: 'line', data: ind.rsi['24'], xAxisIndex: gi, yAxisIndex: gi, showSymbol: false, lineStyle: { width: 1, color: '#9c27b0' } })
    }
    curTop += subHeightPct + gap
  })

  const xCount = xAxes.length
  return {
    animation: false,
    legend: { top: 0, type: 'scroll' },
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross', link: [{ xAxisIndex: 'all' }] } },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    grid: grids,
    xAxis: xAxes,
    yAxis: yAxes,
    dataZoom: [
      { type: 'inside', xAxisIndex: Array.from({ length: xCount }, (_, i) => i), start: 0, end: 100, throttle: 80 },
      { type: 'slider', xAxisIndex: Array.from({ length: xCount }, (_, i) => i), start: 0, end: 100, bottom: 6, height: 18, realtime: false },
    ],
    series,
  }
}

const buildMarkPoints = () => {
  const pts: any[] = []
  const dateSet = new Map<string, number>()
  ;(props.kline || []).forEach((k, i) => dateSet.set(k.date, i))
  ;(props.trades || []).forEach(t => {
    if (t.buy_date && dateSet.has(t.buy_date)) {
      pts.push({
        name: '买', coord: [t.buy_date, t.buy_price], value: '买',
        symbol: 'triangle', symbolRotate: 0, symbolOffset: [0, 12],
        itemStyle: { color: '#ef232a' },
        label: { formatter: '买', position: 'bottom' },
      })
    }
    if (t.sell_date && t.sell_price != null && dateSet.has(t.sell_date)) {
      pts.push({
        name: '卖', coord: [t.sell_date, t.sell_price], value: '卖',
        symbol: 'triangle', symbolRotate: 180, symbolOffset: [0, -12],
        itemStyle: { color: '#3a7afe' },
        label: { formatter: '卖', position: 'top' },
      })
    }
  })
  return pts
}

const renderChart = () => {
  if (renderDebounceTimer !== null) window.clearTimeout(renderDebounceTimer)
  renderDebounceTimer = window.setTimeout(() => {
    renderDebounceTimer = null
    if (!chart) return
    chart.setOption(buildOption(), true)
  }, 60)
}

const initChart = () => {
  if (!chartRef.value) return
  if (!chart) chart = echarts.init(chartRef.value)
  renderChart()
}

const resize = () => {
  if (resizeDebounceTimer !== null) window.clearTimeout(resizeDebounceTimer)
  resizeDebounceTimer = window.setTimeout(() => {
    resizeDebounceTimer = null
    nextTick(() => chart?.resize())
  }, 120)
}

// 定位到指定交易日：将 dataZoom 缩放到该日前后约 20 根 K 线的窗口
const locate = (date: string) => {
  if (!chart || !date) return
  const kl = props.kline || []
  const idx = kl.findIndex(k => k.date === date)
  if (idx < 0) return
  const total = kl.length
  if (total <= 1) return
  const half = 20
  const startPct = Math.max(0, ((idx - half) / total) * 100)
  const endPct = Math.min(100, ((idx + half) / total) * 100)
  chart.dispatchAction({ type: 'dataZoom', start: startPct, end: endPct })
}

watch(() => props.kline, () => {
  applyRecommended()
  nextTick(initChart)
})
watch(chartHeight, () => resize())

onMounted(() => {
  applyRecommended()
  nextTick(initChart)
  window.addEventListener('resize', resize)
})
onActivated(() => resize())
onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  if (resizeDebounceTimer !== null) window.clearTimeout(resizeDebounceTimer)
  if (renderDebounceTimer !== null) window.clearTimeout(renderDebounceTimer)
  chart?.dispose()
  chart = null
})

defineExpose({ resize, locate })
</script>

<style scoped>
.kline-backtest-chart {
  width: 100%;
}
.overlay-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 10px;
}
.overlay-group {
  display: flex;
  align-items: center;
  gap: 8px;
}
.group-label {
  font-size: 12px;
  color: #909399;
  white-space: nowrap;
}
.chart-canvas {
  width: 100%;
}
</style>

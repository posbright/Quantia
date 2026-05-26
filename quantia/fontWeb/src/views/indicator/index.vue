<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as echarts from 'echarts'
import dayjs from 'dayjs'
import { getKlineData, type KlineParams } from '@/api/stock'
import { ElMessage } from 'element-plus'
import { useCustomIndicatorOverlay } from '@/composables/useCustomIndicatorOverlay'
import CustomIndicatorOverlayBar from '@/components/CustomIndicatorOverlayBar.vue'

const route = useRoute()
const router = useRouter()

let chartInstance: echarts.ECharts | null = null

const code = computed(() => route.query.code as string)
const date = computed(() => route.query.date as string || dayjs().format('YYYY-MM-DD'))
const stockName = computed(() => route.query.name as string)
const strategy = computed(() => route.query.strategy as string || '')

const klineChartRef = ref<HTMLDivElement>()
const loading = ref(false)

// === Period tabs ===
const currentPeriod = ref('daily')
const periods = [
  { label: '日K', value: 'daily' },
  { label: '周K', value: 'weekly' },
  { label: '月K', value: 'monthly' },
  { label: '季K', value: 'quarterly' },
  { label: '年K', value: 'yearly' },
]

// === Main chart overlay toggles ===
const mainOverlays = ref<string[]>(['MA'])
const mainOverlayOptions = [
  { label: '均线', value: 'MA' },
  { label: 'BOLL', value: 'BOLL' },
]

// === Sub indicator tabs (East Money style bottom bar) ===
const currentSubIndicator = ref('MACD')
const subIndicatorOptions = ['MACD', 'KDJ', 'RSI', 'WR', '多空趋势']

// K-line data
const klineData = ref<any>(null)

// === 自定义指标叠加 (PR-5) ===
const klineDates = computed<string[]>(() => klineData.value?.dates || [])
const codeStr = computed(() => code.value || '')
const ciOverlay = useCustomIndicatorOverlay(codeStr, currentPeriod, klineDates)

// 容器高度根据是否有 CI 自定义指标副图自适应（和 renderChart 中 grid 计算保持一致）
const chartHeight = computed(() => (ciOverlay.extension.value?.subPanel ? 780 : 680))

// Load K-line data
const loadKlineData = async () => {
  if (!code.value) return
  loading.value = true
  try {
    const params: KlineParams = {
      code: code.value,
      date: date.value,
      period: currentPeriod.value,
      name: stockName.value || '',
    }
    // 根据来源表名判断数据类型，避免同代码股票/指数混淆（如 000001）
    if (strategy.value.includes('index')) {
      params.type = 'index'
    } else if (strategy.value.includes('etf')) {
      params.type = 'etf'
    }
    const res = await getKlineData(params) as any
    if (res?.error) {
      ElMessage.warning(res.error)
      klineData.value = null
    } else {
      klineData.value = res
    }
  } catch (e: any) {
    ElMessage.error('K线数据加载失败')
    klineData.value = null
  } finally {
    loading.value = false
    await nextTick()
    renderChart()
  }
}

// === Format volume for axis labels ===
const formatVolume = (val: number): string => {
  if (val >= 1e8) return (val / 1e8).toFixed(2) + '亿'
  if (val >= 1e4) return (val / 1e4).toFixed(1) + '万'
  return val.toString()
}

// === Smart dataZoom start per period (show recent N bars like East Money) ===
const getZoomStart = (total: number): number => {
  const visible: Record<string, number> = {
    daily: 80,       // ~4 months of trading days
    weekly: 52,      // ~1 year
    monthly: 24,     // ~2 years
    quarterly: 12,   // ~3 years
    yearly: 9999,    // show all
  }
  const n = visible[currentPeriod.value] || 80
  if (n >= total) return 0
  return Math.max(0, Math.round((1 - n / total) * 100))
}

// === East Money color scheme ===
const COLORS = {
  up: '#ec0000',
  down: '#00da3c',
  ma5: '#FF9900',
  ma10: '#0099FF',
  ma20: '#FF00FF',
  ma30: '#888800',
  ma60: '#00CC66',
  bollUpper: '#e6a23c',
  bollMiddle: '#909399',
  bollLower: '#67c23a',
}

// === Render ECharts ===
const renderChart = () => {
  if (!klineChartRef.value || !klineData.value) return
  const d = klineData.value

  if (chartInstance) { chartInstance.dispose() }
  chartInstance = echarts.init(klineChartRef.value)

  const dates: string[] = d.dates
  const ohlc: number[][] = d.ohlc
  const volumes: number[] = d.volumes
  const ma = d.ma || {}
  const volMa = d.vol_ma || {}
  const boll = d.boll || {}
  const rsi: (number | null)[] = d.rsi || []
  const macd = d.macd || {}
  const kdj = d.kdj || {}
  const wr = d.wr || {}
  const bbi = d.bbi || {}

  const showMA = mainOverlays.value.includes('MA')
  const showBollOnMain = mainOverlays.value.includes('BOLL')
  const subInd = currentSubIndicator.value
  const hasSub = ['MACD', 'KDJ', 'RSI', 'WR', '多空趋势'].includes(subInd)

  // Volume bar coloring
  const volData = volumes.map((v, i) => ({
    value: v,
    itemStyle: {
      color: ohlc[i] && ohlc[i][1] >= ohlc[i][0] ? COLORS.up : COLORS.down
    }
  }))

  // === 布局：使用绝对像素的 grid + title 标签，避免百分比导致的副图重叠 ===
  // 三段独立 grid，子图之间留 ≥30px 间距给标题，再用 graphic 画虚线分隔条
  // 容器高 680px：预留上 60（图例 + 主标题）、下 30（dataZoom slider）
  const stockLabel = (stockName.value ? `${code.value} ${stockName.value}` : code.value || '') + ` · ${currentPeriod.value}`
  const subLabelMap: Record<string, string> = {
    MACD: 'MACD (12,26,9)', KDJ: 'KDJ (9,3,3)', RSI: 'RSI (14)',
    WR: 'WR (10/6)', '多空趋势': '多空趋势 (BBI/MABB)',
  }
  const subLabel = subLabelMap[subInd] || subInd

  const grids: any[] = []
  const titleItems: any[] = []
  const dividers: number[] = []  // y-像素位置，稍后渲染为分割线
  const titleStyle = { fontSize: 12, color: '#303133', fontWeight: 'bold' as const }
  const subTitleStyle = { fontSize: 10, color: '#909399' }
  if (hasSub) {
    // 主图 60-320  分割线 340  成交量 380-450  分割线 470  副图 510-610  slider 644-662
    grids.push(
      { left: 60, right: 24, top: 60, height: 260 },
      { left: 60, right: 24, top: 380, height: 70 },
      { left: 60, right: 24, top: 510, height: 100 },
    )
    titleItems.push(
      { text: `K线主图 · ${stockLabel}`, subtext: showMA && showBollOnMain ? 'MA + BOLL' : showMA ? 'MA 均线' : showBollOnMain ? 'BOLL 布林带' : '蜡烛图', left: 60, top: 36, textStyle: titleStyle, subtextStyle: subTitleStyle },
      { text: '成交量', subtext: '红涨绿跌·按当日K线方向上色', left: 60, top: 358, textStyle: titleStyle, subtextStyle: subTitleStyle },
      { text: subLabel, subtext: '副图指标', left: 60, top: 488, textStyle: titleStyle, subtextStyle: subTitleStyle },
    )
    dividers.push(340, 470)
  } else {
    // 主图 60-400  分割线 420  成交量 460-600  slider 644-662
    grids.push(
      { left: 60, right: 24, top: 60, height: 340 },
      { left: 60, right: 24, top: 460, height: 140 },
    )
    titleItems.push(
      { text: `K线主图 · ${stockLabel}`, subtext: showMA && showBollOnMain ? 'MA + BOLL' : showMA ? 'MA 均线' : showBollOnMain ? 'BOLL 布林带' : '蜡烛图', left: 60, top: 36, textStyle: titleStyle, subtextStyle: subTitleStyle },
      { text: '成交量', subtext: '红涨绿跌·按当日K线方向上色', left: 60, top: 438, textStyle: titleStyle, subtextStyle: subTitleStyle },
    )
    dividers.push(420)
  }

  // === X/Y axes ===
  const xAxes: any[] = [
    {
      type: 'category', data: dates, boundaryGap: false,
      axisLine: { onZero: false, lineStyle: { color: '#ccc' } },
      splitLine: { show: false },
      axisLabel: { fontSize: 10, color: '#666' },
      min: 'dataMin', max: 'dataMax',
    },
    {
      type: 'category', gridIndex: 1, data: dates,
      axisLabel: { show: false }, axisTick: { show: false }, axisLine: { show: false },
    },
  ]
  const yAxes: any[] = [
    {
      scale: true,
      splitArea: { show: true, areaStyle: { color: ['rgba(250,250,250,0.3)', 'rgba(240,240,240,0.3)'] } },
      splitLine: { lineStyle: { color: '#eee' } },
      axisLabel: { fontSize: 10, color: '#666' },
    },
    {
      scale: true, gridIndex: 1, splitNumber: 2,
      axisLabel: { show: true, fontSize: 9, color: '#999', formatter: (v: number) => formatVolume(v) },
      axisLine: { show: false }, axisTick: { show: false },
      splitLine: { show: false },
    },
  ]
  if (hasSub) {
    xAxes.push({
      type: 'category', gridIndex: 2, data: dates,
      axisLabel: { show: false }, axisTick: { show: false }, axisLine: { show: false },
    })
    // Dynamic y-axis config based on sub-indicator type
    const subYAxis: any = {
      scale: true, gridIndex: 2, splitNumber: 3,
      axisLabel: { show: true, fontSize: 9, color: '#999' },
      axisLine: { show: false }, axisTick: { show: false },
      splitLine: { lineStyle: { color: '#f5f5f5' } },
    }
    if (subInd === 'KDJ') {
      subYAxis.min = -20
      subYAxis.max = 120
    } else if (subInd === 'WR') {
      subYAxis.min = -100
      subYAxis.max = 0
    } else if (subInd === 'RSI') {
      subYAxis.min = 0
      subYAxis.max = 100
    }
    yAxes.push(subYAxis)
  }

  // === Legend ===
  const legendData: string[] = []
  if (showMA) legendData.push('MA5', 'MA10', 'MA20', 'MA30', 'MA60')
  if (showBollOnMain) legendData.push('BOLL上轨', 'BOLL中轨', 'BOLL下轨')

  // === Series ===
  const series: any[] = [
    {
      name: 'K线', type: 'candlestick', data: ohlc,
      itemStyle: {
        color: COLORS.up, color0: COLORS.down,
        borderColor: COLORS.up, borderColor0: COLORS.down,
      },
      markPoint: {
        symbol: 'rect',
        symbolSize: [1, 8],
        label: {
          show: true,
          fontSize: 10,
          fontWeight: 'bold',
          formatter: (p: any) => p.data.type === 'max' ? `── ${p.value}` : `── ${p.value}`,
        },
        data: [
          {
            name: '最高价', type: 'max', valueDim: 'highest',
            itemStyle: { color: 'transparent' },
            label: { position: 'top', color: COLORS.up },
          },
          {
            name: '最低价', type: 'min', valueDim: 'lowest',
            itemStyle: { color: 'transparent' },
            label: { position: 'bottom', color: COLORS.down },
          },
        ],
      },
    },
  ]

  // MA lines
  if (showMA) {
    const maLines: [string, any, string][] = [
      ['MA5', ma.ma5, COLORS.ma5],
      ['MA10', ma.ma10, COLORS.ma10],
      ['MA20', ma.ma20, COLORS.ma20],
      ['MA30', ma.ma30, COLORS.ma30],
      ['MA60', ma.ma60, COLORS.ma60],
    ]
    for (const [name, data, color] of maLines) {
      if (data) {
        series.push({
          name, type: 'line', data, smooth: true,
          lineStyle: { width: 1, color }, symbol: 'none',
        })
      }
    }
  }

  // BOLL overlay on main chart
  if (showBollOnMain && boll.upper) {
    series.push(
      { name: 'BOLL上轨', type: 'line', data: boll.upper, lineStyle: { width: 1, type: 'dashed', color: COLORS.bollUpper }, symbol: 'none' },
      { name: 'BOLL中轨', type: 'line', data: boll.middle, lineStyle: { width: 1, color: COLORS.bollMiddle }, symbol: 'none' },
      { name: 'BOLL下轨', type: 'line', data: boll.lower, lineStyle: { width: 1, type: 'dashed', color: COLORS.bollLower }, symbol: 'none' },
    )
  }

  // Volume bars + volume MA lines
  series.push(
    { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volData, barMaxWidth: 8 },
  )
  if (volMa.ma5) {
    series.push({
      name: 'VOL MA5', type: 'line', xAxisIndex: 1, yAxisIndex: 1,
      data: volMa.ma5, lineStyle: { width: 1, color: COLORS.ma5 }, symbol: 'none',
    })
  }
  if (volMa.ma10) {
    series.push({
      name: 'VOL MA10', type: 'line', xAxisIndex: 1, yAxisIndex: 1,
      data: volMa.ma10, lineStyle: { width: 1, color: COLORS.ma10 }, symbol: 'none',
    })
  }

  // === Sub indicator chart ===
  if (hasSub) {
    if (subInd === 'MACD' && macd.dif) {
      legendData.push('DIF', 'DEA', 'MACD柱')
      const macdBarData = (macd.histogram || []).map((v: number | null) => ({
        value: v,
        itemStyle: { color: v !== null && v >= 0 ? COLORS.up : COLORS.down }
      }))
      series.push(
        { name: 'DIF', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: macd.dif, connectNulls: true, lineStyle: { width: 1 }, symbol: 'none' },
        { name: 'DEA', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: macd.dea, connectNulls: true, lineStyle: { width: 1, color: COLORS.ma5 }, symbol: 'none' },
        { name: 'MACD柱', type: 'bar', xAxisIndex: 2, yAxisIndex: 2, data: macdBarData, barMaxWidth: 4 },
      )
    }

    if (subInd === 'KDJ') {
      const kArr = kdj.k || []
      const dArr = kdj.d || []
      const jArr = kdj.j || []
      if (kArr.length > 0) {
        legendData.push('K(9,3,3)', 'D(9,3,3)', 'J(9,3,3)')
        series.push(
          { name: 'K(9,3,3)', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: kArr, connectNulls: true, lineStyle: { width: 1, color: COLORS.ma5 }, symbol: 'none' },
          { name: 'D(9,3,3)', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: dArr, connectNulls: true, lineStyle: { width: 1, color: COLORS.ma10 }, symbol: 'none' },
          { name: 'J(9,3,3)', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: jArr, connectNulls: true, lineStyle: { width: 1, color: COLORS.ma20 }, symbol: 'none' },
        )
      }
    }

    if (subInd === 'RSI') {
      if (rsi.length > 0) {
        legendData.push('RSI(14)')
        series.push(
          { name: 'RSI(14)', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: rsi, connectNulls: true, lineStyle: { width: 1, color: COLORS.ma5 }, symbol: 'none' },
        )
      }
    }

    if (subInd === 'WR') {
      const wr10Arr = wr.wr10 || []
      const wr6Arr = wr.wr6 || []
      if (wr10Arr.length > 0) {
        legendData.push('WR(10)', 'WR(6)')
        series.push(
          { name: 'WR(10)', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: wr10Arr, connectNulls: true, lineStyle: { width: 1, color: COLORS.ma5 }, symbol: 'none' },
          { name: 'WR(6)', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: wr6Arr, connectNulls: true, lineStyle: { width: 1, color: COLORS.ma10 }, symbol: 'none' },
        )
      }
    }

    if (subInd === '多空趋势') {
      const bbiArr = bbi.bbi || []
      const mabbArr = bbi.mabb || []
      if (bbiArr.length > 0) {
        legendData.push('BBI(3,6,12,24)', 'MABB(6)')
        series.push(
          { name: 'BBI(3,6,12,24)', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: bbiArr, connectNulls: true, lineStyle: { width: 1.5, color: '#e6a23c' }, symbol: 'none' },
          { name: 'MABB(6)', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: mabbArr, connectNulls: true, lineStyle: { width: 1.5, color: '#409eff' }, symbol: 'none' },
        )
      }
    }
  }

  // === dataZoom ===
  const zoomStart = getZoomStart(dates.length)
  const zoomXIndices: number[] = hasSub ? [0, 1, 2] : [0, 1]

  // === 自定义指标叠加 (PR-5) ===
  const ext = ciOverlay.extension.value
  if (ext.mainSignalSeries) {
    series.push(ext.mainSignalSeries)
    legendData.push(ext.mainSignalSeries.name)
  }
  if (ext.subPanel) {
    // 启用 CI 自定义指标副图：在已有布局尾部追加一段，并在其上方画分割线
    // 整体容器高度通过 chartHeight 计算属性自动增高（详见 <template>）
    const ciTopActual = 644
    const ciDividerY = ciTopActual - 22
    const ciIdx = grids.length
    grids.push({ left: 60, right: 24, top: ciTopActual, height: 90 })
    titleItems.push({ text: '自定义指标', subtext: 'CI 叠加（快慢线 EMA / 策略买卖点）', left: 60, top: ciTopActual - 24, textStyle: titleStyle, subtextStyle: subTitleStyle })
    dividers.push(ciDividerY - 12)
    xAxes.push({ ...ext.subPanel.xAxis, gridIndex: ciIdx })
    yAxes.push({ ...ext.subPanel.yAxis, gridIndex: ciIdx })
    for (const s of ext.subPanel.series) {
      series.push({ ...s, xAxisIndex: ciIdx, yAxisIndex: ciIdx })
    }
    legendData.push(...ext.subPanel.legend)
    zoomXIndices.push(ciIdx)
  }

  // 分割线 graphic：每条 dashed 横线横跨整个绘图区
  const graphicElements: any[] = dividers.map(y => ({
    type: 'line' as const,
    left: 60,
    right: 24,
    top: y,
    silent: true,
    z: 1,
    shape: { x1: 0, y1: 0, x2: 9999, y2: 0 },
    style: { stroke: '#dcdfe6', lineWidth: 1, lineDash: [4, 4] },
  }))

  const option: echarts.EChartsOption = {
    animation: false,
    title: titleItems,
    graphic: graphicElements,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: 'rgba(255,255,255,0.96)',
      borderColor: '#ddd',
      textStyle: { fontSize: 12, color: '#333' },
    },
    legend: {
      data: legendData,
      top: 4, left: 220,
      textStyle: { fontSize: 11 },
      itemWidth: 14, itemHeight: 10,
    },
    grid: grids,
    xAxis: xAxes,
    yAxis: yAxes,
    dataZoom: [
      { type: 'inside', xAxisIndex: zoomXIndices, start: zoomStart, end: 100 },
      {
        show: true, xAxisIndex: zoomXIndices, type: 'slider',
        bottom: 6, height: 18, start: zoomStart, end: 100,
        borderColor: '#ddd', fillerColor: 'rgba(64,158,255,0.15)',
        handleStyle: { color: '#409eff' },
      },
    ],
    series,
  }

  chartInstance.setOption(option)
}

// Switch period
const switchPeriod = (p: string) => {
  currentPeriod.value = p
  loadKlineData()
}

// Re-render chart (no data reload) when overlay or sub-indicator changes
watch([currentSubIndicator, mainOverlays], () => { renderChart() }, { deep: true })

// PR-5: 自定义指标叠加变化时重渲
watch(() => ciOverlay.extension.value, async () => { await nextTick(); renderChart() }, { deep: true })

// Navigate to backtest
const goBacktest = () => {
  router.push({
    path: '/backtest/custom',
    query: { code: code.value, name: stockName.value, strategy: strategy.value || undefined }
  })
}

const handleResize = () => { chartInstance?.resize() }

watch(() => route.query.code, (newCode, oldCode) => {
  if (newCode && newCode !== oldCode) {
    currentPeriod.value = 'daily'
    loadKlineData()
  }
})

// M0: 仅在 onMounted 绑 resize，onUnmounted 解绑 + dispose chart。
// 项目未使用 <keep-alive>，所以 onActivated / onDeactivated 不会触发、不需要处理。
onMounted(() => {
  loadKlineData()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  chartInstance?.dispose()
  chartInstance = null
})
</script>

<template>
  <div class="indicator-container">
    <!-- Top info bar -->
    <div class="top-bar">
      <div class="stock-basic">
        <span class="stock-code">{{ code }}</span>
        <span class="stock-name">{{ stockName }}</span>
        <el-tag size="small" effect="plain">{{ date }}</el-tag>
      </div>
      <div class="top-actions">
        <el-button type="primary" size="small" @click="goBacktest">查看回测</el-button>
      </div>
    </div>

    <!-- Toolbar: period tabs + main chart overlay checkboxes -->
    <div class="toolbar">
      <div class="toolbar-left">
        <div class="period-tabs">
          <span
            v-for="p in periods" :key="p.value"
            :class="['period-tab', { active: currentPeriod === p.value }]"
            @click="switchPeriod(p.value)"
          >{{ p.label }}</span>
        </div>
        <div class="overlay-checks">
          <span class="label">主图指标</span>
          <el-checkbox-group v-model="mainOverlays" size="small">
            <el-checkbox v-for="opt in mainOverlayOptions" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </el-checkbox>
          </el-checkbox-group>
        </div>
        <CustomIndicatorOverlayBar :state="ciOverlay" />
      </div>
    </div>

    <!-- Chart area -->
    <div class="chart-wrapper" v-loading="loading">
      <div ref="klineChartRef" class="chart-main" :style="{ height: chartHeight + 'px' }"></div>
      <!-- Sub indicator tab bar (East Money style) -->
      <div class="sub-indicator-bar">
        <span
          v-for="ind in subIndicatorOptions" :key="ind"
          :class="['sub-tab', { active: currentSubIndicator === ind }]"
          @click="currentSubIndicator = ind"
        >{{ ind }}</span>
      </div>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.indicator-container {
  display: flex;
  flex-direction: column;
  gap: 0;
  background: #fff;
  border-radius: 4px;
  overflow: hidden;
}

/* Top info bar */
.top-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  border-bottom: 1px solid #eee;
}
.stock-basic {
  display: flex; align-items: center; gap: 10px;
  .stock-code { font-size: 18px; font-weight: 700; color: #333; }
  .stock-name { font-size: 16px; color: #666; }
}

/* Toolbar */
.toolbar {
  display: flex; align-items: center; padding: 6px 16px; border-bottom: 1px solid #f0f0f0;
  background: #fafafa;
}
.toolbar-left {
  display: flex; align-items: center; gap: 24px; flex-wrap: wrap;
}
.period-tabs {
  display: flex; gap: 2px;
  .period-tab {
    padding: 3px 12px; font-size: 13px; cursor: pointer; border-radius: 3px;
    color: #666; transition: all .15s;
    &:hover { background: #e8f0fe; color: #409eff; }
    &.active { background: #409eff; color: #fff; font-weight: 600; }
  }
}
.overlay-checks {
  display: flex; align-items: center; gap: 6px;
  .label { font-size: 12px; color: #999; }
}

/* Chart */
.chart-wrapper {
  position: relative;
}
.chart-main {
  height: 680px; /* 默认值，动态由 :style="{height}" 覆盖 */
}

/* Sub indicator tab bar */
.sub-indicator-bar {
  display: flex; gap: 0; border-top: 1px solid #eee; background: #fafafa;
  .sub-tab {
    flex: 1; text-align: center; padding: 5px 0; font-size: 12px;
    cursor: pointer; color: #888; border-right: 1px solid #eee;
    transition: all .15s; user-select: none;
    &:last-child { border-right: none; }
    &:hover { background: #e8f0fe; color: #409eff; }
    &.active { background: #fff; color: #409eff; font-weight: 600; border-bottom: 2px solid #409eff; }
  }
}
</style>
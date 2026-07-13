<script setup lang="ts">
import { ref, shallowRef, onMounted, onUnmounted, onActivated, onDeactivated, computed, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as echarts from 'echarts'
import dayjs from 'dayjs'
import { getKlineData, getFinancialSummary, getBacktestHistory, getKpred, getChipDistribution, type KlineParams, type FinancialSummaryResult, type KpredResult, type KpredPrediction, type ChipDistributionResult } from '@/api/stock'
import { getReportHistory, getStockQuote, getAttentionList, setAttention, type ReportHistoryItem, type StockQuote } from '@/api/report'
import { getStrategyHistory } from '@/api/strategy'
import { ChatDotRound, ArrowDown, Star, StarFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useCustomIndicatorOverlay } from '@/composables/useCustomIndicatorOverlay'
import CustomIndicatorOverlayBar from '@/components/CustomIndicatorOverlayBar.vue'
import { useResponsive } from '@/composables/useResponsive'
import { useChartFullscreen } from '@/composables/useChartFullscreen'
import ChartFullscreenBtn from '@/components/ChartFullscreenBtn.vue'
import PatentCard from '@/components/PatentCard.vue'
import CompanyProfileCard from '@/components/CompanyProfileCard.vue'

const route = useRoute()
const router = useRouter()

let chartInstance: echarts.ECharts | null = null
const chartShallow = shallowRef<echarts.ECharts | null>(null)
const klineWrapRef = ref<HTMLDivElement>()
const klineChartFs = useChartFullscreen(klineWrapRef, chartShallow)
let resizeDebounceTimer: number | null = null

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
  { label: '筹码', value: 'CYQ' },
]

// === Sub indicator tabs (East Money style bottom bar) ===
const currentSubIndicator = ref('MACD')
const subIndicatorOptions = ['MACD', 'KDJ', 'RSI', 'WR', '多空趋势']

// K-line data
const klineData = ref<any>(null)

// === 筹码分布 (CYQ) ===
// DB 标量优先 + 直方图现算：勾选"筹码"叠加项时按需拉取，缓存于组件内
const chipData = ref<ChipDistributionResult | null>(null)
const chipLoading = ref(false)
const showChip = computed(() => mainOverlays.value.includes('CYQ'))
const loadChipData = async () => {
  if (!code.value) return
  chipLoading.value = true
  try {
    chipData.value = await getChipDistribution({
      code: code.value, date: date.value, name: stockName.value || '',
    })
  } catch {
    chipData.value = null
  } finally {
    chipLoading.value = false
  }
}

// 筹码读数条格式化
const fmtChipNum = (v: number | null | undefined) => (v == null || !isFinite(Number(v))) ? '--' : Number(v).toFixed(2)
const fmtChipPct = (v: number | null | undefined) => (v == null || !isFinite(Number(v))) ? '--' : Number(v).toFixed(2) + '%'
const fmtChipConc = (v: number | null | undefined) => (v == null || !isFinite(Number(v))) ? '--' : (Number(v) * 100).toFixed(2) + '%'
const fmtChipRange = (lo: number | null | undefined, hi: number | null | undefined) =>
  (lo == null || hi == null || !isFinite(Number(lo)) || !isFinite(Number(hi))) ? '--' : `${Number(lo).toFixed(2)} ~ ${Number(hi).toFixed(2)}`
const winnerRateCls = computed(() => {
  const w = chipData.value?.metrics?.winner_rate
  return (w == null) ? '' : (w >= 50 ? 'kt-up' : 'kt-down')
})
const chipSourceLabel = computed(() => {
  const s = chipData.value?.metrics_source
  return s === 'db' ? '库存标量' : s === 'compute' ? '实时计算' : s === 'db_stale' ? '库存(历史)' : ''
})

// === 策略选中标记 (策略选股有效性可视化) ===
// 该股票被当前策略历史选中的全部日期（来自策略选股结果表），在日K主图上以图钉标注
const strategyMarkDates = ref<string[]>([])
const strategyMarkName = ref<string>('')
let lastMarkKey = ''  // `${code}|${strategy}` 缓存键，避免重复请求

const loadStrategyMarks = async () => {
  const stg = strategy.value
  // 仅当带有策略标识、且为个股时才查询（指数/ETF/资金流等非策略选股表后端会返回空）
  if (!code.value || !stg) {
    strategyMarkDates.value = []
    strategyMarkName.value = ''
    lastMarkKey = ''
    return
  }
  const key = `${code.value}|${stg}`
  if (key === lastMarkKey) return  // 同股票同策略已查过，直接复用
  lastMarkKey = key
  try {
    const res: any = await getStrategyHistory(stg, code.value)
    if (res?.success && Array.isArray(res.dates)) {
      strategyMarkDates.value = res.dates
      strategyMarkName.value = res.strategy_name || ''
    } else {
      strategyMarkDates.value = []
      strategyMarkName.value = ''
    }
  } catch {
    strategyMarkDates.value = []
    strategyMarkName.value = ''
  }
}

// === 行情快照（实时盘口）===
// 复用个股分析页(stock/analysis.vue)的 /api/ai/report/quote 接口，在 K 线上方
// 展示现价/涨跌/今开高低收/量额/振幅换手/市值估值/股本，提升详情页信息密度与体验。
const quoteData = ref<StockQuote | null>(null)
const quoteLoading = ref(false)
const quoteCollapsed = ref(false)  // 折叠盘口指标网格（保留现价行）

// === 财务分析数据 ===
const financialData = ref<FinancialSummaryResult | null>(null)
const financialLoading = ref(false)
const financialChartRef = ref<HTMLDivElement>()
const expenseChartRef = ref<HTMLDivElement>()
let financialChartInstance: echarts.ECharts | null = null
let expenseChartInstance: echarts.ECharts | null = null

// 判断是否有费用数据
const hasExpenseData = computed(() => {
  const hist = financialData.value?.history
  if (!hist?.length) return false
  return hist.some(h => h.rd_expense != null || h.admin_expense != null)
})

// === AI 分析历史报告 ===
const latestReport = ref<ReportHistoryItem | null>(null)
const reportLoading = ref(false)

// === 专利/护城河卡片是否有数据（无数据则隐藏该卡片）===
const patentHasData = ref(false)
const onPatentLoaded = (hasData: boolean) => {
  patentHasData.value = hasData
}

// === 公司概况卡片是否有数据（非个股如ETF/指数无数据时隐藏）===
const profileHasData = ref(false)
const onProfileLoaded = (hasData: boolean) => {
  profileHasData.value = hasData
}

// === 关注 / 取消关注（个股详情页入口）===
const attentionCodes = ref<string[]>([])
const watchLoading = ref(false)
const isWatched = computed(() => !!code.value && attentionCodes.value.includes(code.value))

// === 自定义指标叠加 (PR-5) ===
const klineDates = computed<string[]>(() => klineData.value?.dates || [])
const codeStr = computed(() => code.value || '')
const ciOverlay = useCustomIndicatorOverlay(codeStr, currentPeriod, klineDates)

// === K线预测（AgentPit / 本地兼容服务） ===
const predEnabled = ref(false)
const predDays = ref(5)
const predDaysOptions = [3, 5, 10]
const predLoading = ref(false)
const predData = ref<KpredResult | null>(null)
const predError = ref('')  // 预测失败时的错误信息（持久显示，直到下次成功或关闭开关）
let predRequestSeq = 0  // 请求序列号，防止快速切股时旧请求覆盖新数据

const predPro = computed(() => predData.value?.pro || null)
const predFactors = computed(() => predPro.value?.factors || [])
const toPredNumber = (value: unknown): number => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}
const fmtPredNumber = (value: unknown, digits = 2): string => toPredNumber(value).toFixed(digits)
const fmtPredSigned = (value: unknown, digits = 3): string => {
  const parsed = toPredNumber(value)
  return `${parsed >= 0 ? '+' : ''}${parsed.toFixed(digits)}`
}
const predValueClass = (value: unknown): string => toPredNumber(value) >= 0 ? 'is-up' : 'is-down'
const predProviderLabel = computed(() => predData.value?.provider === 'local' ? '本地模型' : 'AgentPit')

const loadPrediction = async (forceRefresh = false) => {
  if (!code.value) return
  predLoading.value = true
  predData.value = null
  predError.value = ''
  const seq = ++predRequestSeq
  try {
    // 服务端缓存：同一 provider+股票+天数+日期只请求一次供应商 API，全局共享。
    // forceRefresh=true 时传 refresh 参数绕过服务端缓存。
    const params: any = { code: code.value, days: predDays.value }
    if (forceRefresh) params.refresh = true
    const res = await getKpred(params) as any
    if (seq !== predRequestSeq) return  // 已被更新的请求取代，丢弃
    const body = res?.code !== undefined ? res : res?.data
    if (body?.code === 0 && body.data) {
      predData.value = body.data as KpredResult
      predError.value = ''
    } else {
      const msg = body?.msg || 'K线预测请求失败'
      predError.value = msg
      ElMessage.warning(msg)
    }
  } catch (e: any) {
    if (seq !== predRequestSeq) return
    predError.value = 'K线预测服务异常，请稍后重试'
    ElMessage.error('K线预测服务异常')
  } finally {
    if (seq === predRequestSeq) {
      predLoading.value = false
      await nextTick()
      renderChart()
    }
  }
}

watch(predEnabled, (v) => {
  if (v && !predData.value) loadPrediction()
  else {
    if (!v) predError.value = ''
    renderChart()
  }
})
watch(predDays, () => {
  if (predEnabled.value) loadPrediction()
})
// 切换股票时清空预测数据
watch(code, () => {
  predData.value = null
  if (predEnabled.value) loadPrediction()
})
// 非日K时禁用预测展示（API 仅返回日K预测）
watch(currentPeriod, (p) => {
  if (p !== 'daily' && predEnabled.value) {
    predEnabled.value = false
  }
})

const { isMobile, breakpoint } = useResponsive()

// 当前是否展示技术副图（MACD/KDJ/...）
const hasSubInd = computed(() => ['MACD', 'KDJ', 'RSI', 'WR', '多空趋势'].includes(currentSubIndicator.value))

// 容器高度按断点 + 是否有副图 + 是否有 CI 副图自适应
//   xs: 280/380   sm: 380/480   md: 520/620   lg+: 680/780
//   CI 副图再 +100
const chartHeight = computed(() => {
  const bp = breakpoint.value
  const base: Record<string, number> = { xs: 280, sm: 380, md: 520, lg: 680, xl: 680, xxl: 680 }
  let H = base[bp] ?? 680
  if (hasSubInd.value) H += 100
  if (ciOverlay.extension.value?.subPanel) H += 100
  return H
})

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
  let n = visible[currentPeriod.value] || 80
  // PR-09: 移动端默认仅展示最近 30%，避免屏幕过窄时蜡烛挤成一团
  if (isMobile.value && currentPeriod.value !== 'yearly') {
    n = Math.min(n, 40)
  }
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
  // 移动端：压缩左右留白，把宽度让给 K 线
  const padLeft = isMobile.value ? 38 : 60
  const padRight = isMobile.value ? 8 : 24

  if (chartInstance) { chartInstance.dispose() }
  // K-line 主图采用完整重绘，避免多面板 + dataZoom 在部分环境下出现局部残影
  chartInstance = echarts.init(klineChartRef.value, undefined, {
    devicePixelRatio: Math.min(window.devicePixelRatio || 1, 2.5),
    useDirtyRect: false,
  })

  const dates: string[] = [...d.dates]
  const ohlc: number[][] = [...d.ohlc]
  const volumes: number[] = [...d.volumes]

  // === 预测K线数据追加 ===
  const predPredictions: KpredPrediction[] = (predEnabled.value && predData.value?.predictions) ? predData.value.predictions : []
  const predStartIdx = dates.length  // 预测数据起始索引
  for (const p of predPredictions) {
    dates.push(p.date)
    ohlc.push([p.open, p.close, p.low, p.high])
    volumes.push(p.volume || 0)
  }

  // 逐日 换手率/振幅/涨跌幅（K线接口扩展字段，缺列时为空数组，tooltip 内做兜底）
  const turnoverArr: (number | null)[] = d.turnover || []
  const amplitudeArr: (number | null)[] = d.amplitude || []
  const changeArr: (number | null)[] = d.change_pct || []
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
  // PR-09: 按 chartHeight 缩放，适配 xs(280)/sm(380)/md(520)/lg+(680)
  const H = chartHeight.value
  const baseH = ciOverlay.extension.value?.subPanel ? 780 : 680
  const S = H / baseH
  const sc = (n: number) => Math.max(1, Math.round(n * S))
  const scFs = (n: number) => Math.max(8, Math.round(n * Math.max(S, 0.75)))
  const stockLabel = (stockName.value ? `${code.value} ${stockName.value}` : code.value || '') + ` · ${currentPeriod.value}`
  const subLabelMap: Record<string, string> = {
    MACD: 'MACD (12,26,9)', KDJ: 'KDJ (9,3,3)', RSI: 'RSI (14)',
    WR: 'WR (10/6)', '多空趋势': '多空趋势 (BBI/MABB)',
  }
  const subLabel = subLabelMap[subInd] || subInd

  const grids: any[] = []
  const titleItems: any[] = []
  const dividers: number[] = []  // y-像素位置，稍后渲染为分割线
  const titleStyle = { fontSize: scFs(12), color: '#303133', fontWeight: 'bold' as const }
  const subTitleStyle = { fontSize: scFs(10), color: '#909399' }
  if (hasSub) {
    // 主图 60-320  分割线 340  成交量 380-450  分割线 470  副图 510-610  slider 644-662（baseH=680）
    grids.push(
      { left: padLeft, right: padRight, top: sc(60), height: sc(260) },
      { left: padLeft, right: padRight, top: sc(380), height: sc(70) },
      { left: padLeft, right: padRight, top: sc(510), height: sc(100) },
    )
    titleItems.push(
      { text: `K线主图 · ${stockLabel}`, subtext: showMA && showBollOnMain ? 'MA + BOLL' : showMA ? 'MA 均线' : showBollOnMain ? 'BOLL 布林带' : '蜡烛图', left: padLeft, top: sc(36), textStyle: titleStyle, subtextStyle: subTitleStyle },
      { text: '成交量', subtext: '红涨绿跌·按当日K线方向上色', left: padLeft, top: sc(358), textStyle: titleStyle, subtextStyle: subTitleStyle },
      { text: subLabel, subtext: '副图指标', left: padLeft, top: sc(488), textStyle: titleStyle, subtextStyle: subTitleStyle },
    )
    dividers.push(sc(340), sc(470))
  } else {
    // 主图 60-400  分割线 420  成交量 460-600  slider 644-662（baseH=680）
    grids.push(
      { left: padLeft, right: padRight, top: sc(60), height: sc(340) },
      { left: padLeft, right: padRight, top: sc(460), height: sc(140) },
    )
    titleItems.push(
      { text: `K线主图 · ${stockLabel}`, subtext: showMA && showBollOnMain ? 'MA + BOLL' : showMA ? 'MA 均线' : showBollOnMain ? 'BOLL 布林带' : '蜡烛图', left: padLeft, top: sc(36), textStyle: titleStyle, subtextStyle: subTitleStyle },
      { text: '成交量', subtext: '红涨绿跌·按当日K线方向上色', left: padLeft, top: sc(438), textStyle: titleStyle, subtextStyle: subTitleStyle },
    )
    dividers.push(sc(420))
  }

  // === X/Y axes ===
  // PR-09: 移动端轴字号略缩小，避免标签换行/拥挤
  const axisFs = isMobile.value ? 9 : 10
  const volAxisFs = isMobile.value ? 8 : 9
  const xAxes: any[] = [
    {
      type: 'category', data: dates, boundaryGap: false,
      axisLine: { onZero: false, lineStyle: { color: '#ccc' } },
      splitLine: { show: false },
      axisLabel: { fontSize: axisFs, color: '#666' },
      // 注意：category 轴的可视范围完全由 dataZoom 的 start/end 控制，绝不能再设
      // min:'dataMin'/max:'dataMax'——那会与 inside 缩放争夺轴 extent，缩放放大再
      // 缩小后 ordinal 刻度与 dataZoom 窗口失同步，导致 MA/BOLL 折线按全量 extent
      // 绘制、蜡烛按缩放 extent 绘制，出现均线在右侧扇形发散的残影。
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
      axisLabel: { fontSize: axisFs, color: '#666' },
    },
    {
      scale: true, gridIndex: 1, splitNumber: 2,
      axisLabel: { show: true, fontSize: volAxisFs, color: '#999', formatter: (v: number) => formatVolume(v) },
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
      axisLabel: { show: true, fontSize: volAxisFs, color: '#999' },
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
  // 主K线 data：有预测时，预测区间用 '-' 填充（让预测 series 独立渲染预测区，避免重叠）
  // 注意：ECharts 5 candlestick 的 getInitialData 对 null 会抛 "Cannot read properties of null (reading 'value')"，
  // 必须用 '-' 作为空数据标记。
  const mainOhlcData = predPredictions.length > 0
    ? [...ohlc.slice(0, predStartIdx), ...new Array(predPredictions.length).fill('-')]
    : ohlc
  const series: any[] = [
    {
      name: 'K线', type: 'candlestick', data: mainOhlcData,
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

  // === 预测K线 series（半透明虚线边框，视觉区分于实际K线） ===
  if (predPredictions.length > 0) {
    // 预测区域用 '-' 填充历史部分，只在预测日有值（null 会导致 ECharts 崩溃）
    const predOhlcData: (number[] | string)[] = new Array(predStartIdx).fill('-')
    for (const p of predPredictions) {
      predOhlcData.push([p.open, p.close, p.low, p.high])
    }
    series.push({
      name: '预测K线',
      type: 'candlestick',
      data: predOhlcData,
      itemStyle: {
        color: 'rgba(255, 140, 0, 0.5)',
        color0: 'rgba(0, 180, 120, 0.5)',
        borderColor: 'rgba(255, 140, 0, 0.8)',
        borderColor0: 'rgba(0, 180, 120, 0.8)',
        borderType: 'dashed',
      },
      z: 5,
    })
    legendData.push('预测K线')

    // 预测区间分界竖线 markLine（在主 K线 series 上标注）
    series[0].markLine = {
      silent: true,
      symbol: 'none',
      lineStyle: { type: 'dashed', color: '#e6a23c', width: 1.5 },
      label: { show: true, formatter: '← 预测', position: 'insideEndTop', color: '#e6a23c', fontSize: 10 },
      data: [{ xAxis: dates[predStartIdx] }],
    }
  }

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

  // === 筹码分布 (CYQ)：Tier A 成本带叠加 + Tier B 右侧横向峰图 ===
  // 成本带（markArea/markLine，价格轴 yAxis[0]）保证覆盖股均可显示；
  // 右侧峰图（custom series 叠加主图）需 distribution（含 turnover）方渲染。
  if (showChip.value && chipData.value?.has_chip && chipData.value.metrics) {
    const m = chipData.value.metrics
    const closePrice = chipData.value.close
    // Tier A：90%/70% 成本区间横带
    const markAreas: any[] = []
    if (m.cost_90_low != null && m.cost_90_high != null) {
      markAreas.push([
        { yAxis: m.cost_90_low, itemStyle: { color: 'rgba(64,158,255,0.09)' } },
        { yAxis: m.cost_90_high },
      ])
    }
    if (m.cost_70_low != null && m.cost_70_high != null) {
      markAreas.push([
        { yAxis: m.cost_70_low, itemStyle: { color: 'rgba(230,162,60,0.16)' } },
        { yAxis: m.cost_70_high },
      ])
    }
    if (markAreas.length) {
      series[0].markArea = { silent: true, data: markAreas }
    }
    // Tier A：平均成本水平线（合并进已有 markLine，避免覆盖预测分界线）
    if (m.avg_cost != null) {
      const avgLine = {
        yAxis: m.avg_cost, symbol: 'none',
        lineStyle: { color: '#8250df', type: 'dashed' as const, width: 1.2 },
        label: {
          show: true, formatter: `均价 ${m.avg_cost.toFixed(2)}`,
          position: 'insideStartTop' as const, color: '#8250df', fontSize: scFs(10),
        },
      }
      if (series[0].markLine) {
        series[0].markLine.data = [...(series[0].markLine.data || []), avgLine]
      } else {
        series[0].markLine = { silent: true, symbol: 'none', data: [avgLine] }
      }
    }

    // Tier B：右侧横向筹码峰图（custom series 叠加在主图 gridIndex 0，随价格轴缩放联动）
    const dist = chipData.value.distribution
    if (dist && dist.prices?.length) {
      const cyqPrices = dist.prices
      const cyqChips = dist.chips
      const maxChip = Math.max(...cyqChips, 1e-9)
      const barMaxFrac = isMobile.value ? 0.13 : 0.16  // 峰图最长柱占主图宽度比例
      series.push({
        name: '筹码分布',
        type: 'custom',
        xAxisIndex: 0,
        yAxisIndex: 0,
        silent: true,
        z: 2,
        // data 覆盖整条类目轴（y=null 不影响价格轴 extent），避免 dataZoom(filterMode:'filter')
        // 把仅有的数据点过滤掉导致 renderItem 不触发；仅在窗口内首个可见类目上一次性绘制所有价位柱
        data: dates.map((_: any, i: number) => [i, null]),
        renderItem: (params: any, api: any) => {
          if (params.dataIndexInside !== 0) return
          const cs = params.coordSys
          if (!cs) return
          const rightX = cs.x + cs.width
          const maxLen = cs.width * barMaxFrac
          const children: any[] = []
          for (let i = 0; i < cyqPrices.length; i++) {
            const chip = cyqChips[i]
            if (!(chip > 0)) continue
            const pt = api.coord([0, cyqPrices[i]])
            const y = pt[1]
            if (y < cs.y || y > cs.y + cs.height) continue  // 裁剪到可视价格区
            const len = (chip / maxChip) * maxLen
            const isProfit = closePrice != null && cyqPrices[i] <= closePrice
            children.push({
              type: 'rect',
              shape: { x: rightX - len, y: y - 0.7, width: len, height: 1.5 },
              style: { fill: isProfit ? 'rgba(236,0,0,0.42)' : 'rgba(0,153,220,0.40)' },
            })
          }
          return { type: 'group', children }
        },
      })
    }
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

  // === 策略选中标记：仅日K，标注该股票被当前策略历史选中的时间点 ===
  if (currentPeriod.value === 'daily' && strategyMarkDates.value.length) {
    const markSet = new Set(strategyMarkDates.value.map(s => s.slice(0, 10)))
    const markData: any[] = []
    for (let i = 0; i < dates.length; i++) {
      if (markSet.has(dates[i].slice(0, 10))) {
        const high = ohlc[i]?.[3]
        if (high != null) markData.push({ value: [dates[i], high], date: dates[i].slice(0, 10) })
      }
    }
    if (markData.length) {
      series.push({
        name: '策略选中',
        type: 'scatter',
        data: markData,
        symbol: 'pin',
        symbolSize: 22,
        symbolOffset: [0, '-55%'],
        itemStyle: { color: 'rgba(146,84,222,0.92)', borderColor: '#fff', borderWidth: 1 },
        label: { show: false },
        emphasis: { scale: 1.25 },
        tooltip: {
          trigger: 'item',
          formatter: (p: any) => `${strategyMarkName.value || '策略'}选中<br/>${p.data.date}`,
        },
        z: 6,
        zlevel: 1,
      })
      legendData.push('策略选中')
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
    const ciTopActual = sc(644)
    const ciDividerY = ciTopActual - sc(22)
    const ciIdx = grids.length
    grids.push({ left: padLeft, right: padRight, top: ciTopActual, height: sc(90) })
    titleItems.push({ text: '自定义指标', subtext: 'CI 叠加（快慢线 EMA / 策略买卖点）', left: padLeft, top: ciTopActual - sc(24), textStyle: titleStyle, subtextStyle: subTitleStyle })
    dividers.push(ciDividerY - sc(12))
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
    left: padLeft,
    right: padRight,
    top: y,
    silent: true,
    z: 1,
    shape: { x1: 0, y1: 0, x2: 9999, y2: 0 },
    style: { stroke: '#dcdfe6', lineWidth: 1, lineDash: [4, 4] },
  }))

  // === K线悬浮 tooltip：当日 开/高/低/收（含相对昨收涨跌幅 + 红绿着色）+ 成交/换手/振幅 ===
  // 同时保留东方财富式的多指标读数：把当前 hover 处的 MA/BOLL/副图(MACD/KDJ/...) 数值
  // 追加在盘口块下方，既增强了 K 线信息密度，又不丢失原有指标数值展示。
  const fmtTipVal = (v: any): string => (v == null || !isFinite(Number(v))) ? '--' : Number(v).toFixed(2)
  const klineTooltipFormatter = (params: any): string => {
    const arr = Array.isArray(params) ? params : [params]
    const idx = arr[0]?.dataIndex
    if (idx == null || idx < 0 || !ohlc[idx]) return ''
    const [open, close, low, high] = ohlc[idx]
    const prevClose = idx > 0 && ohlc[idx - 1] ? Number(ohlc[idx - 1][1]) : null

    // === 预测K线区域：展示 Pro 多因子评分 ===
    if (predPredictions.length > 0 && idx >= predStartIdx) {
      const pro = predData.value?.pro
      const predIdx = idx - predStartIdx
      const predItem = predPredictions[predIdx]
      let proHtml = ''
      if (pro) {
        const compositeScore = toPredNumber(pro.composite_score)
        const ratingCls = compositeScore >= 0 ? 'kt-up' : 'kt-down'
        const factorsHtml = (pro.factors || []).slice(0, 6).map(f => {
          const factorScore = toPredNumber(f.score)
          const contribution = toPredNumber(f.contribution)
          const sCls = contribution >= 0 ? 'kt-up' : 'kt-down'
          return `<div class="kt-row"><span class="kt-label">${f.label}</span><span class="kt-val ${sCls}">${factorScore >= 0 ? '+' : ''}${(factorScore * 100).toFixed(0)}分</span><span class="kt-sub">${contribution >= 0 ? '+' : ''}${(contribution * 100).toFixed(1)}%</span></div>`
        }).join('')
        proHtml = `
          <div class="kt-sep"></div>
          <div class="kt-pred-header">Pro 多因子评分</div>
          <div class="kt-row"><span class="kt-label">综合评分</span><span class="kt-val ${ratingCls}">${compositeScore.toFixed(3)}</span></div>
          <div class="kt-row"><span class="kt-label">评级</span><span class="kt-val ${ratingCls}">${pro.rating}</span></div>
          <div class="kt-row"><span class="kt-label">置信度</span><span class="kt-val">${pro.confidence}</span></div>
          <div class="kt-row"><span class="kt-label">因子一致性</span><span class="kt-val">${pro.conflict_level}</span></div>
          <div class="kt-row"><span class="kt-label">预期收益</span><span class="kt-val ${toPredNumber(pro.adj_return_pct) >= 0 ? 'kt-up' : 'kt-down'}">${fmtPredSigned(pro.adj_return_pct, 2)}%</span></div>
          <div class="kt-row"><span class="kt-label">日波动率</span><span class="kt-val">${fmtPredNumber(pro.sigma_daily_pct, 2)}%</span></div>
          ${factorsHtml ? `<div class="kt-sep"></div><div class="kt-pred-header">因子明细</div>${factorsHtml}` : ''}`
      }
      return `
        <div class="kline-tip kline-tip-pred">
          <div class="kt-date">${predItem?.date || dates[idx] || ''} <span class="kt-pred-badge">预测</span></div>
          <div class="kt-row"><span class="kt-label">开盘</span><span class="kt-val">${open?.toFixed(2)}</span></div>
          <div class="kt-row"><span class="kt-label">最高</span><span class="kt-val">${high?.toFixed(2)}</span></div>
          <div class="kt-row"><span class="kt-label">最低</span><span class="kt-val">${low?.toFixed(2)}</span></div>
          <div class="kt-row"><span class="kt-label">收盘</span><span class="kt-val">${close?.toFixed(2)}</span></div>
          ${proHtml}
        </div>`
    }

    const pct = (v: number): string => {
      if (prevClose == null || !(prevClose > 0)) return ''
      const p = ((v - prevClose) / prevClose) * 100
      return `<span class="${p >= 0 ? 'kt-up' : 'kt-down'}">${p >= 0 ? '+' : ''}${p.toFixed(2)}%</span>`
    }
    const cls = (v: number): string => prevClose == null ? '' : (v >= prevClose ? 'kt-up' : 'kt-down')
    const closePct = changeArr[idx]
    const closePctStr = closePct != null
      ? `<span class="${closePct >= 0 ? 'kt-up' : 'kt-down'}">${closePct >= 0 ? '+' : ''}${Number(closePct).toFixed(2)}%</span>`
      : pct(close)
    const amp = amplitudeArr[idx]
    const ampStr = amp != null
      ? `${Number(amp).toFixed(2)}%`
      : (prevClose && prevClose > 0 ? `${(((high - low) / prevClose) * 100).toFixed(2)}%` : '--')
    const turn = turnoverArr[idx]
    const turnStr = turn != null ? `${Number(turn).toFixed(2)}%` : '--'
    // 指标线数值（过滤掉 K线本体、成交量、成交量均线、策略选中标记）
    const indRows = arr
      .filter((p: any) => p.seriesType === 'line'
        && !String(p.seriesName).startsWith('VOL')
        && isFinite(Number(Array.isArray(p.value) ? p.value[1] : p.value)))
      .map((p: any) => {
        const val = Array.isArray(p.value) ? p.value[1] : p.value
        return `<div class="kt-row"><span class="kt-label">${p.marker}${p.seriesName}</span><span class="kt-val">${fmtTipVal(val)}</span></div>`
      }).join('')
    return `
      <div class="kline-tip">
        <div class="kt-date">${dates[idx] || ''}</div>
        <div class="kt-row"><span class="kt-label">开盘</span><span class="kt-val ${cls(open)}">${open?.toFixed(2)}</span>${pct(open)}</div>
        <div class="kt-row"><span class="kt-label">最高</span><span class="kt-val ${cls(high)}">${high?.toFixed(2)}</span>${pct(high)}</div>
        <div class="kt-row"><span class="kt-label">最低</span><span class="kt-val ${cls(low)}">${low?.toFixed(2)}</span>${pct(low)}</div>
        <div class="kt-row"><span class="kt-label">收盘</span><span class="kt-val ${cls(close)}">${close?.toFixed(2)}</span>${closePctStr}</div>
        <div class="kt-row"><span class="kt-label">成交</span><span class="kt-val">${fmtVolHands(volumes[idx])}</span></div>
        <div class="kt-row"><span class="kt-label">换手</span><span class="kt-val">${turnStr}</span></div>
        <div class="kt-row"><span class="kt-label">振幅</span><span class="kt-val">${ampStr}</span></div>
        ${indRows ? `<div class="kt-sep"></div>${indRows}` : ''}
      </div>`
  }

  const option: echarts.EChartsOption = {
    animation: false,
    title: titleItems,
    graphic: graphicElements,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: 'rgba(255,255,255,0.97)',
      borderColor: '#e4e7ed',
      borderWidth: 1,
      padding: 0,
      textStyle: { fontSize: 12, color: '#333' },
      extraCssText: 'box-shadow:0 4px 16px rgba(0,0,0,0.12);border-radius:8px;',
      formatter: klineTooltipFormatter,
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
      {
        type: 'inside', xAxisIndex: zoomXIndices, start: zoomStart, end: 100, throttle: 80,
        zoomOnMouseWheel: true, moveOnMouseMove: true, moveOnMouseWheel: false,
        preventDefaultMouseMove: true,
      },
      {
        show: true, xAxisIndex: zoomXIndices, type: 'slider',
        bottom: 6, height: 18, start: zoomStart, end: 100,
        borderColor: '#ddd', fillerColor: 'rgba(64,158,255,0.15)',
        handleStyle: { color: '#409eff' },
        realtime: false,
      },
    ],
    series,
  }

  chartInstance.clear()
  chartInstance.setOption(option, { notMerge: true, lazyUpdate: false })
  chartShallow.value = chartInstance
}

// Switch period
const switchPeriod = (p: string) => {
  currentPeriod.value = p
  loadKlineData()
}

// Re-render chart (no data reload) when overlay or sub-indicator changes
watch([currentSubIndicator, mainOverlays], () => { renderChart() }, { deep: true })

// 筹码开关：首次开启时按需拉取，拉取完成后重渲
watch(showChip, async (on) => {
  if (on && !chipData.value && !chipLoading.value) {
    await loadChipData()
    renderChart()
  }
})

// PR-5: 自定义指标叠加变化时重渲
watch(() => ciOverlay.extension.value, async () => { await nextTick(); renderChart() }, { deep: true })

// 策略选中标记到达后重渲（仅日K生效）
watch(strategyMarkDates, () => {
  if (klineData.value && currentPeriod.value === 'daily') renderChart()
})

// Navigate to backtest
// 优先跳转「回测历史」并按本股票过滤；若无历史则跳转「单股回测」携带代码回填
const goBacktest = async () => {
  if (!code.value) return
  let hasHistory = false
  try {
    const res: any = await getBacktestHistory({ code: code.value, page: 1, page_size: 1 })
    hasHistory = (res?.total || 0) > 0
  } catch {
    hasHistory = false
  }
  if (hasHistory) {
    router.push({
      path: '/backtest/history',
      query: { code: code.value, name: stockName.value }
    })
  } else {
    router.push({
      path: '/backtest/single',
      query: { code: code.value, name: stockName.value }
    })
  }
}

// Navigate to AI analysis
const goAIAnalysis = () => {
  router.push({
    path: '/ai-report/analysis',
    query: { code: code.value, name: stockName.value }
  })
}

// 加载关注列表（判断当前股票是否已关注）
const loadAttentionList = async () => {
  try {
    const res = await getAttentionList() as any
    const items = res?.items || []
    attentionCodes.value = items.map((i: { code: string }) => i.code)
  } catch {
    attentionCodes.value = []
  }
}

// 关注 / 取消关注当前个股
const toggleAttention = async () => {
  if (!code.value) {
    ElMessage.warning('无效的股票代码')
    return
  }
  const willWatch = !isWatched.value
  watchLoading.value = true
  try {
    await setAttention(code.value, willWatch)
    await loadAttentionList()
    ElMessage.success(willWatch ? '已加入关注' : '已取消关注')
  } catch {
    ElMessage.error('操作失败，请稍后重试')
  } finally {
    watchLoading.value = false
  }
}

// Load financial data
const loadFinancialData = async () => {
  if (!code.value) return
  financialLoading.value = true
  try {
    const res = await getFinancialSummary(code.value, 12) as any
    if (res && !res.error) {
      financialData.value = res
      await nextTick()
      renderFinancialChart()
      renderExpenseChart()
    }
  } catch {
    financialData.value = null
  } finally {
    financialLoading.value = false
  }
}

// Render financial trend chart
const renderFinancialChart = () => {
  if (!financialChartRef.value || !financialData.value?.history?.length) return
  const hist = financialData.value.history

  if (financialChartInstance) financialChartInstance.dispose()
  financialChartInstance = echarts.init(financialChartRef.value, undefined, {
    devicePixelRatio: Math.min(window.devicePixelRatio || 1, 2.5),
  })

  const dates = hist.map(h => h.report_name || h.report_date)
  const revenue = hist.map(h => h.revenue != null ? +(h.revenue / 1e8).toFixed(2) : null)
  const netProfit = hist.map(h => h.net_profit != null ? +(h.net_profit / 1e8).toFixed(2) : null)
  const eps = hist.map(h => h.eps)
  const grossMargin = hist.map(h => h.gross_margin)
  const netMarginPct = hist.map(h => h.net_profit_margin)

  const option: echarts.EChartsOption = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
    },
    legend: {
      data: ['营业总收入(亿)', '净利润(亿)', '每股收益', '毛利率(%)', '销售净利率(%)'],
      top: 0,
      textStyle: { fontSize: 11 },
    },
    grid: { left: 50, right: 50, top: 40, bottom: 30 },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { fontSize: 10, rotate: 30 },
    },
    yAxis: [
      {
        type: 'value',
        name: '金额(亿)',
        position: 'left',
        axisLabel: { fontSize: 10 },
      },
      {
        type: 'value',
        name: '% / 元',
        position: 'right',
        axisLabel: { fontSize: 10 },
      },
    ],
    series: [
      {
        name: '营业总收入(亿)',
        type: 'bar',
        data: revenue,
        barMaxWidth: 24,
        itemStyle: { color: '#409eff' },
      },
      {
        name: '净利润(亿)',
        type: 'bar',
        data: netProfit,
        barMaxWidth: 24,
        itemStyle: { color: (params: any) => (params.data ?? 0) >= 0 ? '#67c23a' : '#f56c6c' },
      },
      {
        name: '每股收益',
        type: 'line',
        data: eps,
        yAxisIndex: 1,
        symbol: 'circle',
        symbolSize: 5,
        lineStyle: { width: 2, color: '#e6a23c' },
        itemStyle: { color: '#e6a23c' },
      },
      {
        name: '毛利率(%)',
        type: 'line',
        data: grossMargin,
        yAxisIndex: 1,
        symbol: 'diamond',
        symbolSize: 5,
        lineStyle: { width: 2, color: '#9b59b6' },
        itemStyle: { color: '#9b59b6' },
      },
      {
        name: '销售净利率(%)',
        type: 'line',
        data: netMarginPct,
        yAxisIndex: 1,
        symbol: 'triangle',
        symbolSize: 5,
        lineStyle: { width: 2, color: '#f56c6c', type: 'dashed' },
        itemStyle: { color: '#f56c6c' },
      },
    ],
  }
  financialChartInstance.setOption(option)
}

// Render expense structure trend chart
const renderExpenseChart = () => {
  if (!expenseChartRef.value || !financialData.value?.history?.length) return
  const hist = financialData.value.history
  // Only render if we have expense data
  if (!hist.some(h => h.rd_expense != null || h.admin_expense != null)) return

  if (expenseChartInstance) expenseChartInstance.dispose()
  expenseChartInstance = echarts.init(expenseChartRef.value, undefined, {
    devicePixelRatio: Math.min(window.devicePixelRatio || 1, 2.5),
  })

  const dates = hist.map(h => h.report_name || h.report_date)
  // 计算各项费用占营收百分比
  const rdRatio = hist.map(h => {
    if (h.rd_expense == null || !h.revenue) return null
    return +((h.rd_expense / h.revenue) * 100).toFixed(2)
  })
  const adminRatio = hist.map(h => {
    if (h.admin_expense == null || !h.revenue) return null
    return +((h.admin_expense / h.revenue) * 100).toFixed(2)
  })
  const sellRatio = hist.map(h => {
    if (h.selling_expense == null || !h.revenue) return null
    return +((h.selling_expense / h.revenue) * 100).toFixed(2)
  })
  // 绝对值（亿元）
  const rdAbs = hist.map(h => h.rd_expense != null ? +(h.rd_expense / 1e8).toFixed(4) : null)
  const adminAbs = hist.map(h => h.admin_expense != null ? +(h.admin_expense / 1e8).toFixed(4) : null)
  const sellAbs = hist.map(h => h.selling_expense != null ? +(h.selling_expense / 1e8).toFixed(4) : null)
  const finAbs = hist.map(h => h.financial_expense != null ? +(h.financial_expense / 1e8).toFixed(4) : null)

  const option: echarts.EChartsOption = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
    },
    legend: {
      data: ['研发费用(亿)', '管理费用(亿)', '销售费用(亿)', '财务费用(亿)', '研发占比(%)', '管理占比(%)', '销售占比(%)'],
      top: 0,
      textStyle: { fontSize: 10 },
    },
    grid: { left: 50, right: 50, top: 50, bottom: 30 },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { fontSize: 10, rotate: 30 },
    },
    yAxis: [
      { type: 'value', name: '金额(亿)', position: 'left', axisLabel: { fontSize: 10 } },
      { type: 'value', name: '占比(%)', position: 'right', axisLabel: { fontSize: 10 } },
    ],
    series: [
      { name: '研发费用(亿)', type: 'bar', stack: 'expense', data: rdAbs, barMaxWidth: 20, itemStyle: { color: '#409eff' } },
      { name: '管理费用(亿)', type: 'bar', stack: 'expense', data: adminAbs, barMaxWidth: 20, itemStyle: { color: '#67c23a' } },
      { name: '销售费用(亿)', type: 'bar', stack: 'expense', data: sellAbs, barMaxWidth: 20, itemStyle: { color: '#e6a23c' } },
      { name: '财务费用(亿)', type: 'bar', stack: 'expense', data: finAbs, barMaxWidth: 20, itemStyle: { color: '#909399' } },
      { name: '研发占比(%)', type: 'line', yAxisIndex: 1, data: rdRatio, symbol: 'circle', symbolSize: 5, lineStyle: { width: 2, color: '#409eff' }, itemStyle: { color: '#409eff' } },
      { name: '管理占比(%)', type: 'line', yAxisIndex: 1, data: adminRatio, symbol: 'diamond', symbolSize: 5, lineStyle: { width: 2, color: '#67c23a', type: 'dashed' }, itemStyle: { color: '#67c23a' } },
      { name: '销售占比(%)', type: 'line', yAxisIndex: 1, data: sellRatio, symbol: 'triangle', symbolSize: 5, lineStyle: { width: 2, color: '#e6a23c', type: 'dashed' }, itemStyle: { color: '#e6a23c' } },
    ],
  }
  expenseChartInstance.setOption(option)
}

// Load latest AI report for this stock
const loadLatestReport = async () => {
  if (!code.value) return
  reportLoading.value = true
  try {
    const res = await getReportHistory({ code: code.value, limit: 1, days: 0 }) as any
    if (res?.items?.length) {
      latestReport.value = res.items[0]
    } else {
      latestReport.value = null
    }
  } catch {
    latestReport.value = null
  } finally {
    reportLoading.value = false
  }
}

// Format number for display
const fmtNum = (val: number | undefined | null, decimals = 2): string => {
  if (val == null || !isFinite(val)) return '-'
  if (Math.abs(val) >= 1e8) return (val / 1e8).toFixed(decimals) + '亿'
  if (Math.abs(val) >= 1e4) return (val / 1e4).toFixed(decimals) + '万'
  return val.toFixed(decimals)
}

// Format 万元 to 亿 (market_cap stored in 万元)
const fmtWanToYi = (val: number | undefined | null): string => {
  if (val == null || !isFinite(val)) return '-'
  if (Math.abs(val) >= 1e4) return (val / 1e4).toFixed(2) + '亿'
  return val.toFixed(2) + '万'
}

const fmtPct = (val: number | undefined | null): string => {
  if (val == null || !isFinite(val)) return '-'
  return val.toFixed(2) + '%'
}

// === 行情快照专用格式化（与个股分析页口径一致）===
// 注意：本页已有 fmtNum（带亿/万后缀，用于财务大数），故价格类单独用 fmtPrice 避免误加后缀。
/** 价格：固定保留 2 位小数 */
const fmtPrice = (v: number | null | undefined, digits = 2): string => {
  if (v == null || !isFinite(Number(v))) return '--'
  return Number(v).toFixed(digits)
}
/** 带正负号的百分比 */
const fmtSignedPct = (v: number | null | undefined): string => {
  if (v == null || !isFinite(Number(v))) return '--'
  const n = Number(v)
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
}
/** 成交量：后端单位为股，展示为手（1手=100股），自动选用万手 */
const fmtVolHands = (v: number | null | undefined): string => {
  if (v == null || !isFinite(Number(v))) return '--'
  const hands = Number(v) / 100
  if (hands >= 1e4) return `${(hands / 1e4).toFixed(2)}万手`
  return `${Math.round(hands).toLocaleString()}手`
}
/** 成交额：后端单位为元，自动选用亿/万 */
const fmtAmt = (v: number | null | undefined): string => {
  if (v == null || !isFinite(Number(v))) return '--'
  const n = Number(v)
  if (n >= 1e8) return `${(n / 1e8).toFixed(2)}亿`
  if (n >= 1e4) return `${(n / 1e4).toFixed(2)}万`
  return n.toLocaleString()
}
/** 股本：后端单位为股，自动选用亿/万股 */
const fmtShares = (v: number | null | undefined): string => {
  if (v == null || !isFinite(Number(v))) return '--'
  const n = Number(v)
  if (n >= 1e8) return `${(n / 1e8).toFixed(2)}亿`
  if (n >= 1e4) return `${(n / 1e4).toFixed(2)}万`
  return Math.round(n).toLocaleString()
}
/** 涨跌方向：1 涨 / -1 跌 / 0 平（用于整条快照栏的红绿基调） */
const quoteDir = computed(() => {
  const p = quoteData.value?.change_pct
  if (p == null) return 0
  if (p > 0) return 1
  if (p < 0) return -1
  return 0
})
/** 价格相对昨收的涨跌着色类（用于今开/最高/最低） */
const priceCls = (v: number | null | undefined): string => {
  const pc = quoteData.value?.pre_close
  if (v == null || pc == null) return ''
  if (Number(v) > Number(pc)) return 'qv-up'
  if (Number(v) < Number(pc)) return 'qv-down'
  return ''
}

// 加载行情快照（与 K 线/财务并行；带防抖式 stale 守卫，避免切股票时旧响应覆盖）
const loadStockQuote = async () => {
  if (!code.value) { quoteData.value = null; return }
  const reqCode = code.value
  quoteLoading.value = true
  try {
    const res = await getStockQuote(reqCode) as unknown as StockQuote
    if (code.value !== reqCode) return  // 用户已切换股票，丢弃旧响应
    quoteData.value = (res && !(res as { error?: string }).error) ? res : null
  } catch (e) {
    console.warn('[indicator] 行情快照加载失败:', e)
    quoteData.value = null
  } finally {
    quoteLoading.value = false
  }
}

const handleResize = () => {
  if (resizeDebounceTimer !== null) window.clearTimeout(resizeDebounceTimer)
  resizeDebounceTimer = window.setTimeout(() => {
    resizeDebounceTimer = null
    chartInstance?.resize()
    financialChartInstance?.resize()
    expenseChartInstance?.resize()
  }, 120)
}

// keep-alive 缓存期间标记，避免无意义的 breakpoint 重渲
let isActive = true

let lastLoadedCode = ''
watch(() => route.query.code, (newCode, oldCode) => {
  if (newCode && newCode !== oldCode) {
    currentPeriod.value = 'daily'
    lastLoadedCode = newCode as string
    chipData.value = null
    if (showChip.value) loadChipData().then(() => renderChart())
    loadKlineData()
    loadStockQuote()
    loadFinancialData()
    loadLatestReport()
    loadStrategyMarks()
  }
})

// 策略标识变化（同股票切换不同策略）时重新拉取选中标记
watch(() => route.query.strategy, () => { loadStrategyMarks() })

// 断点变化时（桌面 <-> 移动）重新渲染：grid 左右内边距会切换
watch(breakpoint, () => {
  if (isActive && klineData.value) {
    nextTick(() => renderChart())
  }
})

// layout/index.vue 使用 <keep-alive> 缓存 router-view，所以本组件会被复用：
// - onMounted: 仅在首次挂载时执行一次（绑 resize、首次加载）
// - onActivated: 每次切回都触发（resize + 若 code 已变则重新加载）
// - onDeactivated: 切走时 clear() 让出 GPU；切回时 resize 会重渲
// - onUnmounted: keep-alive 真正卸载时移除 resize 并 dispose
onMounted(() => {
  lastLoadedCode = code.value || ''
  loadKlineData()
  loadStockQuote()
  loadFinancialData()
  loadLatestReport()
  loadStrategyMarks()
  loadAttentionList()
  window.addEventListener('resize', handleResize)
  ;(window as any).visualViewport?.addEventListener?.('resize', handleResize)
})

onActivated(() => {
  isActive = true
  if (code.value && code.value !== lastLoadedCode) {
    lastLoadedCode = code.value
    currentPeriod.value = 'daily'
    loadKlineData()
    loadStockQuote()
    loadFinancialData()
    loadLatestReport()
    loadStrategyMarks()
    loadAttentionList()
  } else {
    // Same stock: re-render charts that were clear()ed during deactivation
    nextTick(() => {
      if (klineData.value) renderChart()
      if (financialData.value?.history?.length) {
        renderFinancialChart()
        renderExpenseChart()
      }
    })
  }
})

onDeactivated(() => {
  isActive = false
  chartInstance?.clear()
  financialChartInstance?.clear()
  expenseChartInstance?.clear()
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  ;(window as any).visualViewport?.removeEventListener?.('resize', handleResize)
  if (resizeDebounceTimer !== null) window.clearTimeout(resizeDebounceTimer)
  chartInstance?.dispose()
  chartInstance = null
  financialChartInstance?.dispose()
  financialChartInstance = null
  expenseChartInstance?.dispose()
  expenseChartInstance = null
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
        <el-button
          :type="isWatched ? 'warning' : 'default'"
          size="small"
          :loading="watchLoading"
          @click="toggleAttention"
        >
          <el-icon><StarFilled v-if="isWatched" /><Star v-else /></el-icon>
          &nbsp;{{ isWatched ? '已关注' : '关注' }}
        </el-button>
        <el-button type="warning" size="small" @click="goAIAnalysis">
          <el-icon><ChatDotRound /></el-icon>&nbsp;AI 分析
        </el-button>
        <el-button type="primary" size="small" @click="goBacktest">查看回测</el-button>
      </div>
    </div>

    <!-- 行情快照（实时盘口）：紧贴信息栏，东方财富详情页风格 -->
    <!-- 左侧大字现价 + 涨跌；右侧密排盘口指标网格（可折叠）。整体红绿基调随涨跌方向。 -->
    <div v-if="quoteData" class="quote-bar" :class="`qdir-${quoteDir}`" v-loading="quoteLoading">
      <div class="quote-main">
        <span class="quote-price">{{ fmtPrice(quoteData.price) }}</span>
        <div class="quote-chg">
          <span class="chg-amt">{{ quoteData.change_amount != null && quoteData.change_amount >= 0 ? '+' : '' }}{{ fmtPrice(quoteData.change_amount) }}</span>
          <span class="chg-pct">{{ fmtSignedPct(quoteData.change_pct) }}</span>
        </div>
        <div class="quote-limit">
          <span class="lim-up">涨停&nbsp;{{ fmtPrice(quoteData.limit_up) }}</span>
          <span class="lim-down">跌停&nbsp;{{ fmtPrice(quoteData.limit_down) }}</span>
        </div>
        <span class="quote-toggle" @click="quoteCollapsed = !quoteCollapsed">
          {{ quoteCollapsed ? '展开盘口' : '收起盘口' }}
          <el-icon :class="{ collapsed: quoteCollapsed }"><ArrowDown /></el-icon>
        </span>
      </div>
      <div v-show="!quoteCollapsed" class="quote-metrics">
        <div class="qm"><span class="qm-l">今开</span><span class="qm-v" :class="priceCls(quoteData.open)">{{ fmtPrice(quoteData.open) }}</span></div>
        <div class="qm"><span class="qm-l">最高</span><span class="qm-v" :class="priceCls(quoteData.high)">{{ fmtPrice(quoteData.high) }}</span></div>
        <div class="qm"><span class="qm-l">最低</span><span class="qm-v" :class="priceCls(quoteData.low)">{{ fmtPrice(quoteData.low) }}</span></div>
        <div class="qm"><span class="qm-l">昨收</span><span class="qm-v">{{ fmtPrice(quoteData.pre_close) }}</span></div>
        <div class="qm"><span class="qm-l">成交量</span><span class="qm-v">{{ fmtVolHands(quoteData.volume) }}</span></div>
        <div class="qm"><span class="qm-l">成交额</span><span class="qm-v">{{ fmtAmt(quoteData.amount) }}</span></div>
        <div class="qm"><span class="qm-l">振幅</span><span class="qm-v">{{ fmtPrice(quoteData.amplitude) }}%</span></div>
        <div class="qm"><span class="qm-l">换手率</span><span class="qm-v">{{ fmtPrice(quoteData.turnover_rate) }}%</span></div>
        <div class="qm"><span class="qm-l">总市值</span><span class="qm-v">{{ fmtWanToYi(quoteData.total_market_cap) }}</span></div>
        <div class="qm"><span class="qm-l">流通值</span><span class="qm-v">{{ fmtWanToYi(quoteData.free_market_cap) }}</span></div>
        <div class="qm"><span class="qm-l">市净率</span><span class="qm-v">{{ fmtPrice(quoteData.pb) }}</span></div>
        <div class="qm"><span class="qm-l">市盈率(动)</span><span class="qm-v">{{ fmtPrice(quoteData.pe) }}</span></div>
        <div class="qm"><span class="qm-l">总股本</span><span class="qm-v">{{ fmtShares(quoteData.total_shares) }}</span></div>
        <div class="qm"><span class="qm-l">流通股</span><span class="qm-v">{{ fmtShares(quoteData.free_shares) }}</span></div>
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
        <div v-if="currentPeriod === 'daily'" class="pred-controls">
          <el-switch v-model="predEnabled" size="small" active-text="预测" inactive-text="" :loading="predLoading" />
          <el-select
            v-if="predEnabled"
            v-model="predDays"
            size="small"
            style="width: 80px; margin-left: 6px;"
          >
            <el-option v-for="d in predDaysOptions" :key="d" :label="`${d}天`" :value="d" />
          </el-select>
          <el-button
            v-if="predEnabled"
            size="small"
            type="warning"
            :loading="predLoading"
            style="margin-left: 6px;"
            @click="loadPrediction(true)"
          >刷新</el-button>
        </div>
      </div>
      <div v-if="currentPeriod === 'daily' && strategyMarkDates.length" class="strategy-mark-hint">
        <span class="dot"></span>
        <span class="txt">{{ strategyMarkName || '策略' }} 历史选中 <b>{{ strategyMarkDates.length }}</b> 次（图钉标注）</span>
      </div>
      <!-- 预测失败持久提示（历史K线仍正常显示） -->
      <el-alert
        v-if="predEnabled && predError && !predLoading"
        :title="predError"
        type="warning"
        show-icon
        :closable="false"
        style="margin-bottom: 4px;"
      />
    </div>

    <section v-if="predEnabled && predPro && !predLoading" class="pred-score-panel">
      <div class="pred-score-summary">
        <div class="pred-score-heading">
          <span class="pred-score-title">Pro 多因子评分</span>
          <span class="pred-provider">{{ predProviderLabel }}</span>
        </div>
        <div class="pred-summary-item">
          <span>综合评分</span>
          <b :class="predValueClass(predPro.composite_score)">{{ fmtPredSigned(predPro.composite_score) }}</b>
        </div>
        <div class="pred-summary-item">
          <span>评级</span>
          <b :class="predValueClass(predPro.composite_score)">{{ predPro.rating }}</b>
        </div>
        <div class="pred-summary-item">
          <span>置信度</span>
          <b>{{ predPro.confidence }}</b>
        </div>
        <div class="pred-summary-item">
          <span>因子一致性</span>
          <b>{{ predPro.conflict_level }}</b>
        </div>
        <div class="pred-summary-item">
          <span>预期收益</span>
          <b :class="predValueClass(predPro.adj_return_pct)">{{ fmtPredSigned(predPro.adj_return_pct, 2) }}%</b>
        </div>
        <div class="pred-summary-item">
          <span>日波动率</span>
          <b>{{ fmtPredNumber(predPro.sigma_daily_pct, 2) }}%</b>
        </div>
      </div>
      <div v-if="predFactors.length" class="pred-factor-grid">
        <div v-for="factor in predFactors" :key="factor.key || factor.label" class="pred-factor-item">
          <span class="pred-factor-name">{{ factor.label }}</span>
          <span class="pred-factor-score" :class="predValueClass(factor.score)">{{ fmtPredSigned(factor.score) }}</span>
          <span class="pred-factor-meta">权重 {{ fmtPredNumber(toPredNumber(factor.weight) * 100, 0) }}%</span>
          <span class="pred-factor-contribution" :class="predValueClass(factor.contribution)">
            贡献 {{ fmtPredSigned(factor.contribution) }}
          </span>
        </div>
      </div>
    </section>

    <!-- Chart area -->
    <div class="chart-wrapper" v-loading="loading">
      <div ref="klineWrapRef" class="chart-wrap kline-chart-wrap">
        <div ref="klineChartRef" class="chart-main" :style="{ height: chartHeight + 'px' }"></div>
        <ChartFullscreenBtn :is-fullscreen="klineChartFs.isFullscreen.value" @toggle="klineChartFs.toggle" />
      </div>
      <!-- 筹码分布读数条（Tier A）：仅在勾选"筹码"叠加项时展示 -->
      <div v-if="showChip" class="chip-strip" v-loading="chipLoading">
        <template v-if="chipData?.has_chip && chipData.metrics">
          <div class="chip-items">
            <div class="chip-item">
              <span class="chip-label">获利比例</span>
              <span class="chip-val" :class="winnerRateCls">{{ fmtChipPct(chipData.metrics.winner_rate) }}</span>
            </div>
            <div class="chip-item">
              <span class="chip-label">平均成本</span>
              <span class="chip-val">{{ fmtChipNum(chipData.metrics.avg_cost) }}</span>
            </div>
            <div class="chip-item">
              <span class="chip-label">90%成本区间</span>
              <span class="chip-val">{{ fmtChipRange(chipData.metrics.cost_90_low, chipData.metrics.cost_90_high) }}</span>
            </div>
            <div class="chip-item">
              <span class="chip-label">90%集中度</span>
              <span class="chip-val">{{ fmtChipConc(chipData.metrics.concentration_90) }}</span>
            </div>
            <div class="chip-item">
              <span class="chip-label">70%成本区间</span>
              <span class="chip-val">{{ fmtChipRange(chipData.metrics.cost_70_low, chipData.metrics.cost_70_high) }}</span>
            </div>
            <div class="chip-item">
              <span class="chip-label">70%集中度</span>
              <span class="chip-val">{{ fmtChipConc(chipData.metrics.concentration_70) }}</span>
            </div>
          </div>
          <div class="chip-meta">
            <span v-if="chipSourceLabel" :class="['chip-src', 'src-' + chipData.metrics_source]">{{ chipSourceLabel }}</span>
            <span v-if="chipData.metrics_as_of" class="chip-asof">数据日 {{ chipData.metrics_as_of }}</span>
            <span v-if="chipData.message" class="chip-msg">{{ chipData.message }}</span>
          </div>
        </template>
        <div v-else class="chip-empty">
          {{ chipData?.message || (chipLoading ? '筹码数据加载中…' : '该股暂无筹码数据') }}
        </div>
      </div>
      <!-- Sub indicator picker: 桌面用东方财富风格 tab bar；移动端用 el-segmented 节省高度 -->
      <el-segmented
        v-if="isMobile"
        v-model="currentSubIndicator"
        :options="subIndicatorOptions.map(v => ({ label: v, value: v }))"
        size="small"
        class="sub-indicator-segmented"
      />
      <div v-else class="sub-indicator-bar">
        <span
          v-for="ind in subIndicatorOptions" :key="ind"
          :class="['sub-tab', { active: currentSubIndicator === ind }]"
          @click="currentSubIndicator = ind"
        >{{ ind }}</span>
      </div>
    </div>

    <!-- 财务分析 -->
    <div class="section-card" v-loading="financialLoading">
      <div class="section-title">
        财务分析
        <span v-if="financialData?.latest?.report_name || financialData?.latest?.report_date" class="report-period-badge">
          报告期：{{ financialData.latest.report_name || financialData.latest.report_date }}
        </span>
      </div>
      <div v-if="financialData?.latest" class="financial-content">
        <!-- 估值与核心指标网格 -->
        <div class="financial-grid">
          <!-- 核心财务指标（来自 cn_stock_financial 最新一期） -->
          <template v-if="financialData?.latest">
            <div class="fin-item">
              <span class="fin-label">每股收益 (EPS)</span>
              <span class="fin-value">{{ fmtNum(financialData.latest.eps, 4) }}</span>
            </div>
            <div class="fin-item">
              <span class="fin-label">每股净资产 (BPS)</span>
              <span class="fin-value">{{ fmtNum(financialData.latest.bps) }}</span>
            </div>
            <div class="fin-item">
              <span class="fin-label">净资产收益率 (ROE)</span>
              <span class="fin-value">{{ fmtPct(financialData.latest.roe) }}</span>
            </div>
            <div class="fin-item">
              <span class="fin-label">营业收入</span>
              <span class="fin-value">{{ fmtNum(financialData.latest.revenue) }}</span>
            </div>
            <div class="fin-item">
              <span class="fin-label">净利润</span>
              <span class="fin-value">{{ fmtNum(financialData.latest.net_profit) }}</span>
            </div>
            <div class="fin-item">
              <span class="fin-label">营收同比</span>
              <span class="fin-value" :class="{ 'val-up': (financialData.latest.revenue_yoy ?? 0) > 0, 'val-down': (financialData.latest.revenue_yoy ?? 0) < 0 }">{{ fmtPct(financialData.latest.revenue_yoy) }}</span>
            </div>
            <div class="fin-item">
              <span class="fin-label">净利润同比</span>
              <span class="fin-value" :class="{ 'val-up': (financialData.latest.net_profit_yoy ?? 0) > 0, 'val-down': (financialData.latest.net_profit_yoy ?? 0) < 0 }">{{ fmtPct(financialData.latest.net_profit_yoy) }}</span>
            </div>
            <div class="fin-item">
              <span class="fin-label">毛利率</span>
              <span class="fin-value">{{ fmtPct(financialData.latest.gross_margin) }}</span>
            </div>
            <div class="fin-item">
              <span class="fin-label">销售净利率</span>
              <span class="fin-value">{{ fmtPct(financialData.latest.net_profit_margin) }}</span>
            </div>
            <div class="fin-item">
              <span class="fin-label">资产负债率</span>
              <span class="fin-value">{{ fmtPct(financialData.latest.asset_liability_ratio) }}</span>
            </div>
            <div class="fin-item">
              <span class="fin-label">流动比率</span>
              <span class="fin-value">{{ fmtNum(financialData.latest.current_ratio) }}</span>
            </div>
            <div class="fin-item">
              <span class="fin-label">每股经营现金流</span>
              <span class="fin-value">{{ fmtNum(financialData.latest.ocfps, 4) }}</span>
            </div>
            <div class="fin-item">
              <span class="fin-label">研发费用</span>
              <span class="fin-value">{{ fmtNum(financialData.latest.rd_expense) }}</span>
            </div>
            <div class="fin-item">
              <span class="fin-label">研发费用率</span>
              <span class="fin-value">{{ fmtPct(financialData.latest.rd_ratio) }}</span>
            </div>
            <div class="fin-item">
              <span class="fin-label">管理费用</span>
              <span class="fin-value">{{ fmtNum(financialData.latest.admin_expense) }}</span>
            </div>
            <div class="fin-item">
              <span class="fin-label">销售费用</span>
              <span class="fin-value">{{ fmtNum(financialData.latest.selling_expense) }}</span>
            </div>
            <div class="fin-item">
              <span class="fin-label">财务费用</span>
              <span class="fin-value">{{ fmtNum(financialData.latest.financial_expense) }}</span>
            </div>
            <div class="fin-item fin-item-full">
              <span class="fin-label">报告期</span>
              <span class="fin-value">{{ financialData.latest.report_name || financialData.latest.report_date || '-' }}</span>
            </div>
          </template>
        </div>
        <!-- 季度/年度趋势图表 -->
        <div v-if="financialData?.history?.length" class="financial-chart-wrap">
          <div class="chart-subtitle">季度/年度财务趋势（营收·净利润·EPS·利润率）</div>
          <div ref="financialChartRef" class="financial-chart"></div>
        </div>
        <!-- 费用结构趋势图表 -->
        <div v-if="financialData?.history?.length && hasExpenseData" class="financial-chart-wrap">
          <div class="chart-subtitle">费用结构趋势（研发·管理·销售·财务费用占营收比）</div>
          <div ref="expenseChartRef" class="financial-chart"></div>
        </div>
      </div>
      <el-empty v-else description="暂无财务数据" :image-size="60" />
    </div>

    <!-- 公司概况 / 基本面 (行业·地区·概念·板块·营收总额，cn_stock_selection 100% 覆盖) -->
    <div v-if="code" v-show="profileHasData" class="section-card">
      <CompanyProfileCard :code="code" :name="stockName" @loaded="onProfileLoaded" />
    </div>

    <!-- 知识产权 / 专利护城河 (仅当存在专利数据时显示；无数据自动隐藏) -->
    <div v-if="code" v-show="patentHasData" class="section-card">
      <PatentCard :code="code" @loaded="onPatentLoaded" />
    </div>

    <!-- 最新 AI 分析报告 -->
    <div v-if="latestReport" class="section-card">
      <div class="section-title">
        <span>最新 AI 分析</span>
        <el-button type="primary" link size="small" @click="goAIAnalysis">查看完整报告 →</el-button>
      </div>
      <div class="report-summary">
        <div class="report-meta">
          <el-tag size="small" type="info">{{ latestReport.model }}</el-tag>
          <span class="report-time">{{ latestReport.created_at }}</span>
        </div>
        <div class="report-action">
          <el-button type="primary" size="small" @click="goAIAnalysis">
            <el-icon><ChatDotRound /></el-icon>&nbsp;生成/查看完整分析
          </el-button>
        </div>
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
  background: #fafafa; flex-wrap: wrap; gap: 8px;
}
.toolbar-left {
  display: flex; align-items: center; gap: 24px; flex-wrap: wrap;
}
.strategy-mark-hint {
  margin-left: auto; display: flex; align-items: center; gap: 6px;
  font-size: 12px; color: #7b3fe4; white-space: nowrap;
  .dot { width: 8px; height: 8px; border-radius: 50%; background: rgba(146,84,222,0.92); flex: none; }
  b { font-weight: 700; }
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
.pred-controls {
  display: flex; align-items: center; margin-left: 12px;
}

.pred-score-panel {
  border-bottom: 1px solid #dfe4ea;
  background: #f7f9fb;
  padding: 10px 16px 12px;
}
.pred-score-summary {
  display: grid;
  grid-template-columns: minmax(150px, 1.35fr) repeat(6, minmax(82px, 1fr));
  gap: 8px 14px;
  align-items: center;
}
.pred-score-heading {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.pred-score-title { font-size: 14px; font-weight: 700; color: #303133; }
.pred-provider {
  padding: 1px 6px;
  border: 1px solid #d9a441;
  border-radius: 3px;
  color: #9a6413;
  background: #fff8e8;
  font-size: 10px;
  white-space: nowrap;
}
.pred-summary-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  span { color: #909399; font-size: 10px; white-space: nowrap; }
  b { color: #303133; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
}
.pred-factor-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-top: 9px;
  border-top: 1px solid #e3e7ed;
  border-left: 1px solid #e3e7ed;
}
.pred-factor-item {
  display: grid;
  grid-template-columns: minmax(72px, 1fr) auto;
  gap: 2px 10px;
  padding: 7px 9px;
  border-right: 1px solid #e3e7ed;
  border-bottom: 1px solid #e3e7ed;
  min-width: 0;
  background: #fff;
}
.pred-factor-name, .pred-factor-score { font-size: 12px; font-weight: 600; color: #303133; }
.pred-factor-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pred-factor-score, .pred-factor-contribution { text-align: right; }
.pred-factor-meta, .pred-factor-contribution { color: #909399; font-size: 10px; white-space: nowrap; }
.pred-score-panel .is-up { color: #ec0000; }
.pred-score-panel .is-down { color: #00a838; }

/* 行情快照栏（实时盘口）—— 扁平、密排，贴合本页东方财富风格 */
.quote-bar {
  border-bottom: 1px solid #f0f0f0;
  background: #fff;
  /* 涨/跌/平 三态基调：通过 CSS 变量驱动现价与涨跌字色 */
  --q-color: #909399;
}
.quote-bar.qdir-1 { --q-color: #ec0000; }   /* 涨：红 */
.quote-bar.qdir--1 { --q-color: #00a838; }  /* 跌：绿 */
.quote-main {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 16px;
  padding: 8px 16px;
}
.quote-main .quote-price {
  font-size: 30px;
  font-weight: 700;
  line-height: 1;
  color: var(--q-color);
}
.quote-main .quote-chg {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: var(--q-color);
}
.quote-main .quote-limit {
  display: flex;
  gap: 12px;
  font-size: 12px;
  .lim-up { color: #ec0000; }
  .lim-down { color: #00a838; }
}
.quote-main .quote-toggle {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 12px;
  color: #909399;
  cursor: pointer;
  user-select: none;
  .el-icon { transition: transform .2s; }
  .el-icon.collapsed { transform: rotate(-90deg); }
  &:hover { color: #409eff; }
}
.quote-metrics {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(118px, 1fr));
  gap: 1px;
  padding: 0 16px 10px;
}
.quote-metrics .qm {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 4px 8px;
  background: #fafbfc;
  border-radius: 4px;
  .qm-l { font-size: 12px; color: #909399; white-space: nowrap; }
  .qm-v { font-size: 13px; font-weight: 600; color: #303133; }
  .qm-v.qv-up { color: #ec0000; }
  .qm-v.qv-down { color: #00a838; }
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

/* 筹码分布读数条 */
.chip-strip {
  border-top: 1px solid #eee;
  background: linear-gradient(180deg, #fbfcfe 0%, #f6f8fb 100%);
  padding: 8px 14px;
  .chip-items {
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 8px 14px;
  }
  .chip-item {
    display: flex; flex-direction: column; gap: 2px;
    min-width: 0;
  }
  .chip-label { font-size: 11px; color: #909399; white-space: nowrap; }
  .chip-val {
    font-size: 13px; font-weight: 600; color: #303133;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .chip-val.kt-up { color: #ec0000; }
  .chip-val.kt-down { color: #00a838; }
  .chip-meta {
    display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
    margin-top: 6px; font-size: 11px; color: #909399;
  }
  .chip-src {
    padding: 1px 7px; border-radius: 9px; font-weight: 600;
    background: #eef1f6; color: #606266;
    &.src-compute { background: #e7f6ec; color: #00a838; }
    &.src-db_stale { background: #fdf0e6; color: #e6a23c; }
  }
  .chip-asof { color: #a8abb2; }
  .chip-msg { color: #e6a23c; }
  .chip-empty { font-size: 12px; color: #909399; text-align: center; padding: 4px 0; }
}

/* 移动端：紧凑信息栏与工具栏，避免横向溢出 */
@media (max-width: 767.98px) {
  .top-bar {
    flex-wrap: wrap;
    gap: 8px;
    padding: 8px 12px;
    .stock-basic { gap: 8px; .stock-code { font-size: 16px; } .stock-name { font-size: 13px; } }
  }
  .toolbar { padding: 6px 8px; }
  .toolbar-left { gap: 12px; }
  .pred-score-panel { padding: 8px 10px 10px; }
  .pred-score-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 7px 10px; }
  .pred-score-heading { grid-column: 1 / -1; }
  .pred-factor-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .pred-factor-item { padding: 6px 7px; grid-template-columns: minmax(64px, 1fr) auto; gap: 2px 6px; }
  .period-tabs .period-tab { padding: 3px 8px; font-size: 12px; }
  .overlay-checks .label { display: none; }
  .sub-indicator-bar .sub-tab { padding: 6px 0; font-size: 11px; }
  /* 移动端筹码读数条：改为 2 列，缩小内边距与字号 */
  .chip-strip { padding: 6px 10px; }
  .chip-strip .chip-items { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px 10px; }
  .chip-strip .chip-label { font-size: 10px; }
  .chip-strip .chip-val { font-size: 12px; }
  /* 移动端行情快照：现价缩小，盘口网格改为更窄列 */
  .quote-main { gap: 10px; padding: 8px 12px; }
  .quote-main .quote-price { font-size: 24px; }
  .quote-main .quote-chg { font-size: 13px; }
  .quote-metrics { grid-template-columns: repeat(auto-fill, minmax(96px, 1fr)); padding: 0 12px 8px; }
  .quote-metrics .qm { padding: 4px 6px; .qm-l { font-size: 11px; } .qm-v { font-size: 12px; } }
  .sub-indicator-segmented {
    width: 100%;
    padding: 4px 8px;
    background: #fafafa;
    border-top: 1px solid #eee;
  }
}

/* PR-09 C: 移动端横屏 —— 隐藏信息栏 / 工具栏，把整个高度让给图表 */
@media (max-width: 991.98px) and (orientation: landscape) and (max-height: 540px) {
  .top-bar, .toolbar, .quote-bar, .pred-score-panel { display: none; }
  .chart-wrapper .chart-main { height: calc(100dvh - 40px) !important; }
  .sub-indicator-bar, .sub-indicator-segmented { padding: 2px 6px; }
}

/* 财务分析 & AI报告 区块 */
.section-card {
  margin: 12px 16px;
  padding: 16px;
  background: #fafbfc;
  border: 1px solid #eee;
  border-radius: 8px;
}
.section-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.report-period-badge {
  font-size: 12px;
  font-weight: 500;
  color: #409eff;
  background: #ecf5ff;
  border: 1px solid #d9ecff;
  border-radius: 4px;
  padding: 2px 8px;
}
.financial-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 10px;
}
.fin-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  background: #fff;
  border-radius: 6px;
  border: 1px solid #f0f0f0;
}
.fin-item-full {
  grid-column: 1 / -1;
}
.fin-label {
  font-size: 12px;
  color: #909399;
}
.fin-value {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}
.val-up { color: #ec0000; }
.val-down { color: #00da3c; }
.financial-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.financial-chart-wrap {
  margin-top: 4px;
}
.chart-subtitle {
  font-size: 13px;
  color: #606266;
  margin-bottom: 8px;
  font-weight: 500;
}
.financial-chart {
  width: 100%;
  height: 320px;
}
.report-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.report-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}
.report-time {
  font-size: 12px;
  color: #909399;
}
</style>

<!-- 非 scoped：K线悬浮 tooltip 由 ECharts 渲染到组件外部 DOM，scoped 选择器无法命中，故单列全局样式 -->
<style lang="scss">
.kline-tip {
  min-width: 168px;
  padding: 8px 12px;
  font-size: 12px;
  line-height: 1.7;
  .kt-date { font-weight: 700; color: #303133; margin-bottom: 4px; }
  .kt-row {
    display: flex; align-items: center; gap: 8px;
    .kt-label { color: #909399; min-width: 36px; }
    .kt-val { font-weight: 600; color: #303133; margin-left: auto; }
    .kt-val.kt-up { color: #ec0000; }
    .kt-val.kt-down { color: #00a838; }
    .kt-up { color: #ec0000; }
    .kt-down { color: #00a838; }
    .kt-sub { font-size: 10px; color: #b0b0b0; margin-left: 4px; }
  }
  .kt-sep { height: 1px; background: #f0f0f0; margin: 5px 0; }
  .kt-pred-badge {
    display: inline-block;
    font-size: 10px;
    padding: 0 4px;
    border-radius: 3px;
    background: #e6a23c;
    color: #fff;
    margin-left: 6px;
    vertical-align: middle;
  }
  .kt-pred-header {
    font-weight: 700;
    font-size: 11px;
    color: #e6a23c;
    margin: 3px 0 2px;
  }
}
.kline-tip-pred {
  min-width: 200px;
  max-width: 280px;
}
</style>
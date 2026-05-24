<template>
  <div class="stock-analysis">
    <!-- 搜索栏 -->
    <div class="search-bar">
      <el-autocomplete
        v-model="searchText"
        :fetch-suggestions="queryStock"
        placeholder="输入股票代码或名称搜索"
        :trigger-on-focus="false"
        :debounce="300"
        clearable
        class="search-input"
        @select="handleSelect"
      >
        <template #default="{ item }">
          <span class="suggestion-code">{{ item.code }}</span>
          <span class="suggestion-name">{{ item.name }}</span>
          <span v-if="item.industry" class="suggestion-industry">{{ item.industry }}</span>
        </template>
      </el-autocomplete>
      <el-button type="primary" :loading="generating" :disabled="!currentCode" @click="handleGenerate">
        <el-icon><VideoPlay /></el-icon>
        生成报告
      </el-button>
      <el-button v-if="reportContent" @click="handleCopy">
        <el-icon><CopyDocument /></el-icon>
        复制
      </el-button>
    </div>

    <!-- 进度可视化 -->
    <div v-if="generating" class="progress-panel">
      <div class="progress-title">
        <el-icon class="is-loading"><Loading /></el-icon>
        分析中：{{ currentCode }} {{ currentName }}
      </div>
      <div class="progress-steps">
        <div v-for="step in progressSteps" :key="step.name" class="step-item">
          <el-icon v-if="step.status === 'done'" class="step-icon done"><CircleCheckFilled /></el-icon>
          <el-icon v-else-if="step.status === 'running'" class="step-icon running is-loading"><Loading /></el-icon>
          <el-icon v-else class="step-icon pending"><Clock /></el-icon>
          <span class="step-label">{{ step.label }}</span>
          <span v-if="step.elapsed" class="step-elapsed">{{ step.elapsed }}ms</span>
        </div>
      </div>
    </div>

    <!-- K线图面板 -->
    <div v-if="currentCode && klineLoaded" class="kline-panel">
      <div class="kline-header" @click="klineCollapsed = !klineCollapsed">
        <span class="kline-title">📈 K线走势 · {{ currentCode }} {{ currentName }}</span>
        <el-icon class="kline-toggle" :class="{ collapsed: klineCollapsed }"><ArrowDown /></el-icon>
      </div>
      <div v-show="!klineCollapsed" class="kline-chart-wrap">
        <div ref="klineChartRef" class="kline-chart"></div>
      </div>
    </div>

    <!-- 错误降级面板 -->
    <div v-if="errorMsg && !reportContent" class="fallback-panel">
      <el-alert type="warning" :closable="false" show-icon>
        <template #title>AI 分析服务暂时不可用</template>
        <template #default>
          <p>{{ errorMsg }}</p>
          <el-button size="small" type="primary" @click="handleGenerate">重试生成报告</el-button>
        </template>
      </el-alert>
    </div>

    <!-- 报告内容 -->
    <div v-if="reportContent" class="report-container" ref="reportRef">
      <!-- 数据更新提示横幅 -->
      <el-alert
        v-if="dataUpdateReason"
        type="info"
        :closable="false"
        class="data-update-banner"
      >
        <template #title>
          ⚠️ {{ dataUpdateReason }}，本报告基于缓存数据
          <el-button size="small" type="primary" link @click="handleGenerate(true)">刷新分析</el-button>
        </template>
      </el-alert>
      <div class="report-header">
        <el-tag v-if="fromCache" type="info" size="small">缓存</el-tag>
        <span class="report-meta" v-if="reportMeta.created_at">
          生成时间：{{ reportMeta.created_at }}
        </span>
        <span class="report-meta" v-if="reportMeta.tokens_used">
          Token：{{ reportMeta.tokens_used }}
        </span>
        <span class="report-meta" v-if="reportMeta.latency_ms">
          耗时：{{ (reportMeta.latency_ms / 1000).toFixed(1) }}s
        </span>
      </div>
      <div class="report-body markdown-body" v-html="renderedHtml"></div>

      <!-- 追问回答区域 -->
      <div v-if="followupAnswers.length" class="followup-answers">
        <div v-for="(fa, idx) in followupAnswers" :key="idx" class="followup-item">
          <div class="followup-question">💬 {{ fa.question }}</div>
          <div class="followup-answer markdown-body" v-html="renderFollowup(fa.answer)"></div>
        </div>
      </div>

      <!-- 追问输入框 -->
      <div class="followup-bar">
        <el-input
          v-model="followupText"
          placeholder="对报告有疑问？输入追问..."
          :disabled="followupLoading"
          clearable
          @keyup.enter="handleFollowup"
        />
        <el-button
          type="primary"
          :loading="followupLoading"
          :disabled="!followupText.trim()"
          @click="handleFollowup"
        >
          追问
        </el-button>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-if="!generating && !reportContent && !errorMsg" class="empty-state">
      <el-empty description="输入股票代码，一键生成 AI 分析报告">
        <template #image>
          <el-icon :size="64" color="#c0c4cc"><DataAnalysis /></el-icon>
        </template>
      </el-empty>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  VideoPlay, CopyDocument, Loading, CircleCheckFilled, Clock, DataAnalysis, ArrowDown
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { searchStock, generateReportStream, followupReportStream } from '@/api/report'
import { getKlineData } from '@/api/stock'
import type { ReportStreamEvent, StockSearchItem, FollowupStreamEvent } from '@/api/report'
import * as echarts from 'echarts'

// ---- markdown-it setup (dynamic import for code-split) ----
const mdInstance = ref<{ render: (src: string) => string } | null>(null)
async function ensureMarkdownIt() {
  if (mdInstance.value) return mdInstance.value
  const MarkdownIt = (await import('markdown-it')).default
  mdInstance.value = new MarkdownIt({ html: false, linkify: true, typographer: true })
  return mdInstance.value
}

// ---- State ----
const route = useRoute()
const searchText = ref('')
const currentCode = ref('')
const currentName = ref('')
const generating = ref(false)
const reportContent = ref('')
const errorMsg = ref('')
const fromCache = ref(false)
const dataUpdateReason = ref('')
const reportRef = ref<HTMLElement | null>(null)
const abortController = ref<AbortController | null>(null)

// ---- K-line Chart State ----
const klineChartRef = ref<HTMLElement | null>(null)
const klineLoaded = ref(false)
const klineCollapsed = ref(false)
let chartInstance: echarts.ECharts | null = null

// ---- Follow-up State ----
const followupText = ref('')
const followupLoading = ref(false)
interface FollowupEntry { question: string; answer: string }
const followupAnswers = ref<FollowupEntry[]>([])

interface ProgressStep {
  name: string
  label: string
  status: 'pending' | 'running' | 'done'
  elapsed?: number
}

const progressSteps = ref<ProgressStep[]>([
  { name: 'stock_profile', label: '获取基础行情数据', status: 'pending' },
  { name: 'kline_fetch', label: '查询K线与指标', status: 'pending' },
  { name: 'web_search', label: '搜索近期新闻', status: 'pending' },
  { name: 'report', label: '生成分析报告', status: 'pending' },
])

interface ReportMeta {
  created_at?: string
  tokens_used?: number
  latency_ms?: number
  model?: string
}
const reportMeta = ref<ReportMeta>({})

const renderedHtml = computed(() => {
  if (!reportContent.value || !mdInstance.value) return ''
  return mdInstance.value.render(reportContent.value)
})

// ---- Methods ----
async function queryStock(queryString: string, cb: (items: { value: string; code: string; name: string }[]) => void) {
  if (!queryString || queryString.length < 1) {
    cb([])
    return
  }
  try {
    const res = await searchStock(queryString) as any
    const data = res?.items || res?.data?.items || []
    const items = data.map((item: StockSearchItem) => ({
      value: `${item.code} ${item.name}`,
      code: item.code,
      name: item.name,
      industry: item.industry || '',
    }))
    cb(items)
  } catch (e) {
    console.warn('[analysis] 股票搜索失败:', e)
    cb([])
  }
}

function handleSelect(item: { code: string; name: string }) {
  currentCode.value = item.code
  currentName.value = item.name
  searchText.value = `${item.code} ${item.name}`
}

async function handleGenerate(force?: boolean | MouseEvent) {
  if (!currentCode.value) {
    ElMessage.warning('请先选择股票')
    return
  }
  // @click passes MouseEvent as first arg; normalize to boolean
  const forceRefresh = force === true

  // Reset state
  generating.value = true
  reportContent.value = ''
  errorMsg.value = ''
  fromCache.value = false
  dataUpdateReason.value = ''
  reportMeta.value = {}
  followupAnswers.value = []
  progressSteps.value = progressSteps.value.map(s => ({ ...s, status: 'pending' as const, elapsed: undefined }))

  // Init markdown-it
  await ensureMarkdownIt()

  // Abort previous
  if (abortController.value) {
    abortController.value.abort()
  }
  abortController.value = new AbortController()

  try {
    await generateReportStream(
      currentCode.value,
      (ev: ReportStreamEvent) => handleStreamEvent(ev),
      { force: forceRefresh, signal: abortController.value!.signal }
    )
  } catch (e: unknown) {
    if (e instanceof Error && e.name !== 'AbortError') {
      errorMsg.value = e.message || '生成报告失败'
    }
  } finally {
    generating.value = false
  }
}

function handleStreamEvent(ev: ReportStreamEvent) {
  switch (ev.type) {
    case 'progress':
      updateProgress(ev.step || '', ev.status || '', ev.elapsed_ms)
      break
    case 'chunk':
      reportContent.value += ev.text || ''
      // Auto scroll
      nextTick(() => {
        if (reportRef.value) {
          reportRef.value.scrollTop = reportRef.value.scrollHeight
        }
      })
      break
    case 'cached':
      fromCache.value = true
      if (ev.report) {
        reportContent.value = ev.report.report_md || ''
        currentName.value = ev.report.name || currentName.value
        reportMeta.value = {
          created_at: ev.report.created_at,
          tokens_used: ev.report.tokens_used,
          latency_ms: ev.report.latency_ms,
          model: ev.report.model,
        }
        // 数据已更新提示
        if ((ev.report as any).data_updated) {
          dataUpdateReason.value = (ev.report as any).update_reason || '数据已更新'
        }
      }
      generating.value = false
      break
    case 'done':
      if (ev.tokens_used) reportMeta.value.tokens_used = ev.tokens_used
      if (ev.latency_ms) reportMeta.value.latency_ms = ev.latency_ms
      if (!reportMeta.value.created_at) {
        reportMeta.value.created_at = new Date().toLocaleString()
      }
      generating.value = false
      break
    case 'error':
      errorMsg.value = ev.msg || '生成失败'
      generating.value = false
      break
  }
}

function updateProgress(step: string, status: string, elapsed?: number) {
  const idx = progressSteps.value.findIndex(s => s.name === step)
  if (idx >= 0) {
    progressSteps.value[idx].status = status as 'running' | 'done'
    if (elapsed) progressSteps.value[idx].elapsed = elapsed
  }
}

async function handleCopy() {
  try {
    await navigator.clipboard.writeText(reportContent.value)
    ElMessage.success('已复制报告内容')
  } catch {
    ElMessage.error('复制失败')
  }
}

// ---- Follow-up ----
function renderFollowup(md: string): string {
  if (!mdInstance.value) return md
  return mdInstance.value.render(md)
}

async function handleFollowup() {
  const question = followupText.value.trim()
  if (!question || !reportContent.value) return

  followupLoading.value = true
  const entry: FollowupEntry = { question, answer: '' }
  followupAnswers.value.push(entry)
  followupText.value = ''

  try {
    await followupReportStream(
      currentCode.value,
      question,
      reportContent.value,
      (ev: FollowupStreamEvent) => {
        if (ev.type === 'chunk' && ev.text) {
          entry.answer += ev.text
        } else if (ev.type === 'error') {
          entry.answer = `⚠️ ${ev.msg || '追问失败'}`
        }
      },
    )
  } catch (e: unknown) {
    if (e instanceof Error && e.name !== 'AbortError') {
      entry.answer = `⚠️ ${e.message || '追问失败'}`
    }
  } finally {
    followupLoading.value = false
    // Scroll to bottom
    nextTick(() => {
      if (reportRef.value) {
        reportRef.value.scrollTop = reportRef.value.scrollHeight
      }
    })
  }
}

// ---- K-line Chart ----
async function loadKlineChart(code: string) {
  klineLoaded.value = false
  try {
    const res = await getKlineData({ code, days: 90 }) as any
    const data = res?.data || res
    if (!data?.dates?.length) return

    klineLoaded.value = true
    await nextTick()

    if (!klineChartRef.value) return
    if (chartInstance) chartInstance.dispose()
    chartInstance = echarts.init(klineChartRef.value)

    const dates: string[] = data.dates
    const ohlc: number[][] = data.ohlc || []
    const volumes: number[] = data.volumes || []
    const ma = data.ma || {}
    const boll = data.boll || {}
    const macd = data.macd || {}

    // Show last ~60 data points by default
    const startPercent = dates.length > 60 ? Math.round((1 - 60 / dates.length) * 100) : 0

    const option: echarts.EChartsOption = {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        backgroundColor: 'rgba(255,255,255,0.95)',
        borderColor: '#eee',
        textStyle: { fontSize: 12 },
      },
      legend: {
        data: ['MA5', 'MA20', 'MA60', 'BOLL上轨', 'BOLL下轨'],
        top: 4,
        textStyle: { fontSize: 11 },
        itemWidth: 14,
        itemHeight: 8,
      },
      grid: [
        { left: 56, right: 20, top: 40, height: 200 },
        { left: 56, right: 20, top: 280, height: 50 },
        { left: 56, right: 20, top: 360, height: 50 },
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1, 2], start: startPercent, end: 100 },
        { type: 'slider', xAxisIndex: [0, 1, 2], start: startPercent, end: 100, bottom: 4, height: 16 },
      ],
      xAxis: [
        { type: 'category', data: dates, boundaryGap: true, axisLabel: { fontSize: 10 } },
        { type: 'category', data: dates, gridIndex: 1, axisLabel: { show: false } },
        { type: 'category', data: dates, gridIndex: 2, axisLabel: { fontSize: 10 } },
      ],
      yAxis: [
        { scale: true, axisLabel: { fontSize: 10 }, splitLine: { lineStyle: { type: 'dashed', color: '#eee' } } },
        { scale: true, gridIndex: 1, axisLabel: { fontSize: 10 }, splitLine: { show: false } },
        { scale: true, gridIndex: 2, axisLabel: { fontSize: 10 }, splitLine: { show: false } },
      ],
      series: [
        {
          name: 'K线',
          type: 'candlestick',
          data: ohlc,
          itemStyle: {
            color: '#f56c6c',
            color0: '#67c23a',
            borderColor: '#f56c6c',
            borderColor0: '#67c23a',
          },
        },
        { name: 'MA5', type: 'line', data: ma.ma5 || [], symbol: 'none', lineStyle: { width: 1, color: '#e6a23c' } },
        { name: 'MA20', type: 'line', data: ma.ma20 || [], symbol: 'none', lineStyle: { width: 1, color: '#409eff' } },
        { name: 'MA60', type: 'line', data: ma.ma60 || [], symbol: 'none', lineStyle: { width: 1, color: '#909399' } },
        { name: 'BOLL上轨', type: 'line', data: boll.upper || [], symbol: 'none', lineStyle: { width: 1, type: 'dashed', color: '#c45656' } },
        { name: 'BOLL下轨', type: 'line', data: boll.lower || [], symbol: 'none', lineStyle: { width: 1, type: 'dashed', color: '#529b2e' } },
        {
          name: '成交量',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumes.map((v, i) => ({
            value: v,
            itemStyle: { color: ohlc[i] && Number(ohlc[i][1]) >= Number(ohlc[i][0]) ? '#f56c6c' : '#67c23a' },
          })),
          barMaxWidth: 6,
        },
        { name: 'MACD柱', type: 'bar', xAxisIndex: 2, yAxisIndex: 2, data: (macd.histogram || []).map((v: number) => ({ value: v, itemStyle: { color: v >= 0 ? '#f56c6c' : '#67c23a' } })), barMaxWidth: 6 },
        { name: 'DIF', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: macd.dif || [], symbol: 'none', lineStyle: { width: 1, color: '#e6a23c' } },
        { name: 'DEA', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: macd.dea || [], symbol: 'none', lineStyle: { width: 1, color: '#409eff' } },
      ],
    }

    chartInstance.setOption(option)
  } catch (e) {
    console.warn('[analysis] K线数据加载失败:', e)
  }
}

function handleChartResize() {
  chartInstance?.resize()
}

// ---- Lifecycle ----
onMounted(async () => {
  await ensureMarkdownIt()
  window.addEventListener('resize', handleChartResize)
  // 支持从 URL query 参数传入 code
  const code = route.query.code as string
  if (code && code.length === 6) {
    currentCode.value = code
    searchText.value = code
    handleGenerate()
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleChartResize)
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
})

// Watch code changes to load kline
watch(currentCode, (code) => {
  if (code && code.length === 6) {
    loadKlineChart(code)
  } else {
    klineLoaded.value = false
  }
})

// Resize chart after expand (v-show → ECharts container size may be 0)
watch(klineCollapsed, (collapsed) => {
  if (!collapsed && chartInstance) {
    nextTick(() => chartInstance?.resize())
  }
})
</script>

<style scoped>
.stock-analysis {
  padding: 20px;
  max-width: 960px;
  margin: 0 auto;
}

.search-bar {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 20px;
}

.search-input {
  width: 320px;
}

.suggestion-code {
  font-family: monospace;
  font-weight: 600;
  margin-right: 8px;
  color: var(--el-color-primary);
}

.suggestion-name {
  color: var(--el-text-color-regular);
}

.suggestion-industry {
  margin-left: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.progress-panel {
  background: var(--el-fill-color-light);
  border-radius: 8px;
  padding: 16px 20px;
  margin-bottom: 20px;
}

.progress-title {
  font-size: 15px;
  font-weight: 500;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.progress-steps {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.step-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.step-icon.done { color: var(--el-color-success); }
.step-icon.running { color: var(--el-color-primary); }
.step-icon.pending { color: var(--el-text-color-placeholder); }

.step-elapsed {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-left: auto;
}

.fallback-panel {
  margin-bottom: 20px;
}

.report-container {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 20px;
  max-height: 70vh;
  overflow-y: auto;
}

.report-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.report-meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.report-body :deep(h3) {
  margin-top: 20px;
  margin-bottom: 8px;
  font-size: 16px;
}

.report-body :deep(h4) {
  margin-top: 16px;
  margin-bottom: 6px;
  font-size: 14px;
  color: var(--el-text-color-primary);
}

.report-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
}

.report-body :deep(th),
.report-body :deep(td) {
  border: 1px solid var(--el-border-color-lighter);
  padding: 8px 12px;
  text-align: left;
  font-size: 13px;
}

.report-body :deep(th) {
  background: var(--el-fill-color-light);
  font-weight: 600;
}

.report-body :deep(ul),
.report-body :deep(ol) {
  padding-left: 20px;
  margin: 8px 0;
}

.report-body :deep(li) {
  margin: 4px 0;
  line-height: 1.6;
}

.report-body :deep(strong) {
  color: var(--el-text-color-primary);
}

.empty-state {
  margin-top: 80px;
}

.kline-panel {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  margin-bottom: 20px;
  overflow: hidden;
}

.kline-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  cursor: pointer;
  user-select: none;
  background: var(--el-fill-color-light);
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.kline-header:hover {
  background: var(--el-fill-color);
}

.kline-title {
  font-size: 14px;
  font-weight: 500;
}

.kline-toggle {
  transition: transform 0.2s;
}

.kline-toggle.collapsed {
  transform: rotate(-90deg);
}

.kline-chart-wrap {
  padding: 8px 0;
}

.kline-chart {
  width: 100%;
  height: 440px;
}

.followup-answers {
  margin-top: 20px;
  border-top: 1px solid var(--el-border-color-lighter);
  padding-top: 16px;
}

.followup-item {
  margin-bottom: 16px;
}

.followup-question {
  font-size: 13px;
  font-weight: 500;
  color: var(--el-color-primary);
  margin-bottom: 6px;
}

.followup-answer {
  font-size: 13px;
  line-height: 1.6;
  padding-left: 12px;
  border-left: 3px solid var(--el-color-primary-light-5);
}

.followup-bar {
  display: flex;
  gap: 8px;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px dashed var(--el-border-color-lighter);
}

@media (max-width: 600px) {
  .search-bar {
    flex-wrap: wrap;
  }
  .search-input {
    width: 100%;
  }
  .report-container {
    max-height: none;
    padding: 12px;
  }
  .kline-chart {
    height: 320px;
  }
  .followup-bar {
    flex-direction: column;
  }
}
</style>

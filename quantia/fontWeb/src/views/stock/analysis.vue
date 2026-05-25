<template>
  <div class="stock-analysis">
    <!-- 搜索栏 -->
    <div class="search-bar">
      <div class="search-row">
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
        <el-button
          v-if="attentionCount > 0"
          :loading="batchGenerating"
          @click="handleBatchAnalysis"
        >
          📋 批量分析({{ attentionCount }})
        </el-button>
      </div>
      <!-- 报告工具栏：仅报告生成后显示 -->
      <div v-if="reportContent" class="toolbar-row">
        <el-button size="small" @click="handleCopy">
          <el-icon><CopyDocument /></el-icon>
          复制
        </el-button>
        <el-button size="small" @click="handleExportPdf">📄 PDF</el-button>
        <el-button size="small" @click="handleExportImage">🖼️ 图片</el-button>
        <el-button v-if="reportMeta.report_id" size="small" @click="handleShare">🔗 分享</el-button>
        <el-button size="small" :loading="translating" @click="handleTranslate">
          {{ isTranslated ? '🇨🇳 中文' : '🌐 英文' }}
        </el-button>
        <el-button size="small" @click="handleVoice" :type="isSpeaking ? 'danger' : 'default'">
          {{ isSpeaking ? '⏹️ 停止' : '🔊 播报' }}
        </el-button>
      </div>
    </div>

    <!-- 批量分析结果卡片网格 -->
    <div v-if="batchResults.length > 0" class="batch-panel">
      <div class="batch-header">
        <span class="batch-title">📋 关注列表分析摘要</span>
        <el-button size="small" text @click="batchResults = []">关闭</el-button>
      </div>
      <div class="batch-grid">
        <div
          v-for="item in batchResults"
          :key="item.code"
          class="batch-card"
          :class="{ 'batch-card--error': item.error }"
          @click="handleBatchCardClick(item)"
        >
          <div class="batch-card-header">
            <span class="batch-card-code">{{ item.code }}</span>
            <span class="batch-card-name">{{ item.name }}</span>
            <span v-if="item.rating" class="batch-card-rating" :class="`rating-${item.rating}`">
              {{ item.rating === 'bullish' ? '🟢 看多' : item.rating === 'bearish' ? '🔴 看空' : '🟡 中性' }}
            </span>
          </div>
          <p class="batch-card-summary">{{ item.summary }}</p>
          <div v-if="item.latency_ms" class="batch-card-meta">
            {{ item.latency_ms }}ms
          </div>
        </div>
        <!-- 生成中占位卡片 -->
        <div v-if="batchGenerating" class="batch-card batch-card--loading">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span>生成中... ({{ batchResults.length }}/{{ batchTotal }})</span>
        </div>
      </div>
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

    <!-- 主内容区域（宽屏并排） -->
    <div class="main-content">
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

    <!-- 错误降级面板：展示结构化数据 -->
    <div v-if="errorMsg && !reportContent" class="fallback-panel">
      <el-alert type="warning" :closable="false" show-icon>
        <template #title>AI 分析服务暂时不可用</template>
        <template #default>
          <p>{{ errorMsg }}</p>
          <el-button size="small" type="primary" @click="handleGenerate">重试生成报告</el-button>
        </template>
      </el-alert>
      <!-- 结构化数据面板 -->
      <div v-if="fallbackData" class="fallback-data">
        <h4>📊 核心指标</h4>
        <div v-if="fallbackData.spot" class="fallback-metrics">
          <div class="metric-item">
            <span class="metric-label">最新价</span>
            <span class="metric-value" :class="{ up: fallbackData.spot.change_pct > 0, down: fallbackData.spot.change_pct < 0 }">
              {{ fallbackData.spot.close }} ({{ fallbackData.spot.change_pct > 0 ? '+' : '' }}{{ fallbackData.spot.change_pct?.toFixed(2) }}%)
            </span>
          </div>
          <div class="metric-item"><span class="metric-label">PE</span><span class="metric-value">{{ fallbackData.spot.pe?.toFixed(1) || '-' }}</span></div>
          <div class="metric-item"><span class="metric-label">PB</span><span class="metric-value">{{ fallbackData.spot.pb?.toFixed(2) || '-' }}</span></div>
          <div class="metric-item"><span class="metric-label">ROE</span><span class="metric-value">{{ fallbackData.spot.roe?.toFixed(1) || '-' }}%</span></div>
          <div class="metric-item"><span class="metric-label">总市值</span><span class="metric-value">{{ formatCap(fallbackData.spot.market_cap) }}</span></div>
          <div class="metric-item"><span class="metric-label">换手率</span><span class="metric-value">{{ fallbackData.spot.turnover?.toFixed(2) || '-' }}%</span></div>
        </div>
        <div v-if="fallbackData.indicators" class="fallback-section">
          <h4>📈 技术面</h4>
          <div class="fallback-metrics">
            <div class="metric-item">
              <span class="metric-label">MACD</span>
              <span class="metric-value" :class="{ up: fallbackData.indicators.macd > fallbackData.indicators.macd_signal, down: fallbackData.indicators.macd < fallbackData.indicators.macd_signal }">
                {{ fallbackData.indicators.macd > fallbackData.indicators.macd_signal ? '金叉' : '死叉' }}
              </span>
            </div>
            <div class="metric-item">
              <span class="metric-label">KDJ</span>
              <span class="metric-value" :class="{ up: fallbackData.indicators.kdj_k > 80, down: fallbackData.indicators.kdj_k < 20 }">
                K={{ fallbackData.indicators.kdj_k?.toFixed(0) }}
                {{ fallbackData.indicators.kdj_k > 80 ? '(超买)' : fallbackData.indicators.kdj_k < 20 ? '(超卖)' : '' }}
              </span>
            </div>
            <div class="metric-item"><span class="metric-label">RSI(6)</span><span class="metric-value">{{ fallbackData.indicators.rsi_6?.toFixed(1) || '-' }}</span></div>
          </div>
        </div>
        <div v-if="fallbackData.fund_flow?.length" class="fallback-section">
          <h4>💰 资金面（近5日主力净流入）</h4>
          <div class="fallback-flow">
            <span v-for="f in fallbackData.fund_flow" :key="f.date" class="flow-tag" :class="{ up: f.main > 0, down: f.main < 0 }">
              {{ f.date.slice(5) }}: {{ f.main > 0 ? '+' : '' }}{{ (f.main / 10000).toFixed(0) }}万
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- 报告内容 -->
    <div v-if="reportContent" class="report-container" ref="reportRef">
      <!-- TOC 目录侧栏 -->
      <div v-if="tocItems.length && !generating" class="report-toc">
        <div class="toc-title">目录</div>
        <div
          v-for="(item, idx) in tocItems"
          :key="item.id"
          class="toc-item"
          @click="scrollToSection(idx)"
        >{{ item.title }}</div>
      </div>
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

      <!-- 报告反馈 -->
      <div v-if="reportMeta.report_id" class="feedback-bar">
        <span class="feedback-label">这份报告有帮助吗？</span>
        <el-button
          :type="feedbackSubmitted === 1 ? 'success' : 'default'"
          size="small"
          :disabled="feedbackSubmitted !== 0"
          @click="handleFeedback(1)"
        >👍</el-button>
        <el-button
          :type="feedbackSubmitted === -1 ? 'danger' : 'default'"
          size="small"
          :disabled="feedbackSubmitted !== 0"
          @click="handleFeedback(-1)"
        >👎</el-button>
        <span v-if="feedbackSubmitted !== 0" class="feedback-done">感谢反馈！</span>
      </div>

      <!-- AI 评分历史趋势 (Phase 3) -->
      <div v-if="scoreHistory.length > 0" class="score-trend-panel">
        <h4 class="panel-title">📈 AI 评分趋势</h4>
        <div ref="scoreTrendChartRef" class="score-trend-chart"></div>
      </div>

      <!-- 报告版本时间线 (Phase 3) -->
      <div v-if="reportTimeline.length > 1" class="timeline-panel">
        <h4 class="panel-title">📋 分析历史</h4>
        <div class="timeline-items">
          <div
            v-for="(t, idx) in reportTimeline"
            :key="t.id"
            class="timeline-item"
            :class="{ active: t.id === reportMeta.report_id }"
            @click="loadTimelineReport(t.id)"
          >
            <span class="timeline-date">{{ t.created_at?.slice(0, 16) }}</span>
            <span v-if="t.rating" class="timeline-rating">{{ t.rating }}</span>
            <span class="timeline-model">{{ t.model }}</span>
            <span v-if="idx === 0" class="timeline-badge">最新</span>
          </div>
        </div>
      </div>
    </div>
    </div><!-- /main-content -->

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
import { searchStock, generateReportStream, followupReportStream, submitReportFeedback, getStockFallbackData, getAttentionList, batchSummaryStream, getScoreHistory, getReportTimeline, getReportDetail, createShareLink, translateReport, getSpeechText, getReportPreference } from '@/api/report'
import { getKlineData } from '@/api/stock'
import type { ReportStreamEvent, StockSearchItem, FollowupStreamEvent, StockFallbackData, BatchSummaryEvent, ScoreHistoryItem, ReportTimelineItem } from '@/api/report'
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
  report_id?: number
  created_at?: string
  tokens_used?: number
  latency_ms?: number
  model?: string
}
const reportMeta = ref<ReportMeta>({})

// ---- Feedback State ----
const feedbackSubmitted = ref<0 | 1 | -1>(0)

// ---- Fallback Data State ----
const fallbackData = ref<StockFallbackData | null>(null)

// ---- Batch Analysis State ----
const attentionCount = ref(0)
const attentionCodes = ref<string[]>([])
const batchGenerating = ref(false)
const batchTotal = ref(0)
interface BatchItem { code: string; name: string; summary: string; rating?: string; error?: boolean; latency_ms?: number }
const batchResults = ref<BatchItem[]>([])

// ---- Score History & Timeline State (Phase 3) ----
const scoreHistory = ref<ScoreHistoryItem[]>([])
const reportTimeline = ref<ReportTimelineItem[]>([])
const scoreTrendChartRef = ref<HTMLElement | null>(null)
let scoreTrendChart: echarts.ECharts | null = null
const renderedHtml = computed(() => {
  if (!reportContent.value || !mdInstance.value) return ''
  return mdInstance.value.render(reportContent.value)
})

// ---- TOC 目录锚点 (§10.8) ----
interface TocItem { id: string; title: string }
const tocItems = computed<TocItem[]>(() => {
  if (!reportContent.value) return []
  const headingRegex = /^#{4}\s+(.+)$/gm
  const items: TocItem[] = []
  let match: RegExpExecArray | null
  while ((match = headingRegex.exec(reportContent.value)) !== null) {
    const title = match[1].trim()
    const id = 'toc-' + items.length
    items.push({ id, title })
  }
  return items
})

function scrollToSection(idx: number) {
  const container = reportRef.value
  if (!container) return
  const headings = container.querySelectorAll('.report-body h4')
  if (headings[idx]) {
    headings[idx].scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

// ---- Methods ----
async function queryStock(queryString: string, cb: (items: { value: string; code: string; name: string }[]) => void) {
  if (!queryString || queryString.length < 1) {
    cb([])
    return
  }
  try {
    const res = await searchStock(queryString) as any
    const data = res?.items || []
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
  feedbackSubmitted.value = 0
  fallbackData.value = null
  isTranslated.value = false
  originalReportMd.value = ''
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
      loadFallbackData(currentCode.value)
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
          report_id: ev.report.id,
          created_at: ev.report.created_at,
          tokens_used: ev.report.tokens_used,
          latency_ms: ev.report.latency_ms,
          model: ev.report.model,
        }
        // 数据已更新提示
        if (ev.report.data_updated) {
          dataUpdateReason.value = ev.report.update_reason || '数据已更新'
        }
      }
      generating.value = false
      loadScoreHistory(currentCode.value)
      loadReportTimeline(currentCode.value)
      // 偏好设置：自动语音播报
      if (userVoiceEnabled.value && reportContent.value && !isSpeaking.value) {
        nextTick(() => handleVoice())
      }
      break
    case 'done':
      if (ev.tokens_used) reportMeta.value.tokens_used = ev.tokens_used
      if (ev.latency_ms) reportMeta.value.latency_ms = ev.latency_ms
      if (ev.report_id) reportMeta.value.report_id = ev.report_id
      if (!reportMeta.value.created_at) {
        reportMeta.value.created_at = new Date().toLocaleString()
      }
      generating.value = false
      loadScoreHistory(currentCode.value)
      loadReportTimeline(currentCode.value)
      // 偏好设置：自动语音播报
      if (userVoiceEnabled.value && reportContent.value && !isSpeaking.value) {
        nextTick(() => handleVoice())
      }
      break
    case 'error':
      errorMsg.value = ev.msg || '生成失败'
      generating.value = false
      loadFallbackData(currentCode.value)
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

async function handleExportPdf() {
  if (!reportRef.value) return
  try {
    ElMessage.info('正在生成 PDF...')
    const html2canvas = (await import('html2canvas')).default
    const { jsPDF } = await import('jspdf')
    const canvas = await html2canvas(reportRef.value, { scale: 2, useCORS: true })
    const imgData = canvas.toDataURL('image/png')
    const pdf = new jsPDF('p', 'mm', 'a4')
    const pageWidth = pdf.internal.pageSize.getWidth()
    const pageHeight = pdf.internal.pageSize.getHeight()
    const imgWidth = pageWidth - 20
    const imgHeight = (canvas.height * imgWidth) / canvas.width
    let heightLeft = imgHeight
    let position = 10
    pdf.addImage(imgData, 'PNG', 10, position, imgWidth, imgHeight)
    heightLeft -= pageHeight - 20
    while (heightLeft > 0) {
      position = heightLeft - imgHeight + 10
      pdf.addPage()
      pdf.addImage(imgData, 'PNG', 10, position, imgWidth, imgHeight)
      heightLeft -= pageHeight - 20
    }
    pdf.save(`AI分析报告_${currentCode.value}_${currentName.value}.pdf`)
    ElMessage.success('PDF 已下载')
  } catch (e) {
    ElMessage.error('PDF 导出失败')
    console.error(e)
  }
}

async function handleExportImage() {
  if (!reportRef.value) return
  try {
    ElMessage.info('正在生成图片...')
    const html2canvas = (await import('html2canvas')).default
    const canvas = await html2canvas(reportRef.value, { scale: 2, useCORS: true })
    const link = document.createElement('a')
    link.download = `AI分析报告_${currentCode.value}_${currentName.value}.png`
    link.href = canvas.toDataURL('image/png')
    link.click()
    ElMessage.success('图片已下载')
  } catch (e) {
    ElMessage.error('图片导出失败')
    console.error(e)
  }
}

async function handleShare() {
  const reportId = reportMeta.value.report_id
  if (!reportId) return
  try {
    const res = await createShareLink(reportId) as any
    const shareUrl = `${window.location.origin}${res.share_url}`
    await navigator.clipboard.writeText(shareUrl)
    ElMessage.success('分享链接已复制到剪贴板')
  } catch {
    ElMessage.error('生成分享链接失败')
  }
}

// ---- Phase 4: Voice Broadcast (Web Speech API) ----
const isSpeaking = ref(false)
const userVoiceEnabled = ref(false)  // 用户偏好：自动播报
let speechUtterance: SpeechSynthesisUtterance | null = null

async function handleVoice() {
  if (isSpeaking.value) {
    window.speechSynthesis.cancel()
    isSpeaking.value = false
    return
  }
  if (!reportContent.value) return

  try {
    const res = await getSpeechText({
      report_id: reportMeta.value.report_id,
      report_md: reportContent.value,
    }) as any
    const text = res.speech_text || reportContent.value.slice(0, 2000)

    if (!window.speechSynthesis) {
      ElMessage.warning('当前浏览器不支持语音播报')
      return
    }

    speechUtterance = new SpeechSynthesisUtterance(text)
    speechUtterance.lang = 'zh-CN'
    speechUtterance.rate = 1.0
    speechUtterance.onend = () => { isSpeaking.value = false }
    speechUtterance.onerror = () => { isSpeaking.value = false }

    window.speechSynthesis.speak(speechUtterance)
    isSpeaking.value = true
  } catch {
    ElMessage.error('获取播报文本失败')
  }
}

// ---- Phase 4: Multi-language Translation ----
const translating = ref(false)
const originalReportMd = ref('')  // 保存翻译前的原文
const isTranslated = ref(false)

async function handleTranslate() {
  if (!reportContent.value) return

  // 如果已翻译，恢复原文
  if (isTranslated.value && originalReportMd.value) {
    reportContent.value = originalReportMd.value
    isTranslated.value = false
    ElMessage.success('已恢复中文原文')
    return
  }

  translating.value = true
  try {
    const res = await translateReport({
      report_id: reportMeta.value.report_id,
      report_md: reportContent.value,
    }) as any
    if (res.translated_md) {
      originalReportMd.value = reportContent.value
      reportContent.value = res.translated_md
      isTranslated.value = true
      ElMessage.success('报告已翻译为英文')
    }
  } catch (err: any) {
    ElMessage.error('翻译失败: ' + (err.message || err))
  } finally {
    translating.value = false
  }
}

async function handleFeedback(value: 1 | -1) {
  const reportId = reportMeta.value.report_id
  if (!reportId) return
  try {
    await submitReportFeedback(reportId, value)
    feedbackSubmitted.value = value
  } catch {
    ElMessage.error('反馈提交失败')
  }
}

async function loadFallbackData(code: string) {
  if (!code) return
  try {
    const res = await getStockFallbackData(code) as any
    fallbackData.value = res || null
  } catch {
    // silent — fallback data is best-effort
  }
}

function formatCap(v: number | undefined | null): string {
  if (!v) return '-'
  if (v >= 100000000) return (v / 100000000).toFixed(0) + '亿'
  if (v >= 10000) return (v / 10000).toFixed(0) + '万'
  return String(v)
}

// ---- Batch Analysis ----
async function loadAttentionList() {
  try {
    const res = await getAttentionList() as any
    const items = res?.items || []
    attentionCount.value = items.length
    attentionCodes.value = items.map((i: { code: string }) => i.code)
  } catch {
    attentionCount.value = 0
    attentionCodes.value = []
  }
}

async function handleBatchAnalysis() {
  if (!attentionCodes.value.length) {
    ElMessage.warning('关注列表为空')
    return
  }
  batchGenerating.value = true
  batchResults.value = []
  batchTotal.value = attentionCodes.value.length

  try {
    await batchSummaryStream(
      attentionCodes.value,
      (ev: BatchSummaryEvent) => {
        switch (ev.type) {
          case 'start':
            batchTotal.value = ev.total || attentionCodes.value.length
            break
          case 'item':
            batchResults.value.push({
              code: ev.code || '',
              name: ev.name || '',
              summary: ev.summary || '',
              rating: ev.rating,
              error: ev.error,
              latency_ms: ev.latency_ms,
            })
            break
          case 'done':
            batchGenerating.value = false
            break
        }
      }
    )
  } catch (e: unknown) {
    if (e instanceof Error && e.name !== 'AbortError') {
      ElMessage.error(e.message || '批量分析失败')
    }
  } finally {
    batchGenerating.value = false
  }
}

function handleBatchCardClick(item: BatchItem) {
  if (item.error) return
  // Navigate to generate full report for this stock
  currentCode.value = item.code
  currentName.value = item.name
  searchText.value = `${item.code} ${item.name}`
  handleGenerate()
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
  followupAnswers.value.push({ question, answer: '' })
  const entryIndex = followupAnswers.value.length - 1
  followupText.value = ''

  try {
    await followupReportStream(
      currentCode.value,
      question,
      reportContent.value,
      (ev: FollowupStreamEvent) => {
        if (ev.type === 'chunk' && ev.text) {
          // Access through reactive array so Vue detects the change
          followupAnswers.value[entryIndex].answer += ev.text
        } else if (ev.type === 'error') {
          followupAnswers.value[entryIndex].answer = `⚠️ ${ev.msg || '追问失败'}`
        }
      },
    )
  } catch (e: unknown) {
    if (e instanceof Error && e.name !== 'AbortError') {
      followupAnswers.value[entryIndex].answer = `⚠️ ${e.message || '追问失败'}`
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
    // Guard: discard stale response if user already switched to another stock
    if (currentCode.value !== code) return
    const data = res
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

// ---- Score History & Timeline (Phase 3) ----
async function loadScoreHistory(code: string) {
  try {
    const res = await getScoreHistory(code) as any
    scoreHistory.value = res?.items || []
    if (scoreHistory.value.length > 0) {
      nextTick(() => renderScoreTrendChart())
    }
  } catch {
    scoreHistory.value = []
  }
}

async function loadReportTimeline(code: string) {
  try {
    const res = await getReportTimeline(code) as any
    reportTimeline.value = res?.items || []
  } catch {
    reportTimeline.value = []
  }
}

async function loadTimelineReport(id: number) {
  try {
    const res = await getReportDetail(id) as any
    if (res?.report_md) {
      reportContent.value = res.report_md
      reportMeta.value = {
        report_id: res.id,
        created_at: res.created_at,
        tokens_used: res.tokens_used,
        latency_ms: res.latency_ms,
        model: res.model,
      }
    }
  } catch {
    ElMessage.error('加载报告失败')
  }
}

function renderScoreTrendChart() {
  if (!scoreTrendChartRef.value || scoreHistory.value.length === 0) return
  if (scoreTrendChart) {
    scoreTrendChart.dispose()
  }
  scoreTrendChart = echarts.init(scoreTrendChartRef.value)
  // 过滤掉 null 评分的记录
  const validItems = scoreHistory.value.filter(i => i.score != null)
  if (validItems.length === 0) return
  const dates = validItems.map(i => i.date.slice(5))
  const scores = validItems.map(i => i.score)
  scoreTrendChart.setOption({
    tooltip: { trigger: 'axis', formatter: (params: any) => {
      const p = params[0]
      if (!p) return ''
      const item = validItems[p.dataIndex]
      if (!item) return ''
      return `${item.date}<br/>评分: ${item.score}<br/>动作: ${item.action}<br/>${item.reason}`
    }},
    grid: { left: 40, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: dates },
    yAxis: { type: 'value', min: 0, max: 100, splitNumber: 5 },
    series: [{
      type: 'line', data: scores, smooth: true,
      areaStyle: { opacity: 0.15 },
      markLine: {
        silent: true,
        data: [
          { yAxis: 70, lineStyle: { color: '#67c23a', type: 'dashed' }, label: { formatter: '买入线' } },
          { yAxis: 50, lineStyle: { color: '#e6a23c', type: 'dashed' }, label: { formatter: '观望线' } },
        ],
      },
      itemStyle: { color: (params: any) => {
        const v = params.value
        if (v == null) return '#909399'
        return v >= 70 ? '#67c23a' : v >= 50 ? '#e6a23c' : '#f56c6c'
      }},
    }],
  })
}

function handleChartResize() {
  chartInstance?.resize()
  scoreTrendChart?.resize()
}

// ---- Lifecycle ----
onMounted(async () => {
  await ensureMarkdownIt()
  window.addEventListener('resize', handleChartResize)
  loadAttentionList()
  // 加载用户偏好（用于自动语音播报）
  try {
    const pref = await getReportPreference() as any
    if (pref?.voice_enabled) userVoiceEnabled.value = true
  } catch { /* 偏好加载失败不阻塞 */ }
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
  if (abortController.value) {
    abortController.value.abort()
  }
  // 停止语音播报
  if (isSpeaking.value) {
    window.speechSynthesis.cancel()
    isSpeaking.value = false
  }
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
  if (scoreTrendChart) {
    scoreTrendChart.dispose()
    scoreTrendChart = null
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
  padding: 24px 32px;
  max-width: 1100px;
  margin: 0 auto;
}

.search-bar {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 24px;
  padding: 16px 20px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
}

.search-row {
  display: flex;
  gap: 12px;
  align-items: center;
}

.toolbar-row {
  display: flex;
  gap: 8px;
  align-items: center;
  padding-top: 8px;
  border-top: 1px solid var(--el-border-color-extra-light);
}

.search-input {
  width: 360px;
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
  background: linear-gradient(135deg, var(--el-color-primary-light-9), var(--el-fill-color-light));
  border-radius: 10px;
  padding: 18px 24px;
  margin-bottom: 20px;
  border: 1px solid var(--el-color-primary-light-8);
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
  border-radius: 10px;
  padding: 28px 32px;
  max-height: 75vh;
  overflow-y: auto;
  position: relative;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.report-toc {
  position: sticky;
  top: 0;
  float: right;
  width: 160px;
  margin-left: 12px;
  padding: 10px;
  background: var(--el-fill-color-lighter);
  border-radius: 6px;
  font-size: 12px;
  z-index: 10;
}
.toc-title {
  font-weight: 600;
  margin-bottom: 6px;
  color: var(--el-text-color-primary);
}
.toc-item {
  padding: 3px 6px;
  cursor: pointer;
  border-radius: 4px;
  color: var(--el-text-color-regular);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.toc-item:hover {
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
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

.report-body {
  font-size: 14px;
  line-height: 1.8;
  color: var(--el-text-color-regular);
}

.report-body :deep(h3) {
  margin-top: 24px;
  margin-bottom: 10px;
  font-size: 17px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.report-body :deep(h4) {
  margin-top: 20px;
  margin-bottom: 8px;
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  padding-bottom: 4px;
  border-bottom: 1px solid var(--el-border-color-extra-light);
}

.report-body :deep(p) {
  margin: 8px 0;
  line-height: 1.8;
}

.report-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
}

.report-body :deep(th),
.report-body :deep(td) {
  border: 1px solid var(--el-border-color-lighter);
  padding: 10px 14px;
  text-align: left;
  font-size: 13px;
  line-height: 1.6;
}

.report-body :deep(th) {
  background: var(--el-fill-color-light);
  font-weight: 600;
  white-space: nowrap;
}

.report-body :deep(ul),
.report-body :deep(ol) {
  padding-left: 20px;
  margin: 8px 0;
}

.report-body :deep(li) {
  margin: 6px 0;
  line-height: 1.7;
}

.report-body :deep(strong) {
  color: var(--el-text-color-primary);
}

.empty-state {
  margin-top: 100px;
  text-align: center;
}

.empty-state :deep(.el-empty__description) {
  font-size: 15px;
  color: var(--el-text-color-secondary);
}

/* ---- Fallback Data Panel ---- */
.fallback-data {
  margin-top: 16px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 16px;
}

.fallback-data h4 {
  font-size: 14px;
  margin: 0 0 12px;
  color: var(--el-text-color-primary);
}

.fallback-section {
  margin-top: 16px;
}

.fallback-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 24px;
}

.metric-item {
  display: flex;
  gap: 6px;
  font-size: 13px;
}

.metric-label {
  color: var(--el-text-color-secondary);
}

.metric-value {
  font-weight: 500;
}

.metric-value.up { color: #f56c6c; }
.metric-value.down { color: #67c23a; }

.fallback-flow {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.flow-tag {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
}

.flow-tag.up { color: #f56c6c; background: #fef0f0; }
.flow-tag.down { color: #67c23a; background: #f0f9eb; }

/* ---- Feedback Bar ---- */
.feedback-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px dashed var(--el-border-color-lighter);
}

.feedback-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.feedback-done {
  font-size: 12px;
  color: var(--el-color-success);
  margin-left: 4px;
}

.kline-panel {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  margin-bottom: 24px;
  overflow: hidden;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
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

@media (max-width: 768px) {
  .stock-analysis {
    padding: 12px;
  }
  .search-bar {
    padding: 12px;
  }
  .search-row {
    flex-wrap: wrap;
  }
  .toolbar-row {
    flex-wrap: wrap;
  }
  .search-input {
    width: 100%;
  }
  .report-container {
    max-height: none;
    padding: 16px;
  }
  .kline-chart {
    height: 320px;
  }
  .followup-bar {
    flex-direction: column;
  }
  .report-toc {
    display: none;
  }
}

/* Batch analysis panel */
.batch-panel {
  margin: 16px 0;
  padding: 16px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}

.batch-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.batch-title {
  font-size: 15px;
  font-weight: 500;
}

.batch-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}

.batch-card {
  padding: 14px;
  background: var(--el-fill-color-lighter);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  cursor: pointer;
  transition: box-shadow 0.2s, border-color 0.2s;
}

.batch-card:hover {
  border-color: var(--el-color-primary-light-5);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.batch-card--error {
  border-color: var(--el-color-danger-light-5);
  opacity: 0.7;
  cursor: default;
}

.batch-card--loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--el-text-color-secondary);
  min-height: 80px;
  cursor: default;
}

.batch-card-header {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-bottom: 8px;
}

.batch-card-code {
  font-family: monospace;
  font-size: 13px;
  color: var(--el-color-primary);
  font-weight: 600;
}

.batch-card-name {
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.batch-card-rating {
  margin-left: auto;
  font-size: 11px;
  white-space: nowrap;
}
.rating-bullish { color: #67c23a; }
.rating-bearish { color: #f56c6c; }
.rating-neutral { color: #e6a23c; }

.batch-card-summary {
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 5;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.batch-card-meta {
  margin-top: 6px;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  text-align: right;
}

@media (min-width: 1100px) {
  .stock-analysis {
    max-width: 1200px;
  }
  .stock-analysis .main-content {
    display: flex;
    gap: 20px;
    align-items: flex-start;
  }
  .stock-analysis .main-content .kline-panel {
    flex: 0 0 45%;
    position: sticky;
    top: 20px;
    margin-bottom: 0;
  }
  .stock-analysis .main-content .report-container {
    flex: 1;
    max-height: 80vh;
  }
  .stock-analysis .main-content .fallback-panel {
    flex: 1;
  }
}

/* Score trend panel (Phase 3) */
.score-trend-panel {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.panel-title {
  font-size: 14px;
  font-weight: 500;
  margin: 0 0 12px;
}

.score-trend-chart {
  width: 100%;
  height: 220px;
}

/* Report timeline panel (Phase 3) */
.timeline-panel {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.timeline-items {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.timeline-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  background: var(--el-fill-color-lighter);
  transition: background 0.2s;
}

.timeline-item:hover {
  background: var(--el-fill-color);
}

.timeline-item.active {
  background: var(--el-color-primary-light-9);
  border-left: 3px solid var(--el-color-primary);
}

.timeline-date {
  color: var(--el-text-color-regular);
  font-family: monospace;
}

.timeline-model {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.timeline-rating {
  font-size: 12px;
  margin-left: 4px;
}

.timeline-badge {
  margin-left: auto;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--el-color-primary-light-8);
  color: var(--el-color-primary);
}
</style>

<template>
  <div class="report-history">
    <div class="filter-bar">
      <el-input
        v-model="filterCode"
        placeholder="输入股票代码查看全部历史"
        clearable
        style="width: 220px"
        @clear="handleClear"
        @keyup.enter="handleSearch"
      />
      <el-button type="primary" @click="handleSearch">查询</el-button>
      <span class="filter-hint" v-if="!filterCode">
        默认显示最近 1 个月所有报告（最多 100 条）
      </span>
      <span class="filter-hint" v-else>
        查询 {{ filterCode }} 的所有历史报告
      </span>
    </div>

    <el-table :data="historyList" v-loading="loading" stripe empty-text="暂无报告数据">
      <el-table-column prop="code" label="代码" width="90" />
      <el-table-column prop="name" label="名称" width="120" />
      <el-table-column label="评级" width="90">
        <template #default="{ row }">
          <el-tag v-if="row.rating" :type="ratingType(row.rating)" size="small">
            {{ ratingLabel(row.rating) }}
          </el-tag>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column label="护城河" width="90" align="right">
        <template #default="{ row }">
          {{ row.moat_score ?? '-' }}<span v-if="row.moat_score !== null && row.moat_score !== undefined">/5</span>
        </template>
      </el-table-column>
      <el-table-column label="版本" width="80" align="right">
        <template #default="{ row }">v{{ row.report_version || 1 }}</template>
      </el-table-column>
      <el-table-column prop="model" label="模型" width="140" />
      <el-table-column prop="tokens_used" label="Token" width="90" align="right" />
      <el-table-column label="耗时" width="90" align="right">
        <template #default="{ row }">
          {{ row.latency_ms ? (row.latency_ms / 1000).toFixed(1) + 's' : '-' }}
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="生成时间" width="180" />
      <el-table-column label="操作" width="100">
        <template #default="{ row }">
          <el-button link type="primary" @click="viewReport(row)">查看</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pagination-bar" v-if="total > pageSize">
      <el-pagination
        layout="total, prev, pager, next"
        :total="total"
        :page-size="pageSize"
        :current-page="currentPage"
        @current-change="handlePageChange"
      />
    </div>

    <!-- 报告详情弹窗 -->
    <el-dialog v-model="dialogVisible" title="报告详情" width="min(900px, 92vw)" top="5vh">
      <div v-if="detailReport" class="structured-summary">
        <div class="summary-row">
          <el-tag v-if="detailReport.rating" :type="ratingType(detailReport.rating)">
            {{ ratingLabel(detailReport.rating) }}
          </el-tag>
          <span v-if="detailReport.rating_score !== null && detailReport.rating_score !== undefined">
            评分 {{ detailReport.rating_score }}
          </span>
          <span v-if="detailReport.moat_score !== null && detailReport.moat_score !== undefined">
            护城河 {{ detailReport.moat_score }}/5
          </span>
          <span v-if="detailReport.target_price_low || detailReport.target_price_high">
            目标 {{ formatPriceRange(detailReport) }}
          </span>
          <span v-if="detailReport.stop_loss_price">止损 {{ detailReport.stop_loss_price }}</span>
        </div>
        <div class="advice-grid">
          <div v-if="detailReport.short_term_advice" class="advice-item">
            <strong>短期</strong>
            <span>{{ detailReport.short_term_advice }}</span>
          </div>
          <div v-if="detailReport.mid_term_advice" class="advice-item">
            <strong>中期</strong>
            <span>{{ detailReport.mid_term_advice }}</span>
          </div>
          <div v-if="detailReport.long_term_advice" class="advice-item">
            <strong>长期</strong>
            <span>{{ detailReport.long_term_advice }}</span>
          </div>
        </div>
      </div>
      <div class="report-detail-body markdown-body" v-html="detailHtml"></div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onActivated } from 'vue'
import { getReportHistory, getReportDetail } from '@/api/report'
import type { ReportDetail, ReportHistoryItem, ReportRating } from '@/api/report'

const loading = ref(false)
const filterCode = ref('')
const historyList = ref<ReportHistoryItem[]>([])
const currentPage = ref(1)
const pageSize = 20
const total = ref(0)
const dialogVisible = ref(false)
const detailHtml = ref('')
const detailReport = ref<ReportDetail | null>(null)

let mdInstance: { render: (src: string) => string } | null = null

async function ensureMd() {
  if (mdInstance) return mdInstance
  const MarkdownIt = (await import('markdown-it')).default
  mdInstance = new MarkdownIt({ html: false, linkify: true, typographer: true })
  return mdInstance
}

async function loadHistory() {
  loading.value = true
  try {
    const params: { code?: string; limit: number; offset: number; days?: number } = {
      limit: pageSize,
      offset: (currentPage.value - 1) * pageSize,
    }
    if (filterCode.value.trim()) {
      // 按代码查询：不限天数，返回该股所有历史
      params.code = filterCode.value.trim()
      params.days = 0
    } else {
      // 默认：最近 30 天，最多 100 条
      params.limit = Math.min(pageSize, 100)
      params.days = 30
    }
    const res = await getReportHistory(params) as any
    historyList.value = res?.items || []
    total.value = res?.total ?? historyList.value.length
  } catch (e) {
    console.warn('[report-history] 加载历史失败:', e)
    historyList.value = []
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  currentPage.value = 1
  loadHistory()
}

function handleClear() {
  filterCode.value = ''
  currentPage.value = 1
  loadHistory()
}

function handlePageChange(page: number) {
  currentPage.value = page
  loadHistory()
}

async function viewReport(row: ReportHistoryItem) {
  try {
    const md = await ensureMd()
    const res = await getReportDetail(row.id) as any as ReportDetail
    const reportMd = res?.report_md || ''
    detailReport.value = res
    detailHtml.value = md.render(reportMd)
    dialogVisible.value = true
  } catch {
    detailReport.value = null
    detailHtml.value = '<p>加载失败</p>'
    dialogVisible.value = true
  }
}

function ratingLabel(rating?: ReportRating | null) {
  if (rating === 'buy') return '买入'
  if (rating === 'avoid') return '回避'
  if (rating === 'hold') return '观望'
  return '-'
}

function ratingType(rating?: ReportRating | null) {
  if (rating === 'buy') return 'success'
  if (rating === 'avoid') return 'danger'
  if (rating === 'hold') return 'warning'
  return 'info'
}

function formatPriceRange(report: ReportDetail) {
  const low = report.target_price_low
  const high = report.target_price_high
  if (low && high && low !== high) return `${low}-${high}`
  return `${low || high || '-'}`
}

onMounted(() => {
  loadHistory()
})

onActivated(() => {
  loadHistory()
})
</script>

<style scoped>
.report-history {
  padding: 20px;
}
.filter-bar {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 16px;
}
.filter-hint {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.pagination-bar {
  margin-top: 16px;
  display: flex;
  justify-content: center;
}
.report-detail-body {
  max-height: 70vh;
  overflow-y: auto;
  padding: 12px;
}
.structured-summary {
  border-bottom: 1px solid var(--el-border-color-light);
  margin-bottom: 12px;
  padding: 0 4px 12px;
}
.summary-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  color: var(--el-text-color-regular);
  font-size: 13px;
  margin-bottom: 10px;
}
.advice-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 8px;
}
.advice-item {
  border: 1px solid var(--el-border-color-light);
  border-radius: 6px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  line-height: 1.5;
}
.advice-item strong {
  color: var(--el-text-color-primary);
}
.advice-item span {
  color: var(--el-text-color-regular);
}
</style>

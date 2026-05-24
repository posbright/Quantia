<template>
  <div class="report-history">
    <div class="filter-bar">
      <el-input
        v-model="filterCode"
        placeholder="按股票代码筛选"
        clearable
        style="width: 180px"
        @clear="loadHistory"
        @keyup.enter="loadHistory"
      />
      <el-button type="primary" @click="loadHistory">查询</el-button>
    </div>

    <el-table :data="historyList" v-loading="loading" stripe>
      <el-table-column prop="code" label="代码" width="90" />
      <el-table-column prop="name" label="名称" width="120" />
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

    <el-pagination
      v-if="historyList.length > 0"
      class="pagination"
      layout="prev, pager, next"
      :total="total"
      :page-size="pageSize"
      :current-page="currentPage"
      @current-change="handlePageChange"
    />

    <!-- 报告详情弹窗 -->
    <el-dialog v-model="dialogVisible" title="报告详情" width="70%" top="5vh">
      <div class="report-detail-body markdown-body" v-html="detailHtml"></div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getReportHistory, getReportDetail } from '@/api/report'
import type { ReportHistoryItem } from '@/api/report'

const loading = ref(false)
const filterCode = ref('')
const historyList = ref<ReportHistoryItem[]>([])
const currentPage = ref(1)
const pageSize = 20
const total = ref(0)
const dialogVisible = ref(false)
const detailHtml = ref('')

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
    const res = await getReportHistory({
      code: filterCode.value || undefined,
      limit: pageSize,
      offset: (currentPage.value - 1) * pageSize,
    }) as any
    historyList.value = res?.items || res?.data?.items || []
    // Approximate total (API doesn't return count, use items.length heuristic)
    if (historyList.value.length === pageSize) {
      total.value = currentPage.value * pageSize + 1
    } else {
      total.value = (currentPage.value - 1) * pageSize + historyList.value.length
    }
  } catch (e) {
    console.warn('[report-history] 加载历史失败:', e)
    historyList.value = []
  } finally {
    loading.value = false
  }
}

function handlePageChange(page: number) {
  currentPage.value = page
  loadHistory()
}

async function viewReport(row: ReportHistoryItem) {
  try {
    const md = await ensureMd()
    const res = await getReportDetail(row.id) as any
    const reportMd = res?.report_md || res?.data?.report_md || ''
    detailHtml.value = md.render(reportMd)
    dialogVisible.value = true
  } catch {
    detailHtml.value = '<p>加载失败</p>'
    dialogVisible.value = true
  }
}

onMounted(() => {
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
  margin-bottom: 16px;
}
.pagination {
  margin-top: 16px;
  justify-content: center;
}
.report-detail-body {
  max-height: 70vh;
  overflow-y: auto;
  padding: 12px;
}
</style>

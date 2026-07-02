<template>
  <div class="report-compare-page">
    <el-card class="compare-header">
      <div class="compare-inputs">
        <el-autocomplete
          v-model="stockA"
          :fetch-suggestions="handleSearch"
          placeholder="股票A（代码或名称）"
          value-key="code"
          class="stock-input"
          @select="(item: any) => stockA = item.code"
        >
          <template #default="{ item }">
            <span>{{ item.code }} {{ item.name }}</span>
          </template>
        </el-autocomplete>

        <span class="vs-label">VS</span>

        <el-autocomplete
          v-model="stockB"
          :fetch-suggestions="handleSearch"
          placeholder="股票B（代码或名称）"
          value-key="code"
          class="stock-input"
          @select="(item: any) => stockB = item.code"
        >
          <template #default="{ item }">
            <span>{{ item.code }} {{ item.name }}</span>
          </template>
        </el-autocomplete>

        <el-button type="primary" :loading="loading" @click="runCompare" :disabled="!canCompare">
          <el-icon><DataAnalysis /></el-icon>
          开始对比
        </el-button>
      </div>
    </el-card>

    <!-- 对比结果 -->
    <el-card v-if="reportMd || loading" class="compare-result">
      <template #header>
        <div class="result-header">
          <span>对比分析报告</span>
          <div v-if="meta.tokens_used" class="meta-info">
            <el-tag size="small" type="info">{{ meta.model }}</el-tag>
            <el-tag size="small">{{ meta.tokens_used }} tokens</el-tag>
          </div>
        </div>
      </template>

      <div v-if="loading" class="loading-area">
        <el-skeleton :rows="8" animated />
        <p class="loading-text">正在对比分析，请稍候...</p>
      </div>

      <div v-else class="report-content" v-html="renderedHtml"></div>
    </el-card>

    <el-empty v-if="!reportMd && !loading" description="选择两只股票开始对比分析" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onBeforeUnmount } from 'vue'
import { DataAnalysis } from '@element-plus/icons-vue'
import { searchStock, compareReportStream } from '@/api/report'
import MarkdownIt from 'markdown-it'

const md = new MarkdownIt({ html: false, breaks: true, linkify: true })

const stockA = ref('')
const stockB = ref('')
const loading = ref(false)
const reportMd = ref('')
const meta = ref<{ tokens_used?: number; model?: string }>({})
let abortCtrl: AbortController | null = null

const canCompare = computed(() => {
  return stockA.value.length === 6 && stockB.value.length === 6 && stockA.value !== stockB.value
})

const renderedHtml = computed(() => md.render(reportMd.value))

function handleSearch(query: string, cb: (items: any[]) => void) {
  if (!query || query.length < 1) {
    cb([])
    return
  }
  searchStock(query)
    .then((res) => cb((res as any)?.items || []))
    .catch(() => cb([]))
}

async function runCompare() {
  if (!canCompare.value) return
  loading.value = true
  reportMd.value = ''
  meta.value = {}

  abortCtrl = new AbortController()

  try {
    await compareReportStream(
      [stockA.value, stockB.value],
      (ev) => {
        if (ev.type === 'done') {
          reportMd.value = ev.report_md || ''
          meta.value = { tokens_used: ev.tokens_used, model: ev.model }
        } else if (ev.type === 'error') {
          reportMd.value = `> 对比失败: ${ev.msg || '未知错误'}`
        }
      },
      { signal: abortCtrl.signal }
    )
  } catch (err: any) {
    if (err.name !== 'AbortError') {
      reportMd.value = `> 请求失败: ${err.message || err}`
    }
  } finally {
    loading.value = false
    abortCtrl = null
  }
}

onBeforeUnmount(() => {
  if (abortCtrl) {
    abortCtrl.abort()
    abortCtrl = null
  }
})
</script>

<style scoped>
.report-compare-page {
  padding: 20px;
}
.compare-inputs {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.stock-input {
  width: 200px;
}
.vs-label {
  font-size: 18px;
  font-weight: bold;
  color: var(--el-color-primary);
}
.compare-result {
  margin-top: 20px;
}
.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.meta-info {
  display: flex;
  gap: 8px;
}
.loading-area {
  padding: 20px 0;
}
.loading-text {
  text-align: center;
  color: var(--el-text-color-secondary);
  margin-top: 16px;
}
.report-content {
  line-height: 1.8;
}
.report-content :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 12px 0;
}
.report-content :deep(th),
.report-content :deep(td) {
  border: 1px solid var(--el-border-color);
  padding: 8px 12px;
  text-align: left;
}
.report-content :deep(th) {
  background: var(--el-fill-color-light);
  font-weight: 600;
}

/* 移动端：输入框整行、内边距收窄、宽报告表格可横向滚动 */
@media (max-width: 767.98px) {
  .report-compare-page {
    padding: 12px;
  }
  .compare-inputs {
    gap: 8px;
  }
  .stock-input {
    width: 100%;
  }
  .compare-inputs > .el-button {
    width: 100%;
  }
  .vs-label {
    width: 100%;
    text-align: center;
  }
  .report-content :deep(table) {
    display: block;
    overflow-x: auto;
    white-space: nowrap;
  }
}
</style>

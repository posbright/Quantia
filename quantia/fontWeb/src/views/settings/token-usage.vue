<template>
  <div class="token-usage-page">
    <!-- 汇总卡片 -->
    <el-row :gutter="16" class="summary-row">
      <el-col :span="6">
        <el-card shadow="hover" class="summary-card">
          <div class="card-title">今日消耗</div>
          <div class="card-value">{{ formatNumber(summary.today_tokens) }}</div>
          <div class="card-sub">{{ summary.today_calls }} 次调用</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="summary-card">
          <div class="card-title">本月消耗</div>
          <div class="card-value">{{ formatNumber(summary.month_tokens) }}</div>
          <div class="card-sub">tokens</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="summary-card">
          <div class="card-title">小时配额</div>
          <div class="card-value">{{ summary.hour_calls }}/{{ summary.hour_limit_calls }}</div>
          <div class="card-sub">{{ formatNumber(summary.hour_tokens) }}/{{ formatNumber(summary.hour_limit_tokens) }} tokens</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="summary-card">
          <div class="card-title">小时余量</div>
          <div class="card-value">{{ formatNumber(Math.max(0, summary.hour_limit_tokens - summary.hour_tokens)) }}</div>
          <div class="card-sub">tokens 可用</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 图表行 -->
    <el-row :gutter="16" style="margin-top: 16px">
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header><span>按模型分布（近30天）</span></template>
          <div ref="modelChartRef" style="height: 280px"></div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header><span>按场景分布（近30天）</span></template>
          <div ref="sceneChartRef" style="height: 280px"></div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 趋势图 -->
    <el-card shadow="hover" style="margin-top: 16px">
      <template #header><span>每日趋势（近30天）</span></template>
      <div ref="trendChartRef" style="height: 300px"></div>
    </el-card>

    <!-- 功能开关状态 -->
    <el-card shadow="hover" style="margin-top: 16px">
      <template #header><span>功能配额状态</span></template>
      <el-table :data="featureList" stripe size="small">
        <el-table-column prop="feature" label="功能" width="180">
          <template #default="{ row }">{{ featureLabel(row.feature) }}</template>
        </el-table-column>
        <el-table-column prop="enabled" label="启用" width="80" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" size="small" @change="onToggle(row)" />
          </template>
        </el-table-column>
        <el-table-column label="日预算" width="140" align="right">
          <template #default="{ row }">
            <span v-if="row.daily_budget">{{ formatNumber(row.daily_budget) }}</span>
            <span v-else class="text-muted">不限</span>
          </template>
        </el-table-column>
        <el-table-column label="今日已用" width="120" align="right">
          <template #default="{ row }">{{ formatNumber(row.used_today) }}</template>
        </el-table-column>
        <el-table-column label="余量" width="120" align="right">
          <template #default="{ row }">
            <span v-if="row.remaining !== null">{{ formatNumber(row.remaining) }}</span>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="!row.enabled" type="info" size="small">关闭</el-tag>
            <el-tag v-else-if="row.remaining !== null && row.remaining <= 0" type="danger" size="small">超限</el-tag>
            <el-tag v-else type="success" size="small">正常</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" align="center">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="editBudget(row)">编辑预算</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 最近调用 -->
    <el-card shadow="hover" style="margin-top: 16px">
      <template #header><span>最近调用记录</span></template>
      <el-table :data="recentCalls" stripe size="small" max-height="360">
        <el-table-column prop="created_at" label="时间" width="170" />
        <el-table-column prop="scene" label="场景" width="160" />
        <el-table-column prop="model" label="模型" width="180" />
        <el-table-column prop="provider" label="Provider" width="140" />
        <el-table-column label="Tokens" width="100" align="right">
          <template #default="{ row }">{{ row.total_tokens ?? '-' }}</template>
        </el-table-column>
        <el-table-column label="耗时" width="80" align="right">
          <template #default="{ row }">{{ row.latency_ms ? (row.latency_ms / 1000).toFixed(1) + 's' : '-' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="60" align="center">
          <template #default="{ row }">
            <el-tag :type="row.ok ? 'success' : 'danger'" size="small">{{ row.ok ? '✓' : '✗' }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 编辑预算对话框 -->
    <el-dialog v-model="budgetDialogVisible" title="编辑日预算" width="400px">
      <el-form label-width="100px">
        <el-form-item label="功能">
          <span>{{ featureLabel(editingFeature.feature) }}</span>
        </el-form-item>
        <el-form-item label="日预算">
          <el-input-number v-model="editingFeature.daily_budget" :min="0" :step="10000" placeholder="0 表示不限" />
          <span style="margin-left: 8px; color: #909399; font-size: 12px">tokens（0=不限）</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="budgetDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveBudget">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import {
  aiTokenSummary,
  aiTokenByModel,
  aiTokenByScene,
  aiTokenDailyTrend,
  aiTokenFeatureStatus,
  aiTokenRecentCalls,
  aiTokenUpdateFeature,
  type TokenSummary,
  type TokenFeatureStatus,
  type TokenRecentCall,
} from '@/api/ai'

const summary = ref<TokenSummary>({
  today_tokens: 0, today_calls: 0, month_tokens: 0,
  hour_calls: 0, hour_tokens: 0, hour_limit_calls: 60, hour_limit_tokens: 200000,
})
const featureList = ref<TokenFeatureStatus[]>([])
const recentCalls = ref<TokenRecentCall[]>([])

const modelChartRef = ref<HTMLElement>()
const sceneChartRef = ref<HTMLElement>()
const trendChartRef = ref<HTMLElement>()

const budgetDialogVisible = ref(false)
const editingFeature = ref<{ feature: string; daily_budget: number | null }>({ feature: '', daily_budget: null })

const FEATURE_LABELS: Record<string, string> = {
  strategy_gen: '策略生成',
  strategy_refine: '策略优化',
  strategy_repair: '策略修复',
  chat: 'AI 聊天',
  trade_gate: '交易 Gate',
  report_generate: '个股分析报告',
  report_cron_pregenerate: '热门预生成(cron)',
}

function featureLabel(f: string) {
  return FEATURE_LABELS[f] || f
}

function formatNumber(n: number | null | undefined): string {
  if (n == null) return '0'
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
  return String(n)
}

async function loadData() {
  const [summaryRes, featureRes, callsRes] = await Promise.all([
    aiTokenSummary(),
    aiTokenFeatureStatus(),
    aiTokenRecentCalls(50),
  ])
  if (summaryRes.ok && summaryRes.data) summary.value = summaryRes.data
  if (featureRes.ok && featureRes.data) featureList.value = featureRes.data
  if (callsRes.ok && callsRes.data) recentCalls.value = callsRes.data
}

async function loadCharts() {
  const [modelRes, sceneRes, trendRes] = await Promise.all([
    aiTokenByModel(30),
    aiTokenByScene(30),
    aiTokenDailyTrend(30),
  ])

  await nextTick()

  // 模型饼图
  if (modelChartRef.value && modelRes.ok && modelRes.data) {
    const chart = echarts.init(modelChartRef.value)
    chart.setOption({
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      series: [{
        type: 'pie', radius: ['40%', '70%'],
        data: modelRes.data.map(d => ({ name: d.model || 'unknown', value: d.total_tokens })),
      }],
    })
  }

  // 场景饼图
  if (sceneChartRef.value && sceneRes.ok && sceneRes.data) {
    const chart = echarts.init(sceneChartRef.value)
    chart.setOption({
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      series: [{
        type: 'pie', radius: ['40%', '70%'],
        data: sceneRes.data.map(d => ({ name: d.scene || 'unknown', value: d.total_tokens })),
      }],
    })
  }

  // 趋势折线图
  if (trendChartRef.value && trendRes.ok && trendRes.data) {
    const chart = echarts.init(trendChartRef.value)
    const dates = trendRes.data.map(d => d.date)
    chart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: ['Prompt', 'Completion', 'Total'] },
      grid: { left: 60, right: 30, bottom: 30 },
      xAxis: { type: 'category', data: dates },
      yAxis: { type: 'value', name: 'tokens' },
      series: [
        { name: 'Prompt', type: 'line', data: trendRes.data.map(d => d.prompt_tokens), smooth: true },
        { name: 'Completion', type: 'line', data: trendRes.data.map(d => d.completion_tokens), smooth: true },
        { name: 'Total', type: 'line', data: trendRes.data.map(d => d.total_tokens), smooth: true, lineStyle: { width: 2 } },
      ],
    })
  }
}

async function onToggle(row: TokenFeatureStatus) {
  const res = await aiTokenUpdateFeature(row.feature, { enabled: row.enabled })
  if (res.ok) {
    ElMessage.success(`${featureLabel(row.feature)} 已${row.enabled ? '启用' : '禁用'}`)
  } else {
    ElMessage.error(res.error || '操作失败')
    row.enabled = !row.enabled // revert
  }
}

function editBudget(row: TokenFeatureStatus) {
  editingFeature.value = { feature: row.feature, daily_budget: row.daily_budget }
  budgetDialogVisible.value = true
}

async function saveBudget() {
  const { feature, daily_budget } = editingFeature.value
  const res = await aiTokenUpdateFeature(feature, { daily_token_budget: daily_budget || 0 })
  if (res.ok) {
    ElMessage.success('预算已更新')
    budgetDialogVisible.value = false
    await loadData()
  } else {
    ElMessage.error(res.error || '保存失败')
  }
}

onMounted(async () => {
  await loadData()
  await loadCharts()
})
</script>

<style scoped>
.token-usage-page {
  padding: 16px;
}
.summary-row .summary-card {
  text-align: center;
}
.card-title {
  font-size: 13px;
  color: #909399;
  margin-bottom: 8px;
}
.card-value {
  font-size: 24px;
  font-weight: 600;
  color: #303133;
}
.card-sub {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.text-muted {
  color: #c0c4cc;
}
</style>

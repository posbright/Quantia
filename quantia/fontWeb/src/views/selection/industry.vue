<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { getSelectionScoreIndustries, getSelectionScoreList } from '@/api/selectionScore'

type AnyObj = Record<string, any>

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const loadingSummary = ref(false)
const listData = ref<AnyObj[]>([])
const summary = ref<AnyObj | null>(null)
const meta = ref<AnyObj>({})

const pagination = ref({
  page: 1,
  page_size: 40,
  total: 0,
})

const chartRef = ref<HTMLDivElement | null>(null)
let radarChart: echarts.ECharts | null = null

const industryName = computed(() => decodeURIComponent(String(route.params.name || '')).trim())
const date = computed(() => String(route.query.date || '').trim())
const template = computed(() => String(route.query.template || 'balanced').trim())
const sort = computed(() => String(route.query.sort || 'total_score').trim())
const rating = computed(() => String(route.query.rating || '').trim())
const minQuality = computed(() => {
  const raw = String(route.query.min_quality || '').trim()
  if (!raw) return undefined
  const n = Number(raw)
  return Number.isFinite(n) ? n : undefined
})

const scoreDimensions = computed(() => {
  const rows = listData.value
  if (!rows.length) {
    return [
      { name: '估值', value: 0 },
      { name: '盈利', value: 0 },
      { name: '成长', value: 0 },
      { name: '健康', value: 0 },
      { name: '资金', value: 0 },
      { name: '技术', value: 0 },
      { name: '情绪', value: 0 },
    ]
  }

  const avg = (key: string) => {
    const arr = rows.map((x) => Number(x[key])).filter((n) => Number.isFinite(n))
    if (!arr.length) return 0
    return arr.reduce((s, n) => s + n, 0) / arr.length
  }

  return [
    { name: '估值', value: avg('score_valuation') },
    { name: '盈利', value: avg('score_profitability') },
    { name: '成长', value: avg('score_growth') },
    { name: '健康', value: avg('score_health') },
    { name: '资金', value: avg('score_capital') },
    { name: '技术', value: avg('score_technical') },
    { name: '情绪', value: avg('score_sentiment') },
  ]
})

const dimLabelMap: Record<string, string> = {
  valuation: '估值',
  profitability: '盈利',
  growth: '成长',
  health: '健康',
  capital: '资金',
  technical: '技术',
  sentiment: '情绪',
}

const templateWeights = computed(() => {
  const src = meta.value.template_weights || {}
  return Object.entries(src as Record<string, number>)
    .map(([key, val]) => ({ key, label: dimLabelMap[key] || key, value: Number(val || 0) }))
    .filter((x) => Number.isFinite(x.value) && x.value > 0)
    .sort((a, b) => b.value - a.value)
})

const templateFocus = computed(() => templateWeights.value.slice(0, 3))

function toNum(v: any, digits = 2): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '--'
  return n.toFixed(digits)
}

function initRadar() {
  if (!chartRef.value) return
  if (!radarChart) radarChart = echarts.init(chartRef.value)
  const dims = scoreDimensions.value
  radarChart.setOption({
    tooltip: { trigger: 'item' },
    radar: {
      indicator: dims.map((d) => ({ name: d.name, max: 100 })),
      radius: '63%',
      splitNumber: 5,
      axisName: { color: '#334' },
      splitArea: { areaStyle: { color: ['#f8fbff', '#f1f7ff'] } },
    },
    series: [
      {
        type: 'radar',
        data: [{
          value: dims.map((d) => Number(d.value.toFixed(2))),
          name: industryName.value,
          areaStyle: { color: 'rgba(37, 99, 235, 0.22)' },
          lineStyle: { color: '#2563eb', width: 2 },
          itemStyle: { color: '#1d4ed8' },
        }],
      },
    ],
  })
}

async function loadList() {
  if (!industryName.value) return
  loading.value = true
  try {
    const res: AnyObj = await getSelectionScoreList({
      date: date.value || undefined,
      industry: industryName.value,
      rating: rating.value || undefined,
      min_quality: minQuality.value,
      template: template.value || 'balanced',
      sort: sort.value || 'total_score',
      page: pagination.value.page,
      page_size: pagination.value.page_size,
    })
    meta.value = res || {}
    listData.value = Array.isArray(res?.items) ? res.items : []
    pagination.value.total = Number(res?.total || 0)
    if (res?.warning) ElMessage.warning(String(res.warning))
    await nextTick()
    initRadar()
  } catch (e: any) {
    listData.value = []
    pagination.value.total = 0
    ElMessage.error(e?.response?.data?.error || '加载行业详情失败')
  } finally {
    loading.value = false
  }
}

async function loadSummary() {
  if (!industryName.value) return
  loadingSummary.value = true
  try {
    const res: AnyObj = await getSelectionScoreIndustries({
      date: date.value || undefined,
      min_quality: minQuality.value,
      template: template.value || 'balanced',
    })
    const items = Array.isArray(res?.items) ? res.items : []
    summary.value = items.find((x) => String(x.industry || '') === industryName.value) || null
  } catch {
    summary.value = null
  } finally {
    loadingSummary.value = false
  }
}

function toDetail(row: AnyObj) {
  router.push({
    path: `/selection/detail/${encodeURIComponent(String(row.code || ''))}`,
    query: { date: meta.value.date_effective || date.value || undefined },
  })
}

function backToAll() {
  router.push({
    path: '/selection/all',
    query: {
      date: date.value || undefined,
      template: template.value || undefined,
      sort: sort.value || undefined,
      rating: rating.value || undefined,
      min_quality: minQuality.value,
      industry: industryName.value,
    },
  })
}

function onPageChange(page: number) {
  pagination.value.page = page
  loadList()
}

watch(
  () => [industryName.value, date.value, template.value, sort.value, rating.value, minQuality.value],
  () => {
    pagination.value.page = 1
    loadSummary()
    loadList()
  }
)

onMounted(async () => {
  await loadSummary()
  await loadList()
})

onBeforeUnmount(() => {
  if (radarChart) {
    radarChart.dispose()
    radarChart = null
  }
})
</script>

<template>
  <div class="industry-page">
    <section class="hero">
      <div>
        <h1>{{ industryName || '行业详情' }}评分榜</h1>
        <p>日期 {{ meta.date_effective || date || '--' }} · 模板 {{ meta.template_effective || template }} · 股票 {{ pagination.total }}</p>
      </div>
      <el-button @click="backToAll">返回总览</el-button>
    </section>

    <section class="summary-grid">
      <el-card shadow="never" class="summary-card" v-loading="loadingSummary">
        <el-alert
          v-if="meta.template_fallback"
          title="模板已回退到均衡（请求模板未识别）"
          type="warning"
          :closable="false"
          show-icon
          style="margin-bottom: 10px"
        />
        <div class="summary-title">行业概览</div>
        <div class="summary-item">行业均分：{{ toNum(summary?.avg_display_score ?? summary?.avg_total_score) }}</div>
        <div class="summary-item">龙头：{{ summary?.leader_name || summary?.leader_code || '--' }}</div>
        <div class="summary-item">可比占比：{{ toNum((Number(summary?.comparable_ratio || 0) * 100), 1) }}%</div>
        <div class="summary-item" v-if="templateFocus.length">
          模板重点：
          <el-tag v-for="item in templateFocus" :key="item.key" size="small" style="margin-left: 6px">
            {{ item.label }} {{ (item.value * 100).toFixed(1) }}%
          </el-tag>
        </div>
      </el-card>

      <el-card shadow="never" class="radar-card">
        <template #header>
          <div class="radar-title">行业七维雷达（当前筛选页均值）</div>
        </template>
        <div ref="chartRef" class="radar"></div>
      </el-card>
    </section>

    <el-card shadow="never" class="table-card">
      <template #header>
        <div class="table-title">行业内股票列表</div>
      </template>
      <el-table :data="listData" stripe border v-loading="loading" height="580">
        <el-table-column type="index" width="60" label="#" />
        <el-table-column prop="code" label="代码" width="96" />
        <el-table-column prop="name" label="名称" min-width="120">
          <template #default="scope">
            <el-button link type="primary" @click="toDetail(scope.row)">{{ scope.row.name || scope.row.code }}</el-button>
          </template>
        </el-table-column>
        <el-table-column label="展示分" width="110">
          <template #default="scope">{{ toNum(scope.row.display_score) }}</template>
        </el-table-column>
        <el-table-column label="质量分Q" width="110">
          <template #default="scope">{{ toNum(scope.row.quality_score) }}</template>
        </el-table-column>
        <el-table-column prop="rating" label="评级" width="80" />
        <el-table-column prop="industry_rank" label="行业名次" width="108" />
        <el-table-column label="排名变化" width="130">
          <template #default="scope">
            <span>{{ scope.row.rank_change_1d ?? '--' }}</span>
            <el-tag v-if="scope.row.rank_change_comparable === false" size="small" type="info" style="margin-left: 6px">不可比</el-tag>
          </template>
        </el-table-column>
      </el-table>
      <div class="pager-wrap">
        <el-pagination
          background
          layout="prev, pager, next, total"
          :current-page="pagination.page"
          :page-size="pagination.page_size"
          :total="pagination.total"
          @current-change="onPageChange"
        />
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.industry-page {
  display: grid;
  gap: 12px;
  padding: 14px;
  background: linear-gradient(180deg, #f8fbff, #f5f9ff 45%, #f5fbf8);
}

.hero {
  background: linear-gradient(120deg, #0b2b5e, #0f4a89);
  color: #fff;
  border-radius: 14px;
  padding: 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.hero h1 {
  margin: 0;
  font-size: 24px;
}

.hero p {
  margin: 8px 0 0;
  opacity: .9;
}

.summary-grid {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 10px;
}

.summary-card,
.radar-card,
.table-card {
  border-color: #dce8ff;
  border-radius: 12px;
}

.summary-title,
.radar-title,
.table-title {
  font-weight: 700;
  color: #223151;
}

.summary-item {
  margin-top: 8px;
  color: #334766;
}

.radar {
  height: 280px;
}

.pager-wrap {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}

@media (max-width: 960px) {
  .summary-grid {
    grid-template-columns: 1fr;
  }
}
</style>

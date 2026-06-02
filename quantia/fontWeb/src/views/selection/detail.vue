<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { getSelectionScoreDetail } from '@/api/selectionScore'

type AnyObj = Record<string, any>

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const detail = ref<AnyObj | null>(null)
const meta = ref<AnyObj>({})

const chartRef = ref<HTMLDivElement | null>(null)
let radarChart: echarts.ECharts | null = null

const code = computed(() => decodeURIComponent(String(route.params.code || '')).trim())
const date = computed(() => String(route.query.date || '').trim())

const dimensions = computed(() => {
  const item = detail.value || {}
  return [
    { name: '估值', key: 'score_valuation', value: Number(item.score_valuation || 0) },
    { name: '盈利', key: 'score_profitability', value: Number(item.score_profitability || 0) },
    { name: '成长', key: 'score_growth', value: Number(item.score_growth || 0) },
    { name: '健康', key: 'score_health', value: Number(item.score_health || 0) },
    { name: '资金', key: 'score_capital', value: Number(item.score_capital || 0) },
    { name: '技术', key: 'score_technical', value: Number(item.score_technical || 0) },
    { name: '情绪', key: 'score_sentiment', value: Number(item.score_sentiment || 0) },
  ]
})

const topStrengths = computed(() => [...dimensions.value].sort((a, b) => b.value - a.value).slice(0, 3))
const weakSpots = computed(() => [...dimensions.value].sort((a, b) => a.value - b.value).slice(0, 3))

function toNum(v: any, digits = 2): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '--'
  return n.toFixed(digits)
}

function initRadar() {
  if (!chartRef.value) return
  if (!radarChart) radarChart = echarts.init(chartRef.value)
  const dims = dimensions.value
  radarChart.setOption({
    tooltip: { trigger: 'item' },
    radar: {
      indicator: dims.map((d) => ({ name: d.name, max: 100 })),
      radius: '66%',
      splitArea: { areaStyle: { color: ['#f8fbff', '#eef5ff'] } },
      axisName: { color: '#24344f' },
    },
    series: [{
      type: 'radar',
      data: [{
        value: dims.map((d) => Number(d.value.toFixed(2))),
        name: detail.value?.name || code.value,
        areaStyle: { color: 'rgba(14, 165, 164, 0.22)' },
        lineStyle: { color: '#0f766e', width: 2 },
        itemStyle: { color: '#0d9488' },
      }],
    }],
  })
}

async function loadDetail() {
  if (!code.value) return
  loading.value = true
  try {
    const res: AnyObj = await getSelectionScoreDetail({
      code: code.value,
      date: date.value || undefined,
    })
    meta.value = res || {}
    detail.value = res?.item || null
    if (!detail.value) {
      ElMessage.warning('未查询到该股票评分详情')
    }
    await nextTick()
    initRadar()
  } catch (e: any) {
    detail.value = null
    ElMessage.error(e?.response?.data?.error || '加载个股详情失败')
  } finally {
    loading.value = false
  }
}

function backToAll() {
  router.push('/selection/all')
}

watch(() => [code.value, date.value], loadDetail)
onMounted(loadDetail)

onBeforeUnmount(() => {
  if (radarChart) {
    radarChart.dispose()
    radarChart = null
  }
})
</script>

<template>
  <div class="detail-page" v-loading="loading">
    <section class="hero" v-if="detail">
      <div>
        <h1>{{ detail.name || code }}（{{ detail.code || code }}）</h1>
        <p>
          评分日 {{ meta.date_effective || detail.date || date || '--' }} · 评级 {{ detail.rating || '--' }}
          · 行业 {{ detail.industry || '--' }}
        </p>
      </div>
      <el-button @click="backToAll">返回总览</el-button>
    </section>

    <template v-if="detail">
      <section class="kpi-row">
        <article class="kpi-card">
          <div class="kpi-label">展示分</div>
          <div class="kpi-value">{{ toNum(detail.display_score || detail.total_score) }}</div>
        </article>
        <article class="kpi-card">
          <div class="kpi-label">质量分 Q</div>
          <div class="kpi-value">{{ toNum(detail.quality_score) }}</div>
        </article>
        <article class="kpi-card">
          <div class="kpi-label">行业相对分 R</div>
          <div class="kpi-value">{{ toNum(detail.industry_score) }}</div>
        </article>
        <article class="kpi-card">
          <div class="kpi-label">行业排名</div>
          <div class="kpi-value">{{ detail.industry_rank || '--' }}/{{ detail.industry_total || '--' }}</div>
        </article>
      </section>

      <section class="main-grid">
        <el-card shadow="never" class="radar-card">
          <template #header>
            <div class="panel-title">七维雷达</div>
          </template>
          <div ref="chartRef" class="radar"></div>
        </el-card>

        <el-card shadow="never" class="reason-card">
          <template #header>
            <div class="panel-title">分数归因</div>
          </template>
          <div class="reason-block">
            <h4>优势维度</h4>
            <ul>
              <li v-for="d in topStrengths" :key="d.key">{{ d.name }}：{{ toNum(d.value) }}</li>
            </ul>
          </div>
          <div class="reason-block">
            <h4>短板维度</h4>
            <ul>
              <li v-for="d in weakSpots" :key="d.key">{{ d.name }}：{{ toNum(d.value) }}</li>
            </ul>
          </div>
        </el-card>
      </section>

      <section class="tag-grid">
        <el-card shadow="never" class="tag-card">
          <template #header><div class="panel-title">亮点标签</div></template>
          <div class="tag-wrap" v-if="Array.isArray(detail.tags) && detail.tags.length">
            <el-tag v-for="tag in detail.tags" :key="String(tag)" type="success">{{ tag }}</el-tag>
          </div>
          <div class="empty-text" v-else>暂无亮点标签</div>
        </el-card>

        <el-card shadow="never" class="tag-card">
          <template #header><div class="panel-title">风险标签</div></template>
          <div class="tag-wrap" v-if="Array.isArray(detail.risk_flags) && detail.risk_flags.length">
            <el-tag v-for="risk in detail.risk_flags" :key="String(risk)" type="warning">{{ risk }}</el-tag>
          </div>
          <div class="empty-text" v-else>暂无风险标签</div>
        </el-card>
      </section>
    </template>

    <el-empty v-else description="暂无详情数据" />
  </div>
</template>

<style scoped>
.detail-page {
  display: grid;
  gap: 12px;
  padding: 14px;
  background: linear-gradient(170deg, #f7fbff, #f1f8ff 55%, #f5fbf7);
}

.hero {
  background: linear-gradient(120deg, #0b2b5e, #1d4ed8, #0f766e);
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
  opacity: 0.92;
}

.kpi-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.kpi-card,
.radar-card,
.reason-card,
.tag-card {
  border-radius: 12px;
  border-color: #dce8ff;
}

.kpi-card {
  background: #fff;
  padding: 12px;
}

.kpi-label {
  font-size: 12px;
  color: #64748b;
}

.kpi-value {
  margin-top: 6px;
  color: #0f1f3d;
  font-weight: 700;
  font-size: 24px;
}

.panel-title {
  font-weight: 700;
  color: #223151;
}

.main-grid {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 10px;
}

.radar {
  height: 320px;
}

.reason-block + .reason-block {
  margin-top: 10px;
}

.reason-block h4 {
  margin: 0 0 8px;
  color: #1f2f4d;
}

.reason-block ul {
  margin: 0;
  padding-left: 20px;
  color: #334766;
}

.tag-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.tag-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.empty-text {
  color: #6b7e99;
}

@media (max-width: 960px) {
  .kpi-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .main-grid,
  .tag-grid {
    grid-template-columns: 1fr;
  }
}
</style>

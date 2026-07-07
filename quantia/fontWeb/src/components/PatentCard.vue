<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick, shallowRef } from 'vue'
import * as echarts from 'echarts'
import { getStockPatents, getStockPatentsCompare, type PatentData, type PatentCompareItem } from '@/api/stock'

const props = defineProps<{ code: string }>()
const emit = defineEmits<{ (e: 'loaded', hasData: boolean): void }>()

const data = ref<PatentData | null>(null)
const reason = ref<string>('')
const loading = ref(false)
const compareTop = ref<PatentCompareItem[]>([])
const industry = ref<string | null>(null)
const rank = ref<number | null>(null)

const trendChartRef = ref<HTMLDivElement>()
const ipcChartRef = ref<HTMLDivElement>()
const trendChart = shallowRef<echarts.ECharts | null>(null)
const ipcChart = shallowRef<echarts.ECharts | null>(null)

const qualityScore = computed(() => data.value?.patent_quality_score ?? null)
const qualityLevel = computed(() => {
  const s = qualityScore.value
  if (s == null) return { text: '暂缺', color: '#909399' }
  if (s >= 80) return { text: '强', color: '#67c23a' }
  if (s >= 50) return { text: '中', color: '#e6a23c' }
  if (s >= 20) return { text: '弱', color: '#f56c6c' }
  return { text: '无', color: '#909399' }
})
const directionIcon = computed(() => {
  const d = data.value?.trend_direction
  if (d === 'accelerating') return { icon: '↑', text: '加速', color: '#67c23a' }
  if (d === 'stable') return { icon: '→', text: '稳定', color: '#409eff' }
  if (d === 'decelerating') return { icon: '↘', text: '减速', color: '#e6a23c' }
  if (d === 'declining') return { icon: '↓', text: '下滑', color: '#f56c6c' }
  return { icon: '—', text: '—', color: '#909399' }
})

const fmtNum = (v: number | null | undefined, digits = 0): string => {
  if (v == null || isNaN(v as number)) return '-'
  return Number(v).toFixed(digits)
}
const fmtPct = (v: number | null | undefined): string => {
  if (v == null || isNaN(v as number)) return '-'
  return Number(v).toFixed(2) + '%'
}

const loadPatents = async () => {
  if (!props.code) return
  loading.value = true
  data.value = null
  reason.value = ''
  compareTop.value = []
  rank.value = null
  industry.value = null
  try {
    const res = await getStockPatents(props.code) as any
    if (res?.data) {
      data.value = res.data
    } else if (res?.reason) {
      reason.value = res.reason
    }
    // 行业对标 (失败不阻塞主卡片)
    try {
      const cmp = await getStockPatentsCompare(props.code) as any
      if (cmp) {
        compareTop.value = cmp.top || []
        industry.value = cmp.industry || null
        rank.value = cmp.rank ?? null
      }
    } catch (e) {
      // ignore
    }
    await nextTick()
    renderTrendChart()
    renderIpcChart()
  } catch (e) {
    data.value = null
    reason.value = '加载失败'
  } finally {
    loading.value = false
    emit('loaded', !!data.value)
  }
}

const renderTrendChart = () => {
  if (!trendChartRef.value) return
  const trend = data.value?.trend_5y || []
  if (!trend.length) {
    trendChart.value?.dispose()
    trendChart.value = null
    return
  }
  if (!trendChart.value) {
    trendChart.value = echarts.init(trendChartRef.value)
  }
  const years = trend.map(t => String(t.year))
  const totals = trend.map(t => t.count ?? 0)
  trendChart.value.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 16, top: 32, bottom: 28 },
    xAxis: { type: 'category', data: years },
    yAxis: { type: 'value', name: '专利数' },
    series: [{
      name: '专利申请数',
      type: 'bar',
      data: totals,
      itemStyle: { color: '#409eff' },
      label: { show: true, position: 'top' },
    }],
  })
}

const renderIpcChart = () => {
  if (!ipcChartRef.value) return
  const dist = data.value?.ipc_distribution
  if (!dist || Object.keys(dist).length === 0) {
    ipcChart.value?.dispose()
    ipcChart.value = null
    return
  }
  if (!ipcChart.value) {
    ipcChart.value = echarts.init(ipcChartRef.value)
  }
  const entries = Object.entries(dist).map(([name, value]) => ({ name, value: value as number }))
  ipcChart.value.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { type: 'scroll', orient: 'horizontal', bottom: 0 },
    series: [{
      name: 'IPC 分布',
      type: 'pie',
      radius: ['38%', '68%'],
      center: ['50%', '46%'],
      data: entries,
      label: { formatter: '{b}: {c}' },
    }],
  })
}

const handleResize = () => {
  trendChart.value?.resize()
  ipcChart.value?.resize()
}

watch(() => props.code, () => loadPatents())

onMounted(() => {
  loadPatents()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  trendChart.value?.dispose()
  ipcChart.value?.dispose()
})
</script>

<template>
  <div class="patent-card" v-loading="loading">
    <div class="patent-header">
      <span class="patent-title">知识产权 / 护城河</span>
      <span v-if="data" class="patent-meta">
        <el-tag size="small" :type="data.data_source === 'annual_report' ? 'success' : 'info'">
          {{ data.data_source === 'annual_report' ? '年报' : (data.data_source || '未知') }}
        </el-tag>
        <span class="updated">更新于 {{ data.updated_at || '-' }}</span>
      </span>
    </div>

    <template v-if="data">
      <div class="patent-grid">
        <div class="patent-item">
          <div class="patent-label">含金量评分</div>
          <div class="patent-value">
            <el-progress :percentage="qualityScore || 0" :stroke-width="14"
              :color="qualityLevel.color" :show-text="false" />
            <span class="score-text">{{ qualityScore ?? '-' }}
              <small :style="{ color: qualityLevel.color }">({{ qualityLevel.text }})</small>
            </span>
          </div>
        </div>
        <div class="patent-item">
          <div class="patent-label">专利总数（{{ data.year ?? '-' }}）</div>
          <div class="patent-value big">{{ fmtNum(data.total_patents) }}</div>
        </div>
        <div class="patent-item">
          <div class="patent-label">发明专利</div>
          <div class="patent-value">
            {{ fmtNum(data.invention_patents) }}
            <small>({{ fmtPct(data.invention_ratio) }})</small>
          </div>
        </div>
        <div class="patent-item">
          <div class="patent-label">实用 / 外观</div>
          <div class="patent-value">
            {{ fmtNum(data.utility_patents) }} / {{ fmtNum(data.design_patents) }}
          </div>
        </div>
        <div class="patent-item">
          <div class="patent-label">5年CAGR</div>
          <div class="patent-value">
            {{ fmtPct(data.trend_5y_cagr) }}
            <small :style="{ color: directionIcon.color }">
              {{ directionIcon.icon }} {{ directionIcon.text }}
            </small>
          </div>
        </div>
        <div class="patent-item">
          <div class="patent-label">主IPC / 技术领域</div>
          <div class="patent-value">
            <el-tag v-if="data.ipc_primary" size="small">{{ data.ipc_primary }}</el-tag>
            <span class="tech">{{ data.ipc_primary_desc || data.tech_domain || '-' }}</span>
          </div>
        </div>
        <div class="patent-item">
          <div class="patent-label">研发人员</div>
          <div class="patent-value">
            {{ fmtNum(data.rd_staff_count) }}
            <small v-if="data.rd_staff_ratio != null">({{ fmtPct(data.rd_staff_ratio) }})</small>
          </div>
        </div>
        <div class="patent-item">
          <div class="patent-label">PCT 国际</div>
          <div class="patent-value">{{ fmtNum(data.pct_international) }}</div>
        </div>
        <div v-if="industry" class="patent-item patent-item-full">
          <div class="patent-label">行业对标（{{ industry }}）</div>
          <div class="patent-value">
            <span v-if="rank">第 <b>{{ rank }}</b> 名</span>
            <span v-else class="muted">未上榜</span>
          </div>
        </div>
      </div>

      <div class="patent-charts">
        <div class="chart-block">
          <div class="chart-subtitle">近5年专利申请趋势</div>
          <div ref="trendChartRef" class="patent-chart"></div>
        </div>
        <div class="chart-block" v-if="data.ipc_distribution && Object.keys(data.ipc_distribution).length">
          <div class="chart-subtitle">
            IPC 技术分布
            <el-tag v-if="data.ipc_estimated" size="small" type="warning" effect="plain" class="ipc-est-tag">
              按行业估算{{ data.ipc_estimate_industry ? '·' + data.ipc_estimate_industry : '' }}
            </el-tag>
          </div>
          <div ref="ipcChartRef" class="patent-chart"></div>
        </div>
      </div>

      <div v-if="data.key_tech_desc" class="patent-desc">
        <div class="chart-subtitle">核心技术描述</div>
        <p>{{ data.key_tech_desc }}</p>
      </div>

      <div v-if="compareTop.length" class="patent-top">
        <div class="chart-subtitle">行业 TOP（按专利总数）</div>
        <el-table :data="compareTop" size="small" stripe>
          <el-table-column type="index" label="#" width="48" />
          <el-table-column prop="code" label="代码" width="80" />
          <el-table-column prop="name" label="名称" min-width="100" />
          <el-table-column prop="total_patents" label="专利数" width="80" align="right" />
          <el-table-column prop="invention_patents" label="发明" width="70" align="right" />
          <el-table-column prop="patent_quality_score" label="评分" width="70" align="right" />
        </el-table>
      </div>
    </template>

    <el-empty v-else-if="!loading" :description="reason || '暂无专利数据'" :image-size="60" />
  </div>
</template>

<style lang="scss" scoped>
.patent-card {
  .patent-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
    .patent-title {
      font-size: 15px;
      font-weight: 600;
    }
    .patent-meta {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 12px;
      color: #909399;
      .updated { font-size: 12px; }
    }
  }
  .patent-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 10px 16px;
    margin-bottom: 16px;
    .patent-item {
      display: flex;
      flex-direction: column;
      gap: 2px;
      &.patent-item-full { grid-column: 1 / -1; }
      .patent-label {
        font-size: 12px;
        color: #909399;
      }
      .patent-value {
        font-size: 14px;
        color: #303133;
        display: flex;
        align-items: center;
        gap: 6px;
        flex-wrap: wrap;
        &.big {
          font-size: 18px;
          font-weight: 600;
          color: #409eff;
        }
        .score-text {
          font-weight: 600;
          margin-left: 8px;
          small { font-weight: normal; margin-left: 4px; }
        }
        .tech { color: #606266; }
        .muted { color: #c0c4cc; }
        small { color: #909399; font-size: 12px; }
      }
    }
  }
  .patent-charts {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    @media (max-width: 768px) {
      grid-template-columns: 1fr;
    }
    .chart-block {
      .patent-chart {
        width: 100%;
        height: 240px;
      }
    }
  }
  .chart-subtitle {
    font-size: 13px;
    color: #606266;
    margin: 8px 0 4px;
    font-weight: 500;
  }
  .ipc-est-tag {
    margin-left: 6px;
    vertical-align: middle;
  }
  .patent-desc {
    margin-top: 12px;
    p {
      font-size: 13px;
      color: #606266;
      line-height: 1.6;
      margin: 4px 0 0;
    }
  }
  .patent-top {
    margin-top: 12px;
  }
}
</style>

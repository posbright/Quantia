<template>
  <div class="fct">
    <div class="fct-tip">
      在「{{ fundType }}」类型内选择 2–3 只基金，叠加同类五维雷达并对比关键指标。维度分越高代表在同类中越优。
    </div>

    <div class="fct-picker">
      <el-select
        v-model="selected"
        multiple
        filterable
        :multiple-limit="3"
        collapse-tags
        collapse-tags-tooltip
        placeholder="搜索并选择基金（最多 3 只）"
        style="width: 420px"
        :loading="optionsLoading"
        @change="onSelectChange"
      >
        <el-option
          v-for="o in options"
          :key="o.code"
          :label="`${o.name}（${o.code}）`"
          :value="o.code"
        />
      </el-select>
      <el-button size="small" @click="clearAll" :disabled="!selected.length">清空</el-button>
    </div>

    <div v-if="!selected.length" class="fct-empty">请选择至少 2 只基金开始对比</div>

    <template v-else>
      <div v-show="hasData" ref="radarRef" v-loading="loading" class="fct-radar"></div>

      <table v-if="hasData" class="fct-table">
        <thead>
          <tr>
            <th>维度</th>
            <th v-for="f in compares" :key="f.code">{{ f.name || f.code }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="dim in dimLabels" :key="dim">
            <td class="fct-dim">{{ dim }}</td>
            <td
              v-for="f in compares"
              :key="f.code + dim"
              :class="{ 'fct-best': isBest(dim, f.code) }"
            >{{ dimValue(f, dim) }}</td>
          </tr>
        </tbody>
      </table>

      <div v-if="!hasData && !loading" class="fct-empty">所选基金暂无同类对比数据</div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import {
  getFundRank,
  getFundPeerCompare,
  type FundRankResult,
  type FundPeerCompare,
} from '@/api/fund'

const props = defineProps<{ fundType: string; period: string }>()

const options = ref<{ code: string; name: string }[]>([])
const optionsLoading = ref(false)
const selected = ref<string[]>([])
const compares = ref<FundPeerCompare[]>([])
const loading = ref(false)

const radarRef = ref<HTMLElement | null>(null)
let radarChart: echarts.ECharts | null = null

// A 股惯例配色 + 区分多只基金
const SERIES_COLORS = ['#d23b3b', '#2563eb', '#f59e0b']

const hasData = computed(() => compares.value.some((c) => c.dims && c.dims.length))
const dimLabels = computed(() => {
  const first = compares.value.find((c) => c.dims && c.dims.length)
  return first ? first.dims.map((d) => d.label) : []
})

function dimValue(f: FundPeerCompare, label: string): string {
  const d = f.dims?.find((x) => x.label === label)
  return d ? d.value.toFixed(0) : '—'
}

function isBest(label: string, code: string): boolean {
  let bestCode = ''
  let bestVal = -Infinity
  for (const f of compares.value) {
    const d = f.dims?.find((x) => x.label === label)
    if (d && d.value > bestVal) {
      bestVal = d.value
      bestCode = f.code
    }
  }
  return bestCode === code && compares.value.length > 1
}

async function loadOptions() {
  optionsLoading.value = true
  try {
    const res = (await getFundRank({
      fund_type: props.fundType,
      period: props.period,
      limit: 200,
    })) as unknown as FundRankResult
    options.value = (res.items || []).map((i) => ({ code: i.code, name: i.name }))
  } catch {
    options.value = []
  } finally {
    optionsLoading.value = false
  }
}

async function renderRadar() {
  if (!hasData.value || !radarRef.value) return
  await nextTick()
  if (!radarChart) radarChart = echarts.init(radarRef.value)
  const indicator = dimLabels.value.map((name) => ({ name, max: 100 }))
  const series = compares.value
    .filter((c) => c.dims && c.dims.length)
    .map((c) => ({
      value: c.dims.map((d) => d.value),
      name: c.name || c.code,
    }))
  radarChart.setOption({
    color: SERIES_COLORS,
    tooltip: {},
    legend: { data: series.map((s) => s.name), bottom: 0, textStyle: { fontSize: 11 } },
    radar: {
      indicator,
      radius: '62%',
      center: ['50%', '48%'],
      splitNumber: 4,
      axisName: { fontSize: 11, color: '#606266' },
    },
    series: [{ type: 'radar', data: series, areaStyle: { opacity: 0.08 } }],
  })
  radarChart.resize()
}

async function loadCompares() {
  if (selected.value.length < 1) {
    compares.value = []
    return
  }
  loading.value = true
  try {
    const results = await Promise.allSettled(
      selected.value.map((code) => getFundPeerCompare(code) as unknown as Promise<FundPeerCompare>),
    )
    compares.value = results
      .filter((r): r is PromiseFulfilledResult<FundPeerCompare> => r.status === 'fulfilled')
      .map((r) => r.value)
    await renderRadar()
  } catch {
    ElMessage.error('加载对比数据失败')
  } finally {
    loading.value = false
  }
}

function onSelectChange() {
  void loadCompares()
}

function clearAll() {
  selected.value = []
  compares.value = []
}

// 类型 / 周期变化：重置已选并重新拉候选池
watch(
  () => [props.fundType, props.period] as const,
  () => {
    selected.value = []
    compares.value = []
    void loadOptions()
  },
  { immediate: true },
)
</script>

<style scoped>
.fct {
  padding: 4px 2px;
}
.fct-tip {
  font-size: 13px;
  color: #606266;
  background: #f7f9fc;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 8px 12px;
  margin-bottom: 12px;
}
.fct-picker {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}
.fct-empty {
  color: #909399;
  font-size: 13px;
  text-align: center;
  padding: 32px 0;
}
.fct-radar {
  width: 100%;
  height: 340px;
}
.fct-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  margin-top: 12px;
}
.fct-table th,
.fct-table td {
  padding: 8px 10px;
  border-bottom: 1px solid #f0f2f5;
  text-align: center;
}
.fct-table th {
  color: #909399;
  font-weight: 500;
  background: #fafafa;
}
.fct-dim {
  color: #606266;
  font-weight: 500;
}
.fct-best {
  color: #d23b3b;
  font-weight: 700;
}
</style>

<template>
  <div class="verify-fusion">
    <!-- 配置器 -->
    <el-card shadow="never">
      <template #header><span>策略融合配置</span></template>
      <el-row :gutter="24">
        <el-col :span="6">
          <div class="config-label">融合模式</div>
          <el-radio-group v-model="fusionMode" style="margin-top: 8px">
            <el-radio value="intersection">信号交集</el-radio>
            <el-radio value="union">信号并集</el-radio>
            <el-radio value="vote">投票制</el-radio>
            <el-radio value="rotation">环境轮动</el-radio>
          </el-radio-group>
          <el-input-number
            v-if="fusionMode === 'vote'"
            v-model="voteThreshold"
            :min="2"
            :max="selectedStrategies.length"
            size="small"
            style="margin-top: 8px; width: 120px"
          />
        </el-col>
        <el-col :span="10">
          <div class="config-label">参与策略（2-6个）</div>
          <el-checkbox-group v-model="selectedStrategies" style="margin-top: 8px">
            <el-checkbox v-for="s in strategyOptions" :key="s.value" :value="s.value" :label="s.label" />
          </el-checkbox-group>
        </el-col>
        <el-col :span="8">
          <div class="config-label">日期范围 & 持仓天数</div>
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            range-separator="至"
            start-placeholder="开始"
            end-placeholder="结束"
            value-format="YYYY-MM-DD"
            style="margin-top: 8px; width: 100%"
          />
          <el-select v-model="holdingDays" style="margin-top: 8px; width: 120px">
            <el-option v-for="d in [1,3,5,7,10,15,20,30]" :key="d" :label="`${d}天`" :value="d" />
          </el-select>
          <el-button type="primary" :loading="loading" style="margin-top: 8px; margin-left: 12px" @click="runFusion">
            运行融合
          </el-button>
        </el-col>
      </el-row>
    </el-card>

    <!-- KPI 卡片 -->
    <el-row v-if="fusionResult" :gutter="16" style="margin-top: 16px">
      <el-col :span="4">
        <div class="kpi-card">
          <div class="kpi-value" :class="rateClass(fusionResult.avg_return)">{{ fmt(fusionResult.avg_return) }}%</div>
          <div class="kpi-label">融合平均收益</div>
        </div>
      </el-col>
      <el-col :span="4">
        <div class="kpi-card">
          <div class="kpi-value">{{ fmt(fusionResult.win_rate) }}%</div>
          <div class="kpi-label">融合胜率</div>
        </div>
      </el-col>
      <el-col :span="4">
        <div class="kpi-card">
          <div class="kpi-value" :class="sharpeClass(fusionResult.sharpe)">{{ fmt(fusionResult.sharpe) }}</div>
          <div class="kpi-label">融合夏普</div>
        </div>
      </el-col>
      <el-col :span="4">
        <div class="kpi-card">
          <div class="kpi-value">{{ fusionResult.signal_count }}</div>
          <div class="kpi-label">融合信号数</div>
        </div>
      </el-col>
      <el-col :span="4">
        <div class="kpi-card">
          <div class="kpi-value">{{ fmt(fusionResult.daily_signal_avg) }}</div>
          <div class="kpi-label">日均信号</div>
        </div>
      </el-col>
      <el-col v-if="improvement.sharpe_vs_best" :span="4">
        <div class="kpi-card">
          <div class="kpi-value text-blue">{{ improvement.sharpe_vs_best }}</div>
          <div class="kpi-label">夏普提升</div>
        </div>
      </el-col>
    </el-row>

    <!-- 对比表 -->
    <el-card v-if="individualResults && Object.keys(individualResults).length > 0" shadow="never" style="margin-top: 16px">
      <template #header><span>融合 vs 各策略对比</span></template>
      <div class="table-wrapper">
        <table class="cmp-table">
          <thead>
            <tr><th>策略</th><th>平均收益%</th><th>胜率%</th><th>夏普</th><th>信号数</th></tr>
          </thead>
          <tbody>
            <tr class="best-row">
              <td><strong>🔗 融合结果</strong></td>
              <td :class="rateClass(fusionResult?.avg_return)">{{ fmt(fusionResult?.avg_return) }}</td>
              <td>{{ fmt(fusionResult?.win_rate) }}</td>
              <td :class="sharpeClass(fusionResult?.sharpe)">{{ fmt(fusionResult?.sharpe) }}</td>
              <td>{{ fusionResult?.signal_count }}</td>
            </tr>
            <tr v-for="(data, key) in individualResults" :key="key">
              <td>{{ data.cn || key }}</td>
              <td :class="rateClass(data.avg_return)">{{ fmt(data.avg_return) }}</td>
              <td>{{ fmt(data.win_rate) }}</td>
              <td>{{ fmt(data.sharpe) }}</td>
              <td>{{ data.signal_count }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </el-card>

    <el-empty v-if="!loading && !fusionResult && hasQueried" description="暂无融合结果" />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { runFusion as apiFusion } from '@/api/verify'

const fusionMode = ref<'intersection' | 'union' | 'vote'>('intersection')
const voteThreshold = ref(2)
const selectedStrategies = ref<string[]>([])
const dateRange = ref<[string, string]>(['2025-01-01', '2025-12-31'])
const holdingDays = ref(5)
const loading = ref(false)
const hasQueried = ref(false)

const fusionResult = ref<any>(null)
const individualResults = ref<Record<string, any>>({})
const improvement = ref<any>({})

const strategyOptions = [
  { value: 'keep_increasing', label: '放量上涨' },
  { value: 'parking_apron', label: '停机坪' },
  { value: 'backtrace_ma250', label: '回踩年线' },
  { value: 'breakthrough_platform', label: '突破平台' },
  { value: 'low_atr', label: '低ATR成长' },
  { value: 'climax_limitdown', label: '放量跌停' },
  { value: 'high_tight_flag', label: '高而窄旗形' },
  { value: 'low_backtrace_increase', label: '无大幅回撤' },
  { value: 'turtle_trade', label: '海龟交易' },
  { value: 'enter_strategy', label: '企业战略' },
  { value: 'share_holder_increase', label: '股东增持' },
  { value: 'roaming_loong', label: '游龙' },
]

function fmt(v: number | null | undefined): string {
  if (v === null || v === undefined) return '--'
  return Number(v).toFixed(2)
}
function rateClass(v: number | null | undefined): string {
  if (v === null || v === undefined) return ''
  return v > 0 ? 'text-red' : v < 0 ? 'text-green' : ''
}
function sharpeClass(v: number | null | undefined): string {
  if (v === null || v === undefined) return ''
  return v !== null && v !== undefined && v >= 2 ? 'text-red font-bold' : v !== null && v !== undefined && v < 0 ? 'text-green' : ''
}

async function runFusion() {
  if (selectedStrategies.value.length < 2) {
    ElMessage.warning('请至少选择 2 个策略')
    return
  }
  if (selectedStrategies.value.length > 6) {
    ElMessage.warning('最多选择 6 个策略')
    return
  }
  if (!dateRange.value?.[0]) {
    ElMessage.warning('请选择日期范围')
    return
  }

  loading.value = true
  hasQueried.value = true
  fusionResult.value = null
  individualResults.value = {}
  improvement.value = {}

  try {
    const res: any = await apiFusion({
      strategy_names: selectedStrategies.value,
      mode: fusionMode.value,
      vote_threshold: voteThreshold.value,
      start_date: dateRange.value[0],
      end_date: dateRange.value[1],
      holding_days: holdingDays.value,
    })
    fusionResult.value = res.fusion_result
    individualResults.value = res.individual_results || {}
    improvement.value = res.improvement || {}
  } catch (e: any) {
    ElMessage.error(e.message || '融合请求失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.verify-fusion { padding: 16px; }
.config-label { font-weight: 600; font-size: 13px; color: #595959; }
.table-wrapper { overflow-x: auto; }
.cmp-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.cmp-table th, .cmp-table td { border: 1px solid #ebeef5; padding: 8px 12px; text-align: center; white-space: nowrap; }
.cmp-table th { background: #fafafa; font-weight: 600; }
.best-row { background: #fff7e6; }
.kpi-card { text-align: center; padding: 16px; background: #fafafa; border-radius: 8px; }
.kpi-value { font-size: 22px; font-weight: 700; }
.kpi-label { font-size: 12px; color: #8c8c8c; margin-top: 4px; }
.text-red { color: #cf1322; }
.text-green { color: #389e0d; }
.text-blue { color: #1890ff; }
.font-bold { font-weight: 700; }
</style>

<script setup lang="ts">
import { ref, onMounted, onActivated } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getBacktestConfig, runBacktest, runBatchBacktest } from '@/api/stock'

const route = useRoute()
const router = useRouter()

// 配置数据
const periods = ref<any[]>([])
const strategies = ref<any[]>([])

// 表单
const backtestForm = ref({
  mode: 'single',    // single: 单股回测, batch: 批量回测
  code: '',
  strategy: '',
  period: '1m',
  start_date: '',
  checkpoints: [1, 3, 5, 10, 20] as any[],
  horizons: [1, 3, 5, 10, 20] as any[],
  success_days: 5,
})

// 结果
const loading = ref(false)
const singleResult = ref<any>(null)
const batchResult = ref<any>(null)

// 加载配置
onMounted(async () => {
  try {
    const config: any = await getBacktestConfig()
    if (config) {
      periods.value = config.periods || []
      strategies.value = config.strategies || []

      const defaults = config.default_horizons || [1, 3, 5, 10, 20]
      if (Array.isArray(defaults) && defaults.length) {
        backtestForm.value.checkpoints = defaults
        backtestForm.value.horizons = defaults
      }
    }
  } catch {
    ElMessage.error('加载回测配置失败')
  }
  // 从路由参数回填表单
  _applyQueryParams()
})

// keep-alive 重新激活时回填
onActivated(() => {
  _applyQueryParams()
})

// 从 route.query 回填表单字段
const _applyQueryParams = () => {
  const q = route.query
  if (q.code) {
    backtestForm.value.code = q.code as string
    backtestForm.value.mode = 'single'
  }
  if (q.strategy) {
    backtestForm.value.strategy = q.strategy as string
  }
}

const joinNumbers = (arr: any[]) => {
  return (arr || [])
    .map(v => Number(v))
    .filter(v => Number.isFinite(v) && v > 0)
    .join(',')
}

// 执行回测
const handleRun = async () => {
  if (backtestForm.value.mode === 'single') {
    if (!backtestForm.value.code) {
      ElMessage.warning('请输入股票代码')
      return
    }
    await runSingleBacktest()
  } else {
    if (!backtestForm.value.strategy) {
      ElMessage.warning('请选择回测策略')
      return
    }
    await runBatchBacktestAction()
  }
}

const runSingleBacktest = async () => {
  loading.value = true
  singleResult.value = null
  try {
    const res: any = await runBacktest({
      code: backtestForm.value.code,
      strategy: backtestForm.value.strategy || undefined,
      period: backtestForm.value.period,
      start_date: backtestForm.value.start_date || undefined,
      checkpoints: joinNumbers(backtestForm.value.checkpoints),
    })
    if (res.error) {
      ElMessage.error(res.error)
    } else {
      singleResult.value = res
    }
  } catch (e: any) {
    ElMessage.error(e.message || '回测执行失败')
  } finally {
    loading.value = false
  }
}

const runBatchBacktestAction = async () => {
  loading.value = true
  batchResult.value = null
  try {
    const res: any = await runBatchBacktest({
      strategy: backtestForm.value.strategy,
      period: backtestForm.value.period,
      limit: 30,
      horizons: joinNumbers(backtestForm.value.horizons),
      success_days: Number(backtestForm.value.success_days) || 5,
    })
    if (res.error) {
      ElMessage.error(res.error)
    } else {
      batchResult.value = res
    }
  } catch (e: any) {
    ElMessage.error(e.message || '批量回测执行失败')
  } finally {
    loading.value = false
  }
}

const goDashboard = () => {
  router.push({ path: '/backtest/dashboard' })
}

const goIndicatorDetail = () => {
  if (!singleResult.value?.code) return
  router.push({
    path: '/indicator/detail',
    query: {
      code: singleResult.value.code,
      name: singleResult.value.name,
      date: singleResult.value.buy_date,
      strategy: backtestForm.value.strategy || undefined,
    }
  })
}

const formatRate = (val: any) => {
  if (val === null || val === undefined) return '-'
  const num = Number(val)
  return num >= 0 ? `+${num.toFixed(2)}%` : `${num.toFixed(2)}%`
}

const getRateClass = (val: any) => {
  if (val === null || val === undefined) return ''
  return Number(val) >= 0 ? 'text-up' : 'text-down'
}
</script>

<template>
  <div class="backtest-container">
    <!-- 配置面板 -->
    <el-card shadow="never" class="config-card">
      <template #header>
        <div class="header-row">
          <span class="card-title">自定义回测</span>
          <el-button link type="primary" @click="goDashboard">回测看板</el-button>
        </div>
      </template>
      
      <el-form :model="backtestForm" label-width="100px" inline>
        <el-form-item label="回测模式">
          <el-radio-group v-model="backtestForm.mode" @change="singleResult = null; batchResult = null">
            <el-radio value="single">单股回测</el-radio>
            <el-radio value="batch">策略验证</el-radio>
          </el-radio-group>
        </el-form-item>
        
        <el-form-item v-if="backtestForm.mode === 'single'" label="股票代码">
          <el-input v-model="backtestForm.code" placeholder="如 000001" style="width: 150px" />
        </el-form-item>
        
        <el-form-item label="选择策略">
          <el-select v-model="backtestForm.strategy" placeholder="选择策略（可选）" clearable style="width: 220px">
            <el-option v-for="s in strategies" :key="s.name" :label="s.cn" :value="s.name" />
          </el-select>
        </el-form-item>
        
        <el-form-item label="回测周期">
          <el-select v-model="backtestForm.period" style="width: 130px">
            <el-option v-for="p in periods" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
        </el-form-item>
        
        <el-form-item v-if="backtestForm.mode === 'single'" label="买入日期">
          <el-date-picker v-model="backtestForm.start_date" type="date" placeholder="默认最新" 
            format="YYYY-MM-DD" value-format="YYYY-MM-DD" clearable style="width: 160px" />
        </el-form-item>

        <el-form-item v-if="backtestForm.mode === 'single'" label="收益周期">
          <el-select v-model="backtestForm.checkpoints" multiple filterable allow-create default-first-option :reserve-keyword="false" style="width: 260px">
            <el-option v-for="h in backtestForm.checkpoints" :key="h" :label="`${h}日`" :value="h" />
          </el-select>
        </el-form-item>

        <el-form-item v-if="backtestForm.mode === 'batch'" label="收益周期">
          <el-select v-model="backtestForm.horizons" multiple filterable allow-create default-first-option :reserve-keyword="false" style="width: 260px">
            <el-option v-for="h in backtestForm.horizons" :key="h" :label="`${h}日`" :value="h" />
          </el-select>
        </el-form-item>

        <el-form-item v-if="backtestForm.mode === 'batch'" label="成功判定">
          <el-input-number v-model="backtestForm.success_days" :min="1" :max="100" />
          <span style="margin-left: 6px; color: var(--el-text-color-secondary)">日收益 &gt; 0</span>
        </el-form-item>
        
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="handleRun">
            {{ loading ? '回测中...' : '执行回测' }}
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 单股回测结果 -->
    <el-card v-if="singleResult" shadow="never" class="result-card">
      <template #header>
        <div class="header-row">
          <span class="card-title">回测结果：{{ singleResult.name }}（{{ singleResult.code }}）</span>
          <el-button link type="primary" @click="goIndicatorDetail">查看K线指标</el-button>
        </div>
      </template>
      
      <!-- 概要信息 -->
      <el-descriptions :column="4" border size="small">
        <el-descriptions-item label="买入日期">{{ singleResult.buy_date }}</el-descriptions-item>
        <el-descriptions-item label="买入价格">{{ singleResult.buy_price }}</el-descriptions-item>
        <el-descriptions-item label="回测周期">{{ singleResult.period }}</el-descriptions-item>
        <el-descriptions-item label="数据天数">{{ singleResult.data_points }} 个交易日</el-descriptions-item>
        <el-descriptions-item label="区间最大涨幅">
          <span :class="getRateClass(singleResult.max_return)">{{ formatRate(singleResult.max_return) }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="区间最大回撤">
          <span :class="getRateClass(singleResult.max_drawdown)">{{ formatRate(singleResult.max_drawdown) }}</span>
        </el-descriptions-item>
        <el-descriptions-item v-if="singleResult.strategy_result !== null" label="策略命中">
          <el-tag :type="singleResult.strategy_result ? 'success' : 'info'" size="small">
            {{ singleResult.strategy_result ? '是' : '否' }}
          </el-tag>
        </el-descriptions-item>
      </el-descriptions>

      <!-- 收益率表 -->
      <h4 style="margin: 16px 0 8px">各周期收益率</h4>
      <el-table :data="singleResult.returns" border size="small" stripe>
        <el-table-column prop="days" label="持有天数" width="100" align="center" />
        <el-table-column prop="date" label="卖出日期" width="120" align="center" />
        <el-table-column prop="price" label="卖出价格" width="100" align="right" />
        <el-table-column label="收益率" width="120" align="right">
          <template #default="{ row }">
            <span :class="getRateClass(row.rate)">{{ formatRate(row.rate) }}</span>
          </template>
        </el-table-column>
      </el-table>

      <!-- 关键指标 -->
      <h4 v-if="singleResult.indicators && Object.keys(singleResult.indicators).length > 0" style="margin: 16px 0 8px">买入日关键指标</h4>
      <el-descriptions v-if="singleResult.indicators" :column="5" border size="small">
        <el-descriptions-item v-for="(val, key) in singleResult.indicators" :key="key" :label="String(key).toUpperCase()">
          {{ val !== null ? val : '-' }}
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 批量回测结果 -->
    <el-card v-if="batchResult" shadow="never" class="result-card">
      <template #header>
        <span class="card-title">策略验证：{{ batchResult.strategy }}</span>
      </template>
      
      <!-- 汇总统计 -->
      <el-descriptions :column="4" border size="small">
        <el-descriptions-item label="回测天数">{{ batchResult.total_days }} 天</el-descriptions-item>
        <el-descriptions-item label="总选股数">{{ batchResult.total_stocks }} 只</el-descriptions-item>
        <el-descriptions-item label="成功数">{{ batchResult.success_count }} 只</el-descriptions-item>
        <el-descriptions-item label="总成功率">
          <span :class="batchResult.success_rate >= 50 ? 'text-up' : 'text-down'">
            {{ batchResult.success_rate }}%
          </span>
        </el-descriptions-item>
        <el-descriptions-item v-for="h in (batchResult.horizons || [])" :key="h" :label="`平均${h}日收益`">
          <span :class="getRateClass(batchResult.avg_returns?.[`${h}d`])">{{ formatRate(batchResult.avg_returns?.[`${h}d`]) }}</span>
        </el-descriptions-item>
      </el-descriptions>

      <!-- 每日明细 -->
      <h4 style="margin: 16px 0 8px">每日明细</h4>
      <el-table :data="batchResult.details" border size="small" stripe max-height="400">
        <el-table-column prop="date" label="日期" width="120" align="center" />
        <el-table-column prop="stock_count" label="选股数" width="80" align="center" />
        <el-table-column prop="success_count" label="成功数" width="80" align="center" />
        <el-table-column label="成功率" width="100" align="right">
          <template #default="{ row }">
            <span :class="row.success_rate >= 50 ? 'text-up' : 'text-down'">{{ row.success_rate }}%</span>
          </template>
        </el-table-column>
        <el-table-column v-for="h in (batchResult.horizons || [])" :key="h" :label="`${h}日收益`" width="110" align="right">
          <template #default="{ row }">
            <span :class="getRateClass(row[`avg_${h}d`])">{{ formatRate(row[`avg_${h}d`]) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style lang="scss" scoped>
.backtest-container {
  padding: 0;
}

.config-card {
  margin-bottom: 16px;
}

.result-card {
  margin-bottom: 16px;
}

.card-title {
  font-size: 16px;
  font-weight: 600;
}

.header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.text-up {
  color: #f56c6c;
  font-weight: 500;
}

.text-down {
  color: #67c23a;
  font-weight: 500;
}

:deep(.el-descriptions__label) {
  width: 120px;
}
</style>

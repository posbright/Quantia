<script setup lang="ts">
import { ref, onMounted, onActivated, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { QuestionFilled } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import { getBacktestConfig, runSingleBacktest } from '@/api/stock'
import KlineBacktestChart from '@/components/KlineBacktestChart.vue'
import { useResponsive } from '@/composables/useResponsive'

const { isMobile } = useResponsive()
const route = useRoute()
const router = useRouter()

const strategies = ref<any[]>([])
const loading = ref(false)
const result = ref<any>(null)
const chartRef = ref<InstanceType<typeof KlineBacktestChart> | null>(null)

const form = ref({
  code: '',
  strategy: '',
  start_date: dayjs().subtract(1, 'year').format('YYYY-MM-DD'),
  end_date: dayjs().format('YYYY-MM-DD'),
  hold_days: undefined as number | undefined,
  allow_overlap: false,
  save: true,
})

onMounted(async () => {
  try {
    const config: any = await getBacktestConfig()
    strategies.value = config?.strategies || []
  } catch {
    ElMessage.error('加载策略配置失败')
  }
  _applyQuery()
})

onActivated(() => {
  nextTick(() => chartRef.value?.resize())
})

// 历史「查看」复现：从 query 回填并自动执行
const _applyQuery = () => {
  const q = route.query
  let needRun = false
  if (q.code) { form.value.code = q.code as string; needRun = true }
  // 仅接受合法的回测策略名（来源页面可能转发数据表名如 cn_stock_indicators，需校验后再回填）
  if (q.strategy) {
    const sName = q.strategy as string
    if (strategies.value.some((s: any) => s.name === sName)) {
      form.value.strategy = sName
    }
  }
  if (q.start_date && q.end_date) {
    form.value.start_date = q.start_date as string
    form.value.end_date = q.end_date as string
  }
  if (q.hold_days !== undefined && q.hold_days !== '') {
    const hd = Number(q.hold_days)
    form.value.hold_days = Number.isFinite(hd) && hd > 0 ? hd : undefined
  }
  if (needRun && form.value.strategy) {
    handleRun(false)
  }
}

const handleRun = async (save = true) => {
  if (!form.value.code) {
    ElMessage.warning('请输入股票代码')
    return
  }
  if (!form.value.strategy) {
    ElMessage.warning('请选择回测策略')
    return
  }
  if (!form.value.start_date || !form.value.end_date) {
    ElMessage.warning('请选择回测区间')
    return
  }
  if (dayjs(form.value.start_date).isAfter(dayjs(form.value.end_date))) {
    ElMessage.warning('开始日期不能晚于结束日期')
    return
  }
  loading.value = true
  result.value = null
  try {
    const params: any = {
      code: form.value.code.trim(),
      strategy: form.value.strategy,
      start_date: form.value.start_date,
      end_date: form.value.end_date,
      allow_overlap: form.value.allow_overlap ? 1 : 0,
    }
    if (form.value.hold_days != null && form.value.hold_days > 0) {
      params.hold_days = form.value.hold_days
    }
    if (save && form.value.save) params.save = 1
    const res: any = await runSingleBacktest(params)
    if (res.error) {
      ElMessage.error(res.error)
    } else {
      result.value = res
      nextTick(() => chartRef.value?.resize())
    }
  } catch (e: any) {
    ElMessage.error(e.message || '回测执行失败')
  } finally {
    loading.value = false
  }
}

const formatRate = (val: any) => {
  if (val === null || val === undefined) return '—'
  const num = Number(val)
  return num >= 0 ? `+${num.toFixed(2)}%` : `${num.toFixed(2)}%`
}
const getRateClass = (val: any) => {
  if (val === null || val === undefined) return ''
  return Number(val) >= 0 ? 'text-up' : 'text-down'
}
const fmtNum = (val: any, digits = 2) => {
  if (val === null || val === undefined) return '—'
  return Number(val).toFixed(digits)
}
const exitReasonText = (r: string) => {
  return ({ hold_expired: '持仓到期', sell_signal: '策略卖点', interval_end: '区间末持仓' } as any)[r] || r || '—'
}

// 最大盈利 / 最大回撤对应的交易（用于指标卡副文案显示入场日）
const closedTrades = () => (result.value?.trades || []).filter((t: any) => t.status === 'closed')
const maxReturnTrade = () => {
  const cs = closedTrades()
  if (!cs.length) return null
  return cs.reduce((a: any, b: any) => (b.rate > a.rate ? b : a))
}
const maxDrawdownTrade = () => {
  const cs = closedTrades()
  if (!cs.length) return null
  return cs.reduce((a: any, b: any) => (b.rate < a.rate ? b : a))
}
// 平均每笔收益副文案：固定持仓显示周期，策略卖点显示出场方式
const avgSubText = () => {
  if (!result.value) return ''
  return result.value.exit_mode === 'fixed'
    ? `已平仓·持仓${result.value.hold_days}个交易日`
    : '已平仓·策略卖点出场'
}

// 定位到 K 线上的某笔交易
const locateTrade = (row: any) => {
  if (row?.buy_date) chartRef.value?.locate(row.buy_date)
}

// 携带当前股票代码跳转到回测历史页
const goHistory = () => {
  if (!form.value.code) {
    ElMessage.warning('请输入股票代码')
    return
  }
  const query: Record<string, string> = { code: form.value.code.trim() }
  const name = route.query.name as string
  if (name) query.name = name
  router.push({ path: '/backtest/history', query })
}

</script>

<template>
  <div class="single-backtest">
    <el-card shadow="never" class="config-card">
      <template #header>
        <span class="card-title">单股回测</span>
      </template>
      <el-form :model="form" label-width="92px" inline>
        <el-form-item label="股票代码">
          <el-input v-model="form.code" placeholder="如 000001" style="width: 150px" clearable />
        </el-form-item>
        <el-form-item label="选择策略">
          <el-select v-model="form.strategy" placeholder="请选择策略" filterable style="width: 220px">
            <el-option v-for="s in strategies" :key="s.name" :label="s.cn" :value="s.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="回测区间">
          <el-date-picker v-model="form.start_date" type="date" placeholder="开始日期"
            format="YYYY-MM-DD" value-format="YYYY-MM-DD" style="width: 150px" :clearable="false" />
          <span class="range-sep">至</span>
          <el-date-picker v-model="form.end_date" type="date" placeholder="结束日期"
            format="YYYY-MM-DD" value-format="YYYY-MM-DD" style="width: 150px" :clearable="false" />
        </el-form-item>
        <el-form-item label="持仓周期">
          <el-input-number v-model="form.hold_days" :min="1" :max="250" placeholder="留空=策略卖点"
            controls-position="right" style="width: 160px" />
          <span class="hint">留空按策略卖点出场</span>
        </el-form-item>
        <el-form-item label="允许重叠">
          <el-switch v-model="form.allow_overlap" />
          <el-tooltip placement="top"
            content="开启后：持仓尚未了结时若再次出现买入信号，会另开一笔新仓位（可同时持有多笔重叠仓位）。关闭（默认）：持仓期内的买入信号将被忽略，避免在同一波行情里重复开仓。">
            <el-icon class="tip-icon"><QuestionFilled /></el-icon>
          </el-tooltip>
        </el-form-item>
        <el-form-item label="保存历史">
          <el-switch v-model="form.save" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="handleRun(true)">
            {{ loading ? '回测中...' : '执行回测' }}
          </el-button>
          <el-button type="success" plain @click="goHistory">查看回测历史</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <template v-if="result">
      <!-- 指标卡（对齐原型：7 张带副文案） -->
      <div class="metric-grid">
        <div class="metric-card">
          <div class="metric-label">买卖点对数</div>
          <div class="metric-value">{{ result.summary.trade_count }}</div>
          <div class="metric-sub">{{ result.summary.closed_count }} 已平仓 / {{ result.summary.open_count }} 持仓中</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">胜率</div>
          <div class="metric-value" :class="(result.summary.win_rate ?? 0) >= 50 ? 'text-up' : 'text-down'">{{ result.summary.win_rate == null ? '—' : result.summary.win_rate + '%' }}</div>
          <div class="metric-sub">{{ result.summary.win_count }} 胜 / {{ result.summary.lose_count }} 负（仅计已平仓）</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">累计收益</div>
          <div class="metric-value" :class="getRateClass(result.summary.cum_return)">{{ formatRate(result.summary.cum_return) }}</div>
          <div class="metric-sub">已平仓复利，含0.30%成本</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">平均每笔收益</div>
          <div class="metric-value" :class="getRateClass(result.summary.avg_return)">{{ formatRate(result.summary.avg_return) }}</div>
          <div class="metric-sub">{{ avgSubText() }}</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">夏普比率</div>
          <div class="metric-value">{{ fmtNum(result.summary.sharpe) }}</div>
          <div class="metric-sub">基于交易级收益年化估算，无风险3%</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">最大单笔回撤</div>
          <div class="metric-value text-down">{{ formatRate(result.summary.max_trade_drawdown) }}</div>
          <div class="metric-sub">{{ maxDrawdownTrade() ? maxDrawdownTrade().buy_date + ' 入场' : '—' }}</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">最大单笔盈利</div>
          <div class="metric-value text-up">{{ formatRate(result.summary.max_trade_return) }}</div>
          <div class="metric-sub">{{ maxReturnTrade() ? maxReturnTrade().buy_date + ' 入场' : '—' }}</div>
        </div>
      </div>

      <!-- K线买卖点图 -->
      <el-card shadow="never" class="chart-card">
        <template #header>
          <div class="header-row">
            <span class="card-title">{{ result.name }}（{{ result.code }}）· {{ result.strategy_cn }}</span>
            <span class="sub-info">{{ result.start_date }} ~ {{ result.end_date }} · {{ result.exit_mode === 'fixed' ? `固定持仓 ${result.hold_days} 日` : '策略卖点出场' }}</span>
          </div>
        </template>
        <KlineBacktestChart ref="chartRef" :kline="result.kline" :indicators="result.indicators" :trades="result.trades" />
      </el-card>

      <!-- 交易明细 -->
      <el-card shadow="never" class="result-card">
        <template #header><span class="card-title">交易明细</span></template>
        <el-table v-if="!isMobile" :data="result.trades" border size="small" stripe max-height="420">
          <el-table-column prop="no" label="#" width="50" align="center" />
          <el-table-column label="类型" width="80" align="center">
            <template #default="{ row }">
              <el-tag :type="row.status === 'open' ? 'warning' : 'danger'" size="small" effect="plain">
                {{ row.status === 'open' ? '持仓中' : '买入' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="buy_date" label="买入日" width="110" align="center" />
          <el-table-column prop="buy_price" label="买入价" width="90" align="right" />
          <el-table-column label="卖出日" width="110" align="center">
            <template #default="{ row }">{{ row.sell_date || '—' }}</template>
          </el-table-column>
          <el-table-column label="卖出价" width="90" align="right">
            <template #default="{ row }">{{ row.sell_price ?? '—' }}</template>
          </el-table-column>
          <el-table-column prop="hold_days" label="持仓天数" width="90" align="center" />
          <el-table-column label="出场原因" width="110" align="center">
            <template #default="{ row }">{{ exitReasonText(row.exit_reason) }}</template>
          </el-table-column>
          <el-table-column label="收益率" width="100" align="right">
            <template #default="{ row }">
              <span :class="getRateClass(row.rate)">{{ formatRate(row.rate) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90" align="center">
            <template #default="{ row }">
              <el-tag :type="row.status === 'open' ? 'warning' : (row.win ? 'success' : 'info')" size="small">
                {{ row.status === 'open' ? '持仓中' : (row.win ? '盈利' : '亏损') }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80" align="center">
            <template #default="{ row }">
              <el-button type="primary" link size="small" @click="locateTrade(row)">定位</el-button>
            </template>
          </el-table-column>
        </el-table>

        <!-- 移动端卡片视图 -->
        <div v-if="isMobile" class="tr-card-list">
          <el-empty v-if="(result.trades || []).length === 0" description="暂无交易" :image-size="60" />
          <div v-for="(row, ri) in result.trades" :key="ri" class="tr-card">
            <div class="tr-card-head">
              <span class="tr-card-title">#{{ row.no }} {{ row.buy_date }}</span>
              <el-tag :type="row.status === 'open' ? 'warning' : (row.win ? 'success' : 'info')" size="small">
                {{ row.status === 'open' ? '持仓中' : (row.win ? '盈利' : '亏损') }}
              </el-tag>
            </div>
            <div class="tr-card-body">
              <div class="tr-field"><span class="tr-lbl">买入价</span><span>{{ row.buy_price }}</span></div>
              <div class="tr-field"><span class="tr-lbl">卖出日</span><span>{{ row.sell_date || '—' }}</span></div>
              <div class="tr-field"><span class="tr-lbl">卖出价</span><span>{{ row.sell_price ?? '—' }}</span></div>
              <div class="tr-field"><span class="tr-lbl">持仓天数</span><span>{{ row.hold_days }}</span></div>
              <div class="tr-field"><span class="tr-lbl">出场原因</span><span>{{ exitReasonText(row.exit_reason) }}</span></div>
              <div class="tr-field"><span class="tr-lbl">收益率</span><span :class="getRateClass(row.rate)">{{ formatRate(row.rate) }}</span></div>
            </div>
            <div class="tr-card-ops">
              <span class="tr-op" @click="locateTrade(row)">定位</span>
            </div>
          </div>
        </div>
      </el-card>
    </template>

    <el-empty v-else-if="!loading" description="填写参数后执行回测" />
  </div>
</template>

<style lang="scss" scoped>
.single-backtest { padding: 0; }
.config-card, .chart-card, .result-card { margin-bottom: 16px; }
.card-title { font-size: 16px; font-weight: 600; }
.sub-info { font-size: 13px; color: #909399; }
.header-row { display: flex; align-items: center; justify-content: space-between; }
.hint { margin-left: 8px; font-size: 12px; color: #c0c4cc; }
.range-sep { margin: 0 8px; color: #909399; }
.tip-icon { margin-left: 6px; font-size: 15px; color: #909399; cursor: help; vertical-align: middle; }
.metric-row { margin-bottom: 16px; }
.metric-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
@media (max-width: 1280px) {
  .metric-grid { grid-template-columns: repeat(4, 1fr); }
}
@media (max-width: 768px) {
  .metric-grid { grid-template-columns: repeat(2, 1fr); }
}
.metric-card {
  background: var(--el-bg-color-overlay);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 14px 12px;
  text-align: center;
}
.metric-label { font-size: 12px; color: #909399; margin-bottom: 6px; }
.metric-value { font-size: 20px; font-weight: 600; }
.metric-sub { font-size: 11px; color: #c0c4cc; margin-top: 6px; }
.text-up { color: #f56c6c; }
.text-down { color: #67c23a; }

/* ─── 移动端交易明细卡片 ─── */
.tr-card-list { display: flex; flex-direction: column; gap: 10px; }
.tr-card { background: var(--el-bg-color-overlay); border: 1px solid var(--el-border-color-lighter); border-radius: 6px; padding: 10px 12px; }
.tr-card-head { display: flex; justify-content: space-between; align-items: center; padding-bottom: 8px; border-bottom: 1px dashed var(--el-border-color-lighter); }
.tr-card-title { font-weight: 600; font-size: 14px; }
.tr-card-body { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 12px; font-size: 13px; padding: 8px 0; }
.tr-field { display: flex; justify-content: space-between; gap: 6px; }
.tr-lbl { color: #909399; }
.tr-card-ops { display: flex; justify-content: flex-end; padding-top: 8px; border-top: 1px dashed var(--el-border-color-lighter); }
.tr-op { color: #409eff; cursor: pointer; font-size: 13px; }

@include sm-down {
  .config-card, .chart-card, .result-card { margin-bottom: 12px; }
  .header-row { flex-wrap: wrap; gap: 6px; }
  :deep(.el-form--inline) {
    .el-form-item { display: flex; margin-right: 0; margin-bottom: 10px; width: 100%; }
    .el-form-item__content { flex: 1; }
    .el-form-item__content > .el-input,
    .el-form-item__content > .el-select,
    .el-form-item__content > .el-input-number { width: 100% !important; }
  }
  .range-sep { margin: 0 6px; }
}
</style>

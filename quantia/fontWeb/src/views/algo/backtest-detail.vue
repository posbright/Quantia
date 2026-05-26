<template>
  <div class="bt-detail" v-loading="loading">
    <!-- ── Header ── -->
    <div class="detail-header">
      <el-button text @click="$router.back()">
        <el-icon><ArrowLeft /></el-icon> 返回
      </el-button>
      <h3>回测详情 #{{ btId }}</h3>
      <span class="header-sub" v-if="info">
        {{ info.strategy_name }} &nbsp;|&nbsp; {{ info.start_date }} ~ {{ info.end_date }}
        &nbsp;|&nbsp; 初始资金 {{ Number(info.initial_cash || 0).toLocaleString() }} 元
      </span>
    </div>

    <!-- ── M4：失败回测 → AI 修复入口 ── -->
    <el-alert
      v-if="info?.status === 'failed'"
      type="error"
      :closable="false"
      show-icon
      style="margin-bottom: 12px;"
    >
      <template #title>
        <div class="failed-banner">
          <span>回测失败：{{ info.error_message || '(无错误信息)' }}</span>
          <el-button
            v-if="info.strategy_id"
            type="primary"
            size="small"
            @click="openAiRepair"
          >AI 一键修复</el-button>
        </div>
      </template>
    </el-alert>

    <AiChatDrawer
      v-model="aiDrawerOpen"
      :strategy-id="info?.strategy_id"
      :current-code="info?.strategy_code || ''"
      default-mode="repair"
      @apply="onAiRepairApply"
    />

    <!-- ═══════════  收益概述（聚宽双列表格风格）═══════════ -->
    <div class="jq-summary" v-if="info?.metrics">
      <table class="jq-table">
        <tbody>
          <tr>
            <td class="jq-lbl">策略收益</td>
            <td class="jq-val" :class="pctCls(M.total_return)">{{ fmtPct(M.total_return) }}</td>
            <td class="jq-lbl">策略年化收益</td>
            <td class="jq-val" :class="pctCls(M.annual_return)">{{ fmtPct(M.annual_return) }}</td>
            <td class="jq-lbl">超额收益</td>
            <td class="jq-val" :class="pctCls(M.excess_return)">{{ fmtPct(M.excess_return) }}</td>
          </tr>
          <tr>
            <td class="jq-lbl">基准收益</td>
            <td class="jq-val" :class="pctCls(M.benchmark_return)">{{ fmtPct(M.benchmark_return) }}</td>
            <td class="jq-lbl">阿尔法</td>
            <td class="jq-val">{{ fmtNum(M.alpha) }}</td>
            <td class="jq-lbl">贝塔</td>
            <td class="jq-val">{{ fmtNum(M.beta) }}</td>
          </tr>
          <tr>
            <td class="jq-lbl">夏普比率</td>
            <td class="jq-val">{{ fmtNum(M.sharpe_ratio) }}</td>
            <td class="jq-lbl">索提诺比率</td>
            <td class="jq-val">{{ fmtNum(M.sortino_ratio) }}</td>
            <td class="jq-lbl">信息比率</td>
            <td class="jq-val">{{ fmtNum(M.information_ratio) }}</td>
          </tr>
          <tr>
            <td class="jq-lbl">胜率</td>
            <td class="jq-val">{{ fmtPct(M.trade_win_rate, 1) }}</td>
            <td class="jq-lbl">盈亏比</td>
            <td class="jq-val">{{ fmtNum(M.profit_loss_ratio) }}</td>
            <td class="jq-lbl">最大回撤</td>
            <td class="jq-val val-green">{{ fmtPct(M.max_drawdown) }}</td>
          </tr>
          <tr>
            <td class="jq-lbl">日胜率</td>
            <td class="jq-val">{{ fmtPct(M.daily_win_rate, 1) }}</td>
            <td class="jq-lbl">盈利次数</td>
            <td class="jq-val val-red">{{ M.win_count ?? 0 }}</td>
            <td class="jq-lbl">亏损次数</td>
            <td class="jq-val val-green">{{ M.loss_count ?? 0 }}</td>
          </tr>
          <tr>
            <td class="jq-lbl">日均超额收益</td>
            <td class="jq-val" :class="pctCls(M.avg_daily_excess)">{{ fmtPct(M.avg_daily_excess, 3) }}</td>
            <td class="jq-lbl">超额收益最大回撤</td>
            <td class="jq-val val-green">{{ fmtPct(M.excess_max_drawdown) }}</td>
            <td class="jq-lbl">超额收益夏普比率</td>
            <td class="jq-val">{{ fmtNum(M.excess_sharpe_ratio) }}</td>
          </tr>
          <tr>
            <td class="jq-lbl">策略波动率</td>
            <td class="jq-val">{{ fmtPct(M.strategy_volatility) }}</td>
            <td class="jq-lbl">基准波动率</td>
            <td class="jq-val">{{ fmtPct(M.benchmark_volatility) }}</td>
            <td class="jq-lbl">最大回撤区间</td>
            <td class="jq-val jq-val-sm">{{ ddRange }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ═══════════  Tabs ═══════════ -->
    <el-tabs v-model="activeTab">

      <!-- Tab 1: 收益走势（累计收益 + 超额） -->
      <el-tab-pane label="收益走势" name="overview">
        <div ref="chartEl" class="chart-box"></div>
      </el-tab-pane>

      <!-- Tab 2: 每日盈亏 -->
      <el-tab-pane label="每日盈亏" name="daily_pnl">
        <div ref="pnlChartEl" class="chart-box"></div>
        <el-table :data="dailyPnlData" size="small" max-height="480" stripe style="margin-top: 8px">
          <el-table-column prop="date" label="日期" width="100" />
          <el-table-column label="策略净值" width="95" align="right">
            <template #default="{ row }">{{ N(row.nav).toFixed(4) }}</template>
          </el-table-column>
          <el-table-column label="基准净值" width="95" align="right">
            <template #default="{ row }">{{ N(row.benchmark_nav).toFixed(4) }}</template>
          </el-table-column>
          <el-table-column label="策略日收益" width="100" align="right">
            <template #default="{ row }">
              <span :class="pctCls(row.daily_return)">{{ ((row.daily_return ?? 0) * 100).toFixed(2) }}%</span>
            </template>
          </el-table-column>
          <el-table-column label="基准日收益" width="100" align="right">
            <template #default="{ row }">
              <span :class="pctCls(row.benchmark_return)">{{ ((row.benchmark_return ?? 0) * 100).toFixed(2) }}%</span>
            </template>
          </el-table-column>
          <el-table-column label="累计收益" width="100" align="right">
            <template #default="{ row }">
              <span :class="pctCls((row.nav ?? 1) - 1)">{{ (((row.nav ?? 1) - 1) * 100).toFixed(2) }}%</span>
            </template>
          </el-table-column>
          <el-table-column label="总资产" width="130" align="right">
            <template #default="{ row }">{{ N(row.total_value).toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}</template>
          </el-table-column>
          <el-table-column label="现金" width="130" align="right">
            <template #default="{ row }">{{ N(row.cash).toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}</template>
          </el-table-column>
          <el-table-column label="持仓市值" width="130" align="right">
            <template #default="{ row }">{{ N(row.market_value).toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- Tab 3: 每日买卖 -->
      <el-tab-pane :label="'每日买卖(' + (info?.trades?.length || 0) + ')'" name="trades">
        <div ref="tradeChartEl" class="chart-box"></div>
        <el-table :data="info?.trades || []" size="small" max-height="480" stripe style="margin-top: 8px">
          <el-table-column prop="date" label="日期" width="100" />
          <el-table-column prop="code" label="代码" width="75">
            <template #default="{ row }">
              <el-button link type="primary" @click.stop="openStockTrade(row)">{{ row.code }}</el-button>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" width="85" show-overflow-tooltip />
          <el-table-column prop="direction" label="方向" width="55">
            <template #default="{ row }">
              <span :style="{ color: row.direction === 'buy' ? '#f56c6c' : '#67c23a', fontWeight: 600 }">
                {{ row.direction === 'buy' ? '买入' : '卖出' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="成交价" width="85" align="right">
            <template #default="{ row }">{{ N(row.price).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column label="数量(股)" width="90" align="right">
            <template #default="{ row }">{{ N(row.amount).toLocaleString() }}</template>
          </el-table-column>
          <el-table-column label="成交金额" width="110" align="right">
            <template #default="{ row }">{{ N(row.value || row.price * row.amount).toLocaleString('zh-CN', { maximumFractionDigits: 0 }) }}</template>
          </el-table-column>
          <el-table-column label="佣金" width="75" align="right">
            <template #default="{ row }">{{ N(row.commission || 0).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column label="印花税" width="75" align="right">
            <template #default="{ row }">{{ N(row.tax || 0).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column label="滑点" width="75" align="right">
            <template #default="{ row }">{{ N(row.slippage_cost || 0).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column label="平仓盈亏" width="110" align="right">
            <template #default="{ row }">
              <span v-if="row.direction === 'sell'" :class="pctCls(row.close_profit)">
                {{ (row.close_profit ?? 0) >= 0 ? '+' : '' }}{{ N(row.close_profit || 0).toFixed(2) }}
              </span>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column label="收益率" width="85" align="right">
            <template #default="{ row }">
              <span v-if="row.direction === 'sell'" :class="pctCls(row.return_rate)">
                {{ (row.return_rate ?? 0) >= 0 ? '+' : '' }}{{ N(row.return_rate || 0).toFixed(2) }}%
              </span>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column label="交易原因" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">{{ tradeReason(row) }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- Tab 4: 每日持仓 -->
      <el-tab-pane label="每日持仓" name="positions">
        <div style="margin-bottom: 10px" v-if="info?.positions?.length">
          <el-select v-model="selectedPosDate" size="small" style="width: 160px" placeholder="选择日期">
            <el-option v-for="p in info.positions" :key="p.date" :label="p.date" :value="p.date" />
          </el-select>
        </div>
        <el-table :data="selectedPositions" size="small" max-height="600" stripe>
          <el-table-column prop="code" label="代码" width="75" />
          <el-table-column prop="name" label="名称" width="85" show-overflow-tooltip />
          <el-table-column label="持仓(股)" width="90" align="right">
            <template #default="{ row }">{{ N(row.amount).toLocaleString() }}</template>
          </el-table-column>
          <el-table-column label="成本价" width="85" align="right">
            <template #default="{ row }">{{ N(row.avg_cost).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column label="现价" width="85" align="right">
            <template #default="{ row }">{{ N(row.price).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column label="市值" width="110" align="right">
            <template #default="{ row }">{{ N(row.value).toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}</template>
          </el-table-column>
          <el-table-column label="盈亏" width="100" align="right">
            <template #default="{ row }">
              <span :class="pctCls(row.profit)">{{ (row.profit ?? 0) >= 0 ? '+' : '' }}{{ N(row.profit ?? 0).toFixed(2) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="盈亏比例" width="90" align="right">
            <template #default="{ row }">
              <span :class="pctCls(row.profit_rate)">{{ (row.profit_rate ?? 0) >= 0 ? '+' : '' }}{{ N(row.profit_rate ?? 0).toFixed(2) }}%</span>
            </template>
          </el-table-column>
          <el-table-column label="仓位占比" width="90" align="right">
            <template #default="{ row }">{{ N(row.weight).toFixed(1) }}%</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- Tab 5: 运行日志 -->
      <el-tab-pane :label="'日志(' + (info?.logs?.length || 0) + ')'" name="logs">
        <div class="log-box">
          <div v-for="(l, i) in (info?.logs || []).slice(-300)" :key="i" class="log-line">{{ l }}</div>
          <div v-if="!info?.logs?.length" class="log-empty">暂无日志</div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="stockDialogVisible" :title="stockDialogTitle" width="92vw" top="4vh" destroy-on-close
               @closed="disposeStockCharts">
      <div class="stock-dialog" v-loading="stockLoading">
        <div class="stock-summary" v-if="selectedTrade">
          <div class="summary-item"><span>交易日期</span><b>{{ selectedTrade.date }}</b></div>
          <div class="summary-item"><span>方向</span><b :class="selectedTrade.direction === 'buy' ? 'val-red' : 'val-green'">{{ directionLabel(selectedTrade) }}</b></div>
          <div class="summary-item"><span>成交价</span><b>{{ N(selectedTrade.price).toFixed(2) }}</b></div>
          <div class="summary-item"><span>数量</span><b>{{ N(selectedTrade.amount).toLocaleString() }}</b></div>
          <div class="summary-item wide"><span>原因</span><b>{{ tradeReason(selectedTrade) }}</b></div>
        </div>

        <div class="decision-panel" v-if="selectedTrade">
          <div class="panel-title">交易决策依据</div>
          <div class="decision-summary">
            <span>{{ decisionSummary.action }}</span>
            <b>{{ decisionSummary.reason }}</b>
          </div>
          <el-table :data="decisionRows" size="small" border class="decision-table" empty-text="暂无指标数据">
            <el-table-column prop="name" label="指标/规则" min-width="120" />
            <el-table-column prop="threshold" label="阈值/判定" min-width="150" />
            <el-table-column prop="actual" label="实际数据" min-width="170" />
            <el-table-column prop="result" label="结果" width="80" align="center">
              <template #default="{ row }">
                <el-tag :type="row.pass ? 'success' : row.pass === false ? 'warning' : 'info'" size="small" effect="plain">
                  {{ row.result }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="note" label="说明" min-width="180" show-overflow-tooltip />
          </el-table>
        </div>

        <div class="stock-toolbar">
          <span class="toolbar-label">主图叠加</span>
          <el-checkbox-group v-model="stockOverlayIndicators" size="small" @change="renderActiveStockChart">
            <el-checkbox-button label="MA5">MA5</el-checkbox-button>
            <el-checkbox-button label="MA20">MA20</el-checkbox-button>
            <el-checkbox-button label="MA30">MA30</el-checkbox-button>
            <el-checkbox-button label="MA60">MA60</el-checkbox-button>
            <el-checkbox-button label="BOLL">BOLL</el-checkbox-button>
          </el-checkbox-group>
          <el-switch
            v-model="stockShowBenchmark"
            size="small"
            :active-text="benchmarkSwitchText"
            inactive-text="隐藏基准K线"
            @change="renderActiveStockChart"
          />
          <span class="toolbar-hint">指标基于完整历史K线计算，视图默认聚焦回测区间，买卖点来自本次回测交易记录。</span>
        </div>

        <CustomIndicatorOverlayBar :state="ciOverlay" />

        <el-tabs v-model="stockActivePeriod" @tab-change="renderActiveStockChart">
          <el-tab-pane label="日K" name="daily">
            <div ref="stockDailyEl" class="stock-chart-box" :class="{ 'has-sub': hasCiSubPanel }"></div>
          </el-tab-pane>
          <el-tab-pane label="周K" name="weekly">
            <div ref="stockWeeklyEl" class="stock-chart-box" :class="{ 'has-sub': hasCiSubPanel }"></div>
          </el-tab-pane>
          <el-tab-pane label="月K" name="monthly">
            <div ref="stockMonthlyEl" class="stock-chart-box" :class="{ 'has-sub': hasCiSubPanel }"></div>
          </el-tab-pane>
        </el-tabs>

        <div class="indicator-panel" v-if="selectedTrade">
          <div class="panel-title">{{ stockPeriodLabel }}指标快照</div>
          <el-descriptions :column="4" size="small" border>
            <el-descriptions-item label="K线日期">{{ activeIndicatorSnapshot.date || '--' }}</el-descriptions-item>
            <el-descriptions-item label="开盘">{{ fmtMaybe(activeIndicatorSnapshot.open) }}</el-descriptions-item>
            <el-descriptions-item label="最高">{{ fmtMaybe(activeIndicatorSnapshot.high) }}</el-descriptions-item>
            <el-descriptions-item label="最低">{{ fmtMaybe(activeIndicatorSnapshot.low) }}</el-descriptions-item>
            <el-descriptions-item label="收盘">{{ fmtMaybe(activeIndicatorSnapshot.close) }}</el-descriptions-item>
            <el-descriptions-item label="MA5">{{ fmtMaybe(activeIndicatorSnapshot.ma5) }}</el-descriptions-item>
            <el-descriptions-item label="MA20">{{ fmtMaybe(activeIndicatorSnapshot.ma20) }}</el-descriptions-item>
            <el-descriptions-item label="MA30">{{ fmtMaybe(activeIndicatorSnapshot.ma30) }}</el-descriptions-item>
            <el-descriptions-item label="MA60">{{ fmtMaybe(activeIndicatorSnapshot.ma60) }}</el-descriptions-item>
            <el-descriptions-item label="BOLL上轨">{{ fmtMaybe(activeIndicatorSnapshot.bollUpper) }}</el-descriptions-item>
            <el-descriptions-item label="BOLL中轨">{{ fmtMaybe(activeIndicatorSnapshot.bollMiddle) }}</el-descriptions-item>
            <el-descriptions-item label="BOLL下轨">{{ fmtMaybe(activeIndicatorSnapshot.bollLower) }}</el-descriptions-item>
            <el-descriptions-item label="RSI14">{{ fmtMaybe(activeIndicatorSnapshot.rsi) }}</el-descriptions-item>
            <el-descriptions-item label="MACD DIF">{{ fmtMaybe(activeIndicatorSnapshot.macdDif) }}</el-descriptions-item>
            <el-descriptions-item label="MACD DEA">{{ fmtMaybe(activeIndicatorSnapshot.macdDea) }}</el-descriptions-item>
            <el-descriptions-item label="MACD柱">{{ fmtMaybe(activeIndicatorSnapshot.macdHist) }}</el-descriptions-item>
            <el-descriptions-item label="成交量">{{ N(activeIndicatorSnapshot.volume || 0).toLocaleString() }}</el-descriptions-item>
          </el-descriptions>
        </div>

        <el-table :data="selectedStockTrades" size="small" max-height="220" stripe class="stock-trade-table"
                  @row-click="selectTradeInDialog">
          <el-table-column prop="date" label="日期" width="100" />
          <el-table-column label="方向" width="70">
            <template #default="{ row }">
              <span :class="row.direction === 'buy' ? 'val-red' : 'val-green'">{{ directionLabel(row) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="code" label="代码" width="75" />
          <el-table-column prop="name" label="名称" width="110" show-overflow-tooltip />
          <el-table-column label="价格" width="85" align="right"><template #default="{ row }">{{ N(row.price).toFixed(2) }}</template></el-table-column>
          <el-table-column label="数量" width="95" align="right"><template #default="{ row }">{{ N(row.amount).toLocaleString() }}</template></el-table-column>
          <el-table-column label="盈亏/收益率" width="140" align="right">
            <template #default="{ row }">
              <span v-if="row.direction === 'sell'" :class="pctCls(row.close_profit)">
                {{ (row.close_profit ?? 0) >= 0 ? '+' : '' }}{{ N(row.close_profit || 0).toFixed(2) }} / {{ N(row.return_rate || 0).toFixed(2) }}%
              </span>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column label="交易原因" min-width="260" show-overflow-tooltip>
            <template #default="{ row }">{{ tradeReason(row) }}</template>
          </el-table-column>
        </el-table>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, onActivated, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getKlineData, getPortfolioBacktestDetail } from '@/api/stock'
import * as echarts from 'echarts'
import { useCustomIndicatorOverlay } from '@/composables/useCustomIndicatorOverlay'
import CustomIndicatorOverlayBar from '@/components/CustomIndicatorOverlayBar.vue'
import AiChatDrawer, { type AiApplyMeta } from '@/components/AiChatDrawer.vue'
import { useResponsive } from '@/composables/useResponsive'

const route = useRoute()
const router = useRouter()
const { isMobile } = useResponsive()

const btId = computed(() => Number(route.params.id))
const info = ref<any>(null)
const loading = ref(false)
const activeTab = ref('overview')
const selectedPosDate = ref('')
let lastLoadedId = 0   // 记录上次加载的回测ID，用于 keep-alive 激活时判断是否需要重新加载

// M4：AI 修复抽屉
const aiDrawerOpen = ref(false)
function openAiRepair() {
  aiDrawerOpen.value = true
}
function onAiRepairApply(code: string, meta: AiApplyMeta) {
  const sid = info.value?.strategy_id
  // P1-C：先写 sessionStorage 兜底（drawer 已 emit→close，避免代码丢失）
  const payload = {
    strategy_id: sid || null,
    code,
    meta,
    backtest_id: info.value?.id,
    ts: Date.now(),
  }
  try {
    sessionStorage.setItem('ai-repair-pending', JSON.stringify(payload))
  } catch (e) {
    ElMessage.error('存储修复结果失败：' + (e as Error).message)
    return
  }
  if (!sid) {
    ElMessage.warning('该回测无关联策略 ID，已暂存修复代码到本地，请手动在目标策略编辑页应用')
    return
  }
  ElMessage.success('已生成修复代码，跳转到编辑器')
  router.push('/algo/edit/' + sid)
}

const chartEl = ref<HTMLElement>()
const pnlChartEl = ref<HTMLElement>()
const tradeChartEl = ref<HTMLElement>()
const stockDailyEl = ref<HTMLElement>()
const stockWeeklyEl = ref<HTMLElement>()
const stockMonthlyEl = ref<HTMLElement>()
let chart: echarts.ECharts | null = null
let pnlChart: echarts.ECharts | null = null
let tradeChart: echarts.ECharts | null = null
let stockDailyChart: echarts.ECharts | null = null
let stockWeeklyChart: echarts.ECharts | null = null
let stockMonthlyChart: echarts.ECharts | null = null

const stockDialogVisible = ref(false)
const stockLoading = ref(false)
const stockActivePeriod = ref<'daily' | 'weekly' | 'monthly'>('daily')
const selectedStock = ref<any>(null)
const selectedTrade = ref<any>(null)
const stockKlines = ref<Record<string, any>>({})
const benchmarkKlines = ref<Record<string, any>>({})
const stockOverlayIndicators = ref(['MA5', 'MA20', 'MA30', 'MA60', 'BOLL'])
const stockShowBenchmark = ref(true)

// PR-5 自定义指标叠加
const ciCodeRef = computed(() => {
  const c = selectedStock.value?.code
  return c ? String(c).padStart(6, '0') : ''
})
const ciDatesRef = computed<string[]>(() => stockKlines.value[stockActivePeriod.value]?.dates || [])
const ciOverlay = useCustomIndicatorOverlay(
  ciCodeRef as any,
  stockActivePeriod as any,
  ciDatesRef as any,
)
watch(
  () => ciOverlay.extension.value,
  async () => {
    await nextTick()
    renderActiveStockChart()
  },
  { deep: true },
)
const hasCiSubPanel = computed(() => !!ciOverlay.extension.value.subPanel)

// ── shortcuts ──
const N = Number
const M = computed(() => info.value?.metrics || {})

function fmtPct(v: number | undefined, digits = 2) {
  if (v == null) return '--'
  return `${v >= 0 ? '+' : ''}${N(v).toFixed(digits)}%`
}
function fmtNum(v: number | undefined, digits = 3) {
  if (v == null) return '--'
  return N(v).toFixed(digits)
}
function pctCls(v: number | undefined) {
  if (v == null || v === 0) return ''
  return v > 0 ? 'val-red' : 'val-green'
}

function fmtMaybe(v: any, digits = 2) {
  if (v == null || Number.isNaN(Number(v))) return '--'
  return N(v).toFixed(digits)
}

function finiteNumber(v: any): number | null {
  const num = Number(v)
  return Number.isFinite(num) ? num : null
}

function fmtDiffPct(value: any, base: any) {
  const actual = finiteNumber(value)
  const threshold = finiteNumber(base)
  if (actual == null || threshold == null || threshold === 0) return '--'
  const diff = (actual / threshold - 1) * 100
  return `${diff >= 0 ? '+' : ''}${diff.toFixed(2)}%`
}

function directionLabel(trade: any) {
  return trade?.direction === 'buy' ? '买入' : '卖出'
}

function tradeReason(trade: any) {
  if (!trade) return '--'
  if (trade.reason) return trade.reason
  const logReason = findTradeLogReason(trade)
  if (logReason) return logReason
  if (trade.direction === 'buy') {
    return `策略触发买入信号，按收盘价撮合；成交价 ${fmtMaybe(trade.price)}，成交金额 ${N(trade.value || trade.price * trade.amount).toLocaleString('zh-CN', { maximumFractionDigits: 0 })} 元，佣金 ${fmtMaybe(trade.commission || 0)}，滑点成本 ${fmtMaybe(trade.slippage_cost || 0)}`
  }
  const profit = trade.close_profit == null ? '--' : `${trade.close_profit >= 0 ? '+' : ''}${fmtMaybe(trade.close_profit)}`
  const ret = trade.return_rate == null ? '--' : `${trade.return_rate >= 0 ? '+' : ''}${fmtMaybe(trade.return_rate)}%`
  return `策略触发卖出/风控/调仓信号，按收盘价撮合；成交价 ${fmtMaybe(trade.price)}，平仓盈亏 ${profit}，收益率 ${ret}，佣金 ${fmtMaybe(trade.commission || 0)}，印花税 ${fmtMaybe(trade.tax || 0)}，滑点成本 ${fmtMaybe(trade.slippage_cost || 0)}`
}

function decisionStatus(pass: boolean | null, positive = '满足', negative = '偏离') {
  if (pass == null) return '缺数据'
  return pass ? positive : negative
}

function buildDecisionRow(name: string, threshold: string, actual: string, pass: boolean | null, note: string) {
  return {
    name,
    threshold,
    actual,
    pass,
    result: decisionStatus(pass),
    note,
  }
}

function fmtVolume(v: any) {
  const num = finiteNumber(v)
  if (num == null) return '--'
  if (Math.abs(num) >= 100000000) return `${(num / 100000000).toFixed(2)}亿`
  if (Math.abs(num) >= 10000) return `${(num / 10000).toFixed(1)}万`
  return num.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
}

function fmtIndicatorDiff(value: any, base: any) {
  const diff = fmtDiffPct(value, base)
  return diff === '--' ? '' : `（偏离 ${diff}）`
}

function maCrossText(snapshot: any) {
  const current = finiteNumber(snapshot.ma5) != null && finiteNumber(snapshot.ma20) != null
    ? `MA5 ${fmtMaybe(snapshot.ma5)} / MA20 ${fmtMaybe(snapshot.ma20)}`
    : 'MA5/MA20 --'
  const prev = finiteNumber(snapshot.prevMa5) != null && finiteNumber(snapshot.prevMa20) != null
    ? `，前值 ${fmtMaybe(snapshot.prevMa5)} / ${fmtMaybe(snapshot.prevMa20)}`
    : ''
  return current + prev
}

function decisionRowsForTrade(trade: any, snapshot: any) {
  if (!trade) return []
  const rows: any[] = []
  const isBuy = trade.direction === 'buy'
  const close = finiteNumber(snapshot?.close)
  const price = finiteNumber(trade.price)
  const ma60 = finiteNumber(snapshot?.ma60)
  const bollUpper = finiteNumber(snapshot?.bollUpper)
  const bollMiddle = finiteNumber(snapshot?.bollMiddle)
  const bollLower = finiteNumber(snapshot?.bollLower)
  const rsi = finiteNumber(snapshot?.rsi)
  const macdDif = finiteNumber(snapshot?.macdDif)
  const macdDea = finiteNumber(snapshot?.macdDea)
  const macdHist = finiteNumber(snapshot?.macdHist)
  const volume = finiteNumber(snapshot?.volume)
  const volMa5 = finiteNumber(snapshot?.volMa5)
  const tradeValue = finiteNumber(trade.value || (trade.price * trade.amount))
  const returnRate = finiteNumber(trade.return_rate)
  const closeProfit = finiteNumber(trade.close_profit)
  const reasonText = String(tradeReason(trade) || '')
  const reasonSrc = String(trade?.reason_source || '')

  // 决策来源（让用户清楚 reason 是谁给的）
  let sourceLabel = '系统兜底文案'
  if (reasonSrc === 'strategy') sourceLabel = '策略显式说明（reason=）'
  else if (reasonSrc === 'derived') sourceLabel = '从策略当日 log.info 派生'

  rows.push(buildDecisionRow(
    '策略决策',
    isBuy ? '本笔买入/建仓的策略说明' : '本笔卖出/调仓/风控的策略说明',
    reasonText || '--',
    null,
    sourceLabel,
  ))

  rows.push(buildDecisionRow(
    '成交撮合',
    '按当日 K 线收盘价附近撮合',
    `成交 ${fmtMaybe(price)} / 收盘 ${fmtMaybe(close)}${fmtIndicatorDiff(price, close)}`,
    price != null && close != null ? Math.abs(price - close) <= Math.max(0.01, Math.abs(close) * 0.03) : null,
    `金额 ${tradeValue == null ? '--' : tradeValue.toLocaleString('zh-CN', { maximumFractionDigits: 0 })} 元，佣金 ${fmtMaybe(trade.commission || 0)}，滑点 ${fmtMaybe(trade.slippage_cost || 0)}`,
  ))

  // 仅当卖出且具备数据时记录盈亏（事实，不做规则判定）
  if (!isBuy && (returnRate != null || closeProfit != null)) {
    rows.push(buildDecisionRow(
      '平仓结果',
      '本次卖出实际兑现情况',
      `盈亏 ${closeProfit == null ? '--' : `${closeProfit >= 0 ? '+' : ''}${fmtMaybe(closeProfit)}`} / 收益率 ${returnRate == null ? '--' : `${returnRate >= 0 ? '+' : ''}${fmtMaybe(returnRate)}%`}`,
      null,
      returnRate == null ? '历史结果缺失' : returnRate >= 0 ? '获利兑现' : '亏损退出',
    ))
  }

  // ── 仅追加与本笔 reason 文本相关的指标行 ──
  const hasMA = /MA\d|均线|金叉|死叉|上穿|下穿/i.test(reasonText)
  const hasBOLL = /BOLL|布林|上轨|下轨|中轨/i.test(reasonText)
  const hasRSI = /RSI/i.test(reasonText)
  const hasMACD = /MACD|DIF|DEA|柱/i.test(reasonText)
  const hasVol = /成交量|量能|放量|缩量|换手/i.test(reasonText)
  const hasRisk = /止损|止盈|风控|超时|最大持有|max[_ ]?hold/i.test(reasonText)

  if (hasMA) {
    rows.push(buildDecisionRow(
      '均线快照',
      '策略提及均线 / 金叉死叉，列出当前实际值',
      maCrossText(snapshot) + (ma60 != null ? ` / MA60 ${fmtMaybe(ma60)}` : ''),
      null,
      '事实数据，仅供核对，未做通用阈值判定',
    ))
  }
  if (hasBOLL) {
    rows.push(buildDecisionRow(
      'BOLL 快照',
      '策略提及布林通道，列出当前实际值',
      `收盘 ${fmtMaybe(close)} / 下轨 ${fmtMaybe(bollLower)} / 中轨 ${fmtMaybe(bollMiddle)} / 上轨 ${fmtMaybe(bollUpper)}`,
      null,
      '事实数据，仅供核对',
    ))
  }
  if (hasRSI) {
    rows.push(buildDecisionRow(
      'RSI 快照',
      '策略提及 RSI，列出当前实际值',
      `RSI14 ${fmtMaybe(rsi)}`,
      null,
      '事实数据，仅供核对',
    ))
  }
  if (hasMACD) {
    rows.push(buildDecisionRow(
      'MACD 快照',
      '策略提及 MACD，列出当前实际值',
      `DIF ${fmtMaybe(macdDif)} / DEA ${fmtMaybe(macdDea)} / 柱 ${fmtMaybe(macdHist)}`,
      null,
      '事实数据，仅供核对',
    ))
  }
  if (hasVol) {
    rows.push(buildDecisionRow(
      '量能快照',
      '策略提及量能，列出当前实际值',
      `成交量 ${fmtVolume(volume)} / 量MA5 ${fmtVolume(volMa5)}${fmtIndicatorDiff(volume, volMa5)}`,
      null,
      '事实数据，仅供核对',
    ))
  }
  if (hasRisk) {
    rows.push(buildDecisionRow(
      '风控触发',
      '策略提及止盈 / 止损 / 风控 / 超时',
      reasonText,
      null,
      '由风控或最大持有期等规则触发，详见左列说明',
    ))
  }

  // 没有任何指标关键词命中时（典型自定义策略），不再硬塞 MA/BOLL/RSI/MACD/量能
  // —— 完整指标快照可在下方"指标快照"面板查看
  if (!hasMA && !hasBOLL && !hasRSI && !hasMACD && !hasVol && !hasRisk) {
    rows.push(buildDecisionRow(
      '指标参考',
      '本策略 reason 未点名具体指标',
      '请查看下方"指标快照"面板获取完整 K 线 / 技术指标数据',
      null,
      '避免给出与本策略无关的通用规则判定',
    ))
  }

  return rows
}

function findTradeLogReason(trade: any) {
  const logs = (info.value?.logs || []) as string[]
  const code = String(trade?.code || '')
  if (!code) return ''
  const dirWords = trade.direction === 'buy' ? ['买入', '加仓', '回补'] : ['卖出', '减仓', '清仓', '止损', '退出']
  const hit = logs.slice().reverse().find(line => {
    const text = String(line)
    return text.includes(code) && dirWords.some(w => text.includes(w))
  })
  return hit || ''
}

function tradeDetailHtml(trade: any) {
  const value = N(trade.value || trade.price * trade.amount).toLocaleString('zh-CN', { maximumFractionDigits: 0 })
  const reason = tradeReason(trade)
  const decisionHtml = decisionRowsForTrade(trade, activeIndicatorSnapshot.value).slice(0, 6)
    .map(row => `<br/>${row.name}: ${row.threshold}；实际 ${row.actual}；${row.result}`)
    .join('')
  const name = trade.name ? ` ${trade.name}` : ''
  const extra = trade.direction === 'sell'
    ? `<br/>平仓盈亏: ${(trade.close_profit ?? 0) >= 0 ? '+' : ''}${fmtMaybe(trade.close_profit || 0)}，收益率: ${(trade.return_rate ?? 0) >= 0 ? '+' : ''}${fmtMaybe(trade.return_rate || 0)}%`
    : ''
  return `<b>${trade.date}</b><br/>${directionLabel(trade)} ${trade.code}${name}<br/>价格: ${fmtMaybe(trade.price)}，数量: ${N(trade.amount).toLocaleString()}<br/>成交金额: ${value} 元${extra}<br/>佣金: ${fmtMaybe(trade.commission || 0)}，印花税: ${fmtMaybe(trade.tax || 0)}，滑点: ${fmtMaybe(trade.slippage_cost || 0)}<br/>原因: ${reason}${decisionHtml}`
}

const ddRange = computed(() => {
  const m = M.value
  return (m.max_drawdown_start && m.max_drawdown_end)
    ? `${m.max_drawdown_start} ~ ${m.max_drawdown_end}` : '--'
})

const dailyPnlData = computed(() => info.value?.nav || [])

const selectedStockTrades = computed(() => {
  if (!selectedStock.value?.code) return []
  return ((info.value?.trades || []) as any[])
    .filter(t => t.code === selectedStock.value.code)
    .sort((a, b) => String(a.date).localeCompare(String(b.date)))
})

const stockDialogTitle = computed(() => {
  if (!selectedStock.value) return '个股回测轨迹'
  const name = selectedStock.value.name ? ` ${selectedStock.value.name}` : ''
  return `${selectedStock.value.code}${name} - 回测买卖点与技术指标`
})

const stockPeriodLabel = computed(() => {
  const map: Record<string, string> = { daily: '日K', weekly: '周K', monthly: '月K' }
  return map[stockActivePeriod.value] || '日K'
})

const benchmarkCode = computed(() => normalizeBenchmarkCode(info.value?.benchmark || info.value?.params?.benchmark || '000300'))

const benchmarkSwitchText = computed(() => `显示基准K线(${benchmarkCode.value})`)

const activeIndicatorSnapshot = computed(() => {
  if (!selectedTrade.value) return {}
  return indicatorSnapshot(stockActivePeriod.value, selectedTrade.value)
})

const decisionSummary = computed(() => {
  const trade = selectedTrade.value
  if (!trade) return { action: '--', reason: '--' }
  const action = `${directionLabel(trade)} ${trade.code}${trade.name ? ' ' + trade.name : ''}`
  return { action, reason: tradeReason(trade) }
})

const decisionRows = computed(() => decisionRowsForTrade(selectedTrade.value, activeIndicatorSnapshot.value))

const selectedPositions = computed(() => {
  const pos = info.value?.positions
  if (!pos || pos.length === 0) return []
  if (!selectedPosDate.value) return pos[pos.length - 1].positions || []
  const found = pos.find((p: any) => p.date === selectedPosDate.value)
  return found ? found.positions : []
})

// ── lifecycle ──

/** 清理所有图表实例 */
function disposeAllCharts() {
  chart?.dispose(); chart = null
  pnlChart?.dispose(); pnlChart = null
  tradeChart?.dispose(); tradeChart = null
  disposeStockCharts()
}

function disposeStockCharts() {
  stockDailyChart?.dispose(); stockDailyChart = null
  stockWeeklyChart?.dispose(); stockWeeklyChart = null
  stockMonthlyChart?.dispose(); stockMonthlyChart = null
}

/** 加载回测详情数据 */
async function loadDetail() {
  const id = btId.value
  if (!id) return
  // 清理旧状态
  disposeAllCharts()
  info.value = null
  activeTab.value = 'overview'
  selectedPosDate.value = ''

  loading.value = true
  try {
    const res = await getPortfolioBacktestDetail(id) as any
    info.value = res?.code === 0 ? res.data : res?.data
    if (info.value?.positions?.length) {
      selectedPosDate.value = info.value.positions[info.value.positions.length - 1].date
    }
    lastLoadedId = id
    await nextTick()
    safeRender('overview')
  } finally {
    loading.value = false
  }
}

onMounted(() => loadDetail())

// keep-alive 激活时，检查路由参数是否变化，如有变化则重新加载
onActivated(() => {
  const id = btId.value
  if (id && id !== lastLoadedId) {
    loadDetail()
  }
})

// 同一组件激活期间，路由 :id 参数发生变化时也重新加载
watch(btId, (newId, oldId) => {
  if (newId && newId !== oldId && newId !== lastLoadedId) {
    loadDetail()
  }
})

const onResize = () => {
  chart?.resize(); pnlChart?.resize(); tradeChart?.resize()
  stockDailyChart?.resize(); stockWeeklyChart?.resize(); stockMonthlyChart?.resize()
}
onMounted(() => {
  window.addEventListener('resize', onResize, { passive: true })
  ;(window as any).visualViewport?.addEventListener?.('resize', onResize, { passive: true })
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  ;(window as any).visualViewport?.removeEventListener?.('resize', onResize)
  disposeAllCharts()
})

watch(activeTab, async (tab) => {
  await nextTick()
  safeRender(tab)
})

function safeRender(tab: string) {
  // el-tabs lazy: chart container may have 0 width on first paint
  const map: Record<string, () => void> = {
    overview: renderReturnChart,
    daily_pnl: renderPnlChart,
    trades: renderTradeChart,
  }
  const fn = map[tab]
  if (!fn) return
  setTimeout(() => fn(), 80)
}

// ═══════════════════════════════════════════════════
// Chart 1 — 收益走势（策略 vs 基准 + 超额）
// ═══════════════════════════════════════════════════
function renderReturnChart() {
  const el = chartEl.value
  if (!el || !info.value?.nav?.length) return
  if (el.clientWidth === 0) { setTimeout(renderReturnChart, 120); return }
  if (chart) chart.dispose()
  chart = echarts.init(el, undefined, {
    devicePixelRatio: Math.min(window.devicePixelRatio || 1, 2.5),
    useDirtyRect: true,
  })

  const nav = info.value.nav as any[]
  const dates = nav.map(r => r.date)
  const stratRet = nav.map(r => +(((r.nav ?? 1) - 1) * 100).toFixed(2))
  const bmRet = nav.map(r => +(((r.benchmark_nav ?? 1) - 1) * 100).toFixed(2))
  const excessRet = nav.map((_r, i) => +(stratRet[i] - bmRet[i]).toFixed(2))
  const hasBm = bmRet.some(v => Math.abs(v) > 0.01)

  const legend = ['策略收益']
  const series: any[] = [
    {
      name: '策略收益', type: 'line', yAxisIndex: 0,
      data: stratRet, symbol: 'none',
      lineStyle: { width: 2, color: '#e6a23c' },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(230,162,60,0.22)' },
          { offset: 1, color: 'rgba(230,162,60,0.01)' },
        ]),
      },
    },
  ]
  if (hasBm) {
    legend.push('基准收益', '超额收益')
    series.push(
      {
        name: '基准收益', type: 'line', yAxisIndex: 0,
        data: bmRet, symbol: 'none',
        lineStyle: { width: 1.5, type: 'dashed', color: '#909399' },
      },
      {
        name: '超额收益', type: 'line', yAxisIndex: 0,
        data: excessRet, symbol: 'none',
        lineStyle: { width: 1, color: '#67c23a' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(103,194,58,0.15)' },
            { offset: 1, color: 'rgba(103,194,58,0.01)' },
          ]),
        },
      },
    )
  }

  chart.setOption({
    tooltip: {
      trigger: 'axis',
      formatter(p: any) {
        let h = `<b>${p[0].axisValue}</b>`
        p.forEach((s: any) => {
          h += `<br/>${s.marker} ${s.seriesName}: ${s.value >= 0 ? '+' : ''}${s.value}%`
        })
        return h
      },
    },
    legend: { data: legend, top: 4, textStyle: { fontSize: 11 } },
    grid: { left: isMobile.value ? 38 : 55, right: isMobile.value ? 8 : 20, top: 38, bottom: 36 },
    dataZoom: [{ type: 'inside', start: 0, end: 100 }],
    xAxis: {
      type: 'category', data: dates, boundaryGap: false,
      axisLabel: { fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: '{value}%', fontSize: 10 },
      splitLine: { lineStyle: { type: 'dashed', color: '#eee' } },
    },
    series,
  })
}

// ═══════════════════════════════════════════════════
// Chart 2 — 每日盈亏 柱形图
// ═══════════════════════════════════════════════════
function renderPnlChart() {
  const el = pnlChartEl.value
  if (!el || !info.value?.nav?.length) return
  if (el.clientWidth === 0) { setTimeout(renderPnlChart, 120); return }
  if (pnlChart) pnlChart.dispose()
  pnlChart = echarts.init(el, undefined, {
    devicePixelRatio: Math.min(window.devicePixelRatio || 1, 2.5),
    useDirtyRect: true,
  })

  const nav = info.value.nav as any[]
  const dates = nav.map(r => r.date)
  const dailyRet = nav.map(r => +((r.daily_return ?? 0) * 100).toFixed(3))
  // 每日盈亏金额
  const dailyPnl = nav.map((r: any, i: number) => {
    if (i === 0) return 0
    return +((r.total_value ?? 0) - (nav[i - 1].total_value ?? 0)).toFixed(2)
  })

  pnlChart.setOption({
    tooltip: {
      trigger: 'axis',
      formatter(p: any) {
        const d = p[0].axisValue
        let h = `<b>${d}</b>`
        p.forEach((s: any) => {
          const unit = s.seriesIndex === 0 ? '%' : ' 元'
          h += `<br/>${s.marker} ${s.seriesName}: ${s.seriesIndex === 0 ? (s.value >= 0 ? '+' : '') : ''}${s.value}${unit}`
        })
        return h
      },
    },
    legend: { data: ['日收益率', '日盈亏金额'], top: 4, textStyle: { fontSize: 11 } },
    grid: { left: isMobile.value ? 42 : 60, right: isMobile.value ? 42 : 60, top: 38, bottom: 36 },
    dataZoom: [{ type: 'inside', start: 0, end: 100 }],
    xAxis: {
      type: 'category', data: dates, boundaryGap: true,
      axisLabel: { fontSize: 10 },
    },
    yAxis: [
      {
        type: 'value', name: '日收益率',
        axisLabel: { formatter: '{value}%', fontSize: 10 },
        splitLine: { lineStyle: { type: 'dashed', color: '#eee' } },
      },
      {
        type: 'value', name: '盈亏(元)',
        axisLabel: { fontSize: 10 },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '日收益率', type: 'bar', yAxisIndex: 0,
        data: dailyRet,
        itemStyle: {
          color(p: any) { return p.value >= 0 ? '#f56c6c' : '#67c23a' },
        },
        barMaxWidth: 6,
      },
      {
        name: '日盈亏金额', type: 'line', yAxisIndex: 1,
        data: dailyPnl, symbol: 'none',
        lineStyle: { width: 1, color: '#409eff' },
      },
    ],
  })
}

// ═══════════════════════════════════════════════════
// Chart 3 — 每日买卖 (资金曲线 + 买卖标记)
// ═══════════════════════════════════════════════════
function renderTradeChart() {
  const el = tradeChartEl.value
  if (!el || !info.value?.nav?.length) return
  if (el.clientWidth === 0) { setTimeout(renderTradeChart, 120); return }
  if (tradeChart) tradeChart.dispose()
  tradeChart = echarts.init(el, undefined, {
    devicePixelRatio: Math.min(window.devicePixelRatio || 1, 2.5),
    useDirtyRect: true,
  })

  const nav = info.value.nav as any[]
  const trades = (info.value.trades || []) as any[]
  const dates = nav.map(r => r.date)
  const totalVals = nav.map(r => +(N(r.total_value || 0)).toFixed(0))

  // 构建买入/卖出散点数据
  const dateIdx = new Map<string, number>()
  dates.forEach((d, i) => dateIdx.set(d, i))

  const buyPoints: any[] = []
  const sellPoints: any[] = []
  trades.forEach((t: any) => {
    const idx = dateIdx.get(t.date)
    if (idx == null) return
    const val = totalVals[idx]
    const point = { value: [t.date, val], trade: t }
    if (t.direction === 'buy') buyPoints.push(point)
    else sellPoints.push(point)
  })

  tradeChart.on('click', (params: any) => {
    const trade = params?.data?.trade
    if (trade) openStockTrade(trade)
  })

  tradeChart.setOption({
    tooltip: {
      trigger: 'item',
      formatter(p: any) {
        if (p.seriesType === 'scatter') {
          return tradeDetailHtml(p.data.trade)
        }
        return `<b>${p.name}</b><br/>${p.marker} 总资产: ${N(p.value).toLocaleString()} 元`
      },
    },
    legend: { data: ['总资产', '买入', '卖出'], top: 4, textStyle: { fontSize: 11 } },
    grid: { left: isMobile.value ? 46 : 70, right: isMobile.value ? 8 : 20, top: 38, bottom: 36 },
    dataZoom: [{ type: 'inside', start: 0, end: 100 }],
    xAxis: {
      type: 'category', data: dates, boundaryGap: false,
      axisLabel: { fontSize: 10 },
    },
    yAxis: {
      type: 'value', name: '总资产(元)',
      axisLabel: { fontSize: 10 },
      splitLine: { lineStyle: { type: 'dashed', color: '#eee' } },
      scale: true,
    },
    series: [
      {
        name: '总资产', type: 'line',
        data: totalVals, symbol: 'none',
        lineStyle: { width: 1.5, color: '#409eff' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(64,158,255,0.15)' },
            { offset: 1, color: 'rgba(64,158,255,0.01)' },
          ]),
        },
      },
      {
        name: '买入', type: 'scatter',
        data: buyPoints, symbolSize: 12, symbol: 'triangle',
        itemStyle: { color: '#f56c6c' },
        emphasis: { scale: 1.6 },
      },
      {
        name: '卖出', type: 'scatter',
        data: sellPoints, symbolSize: 12, symbol: 'diamond',
        itemStyle: { color: '#67c23a' },
        emphasis: { scale: 1.6 },
      },
    ],
  })
}

async function openStockTrade(trade: any) {
  selectedStock.value = { code: trade.code, name: trade.name || '' }
  selectedTrade.value = trade
  stockActivePeriod.value = 'daily'
  stockDialogVisible.value = true
  stockLoading.value = true
  stockKlines.value = {}
  benchmarkKlines.value = {}
  disposeStockCharts()
  try {
    const periods: Array<'daily' | 'weekly' | 'monthly'> = ['daily', 'weekly', 'monthly']
    const stockResults = await Promise.all(periods.map(period => getKlineData({
      code: trade.code,
      name: trade.name || '',
      period,
    }) as Promise<any>))
    const benchmarkResults = await Promise.all(periods.map(period => getKlineData({
      code: benchmarkCode.value,
      name: benchmarkCode.value,
      period,
      type: 'index',
    }).catch(() => null) as Promise<any>))
    periods.forEach((period, index) => {
      stockKlines.value[period] = stockResults[index]?.data || stockResults[index]
      const benchmarkResult = benchmarkResults[index]?.data || benchmarkResults[index]
      benchmarkKlines.value[period] = benchmarkResult?.dates?.length ? benchmarkResult : null
    })
    await nextTick()
    renderActiveStockChart()
  } finally {
    stockLoading.value = false
  }
}

function selectTradeInDialog(row: any) {
  selectedTrade.value = row
  renderActiveStockChart()
}

function renderActiveStockChart() {
  setTimeout(() => renderStockChart(stockActivePeriod.value), 80)
}

function getStockChartRef(period: string) {
  if (period === 'weekly') return stockWeeklyEl.value
  if (period === 'monthly') return stockMonthlyEl.value
  return stockDailyEl.value
}

function getStockChart(period: string) {
  if (period === 'weekly') return stockWeeklyChart
  if (period === 'monthly') return stockMonthlyChart
  return stockDailyChart
}

function setStockChart(period: string, instance: echarts.ECharts | null) {
  if (period === 'weekly') stockWeeklyChart = instance
  else if (period === 'monthly') stockMonthlyChart = instance
  else stockDailyChart = instance
}

function renderStockChart(period: 'daily' | 'weekly' | 'monthly') {
  const el = getStockChartRef(period)
  const kline = stockKlines.value[period]
  if (!el || !kline?.dates?.length) return
  if (el.clientWidth === 0) { setTimeout(() => renderStockChart(period), 120); return }
  getStockChart(period)?.dispose()
  const instance = echarts.init(el, undefined, {
    devicePixelRatio: Math.min(window.devicePixelRatio || 1, 2.5),
    useDirtyRect: true,
  })
  setStockChart(period, instance)

  const dates = kline.dates as string[]
  const ohlc = kline.ohlc || []
  const volumes = kline.volumes || []
  const ma = kline.ma || {}
  const boll = kline.boll || {}
  const macd = kline.macd || {}
  const range = stockDataZoomRange(dates)
  const tradeMarkers = buildStockTradeMarkers(kline, period)
  const overlaySeries = buildOverlaySeries(ma, boll)
  const benchmarkOverlay = buildBenchmarkOverlay(period, dates)
  const legendData = ['K线', ...overlaySeries.map(s => s.name), ...(benchmarkOverlay ? [benchmarkOverlay.name] : []), '买入', '卖出']

  // PR-5 自定义指标叠加（仅在当前激活的 period 上注入）
  const ext = (period === stockActivePeriod.value) ? ciOverlay.extension.value
    : { mainSignalSeries: null, subPanel: null, extraXAxisCount: 0 }

  instance.on('click', (params: any) => {
    const trade = params?.data?.trade
    if (trade) selectedTrade.value = trade
  })

  instance.setOption({
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter(params: any[]) {
        const scatter = params.find(p => p.seriesType === 'scatter' && p.data?.trade)
        if (scatter) return tradeDetailHtml(scatter.data.trade)
        const first = params[0]
        const index = first?.dataIndex ?? dates.indexOf(first?.axisValue)
        const candle = ohlc[index] || []
        let html = `<b>${first?.axisValue || ''}</b><br/>开: ${fmtMaybe(candle[0])} 收: ${fmtMaybe(candle[1])} 低: ${fmtMaybe(candle[2])} 高: ${fmtMaybe(candle[3])}`
        html += `<br/>MA5: ${fmtMaybe(ma.ma5?.[index])} MA20: ${fmtMaybe(ma.ma20?.[index])} MA30: ${fmtMaybe(ma.ma30?.[index])} MA60: ${fmtMaybe(ma.ma60?.[index])}`
        if (benchmarkOverlay) html += benchmarkTooltipHtml(benchmarkOverlay, index)
        html += `<br/>BOLL: 上 ${fmtMaybe(boll.upper?.[index])} 中 ${fmtMaybe(boll.middle?.[index])} 下 ${fmtMaybe(boll.lower?.[index])}`
        html += `<br/>RSI14: ${fmtMaybe(kline.rsi?.[index])} MACD: ${fmtMaybe(macd.histogram?.[index])}`
        html += `<br/>成交量: ${N(volumes[index] || 0).toLocaleString()}`
        return html
      },
    },
    legend: { data: legendData, top: 2, textStyle: { fontSize: 11 } },
    title: [
      { text: 'K线主图', subtext: '蜡烛+MA/BOLL叠加，散点为回测交易', left: 60, top: 20, textStyle: { fontSize: 11, color: '#303133', fontWeight: 'bold' as const }, subtextStyle: { fontSize: 9, color: '#909399' }, triggerEvent: true },
      { text: '成交量', subtext: '红涨绿跌·按当日K线方向上色', left: 60, top: 332, textStyle: { fontSize: 11, color: '#303133', fontWeight: 'bold' as const }, subtextStyle: { fontSize: 9, color: '#909399' }, triggerEvent: true },
      { text: 'MACD', subtext: 'DIF/DEA交叉+柱状能量，判趋势强弱', left: 60, top: 422, textStyle: { fontSize: 11, color: '#303133', fontWeight: 'bold' as const }, subtextStyle: { fontSize: 9, color: '#909399' }, triggerEvent: true },
      ...(ext.subPanel ? [{ text: '自定义指标', subtext: '快慢线EMA交叉+策略买卖点(点击查看理由)', left: 60, top: 512, textStyle: { fontSize: 11, color: '#303133', fontWeight: 'bold' as const }, subtextStyle: { fontSize: 9, color: '#909399' }, triggerEvent: true }] : []),
    ],
    grid: [
      { left: 58, right: 62, top: 60, height: 248 },
      { left: 58, right: 62, top: 370, height: 40 },
      { left: 58, right: 62, top: 460, height: 40 },
      ...(ext.subPanel ? [{ left: 58, right: 62, top: 550, height: 60 }] : []),
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: ext.subPanel ? [0, 1, 2, 3] : [0, 1, 2], start: range.start, end: range.end, minSpan: Math.max(5, Math.round(150 / dates.length * 100)) },
      { type: 'slider', xAxisIndex: ext.subPanel ? [0, 1, 2, 3] : [0, 1, 2], start: range.start, end: range.end, bottom: 4, height: 20, minSpan: Math.max(5, Math.round(150 / dates.length * 100)) },
    ],
    xAxis: [
      { type: 'category', data: dates, boundaryGap: true, axisLabel: { fontSize: 10 } },
      { type: 'category', data: dates, gridIndex: 1, axisLabel: { show: false } },
      { type: 'category', data: dates, gridIndex: 2, axisLabel: { fontSize: 10 } },
      ...(ext.subPanel ? [{ type: 'category' as const, data: dates, gridIndex: 3, axisLabel: { fontSize: 10 } }] : []),
    ],
    yAxis: [
      { scale: true, axisLabel: { fontSize: 10 }, splitLine: { lineStyle: { type: 'dashed', color: '#eee' } } },
      { scale: true, gridIndex: 1, axisLabel: { fontSize: 10 }, splitLine: { show: false } },
      { scale: true, gridIndex: 2, axisLabel: { fontSize: 10 }, splitLine: { show: false } },
      ...(benchmarkOverlay ? [{ scale: true, gridIndex: 0, position: 'right', name: benchmarkCode.value, axisLabel: { fontSize: 10 }, splitLine: { show: false } }] : []),
      ...(ext.subPanel ? [{ scale: true, gridIndex: 3, min: 0, max: 100, splitNumber: 3, axisLabel: { fontSize: 10 } }] : []),
    ],
    series: [
      { name: 'K线', type: 'candlestick', data: ohlc, barMaxWidth: 20, barMinWidth: 1, large: true, largeThreshold: 300, itemStyle: { color: '#f56c6c', color0: '#67c23a', borderColor: '#f56c6c', borderColor0: '#67c23a' } },
      ...overlaySeries,
      ...(benchmarkOverlay ? [benchmarkOverlay] : []),
      { name: '买入', type: 'scatter', data: tradeMarkers.buy, symbol: 'triangle', symbolSize: 18, itemStyle: { color: '#f56c6c', borderColor: '#8a1f11', borderWidth: 1 }, label: tradeMarkerLabel('buy'), emphasis: { scale: 1.5 } },
      { name: '卖出', type: 'scatter', data: tradeMarkers.sell, symbol: 'diamond', symbolSize: 17, itemStyle: { color: '#67c23a', borderColor: '#2f6f1f', borderWidth: 1 }, label: tradeMarkerLabel('sell'), emphasis: { scale: 1.5 } },
      { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volumes.map((v: any, i: number) => ({
        value: v,
        itemStyle: { color: (ohlc[i] && Number(ohlc[i][1]) >= Number(ohlc[i][0])) ? '#f56c6c' : '#67c23a' },
      })), barMaxWidth: 8 },
      { name: 'MACD柱', type: 'bar', xAxisIndex: 2, yAxisIndex: 2, data: macd.histogram || [], itemStyle: { color: (p: any) => p.value >= 0 ? '#f56c6c' : '#67c23a' }, barMaxWidth: 8 },
      { name: 'DIF', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: macd.dif || [], symbol: 'none', lineStyle: { width: 1, color: '#e6a23c' } },
      { name: 'DEA', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: macd.dea || [], symbol: 'none', lineStyle: { width: 1, color: '#409eff' } },
      ...(ext.mainSignalSeries ? [{ ...ext.mainSignalSeries, xAxisIndex: 0, yAxisIndex: 0 }] : []),
      ...(ext.subPanel ? ext.subPanel.series.map(s => ({
        ...s, xAxisIndex: 3, yAxisIndex: benchmarkOverlay ? 4 : 3,
      })) : []),
    ],
  })
}

function stockDataZoomRange(dates: string[]) {
  const startDate = String(info.value?.start_date || '')
  const endDate = String(info.value?.end_date || '')
  if (!dates.length || !startDate || !endDate) return { start: 0, end: 100 }
  const firstIdx = dates.findIndex(d => d >= startDate)
  const startIdx = Math.max(0, firstIdx >= 0 ? firstIdx : 0)
  const endRaw = dates.findIndex(d => d >= endDate)
  const endIdx = endRaw >= 0 ? endRaw : dates.length - 1
  return {
    start: Math.max(0, Math.min(100, startIdx / dates.length * 100)),
    end: Math.max(0, Math.min(100, (endIdx + 1) / dates.length * 100)),
  }
}

function buildOverlaySeries(ma: any, boll: any) {
  const selected = new Set(stockOverlayIndicators.value)
  const series: any[] = []
  if (selected.has('MA5')) {
    series.push({ name: 'MA5', type: 'line', data: ma.ma5 || [], symbol: 'none', lineStyle: { width: 1, color: '#e6a23c' } })
  }
  if (selected.has('MA20')) {
    series.push({ name: 'MA20', type: 'line', data: ma.ma20 || [], symbol: 'none', lineStyle: { width: 1, color: '#409eff' } })
  }
  if (selected.has('MA30')) {
    series.push({ name: 'MA30', type: 'line', data: ma.ma30 || [], symbol: 'none', lineStyle: { width: 1, color: '#7f56d9' } })
  }
  if (selected.has('MA60')) {
    series.push({ name: 'MA60', type: 'line', data: ma.ma60 || [], symbol: 'none', lineStyle: { width: 1, color: '#909399' } })
  }
  if (selected.has('BOLL')) {
    series.push(
      { name: 'BOLL上轨', type: 'line', data: boll.upper || [], symbol: 'none', lineStyle: { width: 1, type: 'dashed', color: '#c45656' } },
      { name: 'BOLL中轨', type: 'line', data: boll.middle || [], symbol: 'none', lineStyle: { width: 1, type: 'dashed', color: '#909399' } },
      { name: 'BOLL下轨', type: 'line', data: boll.lower || [], symbol: 'none', lineStyle: { width: 1, type: 'dashed', color: '#529b2e' } },
    )
  }
  return series
}

function normalizeBenchmarkCode(code: any) {
  const text = String(code || '000300').trim()
  const match = text.match(/\d{6}/)
  return match ? match[0] : text
}

function buildBenchmarkOverlay(period: string, dates: string[]) {
  if (!stockShowBenchmark.value) return null
  const benchmark = benchmarkKlines.value[period]
  if (!benchmark?.dates?.length || !dates.length) return null
  const alignedOhlc = alignOhlcToDates(dates, benchmark)
  if (!alignedOhlc.some(item => item !== '-')) return null
  return {
    name: `基准K线(${benchmarkCode.value})`,
    type: 'candlestick',
    xAxisIndex: 0,
    yAxisIndex: 3,
    data: alignedOhlc,
    itemStyle: {
      color: 'rgba(144, 147, 153, 0.28)',
      color0: 'rgba(64, 158, 255, 0.24)',
      borderColor: 'rgba(96, 98, 102, 0.7)',
      borderColor0: 'rgba(64, 158, 255, 0.65)',
    },
    barWidth: '45%',
    barMaxWidth: 20,
    barMinWidth: 1,
    large: true,
    largeThreshold: 300,
    barGap: '-55%',
    z: 1,
  }
}

function alignOhlcToDates(dates: string[], kline: any) {
  const dateIndex = new Map((kline.dates || []).map((date: string, index: number) => [date, index]))
  return dates.map(date => {
    const index = dateIndex.get(date)
    return typeof index === 'number' ? (kline.ohlc?.[index] || '-') : '-'
  })
}

function benchmarkTooltipHtml(benchmarkOverlay: any, index: number) {
  const candle = benchmarkOverlay.data?.[index]
  if (!Array.isArray(candle)) return ''
  return `<br/>${benchmarkOverlay.name}: 开 ${fmtMaybe(candle[0])} 收 ${fmtMaybe(candle[1])} 低 ${fmtMaybe(candle[2])} 高 ${fmtMaybe(candle[3])}`
}

function tradeMarkerLabel(direction: 'buy' | 'sell') {
  return {
    show: true,
    position: direction === 'buy' ? 'bottom' : 'top',
    distance: 6,
    color: direction === 'buy' ? '#a82116' : '#2f6f1f',
    fontSize: 10,
    fontWeight: 600,
    formatter(params: any) {
      const trade = params?.data?.trade
      if (!trade) return direction === 'buy' ? '买' : '卖'
      return `${direction === 'buy' ? '买' : '卖'} ${fmtMaybe(trade.price)}`
    },
  }
}

function buildStockTradeMarkers(kline: any, period: string) {
  const dates = kline.dates || []
  const closeValues = (kline.ohlc || []).map((x: any[]) => x?.[1])
  const buy: any[] = []
  const sell: any[] = []
  selectedStockTrades.value.forEach((trade: any) => {
    const idx = findTradeBarIndex(dates, trade.date, period)
    if (idx < 0) return
    const point = {
      value: [dates[idx], closeValues[idx]],
      trade,
      name: `${directionLabel(trade)} ${trade.code}`,
    }
    if (trade.direction === 'buy') buy.push(point)
    else sell.push(point)
  })
  return { buy, sell }
}

function findTradeBarIndex(dates: string[], tradeDate: string, period: string) {
  if (!dates.length) return -1
  const exact = dates.indexOf(tradeDate)
  if (exact >= 0) return exact
  if (period === 'daily') return -1
  const idx = dates.findIndex(d => d >= tradeDate)
  return idx >= 0 ? idx : dates.length - 1
}

function indicatorSnapshot(period: string, trade: any) {
  const kline = stockKlines.value[period]
  if (!kline?.dates?.length || !trade) return {}
  const idx = findTradeBarIndex(kline.dates, trade.date, period)
  if (idx < 0) return {}
  const candle = kline.ohlc?.[idx] || []
  const prevIdx = idx > 0 ? idx - 1 : -1
  return {
    date: kline.dates[idx],
    open: candle[0],
    close: candle[1],
    low: candle[2],
    high: candle[3],
    volume: kline.volumes?.[idx],
    ma5: kline.ma?.ma5?.[idx],
    ma20: kline.ma?.ma20?.[idx],
    ma30: kline.ma?.ma30?.[idx],
    ma60: kline.ma?.ma60?.[idx],
    bollUpper: kline.boll?.upper?.[idx],
    bollMiddle: kline.boll?.middle?.[idx],
    bollLower: kline.boll?.lower?.[idx],
    rsi: kline.rsi?.[idx],
    macdDif: kline.macd?.dif?.[idx],
    macdDea: kline.macd?.dea?.[idx],
    macdHist: kline.macd?.histogram?.[idx],
    prevClose: prevIdx >= 0 ? kline.ohlc?.[prevIdx]?.[1] : null,
    prevMa5: prevIdx >= 0 ? kline.ma?.ma5?.[prevIdx] : null,
    prevMa20: prevIdx >= 0 ? kline.ma?.ma20?.[prevIdx] : null,
    prevMacdHist: prevIdx >= 0 ? kline.macd?.histogram?.[prevIdx] : null,
    volMa5: kline.vol_ma?.ma5?.[idx],
    volMa10: kline.vol_ma?.ma10?.[idx],
  }
}
</script>

<style scoped>
.bt-detail { padding: 16px 20px; }
.detail-header { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.detail-header h3 { margin: 0; font-size: 16px; }
.header-sub { color: #909399; font-size: 13px; }
.failed-banner { display: flex; align-items: center; justify-content: space-between; gap: 12px; }

/* ── 聚宽风格收益概述表格 ── */
.jq-summary {
  margin-bottom: 18px;
  border: 1px solid #ebeef5; border-radius: 6px; overflow: hidden;
}
.jq-table {
  width: 100%; border-collapse: collapse;
  font-size: 13px;
}
.jq-table td {
  padding: 9px 12px;
  border-bottom: 1px solid #f0f0f0;
}
.jq-table tr:last-child td { border-bottom: none; }
.jq-lbl {
  color: #909399; white-space: nowrap; width: 120px;
  background: #fafafa;
}
.jq-val {
  color: #303133; font-weight: 600; font-variant-numeric: tabular-nums;
  min-width: 90px;
}
.jq-val-sm { font-size: 12px; font-weight: 500; color: #606266; }
.val-red { color: #f56c6c !important; }
.val-green { color: #67c23a !important; }

/* ── Charts ── */
.chart-box { width: 100%; height: 380px; }
.stock-dialog { min-height: 680px; }
.stock-chart-box { width: 100%; height: 530px; }
.stock-chart-box.has-sub { height: 650px; }
.stock-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  margin: 10px 0 6px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  background: #fafafa;
  flex-wrap: wrap;
}
.toolbar-label {
  color: #606266;
  font-size: 13px;
  font-weight: 600;
}
.toolbar-hint {
  color: #909399;
  font-size: 12px;
}
.stock-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(140px, 1fr)) minmax(260px, 2fr);
  gap: 8px;
  margin-bottom: 10px;
}
.summary-item {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 8px 10px;
  background: #fafafa;
  min-width: 0;
}
.summary-item span {
  display: block;
  color: #909399;
  font-size: 12px;
  margin-bottom: 4px;
}
.summary-item b {
  display: block;
  color: #303133;
  font-size: 13px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
.summary-item.wide { grid-column: span 1; }
.indicator-panel {
  margin-top: 10px;
  border-top: 1px solid #ebeef5;
  padding-top: 10px;
}
.decision-panel {
  margin: 10px 0;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 10px;
  background: #fff;
}
.decision-summary {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 8px 10px;
  margin-bottom: 8px;
  background: #fafafa;
  border-radius: 4px;
  color: #606266;
  font-size: 13px;
  line-height: 1.45;
}
.decision-summary span {
  flex: 0 0 auto;
  font-weight: 600;
  color: #303133;
}
.decision-summary b {
  font-weight: 500;
  color: #303133;
  overflow-wrap: anywhere;
}
.decision-table :deep(.el-table__cell) {
  vertical-align: top;
}
.panel-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}
.stock-trade-table { margin-top: 12px; }

/* ── Logs ── */
.log-box {
  max-height: 500px; overflow-y: auto; font-family: 'Consolas', 'Monaco', monospace; font-size: 12px;
  background: #1e1e1e; color: #d4d4d4; padding: 12px; border-radius: 4px;
}
.log-line { white-space: pre-wrap; line-height: 1.5; }
.log-empty { text-align: center; color: #606266; padding: 40px; }

/* ── PR-10 D: 移动端适配 ── */
@media (max-width: 767.98px) {
  .bt-detail { padding: 10px 12px; }
  .detail-header {
    flex-wrap: wrap;
    gap: 6px 10px;
    margin-bottom: 10px;
    h3 { font-size: 15px; }
  }
  .header-sub { font-size: 12px; flex-basis: 100%; }
  .failed-banner {
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
  }
  /* jq-summary 6 列宽表在手机上极拥挤：改为单列双块（lbl/val 横向，每两个一行） */
  .jq-summary { border-radius: 4px; }
  .jq-table { font-size: 12px; }
  .jq-table td { padding: 6px 8px; }
  .jq-lbl { width: auto; font-size: 11px; }
  .jq-val { min-width: 60px; font-size: 12px; }
  .jq-val-sm { font-size: 11px; }
  /* el-tabs 滚动 */
  :deep(.el-tabs__nav-wrap) { padding: 0 6px; }
  :deep(.el-tabs__item) { padding: 0 10px; font-size: 13px; height: 36px; line-height: 36px; }
  .chart-box { height: 280px; }
  .stock-chart-box { height: 360px; }
  .stock-chart-box.has-sub { height: 460px; }
  /* 持仓 / 交易 / 每日盈亏 大表格水平滚动 */
  :deep(.el-table) { font-size: 11px; }
  /* 收益概述网格 → 移动端两列 */
  .stock-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .stock-toolbar { padding: 6px 8px; gap: 6px; }
  .toolbar-label { font-size: 12px; }
  .decision-summary { font-size: 12px; padding: 6px 8px; flex-wrap: wrap; }
}
</style>

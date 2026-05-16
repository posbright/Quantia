<template>
  <div class="portfolio-backtest">
    <!-- 顶部操作栏 -->
    <el-card class="top-bar" shadow="never">
      <div class="toolbar">
        <h3>组合回测</h3>
        <div class="actions">
          <el-select v-model="selectedTemplate" placeholder="加载模板策略" @change="loadTemplate" style="width: 200px; margin-right: 12px;">
            <el-option v-for="t in templates" :key="t.id" :label="t.name" :value="t.id" />
          </el-select>
          <el-button @click="openImportCiDialog" :icon="MagicStick" style="margin-right: 12px;">从自定义指标导入</el-button>
          <el-button type="primary" @click="runBacktest" :loading="running" :icon="CaretRight">运行回测</el-button>
          <el-button @click="saveStrategy" :icon="DocumentAdd">保存策略</el-button>
        </div>
      </div>
    </el-card>

    <!-- 从自定义指标导入对话框 -->
    <el-dialog v-model="ciDialogVisible" title="从自定义指标导入策略" width="720px" :destroy-on-close="false">
      <div class="ci-import-hint">
        <el-icon><InfoFilled /></el-icon>
        仅展示 <strong>kind=primary_entry</strong> 的指标（评分预警类不可驱动交易）。
        选中后将生成包含硬规则与风控参数的策略代码骨架。
      </div>
      <el-table :data="ciList" v-loading="ciLoading" size="small" highlight-current-row
                @row-click="onCiRowClick" :row-class-name="ciRowClass" max-height="420">
        <el-table-column label="名称" min-width="200">
          <template #default="{ row }">
            <div>
              <div style="font-weight: 500;">{{ row.name }}</div>
              <div style="color:#909399; font-size: 12px; font-family: Consolas, monospace;">
                {{ row.indicator_id }}
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="说明" min-width="240">
          <template #default="{ row }">
            <span style="color:#606266; font-size: 12px;">{{ row.description || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="" width="60" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.is_builtin === 1" size="small" type="info" effect="dark">内置</el-tag>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="ciDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmImportCi" :disabled="!ciSelected" :loading="ciImporting">
          导入选中指标
        </el-button>
      </template>
    </el-dialog>

    <el-row :gutter="16" class="main-content">
      <!-- 左侧：策略编辑器 -->
      <el-col :span="12">
        <el-card shadow="never" class="editor-card">
          <template #header>
            <div class="card-header">
              <span>策略代码</span>
              <el-input v-model="strategyName" placeholder="策略名称" style="width: 200px;" size="small" />
            </div>
          </template>
          <div class="editor-wrapper">
            <textarea ref="codeEditor" v-model="strategyCode" class="code-textarea"
                      spellcheck="false" wrap="off" />
          </div>
          <!-- 参数配置 -->
          <div class="params-row">
            <el-date-picker v-model="dateRange" type="daterange" unlink-panels range-separator="至"
                            start-placeholder="开始日期" end-placeholder="结束日期"
                            value-format="YYYY-MM-DD" size="small" style="width: 260px;" />
            <el-input-number v-model="initialCash" :min="10000" :step="100000"
                             size="small" style="width: 150px;" />
            <span class="param-label">初始资金</span>
          </div>
        </el-card>
      </el-col>

      <!-- 右侧：回测结果 + 实时日志 -->
      <el-col :span="12">
        <div class="right-panel">
          <!-- 上部：回测结果 -->
          <el-card shadow="never" class="result-card" v-loading="running && !logLines.length">
            <template #header>
              <div class="card-header">
                <span>回测结果</span>
                <div class="header-tags">
                  <el-tag v-if="running" type="warning" size="small">运行中...</el-tag>
                  <el-tag v-else-if="result?.status === 'completed'" type="success" size="small">完成</el-tag>
                  <el-tag v-else-if="result?.status === 'error'" type="danger" size="small">错误</el-tag>
                  <span v-if="result?.elapsed" class="elapsed-text">耗时 {{ result.elapsed }}s</span>
                </div>
              </div>
            </template>

            <!-- 错误信息 -->
            <el-alert v-if="result?.status === 'error'" :title="result.message"
                      type="error" show-icon :closable="false" style="margin-bottom: 16px;" />

            <!-- 汇总指标 -->
            <div v-if="result?.metrics" class="metrics-grid">
              <div class="metric-item">
                <div class="metric-value" :class="(result.metrics.total_return ?? 0) >= 0 ? 'positive' : 'negative'">
                  {{ (result.metrics.total_return ?? 0).toFixed(2) }}%
                </div>
                <div class="metric-label">累计收益</div>
              </div>
              <div class="metric-item">
                <div class="metric-value" :class="(result.metrics.annual_return ?? 0) >= 0 ? 'positive' : 'negative'">
                  {{ (result.metrics.annual_return ?? 0).toFixed(2) }}%
                </div>
                <div class="metric-label">年化收益</div>
              </div>
              <div class="metric-item">
                <div class="metric-value negative">{{ (result.metrics.max_drawdown ?? 0).toFixed(2) }}%</div>
                <div class="metric-label">最大回撤</div>
              </div>
              <div class="metric-item">
                <div class="metric-value">{{ (result.metrics.sharpe_ratio ?? 0).toFixed(2) }}</div>
                <div class="metric-label">夏普比率</div>
              </div>
              <div class="metric-item">
                <div class="metric-value">{{ result.metrics.trade_count ?? 0 }}</div>
                <div class="metric-label">交易笔数</div>
              </div>
              <div class="metric-item">
                <div class="metric-value">{{ (result.metrics.daily_win_rate ?? 0).toFixed(1) }}%</div>
                <div class="metric-label">日胜率</div>
              </div>
            </div>

            <!-- 净值曲线 -->
            <div v-if="result?.nav?.length" ref="navChartRef" class="nav-chart"></div>

            <!-- 交易明细 -->
            <div v-if="result?.trades?.length" style="margin-top: 16px;">
              <h4>交易明细 ({{ result.trades.length }} 笔)</h4>
              <el-table :data="result.trades" size="small" max-height="300" stripe>
                <el-table-column prop="date" label="日期" width="100" />
                <el-table-column prop="code" label="代码" width="70" />
                <el-table-column prop="direction" label="方向" width="60">
                  <template #default="{ row }">
                    <el-tag :type="row.direction === 'buy' ? 'danger' : 'success'" size="small">
                      {{ row.direction === 'buy' ? '买入' : '卖出' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="price" label="价格" width="80" align="right">
                  <template #default="{ row }">{{ Number(row.price).toFixed(2) }}</template>
                </el-table-column>
                <el-table-column prop="amount" label="数量" width="80" align="right" />
                <el-table-column prop="value" label="金额" width="100" align="right">
                  <template #default="{ row }">{{ Number(row.value).toFixed(0) }}</template>
                </el-table-column>
                <el-table-column prop="commission" label="佣金" width="70" align="right">
                  <template #default="{ row }">{{ Number(row.commission).toFixed(2) }}</template>
                </el-table-column>
              </el-table>
            </div>

            <!-- 空状态 -->
            <el-empty v-if="!result && !running" description="编写策略后点击「运行回测」" />
          </el-card>

          <!-- 下部：实时运行日志面板 -->
          <el-card shadow="never" class="log-card">
            <template #header>
              <div class="card-header">
                <span>
                  运行日志
                  <el-badge v-if="errorCount > 0" :value="errorCount" type="danger" style="margin-left: 8px;" />
                </span>
                <div class="log-actions">
                  <el-tag v-if="running" type="warning" size="small" effect="dark" class="pulse-tag">
                    <el-icon class="is-loading"><Loading /></el-icon> 运行中
                  </el-tag>
                  <el-button size="small" text @click="clearLogs">清空</el-button>
                </div>
              </div>
            </template>
            <div ref="logContainerRef" class="log-container">
              <div v-if="logLines.length === 0 && !running" class="log-empty">等待回测运行...</div>
              <div v-for="(line, i) in logLines" :key="i"
                   class="log-line" :class="{ 'log-error': line.type === 'error', 'log-warn': line.type === 'warn' }">
                <span class="log-text">{{ line.msg }}</span>
              </div>
            </div>
          </el-card>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { CaretRight, DocumentAdd, Loading, MagicStick, InfoFilled } from '@element-plus/icons-vue'
import { getStrategyTemplates, getStrategyCodeList, startPortfolioBacktest, getBacktestTaskResult, saveStrategyCode } from '@/api/stock'
import { listIndicators, getIndicator,
  type IndicatorListItem, type IndicatorRecord } from '@/api/customIndicator'
import * as echarts from 'echarts'

interface LogLine { type: 'log' | 'error' | 'warn'; msg: string }

const templates = ref<any[]>([])
const selectedTemplate = ref('')
const strategyName = ref('我的策略')
const strategyCode = ref(`def initialize(context):
    context.security = '000001'

def handle_data(context, data):
    code = context.security
    price = data[code].close
    if price <= 0:
        return
    ma5 = history(code, 5, 'close')
    if len(ma5) < 5:
        return
    ma_val = ma5.mean()

    if price > ma_val * 1.01 and code not in context.portfolio.positions:
        order_value(code, context.portfolio.available_cash * 0.9)
    elif price < ma_val * 0.99 and code in context.portfolio.positions:
        order_target(code, 0)
`)
const dateRange = ref(['2024-01-01', '2025-01-01'])
const initialCash = ref(1000000)
const running = ref(false)
const result = ref<any>(null)
const navChartRef = ref<HTMLElement>()
const logContainerRef = ref<HTMLElement>()
const logLines = ref<LogLine[]>([])
const errorCount = ref(0)
const savedStrategyId = ref<number | null>(null)
let navChart: echarts.ECharts | null = null
let eventSource: EventSource | null = null

onMounted(async () => {
  try {
    const res: any = await getStrategyTemplates()
    if (res?.code === 0) {
      templates.value = res.data
    }
  } catch (e) {
    console.error('加载模板失败', e)
  }
})

onBeforeUnmount(() => {
  closeEventSource()
  if (navChart) navChart.dispose()
})

function closeEventSource() {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
}

function clearLogs() {
  logLines.value = []
  errorCount.value = 0
}

function appendLog(line: LogLine) {
  logLines.value.push(line)
  if (line.type === 'error') errorCount.value++
  // 自动滚动到底部
  nextTick(() => {
    const el = logContainerRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function loadTemplate(templateId: string) {
  const t = templates.value.find((x: any) => x.id === templateId)
  if (t) {
    strategyCode.value = t.code
    strategyName.value = t.name
    savedStrategyId.value = null
    ElMessage.success(`已加载模板: ${t.name}`)
  }
}

// ===================== 从自定义指标导入 =====================
const ciDialogVisible = ref(false)
const ciList = ref<IndicatorListItem[]>([])
const ciLoading = ref(false)
const ciSelected = ref<string>('')
const ciImporting = ref(false)

const ciRowClass = ({ row }: { row: IndicatorListItem }) =>
  row.indicator_id === ciSelected.value ? 'ci-row-active' : ''

const onCiRowClick = (row: IndicatorListItem) => {
  ciSelected.value = row.indicator_id
}

async function openImportCiDialog() {
  ciDialogVisible.value = true
  ciSelected.value = ''
  ciLoading.value = true
  try {
    ciList.value = await listIndicators('primary_entry')
  } catch (e) {
    ciList.value = []
  } finally {
    ciLoading.value = false
  }
}

function buildStrategyFromIndicator(rec: IndicatorRecord): string {
  const rp = rec.risk_profile || {}
  const stop = Number(rp.stop ?? -0.08)
  const target = Number(rp.target ?? 0.20)
  const maxHold = Number(rp.max_hold ?? 30)
  const hardRules = (rec.hard_rules || '').trim() || '# (未配置硬规则)'
  const extraFilter = (rec.extra_filter || '').trim()
  const desc = (rec.description || '').replace(/\r?\n/g, ' ')

  const headerLines = [
    '# ============================================================',
    `# 自定义指标: ${rec.name}  (${rec.indicator_id})`,
    '# 类型: 主信号 (primary_entry)',
    `# 说明: ${desc || '-'}`,
    '#',
    '# 硬规则 (hard_rules):',
    ...hardRules.split(/\r?\n/).map(l => '#   ' + l),
  ]
  if (extraFilter) {
    headerLines.push('# 附加过滤 (extra_filter):')
    extraFilter.split(/\r?\n/).forEach(l => headerLines.push('#   ' + l))
  }
  headerLines.push(
    '#',
    `# 风控: 止损=${stop}  止盈=${target}  最长持有=${maxHold} 个交易日`,
    '#',
    '# ⚠️ 以下骨架仅作起点；具体指标列(rsi/ma/boll 等)需要根据 hard_rules',
    '#    在 handle_data 中用 attribute_history 取数后自行计算。',
    '# ============================================================',
    '',
  )

  const body = `def initialize(context):
    # TODO: 配置股票池（默认平安银行）
    context.security = '000001'
    # 风控参数（来自指标 risk_profile）
    context.stop_loss = ${stop}
    context.take_profit = ${target}
    context.max_hold_days = ${maxHold}
    # 持仓状态：记录买入日 + 买入价
    context.entry = {}


def handle_data(context, data):
    code = context.security
    bar = data[code]
    if bar is None or bar.close <= 0:
        return
    price = bar.close

    # ===== 止损/止盈/最长持有 出场判断 =====
    if code in context.portfolio.positions and code in context.entry:
        entry_px = context.entry[code]['px']
        held_days = context.entry[code]['days']
        ret = (price - entry_px) / entry_px
        context.entry[code]['days'] = held_days + 1
        if ret <= context.stop_loss or ret >= context.take_profit or held_days >= context.max_hold_days:
            order_target(code, 0)
            context.entry.pop(code, None)
            return

    # ===== 入场信号 (基于硬规则)，需自行实现 =====
    # 示例：取最近 60 日 K 线，计算所需指标，套用 hard_rules：
    #   hist = attribute_history(code, 60, '1d', ['close','high','low','volume'])
    #   close = hist['close']
    #   ma5 = close.rolling(5).mean()
    #   ma20 = close.rolling(20).mean()
    #   rsi14 = ...
    #   sig = (${hardRules.split(/\r?\n/)[0].slice(0, 80)})
    #   if bool(sig.iloc[-1]) and code not in context.portfolio.positions:
    #       order_value(code, context.portfolio.available_cash * 0.95)
    #       context.entry[code] = {'px': price, 'days': 0}
    pass
`
  return headerLines.join('\n') + body
}

async function confirmImportCi() {
  if (!ciSelected.value) return
  ciImporting.value = true
  try {
    const rec = await getIndicator(ciSelected.value)
    strategyCode.value = buildStrategyFromIndicator(rec)
    strategyName.value = `${rec.name} (导入)`
    selectedTemplate.value = ''
    savedStrategyId.value = null
    ciDialogVisible.value = false
    ElMessage.success(`已导入指标 ${rec.name}，请补全 handle_data 中的指标计算`)
  } finally {
    ciImporting.value = false
  }
}

async function runBacktest() {
  if (!strategyCode.value.trim()) {
    ElMessage.warning('请输入策略代码')
    return
  }
  if (!dateRange.value?.[0] || !dateRange.value?.[1]) {
    ElMessage.warning('请选择回测日期范围')
    return
  }

  running.value = true
  result.value = null
  clearLogs()
  appendLog({ type: 'log', msg: `[系统] 正在启动回测 ${dateRange.value[0]} ~ ${dateRange.value[1]} ...` })

  try {
    // 1. 启动异步回测，获取 task_id
    const startRes: any = await startPortfolioBacktest({
      code: strategyCode.value,
      start_date: dateRange.value[0],
      end_date: dateRange.value[1],
      initial_cash: initialCash.value,
    })

    if (startRes?.code !== 0 || !startRes.data?.task_id) {
      ElMessage.error(startRes?.msg || '启动回测失败')
      running.value = false
      return
    }

    const taskId = startRes.data.task_id
    appendLog({ type: 'log', msg: `[系统] 回测任务已提交 (task_id: ${taskId})` })

    // 2. 连接 SSE 日志流
    closeEventSource()
    const sseUrl = `/quantia/api/backtest/portfolio/log_stream?task_id=${taskId}`
    eventSource = new EventSource(sseUrl)

    eventSource.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data)
        if (data.type === 'log') {
          const isWarn = data.msg?.includes('[WARN]') || data.msg?.includes('[WARNING]')
          appendLog({ type: isWarn ? 'warn' : 'log', msg: data.msg })
        } else if (data.type === 'error') {
          appendLog({ type: 'error', msg: `[ERROR] ${data.context}: ${data.error}` })
        } else if (data.type === 'complete') {
          appendLog({ type: 'log', msg: `[系统] 回测完成 (status: ${data.status})` })
        }
      } catch (e) {
        console.warn('log parse error', e)
      }
    }

    eventSource.addEventListener('done', async () => {
      closeEventSource()
      // 3. 获取完整结果
      try {
        const resData: any = await getBacktestTaskResult(taskId)
        if (resData?.code === 0 && resData.data) {
          result.value = resData.data
          if (result.value?.status === 'completed') {
            ElMessage.success(`回测完成，耗时 ${result.value.elapsed}s`)
            // 将回测引擎的日志也追加到面板
            if (result.value.logs) {
              for (const log of result.value.logs) {
                // 避免重复（SSE 已推送的跳过）
                const exists = logLines.value.some(l => l.msg === log)
                if (!exists) appendLog({ type: 'log', msg: log })
              }
            }
            if (result.value.errors?.length) {
              for (const err of result.value.errors) {
                appendLog({ type: 'error', msg: `[${err.context}] ${err.type}: ${err.error}` })
              }
            }
            await nextTick()
            renderNavChart()
          } else if (result.value?.status === 'error') {
            ElMessage.error(result.value.message)
            appendLog({ type: 'error', msg: `[系统] 回测错误: ${result.value.message}` })
          }
        }
      } catch (e: any) {
        ElMessage.error(`获取结果异常: ${e.message}`)
      }
      running.value = false
    })

    eventSource.onerror = () => {
      closeEventSource()
      appendLog({ type: 'error', msg: '[系统] 日志流连接断开' })
      // 降级：直接轮询结果
      pollResult(taskId)
    }

  } catch (e: any) {
    ElMessage.error(`回测异常: ${e.message}`)
    appendLog({ type: 'error', msg: `[系统] ${e.message}` })
    running.value = false
  }
}

async function pollResult(taskId: string) {
  // SSE 失败时的降级轮询
  const maxAttempts = 600 // 最多等 5 分钟
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise(r => setTimeout(r, 500))
    try {
      const res: any = await getBacktestTaskResult(taskId)
      if (res?.code === 0 && res.data?.status !== 'running') {
        result.value = res.data
        if (result.value?.status === 'completed') {
          ElMessage.success(`回测完成，耗时 ${result.value.elapsed}s`)
          if (result.value.logs) {
            for (const log of result.value.logs) {
              appendLog({ type: 'log', msg: log })
            }
          }
          await nextTick()
          renderNavChart()
        } else if (result.value?.status === 'error') {
          ElMessage.error(result.value.message)
        }
        break
      }
    } catch {
      // continue polling
    }
  }
  running.value = false
}

async function saveStrategy() {
  if (!strategyName.value.trim()) {
    ElMessage.warning('请输入策略名称')
    return
  }
  try {
    let strategyId = savedStrategyId.value || undefined
    if (!strategyId) {
      const listRes: any = await getStrategyCodeList()
      const strategies = listRes?.data?.strategies || []
      const existing = strategies.find((item: any) => item.name === strategyName.value.trim())
      if (existing?.id) strategyId = existing.id
    }
    const res: any = await saveStrategyCode({
      id: strategyId,
      name: strategyName.value,
      code: strategyCode.value,
      initial_cash: initialCash.value,
    })
    if (res?.code === 0) {
      savedStrategyId.value = res?.data?.id || strategyId || savedStrategyId.value
      ElMessage.success('策略已保存')
    } else {
      ElMessage.error(res?.msg || '保存失败')
    }
  } catch (e: any) {
    ElMessage.error(`保存异常: ${e.message}`)
  }
}

function renderNavChart() {
  if (!navChartRef.value || !result.value?.nav?.length) return

  if (navChart) {
    navChart.dispose()
  }
  navChart = echarts.init(navChartRef.value)

  const dates = result.value.nav.map((r: any) => r.date)
  const navs = result.value.nav.map((r: any) => (((r.nav ?? 1) - 1) * 100).toFixed(2))
  const benchmarks = result.value.nav.map((r: any) => (((r.benchmark_nav ?? 1) - 1) * 100).toFixed(2))

  navChart.setOption({
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const date = params[0].name
        let html = `<strong>${date}</strong><br/>`
        params.forEach((p: any) => {
          html += `${p.marker} ${p.seriesName}: ${p.value}%<br/>`
        })
        return html
      }
    },
    legend: { data: ['策略收益', '基准收益'], top: 5 },
    grid: { left: 60, right: 20, top: 35, bottom: 30 },
    xAxis: { type: 'category', data: dates, axisLabel: { fontSize: 10 } },
    yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
    series: [
      {
        name: '策略收益', type: 'line', data: navs,
        lineStyle: { width: 2 }, symbol: 'none',
        itemStyle: { color: '#e6a23c' },
        areaStyle: { color: 'rgba(230, 162, 60, 0.1)' }
      },
      {
        name: '基准收益', type: 'line', data: benchmarks,
        lineStyle: { width: 1, type: 'dashed' }, symbol: 'none',
        itemStyle: { color: '#909399' },
      },
    ]
  })
}

// 监听窗口大小变化
window.addEventListener('resize', () => navChart?.resize())
</script>

<style scoped>
.portfolio-backtest {
  padding: 16px;
}
.ci-import-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background: #ecf5ff;
  border: 1px solid #d9ecff;
  border-radius: 4px;
  margin-bottom: 12px;
  color: #409eff;
  font-size: 13px;
}
:deep(.ci-row-active) { background-color: #ecf5ff !important; }
.top-bar {
  margin-bottom: 16px;
}
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.toolbar h3 { margin: 0; }
.main-content {
  min-height: calc(100vh - 200px);
}
.editor-card {
  height: calc(100vh - 200px);
  overflow-y: auto;
}
.right-panel {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 200px);
  gap: 12px;
}
.result-card {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}
.log-card {
  height: 35%;
  min-height: 200px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
}
.log-card :deep(.el-card__body) {
  flex: 1;
  padding: 0;
  overflow: hidden;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.header-tags {
  display: flex;
  align-items: center;
  gap: 8px;
}
.elapsed-text {
  font-size: 12px;
  color: #909399;
}
.editor-wrapper {
  height: 400px;
}
.code-textarea {
  width: 100%;
  height: 100%;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.5;
  padding: 12px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  background: #fafafa;
  resize: none;
  tab-size: 4;
  outline: none;
}
.code-textarea:focus {
  border-color: #409eff;
  background: #fff;
}
.params-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #ebeef5;
}
.param-label {
  font-size: 12px;
  color: #909399;
}
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
.metric-item {
  text-align: center;
  padding: 12px;
  background: #f5f7fa;
  border-radius: 6px;
}
.metric-value {
  font-size: 20px;
  font-weight: bold;
  color: #303133;
}
.metric-value.positive { color: #f56c6c; }
.metric-value.negative { color: #67c23a; }
.metric-label {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.nav-chart {
  width: 100%;
  height: 300px;
}
/* 日志面板样式 */
.log-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.log-container {
  height: 100%;
  overflow-y: auto;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.5;
  background: #1a1a2e;
  color: #c8d6e5;
  padding: 8px 12px;
}
.log-empty {
  color: #576574;
  font-style: italic;
  padding: 20px;
  text-align: center;
}
.log-line {
  padding: 1px 0;
  border-bottom: 1px solid rgba(255,255,255,0.03);
  white-space: pre-wrap;
  word-break: break-all;
}
.log-line.log-error {
  color: #ff6b6b;
  background: rgba(255, 107, 107, 0.08);
}
.log-line.log-warn {
  color: #feca57;
}
.log-text {
  user-select: text;
}
/* 呼吸灯动画 */
.pulse-tag {
  animation: pulse 1.5s infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
</style>

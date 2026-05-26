<template>
  <div class="algo-editor">
    <!-- 工具栏 -->
    <div class="editor-toolbar">
      <div class="toolbar-left">
        <el-button text @click="$router.push('/algo/list')"><el-icon><ArrowLeft /></el-icon> 返回</el-button>
        <el-divider direction="vertical" />
        <span class="strategy-name" v-if="!editingName" @dblclick="editingName = true">
          {{ strategy.name || '未命名策略' }}
        </span>
        <el-input v-else v-model="strategy.name" size="small" style="width: 200px;"
                  @blur="editingName = false; doSave()" @keyup.enter="editingName = false; doSave()" />
      </div>
      <div class="toolbar-right">
        <el-button @click="aiDrawerVisible = true" :icon="MagicStick" type="success" plain>AI 助手</el-button>
        <el-divider direction="vertical" />
        <el-button @click="doSave" :icon="DocumentChecked" :loading="saving">
          {{ dirty ? '保存 *' : '已保存' }}
        </el-button>
        <el-divider direction="vertical" />
        <el-dropdown trigger="click" @command="applyDateShortcut" style="margin-right: 4px;">
          <el-button size="small">快捷 <el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-for="s in dateShortcuts" :key="s.text" :command="s.text">{{ s.text }}</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-date-picker v-model="btStartDate" type="date" size="small"
                        placeholder="开始日期" value-format="YYYY-MM-DD" style="width: 130px;" />
        <span class="param-label">至</span>
        <el-date-picker v-model="btEndDate" type="date" size="small"
                        placeholder="结束日期" value-format="YYYY-MM-DD" style="width: 130px;" />
        <el-input-number v-model="btCash" :min="10000" :step="100000" size="small"
                         style="width: 130px;" :controls="false" />
        <span class="param-label">元</span>
        <el-button type="primary" @click="doRun" :loading="running" :icon="CaretRight">运行回测</el-button>
        <el-button @click="doCreatePaper" :icon="Monitor" :disabled="!strategy.id">创建模拟</el-button>
        <el-button text @click="$router.push({ path: '/algo/backtests', query: strategy.id ? { strategy_id: strategy.id } : {} })">回测历史</el-button>
      </div>
    </div>

    <div class="editor-main">
      <!-- 左：代码 -->
      <div class="code-panel">
        <div class="panel-header">
          <span>策略代码</span>
          <span class="save-hint" v-if="dirty">● 未保存</span>
        </div>
        <textarea v-model="strategy.code" class="code-editor" spellcheck="false" wrap="off"
                  @input="dirty = true" @keydown.ctrl.s.prevent="doSave" />
      </div>
      <!-- 右：结果 + 日志 -->
      <div class="right-panel">
        <!-- 上：结果区域 -->
        <div class="result-panel" v-if="showResults">
          <el-tabs v-model="activeTab">
            <el-tab-pane label="概览" name="overview">
              <div v-if="btResult?.status === 'error'" style="padding: 12px;">
                <el-alert :title="btResult.message" type="error" show-icon :closable="false" />
                <!-- error 路径下也展示诊断 hints -->
                <div v-if="zeroTradeHints.length > 0" class="zero-trade-hints" style="margin-top: 8px;">
                  <el-alert type="error" :closable="false" show-icon
                            title="系统针对此次失败给出以下诊断与改进建议">
                    <template #default>
                      <ul style="padding-left: 18px; margin: 6px 0;">
                        <li v-for="(h, i) in zeroTradeHints" :key="i" style="margin-bottom: 6px;">
                          <strong>{{ h.title }}</strong>
                          <span style="color: #606266;"> — {{ h.suggestion }}</span>
                        </li>
                      </ul>
                      <div style="text-align: right; margin-top: 8px;">
                        <el-button size="small" type="primary" @click="repairWithHints">
                          一键让 AI 根据建议修复策略
                        </el-button>
                      </div>
                    </template>
                  </el-alert>
                </div>
              </div>
              <div v-if="btResult?.metrics" class="result-overview">
                <div class="metrics-row">
                  <div class="metric" v-for="m in metricCards" :key="m.key">
                    <div class="metric-val" :class="m.cls">{{ m.val }}</div>
                    <div class="metric-lbl">{{ m.label }}</div>
                  </div>
                </div>
                <!-- 0 笔交易诊断与改进建议 -->
                <div v-if="zeroTradeHints.length > 0" class="zero-trade-hints">
                  <el-alert type="warning" :closable="false" show-icon
                            title="本次回测全程 0 笔交易 — 系统给出以下诊断与改进建议">
                    <template #default>
                      <ul style="padding-left: 18px; margin: 6px 0;">
                        <li v-for="(h, i) in zeroTradeHints" :key="i" style="margin-bottom: 6px;">
                          <strong>{{ h.title }}</strong>
                          <span style="color: #606266;"> — {{ h.suggestion }}</span>
                        </li>
                      </ul>
                      <div style="text-align: right; margin-top: 8px;">
                        <el-button size="small" type="primary" @click="repairWithHints">
                          一键让 AI 根据建议修复策略
                        </el-button>
                      </div>
                    </template>
                  </el-alert>
                </div>
                <div ref="chartEl" class="nav-chart"></div>
                <div v-if="btBacktestId" style="text-align: right; padding: 4px 8px;">
                  <el-button type="primary" link @click="$router.push('/algo/backtest-detail/' + btBacktestId)">
                    查看完整回测详情 →
                  </el-button>
                </div>
              </div>
            </el-tab-pane>
            <el-tab-pane :label="'交易(' + (btResult?.trades?.length || 0) + ')'" name="trades">
              <el-table :data="btResult?.trades || []" size="small" max-height="calc(50vh - 160px)" stripe>
                <el-table-column prop="date" label="日期" width="100" />
                <el-table-column prop="code" label="代码" width="70" />
                <el-table-column prop="direction" label="方向" width="55">
                  <template #default="{ row }">
                    <span :style="{ color: row.direction === 'buy' ? '#f56c6c' : '#67c23a', fontWeight: 600 }">
                      {{ row.direction === 'buy' ? '买' : '卖' }}
                    </span>
                  </template>
                </el-table-column>
                <el-table-column prop="price" label="价格" width="80" align="right">
                  <template #default="{ row }">{{ Number(row.price).toFixed(2) }}</template>
                </el-table-column>
                <el-table-column prop="amount" label="数量" width="80" align="right" />
                <el-table-column prop="value" label="金额" width="100" align="right">
                  <template #default="{ row }">{{ Number(row.value).toFixed(0) }}</template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
            <el-tab-pane label="持仓" name="positions">
              <el-table :data="lastPositions" size="small" max-height="calc(50vh - 160px)" stripe>
                <el-table-column prop="code" label="代码" width="70" />
                <el-table-column prop="amount" label="持仓" width="80" align="right" />
                <el-table-column prop="avg_cost" label="成本" width="80" align="right">
                  <template #default="{ row }">{{ Number(row.avg_cost).toFixed(2) }}</template>
                </el-table-column>
                <el-table-column prop="price" label="现价" width="80" align="right">
                  <template #default="{ row }">{{ Number(row.price).toFixed(2) }}</template>
                </el-table-column>
                <el-table-column prop="profit_rate" label="盈亏" width="80" align="right">
                  <template #default="{ row }">
                    <span :style="{ color: (row.profit_rate ?? 0) >= 0 ? '#f56c6c' : '#67c23a' }">
                      {{ Number(row.profit_rate ?? 0).toFixed(1) }}%
                    </span>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
          </el-tabs>
        </div>
        <div class="result-panel placeholder" v-else>
          <div class="placeholder-content">
            <el-icon :size="48" color="#c0c4cc"><DataLine /></el-icon>
            <p>点击「运行回测」查看结果</p>
            <p class="tips">Ctrl+S 保存</p>
          </div>
        </div>

        <!-- 下：实时日志面板 -->
        <div class="log-panel" :class="{ 'log-running': running }">
          <div class="log-panel-header">
            <span>运行日志</span>
            <span v-if="running" class="log-status running">● 运行中...</span>
            <span v-if="logErrorCount > 0" class="log-error-badge">{{ logErrorCount }} 错误</span>
            <el-button v-if="logLines.length" size="small" text @click="logLines = []; logErrorCount = 0">清空</el-button>
          </div>
          <div ref="logContainer" class="log-content">
            <div v-for="(line, i) in logLines" :key="i" class="log-line-item"
                 :class="{ 'log-error': line.type === 'error', 'log-warn': line.type === 'warn' }">
              {{ line.msg }}
            </div>
            <div v-if="!logLines.length" class="log-empty">等待回测运行...</div>
          </div>
        </div>
      </div>
    </div>

    <!-- AI 助手抽屉（M2 最小版） -->
    <AiChatDrawer
      v-model="aiDrawerVisible"
      :current-code="strategy.code"
      :strategy-id="strategy.id || undefined"
      :strategy-name="strategy.name || undefined"
      :backtest-start-date="btStartDate"
      :backtest-end-date="btEndDate"
      :backtest-initial-cash="btCash"
      :initial-prompt="aiPrefillPrompt"
      :default-mode="aiPrefillPrompt ? 'refine' : undefined"
      @apply="onAiApply"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick, watch, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, ArrowDown, DocumentChecked, CaretRight, Monitor, DataLine, MagicStick } from '@element-plus/icons-vue'
import { getStrategyCodeDetail, saveStrategyCode, startPortfolioBacktest, getBacktestTaskResult, createPaperTrading } from '@/api/stock'
import AiChatDrawer from '@/components/AiChatDrawer.vue'
import * as echarts from 'echarts'

interface LogLine { type: 'log' | 'error' | 'warn'; msg: string }

const route = useRoute()
const router = useRouter()
const strategyId = computed(() => Number(route.params.id))

const strategy = ref<any>({ id: 0, name: '', code: '' })

// 从 localStorage 恢复回测参数（上次设置的日期和金额）
const _STORAGE_KEY_DATE = 'bt_date_range'
const _STORAGE_KEY_CASH = 'bt_cash'

function loadSavedDateRange(): [string, string] {
  try {
    const saved = localStorage.getItem(_STORAGE_KEY_DATE)
    if (saved) {
      const arr = JSON.parse(saved)
      if (Array.isArray(arr) && arr.length === 2 && arr[0] && arr[1]) {
        return [arr[0], arr[1]]
      }
    }
  } catch { /* ignore */ }
  // 默认：最近1年
  const e = new Date()
  const s = new Date()
  s.setFullYear(s.getFullYear() - 1)
  const fmt = (d: Date) => d.toISOString().slice(0, 10)
  return [fmt(s), fmt(e)]
}

function loadSavedCash(): number {
  try {
    const v = localStorage.getItem(_STORAGE_KEY_CASH)
    if (v) {
      const n = Number(v)
      if (n >= 10000) return n
    }
  } catch { /* ignore */ }
  return 1000000
}

const _savedRange = loadSavedDateRange()
const btStartDate = ref<string>(_savedRange[0])
const btEndDate = ref<string>(_savedRange[1])
const btCash = ref(loadSavedCash())

// 持久化回测参数
watch([btStartDate, btEndDate], ([s, e]) => {
  if (s && e) {
    localStorage.setItem(_STORAGE_KEY_DATE, JSON.stringify([s, e]))
  }
})

watch(btCash, (val) => {
  if (val >= 10000) {
    localStorage.setItem(_STORAGE_KEY_CASH, String(val))
  }
})
const btResult = ref<any>(null)
const showResults = ref(false)
const running = ref(false)
const saving = ref(false)
const dirty = ref(false)
const editingName = ref(false)
const activeTab = ref('overview')
const aiDrawerVisible = ref(false)
const chartEl = ref<HTMLElement>()
const btBacktestId = ref<number | null>(null)
const logLines = ref<LogLine[]>([])
const logErrorCount = ref(0)
const logContainer = ref<HTMLElement>()
let chart: echarts.ECharts | null = null
let eventSource: EventSource | null = null
let currentTaskId: string | null = null

const dateShortcuts = [
  { text: '近1年', value: () => { const e = new Date(); const s = new Date(); s.setFullYear(s.getFullYear()-1); return [s, e] }},
  { text: '近2年', value: () => { const e = new Date(); const s = new Date(); s.setFullYear(s.getFullYear()-2); return [s, e] }},
  { text: '2024全年', value: () => [new Date('2024-01-01'), new Date('2024-12-31')] },
]

function applyDateShortcut(text: string) {
  const sc = dateShortcuts.find(s => s.text === text)
  if (!sc) return
  const range = typeof sc.value === 'function' ? sc.value() : sc.value
  const fmt = (d: Date) => d.toISOString().slice(0, 10)
  btStartDate.value = fmt(range[0])
  btEndDate.value = fmt(range[1])
}

const metricCards = computed(() => {
  const m = btResult.value?.metrics
  if (!m) return []
  const f = (v: number, d = 2) => v == null ? '--' : `${v >= 0 ? '+' : ''}${Number(v).toFixed(d)}%`
  const n = (v: number, d = 3) => v == null ? '--' : Number(v).toFixed(d)
  const c = (v: number) => v == null ? '' : v >= 0 ? 'val-red' : 'val-green'
  return [
    { key: 'ret', label: '策略收益', val: f(m.total_return), cls: c(m.total_return) },
    { key: 'annual', label: '策略年化收益', val: f(m.annual_return), cls: c(m.annual_return) },
    { key: 'excess', label: '超额收益', val: f(m.excess_return), cls: c(m.excess_return) },
    { key: 'bm', label: '基准收益', val: f(m.benchmark_return), cls: c(m.benchmark_return) },
    { key: 'sharpe', label: '夏普比率', val: n(m.sharpe_ratio), cls: '' },
    { key: 'dd', label: '最大回撤', val: f(-m.max_drawdown), cls: 'val-green' },
    { key: 'alpha', label: 'Alpha', val: n(m.alpha), cls: '' },
    { key: 'beta', label: 'Beta', val: n(m.beta), cls: '' },
    { key: 'sortino', label: '索提诺比率', val: n(m.sortino_ratio), cls: '' },
    { key: 'plr', label: '盈亏比', val: n(m.profit_loss_ratio), cls: '' },
    { key: 'wr', label: '日胜率', val: f(m.daily_win_rate, 1), cls: '' },
    { key: 'tc', label: '交易次数', val: String(m.trade_count ?? 0), cls: '' },
  ]
})

const lastPositions = computed(() => {
  const p = btResult.value?.positions
  return (p && p.length > 0) ? p[p.length - 1].positions || [] : []
})

// Helper: extract response data regardless of axios unwrap
function unwrap(res: any) {
  // After axios interceptor unwrap, res is {code:0, data:{...}}
  if (res?.code === 0) return { ok: true, data: res.data, msg: '' }
  if (res?.data?.code === 0) return { ok: true, data: res.data.data, msg: '' }
  return { ok: false, data: null, msg: res?.msg || res?.data?.msg || '操作失败' }
}

onMounted(async () => {
  if (strategyId.value) {
    try {
      const res = await getStrategyCodeDetail(strategyId.value) as any
      const { ok, data } = unwrap(res)
      if (ok && data) {
        strategy.value = data
        dirty.value = false  // 刚加载，标记为已保存
      }
    } catch (e) {
      ElMessage.error('加载策略失败')
    }
  }
  // M4：检查回测详情页是否传来"AI 修复结果"
  applyPendingAiRepair()
})

/** M4：从 sessionStorage 读取回测详情页跳转过来的 AI 修复代码并应用 */
const AI_REPAIR_TTL_MS = 60 * 60 * 1000  // P2-A：1 小时 TTL，避免应用过期 payload
function applyPendingAiRepair() {
  try {
    const raw = sessionStorage.getItem('ai-repair-pending')
    if (!raw) return
    const payload = JSON.parse(raw)
    if (!payload || !payload.code) {
      sessionStorage.removeItem('ai-repair-pending')
      return
    }
    // P2-A：TTL 校验
    if (payload.ts && (Date.now() - Number(payload.ts)) > AI_REPAIR_TTL_MS) {
      sessionStorage.removeItem('ai-repair-pending')
      return
    }
    // P1-6a（七轮）：payload 缺失 strategy_id 不应静默应用，以免误被另一个
    // 策略页面误使用（该分支依然会清理 sessionStorage，由 P0-2 以后的设计决定）
    if (!payload.strategy_id) {
      sessionStorage.removeItem('ai-repair-pending')
      return
    }
    // P1-A：strategy_id 不匹配时也必须清掉 key，避免下次错配
    if (Number(payload.strategy_id) !== strategyId.value) {
      // 不删除：用户可能正路由切回正确策略；但限制只在 TTL 内重试
      return
    }
    sessionStorage.removeItem('ai-repair-pending')
    strategy.value.code = payload.code
    if (payload.meta) {
      aiMeta.value = payload.meta
      aiAppliedSnapshot.value = payload.code
    }
    dirty.value = true
    ElMessage.success(
      payload.backtest_id
        ? `已加载来自回测 #${payload.backtest_id} 的 AI 修复代码，请审阅后保存`
        : '已加载 AI 修复代码，请审阅后保存'
    )
  } catch (e) {
    // P2-6b（七轮）：JSON 解析失败时清理损坏 payload，避免重复报错
    sessionStorage.removeItem('ai-repair-pending')
    console.warn('[edit.vue] applyPendingAiRepair 失败', e)
  }
}

async function doSave() {
  if (!strategy.value.code?.trim()) { ElMessage.warning('代码为空'); return }
  saving.value = true
  try {
    const res = await saveStrategyCode({
      id: strategy.value.id || undefined,
      name: strategy.value.name || '未命名策略',
      code: strategy.value.code,
      description: strategy.value.description || '',
      initial_cash: btCash.value,
      ...(aiMeta.value ? aiMeta.value : {}),
    }) as any
    const { ok, data, msg } = unwrap(res)
    if (ok) {
      if (!strategy.value.id && data?.id) {
        strategy.value.id = data.id
        // 新建策略保存成功后，将 URL 中的 /new 替换为真实 ID（不留历史项）
        try {
          router.replace({ path: `/algo/edit/${data.id}` })
        } catch { /* ignore */ }
      }
      dirty.value = false
      aiMeta.value = null  // 已落库，下次保存默认按手工
      aiAppliedSnapshot.value = ''
      ElMessage.success('已保存')
    } else {
      ElMessage.error(msg)
    }
  } finally {
    saving.value = false
  }
}

async function doRun() {
  if (!strategy.value.code?.trim()) { ElMessage.warning('请输入策略代码'); return }
  if (!btStartDate.value || !btEndDate.value) { ElMessage.warning('请选择回测日期'); return }
  if (dirty.value) await doSave()

  running.value = true
  showResults.value = false
  btResult.value = null
  logLines.value = []
  logErrorCount.value = 0
  addLog('log', '正在启动回测...')

  try {
    // 使用异步启动接口，立即返回 task_id
    const res = await startPortfolioBacktest({
      code: strategy.value.code,
      strategy_id: strategy.value.id || undefined,
      strategy_name: strategy.value.name || undefined,
      start_date: btStartDate.value,
      end_date: btEndDate.value,
      initial_cash: btCash.value,
    }) as any
    const { ok, data } = unwrap(res)
    if (!ok || !data?.task_id) {
      addLog('error', '启动回测失败: ' + (data?.message || '未知错误'))
      running.value = false
      return
    }

    currentTaskId = data.task_id
    addLog('log', '回测已启动 (task_id: ' + currentTaskId + ')')

    // 建立 SSE 连接接收实时日志
    closeEventSource()
    const sseUrl = `/quantia/api/backtest/portfolio/log_stream?task_id=${currentTaskId}`
    eventSource = new EventSource(sseUrl)

    eventSource.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data)
        if (msg.type === 'log') {
          addLog('log', msg.msg)
        } else if (msg.type === 'error') {
          addLog('error', msg.msg)
        }
      } catch {
        addLog('log', ev.data)
      }
    }

    eventSource.addEventListener('done', async () => {
      closeEventSource()
      addLog('log', '回测完成，正在获取结果...')
      await fetchResult(currentTaskId!)
    })

    eventSource.onerror = () => {
      closeEventSource()
      // SSE 失败则回退到轮询
      if (currentTaskId) {
        addLog('warn', '日志流连接中断，切换到轮询模式...')
        pollResult(currentTaskId)
      }
    }
  } catch (e: any) {
    addLog('error', '回测异常: ' + (e.message || '未知错误'))
    running.value = false
  }
}

function closeEventSource() {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
}

function addLog(type: 'log' | 'error' | 'warn', msg: string) {
  logLines.value.push({ type, msg })
  if (type === 'error') logErrorCount.value++
  // 自动滚动到底部
  nextTick(() => {
    if (logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight
    }
  })
}

async function fetchResult(taskId: string) {
  try {
    const res = await getBacktestTaskResult(taskId) as any
    const { ok, data } = unwrap(res)
    if (ok && data) {
      btResult.value = data
      showResults.value = true
      if (data.status === 'completed') {
        ElMessage.success('回测完成 (' + data.elapsed + 's)')
        btBacktestId.value = data.backtest_id || null
        activeTab.value = 'overview'
        addLog('log', `回测结束 | 收益: ${data.metrics?.total_return?.toFixed(2) ?? '--'}% | 交易: ${data.trades?.length ?? 0} 次`)
        await nextTick()
        setTimeout(() => renderChart(), 100)
      } else if (data.status === 'error') {
        addLog('error', '回测出错: ' + data.message)
        ElMessage.error(data.message)
      }
    }
  } catch (e: any) {
    addLog('error', '获取结果失败: ' + (e.message || '未知'))
  } finally {
    running.value = false
  }
}

async function pollResult(taskId: string) {
  const maxAttempts = 600  // 最长等待 10 分钟 (600 * 1s)
  let attempts = 0
  const poll = async () => {
    attempts++
    try {
      const res = await getBacktestTaskResult(taskId) as any
      const { ok, data } = unwrap(res)
      if (ok && data && data.status !== 'running') {
        btResult.value = data
        showResults.value = true
        if (data.status === 'completed') {
          ElMessage.success('回测完成 (' + data.elapsed + 's)')
          btBacktestId.value = data.backtest_id || null
          activeTab.value = 'overview'
          addLog('log', `回测结束 | 收益: ${data.metrics?.total_return?.toFixed(2) ?? '--'}% | 交易: ${data.trades?.length ?? 0} 次`)
          await nextTick()
          setTimeout(() => renderChart(), 100)
        } else if (data.status === 'error') {
          addLog('error', '回测出错: ' + data.message)
        }
        running.value = false
        return
      }
    } catch { /* continue polling */ }
    if (attempts < maxAttempts) {
      setTimeout(poll, 1000)
    } else {
      addLog('error', '回测超时，请稍后查看回测历史')
      running.value = false
    }
  }
  poll()
}

const handleChartResize = () => { chart?.resize() }

onBeforeUnmount(() => {
  closeEventSource()
  window.removeEventListener('resize', handleChartResize)
  chart?.dispose()
  chart = null
})

async function doCreatePaper() {
  if (!strategy.value.id) { ElMessage.warning('请先保存策略'); return }
  try {
    const res = await createPaperTrading({
      strategy_id: strategy.value.id,
      backtest_id: btBacktestId.value,
      name: '模拟-' + strategy.value.name,
      initial_cash: btCash.value,
      run_frequency: 'daily',
    }) as any
    const { ok, data } = unwrap(res)
    if (ok) {
      ElMessage.success('模拟盘已创建')
      if (data?.backtest_id) btBacktestId.value = data.backtest_id
      router.push('/algo/paper')
    } else {
      ElMessage.error(data?.msg || '创建失败')
    }
  } catch (e: any) { ElMessage.error(e?.message || '创建失败') }
}

function renderChart() {
  if (!chartEl.value || !btResult.value?.nav?.length) return
  // 确保元素有尺寸（el-tabs 可能还没完成布局）
  if (chartEl.value.clientWidth === 0) {
    setTimeout(() => renderChart(), 100)
    return
  }
  if (chart) chart.dispose()
  chart = echarts.init(chartEl.value)
  const nav = btResult.value.nav
  const hasBenchmark = nav.some((r: any) => r.benchmark_nav != null && Math.abs(r.benchmark_nav - 1) > 0.0001)
  const legend = ['策略收益']
  const series: any[] = [
    { name: '策略收益', type: 'line', data: nav.map((r: any) => (((r.nav ?? 1) - 1) * 100).toFixed(2)),
      symbol: 'none', lineStyle: { width: 2, color: '#e6a23c' },
      areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
        { offset: 0, color: 'rgba(230,162,60,0.25)' }, { offset: 1, color: 'rgba(230,162,60,0.02)' }]) }},
  ]
  if (hasBenchmark) {
    legend.push('基准收益')
    series.push(
      { name: '基准收益', type: 'line', data: nav.map((r: any) => (((r.benchmark_nav ?? 1) - 1) * 100).toFixed(2)),
        symbol: 'none', lineStyle: { width: 1.5, type: 'dashed', color: '#909399' }},
    )
  }
  chart.setOption({
    tooltip: { trigger: 'axis', formatter: (p: any) => {
      let h = `<b>${p[0].name}</b><br/>`
      p.forEach((s: any) => { h += `${s.marker} ${s.seriesName}: ${s.value}%<br/>` })
      return h
    }},
    legend: { data: legend, top: 5 },
    grid: { left: 55, right: 15, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: nav.map((r: any) => r.date), axisLabel: { fontSize: 10 } },
    yAxis: { type: 'value', axisLabel: { formatter: '{value}%', fontSize: 10 } },
    series,
  })
}

watch(() => route.params.id, async (newId) => {
  if (newId) {
    const res = await getStrategyCodeDetail(Number(newId)) as any
    const { ok, data } = unwrap(res)
    if (ok && data) {
      strategy.value = data
      showResults.value = false
      btResult.value = null
      dirty.value = false
      // P1-B：路由切换到 payload 目标策略时也尝试应用
      applyPendingAiRepair()
    }
  }
})

// 切换 Tab 回 overview 时重绘图表
watch(activeTab, async (tab) => {
  if (tab === 'overview' && btResult.value?.nav?.length) {
    await nextTick()
    setTimeout(() => renderChart(), 50)
  }
})

window.addEventListener('resize', handleChartResize)

// AI 助手：把生成代码灌入编辑器
const aiMeta = ref<{ source: 'ai'; ai_prompt: string; ai_agent: string; ai_model?: string } | null>(null)
// 应用 AI 代码后的快照，用于检测用户是否在此基础上手工修改
const aiAppliedSnapshot = ref<string>('')
function onAiApply(newCode: string, meta: { source: 'ai'; ai_prompt: string; ai_agent: string; ai_model?: string }) {
  strategy.value.code = newCode
  aiMeta.value = meta
  aiAppliedSnapshot.value = newCode
  dirty.value = true
}
// F2：用户在 AI 应用基础上手工修改代码 → 立即作废 ai 元数据
watch(() => strategy.value.code, (newCode) => {
  if (aiMeta.value && newCode !== aiAppliedSnapshot.value) {
    aiMeta.value = null
    aiAppliedSnapshot.value = ''
  }
})

// ── 0 笔交易 / 失败 → 显示诊断提示 + 一键 AI 修复 ────────────────────
// 引擎对 status='completed'/'error' 两种情形都会在 result.hints 上挂诊断
// 列表（错误时来自 _diagnose_engine_error，0 笔交易来自 _diagnose_zero_trades）。
const zeroTradeHints = computed(() => {
  const r = btResult.value
  if (!r) return [] as Array<{ title: string; suggestion: string; severity?: string }>
  const hints = (r.hints || []) as Array<any>
  return Array.isArray(hints) ? hints : []
})

const aiPrefillPrompt = ref('')
function repairWithHints() {
  if (!zeroTradeHints.value.length) return
  const lines = zeroTradeHints.value.map((h, i) => `${i + 1}. ${h.title} — ${h.suggestion}`).join('\n')
  // 上下文：本次回测的实际现象（trade_count / status / errors / order_stats）
  const r = btResult.value || ({} as any)
  const tc = r.metrics?.trade_count ?? 0
  const stats = r.order_stats || {}
  const statsLine = Object.keys(stats).length
    ? Object.entries(stats).filter(([, v]) => Number(v) > 0)
        .map(([k, v]) => `${k}=${v}`).join(', ')
    : ''
  const contextLines: string[] = []
  contextLines.push(`回测状态: ${r.status || 'unknown'}, 交易笔数: ${tc}`)
  if (r.status === 'error' && r.message) {
    contextLines.push(`引擎错误信息: ${r.message}`)
  }
  if (statsLine) {
    contextLines.push(`订单执行统计: ${statsLine}`)
  }
  if (Array.isArray(r.errors) && r.errors.length) {
    contextLines.push(`策略异常: 共 ${r.errors.length} 次，首条: ${(r.errors[0]?.error || '').slice(0, 200)}`)
  }
  aiPrefillPrompt.value =
    `上次回测出现问题，系统针对本次具体运行情况给出以下诊断与改进建议，请基于实际现象（而非通用建议）改写当前代码：\n\n` +
    `## 本次回测实际现象\n${contextLines.join('\n')}\n\n` +
    `## 系统诊断（基于实际遥测，非通用模板）\n${lines}\n\n` +
    `## 改写要求\n` +
    `1) 保留原策略的方向性逻辑（不要把多 AND 条件全删/改成 OR）；\n` +
    `2) 必须针对上述"本次实际现象"作出修改，不要做与本次现象无关的改动；\n` +
    `3) 输出完整可运行的 Python 源码（含 initialize 与 handle_data），不要只给 diff；\n` +
    `4) 严禁引入新的未导入模块，禁止 eval/exec/open 等高危 API。`
  aiDrawerVisible.value = true
}
</script>

<style scoped>
.algo-editor { display: flex; flex-direction: column; height: 100dvh; overflow: hidden; }
.editor-toolbar {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 16px; border-bottom: 1px solid #ebeef5; background: #fff; flex-shrink: 0;
}
.toolbar-left, .toolbar-right { display: flex; align-items: center; gap: 8px; }
.strategy-name { font-size: 15px; font-weight: 600; cursor: pointer; }
.param-label { font-size: 12px; color: #909399; }
.editor-main { display: flex; flex: 1; overflow: hidden; }
.code-panel { flex: 1; display: flex; flex-direction: column; border-right: 1px solid #ebeef5; }
.panel-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 12px; background: #f5f7fa; border-bottom: 1px solid #ebeef5;
  font-size: 13px; font-weight: 500; flex-shrink: 0;
}
.save-hint { color: #e6a23c; font-size: 12px; }
.code-editor {
  flex: 1; width: 100%; border: none; outline: none; resize: none;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 13px; line-height: 1.6; padding: 12px;
  background: #1e1e1e; color: #d4d4d4; tab-size: 4;
}
.right-panel { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.result-panel { flex: 1; display: flex; flex-direction: column; overflow: hidden; min-height: 0; }
.result-panel.placeholder { display: flex; align-items: center; justify-content: center; }
.placeholder-content { text-align: center; color: #c0c4cc; }
.placeholder-content p { margin: 8px 0; }
.placeholder-content .tips { font-size: 12px; }
.result-overview { padding: 12px; overflow-y: auto; }
.metrics-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 12px; }
.metric { text-align: center; padding: 10px 8px; background: #f5f7fa; border-radius: 6px; }
.metric-val { font-size: 16px; font-weight: 700; color: #303133; }
.metric-lbl { font-size: 11px; color: #909399; margin-top: 2px; }
.val-red { color: #f56c6c !important; }
.val-green { color: #67c23a !important; }
.nav-chart { width: 100%; height: 280px; }

/* 实时日志面板 */
.log-panel {
  height: 200px; min-height: 120px; flex-shrink: 0;
  border-top: 1px solid #ebeef5; display: flex; flex-direction: column;
}
.log-panel-header {
  display: flex; align-items: center; gap: 10px;
  padding: 6px 12px; background: #1a1a2e; border-bottom: 1px solid #2a2a4a;
  font-size: 12px; font-weight: 600; color: #a0a0c0; flex-shrink: 0;
}
.log-status.running { color: #67c23a; animation: pulse 1.5s infinite; }
.log-error-badge {
  background: #f56c6c; color: #fff; font-size: 11px; padding: 1px 8px;
  border-radius: 10px; font-weight: 600;
}
.log-content {
  flex: 1; overflow-y: auto; background: #1a1a2e; color: #c8c8e0;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 12px; line-height: 1.6; padding: 8px 12px;
}
.log-line-item { white-space: pre-wrap; word-break: break-all; }
.log-line-item.log-error { color: #ff6b6b; }
.log-line-item.log-warn { color: #ffd93d; }
.log-empty { text-align: center; color: #606680; padding: 20px; }
.log-panel.log-running .log-panel-header { border-bottom-color: #67c23a33; }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

/* ── PR-10 E: 移动端适配 ── */
@media (max-width: 991.98px) {
  .editor-toolbar {
    flex-direction: column;
    align-items: stretch;
    gap: 6px;
    padding: 8px 10px;
  }
  .toolbar-left, .toolbar-right {
    flex-wrap: wrap;
    gap: 6px;
  }
  .strategy-name { font-size: 14px; }
  .param-label { font-size: 11px; }
  .editor-main {
    flex-direction: column;
    overflow-y: auto;
  }
  .code-panel {
    flex: none;
    height: 45dvh;
    border-right: none;
    border-bottom: 1px solid #ebeef5;
  }
  .right-panel {
    flex: none;
    min-height: 55dvh;
  }
  .code-editor { font-size: 12px; padding: 8px; }
  .nav-chart { height: 220px; }
  .metrics-row { grid-template-columns: repeat(2, 1fr); }
  .metric-val { font-size: 14px; }
  .log-panel { height: 160px; }
}
@media (max-width: 575.98px) {
  .toolbar-right {
    /* 把日期 + 资金折成一行多列 */
    :deep(.el-date-editor.el-input) { width: 130px !important; }
    :deep(.el-input-number) { width: 110px !important; }
  }
  .metrics-row { grid-template-columns: repeat(2, 1fr); }
}
</style>

<template>
  <div class="custom-indicator-page">
    <el-row :gutter="12" class="ci-row">
      <!-- ============================ 左侧列表 ============================ -->
      <el-col :span="7">
        <div class="ci-panel">
          <div class="ci-panel-header">
            <span class="ci-title">指标库</span>
            <div>
              <el-button size="small" type="primary" @click="onCreate">+ 新建</el-button>
              <el-button size="small" @click="loadList">刷新</el-button>
            </div>
          </div>
          <div class="ci-filter-row">
            <el-radio-group v-model="filterKind" size="small" @change="loadList">
              <el-radio-button :label="''">全部</el-radio-button>
              <el-radio-button label="primary_entry">主信号</el-radio-button>
              <el-radio-button label="watchlist_alert">预警类</el-radio-button>
            </el-radio-group>
          </div>
          <el-table :data="list" v-loading="loadingList" size="small" highlight-current-row
                    @row-click="onRowClick" :row-class-name="rowClass" max-height="calc(100dvh - 220px)">
            <el-table-column label="名称" min-width="160">
              <template #default="{ row }">
                <div class="ci-name-cell">
                  <span class="ci-name">{{ row.name }}</span>
                  <span class="ci-id">{{ row.indicator_id }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="类型" width="80" align="center">
              <template #default="{ row }">
                <el-tag size="small" :type="row.kind === 'primary_entry' ? 'success' : 'warning'" effect="plain">
                  {{ row.kind === 'primary_entry' ? '主信号' : '预警' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="" width="55" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.is_builtin === 1" size="small" type="info" effect="dark">内置</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-col>

      <!-- ============================ 右侧编辑器 ============================ -->
      <el-col :span="17">
        <div class="ci-panel ci-edit-panel" v-loading="loadingDetail">
          <!-- 顶部工具栏 -->
          <div class="ci-panel-header">
            <span class="ci-title">
              {{ isNew ? '新建自定义指标' : (form.name || form.indicator_id || '编辑指标') }}
              <el-tag v-if="form.is_builtin === 1" type="info" size="small" effect="dark"
                      style="margin-left: 8px;">内置预设（只读）</el-tag>
            </span>
            <div>
              <el-button size="small" @click="onSaveAs" :disabled="!form.indicator_id">另存为新指标</el-button>
              <el-button size="small" type="primary" @click="onSave"
                         :loading="saving" :disabled="form.is_builtin === 1">
                {{ isNew ? '创建' : '保存' }}
              </el-button>
              <el-popconfirm title="确认删除该指标？此操作不可撤销。" @confirm="onDelete"
                             v-if="!isNew && form.is_builtin !== 1">
                <template #reference>
                  <el-button size="small" type="danger" plain :loading="deleting">删除</el-button>
                </template>
              </el-popconfirm>
            </div>
          </div>

          <!-- 评分类警示横幅 -->
          <el-alert v-if="form.kind === 'watchlist_alert'" type="warning" show-icon :closable="false"
                    style="margin-bottom: 12px;">
            <template #title>
              <strong>⚠️ 评分类指标</strong> — 仅做今日值得关注列表，
              <span style="color:#c45656;">禁止直接驱动交易</span>
              （历史回测会使用未来信息，PF 失真）
            </template>
          </el-alert>

          <el-form :model="form" label-width="120px" size="small" v-if="form.indicator_id || isNew">
            <!-- ============= 基本信息 ============= -->
            <el-divider content-position="left">基本信息</el-divider>
            <el-row :gutter="12">
              <el-col :span="12">
                <el-form-item label="指标 ID" required>
                  <el-input v-model="form.indicator_id" :disabled="!isNew"
                            placeholder="例如 my_oversold_v1（小写字母/数字/下划线，2-50 字）" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="名称" required>
                  <el-input v-model="form.name" :maxlength="64" placeholder="例如 我的超卖反弹策略" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="12">
              <el-col :span="12">
                <el-form-item label="指标类型">
                  <el-radio-group v-model="form.kind" :disabled="form.is_builtin === 1">
                    <el-radio label="primary_entry">主信号（可驱动交易/回测）</el-radio>
                    <el-radio label="watchlist_alert">评分预警（仅今日关注榜）</el-radio>
                  </el-radio-group>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="说明">
                  <el-input v-model="form.description" type="textarea" :rows="1" :maxlength="256"
                            placeholder="一句话描述指标用途" />
                </el-form-item>
              </el-col>
            </el-row>

            <!-- ============= 硬规则（kind=primary_entry） ============= -->
            <template v-if="form.kind === 'primary_entry'">
              <el-divider content-position="left">
                硬规则表达式
                <el-tooltip placement="top" effect="light">
                  <template #content>
                    <div style="max-width: 360px; line-height: 1.6;">
                      使用 pandas 风格表达式，<code>d</code> 为日线 DataFrame。可用列示例：
                      <code>close, ma5, ma20, rsi14, kdj_k, boll_lower, macd_hist, vol_ratio_5</code> 等。<br/>
                      只能使用 <code>&amp; | ~ &lt; &gt; &lt;= &gt;= == != + - * /</code>，
                      不允许 <code>import / open / __xx__</code>。<br/>
                      返回值需为布尔 Series。
                    </div>
                  </template>
                  <el-icon style="cursor: help; vertical-align: middle;"><QuestionFilled /></el-icon>
                </el-tooltip>
              </el-divider>
              <div class="rule-quick-bar">
                <span class="rule-tip">快捷插入：</span>
                <el-button size="small" link type="primary"
                           v-for="snip in ruleSnippets" :key="snip.label"
                           @click="insertSnippet(snip.code)">{{ snip.label }}</el-button>
              </div>
              <el-form-item label="hard_rules">
                <textarea v-model="form.hard_rules" class="rule-editor" spellcheck="false"
                          :disabled="form.is_builtin === 1"
                          placeholder="例如：(d['rsi14'] < 30) & (d['close'] > d['boll_lower'])" />
              </el-form-item>
              <el-form-item label="extra_filter">
                <textarea v-model="form.extra_filter" class="rule-editor rule-editor-small"
                          spellcheck="false" :disabled="form.is_builtin === 1"
                          placeholder="可选；附加过滤条件 AND 收紧信号" />
              </el-form-item>
            </template>

            <!-- ============= 权重表（kind=watchlist_alert 必有，primary_entry 可选） ============= -->
            <template v-if="form.kind === 'watchlist_alert' || hasWeights">
              <el-divider content-position="left">
                评分权重 ({{ weightRows.length }} 项)
                <el-button v-if="form.kind === 'primary_entry' && hasWeights"
                           link size="small" type="danger" @click="clearWeights"
                           :disabled="form.is_builtin === 1">清空</el-button>
              </el-divider>
              <el-table :data="weightRows" size="small" border style="margin-bottom: 8px;">
                <el-table-column label="因子" min-width="280">
                  <template #default="{ row }">
                    <el-select v-model="row.key" filterable allow-create
                               :disabled="form.is_builtin === 1" style="width: 100%;"
                               placeholder="选择或输入归一化因子（n_*）">
                      <el-option v-for="opt in NORMALIZED_FACTORS" :key="opt.value"
                                 :label="opt.label" :value="opt.value" />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column label="权重" width="120">
                  <template #default="{ row }">
                    <el-input-number v-model="row.weight" :min="0" :max="1" :step="0.05"
                                     :precision="3" :controls="false"
                                     :disabled="form.is_builtin === 1" style="width: 100%;" />
                  </template>
                </el-table-column>
                <el-table-column label="" width="60" align="center">
                  <template #default="{ $index }">
                    <el-button link type="danger" :disabled="form.is_builtin === 1"
                               @click="weightRows.splice($index, 1)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
              <div style="margin-bottom: 12px;">
                <el-button size="small" @click="weightRows.push({ key: '', weight: 0.1 })"
                           :disabled="form.is_builtin === 1">+ 添加因子</el-button>
                <span class="weight-sum" :class="{ 'weight-warn': weightSumOff }">
                  权重合计：{{ weightSum.toFixed(3) }}
                  <span v-if="weightSumOff">（建议合计接近 1.0）</span>
                </span>
              </div>
            </template>

            <!-- ============= 触发参数 ============= -->
            <el-divider content-position="left">触发参数</el-divider>
            <el-row :gutter="12">
              <el-col :span="6">
                <el-form-item label="EMA 平滑">
                  <el-input-number v-model="form.smooth_ema" :min="0" :max="20" :step="1"
                                   :disabled="form.is_builtin === 1" style="width: 100%;" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="买点阈值">
                  <el-input-number v-model="form.buy_th" :min="0" :max="100" :step="1"
                                   :disabled="form.is_builtin === 1" style="width: 100%;" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="阈值方向">
                  <el-radio-group v-model="form.direction" :disabled="form.is_builtin === 1">
                    <el-radio label="low">low（评分越低越买，超卖型）</el-radio>
                    <el-radio label="high">high（评分越高越买，趋势型）</el-radio>
                  </el-radio-group>
                </el-form-item>
              </el-col>
            </el-row>

            <!-- ============= 风控参数 ============= -->
            <el-divider content-position="left">风控参数（回测使用）</el-divider>
            <el-row :gutter="12">
              <el-col :span="8">
                <el-form-item label="止损">
                  <el-input-number v-model="riskStop" :min="-0.5" :max="0" :step="0.01"
                                   :precision="3" :disabled="form.is_builtin === 1" style="width: 100%;" />
                  <span class="form-hint">如 -0.08 表示 8% 止损</span>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="止盈">
                  <el-input-number v-model="riskTarget" :min="0" :max="2" :step="0.05"
                                   :precision="3" :disabled="form.is_builtin === 1" style="width: 100%;" />
                  <span class="form-hint">如 0.20 表示 20% 止盈</span>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="最长持有">
                  <el-input-number v-model="riskMaxHold" :min="1" :max="365" :step="1"
                                   :disabled="form.is_builtin === 1" style="width: 100%;" />
                  <span class="form-hint">交易日数</span>
                </el-form-item>
              </el-col>
            </el-row>

            <!-- ============= 实时回测 ============= -->
            <el-divider content-position="left">实时单股回测</el-divider>
            <div class="bt-bar">
              <el-input v-model="btCode" placeholder="股票代码（6位）" style="width: 140px;" />
              <el-date-picker v-model="btStart" type="date" value-format="YYYY-MM-DD"
                              placeholder="开始" style="width: 150px;" />
              <span class="bt-sep">至</span>
              <el-date-picker v-model="btEnd" type="date" value-format="YYYY-MM-DD"
                              placeholder="结束" style="width: 150px;" />
              <el-button type="primary" @click="onBacktest" :loading="bting"
                         :disabled="!form.indicator_id || isNew || form.kind === 'watchlist_alert'">
                运行回测
              </el-button>
              <span v-if="form.kind === 'watchlist_alert'" class="bt-hint">
                评分类指标禁用回测，请在「今日关注」中查看
              </span>
              <el-button v-if="form.kind === 'watchlist_alert'" size="small" link type="primary"
                         @click="onWatchlist" :loading="wlLoading">
                查看今日关注 →
              </el-button>
            </div>

            <!-- 回测结果 -->
            <div v-if="btSummary" class="bt-result">
              <div class="bt-metrics">
                <div class="bt-metric"><span>交易次数</span><b>{{ btSummary.trades ?? '-' }}</b></div>
                <div class="bt-metric"><span>胜率</span><b>{{ btSummary['win%'] ?? '-' }}%</b></div>
                <div class="bt-metric"><span>盈亏比 PF</span><b>{{ btSummary.PF ?? '-' }}</b></div>
                <div class="bt-metric"><span>平均收益</span><b>{{ btSummary['avg%'] ?? '-' }}%</b></div>
                <div class="bt-metric"><span>期望收益</span><b>{{ btSummary['expectancy%'] ?? '-' }}%</b></div>
                <div class="bt-metric"><span>平均持仓</span><b>{{ btSummary.avg_hold ?? '-' }} 日</b></div>
              </div>
              <el-table :data="btTrades" size="small" max-height="300" stripe>
                <el-table-column prop="entry_date" label="买入日" width="110" />
                <el-table-column prop="entry_price" label="买入价" width="80" align="right">
                  <template #default="{ row }">{{ Number(row.entry_price).toFixed(2) }}</template>
                </el-table-column>
                <el-table-column prop="exit_date" label="卖出日" width="110" />
                <el-table-column prop="exit_price" label="卖出价" width="80" align="right">
                  <template #default="{ row }">{{ Number(row.exit_price).toFixed(2) }}</template>
                </el-table-column>
                <el-table-column prop="hold_days" label="持有(日)" width="80" align="right" />
                <el-table-column prop="net_ret_pct" label="收益" width="90" align="right">
                  <template #default="{ row }">
                    <span :style="{ color: row.net_ret_pct >= 0 ? '#f56c6c' : '#67c23a', fontWeight: 600 }">
                      {{ Number(row.net_ret_pct).toFixed(2) }}%
                    </span>
                  </template>
                </el-table-column>
                <el-table-column prop="reason" label="离场原因" />
              </el-table>
            </div>

            <!-- 今日关注 -->
            <div v-if="wlItems.length" class="bt-result">
              <div class="bt-watchlist-title">
                今日关注 Top {{ wlItems.length }}
                <span v-if="wlWarn" class="wl-warning">{{ wlWarn }}</span>
              </div>
              <el-table :data="wlItems" size="small" max-height="400" stripe>
                <el-table-column type="index" label="#" width="50" />
                <el-table-column prop="code" label="代码" width="80" />
                <el-table-column prop="name" label="名称" />
                <el-table-column prop="latest_score" label="评分" width="100" align="right">
                  <template #default="{ row }">
                    {{ row.latest_score != null ? Number(row.latest_score).toFixed(2) : '-' }}
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </el-form>

          <el-empty v-else description="从左侧选择一个指标进行编辑，或点击「+ 新建」" />
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, reactive, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { QuestionFilled } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import {
  listIndicators, getIndicator, saveIndicator, deleteIndicator,
  backtestIndicator, watchlistToday,
  NORMALIZED_FACTORS,
  type IndicatorListItem, type IndicatorRecord, type IndicatorKind,
  type BacktestSummary, type BacktestTrade, type WatchlistItem,
} from '@/api/customIndicator'

// ===================== 列表状态 =====================
const list = ref<IndicatorListItem[]>([])
const loadingList = ref(false)
const filterKind = ref<IndicatorKind | ''>('')
const selectedId = ref<string>('')

const loadList = async () => {
  loadingList.value = true
  try {
    list.value = await listIndicators(filterKind.value || undefined)
  } catch (e) {
    list.value = []
  } finally {
    loadingList.value = false
  }
}

const rowClass = ({ row }: { row: IndicatorListItem }) =>
  row.indicator_id === selectedId.value ? 'ci-row-active' : ''

// ===================== 编辑状态 =====================
const isNew = ref(false)
const loadingDetail = ref(false)
const saving = ref(false)
const deleting = ref(false)

const blankForm = (): IndicatorRecord => ({
  indicator_id: '',
  name: '',
  kind: 'primary_entry',
  description: '',
  weights: {},
  smooth_ema: 0,
  buy_th: 0,
  direction: 'low',
  hard_rules: '',
  extra_filter: '',
  risk_profile: { stop: -0.08, target: 0.20, max_hold: 30 },
  is_builtin: 0,
})
const form = reactive<IndicatorRecord>(blankForm())

// 权重表行
interface WeightRow { key: string; weight: number }
const weightRows = ref<WeightRow[]>([])

const hasWeights = computed(() => weightRows.value.length > 0)
const weightSum = computed(() =>
  weightRows.value.reduce((s, r) => s + (Number(r.weight) || 0), 0))
const weightSumOff = computed(() => Math.abs(weightSum.value - 1.0) > 0.05)

// 风控字段单独绑定，避免 risk_profile 嵌套响应丢失
const riskStop = ref(-0.08)
const riskTarget = ref(0.20)
const riskMaxHold = ref(30)

const fillForm = (r: Partial<IndicatorRecord>) => {
  Object.assign(form, blankForm(), r)
  weightRows.value = Object.entries(form.weights || {})
    .map(([k, v]) => ({ key: k, weight: Number(v) || 0 }))
  const rp = form.risk_profile || {}
  riskStop.value = rp.stop ?? -0.08
  riskTarget.value = rp.target ?? 0.20
  riskMaxHold.value = rp.max_hold ?? 30
  // 清空回测面板
  btSummary.value = null
  btTrades.value = []
  wlItems.value = []
  wlWarn.value = ''
}

const collectForm = (): Partial<IndicatorRecord> => {
  const weights: Record<string, number> = {}
  for (const r of weightRows.value) {
    if (r.key && r.weight > 0) weights[r.key] = Number(r.weight)
  }
  return {
    indicator_id: form.indicator_id.trim(),
    name: form.name.trim(),
    kind: form.kind,
    description: form.description || '',
    weights,
    smooth_ema: form.smooth_ema,
    buy_th: form.buy_th,
    direction: form.direction,
    hard_rules: form.hard_rules || '',
    extra_filter: form.extra_filter || '',
    risk_profile: {
      stop: riskStop.value,
      target: riskTarget.value,
      max_hold: riskMaxHold.value,
    },
  }
}

// ===================== 列表 / 编辑联动 =====================
const onRowClick = async (row: IndicatorListItem) => {
  selectedId.value = row.indicator_id
  isNew.value = false
  loadingDetail.value = true
  try {
    const rec = await getIndicator(row.indicator_id)
    fillForm(rec)
  } finally {
    loadingDetail.value = false
  }
}

const onCreate = () => {
  isNew.value = true
  selectedId.value = ''
  fillForm({ indicator_id: '', name: '', kind: 'primary_entry' })
}

const onSaveAs = async () => {
  try {
    const { value } = await ElMessageBox.prompt(
      '请输入新指标 ID（小写字母/数字/下划线，2-50 字）',
      '另存为新指标',
      {
        inputPattern: /^[a-z][a-z0-9_]{1,49}$/,
        inputErrorMessage: 'ID 格式不正确',
        inputValue: form.indicator_id ? `${form.indicator_id}_copy` : '',
      })
    const payload = collectForm()
    payload.indicator_id = value
    payload.name = `${form.name} 副本`
    saving.value = true
    await saveIndicator(payload)
    ElMessage.success('已另存为新指标')
    await loadList()
    const newRow = list.value.find(r => r.indicator_id === value)
    if (newRow) await onRowClick(newRow)
  } catch (e: any) {
    if (e !== 'cancel') console.error(e)
  } finally {
    saving.value = false
  }
}

const onSave = async () => {
  if (form.is_builtin === 1) {
    ElMessage.warning('内置预设不可修改，请使用「另存为新指标」')
    return
  }
  const payload = collectForm()
  if (!payload.indicator_id) { ElMessage.error('请输入指标 ID'); return }
  if (!payload.name) { ElMessage.error('请输入名称'); return }
  saving.value = true
  try {
    await saveIndicator(payload)
    ElMessage.success(isNew.value ? '创建成功' : '保存成功')
    const wasNew = isNew.value
    isNew.value = false
    selectedId.value = payload.indicator_id!
    await loadList()
    if (wasNew) {
      const row = list.value.find(r => r.indicator_id === selectedId.value)
      if (row) await onRowClick(row)
    }
  } finally {
    saving.value = false
  }
}

const onDelete = async () => {
  if (!form.indicator_id || form.is_builtin === 1) return
  deleting.value = true
  try {
    await deleteIndicator(form.indicator_id)
    ElMessage.success('已删除')
    fillForm(blankForm())
    selectedId.value = ''
    isNew.value = false
    await loadList()
  } finally {
    deleting.value = false
  }
}

const clearWeights = () => { weightRows.value = [] }

// ===================== 硬规则快捷片段 =====================
const ruleSnippets = [
  { label: 'RSI<30',         code: "(d['rsi14'] < 30)" },
  { label: '收盘>布林下轨',   code: "(d['close'] > d['boll_lower'])" },
  { label: 'MA5上穿MA20',    code: "((d['ma5'] > d['ma20']) & (d['ma5'].shift() <= d['ma20'].shift()))" },
  { label: 'MACD金叉',        code: "((d['macd_hist'] > 0) & (d['macd_hist'].shift() <= 0))" },
  { label: '量比>1.5',        code: "(d['vol_ratio_5'] > 1.5)" },
  { label: 'KDJ K<20',        code: "(d['kdj_k'] < 20)" },
  { label: 'AND组合',         code: ' & ' },
  { label: 'OR组合',          code: ' | ' },
]
const insertSnippet = (snip: string) => {
  if (form.is_builtin === 1) return
  const sep = form.hard_rules && !/[\s|&(]$/.test(form.hard_rules) ? ' ' : ''
  form.hard_rules = (form.hard_rules || '') + sep + snip
}

// ===================== 回测 / 今日关注 =====================
const btCode = ref('000001')
const btStart = ref(dayjs().subtract(2, 'year').format('YYYY-MM-DD'))
const btEnd = ref(dayjs().format('YYYY-MM-DD'))
const bting = ref(false)
const btSummary = ref<BacktestSummary | null>(null)
const btTrades = ref<BacktestTrade[]>([])

const onBacktest = async () => {
  if (!form.indicator_id || isNew.value) {
    ElMessage.warning('请先保存指标后再回测')
    return
  }
  bting.value = true
  try {
    const r = await backtestIndicator({
      indicator_id: form.indicator_id,
      code: btCode.value.trim(),
      start: btStart.value,
      end: btEnd.value,
    })
    btSummary.value = r.summary
    btTrades.value = r.trades || []
  } finally {
    bting.value = false
  }
}

const wlLoading = ref(false)
const wlItems = ref<WatchlistItem[]>([])
const wlWarn = ref('')
const onWatchlist = async () => {
  if (!form.indicator_id || isNew.value) return
  wlLoading.value = true
  try {
    const r = await watchlistToday(form.indicator_id, 50)
    wlItems.value = r.items || []
    wlWarn.value = r.warning || ''
  } finally {
    wlLoading.value = false
  }
}

// kind 切换时清空不相关字段提示
watch(() => form.kind, (k) => {
  if (k === 'watchlist_alert' && form.direction === 'low') {
    // V5 实证：评分类用 high
    form.direction = 'high'
  }
})

onMounted(loadList)
</script>

<style scoped>
.custom-indicator-page { padding: 8px; }
.ci-row { margin: 0 !important; }

.ci-panel {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 12px;
  min-height: calc(100dvh - 110px);
}
.ci-edit-panel { padding-bottom: 24px; }
.ci-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #f0f0f0;
}
.ci-title { font-size: 14px; font-weight: 600; }
.ci-filter-row { margin-bottom: 8px; }

.ci-name-cell { display: flex; flex-direction: column; line-height: 1.3; }
.ci-name { font-weight: 500; }
.ci-id { color: #909399; font-size: 12px; font-family: 'Consolas', monospace; }

:deep(.ci-row-active) { background-color: #ecf5ff !important; }

.rule-quick-bar {
  margin-bottom: 6px;
  padding: 4px 8px;
  background: #f5f7fa;
  border-radius: 4px;
}
.rule-tip { color: #909399; font-size: 12px; margin-right: 8px; }

.rule-editor {
  width: 100%;
  min-height: 80px;
  padding: 8px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 13px;
  line-height: 1.5;
  resize: vertical;
  background: #fafbfc;
}
.rule-editor:focus { border-color: #409eff; outline: none; }
.rule-editor-small { min-height: 50px; }

.weight-sum {
  margin-left: 16px;
  color: #67c23a;
  font-size: 12px;
}
.weight-warn { color: #e6a23c; }

.form-hint {
  color: #909399;
  font-size: 11px;
  margin-left: 8px;
}

.bt-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding: 8px;
  background: #f5f7fa;
  border-radius: 4px;
}
.bt-sep { color: #909399; }
.bt-hint { color: #e6a23c; font-size: 12px; }

.bt-result { margin-top: 8px; }
.bt-metrics {
  display: flex;
  gap: 12px;
  margin-bottom: 8px;
}
.bt-metric {
  flex: 1;
  background: #f5f7fa;
  padding: 8px 12px;
  border-radius: 4px;
  text-align: center;
}
.bt-metric span { display: block; color: #909399; font-size: 12px; }
.bt-metric b { font-size: 18px; color: #303133; }

.bt-watchlist-title {
  font-weight: 600;
  margin-bottom: 8px;
}
.wl-warning {
  margin-left: 12px;
  color: #e6a23c;
  font-size: 12px;
  font-weight: normal;
}
</style>

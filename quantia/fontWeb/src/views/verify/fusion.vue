<template>
  <div class="verify-fusion">
    <div class="feature-tabs">
      <router-link class="feature-tab" to="/verify/compare">策略对比</router-link>
      <router-link class="feature-tab" to="/verify/optimize">买卖点优化</router-link>
      <router-link class="feature-tab" to="/verify/fusion">多维融合</router-link>
      <router-link class="feature-tab" to="/verify/factor-lab">因子实验室</router-link>
    </div>
    <!-- 使用说明 -->
    <UsageGuide
      title="📖 策略融合 使用说明（点击展开）"
      :steps="guideSteps"
      :example="guideExample"
      :metrics="guideMetrics"
      :tips="guideTips"
    />
    <!-- 子 Tab -->
    <div class="sub-tabs">
      <div
        v-for="(tab, idx) in subTabs"
        :key="idx"
        class="sub-tab"
        :class="{ active: activeSubTab === idx }"
        @click="activeSubTab = idx"
      >{{ tab }}</div>
    </div>

    <!-- Sub 0: 融合配置器 -->
    <div v-show="activeSubTab === 0" class="sub-panel">
      <!-- 融合模式 -->
      <div class="mode-bar">
        <span class="mode-label">融合模式:</span>
        <label
          v-for="m in fusionModes"
          :key="m.value"
          class="mode-option"
          :class="{ active: fusionMode === m.value }"
        >
          <input type="radio" :value="m.value" v-model="fusionMode" style="margin-right: 6px">
          <b>{{ m.label }}</b>
          <span class="mode-desc">{{ m.desc }}</span>
        </label>
      </div>

      <!-- 回测参数 -->
      <div class="param-bar">
        <span class="param-label">回测区间:</span>
        <el-date-picker v-model="startDate" type="date" size="small" value-format="YYYY-MM-DD" style="width: 140px" />
        <span class="param-sep">~</span>
        <el-date-picker v-model="endDate" type="date" size="small" value-format="YYYY-MM-DD" style="width: 140px" />
        <span class="param-label">持仓天数:</span>
        <el-input-number v-model="holdingDays" :min="1" :max="60" size="small" style="width: 100px" />
        <template v-if="fusionMode === 'weighted_score'">
          <span class="param-label">最小评分:</span>
          <el-input-number v-model="minScore" :min="0" :max="1" :step="0.05" :precision="2" size="small" style="width: 110px" />
          <span class="param-tip">(0~1，达到才算融合命中)</span>
        </template>
        <template v-if="fusionMode === 'vote'">
          <span class="param-label">最少同维度:</span>
          <el-input-number v-model="voteThreshold" :min="1" :max="5" size="small" style="width: 100px" />
          <span class="param-tip">(≥N 个维度命中)</span>
        </template>
      </div>

      <!-- 五维配置 -->
      <div class="dim-grid">
        <div
          v-for="dim in dimensions"
          :key="dim.key"
          class="dim-section"
          :class="{ 'active-dim': dim.enabled, 'dim-off': !dim.enabled, 'dim-full-row': dim.key === 'custom' }"
        >
          <div class="dim-head">
            <div class="dim-name">
              <span class="dim-dot" :style="{ background: dim.color }"></span>
              {{ dim.name }}
            </div>
            <div class="dim-controls">
              <span class="dim-weight-label">权重</span>
              <input
                type="range"
                :min="0"
                :max="100"
                v-model.number="dim.weight"
                :style="{ accentColor: dim.color }"
                :disabled="!dim.enabled"
                class="dim-slider"
              >
              <span class="dim-weight-val" :style="{ color: dim.color }">{{ dim.weight }}%</span>
              <span
                class="dim-toggle"
                :class="{ on: dim.enabled }"
                @click="dim.enabled = !dim.enabled"
              >{{ dim.enabled ? 'ON' : 'OFF' }}</span>
            </div>
          </div>
          <div class="dim-chips">
            <span
              v-for="item in dim.items"
              :key="item.id"
              class="dim-item-chip"
              :class="{ checked: item.checked, disabled: !dim.enabled }"
              :style="item.checked && dim.enabled ? { background: dim.color + '22', borderColor: dim.color, color: dim.color } : {}"
              @click="dim.enabled && (item.checked = !item.checked)"
            >
              <span class="chip-mark" v-if="item.checked">✓</span>
              {{ item.label }}
            </span>
            <span v-if="!dim.items.length" class="dim-empty-tip">暂无可选项</span>
          </div>
          <div class="dim-tip">{{ dim.tip }}</div>
        </div>
      </div>

      <!-- 操作栏 -->
      <div class="action-bar">
        <el-button type="primary" :loading="loading" @click="runFusionBacktest">
          🚀 运行融合回测
        </el-button>
        <el-button size="small" @click="saveFusionScheme">💾 保存方案</el-button>
        <el-button size="small" @click="exportFusionCode">📤 导出代码</el-button>
        <span class="weight-total" :class="{ warn: totalWeight !== 100 }">
          权重总计: {{ totalWeight }}%
          <template v-if="totalWeight !== 100"> ⚠</template>
          <template v-else> ✓</template>
        </span>
      </div>

      <!-- warnings -->
      <el-alert
        v-for="(w, i) in warnings"
        :key="i"
        :title="w"
        type="warning"
        :closable="false"
        style="margin-top: 10px"
      />

      <!-- 融合结果 -->
      <template v-if="fusionResult">
        <div class="kpi-row">
          <div class="kpi-card highlight">
            <div class="kpi-value" :class="fusionResult.sharpe > 0 ? 'text-pos' : 'text-neg'">{{ fmt(fusionResult.sharpe) }}</div>
            <div class="kpi-label">融合夏普</div>
            <div v-if="improvement.sharpe_vs_best_single || improvement.sharpe_vs_best" class="kpi-delta text-pos">vs 最佳单维 {{ improvement.sharpe_vs_best_single || improvement.sharpe_vs_best }}</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-value" :class="fusionResult.win_rate > 50 ? 'text-pos' : ''">{{ fmt(fusionResult.win_rate) }}%</div>
            <div class="kpi-label">融合胜率</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-value">{{ fusionResult.daily_signal_avg }}</div>
            <div class="kpi-label">日均信号</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-value" :class="(fusionResult.max_drawdown || 0) > -10 ? 'text-blue' : 'text-neg'">{{ fmt(fusionResult.max_drawdown) }}%</div>
            <div class="kpi-label">最大回撤</div>
            <div v-if="improvement.drawdown_vs_worst_single" class="kpi-delta text-blue">vs 最差单维 {{ improvement.drawdown_vs_worst_single }}</div>
          </div>
        </div>

        <!-- 对比表 -->
        <div class="card" v-if="individualResults && Object.keys(individualResults).length">
          <div class="card-h">融合 vs 各策略对比</div>
          <div class="card-b">
            <table class="cmp-table">
              <thead>
                <tr><th>策略</th><th>平均收益%</th><th>胜率%</th><th>夏普</th><th>信号数</th></tr>
              </thead>
              <tbody>
                <tr class="best-row">
                  <td><strong>🔗 融合结果</strong></td>
                  <td :class="rateClass(fusionResult.avg_return)">{{ fmt(fusionResult.avg_return) }}</td>
                  <td>{{ fmt(fusionResult.win_rate) }}</td>
                  <td :class="sharpeClass(fusionResult.sharpe)">{{ fmt(fusionResult.sharpe) }}</td>
                  <td>{{ fusionResult.signal_count }}</td>
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
        </div>

        <!-- 收益曲线 -->
        <div class="card" v-if="dailySeries.length">
          <div class="card-h">融合 vs 单策略 累计收益对比</div>
          <div class="card-b">
            <div ref="fusionChartRef" style="height: 280px" />
          </div>
        </div>
      </template>
    </div>

    <!-- Sub 1: 因子贡献分析 -->
    <div v-show="activeSubTab === 1" class="sub-panel">
      <div class="card">
        <div class="card-h">因子贡献分析 (Shapley Value) <span class="card-sub">每个维度对夏普比率的边际贡献</span></div>
        <div class="card-b">
          <template v-if="!fusionResult">
            <el-empty description="请先在「融合配置器」运行融合回测" :image-size="60" />
          </template>
          <template v-else-if="shapleyContribs.length">
            <div v-for="c in shapleyContribs" :key="c.name" class="factor-bar">
              <div class="fb-name">{{ c.name }}</div>
              <div class="fb-track"><div class="fb-fill" :style="{ width: c.pct + '%', background: c.color }"></div></div>
              <div class="fb-val" :class="c.impact >= 0 ? 'text-pos' : 'text-neg'">{{ c.impact >= 0 ? '+' : '' }}{{ c.impact.toFixed(2) }}</div>
            </div>
            <div class="tip">Shapley 贡献度 = 各子集中加入该维度的平均边际增量</div>
          </template>
          <template v-else>
            <el-empty description="Shapley 数据将在 Stage 3 提供（当前回测启用维度可能 < 2 或后端暂未计算）" :image-size="60" />
          </template>
        </div>
      </div>
    </div>

    <!-- Sub 2: A/B 对比验证 -->
    <div v-show="activeSubTab === 2" class="sub-panel">
      <div class="card">
        <div class="card-h">A/B 逐步验证 <span class="card-sub">按 Shapley 顺序逐维加入后的累计效果</span></div>
        <div class="card-b">
          <template v-if="!fusionResult">
            <el-empty description="请先在「融合配置器」运行融合回测" :image-size="60" />
          </template>
          <template v-else-if="abSteps.length">
            <table class="cmp-table">
              <thead><tr><th>维度组合</th><th>夏普</th><th>胜率</th><th>最大回撤</th><th>信号数</th><th>累计增量</th></tr></thead>
              <tbody>
                <tr v-for="(step, idx) in abSteps" :key="idx" :class="{ 'best-row': idx === abSteps.length - 1 }">
                  <td :style="idx === abSteps.length - 1 ? { fontWeight: 600 } : {}">{{ step.label }}</td>
                  <td :class="step.sharpe > 2.5 ? 'text-pos' : ''">{{ step.sharpe.toFixed(2) }}</td>
                  <td>{{ step.winRate.toFixed(1) }}%</td>
                  <td>{{ step.maxDD.toFixed(1) }}%</td>
                  <td>{{ step.signalCount }}</td>
                  <td>
                    <span v-if="idx === 0" class="badge b-flat">基线</span>
                    <span v-else class="badge" :class="step.delta > 0 ? 'b-pos' : 'b-neg'">
                      {{ step.delta > 0 ? '+' : '' }}{{ step.delta.toFixed(1) }}%
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
            <div class="tip">每加一维度，信号数减少（过滤噪音），但剩余信号质量提升。边际效益递减是正常的。</div>
          </template>
          <template v-else>
            <el-empty description="A/B 步进数据将在 Stage 3 提供" :image-size="60" />
          </template>
        </div>
      </div>
    </div>

    <!-- Sub 3: 信号重叠热图 -->
    <div v-show="activeSubTab === 3" class="sub-panel">
      <div class="card">
        <div class="card-h">信号重叠可视化 <span class="card-sub">多维共振信号分布</span></div>
        <div class="card-b">
          <template v-if="!fusionResult">
            <el-empty description="请先在「融合配置器」运行融合回测" :image-size="60" />
          </template>
          <template v-else-if="(overlapData.calendar && overlapData.calendar.length) || (overlapData.co_occurrence && overlapData.co_occurrence.length)">
            <div class="overlap-grid">
              <div class="card-inner">
                <div class="card-inner-h">日历热力图</div>
                <div ref="calendarRef" style="height: 200px" />
              </div>
              <div class="card-inner">
                <div class="card-inner-h">维度 Jaccard 重叠矩阵</div>
                <div ref="overlapRef" style="height: 200px" />
              </div>
            </div>
          </template>
          <template v-else>
            <el-empty description="信号重叠数据将在 Stage 3 提供" :image-size="60" />
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as echarts from 'echarts'
import { runFusion as apiFusion, exportFusionCodeApi, saveFusionSchemeApi, getVerifyStrategyList } from '@/api/verify'
import UsageGuide from '@/components/verify/UsageGuide.vue'

const guideSteps = [
  '在 <b>融合配置器</b> tab 中选择 <b>融合模式</b>（推荐新手从"加权评分"开始）',
  '配置 <b>五个维度</b>：调整权重滑块（总和需 = 100%），勾选各维度下的具体指标',
  '每个维度可通过 <b>ON/OFF</b> 开关启用或禁用（禁用后该维度不参与计算）',
  '点击 <b>"🚀运行融合回测"</b>，等待计算完成',
  '查看 KPI 卡片（融合夏普、胜率、日均信号等）及 "融合 vs 各策略" 对比表',
  '切换到 <b>"因子贡献分析"</b> 查看各维度 Shapley 贡献值',
  '切换到 <b>"A/B 对比验证"</b> 查看逐维度累加的增量效果',
  '切换到 <b>"信号重叠热图"</b> 观察多维共振日历分布',
  '点击 <b>"💾保存方案"</b> 保存当前配置，或 <b>"📤导出代码"</b> 生成 Python 代码',
]
const guideExample = `<b>场景：</b>将技术信号 + 基本面 + 资金流向三维融合<br/>
<b>操作：</b>关闭"情绪面"和"自定义"维度 → 调整权重: 技术40%/基本面35%/资金25% → 勾选各维度下希望使用的指标 → 运行融合回测<br/>
<b>预期：</b>融合夏普通常高于单维度最优值（多维交叉验证减少噪音），日均信号数会减少（过滤效果）`
const guideMetrics = [
  { name: '融合夏普', desc: '多维融合后的综合风险调整收益', range: '-∞ ~ +∞', good: '比最佳单策略高 10%+ 说明融合有效' },
  { name: '融合胜率', desc: '融合信号的盈利比例', range: '0% ~ 100%', good: '> 55% 为较好' },
  { name: '日均信号', desc: '平均每个交易日产生的买入信号数', range: '0 ~ 全市场股票数', good: '3~30 为合理（太少无法分散，太多无法精选）' },
  { name: '最大回撤', desc: '从峰值到谷值的最大跌幅', range: '-100% ~ 0%', good: '> -15% 为优秀回撤控制' },
  { name: 'Shapley贡献', desc: '博弈论方法计算每个维度对夏普的边际贡献', range: '-∞ ~ +∞', good: '正值=该维度有贡献，负值=拖累融合效果' },
  { name: '权重总计', desc: '五个维度权重之和，必须等于 100% 才能运行', range: '必须 = 100%' },
]
const guideTips = [
  '权重总计 ≠ 100% 时无法运行回测，请调整各维度权重或关闭不用的维度',
  '加权评分模式对权重敏感，建议从均分开始微调；信号投票模式对权重不敏感',
  '日均信号 < 3 时统计可靠性下降，考虑放宽条件或减少维度',
  '条件树模式适合"先粗筛再精选"的场景：基本面→技术→资金逐层验证',
  '环境轮动模式在趋势市表现好，但震荡市易频繁切换，需配合较长持仓周期',
]

// ── 子 Tab ────────────────────────────────────────────────────────────

const subTabs = ['融合配置器', '因子贡献分析', 'A/B 对比验证', '信号重叠热图']
const activeSubTab = ref(0)

// ── 融合模式 ──────────────────────────────────────────────────────────

const fusionModes = [
  { value: 'weighted_score', label: '加权评分', desc: '归一化加权求和' },
  { value: 'vote', label: '信号投票', desc: '≥N维同时看多' },
  { value: 'condition_tree', label: '条件树', desc: '先基本面→技术→资金验证' },
  { value: 'rotation', label: '环境轮动', desc: '牛/熊/震荡切换配比' },
]
const fusionMode = ref<string>('weighted_score')

// ── 五维配置 ──────────────────────────────────────────────────────────

interface DimItem { id: string; label: string; checked: boolean }
interface Dimension {
  key: string; name: string; color: string; weight: number; enabled: boolean
  items: DimItem[]; tip: string
}

const dimensions = ref<Dimension[]>([
  {
    key: 'tech', name: '技术策略信号', color: '#1890ff', weight: 30, enabled: true,
    items: [
      { id: 'cn_stock_strategy_keep_increasing', label: '均线多头', checked: true },
      { id: 'cn_stock_strategy_breakthrough_platform', label: '突破平台', checked: true },
      { id: 'cn_stock_strategy_backtrace_ma250', label: '回踩年线', checked: true },
      { id: 'cn_stock_strategy_turtle_trade', label: '海龟交易', checked: false },
      { id: 'cn_stock_strategy_oversold_rebound', label: '超跌反弹', checked: false },
      { id: 'cn_stock_strategy_enter', label: '放量上涨', checked: false },
      { id: 'cn_stock_strategy_breakout_confirm', label: '突破确认', checked: false },
      { id: 'cn_stock_strategy_trend_pullback', label: '趋势回调', checked: false },
    ],
    tip: '来源: 13个 cn_stock_strategy_* 表（同维度内多策略 OR 关系）',
  },
  {
    key: 'fund', name: '基本面筛选', color: '#722ed1', weight: 25, enabled: true,
    items: [
      { id: 'pe9_lt_30', label: '市盈率 PE < 30', checked: true },
      { id: 'pbnewmrq_lt_5', label: '市净率 PB < 5', checked: true },
      { id: 'roe_weight_gte_10', label: 'ROE ≥ 10%', checked: true },
      { id: 'sale_gpr_gte_20', label: '毛利率 ≥ 20%', checked: true },
      { id: 'jroa_gte_3', label: 'ROA ≥ 3%', checked: false },
      { id: 'pettmdeducted_lt_40', label: 'PE扣非 < 40', checked: false },
    ],
    tip: '来源: cn_stock_selection（同维度内多条件 AND）',
  },
  {
    key: 'flow', name: '资金流向', color: '#13c2c2', weight: 20, enabled: true,
    items: [
      { id: 'fund_amount_gt_0', label: '当日主力净流入 > 0', checked: true },
      { id: 'fund_amount_3_gt_0', label: '3日主力净流入 > 0', checked: true },
      { id: 'fund_rate_gt_0', label: '主力占比 > 0%', checked: false },
      { id: 'fund_amount_super_gt_0', label: '超大单净流入 > 0', checked: false },
    ],
    tip: '来源: cn_stock_fund_flow（同维度内多条件 AND）',
  },
  {
    key: 'sent', name: '市场情绪', color: '#eb2f96', weight: 15, enabled: true,
    items: [
      { id: 'turnoverrate_gte_3', label: '换手率 ≥ 3%', checked: true },
      { id: 'volume_ratio_gte_1', label: '量比 ≥ 1', checked: true },
      { id: 'amplitude_gte_2', label: '振幅 ≥ 2%', checked: false },
      { id: 'change_rate_gte_0', label: '涨跌幅 ≥ 0', checked: false },
    ],
    tip: '来源: cn_stock_selection（换手率/量比/振幅/涨跌幅）',
  },
  {
    key: 'custom', name: '自定义策略 & 复合指标', color: '#fa8c16', weight: 10, enabled: false,
    items: [],
    tip: '来源: 用户自定义策略 cn_stock_strategy_<custom_id>（加载中…）',
  },
])

const totalWeight = computed(() =>
  dimensions.value.filter(d => d.enabled).reduce((s, d) => s + d.weight, 0)
)

// ── 融合回测执行 ──────────────────────────────────────────────────────

const loading = ref(false)
const fusionResult = ref<any>(null)
const individualResults = ref<Record<string, any>>({})
const improvement = ref<any>({})
const dailySeries = ref<any[]>([])
const shapleyData = ref<Array<{ dim: string; name?: string; contrib: number }>>([])
const abStepsData = ref<Array<any>>([])
const overlapData = ref<any>({ calendar: [], co_occurrence: [] })
const warnings = ref<string[]>([])
const diagnostics = ref<any>({})
const fusionChartRef = ref<HTMLElement>()
const calendarRef = ref<HTMLElement>()
const overlapRef = ref<HTMLElement>()

// 回测参数
const today = new Date()
const startDate = ref<string>(`${today.getFullYear()}-01-01`)
const endDate = ref<string>(today.toISOString().slice(0, 10))
const holdingDays = ref<number>(10)
const minScore = ref<number>(0.5)
const voteThreshold = ref<number>(2)

// 自定义维度动态加载
async function loadCustomStrategies() {
  const customDim = dimensions.value.find(d => d.key === 'custom')
  if (!customDim) return
  try {
    const res: any = await getVerifyStrategyList()
    const groups: any[] = (res && res.groups) || []
    const customGroup = groups.find(g => g && g.category === 'custom')
    const items: DimItem[] = []
    for (const s of (customGroup?.items || [])) {
      const value = s.value || (s.custom_id != null ? `custom_${s.custom_id}` : null)
      const label = s.label || s.name || `策略#${s.custom_id ?? '?'}`
      if (!value) continue
      items.push({ id: value, label: `自定义: ${label}`, checked: false })
    }
    customDim.items = items
    customDim.tip = items.length
      ? `共 ${items.length} 个有已完成回测的自定义策略（同维 OR，取 buy 交易作为信号）`
      : '尚无已完成回测的自定义策略（请先在「策略管理 → 回测」跑一次）'
  } catch (e) {
    customDim.items = []
    customDim.tip = '自定义策略列表加载失败（/verify/strategy_list 不可用）'
  }
}
onMounted(() => { loadCustomStrategies() })

function buildV2Payload() {
  const dims: Record<string, any> = {}
  for (const d of dimensions.value) {
    const checkedItems = d.items.filter(i => i.checked).map(i => i.id)
    dims[d.key] = {
      enabled: !!d.enabled && checkedItems.length > 0,
      weight: Number(d.weight) || 0,
      items: checkedItems,
    }
  }
  return {
    version: 2 as const,
    mode: fusionMode.value as 'weighted_score' | 'vote' | 'condition_tree' | 'rotation',
    start_date: startDate.value,
    end_date: endDate.value,
    holding_days: holdingDays.value,
    min_score: minScore.value,
    vote_threshold: voteThreshold.value,
    dimensions: dims,
  }
}

async function runFusionBacktest() {
  const payload = buildV2Payload()
  const enabledDims = Object.entries(payload.dimensions).filter(([, d]: any) => d.enabled && d.items.length > 0)
  if (enabledDims.length === 0) {
    ElMessage.warning('请至少启用一个维度并勾选条目')
    return
  }
  if (totalWeight.value !== 100) {
    ElMessage.warning(`已启用维度权重之和需 = 100%（当前 ${totalWeight.value}%）`)
    return
  }

  loading.value = true
  fusionResult.value = null
  individualResults.value = {}
  improvement.value = {}
  dailySeries.value = []
  shapleyData.value = []
  abStepsData.value = []
  overlapData.value = { calendar: [], co_occurrence: [] }
  warnings.value = []
  diagnostics.value = {}

  try {
    const res: any = await apiFusion(payload as any)
    fusionResult.value = res.fusion_result || null
    individualResults.value = res.individual_results || {}
    improvement.value = res.improvement || {}
    dailySeries.value = res.daily_series || []
    shapleyData.value = Array.isArray(res.shapley) ? res.shapley : []
    abStepsData.value = Array.isArray(res.ab_steps) ? res.ab_steps : []
    overlapData.value = res.overlap || { calendar: [], co_occurrence: [] }
    warnings.value = Array.isArray(res.warnings) ? res.warnings : []
    diagnostics.value = res.diagnostics || {}
    await nextTick()
    renderFusionChart()
    if (activeSubTab.value === 3) renderOverlapCharts()
    if (!fusionResult.value || !fusionResult.value.signal_count) {
      ElMessage.warning('融合后无信号，请放宽条件或调整日期区间')
    } else {
      ElMessage.success(`融合完成，共 ${fusionResult.value.signal_count} 条信号`)
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || e?.message || '融合请求失败')
  } finally {
    loading.value = false
  }
}

// ── 因子贡献数据（来自后端 shapley 字段） ────────────────────────────

const shapleyContribs = computed(() => {
  const dimColors: Record<string, string> = { tech: '#1890ff', fund: '#722ed1', flow: '#13c2c2', sent: '#eb2f96', custom: '#fa8c16' }
  const dimNames: Record<string, string> = { tech: '技术信号', fund: '基本面', flow: '资金流向', sent: '市场情绪', custom: '自定义' }
  if (!Array.isArray(shapleyData.value) || shapleyData.value.length === 0) return []
  const arr = shapleyData.value.map((s: any) => ({
    name: s.name || dimNames[s.dim] || s.dim,
    impact: Number(s.contrib) || 0,
    pct: 0,
    color: dimColors[s.dim] || '#999',
  }))
  const maxAbs = Math.max(...arr.map(r => Math.abs(r.impact)), 0.01)
  arr.forEach(r => r.pct = (Math.abs(r.impact) / maxAbs) * 100)
  arr.sort((a, b) => b.impact - a.impact)
  return arr
})

// ── A/B 步进数据（来自后端 ab_steps 字段） ────────────────────────────

const abSteps = computed(() => {
  if (!Array.isArray(abStepsData.value) || abStepsData.value.length === 0) return []
  return abStepsData.value.map((s: any, idx: number, arr: any[]) => {
    const sharpe = Number(s.sharpe) || 0
    const prev = idx === 0 ? 0 : Number(arr[idx - 1].sharpe) || 0
    const delta = idx === 0 ? 0 : ((sharpe - prev) / Math.abs(prev || 1)) * 100
    return {
      label: s.label || (s.dims ? s.dims.join(' + ') : `Step ${idx + 1}`),
      sharpe,
      winRate: Number(s.win_rate) || 0,
      maxDD: Number(s.max_drawdown) || 0,
      signalCount: Number(s.signal_count) || 0,
      delta,
    }
  })
})

// ── 图表 ──────────────────────────────────────────────────────────────

function renderFusionChart() {
  if (!fusionChartRef.value || dailySeries.value.length === 0) return
  const existing = echarts.getInstanceByDom(fusionChartRef.value)
  if (existing) existing.dispose()
  const chart = echarts.init(fusionChartRef.value)

  const dates = dailySeries.value.map((p: any) => p.date)
  const cumData = dailySeries.value.map((p: any) => p.cumulative)
  const ddData = dailySeries.value.map((p: any) => p.drawdown)

  chart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { top: 30, left: 60, right: 20, bottom: 40 },
    xAxis: { type: 'category', data: dates, axisLabel: { fontSize: 10 } },
    yAxis: [
      { type: 'value', name: '累计收益', position: 'left' },
      { type: 'value', name: '回撤%', position: 'right' },
    ],
    dataZoom: [{ type: 'inside' }],
    series: [
      {
        name: '融合净值', type: 'line', data: cumData, showSymbol: false,
        lineStyle: { width: 2.5, color: '#722ed1' },
        areaStyle: { color: 'rgba(114,46,209,0.06)' },
      },
      {
        name: '回撤', type: 'line', yAxisIndex: 1, data: ddData, showSymbol: false,
        lineStyle: { width: 1, color: '#ff4d4f' },
        areaStyle: { color: 'rgba(255,77,79,0.1)' },
      },
    ],
  })
}

function renderOverlapCharts() {
  if (!calendarRef.value || !overlapRef.value) return
  const calData: any[] = Array.isArray(overlapData.value?.calendar) ? overlapData.value.calendar : []
  const coData: any[] = Array.isArray(overlapData.value?.co_occurrence) ? overlapData.value.co_occurrence : []

  // ── 日历热图 ──
  const calExisting = echarts.getInstanceByDom(calendarRef.value)
  if (calExisting) calExisting.dispose()
  const cal = echarts.init(calendarRef.value)
  const calPoints = calData.map((p: any) => [p.date, Number(p.signal_count) || 0])
  const maxCnt = calPoints.length ? Math.max(...calPoints.map(p => p[1] as number)) : 10
  const range = calPoints.length
    ? [calPoints[0][0], calPoints[calPoints.length - 1][0]]
    : [startDate.value, endDate.value]
  cal.setOption({
    tooltip: { formatter: (p: any) => `${p.value[0]}: ${p.value[1]} 信号` },
    visualMap: {
      min: 0, max: maxCnt || 1, show: false,
      inRange: { color: ['#ebedf0', '#9be9a8', '#40c463', '#30a14e', '#216e39'] },
    },
    calendar: { range, cellSize: [14, 14], top: 30, left: 30, right: 10 },
    series: [{ type: 'heatmap', coordinateSystem: 'calendar', data: calPoints }],
  })

  // ── 维度重叠矩阵 ──
  const ovExisting = echarts.getInstanceByDom(overlapRef.value)
  if (ovExisting) ovExisting.dispose()
  const ov = echarts.init(overlapRef.value)
  const dimNames: Record<string, string> = { tech: '技术', fund: '基本面', flow: '资金', sent: '情绪', custom: '自定义' }
  const enabledKeys = dimensions.value.filter(d => d.enabled && d.items.some(i => i.checked)).map(d => d.key)
  const axisLabels = enabledKeys.map(k => dimNames[k] || k)
  const matrix: any[] = []
  for (const row of coData) {
    const xi = enabledKeys.indexOf(row.a)
    const yi = enabledKeys.indexOf(row.b)
    if (xi >= 0 && yi >= 0) matrix.push([xi, yi, Number(row.jaccard) || 0])
  }
  ov.setOption({
    tooltip: { formatter: (p: any) => `${axisLabels[p.value[0]]} ∩ ${axisLabels[p.value[1]]}: ${(p.value[2] * 100).toFixed(1)}%` },
    grid: { top: 30, left: 60, right: 20, bottom: 30 },
    xAxis: { type: 'category', data: axisLabels, axisLabel: { fontSize: 10 } },
    yAxis: { type: 'category', data: axisLabels, axisLabel: { fontSize: 10 } },
    visualMap: {
      min: 0, max: 1, show: false,
      inRange: { color: ['#f0f5ff', '#91d5ff', '#1890ff', '#0050b3'] },
    },
    series: [{
      type: 'heatmap', data: matrix,
      label: { show: true, formatter: (p: any) => (p.value[2] * 100).toFixed(0) + '%', fontSize: 10 },
    }],
  })
}

watch(activeSubTab, (idx) => {
  if (idx === 3 && fusionResult.value) {
    nextTick(() => renderOverlapCharts())
  }
})

onUnmounted(() => {
  ;[fusionChartRef, calendarRef, overlapRef].forEach(r => {
    if (r.value) echarts.dispose(r.value)
  })
})

// ── 工具函数 ──────────────────────────────────────────────────────────

function saveFusionScheme() {
  const scheme = {
    version: 2,
    mode: fusionMode.value,
    start_date: startDate.value,
    end_date: endDate.value,
    holding_days: holdingDays.value,
    min_score: minScore.value,
    vote_threshold: voteThreshold.value,
    dimensions: dimensions.value.map(d => ({
      key: d.key, name: d.name, weight: d.weight, enabled: d.enabled,
      items: d.items.map(i => ({ id: i.id, label: i.label, checked: i.checked })),
    })),
    savedAt: new Date().toISOString(),
  }
  // 始终先写本地，作为离线兜底
  localStorage.setItem('quantia_fusion_scheme_v2', JSON.stringify(scheme))
  // 异步询问方案名并上云
  ElMessageBox.prompt('为方案命名（同名将覆盖）', '保存到云端', {
    confirmButtonText: '保存',
    cancelButtonText: '仅本地',
    inputPlaceholder: '例如：3 维加权-基本面强化',
    inputValidator: (v: string) => (!!v && v.trim().length > 0 && v.length <= 200) || '名称 1-200 字符',
  }).then(({ value }) => {
    const payload = buildV2Payload()
    return saveFusionSchemeApi({ ...payload, name: String(value).trim() })
  }).then((res: any) => {
    ElMessage.success(`已保存到云端（id=${res?.id}）`)
  }).catch((err: any) => {
    if (err === 'cancel' || err === 'close') {
      ElMessage.info('已保存到本地 localStorage')
      return
    }
    ElMessage.error(err?.response?.data?.error || err?.message || '云端保存失败，已留本地副本')
  })
}

async function exportFusionCode() {
  const payload = buildV2Payload()
  try {
    const res = await exportFusionCodeApi(payload)
    const code = res?.code || ''
    if (!code) throw new Error('后端未返回代码')
    try {
      await navigator.clipboard.writeText(code)
      ElMessage.success(`策略代码已复制到剪贴板（${code.length} 字符）`)
    } catch {
      ElMessage.info('代码生成成功，请手动复制')
      // eslint-disable-next-line no-console
      console.log(code)
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || e?.message || '代码导出失败')
  }
}

function fmt(v: number | null | undefined): string {
  if (v === null || v === undefined) return '--'
  return Number(v).toFixed(2)
}
function rateClass(v: number | null | undefined): string {
  if (v == null) return ''
  return v > 0 ? 'text-pos' : v < 0 ? 'text-neg' : ''
}
function sharpeClass(v: number | null | undefined): string {
  if (v == null) return ''
  return v >= 2 ? 'text-pos font-bold' : v < 0 ? 'text-neg' : ''
}
</script>

<style scoped>
.verify-fusion { padding: 16px; }
.feature-tabs { display: flex; align-items: center; gap: 0; height: 42px; padding: 0 12px; margin-bottom: 12px; background: #fff; border: 1px solid #ebeef5; border-radius: 4px; }
.feature-tab { height: 42px; display: inline-flex; align-items: center; padding: 0 18px; font-size: 13px; color: #606266; border-bottom: 2px solid transparent; cursor: pointer; text-decoration: none; }
.feature-tab.router-link-exact-active { color: #1890ff; border-bottom-color: #1890ff; font-weight: 600; }

/* Sub Tabs */
.sub-tabs { display: flex; gap: 0; margin-bottom: 16px; }
.sub-tab {
  padding: 8px 16px; font-size: 12px; cursor: pointer; color: #606266;
  background: #fff; border: 1px solid #e4e7ed; transition: .2s;
}
.sub-tab:first-child { border-radius: 4px 0 0 4px; }
.sub-tab:last-child { border-radius: 0 4px 4px 0; }
.sub-tab:not(:first-child) { border-left: 0; }
.sub-tab.active { background: #409eff; color: #fff; border-color: #409eff; }
.sub-tab:hover:not(.active) { background: #ecf5ff; color: #409eff; }

/* Mode bar */
.mode-bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
.mode-label { font-size: 13px; font-weight: 600; }
.mode-option {
  display: flex; align-items: center; gap: 6px; padding: 8px 14px; border-radius: 4px;
  border: 1px solid #e4e7ed; cursor: pointer; transition: .2s; font-size: 12px;
}
.mode-option.active { background: #e6f7ff; border-color: #91d5ff; }
.mode-desc { font-size: 10px; color: #909399; }

/* Param bar */
.param-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; padding: 8px 12px; background: #fafbfc; border-radius: 4px; border: 1px solid #ebeef5; }
.param-label { font-size: 12px; color: #606266; font-weight: 600; margin-left: 4px; }
.param-sep { color: #909399; }
.param-tip { font-size: 11px; color: #909399; }

/* Dimension grid */
.dim-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px; }
.dim-section {
  border: 2px solid #ebeef5; border-radius: 4px; padding: 14px; transition: .2s;
}
.dim-section.active-dim { border-color: #409eff; box-shadow: 0 0 0 2px rgba(64,158,255,.1); }
.dim-section.dim-off { opacity: .5; border-color: #e4e7ed !important; box-shadow: none !important; }
.dim-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.dim-name { font-weight: 600; font-size: 13px; display: flex; align-items: center; gap: 6px; }
.dim-dot { width: 8px; height: 8px; border-radius: 50%; }
.dim-controls { display: flex; align-items: center; gap: 6px; }
.dim-weight-label { font-size: 11px; color: #909399; }
.dim-slider { width: 70px; }
.dim-weight-val { font-size: 12px; font-weight: 600; width: 32px; }
.dim-toggle {
  font-size: 11px; cursor: pointer; padding: 3px 10px; border-radius: 10px;
  background: #f5f5f5; color: #909399; border: 1px solid #e4e7ed; transition: .2s;
}
.dim-toggle.on { background: #ecf5ff; color: #409eff; border-color: #409eff; }
.dim-items { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; font-size: 11px; }
.dim-item-label { display: flex; align-items: center; gap: 4px; }
.dim-chips {
  display: flex; flex-wrap: wrap; gap: 6px; font-size: 11px; min-height: 28px;
}
.dim-item-chip {
  display: inline-flex; align-items: center; gap: 3px;
  padding: 4px 10px; border: 1px solid #dcdfe6; border-radius: 14px;
  background: #fff; color: #606266; cursor: pointer; transition: .15s;
  user-select: none; line-height: 1.2;
}
.dim-item-chip:hover:not(.disabled) { border-color: #c0c4cc; background: #f5f7fa; }
.dim-item-chip.checked { font-weight: 600; }
.dim-item-chip.disabled { cursor: not-allowed; opacity: .55; }
.chip-mark { font-size: 10px; font-weight: 700; }
.dim-empty-tip { font-size: 11px; color: #c0c4cc; padding: 4px 0; }
.dim-full-row { grid-column: 1 / -1; }
.dim-tip { font-size: 10px; color: #c0c4cc; margin-top: 8px; }

/* Action bar */
.action-bar { display: flex; align-items: center; gap: 16px; margin-bottom: 16px; }
.weight-total { font-size: 12px; color: #909399; }
.weight-total.warn { color: #e6a23c; }

/* KPI row */
.kpi-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }
.kpi-card { text-align: center; padding: 14px; background: #fafafa; border-radius: 6px; border: 1px solid #ebeef5; }
.kpi-card.highlight { border-color: #91d5ff; background: #e6f7ff; }
.kpi-value { font-size: 22px; font-weight: 700; }
.kpi-label { font-size: 11px; color: #909399; margin-top: 4px; }
.kpi-delta { font-size: 10px; margin-top: 2px; }

/* Cards */
.card { background: #fff; border: 1px solid #ebeef5; border-radius: 4px; margin-bottom: 16px; }
.card-h { padding: 12px 16px; border-bottom: 1px solid #ebeef5; font-size: 13px; font-weight: 600; }
.card-sub { font-weight: normal; color: #909399; margin-left: 8px; font-size: 11px; }
.card-b { padding: 16px; }

/* Factor bar */
.factor-bar { display: flex; align-items: center; gap: 8px; margin: 6px 0; }
.fb-name { width: 110px; font-size: 12px; text-align: right; color: #606266; flex-shrink: 0; }
.fb-track { flex: 1; height: 16px; background: #f5f5f5; border-radius: 3px; overflow: hidden; }
.fb-fill { height: 100%; border-radius: 3px; transition: width .3s; }
.fb-val { width: 55px; font-size: 12px; font-weight: 600; flex-shrink: 0; }

/* Table */
.cmp-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.cmp-table th, .cmp-table td { padding: 8px 12px; border-bottom: 1px solid #f0f0f0; text-align: center; }
.cmp-table th { background: #fafafa; font-weight: 600; }
.best-row { background: #e6f7ff; }

/* Badge */
.badge { display: inline-flex; padding: 2px 8px; border-radius: 10px; font-size: 10px; font-weight: 600; }
.b-pos { background: #f6ffed; color: #389e0d; }
.b-neg { background: #fff2f0; color: #cf1322; }
.b-flat { background: #f5f5f5; color: #8c8c8c; }

/* Overlap grid */
.overlap-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.card-inner { border: 1px solid #f0f0f0; border-radius: 4px; padding: 12px; }
.card-inner-h { font-size: 12px; font-weight: 600; margin-bottom: 8px; }

/* Utility */
.tip { font-size: 10px; color: #c0c4cc; margin-top: 10px; }
.text-pos { color: #cf1322; }
.text-neg { color: #389e0d; }
.text-blue { color: #1890ff; }
.font-bold { font-weight: 700; }

@media (max-width: 960px) {
  .dim-grid { grid-template-columns: 1fr; }
  .kpi-row { grid-template-columns: 1fr 1fr; }
}
</style>

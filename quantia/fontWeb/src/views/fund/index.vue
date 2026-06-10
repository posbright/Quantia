<template>
  <div class="fund-center">
    <!-- 顶部标题 + 快照日 -->
    <div class="fund-header">
      <div class="fund-title">
        <span class="title-icon">🏦</span>
        <span>场外基金排行榜</span>
      </div>
      <div class="fund-snapshot" v-if="meta?.latest_date">
        最新净值快照日：<b>{{ meta.latest_date }}</b>
      </div>
      <div class="fund-snapshot fund-snapshot--empty" v-else>
        暂无基金数据（待每日数据采集任务落库）
      </div>
    </div>

    <!-- 风险提示条 -->
    <div class="risk-tip">
      ⚠️ 历史业绩不代表未来表现，本页为数据分析，非投资建议。收益率按 A 股惯例红涨绿跌着色。
    </div>

    <!-- 基金类型胶囊 -->
    <div class="type-capsules">
      <span
        v-for="t in fundTypes"
        :key="t"
        class="capsule"
        :class="{ active: t === fundType }"
        @click="selectType(t)"
      >{{ t }}</span>
    </div>

    <el-tabs v-model="activeTab" class="fund-tabs">
      <el-tab-pane label="排行榜" name="rank">
    <!-- 工具栏：排序周期 + 数量 -->
    <div class="fund-toolbar">
      <div class="toolbar-left">
        <span class="toolbar-label">排序周期</span>
        <el-select v-model="period" size="small" style="width: 160px" @change="loadRank">
          <el-option
            v-for="p in periodOptions"
            :key="p.value"
            :label="p.label"
            :value="p.value"
            :disabled="periodDisabled(p.value)"
          />
        </el-select>
        <span class="toolbar-label">显示数量</span>
        <el-select v-model="limit" size="small" style="width: 110px" @change="loadRank">
          <el-option v-for="n in [20, 50, 100, 200]" :key="n" :label="`Top ${n}`" :value="n" />
        </el-select>
        <template v-if="industrySupported">
          <span class="toolbar-label">主行业</span>
          <el-select
            v-model="industry"
            size="small"
            clearable
            filterable
            placeholder="全部行业"
            style="width: 150px"
            @change="loadRank"
          >
            <el-option v-for="ind in industries" :key="ind" :label="ind" :value="ind" />
          </el-select>
        </template>
      </div>
      <div class="toolbar-right">
        <el-button size="small" :loading="loading" @click="loadRank">
          <el-icon><Refresh /></el-icon>&nbsp;刷新
        </el-button>
      </div>
    </div>

    <!-- 排名表格 -->
    <el-table
      v-if="!isMobile"
      v-loading="loading"
      :data="items"
      size="small"
      stripe
      border
      empty-text="该类型暂无数据"
      class="fund-table"
      :default-sort="{ prop: period, order: 'descending' }"
    >
      <el-table-column label="名次" width="64" align="center">
        <template #default="{ $index }">
          <span class="rank-badge" :class="rankClass($index)">{{ medal($index) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="基金简称" min-width="180" prop="name" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="fund-name fund-name--link" @click="openDetail(row)">{{ row.name }}</span>
          <span class="fund-code">{{ row.code }}</span>
        </template>
      </el-table-column>
      <!-- 综合分（净值型，0~100 进度条色阶）-->
      <el-table-column v-if="!isMoneyType" label="综合分" width="120" align="center" prop="score">
        <template #default="{ row }">
          <div v-if="row.score != null" class="score-cell">
            <div class="score-bar">
              <div class="score-bar-fill" :style="scoreBarStyle(row.score)"></div>
            </div>
            <span class="score-val" :style="{ color: scoreColor(row.score) }">{{ Math.round(row.score) }}</span>
          </div>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="净值日" width="100" align="center" prop="nav_date">
        <template #default="{ row }">{{ row.nav_date || '—' }}</template>
      </el-table-column>

      <!-- 货币型专属列 -->
      <template v-if="isMoneyType">
        <el-table-column label="万份收益" width="100" align="right">
          <template #default="{ row }">{{ fmtNum(row.million_unit_income, 4) }}</template>
        </el-table-column>
        <el-table-column label="7日年化" width="100" align="right">
          <template #default="{ row }">{{ fmtPct(row.seven_day_annual) }}</template>
        </el-table-column>
      </template>

      <!-- 净值型专属列 -->
      <template v-else>
        <el-table-column label="单位净值" width="96" align="right">
          <template #default="{ row }">{{ fmtNum(row.unit_nav, 4) }}</template>
        </el-table-column>
        <el-table-column label="累计净值" width="96" align="right">
          <template #default="{ row }">{{ fmtNum(row.acc_nav, 4) }}</template>
        </el-table-column>
        <el-table-column label="日增长" width="92" align="right" prop="day_growth">
          <template #default="{ row }">
            <span :style="returnStyle(row.day_growth)">{{ fmtPct(row.day_growth) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="近1周" width="84" align="right" prop="rate_1w">
          <template #default="{ row }">
            <span :style="returnStyle(row.rate_1w)">{{ fmtPct(row.rate_1w) }}</span>
          </template>
        </el-table-column>
      </template>

      <!-- 共有周期收益率列 -->
      <el-table-column
        v-for="col in commonRateCols"
        :key="col.prop"
        :label="col.label"
        :prop="col.prop"
        width="84"
        align="right"
      >
        <template #default="{ row }">
          <span :style="returnStyle(row[col.prop])" :class="{ 'sort-active': col.prop === period }">
            {{ fmtPct(row[col.prop]) }}
          </span>
        </template>
      </el-table-column>

      <el-table-column label="手续费" width="84" align="right" prop="fee">
        <template #default="{ row }">{{ fmtFee(row.fee) }}</template>
      </el-table-column>

      <!-- 净值型风险/评分/规模列（来自评分表 + 画像表）-->
      <template v-if="!isMoneyType">
        <el-table-column label="近5年" width="84" align="right" prop="rate_5y">
          <template #default="{ row }">
            <span :style="returnStyle(row.rate_5y)" :class="{ 'sort-active': period === 'rate_5y' }">
              {{ fmtPct(row.rate_5y) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="夏普" width="80" align="right" prop="sharpe">
          <template #default="{ row }">
            <span :style="sharpeStyle(row.sharpe)" :class="{ 'sort-active': period === 'sharpe' }">
              {{ fmtNum(row.sharpe, 2) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="最大回撤" width="92" align="right" prop="max_drawdown">
          <template #default="{ row }">
            <span :style="drawdownStyle(row.max_drawdown)" :class="{ 'sort-active': period === 'max_drawdown' }">
              {{ fmtDrawdown(row.max_drawdown) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="基准超额" width="92" align="right" prop="excess_1y">
          <template #default="{ row }">
            <span :style="returnStyle(row.excess_1y)" :class="{ 'sort-active': period === 'excess_1y' }">
              {{ fmtPct(row.excess_1y) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="规模(亿)" width="92" align="right" prop="scale_yi">
          <template #default="{ row }">{{ fmtNum(row.scale_yi, 2) }}</template>
        </el-table-column>
        <el-table-column label="评级" width="80" align="center" prop="rating">
          <template #default="{ row }">
            <span v-if="row.rating" class="rating-tag">{{ row.rating }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="主行业" width="100" align="center" prop="main_industry" show-overflow-tooltip>
          <template #default="{ row }">{{ row.main_industry || '—' }}</template>
        </el-table-column>
      </template>
    </el-table>

    <!-- 移动端卡片视图 -->
    <div v-if="isMobile" v-loading="loading" class="fund-card-list">
      <div v-for="(row, idx) in items" :key="row.code" class="fund-card" @click="openDetail(row)">
        <div class="fund-card-head">
          <span class="rank-badge" :class="rankClass(idx)">{{ medal(idx) }}</span>
          <div class="fund-card-title">
            <span class="fund-card-name">{{ row.name }}</span>
            <span class="fund-card-code">{{ row.code }}</span>
          </div>
          <span v-if="!isMoneyType && row.score != null" class="fund-card-score" :style="{ color: scoreColor(row.score) }">
            {{ Math.round(row.score) }}分
          </span>
        </div>
        <div class="fund-card-body">
          <template v-if="isMoneyType">
            <div class="fund-card-field">
              <span class="fund-lbl">7日年化</span>
              <span :style="returnStyle(row.seven_day_annual)">{{ fmtPct(row.seven_day_annual) }}</span>
            </div>
            <div class="fund-card-field">
              <span class="fund-lbl">万份收益</span>
              <span>{{ fmtNum(row.million_unit_income, 4) }}</span>
            </div>
          </template>
          <template v-else>
            <div class="fund-card-field">
              <span class="fund-lbl">单位净值</span>
              <span>{{ fmtNum(row.unit_nav, 4) }}</span>
            </div>
            <div class="fund-card-field">
              <span class="fund-lbl">日增长</span>
              <span :style="returnStyle(row.day_growth)">{{ fmtPct(row.day_growth) }}</span>
            </div>
          </template>
          <div class="fund-card-field">
            <span class="fund-lbl">近1月</span>
            <span :style="returnStyle(row.rate_1m)">{{ fmtPct(row.rate_1m) }}</span>
          </div>
          <div class="fund-card-field">
            <span class="fund-lbl">近1年</span>
            <span :style="returnStyle(row.rate_1y)">{{ fmtPct(row.rate_1y) }}</span>
          </div>
          <div class="fund-card-field">
            <span class="fund-lbl">今年来</span>
            <span :style="returnStyle(row.rate_ytd)">{{ fmtPct(row.rate_ytd) }}</span>
          </div>
          <div class="fund-card-field">
            <span class="fund-lbl">净值日</span>
            <span>{{ row.nav_date || '—' }}</span>
          </div>
          <template v-if="!isMoneyType">
            <div class="fund-card-field">
              <span class="fund-lbl">夏普</span>
              <span :style="sharpeStyle(row.sharpe)">{{ fmtNum(row.sharpe, 2) }}</span>
            </div>
            <div class="fund-card-field">
              <span class="fund-lbl">评级</span>
              <span>{{ row.rating || '—' }}</span>
            </div>
          </template>
        </div>
      </div>
      <el-empty v-if="!loading && items.length === 0" description="该类型暂无数据" />
    </div>

    <div class="fund-footer" v-if="items.length">
      共 {{ count }} 条 · {{ fundType }} · 按{{ activePeriodLabel }}降序
    </div>
      </el-tab-pane>

      <el-tab-pane label="同类对比" name="compare">
        <FundCompareTab :fund-type="fundType" :period="period" />
      </el-tab-pane>
    </el-tabs>

    <!-- 基金详情抽屉：同类雷达 + 综合分析 + AI 解读 -->
    <FundDetailDrawer v-model="detailVisible" :code="detailCode" :name="detailName" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onActivated } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import {
  getFundRankMeta,
  getFundRank,
  getFundRankIndustries,
  type FundRankMeta,
  type FundRankResult,
  type FundPeriodOption,
  type FundRankItem,
  type FundIndustriesResult,
} from '@/api/fund'
import FundDetailDrawer from './FundDetailDrawer.vue'
import FundCompareTab from './FundCompareTab.vue'
import { useResponsive } from '@/composables/useResponsive'

const { isMobile } = useResponsive()
const meta = ref<FundRankMeta | null>(null)
const fundTypes = ref<string[]>([])
const periodOptions = ref<FundPeriodOption[]>([])

const activeTab = ref('rank')
const fundType = ref('混合型')
const period = ref('score')
const limit = ref(50)
const industry = ref('')
const industries = ref<string[]>([])
const industrySupported = ref(false)

const items = ref<FundRankItem[]>([])
const count = ref(0)
const loading = ref(false)
const metaLoaded = ref(false)

// 详情抽屉
const detailVisible = ref(false)
const detailCode = ref('')
const detailName = ref('')

function openDetail(row: FundRankItem) {
  detailCode.value = row.code
  detailName.value = row.name
  detailVisible.value = true
}

const isMoneyType = computed(() => fundType.value === '货币型')

// 共有周期收益率列（净值型与货币型都有）
const commonRateCols = [
  { prop: 'rate_1m', label: '近1月' },
  { prop: 'rate_3m', label: '近3月' },
  { prop: 'rate_6m', label: '近6月' },
  { prop: 'rate_1y', label: '近1年' },
  { prop: 'rate_2y', label: '近2年' },
  { prop: 'rate_3y', label: '近3年' },
  { prop: 'rate_ytd', label: '今年来' },
  { prop: 'rate_since', label: '成立来' },
]

const activePeriodLabel = computed(
  () => periodOptions.value.find((p) => p.value === period.value)?.label || period.value,
)

function medal(idx: number): string {
  if (idx === 0) return '🥇'
  if (idx === 1) return '🥈'
  if (idx === 2) return '🥉'
  return String(idx + 1)
}

function rankClass(idx: number): string {
  return idx < 3 ? 'rank-top' : ''
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${v > 0 ? '+' : ''}${v.toFixed(2)}%`
}

function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return v.toFixed(digits)
}

// 手续费是成本、非收益：不加 +/- 号、不着色
function fmtFee(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${v.toFixed(2)}%`
}

// 最大回撤为负数小数（如 -0.35）→ 百分比展示
function fmtDrawdown(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${(v * 100).toFixed(2)}%`
}

// 综合分 0~100 → 进度条宽度 + 色阶（高分绿、中性橙、低分红）
function scoreColor(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '#909399'
  if (v >= 75) return '#16a34a'
  if (v >= 50) return '#e6a23c'
  return '#d23b3b'
}

function scoreBarStyle(v: number | null | undefined): Record<string, string> {
  const n = v === null || v === undefined || Number.isNaN(v) ? 0 : Math.max(0, Math.min(100, v))
  return { width: `${n}%`, background: scoreColor(v) }
}

// 夏普高（>1）绿色高亮，<0 红色警示
function sharpeStyle(v: number | null | undefined): Record<string, string> {
  if (v === null || v === undefined || Number.isNaN(v)) return {}
  if (v >= 1) return { color: '#16a34a', fontWeight: '600' }
  if (v < 0) return { color: '#d23b3b', fontWeight: '600' }
  return {}
}

// 回撤为负：越接近 0 越好（绿），深回撤红色警示
function drawdownStyle(v: number | null | undefined): Record<string, string> {
  if (v === null || v === undefined || Number.isNaN(v)) return {}
  if (v <= -0.3) return { color: '#d23b3b', fontWeight: '600' }
  if (v >= -0.1) return { color: '#16a34a', fontWeight: '600' }
  return {}
}

// 货币型仅有 seven_day_annual，净值型仅有 rate_1w + 评分派生列：按类型禁用不适用周期
function periodDisabled(value: string): boolean {
  if (isMoneyType.value) {
    // 货币型无单位净值波动 → 评分/夏普/回撤/超额/近5年/近1周不适用
    return ['rate_1w', 'rate_5y', 'score', 'sharpe', 'max_drawdown', 'excess_1y'].includes(value)
  }
  return value === 'seven_day_annual'
}

// A 股惯例：红涨绿跌
function returnStyle(v: number | null | undefined): Record<string, string> {
  if (v === null || v === undefined || Number.isNaN(v) || v === 0) return {}
  return { color: v > 0 ? '#d23b3b' : '#16a34a', fontWeight: '600' }
}

function selectType(t: string) {
  if (t === fundType.value) return
  fundType.value = t
  // 切换类型后，若当前排序周期不适用于新类型则回退到该类型的默认排序
  if (periodDisabled(period.value)) {
    period.value = isMoneyType.value
      ? 'seven_day_annual'
      : meta.value?.default_period || 'score'
  }
  // 主行业过滤仅对 A 股权益类生效；切类型重置并重拉行业列表。
  industry.value = ''
  void loadIndustries()
  loadRank()
}

async function loadIndustries() {
  try {
    const res = (await getFundRankIndustries(fundType.value)) as unknown as FundIndustriesResult
    industrySupported.value = !!res.supported
    industries.value = res.industries || []
  } catch {
    industrySupported.value = false
    industries.value = []
  }
}

async function loadMeta() {
  try {
    const res = (await getFundRankMeta()) as unknown as FundRankMeta
    meta.value = res
    fundTypes.value = res.fund_types || []
    periodOptions.value = res.periods || []
    if (res.default_period) period.value = res.default_period
    if (res.default_limit) limit.value = res.default_limit
    metaLoaded.value = true
  } catch (e) {
    ElMessage.error('加载基金元数据失败')
  }
}

async function loadRank() {
  loading.value = true
  try {
    const res = (await getFundRank({
      fund_type: fundType.value,
      period: period.value,
      limit: limit.value,
      industry: industry.value || undefined,
    })) as unknown as FundRankResult
    items.value = res.items || []
    count.value = res.count || 0
  } catch (e) {
    ElMessage.error('加载基金排名失败')
    items.value = []
    count.value = 0
  } finally {
    loading.value = false
  }
}

// 布局使用 keep-alive，用 onActivated 而非 onMounted 保证回到页面时刷新
onActivated(async () => {
  if (!metaLoaded.value) await loadMeta()
  await Promise.all([loadRank(), loadIndustries()])
})
</script>

<style scoped>
.fund-center {
  padding: 16px;
}
.fund-header {
  display: flex;
  align-items: baseline;
  gap: 16px;
  margin-bottom: 12px;
}
.fund-title {
  font-size: 20px;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 8px;
}
.title-icon {
  font-size: 22px;
}
.fund-snapshot {
  font-size: 13px;
  color: #606266;
}
.fund-snapshot--empty {
  color: #e6a23c;
}
.risk-tip {
  background: #fdf6ec;
  color: #b88230;
  border: 1px solid #faecd8;
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 12px;
  margin-bottom: 12px;
}
.type-capsules {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.capsule {
  padding: 5px 16px;
  border-radius: 16px;
  background: #f0f2f5;
  color: #606266;
  font-size: 13px;
  cursor: pointer;
  user-select: none;
  transition: all 0.15s;
  border: 1px solid transparent;
}
.capsule:hover {
  background: #e6eefb;
  color: #409eff;
}
.capsule.active {
  background: #409eff;
  color: #fff;
  border-color: #409eff;
}
.fund-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.toolbar-label {
  font-size: 13px;
  color: #606266;
}
.fund-table {
  width: 100%;
}
.rank-badge {
  font-size: 13px;
  color: #909399;
}
.rank-badge.rank-top {
  font-size: 16px;
}
.fund-name {
  font-weight: 500;
  margin-right: 6px;
}
.fund-name--link {
  color: #409eff;
  cursor: pointer;
}
.fund-name--link:hover {
  text-decoration: underline;
}
.fund-code {
  font-size: 11px;
  color: #a0a0a0;
}
.sort-active {
  text-decoration: underline;
  text-underline-offset: 3px;
}
.score-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}
.score-bar {
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: #f0f2f5;
  overflow: hidden;
}
.score-bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s ease;
}
.score-val {
  min-width: 22px;
  font-size: 12px;
  font-weight: 600;
  text-align: right;
}
.rating-tag {
  display: inline-block;
  padding: 1px 6px;
  font-size: 11px;
  color: #b88230;
  background: #fdf6ec;
  border-radius: 4px;
}
.muted {
  color: #c0c4cc;
}
.fund-footer {
  margin-top: 10px;
  font-size: 12px;
  color: #909399;
  text-align: right;
}

/* ===== 移动端卡片视图（断点对齐 useResponsive：isMobile < 768） ===== */
.fund-card-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.fund-card {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 10px 12px;
}
.fund-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  border-bottom: 1px dashed #ebeef5;
  padding-bottom: 6px;
  margin-bottom: 8px;
}
.fund-card-title {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.fund-card-name {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fund-card-code {
  font-size: 12px;
  color: #909399;
}
.fund-card-score {
  font-size: 16px;
  font-weight: 700;
}
.fund-card-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 12px;
  font-size: 13px;
}
.fund-card-field {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.fund-lbl {
  color: #909399;
  white-space: nowrap;
}

@media (max-width: 767.98px) {
  .fund-toolbar {
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
  }
  .toolbar-left {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 8px;
    align-items: center;
  }
  .toolbar-right {
    display: flex;
    justify-content: flex-end;
  }
  .fund-header {
    flex-wrap: wrap;
    gap: 4px 12px;
  }
}
</style>

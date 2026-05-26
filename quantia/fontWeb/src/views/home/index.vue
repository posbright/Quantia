<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  getStockData,
  getTradeDate,
  getPaperTradingList,
  getStrategyCodeList
} from '@/api/stock'

const router = useRouter()

// ---------- 顶部交易日 ----------
const tradeDate = ref<string>('--')
const tradeDateLatest = ref<string>('--')

// ---------- 核心指标卡 ----------
interface KpiCard {
  key: string
  title: string
  value: string
  delta: string
  trend: 'up' | 'down' | 'flat'
  icon: string
  gradient: string
  to?: string
  hint?: string
  loading: boolean
}

const kpis = ref<KpiCard[]>([
  {
    key: 'index',
    title: '沪深 300',
    value: '--',
    delta: '--',
    trend: 'flat',
    icon: 'TrendCharts',
    gradient: 'linear-gradient(135deg,#ff6b6b 0%,#ee5a52 100%)',
    to: '/basic/index',
    hint: '今日大盘风向',
    loading: true
  },
  {
    key: 'selection',
    title: '综合选股',
    value: '--',
    delta: '--',
    trend: 'flat',
    icon: 'Monitor',
    gradient: 'linear-gradient(135deg,#667eea 0%,#5b6fe2 100%)',
    to: '/selection/all',
    hint: '今日入选数量',
    loading: true
  },
  {
    key: 'paper',
    title: '模拟盘',
    value: '--',
    delta: '--',
    trend: 'flat',
    icon: 'Wallet',
    gradient: 'linear-gradient(135deg,#11998e 0%,#38ef7d 100%)',
    to: '/algo/paper',
    hint: '我的实盘验证',
    loading: true
  },
  {
    key: 'strategy',
    title: '我的策略',
    value: '--',
    delta: '--',
    trend: 'flat',
    icon: 'Aim',
    gradient: 'linear-gradient(135deg,#f093fb 0%,#f5576c 100%)',
    to: '/algo',
    hint: '策略库已保存',
    loading: true
  }
])

// ---------- 大盘指数 ----------
interface IndexCell {
  code: string
  name: string
  price: number | null
  changeRate: number | null
}
const majorIndexes = ref<IndexCell[]>([
  { code: '000001', name: '上证指数', price: null, changeRate: null },
  { code: '399001', name: '深证成指', price: null, changeRate: null },
  { code: '399006', name: '创业板指', price: null, changeRate: null },
  { code: '000300', name: '沪深 300', price: null, changeRate: null }
])
const indexLoading = ref(true)

// ---------- 今日精选选股 ----------
interface PickRow {
  code: string
  name: string
  latest_price: number | null
  change_rate: number | null
}
const picks = ref<PickRow[]>([])
const picksLoading = ref(true)

// ---------- 行业资金流向 ----------
interface FundFlowRow {
  name: string
  changeRate: number | null
  netInflow: number | null
}
const fundFlows = ref<FundFlowRow[]>([])
const fundLoading = ref(true)

// ---------- 功能矩阵 ----------
const features = [
  { icon: 'Monitor', title: '综合选股', desc: '200+ 维度自由组合，覆盖基本面/技术面/消息面', color: '#667eea', to: '/selection/all' },
  { icon: 'TrendCharts', title: '技术指标', desc: '32 种 TA-Lib 指标，与同花顺/通达信结果一致', color: '#11998e', to: '/indicator/list' },
  { icon: 'PriceTag', title: 'K 线形态', desc: '精准识别 61 种经典 K 线形态', color: '#f5576c', to: '/kline/pattern' },
  { icon: 'Aim', title: '策略选股', desc: '14 种内置选股策略，每日自动跑批', color: '#fa8c16', to: '/strategy/enter' },
  { icon: 'DataAnalysis', title: '回测验证', desc: '历史回测 + 多策略对比 + 收益分布', color: '#13c2c2', to: '/backtest' },
  { icon: 'Wallet', title: '模拟实盘', desc: 'NAV 跟踪、收益归因、IM 指令同步', color: '#722ed1', to: '/algo/paper' }
]

// ---------- 快捷入口 ----------
const quicks = [
  { icon: 'Search', text: '今日选股', to: '/selection/all', color: '#409eff' },
  { icon: 'Document', text: '每日数据', to: '/basic/spot', color: '#67c23a' },
  { icon: 'Money', text: '资金流向', to: '/fund-flow/individual', color: '#e6a23c' },
  { icon: 'MagicStick', text: 'AI 助手', to: '/algo', color: '#f56c6c' }
]

// ---------- utils ----------
function fmtNum(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '--'
  return Number(n).toFixed(digits)
}
function fmtPct(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '--'
  const sign = n > 0 ? '+' : ''
  return `${sign}${Number(n).toFixed(2)}%`
}
function fmtMoney(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '--'
  const abs = Math.abs(n)
  if (abs >= 1e8) return `${(n / 1e8).toFixed(2)} 亿`
  if (abs >= 1e4) return `${(n / 1e4).toFixed(2)} 万`
  return n.toFixed(0)
}
// A股习惯：红涨绿跌
function trendColor(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n) || n === 0) return '#909399'
  return n > 0 ? '#f56c6c' : '#52c41a'
}
function trendOf(n: number | null | undefined): 'up' | 'down' | 'flat' {
  if (n === null || n === undefined || Number.isNaN(n) || n === 0) return 'flat'
  return n > 0 ? 'up' : 'down'
}
function pickField(row: any, candidates: string[]): any {
  for (const k of candidates) {
    if (row && row[k] !== undefined && row[k] !== null && row[k] !== '') return row[k]
  }
  return null
}

// ---------- 数据加载 ----------
async function loadTradeDate() {
  try {
    const r: any = await getTradeDate()
    tradeDate.value = r?.run_date || '--'
    tradeDateLatest.value = r?.run_date_nph || r?.run_date || '--'
  } catch { /* ignore */ }
}

async function loadIndexes() {
  indexLoading.value = true
  try {
    const r: any = await getStockData({ name: 'cn_index_spot', page: 1, page_size: 200 })
    const rows: any[] = r?.rows || r?.data || []
    for (const idx of majorIndexes.value) {
      const hit = rows.find(
        (row) => String(row.code) === idx.code || row.name === idx.name
      )
      if (hit) {
        const p = pickField(hit, ['latest_price', 'new_price', 'close', 'price'])
        idx.price = p === null ? null : Number(p)
        const c = pickField(hit, ['change_rate', 'changepercent', 'pct_chg', 'changes'])
        idx.changeRate = c === null ? null : Number(c)
      }
    }
    // 同步沪深300到 KPI 卡
    const hs300 = majorIndexes.value.find((i) => i.code === '000300')
    const kpi = kpis.value.find((k) => k.key === 'index')
    if (hs300 && kpi) {
      kpi.value = hs300.price !== null ? hs300.price.toFixed(2) : '--'
      kpi.delta = fmtPct(hs300.changeRate)
      kpi.trend = trendOf(hs300.changeRate)
    }
  } catch (e) {
    console.warn('[home] loadIndexes failed', e)
  } finally {
    indexLoading.value = false
    const kpi = kpis.value.find((k) => k.key === 'index')
    if (kpi) kpi.loading = false
  }
}

async function loadSelection() {
  const kpi = kpis.value.find((k) => k.key === 'selection')!
  try {
    const r: any = await getStockData({ name: 'cn_stock_selection', page: 1, page_size: 1 })
    const total = Number(r?.total ?? r?.count ?? 0)
    kpi.value = total > 0 ? total.toLocaleString('zh-CN') : '0'
    kpi.delta = total > 0 ? '只入选' : '暂无'
    kpi.trend = total > 0 ? 'up' : 'flat'
  } catch (e) {
    console.warn('[home] loadSelection failed', e)
  } finally {
    kpi.loading = false
  }
}

async function loadPaper() {
  const kpi = kpis.value.find((k) => k.key === 'paper')!
  try {
    const r: any = await getPaperTradingList()
    const items: any[] = r?.items || r?.data || r?.rows || []
    const total = items.length
    let totalAsset = 0
    let totalProfit = 0
    items.forEach((it) => {
      totalAsset += Number(it.current_value || it.latest_value || 0)
      totalProfit += Number(it.total_profit || it.profit || 0)
    })
    if (total > 0) {
      kpi.value = totalAsset > 0 ? fmtMoney(totalAsset) : `${total} 个`
      kpi.delta = totalProfit !== 0 ? `累计 ${fmtMoney(totalProfit)}` : `${total} 个组合`
      kpi.trend = trendOf(totalProfit)
    } else {
      kpi.value = '0'
      kpi.delta = '尚未创建'
      kpi.trend = 'flat'
    }
  } catch (e) {
    console.warn('[home] loadPaper failed', e)
  } finally {
    kpi.loading = false
  }
}

async function loadStrategy() {
  const kpi = kpis.value.find((k) => k.key === 'strategy')!
  try {
    const r: any = await getStrategyCodeList({})
    const items: any[] = r?.items || r?.data || r?.rows || []
    kpi.value = items.length.toString()
    kpi.delta = items.length > 0 ? '个策略' : '空'
    kpi.trend = items.length > 0 ? 'up' : 'flat'
  } catch (e) {
    console.warn('[home] loadStrategy failed', e)
  } finally {
    kpi.loading = false
  }
}

async function loadPicks() {
  picksLoading.value = true
  try {
    const r: any = await getStockData({ name: 'cn_stock_strategy_enter', page: 1, page_size: 8 })
    const rows: any[] = r?.rows || []
    picks.value = rows.map((row) => {
      const p = pickField(row, ['latest_price', 'new_price', 'close'])
      const c = pickField(row, ['change_rate', 'changepercent', 'pct_chg'])
      return {
        code: String(row.code || ''),
        name: String(row.name || ''),
        latest_price: p === null ? null : Number(p),
        change_rate: c === null ? null : Number(c)
      }
    })
  } catch (e) {
    console.warn('[home] loadPicks failed', e)
  } finally {
    picksLoading.value = false
  }
}

async function loadFundFlow() {
  fundLoading.value = true
  try {
    const r: any = await getStockData({ name: 'cn_stock_fund_flow_industry', page: 1, page_size: 50 })
    const rows: any[] = r?.rows || []
    const enriched: FundFlowRow[] = rows.map((row) => {
      const c = pickField(row, ['change_rate', 'changepercent'])
      const inflow = pickField(row, [
        'today_main_net_inflow',
        'main_net_inflow',
        'today_main_net_inflow_ratio',
        'net_inflow'
      ])
      return {
        name: String(row.name || row.industry || ''),
        changeRate: c === null ? null : Number(c),
        netInflow: inflow === null ? null : Number(inflow)
      }
    })
    enriched.sort((a, b) => Math.abs(b.netInflow || 0) - Math.abs(a.netInflow || 0))
    fundFlows.value = enriched.slice(0, 8)
  } catch (e) {
    console.warn('[home] loadFundFlow failed', e)
  } finally {
    fundLoading.value = false
  }
}

const maxFundAbs = computed(() => {
  let m = 0
  fundFlows.value.forEach((f) => {
    if (f.netInflow !== null && Math.abs(f.netInflow) > m) m = Math.abs(f.netInflow)
  })
  return m || 1
})

onMounted(() => {
  loadTradeDate()
  Promise.allSettled([
    loadIndexes(),
    loadSelection(),
    loadPaper(),
    loadStrategy(),
    loadPicks(),
    loadFundFlow()
  ])
})

function go(to?: string) {
  if (to) router.push(to)
}
</script>

<template>
  <div class="home">
    <!-- ============ Hero 顶部 ============ -->
    <section class="hero">
      <div class="hero-bg" />
      <div class="hero-inner">
        <div class="hero-left">
          <div class="hero-tag">
            <el-icon><DataLine /></el-icon>
            <span>玄枢 Quantia 智能量化投资中枢</span>
          </div>
          <h1 class="hero-title">
            数据驱动决策<span class="dot">.</span>
            <br />让每一次交易有迹可循
          </h1>
          <p class="hero-sub">
            A 股 / ETF 全维度数据 · 32 项技术指标 · 61 种 K 线形态 · 14 种内置策略 · 历史回测 + 模拟实盘
          </p>
          <div class="hero-actions">
            <el-button type="primary" size="large" round @click="go('/selection/all')">
              <el-icon><Search /></el-icon>
              开始选股
            </el-button>
            <el-button size="large" round plain @click="go('/algo')">
              <el-icon><MagicStick /></el-icon>
              策略库
            </el-button>
          </div>
        </div>
        <div class="hero-right">
          <div class="trade-date-card">
            <div class="td-label">最近交易日</div>
            <div class="td-value">{{ tradeDate }}</div>
            <div class="td-foot">
              <el-icon><Refresh /></el-icon>
              <span>当前时段：{{ tradeDateLatest }}</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ============ 核心 KPI 卡片 ============ -->
    <section class="kpi-row">
      <div
        v-for="card in kpis"
        :key="card.key"
        class="kpi-card"
        :class="{ clickable: !!card.to }"
        @click="go(card.to)"
      >
        <div class="kpi-icon" :style="{ background: card.gradient }">
          <el-icon :size="22"><component :is="card.icon" /></el-icon>
        </div>
        <div class="kpi-body">
          <div class="kpi-title">{{ card.title }}</div>
          <el-skeleton v-if="card.loading" :rows="1" animated style="width: 80px" />
          <template v-else>
            <div class="kpi-value">{{ card.value }}</div>
            <div class="kpi-delta" :class="card.trend">
              <el-icon v-if="card.trend === 'up'"><CaretTop /></el-icon>
              <el-icon v-else-if="card.trend === 'down'"><CaretBottom /></el-icon>
              <span>{{ card.delta }}</span>
            </div>
          </template>
          <div class="kpi-hint">{{ card.hint }}</div>
        </div>
      </div>
    </section>

    <!-- ============ 大盘指数 ============ -->
    <section class="block">
      <div class="block-head">
        <div class="block-title">
          <el-icon><TrendCharts /></el-icon>
          <span>大盘指数</span>
        </div>
        <span class="block-sub">实时跟踪四大主流指数</span>
      </div>
      <div class="index-row">
        <div v-for="idx in majorIndexes" :key="idx.code" class="index-card">
          <el-skeleton v-if="indexLoading" :rows="2" animated />
          <template v-else>
            <div class="idx-name">{{ idx.name }}</div>
            <div class="idx-code">{{ idx.code }}</div>
            <div class="idx-price" :style="{ color: trendColor(idx.changeRate) }">
              {{ fmtNum(idx.price) }}
            </div>
            <div class="idx-change" :style="{ color: trendColor(idx.changeRate) }">
              <el-icon v-if="(idx.changeRate ?? 0) > 0"><CaretTop /></el-icon>
              <el-icon v-else-if="(idx.changeRate ?? 0) < 0"><CaretBottom /></el-icon>
              <span>{{ fmtPct(idx.changeRate) }}</span>
            </div>
          </template>
        </div>
      </div>
    </section>

    <!-- ============ 双栏：今日选股 + 行业资金 ============ -->
    <section class="two-col">
      <div class="block panel">
        <div class="block-head">
          <div class="block-title">
            <el-icon><Star /></el-icon>
            <span>今日精选 · 放量上涨</span>
          </div>
          <el-button text type="primary" @click="go('/strategy/enter')">
            查看全部
            <el-icon><ArrowRight /></el-icon>
          </el-button>
        </div>
        <el-skeleton v-if="picksLoading" :rows="6" animated />
        <div v-else-if="picks.length === 0" class="empty-tip">
          <el-icon><DocumentRemove /></el-icon>
          <span>当日暂无策略选股结果</span>
        </div>
        <div v-else class="pick-list">
          <div v-for="(p, i) in picks" :key="p.code" class="pick-item">
            <div class="pick-rank" :class="{ top3: i < 3 }">{{ i + 1 }}</div>
            <div class="pick-main">
              <div class="pick-name">{{ p.name || '—' }}</div>
              <div class="pick-code">{{ p.code }}</div>
            </div>
            <div class="pick-price" :style="{ color: trendColor(p.change_rate) }">
              {{ fmtNum(p.latest_price) }}
            </div>
            <div class="pick-chg" :style="{ color: trendColor(p.change_rate) }">
              {{ fmtPct(p.change_rate) }}
            </div>
          </div>
        </div>
      </div>

      <div class="block panel">
        <div class="block-head">
          <div class="block-title">
            <el-icon><Money /></el-icon>
            <span>行业资金流向 · Top 8</span>
          </div>
          <el-button text type="primary" @click="go('/fund-flow/industry')">
            查看全部
            <el-icon><ArrowRight /></el-icon>
          </el-button>
        </div>
        <el-skeleton v-if="fundLoading" :rows="6" animated />
        <div v-else-if="fundFlows.length === 0" class="empty-tip">
          <el-icon><DocumentRemove /></el-icon>
          <span>暂无资金流向数据</span>
        </div>
        <div v-else class="fund-list">
          <div v-for="f in fundFlows" :key="f.name" class="fund-item">
            <div class="fund-name">
              <span>{{ f.name }}</span>
              <span class="fund-chg" :style="{ color: trendColor(f.changeRate) }">
                {{ fmtPct(f.changeRate) }}
              </span>
            </div>
            <div class="fund-bar-wrap">
              <div
                class="fund-bar"
                :class="(f.netInflow ?? 0) >= 0 ? 'pos' : 'neg'"
                :style="{ width: ((Math.abs(f.netInflow ?? 0) / maxFundAbs) * 100).toFixed(1) + '%' }"
              />
            </div>
            <div class="fund-val" :style="{ color: trendColor(f.netInflow) }">
              {{ (f.netInflow ?? 0) >= 0 ? '+' : '' }}{{ fmtMoney(f.netInflow) }}
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ============ 功能矩阵 ============ -->
    <section class="block">
      <div class="block-head">
        <div class="block-title">
          <el-icon><Grid /></el-icon>
          <span>核心能力</span>
        </div>
      </div>
      <div class="feature-grid">
        <div v-for="f in features" :key="f.title" class="feature-card" @click="go(f.to)">
          <div class="feat-glow" :style="{ background: f.color }" />
          <div class="feat-icon" :style="{ color: f.color, background: f.color + '14' }">
            <el-icon :size="26"><component :is="f.icon" /></el-icon>
          </div>
          <div class="feat-title">{{ f.title }}</div>
          <div class="feat-desc">{{ f.desc }}</div>
          <div class="feat-arrow">
            <el-icon><ArrowRight /></el-icon>
          </div>
        </div>
      </div>
    </section>

    <!-- ============ 快捷入口 ============ -->
    <section class="block">
      <div class="block-head">
        <div class="block-title">
          <el-icon><Promotion /></el-icon>
          <span>快捷入口</span>
        </div>
      </div>
      <div class="quick-row">
        <div v-for="q in quicks" :key="q.text" class="quick-card" @click="go(q.to)">
          <div class="quick-icon" :style="{ background: q.color + '18', color: q.color }">
            <el-icon :size="26"><component :is="q.icon" /></el-icon>
          </div>
          <span>{{ q.text }}</span>
        </div>
      </div>
    </section>
  </div>
</template>

<style lang="scss" scoped>
.home {
  max-width: 1440px;
  margin: 0 auto;
  padding: 4px 4px 24px;
}

/* ===== Hero ===== */
.hero {
  position: relative;
  border-radius: 16px;
  overflow: hidden;
  margin-bottom: 24px;
  min-height: 220px;
  color: #fff;

  .hero-bg {
    position: absolute;
    inset: 0;
    background:
      radial-gradient(circle at 20% 20%, rgba(255, 255, 255, 0.18), transparent 40%),
      radial-gradient(circle at 80% 80%, rgba(255, 255, 255, 0.12), transparent 40%),
      linear-gradient(135deg, #1e3c72 0%, #2a5298 50%, #4361ee 100%);
  }

  .hero-inner {
    position: relative;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 24px;
    padding: 32px 40px;
  }
}

.hero-left {
  flex: 1;
  min-width: 320px;

  .hero-tag {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 12px;
    background: rgba(255, 255, 255, 0.16);
    backdrop-filter: blur(6px);
    border-radius: 999px;
    font-size: 12px;
    margin-bottom: 16px;
  }

  .hero-title {
    font-size: 30px;
    line-height: 1.35;
    font-weight: 700;
    margin: 0 0 12px;
    letter-spacing: 0.5px;

    .dot { color: #ffd166; }
  }

  .hero-sub {
    font-size: 14px;
    opacity: 0.88;
    line-height: 1.7;
    margin: 0 0 20px;
    max-width: 620px;
  }

  .hero-actions {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
  }
}

.hero-right {
  .trade-date-card {
    background: rgba(255, 255, 255, 0.14);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.22);
    border-radius: 14px;
    padding: 20px 28px;
    min-width: 200px;
    text-align: center;

    .td-label { font-size: 12px; opacity: 0.85; margin-bottom: 8px; }
    .td-value { font-size: 28px; font-weight: 700; letter-spacing: 1px; }
    .td-foot {
      margin-top: 10px;
      font-size: 12px;
      opacity: 0.78;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 4px;
    }
  }
}

/* ===== KPI ===== */
.kpi-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.kpi-card {
  background: #fff;
  border-radius: 14px;
  padding: 20px;
  display: flex;
  gap: 16px;
  align-items: flex-start;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
  border: 1px solid #eef2f7;
  transition: all 0.25s ease;
  position: relative;
  overflow: hidden;

  &.clickable { cursor: pointer; }
  &::before {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(180deg, rgba(64, 158, 255, 0.04), transparent 60%);
    opacity: 0;
    transition: opacity 0.25s;
    pointer-events: none;
  }
  &:hover {
    transform: translateY(-3px);
    box-shadow: 0 12px 28px rgba(64, 158, 255, 0.18);
    &::before { opacity: 1; }
  }
}

.kpi-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.12);
}

.kpi-body { flex: 1; min-width: 0; }
.kpi-title { font-size: 13px; color: #909399; margin-bottom: 6px; }
.kpi-value {
  font-size: 24px;
  font-weight: 700;
  color: #1a1f36;
  line-height: 1.2;
  letter-spacing: -0.5px;
}
.kpi-delta {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 12px;
  margin-top: 4px;
  padding: 2px 8px;
  border-radius: 999px;
  background: #f4f6fa;
  color: #909399;

  &.up { background: #fff1f0; color: #f56c6c; }
  &.down { background: #f6ffed; color: #52c41a; }
}
.kpi-hint { font-size: 11px; color: #c0c4cc; margin-top: 6px; }

/* ===== Block ===== */
.block { margin-bottom: 24px; }
.block.panel {
  background: #fff;
  border: 1px solid #eef2f7;
  border-radius: 14px;
  padding: 18px 20px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.03);
}
.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;

  .block-title {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 16px;
    font-weight: 600;
    color: #1a1f36;
    .el-icon { color: #4361ee; }
  }
  .block-sub { font-size: 12px; color: #909399; }
}

/* ===== 大盘指数 ===== */
.index-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}
.index-card {
  background: #fff;
  border-radius: 12px;
  padding: 16px 18px;
  border: 1px solid #eef2f7;
  transition: all 0.25s;
  min-height: 110px;
  position: relative;
  overflow: hidden;

  &::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    background: linear-gradient(90deg, #4361ee, #4cc9f0);
  }
  &:hover {
    transform: translateY(-2px);
    box-shadow: 0 10px 24px rgba(67, 97, 238, 0.16);
  }

  .idx-name { font-size: 14px; font-weight: 600; color: #1a1f36; }
  .idx-code { font-size: 11px; color: #c0c4cc; margin-bottom: 8px; }
  .idx-price { font-size: 22px; font-weight: 700; line-height: 1.1; }
  .idx-change {
    margin-top: 4px;
    font-size: 13px;
    display: inline-flex;
    align-items: center;
    gap: 2px;
    font-weight: 500;
  }
}

/* ===== 双栏 ===== */
.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 24px;
}

.empty-tip {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 30px 0;
  color: #c0c4cc;
  font-size: 13px;
  .el-icon { font-size: 28px; }
}

/* ===== 选股列表 ===== */
.pick-list { display: flex; flex-direction: column; gap: 8px; }
.pick-item {
  display: grid;
  grid-template-columns: 28px 1fr 80px 70px;
  gap: 10px;
  align-items: center;
  padding: 8px 4px;
  border-radius: 8px;
  transition: background 0.2s;

  &:hover { background: #f7f9fc; }
}
.pick-rank {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: #f4f6fa;
  color: #909399;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;

  &.top3 {
    background: linear-gradient(135deg, #ffd166, #ff9f1c);
    color: #fff;
  }
}
.pick-main { min-width: 0; }
.pick-name {
  font-size: 14px;
  color: #1a1f36;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pick-code { font-size: 11px; color: #909399; font-family: 'Monaco', Consolas, monospace; }
.pick-price { font-size: 14px; font-weight: 600; text-align: right; }
.pick-chg { font-size: 13px; text-align: right; font-weight: 500; }

/* ===== 资金流向 ===== */
.fund-list { display: flex; flex-direction: column; gap: 12px; }
.fund-item { font-size: 13px; }
.fund-name {
  display: flex;
  justify-content: space-between;
  margin-bottom: 4px;
  color: #1a1f36;
  .fund-chg { font-size: 12px; font-weight: 500; }
}
.fund-bar-wrap {
  background: #f4f6fa;
  height: 6px;
  border-radius: 999px;
  overflow: hidden;
  margin-bottom: 4px;
}
.fund-bar {
  height: 100%;
  border-radius: 999px;
  transition: width 0.6s ease;
  &.pos { background: linear-gradient(90deg, #ff8a80, #f56c6c); }
  &.neg { background: linear-gradient(90deg, #95de64, #52c41a); }
}
.fund-val { text-align: right; font-size: 12px; font-weight: 500; }

/* ===== 功能矩阵 ===== */
.feature-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
.feature-card {
  position: relative;
  background: #fff;
  border-radius: 14px;
  padding: 22px;
  border: 1px solid #eef2f7;
  cursor: pointer;
  transition: all 0.3s;
  overflow: hidden;

  .feat-glow {
    position: absolute;
    top: -40px;
    right: -40px;
    width: 120px;
    height: 120px;
    border-radius: 50%;
    opacity: 0.08;
    transition: all 0.4s;
  }
  &:hover {
    transform: translateY(-4px);
    box-shadow: 0 16px 32px rgba(0, 0, 0, 0.08);
    .feat-glow { opacity: 0.15; transform: scale(1.4); }
    .feat-arrow { transform: translateX(4px); opacity: 1; }
  }

  .feat-icon {
    width: 48px;
    height: 48px;
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 14px;
  }
  .feat-title {
    font-size: 16px;
    font-weight: 600;
    color: #1a1f36;
    margin-bottom: 6px;
  }
  .feat-desc { font-size: 13px; color: #6b7280; line-height: 1.6; }
  .feat-arrow {
    position: absolute;
    bottom: 18px;
    right: 18px;
    color: #c0c4cc;
    opacity: 0;
    transition: all 0.3s;
  }
}

/* ===== 快捷入口 ===== */
.quick-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}
.quick-card {
  background: #fff;
  border: 1px solid #eef2f7;
  border-radius: 12px;
  padding: 18px;
  display: flex;
  align-items: center;
  gap: 14px;
  cursor: pointer;
  transition: all 0.25s;

  span { font-size: 14px; color: #1a1f36; font-weight: 500; }
  &:hover {
    transform: translateY(-2px);
    box-shadow: 0 10px 24px rgba(0, 0, 0, 0.06);
  }

  .quick-icon {
    width: 44px;
    height: 44px;
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
}

/* ===== 响应式（断点对齐 useResponsive：lg<992 / sm<768 / xs<576） ===== */
@media (max-width: 991.98px) {
  .kpi-row { grid-template-columns: repeat(2, 1fr); }
  .index-row { grid-template-columns: repeat(2, 1fr); }
  .feature-grid { grid-template-columns: repeat(2, 1fr); }
  .quick-row { grid-template-columns: repeat(2, 1fr); }
  .two-col { grid-template-columns: 1fr; }
}
@media (max-width: 767.98px) {
  .hero {
    min-height: auto;
    .hero-inner { padding: 20px 16px; flex-direction: column; align-items: stretch; gap: 16px; }
  }
  .hero-left { min-width: 0; }
  .hero-left .hero-title { font-size: 22px; line-height: 1.3; }
  .hero-left .hero-sub { font-size: 13px; }
  .hero-right .trade-date-card { min-width: 0; padding: 14px 18px; }
  .hero-right .trade-date-card .td-value { font-size: 22px; }
  .kpi-card { padding: 14px; gap: 12px; }
  .kpi-icon { width: 40px; height: 40px; }
  .kpi-value { font-size: 20px; }
  .block.panel { padding: 14px 14px; }
}
@media (max-width: 575.98px) {
  .kpi-row { grid-template-columns: 1fr; gap: 12px; margin-bottom: 16px; }
  .index-row { grid-template-columns: 1fr 1fr; gap: 10px; }
  .feature-grid { grid-template-columns: 1fr; gap: 12px; }
  .quick-row { grid-template-columns: 1fr 1fr; gap: 10px; }
  .feature-card { padding: 16px; }
  .index-card { padding: 12px 14px; min-height: 92px; }
  .index-card .idx-price { font-size: 18px; }
  .pick-item { grid-template-columns: 26px 1fr 72px 64px; gap: 8px; }
  .quick-card { padding: 12px; gap: 10px; }
  .quick-card .quick-icon { width: 36px; height: 36px; }
}
</style>

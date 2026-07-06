<script setup lang="ts">
import { ref, computed, watch, onMounted, onActivated } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getStockData, toggleAttention, getTradeDate } from '@/api/stock'
import { getColumnTooltip, strategyDescriptions } from '@/utils/columnTooltips'
import { buildBacktestDashboardQuery } from '@/utils/backtestDashboardLinks'
import { useResponsive } from '@/composables/useResponsive'
import IndustryTopStocksDialog from '@/components/IndustryTopStocksDialog.vue'
import dayjs from 'dayjs'

// 列定义接口
interface ColumnDef {
  value: string       // 字段名
  caption: string     // 中文名
  width: number       // 列宽
  dataType?: string   // 数据类型: 'numeric' | 'bigint' | 'datetime' | 'string'
  format?: string     // 格式化提示: 'pct' | 'price' | 'vol' | 'money' | 'ratio' | 'int'
  color?: boolean     // 涨跌着色
  group?: string      // 列分组: 'ind' = 筛选指标列
  headerStyle?: any
  conditionalFormats?: any[]
}

interface FundFlowRow {
  name: string
  changeRate: number | null
  netInflow: number | null
  sampleStocks: string[]
}

interface IndustrySampleStock {
  code: string
  name: string
  date: string
  price: number | null
  changeRate: number | null
  fundAmount: number | null
}

const route = useRoute()
const router = useRouter()
const { isMobile } = useResponsive()

// 表格数据和列定义
const tableData = ref<any[]>([])
const columnDefs = ref<ColumnDef[]>([])
const loading = ref(false)
const selectedDate = ref(dayjs().format('YYYY-MM-DD'))
const totalCount = ref(0)

// 分页
const currentPage = ref(1)
const pageSize = ref(50)

// 表名
const tableName = computed(() => route.meta.tableName as string || 'cn_stock_spot')
const pageTitle = computed(() => route.meta.title as string || '股票数据')
const noDateFilter = computed(() => route.meta.noDateFilter as boolean ?? false)
const isBacktestSummary = computed(() => tableName.value === 'cn_stock_backtest')
const isFundFlowIndustry = computed(() => tableName.value === 'cn_stock_fund_flow_industry')
// 指标买/卖信号榜单：提供「指标设置」入口
const isIndicatorSignalTable = computed(
  () => tableName.value === 'cn_stock_indicators_buy' || tableName.value === 'cn_stock_indicators_sell'
)

// 资金流向系列页面（个股/行业/概念）统一交互：默认按今日主力净流入-净额降序、列可排序、最大股可点击
const FUND_FLOW_TABLES = ['cn_stock_fund_flow', 'cn_stock_fund_flow_industry', 'cn_stock_fund_flow_concept']
const isFundFlow = computed(() => FUND_FLOW_TABLES.includes(tableName.value))
// 行业/概念资金流向中代表"主力净流入最大股"的列，点击可进入个股详情
const stockNameFields = new Set(['stock_name', 'stock_name_5', 'stock_name_10'])
const isStockNameCol = (colValue: string) => stockNameFields.has(colValue)

// 排序状态（服务端排序）。资金流向默认：今日主力净流入-净额（fund_amount）由高到低
const sortField = ref<string>('fund_amount')
const sortOrder = ref<'asc' | 'desc'>('desc')

const industryDialogVisible = ref(false)
const activeIndustry = ref<FundFlowRow | null>(null)

// 策略说明（仅策略页面显示）
const strategyDesc = computed(() => {
  const tn = tableName.value
  return strategyDescriptions[tn] || ''
})

// 动态列（排除 date, code, name, cdatetime 这些固定列，并隐藏全为空值的列）
const dynamicColumns = computed(() => {
  const baseCols = columnDefs.value.filter(col => 
    !['date', 'code', 'name', 'cdatetime'].includes(col.value)
  )
  // 如果没有数据行，返回所有列
  if (tableData.value.length === 0) return baseCols
  // 过滤掉所有值都为空/0/null 的列
  return baseCols.filter(col => {
    return tableData.value.some(row => {
      const v = row[col.value]
      return v !== null && v !== undefined && v !== '' && v !== 0
    })
  })
})

// 判断是否有code字段（用于显示关注按钮）
const hasCodeField = computed(() => {
  return columnDefs.value.some(col => col.value === 'code')
})

// 是否为策略表（启用指标列分组视觉效果）
const isStrategyTable = computed(() => tableName.value.includes('strategy'))

// 指标列（策略筛选条件）
const indicatorColumns = computed(() =>
  dynamicColumns.value.filter(col => col.group === 'ind')
)

// 回测收益列
const rateColumns = computed(() =>
  dynamicColumns.value.filter(col => col.value.startsWith('rate_'))
)

// 其他动态列（非指标、非回测）
const otherDynamicColumns = computed(() =>
  dynamicColumns.value.filter(col => col.group !== 'ind' && !col.value.startsWith('rate_'))
)

// PR-05-extra: 移动端卡片视图展示的列。优先指标列 + 回测收益列（最多 6 个），不够再补其他列
const mobileCardColumns = computed<ColumnDef[]>(() => {
  const priority = [
    ...indicatorColumns.value,
    ...rateColumns.value,
  ]
  const picked: ColumnDef[] = []
  const seen = new Set<string>()
  for (const c of priority) {
    if (!seen.has(c.value)) { picked.push(c); seen.add(c.value) }
    if (picked.length >= 6) break
  }
  if (picked.length < 6) {
    for (const c of otherDynamicColumns.value) {
      if (seen.has(c.value)) continue
      picked.push(c); seen.add(c.value)
      if (picked.length >= 6) break
    }
  }
  return picked
})

// 搜索关键词
const searchKeyword = ref('')
let searchTimer: ReturnType<typeof setTimeout> | null = null

// 搜索变更时重新请求（防抖 500ms）
const handleSearch = () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    currentPage.value = 1
    loadData()
  }, 500)
}

// 加载数据
const loadData = async () => {
  loading.value = true
  try {
    const params: any = {
      name: tableName.value,
      page: currentPage.value,
      page_size: pageSize.value
    }
    if (selectedDate.value) {
      params.date = selectedDate.value
    }
    if (searchKeyword.value) {
      params.keyword = searchKeyword.value
    }
    // 资金流向系列：服务端排序（默认今日主力净流入-净额降序）
    if (isFundFlow.value && sortField.value) {
      params.sort = sortField.value
      params.order = sortOrder.value
    }
    const res: any = await getStockData(params)
    // 新的响应格式包含 columns、data 和 total
    if (res && res.columns && res.data) {
      columnDefs.value = res.columns
      tableData.value = Array.isArray(res.data) ? res.data : []
      totalCount.value = res.total ?? tableData.value.length
      // 日期回退提示：后端自动切换到最近有数据的日期
      if (res.actual_date && res.actual_date !== selectedDate.value) {
        selectedDate.value = res.actual_date
        ElMessage.info(`${params.date} 暂无数据，已自动切换到最近日期 ${res.actual_date}`)
      }
    } else if (Array.isArray(res)) {
      // 兼容旧格式
      tableData.value = res
      totalCount.value = res.length
    } else {
      tableData.value = []
      totalCount.value = 0
    }
  } catch (error: any) {
    console.error('加载数据失败:', error)
    const errMsg = error?.response?.data?.error || '加载数据失败'
    ElMessage.error(errMsg)
    columnDefs.value = []
    tableData.value = []
    totalCount.value = 0
  } finally {
    loading.value = false
  }
}

const applyRouteQueryFilters = () => {
  const q = route.query as Record<string, any>
  if (typeof q.keyword === 'string') {
    searchKeyword.value = q.keyword.trim()
  } else {
    searchKeyword.value = ''
  }
  if (typeof q.date === 'string' && q.date.trim()) {
    selectedDate.value = q.date.trim()
  } else if (typeof q.keyword === 'string' && q.keyword.trim() && !isFundFlow.value) {
    // 非资金流向页：行业/个股关键词跳转若不带日期，放开日期过滤，避免落到无数据交易日
    // 资金流向页保持"默认最新日期"语义（后端无数据时会自动回退到最近日期），不清空日期
    selectedDate.value = ''
  }
  // 进入页面时重置为默认排序：今日主力净流入-净额由高到低
  sortField.value = 'fund_amount'
  sortOrder.value = 'desc'
}

// 查看指标详情
const viewIndicators = (row: any) => {
  router.push({
    path: '/indicator/detail',
    query: {
      code: row.code,
      date: row.date || selectedDate.value,
      name: row.name,
      strategy: tableName.value
    }
  })
}

const pickField = (row: any, keys: string[]): any => {
  for (const k of keys) {
    const v = row?.[k]
    if (v !== undefined && v !== null && `${v}`.trim() !== '') return v
  }
  return null
}

const toIndustryRow = (row: any): FundFlowRow | null => {
  const name = String(row?.name || row?.industry || '').trim()
  if (!name) return null
  const changeRate = pickField(row, ['change_rate', 'changepercent'])
  const netInflow = pickField(row, [
    'fund_amount',
    'today_main_net_inflow',
    'main_net_inflow',
    'today_main_net_inflow_ratio',
    'net_inflow'
  ])
  const sampleStocks = [
    pickField(row, ['stock_name']),
    pickField(row, ['stock_name_5']),
    pickField(row, ['stock_name_10'])
  ]
    .map((x) => String(x || '').trim())
    .filter(Boolean)
  return {
    name,
    changeRate: changeRate === null ? null : Number(changeRate),
    netInflow: netInflow === null ? null : Number(netInflow),
    sampleStocks: Array.from(new Set(sampleStocks)).slice(0, 6)
  }
}

const handleIndustryRowClick = (row: any) => {
  if (!isFundFlowIndustry.value) return
  const industry = toIndustryRow(row)
  if (!industry) return
  activeIndustry.value = industry
  industryDialogVisible.value = true
}

const goIndustryDetail = (industryName?: string) => {
  const name = industryName || activeIndustry.value?.name
  if (!name) return
  router.push({
    path: '/fund-flow/industry',
    query: { keyword: name }
  })
}

const goSampleStock = (nameOrCode: string) => {
  if (!nameOrCode) return
  router.push({
    path: '/fund-flow/individual',
    query: { keyword: nameOrCode }
  })
}

// 点击"主力净流入最大股"名称 → 进入个股详情页。
// 数据中仅存名称，需先按名称解析出股票代码（依次查 cn_stock_fund_flow → cn_stock_spot），
// 解析成功跳指标详情，全部失败则提示用户。
// 注意：名称可能含内部空格（如 "红 宝 丽"），DB 也以相同格式存储，只能去首尾空格、保留内部空格才能 LIKE 命中。
const goStockDetailByName = async (stockName: string) => {
  const name = String(stockName || '').trim()
  if (!name) return
  // 依次尝试多个表解析股票代码
  const lookupTables = ['cn_stock_fund_flow', 'cn_stock_spot']
  for (const tableName of lookupTables) {
    try {
      const r: any = await getStockData({
        name: tableName,
        keyword: name,
        page: 1,
        page_size: 1
      })
      const row = (r?.data || [])[0]
      const code = row && row.code ? String(row.code) : ''
      if (code) {
        router.push({
          path: '/indicator/detail',
          query: { code, name: row.name || name, date: row.date || selectedDate.value, strategy: 'cn_stock_fund_flow' }
        })
        return
      }
    } catch {
      // 当前表查询失败，继续尝试下一张表
    }
  }
  // 所有表都未解析到代码 → 提示用户，不做无意义跳转
  ElMessage.warning(`"${name}" 暂无个股数据（该股可能未纳入数据采集范围），无法跳转详情`)
}

// 资金流向列排序变更（服务端排序）
const handleSortChange = ({ prop, order }: { prop: string; order: string | null }) => {
  if (!isFundFlow.value) return
  if (prop && order) {
    sortField.value = prop
    sortOrder.value = order === 'ascending' ? 'asc' : 'desc'
  } else {
    // 取消排序 → 回到默认（今日主力净流入-净额降序）
    sortField.value = 'fund_amount'
    sortOrder.value = 'desc'
  }
  currentPage.value = 1
  loadData()
}

const goSampleKline = (s: IndustrySampleStock) => {
  if (!s?.code) return
  router.push({
    path: '/indicator/detail',
    query: {
      code: s.code,
      name: s.name,
      date: s.date || selectedDate.value,
      strategy: 'cn_stock_fund_flow'
    }
  })
}

const goBacktestDashboard = (row: any) => {
  router.push({
    path: '/backtest/dashboard',
    query: buildBacktestDashboardQuery(row)
  })
}

const goBacktestTimeline = (row: any) => {
  router.push({
    path: '/backtest/dashboard',
    query: buildBacktestDashboardQuery(row, 'timeline')
  })
}

const goBacktestDetail = (row: any) => {
  router.push({
    path: '/backtest/dashboard',
    query: buildBacktestDashboardQuery(row, 'detail')
  })
}

const goAnalysis = (row: any) => {
  router.push({
    path: '/ai-report/analysis',
    query: { code: row.code }
  })
}

// 跳转到指标参数设置页（仅指标买/卖榜单工具栏可见）
const goIndicatorParams = () => {
  router.push('/indicator/params')
}

// 关注/取消关注
const handleAttention = async (row: any) => {
  const isCurrentlyAttention = !!row.cdatetime
  try {
    await toggleAttention({
      code: row.code,
      otype: isCurrentlyAttention ? '1' : '0'
    })
    if (isCurrentlyAttention) {
      row.cdatetime = null
      ElMessage.success('已取消关注')
    } else {
      row.cdatetime = new Date().toISOString()
      ElMessage.success('已添加关注')
    }
  } catch (error) {
    ElMessage.error('操作失败')
  }
}

// 格式化大数值为亿/万
const formatLargeNumber = (value: number): string => {
  if (Math.abs(value) >= 100000000) {
    return (value / 100000000).toFixed(2) + '亿'
  } else if (Math.abs(value) >= 10000) {
    return (value / 10000).toFixed(2) + '万'
  }
  return value.toFixed(2)
}

// 已知以"元"为单位的金额字段（需要 亿/万 格式化，即使 dataType 不是 bigint）
const monetaryAmountFields = new Set([
  'net_amount_buy', 'sum_buy', 'sum_sell', 'lhb_amount', 'market_amount',
])

// stock_spot / etf_spot 表中市值字段的原始值单位为"万元"，需先乘 10000 转为元再格式化
const wanyuanSpotTables = new Set(['cn_stock_spot', 'cn_etf_spot', 'cn_index_spot'])
const wanyuanFields = new Set(['total_market_cap', 'free_cap'])

// 不应显示为百分比的字段（用于无 format 元数据的旧表后备逻辑）
const nonPercentFields = new Set([
  'volume_ratio', 'vol_ratio', 'per_netcash_operate', 'equity_multiplier',
  'current_ratio', 'speed_ratio', 'equity_ratio',
  'ma30_ratio', 'back_ratio', 'rise_ratio',
])

// 格式化单元格值（优先使用后端 format 元数据，后备使用字段名启发式）
const formatCellValue = (value: any, col: ColumnDef) => {
  if (value === null || value === undefined) return '-'

  // ===== 优先：后端 format 元数据驱动 =====
  if (col.format && typeof value === 'number') {
    switch (col.format) {
      case 'pct': return value.toFixed(2) + '%'
      case 'price': return value.toFixed(2)
      case 'vol': return formatLargeNumber(value)
      case 'money': return formatLargeNumber(value)
      case 'ratio': return value.toFixed(2)
      case 'int': return Math.round(value).toString()
    }
  }

  // ===== 后备：无元数据的旧表，使用字段名启发式 =====
  const fieldName = col.value
  const dataType = col.dataType || 'string'

  // bigint 类型：大数值字段（成交额、市值等）
  if (dataType === 'bigint') {
    if (typeof value === 'number') {
      if (wanyuanSpotTables.has(tableName.value) && wanyuanFields.has(fieldName)) {
        return formatLargeNumber(value * 10000)
      }
      return formatLargeNumber(value)
    }
    return value
  }

  // 已知金额字段
  if (monetaryAmountFields.has(fieldName)) {
    return typeof value === 'number' ? formatLargeNumber(value) : value
  }

  // 百分比类字段
  if (!nonPercentFields.has(fieldName)) {
    if (fieldName.includes('rate') || fieldName.includes('ratio') ||
        fieldName === 'amplitude' || fieldName === 'turnoverrate' ||
        fieldName === 'p_change' ||
        fieldName.includes('yield') || fieldName.includes('growthrate') ||
        fieldName === 'sale_gpr' || fieldName === 'sale_npr' ||
        fieldName === 'roe_weight' || fieldName === 'jroa' || fieldName === 'roic' ||
        fieldName === 'zxgxl' || fieldName === 'dtsyl') {
      return typeof value === 'number' ? value.toFixed(2) + '%' : value
    }
  }

  // 浮点数保留2位小数
  if (typeof value === 'number' && !Number.isInteger(value)) {
    return value.toFixed(2)
  }

  return value
}

// 获取单元格样式类（优先使用后端 color 元数据）
const getCellClass = (value: any, col: ColumnDef) => {
  // 后端 color 元数据
  if (col.color && typeof value === 'number') {
    if (value > 0) return 'text-up'
    if (value < 0) return 'text-down'
    return ''
  }
  // 后备：旧表的字段名启发式
  const fieldName = col.value
  if (fieldName === 'change_rate' || fieldName === 'ups_downs' ||
      fieldName.includes('change') || fieldName.includes('ranking_after')) {
    if (typeof value === 'number') {
      if (value > 0) return 'text-up'
      if (value < 0) return 'text-down'
    }
  }
  return ''
}

// 获取列最小宽度（用于自适应撑满表格）
const getColumnWidth = (col: ColumnDef) => {
  // 文本类型列（如详因、原因等 VARCHAR 大字段）给予更大的最小宽度
  if (col.dataType === 'string' && col.width && col.width >= 120) {
    return Math.max(col.width, 200)
  }
  if (col.width && col.width > 0) return col.width
  // 默认宽度
  return 100
}

// 日期变更
const handleDateChange = () => {
  currentPage.value = 1
  loadData()
}

// 分页变更
const handlePageChange = () => {
  loadData()
}

const handleSizeChange = () => {
  currentPage.value = 1
  loadData()
}

// 导出 Excel
const exportExcel = () => {
  ElMessage.info('导出功能开发中...')
}

// 获取行样式类名
const getRowClassName = ({ row }: { row: any }) => {
  const classes: string[] = []
  if (row.cdatetime) classes.push('attention-row')
  if (isFundFlowIndustry.value) classes.push('industry-clickable-row')
  return classes.join(' ')
}

// 监听路由变化
watch(
  () => route.fullPath,
  () => {
    applyRouteQueryFilters()
    currentPage.value = 1
    columnDefs.value = []
    lastLoadedPath = route.fullPath
    loadData()
  }
)

// keep-alive 重新激活时，检查路由是否变化并重新加载
let lastLoadedPath = ''
onActivated(() => {
  if (route.fullPath !== lastLoadedPath) {
    applyRouteQueryFilters()
    currentPage.value = 1
    columnDefs.value = []
    lastLoadedPath = route.fullPath
    loadData()
  }
})

onMounted(async () => {
  // 立即记录当前路径，避免 onActivated 在 await 期间重复加载
  lastLoadedPath = route.fullPath
  applyRouteQueryFilters()
  // noDateFilter 模式下不设置日期，加载所有日期的数据
  if (noDateFilter.value) {
    if (!route.query.date) selectedDate.value = ''
    loadData()
    return
  }
  // 从服务端获取正确的交易日期，避免使用客户端本地日期导致日期不匹配
  try {
    const dateRes: any = await getTradeDate()
    if (dateRes && dateRes.run_date && !route.query.date && !route.query.keyword) {
      // 实时数据表用 run_date_nph（含当日未收盘），非实时表用 run_date（仅已收盘）
      const isRealtime = route.meta.isRealtime as boolean
      selectedDate.value = isRealtime ? dateRes.run_date_nph : dateRes.run_date
    }
  } catch {
    // 获取失败时保持客户端日期作为回退
  }
  loadData()
})
</script>

<template>
  <div class="stock-data-container">
    <!-- 顶部工具栏 -->
    <el-card class="toolbar-card" shadow="never">
      <div class="toolbar">
        <div class="toolbar-left">
          <el-tooltip
            v-if="strategyDesc"
            :content="strategyDesc"
            placement="bottom"
            :show-after="200"
            effect="dark"
          >
            <span class="page-title page-title-with-tip">{{ pageTitle }} ⓘ</span>
          </el-tooltip>
          <span v-else class="page-title">{{ pageTitle }}</span>
          <el-date-picker
            v-if="!noDateFilter"
            v-model="selectedDate"
            type="date"
            placeholder="选择日期"
            format="YYYY-MM-DD"
            value-format="YYYY-MM-DD"
            :clearable="false"
            @change="handleDateChange"
          />
          <el-input
            v-model="searchKeyword"
            placeholder="搜索代码/名称"
            clearable
            :style="isMobile ? { width: '100%' } : { width: '200px' }"
            @input="handleSearch"
            @clear="handleSearch"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
        </div>
        <div class="toolbar-right">
          <el-button v-if="isIndicatorSignalTable" type="warning" plain @click="goIndicatorParams">
            <el-icon><Setting /></el-icon>
            {{ isMobile ? '' : '指标设置' }}
          </el-button>
          <el-button @click="loadData">
            <el-icon><Refresh /></el-icon>
            {{ isMobile ? '' : '刷新' }}
          </el-button>
          <el-button type="primary" @click="exportExcel">
            <el-icon><Download /></el-icon>
            {{ isMobile ? '' : '导出' }}
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 数据表格 -->
    <el-card class="table-card" shadow="never">
      <el-table
        v-if="!isMobile"
        v-loading="loading"
        :data="tableData"
        stripe
        border
        :height="isMobile ? 'calc(100dvh - 340px)' : 'calc(100dvh - 280px)'"
        :row-class-name="getRowClassName"
        :default-sort="isFundFlow ? { prop: sortField, order: sortOrder === 'asc' ? 'ascending' : 'descending' } : undefined"
        @row-click="handleIndustryRowClick"
        @sort-change="handleSortChange"
      >
        <el-table-column type="index" label="#" width="50" fixed="left" />
        
        <!-- 固定列：日期 -->
        <el-table-column prop="date" label="日期" width="110" fixed="left" />
        
        <!-- 固定列：代码（如果有） -->
        <el-table-column v-if="hasCodeField" prop="code" label="代码" width="90" fixed="left">
          <template #default="{ row }">
            <el-link type="primary" @click="viewIndicators(row)">
              {{ row.code }}
            </el-link>
          </template>
        </el-table-column>
        
        <!-- 固定列：名称 -->
        <el-table-column prop="name" label="名称" width="100" fixed="left" />
        
        <!-- 策略表：分组显示（筛选指标 + 回测收益） -->
        <template v-if="isStrategyTable && indicatorColumns.length > 0">
          <!-- 筛选指标列组 -->
          <el-table-column label="筛选指标" align="center" header-class-name="indicator-group-header">
            <el-table-column
              v-for="col in indicatorColumns"
              :key="col.value"
              :prop="col.value"
              :min-width="getColumnWidth(col)"
              align="right"
              :show-overflow-tooltip="true"
              header-class-name="indicator-header"
              class-name="indicator-col"
            >
              <template #header>
                <el-tooltip
                  v-if="getColumnTooltip(col.value, tableName)"
                  :content="getColumnTooltip(col.value, tableName)"
                  placement="top"
                  :show-after="300"
                  :hide-after="0"
                  effect="dark"
                  :popper-options="{ modifiers: [{ name: 'computeStyles', options: { adaptive: false } }] }"
                >
                  <span class="header-with-tooltip">{{ col.caption }} ⓘ</span>
                </el-tooltip>
                <span v-else>{{ col.caption }}</span>
              </template>
              <template #default="{ row }">
                <span :class="getCellClass(row[col.value], col)">
                  {{ formatCellValue(row[col.value], col) }}
                </span>
              </template>
            </el-table-column>
          </el-table-column>
          
          <!-- 回测收益列组 -->
          <el-table-column v-if="rateColumns.length > 0" label="回测收益" align="center">
            <el-table-column
              v-for="col in rateColumns"
              :key="col.value"
              :prop="col.value"
              :min-width="getColumnWidth(col)"
              align="right"
              :show-overflow-tooltip="true"
            >
              <template #header>
                <el-tooltip
                  v-if="getColumnTooltip(col.value, tableName)"
                  :content="getColumnTooltip(col.value, tableName)"
                  placement="top"
                  :show-after="300"
                  :hide-after="0"
                  effect="dark"
                  :popper-options="{ modifiers: [{ name: 'computeStyles', options: { adaptive: false } }] }"
                >
                  <span class="header-with-tooltip">{{ col.caption }} ⓘ</span>
                </el-tooltip>
                <span v-else>{{ col.caption }}</span>
              </template>
              <template #default="{ row }">
                <span :class="getCellClass(row[col.value], col)">
                  {{ formatCellValue(row[col.value], col) }}
                </span>
              </template>
            </el-table-column>
          </el-table-column>
          
          <!-- 其他列 -->
          <el-table-column
            v-for="col in otherDynamicColumns"
            :key="col.value"
            :prop="col.value"
            :min-width="getColumnWidth(col)"
            :align="col.dataType === 'string' ? 'left' : 'right'"
            :show-overflow-tooltip="true"
          >
            <template #header>
              <el-tooltip
                v-if="getColumnTooltip(col.value, tableName)"
                :content="getColumnTooltip(col.value, tableName)"
                placement="top"
                :show-after="300"
                :hide-after="0"
                effect="dark"
                :popper-options="{ modifiers: [{ name: 'computeStyles', options: { adaptive: false } }] }"
              >
                <span class="header-with-tooltip">{{ col.caption }} ⓘ</span>
              </el-tooltip>
              <span v-else>{{ col.caption }}</span>
            </template>
            <template #default="{ row }">
              <span :class="getCellClass(row[col.value], col)">
                {{ formatCellValue(row[col.value], col) }}
              </span>
            </template>
          </el-table-column>
        </template>
        
        <!-- 非策略表：平铺显示所有动态列 -->
        <template v-else>
          <el-table-column
            v-for="col in dynamicColumns"
            :key="col.value"
            :prop="col.value"
            :min-width="getColumnWidth(col)"
            :align="col.dataType === 'string' ? 'left' : 'right'"
            :show-overflow-tooltip="true"
            :sortable="isFundFlow && col.dataType !== 'string' ? 'custom' : false"
          >
            <template #header>
              <el-tooltip
                v-if="getColumnTooltip(col.value, tableName)"
                :content="getColumnTooltip(col.value, tableName)"
                placement="top"
                :show-after="300"
                :hide-after="0"
                effect="dark"
                :popper-options="{ modifiers: [{ name: 'computeStyles', options: { adaptive: false } }] }"
              >
                <span class="header-with-tooltip">{{ col.caption }} ⓘ</span>
              </el-tooltip>
              <span v-else>{{ col.caption }}</span>
            </template>
            <template #default="{ row }">
              <el-link
                v-if="isStockNameCol(col.value) && row[col.value]"
                type="primary"
                :underline="false"
                @click.stop="goStockDetailByName(row[col.value])"
              >
                {{ row[col.value] }}
              </el-link>
              <span v-else :class="getCellClass(row[col.value], col)">
                {{ formatCellValue(row[col.value], col) }}
              </span>
            </template>
          </el-table-column>
        </template>
        
        <!-- 固定列：操作 -->
        <el-table-column v-if="hasCodeField || isBacktestSummary" label="操作" width="160" fixed="right" align="center">
          <template #default="{ row }">
            <el-button
              v-if="hasCodeField"
              :type="row.cdatetime ? 'warning' : 'primary'"
              size="small"
              text
              @click="handleAttention(row)"
            >
              <el-icon>
                <StarFilled v-if="row.cdatetime" />
                <Star v-else />
              </el-icon>
              {{ row.cdatetime ? '取消' : '关注' }}
            </el-button>

            <el-button
              v-if="hasCodeField"
              type="success"
              size="small"
              text
              @click="goAnalysis(row)"
            >
              分析
            </el-button>

            <el-button
              v-if="isBacktestSummary"
              type="primary"
              size="small"
              text
              @click="goBacktestDashboard(row)"
            >
              看板
            </el-button>

            <el-button
              v-if="isBacktestSummary"
              type="primary"
              size="small"
              text
              @click="goBacktestTimeline(row)"
            >
              时间序列
            </el-button>

            <el-button
              v-if="isBacktestSummary"
              type="primary"
              size="small"
              text
              @click="goBacktestDetail(row)"
            >
              明细
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- PR-05-extra: 移动端卡片视图 —— 替代窄屏下不可读的横向滚动表 -->
      <div v-else v-loading="loading" class="card-list">
        <div v-if="!loading && tableData.length === 0" class="card-empty">暂无数据</div>
        <div
          v-for="(row, idx) in tableData"
          :key="(row.code || '') + '_' + (row.date || '') + '_' + idx"
          class="stock-card"
          :class="[getRowClassName({ row }), { 'industry-clickable': isFundFlowIndustry }]"
          @click="handleIndustryRowClick(row)"
        >
          <div class="card-head">
            <div class="card-title">
              <el-link
                v-if="hasCodeField"
                type="primary"
                @click="viewIndicators(row)"
              >{{ row.code }}</el-link>
              <span v-else class="card-code">{{ row.code || '-' }}</span>
              <span class="card-name">{{ row.name || '' }}</span>
            </div>
            <div class="card-meta">
              <el-tag size="small" effect="plain">{{ row.date || '' }}</el-tag>
            </div>
          </div>
          <div class="card-body">
            <div
              v-for="col in mobileCardColumns"
              :key="col.value"
              class="card-field"
              :class="{ 'is-indicator': col.group === 'ind', 'is-rate': col.value.startsWith('rate_') }"
            >
              <span class="card-lbl">{{ col.caption }}</span>
              <el-link
                v-if="isStockNameCol(col.value) && row[col.value]"
                type="primary"
                :underline="false"
                class="card-val"
                @click.stop="goStockDetailByName(row[col.value])"
              >
                {{ row[col.value] }}
              </el-link>
              <span v-else class="card-val" :class="getCellClass(row[col.value], col)">
                {{ formatCellValue(row[col.value], col) }}
              </span>
            </div>
          </div>
          <div class="card-actions" v-if="hasCodeField || isBacktestSummary">
            <el-button v-if="hasCodeField" :type="row.cdatetime ? 'warning' : 'primary'" size="small" text @click="handleAttention(row)">
              <el-icon><StarFilled v-if="row.cdatetime" /><Star v-else /></el-icon>
              {{ row.cdatetime ? '取消' : '关注' }}
            </el-button>
            <el-button v-if="hasCodeField" type="success" size="small" text @click="goAnalysis(row)">分析</el-button>
            <el-button v-if="isBacktestSummary" type="primary" size="small" text @click="goBacktestDashboard(row)">看板</el-button>
            <el-button v-if="isBacktestSummary" type="primary" size="small" text @click="goBacktestTimeline(row)">时序</el-button>
            <el-button v-if="isBacktestSummary" type="primary" size="small" text @click="goBacktestDetail(row)">明细</el-button>
          </div>
        </div>
      </div>

      <!-- 分页 -->
      <div class="pagination-wrapper">
        <span class="total-info">
          共 {{ totalCount }} 条记录
        </span>
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[20, 50, 100, 200]"
          :total="totalCount"
          :layout="isMobile ? 'prev, pager, next' : 'sizes, prev, pager, next, jumper'"
          :small="isMobile"
          background
          @current-change="handlePageChange"
          @size-change="handleSizeChange"
        />
      </div>
    </el-card>

    <IndustryTopStocksDialog
      v-model="industryDialogVisible"
      :industry="activeIndustry"
      @open-industry-detail="goIndustryDetail"
      @open-stock-flow="goSampleStock($event.code || $event.name)"
      @open-stock-kline="goSampleKline"
    />
  </div>
</template>

<style lang="scss" scoped>
.stock-data-container {
  height: 100%;
}

.toolbar-card {
  margin-bottom: 16px;
  
  :deep(.el-card__body) {
    padding: 12px 20px;
  }
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  
  .page-title {
    font-size: 16px;
    font-weight: 600;
    color: #303133;
    margin-right: 8px;
  }
  
  .page-title-with-tip {
    cursor: help;
    border-bottom: 1px dashed #909399;
  }
}

.table-card {
  :deep(.el-card__body) {
    padding: 0;
  }
}

.pagination-wrapper {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-top: 1px solid #ebeef5;
  
  .total-info {
    font-size: 14px;
    color: #909399;
  }
}

.text-up {
  color: #f56c6c;
}

.text-down {
  color: #67c23a;
}

:deep(.attention-row) {
  background-color: #fef0f0 !important;
  
  td {
    font-weight: 500;
  }
}

:deep(.el-table__row) {
  &.industry-clickable-row {
    cursor: pointer;
  }
}

:deep(.el-table__row.industry-clickable-row:hover) {
  cursor: pointer;
}

.industry-clickable {
  cursor: pointer;
}

.header-with-tooltip {
  cursor: help;
  border-bottom: 1px dashed #909399;
}

// 筛选指标列组的视觉区分
:deep(.indicator-group-header) {
  background-color: #ecf5ff !important;
  color: #409eff !important;
  font-weight: 600 !important;
}

:deep(.indicator-header) {
  background-color: #f5f7ff !important;
}

:deep(.indicator-col) {
  background-color: #fafbff;
}

/* 移动端：工具栏单列纵向堆叠 + 紧凑分页 */
@media (max-width: 767.98px) {
  .toolbar-card {
    margin-bottom: 8px;
    :deep(.el-card__body) { padding: 10px 12px; }
  }
  .toolbar { gap: 8px; }
  .toolbar-left {
    width: 100%;
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
    .page-title { font-size: 14px; margin-right: 0; }
    :deep(.el-date-editor.el-input),
    :deep(.el-date-editor.el-input__wrapper) { width: 100%; }
  }
  .toolbar-right {
    width: 100%;
    display: flex;
    gap: 8px;
    .el-button { flex: 1; }
  }
  .pagination-wrapper {
    padding: 10px 12px;
    flex-wrap: wrap;
    gap: 8px;
    .total-info { font-size: 12px; }
  }

  /* PR-05-extra: 卡片视图 */
  .card-list {
    padding: 8px 10px 4px;
    max-height: calc(100dvh - 320px);
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .card-empty {
    text-align: center;
    padding: 40px 0;
    color: #909399;
    font-size: 13px;
  }
  .stock-card {
    border: 1px solid #ebeef5;
    border-radius: 6px;
    background: #fff;
    padding: 10px 12px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.02);
  }
  .stock-card .card-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
  }
  .stock-card .card-title {
    display: flex;
    align-items: baseline;
    gap: 8px;
    min-width: 0;
    flex: 1;
    .card-code { font-size: 14px; font-weight: 700; color: #303133; }
    .card-name {
      font-size: 13px; color: #606266;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
  }
  .stock-card .card-body {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 6px 12px;
    margin-bottom: 8px;
  }
  .stock-card .card-field {
    display: flex;
    justify-content: space-between;
    gap: 6px;
    font-size: 12px;
    line-height: 1.4;
    .card-lbl { color: #909399; flex-shrink: 0; }
    .card-val {
      color: #303133;
      font-variant-numeric: tabular-nums;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
  }
  .stock-card .card-field.is-indicator { background: rgba(64,158,255,0.04); padding: 0 4px; border-radius: 2px; }
  .stock-card .card-field.is-rate .card-val { font-weight: 600; }
  .stock-card .card-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    border-top: 1px dashed #f0f0f0;
    padding-top: 6px;
    .el-button { padding: 2px 6px; font-size: 12px; }
  }
  /* 移动端卡片视图行高着色 */
  .stock-card.attention-row { background-color: #fff7e6; }
  .stock-card.text-up-row { border-color: #fbd2d2; }
  .stock-card.text-down-row { border-color: #c8e8c8; }
}
</style>

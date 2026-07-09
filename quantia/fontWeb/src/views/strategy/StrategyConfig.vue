<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getStrategyList,
  getStrategyParams,
  saveStrategyParams,
  resetStrategyParams,
  filterStocks,
  getParamsHistory,
  deleteParamsHistory,
  getParamsDiff
} from '@/api/strategy'
import { toggleAttention } from '@/api/stock'
import dayjs from 'dayjs'
import type { ParamGroup, StrategyListItem } from '@/api/strategy'
import IndicatorThresholdViz from '@/components/IndicatorThresholdViz.vue'
import { useResponsive } from '@/composables/useResponsive'
const { isMobile } = useResponsive()
const route = useRoute()
const router = useRouter()

// ========== 状态 ==========
const strategies = ref<StrategyListItem[]>([])
const activeStrategy = ref((route.meta?.defaultStrategy as string) || 'gpt_value')
const strategyName = ref('')
const strategyDescription = ref('')
const paramGroups = ref<ParamGroup[]>([])
const loading = ref(false)
const saving = ref(false)
const filtering = ref(false)

// 筛选结果
const filterDate = ref(dayjs().format('YYYY-MM-DD'))
const filterResult = ref<any[]>([])
const filterColumns = ref<any[]>([])
const filterTotal = ref(0)
const showResult = ref(false)
const paramsUsed = ref<Record<string, any>>({})

// 分页
const currentPage = ref(1)
const pageSize = ref(50)

// 搜索
const searchKeyword = ref('')
let filterSearchTimer: ReturnType<typeof setTimeout> | null = null

const handleFilterSearch = () => {
  if (filterSearchTimer) clearTimeout(filterSearchTimer)
  filterSearchTimer = setTimeout(() => {
    currentPage.value = 1
    loadFilterResult()
  }, 500)
}

// 是否有自定义修改
const hasCustomParams = computed(() => {
  for (const group of paramGroups.value) {
    for (const param of group.params) {
      if (param.is_custom) return true
    }
  }
  return false
})

// 指标买入/卖出信号：展示阈值确认逻辑可视化
const isIndicatorSignal = computed(
  () => activeStrategy.value === 'indicator_buy' || activeStrategy.value === 'indicator_sell'
)

// ========== 加载策略列表 ==========
const loadStrategies = async () => {
  try {
    const res: any = await getStrategyList()
    strategies.value = res.strategies || []
  } catch (error) {
    console.error('加载策略列表失败:', error)
  }
}

// ========== 加载策略参数 ==========
const loadParams = async () => {
  loading.value = true
  try {
    const res: any = await getStrategyParams(activeStrategy.value)
    strategyName.value = res.name || ''
    strategyDescription.value = res.description || ''
    paramGroups.value = res.groups || []
  } catch (error: any) {
    console.error('加载策略参数失败:', error)
    ElMessage.error('加载策略参数失败')
  } finally {
    loading.value = false
  }
}

// ========== 保存参数 ==========
const handleSave = async () => {
  saving.value = true
  try {
    // 收集所有参数
    const params: Record<string, any> = {}
    for (const group of paramGroups.value) {
      for (const param of group.params) {
        params[param.key] = param.value
      }
    }
    const res: any = await saveStrategyParams(activeStrategy.value, params)
    ElMessage.success(res.message || '保存成功')
    // 重新加载以更新 is_custom 标记
    await loadParams()
  } catch (error) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

// ========== 重置为默认值 ==========
const handleReset = async () => {
  try {
    await ElMessageBox.confirm(
      '确认将所有参数重置为默认值？此操作不可撤销。',
      '重置确认',
      { confirmButtonText: '确认重置', cancelButtonText: '取消', type: 'warning' }
    )
    saving.value = true
    const res: any = await resetStrategyParams(activeStrategy.value)
    ElMessage.success(res.message || '已重置')
    await loadParams()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error('重置失败')
  } finally {
    saving.value = false
  }
}

// ========== 加载筛选结果（支持分页） ==========
const loadFilterResult = async () => {
  filtering.value = true
  try {
    const res: any = await filterStocks(
      activeStrategy.value,
      filterDate.value,
      currentPage.value,
      pageSize.value
    )
    filterColumns.value = res.columns || []
    filterResult.value = Array.isArray(res.data) ? res.data : []
    filterTotal.value = res.total ?? filterResult.value.length
    paramsUsed.value = res.params_used || {}
  } catch (error: any) {
    console.error('加载筛选结果失败:', error)
    ElMessage.error('加载筛选结果失败: ' + (error?.message || '未知错误'))
  } finally {
    filtering.value = false
  }
}

// ========== 执行筛选 ==========
const handleFilter = async () => {
  // 先保存当前参数
  filtering.value = true
  try {
    const params: Record<string, any> = {}
    for (const group of paramGroups.value) {
      for (const param of group.params) {
        params[param.key] = param.value
      }
    }
    await saveStrategyParams(activeStrategy.value, params)

    currentPage.value = 1
    await loadFilterResult()
    showResult.value = true

    if (filterTotal.value === 0) {
      ElMessage.warning('没有符合条件的股票，请尝试放宽筛选条件')
    } else {
      ElMessage.success(`筛选出 ${filterTotal.value} 只股票`)
    }
  } catch (error: any) {
    console.error('筛选失败:', error)
    ElMessage.error('筛选失败: ' + (error?.message || '未知错误'))
  } finally {
    filtering.value = false
  }
}

// ========== 分页变更 ==========
const handleFilterPageChange = () => {
  loadFilterResult()
}

const handleFilterSizeChange = () => {
  currentPage.value = 1
  loadFilterResult()
}

// ========== 查看指标详情 ==========
const viewIndicators = (row: any) => {
  router.push({
    path: '/indicator/detail',
    query: {
      code: row.code,
      date: row.date || filterDate.value,
      name: row.name,
      // 传递当前策略，指标详情页据此在 K 线图上标注该股票历史被本策略选中的时间点
      strategy: activeStrategy.value
    }
  })
}

// ========== 查看回测 ==========
const goBacktest = (row: any) => {
  router.push({
    path: '/backtest/custom',
    query: {
      code: row.code,
      name: row.name
    }
  })
}

// ========== 关注/取消关注 ==========
const handleAttention = async (row: any) => {
  const isAttention = !!row.cdatetime
  try {
    await toggleAttention({
      code: row.code,
      otype: isAttention ? '1' : '0'
    })
    if (isAttention) {
      row.cdatetime = null
      ElMessage.success('已取消关注')
    } else {
      row.cdatetime = new Date().toISOString()
      ElMessage.success('已添加关注')
    }
  } catch {
    ElMessage.error('操作失败')
  }
}

// ========== 格式化 ==========
const formatValue = (value: any) => {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'number' && !Number.isInteger(value)) return value.toFixed(2)
  return value
}

// 监听策略切换
watch(activeStrategy, () => {
  loadParams()
  showResult.value = false
})

// 监听路由变化（在策略参数配置和AI模型设置间切换时更新）
watch(
  () => route.meta?.defaultStrategy,
  (newStrategy) => {
    if (newStrategy && typeof newStrategy === 'string' && newStrategy !== activeStrategy.value) {
      activeStrategy.value = newStrategy
      showResult.value = false
    }
  }
)

onMounted(() => {
  loadStrategies()
  loadParams()
})

// ========== 参数历史 ==========
const showHistory = ref(false)
const historyLoading = ref(false)
const deletingHistory = ref(false)
const historyList = ref<any[]>([])
const selectedVersions = ref<number[]>([])
const selectedHistoryIds = ref<number[]>([])
const diffResult = ref<any>(null)
const diffLoading = ref(false)

const loadHistory = async () => {
  historyLoading.value = true
  showHistory.value = true
  diffResult.value = null
  selectedVersions.value = []
  selectedHistoryIds.value = []
  try {
    const res: any = await getParamsHistory(activeStrategy.value, 50)
    historyList.value = res.data || []
  } catch {
    ElMessage.error('加载历史失败')
  } finally {
    historyLoading.value = false
  }
}

const handleSelectionChange = (rows: any[]) => {
  selectedVersions.value = rows.map((r: any) => r.version).sort((a: number, b: number) => a - b)
  selectedHistoryIds.value = rows.map((r: any) => Number(r.id)).filter((id: number) => Number.isFinite(id))
}

const formatParamValue = (value: any) => {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'boolean') return value ? '开启' : '关闭'
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

const handleDiff = async () => {
  if (selectedVersions.value.length !== 2) {
    ElMessage.warning('请勾选恰好两个版本进行对比')
    return
  }
  diffLoading.value = true
  try {
    const res: any = await getParamsDiff(
      activeStrategy.value,
      selectedVersions.value[0],
      selectedVersions.value[1]
    )
    diffResult.value = res.data || res
  } catch {
    ElMessage.error('对比失败')
  } finally {
    diffLoading.value = false
  }
}

const handleDeleteHistory = async () => {
  if (selectedHistoryIds.value.length === 0) {
    ElMessage.warning('请先选择要删除的变更历史')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认删除选中的 ${selectedHistoryIds.value.length} 条变更历史？删除后不可恢复。`,
      '删除确认',
      { confirmButtonText: '确认删除', cancelButtonText: '取消', type: 'warning' }
    )
    deletingHistory.value = true
    const res: any = await deleteParamsHistory(activeStrategy.value, selectedHistoryIds.value)
    ElMessage.success(res.message || '删除成功')
    diffResult.value = null
    await loadHistory()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  } finally {
    deletingHistory.value = false
  }
}
</script>

<template>
  <div class="strategy-config-container">
    <!-- 策略选择 -->
    <el-card shadow="never" class="strategy-selector-card">
      <div class="strategy-header">
        <el-icon style="font-size: 20px; color: #409eff"><Setting /></el-icon>
        <span class="main-title">策略参数配置</span>
        <el-select v-model="activeStrategy" placeholder="选择策略" style="width: 200px">
          <el-option
            v-for="s in strategies"
            :key="s.key"
            :label="s.name"
            :value="s.key"
          />
        </el-select>
        <el-tag v-if="hasCustomParams" type="warning" effect="plain" size="small">
          已自定义
        </el-tag>
      </div>
      <div class="strategy-desc" v-if="strategyDescription">
        <el-icon><InfoFilled /></el-icon>
        {{ strategyDescription }}
      </div>
    </el-card>

    <!-- 指标买入/卖出信号：阈值确认逻辑可视化说明 -->
    <IndicatorThresholdViz
      v-if="isIndicatorSignal && paramGroups.length"
      :strategy-key="activeStrategy"
      :param-groups="paramGroups"
    />

    <!-- 参数配置区域 -->
    <div class="config-layout" v-loading="loading">
      <!-- 左侧：参数面板 -->
      <div class="params-panel">
        <el-card
          v-for="(group, gi) in paramGroups"
          :key="gi"
          shadow="never"
          class="param-group-card"
        >
          <template #header>
            <div class="group-header">
              <span class="group-title">{{ group.group_name }}</span>
              <span class="group-desc">{{ group.group_description }}</span>
            </div>
          </template>

          <div class="param-list">
            <div v-for="param in group.params" :key="param.key" class="param-item">
              <div class="param-label-row">
                <span class="param-label">
                  {{ param.label }}
                  <el-tag v-if="param.is_custom" size="small" type="success" effect="plain">已修改</el-tag>
                </span>
                <span class="param-unit" v-if="param.unit">{{ param.unit }}</span>
              </div>

              <div class="param-control">
                <!-- 数字类型：滑块+输入 -->
                <template v-if="param.type === 'number'">
                  <el-slider
                    v-model="param.value"
                    :min="param.min"
                    :max="param.max"
                    :step="param.step"
                    :show-tooltip="true"
                    style="flex: 1; margin-right: 16px"
                  />
                  <el-input-number
                    v-model="param.value"
                    :min="param.min"
                    :max="param.max"
                    :step="param.step"
                    :precision="param.step && param.step < 1 ? 2 : 0"
                    size="small"
                    style="width: 120px"
                    controls-position="right"
                  />
                </template>

                <!-- 文本类型 -->
                <template v-else-if="param.type === 'text'">
                  <el-input v-model="param.value" placeholder="请输入" clearable />
                </template>

                <!-- 密码类型 -->
                <template v-else-if="param.type === 'password'">
                  <el-input v-model="param.value" type="password" show-password placeholder="请输入密钥" clearable />
                </template>

                <!-- 选择类型 -->
                <template v-else-if="param.type === 'select'">
                  <el-select v-model="param.value" placeholder="请选择" style="width: 100%">
                    <el-option
                      v-for="opt in param.options"
                      :key="opt.value"
                      :label="opt.label"
                      :value="opt.value"
                    />
                  </el-select>
                </template>

                <!-- 开关类型 -->
                <template v-else-if="param.type === 'switch'">
                  <el-switch
                    v-model="param.value"
                    :active-value="1"
                    :inactive-value="0"
                    active-text="开启"
                    inactive-text="关闭"
                    inline-prompt
                  />
                </template>
              </div>

              <div class="param-description">
                <el-icon><QuestionFilled /></el-icon>
                {{ param.description }}
              </div>
            </div>
          </div>
        </el-card>

        <!-- 操作按钮 -->
        <div class="action-buttons">
          <el-button type="primary" @click="handleSave" :loading="saving" size="large">
            <el-icon><Check /></el-icon>
            保存参数
          </el-button>
          <el-button @click="handleReset" :loading="saving" size="large">
            <el-icon><RefreshLeft /></el-icon>
            恢复默认
          </el-button>
          <el-button @click="loadHistory" size="large">
            <el-icon><Clock /></el-icon>
            变更历史
          </el-button>
          <el-button
            v-if="!['moat_scoring', 'ai_model'].includes(activeStrategy)"
            type="success"
            @click="handleFilter"
            :loading="filtering"
            size="large"
          >
            <el-icon><Search /></el-icon>
            应用筛选
          </el-button>
          <el-date-picker
            v-if="!['moat_scoring', 'ai_model'].includes(activeStrategy)"
            v-model="filterDate"
            type="date"
            placeholder="筛选日期"
            format="YYYY-MM-DD"
            value-format="YYYY-MM-DD"
            :clearable="false"
            style="width: 160px"
          />
        </div>
      </div>
    </div>

    <!-- 筛选结果 -->
    <el-card v-if="showResult" shadow="never" class="result-card">
      <template #header>
        <div class="result-header">
          <span class="result-title">
            <el-icon><DataAnalysis /></el-icon>
            筛选结果
            <el-tag type="info" size="small" style="margin-left: 8px">
              {{ filterDate }} · {{ filterTotal }} 只
            </el-tag>
          </span>
          <el-input
            v-model="searchKeyword"
            placeholder="搜索代码/名称"
            clearable
            style="width: 200px"
            @input="handleFilterSearch"
            @clear="handleFilterSearch"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
        </div>
      </template>

      <!-- 当前参数摘要 -->
      <div class="params-summary" v-if="Object.keys(paramsUsed).length > 0">
        <el-tag
          v-for="(val, key) in paramsUsed"
          :key="key as string"
          type="info"
          effect="plain"
          size="small"
          style="margin: 2px 4px"
        >
          {{ key }}: {{ val }}
        </el-tag>
      </div>

      <el-table
        v-if="!isMobile"
        :data="filterResult"
        stripe
        border
        v-loading="filtering"
        height="400"
      >
        <el-table-column type="index" label="#" width="50" fixed="left" />
        <el-table-column prop="date" label="日期" width="110" fixed="left" />
        <el-table-column prop="code" label="代码" width="90" fixed="left">
          <template #default="{ row }">
            <el-link type="primary" @click="viewIndicators(row)">{{ row.code }}</el-link>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" width="100" fixed="left" />
        <el-table-column prop="pe9" label="PE(TTM)" width="90" align="right">
          <template #default="{ row }"><span>{{ formatValue(row.pe9) }}</span></template>
        </el-table-column>
        <el-table-column prop="roe_weight" label="ROE(%)" width="90" align="right">
          <template #default="{ row }"><span>{{ formatValue(row.roe_weight) }}</span></template>
        </el-table-column>
        <el-table-column prop="sale_gpr" label="毛利率(%)" width="100" align="right">
          <template #default="{ row }"><span>{{ formatValue(row.sale_gpr) }}</span></template>
        </el-table-column>
        <el-table-column prop="sale_npr" label="净利率(%)" width="100" align="right">
          <template #default="{ row }"><span>{{ formatValue(row.sale_npr) }}</span></template>
        </el-table-column>
        <el-table-column prop="income_growthrate_3y" label="营收3年CAGR(%)" width="130" align="right">
          <template #default="{ row }"><span>{{ formatValue(row.income_growthrate_3y) }}</span></template>
        </el-table-column>
        <el-table-column prop="netprofit_growthrate_3y" label="净利润3年CAGR(%)" width="140" align="right">
          <template #default="{ row }"><span>{{ formatValue(row.netprofit_growthrate_3y) }}</span></template>
        </el-table-column>
        <el-table-column prop="debt_asset_ratio" label="资产负债率(%)" width="120" align="right">
          <template #default="{ row }"><span>{{ formatValue(row.debt_asset_ratio) }}</span></template>
        </el-table-column>
        <el-table-column prop="per_netcash_operate" label="每股现金流" width="100" align="right">
          <template #default="{ row }"><span>{{ formatValue(row.per_netcash_operate) }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right" align="center">
          <template #default="{ row }">
            <el-button
              type="primary"
              size="small"
              text
              @click="goBacktest(row)"
            >
              回测
            </el-button>
            <el-button
              :type="row.cdatetime ? 'warning' : 'primary'"
              size="small"
              text
              @click="handleAttention(row)"
            >
              <el-icon>
                <StarFilled v-if="row.cdatetime" />
                <Star v-else />
              </el-icon>
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 移动端卡片视图 -->
      <div v-if="isMobile" v-loading="filtering" class="sc-card-list">
        <el-empty
          v-if="!filtering && filterResult.length === 0"
          description="暂无筛选结果"
          :image-size="60"
        />
        <div v-for="(row, ri) in filterResult" :key="ri" class="sc-card">
          <div class="sc-card-head">
            <div class="sc-card-title">
              <el-link type="primary" @click="viewIndicators(row)">{{ row.code }}</el-link>
              <span class="sc-card-name">{{ row.name }}</span>
            </div>
            <span class="sc-card-date">{{ row.date }}</span>
          </div>
          <div class="sc-card-body">
            <div class="sc-field"><span class="sc-lbl">PE(TTM)</span><span>{{ formatValue(row.pe9) }}</span></div>
            <div class="sc-field"><span class="sc-lbl">ROE(%)</span><span>{{ formatValue(row.roe_weight) }}</span></div>
            <div class="sc-field"><span class="sc-lbl">毛利率(%)</span><span>{{ formatValue(row.sale_gpr) }}</span></div>
            <div class="sc-field"><span class="sc-lbl">净利率(%)</span><span>{{ formatValue(row.sale_npr) }}</span></div>
            <div class="sc-field"><span class="sc-lbl">营收3年CAGR(%)</span><span>{{ formatValue(row.income_growthrate_3y) }}</span></div>
            <div class="sc-field"><span class="sc-lbl">净利3年CAGR(%)</span><span>{{ formatValue(row.netprofit_growthrate_3y) }}</span></div>
            <div class="sc-field"><span class="sc-lbl">资产负债率(%)</span><span>{{ formatValue(row.debt_asset_ratio) }}</span></div>
            <div class="sc-field"><span class="sc-lbl">每股现金流</span><span>{{ formatValue(row.per_netcash_operate) }}</span></div>
          </div>
          <div class="sc-card-ops">
            <span class="sc-op" @click="goBacktest(row)">回测</span>
            <span class="sc-op-sep">|</span>
            <span class="sc-op" @click="handleAttention(row)">{{ row.cdatetime ? '取消关注' : '加关注' }}</span>
          </div>
        </div>
      </div>

      <div class="pagination-wrapper">
        <span class="total-info">共 {{ filterTotal }} 条记录</span>
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[20, 50, 100, 200]"
          :total="filterTotal"
          layout="sizes, prev, pager, next, jumper"
          background
          @current-change="handleFilterPageChange"
          @size-change="handleFilterSizeChange"
        />
      </div>
    </el-card>

    <!-- 参数变更历史对话框 -->
    <el-dialog v-model="showHistory" title="参数变更历史" width="min(1120px, 94vw)" destroy-on-close>
      <div class="history-toolbar">
        <el-button
          type="primary"
          size="small"
          :disabled="selectedVersions.length !== 2"
          :loading="diffLoading"
          @click="handleDiff"
        >
          对比选中的两个版本
        </el-button>
        <el-button
          type="danger"
          size="small"
          :disabled="selectedHistoryIds.length === 0"
          :loading="deletingHistory"
          @click="handleDeleteHistory"
        >
          删除选中历史
        </el-button>
        <span v-if="selectedVersions.length > 0" style="font-size: 12px; color: #909399;">
          已选 {{ selectedVersions.length }} 个版本 / {{ selectedHistoryIds.length }} 条历史
        </span>
      </div>

      <el-table
        :data="historyList"
        v-loading="historyLoading"
        border
        stripe
        max-height="420"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="45" />
        <el-table-column prop="version" label="版本" width="70" align="center" />
        <el-table-column label="变更参数" min-width="520">
          <template #default="{ row }">
            <div v-if="row.changed_items?.length" class="history-change-list">
              <div v-for="item in row.changed_items" :key="item.key" class="history-change-item">
                <span class="change-label">{{ item.label }}</span>
                <span class="change-value before">{{ formatParamValue(item.before_value) }}</span>
                <span class="change-arrow">→</span>
                <span class="change-value after">{{ formatParamValue(item.after_value) }}</span>
              </div>
            </div>
            <div v-else>
              <el-tag
                v-for="label in (row.changed_labels || row.changed_keys || [])"
                :key="label"
                size="small"
                type="info"
                effect="plain"
                style="margin: 2px;"
              >{{ label }}</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="source" label="操作" width="80" align="center">
          <template #default="{ row }">
            <el-tag :type="row.source === 'reset' ? 'warning' : 'info'" size="small">
              {{ row.source === 'reset' ? '重置' : '修改' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" width="170" />
      </el-table>

      <!-- 对比结果 -->
      <div v-if="diffResult" style="margin-top: 16px;">
        <el-divider content-position="left">
          版本 {{ diffResult.v1 }} → {{ diffResult.v2 }} 参数差异
        </el-divider>
        <el-table :data="diffResult.diffs" border stripe size="small" v-if="diffResult.diffs?.length">
          <el-table-column prop="label" label="参数" width="200" />
          <el-table-column :label="'版本' + diffResult.v1" align="right">
            <template #default="{ row }">
              <span style="color: #f56c6c;">{{ formatParamValue(row.v1_value) }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="'版本' + diffResult.v2" align="right">
            <template #default="{ row }">
              <span style="color: #67c23a;">{{ formatParamValue(row.v2_value) }}</span>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="两个版本无差异" :image-size="60" />
      </div>
    </el-dialog>
  </div>
</template>

<style lang="scss" scoped>
.strategy-config-container {
  padding: 0;
}

.strategy-selector-card {
  margin-bottom: 16px;

  :deep(.el-card__body) {
    padding: 16px 20px;
  }
}

.strategy-header {
  display: flex;
  align-items: center;
  gap: 12px;

  .main-title {
    font-size: 18px;
    font-weight: 600;
    color: #303133;
  }
}

.strategy-desc {
  margin-top: 10px;
  font-size: 13px;
  color: #909399;
  display: flex;
  align-items: flex-start;
  gap: 6px;
  line-height: 1.5;
}

.config-layout {
  display: flex;
  gap: 16px;
}

.params-panel {
  flex: 1;
}

.param-group-card {
  margin-bottom: 16px;

  :deep(.el-card__header) {
    padding: 12px 20px;
    background: #fafafa;
  }
}

.group-header {
  display: flex;
  flex-direction: column;
  gap: 4px;

  .group-title {
    font-size: 15px;
    font-weight: 600;
    color: #303133;
  }

  .group-desc {
    font-size: 12px;
    color: #909399;
  }
}

.param-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.param-item {
  padding: 12px 0;
  border-bottom: 1px dashed #ebeef5;

  &:last-child {
    border-bottom: none;
    padding-bottom: 0;
  }
}

.param-label-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;

  .param-label {
    font-size: 14px;
    font-weight: 500;
    color: #303133;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .param-unit {
    font-size: 12px;
    color: #909399;
    background: #f4f4f5;
    padding: 2px 8px;
    border-radius: 4px;
  }
}

.param-control {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.param-description {
  font-size: 12px;
  color: #a8abb2;
  display: flex;
  align-items: flex-start;
  gap: 4px;
  line-height: 1.5;
}

.action-buttons {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 20px 0;
  flex-wrap: wrap;
}

.history-toolbar {
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.history-change-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.history-change-item {
  display: grid;
  grid-template-columns: minmax(120px, 180px) minmax(70px, 1fr) 20px minmax(70px, 1fr);
  align-items: center;
  gap: 6px;
  line-height: 1.4;
}

.change-label {
  color: #606266;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.change-value {
  min-width: 0;
  padding: 2px 6px;
  border-radius: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;

  &.before {
    color: #c45656;
    background: #fef0f0;
  }

  &.after {
    color: #529b2e;
    background: #f0f9eb;
  }
}

.change-arrow {
  color: #909399;
  text-align: center;
}

.result-card {
  margin-top: 16px;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;

  .result-title {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 16px;
    font-weight: 600;
  }
}

.params-summary {
  margin-bottom: 12px;
  padding: 8px 12px;
  background: #f5f7fa;
  border-radius: 4px;
}

.pagination-wrapper {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 0 0;

  .total-info {
    font-size: 14px;
    color: #909399;
  }
}

/* ─── 移动端卡片视图 ─── */
.sc-card-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.sc-card {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 10px 12px;
}
.sc-card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 8px;
  border-bottom: 1px dashed #ebeef5;
}
.sc-card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}
.sc-card-name {
  color: #303133;
  font-size: 14px;
}
.sc-card-date {
  font-size: 12px;
  color: #909399;
}
.sc-card-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 12px;
  font-size: 13px;
  padding: 8px 0;
}
.sc-field {
  display: flex;
  justify-content: space-between;
}
.sc-lbl {
  color: #909399;
}
.sc-card-ops {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px dashed #ebeef5;
}
.sc-op {
  color: #409eff;
  cursor: pointer;
  font-size: 13px;
}
.sc-op-sep {
  color: #dcdfe6;
}

@media (max-width: 767.98px) {
  .config-layout {
    flex-direction: column;
    gap: 12px;
  }
  .action-buttons {
    padding: 12px 0;
    :deep(.el-button) {
      flex: 1 1 auto;
    }
  }
  .result-header {
    flex-wrap: wrap;
    gap: 8px;
    :deep(.el-input) {
      width: 100% !important;
    }
  }
  .strategy-header {
    flex-wrap: wrap;
    gap: 8px;
  }
  .pagination-wrapper {
    flex-direction: column;
    gap: 8px;
    align-items: stretch;
  }
}
</style>

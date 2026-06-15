<template>
  <div class="ind-params-page">
    <!-- 头部说明 -->
    <el-card shadow="never" class="ip-head">
      <div class="ip-head-title">
        <span class="ip-title">指标买卖信号 · 参数设置</span>
        <el-tag size="small" type="info" effect="plain">strategy_key: indicator_signal</el-tag>
      </div>
      <div class="ip-head-desc">{{ strategyDescription }}</div>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        class="ip-tip"
        title="提示"
      >
        <template #default>
          调整阈值并「保存」后，下一次定时计算会生效；如需立即看到效果，请点击「立即重算」。
          想对单只股票做 AI 深度分析，可在
          <el-link type="primary" :underline="false" @click="goBuyList">指标买入</el-link> /
          <el-link type="primary" :underline="false" @click="goSellList">指标卖出</el-link>
          榜单中点击对应行的「分析」按钮。
        </template>
      </el-alert>
    </el-card>

    <!-- 操作栏 -->
    <el-card shadow="never" class="ip-toolbar">
      <div class="ip-toolbar-row" :class="{ 'is-mobile': isMobile }">
        <div class="ip-toolbar-left">
          <el-button type="primary" :loading="saving" @click="handleSave">保存参数</el-button>
          <el-button :loading="saving" @click="handleReset">重置默认</el-button>
        </div>
        <div class="ip-toolbar-right">
          <el-date-picker
            v-model="recomputeDate"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="重算日期(默认最新)"
            :clearable="true"
            :style="{ width: isMobile ? '100%' : '180px' }"
          />
          <el-button type="success" :loading="recomputing" @click="handleRecompute">
            立即重算
          </el-button>
          <el-button type="warning" plain :loading="advising" @click="handleAdvise">
            <el-icon style="margin-right: 4px"><MagicStick /></el-icon>
            AI 推荐参数
          </el-button>
        </div>
      </div>
      <div v-if="recomputeMsg" class="ip-recompute-msg">{{ recomputeMsg }}</div>
    </el-card>

    <!-- AI 推荐结果 -->
    <el-card v-if="advice" shadow="never" class="ip-advice">
      <template #header>
        <div class="ip-advice-head">
          <span><el-icon><MagicStick /></el-icon> AI 参数推荐</span>
          <el-button
            type="primary"
            size="small"
            :disabled="!adviceRows.length"
            @click="applyAdvice"
          >一键填入</el-button>
        </div>
      </template>
      <p v-if="advice.summary" class="ip-advice-summary">{{ advice.summary }}</p>
      <p v-if="advice.current_counts" class="ip-advice-counts">
        当前命中：买入 {{ advice.current_counts.buy ?? '-' }} 只 / 卖出
        {{ advice.current_counts.sell ?? '-' }} 只
      </p>

      <template v-if="adviceRows.length">
        <!-- 桌面表格 -->
        <el-table v-if="!isMobile" :data="adviceRows" size="small" border>
          <el-table-column prop="label" label="参数" min-width="150" />
          <el-table-column prop="current" label="当前值" width="100" align="center" />
          <el-table-column prop="recommended" label="推荐值" width="100" align="center">
            <template #default="{ row }">
              <span class="ip-rec-val">{{ row.recommended }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="reason" label="理由" min-width="220" show-overflow-tooltip />
        </el-table>
        <!-- 移动端卡片 -->
        <div v-else class="ip-adv-card-list">
          <div v-for="row in adviceRows" :key="row.key" class="ip-adv-card">
            <div class="ip-adv-card-head">{{ row.label }}</div>
            <div class="ip-adv-card-body">
              <div class="ip-adv-field"><span class="ip-lbl">当前</span><span>{{ row.current }}</span></div>
              <div class="ip-adv-field"><span class="ip-lbl">推荐</span><span class="ip-rec-val">{{ row.recommended }}</span></div>
              <div class="ip-adv-field ip-adv-full"><span class="ip-lbl">理由</span><span>{{ row.reason }}</span></div>
            </div>
          </div>
        </div>
      </template>
      <el-empty v-else description="AI 未给出可应用的推荐" :image-size="60" />
    </el-card>

    <!-- 参数分组 -->
    <div v-loading="loading">
      <el-card
        v-for="group in paramGroups"
        :key="group.group_name"
        shadow="never"
        class="ip-group"
      >
        <template #header>
          <div class="ip-group-head">
            <span class="ip-group-name">{{ group.group_name }}</span>
            <span class="ip-group-desc">{{ group.group_description }}</span>
          </div>
        </template>
        <div class="ip-param-list">
          <div
            v-for="param in group.params"
            :key="param.key"
            class="ip-param-row"
            :class="{ 'is-mobile': isMobile }"
          >
            <div class="ip-param-label">
              <span class="ip-param-name">{{ param.label }}</span>
              <el-tooltip :content="param.description" placement="top" effect="dark">
                <el-icon class="ip-q"><QuestionFilled /></el-icon>
              </el-tooltip>
              <el-tag v-if="param.is_custom" size="small" type="success" effect="plain">已改</el-tag>
            </div>
            <div class="ip-param-control">
              <el-switch
                v-if="param.type === 'switch'"
                v-model="param.value"
                :active-value="1"
                :inactive-value="0"
              />
              <el-input-number
                v-else
                v-model="param.value"
                :min="param.min"
                :max="param.max"
                :step="param.step"
                :controls-position="isMobile ? 'right' : ''"
                :style="{ width: isMobile ? '140px' : '160px' }"
              />
              <span v-if="param.unit" class="ip-unit">{{ param.unit }}</span>
            </div>
          </div>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { QuestionFilled, MagicStick } from '@element-plus/icons-vue'
import { useResponsive } from '@/composables/useResponsive'
import type { ParamGroup } from '@/api/strategy'
import {
  getIndicatorParams,
  saveIndicatorParams,
  resetIndicatorParams,
  recomputeIndicatorSignals,
  getIndicatorAdvice,
  type AdvisorResult
} from '@/api/indicatorParams'

const { isMobile } = useResponsive()
const router = useRouter()

const loading = ref(false)
const saving = ref(false)
const recomputing = ref(false)
const advising = ref(false)

const strategyDescription = ref('')
const paramGroups = ref<ParamGroup[]>([])

const recomputeDate = ref('')
const recomputeMsg = ref('')
const advice = ref<AdvisorResult | null>(null)

// 扁平 key → label 映射，便于推荐表展示
const labelMap = computed(() => {
  const m: Record<string, string> = {}
  for (const g of paramGroups.value) for (const p of g.params) m[p.key] = p.label
  return m
})
const valueMap = computed(() => {
  const m: Record<string, any> = {}
  for (const g of paramGroups.value) for (const p of g.params) m[p.key] = p.value
  return m
})

const adviceRows = computed(() => {
  if (!advice.value || !advice.value.recommendations) return []
  const recs = advice.value.recommendations
  const reasons = advice.value.reasons || {}
  return Object.keys(recs).map((key) => ({
    key,
    label: labelMap.value[key] || key,
    current: valueMap.value[key],
    recommended: recs[key],
    reason: reasons[key] || ''
  }))
})

const loadParams = async () => {
  loading.value = true
  try {
    const res: any = await getIndicatorParams()
    strategyDescription.value = res.description || ''
    paramGroups.value = res.groups || []
  } catch (e) {
    console.error('加载指标参数失败:', e)
    ElMessage.error('加载指标参数失败')
  } finally {
    loading.value = false
  }
}

const collectParams = () => {
  const params: Record<string, any> = {}
  for (const g of paramGroups.value) for (const p of g.params) params[p.key] = p.value
  return params
}

const handleSave = async () => {
  saving.value = true
  try {
    const res: any = await saveIndicatorParams(collectParams())
    ElMessage.success(res.message || '保存成功')
    await loadParams()
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

const handleReset = async () => {
  try {
    await ElMessageBox.confirm('确认将所有指标参数重置为默认值？', '重置确认', {
      confirmButtonText: '确认重置',
      cancelButtonText: '取消',
      type: 'warning'
    })
    saving.value = true
    const res: any = await resetIndicatorParams()
    ElMessage.success(res.message || '已重置')
    await loadParams()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error('重置失败')
  } finally {
    saving.value = false
  }
}

const handleRecompute = async () => {
  recomputing.value = true
  recomputeMsg.value = ''
  try {
    // 先保存当前参数，确保重算用的是页面上的值
    await saveIndicatorParams(collectParams())
    const res: any = await recomputeIndicatorSignals(recomputeDate.value || undefined)
    if (res.success) {
      recomputeMsg.value = res.message || `已重算：买入 ${res.buy_count} / 卖出 ${res.sell_count}`
      ElMessage.success(recomputeMsg.value)
    } else {
      ElMessage.error(res.error || '重算失败')
    }
  } catch (e: any) {
    ElMessage.error('重算失败: ' + (e?.message || '未知错误'))
  } finally {
    recomputing.value = false
  }
}

const handleAdvise = async () => {
  advising.value = true
  try {
    const res: any = await getIndicatorAdvice({ date: recomputeDate.value || undefined })
    if (res.success) {
      advice.value = res
      if (!res.recommendations || !Object.keys(res.recommendations).length) {
        ElMessage.warning('AI 未给出可应用的推荐')
      }
    } else {
      advice.value = null
      ElMessage.error(res.error || 'AI 推荐失败')
    }
  } catch (e: any) {
    ElMessage.error('AI 推荐失败: ' + (e?.message || '未知错误'))
  } finally {
    advising.value = false
  }
}

const applyAdvice = () => {
  if (!advice.value || !advice.value.recommendations) return
  const recs = advice.value.recommendations
  let applied = 0
  for (const g of paramGroups.value) {
    for (const p of g.params) {
      if (Object.prototype.hasOwnProperty.call(recs, p.key)) {
        p.value = recs[p.key]
        applied++
      }
    }
  }
  ElMessage.success(`已填入 ${applied} 项推荐值，记得点击「保存参数」`)
}

const goBuyList = () => router.push('/indicator/buy')
const goSellList = () => router.push('/indicator/sell')

onMounted(loadParams)
</script>

<style scoped>
.ind-params-page {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.ip-head-title {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.ip-title {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}
.ip-head-desc {
  margin: 8px 0;
  color: #606266;
  font-size: 13px;
  line-height: 1.6;
}
.ip-tip {
  margin-top: 8px;
}

.ip-toolbar-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.ip-toolbar-row.is-mobile {
  flex-direction: column;
  align-items: stretch;
}
.ip-toolbar-left,
.ip-toolbar-right {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.ip-toolbar-row.is-mobile .ip-toolbar-left,
.ip-toolbar-row.is-mobile .ip-toolbar-right {
  width: 100%;
}
.ip-recompute-msg {
  margin-top: 10px;
  color: #67c23a;
  font-size: 13px;
}

.ip-advice-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.ip-advice-summary {
  color: #303133;
  font-size: 14px;
  line-height: 1.7;
  margin: 0 0 8px;
}
.ip-advice-counts {
  color: #909399;
  font-size: 12px;
  margin: 0 0 12px;
}
.ip-rec-val {
  color: #e6a23c;
  font-weight: 600;
}

.ip-group-head {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.ip-group-name {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}
.ip-group-desc {
  font-size: 12px;
  color: #909399;
}
.ip-param-list {
  display: flex;
  flex-direction: column;
}
.ip-param-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px dashed #ebeef5;
  gap: 12px;
}
.ip-param-row:last-child {
  border-bottom: none;
}
.ip-param-row.is-mobile {
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}
.ip-param-label {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.ip-param-name {
  font-size: 14px;
  color: #303133;
}
.ip-q {
  color: #c0c4cc;
  cursor: help;
}
.ip-param-control {
  display: flex;
  align-items: center;
  gap: 6px;
}
.ip-unit {
  color: #909399;
  font-size: 13px;
}

/* AI 推荐移动端卡片 */
.ip-adv-card-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.ip-adv-card {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 10px 12px;
}
.ip-adv-card-head {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
  border-bottom: 1px dashed #ebeef5;
  padding-bottom: 6px;
  margin-bottom: 8px;
}
.ip-adv-card-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 12px;
  font-size: 13px;
}
.ip-adv-field {
  display: flex;
  gap: 8px;
  align-items: baseline;
}
.ip-adv-full {
  grid-column: 1 / -1;
}
.ip-lbl {
  color: #909399;
  white-space: nowrap;
}
</style>

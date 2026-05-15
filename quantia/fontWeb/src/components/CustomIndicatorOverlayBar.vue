<template>
  <div class="ci-overlay-bar">
    <span class="ci-label">自定义指标</span>
    <el-select v-model="state.selectedId.value" placeholder="选择指标" size="small" clearable filterable
               :loading="state.loadingList.value" style="width: 200px;">
      <el-option v-for="it in state.indicatorList.value" :key="it.indicator_id"
                 :value="it.indicator_id" :label="it.name">
        <span style="float: left;">{{ it.name }}</span>
        <span style="float: right; color: #909399; font-size: 12px;">
          {{ it.kind === 'primary_entry' ? '主信号' : '预警' }}
        </span>
      </el-option>
    </el-select>
    <el-radio-group v-model="state.mode.value" size="small" :disabled="!state.selectedId.value">
      <el-radio-button label="off">关闭</el-radio-button>
      <el-radio-button label="main">🎯 主图</el-radio-button>
      <el-radio-button label="sub">📊 副图</el-radio-button>
      <el-radio-button label="both">🔀 双开</el-radio-button>
    </el-radio-group>
    <el-icon v-if="state.loadingSeries.value" class="is-loading"><Loading /></el-icon>
    <span v-if="state.errorMsg.value" class="ci-error">{{ state.errorMsg.value }}</span>
  </div>
</template>

<script setup lang="ts">
import { Loading } from '@element-plus/icons-vue'
import type { useCustomIndicatorOverlay } from '@/composables/useCustomIndicatorOverlay'

defineProps<{
  state: ReturnType<typeof useCustomIndicatorOverlay>
}>()
</script>

<style scoped>
.ci-overlay-bar {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px;
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  margin-left: 12px;
}
.ci-label {
  color: #606266;
  font-size: 12px;
}
.ci-error {
  color: #e6a23c;
  font-size: 12px;
  margin-left: 4px;
}
</style>

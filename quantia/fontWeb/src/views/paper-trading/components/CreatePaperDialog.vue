<template>
  <el-dialog
    v-model="visible"
    title="新建模拟交易"
    width="min(520px, 92vw)"
    :top="isMobile ? '3vh' : '15vh'"
  >
    <el-form label-width="120px" class="paper-create-form">
      <el-form-item label="交易名称">
        <el-input v-model="form.name" placeholder="模拟交易名称（可选）" />
      </el-form-item>
      <el-form-item label="选择策略" required>
        <el-select
          v-model="form.strategy_id"
          placeholder="请选择一个策略"
          style="width: 100%;"
          filterable
          @change="$emit('strategy-change', $event)"
        >
          <el-option v-for="s in strategies" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="选择回测" required>
        <el-select
          v-model="form.backtest_id"
          placeholder="请选择该策略的一个回测版本"
          style="width: 100%;"
          filterable
          :loading="backtestsLoading"
          :disabled="!form.strategy_id"
          @change="$emit('backtest-change', $event)"
        >
          <el-option
            v-for="bt in strategyBacktests"
            :key="bt.id"
            :label="formatters.backtestOptionLabel(bt)"
            :value="bt.id"
          >
            <div class="bt-option">
              <span class="bt-option-name">{{ bt.strategy_name || `回测-${bt.id}` }}</span>
              <span :class="formatters.retCls(bt.total_return)">{{ formatters.fmtPct(bt.total_return) }}</span>
            </div>
          </el-option>
        </el-select>
        <div
          v-if="form.strategy_id && !backtestsLoading && strategyBacktests.length === 0"
          class="form-tip"
        >该策略暂无已完成回测，请先运行一次组合回测。</div>
      </el-form-item>
      <el-form-item label="初始资金">
        <el-input-number v-model="form.initial_cash" :min="10000" :step="100000" style="width: 100%;" />
      </el-form-item>
      <el-form-item label="运行频率" required>
        <div class="form-inline-row">
          <el-select v-model="form.run_frequency" style="width: 130px;">
            <el-option v-for="f in frequencyOptions" :key="f.value" :label="f.label" :value="f.value" />
          </el-select>
          <span class="inline-label">开始时间</span>
          <el-date-picker
            v-model="form.start_at"
            type="datetime"
            value-format="YYYY-MM-DD HH:mm:ss"
            format="YYYY-MM-DD HH:mm"
            style="flex: 1;"
          />
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="creating" @click="$emit('submit')">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
interface CreateForm {
  strategy_id: number | null
  backtest_id: number | null
  name: string
  initial_cash: number
  run_frequency: 'daily' | 'hourly' | '15m'
  start_at: string
}
interface Formatters {
  backtestOptionLabel: (bt: any) => string
  retCls: (v: number | undefined | null) => string
  fmtPct: (v: number | undefined | null, d?: number) => string
}
interface FreqOpt { label: string; value: string }

defineProps<{
  form: CreateForm
  strategies: any[]
  strategyBacktests: any[]
  backtestsLoading: boolean
  creating: boolean
  isMobile: boolean
  frequencyOptions: ReadonlyArray<FreqOpt>
  formatters: Formatters
}>()

defineEmits<{
  (e: 'strategy-change', val: number | null): void
  (e: 'backtest-change', val: number | null): void
  (e: 'submit'): void
}>()

const visible = defineModel<boolean>('visible', { required: true })
</script>

<style scoped>
.paper-create-form :deep(.el-form-item) { margin-bottom: 18px; }
.form-inline-row { display: flex; align-items: center; gap: 10px; width: 100%; min-width: 0; }
.inline-label { color: #606266; white-space: nowrap; }
.form-tip { margin-top: 6px; font-size: 12px; color: #909399; line-height: 1.4; }
.bt-option { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.bt-option-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.val-red { color: #f56c6c !important; }
.val-green { color: #67c23a !important; }
</style>

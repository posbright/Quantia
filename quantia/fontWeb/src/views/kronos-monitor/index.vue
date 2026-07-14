<template>
  <div class="kronos-page" v-loading="loading">
    <header class="page-head">
      <div>
        <div class="eyebrow">MODEL VALIDATION CONTROL</div>
        <h1>Kronos 验证</h1>
        <div class="head-meta">
          <el-tag :type="health.reachable ? 'success' : 'danger'" effect="dark">
            {{ health.reachable ? '推理服务在线' : '推理服务离线' }}
          </el-tag>
          <el-tag :type="qualificationTag" effect="plain">{{ qualificationText }}</el-tag>
          <span v-if="config.config_hash" class="hash">{{ config.config_hash }}</span>
        </div>
      </div>
      <el-button :icon="Refresh" circle title="刷新" :loading="loading" @click="refresh" />
    </header>

    <el-alert
      v-if="config.qualification_status !== 'qualified'"
      title="当前预设仅用于影子验证，不参与交易决策"
      type="warning"
      :closable="false"
      show-icon
      class="gate-alert"
    />

    <section class="metric-grid">
      <article class="metric-block">
        <span>H2 总进度</span>
        <strong>{{ progressText }}</strong>
        <el-progress :percentage="progressPercent" :stroke-width="6" :show-text="false" />
      </article>
      <article class="metric-block">
        <span>有效记录</span>
        <strong>{{ latestRun?.observed ?? 0 }}</strong>
        <small>审计 {{ latestRun?.audited ?? 0 }} · 错误 {{ latestRun?.provider_errors ?? 0 }}</small>
      </article>
      <article class="metric-block">
        <span>配置门禁</span>
        <strong>{{ latestRun?.qualified_count ?? 0 }} / {{ latestRun?.configuration_count ?? 0 }}</strong>
        <small>完成 {{ latestRun?.completed_configurations ?? 0 }} 个配置</small>
      </article>
    </section>

    <el-tabs v-model="activeTab" class="workspace-tabs">
      <el-tab-pane label="参数预设" name="config">
        <section class="workspace-section">
          <div class="section-head">
            <div>
              <h2>影子预设</h2>
              <p>{{ config.preset_name }}</p>
            </div>
            <el-button type="primary" :icon="Check" :loading="saving" @click="saveConfig">保存预设</el-button>
          </div>

          <el-form :model="config" label-position="top" class="config-grid">
            <el-form-item label="预设名称"><el-input v-model="config.preset_name" maxlength="80" /></el-form-item>
            <el-form-item label="运行模式">
              <el-segmented v-model="config.mode" :options="modeOptions" :disabled="config.qualification_status !== 'qualified'" />
            </el-form-item>
            <el-form-item label="Lookback"><el-input-number v-model="config.lookback" :min="32" :max="512" :step="16" /></el-form-item>
            <el-form-item label="Horizons">
              <el-select v-model="config.horizons" multiple><el-option v-for="item in horizonOptions" :key="item" :label="`${item} 日`" :value="item" /></el-select>
            </el-form-item>
            <el-form-item label="Sample count"><el-input-number v-model="config.sample_count" :min="1" :max="64" /></el-form-item>
            <el-form-item label="Sample batch"><el-input-number v-model="config.sample_batch_size" :min="1" :max="config.sample_count" /></el-form-item>
            <el-form-item label="Temperature"><el-input-number v-model="config.temperature" :min="0.05" :max="5" :step="0.05" :precision="2" /></el-form-item>
            <el-form-item label="Top K"><el-input-number v-model="config.top_k" :min="0" :max="1024" /></el-form-item>
            <el-form-item label="Top P"><el-input-number v-model="config.top_p" :min="0.01" :max="1" :step="0.05" :precision="2" /></el-form-item>
            <el-form-item label="Clip"><el-input-number v-model="config.clip" :min="1" :max="20" :step="0.5" /></el-form-item>
            <el-form-item label="Timeout"><el-input-number v-model="config.timeout_seconds" :min="1" :max="3600" /><span class="unit">秒</span></el-form-item>
            <el-form-item label="自动批量"><el-switch v-model="config.enabled" :disabled="config.qualification_status !== 'qualified'" /></el-form-item>
            <el-form-item label="Provider URL" class="wide"><el-input v-model="config.provider_url" /></el-form-item>
            <el-form-item label="备注" class="wide"><el-input v-model="config.notes" type="textarea" :rows="3" maxlength="1000" show-word-limit /></el-form-item>
          </el-form>
        </section>
      </el-tab-pane>

      <el-tab-pane label="运行批次" name="runs">
        <section class="workspace-section">
          <div class="section-head"><div><h2>实验批次</h2><p>最近 {{ runs.length }} 次参数搜索</p></div></div>
          <el-table v-if="!isMobile" :data="runs" stripe>
            <el-table-column prop="name" label="批次" min-width="260" />
            <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="runTag(row.status)">{{ runText(row.status) }}</el-tag></template></el-table-column>
            <el-table-column label="配置" width="110"><template #default="{ row }">{{ row.completed_configurations }}/{{ row.configuration_count }}</template></el-table-column>
            <el-table-column label="记录" width="150"><template #default="{ row }">{{ row.records }}/{{ row.expected_records || '—' }}</template></el-table-column>
            <el-table-column label="进度" min-width="180"><template #default="{ row }"><el-progress :percentage="Math.round((row.progress || 0) * 100)" /></template></el-table-column>
            <el-table-column prop="provider_errors" label="错误" width="80" />
            <el-table-column prop="qualified_count" label="过门禁" width="90" />
          </el-table>
          <div v-else class="run-card-list">
            <article v-for="run in runs" :key="run.name" class="run-card">
              <div class="run-head"><strong>{{ run.name }}</strong><el-tag :type="runTag(run.status)" size="small">{{ runText(run.status) }}</el-tag></div>
              <el-progress :percentage="Math.round((run.progress || 0) * 100)" />
              <div class="run-fields"><span>配置 {{ run.completed_configurations }}/{{ run.configuration_count }}</span><span>记录 {{ run.records }}</span><span>错误 {{ run.provider_errors }}</span><span>过门禁 {{ run.qualified_count }}</span></div>
            </article>
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="候选门禁" name="gates">
        <section class="workspace-section">
          <div class="section-head"><div><h2>当前配置明细</h2><p>{{ latestRun?.name || '暂无运行' }}</p></div></div>
          <el-table v-if="!isMobile" :data="latestRun?.configurations || []" stripe>
            <el-table-column prop="id" label="配置 ID" min-width="310" />
            <el-table-column label="参数" min-width="240"><template #default="{ row }">LB {{ row.configuration.lookback }} · SC {{ row.configuration.sample_count }} · T {{ row.configuration.temperature }}</template></el-table-column>
            <el-table-column prop="records" label="记录" width="80" />
            <el-table-column label="操作门禁" width="110"><template #default="{ row }"><el-tag :type="gateTag(row.operational_qualified)" size="small">{{ gateText(row.operational_qualified) }}</el-tag></template></el-table-column>
            <el-table-column label="稳健门禁" width="110"><template #default="{ row }"><el-tag :type="gateTag(row.robust_qualified)" size="small">{{ gateText(row.robust_qualified) }}</el-tag></template></el-table-column>
            <el-table-column label="最终" width="90"><template #default="{ row }"><el-tag :type="gateTag(row.qualified)" size="small">{{ gateText(row.qualified) }}</el-tag></template></el-table-column>
          </el-table>
          <div v-else class="run-card-list">
            <article v-for="row in latestRun?.configurations || []" :key="row.id" class="run-card">
              <div class="run-head"><strong>LB {{ row.configuration.lookback }} · SC {{ row.configuration.sample_count }}</strong><el-tag :type="gateTag(row.qualified)" size="small">{{ gateText(row.qualified) }}</el-tag></div>
              <div class="run-fields"><span>T {{ row.configuration.temperature }}</span><span>记录 {{ row.records }}</span><span>操作 {{ gateText(row.operational_qualified) }}</span><span>稳健 {{ gateText(row.robust_qualified) }}</span></div>
            </article>
          </div>
        </section>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Check, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useResponsive } from '@/composables/useResponsive'
import { getKronosHealth, getKronosOverview, getKronosRuns, saveKronosConfig, type KronosConfig, type KronosHealth, type KronosRun } from '@/api/kronos'

const { isMobile } = useResponsive()
const activeTab = ref('config')
const loading = ref(false)
const saving = ref(false)
const runs = ref<KronosRun[]>([])
const health = ref<KronosHealth>({ reachable: false, url: '' })
const config = ref<KronosConfig>({ schema_version: 1, enabled: false, mode: 'shadow', qualification_status: 'not_qualified', preset_name: '', provider_url: '', lookback: 48, horizons: [1, 3, 5], sample_count: 10, sample_batch_size: 5, temperature: 0.9, top_k: 0, top_p: 0.85, clip: 5, timeout_seconds: 600, require_human_approval: true, notes: '' })
const horizonOptions = [1, 3, 5, 10, 15, 30]
const modeOptions = [{ label: '影子', value: 'shadow' }, { label: '金丝雀', value: 'canary' }, { label: '生产', value: 'production' }]
const latestRun = computed(() => runs.value[0] || null)
const progressPercent = computed(() => Math.round((latestRun.value?.progress || 0) * 100))
const progressText = computed(() => latestRun.value ? `${progressPercent.value}%` : '—')
const qualificationText = computed(() => ({ not_qualified: '未通过门禁', challenger: '挑战者', qualified: '已合格' }[config.value.qualification_status]))
const qualificationTag = computed(() => config.value.qualification_status === 'qualified' ? 'success' : config.value.qualification_status === 'challenger' ? 'warning' : 'danger')

const gateText = (value: boolean | null) => value === true ? '通过' : value === false ? '未通过' : '待评估'
const gateTag = (value: boolean | null) => value === true ? 'success' : value === false ? 'danger' : 'info'
const runText = (value: string) => ({ completed: '完成', running: '运行中', partial: '部分完成', invalid: '无效' }[value] || value)
const runTag = (value: string) => value === 'completed' ? 'success' : value === 'running' ? 'primary' : value === 'partial' ? 'warning' : 'danger'

async function refresh() {
  loading.value = true
  try {
    const [overview, runResult, healthResult] = await Promise.all([getKronosOverview(), getKronosRuns(), getKronosHealth()])
    config.value = overview.data.config
    runs.value = runResult.data
    health.value = healthResult.data
  } finally { loading.value = false }
}

async function saveConfig() {
  saving.value = true
  try {
    const result = await saveKronosConfig(config.value)
    config.value = result.data
    ElMessage.success('Kronos 预设已保存')
  } finally { saving.value = false }
}

onMounted(refresh)
</script>

<style scoped lang="scss">
@use '@/styles/breakpoints' as *;

.kronos-page { min-height: calc(100dvh - 84px); padding: 22px; background: radial-gradient(circle at 85% 0%, rgba(24, 119, 242, .08), transparent 34%), linear-gradient(180deg, #f7f9fc 0%, #eef2f6 100%); color: #172033; }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; max-width: 1440px; margin: 0 auto 16px; }
.eyebrow { color: #52647d; font: 700 11px/1.2 'IBM Plex Mono', Consolas, monospace; letter-spacing: 1.4px; }
h1 { margin: 5px 0 10px; font-family: 'IBM Plex Sans', 'Microsoft YaHei', sans-serif; font-size: 30px; letter-spacing: 0; }
.head-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.hash { color: #75849a; font: 12px/1.4 Consolas, monospace; }
.gate-alert, .metric-grid, .workspace-tabs { max-width: 1440px; margin-left: auto; margin-right: auto; }
.metric-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 14px; margin-bottom: 18px; }
.metric-block { min-height: 108px; padding: 17px 18px; background: #fff; border: 1px solid #dce3ec; border-top: 3px solid #2477d4; border-radius: 6px; box-shadow: 0 5px 16px rgba(24, 41, 66, .05); }
.metric-block span, .metric-block small { display: block; color: #738197; font-size: 12px; }
.metric-block strong { display: block; margin: 8px 0; font: 700 25px/1.1 'IBM Plex Mono', Consolas, monospace; }
.workspace-tabs { padding: 0 18px 18px; background: #fff; border: 1px solid #dce3ec; border-radius: 6px; }
.workspace-section { padding-top: 12px; }
.section-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.section-head h2 { margin: 0 0 4px; font-size: 18px; letter-spacing: 0; }
.section-head p { margin: 0; color: #8491a4; font-size: 12px; }
.config-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 2px 18px; }
.config-grid :deep(.el-input-number), .config-grid :deep(.el-select), .config-grid :deep(.el-segmented) { width: 100%; }
.config-grid .wide { grid-column: span 2; }
.unit { margin-left: 8px; color: #8491a4; }
.run-card-list { display: grid; gap: 10px; }
.run-card { padding: 14px; border: 1px solid #dce3ec; border-left: 3px solid #2477d4; border-radius: 5px; background: #fff; }
.run-head { display: flex; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
.run-head strong { overflow-wrap: anywhere; font-size: 13px; }
.run-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 10px; color: #67768c; font-size: 12px; }

@include md-down { .config-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@include sm-down {
  .kronos-page { padding: 12px; }
  h1 { font-size: 24px; }
  .metric-grid { grid-template-columns: 1fr; }
  .metric-block { min-height: 90px; }
  .workspace-tabs { padding: 0 12px 12px; }
  .config-grid { grid-template-columns: 1fr; }
  .config-grid .wide { grid-column: span 1; }
  .section-head { align-items: flex-start; gap: 12px; }
}
</style>

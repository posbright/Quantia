<template>
  <div class="report-preference-page">
    <el-card>
      <template #header>
        <span>报告偏好设置</span>
      </template>

      <el-form :model="form" label-width="160px" v-loading="loading">
        <el-form-item label="侧重维度">
          <el-checkbox-group v-model="form.focus_dimensions">
            <el-checkbox label="technical">技术面</el-checkbox>
            <el-checkbox label="fundamental">基本面</el-checkbox>
            <el-checkbox label="fund_flow">资金面</el-checkbox>
            <el-checkbox label="event">事件面</el-checkbox>
            <el-checkbox label="ai_gate">AI Gate</el-checkbox>
          </el-checkbox-group>
        </el-form-item>

        <el-form-item label="报告语言">
          <el-radio-group v-model="form.language">
            <el-radio value="zh">中文</el-radio>
            <el-radio value="en">English</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="语音播报">
          <el-switch v-model="form.voice_enabled" />
          <span class="hint">开启后报告生成完毕可自动朗读</span>
        </el-form-item>

        <el-form-item label="评分预警阈值">
          <el-slider v-model="form.alert_threshold" :min="10" :max="90" :step="5" show-input />
          <span class="hint">AI评分低于此值时触发钉钉预警</span>
        </el-form-item>

        <el-form-item label="历史分析复用窗口">
          <el-input-number v-model="form.reuse_hours" :min="0" :max="720" :step="24" />
          <span class="hint">
            进入 AI 分析时，若该窗口内已有较完整分析记录则直接复用历史、不重复调用 AI（单位：小时，72=3天，0=每次都重新分析）。定时分析任务同样遵循此窗口。
          </span>
        </el-form-item>

        <el-form-item label="每日自动分析">
          <el-switch v-model="form.auto_report" />
          <span class="hint">工作日收盘后自动分析关注列表</span>
        </el-form-item>

        <el-form-item label="定时分析选股方式">
          <el-radio-group v-model="form.analysis_mode">
            <el-radio value="top_score">综合选股评分最高的前 N 只</el-radio>
            <el-radio value="specified">指定股票</el-radio>
          </el-radio-group>
          <div class="hint block-hint">
            「前 N 只」：从关注列表中按综合选股评分降序取前 N 只；「指定股票」：只分析你指定的股票并推送钉钉。
          </div>
        </el-form-item>

        <el-form-item v-if="form.analysis_mode === 'specified'" label="指定股票代码">
          <el-select
            v-model="form.analysis_codes"
            multiple
            filterable
            allow-create
            default-first-option
            :reserve-keyword="false"
            placeholder="输入 6 位股票代码后回车（如 603259）"
            style="width: 100%"
          >
            <el-option
              v-for="c in form.analysis_codes"
              :key="c"
              :label="c"
              :value="c"
            />
          </el-select>
          <span class="hint block-hint">只保留 6 位数字代码，最多 200 只；上限仍受「定时分析股票数」控制。</span>
        </el-form-item>

        <el-form-item label="定时分析股票数">
          <el-input-number v-model="form.analysis_max_stocks" :min="1" :max="200" :step="1" />
          <span class="hint">
            {{ form.analysis_mode === 'specified' ? '指定股票本次最多分析数' : '按综合选股评分取前 N 只（关注列表本身不限数量）' }}
          </span>
        </el-form-item>

        <el-form-item label="连续失败熔断次数">
          <el-input-number v-model="form.max_failures" :min="1" :max="50" :step="1" />
          <span class="hint">定时分析连续失败达此次数且无成功时提前熔断终止</span>
        </el-form-item>

        <el-form-item label="钉钉推送">
          <el-switch v-model="form.push_enabled" />
          <span class="hint">将报告摘要和预警推送到钉钉群</span>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" @click="handleSave" :loading="saving">保存设置</el-button>
          <el-button @click="loadPreference">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onActivated } from 'vue'
import { ElMessage } from 'element-plus'
import { getReportPreference, saveReportPreference } from '@/api/report'

const loading = ref(false)
const saving = ref(false)

const form = reactive({
  focus_dimensions: ['technical', 'fundamental', 'fund_flow'] as string[],
  language: 'zh' as 'zh' | 'en',
  voice_enabled: false,
  alert_threshold: 50,
  auto_report: false,
  push_enabled: false,
  analysis_max_stocks: 10,
  max_failures: 5,
  analysis_mode: 'top_score' as 'top_score' | 'specified',
  analysis_codes: [] as string[],
  reuse_hours: 72,
})

async function loadPreference() {
  loading.value = true
  try {
    const res = await getReportPreference() as any
    form.focus_dimensions = res.focus_dimensions || ['technical', 'fundamental', 'fund_flow']
    form.language = res.language || 'zh'
    form.voice_enabled = !!res.voice_enabled
    form.alert_threshold = res.alert_threshold || 50
    form.auto_report = !!res.auto_report
    form.push_enabled = !!res.push_enabled
    form.analysis_max_stocks = res.analysis_max_stocks || 10
    form.max_failures = res.max_failures || 5
    form.analysis_mode = res.analysis_mode === 'specified' ? 'specified' : 'top_score'
    form.analysis_codes = Array.isArray(res.analysis_codes) ? res.analysis_codes : []
    form.reuse_hours = typeof res.reuse_hours === 'number' ? res.reuse_hours : 72
  } catch (err: any) {
    ElMessage.warning('加载偏好失败: ' + (err.message || err))
  } finally {
    loading.value = false
  }
}

async function handleSave() {
  saving.value = true
  try {
    await saveReportPreference({
      focus_dimensions: form.focus_dimensions,
      language: form.language,
      voice_enabled: form.voice_enabled,
      alert_threshold: form.alert_threshold,
      auto_report: form.auto_report,
      push_enabled: form.push_enabled,
      analysis_max_stocks: form.analysis_max_stocks,
      max_failures: form.max_failures,
      analysis_mode: form.analysis_mode,
      analysis_codes: form.analysis_codes,
      reuse_hours: form.reuse_hours,
    })
    ElMessage.success('偏好保存成功')
  } catch (err: any) {
    ElMessage.error('保存失败: ' + (err.message || err))
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadPreference()
})

onActivated(() => {
  loadPreference()
})
</script>

<style scoped>
.report-preference-page {
  padding: 20px;
  max-width: 700px;
}
.hint {
  margin-left: 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.block-hint {
  display: block;
  margin-left: 0;
  margin-top: 6px;
}
</style>

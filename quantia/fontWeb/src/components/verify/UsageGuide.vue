<template>
  <el-collapse v-model="activeNames" class="usage-guide">
    <el-collapse-item :title="title" name="guide">
      <div class="guide-content">
        <div v-if="steps.length" class="guide-section">
          <div class="section-title">📋 操作步骤</div>
          <ol class="step-list">
            <li v-for="(step, idx) in steps" :key="idx" class="step-item">
              <span class="step-text" v-html="step"></span>
            </li>
          </ol>
        </div>
        <div v-if="example" class="guide-section">
          <div class="section-title">💡 使用示例</div>
          <div class="example-box" v-html="example"></div>
        </div>
        <div v-if="metrics.length" class="guide-section">
          <div class="section-title">📊 指标说明</div>
          <div class="metrics-grid">
            <div v-for="m in metrics" :key="m.name" class="metric-item">
              <div class="metric-name">{{ m.name }}</div>
              <div class="metric-desc">{{ m.desc }}</div>
              <div v-if="m.range" class="metric-range">
                <span class="range-label">取值范围:</span> {{ m.range }}
              </div>
              <div v-if="m.good" class="metric-good">
                <span class="good-label">优秀标准:</span> {{ m.good }}
              </div>
            </div>
          </div>
        </div>
        <div v-if="tips.length" class="guide-section">
          <div class="section-title">⚠️ 注意事项</div>
          <ul class="tips-list">
            <li v-for="(tip, idx) in tips" :key="idx">{{ tip }}</li>
          </ul>
        </div>
      </div>
    </el-collapse-item>
  </el-collapse>
</template>

<script setup lang="ts">
import { ref } from 'vue'

defineProps<{
  title: string
  steps: string[]
  example?: string
  metrics: { name: string; desc: string; range?: string; good?: string }[]
  tips: string[]
}>()

const activeNames = ref<string[]>([])
</script>

<style scoped>
.usage-guide { margin-bottom: 16px; border-radius: 6px; overflow: hidden; }
.usage-guide :deep(.el-collapse-item__header) {
  font-size: 14px; font-weight: 600; color: #409eff; background: #f0f7ff; padding: 0 16px;
}
.usage-guide :deep(.el-collapse-item__wrap) { background: #fafcff; }
.guide-content { padding: 8px 4px; font-size: 13px; line-height: 1.8; color: #333; }
.guide-section { margin-bottom: 16px; }
.guide-section:last-child { margin-bottom: 0; }
.section-title { font-weight: 600; font-size: 13px; margin-bottom: 8px; color: #1f2937; }
.step-list { padding-left: 20px; margin: 0; }
.step-item { margin-bottom: 4px; }
.step-text :deep(b) { color: #409eff; }
.example-box { background: #fff; border: 1px solid #e6e8eb; border-radius: 4px; padding: 12px; font-size: 12px; line-height: 1.7; color: #555; }
.metrics-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; }
.metric-item { background: #fff; border: 1px solid #ebeef5; border-radius: 4px; padding: 10px 12px; }
.metric-name { font-weight: 600; font-size: 13px; color: #1f2937; margin-bottom: 4px; }
.metric-desc { font-size: 12px; color: #666; margin-bottom: 4px; }
.metric-range { font-size: 11px; color: #909399; }
.range-label { font-weight: 500; color: #606266; }
.metric-good { font-size: 11px; color: #67c23a; }
.good-label { font-weight: 500; }
.tips-list { padding-left: 18px; margin: 0; color: #e6a23c; font-size: 12px; }
.tips-list li { margin-bottom: 4px; }
</style>

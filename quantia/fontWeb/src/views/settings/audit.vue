<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { authApi } from '@/api/auth'
import { useResponsive } from '@/composables/useResponsive'

const { isMobile } = useResponsive()

interface AuditRow {
  kind: string
  id: number
  ref_a: unknown
  ref_b: unknown
  modified_by: string
  updated_at: string | null
  config_version: number | null
}

const loading = ref(false)
const rows = ref<AuditRow[]>([])
const limit = ref(200)

async function refresh() {
  loading.value = true
  try {
    const resp = await authApi.audit(limit.value)
    if (resp?.ok) {
      rows.value = resp.data || []
    }
  } catch (err) {
    ElMessage.error('加载失败：' + (err as Error).message)
  } finally {
    loading.value = false
  }
}

function kindLabel(k: string): string {
  if (k === 'notification') return '通知配置'
  if (k === 'ai_decision') return 'AI 研判配置'
  if (k === 'im_operator') return 'IM 操作人白名单'
  return k
}

onMounted(refresh)
</script>

<template>
  <div class="audit-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>配置修改记录（admin / operator）</span>
          <div>
            <el-input-number
              v-model="limit"
              :min="50"
              :max="1000"
              :step="50"
              size="small"
              style="width: 120px"
            />
            <el-button type="primary" size="small" @click="refresh">刷新</el-button>
          </div>
        </div>
      </template>
      <el-table :data="rows" v-if="!isMobile" v-loading="loading" border>
        <el-table-column label="类别" width="160">
          <template #default="{ row }">{{ kindLabel(row.kind) }}</template>
        </el-table-column>
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column label="关联">
          <template #default="{ row }">
            <span v-if="row.ref_a !== null">{{ row.ref_a }}</span>
            <span v-if="row.ref_b !== null"> / {{ row.ref_b }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="modified_by" label="修改人" width="150" />
        <el-table-column prop="config_version" label="版本" width="80" />
        <el-table-column prop="updated_at" label="更新时间" />
      </el-table>

      <!-- 移动端卡片视图 -->
      <div v-if="isMobile" v-loading="loading" class="audit-card-list">
        <div v-for="row in rows" :key="row.kind + '-' + row.id" class="audit-card">
          <div class="audit-card-head">
            <span class="audit-kind">{{ kindLabel(row.kind) }}</span>
            <span class="audit-id">#{{ row.id }}</span>
            <span v-if="row.config_version != null" class="audit-ver">v{{ row.config_version }}</span>
          </div>
          <div class="audit-card-body">
            <div class="audit-field">
              <span class="audit-lbl">修改人</span>
              <span>{{ row.modified_by || '—' }}</span>
            </div>
            <div class="audit-field">
              <span class="audit-lbl">关联</span>
              <span>
                <template v-if="row.ref_a !== null">{{ row.ref_a }}</template>
                <template v-if="row.ref_b !== null"> / {{ row.ref_b }}</template>
                <template v-if="row.ref_a === null && row.ref_b === null">—</template>
              </span>
            </div>
            <div class="audit-field audit-field-full">
              <span class="audit-lbl">更新时间</span>
              <span>{{ row.updated_at || '—' }}</span>
            </div>
          </div>
        </div>
        <el-empty v-if="!loading && rows.length === 0" description="暂无记录" />
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.audit-page {
  padding: 16px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

/* 移动端卡片视图 */
.audit-card-list { display: flex; flex-direction: column; gap: 10px; }
.audit-card {
  background: #fff; border: 1px solid #ebeef5; border-radius: 6px; padding: 10px 12px;
}
.audit-card-head {
  display: flex; align-items: center; gap: 8px;
  border-bottom: 1px dashed #ebeef5; padding-bottom: 6px; margin-bottom: 8px;
}
.audit-kind { font-weight: 600; font-size: 14px; color: #303133; }
.audit-id { color: #909399; font-size: 12px; }
.audit-ver { margin-left: auto; color: #409eff; font-size: 12px; }
.audit-card-body {
  display: grid; grid-template-columns: 1fr 1fr; gap: 6px 12px; font-size: 13px;
}
.audit-field { display: flex; justify-content: space-between; align-items: center; gap: 8px; min-width: 0; }
.audit-field-full { grid-column: 1 / -1; }
.audit-lbl { color: #909399; white-space: nowrap; }

@media (max-width: 767.98px) {
  .audit-page { padding: 10px; }
  .card-header { flex-direction: column; align-items: flex-start; gap: 8px; }
  .card-header > div { display: flex; gap: 8px; width: 100%; }
}
</style>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { authApi } from '@/api/auth'

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
      <el-table :data="rows" v-loading="loading" border>
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
</style>

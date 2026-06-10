<template>
  <div class="settings-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>IM 操作人白名单</span>
          <div>
            <el-button type="primary" size="small" @click="openCreate">新增操作人</el-button>
            <el-button size="small" @click="loadList">刷新</el-button>
          </div>
        </div>
      </template>

      <el-alert type="warning" show-icon :closable="false" style="margin-bottom: 12px">
        <strong>仅在 IM 指令总开关开启后生效</strong>。生产环境默认关闭：未注入
        <code>QUANTIA_IM_COMMAND_ENABLED=1</code> 时，钉钉回调直接返回 503，不会落库。
        测试期可临时开启验证完整流程。当前状态：
        <el-tag size="small" :type="status?.enabled ? 'success' : 'info'" style="margin-left:6px">
          {{ status?.enabled ? '已启用（测试中）' : '已关闭（默认）' }}
        </el-tag>
        ｜单笔上限 ¥{{ status?.max_single_value ?? '-' }} ｜单日上限 ¥{{ status?.max_daily_value ?? '-' }}
        ｜指令 TTL {{ status?.ttl_seconds ?? '-' }}s
      </el-alert>

      <el-table :data="rows" v-if="!isMobile" stripe border size="small">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="channel" label="渠道" width="100" />
        <el-table-column prop="operator_id" label="操作人 ID" min-width="160" />
        <el-table-column prop="operator_name" label="姓名" width="140" />
        <el-table-column label="启用" width="80">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
              {{ row.enabled ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="180" show-overflow-tooltip />
        <el-table-column prop="updated_at" label="更新时间" width="170" />
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 移动端卡片视图 -->
      <div v-if="isMobile" class="imo-card-list">
        <div v-for="row in rows" :key="row.id" class="imo-card">
          <div class="imo-card-head">
            <span class="imo-id">#{{ row.id }}</span>
            <span class="imo-name">{{ row.operator_name || row.operator_id }}</span>
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
              {{ row.enabled ? '启用' : '禁用' }}
            </el-tag>
          </div>
          <div class="imo-card-body">
            <div class="imo-field">
              <span class="imo-lbl">渠道</span>
              <span>{{ row.channel }}</span>
            </div>
            <div class="imo-field imo-field-full">
              <span class="imo-lbl">操作人 ID</span>
              <span class="imo-oid">{{ row.operator_id }}</span>
            </div>
            <div v-if="row.note" class="imo-field imo-field-full">
              <span class="imo-lbl">备注</span>
              <span>{{ row.note }}</span>
            </div>
            <div class="imo-field imo-field-full">
              <span class="imo-lbl">更新时间</span>
              <span>{{ row.updated_at }}</span>
            </div>
          </div>
          <div class="imo-card-ops">
            <a class="imo-op" @click="openEdit(row)">编辑</a>
            <span class="imo-op-sep">|</span>
            <a class="imo-op imo-op-danger" @click="onDelete(row)">删除</a>
          </div>
        </div>
        <el-empty v-if="rows.length === 0" description="暂无操作人" />
      </div>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="form.id ? '编辑操作人' : '新增操作人'" :fullscreen="isMobile" :width="isMobile ? '100%' : 'min(540px, 92vw)'">
      <el-form :model="form" :label-width="isMobile ? '90px' : '120px'">
        <el-form-item label="渠道">
          <el-select v-model="form.channel">
            <el-option label="钉钉 (dingtalk)" value="dingtalk" />
            <el-option label="企业微信 (wecom)" value="wecom" disabled />
          </el-select>
        </el-form-item>
        <el-form-item label="操作人 ID" required>
          <el-input v-model="form.operator_id" placeholder="钉钉 senderStaffId / 企微 userId" />
          <div class="hint">不能含 / 空格；该 ID 与回调中的 senderStaffId 必须严格一致</div>
        </el-form-item>
        <el-form-item label="姓名">
          <el-input v-model="form.operator_name" placeholder="可选，仅作展示" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" type="textarea" :rows="2" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="onSubmit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  IMOperator, IMStatus, getIMStatus, listIMOperators, saveIMOperator, deleteIMOperator,
} from '@/api/imLive'
import { useResponsive } from '@/composables/useResponsive'

const { isMobile } = useResponsive()
const rows = ref<IMOperator[]>([])
const status = ref<IMStatus | null>(null)
const dialogVisible = ref(false)
const form = reactive<IMOperator>({
  channel: 'dingtalk',
  operator_id: '',
  operator_name: '',
  enabled: true,
  note: '',
})

const resetForm = () => {
  form.id = undefined
  form.channel = 'dingtalk'
  form.operator_id = ''
  form.operator_name = ''
  form.enabled = true
  form.note = ''
}

const loadList = async () => {
  try {
    const [s, l] = await Promise.all([getIMStatus(), listIMOperators()])
    status.value = s.data || null
    rows.value = l.data || []
  } catch (e: any) {
    ElMessage.error(`加载失败: ${e?.message || e}`)
  }
}

const openCreate = () => { resetForm(); dialogVisible.value = true }
const openEdit = (row: IMOperator) => {
  Object.assign(form, row)
  dialogVisible.value = true
}

const onSubmit = async () => {
  if (!form.operator_id?.trim()) {
    ElMessage.warning('operator_id 不能为空')
    return
  }
  try {
    const r = await saveIMOperator({ ...form })
    if (!r.ok) {
      ElMessage.error(r.error || '保存失败')
      return
    }
    ElMessage.success('已保存')
    dialogVisible.value = false
    await loadList()
  } catch (e: any) {
    ElMessage.error(`保存失败: ${e?.response?.data?.error || e?.message || e}`)
  }
}

const onDelete = async (row: IMOperator) => {
  try {
    await ElMessageBox.confirm(
      `确认删除操作人 ${row.operator_id}？该操作人后续回调将被拒绝。`,
      '删除确认', { type: 'warning' })
  } catch { return }
  try {
    const r = await deleteIMOperator(row.id!)
    if (r.ok) { ElMessage.success('已删除'); await loadList() }
    else ElMessage.error(r.error || '删除失败')
  } catch (e: any) {
    ElMessage.error(`删除失败: ${e?.message || e}`)
  }
}

onMounted(loadList)
</script>

<style scoped>
.settings-page { padding: 12px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.hint { color: #999; font-size: 12px; line-height: 1.4; margin-top: 4px; }

/* 移动端卡片视图 */
.imo-card-list { display: flex; flex-direction: column; gap: 10px; }
.imo-card {
  background: #fff; border: 1px solid #ebeef5; border-radius: 6px; padding: 10px 12px;
}
.imo-card-head {
  display: flex; align-items: center; gap: 8px;
  border-bottom: 1px dashed #ebeef5; padding-bottom: 6px; margin-bottom: 8px;
}
.imo-id { color: #909399; font-size: 12px; }
.imo-name { flex: 1; font-weight: 600; font-size: 14px; color: #303133; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.imo-card-body {
  display: grid; grid-template-columns: 1fr 1fr; gap: 6px 12px; font-size: 13px;
}
.imo-field { display: flex; justify-content: space-between; align-items: center; gap: 8px; min-width: 0; }
.imo-field-full { grid-column: 1 / -1; }
.imo-lbl { color: #909399; white-space: nowrap; }
.imo-oid { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: Consolas, monospace; }
.imo-card-ops {
  margin-top: 10px; padding-top: 8px; border-top: 1px dashed #ebeef5;
  display: flex; justify-content: flex-end; gap: 8px; font-size: 13px;
}
.imo-op { color: #409eff; cursor: pointer; }
.imo-op:hover { text-decoration: underline; }
.imo-op-danger { color: #f56c6c; }
.imo-op-sep { color: #dcdfe6; }

@media (max-width: 767.98px) {
  .card-header { flex-direction: column; align-items: flex-start; gap: 8px; }
  .card-header > div { display: flex; gap: 8px; width: 100%; }
}
</style>

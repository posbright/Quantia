<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { authApi, type AdminUser } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const loading = ref(false)
const users = ref<AdminUser[]>([])
const dialogVisible = ref(false)
const editing = ref<{
  id?: number
  username: string
  password: string
  role: 'admin' | 'operator' | 'viewer'
  enabled: boolean
}>({
  username: '',
  password: '',
  role: 'operator',
  enabled: true
})

async function refresh() {
  loading.value = true
  try {
    const resp = await authApi.listUsers()
    if (resp?.ok) {
      users.value = resp.data || []
    }
  } catch (err) {
    ElMessage.error('加载失败：' + (err as Error).message)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = {
    username: '',
    password: '',
    role: 'operator',
    enabled: true
  }
  dialogVisible.value = true
}

function openEdit(row: AdminUser) {
  editing.value = {
    id: row.id,
    username: row.username,
    password: '',
    role: row.role,
    enabled: row.enabled
  }
  dialogVisible.value = true
}

async function save() {
  if (!editing.value.id && !editing.value.username) {
    ElMessage.warning('请填写用户名')
    return
  }
  if (!editing.value.id && !editing.value.password) {
    ElMessage.warning('新建用户必须设置密码')
    return
  }
  try {
    const resp = await authApi.saveUser({
      id: editing.value.id,
      username: editing.value.username,
      password: editing.value.password || undefined,
      role: editing.value.role,
      enabled: editing.value.enabled
    })
    if (resp?.ok) {
      ElMessage.success('已保存')
      dialogVisible.value = false
      refresh()
    } else {
      ElMessage.error(resp?.error || '保存失败')
    }
  } catch (err) {
    ElMessage.error('保存失败：' + (err as Error).message)
  }
}

async function remove(row: AdminUser) {
  try {
    await ElMessageBox.confirm(
      `确认删除用户 ${row.username}？`,
      '删除确认',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    const resp = await authApi.deleteUser(row.id)
    if (resp?.ok) {
      ElMessage.success('已删除')
      refresh()
    } else {
      ElMessage.error(resp?.error || '删除失败')
    }
  } catch (err) {
    ElMessage.error('删除失败：' + (err as Error).message)
  }
}

onMounted(refresh)
</script>

<template>
  <div class="user-mgmt-page">
    <el-card v-if="!authStore.enabled">
      <el-alert
        type="info"
        :closable="false"
        title="后端未启用 QUANTIA_AUTH_ENABLED，用户管理仅在启用鉴权后生效。"
      />
    </el-card>
    <el-card v-else>
      <template #header>
        <div class="card-header">
          <span>用户与角色管理（admin only）</span>
          <el-button type="primary" @click="openCreate">新建用户</el-button>
        </div>
      </template>
      <el-table :data="users" v-loading="loading" border>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="username" label="用户名" />
        <el-table-column prop="role" label="角色" width="120">
          <template #default="{ row }">
            <el-tag
              :type="row.role === 'admin' ? 'danger' : row.role === 'operator' ? 'warning' : 'info'"
            >{{ row.role }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="enabled" label="启用" width="80">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'">
              {{ row.enabled ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="last_login_at" label="最近登录" />
        <el-table-column prop="updated_at" label="更新时间" />
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="editing.id ? '编辑用户' : '新建用户'" width="500px">
      <el-form label-width="100px">
        <el-form-item label="用户名">
          <el-input v-model="editing.username" :disabled="!!editing.id" />
        </el-form-item>
        <el-form-item :label="editing.id ? '新密码（留空不改）' : '密码'">
          <el-input v-model="editing.password" type="password" show-password />
        </el-form-item>
        <el-form-item label="角色">
          <el-radio-group v-model="editing.role">
            <el-radio value="admin">admin</el-radio>
            <el-radio value="operator">operator</el-radio>
            <el-radio value="viewer">viewer</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="editing.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.user-mgmt-page {
  padding: 16px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>

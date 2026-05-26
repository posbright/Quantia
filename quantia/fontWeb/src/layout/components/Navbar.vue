<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

interface Props {
  isCollapse: boolean
  isMobile?: boolean
}

withDefaults(defineProps<Props>(), { isMobile: false })
const emit = defineEmits(['toggle'])

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

// 面包屑导航（过滤掉首页，避免重复显示）
const breadcrumbs = computed(() => {
  const matched = route.matched.filter(item => item.meta?.title && item.meta?.title !== '首页')
  return matched.map(item => ({
    path: item.path,
    title: item.meta?.title as string
  }))
})

// 刷新页面
const handleRefresh = () => {
  router.go(0)
}

// 鉴权状态展示
const authEnabled = computed(() => authStore.enabled)
const username = computed(() => authStore.username)
const role = computed(() => authStore.role)
const roleTagType = computed(() => {
  if (role.value === 'admin') return 'danger'
  if (role.value === 'operator') return 'warning'
  return 'info'
})

const goLogin = () => {
  router.push({ path: '/login', query: { redirect: route.fullPath } })
}

const handleLogout = async () => {
  try {
    await authStore.logout()
    ElMessage.success('已退出登录')
    router.push('/login')
  } catch (err) {
    ElMessage.error('退出失败：' + (err as Error).message)
  }
}

const handleUserMgmt = () => router.push('/settings/users')
</script>

<template>
  <div class="navbar" :class="{ 'is-mobile': isMobile }">
    <div class="navbar-left">
      <!-- 折叠/菜单按钮 -->
      <el-icon class="collapse-btn" @click="emit('toggle')">
        <component :is="isMobile ? 'Menu' : (isCollapse ? 'Expand' : 'Fold')" />
      </el-icon>

      <!-- 面包屑：移动端隐藏 -->
      <el-breadcrumb v-if="!isMobile" separator="/">
        <el-breadcrumb-item :to="{ path: '/' }">首页</el-breadcrumb-item>
        <el-breadcrumb-item v-for="item in breadcrumbs" :key="item.path" :to="{ path: item.path }">
          {{ item.title }}
        </el-breadcrumb-item>
      </el-breadcrumb>

      <!-- 移动端仅显示当前页面标题 -->
      <span v-else class="mobile-title">{{ breadcrumbs.length ? breadcrumbs[breadcrumbs.length - 1].title : '玄枢' }}</span>
    </div>
    
    <div class="navbar-right">
      <!-- 刷新按钮 -->
      <el-tooltip content="刷新" placement="bottom">
        <el-icon class="action-btn" @click="handleRefresh">
          <Refresh />
        </el-icon>
      </el-tooltip>
      
      <!-- GitHub 链接 -->
      <el-tooltip content="GitHub" placement="bottom">
        <a
          href="https://github.com/posbright/Quantia"
          target="_blank"
          class="action-btn"
        >
          <el-icon><Link /></el-icon>
        </a>
      </el-tooltip>

      <!-- 鉴权状态 / 用户菜单 -->
      <template v-if="authEnabled">
        <template v-if="username">
          <el-dropdown class="user-dropdown" trigger="click">
            <div class="user-trigger">
              <el-icon><User /></el-icon>
              <span class="user-name">{{ username }}</span>
              <el-tag :type="roleTagType" size="small" class="role-tag">{{ role }}</el-tag>
              <el-icon class="caret"><ArrowDown /></el-icon>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-if="role === 'admin'" @click="handleUserMgmt">
                  <el-icon><Setting /></el-icon>用户管理
                </el-dropdown-item>
                <el-dropdown-item divided @click="handleLogout">
                  <el-icon><SwitchButton /></el-icon>退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
        <el-button v-else size="small" type="primary" plain @click="goLogin">
          登录
        </el-button>
      </template>
      <el-tooltip
        v-else
        content="后端鉴权未启用 (QUANTIA_AUTH_ENABLED=false)，所有请求以 system 直通"
        placement="bottom"
      >
        <el-tag size="small" type="info" class="auth-off-tag">鉴权未启用</el-tag>
      </el-tooltip>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.navbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 100%;
  padding: 0 20px;

  @include md-down {
    padding: 0 12px;
    @include safe-area-padding(0);
  }

  &.is-mobile {
    .navbar-right .action-btn,
    .navbar-right .user-dropdown {
      margin-left: 8px;
    }
    .navbar-right .role-tag,
    .navbar-right .user-name {
      display: none;
    }
  }

  .mobile-title {
    font-size: 15px;
    font-weight: 600;
    color: #303133;
    margin-left: 4px;
    max-width: 50vw;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.navbar-left {
  display: flex;
  align-items: center;
  
  .collapse-btn {
    font-size: 20px;
    cursor: pointer;
    margin-right: 15px;
    
    &:hover {
      color: #409eff;
    }
  }
}

.navbar-right {
  display: flex;
  align-items: center;
  
  .action-btn {
    font-size: 18px;
    cursor: pointer;
    margin-left: 15px;
    color: #606266;
    
    &:hover {
      color: #409eff;
    }
  }

  .user-dropdown {
    margin-left: 16px;
    cursor: pointer;
  }

  .user-trigger {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 4px;
    color: #606266;
    transition: background-color 0.2s;

    &:hover {
      background-color: #f0f2f5;
      color: #409eff;
    }

    .user-name {
      font-weight: 500;
    }

    .role-tag {
      margin-left: 2px;
    }

    .caret {
      font-size: 12px;
    }
  }

  .auth-off-tag {
    margin-left: 16px;
  }
}
</style>

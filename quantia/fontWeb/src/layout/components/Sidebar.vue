<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useAuthStore, type Role } from '@/stores/auth'

interface Props {
  isCollapse: boolean
}

defineProps<Props>()
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

// 角色匹配：未启用鉴权时一律允许；启用且未登录时只放行无 requireRole 的项。
const roleAllowed = (meta: RouteRecordRaw['meta']) => {
  const required = (meta?.requireRole as Role[] | undefined) || []
  if (required.length === 0) return true
  if (!authStore.enabled) return true
  return authStore.hasRole(...required)
}

// 获取路由菜单（过滤 hidden 路由 + 角色不匹配的入口）
const menuList = computed(() => {
  return router.options.routes.filter(item => {
    if (item.meta?.hidden) return false
    if (item.path === '/' && !item.children?.length) return false
    // 父级有 requireRole 时整体过滤
    if (!roleAllowed(item.meta)) return false
    // 父级若有子项但全部被角色过滤掉，也不显示
    if (item.children && item.children.length > 0) {
      const visible = item.children.filter(c => !c.meta?.hidden && roleAllowed(c.meta))
      if (visible.length === 0) return false
    }
    return true
  })
})

// 当前激活的菜单
const activeMenu = computed(() => {
  return route.path
})

// 判断是否应该显示为子菜单（下拉菜单）
// 只有当有多个可见子菜单时才显示为下拉菜单
const shouldShowAsSubMenu = (item: RouteRecordRaw) => {
  const visibleChildren = getVisibleChildren(item)
  // 只有一个子菜单时，直接显示为普通菜单项
  if (visibleChildren.length <= 1) {
    return false
  }
  return true
}

// 获取可见的子菜单（同时过滤 hidden 与角色）
const getVisibleChildren = (item: RouteRecordRaw) => {
  return item.children?.filter(child => !child.meta?.hidden && roleAllowed(child.meta)) || []
}

// 获取单个子菜单的路径和标题（用于只有一个子菜单的情况）
const getSingleChildPath = (item: RouteRecordRaw) => {
  const visibleChildren = getVisibleChildren(item)
  if (visibleChildren.length === 1) {
    const child = visibleChildren[0]
    return item.path === '/' ? `/${child.path}` : `${item.path}/${child.path}`
  }
  return item.redirect as string || item.path
}

const getSingleChildMeta = (item: RouteRecordRaw) => {
  const visibleChildren = getVisibleChildren(item)
  if (visibleChildren.length === 1) {
    return visibleChildren[0].meta
  }
  return item.meta
}
</script>

<template>
  <div class="sidebar-container">
    <!-- Logo -->
    <div class="sidebar-logo">
      <el-icon size="24" color="#409eff"><TrendCharts /></el-icon>
      <span v-show="!isCollapse" class="logo-title">Quantia</span>
    </div>
    
    <!-- 菜单 -->
    <el-scrollbar>
      <el-menu
        :default-active="activeMenu"
        :collapse="isCollapse"
        :collapse-transition="false"
        background-color="#304156"
        text-color="#bfcbd9"
        active-text-color="#409eff"
        router
      >
        <template v-for="item in menuList" :key="item.path">
          <!-- 有多个子菜单，显示为下拉菜单 -->
          <el-sub-menu v-if="shouldShowAsSubMenu(item)" :index="item.path">
            <template #title>
              <el-icon v-if="item.meta?.icon">
                <component :is="item.meta.icon" />
              </el-icon>
              <span>{{ item.meta?.title }}</span>
            </template>
            
            <el-menu-item
              v-for="child in getVisibleChildren(item)"
              :key="child.path"
              :index="`${item.path}/${child.path}`"
            >
              <el-icon v-if="child.meta?.icon">
                <component :is="child.meta.icon" />
              </el-icon>
              <template #title>{{ child.meta?.title }}</template>
            </el-menu-item>
          </el-sub-menu>
          
          <!-- 无子菜单或只有一个子菜单，直接显示 -->
          <el-menu-item v-else :index="getSingleChildPath(item)">
            <el-icon v-if="getSingleChildMeta(item)?.icon">
              <component :is="getSingleChildMeta(item)?.icon" />
            </el-icon>
            <template #title>{{ getSingleChildMeta(item)?.title }}</template>
          </el-menu-item>
        </template>
      </el-menu>
    </el-scrollbar>
  </div>
</template>

<style lang="scss" scoped>
.sidebar-container {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.sidebar-logo {
  height: 50px;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: #263445;
  
  .logo-title {
    margin-left: 10px;
    color: #fff;
    font-size: 18px;
    font-weight: 600;
  }
}

.el-scrollbar {
  flex: 1;
}

.el-menu {
  border-right: none;
}

:deep(.el-sub-menu__title:hover),
:deep(.el-menu-item:hover) {
  background-color: #263445 !important;
}

:deep(.el-menu-item.is-active) {
  background-color: #263445 !important;
}
</style>

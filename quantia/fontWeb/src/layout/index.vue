<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import Sidebar from './components/Sidebar.vue'
import Navbar from './components/Navbar.vue'
import { useResponsive } from '@/composables/useResponsive'

const isCollapse = ref(false)
const mobileDrawerOpen = ref(false)
const { isMobile } = useResponsive()
const route = useRoute()

const toggleCollapse = () => {
  if (isMobile.value) {
    mobileDrawerOpen.value = !mobileDrawerOpen.value
  } else {
    isCollapse.value = !isCollapse.value
  }
}

// 路由切换时自动关闭移动端抽屉
watch(() => route.fullPath, () => {
  if (isMobile.value) mobileDrawerOpen.value = false
})
</script>

<template>
  <el-container class="layout-container">
    <!-- 桌面端固定侧边栏 -->
    <el-aside
      v-if="!isMobile"
      :width="isCollapse ? '64px' : '220px'"
      class="layout-aside"
    >
      <Sidebar :is-collapse="isCollapse" />
    </el-aside>

    <!-- 移动端抽屉式侧边栏 -->
    <el-drawer
      v-if="isMobile"
      v-model="mobileDrawerOpen"
      direction="ltr"
      :with-header="false"
      size="240px"
      class="mobile-sidebar-drawer"
    >
      <Sidebar :is-collapse="false" />
    </el-drawer>

    <el-container class="layout-main">
      <!-- 顶部导航 -->
      <el-header class="layout-header">
        <Navbar :is-collapse="isCollapse" :is-mobile="isMobile" @toggle="toggleCollapse" />
      </el-header>

      <!-- 主内容区 -->
      <el-main class="layout-content">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <keep-alive>
              <component :is="Component" />
            </keep-alive>
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<style lang="scss" scoped>
.layout-container {
  height: 100%;
}

.layout-aside {
  background-color: #304156;
  transition: width 0.3s;
  overflow: hidden;
}

.layout-main {
  flex-direction: column;
  min-width: 0; // 防止 flex 子项溢出
}

.layout-header {
  background-color: #fff;
  border-bottom: 1px solid #e6e6e6;
  padding: 0;
  height: 50px;
  line-height: 50px;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
  flex-shrink: 0;
}

.layout-content {
  background-color: #f5f7fa;
  padding: 20px;
  overflow-y: auto;

  @include md-down {
    padding: 12px;
  }
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>

<style lang="scss">
// 移动端抽屉内的 sidebar 背景统一
.mobile-sidebar-drawer .el-drawer__body {
  padding: 0;
  background-color: #304156;
}
</style>

<style lang="scss" scoped>
.layout-container {
  height: 100%;
}

.layout-aside {
  background-color: #304156;
  transition: width 0.3s;
  overflow: hidden;
}

.layout-main {
  flex-direction: column;
}

.layout-header {
  background-color: #fff;
  border-bottom: 1px solid #e6e6e6;
  padding: 0;
  height: 50px;
  line-height: 50px;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
}

.layout-content {
  background-color: #f5f7fa;
  padding: 20px;
  overflow-y: auto;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>

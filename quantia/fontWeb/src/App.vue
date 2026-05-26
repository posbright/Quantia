<script setup lang="ts">
import { RouterView } from 'vue-router'
import { watch, onMounted, computed } from 'vue'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { useResponsive } from '@/composables/useResponsive'
import AppFooter from '@/components/AppFooter.vue'

// M1: 全局响应式断点同步到 <html data-bp> + data-orientation，
// 让 CSS / e2e / 调试都能从 DOM 直接读到当前断点。
const { breakpoint, isLandscape, forcedDesktop, isMobile } = useResponsive()

// M2: Element Plus 全局组件尺寸 — 移动端用 default(32px)，桌面端 large(40px)
const elSize = computed<'default' | 'large'>(() => (isMobile.value ? 'default' : 'large'))

onMounted(() => {
  if (forcedDesktop) document.documentElement.setAttribute('data-force-desktop', '1')
})

watch(
  [breakpoint, isLandscape],
  ([bp, landscape]) => {
    const html = document.documentElement
    html.setAttribute('data-bp', bp)
    html.setAttribute('data-orientation', landscape ? 'landscape' : 'portrait')
  },
  { immediate: true },
)
</script>

<template>
  <el-config-provider :locale="zhCn" :size="elSize">
    <RouterView />
    <AppFooter />
  </el-config-provider>
</template>

<style>
html, body, #app {
  height: 100%;
  margin: 0;
  padding: 0;
}

/* M2: 移动端输入框字号 >= 16px，避免 iOS Safari 自动放大页面 */
@media (max-width: 575.98px) {
  input,
  textarea,
  select,
  .el-input__inner,
  .el-textarea__inner {
    font-size: 16px !important;
  }
}
</style>

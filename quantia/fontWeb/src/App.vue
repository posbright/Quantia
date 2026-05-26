<script setup lang="ts">
import { RouterView } from 'vue-router'
import { watch, onMounted } from 'vue'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { useResponsive } from '@/composables/useResponsive'

// M1: 全局响应式断点同步到 <html data-bp> + data-orientation，
// 让 CSS / e2e / 调试都能从 DOM 直接读到当前断点。
const { breakpoint, isLandscape, forcedDesktop } = useResponsive()

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
  <el-config-provider :locale="zhCn">
    <RouterView />
  </el-config-provider>
</template>

<style>
html, body, #app {
  height: 100%;
  margin: 0;
  padding: 0;
}
</style>

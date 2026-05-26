<template>
  <button
    v-if="isMobile"
    type="button"
    class="chart-fs-btn"
    :class="{ 'is-active': isFullscreen }"
    :title="isFullscreen ? '退出全屏' : '横屏全屏'"
    :aria-label="isFullscreen ? '退出全屏' : '横屏全屏'"
    @click.stop="$emit('toggle')"
  >
    <el-icon v-if="!isFullscreen"><FullScreen /></el-icon>
    <el-icon v-else><Close /></el-icon>
  </button>
</template>

<script setup lang="ts">
import { FullScreen, Close } from '@element-plus/icons-vue'
import { useResponsive } from '@/composables/useResponsive'

defineProps<{ isFullscreen: boolean }>()
defineEmits<{ (e: 'toggle'): void }>()

const { isMobile } = useResponsive()
</script>

<style scoped>
.chart-fs-btn {
  position: absolute;
  top: 6px;
  right: 6px;
  z-index: 20;
  width: 32px;
  height: 32px;
  padding: 0;
  border: 1px solid #dcdfe6;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.92);
  color: #606266;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
  font-size: 16px;
  -webkit-tap-highlight-color: transparent;
}
.chart-fs-btn:hover { color: #409eff; border-color: #409eff; }
.chart-fs-btn.is-active {
  background: #409eff;
  border-color: #409eff;
  color: #fff;
}
</style>

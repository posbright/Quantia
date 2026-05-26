<script setup lang="ts">
/**
 * PR-05/06/08: 响应式数据视图容器。
 *
 * 设计思路：在桌面端直接交还 default 插槽（业务页面保持原有 `<el-table>` 不变，
 * 列宽/排序/选择/分页等全部不动）；在移动端切换到 `mobile-card` 插槽 + `v-for`
 * 逐行渲染卡片，避免 17 列大表横向滚导致的拇指焦虑。
 *
 * 约定：
 *   - `data` / `loading` / `rowKey` 控制移动端的 v-for
 *   - 桌面端：渲染 `<slot />`（业务方自己提供 `<el-table>` + `<el-pagination>`）
 *   - 移动端：渲染 `mobile-card` 插槽，传入 `{ row, index }`；分页槽 `mobile-footer`
 *   - `breakpoint` 默认 'md'（>=768px 算桌面，<768px 算移动）；可改 'sm'/'lg'
 *
 * 性能：移动端 v-for 加 `:key="row[rowKey]"`，对长列表（>50 行）使用方应自己分页或虚拟滚动。
 */
import { computed } from 'vue'
import { useResponsive } from '@/composables/useResponsive'

interface Props {
  data: any[]
  loading?: boolean
  rowKey?: string
  /** 切换阈值。'sm' = <576 移动；'md' = <768 移动（默认）；'lg' = <992 移动。 */
  switchAt?: 'sm' | 'md' | 'lg'
  /** 移动端为空时的占位文案 */
  emptyText?: string
}

const props = withDefaults(defineProps<Props>(), {
  loading: false,
  rowKey: 'id',
  switchAt: 'md',
  emptyText: '暂无数据',
})

const { breakpoint } = useResponsive()

// breakpoint: xs | sm | md | lg | xl
const useMobile = computed(() => {
  const bp = breakpoint.value
  if (props.switchAt === 'sm') return bp === 'xs'
  if (props.switchAt === 'lg') return ['xs', 'sm', 'md'].includes(bp)
  // 默认 'md'
  return ['xs', 'sm'].includes(bp)
})
</script>

<template>
  <div class="responsive-data-view" :data-mode="useMobile ? 'mobile' : 'desktop'">
    <!-- 桌面端：保留业务自己的 el-table；mobile 时通过 v-show 隐藏，避免重新渲染抖动 -->
    <div v-show="!useMobile" class="rdv-desktop">
      <slot />
    </div>

    <!-- 移动端：卡片列表 -->
    <div v-if="useMobile" class="rdv-mobile" v-loading="loading">
      <template v-if="data.length > 0">
        <div
          v-for="(row, index) in data"
          :key="row[rowKey] ?? index"
          class="rdv-card"
        >
          <slot name="mobile-card" :row="row" :index="index" />
        </div>
        <div v-if="$slots['mobile-footer']" class="rdv-mobile-footer">
          <slot name="mobile-footer" />
        </div>
      </template>
      <el-empty v-else-if="!loading" :description="emptyText" />
    </div>
  </div>
</template>

<style lang="scss" scoped>
.responsive-data-view {
  width: 100%;
}

.rdv-mobile {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-bottom: max(var(--sa-bottom, 0px), 8px);
}

.rdv-card {
  background: #fff;
  border: 1px solid var(--el-border-color-lighter, #ebeef5);
  border-radius: 8px;
  padding: 12px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}

.rdv-mobile-footer {
  display: flex;
  justify-content: center;
  margin-top: 12px;
}
</style>

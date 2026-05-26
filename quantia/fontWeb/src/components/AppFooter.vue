<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useResponsive } from '@/composables/useResponsive'

// M2: 移动端底部安全区 + ICP 占位
// 仅在 layout 内的常规页面显示；登录/注册/全屏类页面 (path 以 /login /register 开头) 不显示。
const route = useRoute()
const { isMobile } = useResponsive()

const visible = computed(() => {
  if (!isMobile.value) return false
  const p = route.path || ''
  if (p.startsWith('/login') || p.startsWith('/register')) return false
  return true
})

// ICP 备案号占位 — 真正部署时填入实际备案号；为空字符串则不渲染备案行
const icpNumber = ''
const year = new Date().getFullYear()
</script>

<template>
  <footer v-if="visible" class="app-footer">
    <div class="app-footer-inner">
      <span class="risk-tip">投资有风险，决策须谨慎。本系统仅供研究学习，不构成投资建议。</span>
      <span v-if="icpNumber" class="icp">
        <a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener">{{ icpNumber }}</a>
      </span>
      <span class="copyright">© {{ year }} Quantia</span>
    </div>
  </footer>
</template>

<style scoped lang="scss">
.app-footer {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 100;
  background: rgba(255, 255, 255, 0.96);
  border-top: 1px solid #ebeef5;
  backdrop-filter: blur(6px);
  @include safe-area-bottom;
  pointer-events: none; // 文本只读，不挡内容点击
}

.app-footer-inner {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  justify-content: center;
  align-items: center;
  padding: 6px 12px;
  font-size: 11px;
  color: #909399;
  line-height: 1.4;
  pointer-events: auto;

  .risk-tip {
    flex: 1 1 100%;
    text-align: center;
  }

  .icp a {
    color: #909399;
    text-decoration: none;
    &:hover { color: #409eff; }
  }
}
</style>

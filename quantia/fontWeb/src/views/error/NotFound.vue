<template>
  <div class="not-found">
    <div class="not-found-content">
      <el-icon class="not-found-icon" :size="80" color="#909399">
        <Warning />
      </el-icon>
      <h1 class="not-found-title">404</h1>
      <p class="not-found-desc">抱歉，您访问的页面不存在</p>
      <el-button type="primary" @click="goHome">
        <el-icon><HomeFilled /></el-icon>
        返回首页
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { Warning, HomeFilled } from '@element-plus/icons-vue'

const router = useRouter()
const goHome = () => router.push('/home')
</script>

<style scoped>
.not-found {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
  min-height: 60vh;
}
.not-found-content {
  text-align: center;
}
.not-found-icon {
  margin-bottom: 16px;
}
.not-found-title {
  font-size: 72px;
  font-weight: 700;
  color: #303133;
  margin: 0 0 8px;
}
.not-found-desc {
  font-size: 16px;
  color: #909399;
  margin: 0 0 24px;
}
</style>

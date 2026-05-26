import { createApp } from 'vue'
import { createPinia } from 'pinia'
// PR-02: Element Plus 组件 + 图标按需引入，由 vite.config.ts 中的 unplugin-vue-components
// 自动补 `import { ElButton } from 'element-plus'` 及 `import { Plus } from '@element-plus/icons-vue'`。
// 这里只保留样式（base reset + 主题变量）+ message/notification 等命令式组件的样式。
// 注：ElMessage/ElMessageBox 的样式由对应组件按需 import 副作用注入。
import 'element-plus/dist/index.css'

import App from './App.vue'
import router from './router'
import './styles/index.scss'
import { startWebVitals } from './lib/webVitals'

// 开发模式下启用 Mock 服务
async function enableMocking() {
  // 检查是否是 mock 模式
  if (import.meta.env.MODE !== 'mock') {
    return
  }

  const { worker } = await import('./mock/browser')

  return worker.start({
    onUnhandledRequest: 'bypass'  // 未匹配的请求直接放行
  })
}

enableMocking().then(() => {
  const app = createApp(App)

  app.use(createPinia())
  app.use(router)

  app.mount('#app')
  startWebVitals()
})

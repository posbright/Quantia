import { createApp } from 'vue'
import { createPinia } from 'pinia'
// PR-02: Element Plus 组件按需引入（由 vite.config.ts 中的 unplugin-vue-components 自动补 import）
// 仍保留全局 CSS + 命令式组件样式。
// 图标必须全局注册：Sidebar/Navbar/home 等使用 `<component :is="'IconName'">` 动态字符串绑定，
// auto-import 只识别静态标识符，无法解析动态字符串。
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

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

  // 仅注册图标（组件本身由 unplugin-vue-components 按需注入）
  for (const [name, comp] of Object.entries(ElementPlusIconsVue)) {
    app.component(name, comp as any)
  }

  app.use(createPinia())
  app.use(router)

  app.mount('#app')
  startWebVitals()
})

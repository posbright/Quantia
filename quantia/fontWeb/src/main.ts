import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'

import App from './App.vue'
import router from './router'
import './styles/index.scss'

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

  // 注册所有 Element Plus 图标
  for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
    app.component(key, component)
  }

  app.use(createPinia())
  app.use(router)
  app.use(ElementPlus, { locale: zhCn })

  app.mount('#app')
})

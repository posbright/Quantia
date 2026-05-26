import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

// PR-02: 把全部 Element Plus 图标名缓存为 Set，给 Components resolver 用。
// 仅在构建期读取 keys，不会把图标二进制打进运行时——
// 实际生成的是 `import { Plus } from '@element-plus/icons-vue'` 语句，Vite tree-shake。
const ELEMENT_PLUS_ICON_NAMES = new Set(Object.keys(ElementPlusIconsVue))

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname)
  const apiTarget = env.VITE_API_TARGET || 'http://localhost:9988'

  return {
    plugins: [
      vue(),
      // PR-02: ElMessage / ElMessageBox / ElNotification / ElLoading 等命令式 API 仍按
      // 现有 `import { ElMessage } from 'element-plus'` 显式使用；本 AutoImport 主要负责
      // 兜底（如 .vue 内未显式 import 时自动补）。
      AutoImport({
        resolvers: [ElementPlusResolver()],
        dts: 'src/auto-imports.d.ts',
      }),
      // PR-02: 模板里 `<el-button>` / `<ArrowDown />` 不再依赖 main.ts 全量注册，
      // 由 unplugin-vue-components 按需补 import。
      Components({
        resolvers: [
          ElementPlusResolver(),
          (componentName: string) => {
            if (ELEMENT_PLUS_ICON_NAMES.has(componentName)) {
              return { name: componentName, from: '@element-plus/icons-vue' }
            }
            return undefined
          },
        ],
        dts: 'src/components.d.ts',
        dirs: [], // 不自动扫描 src/components；本地组件保持显式 import，避免冲突
      }),
    ],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, 'src')
      }
    },
    server: {
      port: 3000,
      proxy: {
        // 代理后端 API（target 由 .env.development 中 VITE_API_TARGET 控制）
        '/api': {
          target: apiTarget,
          changeOrigin: true
        },
        '/quantia': {
          target: apiTarget,
          changeOrigin: true
        }
      }
    },
    build: {
      outDir: 'dist',
      assetsDir: 'assets',
      chunkSizeWarningLimit: 600,
      rollupOptions: {
        output: {
          // M0 / PR-12: 把 vendor 拆出来，业务 chunk 才能进二级缓存
          manualChunks(id: string) {
            if (!id.includes('node_modules')) return
            if (id.includes('echarts') || id.includes('zrender')) return 'vendor-echarts'
            if (id.includes('element-plus') || id.includes('@element-plus')) return 'vendor-element'
            if (id.includes('@vue') || id.includes('/vue/') || id.includes('vue-router') || id.includes('pinia')) return 'vendor-vue'
            if (id.includes('jspdf') || id.includes('html2canvas')) return 'vendor-export'
            if (id.includes('markdown-it')) return 'vendor-markdown'
            if (
              id.includes('axios') ||
              id.includes('dayjs') ||
              id.includes('lodash') ||
              id.includes('@vueuse/core') ||
              id.includes('web-vitals')
            ) return 'vendor-utils'
            return 'vendor'
          }
        }
      }
    },
    css: {
      preprocessorOptions: {
        scss: {
          // M1: 全局注入响应式断点 mixin，任何 .vue/.scss 文件可直接用 mixin（不需手写 @use）
          additionalData: '@use "@/styles/_breakpoints.scss" as *;\n',
          api: 'modern-compiler' as const,
        }
      }
    }
  }
})

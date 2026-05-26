import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname)
  const apiTarget = env.VITE_API_TARGET || 'http://localhost:9988'

  return {
    plugins: [vue()],
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
          // M0: 把 vendor 拆出来，业务 chunk 才能进二级缓存
          manualChunks(id: string) {
            if (!id.includes('node_modules')) return
            if (id.includes('echarts') || id.includes('zrender')) return 'vendor-echarts'
            if (id.includes('element-plus') || id.includes('@element-plus')) return 'vendor-element'
            if (id.includes('@vue') || id.includes('/vue/') || id.includes('vue-router') || id.includes('pinia')) return 'vendor-vue'
            if (id.includes('jspdf') || id.includes('html2canvas')) return 'vendor-export'
            if (id.includes('axios') || id.includes('dayjs') || id.includes('lodash')) return 'vendor-utils'
            return 'vendor'
          }
        }
      }
    },
    css: {
      preprocessorOptions: {
        scss: {
          // M1: 全局注入 响应式断点 mixin，任何 .vue/.scss 文件可直接用 mixin（不需手写 @use）
          additionalData: '@use "@/styles/_breakpoints.scss" as *;\n',
          api: 'modern-compiler' as const,
        }
      }
    }
  }
})

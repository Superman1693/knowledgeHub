import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 后端端口由启动脚本（scripts/run.py）通过环境变量注入，
// 以便在 8000 被其他程序占用时自动避让。
const backendPort = process.env.KH_BACKEND_PORT || '8000'
const frontendPort = Number(process.env.KH_FRONTEND_PORT || 5173)

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '127.0.0.1',
    port: frontendPort,
    // 端口已由启动脚本预先探测为空闲，因此严格要求使用该端口
    strictPort: true,
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${backendPort}`,
        changeOrigin: true,
      },
    },
  },
})

import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 后端端口由启动脚本（scripts/run.py）通过环境变量注入，
// 以便在 8000 被其他程序占用时自动避让。
const backendPort = process.env.KH_BACKEND_PORT || '8000'
const frontendPort = Number(process.env.KH_FRONTEND_PORT || 5173)

// 监听地址：默认仅本机。要让手机/其它设备通过局域网访问时，
// 在 .env 里把 BACKEND_HOST 设为 0.0.0.0，启动脚本会同步注入 KH_HOST。
// ⚠️ 对外监听时后端会强制要求 ACCESS_TOKEN（见 backend/app/core/security.py），
// 否则启动直接失败——局域网不等于可信网络。
const host = process.env.KH_HOST || '127.0.0.1'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host,
    port: frontendPort,
    // 端口已由启动脚本预先探测为空闲，因此严格要求使用该端口
    strictPort: true,
    proxy: {
      '/api': {
        // 代理目标是本机后端，与外网监听地址无关，固定用回环
        target: `http://127.0.0.1:${backendPort}`,
        changeOrigin: true,
      },
    },
  },
})

import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

/**
 * 前端单元测试配置。
 *
 * 单独一份配置（而不是塞进 vite.config.ts）：构建配置关心产物与代理，
 * 测试配置关心环境与 include，分开后两者互不牵连。
 * `environment: 'jsdom'` 是必需的——DOMPurify 需要一个真实 DOM 才能按白名单净化。
 */
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.spec.ts'],
    // 测试不需要真实后端；所有网络调用都在用例里被 stub
    restoreMocks: true,
  },
})

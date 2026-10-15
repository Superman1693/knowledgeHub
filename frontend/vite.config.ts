import { fileURLToPath, URL } from 'node:url'
import { cp, mkdir } from 'node:fs/promises'
import path from 'node:path'
import { createReadStream } from 'node:fs'
import { defineConfig, type Plugin } from 'vite'
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

/**
 * 把 pdf.js 的 cMap 与标准字体提供给浏览器。
 *
 * **为什么必须提供**：cMap 是把字形映射回 Unicode 的对照表，
 * 缺了它 `getTextContent()` 对中日韩 PDF 会返回 0 个文本项——
 * 也就是中文 PDF 的文本层整个消失、无法划词。这是本项目的核心场景。
 *
 * **为什么不用 CDN**：项目定位是「本地优先、可离线」，断网时中文 PDF
 * 打不开是不可接受的（同理 worker 也不用 CDN）。
 *
 * **为什么不用 `public/` + 手动拷贝**：1.4MB / 169 个二进制文件进版本库没有意义，
 * 而且一旦有人直接跑 `vite build`（不经 npm 脚本）就会漏拷，且**是静默失效**——
 * 文本层渲染不出来但没有任何报错。做成插件后两种运行方式都自动处理。
 */
function pdfjsAssets(): Plugin {
  const mount = '/pdfjs'
  const srcRoot = fileURLToPath(new URL('./node_modules/pdfjs-dist', import.meta.url))
  const dirs = ['cmaps', 'standard_fonts']
  const MIME: Record<string, string> = {
    '.bcmap': 'application/octet-stream',
    '.ttf': 'font/ttf',
    '.otf': 'font/otf',
    '.pfb': 'application/octet-stream',
    '.ttc': 'font/collection',
  }

  return {
    name: 'kh-pdfjs-assets',

    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = (req.url || '').split('?')[0]
        if (!url.startsWith(`${mount}/`)) return next()

        const rel = decodeURIComponent(url.slice(mount.length + 1))
        const abs = path.resolve(srcRoot, rel)
        // 目录穿越防护：只允许读 pdfjs-dist 内部的资源。
        // 刻意**返回 404 而不是 next()** —— 交给后续中间件的话，
        // dev 下 Vite 的静态服务会把 `/pdfjs/../package.json` 归一化成项目根的文件并返回 200，
        // 行为随 Vite 版本变化；这里自己收口更可预测。
        if (abs !== path.resolve(srcRoot) && !abs.startsWith(path.resolve(srcRoot) + path.sep)) {
          res.statusCode = 404
          res.end()
          return
        }

        res.setHeader('Content-Type', MIME[path.extname(abs).toLowerCase()] || 'application/octet-stream')
        res.setHeader('Cache-Control', 'public, max-age=86400')
        createReadStream(abs)
          .on('error', () => {
            res.statusCode = 404
            res.end()
          })
          .pipe(res)
      })
    },

    async closeBundle() {
      // 产物里也要有：构建后直接部署时不能依赖 node_modules
      const outRoot = path.resolve(fileURLToPath(new URL('./dist', import.meta.url)), 'pdfjs')
      for (const dir of dirs) {
        await mkdir(path.join(outRoot, dir), { recursive: true })
        await cp(path.join(srcRoot, dir), path.join(outRoot, dir), { recursive: true })
      }
    },
  }
}

export default defineConfig({
  plugins: [vue(), pdfjsAssets()],
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

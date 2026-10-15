// PDF 批注坐标系的浏览器自检驱动。
//
// 为什么需要它：坐标换算是 PDF 批注方案里唯一「做了才发现不对」的部分，
// 而它只有在**真实浏览器 + 真实 pdf.js 文本层**里才能验证 —— jsdom 没有布局引擎，
// 单元测试只能覆盖纯函数（边界、往返、缩放不变性），覆盖不到「pdf.js 渲染出来的
// 文本层，它的 DOM 矩形归一化后，在另一个缩放下重绘是否还压在原文上」。
//
// 用法（需先启动前端 dev server）：
//   1) cd frontend && npm run dev
//   2) node e2e/run-pdf-coords-selftest.mjs
// 退出码 0 = 全部通过。
//
// 实现：用 Chrome DevTools Protocol 驱动 headless Chrome。
// Node 22 自带全局 WebSocket，因此不需要 puppeteer / playwright 这类依赖。
import { spawn } from 'node:child_process'
import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { setTimeout as sleep } from 'node:timers/promises'
import { fileURLToPath } from 'node:url'

const PAGE_URL =
  process.env.SELFTEST_URL || 'http://127.0.0.1:5173/e2e/pdf-coords.selftest.html?worker=1'
const PORT = Number(process.env.CDP_PORT || 9333)
const WAIT_MS = Number(process.env.WAIT_MS || 90000)

const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  '/usr/bin/google-chrome',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
].filter(Boolean)

const chromePath = CHROME_CANDIDATES.find((p) => existsSync(p))
if (!chromePath) {
  console.error('找不到 Chrome/Edge，可用 CHROME_PATH 环境变量指定')
  process.exit(2)
}

const profileDir = mkdtempSync(path.join(tmpdir(), 'kh-pdf-selftest-'))
const chrome = spawn(
  chromePath,
  [
    '--headless=new',
    '--disable-gpu',
    '--no-sandbox',
    '--no-proxy-server', // 本机访问不该走系统代理
    '--hide-scrollbars',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${profileDir}`,
    'about:blank',
  ],
  { stdio: 'ignore' },
)

let exitCode = 1
try {
  // ---------- 等 CDP 端口就绪 ----------
  let target = null
  for (let i = 0; i < 60 && !target; i++) {
    await sleep(500)
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()
      target = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl)
    } catch {
      /* Chrome 还没起来 */
    }
  }
  if (!target) throw new Error('等不到可调试的页面目标')

  const ws = new WebSocket(target.webSocketDebuggerUrl)
  let id = 0
  const pending = new Map()
  ws.addEventListener('message', (e) => {
    const m = JSON.parse(e.data)
    const r = pending.get(m.id)
    if (r) {
      pending.delete(m.id)
      r(m)
    }
  })
  await new Promise((r, j) => {
    ws.addEventListener('open', r)
    ws.addEventListener('error', () => j(new Error('CDP 连接失败')))
  })
  const send = (method, params = {}) =>
    new Promise((r) => {
      const i = ++id
      pending.set(i, r)
      ws.send(JSON.stringify({ id: i, method, params }))
    })

  const evaluate = async (expression) => {
    const m = await send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true,
    })
    if (m.result?.exceptionDetails) {
      throw new Error('页面内异常: ' + JSON.stringify(m.result.exceptionDetails.exception))
    }
    return m.result?.result?.value
  }

  await send('Page.enable')
  await send('Runtime.enable')
  await send('Page.navigate', { url: `${PAGE_URL}&_t=${Date.now()}` })

  // ---------- 轮询直到页面自报完成 ----------
  const deadline = Date.now() + WAIT_MS
  let title = ''
  let text = ''
  while (Date.now() < deadline) {
    await sleep(700)
    try {
      title = (await evaluate('document.title')) || ''
      text = (await evaluate('document.getElementById("result").innerText')) || ''
    } catch {
      continue
    }
    if (title.startsWith('DONE')) break
  }

  console.log(text || '(页面无输出)')
  console.log('---')
  console.log('title:', title)
  exitCode = title.startsWith('DONE PASS') ? 0 : 1
  ws.close()
} catch (err) {
  console.error('自检驱动失败：', err.message)
  console.error(`（确认 dev server 已在运行，且地址为 ${PAGE_URL}）`)
} finally {
  chrome.kill()
  await sleep(500)
  try {
    rmSync(profileDir, { recursive: true, force: true })
  } catch {
    /* Windows 上偶发占用，忽略 */
  }
}

process.exit(exitCode)

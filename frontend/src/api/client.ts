import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

declare module 'axios' {
  export interface AxiosRequestConfig {
    /**
     * 由调用方显式关闭该请求失败时的全局 toast。
     * 用于「自己会处理错误」的场景——最典型的是编辑器自动保存：
     * 它需要把 409 冲突转成一个对比对话框，而不是同时弹一条提示。
     */
    silent?: boolean
  }
}

const client = axios.create({
  baseURL: '/api',
  timeout: 180000,
})

// ---------------- 局域网访问口令 ----------------
/**
 * 后端把 BACKEND_HOST 设为 0.0.0.0 对外提供局域网访问时，会要求访问口令。
 * 口令存在 localStorage，随每个请求以请求头发送。
 *
 * 用 localStorage 而不是 cookie：本项目是纯本地工具，没有服务端会话，
 * cookie 只会多一层 SameSite/域的限制，没有收益。
 */
const TOKEN_KEY = 'kh-access-token'

export function getAccessToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) || ''
  } catch {
    // 隐私模式下 localStorage 可能不可用——退化为「无口令」，
    // 仅本机访问时本来就无需口令，不影响正常使用
    return ''
  }
}

export function setAccessToken(token: string) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* 同上 */
  }
}

client.interceptors.request.use((config) => {
  const token = getAccessToken()
  if (token) config.headers.set('X-Access-Token', token)
  return config
})

/**
 * 口令缺失/错误时弹一次输入框。
 *
 * 用模块级 flag 去重：一进页面往往并发发出十几个请求，
 * 全都会拿到 401，不做去重就会叠出十几个输入框。
 */
let prompting = false

async function promptForToken() {
  if (prompting) return
  prompting = true
  try {
    const { value } = await ElMessageBox.prompt(
      '这台设备访问知识库需要口令（由运行服务的机器在 .env 中设置 ACCESS_TOKEN）。',
      '需要访问口令',
      { confirmButtonText: '确定', cancelButtonText: '取消', inputType: 'password' },
    )
    if (value) {
      setAccessToken(value.trim())
      ElMessage.success('已保存口令，正在重新加载…')
      window.location.reload()
    }
  } catch {
    /* 用户取消：保持未授权状态，不再打扰 */
  } finally {
    prompting = false
  }
}

/**
 * 从后端错误响应中提取可读信息。
 * 后端业务异常形如 {code, message, detail}；而 FastAPI 的参数校验失败
 * 返回的是 {detail: [{loc, msg, ...}]} —— detail 是**数组**，
 * 直接 String() 会得到 "[object Object]"，用户看不到任何有效信息。
 */
function readableError(error: any): string {
  const data = error?.response?.data
  if (typeof data?.message === 'string' && data.message) return data.message
  if (typeof data?.detail === 'string' && data.detail) return data.detail
  if (Array.isArray(data?.detail)) {
    const parts = data.detail
      .map((d: any) => {
        const loc = Array.isArray(d?.loc) ? d.loc.slice(1).join('.') : ''
        const msg = d?.msg ?? d?.message ?? ''
        return loc && msg ? `${loc}: ${msg}` : String(msg || '')
      })
      .filter(Boolean)
    if (parts.length) return parts.join('；')
  }
  return error?.message || '请求失败'
}

client.interceptors.response.use(
  (response) => response,
  (error) => {
    // 401 单独处理：弹口令输入框，而不是弹一条看不懂的错误提示
    if (error?.response?.status === 401) {
      void promptForToken()
      return Promise.reject(error)
    }
    // silent 请求自行处理错误（如编辑器的 409 冲突会转成对比对话框）
    if (!error?.config?.silent) {
      ElMessage.error(readableError(error))
    }
    return Promise.reject(error)
  },
)

export default client

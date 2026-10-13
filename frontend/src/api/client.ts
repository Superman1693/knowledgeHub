import axios from 'axios'
import { ElMessage } from 'element-plus'

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
    // silent 请求自行处理错误（如编辑器的 409 冲突会转成对比对话框）
    if (!error?.config?.silent) {
      ElMessage.error(readableError(error))
    }
    return Promise.reject(error)
  },
)

export default client

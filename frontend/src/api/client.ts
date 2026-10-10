import axios from 'axios'
import { ElMessage } from 'element-plus'

const client = axios.create({
  baseURL: '/api',
  timeout: 180000,
})

client.interceptors.response.use(
  (response) => response,
  (error) => {
    const message =
      error?.response?.data?.message ||
      error?.response?.data?.detail ||
      error?.message ||
      '请求失败'
    ElMessage.error(String(message))
    return Promise.reject(error)
  },
)

export default client

import axios, { type AxiosInstance, type AxiosRequestConfig, type InternalAxiosRequestConfig } from 'axios'
import { normalizeApiBaseURL } from '@/utils/network'
import { loadAppSettings } from '@/utils/settings'

interface RequestMetadata {
  startTime: number
}

type TimedAxiosRequestConfig = InternalAxiosRequestConfig & {
  metadata?: RequestMetadata
}

/** 解析 API 根地址：优先本地设置，其次 Vite 环境变量 */
function resolveBaseURL() {
  const settings = loadAppSettings()
  const configured = settings.apiBaseUrl.trim() || import.meta.env.VITE_API_BASE_URL?.trim()
  return normalizeApiBaseURL(configured)
}

/** 将 params 展平为日志友好字符串 */
function formatParams(params: unknown) {
  if (!params || typeof params !== 'object') return ''
  const entries = Object.entries(params as Record<string, unknown>)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([key, value]) => `${key}=${String(value)}`)
  return entries.length ? ` ${entries.join(' ')}` : ''
}

/** 提取请求方法、路径、参数与超时，供拦截器日志使用 */
function describeRequest(config: TimedAxiosRequestConfig) {
  const method = (config.method || 'get').toUpperCase()
  const url = config.url || ''
  const params = formatParams(config.params)
  const timeout = config.timeout ?? 30000
  return { method, url, params, timeout }
}

/** 全局 Axios 实例：统一 baseURL、超时与 JSON Content-Type */
const request: AxiosInstance = axios.create({
  baseURL: resolveBaseURL(),
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

request.interceptors.request.use(
  (config) => {
    const timedConfig = config as TimedAxiosRequestConfig
    const url = timedConfig.url || ''
    // /api/*（非 /api/v1/*）走同源相对路径，避免重复拼接 baseURL
    timedConfig.baseURL = url.startsWith('/api/') && !url.startsWith('/api/v1/') ? '' : resolveBaseURL()
    timedConfig.metadata = { startTime: Date.now() }
    const token = localStorage.getItem('token')
    if (token) {
      timedConfig.headers.Authorization = `Bearer ${token}`
    }
    return timedConfig
  },
  (error) => Promise.reject(error),
)

request.interceptors.response.use(
  (response) => {
    const config = response.config as TimedAxiosRequestConfig
    const duration = Date.now() - (config.metadata?.startTime ?? Date.now())
    const { method, url, params } = describeRequest(config)
    console.info(`[API] ${method} ${url}${params} duration=${duration}ms status=ok`)
    // 业务层直接拿到 data，不再包一层 AxiosResponse
    return response.data
  },
  (error) => {
    const config = (error.config || {}) as TimedAxiosRequestConfig
    const duration = Date.now() - (config.metadata?.startTime ?? Date.now())
    const { method, url, params, timeout } = describeRequest(config)
    const errorType = error.code || (error.response ? `HTTP_${error.response.status}` : 'UNKNOWN')
    console.error(
      `[API Error] ${method} ${url}${params} timeout=${timeout}ms duration=${duration}ms type=${errorType} message=${error.message}`,
    )
    return Promise.reject(error)
  },
)

export default request
export type { AxiosRequestConfig }

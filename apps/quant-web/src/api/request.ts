import axios, { type AxiosInstance, type AxiosRequestConfig, type InternalAxiosRequestConfig } from 'axios'
import {
  formatApiLogSummary,
  isProductionBuild,
  toSafeErrorInfo,
} from '@/utils/errorRedaction'
import { normalizeApiBaseURL } from '@/utils/network'
import { purgeLegacyWebCredentials } from '@/utils/settings'

interface RequestMetadata {
  startTime: number
}

type TimedAxiosRequestConfig = InternalAxiosRequestConfig & {
  metadata?: RequestMetadata
}

/** 解析 API 根地址：只接受 Vite 环境变量，否则使用同源默认值。 */
function resolveBaseURL() {
  return normalizeApiBaseURL(import.meta.env.VITE_API_BASE_URL?.trim())
}

/** 提取请求方法与路径（不含 query/body），供安全摘要日志使用 */
function describeRequest(config: TimedAxiosRequestConfig) {
  const method = (config.method || 'get').toUpperCase()
  const url = config.url || ''
  const timeout = config.timeout ?? 30000
  return { method, url, timeout }
}

/** 全局 Axios 实例：统一 baseURL、超时与 JSON Content-Type */
const request: AxiosInstance = axios.create({
  baseURL: resolveBaseURL(),
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

purgeLegacyWebCredentials()

request.interceptors.request.use(
  (config) => {
    const timedConfig = config as TimedAxiosRequestConfig
    const url = timedConfig.url || ''
    // /api/*（非 /api/v1/*）走同源相对路径，避免重复拼接 baseURL
    timedConfig.baseURL = url.startsWith('/api/') && !url.startsWith('/api/v1/') ? '' : resolveBaseURL()
    timedConfig.metadata = { startTime: Date.now() }
    return timedConfig
  },
  (error) => Promise.reject(error),
)

request.interceptors.response.use(
  (response) => {
    const config = response.config as TimedAxiosRequestConfig
    const duration = Date.now() - (config.metadata?.startTime ?? Date.now())
    const { method, url } = describeRequest(config)
    // Production 不输出每次 API 成功日志；开发环境仅安全摘要
    if (!isProductionBuild()) {
      console.info(formatApiLogSummary({ method, url, status: 'ok', durationMs: duration }))
    }
    // 业务层直接拿到 data，不再包一层 AxiosResponse
    return response.data
  },
  (error) => {
    const config = (error.config || {}) as TimedAxiosRequestConfig
    const duration = Date.now() - (config.metadata?.startTime ?? Date.now())
    const { method, url } = describeRequest(config)
    const safe = toSafeErrorInfo(error, 'request failed')
    console.error(
      formatApiLogSummary({
        method,
        url,
        status: 'error',
        durationMs: duration,
        errorType: safe.errorType,
      }),
    )
    return Promise.reject(error)
  },
)

export default request
export type { AxiosRequestConfig }

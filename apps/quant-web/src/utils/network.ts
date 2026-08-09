export type BrowserLocation = Pick<Location, 'protocol' | 'host' | 'hostname'>

/** 默认 API 基础路径（相对当前站点） */
export const DEFAULT_API_BASE_URL = '/api/v1'

function isLocalHostname(hostname: string) {
  return hostname === 'localhost' || hostname === '127.0.0.1'
}

/**
 * 判断 URL 是否指向 localhost / 127.0.0.1。
 */
export function pointsToLocalhost(value: string) {
  const trimmed = value.trim()
  if (!trimmed) return false
  return /^(https?|wss?):\/\/(localhost|127\.0\.0\.1)(:\d+)?(\/|$)/i.test(trimmed)
}

/**
 * 非本地访问时忽略指向 localhost 的端点配置，避免远程部署误连开发机。
 */
export function shouldIgnoreLocalhostEndpoint(value: string, locationOverride?: BrowserLocation) {
  const configured = value.trim()
  if (!configured || !pointsToLocalhost(configured)) return false

  const location = locationOverride ?? getBrowserLocation()
  if (!location) return false
  return !isLocalHostname(location.hostname)
}

/**
 * 规范化 API 基础 URL：空值用默认路径，忽略无效 localhost 配置，去除末尾斜杠。
 */
export function normalizeApiBaseURL(value?: string, locationOverride?: BrowserLocation) {
  const configured = value?.trim() ?? ''
  if (!configured) return DEFAULT_API_BASE_URL
  if (shouldIgnoreLocalhostEndpoint(configured, locationOverride)) return DEFAULT_API_BASE_URL
  return configured.replace(/\/+$/, '')
}

/**
 * 解析 WebSocket URL：优先使用有效配置，否则按当前页面协议推导 ws/wss 地址。
 */
export function resolveWsURL(value?: string, locationOverride?: BrowserLocation) {
  const configured = value?.trim() ?? ''
  const currentLocation = locationOverride ?? getBrowserLocation()

  if (configured && !shouldIgnoreLocalhostEndpoint(configured, locationOverride)) {
    return configured.replace(/\/+$/, '')
  }

  if (!currentLocation) return '/api/v1/market/ws'

  const protocol = currentLocation.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${currentLocation.host}/api/v1/market/ws`
}

function getBrowserLocation() {
  if (typeof window === 'undefined') return undefined
  return window.location
}

import { shouldIgnoreLocalhostEndpoint } from './network'

/** 应用级用户设置（API、WebSocket、交易所、配色） */
export interface AppSettings {
  apiBaseUrl: string
  wsUrl: string
  defaultExchange: string
  redUpGreenDown: boolean
}

const STORAGE_KEY = 'guiyi_app_settings'

const defaultSettings: AppSettings = {
  apiBaseUrl: '',
  wsUrl: '',
  defaultExchange: 'DCE',
  redUpGreenDown: true,
}

/** 清理无效 localhost 端点并回写 localStorage */
function sanitizeSettings(settings: AppSettings): AppSettings {
  const next = { ...settings }
  let changed = false

  if (shouldIgnoreLocalhostEndpoint(next.apiBaseUrl)) {
    next.apiBaseUrl = ''
    changed = true
  }
  if (shouldIgnoreLocalhostEndpoint(next.wsUrl)) {
    next.wsUrl = ''
    changed = true
  }

  if (changed && typeof localStorage !== 'undefined') {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
  }

  return next
}

/**
 * 从 localStorage 加载应用设置，失败时返回默认值。
 */
export function loadAppSettings(): AppSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...defaultSettings }
    return sanitizeSettings({ ...defaultSettings, ...JSON.parse(raw) })
  } catch {
    return { ...defaultSettings }
  }
}

/**
 * 保存应用设置到 localStorage（会先 sanitize）。
 */
export function saveAppSettings(settings: AppSettings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(sanitizeSettings(settings)))
}

/**
 * 获取已配置的 API 基础 URL（trim 后，空则调用方需用默认值）。
 */
export function resolvedApiBaseUrl(settings = loadAppSettings()) {
  return settings.apiBaseUrl.trim()
}

/**
 * 获取已配置的 WebSocket URL（trim 后，空则调用方需推导）。
 */
export function resolvedWsUrl(settings = loadAppSettings()) {
  return settings.wsUrl.trim()
}

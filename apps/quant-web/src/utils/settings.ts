import { shouldIgnoreLocalhostEndpoint } from './network.ts'

/** 应用级用户设置（API、WebSocket、交易所、配色） */
export interface AppSettings {
  apiBaseUrl: string
  wsUrl: string
  defaultExchange: string
  redUpGreenDown: boolean
}

const STORAGE_KEY = 'guiyi_app_settings'
const CONNECTION_STORAGE_KEY = 'guiyi_connection_overrides'

const defaultSettings: AppSettings = {
  apiBaseUrl: '',
  wsUrl: '',
  defaultExchange: 'DCE',
  redUpGreenDown: true,
}

/** 清理无效 localhost 端点；连接覆盖只允许保留在当前会话。 */
function sanitizeSettings(settings: AppSettings): AppSettings {
  const next = { ...settings }

  if (shouldIgnoreLocalhostEndpoint(next.apiBaseUrl)) {
    next.apiBaseUrl = ''
  }
  if (shouldIgnoreLocalhostEndpoint(next.wsUrl)) {
    next.wsUrl = ''
  }

  return next
}

/**
 * 从 localStorage 加载显示偏好，从 sessionStorage 加载临时连接覆盖。
 * 旧版本留在 localStorage 的 API/WS 地址会迁入当前会话并从长期存储删除。
 */
export function loadAppSettings(): AppSettings {
  try {
    const local = storageOf('local')
    const session = storageOf('session')
    const persisted = parseRecord(local?.getItem(STORAGE_KEY))
    const overrides = parseRecord(session?.getItem(CONNECTION_STORAGE_KEY))
    const migratedApi = stringValue(persisted.apiBaseUrl)
    const migratedWs = stringValue(persisted.wsUrl)
    if ((migratedApi || migratedWs) && session) {
      session.setItem(CONNECTION_STORAGE_KEY, JSON.stringify({ apiBaseUrl: migratedApi, wsUrl: migratedWs }))
    }
    if ((migratedApi || migratedWs) && local) {
      local.setItem(STORAGE_KEY, JSON.stringify(displaySettings({ ...defaultSettings, ...persisted })))
    }
    return sanitizeSettings({
      ...defaultSettings,
      ...persisted,
      apiBaseUrl: stringValue(overrides.apiBaseUrl) || migratedApi,
      wsUrl: stringValue(overrides.wsUrl) || migratedWs,
    })
  } catch {
    return { ...defaultSettings }
  }
}

/**
 * 保存显示偏好到 localStorage；API/WS 覆盖仅保存到 sessionStorage。
 */
export function saveAppSettings(settings: AppSettings) {
  const sanitized = sanitizeSettings(settings)
  storageOf('local')?.setItem(STORAGE_KEY, JSON.stringify(displaySettings(sanitized)))
  storageOf('session')?.setItem(CONNECTION_STORAGE_KEY, JSON.stringify({
    apiBaseUrl: sanitized.apiBaseUrl,
    wsUrl: sanitized.wsUrl,
  }))
}

/** 删除旧 Web Bearer token；单用户工作台不提供浏览器凭据注入。 */
export function purgeLegacyWebCredentials() {
  storageOf('local')?.removeItem('token')
  storageOf('session')?.removeItem('token')
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

function storageOf(kind: 'local' | 'session'): Storage | null {
  if (typeof globalThis === 'undefined') return null
  return kind === 'local'
    ? (typeof globalThis.localStorage === 'undefined' ? null : globalThis.localStorage)
    : (typeof globalThis.sessionStorage === 'undefined' ? null : globalThis.sessionStorage)
}

function parseRecord(raw: string | null | undefined): Record<string, unknown> {
  if (!raw) return {}
  const parsed = JSON.parse(raw)
  return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}
}

function stringValue(value: unknown) {
  return typeof value === 'string' ? value.trim() : ''
}

function displaySettings(settings: AppSettings) {
  return {
    defaultExchange: settings.defaultExchange,
    redUpGreenDown: settings.redUpGreenDown,
  }
}

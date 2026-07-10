import { shouldIgnoreLocalhostEndpoint } from './network'

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

export function loadAppSettings(): AppSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...defaultSettings }
    return sanitizeSettings({ ...defaultSettings, ...JSON.parse(raw) })
  } catch {
    return { ...defaultSettings }
  }
}

export function saveAppSettings(settings: AppSettings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(sanitizeSettings(settings)))
}

export function resolvedApiBaseUrl(settings = loadAppSettings()) {
  return settings.apiBaseUrl.trim()
}

export function resolvedWsUrl(settings = loadAppSettings()) {
  return settings.wsUrl.trim()
}

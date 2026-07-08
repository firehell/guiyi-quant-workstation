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

export function loadAppSettings(): AppSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...defaultSettings }
    return { ...defaultSettings, ...JSON.parse(raw) }
  } catch {
    return { ...defaultSettings }
  }
}

export function saveAppSettings(settings: AppSettings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
}

export function resolvedApiBaseUrl(settings = loadAppSettings()) {
  return settings.apiBaseUrl.trim()
}

export function resolvedWsUrl(settings = loadAppSettings()) {
  return settings.wsUrl.trim()
}

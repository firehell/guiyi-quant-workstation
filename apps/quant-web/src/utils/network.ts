export type BrowserLocation = Pick<Location, 'protocol' | 'host'>

export const DEFAULT_API_BASE_URL = '/api/v1'

export function normalizeApiBaseURL(value?: string) {
  const configured = value?.trim() ?? ''
  if (!configured) return DEFAULT_API_BASE_URL
  return configured.replace(/\/+$/, '')
}

export function resolveWsURL(value?: string, locationOverride?: BrowserLocation) {
  const configured = value?.trim() ?? ''
  if (configured) return configured.replace(/\/+$/, '')

  const currentLocation = locationOverride ?? getBrowserLocation()
  if (!currentLocation) return '/ws'

  const protocol = currentLocation.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${currentLocation.host}/ws`
}

function getBrowserLocation() {
  if (typeof window === 'undefined') return undefined
  return window.location
}

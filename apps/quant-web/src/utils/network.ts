export type BrowserLocation = Pick<Location, 'protocol' | 'host'>

export function normalizeApiBaseURL(value?: string) {
  const configured = value?.trim() ?? ''
  if (!configured) return ''
  return configured.replace(/\/+$/, '').replace(/\/api\/v1$/, '').replace(/\/api$/, '')
}

export function resolveWsURL(value?: string, locationOverride?: BrowserLocation) {
  const configured = value?.trim() ?? ''
  if (configured) return configured.replace(/\/+$/, '')

  const currentLocation = locationOverride ?? getBrowserLocation()
  if (!currentLocation) return 'ws://localhost:8000/ws'

  const protocol = currentLocation.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${currentLocation.host}/ws`
}

function getBrowserLocation() {
  if (typeof window === 'undefined') return undefined
  return window.location
}

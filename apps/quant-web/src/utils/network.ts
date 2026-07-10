export type BrowserLocation = Pick<Location, 'protocol' | 'host' | 'hostname'>

export const DEFAULT_API_BASE_URL = '/api/v1'

function isLocalHostname(hostname: string) {
  return hostname === 'localhost' || hostname === '127.0.0.1'
}

export function pointsToLocalhost(value: string) {
  const trimmed = value.trim()
  if (!trimmed) return false
  return /^(https?|wss?):\/\/(localhost|127\.0\.0\.1)(:\d+)?(\/|$)/i.test(trimmed)
}

export function shouldIgnoreLocalhostEndpoint(value: string, locationOverride?: BrowserLocation) {
  const configured = value.trim()
  if (!configured || !pointsToLocalhost(configured)) return false

  const location = locationOverride ?? getBrowserLocation()
  if (!location) return false
  return !isLocalHostname(location.hostname)
}

export function normalizeApiBaseURL(value?: string, locationOverride?: BrowserLocation) {
  const configured = value?.trim() ?? ''
  if (!configured) return DEFAULT_API_BASE_URL
  if (shouldIgnoreLocalhostEndpoint(configured, locationOverride)) return DEFAULT_API_BASE_URL
  return configured.replace(/\/+$/, '')
}

export function resolveWsURL(value?: string, locationOverride?: BrowserLocation) {
  const configured = value?.trim() ?? ''
  const currentLocation = locationOverride ?? getBrowserLocation()

  if (configured && !shouldIgnoreLocalhostEndpoint(configured, locationOverride)) {
    return configured.replace(/\/+$/, '')
  }

  if (!currentLocation) return '/ws'

  const protocol = currentLocation.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${currentLocation.host}/ws`
}

function getBrowserLocation() {
  if (typeof window === 'undefined') return undefined
  return window.location
}

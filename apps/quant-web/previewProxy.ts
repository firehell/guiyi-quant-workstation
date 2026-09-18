import type { Plugin, ProxyOptions } from 'vite'

export const DEFAULT_CANDIDATE_ORIGIN = 'http://127.0.0.1:8010'
export const OVERFLOW_CANDIDATE_ORIGIN = 'http://127.0.0.1:8011'
export const STATUS_ORIGIN = 'http://127.0.0.1:8000'

const candidatePaths = new Set([
  '/api/preview/identity',
  '/api/v1/market/bars/page', '/api/v1/market/dominants',
  '/api/v1/market/research/home-overview',
  '/api/v1/market/newow/product-capabilities',
  '/api/v1/market/newow/strategy-detail', '/api/v1/market/newow/historical-snapshot',
])

export function resolveCandidateOrigin(raw = process.env.GUIYI_PREVIEW_CANDIDATE_ORIGIN): string {
  const origin = raw || DEFAULT_CANDIDATE_ORIGIN
  if (!/^http:\/\/127\.0\.0\.1:801[01]$/.test(origin)) throw new Error('PREVIEW_CANDIDATE_ORIGIN_INVALID')
  return origin
}

export function candidatePreviewWebPort(origin = resolveCandidateOrigin()): number {
  return origin === OVERFLOW_CANDIDATE_ORIGIN ? 5175 : 5174
}

export function previewTarget(
  method: string,
  rawURL: string,
  upgrade = false,
  origin = resolveCandidateOrigin(),
): string | null {
  if (method !== 'GET' || upgrade) return null
  const [path] = rawURL.split('?')
  if (path && (candidatePaths.has(path) || /^\/api\/v1\/market\/[a-z]{1,8}\/subing\/reference$/.test(path))) {
    return origin
  }
  if (rawURL === '/api/runtime/health' || rawURL === '/api/alerts/current-events?limit=30') {
    return STATUS_ORIGIN
  }
  return null
}

export function candidatePreviewPlugin(origin = resolveCandidateOrigin()): Plugin {
  return {
    name: 'candidate-preview-isolation',
    configResolved(config) {
      if (config.server.host !== '127.0.0.1') throw new Error('PREVIEW_LOCAL_ONLY')
      if (origin === OVERFLOW_CANDIDATE_ORIGIN && config.server.port === 5174) {
        throw new Error('PREVIEW_OVERFLOW_PORT_REQUIRED')
      }
    },
    configureServer(server) {
      // Runs before Vite's proxy middleware. Rejected traffic never reaches a target.
      server.middlewares.use((request, response, next) => {
        const url = request.url || ''
        if (!url.startsWith('/api') && !url.startsWith('/ws') && !url.startsWith('/healthz')) return next()
        if (previewTarget(request.method || '', url, false, origin)) return next()
        response.statusCode = 403
        response.setHeader('Content-Type', 'application/json')
        response.end(JSON.stringify({ detail: { code: 'PREVIEW_ROUTE_FORBIDDEN' } }))
      })
      server.httpServer?.prependListener('upgrade', (request, socket) => {
        const url = request.url || ''
        if (url.startsWith('/api') || url.startsWith('/ws')) socket.destroy()
      })
    },
  }
}

export function candidatePreviewProxy(origin = resolveCandidateOrigin()): Record<string, ProxyOptions> {
  return {
    '^/api/(preview/identity|v1/market/)': { target: origin, ws: false },
    '^/api/(runtime/health|alerts/current-events)': { target: STATUS_ORIGIN, ws: false },
  }
}

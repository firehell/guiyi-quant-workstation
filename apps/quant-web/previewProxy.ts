import type { Plugin, ProxyOptions } from 'vite'

const candidatePaths = new Set([
  '/api/preview/identity',
  '/api/v1/market/bars/page', '/api/v1/market/dominants',
  '/api/v1/market/research/home-overview',
  '/api/v1/market/newow/strategy-detail', '/api/v1/market/newow/historical-snapshot',
])

export function previewTarget(method: string, rawURL: string, upgrade = false): string | null {
  if (method !== 'GET' || upgrade) return null
  const [path] = rawURL.split('?')
  if (path && candidatePaths.has(path)) return 'http://127.0.0.1:8010'
  if (rawURL === '/api/runtime/health' || rawURL === '/api/alerts/current-events?limit=30') {
    return 'http://127.0.0.1:8000'
  }
  return null
}

export function candidatePreviewPlugin(): Plugin {
  return {
    name: 'candidate-preview-isolation',
    configResolved(config) {
      if (config.server.host !== '127.0.0.1') throw new Error('PREVIEW_LOCAL_ONLY')
    },
    configureServer(server) {
      // Runs before Vite's proxy middleware. Rejected traffic never reaches a target.
      server.middlewares.use((request, response, next) => {
        const url = request.url || ''
        if (!url.startsWith('/api') && !url.startsWith('/ws') && !url.startsWith('/healthz')) return next()
        if (previewTarget(request.method || '', url)) return next()
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

export function candidatePreviewProxy(): Record<string, ProxyOptions> {
  return {
    '^/api/(preview/identity|v1/market/)': { target: 'http://127.0.0.1:8010', ws: false },
    '^/api/(runtime/health|alerts/current-events)': { target: 'http://127.0.0.1:8000', ws: false },
  }
}

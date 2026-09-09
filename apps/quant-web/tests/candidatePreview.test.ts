import assert from 'node:assert/strict'
import { test } from 'node:test'
import { existsSync } from 'node:fs'

test('candidate preview policy exists as explicit isolated configuration', () => {
  assert.ok(existsSync(new URL('../previewProxy.ts', import.meta.url)))
})

test('proxy allows exact GET resources only, never encoded paths or WS', async () => {
  const { previewTarget } = await import('../previewProxy.ts')
  assert.equal(previewTarget('GET', '/api/v1/market/bars/page?symbol=rb'), 'http://127.0.0.1:8010')
  assert.equal(previewTarget('GET', '/api/preview/identity'), 'http://127.0.0.1:8010')
  assert.equal(previewTarget('GET', '/api/runtime/health'), 'http://127.0.0.1:8000')
  assert.equal(previewTarget('GET', '/api/alerts/current-events?limit=30'), 'http://127.0.0.1:8000')
  for (const path of ['/api/runtime/health/', '/api/runtime/%68ealth', '/api/runtime/health?x=1',
    '/api/alerts/current-events?limit=31', '/api/alerts/current-events?limit=30&limit=30',
    '/api/alerts/rules', '/api/v1/market/state', '/api/v1/market/research/product',
    '/api/v1/market/dominants/', '/api/v1/market/dominants%3F', '/ws/market']) {
    assert.equal(previewTarget('GET', path), null, path)
  }
  for (const method of ['POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD']) {
    assert.equal(previewTarget(method, '/api/runtime/health'), null)
  }
  assert.equal(previewTarget('GET', '/api/runtime/health', true), null)
})

test('browser preview identity must match code, cutoff and both fixed origins', async () => {
  const { matchesPreviewIdentity } = await import('../src/utils/candidatePreview.ts')
  const config = { enabled: true, codeSha: 'a'.repeat(40), asOf: '2026-09-03T08:00:00.000Z' }
  const payload = { mode: 'local_candidate_readonly', code_sha: config.codeSha,
    as_of: '2026-09-03T08:00:00+00:00', realtime: false,
    candidate_origin: 'http://127.0.0.1:8010', status_origin: 'http://127.0.0.1:8000' }
  assert.equal(matchesPreviewIdentity(payload, config), true)
  for (const change of [{ code_sha: 'b'.repeat(40) }, { as_of: '2026-09-04T08:00:00Z' },
    { candidate_origin: 'http://127.0.0.1:8000' }, { realtime: true }]) {
    assert.equal(matchesPreviewIdentity({ ...payload, ...change }, config), false)
  }
})

test('candidate config keeps the exact exclusive cutoff string', async (context) => {
  context.mock.method(Date, 'now', () => Date.parse('2026-09-09T00:00:00Z'))
  const original = process.env.GUIYI_PREVIEW_AS_OF
  const cutoff = '2026-09-08T07:00:00.000001+00:00'
  process.env.GUIYI_PREVIEW_AS_OF = cutoff
  try {
    const { default: config } = await import('../vite.config.ts')
    const result = (config as Function)({ mode: 'candidate-preview', command: 'serve' })
    assert.equal(JSON.parse(result.define['import.meta.env.VITE_PREVIEW_AS_OF']), cutoff)
  } finally {
    if (original === undefined) delete process.env.GUIYI_PREVIEW_AS_OF
    else process.env.GUIYI_PREVIEW_AS_OF = original
  }
})

test('candidate cutoff validation rejects invalid dates and a future microsecond', async (context) => {
  context.mock.method(Date, 'now', () => Date.parse('2026-09-08T07:00:00Z'))
  const original = process.env.GUIYI_PREVIEW_AS_OF
  try {
    const { default: config } = await import('../vite.config.ts')
    for (const cutoff of ['2026-09-08T07:00:00.000001Z', '2026-02-30T07:00:00Z', '2026-09-08T07:00:00']) {
      process.env.GUIYI_PREVIEW_AS_OF = cutoff
      assert.throws(() => (config as Function)({ mode: 'candidate-preview', command: 'serve' }), /PREVIEW_CUTOFF_INVALID/)
    }
    process.env.GUIYI_PREVIEW_AS_OF = '2026-09-08T07:00:00.000000Z'
    assert.doesNotThrow(() => (config as Function)({ mode: 'candidate-preview', command: 'serve' }))
    assert.throws(() => (config as Function)({ mode: 'candidate-preview', command: 'build' }), /PREVIEW_CUTOFF_INVALID/)
  } finally {
    if (original === undefined) delete process.env.GUIYI_PREVIEW_AS_OF
    else process.env.GUIYI_PREVIEW_AS_OF = original
  }
})

test('preview identity distinguishes microseconds but accepts equivalent timezones', async () => {
  const { matchesPreviewIdentity } = await import('../src/utils/candidatePreview.ts')
  const config = { enabled: true, codeSha: 'a'.repeat(40), asOf: '2026-09-08T07:00:00.000001Z' }
  const payload = { mode: 'local_candidate_readonly', code_sha: config.codeSha,
    as_of: '2026-09-08T15:00:00.000001+08:00', realtime: false,
    candidate_origin: 'http://127.0.0.1:8010', status_origin: 'http://127.0.0.1:8000' }
  assert.equal(matchesPreviewIdentity(payload, config), true)
  for (const as_of of ['2026-09-08T07:00:00.000000Z', '2026-09-08T07:00:00.000002Z', 'invalid']) {
    assert.equal(matchesPreviewIdentity({ ...payload, as_of }, config), false)
  }
})

test('server middleware denies management before proxy and destroys API upgrades', async () => {
  const { candidatePreviewPlugin, candidatePreviewProxy } = await import('../previewProxy.ts')
  const middleware: Function[] = []
  const upgrades: Function[] = []
  const plugin = candidatePreviewPlugin()
  const configure = plugin.configureServer as Function
  configure({ middlewares: { use: (handler: Function) => middleware.push(handler) },
    httpServer: { prependListener: (_event: string, handler: Function) => upgrades.push(handler) } })
  for (const [method, url] of [['POST', '/api/runtime/health'], ['GET', '/api/alerts/rules'],
    ['GET', '/api/runtime/%68ealth'], ['GET', '/api/runtime/health/'], ['GET', '/ws/market']]) {
    let forwarded = false
    let body = ''
    const response = { statusCode: 200, setHeader() {}, end(value: string) { body = value } }
    middleware[0]!({ method, url }, response, () => { forwarded = true })
    assert.equal(forwarded, false)
    assert.equal(response.statusCode, 403)
    assert.match(body, /PREVIEW_ROUTE_FORBIDDEN/)
  }
  let forwarded = false
  middleware[0]!({ method: 'GET', url: '/api/runtime/health' }, {}, () => { forwarded = true })
  assert.equal(forwarded, true)
  let destroyed = false
  upgrades[0]!({ url: '/api/runtime/health' }, { destroy() { destroyed = true } })
  assert.equal(destroyed, true)
  const proxies = candidatePreviewProxy()
  assert.equal(Object.keys(proxies).includes('/api'), false)
  assert.equal(Object.values(proxies).every(option => option.ws === false), true)
})

test('candidate server rejects attempts to bind non-loopback', async () => {
  const { candidatePreviewPlugin } = await import('../previewProxy.ts')
  const hook = candidatePreviewPlugin().configResolved as Function
  assert.equal(typeof hook, 'function')
  assert.throws(() => hook({ server: { host: '0.0.0.0' } }), /PREVIEW_LOCAL_ONLY/)
  assert.doesNotThrow(() => hook({ server: { host: '127.0.0.1' } }))
})

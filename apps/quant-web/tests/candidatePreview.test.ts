import assert from 'node:assert/strict'
import { test } from 'node:test'
import { existsSync } from 'node:fs'

test('candidate preview policy exists as explicit isolated configuration', () => {
  assert.ok(existsSync(new URL('../previewProxy.ts', import.meta.url)))
})

test('proxy allows exact GET resources only, never encoded paths or WS', async () => {
  const { previewTarget } = await import('../previewProxy.ts')
  assert.equal(previewTarget('GET', '/api/v1/market/bars/page?symbol=rb'), 'http://127.0.0.1:8010')
  assert.equal(previewTarget('GET', '/api/v1/market/newow/product-capabilities'), 'http://127.0.0.1:8010')
  assert.equal(previewTarget('GET', '/api/v1/market/newow/daily-snapshot?product=rb&strategy=trend&frequency=1d'), 'http://127.0.0.1:8010')
  assert.equal(previewTarget('GET', '/api/v1/market/newow/weekly-snapshot?product=rb&strategy=trend&frequency=1w'), 'http://127.0.0.1:8010')
  assert.equal(previewTarget('GET', '/api/v1/market/jm/subing/reference?since=2026-08-01'), 'http://127.0.0.1:8010')
  assert.equal(previewTarget('GET', '/api/preview/identity'), 'http://127.0.0.1:8010')
  assert.equal(previewTarget('GET', '/api/runtime/health'), 'http://127.0.0.1:8000')
  assert.equal(previewTarget('GET', '/api/alerts/current-events?limit=30'), 'http://127.0.0.1:8000')
  for (const path of ['/api/runtime/health/', '/api/runtime/%68ealth', '/api/runtime/health?x=1',
    '/api/alerts/current-events?limit=31', '/api/alerts/current-events?limit=30&limit=30',
    '/api/alerts/rules', '/api/v1/market/state', '/api/v1/market/research/product',
    '/api/v1/market/JM/subing/reference', '/api/v1/market/jm-1/subing/reference',
    '/api/v1/market/jm/subing/reference/', '/api/v1/market/dominants/', '/api/v1/market/dominants%3F', '/ws/market']) {
    assert.equal(previewTarget('GET', path), null, path)
  }
  for (const method of ['POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD']) {
    assert.equal(previewTarget(method, '/api/runtime/health'), null)
  }
  assert.equal(previewTarget('GET', '/api/runtime/health', true), null)
})

test('wall-clock weekly preview matches a dynamic identity without a fixed cutoff', async (context) => {
  const { matchesPreviewIdentity } = await import('../src/utils/candidatePreview.ts')
  const config = { enabled: true, codeSha: 'a'.repeat(40), asOf: '', defaultWeekly: true }
  const payload = { mode: 'local_candidate_readonly', code_sha: config.codeSha,
    as_of: null, default_weekly: true, realtime: false,
    candidate_origin: 'http://127.0.0.1:8010', status_origin: 'http://127.0.0.1:8000' }
  assert.equal(matchesPreviewIdentity(payload, config), true)
  assert.equal(matchesPreviewIdentity({ ...payload, as_of: '2026-09-18T07:00:00Z' }, config), false)
  assert.equal(matchesPreviewIdentity({ ...payload, default_weekly: false }, config), false)
  context.mock.method(Date, 'now', () => Date.parse('2026-09-18T08:00:00Z'))
  const old = process.env.GUIYI_PREVIEW_DEFAULT_WEEKLY
  const cutoff = process.env.GUIYI_PREVIEW_AS_OF
  process.env.GUIYI_PREVIEW_DEFAULT_WEEKLY = '1'
  delete process.env.GUIYI_PREVIEW_AS_OF
  try {
    const { default: configFactory } = await import('../vite.config.ts')
    const result = (configFactory as Function)({ mode: 'candidate-preview', command: 'serve' })
    assert.equal(JSON.parse(result.define['import.meta.env.VITE_PREVIEW_DEFAULT_WEEKLY']), '1')
    assert.equal(JSON.parse(result.define['import.meta.env.VITE_PREVIEW_AS_OF']), '')
  } finally {
    if (old === undefined) delete process.env.GUIYI_PREVIEW_DEFAULT_WEEKLY
    else process.env.GUIYI_PREVIEW_DEFAULT_WEEKLY = old
    if (cutoff === undefined) delete process.env.GUIYI_PREVIEW_AS_OF
    else process.env.GUIYI_PREVIEW_AS_OF = cutoff
  }
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

test('overflow AP preview matches 8011 origin and rejects PD/PT 8010 identity', async () => {
  const { matchesPreviewIdentity, candidateOriginHost } = await import('../src/utils/candidatePreview.ts')
  const config = {
    enabled: true,
    codeSha: 'a'.repeat(40),
    asOf: '2026-09-03T08:00:00.000Z',
    candidateOrigin: 'http://127.0.0.1:8011',
  }
  const payload = {
    mode: 'local_candidate_readonly',
    code_sha: config.codeSha,
    as_of: '2026-09-03T08:00:00+00:00',
    realtime: false,
    candidate_origin: 'http://127.0.0.1:8011',
    status_origin: 'http://127.0.0.1:8000',
  }
  assert.equal(matchesPreviewIdentity(payload, config), true)
  assert.equal(matchesPreviewIdentity({ ...payload, candidate_origin: 'http://127.0.0.1:8010' }, config), false)
  assert.equal(candidateOriginHost(config.candidateOrigin), '127.0.0.1:8011')
  assert.equal(candidateOriginHost('http://127.0.0.1:8010'), '127.0.0.1:8010')
})

test('8011 candidate origin proxies market API to 8011 and binds 5175, not PD/PT 8010/5174', async (context) => {
  context.mock.method(Date, 'now', () => Date.parse('2026-09-18T00:00:00Z'))
  const originalAsOf = process.env.GUIYI_PREVIEW_AS_OF
  const originalOrigin = process.env.GUIYI_PREVIEW_CANDIDATE_ORIGIN
  process.env.GUIYI_PREVIEW_AS_OF = '2026-09-17T07:00:00Z'
  process.env.GUIYI_PREVIEW_CANDIDATE_ORIGIN = 'http://127.0.0.1:8011'
  try {
    const origin = 'http://127.0.0.1:8011'
    const { previewTarget, candidatePreviewProxy, candidatePreviewWebPort } = await import('../previewProxy.ts')
    assert.equal(previewTarget('GET', '/api/preview/identity', false, origin), origin)
    assert.equal(previewTarget('GET', '/api/v1/market/newow/product-capabilities', false, origin), origin)
    assert.equal(previewTarget('GET', '/api/runtime/health', false, origin), 'http://127.0.0.1:8000')
    assert.equal(candidatePreviewProxy(origin)['^/api/(preview/identity|v1/market/)'].target, origin)
    assert.equal(candidatePreviewWebPort(origin), 5175)
    assert.equal(candidatePreviewWebPort('http://127.0.0.1:8010'), 5174)
    const { default: config } = await import('../vite.config.ts')
    const result = (config as Function)({ mode: 'candidate-preview', command: 'serve' })
    assert.equal(result.server.port, 5175)
    assert.equal(result.server.proxy['^/api/(preview/identity|v1/market/)'].target, origin)
    assert.equal(JSON.parse(result.define['import.meta.env.VITE_PREVIEW_CANDIDATE_ORIGIN']), origin)
  } finally {
    if (originalAsOf === undefined) delete process.env.GUIYI_PREVIEW_AS_OF
    else process.env.GUIYI_PREVIEW_AS_OF = originalAsOf
    if (originalOrigin === undefined) delete process.env.GUIYI_PREVIEW_CANDIDATE_ORIGIN
    else process.env.GUIYI_PREVIEW_CANDIDATE_ORIGIN = originalOrigin
  }
})

test('AP 5175 overlay reuses origin-aligned proxy and does not bind 5174', async (context) => {
  context.mock.method(Date, 'now', () => Date.parse('2026-09-18T00:00:00Z'))
  const originalAsOf = process.env.GUIYI_PREVIEW_AS_OF
  const originalOrigin = process.env.GUIYI_PREVIEW_CANDIDATE_ORIGIN
  process.env.GUIYI_PREVIEW_AS_OF = '2026-09-17T07:00:00Z'
  delete process.env.GUIYI_PREVIEW_CANDIDATE_ORIGIN
  try {
    const { default: overlay } = await import('../vite.ap5175.config.ts')
    const result = (overlay as Function)({ mode: 'candidate-preview', command: 'serve' })
    assert.equal(result.server.port, 5175)
    assert.equal(result.server.host, '127.0.0.1')
    assert.equal(result.server.proxy['^/api/(preview/identity|v1/market/)'].target, 'http://127.0.0.1:8011')
    assert.equal(JSON.parse(result.define['import.meta.env.VITE_PREVIEW_CANDIDATE_ORIGIN']), 'http://127.0.0.1:8011')
  } finally {
    if (originalAsOf === undefined) delete process.env.GUIYI_PREVIEW_AS_OF
    else process.env.GUIYI_PREVIEW_AS_OF = originalAsOf
    if (originalOrigin === undefined) delete process.env.GUIYI_PREVIEW_CANDIDATE_ORIGIN
    else process.env.GUIYI_PREVIEW_CANDIDATE_ORIGIN = originalOrigin
  }
})

test('8011 candidate plugin refuses to share PD/PT web port 5174', async () => {
  const { candidatePreviewPlugin } = await import('../previewProxy.ts')
  const hook = candidatePreviewPlugin('http://127.0.0.1:8011').configResolved as Function
  assert.throws(() => hook({ server: { host: '127.0.0.1', port: 5174 } }), /PREVIEW_OVERFLOW_PORT_REQUIRED/)
  assert.doesNotThrow(() => hook({ server: { host: '127.0.0.1', port: 5175 } }))
  const defaultHook = candidatePreviewPlugin('http://127.0.0.1:8010').configResolved as Function
  assert.doesNotThrow(() => defaultHook({ server: { host: '127.0.0.1', port: 5174 } }))
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

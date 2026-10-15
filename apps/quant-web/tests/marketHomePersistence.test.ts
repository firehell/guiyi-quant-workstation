import assert from 'node:assert/strict'
import test from 'node:test'
import { createHomeSnapshotCache, indexedHomeStorage, type HomeSnapshot } from '../src/utils/marketHomePersistence.ts'
import { useMarketHome } from '../src/composables/useMarketHome.ts'

test('restore discards invalid and expired data, bounds products and bytes, and preserves resources', async () => {
  let saved: HomeSnapshot[] = []
  const cache = createHomeSnapshotCache({ read: async () => [null, { key: 'overview', savedAt: 0, value: 'expired' }, { key: 'directory', savedAt: NaN, value: [] }], write: async values => { saved = values } }, { now: () => 1000, maxProducts: 2, maxBytes: 350, maxAgeMs: 100 })
  await cache.restore()
  assert.equal(cache.stats().entries, 0)
  await cache.put('overview', { data: 'accepted' })
  for (const product of ['rb', 'cu', 'ag']) await cache.put(`card:${product}`, { state: 'HOLD' })
  assert.equal(cache.peek('card:rb'), undefined)
  assert.equal(cache.stats().entries, 3)
  await cache.put('card:au', 'x'.repeat(500))
  assert.equal(cache.peek('card:au'), undefined)
  assert.ok(cache.stats().bytes <= 350)
  assert.equal(saved.length, 3)
})

test('IDB unavailable and failed writes degrade to bounded memory without failing page reads', async () => {
  const cache = createHomeSnapshotCache(indexedHomeStorage('unavailable-test', undefined))
  await cache.put('overview', { ok: true })
  assert.deepEqual(cache.peek('overview')?.value, { ok: true })
  assert.equal(cache.stats().persistent, false)
  const quota = createHomeSnapshotCache({ read: async () => [], write: async () => { throw new Error('quota') } })
  await quota.put('directory', ['rb'])
  assert.deepEqual(quota.peek('directory')?.value, ['rb'])
  assert.equal(quota.stats().persistent, false)
})

test('detail disk bookkeeping can release memory and directory metadata expires at 24 hours', async () => {
  const now = 2 * 86400_000
  const cache = createHomeSnapshotCache({ read: async () => [
    { key: 'directory', savedAt: 0, value: ['old'] },
    { key: 'price:jm', savedAt: now, value: { prices: [1] } },
  ], write: async () => {} }, { now: () => now, acceptsKey: key => key === 'directory' || key.startsWith('price:') })
  await cache.restore()
  assert.equal(cache.peek('directory'), undefined)
  assert.deepEqual(cache.peek('price:jm')?.value, { prices: [1] })
  await cache.releaseMemory()
  assert.equal(cache.stats().bytes, 0)
})

test('restored overview shows before revalidation and fails stale while Runtime remains independent', async () => {
  const cache = createHomeSnapshotCache({ read: async () => [{ key: 'overview', savedAt: Date.now(), value: 'display' }], write: async () => {} })
  let reject!: (reason: Error) => void
  let runtimeCalls = 0
  const home = useMarketHome({ persistence: cache, validateOverview: value => { if (typeof value !== 'string') throw Error(); return value }, fetchOverview: () => new Promise<string>((_resolve, fail) => { reject = fail }), fetchDirectory: async () => [], fetchRuntime: async () => { runtimeCalls++; return 'runtime' } })
  await home.restore()
  assert.equal(home.overview.data.value, 'display')
  assert.equal(home.overview.stale.value, true)
  const refresh = home.refreshAll()
  for (let i = 0; i < 8; i++) await Promise.resolve()
  assert.equal(home.overview.loading.value, true)
  assert.equal(runtimeCalls, 1)
  reject(new Error('offline')); await refresh
  assert.equal(home.overview.data.value, 'display')
  assert.equal(home.overview.stale.value, true)
  assert.equal(cache.peek('runtime'), undefined)
  home.dispose()
})

test('corrupt persisted overview is discarded through its domain validator', async () => {
  const cache = createHomeSnapshotCache({ read: async () => [{ key: 'overview', savedAt: Date.now(), value: { corrupt: true } }], write: async () => {} })
  const home = useMarketHome({ persistence: cache, validateOverview: () => { throw Error('invalid') }, fetchOverview: async () => 'fresh', fetchDirectory: async () => [], fetchRuntime: async () => null })
  await home.restore()
  assert.equal(home.overview.data.value, null)
  assert.equal(cache.peek('overview'), undefined)
  await home.refreshOverview()
  assert.equal(home.overview.data.value, 'fresh')
  home.dispose()
})


test('actual normalized overview round-trips through persistence without relaxing Decimal HTTP validation', async () => {
  const { normalizeMarketHomeOverviewResponse, validateStoredMarketHomeOverview } = await import('../src/utils/marketHomeTypes.ts')
  const { lightHomeOverview } = await import('../e2e/fixtures/market-home-light.mjs')
  const wire = lightHomeOverview()
  const normalized = normalizeMarketHomeOverviewResponse(wire)
  assert.deepEqual(validateStoredMarketHomeOverview(normalized), normalized)
  assert.throws(() => normalizeMarketHomeOverviewResponse(normalized), /Decimal string/)
  assert.throws(() => validateStoredMarketHomeOverview({ ...normalized, items: [{ close: Infinity }] }))
})


test('hung storage read falls back within bounded time and cannot block network recovery', async () => {
  const cache = createHomeSnapshotCache({ read: () => new Promise(() => {}), write: async () => {} }, { storageTimeoutMs: 10 })
  let calls = 0
  const home = useMarketHome({ persistence: cache, validateOverview: value => String(value), fetchOverview: async () => { calls++; return 'network' }, fetchDirectory: async () => [], fetchRuntime: async () => null })
  await home.refreshAll()
  assert.equal(calls, 1)
  assert.equal(home.overview.data.value, 'network')
  assert.equal(cache.stats().persistent, false)
  home.dispose()
})

test('snapshot read publishes before a hanging prune write completes', async () => {
  const cache = createHomeSnapshotCache({ read: async () => [{ key: 'overview', savedAt: Date.now(), value: 'display' }], write: () => new Promise(() => {}) }, { storageTimeoutMs: 10 })
  await cache.restore()
  assert.equal(cache.peek('overview')?.value, 'display')
  await new Promise(resolve => setTimeout(resolve, 20))
  assert.equal(cache.stats().persistent, false)
  await cache.put('directory', ['rb'])
  assert.deepEqual(cache.peek('directory')?.value, ['rb'])
})

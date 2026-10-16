import assert from 'node:assert/strict'
import test from 'node:test'
import { homeCardSessionKey, homeCardsReloadIdentity, createHomeCardLoader, normalizeHomeCards, type CardDelivery, type HomeCardsResponse } from '../src/utils/newowHomeCards.ts'
import { marketHomeUnifiedProductChartQuery } from '../src/utils/marketHomeRoutes.ts'

const response = (products: string[]): HomeCardsResponse => ({ schema_version: 'newow_home_cards_v2', requested_at: '2026-10-09T00:00:00Z', items: products.map(product => ({ product, strategies: { trend: { '1d': { status: 'warming', state: null }, '1w': { status: 'unavailable', state: null } }, oscillation: { '1d': { status: 'warming', state: null }, '1w': { status: 'warming', state: null } } } })) })
const tick = () => new Promise<void>(resolve => setImmediate(resolve))

test('returning home publishes later cached cards before expired earlier products finish', async () => {
  let items: Record<string, CardDelivery> = {}
  const pending: Array<{ product: string; resolve: (value: HomeCardsResponse) => void }> = []
  const loader = createHomeCardLoader((products) => new Promise(resolve => pending.push({ product: products[0]!, resolve })), value => { items = value }, product => product === 'al' ? response(['al']) : undefined)
  const loading = loader.load(['a', 'ag', 'al'])
  assert.equal(items.al!.loading, false)
  assert.equal(items.al!.stale, false)
  assert.ok(items.al!.card)
  assert.deepEqual(pending.map(item => item.product), ['a', 'ag'])
  for (const item of pending) item.resolve(response([item.product]))
  await loading
  assert.equal(pending.length, 2)
  loader.dispose()
})

test('60 cards load in bounded batches and no more than two concurrent requests', async () => {
  let active = 0, maximum = 0
  const sizes: number[] = []
  let items: Record<string, CardDelivery> = {}
  const loader = createHomeCardLoader(async products => {
    active++; maximum = Math.max(maximum, active); sizes.push(products.length)
    await tick(); active--
    return response(products)
  }, value => { items = value })
  await loader.load(Array.from({ length: 60 }, (_, i) => `p${i}`))
  assert.equal(maximum, 2)
  assert.deepEqual(sizes, Array(60).fill(1))
  assert.equal(Object.values(items).filter(item => item.card && !item.loading).length, 60)
})

test('a failed refresh retains a labelled old snapshot and recovery clears stale', async () => {
  let fail = false
  let items: Record<string, CardDelivery> = {}
  const loader = createHomeCardLoader(async products => { if (fail) throw Error('offline'); return response(products) }, value => { items = value })
  await loader.load(['rb']); const old = items.rb!.card
  fail = true; await loader.load(['rb'])
  assert.equal(items.rb!.card, old); assert.equal(items.rb!.stale, true); assert.equal(items.rb!.failed, true)
  fail = false; await loader.load(['rb'])
  assert.equal(items.rb!.stale, false); assert.equal(items.rb!.failed, false)
})

test('late responses cannot overwrite a changed authority and obsolete batches stop', async () => {
  const pending: Array<{ products: string[]; signal: AbortSignal; resolve: (value: HomeCardsResponse) => void }> = []
  let items: Record<string, CardDelivery> = {}
  const loader = createHomeCardLoader((products, signal) => new Promise(resolve => pending.push({ products, signal, resolve })), value => { items = value })
  const old = loader.load(Array.from({ length: 36 }, (_, i) => `p${i}`))
  const latest = loader.load(['rb'])
  assert.equal(pending[0]!.signal.aborted, true)
  pending[2]!.resolve(response(['rb'])); await latest
  pending[0]!.resolve(response(pending[0]!.products)); pending[1]!.resolve(response(pending[1]!.products)); await old
  assert.deepEqual(Object.keys(items), ['rb']); assert.equal(pending.length, 3)
  loader.dispose()
})

test('reject incomplete or foreign snapshots and keep unavailable periods independent', () => {
  assert.equal(normalizeHomeCards(response(['rb']), ['rb']).items[0]!.strategies.trend['1w'].status, 'unavailable')
  assert.throws(() => normalizeHomeCards(response(['ag']), ['rb']))
  const invalid = response(['rb']); invalid.items[0]!.strategies.trend['1d'] = { status: 'ready', state: 'HOLD' }
  assert.throws(() => normalizeHomeCards(invalid, ['rb']))
})

test('card chart route preserves independent strategy and weekly period', () => {
  const query = marketHomeUnifiedProductChartQuery('rb', '1w', 'oscillation')
  assert.equal(query.strategy, 'oscillation'); assert.equal(query.frequency, '1w'); assert.equal(query.series_kind, 'actual_dominant')
})


test('unchanged overview readback does not cancel the bounded strategy queue', () => {
  const data = { target_as_of: '2026-10-09', items: [{ symbol: 'rb', actual_contract: 'RB2701', close: 3080 }, { symbol: 'ag', actual_contract: 'AG2612', close: 14717 }] }
  assert.equal(homeCardsReloadIdentity(data), homeCardsReloadIdentity({ ...data, items: [...data.items].reverse() }))
  assert.notEqual(homeCardsReloadIdentity(data), homeCardsReloadIdentity({ ...data, items: [{ ...data.items[0]!, actual_contract: 'RB2705' }, data.items[1]!] }))
  assert.notEqual(homeCardsReloadIdentity(data), homeCardsReloadIdentity({ ...data, target_as_of: '2026-10-12' }))
})


test('persisted display cards publish stale first and must reacquire a network owner', async () => {
  let items: Record<string, CardDelivery> = {}
  let complete!: (value: HomeCardsResponse) => void
  let reads = 0
  const loader = createHomeCardLoader(() => { reads++; return new Promise(resolve => { complete = resolve }) }, value => { items = value }, () => ({ ...response(['rb']), restored: true }))
  const pending = loader.load(['rb'])
  assert.ok(items.rb!.card)
  assert.equal(items.rb!.stale, true)
  assert.equal(items.rb!.loading, true)
  assert.equal(reads, 1)
  complete(response(['rb'])); await pending
  assert.equal(items.rb!.stale, false)
  loader.dispose()
})

test('selective refresh leaves unaffected cards and old contents visible and rejects late owners', async () => {
  let items: Record<string, CardDelivery> = {}, phase = false
  const pending: Array<(value: HomeCardsResponse) => void> = []
  const calls: string[] = []
  const loader = createHomeCardLoader(products => { calls.push(products[0]!); return phase ? new Promise(resolve => pending.push(resolve)) : Promise.resolve(response(products)) }, value => { items = value })
  await loader.load(['rb', 'cu'])
  const cu = items.cu!.card, rb = items.rb!.card
  phase = true
  const old = loader.reloadProduct('rb'), fresh = loader.reloadProduct('rb')
  assert.equal(items.cu!.card, cu)
  assert.equal(items.rb!.card, rb)
  assert.equal(items.rb!.stale, true)
  const current = { ...response(['rb']), requested_at: '2026-10-14T00:00:00Z' }
  pending[1]!(current); await fresh
  const owner = items.rb!.card
  pending[0]!(response(['rb'])); await old
  assert.equal(items.rb!.card, owner)
  assert.deepEqual(calls, ['rb', 'cu', 'rb', 'rb'])
  loader.dispose()
})


test('a previously hidden product cannot reuse a fresh card alias from another authority', async () => {
  const { createSessionResources } = await import('../src/utils/newowSessionResources.ts')
  const cache = createSessionResources()
  const first = homeCardSessionKey(['rb'], 'contract-generation-one')
  const second = homeCardSessionKey(['rb'], 'contract-generation-two')
  cache.put(first, response(['rb']), 'one')
  assert.ok(cache.peek(first))
  assert.equal(cache.peek(second), undefined)
  let reads = 0
  await cache.load(second, async () => { reads++; return response(['rb']) }, () => 'two')
  assert.equal(reads, 1)
  assert.ok(cache.peek(second))
})

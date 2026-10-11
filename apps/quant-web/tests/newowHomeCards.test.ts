import assert from 'node:assert/strict'
import test from 'node:test'
import { createHomeCardLoader, normalizeHomeCards, type CardDelivery, type HomeCardsResponse } from '../src/utils/newowHomeCards.ts'
import { marketHomeUnifiedProductChartQuery } from '../src/utils/marketHomeRoutes.ts'

const response = (products: string[]): HomeCardsResponse => ({ schema_version: 'newow_home_cards_v1', requested_at: '2026-10-09T00:00:00Z', items: products.map(product => ({ product, strategies: { trend: { '1d': { status: 'warming', state: null }, '1w': { status: 'unavailable', state: null } }, oscillation: { '1d': { status: 'warming', state: null }, '1w': { status: 'warming', state: null } } } })) })
const tick = () => new Promise<void>(resolve => setImmediate(resolve))

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

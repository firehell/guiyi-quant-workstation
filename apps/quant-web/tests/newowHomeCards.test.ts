import assert from 'node:assert/strict'
import test from 'node:test'
import { homeCardsReloadIdentity, normalizeHomeCards, type CardDelivery, type HomeCardsResponse } from '../src/utils/newowHomeCards.ts'
import { marketHomeUnifiedProductChartQuery } from '../src/utils/marketHomeRoutes.ts'

const response = (products: string[]): HomeCardsResponse => ({ schema_version: 'newow_home_cards_v2', requested_at: '2026-10-09T00:00:00Z', items: products.map(product => ({ product, strategies: { trend: { '1d': { status: 'warming', state: null }, '1w': { status: 'unavailable', state: null } }, oscillation: { '1d': { status: 'warming', state: null }, '1w': { status: 'warming', state: null } } } })) })
const tick = () => new Promise<void>(resolve => setImmediate(resolve))

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

import assert from 'node:assert/strict'
import test from 'node:test'
import { buildMarketHomeViewModel, formatMarketHomeNumber } from '../src/utils/marketHomeViewModel.ts'

function item(symbol: string, daily_trend: 'up' | 'down' | 'neutral' | 'unavailable', weekly_trend: 'up' | 'down' | 'neutral' | 'unavailable') {
  const price_change_1d = daily_trend === 'up' ? 0.01 : daily_trend === 'down' ? -0.01 : daily_trend === 'neutral' ? 0 : null
  return { symbol, product_name: symbol, sector: 'black', exchange: 'DCE', actual_contract: `${symbol.toUpperCase()}2601`, dominant_mapping_date: '2026-09-02', data_as_of: '2026-09-02', close: 100, price_change_1d, price_change_5d: null, volume_ratio20: null, oi_change_1d: null, atr14_percentile252: null, daily_trend, weekly_trend, reason_codes: [] }
}
function overview(items = [item('ag', 'up', 'up')], overrides: Record<string, unknown> = {}) {
  return { status: 'ready' as const, target_as_of: '2026-09-02', data_as_of: '2026-09-02', freshness: 'fresh' as const, active_count: items.length, participant_count: items.length, stale_count: 0, unavailable_count: 0, summary: { price_up_count: 1, price_down_count: 0, price_flat_count: 0, price_unavailable_count: 0, daily_up_count: 1, daily_down_count: 0, daily_neutral_count: 0, daily_unavailable_count: 0, aligned_up_count: 1, aligned_down_count: 0 }, items, sectors: [], ...overrides }
}
const runtime = { status: 'degraded', generated_at: '2026-09-02T01:00:00Z' }

test('maps D1 and W1 only into the approved alignment states', () => {
  const value = buildMarketHomeViewModel({ overview: overview([item('a', 'up', 'up'), item('b', 'down', 'down'), item('c', 'neutral', 'neutral'), item('d', 'up', 'down'), item('e', 'up', 'unavailable')]), overviewStale: false, runtime, runtimeStale: false })
  assert.deepEqual(value.rows.map((row) => row.alignment), ['aligned-up', 'aligned-down', 'neutral', 'mixed', 'unavailable'])
  assert.equal(value.runtime.status, 'degraded')
  assert.equal(formatMarketHomeNumber(null), '—')
})

test('keeps overview and Runtime authority independent while stale facts override colored row states', () => {
  const value = buildMarketHomeViewModel({ overview: overview(), overviewStale: true, runtime: null, runtimeStale: false })
  assert.equal(value.overview.availability, 'ready')
  assert.equal(value.overview.cachedStale, true)
  assert.equal(value.rows[0]!.dailyState, 'unavailable')
  assert.equal(value.runtime.availability, 'unavailable')
})

test('server-degraded overview is current transport data but withholds stale row facts', () => {
  const value = buildMarketHomeViewModel({ overview: overview([item('ag', 'up', 'up')], { status: 'degraded', freshness: 'stale' }), overviewStale: false, runtime, runtimeStale: false })
  assert.equal(value.overview.availability, 'degraded')
  assert.equal(value.overview.cachedStale, false)
  assert.equal(value.rows[0]!.alignment, 'unavailable')
})

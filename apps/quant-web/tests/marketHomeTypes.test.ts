import assert from 'node:assert/strict'
import test from 'node:test'
import {
  normalizeMarketHomeOverviewResponse,
  normalizeCurrentHtdyEventsResponse,
} from '../src/utils/marketHomeTypes.ts'

const overview = {
  status: 'ready',
  target_as_of: '2026-09-02',
  data_as_of: '2026-09-02',
  freshness: 'fresh',
  active_count: 2,
  participant_count: 2,
  stale_count: 0,
  unavailable_count: 0,
  summary: {
    price_up_count: 1,
    price_down_count: 1,
    price_flat_count: 0,
    daily_up_count: 1,
    daily_down_count: 1,
    daily_neutral_count: 0,
    daily_unavailable_count: 0,
    aligned_up_count: 1,
    aligned_down_count: 1,
  },
  items: [
    {
      symbol: 'ag', product_name: '白银', sector: 'precious', exchange: 'SHFE',
      actual_contract: 'AG2610', dominant_mapping_date: '2026-09-02', data_as_of: '2026-09-02',
      close: '8123.5', price_change_1d: '0.0125', price_change_5d: null,
      volume_ratio20: '1.2', oi_change_1d: null, atr14_percentile252: '0.35',
      daily_trend: 'up', weekly_trend: 'up', reason_codes: ['price_up', 'daily_up'],
    },
    {
      symbol: 'jm', product_name: '焦煤', sector: 'black', exchange: 'DCE',
      actual_contract: 'JM2601', dominant_mapping_date: '2026-09-02', data_as_of: '2026-09-02',
      close: '1100', price_change_1d: '-0.02', price_change_5d: '0',
      volume_ratio20: null, oi_change_1d: '0', atr14_percentile252: null,
      daily_trend: 'down', weekly_trend: 'down', reason_codes: ['price_down', 'daily_down'],
    },
  ],
  sectors: [
    { sector: 'precious', active_count: 1, participant_count: 1, median_price_change_1d: '0.0125' },
    { sector: 'black', active_count: 1, participant_count: 1, median_price_change_1d: '-0.02' },
  ],
}

const currentEvents = {
  status: 'ready',
  trading_day: '2026-09-02',
  items: [{
    id: 7, rule_code: 'htdy_original_15m', symbol: 'ag', contract: 'AG2610',
    trading_day: '2026-09-02', frequency: '15m', bar_end: '2026-09-02T02:45:00Z',
    result_codes: ['buy'], detected_at: '2026-09-02T02:45:01Z', notification_attempted_at: null,
  }],
}

test('normalizes finite Decimal strings and preserves null market home metrics', () => {
  const value = normalizeMarketHomeOverviewResponse(overview)

  assert.equal(value.items[0]!.close, 8123.5)
  assert.equal(value.items[0]!.price_change_1d, 0.0125)
  assert.equal(value.items[0]!.price_change_5d, null)
  assert.equal(value.items[1]!.volume_ratio20, null)
  assert.equal(value.sectors[0]!.median_price_change_1d, 0.0125)
})

test('fails closed for malformed market home authority facts', () => {
  const invalidCases: unknown[] = [
    { ...overview, active_count: -1 },
    { ...overview, participant_count: 1 },
    { ...overview, items: [overview.items[0], { ...overview.items[1], symbol: 'ag' }] },
    { ...overview, items: [{ ...overview.items[0], close: 'Infinity' }, overview.items[1]] },
    { ...overview, items: [{ ...overview.items[0], daily_trend: 'buy' }, overview.items[1]] },
    { ...overview, target_as_of: '2026-02-30' },
  ]

  for (const payload of invalidCases) {
    assert.throws(() => normalizeMarketHomeOverviewResponse(payload))
  }
})

test('fails closed for overview status, date, and per-sector fact disagreements', () => {
  const degradedStale = {
    ...structuredClone(overview),
    status: 'degraded',
    freshness: 'stale',
    active_count: 3,
    stale_count: 1,
    sectors: [
      { ...overview.sectors[0], active_count: 2 },
      { ...overview.sectors[1], active_count: 1 },
    ],
  }
  const invalidCases: unknown[] = [
    { ...degradedStale, status: 'ready', freshness: 'fresh' },
    { ...overview, status: 'degraded' },
    { ...overview, target_as_of: '2026-09-01' },
    {
      ...degradedStale,
      sectors: [
        { ...degradedStale.sectors[0], active_count: 1, participant_count: 0 },
        { ...degradedStale.sectors[1], active_count: 2, participant_count: 2 },
      ],
    },
  ]

  for (const payload of invalidCases) {
    assert.throws(() => normalizeMarketHomeOverviewResponse(payload))
  }
})

test('fails closed when summary bins disagree with the returned item facts', () => {
  const invalidCases: unknown[] = [
    { ...overview, summary: { ...overview.summary, price_up_count: 0, price_down_count: 2 } },
    { ...overview, summary: { ...overview.summary, daily_up_count: 0, daily_down_count: 2 } },
    { ...overview, summary: { ...overview.summary, aligned_up_count: 0, aligned_down_count: 2 } },
  ]

  for (const payload of invalidCases) {
    assert.throws(() => normalizeMarketHomeOverviewResponse(payload))
  }
})

test('fails closed when a completed D1 close is null', () => {
  const payload = structuredClone(overview)
  payload.items[0].close = null
  assert.throws(() => normalizeMarketHomeOverviewResponse(payload), /close must be a Decimal string/)
})

test('distinguishes ready HTDY events from an unavailable current-event projection', () => {
  const ready = normalizeCurrentHtdyEventsResponse(currentEvents)
  const unavailable = normalizeCurrentHtdyEventsResponse({ status: 'unavailable', trading_day: null, items: [] })

  assert.equal(ready.status, 'ready')
  assert.deepEqual(ready.items[0]!.result_codes, ['buy'])
  assert.equal(unavailable.status, 'unavailable')
  assert.equal(unavailable.trading_day, null)
})

test('fails closed for a calendar-invalid HTDY instant that Date.parse would normalize', () => {
  const payload = structuredClone(currentEvents)
  payload.items[0].bar_end = '2026-02-30T01:00:00Z'
  assert.throws(() => normalizeCurrentHtdyEventsResponse(payload), /bar_end/)
})

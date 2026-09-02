import assert from 'node:assert/strict'
import test from 'node:test'

import { buildMarketHomeViewModel, formatMarketHomeNumber } from '../src/utils/marketHomeViewModel.ts'

function overview(items = [item('ag', 'up', 'up'), item('jm', 'down', 'down')], overrides: Record<string, unknown> = {}) {
  return {
    status: 'ready' as const,
    target_as_of: '2026-09-02', data_as_of: '2026-09-02', freshness: 'fresh' as const,
    active_count: items.length, participant_count: items.length, stale_count: 0, unavailable_count: 0,
    summary: { price_up_count: 1, price_down_count: 1, price_flat_count: 0, daily_up_count: 1, daily_down_count: 1, daily_neutral_count: 0, daily_unavailable_count: 0, aligned_up_count: 1, aligned_down_count: 1 },
    items,
    sectors: [{ sector: 'black', active_count: items.length, participant_count: items.length, median_price_change_1d: 0.01 }],
    ...overrides,
  }
}

function item(symbol: string, dailyTrend: 'up' | 'down' | 'neutral' | 'unavailable', weeklyTrend: 'up' | 'down' | 'neutral' | 'unavailable') {
  return { symbol, product_name: symbol, sector: 'black', exchange: 'DCE', actual_contract: `${symbol.toUpperCase()}2601`, dominant_mapping_date: '2026-09-02', data_as_of: '2026-09-02', close: 100, price_change_1d: null, price_change_5d: null, volume_ratio20: null, oi_change_1d: null, atr14_percentile252: null, daily_trend: dailyTrend, weekly_trend: weeklyTrend, reason_codes: [] }
}

const runtime = { status: 'degraded', generated_at: '2026-09-02T01:00:00Z' }

test('maps D1 and W1 only into the approved alignment states', () => {
  const value = buildMarketHomeViewModel({
    overview: overview([item('a', 'up', 'up'), item('b', 'down', 'down'), item('c', 'neutral', 'neutral'), item('d', 'up', 'down'), item('e', 'up', 'unavailable')]),
    overviewStale: false, runtime, runtimeStale: false,
    events: { status: 'ready', trading_day: '2026-09-02', items: [] }, eventsStale: false,
  })

  assert.deepEqual(value.rows.map((row) => row.alignment), ['aligned-up', 'aligned-down', 'neutral', 'mixed', 'unavailable'])
  assert.equal(value.events.availability, 'empty')
  assert.equal(value.runtime.status, 'degraded')
})

test('keeps overview, Runtime, and Event authority independent while stale facts override colored row states', () => {
  const value = buildMarketHomeViewModel({
    overview: overview([item('ag', 'up', 'up')]), overviewStale: true,
    runtime: null, runtimeStale: false,
    events: { status: 'unavailable', trading_day: null, items: [] }, eventsStale: false,
  })

  assert.equal(value.overview.availability, 'ready')
  assert.equal(value.overview.cachedStale, true)
  assert.equal(value.rows[0]!.dailyState, 'unavailable')
  assert.equal(value.runtime.availability, 'unavailable')
  assert.equal(value.events.availability, 'unavailable')
})

test('joins the latest immutable Event by exact symbol without inferring Event silence', () => {
  const value = buildMarketHomeViewModel({
    overview: overview(), overviewStale: false, runtime, runtimeStale: false,
    events: {
      status: 'ready', trading_day: '2026-09-02',
      items: [
        event(1, 'ag', '2026-09-02T01:00:00Z'),
        event(2, 'ag', '2026-09-02T02:00:00Z'),
      ],
    },
    eventsStale: false,
  })

  assert.equal(value.rows[0]!.event?.id, 2)
  assert.equal(value.rows[1]!.event, null)
  assert.equal(formatMarketHomeNumber(null), '—')
  assert.throws(() => buildMarketHomeViewModel({
    overview: overview(), overviewStale: false, runtime, runtimeStale: false,
    events: { status: 'ready', trading_day: '2026-09-02', items: [event(1, 'ag', '2026-09-02T01:00:00Z'), event(3, 'ag', '2026-09-02T01:00:00Z')] }, eventsStale: false,
  }))
})

test('allows two Rules at the same formal Bar and keeps the latest row Event deterministic', () => {
  const htdy = event(1, 'ag', '2026-09-02T01:00:00Z')
  const subing = {
    ...event(2, 'ag', '2026-09-02T01:00:01Z'),
    rule_code: 'subing_ths_alert_15m_v1' as const,
    result_codes: ['sell'] as ['sell'],
    bar_end: htdy.bar_end,
  } as never
  const value = buildMarketHomeViewModel({
    overview: overview(), overviewStale: false, runtime, runtimeStale: false,
    events: { status: 'ready', trading_day: '2026-09-02', items: [htdy, subing] }, eventsStale: false,
  })

  assert.equal(value.rows[0]!.event?.id, 2)
})

test('withholds cached Event facts from rows while the current Event projection is unavailable', () => {
  const cached = event(9, 'ag', '2026-09-02T02:00:00Z')
  const value = buildMarketHomeViewModel({
    overview: overview([item('ag', 'up', 'up')]), overviewStale: false,
    runtime, runtimeStale: false,
    events: { status: 'ready', trading_day: '2026-09-02', items: [cached] }, eventsStale: true,
  })

  assert.equal(value.events.availability, 'unavailable')
  assert.equal(value.rows[0]!.event, null)
})

test('keeps a server-degraded overview distinct from a cached client snapshot while withholding stale row facts', () => {
  const value = buildMarketHomeViewModel({
    overview: overview([item('ag', 'up', 'up')], { status: 'degraded', freshness: 'stale' }), overviewStale: false,
    runtime, runtimeStale: false,
    events: { status: 'ready', trading_day: '2026-09-02', items: [] }, eventsStale: false,
  })

  assert.equal(value.overview.availability, 'degraded')
  assert.equal(value.overview.cachedStale, false)
  assert.equal(value.rows[0]!.dailyState, 'unavailable')
  assert.equal(value.rows[0]!.weeklyState, 'unavailable')
  assert.equal(value.rows[0]!.alignment, 'unavailable')
})

function event(id: number, symbol: string, detectedAt: string) {
  return { id, rule_code: 'htdy_original_15m' as const, symbol, contract: `${symbol.toUpperCase()}2601`, trading_day: '2026-09-02', frequency: '15m' as const, bar_end: detectedAt, result_codes: ['buy'] as Array<'buy'>, detected_at: detectedAt, notification_attempted_at: null }
}

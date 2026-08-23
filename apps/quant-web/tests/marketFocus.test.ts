import assert from 'node:assert/strict'
import test from 'node:test'
import {
  normalizeMarketTrendFocus,
  type MarketTrendFocusWireItem,
  type MarketTrendFocusWireResponse,
} from '../src/types/market.ts'

function item(
  symbol: string,
  overrides: Partial<MarketTrendFocusWireItem> = {},
): MarketTrendFocusWireItem {
  return {
    symbol,
    product_name: symbol.toUpperCase(),
    sector: 'black',
    physical_contract: `${symbol.toUpperCase()}2701`,
    direction: 'long',
    stage: 'ready',
    hot_conditions: ['price_move_up', 'volume_expansion'],
    hot_count: 2,
    price_change_1d: '0.0234',
    volume_ratio20: '1.75',
    atr14_percentile252: '0.81',
    daily_volume_support: true,
    hourly_state: 'continuation',
    hourly_volume_support: false,
    range_upper: '101.25',
    range_lower: '96.5',
    confirmation_count: 3,
    retest_held: true,
    rebreak_reference: '103.5',
    ready_invalidation: '99.25',
    volume_confirmed: true,
    five_minute_confirmed: false,
    entry_confirmed_at: null,
    latest_swing_high: '103.5',
    latest_swing_low: '99.25',
    next_level: '104.75',
    invalidation_level: '101.25',
    last_transition_at: '2026-08-23T02:30:00Z',
    ...overrides,
  }
}

test('Trend Focus normalizes Decimal strings in every backend group at the HTTP boundary', () => {
  const payload: MarketTrendFocusWireResponse = {
    status: 'ready',
    observed_at: '2026-08-23T03:00:00Z',
    long_opportunities: [item('jm')],
    short_opportunities: [item('ag', { direction: 'short', stage: 'setup' })],
    running_trends: [item('au', { stage: 'running', five_minute_confirmed: true })],
    weakening_trends: [item('rb', { direction: 'short', stage: 'weakening' })],
    unavailable: [{ symbol: 'cu', code: 'HOURLY_HISTORY_INSUFFICIENT' }],
  }

  const result = normalizeMarketTrendFocus(payload)

  assert.deepEqual([
    result.long_opportunities.length,
    result.short_opportunities.length,
    result.running_trends.length,
    result.weakening_trends.length,
  ], [1, 1, 1, 1])
  assert.equal(result.long_opportunities[0].price_change_1d, 0.0234)
  assert.equal(result.short_opportunities[0].range_lower, 96.5)
  assert.equal(result.running_trends[0].rebreak_reference, 103.5)
  assert.equal(result.weakening_trends[0].invalidation_level, 101.25)
  assert.equal(result.long_opportunities[0].stage, 'ready')
  assert.equal(result.running_trends[0].five_minute_confirmed, true)
  assert.deepEqual(result.unavailable, [
    { symbol: 'cu', code: 'HOURLY_HISTORY_INSUFFICIENT' },
  ])
})

test('Trend Focus preserves null optional levels while normalizing required levels', () => {
  const payload: MarketTrendFocusWireResponse = {
    status: 'ready',
    observed_at: '2026-08-23T03:00:00Z',
    long_opportunities: [item('jm', {
      price_change_1d: null,
      volume_ratio20: null,
      atr14_percentile252: null,
      rebreak_reference: null,
      ready_invalidation: null,
      latest_swing_high: null,
      latest_swing_low: null,
      next_level: null,
      invalidation_level: null,
    })],
    short_opportunities: [],
    running_trends: [],
    weakening_trends: [],
    unavailable: [],
  }

  const [result] = normalizeMarketTrendFocus(payload).long_opportunities

  assert.equal(result.range_upper, 101.25)
  assert.equal(result.range_lower, 96.5)
  assert.equal(result.next_level, null)
  assert.equal(result.invalidation_level, null)
  assert.equal(result.latest_swing_high, null)
})

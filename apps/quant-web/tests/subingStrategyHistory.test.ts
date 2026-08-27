import assert from 'node:assert/strict'
import test from 'node:test'

import { normalizeSubingStrategyHistory } from '../src/types/market.ts'


function action(kind: string, id: string) {
  const open = kind.startsWith('open_')
  return {
    action_id: id,
    episode_id: 'subing-episode:one',
    strategy_id: 'subing_strategy_v1',
    formula_version: 'subing_strategy_15m_v1',
    kind,
    symbol: 'jm',
    contract: 'JM2609',
    trading_day: open ? '2026-08-03' : '2026-08-07',
    segment_start_trading_day: '2026-08-01',
    opportunity_id: 'subing-opportunity:one',
    decision_at: open ? '2026-08-03T02:15:00Z' : '2026-08-07T02:15:00Z',
    effective_open_at: open ? '2026-08-03T02:15:00Z' : '2026-08-07T02:15:00Z',
    effective_bar_end: open ? '2026-08-03T02:30:00Z' : '2026-08-07T02:30:00Z',
    reference_price: open ? '100.5' : '108.50985',
    fill_basis: 'next_bar_open',
    confirmation_source: open ? 'formal_v1' : null,
    reason_codes: open ? [] : ['EMA21', 'MACD_HIGH_DEAD_CROSS'],
    direction_context_source_day: open ? '2026-07-31' : null,
    direction_context_target_day: open ? '2026-08-03' : null,
    bound_reference_pivot: null,
  }
}

function strategyWireResponse() {
  const entry = action('open_long', 'subing-action:entry')
  const exit = action('close_long', 'subing-action:exit')
  return {
    request: {
      series_kind: 'actual_dominant', symbol: 'jm', frequency: '15m',
      since: '2026-08-07', through: '2026-08-20',
    },
    policy: {
      strategy_id: 'subing_strategy_v1', formula_version: 'subing_strategy_15m_v1',
      research_only: true, series_kind: 'actual_dominant', decision_frequency: '15m',
      lifecycle_policy_id: 'subing_lifecycle_v2_research_v1',
      allowed_confirmation_sources: [
        'formal_v1', 'momentum_hold', 'pivot_break_hold', 'pivot_retest_rebreak',
      ],
    },
    resolved_cutoff: '2026-08-20T07:00:00Z',
    segment_summaries: [{
      contract: 'JM2609', start_trading_day: '2026-08-01',
      end_trading_day: '2026-08-20', loaded_through: '2026-08-20',
      bar_count_5m: 300, bar_count_15m: 100, initial_position: 'flat',
      final_position: 'flat', terminal_bar_end: '2026-08-20T07:00:00Z',
      pending_action: false,
    }],
    actions: [exit],
    episodes: [{
      episode_id: 'subing-episode:one', direction: 'long', entry_action: entry,
      exit_action: exit, state: 'closed', holding_bar_count: 20,
      reference_change_percent: '7.97', current_reference_change_percent: null,
      latest_reference_price: null,
      exit_reason_codes: ['EMA21', 'MACD_HIGH_DEAD_CROSS'],
      structure_exit_available: false,
    }],
    context_unavailable: [],
    cache_state: 'miss',
  }
}

test('normalizes Decimal strings while preserving deterministic identities', () => {
  const normalized = normalizeSubingStrategyHistory(strategyWireResponse())

  assert.equal(normalized.actions[0].reference_price, '108.50985')
  assert.equal(normalized.episodes[0].reference_change_percent, '7.97')
  assert.equal(normalized.actions[0].action_id, 'subing-action:exit')
  assert.equal(normalized.episodes[0].entry_action.action_id, 'subing-action:entry')
})

test('preserves exact high-precision Decimal facts through the HTTP boundary', () => {
  const payload = strategyWireResponse()
  const price = '12345678901234567890.1234567890123456789'
  const entryPrice = '12345678901234567889.9999999999999999999'
  const change = '0.08100445524503847711624139328'
  const pivotPrice = '12345678901234567000.0000000000000000001'
  payload.actions[0].reference_price = price
  payload.actions[0].bound_reference_pivot = {
    pivot_id: 'pivot:exact',
    kind: 'low',
    source_timeframe: '5m',
    pivot_time: '2026-08-07T02:00:00Z',
    confirmed_at: '2026-08-07T02:10:00Z',
    price: pivotPrice,
    contract: 'JM2609',
    segment_start_trading_day: '2026-08-01',
  }
  payload.episodes[0].entry_action.reference_price = entryPrice
  payload.episodes[0].exit_action.reference_price = price
  payload.episodes[0].reference_change_percent = change

  const normalized = normalizeSubingStrategyHistory(payload)

  assert.equal(normalized.actions[0].reference_price, price)
  assert.equal(normalized.actions[0].bound_reference_pivot?.price, pivotPrice)
  assert.equal(normalized.episodes[0].entry_action.reference_price, entryPrice)
  assert.equal(normalized.episodes[0].exit_action?.reference_price, price)
  assert.equal(normalized.episodes[0].reference_change_percent, change)
})

test('rejects a nested entry whose episode identity conflicts', () => {
  const payload = strategyWireResponse()
  payload.episodes[0].entry_action.episode_id = 'subing-episode:different'

  assert.throws(
    () => normalizeSubingStrategyHistory(payload),
    /SUBING_STRATEGY_INVALID_RESPONSE/,
  )
})

test('rejects non-finite Decimal strings and an invalid policy identity', () => {
  const invalidDecimal = strategyWireResponse()
  invalidDecimal.actions[0].reference_price = 'Infinity'
  assert.throws(
    () => normalizeSubingStrategyHistory(invalidDecimal),
    /SUBING_STRATEGY_INVALID_RESPONSE/,
  )

  const invalidPolicy = strategyWireResponse()
  invalidPolicy.policy.formula_version = 'other'
  assert.throws(
    () => normalizeSubingStrategyHistory(invalidPolicy),
    /SUBING_STRATEGY_INVALID_RESPONSE/,
  )
})

test('rejects top-level Action and context identities outside the response request', () => {
  const invalidAction = strategyWireResponse()
  invalidAction.actions[0].symbol = 'ag'
  assert.throws(
    () => normalizeSubingStrategyHistory(invalidAction),
    /SUBING_STRATEGY_INVALID_RESPONSE/,
  )

  const invalidContext = strategyWireResponse()
  invalidContext.context_unavailable.push({
    symbol: 'ag', target_trading_day: '2026-08-08', source_trading_day: null,
    direction: 'unavailable', reason_codes: ['D1_UNAVAILABLE'], daily_bar_end: null,
    hourly_bar_end: null, physical_contract: null,
  })
  assert.throws(
    () => normalizeSubingStrategyHistory(invalidContext),
    /SUBING_STRATEGY_INVALID_RESPONSE/,
  )
})

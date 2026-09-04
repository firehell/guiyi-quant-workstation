import assert from 'node:assert/strict'
import test from 'node:test'
import { normalizeNewowTrendDetailResponse } from '../src/utils/newowTypes.ts'

const calculationIdentity = [
  'market_data_service:canonical_v2',
  'main_contract_map:rank1:canonical_v1',
  'rb',
  'actual_dominant',
  '1d+1w+60m',
  'newow_trend_d1_page_v2',
  'newow_trend_band_page_v2',
  'newow_escape_d123_page_v2',
  'newow_cup_handle_v1',
  'newow_oscillation_hhv_llv10_page_v1',
  'newow_main_force_control_page_v1',
  'newow_main_rise_ma35_ma45_page_v1',
  'newow_target_absorb_hhv_llv10_page_v1',
  'newow_target_absorb_display_selection_page_v2',
  'newow_hhv_llv_window_optimizer_page_v1',
  'newow_hhv_llv_window_optimizer_causal_v1',
  'newow_composite_decision_page_v3_2_82',
  'newow_composite_decision_cleanroom_v1',
  'newow_first_action_principle_page_v3_2_63',
  'newow_diagnostic_facts_cleanroom_v1',
  'newow_diagnostic_rules_cleanroom_v1',
].join('|')

const query = { symbol: 'rb', from: '2026-01-05', through: '2026-01-07' }

function marker(
  markerId: string,
  markerType: string,
  barEnd: string,
  formulaVersion: string,
  triggerFacts: Record<string, unknown> = {},
) {
  const price = formulaVersion === 'newow_trend_band_page_v2'
    ? (barEnd.includes('05') ? '10.20' : '10.30')
    : formulaVersion === 'newow_escape_d123_page_v2'
      ? '11.30'
      : (barEnd.includes('05') ? '10.50' : '11.00')
  return {
    marker_id: markerId,
    marker_type: markerType,
    bar_end: barEnd,
    price,
    label: markerType,
    color_token: 'newow-test',
    priority: 100,
    related_marker_ids: [],
    trigger_facts: triggerFacts,
    formula_version: formulaVersion,
  }
}

function basePayload() {
  return {
    meta: {
      strategy_code: 'newow_trend_v1',
      profile_id: 'newow_trend_d1_page_v2',
      frequency: '1d',
      series_kind: 'actual_dominant',
      calculation_identity: calculationIdentity,
      data_revision_identity: null,
      request_identity: `${calculationIdentity}:2026-01-05:2026-01-07`,
    },
    instrument: {
      product: 'rb',
      display_name: '螺纹钢',
      last_visible_physical_contract: 'RB2610',
    },
    bars: [
      {
        bar_end: '2026-01-05T07:00:00Z', trading_day: '2026-01-05',
        open: '10.10', high: '11.20', low: '9.90', close: '10.50',
        volume: 100, open_interest: 200, physical_contract: 'RB2605',
        segment_id: 'RB2605:2026-01-01:2026-01-06', source_identity: calculationIdentity,
      },
      {
        bar_end: '2026-01-06T07:00:00+00:00', trading_day: '2026-01-06',
        open: '10.50', high: '11.30', low: '10.20', close: '11.00',
        volume: 110, open_interest: null, physical_contract: 'RB2605',
        segment_id: 'RB2605:2026-01-01:2026-01-06', source_identity: calculationIdentity,
      },
      {
        bar_end: '2026-01-07T15:00:00+08:00', trading_day: '2026-01-07',
        open: '10.80', high: '11.40', low: '10.60', close: '11.00',
        volume: 120, open_interest: 220, physical_contract: 'RB2610',
        segment_id: 'RB2610:2026-01-07:2026-05-31', source_identity: calculationIdentity,
      },
    ],
    bar_policy: 'completed_only',
    trend_band: [
      {
        bar_end: '2026-01-05T07:00:00Z', b_value: 10.1, c_value: 10.2,
        state: 'BLUE', state_before: 'YELLOW', transition: 'CLEAR',
      },
      {
        bar_end: '2026-01-06T07:00:00+00:00', b_value: 10.4, c_value: 10.3,
        state: 'YELLOW', state_before: 'BLUE', transition: 'BUILD',
      },
      {
        bar_end: '2026-01-07T15:00:00+08:00', b_value: 10.6, c_value: 10.5,
        state: 'YELLOW', state_before: 'YELLOW', transition: null,
      },
    ],
    trend_markers: [
      { ...marker('clear-1', 'CLEAR', '2026-01-05T07:00:00Z', 'newow_trend_band_page_v2'), related_marker_ids: ['prior-build'] },
      marker('build-1', 'BUILD', '2026-01-06T07:00:00+00:00', 'newow_trend_band_page_v2'),
    ],
    escape_markers: [
      marker('d1-1', 'NEWOW_ESCAPE_D1', '2026-01-06T07:00:00+00:00', 'newow_escape_d123_page_v2', { nested: [true, { ratio: 1.25 }], price: '11.00' }),
      marker('d2-1', 'NEWOW_ESCAPE_D2', '2026-01-06T07:00:00+00:00', 'newow_escape_d123_page_v2'),
      marker('d3-1', 'NEWOW_ESCAPE_D3', '2026-01-06T07:00:00+00:00', 'newow_escape_d123_page_v2'),
    ],
    cup_markers: [
      marker('cup-ready-1', 'CUP_HANDLE_READY', '2026-01-05T07:00:00Z', 'newow_cup_handle_v1', { candidate_id: 'cup-1' }),
      marker('cup-breakout-1', 'CUP_HANDLE_BREAKOUT', '2026-01-06T07:00:00+00:00', 'newow_cup_handle_v1', { candidate_id: 'cup-1' }),
      marker('cup-weakened-1', 'CUP_HANDLE_WEAKENED', '2026-01-06T07:00:00+00:00', 'newow_cup_handle_v1', { candidate_id: 'cup-1' }),
      marker('cup-invalidated-1', 'CUP_HANDLE_INVALIDATED', '2026-01-06T07:00:00+00:00', 'newow_cup_handle_v1', { candidate_id: 'cup-1' }),
      marker('cup-expired-1', 'CUP_HANDLE_EXPIRED', '2026-01-06T07:00:00+00:00', 'newow_cup_handle_v1', { candidate_id: 'cup-1' }),
    ],
    cup_handles: [{
      candidate_id: 'cup-1', direction: 'BULLISH', state: 'BREAKOUT',
      left_rim: { pivot_at: '2025-11-03T07:00:00Z', confirmed_at: '2025-11-05T07:00:00Z', price: '12.00' },
      bottom: { pivot_at: '2025-12-01T07:00:00Z', confirmed_at: '2025-12-03T07:00:00Z', price: '8.00' },
      right_rim: { pivot_at: '2026-01-01T07:00:00Z', confirmed_at: '2026-01-02T07:00:00Z', price: '11.80' },
      handle_start_at: '2026-01-01T07:00:00Z',
      handle_extreme: { pivot_at: '2026-01-03T07:00:00Z', confirmed_at: '2026-01-04T07:00:00Z', price: '10.80' },
      pivot_price: '11.90', pivot_frozen_at: '2026-01-05T07:00:00Z',
      confirmed_at: '2026-01-05T07:00:00Z', first_seen_at: '2026-01-02T07:00:00Z',
      state_changed_at: '2026-01-06T07:00:00Z', score: 88,
      score_breakdown: { pretrend: 20, cup_geometry: 25, u_shape_purity: 15, handle_quality: 15, volume_structure: 13 },
      hard_failures: [], diagnostics: [],
      volume_facts: { right_leg_median: 100, handle_median: 70, handle_baseline_median: 90, handle_right_ratio: 0.7, handle_baseline_ratio: 0.7777777778 },
      formula_version: 'newow_cup_handle_v1',
    }],
    rollover_seams: [{
      trading_day: '2026-01-07', previous_contract: 'RB2605', next_contract: 'RB2610',
      previous_bar_end: '2026-01-06T07:00:00+00:00', next_bar_end: '2026-01-07T15:00:00+08:00',
      previous_segment_id: 'RB2605:2026-01-01:2026-01-06', next_segment_id: 'RB2610:2026-01-07:2026-05-31',
    }],
    price_channel: {
      daily: {
        frequency: '1d',
        points: [
          channelPoint('2026-01-05T07:00:00Z', null, null, false),
          channelPoint('2026-01-06T07:00:00+00:00', null, null, false),
          channelPoint('2026-01-07T15:00:00+08:00', '12.00', '9.50', true),
        ],
        owner_segment_ids: ['RB2605:2026-01-01:2026-01-06', 'RB2610:2026-01-07:2026-05-31'],
        formula_version: 'newow_target_absorb_hhv_llv10_page_v1',
      },
      weekly: {
        frequency: '1w', points: [channelPoint('2026-01-02T07:00:00Z', '13.00', '9.00', true)],
        owner_segment_ids: ['RB2605:2026-01-01:2026-01-06'],
        formula_version: 'newow_target_absorb_hhv_llv10_page_v1',
      },
      sixty_minute: {
        frequency: '60m', points: [channelPoint('2026-01-07T06:00:00Z', '11.80', '10.00', true)],
        owner_segment_ids: ['RB2610:2026-01-07:2026-05-31'],
        formula_version: 'newow_target_absorb_hhv_llv10_page_v1',
      },
      display: {
        target: '13.00', absorb: '9.00', raw_target: '13.00', raw_absorb: '9.00',
        target_period: 'week', absorb_period: 'week', target_branch_token: 'weekly_target',
        absorb_branch_token: 'weekly_absorb', formula_version: 'newow_target_absorb_display_selection_page_v2',
      },
    },
    page_window_comparison: [10, 20, 24, 30, 52].map((window, index) => ({
      window, cumulative_return_pct: String(10 - index), max_drawdown_pct: String(-5 - index),
      trade_count: 3 + index, win_rate_pct: '50', score: String(5 - index),
      terminal_position_was_open: index === 0, force_closed_at_end: true,
      execution_timing: 'same_bar_close', trustworthy_for_research: false,
      formula_version: 'newow_hhv_llv_window_optimizer_page_v1',
    })),
    composite_page: composite('newow_composite_decision_page_v3_2_82'),
    composite_cleanroom: {
      ...composite('newow_composite_decision_cleanroom_v1'),
      page_difference_reason: 'page uses same-bar close and is display parity only',
    },
    first_action_principle: {
      level: 'ok', rule_token: 'first_action_ok', fact_tokens: ['weekly_hold', 'daily_buy'],
      formula_version: 'newow_first_action_principle_page_v3_2_63',
    },
    diagnostic_facts: {
      as_of: '2026-01-07T15:00:00+08:00', target_price: '13.00', absorb_price: '9.00',
      target_distance_pct: '18.18', absorb_distance_pct: '-18.18', ema20: '10.50',
      close_vs_ema20: 'above', trend_state: 'YELLOW', trend_duration_bars: 2,
      oscillation_holding: true, main_force_status: '有庄控盘', main_rise_active: true,
      cup_state: 'BREAKOUT', weekly_signal: 'hold', daily_signal: 'buy',
      repainting_inputs_excluded: ['zigzag'],
      formula_versions: ['newow_diagnostic_facts_cleanroom_v1', 'newow_target_absorb_display_selection_page_v2'],
    },
    diagnostic_tokens: [{
      code: 'TARGET_ABOVE_CLOSE', severity: 'info', fact_keys: ['target_price'],
      formula_identities: ['newow_diagnostic_rules_cleanroom_v1'],
    }],
    semantic_labels: {
      page_parity: true, cleanroom_separated: true, observation_only: true,
      causal_research_result: false, repainting_input_used: false,
    },
    legend: { BUILD: 'trend build', CLEAR: 'trend clear', D1: 'escape D1', D2: 'escape D2', D3: 'escape D3' },
    formula_descriptions: {
      trend_band: 'newow_trend_band_page_v2', escape: 'newow_escape_d123_page_v2', cup_handle: 'newow_cup_handle_v1',
      oscillation: 'newow_oscillation_hhv_llv10_page_v1', main_force: 'newow_main_force_control_page_v1',
      main_rise: 'newow_main_rise_ma35_ma45_page_v1', price_channel: 'newow_target_absorb_hhv_llv10_page_v1',
      display_selection: 'newow_target_absorb_display_selection_page_v2',
      page_window_comparison: 'newow_hhv_llv_window_optimizer_page_v1',
      causal_window_identity: 'newow_hhv_llv_window_optimizer_causal_v1',
      composite_page: 'newow_composite_decision_page_v3_2_82',
      composite_cleanroom: 'newow_composite_decision_cleanroom_v1',
      first_action: 'newow_first_action_principle_page_v3_2_63',
      diagnostic_facts: 'newow_diagnostic_facts_cleanroom_v1',
      diagnostic_rules: 'newow_diagnostic_rules_cleanroom_v1',
    },
    warnings: [],
  }
}

const payload = basePayload

export function completeNewowPayload() {
  const value = basePayload()
  const extension = Array.from({ length: 18 }, (_, offset) => {
    const day = `2026-01-${String(offset + 8).padStart(2, '0')}`
    const close = 11 + (offset + 1) / 10
    return {
      bar_end: `${day}T07:00:00Z`, trading_day: day,
      open: (close - 0.1).toFixed(2), high: (close + 0.3).toFixed(2),
      low: (close - 0.3).toFixed(2), close: close.toFixed(2),
      volume: 121 + offset, open_interest: 221 + offset, physical_contract: 'RB2610',
      segment_id: 'RB2610:2026-01-07:2026-05-31', source_identity: calculationIdentity,
    }
  })
  value.bars.push(...extension)
  value.trend_band.push(...extension.map(bar => ({
    bar_end: bar.bar_end, b_value: Number(bar.close) - 0.1, c_value: Number(bar.close) - 0.2,
    state: 'YELLOW', state_before: 'YELLOW', transition: null,
  })))
  value.price_channel.daily.points.push(...extension.map(bar => channelPoint(
    bar.bar_end, (Number(bar.high) + 0.5).toFixed(2), (Number(bar.low) - 0.5).toFixed(2), true,
  )))
  value.meta.request_identity = `${calculationIdentity}:2026-01-05:2026-01-25`
  value.diagnostic_facts.as_of = extension.at(-1)!.bar_end
  return value
}

function channelPoint(barEnd: string, target: string | null, absorb: string | null, available: boolean) {
  return { bar_end: barEnd, target, absorb, window: 10, available, formula_version: 'newow_target_absorb_hhv_llv10_page_v1' }
}

function composite(formulaVersion: string) {
  return {
    trend_bias: 'bullish', oscillation_bias: 'bullish', direction_token: 'multiperiod_bullish',
    decision_key: 'bullish-bullish', action_token: 'BUILD_OR_ADD',
    position_range: { minimum: '0.70', maximum: '1.00' },
    certainty: { trend: 20, oscillation: 20, alignment: 20, direction: 20, total: 80 },
    volatility: { value_pct: '1.25', level: 'mid', sample_size: 20 }, risk_tokens: [],
    ...(formulaVersion === 'newow_composite_decision_page_v3_2_82'
      ? { unreachable_decision_keys: ['warning-bullish', 'warning-bearish', 'warning-neutral'] }
      : {}),
    formula_version: formulaVersion,
  }
}

function rejects(mutator: (value: ReturnType<typeof payload>) => void, pattern?: RegExp): void {
  const value = payload()
  mutator(value)
  assert.throws(() => normalizeNewowTrendDetailResponse(value, query), pattern)
}

test('normalizes the exact Newow wire and returns a detached deep-readonly snapshot', () => {
  const raw = payload()
  const value = normalizeNewowTrendDetailResponse(raw, query)

  assert.equal(value.bars[0]!.open, 10.1)
  assert.equal(value.bars[1]!.open_interest, null)
  assert.equal(value.trend_markers[0]!.price, 10.2)
  assert.equal(value.cup_handles[0]!.pivot_price, 11.9)
  assert.equal(value.cup_handles[0]!.left_rim.price, 12)
  assert.deepEqual(value.escape_markers[0]!.trigger_facts, { nested: [true, { ratio: 1.25 }], price: '11.00' })
  assert.ok(Object.isFrozen(value))
  assert.ok(Object.isFrozen(value.bars))
  assert.ok(Object.isFrozen(value.escape_markers[0]!.trigger_facts))
  assert.ok(Object.isFrozen((value.escape_markers[0]!.trigger_facts.nested as readonly unknown[])[1]))

  raw.bars[0]!.close = '999'
  raw.escape_markers[0]!.trigger_facts.nested = []
  assert.equal(value.bars[0]!.close, 10.5)
  assert.deepEqual(value.escape_markers[0]!.trigger_facts.nested, [true, { ratio: 1.25 }])
  assert.throws(() => (value.bars as unknown[]).push({}))
})

test('normalizes the complete 21-bar fixture used by the bounded detail contract', () => {
  const value = normalizeNewowTrendDetailResponse(
    completeNewowPayload(),
    { symbol: 'rb', from: '2026-01-05', through: '2026-01-25' },
  )
  assert.equal(value.bars.length, 21)
  assert.equal(value.price_channel.daily.points.length, 21)
  assert.equal(value.diagnostic_facts.as_of, value.bars.at(-1)!.bar_end)
})

test('accepts the page-v2 identity and validates band/high marker prices', () => {
  const raw = payload()

  const value = normalizeNewowTrendDetailResponse(raw, query)

  assert.equal(value.meta.profile_id, 'newow_trend_d1_page_v2')
  assert.deepEqual(value.trend_markers.map((marker) => marker.price), [10.2, 10.3])
  assert.deepEqual(value.escape_markers.map((marker) => marker.price), [11.3, 11.3, 11.3])
})

test('normalizes finite Decimal exponent strings without accepting JSON numbers as Decimal wire values', () => {
  const raw = payload()
  raw.bars[0]!.open = '1E+1'
  assert.equal(normalizeNewowTrendDetailResponse(raw, query).bars[0]!.open, 10)

  rejects((value) => { value.bars[0]!.open = 10 as unknown as string }, /Decimal string/)
})

test('fails closed instead of collapsing a more precise Decimal string into the same chart number', () => {
  rejects((value) => { value.bars[0]!.open = '10.1000000000000001' }, /precision/)
})

test('fails closed on identity, exact-field, and completed-only violations', () => {
  rejects((value) => Object.assign(value, { unexpected: true }), /unexpected/)
  rejects((value) => Object.assign(value.meta, { unexpected: true }), /unexpected/)
  rejects((value) => { value.meta.strategy_code = 'other' })
  rejects((value) => { value.meta.profile_id = 'other' })
  rejects((value) => { value.meta.frequency = '15m' })
  rejects((value) => { value.meta.series_kind = 'continuous' })
  rejects((value) => { value.meta.calculation_identity = 'calculation' })
  rejects((value) => { value.meta.request_identity = 'request' })
  rejects((value) => { value.instrument.product = 'ag' })
  rejects((value) => { value.bar_policy = 'preview' })
  rejects((value) => { value.formula_descriptions.escape = 'other' })
  rejects((value) => { value.legend.D1 = 'other' })
})

test('fails closed on malformed, out-of-window, unordered, or inconsistent visible bars', () => {
  rejects((value) => { value.bars[0]!.bar_end = '2026-01-05T07:00:00' }, /timezone/)
  rejects((value) => { value.bars[0]!.trading_day = '2026-02-30' })
  rejects((value) => { value.bars[0]!.trading_day = '2026-01-04' })
  rejects((value) => { value.bars[1]!.trading_day = '2026-01-05' })
  rejects((value) => { [value.bars[0], value.bars[1]] = [value.bars[1]!, value.bars[0]!] })
  rejects((value) => { value.bars[0]!.low = '11.30' }, /OHLC/)
  rejects((value) => { value.bars[0]!.volume = -1 })
  rejects((value) => { value.bars[0]!.open_interest = 1.5 })
  rejects((value) => { value.bars[0]!.physical_contract = 'rb2605' })
  rejects((value) => { value.bars[0]!.source_identity = 'other' })
  rejects((value) => { value.instrument.last_visible_physical_contract = 'RB2605' })
})

test('fails closed when trend bands do not align exactly with bars and transitions', () => {
  rejects((value) => { value.trend_band.pop() })
  rejects((value) => { value.trend_band[0]!.bar_end = value.bars[1]!.bar_end })
  rejects((value) => { value.trend_band[0]!.state = 'GREEN' })
  rejects((value) => { value.trend_band[0]!.b_value = Number.NaN })
  rejects((value) => { value.trend_band[0]!.transition = 'BUILD' })
  rejects((value) => { value.trend_markers.shift() })
})

test('accepts a suppressed CLEAR when the prior BUILD was never formally eligible', () => {
  const raw = payload()
  raw.trend_band[0]!.transition = null
  raw.trend_markers.shift()

  const value = normalizeNewowTrendDetailResponse(raw, query)

  assert.equal(value.trend_band[0]!.state_before, 'YELLOW')
  assert.equal(value.trend_band[0]!.state, 'BLUE')
  assert.equal(value.trend_band[0]!.transition, null)
  assert.deepEqual(value.trend_markers.map((item) => item.marker_type), ['BUILD'])
})

test('requires BUILD and its marker when the trend changes from BLUE to YELLOW', () => {
  rejects((value) => {
    value.trend_band[1]!.transition = null
    value.trend_markers.splice(1, 1)
  }, /transition/)
})

test('fails closed on marker family, global identity, visible reference, and JSON facts violations', () => {
  rejects((value) => { value.trend_markers[0]!.marker_type = 'NEWOW_ESCAPE_D1' })
  rejects((value) => { value.escape_markers[0]!.marker_type = 'BUILD' })
  rejects((value) => { value.cup_markers[0]!.marker_type = 'CUP_UNKNOWN' })
  rejects((value) => { value.escape_markers[0]!.marker_id = value.trend_markers[0]!.marker_id })
  rejects((value) => { value.escape_markers[0]!.bar_end = '2026-01-04T07:00:00Z' })
  rejects((value) => { value.escape_markers[0]!.price = '12.00' })
  rejects((value) => { value.escape_markers[0]!.formula_version = 'other' })
  rejects((value) => { value.escape_markers[0]!.trigger_facts = { bad: Number.POSITIVE_INFINITY } })
  rejects((value) => { value.escape_markers[0]!.trigger_facts = { bad: undefined } })
})

test('fails closed on invalid cup identity, chronology, state requirements, score, and maps', () => {
  rejects((value) => { value.cup_handles.push(structuredClone(value.cup_handles[0]!)) })
  rejects((value) => { value.cup_handles[0]!.direction = 'SIDEWAYS' })
  rejects((value) => { value.cup_handles[0]!.state = 'NONE' })
  rejects((value) => { value.cup_handles[0]!.bottom.pivot_at = '2025-10-01T07:00:00Z' })
  rejects((value) => { value.cup_handles[0]!.handle_start_at = '2026-01-02T07:00:00Z' })
  rejects((value) => { value.cup_handles[0]!.pivot_price = null })
  rejects((value) => { value.cup_handles[0]!.score = 101 })
  rejects((value) => { value.cup_handles[0]!.score_breakdown.pretrend = 19 })
  rejects((value) => { Object.assign(value.cup_handles[0]!.score_breakdown, { unknown: 1 }) })
  rejects((value) => { delete value.cup_handles[0]!.volume_facts.handle_median })
  rejects((value) => { value.cup_handles[0]!.hard_failures.push('bad') })
  rejects((value) => { value.cup_handles[0]!.formula_version = 'other' })
})

test('rejects Cup facts that are unmatched or cross a visible rollover segment', () => {
  rejects((value) => {
    value.cup_handles[0]!.right_rim.pivot_at = value.bars[1]!.bar_end
    value.cup_handles[0]!.right_rim.confirmed_at = value.bars[1]!.bar_end
    value.cup_handles[0]!.handle_start_at = value.bars[1]!.bar_end
    value.cup_handles[0]!.handle_extreme!.pivot_at = value.bars[2]!.bar_end
    value.cup_handles[0]!.handle_extreme!.confirmed_at = value.bars[2]!.bar_end
    value.cup_handles[0]!.pivot_frozen_at = value.bars[2]!.bar_end
    value.cup_handles[0]!.confirmed_at = value.bars[2]!.bar_end
    value.cup_handles[0]!.first_seen_at = value.bars[1]!.bar_end
    value.cup_handles[0]!.state_changed_at = value.bars[2]!.bar_end
  }, /segment/)
  rejects((value) => {
    value.cup_markers[4]!.bar_end = value.bars[2]!.bar_end
  }, /segment/)
  rejects((value) => {
    value.cup_handles[0]!.state_changed_at = '2026-01-06T08:00:00Z'
  }, /bar_end/)
})

test('accepts the backend FORMING shape with five score keys and later first-seen time', () => {
  const raw = payload()
  const cup = raw.cup_handles[0]!
  cup.state = 'FORMING'
  cup.handle_extreme = null
  cup.pivot_price = null
  cup.pivot_frozen_at = null
  cup.confirmed_at = cup.right_rim.confirmed_at
  cup.first_seen_at = raw.bars[0]!.bar_end
  cup.state_changed_at = cup.first_seen_at
  cup.score = 60
  cup.score_breakdown = {
    pretrend: 15,
    cup_geometry: 25,
    u_shape_purity: 20,
    handle_quality: 0,
    volume_structure: 0,
  }
  cup.volume_facts = {}
  raw.cup_markers = []

  const value = normalizeNewowTrendDetailResponse(raw, query)
  assert.equal(value.cup_handles[0]!.state, 'FORMING')
  assert.equal(value.cup_handles[0]!.pivot_price, null)
  assert.deepEqual(value.cup_handles[0]!.score_breakdown, cup.score_breakdown)

  cup.score = 61
  cup.score_breakdown.handle_quality = 1
  assert.throws(() => normalizeNewowTrendDetailResponse(raw, query), /FORMING/)
})

test('fails closed on missing, extra, unordered, or contradictory rollover seams', () => {
  rejects((value) => { value.rollover_seams = [] })
  rejects((value) => { value.rollover_seams[0]!.trading_day = '2026-01-06' })
  rejects((value) => { value.rollover_seams[0]!.previous_contract = 'RB2610' })
  rejects((value) => { value.rollover_seams[0]!.next_bar_end = value.rollover_seams[0]!.previous_bar_end })
})

test('accepts only unique known warnings and binds the composite warning to unavailable composites', () => {
  rejects((value) => { value.warnings = ['UNKNOWN'] })
  rejects((value) => { value.warnings = ['NEWOW_CUP_WARMUP_INSUFFICIENT', 'NEWOW_CUP_WARMUP_INSUFFICIENT'] })

  const raw = payload()
  raw.composite_page = null as unknown as ReturnType<typeof composite>
  raw.composite_cleanroom = null as unknown as ReturnType<typeof composite> & { page_difference_reason: string }
  raw.warnings = ['NEWOW_COMPOSITE_DAILY_BARS_INSUFFICIENT']

  const value = normalizeNewowTrendDetailResponse(raw, query)
  assert.equal(value.composite_page, null)
  assert.equal(value.composite_cleanroom, null)
  assert.deepEqual(value.warnings, raw.warnings)
})

test('fails closed on multi-period channel, page-return trust, composite, diagnostic, and semantic drift', () => {
  rejects((value) => { value.price_channel.daily.points.pop() }, /align exactly/)
  rejects((value) => { value.price_channel.weekly.frequency = '1d' }, /frequency/)
  rejects((value) => { value.price_channel.display.target = 'NaN' }, /Decimal/)
  rejects((value) => { value.page_window_comparison[0]!.trustworthy_for_research = true }, /must be false/)
  rejects((value) => { value.page_window_comparison.pop() }, /exact five/)
  rejects((value) => { value.composite_page!.decision_key = 'bearish-bullish' }, /contradicts/)
  rejects((value) => { value.composite_page!.position_range.minimum = '1.10' }, /position_range/)
  rejects((value) => { value.composite_page!.unreachable_decision_keys.reverse() }, /frozen page matrix/)
  rejects((value) => { value.diagnostic_facts.target_price = '12.00' }, /display facts/)
  rejects((value) => { value.diagnostic_tokens[0]!.formula_identities = ['unknown'] }, /unknown lineage/)
  rejects((value) => { value.semantic_labels.causal_research_result = true }, /trust boundary/)
  rejects((value) => { delete value.semantic_labels.observation_only }, /missing/)
})

test('accepts the frozen 60 and 85 point certainty caps', () => {
  const conflict = payload()
  conflict.composite_page!.certainty = {
    trend: 30, oscillation: 18, alignment: 0, direction: 20, total: 60,
  }
  assert.equal(
    normalizeNewowTrendDetailResponse(conflict, query).composite_page!.certainty.total,
    60,
  )

  const neutral = payload()
  neutral.composite_cleanroom!.certainty = {
    trend: 30, oscillation: 30, alignment: 10, direction: 20, total: 85,
  }
  assert.equal(
    normalizeNewowTrendDetailResponse(neutral, query).composite_cleanroom!.certainty.total,
    85,
  )
})

import assert from 'node:assert/strict'
import test from 'node:test'

import type { MarketDetailHeaderModel, MarketDetailIdentity } from '../src/types/marketDetail.ts'
import type {
  NewowCupHandle,
  NewowMarker,
  NewowTrendBandPoint,
  NewowTrendDetailResponse,
} from '../src/types/newow.ts'
import { buildNewowDetailViewModel, newowMarkerHistory } from '../src/utils/newowViewModel.ts'

const identity: MarketDetailIdentity = {
  view: 'trend', symbol: 'rb', seriesKind: 'actual_dominant', frequency: '1d',
}

test('maps only the latest completed trend-band fact to the four engine-state labels', () => {
  const cases: Array<{
    latest: Pick<NewowTrendBandPoint, 'state' | 'transition'>
    expected: string
  }> = [
    { latest: { state: 'YELLOW', transition: 'BUILD' }, expected: '建仓' },
    { latest: { state: 'YELLOW', transition: null }, expected: '持有' },
    { latest: { state: 'BLUE', transition: 'CLEAR' }, expected: '清仓' },
    { latest: { state: 'BLUE', transition: null }, expected: '空仓' },
    { latest: { state: 'UNAVAILABLE', transition: null }, expected: '不可用' },
  ]

  for (const item of cases) {
    const data = snapshot()
    data.trend_band[2] = { ...data.trend_band[2]!, ...item.latest }
    const model = buildNewowDetailViewModel({ identity, header: header(), data })
    assert.equal(model.facts[0].value, item.expected)
  }
})

test('uses only latest-bar D markers with D1 priority while retaining every same-bar D fact in history', () => {
  const data = snapshot()
  data.escape_markers = [
    marker('older-d1', 'NEWOW_ESCAPE_D1', data.bars[1]!.bar_end, 'newow_escape_d123_page_v2'),
    marker('latest-d3', 'NEWOW_ESCAPE_D3', data.bars[2]!.bar_end, 'newow_escape_d123_page_v2'),
    marker('latest-d2', 'NEWOW_ESCAPE_D2', data.bars[2]!.bar_end, 'newow_escape_d123_page_v2'),
    marker('latest-d1', 'NEWOW_ESCAPE_D1', data.bars[2]!.bar_end, 'newow_escape_d123_page_v2'),
  ]

  const model = buildNewowDetailViewModel({ identity, header: header(), data })

  assert.equal(model.facts[1].value, 'D1')
  assert.deepEqual(
    model.history.filter((item) => item.barEnd === data.bars[2]!.bar_end).map((item) => item.markerType),
    ['NEWOW_ESCAPE_D1', 'NEWOW_ESCAPE_D2', 'NEWOW_ESCAPE_D3'],
  )
})

test('selects current cup by newest state change and then ascending candidate id', () => {
  const data = snapshot()
  data.cup_handles = [
    cup('z-latest', 'BREAKOUT', '2026-01-07T07:00:00Z'),
    cup('a-latest', 'READY', '2026-01-07T07:00:00Z'),
    cup('newer-input-order', 'EXPIRED', '2026-01-06T07:00:00Z'),
  ]

  const model = buildNewowDetailViewModel({ identity, header: header(), data })

  assert.equal(model.facts[2].value, '就绪')
})

test('discloses exact trend, D, Cup, contract, rollover, and warning evidence from the normalized snapshot', () => {
  const data = snapshot()
  data.trend_band[0] = {
    ...data.trend_band[0]!, state: 'YELLOW', state_before: 'BLUE', transition: 'BUILD',
  }
  data.trend_band[1] = {
    ...data.trend_band[1]!, state: 'BLUE', state_before: 'YELLOW', transition: 'CLEAR',
  }
  data.trend_band[2] = {
    ...data.trend_band[2]!, state: 'YELLOW', state_before: 'YELLOW', transition: null,
  }
  data.escape_markers = [
    marker('older-d1', 'NEWOW_ESCAPE_D1', data.bars[1]!.bar_end, 'newow_escape_d123_page_v2'),
    marker('current-d3', 'NEWOW_ESCAPE_D3', data.bars[2]!.bar_end, 'newow_escape_d123_page_v2'),
    marker('current-d2', 'NEWOW_ESCAPE_D2', data.bars[2]!.bar_end, 'newow_escape_d123_page_v2'),
  ]
  data.cup_handles = [cup('cup-exact', 'BREAKOUT', '2026-01-07T07:00:00Z')]
  data.rollover_seams = [{
    trading_day: '2026-01-07', previous_contract: 'RB2605', next_contract: 'RB2610',
    previous_bar_end: '2026-01-06T07:00:00Z', next_bar_end: '2026-01-07T07:00:00Z',
    previous_segment_id: 'segment-1', next_segment_id: 'segment-2',
  }]

  const model = buildNewowDetailViewModel({ identity, header: header(), data })

  assert.deepEqual(sectionValues(model, 'newow-trend'), {
    当前策略状态: '持有',
    当前趋势带: 'YELLOW',
    最近转换: 'CLEAR',
    转换时间: '2026-01-06T07:00:00Z',
    当前物理合约: 'RB2610',
    '分析截至 completed D1': '2026-01-07T07:00:00Z',
  })
  assert.deepEqual(sectionValues(model, 'newow-risk-shape'), {
    '当前 Bar D Markers': 'NEWOW_ESCAPE_D2 / NEWOW_ESCAPE_D3',
    '当前 D Bar': '2026-01-07T07:00:00Z',
    '最近历史 D Marker': 'NEWOW_ESCAPE_D2',
    '最近历史 D Bar': '2026-01-07T07:00:00Z',
    '杯柄 Candidate': 'cup-exact',
    杯柄方向: 'BULLISH',
    杯柄当前状态: 'BREAKOUT · 突破',
    'L 左杯沿': '{"pivot_at":"2025-11-01T07:00:00Z","confirmed_at":"2025-11-02T07:00:00Z","price":12}',
    'B 杯底': '{"pivot_at":"2025-12-01T07:00:00Z","confirmed_at":"2025-12-02T07:00:00Z","price":8}',
    'R 右杯沿': '{"pivot_at":"2026-01-01T07:00:00Z","confirmed_at":"2026-01-02T07:00:00Z","price":11.8}',
    'H 柄起点': '2026-01-01T07:00:00Z',
    'H 柄极值': '{"pivot_at":"2026-01-03T07:00:00Z","confirmed_at":"2026-01-04T07:00:00Z","price":10.8}',
    'P 枢轴': '{"pivot_frozen_at":"2026-01-05T07:00:00Z","price":11.9}',
    confirmed_at: '2026-01-05T07:00:00Z',
    first_seen_at: '2026-01-03T07:00:00Z',
    state_changed_at: '2026-01-07T07:00:00Z',
    score: '80',
    score_breakdown: '{"pretrend":20,"cup_geometry":20,"u_shape_purity":15,"handle_quality":15,"volume_structure":10}',
    volume_facts: '{"right_leg_median":100,"handle_median":70,"handle_baseline_median":90,"handle_right_ratio":0.7,"handle_baseline_ratio":0.78}',
  })
  assert.deepEqual(sectionValues(model, 'newow-data'), {
    序列: '真实主力',
    当前合约: 'RB2610',
    '当前 Segment': 'segment-2',
    最近换月: '{"trading_day":"2026-01-07","previous_contract":"RB2605","next_contract":"RB2610","previous_bar_end":"2026-01-06T07:00:00Z","next_bar_end":"2026-01-07T07:00:00Z","previous_segment_id":"segment-1","next_segment_id":"segment-2"}',
    warnings: '[]',
    数据覆盖: '2026-01-05 至 2026-01-07',
    共享行情状态: '正常',
  })
})

test('fails each current family closed on its warmup warning and exposes no projected history without valid data', () => {
  const data = snapshot()
  data.escape_markers = [
    marker('old-d1', 'NEWOW_ESCAPE_D1', data.bars[1]!.bar_end, 'newow_escape_d123_page_v2'),
  ]
  data.cup_handles = [cup('old-cup', 'BREAKOUT', data.bars[1]!.bar_end)]
  data.warnings = [
    'NEWOW_TREND_WARMUP_INSUFFICIENT',
    'NEWOW_D123_WARMUP_INSUFFICIENT',
    'NEWOW_CUP_WARMUP_INSUFFICIENT',
  ]
  const warned = buildNewowDetailViewModel({ identity, header: header(), data })
  const unavailable = buildNewowDetailViewModel({ identity, header: header(), data: null })

  assert.deepEqual(warned.facts.map((fact) => [fact.value, fact.tone]), [
    ['不可用', 'unavailable'],
    ['不可用', 'unavailable'],
    ['不可用', 'unavailable'],
  ])
  assert.equal(sectionValues(warned, 'newow-risk-shape')['当前 Bar D Markers'], '不可用')
  assert.equal(sectionValues(warned, 'newow-risk-shape')['杯柄 Candidate'], '不可用')
  assert.equal(sectionValues(warned, 'newow-risk-shape')['杯柄当前状态'], '不可用')
  assert.equal(sectionValues(warned, 'newow-data').warnings, '["NEWOW_TREND_WARMUP_INSUFFICIENT","NEWOW_D123_WARMUP_INSUFFICIENT","NEWOW_CUP_WARMUP_INSUFFICIENT"]')
  assert.deepEqual(unavailable.facts.map((fact) => fact.value), ['不可用', '不可用', '不可用'])
  assert.deepEqual(unavailable.history, [])
  assert.equal(unavailable.dataStatus, 'unavailable')
})

test('projects all Newow marker families newest first with family order, historical contract, and display metadata', () => {
  const data = snapshot()
  data.trend_markers = [
    marker('old-clear', 'CLEAR', data.bars[0]!.bar_end, 'newow_trend_band_page_v2'),
    marker('latest-build', 'BUILD', data.bars[2]!.bar_end, 'newow_trend_band_page_v2'),
  ]
  data.escape_markers = [
    marker('latest-d2', 'NEWOW_ESCAPE_D2', data.bars[2]!.bar_end, 'newow_escape_d123_page_v2'),
  ]
  data.cup_markers = [
    marker('middle-cup', 'CUP_HANDLE_READY', data.bars[1]!.bar_end, 'newow_cup_handle_v1'),
    marker('latest-cup', 'CUP_HANDLE_BREAKOUT', data.bars[2]!.bar_end, 'newow_cup_handle_v1'),
  ]

  const history = newowMarkerHistory(data)

  assert.deepEqual(history.map((item) => item.id), [
    'newow-marker:latest-build',
    'newow-marker:latest-d2',
    'newow-marker:latest-cup',
    'newow-marker:middle-cup',
    'newow-marker:old-clear',
  ])
  assert.deepEqual(history.map((item) => item.contract), [
    'RB2610', 'RB2610', 'RB2610', 'RB2605', 'RB2605',
  ])
  assert.deepEqual(
    history.map((item) => [item.markerType, item.formulaVersion]),
    [
      ['BUILD', 'newow_trend_band_page_v2'],
      ['NEWOW_ESCAPE_D2', 'newow_escape_d123_page_v2'],
      ['CUP_HANDLE_BREAKOUT', 'newow_cup_handle_v1'],
      ['CUP_HANDLE_READY', 'newow_cup_handle_v1'],
      ['CLEAR', 'newow_trend_band_page_v2'],
    ],
  )
  for (const item of history) {
    assert.equal(item.source, 'newow')
    assert.equal(item.occurredAt, item.barEnd)
    assert.equal(Object.hasOwn(item, 'notificationAttemptedAt'), false)
    assert.equal(Object.hasOwn(item, 'alertRuleCode'), false)
    assert.equal(Object.hasOwn(item, 'delivery'), false)
  }
})

test('keeps same-bar Cup markers in the frozen lifecycle order instead of marker-id order', () => {
  const data = snapshot()
  data.cup_markers = [
    marker('a-expired', 'CUP_HANDLE_EXPIRED', data.bars[2]!.bar_end, 'newow_cup_handle_v1'),
    marker('b-invalidated', 'CUP_HANDLE_INVALIDATED', data.bars[2]!.bar_end, 'newow_cup_handle_v1'),
    marker('c-weakened', 'CUP_HANDLE_WEAKENED', data.bars[2]!.bar_end, 'newow_cup_handle_v1'),
    marker('d-breakout', 'CUP_HANDLE_BREAKOUT', data.bars[2]!.bar_end, 'newow_cup_handle_v1'),
    marker('z-ready', 'CUP_HANDLE_READY', data.bars[2]!.bar_end, 'newow_cup_handle_v1'),
  ]

  assert.deepEqual(
    newowMarkerHistory(data).map((item) => item.markerType),
    [
      'CUP_HANDLE_READY',
      'CUP_HANDLE_BREAKOUT',
      'CUP_HANDLE_WEAKENED',
      'CUP_HANDLE_INVALIDATED',
      'CUP_HANDLE_EXPIRED',
    ],
  )
})

test('fails closed on a stale snapshot identity instead of projecting strategy facts', () => {
  const data = snapshot()
  data.instrument = { ...data.instrument, product: 'ag' }

  const model = buildNewowDetailViewModel({ identity, header: header(), data })

  assert.deepEqual(model.facts.map((fact) => fact.value), ['不可用', '不可用', '不可用'])
  assert.deepEqual(model.history, [])
  assert.equal(model.dataStatus, 'unavailable')
})

test('projects multi-period channels, page parity, clean-room decisions, and diagnostics without recalculation', () => {
  const model = buildNewowDetailViewModel({ identity, header: header(), data: snapshot() })

  assert.deepEqual(sectionValues(model, 'newow-channel'), {
    页面目标价: '12', 页面吸纳价: '9', 目标周期: 'week', 吸纳周期: 'week',
    目标分支: 'weekly_target', 吸纳分支: 'weekly_absorb',
    '日线 owner segments': '["segment-1","segment-2"]',
    '周线 owner segments': '["segment-2"]', '60m owner segments': '["segment-2"]',
  })
  const compositeRows = sectionValues(model, 'newow-composite')
  assert.equal(compositeRows.页面复刻动作, 'BUILD_OR_ADD')
  assert.equal(compositeRows['页面回放可信研究'], '否（同 Bar 收盘，仅用于页面复刻）')
  assert.equal(compositeRows['Clean-room 动作'], 'BUILD_OR_ADD')
  assert.equal(compositeRows.差异原因, 'causal timing')
  const diagnostics = sectionValues(model, 'newow-diagnostics')
  assert.equal(diagnostics.主力控盘, '有庄控盘')
  assert.equal(diagnostics.主升浪, '是')
  assert.equal(diagnostics['周/日信号'], 'hold / buy')
})

function header(): MarketDetailHeaderModel {
  return {
    symbol: 'rb', productName: '螺纹钢', exchange: 'SHFE', sector: '黑色',
    seriesKind: 'actual_dominant', displayContract: 'RB2610', asOf: '2026-01-07T07:00:00Z',
    open: 10, high: 12, low: 9, close: 11, change: 1, pct: 10,
    volume: 100, turnover: null, openInterest: 200, phase: 'CLOSED',
    displaySource: 'Canonical', freshness: 'fresh', extendedSections: [],
  }
}

function sectionValues(model: ReturnType<typeof buildNewowDetailViewModel>, id: string): Record<string, string> {
  const section = model.disclosureSections.find((item) => item.id === id)
  assert.ok(section, `missing disclosure section ${id}`)
  return Object.fromEntries(section.rows.map((row) => [row.label, row.value]))
}

function snapshot(): MutableSnapshot {
  const bars = [
    bar('2026-01-05T07:00:00Z', '2026-01-05', 'RB2605', 'segment-1'),
    bar('2026-01-06T07:00:00Z', '2026-01-06', 'RB2605', 'segment-1'),
    bar('2026-01-07T07:00:00Z', '2026-01-07', 'RB2610', 'segment-2'),
  ]
  return {
    meta: {
      strategy_code: 'newow_trend_v1', profile_id: 'newow_trend_d1_page_v2', frequency: '1d',
      series_kind: 'actual_dominant', calculation_identity: 'calculation',
      data_revision_identity: null, request_identity: 'request',
    },
    instrument: { product: 'rb', display_name: '螺纹钢', last_visible_physical_contract: 'RB2610' },
    bars,
    bar_policy: 'completed_only',
    trend_band: bars.map((item) => ({
      bar_end: item.bar_end, b_value: 10, c_value: 9, state: 'YELLOW' as const,
      state_before: 'YELLOW' as const, transition: null,
    })),
    trend_markers: [], escape_markers: [], cup_markers: [], cup_handles: [], rollover_seams: [],
    ...expandedFacts(bars),
    legend: { BUILD: 'trend build', CLEAR: 'trend clear', D1: 'escape D1', D2: 'escape D2', D3: 'escape D3' },
    formula_descriptions: {
      trend_band: 'newow_trend_band_page_v2',
      escape: 'newow_escape_d123_page_v2',
      cup_handle: 'newow_cup_handle_v1',
      oscillation: 'newow_oscillation_hhv_llv10_page_v1',
      main_force: 'newow_main_force_control_page_v1',
      main_rise: 'newow_main_rise_ma35_ma45_page_v1',
      price_channel: 'newow_target_absorb_hhv_llv10_page_v1',
      display_selection: 'newow_target_absorb_display_selection_page_v1',
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

function expandedFacts(bars: ReturnType<typeof bar>[]) {
  const channel = {
    frequency: '1d' as const,
    points: bars.map(item => ({
      bar_end: item.bar_end, target: 12, absorb: 9, window: 10 as const, available: true,
      formula_version: 'newow_target_absorb_hhv_llv10_page_v1' as const,
    })),
    owner_segment_ids: ['segment-1', 'segment-2'],
    formula_version: 'newow_target_absorb_hhv_llv10_page_v1' as const,
  }
  const common = {
    trend_bias: 'bullish' as const, oscillation_bias: 'bullish' as const,
    direction_token: 'multiperiod_bullish' as const, decision_key: 'bullish-bullish',
    action_token: 'BUILD_OR_ADD' as const, position_range: { minimum: 0.7, maximum: 1 },
    certainty: { trend: 20, oscillation: 20, alignment: 20, direction: 20, total: 80 },
    volatility: { value_pct: 1.2, level: 'mid' as const, sample_size: 20 }, risk_tokens: [],
  }
  return {
    price_channel: {
      daily: channel,
      weekly: { ...channel, frequency: '1w' as const, owner_segment_ids: ['segment-2'] },
      sixty_minute: { ...channel, frequency: '60m' as const, owner_segment_ids: ['segment-2'] },
      display: {
        target: 12, absorb: 9, raw_target: 12, raw_absorb: 9,
        target_period: 'week' as const, absorb_period: 'week' as const,
        target_branch_token: 'weekly_target', absorb_branch_token: 'weekly_absorb',
        formula_version: 'newow_target_absorb_display_selection_page_v1' as const,
      },
    },
    page_window_comparison: [10, 20, 24, 30, 52].map(window => ({
      window: window as 10 | 20 | 24 | 30 | 52, cumulative_return_pct: 1, max_drawdown_pct: -1,
      trade_count: 1, win_rate_pct: 50, score: 1, terminal_position_was_open: false,
      force_closed_at_end: true as const, execution_timing: 'same_bar_close' as const,
      trustworthy_for_research: false as const, formula_version: 'newow_hhv_llv_window_optimizer_page_v1' as const,
    })),
    composite_page: {
      ...common, unreachable_decision_keys: ['warning-bullish', 'warning-bearish', 'warning-neutral'],
      formula_version: 'newow_composite_decision_page_v3_2_82' as const,
    },
    composite_cleanroom: {
      ...common, page_difference_reason: 'causal timing',
      formula_version: 'newow_composite_decision_cleanroom_v1' as const,
    },
    first_action_principle: {
      level: 'ok' as const, rule_token: 'first_action_ok', fact_tokens: ['weekly_hold'],
      formula_version: 'newow_first_action_principle_page_v3_2_63' as const,
    },
    diagnostic_facts: {
      as_of: bars.at(-1)!.bar_end, target_price: 12, absorb_price: 9,
      target_distance_pct: 9, absorb_distance_pct: -18, ema20: 10,
      close_vs_ema20: 'above' as const, trend_state: 'YELLOW' as const, trend_duration_bars: 2,
      oscillation_holding: true, main_force_status: '有庄控盘', main_rise_active: true,
      cup_state: 'BREAKOUT' as const, weekly_signal: 'hold' as const, daily_signal: 'buy' as const,
      repainting_inputs_excluded: ['zigzag'], formula_versions: ['newow_diagnostic_facts_cleanroom_v1'],
    },
    diagnostic_tokens: [{ code: 'TARGET_ABOVE_CLOSE', severity: 'info' as const, fact_keys: ['target_price'], formula_identities: ['newow_diagnostic_rules_cleanroom_v1'] }],
    semantic_labels: { page_parity: true as const, cleanroom_separated: true as const, observation_only: true as const, causal_research_result: false as const, repainting_input_used: false as const },
  }
}

type MutableSnapshot = {
  -readonly [K in keyof NewowTrendDetailResponse]: NewowTrendDetailResponse[K] extends readonly (infer T)[]
    ? T[]
    : NewowTrendDetailResponse[K]
}

function bar(barEnd: string, tradingDay: string, physicalContract: string, segmentId: string) {
  return {
    bar_end: barEnd, trading_day: tradingDay, open: 10, high: 12, low: 9, close: 11,
    volume: 100, open_interest: 200, physical_contract: physicalContract,
    segment_id: segmentId, source_identity: 'calculation',
  }
}

function marker(
  id: string,
  type: NewowMarker['marker_type'],
  barEnd: string,
  formulaVersion: string,
): NewowMarker {
  return {
    marker_id: id, marker_type: type, bar_end: barEnd, price: 11,
    label: type, color_token: 'newow-test', priority: 100,
    related_marker_ids: [], trigger_facts: {}, formula_version: formulaVersion,
  }
}

function cup(candidateId: string, state: NewowCupHandle['state'], stateChangedAt: string): NewowCupHandle {
  return {
    candidate_id: candidateId, direction: 'BULLISH', state,
    left_rim: { pivot_at: '2025-11-01T07:00:00Z', confirmed_at: '2025-11-02T07:00:00Z', price: 12 },
    bottom: { pivot_at: '2025-12-01T07:00:00Z', confirmed_at: '2025-12-02T07:00:00Z', price: 8 },
    right_rim: { pivot_at: '2026-01-01T07:00:00Z', confirmed_at: '2026-01-02T07:00:00Z', price: 11.8 },
    handle_start_at: '2026-01-01T07:00:00Z',
    handle_extreme: { pivot_at: '2026-01-03T07:00:00Z', confirmed_at: '2026-01-04T07:00:00Z', price: 10.8 },
    pivot_price: 11.9, pivot_frozen_at: '2026-01-05T07:00:00Z',
    confirmed_at: '2026-01-05T07:00:00Z', first_seen_at: '2026-01-03T07:00:00Z',
    state_changed_at: stateChangedAt, score: 80,
    score_breakdown: { pretrend: 20, cup_geometry: 20, u_shape_purity: 15, handle_quality: 15, volume_structure: 10 },
    hard_failures: [], diagnostics: [],
    volume_facts: { right_leg_median: 100, handle_median: 70, handle_baseline_median: 90, handle_right_ratio: 0.7, handle_baseline_ratio: 0.78 },
    formula_version: 'newow_cup_handle_v1',
  }
}

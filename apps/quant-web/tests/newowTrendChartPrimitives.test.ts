import assert from 'node:assert/strict'
import test from 'node:test'

import type { BarData } from '../src/types/market.ts'
import type {
  NewowCupHandle,
  NewowMarker,
  NewowTrendDetailResponse,
} from '../src/types/newow.ts'
import {
  buildNewowTrendChartProjection,
  newowTrendPrimitiveDrawCommands,
  resolveNewowTrendCrosshairFacts,
} from '../src/components/market/detail/newowTrendChartPrimitives.ts'

test('projects API bars, non-null bands, three marker families, clipped cups, and rollover facts', () => {
  const data = snapshot()
  const fallback = [genericBar('2026-01-02', 999)]

  const projection = buildNewowTrendChartProjection({ data, genericBars: fallback })

  assert.equal(projection.source, 'newow')
  assert.equal(projection.paneCount, 2)
  assert.deepEqual(projection.bars.map((bar) => [bar.close, bar.segmentId]), [
    [11, 'segment-1'], [12, 'segment-1'], [13, 'segment-2'],
  ])
  assert.deepEqual(projection.band.b.map((point) => [point.tradingDay, point.value]), [
    ['2026-01-02', 10.5],
    ['2026-01-03', 11.5],
    ['2026-01-04', 12.5],
  ])
  assert.deepEqual(projection.band.c.map((point) => [point.tradingDay, point.value]), [
    ['2026-01-03', 10.8],
    ['2026-01-04', 11.8],
  ])
  assert.deepEqual(projection.band.areas.map((area) => area.state), ['YELLOW'])
  assert.deepEqual(projection.markers.map((marker) => [marker.family, marker.markerType, marker.id]), [
    ['trend', 'BUILD', 'build'],
    ['escape', 'NEWOW_ESCAPE_D1', 'd1'],
    ['cup', 'CUP_HANDLE_READY', 'cup-ready'],
  ])
  assert.deepEqual(projection.cups[0]!.points.map((point) => point.role), [
    'bottom', 'right-rim',
  ])
  assert.deepEqual(projection.cups[0]!.pivotLine, {
    fromTradingDay: '2026-01-03', throughTradingDay: '2026-01-03', price: 12.7,
  })
  assert.deepEqual(projection.rolloverSeams, [{
    tradingDay: '2026-01-04',
    previousContract: 'RB2605',
    nextContract: 'RB2610',
    label: 'RB2605 → RB2610 · 主力切换',
  }])

  const hover = resolveNewowTrendCrosshairFacts(projection, '2026-01-04')
  assert.equal(hover?.bar.close, 13)
  assert.equal(hover?.trend.state, 'YELLOW')
  assert.equal(hover?.trend.b, 12.5)
  assert.equal(hover?.trend.c, 11.8)
  assert.deepEqual(hover?.markerLabels, ['BUILD', 'D1', '杯柄就绪'])
  assert.deepEqual(hover?.cupStates, [{ candidateId: 'cup-1', direction: 'BULLISH', state: 'READY' }])
  assert.equal(hover?.rolloverLabel, 'RB2605 → RB2610 · 主力切换')
  assert.equal(hover?.physicalContract, 'RB2610')
})

test('uses generic completed D1 only when Newow is unavailable and discards strategy-looking extras', () => {
  const generic = Object.assign(genericBar('2026-01-08', 88), {
    trend_band: [{ b_value: 100, c_value: 90 }],
    markers: [{ marker_type: 'BUILD' }],
    cup_handles: [{ candidate_id: 'must-not-leak' }],
    rollover_seams: [{ next_contract: 'FAKE' }],
  })

  const projection = buildNewowTrendChartProjection({ data: null, genericBars: [generic] })

  assert.equal(projection.source, 'generic-fallback')
  assert.deepEqual(projection.bars, [{
    barEnd: '2026-01-08T15:00:00+08:00', tradingDay: '2026-01-08',
    open: 87, high: 89, low: 86, close: 88, volume: 108, openInterest: 208,
    physicalContract: null, segmentId: null,
  }])
  assert.deepEqual(projection.band, { b: [], c: [], areas: [] })
  assert.deepEqual(projection.markers, [])
  assert.deepEqual(projection.cups, [])
  assert.deepEqual(projection.rolloverSeams, [])
  assert.equal(projection.unavailableDisclosure, 'Newow 趋势数据不可用，仅显示 completed D1 K 线与成交量。')
  const hover = resolveNewowTrendCrosshairFacts(projection, '2026-01-08')
  assert.equal(hover?.trend, null)
  assert.deepEqual(hover?.markerLabels, [])
  assert.deepEqual(hover?.cupStates, [])
  assert.equal(hover?.rolloverLabel, null)
})

test('turns projected API facts into primitive commands without inventing clipped geometry', () => {
  const projection = buildNewowTrendChartProjection({ data: snapshot(), genericBars: [] })
  const x = new Map([
    ['2026-01-02', 10], ['2026-01-03', 20], ['2026-01-04', 30],
  ])
  const commands = newowTrendPrimitiveDrawCommands(
    projection,
    (day) => x.get(day) ?? null,
    (price) => price * 10,
  )

  assert.equal(commands.filter((command) => command.kind === 'band').length, 1)
  assert.deepEqual(
    commands.filter((command) => command.kind === 'cup-segment').map((command) => [command.fromX, command.toX]),
    [[10, 20]],
  )
  assert.equal(commands.filter((command) => command.kind === 'cup-pivot').length, 1)
  assert.equal(
    commands.filter((command) => command.kind === 'cup-segment' || command.kind === 'cup-pivot')
      .some((command) => command.fromX > 20 || command.toX > 20),
    false,
  )
  assert.deepEqual(
    commands.filter((command) => command.kind === 'rollover').map((command) => [command.fromX, command.label]),
    [[30, 'RB2605 → RB2610 · 主力切换']],
  )
})

test('keeps same-day Cup markers in frozen lifecycle order despite adversarial ids', () => {
  const data = snapshot()
  const barEnd = data.bars[2]!.bar_end
  data.cup_markers = [
    marker('a-expired', 'CUP_HANDLE_EXPIRED', barEnd, 13, '过期'),
    marker('b-invalidated', 'CUP_HANDLE_INVALIDATED', barEnd, 13, '失效'),
    marker('c-weakened', 'CUP_HANDLE_WEAKENED', barEnd, 13, '走弱'),
    marker('d-breakout', 'CUP_HANDLE_BREAKOUT', barEnd, 13, '突破'),
    marker('z-ready', 'CUP_HANDLE_READY', barEnd, 13, '就绪'),
  ]

  const projection = buildNewowTrendChartProjection({ data, genericBars: [] })

  assert.deepEqual(
    projection.markers.filter((item) => item.family === 'cup').map((item) => item.markerType),
    [
      'CUP_HANDLE_READY',
      'CUP_HANDLE_BREAKOUT',
      'CUP_HANDLE_WEAKENED',
      'CUP_HANDLE_INVALIDATED',
      'CUP_HANDLE_EXPIRED',
    ],
  )
})

function genericBar(day: string, close: number): BarData {
  return {
    time: `${day}T15:00:00+08:00`, trading_day: day,
    open: close - 1, high: close + 1, low: close - 2, close,
    volume: close + 20, openInterest: close + 120,
  }
}

function snapshot(): NewowTrendDetailResponse {
  const bars = [
    apiBar('2026-01-02', 11, 'RB2605', 'segment-1'),
    apiBar('2026-01-03', 12, 'RB2605', 'segment-1'),
    apiBar('2026-01-04', 13, 'RB2610', 'segment-2'),
  ]
  return {
    meta: {
      strategy_code: 'newow_trend_v1', profile_id: 'newow_trend_d1_v1', frequency: '1d',
      series_kind: 'actual_dominant', calculation_identity: 'calculation',
      data_revision_identity: null, request_identity: 'request',
    },
    instrument: { product: 'rb', display_name: '螺纹钢', last_visible_physical_contract: 'RB2610' },
    bars,
    bar_policy: 'completed_only',
    trend_band: [
      { bar_end: bars[0]!.bar_end, b_value: 10.5, c_value: null, state: 'UNAVAILABLE', state_before: null, transition: null },
      { bar_end: bars[1]!.bar_end, b_value: 11.5, c_value: 10.8, state: 'BLUE', state_before: 'YELLOW', transition: 'CLEAR' },
      { bar_end: bars[2]!.bar_end, b_value: 12.5, c_value: 11.8, state: 'YELLOW', state_before: 'BLUE', transition: 'BUILD' },
    ],
    trend_markers: [marker('build', 'BUILD', bars[2]!.bar_end, 13, 'BUILD')],
    escape_markers: [
      marker('d3', 'NEWOW_ESCAPE_D3', bars[2]!.bar_end, 13, 'D3'),
      marker('d1', 'NEWOW_ESCAPE_D1', bars[2]!.bar_end, 13, 'D1'),
      marker('d2', 'NEWOW_ESCAPE_D2', bars[2]!.bar_end, 13, 'D2'),
    ],
    cup_markers: [marker('cup-ready', 'CUP_HANDLE_READY', bars[2]!.bar_end, 13, '杯柄就绪')],
    cup_handles: [cup()],
    rollover_seams: [{
      trading_day: '2026-01-04', previous_contract: 'RB2605', next_contract: 'RB2610',
      previous_bar_end: bars[1]!.bar_end, next_bar_end: bars[2]!.bar_end,
      previous_segment_id: 'segment-1', next_segment_id: 'segment-2',
    }],
    legend: { BUILD: 'trend build', CLEAR: 'trend clear', D1: 'escape D1', D2: 'escape D2', D3: 'escape D3' },
    formula_descriptions: {
      trend_band: 'newow_trend_band_cleanroom_v1', escape: 'newow_escape_d123_v1', cup_handle: 'newow_cup_handle_v1',
    },
    warnings: [],
  }
}

function apiBar(day: string, close: number, physicalContract: string, segmentId: string) {
  return {
    bar_end: `${day}T07:00:00Z`, trading_day: day,
    open: close - 1, high: close + 1, low: close - 2, close,
    volume: close + 20, open_interest: close + 120,
    physical_contract: physicalContract, segment_id: segmentId, source_identity: 'calculation',
  }
}

function marker(
  id: string,
  markerType: NewowMarker['marker_type'],
  barEnd: string,
  price: number,
  label: string,
): NewowMarker {
  return {
    marker_id: id, marker_type: markerType, bar_end: barEnd, price, label,
    color_token: `newow-${id}`, priority: markerType === 'NEWOW_ESCAPE_D3' ? 999 : 1,
    related_marker_ids: [], trigger_facts: {},
    formula_version: markerType === 'BUILD' || markerType === 'CLEAR'
      ? 'newow_trend_band_cleanroom_v1'
      : markerType.startsWith('NEWOW_ESCAPE_') ? 'newow_escape_d123_v1' : 'newow_cup_handle_v1',
  }
}

function cup(): NewowCupHandle {
  return {
    candidate_id: 'cup-1', direction: 'BULLISH', state: 'READY',
    left_rim: { pivot_at: '2026-01-01T07:00:00Z', confirmed_at: '2026-01-01T07:00:00Z', price: 12 },
    bottom: { pivot_at: '2026-01-02T07:00:00Z', confirmed_at: '2026-01-02T07:00:00Z', price: 9 },
    right_rim: { pivot_at: '2026-01-03T07:00:00Z', confirmed_at: '2026-01-03T07:00:00Z', price: 12.5 },
    handle_start_at: '2026-01-03T07:00:00Z',
    handle_extreme: { pivot_at: '2026-01-04T07:00:00Z', confirmed_at: '2026-01-04T07:00:00Z', price: 11.5 },
    pivot_price: 12.7, pivot_frozen_at: '2026-01-03T07:00:00Z',
    confirmed_at: '2026-01-03T07:00:00Z', first_seen_at: '2026-01-03T07:00:00Z',
    state_changed_at: '2026-01-04T07:00:00Z', score: 80,
    score_breakdown: { pretrend: 20, cup_geometry: 20, u_shape_purity: 15, handle_quality: 15, volume_structure: 10 },
    hard_failures: [], diagnostics: [], volume_facts: {
      right_leg_median: 100, handle_median: 70, handle_baseline_median: 90,
      handle_right_ratio: 0.7, handle_baseline_ratio: 0.78,
    },
    formula_version: 'newow_cup_handle_v1',
  }
}

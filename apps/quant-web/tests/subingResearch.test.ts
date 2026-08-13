import test from 'node:test'
import assert from 'node:assert/strict'
import {
  filterBarsToSubingSegment,
  isSubingSupportedFrequency,
  shouldScheduleSubingCompanionRefresh,
  normalizeSubingResearch,
  type BarData,
  type SubingResearchResponse,
} from '../src/types/market.ts'

const readyPayload = {
  symbol: 'jm',
  product_name: '焦煤',
  frequency: '5m',
  actual_contract: 'JM2609',
  dominant_mapping_date: '2026-08-13',
  segment_start_trading_day: '2026-08-12',
  source_mode: 'canonical_live',
  live_observation: 'available',
  live_reason: null,
  macd_policy_id: 'web_macd_legacy_v1',
  calibration_state: 'pending',
  primary: {
    status: 'ready',
    snapshot: {
      timeframe: '5m',
      bar_end: '2026-08-13T02:25:00Z',
      trading_day: '2026-08-13',
      contract: 'JM2609',
      segment_start_trading_day: '2026-08-12',
      bar_source: 'live',
      close: '100.5',
      ema21: '99.5',
      price_side: 'above',
      slope_5_raw: '0.12',
      slope_10_raw: '0.08',
      slope_5_bps_per_bar: '2.7',
      slope_10_bps_per_bar: '1.8',
      macd_dif: '0.7',
      macd_dea: '0.5',
      macd_histogram: '0.4',
      macd_cross: 'golden',
      macd_cross_level: '0.6',
      macd_zero_distance_abs: '0.6',
      macd_zero_distance_bps: '59.7',
      volume: '342',
      previous_volume: '100',
      volume_ratio_prev: '3.42',
    },
  },
  companion: {
    status: 'insufficient_data',
    snapshot: null,
  },
} as unknown as SubingResearchResponse

test('normalizes Decimal Factor values at the SuBing HTTP boundary', () => {
  const result = normalizeSubingResearch(readyPayload)

  assert.equal(result.primary.snapshot?.slope_5_bps_per_bar, 2.7)
  assert.equal(result.primary.snapshot?.macd_zero_distance_bps, 59.7)
  assert.equal(result.primary.snapshot?.volume_ratio_prev, 3.42)
})

test('filters old same-contract bars before the current dominant segment', () => {
  const bars: BarData[] = [
    bar('2026-07-15T02:25:00Z', '2026-07-15'),
    bar('2026-08-11T02:25:00Z', '2026-08-11'),
    bar('2026-08-12T02:25:00Z', '2026-08-12'),
    bar('2026-08-13T02:25:00Z', '2026-08-13'),
  ]

  const result = filterBarsToSubingSegment(bars, '2026-08-12')

  assert.deepEqual(result.map((item) => item.trading_day), ['2026-08-12', '2026-08-13'])
})

test('keeps an insufficient companion explicit without inventing a Factor snapshot', () => {
  const result = normalizeSubingResearch(readyPayload)

  assert.equal(result.companion?.status, 'insufficient_data')
  assert.equal(result.companion?.snapshot, null)
})

test('supports only the three SuBing V1 snapshot frequencies', () => {
  assert.equal(isSubingSupportedFrequency('5m'), true)
  assert.equal(isSubingSupportedFrequency('15m'), true)
  assert.equal(isSubingSupportedFrequency('1d'), true)
  assert.equal(isSubingSupportedFrequency('30m'), false)
})

test('schedules one bounded refresh only for an older companion at a common 5m boundary', () => {
  const commonBoundary = normalizeSubingResearch({
    ...readyPayload,
    primary: {
      ...readyPayload.primary,
      snapshot: {
        ...readyPayload.primary.snapshot!,
        bar_end: '2026-08-13T02:30:00Z',
      },
    },
    companion: {
      status: 'ready',
      snapshot: {
        ...readyPayload.primary.snapshot!,
        timeframe: '15m',
        bar_end: '2026-08-13T02:15:00Z',
      },
    },
  })

  assert.equal(shouldScheduleSubingCompanionRefresh(commonBoundary), true)
  assert.equal(shouldScheduleSubingCompanionRefresh({
    ...commonBoundary,
    companion: { status: 'insufficient_data', snapshot: null },
  }), false)
  assert.equal(shouldScheduleSubingCompanionRefresh({
    ...commonBoundary,
    primary: {
      ...commonBoundary.primary,
      snapshot: { ...commonBoundary.primary.snapshot!, bar_end: '2026-08-13T02:25:00Z' },
    },
  }), false)
})

function bar(time: string, tradingDay: string): BarData {
  return {
    time,
    trading_day: tradingDay,
    open: 99,
    high: 102,
    low: 98,
    close: 100,
    volume: 1_000,
  }
}

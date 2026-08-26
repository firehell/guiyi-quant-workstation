import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  normalizeSubingDailyWatchCurrent,
  type SubingDailyWatchCurrentWireResponse,
  type SubingDailyWatchItemWire,
} from '../src/types/market.ts'
import {
  subingDailyWatchReasonLabel,
  visibleDailyWatchItems,
} from '../src/utils/subingDailyWatch.ts'

function trend(priceSide: 'above' | 'below' = 'above') {
  return {
    bar_end: '2026-08-24T07:00:00Z',
    trading_day: '2026-08-24',
    physical_contract: 'RB2610',
    current_segment_start_trading_day: '2026-07-20',
    warmup_start_trading_day: '2026-07-01',
    warmup_bar_count: 30,
    warmup_segment_count: 2,
    history_mode: 'rank1_stitched_raw',
    close: priceSide === 'above' ? '3512.125' : '3400.5',
    ema21: '3478.2468',
    price_side: priceSide,
    slope_5_bps_per_bar: priceSide === 'above' ? '8.6214' : '-8.6214',
    slope_10_bps_per_bar: priceSide === 'above' ? '5.9173' : '-5.9173',
  } as const
}

function readyItem(
  symbol: string,
  decision: 'long_watch' | 'short_watch' = 'long_watch',
): SubingDailyWatchItemWire {
  const priceSide = decision === 'long_watch' ? 'above' : 'below'
  return {
    symbol,
    product_name: symbol.toUpperCase(),
    sector: 'black',
    decision,
    reason_codes: [decision === 'long_watch' ? 'D1_H1_LONG_ALIGNED' : 'D1_H1_SHORT_ALIGNED'],
    daily: trend(priceSide),
    hourly: trend(priceSide),
    unavailable_reasons: [],
  }
}

function unavailableItem(symbol: string): SubingDailyWatchItemWire {
  return {
    symbol,
    product_name: symbol.toUpperCase(),
    sector: 'black',
    decision: 'unavailable',
    reason_codes: [],
    daily: null,
    hourly: null,
    unavailable_reasons: ['H1_HISTORY_INSUFFICIENT'],
  }
}

function readyPayload(): SubingDailyWatchCurrentWireResponse {
  return {
    projection_version: 'subing_daily_watch_v2',
    formula_version: 'subing_ema21_rank1_stitched_raw_v2',
    history_mode: 'rank1_stitched_raw',
    status: 'ready',
    expected_target_trading_day: '2026-08-25',
    latest_target_trading_day: '2026-08-25',
    error_code: null,
    snapshot: {
      source_trading_day: '2026-08-24',
      target_trading_day: '2026-08-25',
      generated_at: '2026-08-24T10:24:13Z',
      counts: {
        universe: 5,
        long_watch: 2,
        short_watch: 1,
        excluded: 1,
        unavailable: 1,
      },
      long_watch: [readyItem('rb'), readyItem('ag')],
      short_watch: [readyItem('jm', 'short_watch')],
      unavailable: [unavailableItem('cu')],
    },
  }
}

test('Daily Watch normalizes only finite Decimal strings while preserving V2 identity, lineage, counts, order and unavailable reasons', () => {
  const result = normalizeSubingDailyWatchCurrent(readyPayload())

  assert.equal(result.status, 'ready')
  assert.equal(result.projection_version, 'subing_daily_watch_v2')
  assert.equal(result.formula_version, 'subing_ema21_rank1_stitched_raw_v2')
  assert.equal(result.history_mode, 'rank1_stitched_raw')
  assert.deepEqual(result.snapshot?.counts, {
    universe: 5,
    long_watch: 2,
    short_watch: 1,
    excluded: 1,
    unavailable: 1,
  })
  assert.deepEqual(result.snapshot?.long_watch.map((item) => item.symbol), ['rb', 'ag'])
  assert.deepEqual(result.snapshot?.short_watch.map((item) => item.symbol), ['jm'])
  assert.equal(result.snapshot?.long_watch[0].daily?.close, 3512.125)
  assert.equal(result.snapshot?.long_watch[0].hourly?.ema21, 3478.2468)
  assert.equal(result.snapshot?.short_watch[0].daily?.slope_5_bps_per_bar, -8.6214)
  assert.equal(result.snapshot?.short_watch[0].hourly?.slope_10_bps_per_bar, -5.9173)
  assert.deepEqual(result.snapshot?.long_watch[0].daily, {
    bar_end: '2026-08-24T07:00:00Z',
    trading_day: '2026-08-24',
    physical_contract: 'RB2610',
    current_segment_start_trading_day: '2026-07-20',
    warmup_start_trading_day: '2026-07-01',
    warmup_bar_count: 30,
    warmup_segment_count: 2,
    history_mode: 'rank1_stitched_raw',
    close: 3512.125,
    ema21: 3478.2468,
    price_side: 'above',
    slope_5_bps_per_bar: 8.6214,
    slope_10_bps_per_bar: 5.9173,
  })
  assert.deepEqual(result.snapshot?.unavailable[0].unavailable_reasons, ['H1_HISTORY_INSUFFICIENT'])
})

test('Daily Watch rejects a V1 projection version', () => {
  const payload = readyPayload() as unknown as Record<string, unknown>
  payload.projection_version = 'subing_daily_watch_v1'

  assert.throws(
    () => normalizeSubingDailyWatchCurrent(payload as unknown as SubingDailyWatchCurrentWireResponse),
    new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE'),
  )
})

test('Daily Watch rejects a V1 formula version', () => {
  const payload = readyPayload() as unknown as Record<string, unknown>
  payload.formula_version = 'subing_ema21_trend_v1'

  assert.throws(
    () => normalizeSubingDailyWatchCurrent(payload as unknown as SubingDailyWatchCurrentWireResponse),
    new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE'),
  )
})

test('Daily Watch rejects missing or wrong top-level history mode', () => {
  const missing = readyPayload() as unknown as Record<string, unknown>
  delete missing.history_mode
  const wrong = readyPayload() as unknown as Record<string, unknown>
  wrong.history_mode = 'segment_local'

  assert.throws(
    () => normalizeSubingDailyWatchCurrent(missing as unknown as SubingDailyWatchCurrentWireResponse),
    new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE'),
  )
  assert.throws(
    () => normalizeSubingDailyWatchCurrent(wrong as unknown as SubingDailyWatchCurrentWireResponse),
    new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE'),
  )
})

test('Daily Watch rejects trend history mode mismatch', () => {
  const payload = readyPayload()
  const daily = payload.snapshot!.long_watch[0].daily! as unknown as Record<string, unknown>
  daily.history_mode = 'segment_local'

  assert.throws(
    () => normalizeSubingDailyWatchCurrent(payload),
    new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE'),
  )
})

test('Daily Watch rejects missing trend warm-up start', () => {
  const payload = readyPayload()
  const daily = payload.snapshot!.long_watch[0].daily! as unknown as Record<string, unknown>
  delete daily.warmup_start_trading_day

  assert.throws(
    () => normalizeSubingDailyWatchCurrent(payload),
    new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE'),
  )
})

test('Daily Watch rejects a trend warm-up bar count other than 30', () => {
  const payload = readyPayload()
  const daily = payload.snapshot!.long_watch[0].daily! as unknown as Record<string, unknown>
  daily.warmup_bar_count = 29

  assert.throws(
    () => normalizeSubingDailyWatchCurrent(payload),
    new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE'),
  )
})

test('Daily Watch rejects invalid trend warm-up segment counts', () => {
  const zero = readyPayload()
  const tooMany = readyPayload()
  ;(zero.snapshot!.long_watch[0].daily! as unknown as Record<string, unknown>).warmup_segment_count = 0
  ;(tooMany.snapshot!.long_watch[0].daily! as unknown as Record<string, unknown>).warmup_segment_count = 31

  assert.throws(
    () => normalizeSubingDailyWatchCurrent(zero),
    new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE'),
  )
  assert.throws(
    () => normalizeSubingDailyWatchCurrent(tooMany),
    new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE'),
  )
})

test('Daily Watch rejects legacy-only trend lineage', () => {
  const payload = readyPayload()
  const daily = payload.snapshot!.long_watch[0].daily! as unknown as Record<string, unknown>
  delete daily.current_segment_start_trading_day
  daily.segment_start_trading_day = '2026-07-20'

  assert.throws(
    () => normalizeSubingDailyWatchCurrent(payload),
    new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE'),
  )
})

test('Daily Watch rejects invalid, future, or mixed V1/V2 trend lineage', () => {
  const invalidDate = readyPayload()
  const futureCurrentSegment = readyPayload()
  const futureWarmupSegment = readyPayload()
  const mixed = readyPayload()
  ;(invalidDate.snapshot!.long_watch[0].daily! as unknown as Record<string, unknown>)
    .warmup_start_trading_day = '2026-02-30'
  ;(futureCurrentSegment.snapshot!.long_watch[0].daily! as unknown as Record<string, unknown>)
    .current_segment_start_trading_day = '2026-08-25'
  ;(futureWarmupSegment.snapshot!.long_watch[0].daily! as unknown as Record<string, unknown>)
    .warmup_start_trading_day = '2026-08-25'
  ;(mixed.snapshot!.long_watch[0].daily! as unknown as Record<string, unknown>)
    .segment_start_trading_day = '2026-07-20'

  for (const payload of [invalidDate, futureCurrentSegment, futureWarmupSegment, mixed]) {
    assert.throws(
      () => normalizeSubingDailyWatchCurrent(payload),
      new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE'),
    )
  }
})

test('Daily Watch rejects negative and fractional count fields', () => {
  const negative = readyPayload()
  const fractional = readyPayload()
  negative.snapshot!.counts.excluded = -1
  fractional.snapshot!.counts.unavailable = 0.5

  assert.throws(
    () => normalizeSubingDailyWatchCurrent(negative),
    new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE'),
  )
  assert.throws(
    () => normalizeSubingDailyWatchCurrent(fractional),
    new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE'),
  )
})

test('Daily Watch rejects non-finite Decimal strings', () => {
  const payload = readyPayload()
  payload.snapshot!.long_watch[0].daily!.close = 'Infinity'

  assert.throws(
    () => normalizeSubingDailyWatchCurrent(payload),
    new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE'),
  )
})

test('Daily Watch rejects non-decimal string syntax and numeric transport values', () => {
  const hexadecimal = readyPayload()
  hexadecimal.snapshot!.long_watch[0].daily!.close = '0x10'
  const numericTransport = readyPayload()
  numericTransport.snapshot!.long_watch[0].daily!.close = 3512.125 as never

  assert.throws(
    () => normalizeSubingDailyWatchCurrent(hexadecimal),
    new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE'),
  )
  assert.throws(
    () => normalizeSubingDailyWatchCurrent(numericTransport),
    new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE'),
  )
})

test('Daily Watch rejects a missing count field', () => {
  const payload = readyPayload() as unknown as Record<string, unknown>
  const snapshot = payload.snapshot as Record<string, unknown>
  const counts = snapshot.counts as Record<string, unknown>
  delete counts.excluded

  assert.throws(
    () => normalizeSubingDailyWatchCurrent(payload as unknown as SubingDailyWatchCurrentWireResponse),
    new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE'),
  )
})

test('Daily Watch rejects count mismatches and duplicate symbols across projected groups', () => {
  const mismatched = readyPayload()
  mismatched.snapshot!.counts.long_watch = 3
  const duplicated = readyPayload()
  duplicated.snapshot!.short_watch[0] = readyItem('rb', 'short_watch')

  assert.throws(
    () => normalizeSubingDailyWatchCurrent(mismatched),
    new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE'),
  )
  assert.throws(
    () => normalizeSubingDailyWatchCurrent(duplicated),
    new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE'),
  )
})

test('Daily Watch preserves a typed unavailable response without inventing a snapshot', () => {
  const result = normalizeSubingDailyWatchCurrent({
    status: 'unavailable',
    projection_version: 'subing_daily_watch_v2',
    formula_version: 'subing_ema21_rank1_stitched_raw_v2',
    history_mode: 'rank1_stitched_raw',
    expected_target_trading_day: '2026-08-25',
    latest_target_trading_day: '2026-08-22',
    error_code: 'SUBING_DAILY_WATCH_STALE',
    snapshot: null,
  })

  assert.deepEqual(result, {
    status: 'unavailable',
    projection_version: 'subing_daily_watch_v2',
    formula_version: 'subing_ema21_rank1_stitched_raw_v2',
    history_mode: 'rank1_stitched_raw',
    expected_target_trading_day: '2026-08-25',
    latest_target_trading_day: '2026-08-22',
    error_code: 'SUBING_DAILY_WATCH_STALE',
    snapshot: null,
  })
})

test('Daily Watch shows only the first six items until that group is expanded', () => {
  const items = ['a', 'b', 'c', 'd', 'e', 'f', 'g'].map((symbol) => readyItem(symbol))

  assert.deepEqual(
    visibleDailyWatchItems(items, false).map((item) => item.symbol),
    ['a', 'b', 'c', 'd', 'e', 'f'],
  )
  assert.equal(visibleDailyWatchItems(items, true).length, 7)
})

test('Daily Watch maps stable unavailable reasons and never exposes unknown backend text', () => {
  assert.equal(subingDailyWatchReasonLabel('H1_HISTORY_INSUFFICIENT'), '60m 历史不足')
  assert.equal(subingDailyWatchReasonLabel('D1_HISTORY_INSUFFICIENT'), '日线历史不足')
  assert.equal(subingDailyWatchReasonLabel('raw backend database detail'), '数据身份不可用')
})

test('Market homepage owns exactly one SuBing workbench instead of sibling source components', () => {
  const homeSource = readFileSync(new URL('../src/pages/market/index.vue', import.meta.url), 'utf8')

  assert.equal(homeSource.match(/<SubingWorkbench\b/g)?.length, 1)
  assert.equal(homeSource.includes('<MarketFormalSignals'), false)
  assert.equal(homeSource.includes('<SubingDailyWatch'), false)
})

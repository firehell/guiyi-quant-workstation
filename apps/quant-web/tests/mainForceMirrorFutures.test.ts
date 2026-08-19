import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import type { BarData } from '../src/types/market.ts'
import {
  DEFAULT_PARAMETERS,
  INDICATOR_CODE,
  INDICATOR_VERSION,
  PARAMETERS_HASH,
  calculateMainForceMirrorFutures,
  isMainForceMirrorFuturesCandidate,
  roundHalfAwayFromZeroBinary64,
} from '../src/utils/mainForceMirrorFutures.ts'

interface GoldenBar {
  time: string
  physical_contract: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  open_interest: number | null
}

interface GoldenFixture {
  schema_version: number
  indicator_code: string
  indicator_version: string
  parameters_hash: string
  bars: GoldenBar[]
  rounding_cases: Array<{ value: number; digits: number; expected: number }>
  expected_points: Array<Record<string, unknown>>
}

const fixture = JSON.parse(readFileSync(new URL(
  '../../../tests/fixtures/main_force_mirror_futures_v1_golden.json',
  import.meta.url,
), 'utf8')) as GoldenFixture

const pointFields = [
  'valid',
  'state_ready',
  'caution_ready',
  'ready',
  'reason',
  'caution_availability_reason',
  'state',
  'signed_score',
  'strength',
  'price_impulse',
  'clv',
  'volume_ratio',
  'delta_oi',
  'oi_impulse',
  'direction',
  'range_position',
  'long_open_pressure',
  'short_open_pressure',
  'long_caution_score',
  'short_caution_score',
  'caution',
  'caution_reason_codes',
] as const

function jsonSafe(value: unknown): unknown {
  if (typeof value !== 'number') return value
  if (!Number.isFinite(value)) return null
  return Object.is(value, -0) ? 0 : value
}

test('futures mirror freezes exact indicator and parameter identity', () => {
  assert.equal(fixture.schema_version, 1)
  assert.equal(INDICATOR_CODE, fixture.indicator_code)
  assert.equal(INDICATOR_VERSION, fixture.indicator_version)
  assert.equal(PARAMETERS_HASH, fixture.parameters_hash)
  assert.deepEqual(DEFAULT_PARAMETERS, {
    atr_period: 14,
    volume_window: 20,
    oi_impulse_ema_period: 20,
    range_window: 20,
    pressure_divergence_window: 10,
    direction_price_weight: 0.7,
    direction_clv_weight: 0.3,
    direction_deadband: 0.15,
    oi_deadband: 0.25,
    volume_ratio_clip: 3,
    price_impulse_clip: 3,
    oi_impulse_clip: 3,
    strength_scale: 25,
    turnover_display_cap: 15,
    upper_location_threshold: 0.85,
    lower_location_threshold: 0.15,
    liquidation_dominated_oi_threshold: 0.5,
    pressure_confirmation_ratio: 0.7,
    high_volume_threshold: 1.5,
    clv_rejection_threshold: 0.25,
    wick_rejection_threshold: 0.35,
    caution_threshold: 70,
    rearm_score_threshold: 40,
    rearm_low_score_bars: 3,
    rearm_build_bars: 2,
    long_rearm_range_threshold: 0.65,
    short_rearm_range_threshold: 0.35,
    round_digits: 6,
    rounding_policy: 'half_away_from_zero_binary64',
  })
})

test('futures mirror matches every shared golden point exactly', () => {
  const bars: BarData[] = fixture.bars.map((bar) => ({
    time: bar.time,
    physicalContract: bar.physical_contract,
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
    volume: bar.volume,
    openInterest: bar.open_interest === null ? undefined : bar.open_interest,
  }))

  const result = calculateMainForceMirrorFutures(bars)
  const actual = result.points.map((point) => Object.fromEntries(
    pointFields.map((field) => [field, jsonSafe(point[field])]),
  ))

  assert.deepEqual(actual, fixture.expected_points)
  assert.deepEqual(actual[36].caution_reason_codes, [
    'LONG_SHORT_COVER_DOMINATED',
    'LONG_OPEN_PRESSURE_DIVERGENCE',
    'LONG_HIGH_VOLUME_EXHAUSTION',
    'SHORT_LOWER_EXTREME',
    'SHORT_OPEN_PRESSURE_DIVERGENCE',
    'SHORT_LOW_PRICE_ABSORPTION',
  ])
})

test('futures mirror uses binary64 half-away rounding and normalizes negative zero', () => {
  for (const roundingCase of fixture.rounding_cases) {
    const actual = roundHalfAwayFromZeroBinary64(roundingCase.value, roundingCase.digits)
    assert.equal(actual, roundingCase.expected)
    assert.equal(Object.is(actual, -0), false)
  }
})

test('futures mirror threshold decisions use raw values before public rounding', () => {
  const rawScoreThatDisplaysAsSeventy = 69.9999996
  assert.equal(roundHalfAwayFromZeroBinary64(rawScoreThatDisplaysAsSeventy, 6), 70)
  assert.equal(isMainForceMirrorFuturesCandidate(rawScoreThatDisplaysAsSeventy), false)
  assert.equal(isMainForceMirrorFuturesCandidate(70), true)
})

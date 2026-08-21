import test from 'node:test'
import assert from 'node:assert/strict'
import type { BarData, MainForceMirrorV2Point } from '../src/types/market.ts'
import {
  buildKlineDerivedData,
  formatKlineHoverValue,
  resolveKlineHoverContext,
} from '../src/utils/klineViewModel.ts'

const bars: BarData[] = Array.from({ length: 100 }, (_, index) => {
  const close = 100 + index
  return {
    time: new Date(Date.UTC(2026, 0, index + 1, 7)).toISOString(),
    trading_day: new Date(Date.UTC(2026, 0, index + 1)).toISOString().slice(0, 10),
    open: close - 1,
    high: close + 2,
    low: close - 3,
    close,
    volume: 1_000 + index,
    openInterest: 2_000 + index,
  }
})

test('only enabled EMA is derived while MACD is always available', () => {
  const result = buildKlineDerivedData(bars, ['ema_21'])

  assert.equal(result.ema.ema_10, undefined)
  assert.equal(result.ema.ema_60, undefined)
  assert.equal(result.ema.ema_21?.length, 80)
  assert.ok(result.macd.dif.length > 0)
  assert.equal(result.macd.dif.length, result.macd.dea.length)
  assert.equal(result.macd.dea.length, result.macd.histogram.length)
})

test('HTDY is only derived when its observation overlay is explicitly visible', () => {
  const htdyBars = makeDeterministicHtdyBars(2)
  const hidden = buildKlineDerivedData(htdyBars, ['ema_21'])
  const visible = buildKlineDerivedData(htdyBars, ['ema_21', 'htdy'])

  assert.equal(hidden.htdy, null)
  assert.ok(visible.htdy)
  assert.ok(visible.htdy?.zk1.length)
  assert.ok(visible.htdy?.zd1.length)
  assert.ok(visible.htdy?.zd2.length)
  assert.ok(visible.htdy?.markers.length)
  assert.ok(visible.htdy?.markers.every((marker) => ['买观察', '卖观察'].includes(marker.label)))
  assert.ok(visible.htdy?.markers.every((marker) => marker.tone === 'htdy'))
})

test('crosshair context keeps OHLCV OI EMA and MACD on the hovered bar timestamp', () => {
  const result = buildKlineDerivedData(bars, ['ema_21'])
  const target = bars[79]
  const hover = resolveKlineHoverContext(bars, result, ['ema_21'], target.time)

  assert.ok(hover)
  assert.equal(hover.time, target.time)
  assert.equal(hover.bar.open, 178)
  assert.equal(hover.bar.high, 181)
  assert.equal(hover.bar.low, 176)
  assert.equal(hover.bar.close, 179)
  assert.equal(hover.bar.volume, 1_079)
  assert.equal(hover.bar.openInterest, 2_079)
  assert.equal(hover.mainIndicators?.[0]?.id, 'ema_21')
  assert.ok(hover.mainIndicators?.[0]?.value)
  assert.notEqual(hover.macd?.dif, null)
  assert.notEqual(hover.macd?.dea, null)
  assert.notEqual(hover.macd?.histogram, null)
})

test('missing hover values render as unavailable instead of a fabricated zero', () => {
  assert.equal(formatKlineHoverValue(undefined), '—')
  assert.equal(formatKlineHoverValue(null), '—')
  assert.equal(formatKlineHoverValue(0), '0')
})

test('crosshair projects the exact timestamp-aligned V2 observation without inventing missing values', () => {
  const result = buildKlineDerivedData(bars, [])
  const target = bars[79]
  const point: MainForceMirrorV2Point = {
    bar_end: target.time,
    trading_day: target.trading_day!,
    physical_contract: 'AG2601',
    pressure_ready: true,
    pressure_state: 'long_build',
    instant_pressure: 82,
    accumulated_ready: true,
    accumulated_pressure: 61,
    caution_ready: true,
    caution: 'long_chase_caution',
    caution_conflict: false,
    long_caution_score: 70,
    short_caution_score: 10,
    caution_reason_codes: ['LONG_BUILD_STREAK'],
    price_impulse: 0.23,
    clv: null,
    volume_ratio: 1.4,
    delta_oi: 41,
    oi_impulse: 0.18,
    range_position: 0.79,
    member_status: 'ready',
    member_trade_date: '2026-03-20',
    member_direction: 'long',
    member_change_bias: 0.24,
    member_strength: 1.4,
    position_skew: 0.3,
    top5_volume_share: 0.42,
    relation_to_accumulated: 'strong_aligned',
    relation_to_caution: 'aligned',
    unavailable_reason: null,
  }

  const hover = resolveKlineHoverContext(bars, result, [], target.time, [point])

  assert.ok(hover?.mainForceMirrorV2)
  assert.equal(hover.mainForceMirrorV2.physicalContract, 'AG2601')
  assert.equal(hover.mainForceMirrorV2.state, 'long_build')
  assert.equal(hover.mainForceMirrorV2.instantPressure, 82)
  assert.equal(hover.mainForceMirrorV2.accumulatedPressure, 61)
  assert.equal(hover.mainForceMirrorV2.memberTradeDate, '2026-03-20')
  assert.equal(hover.mainForceMirrorV2.memberStrength, 1.4)
  assert.equal(hover.mainForceMirrorV2.relationToAccumulated, 'strong_aligned')
  assert.equal(hover.mainForceMirrorV2.unavailableReason, null)
})

test('crosshair returns no V2 hover object when the server has no exact bar_end match', () => {
  const result = buildKlineDerivedData(bars, [])
  const target = bars[79]
  const unmatched = {
    bar_end: bars[78].time,
  } as MainForceMirrorV2Point

  const hover = resolveKlineHoverContext(bars, result, [], target.time, [unmatched])

  assert.ok(hover)
  assert.equal(hover.mainForceMirrorV2, null)
})

function makeDeterministicHtdyBars(seed: number, length = 100): BarData[] {
  let state = seed >>> 0
  const random = () => {
    state = (Math.imul(1664525, state) + 1013904223) >>> 0
    return state / 2 ** 32
  }
  const normal = () => Array.from({ length: 6 }, random).reduce((sum, value) => sum + value, -3)
  const close: number[] = []
  let value = 100
  for (let index = 0; index < length; index += 1) {
    value += normal() * 2
    close.push(value)
  }
  const open = close.map((item) => item + normal())
  const high = close.map((item, index) => Math.max(open[index], item) + 0.1 + random() * 1.9)
  const low = close.map((item, index) => Math.min(open[index], item) - 0.1 - random() * 1.9)

  return close.map((item, index) => ({
    time: `htdy-${index}`,
    open: open[index],
    high: high[index],
    low: low[index],
    close: item,
    volume: 1000,
  }))
}

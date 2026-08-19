import test from 'node:test'
import assert from 'node:assert/strict'
import type { BarData } from '../src/types/market.ts'
import type { MainForceMirrorFuturesPoint, MainForceMirrorFuturesResult } from '../src/utils/mainForceMirrorFutures.ts'
import { buildKlineDerivedData, formatKlineHoverValue, resolveKlineHoverContext } from '../src/utils/klineViewModel.ts'

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

test('crosshair projects the timestamp-aligned futures mirror observation without inventing missing values', () => {
  const result = buildKlineDerivedData(bars, [])
  const target = bars[79]
  const point: MainForceMirrorFuturesPoint = {
    time: target.time,
    physical_contract: 'AG2601',
    valid: true,
    state_ready: true,
    caution_ready: true,
    ready: true,
    reason: null,
    caution_availability_reason: null,
    state: 'long_build',
    signed_score: 82,
    strength: 82,
    price_impulse: 0.23,
    clv: null,
    volume_ratio: 1.4,
    delta_oi: 41,
    oi_impulse: 0.18,
    direction: 0.56,
    range_position: 0.79,
    long_open_pressure: 82,
    short_open_pressure: 12,
    long_caution_score: 70,
    short_caution_score: 10,
    caution: 'long_chase_caution',
    caution_reason_codes: ['LONG_BUILD_STREAK'],
  }
  const futures: MainForceMirrorFuturesResult = {
    points: [point],
    metadata: {} as MainForceMirrorFuturesResult['metadata'],
  }

  const hover = resolveKlineHoverContext(bars, result, [], target.time, futures)

  assert.ok(hover?.mainForceFutures)
  assert.equal(hover.mainForceFutures.physicalContract, 'AG2601')
  assert.equal(hover.mainForceFutures.state, 'long_build')
  assert.equal(hover.mainForceFutures.strength, 82)
  assert.equal(hover.mainForceFutures.priceImpulse, 0.23)
  assert.equal(hover.mainForceFutures.volumeRatio, 1.4)
  assert.equal(hover.mainForceFutures.deltaOi, 41)
  assert.equal(hover.mainForceFutures.oiImpulse, 0.18)
  assert.equal(hover.mainForceFutures.rangePosition, 0.79)
  assert.equal(hover.mainForceFutures.longScore, 70)
  assert.equal(hover.mainForceFutures.shortScore, 10)
  assert.deepEqual(hover.mainForceFutures.reasonCodes, ['LONG_BUILD_STREAK'])
  assert.equal(formatKlineHoverValue(hover.mainForceFutures.clv), '—')
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

import test from 'node:test'
import assert from 'node:assert/strict'
import type { BarData } from '../src/types/market.ts'
import {
  calculateATR,
  calculateEMA,
  calculateHuoTianDaYou,
  calculateMACD,
  isNewThirdConsecutive,
  resolveHuoTianDaYouCandleObservation,
  tdxXma,
} from '../src/utils/indicators.ts'
import { MAIN_INDICATOR_DEFINITIONS } from '../src/utils/mainIndicators.ts'

const bars: BarData[] = Array.from({ length: 40 }, (_, index) => {
  const close = 100 + index
  return {
    time: `2026-01-${String(index + 1).padStart(2, '0')}`,
    open: close - 1,
    high: close + 2,
    low: close - 2,
    close,
    volume: 100 + index,
  }
})

test('calculateEMA returns no points when there is not enough data', () => {
  assert.deepEqual(calculateEMA(bars.slice(0, 20), 21), [])
})

test('calculateEMA returns one point per bar after the seed window', () => {
  const result = calculateEMA(bars, 21)
  assert.equal(result.length, 20)
  assert.equal(result[0].time, bars[20].time)
  assert.ok(result[0].value > bars[0].close)
  assert.ok(result.at(-1)!.value > result[0].value)
})

test('calculateEMA supports main chart periods 10, 21 and 60 with the same seed rule', () => {
  const longerBars: BarData[] = Array.from({ length: 80 }, (_, index) => ({
    time: `2026-03-${String(index + 1).padStart(2, '0')}`,
    open: 100 + index,
    high: 103 + index,
    low: 98 + index,
    close: 101 + index,
    volume: 1000 + index,
  }))

  assert.equal(calculateEMA(longerBars, 10)[0].time, longerBars[9].time)
  assert.equal(calculateEMA(longerBars, 21)[0].time, longerBars[20].time)
  assert.equal(calculateEMA(longerBars, 60)[0].time, longerBars[59].time)
})

test('tdxXma uses the corrected symmetric clipped future-looking window', () => {
  const sample = [10, 20, 30, 40, 50, 60, 70]
  const result = tdxXma(sample, 5)

  assert.equal(result[3], 40)
})

test('tdxXma normalizes period 6 to the symmetric seven-bar window', () => {
  const sample = [0, 1, 2, 3, 4, 5, 6]

  assert.equal(tdxXma(sample, 6)[3], 3)
})

test('HTDY Web remains historical browser observation-only with a conservative 27-bar repaint zone', () => {
  const htdy = MAIN_INDICATOR_DEFINITIONS.find((definition) => definition.id === 'htdy')

  assert.ok(htdy)
  assert.equal(htdy.defaultVisible, false)
  assert.equal(htdy.capability, 'observation_overlay')
  assert.equal(htdy.repaintingRisk, 'known')
  assert.equal(htdy.alertCapable, true)
  assert.equal(htdy.unstableTailBars, 27)
})

test('tdxXma repaints a historical value when future tail changes', () => {
  const original = [10, 20, 30, 40, 50, 60, 70]
  const changedFuture = [10, 20, 30, 40, 500, 600, 700]

  assert.notEqual(tdxXma(original, 5)[3], tdxXma(changedFuture, 5)[3])
})

test('calculateHuoTianDaYou returns observation-only channel points aligned to bars', () => {
  const longerBars: BarData[] = Array.from({ length: 90 }, (_, index) => {
    const close = 100 + Math.sin(index / 5) * 8 + index * 0.2
    return {
      time: `2026-04-${String(index + 1).padStart(2, '0')}`,
      open: close - 1,
      high: close + 4,
      low: close - 4,
      close,
      volume: 1000 + index,
    }
  })

  const result = calculateHuoTianDaYou(longerBars)

  assert.equal(result.points.length, longerBars.length)
  assert.equal(result.points[0].time, longerBars[0].time)
  assert.ok(result.points.some((point) => point.zk1 !== null && point.zd1 !== null))
})

test('HTDY yellow candle uses all original strict conditions and partial STICKLINE segments', () => {
  const bar: BarData = { time: '2026-05-01', open: 100, high: 115, low: 95, close: 110, volume: 1000 }
  const partial = resolveHuoTianDaYouCandleObservation(bar, 120, 105)
  const aboveHigh = resolveHuoTianDaYouCandleObservation(bar, 120, 116)

  assert.equal(partial.yellowCandle, true)
  assert.deepEqual(partial.candleSegments, [
    { kind: 'body', colorRole: 'yellow', from: 105, to: 100 },
    { kind: 'body', colorRole: 'yellow', from: 105, to: 100 },
  ])
  assert.equal(aboveHigh.yellowCandle, true)
  assert.deepEqual(aboveHigh.candleSegments, [
    { kind: 'body', colorRole: 'yellow', from: 100, to: 110 },
    { kind: 'wick', colorRole: 'yellow', from: 115, to: 95 },
  ])
  assert.equal(resolveHuoTianDaYouCandleObservation(bar, 120, bar.low).yellowCandle, false)
  assert.equal(resolveHuoTianDaYouCandleObservation(bar, 120, bar.high).yellowCandle, false)
})

test('HTDY white candle requires the body to cross ZK1 and preserves white-before-yellow order', () => {
  const bar: BarData = { time: '2026-05-02', open: 100, high: 115, low: 95, close: 110, volume: 1000 }

  assert.equal(resolveHuoTianDaYouCandleObservation(bar, 112, undefined).whiteCandle, false)
  const simultaneous = resolveHuoTianDaYouCandleObservation(bar, 105, 116)
  assert.equal(simultaneous.whiteCandle, true)
  assert.deepEqual(simultaneous.candleSegments, [
    { kind: 'body', colorRole: 'white', from: 110, to: 105 },
    { kind: 'body', colorRole: 'yellow', from: 100, to: 110 },
    { kind: 'wick', colorRole: 'yellow', from: 115, to: 95 },
  ])
})

test('HTDY consecutive observations fire only on the newly completed third candle', () => {
  const flags = [false, true, true, true, true, false, true, true, true]
  assert.equal(isNewThirdConsecutive(flags, 3), true)
  assert.equal(isNewThirdConsecutive(flags, 4), false)
  assert.equal(isNewThirdConsecutive(flags, 8), true)
})

test('HTDY Web output exposes only buy and sell observations', () => {
  const result = calculateHuoTianDaYou(makeDeterministicHtdyBars(8))

  assert.ok(result.points.every((point) => typeof point.buyObservation === 'boolean'))
  assert.ok(result.points.every((point) => typeof point.sellObservation === 'boolean'))
  assert.ok(result.points.every((point) => !('xgObservation' in point)))
})

test('HTDY future tail changes historical observation output and remains repainting-only', () => {
  const fullBars = makeDeterministicHtdyBars(13)
  const prefixBars = fullBars.slice(0, 80)
  const original = calculateHuoTianDaYou(prefixBars).points
  const extended = calculateHuoTianDaYou(fullBars).points.slice(0, prefixBars.length)

  assert.ok(original.some((point, index) => point.zk1 !== extended[index].zk1 || point.zd1 !== extended[index].zd1))
})

test('calculateMACD returns aligned dif dea and histogram points', () => {
  const result = calculateMACD(bars)
  assert.ok(result.dif.length > 0)
  assert.equal(result.dif.length, result.dea.length)
  assert.equal(result.dea.length, result.histogram.length)
  assert.equal(result.dif[0].time, result.dea[0].time)
})

test('calculateATR returns no points before the period and then true range averages', () => {
  assert.deepEqual(calculateATR(bars.slice(0, 13), 14), [])

  const result = calculateATR(bars, 14)
  assert.equal(result[0].time, bars[13].time)
  assert.ok(result[0].value > 0)
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

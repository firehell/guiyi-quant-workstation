import test from 'node:test'
import assert from 'node:assert/strict'
import type { BarData } from '../src/types/market.ts'
import { calculateATR, calculateEMA, calculateMACD } from '../src/utils/indicators.ts'

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

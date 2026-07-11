import test from 'node:test'
import assert from 'node:assert/strict'
import type { BarData } from '../src/types/market.ts'
import { calculateATR, calculateEMA, calculateHuoTianDaYou, calculateMACD, tdxXma } from '../src/utils/indicators.ts'

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

test('tdxXma matches the documented centered future-looking window', () => {
  const sample = [10, 20, 30, 40, 50, 60, 70]
  const result = tdxXma(sample, 5)

  assert.equal(result[3], 30)
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

import test from 'node:test'
import assert from 'node:assert/strict'
import type { BarData } from '../src/types/market.ts'
import {
  buildRibbonPoints,
  buildSubingEmaRibbon,
} from '../src/utils/subingEmaRibbon.ts'

function point(time: string, value: number) {
  return { time, value }
}

function bar(index: number, close: number): BarData {
  return {
    time: new Date(Date.UTC(2026, 0, 1, 1, index)).toISOString(),
    trading_day: '2026-01-01',
    open: close,
    high: close,
    low: close,
    close,
    volume: 1,
  }
}

test('one EMA-ready bar emits one ribbon point', () => {
  const points = buildRibbonPoints(
    [point('a', 12), point('b', 13)],
    [point('a', 10), point('b', 11)],
  )

  assert.deepEqual(points, [
    { time: 'a', ema10: 12, ema21: 10, tone: 'bull' },
    { time: 'b', ema10: 13, ema21: 11, tone: 'bull' },
  ])
})

test('bear values emit bear points', () => {
  const points = buildRibbonPoints(
    [point('a', 8)],
    [point('a', 10)],
  )

  assert.equal(points[0]?.tone, 'bear')
})

test('equal EMA inherits only the previous tone', () => {
  const points = buildRibbonPoints(
    [point('a', 12), point('b', 10), point('c', 8)],
    [point('a', 10), point('b', 10), point('c', 10)],
  )

  assert.deepEqual(points.map((item) => item.tone), ['bull', 'bull', 'bear'])
})

test('leading equal EMA does not look ahead for tone', () => {
  const points = buildRibbonPoints(
    [point('a', 10), point('b', 12)],
    [point('a', 10), point('b', 10)],
  )

  assert.deepEqual(points, [
    { time: 'b', ema10: 12, ema21: 10, tone: 'bull' },
  ])
})

test('buildSubingEmaRibbon stays empty until EMA21 is ready', () => {
  const ribbon = buildSubingEmaRibbon(Array.from({ length: 20 }, (_, index) => bar(index, 100 + index)))

  assert.deepEqual(ribbon.ema10.length, 11)
  assert.deepEqual(ribbon.ema21, [])
  assert.deepEqual(ribbon.points, [])
})

test('rising closes after warmup produce bull points', () => {
  const ribbon = buildSubingEmaRibbon(Array.from({ length: 40 }, (_, index) => bar(index, 100 + index)))

  assert.ok(ribbon.ema21.length > 0)
  assert.equal(ribbon.points.length, ribbon.ema21.length)
  assert.ok(ribbon.points.every((item) => item.tone === 'bull'))
})

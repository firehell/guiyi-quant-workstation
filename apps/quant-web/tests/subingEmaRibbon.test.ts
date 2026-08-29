import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import type { BarData } from '../src/types/market.ts'
import {
  buildSubingEmaRibbon,
  crossingSplitT,
  segmentSubingEmaRibbon,
  splitRibbonCoordinates,
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

test('fast above slow emits one bull band per adjacent pair', () => {
  const bands = segmentSubingEmaRibbon(
    [point('a', 12), point('b', 13), point('c', 14)],
    [point('a', 10), point('b', 11), point('c', 12)],
  )

  assert.equal(bands.length, 2)
  assert.ok(bands.every((band) => band.leftTone === 'bull' && band.rightTone === 'bull'))
  assert.ok(bands.every((band) => band.splitT === null))
  assert.deepEqual(bands[0].right, bands[1].left)
  assert.equal(bands[0].left.time, 'a')
  assert.equal(bands[0].right.time, 'b')
  assert.equal(bands[1].right.time, 'c')
})

test('fast below slow emits one bear band', () => {
  const bands = segmentSubingEmaRibbon(
    [point('a', 8), point('b', 7)],
    [point('a', 10), point('b', 11)],
  )

  assert.equal(bands.length, 1)
  assert.equal(bands[0].leftTone, 'bear')
  assert.equal(bands[0].rightTone, 'bear')
  assert.equal(bands[0].splitT, null)
})

test('sign change splits one band at the interpolated t without a fake time', () => {
  const left = { time: '2026-01-01T00:00:00.000Z', ema10: 12, ema21: 10 }
  const right = { time: '2026-01-01T00:02:00.000Z', ema10: 8, ema21: 10 }
  const bands = segmentSubingEmaRibbon(
    [point(left.time, left.ema10), point(right.time, right.ema10)],
    [point(left.time, left.ema21), point(right.time, right.ema21)],
  )

  assert.equal(bands.length, 1)
  assert.equal(bands[0].leftTone, 'bull')
  assert.equal(bands[0].rightTone, 'bear')
  assert.equal(bands[0].splitT, 0.5)
  assert.equal(crossingSplitT(left, right), 0.5)
  assert.deepEqual(bands[0].left, left)
  assert.deepEqual(bands[0].right, right)
  assert.equal(bands[0].left.time, '2026-01-01T00:00:00.000Z')
  assert.equal(bands[0].right.time, '2026-01-01T00:02:00.000Z')
})

test('equal EMA values inherit the previous tone without a fake time', () => {
  const bands = segmentSubingEmaRibbon(
    [point('a', 12), point('b', 10), point('c', 8)],
    [point('a', 10), point('b', 10), point('c', 10)],
  )

  assert.equal(bands.length, 2)
  assert.equal(bands[0].leftTone, 'bull')
  assert.equal(bands[0].rightTone, 'bull')
  assert.equal(bands[0].splitT, null)
  assert.equal(bands[1].leftTone, 'bull')
  assert.equal(bands[1].rightTone, 'bear')
  assert.equal(bands[1].splitT, 0)
  assert.equal(bands[0].left.time, 'a')
  assert.equal(bands[0].right.time, 'b')
  assert.equal(bands[1].right.time, 'c')
})

test('buildSubingEmaRibbon stays empty until EMA21 is ready', () => {
  const ribbon = buildSubingEmaRibbon(Array.from({ length: 20 }, (_, index) => bar(index, 100 + index)))

  assert.deepEqual(ribbon.ema10.length, 11)
  assert.deepEqual(ribbon.ema21, [])
  assert.deepEqual(ribbon.bands, [])
})

test('rising closes after warmup produce bull bands', () => {
  const ribbon = buildSubingEmaRibbon(Array.from({ length: 40 }, (_, index) => bar(index, 100 + index)))

  assert.ok(ribbon.ema21.length > 0)
  assert.ok(ribbon.bands.length >= 1)
  assert.ok(ribbon.bands.every((band) => band.leftTone === 'bull' && band.rightTone === 'bull'))
  assert.ok(ribbon.bands.every((band) => band.splitT === null))
  assert.ok(ribbon.bands.every((band) => band.left.ema10 >= band.left.ema21))
})

test('split coordinates share one vertical edge at splitT', () => {
  const mid = splitRibbonCoordinates(
    { x: 0, y10: 10, y21: 40 },
    { x: 100, y10: 30, y21: 20 },
    0.5,
  )
  assert.deepEqual(mid, { x: 50, y10: 20, y21: 30 })
})

test('primitive fills per-bar quads and splits crossing on screen x', () => {
  const primitive = readFileSync(new URL('../src/components/kline/subingEmaRibbonPrimitive.ts', import.meta.url), 'utf8')
  const chart = readFileSync(new URL('../src/components/kline/KlineChart.vue', import.meta.url), 'utf8')
  assert.match(primitive, /splitRibbonCoordinates/)
  assert.match(primitive, /fillRibbonQuad/)
  assert.match(primitive, /projectBands/)
  assert.match(chart, /subingEmaRibbon\?\.bands/)
})

import test from 'node:test'
import assert from 'node:assert/strict'
import type { BarData } from '../src/types/market.ts'
import {
  calculateMainForceMirror,
  classifyMainForceMirrorState,
} from '../src/utils/mainForceMirror.ts'

test('main-force mirror exposes the six designed observation states', () => {
  assert.equal(classifyMainForceMirrorState(0.20, 0.50, 0.10, 0.20), 'entry')
  assert.equal(classifyMainForceMirrorState(0.20, 0.50, -0.10, 0.20), 'wash')
  assert.equal(classifyMainForceMirrorState(0.70, 0.50, 0.10, 0.20), 'pull_up')
  assert.equal(classifyMainForceMirrorState(0.70, 0.50, -0.10, 0.20), 'distribute')
  assert.equal(classifyMainForceMirrorState(0.70, -0.50, 0.10, 0.20), 'lure')
  assert.equal(classifyMainForceMirrorState(0.30, -0.50, -0.10, -0.20), 'exit')
})

test('caution reproduces the rising edge of BARSLAST(HIGH = HHV(HIGH, 5)) < 10', () => {
  const highs = [1, 2, 3, 4, 5, 4, 3, 2, 1, 0, -1, -2, -3, -4, -5, 6]
  const bars: BarData[] = highs.map((high, index) => ({
    time: `bar-${index}`,
    open: high - 1.2,
    high,
    low: high - 2,
    close: high - 1,
    volume: 1_000,
  }))

  const result = calculateMainForceMirror(bars)
  const cautionIndexes = result.points.flatMap((point, index) => point.caution ? [index] : [])

  assert.deepEqual(cautionIndexes, [4, 15])
  assert.equal(result.points[4].cautionLevel, 50)
  assert.equal(result.points[15].cautionLevel, 50)
})

test('main-force mirror keeps warm-up values unavailable instead of fabricating zeros', () => {
  const bars: BarData[] = Array.from({ length: 19 }, (_, index) => ({
    time: `warmup-${index}`,
    open: 100 + index,
    high: 102 + index,
    low: 98 + index,
    close: 101 + index,
    volume: 1_000 + index,
  }))

  const result = calculateMainForceMirror(bars)

  assert.equal(result.points.length, bars.length)
  assert.ok(result.points.every((point) => point.value === null && point.state === null))
})

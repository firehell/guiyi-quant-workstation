import test from 'node:test'
import assert from 'node:assert/strict'
import type { BarData } from '../src/types/market.ts'
import {
  calculateMainForceMirror,
  classifyMainForceMirrorState,
} from '../src/utils/mainForceMirror.ts'

function goldenBars(count = 28): BarData[] {
  return Array.from({ length: count }, (_, index) => {
    const base = 100 + index * 0.6 + 4 * Math.sin(index / 2.2)
    const open = base + 0.7 * Math.sin(index * 1.7)
    const close = base + 1.1 * Math.sin(index * 1.1)
    return {
      time: `golden-${index}`,
      open,
      high: Math.max(open, close) + 1.5 + (index % 3) * 0.2,
      low: Math.min(open, close) - 1.2 - (index % 4) * 0.15,
      close,
      volume: 1_000 + (index % 5) * 250 + index * 15,
    }
  })
}

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

test('main-force mirror matches the shared kernel golden observation sample', () => {
  const result = calculateMainForceMirror(goldenBars())
  const actual = result.points.flatMap((point, index) => (
    point.value === null || point.state === null ? [] : [[index, point.value, point.state] as const]
  ))

  assert.deepEqual(actual, [
    [20, -0.654814, 'distribute'],
    [21, 0.697117, 'exit'],
    [22, 1.896099, 'exit'],
    [23, -2.603149, 'lure'],
    [24, -0.181907, 'lure'],
    [25, -2.923248, 'pull_up'],
    [26, -0.584624, 'lure'],
    [27, -2.445683, 'lure'],
  ])
  assert.deepEqual(result.points.flatMap((point, index) => point.caution ? [index] : []), [4])
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

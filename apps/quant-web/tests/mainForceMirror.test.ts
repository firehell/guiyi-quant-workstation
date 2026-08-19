import test from 'node:test'
import assert from 'node:assert/strict'
import type { BarData } from '../src/types/market.ts'
import * as indicators from '../src/utils/indicators.ts'

type MirrorState = 'entry' | 'wash' | 'pull_up' | 'distribute' | 'exit' | 'lure'
type MirrorPoint = { time: unknown; value: number | null; state: MirrorState | null; caution: boolean; cautionLevel: number | null }
type MirrorResult = { points: MirrorPoint[] }

type CalculateMirror = (bars: BarData[]) => MirrorResult
type ClassifyState = (rangePosition: number, flow: number, flowDelta: number, priceDelta: number) => MirrorState

function mirrorApi() {
  const api = indicators as unknown as Record<string, unknown>
  const calculate = api.calculateMainForceMirror as CalculateMirror | undefined
  const classify = api.classifyMainForceMirrorState as ClassifyState | undefined
  assert.equal(typeof calculate, 'function')
  assert.equal(typeof classify, 'function')
  return { calculate: calculate!, classify: classify! }
}

test('main-force mirror exposes the six designed observation states', () => {
  const { classify } = mirrorApi()

  assert.equal(classify(0.20, 0.50, 0.10, 0.20), 'entry')
  assert.equal(classify(0.20, 0.50, -0.10, 0.20), 'wash')
  assert.equal(classify(0.70, 0.50, 0.10, 0.20), 'pull_up')
  assert.equal(classify(0.70, 0.50, -0.10, 0.20), 'distribute')
  assert.equal(classify(0.70, -0.50, 0.10, 0.20), 'lure')
  assert.equal(classify(0.30, -0.50, -0.10, -0.20), 'exit')
})

test('caution reproduces the rising edge of BARSLAST(HIGH = HHV(HIGH, 5)) < 10', () => {
  const { calculate } = mirrorApi()
  const highs = [1, 2, 3, 4, 5, 4, 3, 2, 1, 0, -1, -2, -3, -4, -5, 6]
  const bars: BarData[] = highs.map((high, index) => ({
    time: `bar-${index}`,
    open: high - 1.2,
    high,
    low: high - 2,
    close: high - 1,
    volume: 1_000,
  }))

  const result = calculate(bars)
  const cautionIndexes = result.points.flatMap((point, index) => point.caution ? [index] : [])

  assert.deepEqual(cautionIndexes, [4, 15])
  assert.equal(result.points[4].cautionLevel, 50)
  assert.equal(result.points[15].cautionLevel, 50)
})

test('main-force mirror keeps warm-up values unavailable instead of fabricating zeros', () => {
  const { calculate } = mirrorApi()
  const bars: BarData[] = Array.from({ length: 19 }, (_, index) => ({
    time: `warmup-${index}`,
    open: 100 + index,
    high: 102 + index,
    low: 98 + index,
    close: 101 + index,
    volume: 1_000 + index,
  }))

  const result = calculate(bars)

  assert.equal(result.points.length, bars.length)
  assert.ok(result.points.every((point) => point.value === null && point.state === null))
})

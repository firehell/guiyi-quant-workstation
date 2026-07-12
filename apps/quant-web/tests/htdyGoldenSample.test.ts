import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import type { BarData } from '../src/types/market.ts'
import { calculateHuoTianDaYou } from '../src/utils/indicators.ts'

interface GoldenBundle {
  sample: {
    input_sha256: string
    row_count: number
    bars: Array<{
      datetime: string
      open: number
      high: number
      low: number
      close: number
      volume: number
    }>
  }
  python_original: {
    zk1: Array<number | null>
    zd1: Array<number | null>
    zd2: Array<number | null>
    yellow_candle: boolean[]
    white_candle: boolean[]
    buy_observation: boolean[]
    sell_observation: boolean[]
    xg: boolean[]
  }
  comparison: {
    numeric_atol: number
    numeric_rtol: number
    datetime_exact: boolean
    boolean_exact: boolean
    null_position_exact: boolean
  }
}

const bundlePath = process.env.HTDY_GOLDEN_BUNDLE

test(
  'HTDY Web observation-only output matches the fixed Python Golden Sample',
  { skip: bundlePath ? false : 'set HTDY_GOLDEN_BUNDLE to the generated read-only bundle' },
  () => {
    const bundle = JSON.parse(readFileSync(bundlePath!, 'utf8')) as GoldenBundle
    const bars: BarData[] = bundle.sample.bars.map((bar) => ({
      time: bar.datetime,
      datetime: bar.datetime,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
      volume: bar.volume,
    }))
    assert.equal(bars.length, bundle.sample.row_count)

    // Disable display rounding only for this cross-language numeric acceptance.
    const points = calculateHuoTianDaYou(bars, 25, false).points
    assert.deepEqual(points.map((point) => point.time), bundle.sample.bars.map((bar) => bar.datetime))

    compareNumeric(points.map((point) => point.zk1), bundle.python_original.zk1, bundle.comparison)
    compareNumeric(points.map((point) => point.zd1), bundle.python_original.zd1, bundle.comparison)
    compareNumeric(points.map((point) => point.zd2), bundle.python_original.zd2, bundle.comparison)
    assert.deepEqual(points.map((point) => point.yellowCandle), bundle.python_original.yellow_candle)
    assert.deepEqual(points.map((point) => point.whiteCandle), bundle.python_original.white_candle)
    assert.deepEqual(points.map((point) => point.buyObservation), bundle.python_original.buy_observation)
    assert.deepEqual(points.map((point) => point.sellObservation), bundle.python_original.sell_observation)
    assert.deepEqual(points.map((point) => point.xgObservation), bundle.python_original.xg)
  },
)

function compareNumeric(
  actual: Array<number | null>,
  expected: Array<number | null>,
  tolerance: GoldenBundle['comparison'],
): void {
  assert.equal(actual.length, expected.length)
  actual.forEach((value, index) => {
    const expectedValue = expected[index]
    if (expectedValue === null) {
      assert.equal(value, null, `null position ${index}`)
      return
    }
    assert.notEqual(value, null, `numeric position ${index}`)
    const limit = tolerance.numeric_atol + tolerance.numeric_rtol * Math.abs(expectedValue)
    assert.ok(Math.abs(value! - expectedValue) <= limit, `numeric mismatch at ${index}: ${value} vs ${expectedValue}`)
  })
}

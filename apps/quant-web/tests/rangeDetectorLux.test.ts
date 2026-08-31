import test from 'node:test'
import assert from 'node:assert/strict'
import type { BarData } from '../src/types/market.ts'
import { calculateRangeDetectorLux } from '../src/utils/rangeDetectorLux.ts'

function bars(closes: number[]): BarData[] {
  return closes.map((close, index) => ({
    time: `2026-05-${String(index + 1).padStart(2, '0')}T00:00:00Z`,
    trading_day: `2026-05-${String(index + 1).padStart(2, '0')}`,
    open: close,
    high: close + 1,
    low: close - 1,
    close,
    volume: 1,
  }))
}

test('Range Detector distinguishes causal confirmation from visual backpaint', () => {
  const result = calculateRangeDetectorLux(bars([10, 10, 10, 10, 10, 12, 13]), {
    sourceIdentity: 'test:actual_dominant:jm:1d',
    minimumRangeLength: 4,
    rangeAtrLength: 5,
  })

  assert.equal(result.points[4].transition?.kind, 'confirmed')
  assert.equal(result.points[4].snapshot?.visualStartAt, '2026-05-01T00:00:00Z')
  assert.equal(result.points[4].snapshot?.confirmedAt, '2026-05-05T00:00:00Z')
  assert.equal(result.points[5].snapshot?.state, 'intact')
  assert.equal(result.points[6].transition?.kind, 'broken_up')
})

test('Range Detector rejects invalid timestamps and does not rewrite an appended prefix', () => {
  const source = bars([10, 10, 10, 10, 10, 12, 13])
  const original = calculateRangeDetectorLux(source, {
    sourceIdentity: 'test:actual_dominant:jm:1d', minimumRangeLength: 4, rangeAtrLength: 5,
  })
  const appended = calculateRangeDetectorLux([...source, ...bars([100]).map((bar) => ({ ...bar, time: '2026-05-08T00:00:00Z' }))], {
    sourceIdentity: 'test:actual_dominant:jm:1d', minimumRangeLength: 4, rangeAtrLength: 5,
  })
  assert.deepEqual(appended.points.slice(0, original.points.length), original.points)
  assert.throws(() => calculateRangeDetectorLux([{ ...source[0], time: 'bad' }], {
    sourceIdentity: 'test:actual_dominant:jm:1d', minimumRangeLength: 4, rangeAtrLength: 5,
  }), /ISO-8601/)
})

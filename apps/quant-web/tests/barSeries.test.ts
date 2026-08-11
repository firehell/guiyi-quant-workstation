import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { normalizeBarSeries } from '../src/utils/barSeries.ts'
import type { BarData } from '../src/types/market.ts'

function bar(time: string, close: number): BarData {
  return { time, open: close, high: close, low: close, close, volume: 1 }
}

describe('normalizeBarSeries', () => {
  it('sorts ascending and keeps the last value for a duplicate formal end', () => {
    const result = normalizeBarSeries([
      bar('2026-08-11T09:30:00Z', 2),
      bar('2026-08-11T09:15:00Z', 1),
      bar('2026-08-11T09:30:00Z', 3),
    ])

    assert.deepEqual(result.map((item) => [item.time, item.close]), [
      ['2026-08-11T09:15:00Z', 1],
      ['2026-08-11T09:30:00Z', 3],
    ])
  })
})

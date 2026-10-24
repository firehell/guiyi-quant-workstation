import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { initialChartLogicalRange } from '../src/utils/chartViewport.ts'

describe('initialChartLogicalRange', () => {
  it('shows exactly the latest 300 bars when the live seam adds to the initial page', () => {
    assert.deepEqual(initialChartLogicalRange(307), { from: 7, to: 306 })
  })

  it('shows all available bars when fewer than 300 are loaded', () => {
    assert.deepEqual(initialChartLogicalRange(120), { from: 0, to: 119 })
  })
})


it('a warmup prepend keeps pending stabilization anchored to the same candles', async () => {
  const { prependChartLogicalRange } = await import('../src/utils/chartViewport.ts')
  const pending = { from: 700, to: 999 }
  const shifted = prependChartLogicalRange(pending, 1000)!
  assert.deepEqual(shifted, { from: 1700, to: 1999 })
  assert.equal(shifted.from - 1000, pending.from)
  assert.equal(shifted.to - 1000, pending.to)
  assert.deepEqual(prependChartLogicalRange(shifted, 500), { from: 2200, to: 2499 })
  assert.equal(prependChartLogicalRange(null, 1000), null)
})

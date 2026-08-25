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

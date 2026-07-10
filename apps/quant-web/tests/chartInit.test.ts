import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  applyRouteSelectionFromQuery,
  deriveBarsRequestParams,
  resolveRoutePeriod,
  scopedCoverageParams,
} from '../src/utils/marketChartInit.ts'

describe('marketChartInit', () => {
  it('derives chart selection from route query without coverage', () => {
    const selection = applyRouteSelectionFromQuery({
      symbol: 'jm',
      contract: 'JM2609',
      period: '15m',
    })
    assert.deepEqual(selection, {
      selectedSymbol: 'jm',
      selectedActualContract: 'JM2609',
      selectedPeriod: '15m',
      contractView: 'actual',
    })
  })

  it('builds bars request params even when coverage is unavailable', () => {
    const selection = applyRouteSelectionFromQuery({
      symbol: 'jm',
      contract: 'JM2609',
      period: '15m',
    })
    assert.ok(selection)
    assert.deepEqual(deriveBarsRequestParams(selection), {
      symbol: 'jm',
      contract: 'JM2609',
      period: '15m',
    })
  })

  it('prefers interval when period is missing', () => {
    assert.equal(resolveRoutePeriod({ interval: '5m' }), '5m')
  })

  it('builds scoped coverage params from route query', () => {
    assert.deepEqual(
      scopedCoverageParams({ symbol: 'jm', contract: 'JM2609', period: '15m' }),
      { symbol: 'jm', include_paths: false },
    )
  })
})

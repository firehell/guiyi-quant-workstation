import assert from 'node:assert/strict'
import test from 'node:test'
import { seriesRefreshQuery } from '../src/utils/marketChartEntry.ts'

test('series refresh query keeps only canonical market identity', () => {
  assert.deepEqual(seriesRefreshQuery({
    symbol: 'jm',
    contract: '',
    seriesKind: 'actual_dominant',
    frequency: '15m',
  }), {
    symbol: 'jm',
    contract: undefined,
    series_kind: 'actual_dominant',
    frequency: '15m',
  })
})

test('contract is serialized only for a concrete-contract series', () => {
  assert.deepEqual(seriesRefreshQuery({
    symbol: 'jm',
    contract: 'JM2601',
    seriesKind: 'contract',
    frequency: '1d',
  }), {
    symbol: 'jm',
    contract: 'JM2601',
    series_kind: 'contract',
    frequency: '1d',
  })
  assert.equal(seriesRefreshQuery({
    symbol: 'jm',
    contract: 'JM2601',
    seriesKind: 'continuous',
    frequency: '1d',
  }).contract, undefined)
})

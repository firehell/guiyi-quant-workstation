import assert from 'node:assert/strict'
import test from 'node:test'
import {
  consumeFocusBarEnd,
  resolveFocusBarEnd,
  seriesRefreshQuery,
  withoutFocusBarEnd,
} from '../src/utils/marketChartEntry.ts'

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

test('accepts focus_bar_end for an actual-dominant supported period with a valid timezone-aware instant', () => {
  assert.equal(resolveFocusBarEnd('2026-09-02T02:45:00Z', {
    seriesKind: 'actual_dominant', frequency: '15m',
  }), '2026-09-02T02:45:00Z')
  assert.equal(resolveFocusBarEnd('2026-09-02T02:45:00', {
    seriesKind: 'actual_dominant', frequency: '15m',
  }), null)
  assert.equal(resolveFocusBarEnd('2026-02-30T02:45:00Z', {
    seriesKind: 'actual_dominant', frequency: '15m',
  }), null)
  assert.equal(resolveFocusBarEnd('2026-09-02T02:45:00Z', {
    seriesKind: 'continuous', frequency: '15m',
  }), null)
  assert.equal(resolveFocusBarEnd('2026-09-02T02:45:00Z', {
    seriesKind: 'actual_dominant', frequency: '30m',
  }), '2026-09-02T02:45:00Z')
})

test('removes only focus_bar_end after its one-shot attempt', () => {
  assert.deepEqual(withoutFocusBarEnd({
    symbol: 'jm', series_kind: 'actual_dominant', frequency: '15m', overlay: 'htdy',
    focus_bar_end: '2026-09-02T02:45:00Z',
  }), {
    symbol: 'jm', series_kind: 'actual_dominant', frequency: '15m', overlay: 'htdy',
  })
})

test('consumes a valid matching focus exactly once through the existing reveal seam', () => {
  const calls: string[] = []
  const identity = { seriesKind: 'actual_dominant' as const, frequency: '15m' as const }
  assert.equal(consumeFocusBarEnd('2026-09-02T02:45:00Z', identity, (value) => {
    calls.push(value)
    return false
  }), true)
  assert.deepEqual(calls, ['2026-09-02T02:45:00Z'])
  assert.equal(consumeFocusBarEnd('2026-09-02T02:45:00Z', {
    seriesKind: 'continuous', frequency: '15m',
  }, () => true), false)
})

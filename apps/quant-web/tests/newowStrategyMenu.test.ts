import assert from 'node:assert/strict'
import test from 'node:test'
import { newowMenuIdentity } from '../src/utils/newowStrategyMenu.ts'
import type { MarketDetailIdentity } from '../src/types/marketDetail.ts'

const identity: MarketDetailIdentity = { view: 'newow', symbol: 'rb', strategy: 'trend', seriesKind: 'actual_dominant', frequency: '60m', newowMode: 'dual', focusBarEnd: '2026-10-09T07:00:00Z' }
test('T menu selects standalone main-rise while retaining product and supported period', () => {
  assert.deepEqual(newowMenuIdentity(identity, 'main_rise'), { view: 'newow', symbol: 'rb', strategy: 'main_rise', seriesKind: 'actual_dominant', frequency: '60m' })
})
test('main-rise selection does not request unsupported short periods', () => {
  for (const frequency of ['1m', '5m', '15m', '30m'] as const) assert.equal(newowMenuIdentity({ ...identity, frequency }, 'main_rise').frequency, '1d')
  for (const frequency of ['1d', '1w', '60m'] as const) assert.equal(newowMenuIdentity({ ...identity, frequency }, 'main_rise').frequency, frequency)
})
test('base option leaves main-rise for independent oscillation without stale focus or dual mode', () => {
  assert.deepEqual(newowMenuIdentity({ ...identity, strategy: 'main_rise', frequency: '1w' }, 'oscillation'), { view: 'newow', symbol: 'rb', strategy: 'oscillation', seriesKind: 'actual_dominant', frequency: '1w' })
})

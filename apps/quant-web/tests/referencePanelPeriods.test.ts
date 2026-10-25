import test from 'node:test'
import assert from 'node:assert/strict'
import { referencePanelSupported } from '../src/utils/referencePanelPeriods.ts'

const periods = ['1m', '5m', '15m', '30m', '60m', '1d', '1w']
test('HTDY reference panel appears only at 60m', () => {
  assert.deepEqual(periods.filter(period => referencePanelSupported('htdy', period)), ['60m'])
})
test('SuBing reference panel appears only at 15m, 30m, 60m and D1', () => {
  for (const strategy of ['subing-reference', 'subing_reference']) {
    assert.deepEqual(periods.filter(period => referencePanelSupported(strategy, period)), ['15m', '30m', '60m', '1d'])
  }
})
test('reference panels require actual dominant and a known strategy', () => {
  assert.equal(referencePanelSupported('htdy', '60m', 'actual_dominant'), true)
  for (const series of ['continuous', 'contract']) assert.equal(referencePanelSupported('subing-reference', '15m', series), false)
  assert.equal(referencePanelSupported('unknown', '15m'), false)
})

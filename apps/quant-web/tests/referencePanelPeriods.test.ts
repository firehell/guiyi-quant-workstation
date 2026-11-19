import test from 'node:test'
import assert from 'node:assert/strict'
import { referencePanelSupported } from '../src/utils/referencePanelPeriods.ts'

const periods = ['1m', '5m', '15m', '30m', '60m', '1d', '1w']
test('HTDY and SuBing reference panels are retired at every period', () => {
  for (const strategy of ['htdy', 'subing-reference', 'subing_reference']) {
    assert.deepEqual(periods.filter(period => referencePanelSupported(strategy, period)), [])
  }
})
test('only Newow reference panels support the six reference periods', () => {
  for (const strategy of ['newow_trend', 'newow_oscillation', 'newow_main_rise', 'newow_dual_fusion']) {
    assert.deepEqual(periods.filter(period => referencePanelSupported(strategy, period)), periods.slice(1))
  }
})
test('reference panels require actual dominant and a known strategy', () => {
  assert.equal(referencePanelSupported('newow_trend', '60m', 'actual_dominant'), true)
  for (const series of ['continuous', 'contract']) assert.equal(referencePanelSupported('newow_trend', '15m', series), false)
  assert.equal(referencePanelSupported('unknown', '15m'), false)
})

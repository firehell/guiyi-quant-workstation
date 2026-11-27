import assert from 'node:assert/strict'
import test from 'node:test'
import { newowAuxiliaryLayerStatus, NEWOW_AUXILIARY_OPTIONS, NEWOW_EXTRA_AUXILIARY_OPTIONS, newowPaneId } from '../src/utils/newowAdditionalPanes.ts'

test('Newow MACD is available as an extra pane while the four primary choices remain intact', () => {
  assert.deepEqual(NEWOW_AUXILIARY_OPTIONS.map(option => option.id), ['zhaoyao_mirror', 'up_down_energy', 'main_force_control', 'trend_reversal'])
  assert.equal(NEWOW_EXTRA_AUXILIARY_OPTIONS.at(-1)?.id, 'macd')
  assert.equal(newowPaneId('macd'), 'macd')
})

test('extra pane does not report ready when its current owner, input or renderer evidence is missing', () => {
  assert.equal(newowAuxiliaryLayerStatus('ready', true, false, 'ready', false, null), 'invalid_source')
  assert.equal(newowAuxiliaryLayerStatus('ready', true, true, null, true, null), 'missing_input')
  assert.equal(newowAuxiliaryLayerStatus('ready', true, true, 'unavailable', true, null), 'compute_error')
  assert.equal(newowAuxiliaryLayerStatus('ready', true, true, 'ready', false, null), 'missing_input')
  assert.equal(newowAuxiliaryLayerStatus('warming', true, true, 'warming', false, 'NEWOW_MACD_WARMING'), 'warming')
  assert.equal(newowAuxiliaryLayerStatus('ready', true, true, 'ready', true, null), 'ready')
  assert.equal(newowAuxiliaryLayerStatus('stale', true, true, 'ready', true, 'NEWOW_RESOURCE_BUSY'), 'compute_error')
  assert.equal(newowAuxiliaryLayerStatus('unavailable', true, true, 'ready', true, null), 'compute_error')
  assert.equal(newowAuxiliaryLayerStatus('warming', false, false, null, false, null), 'warming')
  assert.equal(newowAuxiliaryLayerStatus('warming', true, true, 'ready', true, null), 'ready')
  assert.equal(newowAuxiliaryLayerStatus('not_applicable', false, false, null, false, 'NEWOW_AUXILIARY_NOT_APPLICABLE'), 'missing_input')
})

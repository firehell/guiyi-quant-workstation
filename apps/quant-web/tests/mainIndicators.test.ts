import assert from 'node:assert/strict'
import test from 'node:test'
import {
  HTDY_WEB_OBSERVATION_METADATA,
  RESEARCH_OVERLAY_DEFINITIONS,
  normalizeOptionalEmaIndicators,
  researchOverlayCapability,
  visibleMainIndicatorsForOverlay,
} from '../src/utils/mainIndicators.ts'


test('only none and HTDY remain as research overlays', () => {
  assert.deepEqual(RESEARCH_OVERLAY_DEFINITIONS.map((item) => item.id), ['none', 'htdy'])
  assert.equal(researchOverlayCapability('htdy', 'actual_dominant', '15m').supported, true)
  assert.equal(researchOverlayCapability('none', 'contract', '1w').supported, true)
})

test('generic EMA and Range visibility is independent from the selected overlay', () => {
  assert.deepEqual(
    visibleMainIndicatorsForOverlay('none', ['ema_10', 'ema_21', 'ema_60'], true),
    ['ema_10', 'ema_21', 'ema_60', 'range_detector'],
  )
  assert.deepEqual(
    visibleMainIndicatorsForOverlay('htdy', ['ema_21'], false),
    ['ema_21', 'htdy'],
  )
  assert.deepEqual(normalizeOptionalEmaIndicators(['ema_60', 'ema_21', 'ema_10', 'ema_21']), [
    'ema_10', 'ema_21', 'ema_60',
  ])
})




test('HTDY remains explicitly repainting and observation-only', () => {
  assert.equal(HTDY_WEB_OBSERVATION_METADATA.status, 'observation_only')
  assert.equal(HTDY_WEB_OBSERVATION_METADATA.future_looking, true)
  assert.equal(HTDY_WEB_OBSERVATION_METADATA.historical_backtest_allowed, false)
})

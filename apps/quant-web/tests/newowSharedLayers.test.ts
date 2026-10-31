import assert from 'node:assert/strict'
import test from 'node:test'
import { buildNewowFixtureEnvelopeForTest, NEWOW_AS_OF } from '../e2e/newow-product.helpers.mjs'
import { normalizeNewowProductResponse } from '../src/utils/newowProductTypes.ts'
import { canShareNewowAuxiliary } from '../src/utils/newowSharedLayers.ts'
import { alignNewowAuxiliaryChartModel } from '../src/components/market/detail/newow/newowProductChartPrimitives.ts'

function response(section: 'chart' | 'auxiliary', strategy: 'trend' | 'oscillation') {
  const component = 'main_force_control'
  const wire = buildNewowFixtureEnvelopeForTest(section, strategy, '1d', false, null, { component })
  wire.meta.shared_input_proof = { schema_version: 'newow_shared_input_proof_v1', market_input_sha256: 'a'.repeat(64), auxiliary_input_sha256: section === 'auxiliary' ? 'b'.repeat(64) : null }
  return normalizeNewowProductResponse(wire, { product: 'rb', strategy, frequency: '1d', seriesKind: 'actual_dominant', section, component, asOf: NEWOW_AS_OF })
}

test('shared auxiliary uses full market proof and preserves the original strategy and token', () => {
  const chart = response('chart', 'oscillation')
  const auxiliary = response('auxiliary', 'trend')
  const before = JSON.stringify(auxiliary)
  assert.equal(canShareNewowAuxiliary(chart, auxiliary, 'main_force_control'), true)
  assert.equal(JSON.stringify(auxiliary), before)
  assert.notEqual(chart.meta.snapshot_token, auxiliary.meta.snapshot_token)
  assert.ok(alignNewowAuxiliaryChartModel(chart, auxiliary)?.series.length)
})

test('legacy, changed full inputs, cutoff, quality, formula and owners cannot share', () => {
  const chart = response('chart', 'oscillation')
  const auxiliary = response('auxiliary', 'trend')
  for (const mutate of [
    (copy) => { delete copy.meta.shared_input_proof },
    (copy) => { copy.meta.shared_input_proof.market_input_sha256 = 'c'.repeat(64) },
    (copy) => { copy.meta.shared_input_proof.auxiliary_input_sha256 = null },
    (copy) => { copy.meta.as_of = '2026-09-03T07:00:00.000001Z' },
    (copy) => { copy.meta.identity.input_quality_policy = 'newow_daily_input_quality_v2' },
    (copy) => { copy.meta.futures_adaptation_version = 'unknown' },
    (copy) => { copy.value.formula_version = 'future-formula' },
    (copy) => { copy.value.segments[0].segment_id = 'other-owner' },
  ]) {
    const copy = structuredClone(auxiliary)
    mutate(copy)
    assert.equal(canShareNewowAuxiliary(chart, copy, 'main_force_control'), false)
    assert.equal(alignNewowAuxiliaryChartModel(chart, copy), null)
  }
  assert.equal(canShareNewowAuxiliary(chart, auxiliary, 'up_down_energy'), false)
})

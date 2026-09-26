import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'
import { buildNewowFixtureEnvelopeForTest } from '../e2e/newow-product.helpers.mjs'
import { newowComparisonCompatible } from '../src/utils/newowComparison.ts'
import { useNewowComparison } from '../src/composables/useNewowComparison.ts'
function chart(strategy = 'trend') { const raw = buildNewowFixtureEnvelopeForTest('chart', strategy, '1d', false, null, { dualMarket: true }); return { meta: raw.meta, section: 'chart', ...raw.chart } }
test('comparison accepts independent tokens only with equal time, market and calculation segment facts', () => {
  const a = chart(), b = chart('oscillation')
  assert.equal(newowComparisonCompatible(a, b), true)
  for (const mutate of [value => { value.meta.as_of = '2026-09-04T08:00:00.000Z' }, value => { value.value.bars[0].close = '777' }, value => { value.value.bars[0].physical_contract = 'RB2610' }, value => { value.value.bars[0].calculation_segment_id = 'different' }, value => { value.value.bars.shift() }, value => { value.meta.identity.strategy = 'main_rise' }]) {
    const copy = structuredClone(b); mutate(copy); assert.equal(newowComparisonCompatible(a, copy), false)
  }
})
test('disabled comparison performs no request and late unabortable response cannot survive identity replacement', async () => {
  const base = ref(chart()), enabled = ref(false)
  const pending = []
  const comparison = useNewowComparison(base, enabled, (request, signal) => new Promise(resolve => pending.push({ request, signal, resolve })))
  assert.equal(pending.length, 0)
  enabled.value = true; assert.equal(pending.length, 1)
  assert.equal(pending[0].request.asOf, base.value.meta.as_of)
  assert.equal(pending[0].request.snapshotToken, undefined)
  enabled.value = false; pending[0].resolve(chart('oscillation'))
  await Promise.resolve(); await Promise.resolve()
  assert.equal(comparison.response.value, null)
  assert.equal(comparison.state.value, 'not_requested')
  assert.equal(pending[0].signal.aborted, true)
  comparison.dispose()
})

test('comparison requests the whole accumulated axis after an older display window was appended', async () => {
  const value = chart()
  value.value.chart_from = '2025-01-01'; value.value.chart_through = '2025-12-31'
  const base = ref(value), enabled = ref(true)
  const requests = []
  const partner = chart('oscillation')
  const comparison = useNewowComparison(base, enabled, async request => { requests.push(request); return partner })
  await Promise.resolve(); await Promise.resolve()
  assert.equal(requests[0].from, '2025-01-01')
  assert.equal(requests[0].through, '2026-08-03')
  assert.equal(comparison.state.value, 'ready')
  comparison.dispose()
})

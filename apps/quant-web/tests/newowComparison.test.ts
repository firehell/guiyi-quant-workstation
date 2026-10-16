import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'
import { buildNewowFixtureEnvelopeForTest } from '../e2e/newow-product.helpers.mjs'
import { newowComparisonCompatible } from '../src/utils/newowComparison.ts'
import { useNewowComparison } from '../src/composables/useNewowComparison.ts'

function chart(strategy = 'trend') {
  const raw = buildNewowFixtureEnvelopeForTest('chart', strategy, '1d', false, null, { dualMarket: true })
  return { meta: raw.meta, section: 'chart', ...raw.chart }
}
async function settle() { for (let index = 0; index < 8; index++) await Promise.resolve() }

test('partner comparison reads its chart only, with the accepted chart window', async () => {
  const base = chart()
  base.value.chart_from = '2025-01-01'
  const requests = []
  const comparison = useNewowComparison(ref(base), ref(true), async request => {
    requests.push(request)
    return chart('oscillation')
  })
  await settle()
  assert.equal(comparison.state.value, 'ready')
  assert.deepEqual(requests.map(request => request.section), ['chart'])
  assert.equal(requests[0].from, '2025-01-01')
  assert.equal(requests[0].through, '2026-09-03')
  assert.equal(comparison.reference.value, null)
  assert.equal(comparison.referenceSettled.value, true)
  comparison.dispose()
})

test('partner chart requires equal time, market and calculation segment facts', () => {
  const a = chart(), b = chart('oscillation')
  assert.equal(newowComparisonCompatible(a, b), true)
  for (const mutate of [
    value => { value.meta.as_of = '2026-09-04T08:00:00.000Z' },
    value => { value.value.bars[0].close = '777' },
    value => { value.value.bars[0].physical_contract = 'RB2610' },
    value => { value.value.bars[0].calculation_segment_id = 'different' },
    value => { value.value.bars.shift() },
    value => { value.meta.identity.strategy = 'main_rise' },
  ]) {
    const copy = structuredClone(b); mutate(copy)
    assert.equal(newowComparisonCompatible(a, copy), false)
  }
})

test('disabled comparison dispatches nothing and rejects a late unabortable chart', async () => {
  const enabled = ref(false), pending = []
  const comparison = useNewowComparison(ref(chart()), enabled, (request, signal) => new Promise(resolve => pending.push({ request, signal, resolve })))
  assert.equal(pending.length, 0)
  assert.equal(comparison.referenceSettled.value, false)
  enabled.value = true
  assert.equal(pending.length, 1)
  assert.equal(pending[0].request.section, 'chart')
  enabled.value = false
  pending[0].resolve(chart('oscillation'))
  await settle()
  assert.equal(pending[0].signal.aborted, true)
  assert.equal(comparison.response.value, null)
  assert.equal(comparison.state.value, 'not_requested')
  comparison.dispose()
})

test('replacement identity cancels the old partner and accepts only the new chart', async () => {
  const base = ref(chart()), pending = []
  const comparison = useNewowComparison(base, ref(true), (request, signal) => new Promise(resolve => pending.push({ request, signal, resolve })))
  assert.equal(pending.length, 1)
  const replacement = chart()
  replacement.meta.identity.product = 'j'
  replacement.meta.identity.frequency = '1w'
  base.value = replacement
  assert.equal(pending.length, 2)
  assert.equal(pending[0].signal.aborted, true)
  pending[0].resolve(chart('oscillation'))
  await settle()
  assert.equal(comparison.response.value, null)
  const partner = chart('oscillation')
  partner.meta.identity.product = 'j'
  partner.meta.identity.frequency = '1w'
  pending[1].resolve(partner)
  await settle()
  assert.equal(comparison.response.value?.meta.identity.product, 'j')
  assert.equal(comparison.response.value?.meta.identity.frequency, '1w')
  comparison.dispose()
})

test('incompatible partner market facts fail closed without reference requests', async () => {
  const partner = chart('oscillation')
  partner.value.bars[0].close = '777'
  const requests = []
  const comparison = useNewowComparison(ref(chart()), ref(true), async request => { requests.push(request); return partner })
  await settle()
  assert.equal(comparison.state.value, 'input_conflict')
  assert.equal(comparison.response.value, null)
  assert.equal(comparison.referenceSettled.value, true)
  assert.deepEqual(requests.map(request => request.section), ['chart'])
  comparison.dispose()
})

test('partner transport failure is terminal until an explicit reload', async () => {
  let calls = 0
  const comparison = useNewowComparison(ref(chart()), ref(true), async () => { calls++; throw Error('network') })
  await settle()
  assert.equal(comparison.state.value, 'unavailable')
  assert.equal(comparison.referenceSettled.value, true)
  assert.equal(calls, 1)
  await comparison.reload()
  assert.equal(calls, 2)
  comparison.dispose()
})

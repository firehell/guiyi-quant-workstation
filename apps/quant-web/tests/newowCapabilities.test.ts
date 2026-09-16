import assert from 'node:assert/strict'
import test from 'node:test'

import { useNewowCapabilities } from '../src/composables/useNewowCapabilities.ts'
import type { NewowProductCapabilities } from '../src/types/newowProduct.ts'

const daily = (): NewowProductCapabilities => ({
  schema_version: 'newow_product_capabilities_v2',
  release_stage: 'daily',
  open_frequencies: ['1w', '1d'],
  deferred_frequencies: [
    { frequency: '60m', reason_code: 'NEWOW_HOURLY_RELEASE_PENDING' },
  ],
  open_sections: ['chart', 'auxiliary', 'reference', 'comparator'],
  deferred_sections: [{ section: 'explanation', reason_code: 'NEWOW_CROSS_FREQUENCY_INPUTS_NOT_OPEN' }],
})

test('capability loader coalesces reads and exposes only server-open facts', async () => {
  let calls = 0
  const state = useNewowCapabilities(async () => { calls += 1; return daily() })
  await Promise.all([state.load(), state.load()])
  assert.equal(calls, 1)
  assert.equal(state.state.value, 'ready')
  assert.deepEqual(state.openFrequencies.value, ['1w', '1d'])
  assert.equal(state.isFrequencyOpen('1w'), true)
  assert.equal(state.isFrequencyOpen('1d'), true)
  assert.equal(state.isFrequencyOpen('60m'), false)
  assert.equal(state.isSectionOpen('reference'), true)
  assert.equal(state.isSectionOpen('explanation'), false)
})

test('capability failure stays unavailable without inventing legacy defaults', async () => {
  const state = useNewowCapabilities(async () => { throw new Error('offline') })
  await state.load()
  assert.equal(state.state.value, 'unavailable')
  assert.deepEqual(state.openFrequencies.value, [])
  assert.equal(state.isFrequencyOpen('1d'), false)
})

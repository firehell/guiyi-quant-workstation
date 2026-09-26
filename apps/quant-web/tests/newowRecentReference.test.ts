import test from 'node:test'
import assert from 'node:assert/strict'
import { ref, nextTick } from 'vue'
import { useNewowRecentReference } from '../src/composables/useNewowRecentReference.ts'
import type { NewowProductRequest, NewowProductSectionResponse } from '../src/types/newowProduct.ts'
const anchor = (token = 'snapshot') => ({ section: 'reference', meta: { snapshot_token: token, as_of: '2026-09-24T07:00:00Z', identity: { product: 'jm', strategy: 'trend', frequency: '1d' } }, value: { performance_since: '2023-01-01', actual_available_through: '2026-09-24', items: [], next_before: null } }) as unknown as NewowProductSectionResponse<'reference'>
const flush = async () => { await nextTick(); await Promise.resolve(); await nextTick() }
test('recent records have an independent three-month window and cursor', async () => {
  const source = ref(anchor())
  const calls: NewowProductRequest[] = []
  const state = useNewowRecentReference(source, async request => {
    calls.push(request)
    return { ...anchor(), value: { ...anchor().value!, items: [], next_before: calls.length === 1 ? 'page2' : null } }
  })
  await flush()
  assert.equal(calls.length, 1)
  assert.equal(calls[0].section, 'reference')
  assert.equal(calls[0].performanceSince, '2026-06-24')
  assert.equal(calls[0].performanceThrough, '2026-09-24')
  // A changed performance window on the same snapshot is not a records reload.
  source.value = { ...source.value, value: { ...source.value.value!, performance_since: '2026-01-01' } }
  await flush()
  assert.equal(calls.length, 1)
  await state.loadMore()
  assert.equal(calls[1].historyBefore, 'page2')
  assert.equal(calls[1].performanceSince, '2026-06-24')
  await state.loadMore()
  assert.equal(calls.length, 2)
})
test('records reject responses from an obsolete chart snapshot', async () => {
  const source = ref(anchor('old'))
  const pending: Array<(value: any) => void> = []
  const state = useNewowRecentReference(source, () => new Promise(resolve => pending.push(resolve)))
  source.value = anchor('new')
  await flush()
  pending[0](anchor('old'))
  await flush()
  assert.equal(state.response.value, null)
  pending[1](anchor('new'))
  await flush()
  assert.equal(state.response.value?.meta.snapshot_token, 'new')
})

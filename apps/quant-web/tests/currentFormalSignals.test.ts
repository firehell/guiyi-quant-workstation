import test from 'node:test'
import assert from 'node:assert/strict'
import { useCurrentFormalSignals } from '../src/composables/useCurrentFormalSignals.ts'

test('ready empty is different from unavailable', async () => {
  const ready = useCurrentFormalSignals({
    fetchCurrent: async () => ({ status: 'ready', trading_day: '2026-08-15', items: [] }),
  })
  await ready.refresh()
  assert.equal(ready.status.value, 'ready')
  assert.deepEqual(ready.items.value, [])
  assert.equal(ready.tradingDay.value, '2026-08-15')

  const unavailable = useCurrentFormalSignals({
    fetchCurrent: async () => ({ status: 'unavailable', trading_day: null, items: [] }),
  })
  await unavailable.refresh()
  assert.equal(unavailable.status.value, 'unavailable')
})

test('network error stays unavailable instead of ready empty', async () => {
  const state = useCurrentFormalSignals({
    fetchCurrent: async () => { throw new Error('network unavailable') },
  })

  await state.refresh()

  assert.equal(state.status.value, 'unavailable')
  assert.deepEqual(state.items.value, [])
  assert.equal(state.tradingDay.value, null)
  assert.equal(state.loading.value, false)
})

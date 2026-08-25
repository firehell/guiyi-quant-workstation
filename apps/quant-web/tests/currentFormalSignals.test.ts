import test from 'node:test'
import assert from 'node:assert/strict'
import { useCurrentFormalSignals } from '../src/composables/useCurrentFormalSignals.ts'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function currentItem(ruleCode: string, displayName: string) {
  return {
    id: ruleCode === 'subing_entry_signal_v1' ? 1 : 2,
    rule_code: ruleCode,
    display_name: displayName,
    symbol: 'jm',
    product_name: '焦煤',
    contract: 'JM2609',
    trading_day: '2026-08-15',
    frequency: '15m' as const,
    bar_end: '2026-08-15T02:30:00Z',
    result_codes: ['buy'] as const,
    lower_tf_confirmation: false,
    detected_at: '2026-08-15T02:31:00Z',
    notification_attempted_at: null,
  }
}

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
  assert.equal(state.stale.value, false)
})

test('a failed refresh preserves the last successful formal snapshot and marks it stale until recovery', async () => {
  let attempt = 0
  const state = useCurrentFormalSignals({
    fetchCurrent: async () => {
      attempt += 1
      if (attempt === 2) throw new Error('temporarily unavailable')
      return {
        status: 'ready' as const,
        trading_day: attempt === 1 ? '2026-08-15' : '2026-08-16',
        items: [currentItem('subing_entry_signal_v1', '苏冰')],
      }
    },
  })

  await state.refresh()
  await state.refresh()
  assert.equal(state.status.value, 'ready')
  assert.equal(state.tradingDay.value, '2026-08-15')
  assert.deepEqual(state.items.value.map((item) => item.id), [1])
  assert.equal(state.stale.value, true)

  await state.refresh()
  assert.equal(state.tradingDay.value, '2026-08-16')
  assert.equal(state.stale.value, false)
})

test('homepage preserves the backend formal-signal response without duplicating rule filtering', async () => {
  const state = useCurrentFormalSignals({
    fetchCurrent: async () => ({
      status: 'ready',
      trading_day: '2026-08-15',
      items: [currentItem('subing_entry_signal_v1', '苏冰')],
    }),
  })

  await state.refresh()

  assert.deepEqual(state.items.value.map((item) => item.rule_code), ['subing_entry_signal_v1'])
})

test('an older formal success and finally cannot overwrite or unlock a newer generation', async () => {
  const first = deferred<{
    status: 'ready'
    trading_day: string
    items: ReturnType<typeof currentItem>[]
  }>()
  const second = deferred<{
    status: 'ready'
    trading_day: string
    items: ReturnType<typeof currentItem>[]
  }>()
  let attempt = 0
  const state = useCurrentFormalSignals({
    fetchCurrent: () => (attempt++ === 0 ? first.promise : second.promise),
  })

  const olderRefresh = state.refresh()
  const newerRefresh = state.refresh()
  first.resolve({
    status: 'ready',
    trading_day: '2026-08-14',
    items: [currentItem('htdy_original_15m', '火天大有')],
  })
  await olderRefresh

  assert.equal(state.loading.value, true)
  assert.equal(state.status.value, null)

  second.resolve({
    status: 'ready',
    trading_day: '2026-08-15',
    items: [currentItem('subing_entry_signal_v1', '苏冰')],
  })
  await newerRefresh

  assert.equal(state.loading.value, false)
  assert.equal(state.tradingDay.value, '2026-08-15')
  assert.deepEqual(state.items.value.map((item) => item.rule_code), ['subing_entry_signal_v1'])
})

test('invalidating formal state prevents a pending request from updating after unmount', async () => {
  const pending = deferred<{
    status: 'ready'
    trading_day: string
    items: ReturnType<typeof currentItem>[]
  }>()
  const state = useCurrentFormalSignals({ fetchCurrent: () => pending.promise })

  const refresh = state.refresh()
  state.invalidate()
  pending.resolve({
    status: 'ready',
    trading_day: '2026-08-15',
    items: [currentItem('subing_entry_signal_v1', '苏冰')],
  })
  await refresh

  assert.equal(state.loading.value, false)
  assert.equal(state.status.value, null)
  assert.deepEqual(state.items.value, [])
})

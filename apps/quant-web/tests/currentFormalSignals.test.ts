import test from 'node:test'
import assert from 'node:assert/strict'
import { useCurrentFormalSignals } from '../src/composables/useCurrentFormalSignals.ts'

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
})

test('homepage formal signals fail closed against HTDY observations', async () => {
  const state = useCurrentFormalSignals({
    fetchCurrent: async () => ({
      status: 'ready',
      trading_day: '2026-08-15',
      items: [
        currentItem('subing_entry_signal_v1', '苏冰'),
        currentItem('htdy_original_15m', '火天大有'),
      ],
    }),
  })

  await state.refresh()

  assert.deepEqual(state.items.value.map((item) => item.rule_code), ['subing_entry_signal_v1'])
})

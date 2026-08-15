import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { nextTick, ref } from 'vue'
import { useProductCurrentAlertEvents } from '../src/composables/useProductCurrentAlertEvents.ts'
import type { AlertEvent } from '../src/types/market.ts'

const todayEventsSource = readFileSync(new URL('../src/components/market/ProductTodayAlertEvents.vue', import.meta.url), 'utf-8')
const formalSignalSource = readFileSync(new URL('../src/components/market/ProductFormalSignalCard.vue', import.meta.url), 'utf-8')

test('drops a stale response after the product symbol changes', async () => {
  const symbol = ref('ag')
  const resolvers = new Map<string, (response: { status: 'ready'; trading_day: string; items: AlertEvent[] }) => void>()
  const state = useProductCurrentAlertEvents({
    symbol,
    fetchCurrentEvents: (requestedSymbol) => new Promise((resolve) => resolvers.set(requestedSymbol, resolve)),
  })

  const oldRequest = state.refresh()
  symbol.value = 'jm'
  await nextTick()
  resolvers.get('jm')!({ status: 'ready', trading_day: '2026-08-15', items: [event(2)] })
  await nextTick()
  resolvers.get('ag')!({ status: 'ready', trading_day: '2026-08-14', items: [event(1)] })
  await oldRequest

  assert.deepEqual(state.items.value.map((item) => item.id), [2])
  assert.equal(state.tradingDay.value, '2026-08-15')
  state.dispose()
})

test('keeps a ready empty response distinct from unavailable', async () => {
  const state = useProductCurrentAlertEvents({
    symbol: ref('ag'),
    fetchCurrentEvents: async () => ({ status: 'ready', trading_day: '2026-08-15', items: [] }),
  })

  await state.refresh()

  assert.equal(state.status.value, 'ready')
  assert.equal(state.tradingDay.value, '2026-08-15')
  assert.deepEqual(state.items.value, [])
  state.dispose()
})

test('converts a current-events network error to unavailable', async () => {
  const state = useProductCurrentAlertEvents({
    symbol: ref('ag'),
    fetchCurrentEvents: async () => { throw new Error('network unavailable') },
  })

  await state.refresh()

  assert.equal(state.status.value, 'unavailable')
  assert.equal(state.tradingDay.value, null)
  assert.deepEqual(state.items.value, [])
  assert.equal(state.loading.value, false)
  state.dispose()
})

test('preserves the backend bar_end descending order', async () => {
  const state = useProductCurrentAlertEvents({
    symbol: ref('ag'),
    fetchCurrentEvents: async () => ({
      status: 'ready',
      trading_day: '2026-08-15',
      items: [event(3), event(2), event(1)],
    }),
  })

  await state.refresh()

  assert.deepEqual(state.items.value.map((item) => item.id), [3, 2, 1])
  state.dispose()
})

test('uses a stable safe fallback for an unknown current-event rule', () => {
  assert.match(todayEventsSource, /return '未知提醒'/)
  assert.match(todayEventsSource, /v-for="item in items"/)
})

test('keeps the primary signal card restricted to resolved MATCHED signals', () => {
  assert.match(formalSignalSource, /resolved_signal/)
  assert.doesNotMatch(formalSignalSource, /primary_signal/)
  assert.match(formalSignalSource, /5m 同向确认/)
})

function event(id: number): AlertEvent {
  return {
    id,
    rule_code: 'subing_entry_signal_v1',
    symbol: 'ag',
    contract: 'AG2610',
    trading_day: '2026-08-15',
    frequency: '15m',
    bar_end: `2026-08-15T0${id}:00:00Z`,
    result_codes: ['buy'],
    lower_tf_confirmation: false,
    detected_at: '2026-08-15T01:00:01Z',
    notification_attempted_at: null,
  }
}

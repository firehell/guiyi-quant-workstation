import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { ref } from 'vue'
import { useProductCurrentAlertEvents } from '../src/composables/useProductCurrentAlertEvents.ts'
import type { AlertEvent } from '../src/types/market.ts'
import {
  alertEventDirectionalTone,
  alertEventResultLabel,
  alertEventRuleShortLabel,
} from '../src/utils/alertRules.ts'

const legacyChartSource = readFileSync(new URL('../src/pages/market/LegacyMarketChart.vue', import.meta.url), 'utf-8')
const sidebarSource = readFileSync(new URL('../src/components/market/ProductCheckSidebar.vue', import.meta.url), 'utf-8')

test('current events refresh only on an explicit call', async () => {
  const symbol = ref('ag')
  const requests: string[] = []
  const state = useProductCurrentAlertEvents({
    symbol,
    fetchCurrentEvents: async (requestedSymbol) => {
      requests.push(requestedSymbol)
      return { status: 'ready', trading_day: '2026-08-15', items: [] }
    },
  })
  symbol.value = 'jm'
  await Promise.resolve()
  assert.deepEqual(requests, [])
  await state.refresh()
  assert.deepEqual(requests, ['jm'])
  state.dispose()
})

test('identity invalidation drops an older response', async () => {
  const symbol = ref('ag')
  const resolvers: Array<(response: { status: 'ready'; trading_day: string; items: AlertEvent[] }) => void> = []
  const state = useProductCurrentAlertEvents({
    symbol,
    fetchCurrentEvents: () => new Promise((resolve) => resolvers.push(resolve)),
  })
  const oldRequest = state.refresh()
  state.invalidateIdentity()
  const finalRequest = state.refresh()
  resolvers[1]!({ status: 'ready', trading_day: '2026-08-15', items: [event(2)] })
  await finalRequest
  resolvers[0]!({ status: 'ready', trading_day: '2026-08-14', items: [event(1)] })
  await oldRequest
  assert.deepEqual(state.items.value.map((item) => item.id), [2])
  state.dispose()
})

test('network failure becomes unavailable without stale items', async () => {
  const state = useProductCurrentAlertEvents({
    symbol: ref('ag'),
    fetchCurrentEvents: async () => { throw new Error('network unavailable') },
  })
  await state.refresh()
  assert.equal(state.status.value, 'unavailable')
  assert.equal(state.tradingDay.value, null)
  assert.deepEqual(state.items.value, [])
  state.dispose()
})

test('HTDY labels and combined direction remain observation-only', () => {
  const single = event(1)
  const combined = { ...event(2), result_codes: ['buy', 'sell'] as ['buy', 'sell'] }
  assert.equal(alertEventRuleShortLabel(single), '火天大有')
  assert.equal(alertEventResultLabel(single, single.result_codes), '买入观察')
  assert.equal(alertEventDirectionalTone(single, single.result_codes), 'buy')
  assert.equal(alertEventResultLabel(combined, combined.result_codes), '买入/卖出观察')
  assert.equal(alertEventDirectionalTone(combined, combined.result_codes), null)
})

test('sidebar observation is derived from the latest HTDY marker', () => {
  assert.match(legacyChartSource, /selectedOverlay\.value !== 'htdy'/)
  assert.match(legacyChartSource, /buildKlineDerivedData\(bars\.value, \['htdy'\]\)/)
  assert.match(legacyChartSource, /htdy\?\.markers\.at\(-1\) \?\? null/)
  assert.match(sidebarSource, /htdyObservation: KlineMarker \| null/)
  assert.match(sidebarSource, /v-if="htdyObservation"/)
})

function event(id: number): AlertEvent {
  return {
    id,
    rule_code: 'htdy_original_15m',
    symbol: 'ag',
    contract: 'AG2610',
    trading_day: '2026-08-15',
    frequency: '15m',
    bar_end: `2026-08-15T0${id}:00:00Z`,
    result_codes: ['buy'],
    detected_at: '2026-08-15T01:00:01Z',
    notification_attempted_at: null,
  }
}

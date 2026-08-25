import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { ref } from 'vue'
import { useProductCurrentAlertEvents } from '../src/composables/useProductCurrentAlertEvents.ts'
import type { AlertEvent } from '../src/types/market.ts'
import {
  alertDirectionalTone,
  alertResultLabel,
  alertRuleShortLabel,
} from '../src/utils/alertRules.ts'

const chartSource = readFileSync(new URL('../src/pages/market/chart.vue', import.meta.url), 'utf-8')
const sidebarSource = readFileSync(new URL('../src/components/market/ProductCheckSidebar.vue', import.meta.url), 'utf-8')

test('does not refresh merely because the product symbol changes', async () => {
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

test('invalidates old facts synchronously and drops an earlier same-symbol response', async () => {
  const symbol = ref('ag')
  const resolvers: Array<(response: { status: 'ready'; trading_day: string; items: AlertEvent[] }) => void> = []
  const state = useProductCurrentAlertEvents({
    symbol,
    fetchCurrentEvents: () => new Promise((resolve) => resolvers.push(resolve)),
  })

  const oldRequest = state.refresh()
  state.invalidateIdentity()
  assert.equal(state.loading.value, true)
  assert.equal(state.status.value, null)
  assert.equal(state.tradingDay.value, null)
  assert.deepEqual(state.items.value, [])
  symbol.value = 'jm'
  state.invalidateIdentity()
  symbol.value = 'ag'
  const finalRequest = state.refresh()
  resolvers[1]({ status: 'ready', trading_day: '2026-08-15', items: [event(2)] })
  await finalRequest
  resolvers[0]({ status: 'ready', trading_day: '2026-08-14', items: [event(1)] })
  await oldRequest

  assert.deepEqual(state.items.value.map((item) => item.id), [2])
  assert.equal(state.tradingDay.value, '2026-08-15')
  state.dispose()
})

test('marks an invalidated identity unavailable without restoring old items', async () => {
  const state = useProductCurrentAlertEvents({
    symbol: ref('ag'),
    fetchCurrentEvents: async () => ({ status: 'ready', trading_day: '2026-08-15', items: [event(1)] }),
  })
  await state.refresh()

  state.invalidateIdentity()
  state.markUnavailable()

  assert.equal(state.status.value, 'unavailable')
  assert.equal(state.tradingDay.value, null)
  assert.deepEqual(state.items.value, [])
  assert.equal(state.loading.value, false)
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

test('does not infer a formal or observation result for an unknown current-event rule', () => {
  const unknown = eventWith({ rule_code: 'future_rule', result_codes: ['buy'] })

  assert.equal(alertRuleShortLabel(unknown.rule_code), '未知提醒')
  assert.equal(alertResultLabel(unknown.rule_code, unknown.result_codes), '提醒记录')
  assert.equal(alertDirectionalTone(unknown.rule_code, unknown.result_codes), null)
})

test('preserves legal combined HTDY and SuBing current-event directions without coloring them as one direction', () => {
  assert.equal(alertResultLabel('htdy_original_15m', ['buy', 'sell']), '买入/卖出观察')
  assert.equal(alertResultLabel('subing_entry_signal_v1', ['buy', 'sell']), '买入/卖出信号')
  assert.equal(alertDirectionalTone('htdy_original_15m', ['buy', 'sell']), null)
  assert.equal(alertDirectionalTone('subing_entry_signal_v1', ['buy', 'sell']), null)
})

test('keeps an unknown combined current event fail-closed', () => {
  const unknown = eventWith({ rule_code: 'future_rule', result_codes: ['buy', 'sell'] })

  assert.equal(alertRuleShortLabel(unknown.rule_code), '未知提醒')
  assert.equal(alertResultLabel(unknown.rule_code, unknown.result_codes), '提醒记录')
  assert.equal(alertDirectionalTone(unknown.rule_code, unknown.result_codes), null)
})

test('derives the sidebar HTDY observation from the latest existing HTDY marker', () => {
  assert.match(
    chartSource,
    /if \(!htdyVisible\.value \|\| !overlayCapability\.value\.supported\) return null/,
  )
  assert.match(chartSource, /buildKlineDerivedData\(visibleBars\.value, \['htdy'\]\)/)
  assert.ok(
    chartSource.indexOf(
      'if (!htdyVisible.value || !overlayCapability.value.supported) return null',
    )
      < chartSource.indexOf("buildKlineDerivedData(visibleBars.value, ['htdy'])"),
  )
  assert.match(chartSource, /htdy\?\.markers\.at\(-1\) \?\? null/)
  assert.doesNotMatch(chartSource, /htdyVisible && visibleBars\.length > 0/)
  assert.match(sidebarSource, /htdyObservation: KlineMarker \| null/)
  assert.match(sidebarSource, /v-if="htdyObservation"/)
  assert.match(sidebarSource, /htdyObservationLabel\(htdyObservation\)/)
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

function eventWith(overrides: Pick<AlertEvent, 'rule_code' | 'result_codes'>): AlertEvent {
  return { ...event(9), ...overrides }
}

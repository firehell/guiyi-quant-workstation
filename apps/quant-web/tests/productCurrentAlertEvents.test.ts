import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import test from 'node:test'
import { nextTick, ref } from 'vue'
import { useProductCurrentAlertEvents } from '../src/composables/useProductCurrentAlertEvents.ts'
import type { AlertEvent } from '../src/types/market.ts'
import {
  alertDirectionalTone,
  alertResultLabel,
  alertRuleShortLabel,
} from '../src/utils/alertRules.ts'

const todayEventsSource = readFileSync(new URL('../src/components/market/ProductTodayAlertEvents.vue', import.meta.url), 'utf-8')
const subingPanelUrl = new URL('../src/components/market/SubingPanel.vue', import.meta.url)
const subingPanelSource = existsSync(subingPanelUrl) ? readFileSync(subingPanelUrl, 'utf-8') : ''
const chartSource = readFileSync(new URL('../src/pages/market/chart.vue', import.meta.url), 'utf-8')
const sidebarSource = readFileSync(new URL('../src/components/market/ProductCheckSidebar.vue', import.meta.url), 'utf-8')

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
  assert.match(todayEventsSource, /alertRuleShortLabel\(ruleCode\)/)
  assert.match(todayEventsSource, /v-for="item in items"/)
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

test('keeps the SuBing formal section sourced only from recorded SuBing AlertEvents', () => {
  assert.match(subingPanelSource, /event\.rule_code === ALERT_RULE_CODES\.SUBING/)
  assert.match(subingPanelSource, /summarizeFormalEvent\(subingEvents\.value, props\.currentEventStates\)/)
  assert.match(subingPanelSource, /data-testid="subing-formal-event"/)
  assert.match(subingPanelSource, /今日正式提醒记录/)
  assert.doesNotMatch(sidebarSource, /summarizeFormalEvent/)
  assert.match(sidebarSource, /v-if="currentEventsLoading"/)
  assert.match(sidebarSource, /currentEventsStatus === 'unavailable'/)
  assert.match(sidebarSource, /currentEventsStatus === 'ready'/)
  assert.doesNotMatch(subingPanelSource, /status="ready"/)
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

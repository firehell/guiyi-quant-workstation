import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'

import { alertRuntimeLabel, isCurrentAlertMutation } from '../src/utils/alertControl.ts'
import {
  alertEventsToMarkers,
  isPersistentAlertIdentity,
  mergeKlineMarkers,
} from '../src/utils/alertMarkers.ts'
import { usePersistentAlertMarkers } from '../src/composables/usePersistentAlertMarkers.ts'
import { useProductAlertScope } from '../src/composables/useProductAlertScope.ts'
import { ref } from 'vue'
import type { AlertEvent } from '../src/api/alerts.ts'
import type { BarData } from '../src/types/market.ts'


const apiSource = read('../src/api/alerts.ts')
const marketTypesSource = read('../src/types/market.ts')
const controlSource = read('../src/components/market/ProductAlertControl.vue')
const chartSource = read('../src/pages/market/chart.vue')
const scopeSource = read('../src/composables/useProductAlertScope.ts')


describe('Product Alert server-side scope', () => {
  it('uses the exact GET and PUT server API contracts without localStorage truth', () => {
    assert.match(apiSource, /`\/api\/alerts\/products\/\$\{symbol\}`/)
    assert.match(apiSource, /`\/api\/alerts\/rules\/\$\{ruleCode\}\/scope\/\$\{symbol\}`/)
    assert.match(apiSource, /\{ enabled \}/)
    assert.doesNotMatch(apiSource, /localStorage|sessionStorage/)
    assert.doesNotMatch(chartSource, /localStorage.*alert|alert.*localStorage/i)
  })

  it('uses the exact V2 current-view endpoints', () => {
    assert.match(
      apiSource,
      /getCurrentFormalSignals\(\)\s*\{\s*return request\.get<never, CurrentFormalSignalsResponse>\('\/api\/alerts\/formal-signals\/current'\)/,
    )
    assert.match(
      apiSource,
      /getProductCurrentAlertEvents\(symbol: string\)\s*\{\s*return request\.get<never, ProductCurrentAlertEventsResponse>\(\s*`\/api\/alerts\/products\/\$\{symbol\}\/current-events`,/,
    )
  })

  it('declares only the backend V2 rule and event DTO fields', () => {
    assert.deepEqual(interfaceFields(apiSource, 'ProductAlertRuleState'), [
      'rule_code: string',
      'display_name: string',
      'kind: AlertRuleKind',
      'input_frequencies: MarketFrequency[]',
      'enabled_for_product: boolean',
    ])
    assert.deepEqual(interfaceFields(marketTypesSource, 'AlertEvent'), [
      'id: number',
      'rule_code: string',
      'symbol: string',
      'contract: string',
      'trading_day: string | null',
      'frequency: MarketFrequency',
      'bar_end: string',
      "result_codes: Array<'buy' | 'sell'>",
      'lower_tf_confirmation: boolean',
      'detected_at: string',
      'notification_attempted_at: string | null',
    ])
    assert.deepEqual(interfaceFields(apiSource, 'CurrentFormalSignalItem'), [
      'display_name: string',
      'product_name: string',
    ])
    assert.deepEqual(interfaceFields(apiSource, 'CurrentFormalSignalsResponse'), [
      "status: 'ready' | 'unavailable'",
      'trading_day: string | null',
      'items: CurrentFormalSignalItem[]',
    ])
    assert.deepEqual(interfaceFields(apiSource, 'ProductCurrentAlertEventsResponse'), [
      "status: 'ready' | 'unavailable'",
      'trading_day: string | null',
      'items: AlertEvent[]',
    ])
  })

  it('drops V1 rule shape fields in favor of the V2 rule registry contract', () => {
    assert.doesNotMatch(interfaceBody(apiSource, 'ProductAlertRuleState'), /indicator_code|series_kind|frequency:/)
    assert.doesNotMatch(interfaceBody(marketTypesSource, 'AlertEvent'), /observation_types|notified_at/)
  })

  it('renders the switch directly from server true or false and emits the selected value', () => {
    assert.match(controlSource, /rule\?\.enabled_for_product \|\| false/)
    assert.match(controlSource, /@update:value="emit\('toggle', \$event\)"/)
    assert.match(scopeSource, /alertRule\.value = updated/)
  })

  it('refetches on symbol change while series/frequency changes never invoke scope PUT', () => {
    const symbolWatcher = between(chartSource, 'watch(symbol, async () => {', 'watch([contract, seriesKind, frequency]')
    const identityWatcher = between(chartSource, 'watch([contract, seriesKind, frequency]', 'watch([symbol, seriesKind, contract]')
    assert.match(symbolWatcher, /refreshAlerts\(\)/)
    assert.doesNotMatch(identityWatcher, /setAlertProductEnabled|toggleAlert/)
    assert.match(
      scopeSource,
      /setProductEnabled\([\s\S]*current\.rule_code,[\s\S]*requestedSymbol,[\s\S]*enabled/,
    )
  })

  it('maps Runtime health to the three fixed labels', () => {
    assert.equal(alertRuntimeLabel('ok'), '正常')
    assert.equal(alertRuntimeLabel('disabled'), '未启用')
    assert.equal(alertRuntimeLabel('degraded'), '不可用')
    assert.equal(alertRuntimeLabel('failed'), '不可用')
  })

  it('rejects an old AG PUT response after AG to JM to AG generation changes', () => {
    assert.equal(isCurrentAlertMutation({
      requestGeneration: 1,
      currentGeneration: 3,
      requestedSymbol: 'ag',
      currentSymbol: 'ag',
      requestedRuleCode: 'htdy_original_15m',
      currentRuleCode: 'htdy_original_15m',
      updatedRuleCode: 'htdy_original_15m',
    }), false)
    assert.equal(isCurrentAlertMutation({
      requestGeneration: 3,
      currentGeneration: 3,
      requestedSymbol: 'ag',
      currentSymbol: 'ag',
      requestedRuleCode: 'htdy_original_15m',
      currentRuleCode: 'htdy_original_15m',
      updatedRuleCode: 'htdy_original_15m',
    }), true)
  })

  it('keeps only the latest symbol scope response after page lifecycle extraction', async () => {
    const symbol = ref('ag')
    const resolvers = new Map<string, (value: { symbol: string; rules: never[] }) => void>()
    const controller = useProductAlertScope({
      symbol,
      fetchProductAlerts: (requestedSymbol) => new Promise((resolve) => {
        resolvers.set(requestedSymbol, resolve)
      }),
      fetchRuntimeStatus: async () => 'ok',
      setProductEnabled: async () => { throw new Error('not used') },
      notifyError: () => undefined,
    })

    const oldRequest = controller.refresh()
    symbol.value = 'jm'
    const currentRequest = controller.refresh()
    resolvers.get('jm')!({ symbol: 'jm', rules: [] })
    await currentRequest
    resolvers.get('ag')!({ symbol: 'ag', rules: [] })
    await oldRequest

    assert.equal(controller.alertRuntimeStatus.value, 'ok')
    assert.equal(controller.alertLoading.value, false)
    controller.dispose()
  })

  it('builds one persistent bell marker for buy, sell, or buy+sell only', () => {
    assert.deepEqual(alertEventsToMarkers([
      event(1, ['buy']),
      event(2, ['sell']),
      event(3, ['buy', 'sell']),
    ]).map((marker) => [marker.id, marker.label]), [
      ['alert:htdy_original_15m:ag:2026-08-13T02:15:00Z', '🔔买'],
      ['alert:htdy_original_15m:ag:2026-08-13T02:30:00Z', '🔔卖'],
      ['alert:htdy_original_15m:ag:2026-08-13T02:45:00Z', '🔔买/卖'],
    ])
  })

  it('keeps persistent bells independent from current repainting HTDY markers', () => {
    const persistent = alertEventsToMarkers([event(3, ['buy', 'sell'])])
    assert.deepEqual(mergeKlineMarkers([], persistent), persistent)
    assert.deepEqual(
      mergeKlineMarkers([{ ...persistent[0], id: 'htdy:old', label: '买观察' }], persistent)
        .map((marker) => marker.id),
      ['htdy:old', persistent[0].id],
    )
    assert.deepEqual(mergeKlineMarkers([], persistent), persistent)
  })

  it('sorts merged current and persistent markers by bar time and stable id', () => {
    const marker = (id: string, time: string) => ({
      id,
      time,
      label: id,
      tooltip: id,
      color: '#fff',
      position: 'aboveBar' as const,
      shape: 'square' as const,
    })

    assert.deepEqual(
      mergeKlineMarkers(
        [marker('current:1100', '2026-08-13T03:00:00Z'), marker('current:1000', '2026-08-13T02:00:00Z')],
        [marker('persistent:b', '2026-08-13T02:30:00Z'), marker('persistent:a', '2026-08-13T02:30:00Z')],
      ).map((item) => item.id),
      ['current:1000', 'persistent:a', 'persistent:b', 'current:1100'],
    )
  })

  it('enables persistent reads only for actual_dominant 15m', () => {
    assert.equal(isPersistentAlertIdentity('actual_dominant', '15m'), true)
    assert.equal(isPersistentAlertIdentity('continuous', '15m'), false)
    assert.equal(isPersistentAlertIdentity('contract', '15m'), false)
    assert.equal(isPersistentAlertIdentity('actual_dominant', '30m'), false)
  })

  it('fetches initial/prepend/recent ranges, dedups, and clears timer off identity', async () => {
    const requests: Array<{ start: string; end: string }> = []
    const scheduled: Array<() => void> = []
    const cleared: unknown[] = []
    let response: AlertEvent[] = [event(3, ['buy'])]
    const controller = usePersistentAlertMarkers({
      fetchEvents: async (params) => {
        requests.push({ start: params.start, end: params.end })
        return { items: response }
      },
      scheduleInterval: (callback, delay) => {
        assert.equal(delay, 30_000)
        scheduled.push(callback)
        return scheduled.length
      },
      clearInterval: (handle) => cleared.push(handle),
    })
    const initialBars = bars('2026-08-13T02:30:00Z', '2026-08-13T02:45:00Z')

    await controller.sync(identity(), initialBars, 'replace')
    assert.equal(requests.length, 1)
    assert.equal(controller.markers.value.length, 1)

    response = [event(1, ['sell']), event(3, ['buy'])]
    await controller.sync(
      identity(),
      bars('2026-08-13T02:15:00Z', ...initialBars),
      'prepend',
    )
    assert.equal(requests.length, 2)
    assert.equal(controller.markers.value.length, 2)

    await scheduled.at(-1)!()
    assert.equal(requests.length, 3)
    assert.match(requests.at(-1)!.start, /2026-08-13/)

    await controller.sync({ ...identity(), seriesKind: 'continuous' }, initialBars, 'replace')
    assert.deepEqual(controller.markers.value, [])
    assert.ok(cleared.length >= 1)
    controller.dispose()
  })
})


function read(relative: string) {
  return readFileSync(new URL(relative, import.meta.url), 'utf-8')
}

function between(source: string, start: string, end: string) {
  const from = source.indexOf(start)
  const to = source.indexOf(end, from + start.length)
  assert.notEqual(from, -1)
  assert.notEqual(to, -1)
  return source.slice(from, to)
}

function interfaceBody(source: string, name: string) {
  const match = source.match(new RegExp(`export interface ${name}(?: extends [^{]+)? \\{([\\s\\S]*?)\\n\\}`))
  assert.ok(match, `missing interface ${name}`)
  return match[1]
}

function interfaceFields(source: string, name: string) {
  return interfaceBody(source, name)
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
}

function event(index: number, observations: Array<'buy' | 'sell'>): AlertEvent {
  const minute = String(index * 15).padStart(2, '0')
  return {
    id: index,
    rule_code: 'htdy_original_15m',
    symbol: 'ag',
    contract: 'AG2610',
    trading_day: '2026-08-13',
    frequency: '15m',
    bar_end: `2026-08-13T02:${minute}:00Z`,
    result_codes: observations,
    lower_tf_confirmation: false,
    detected_at: '2026-08-13T02:45:01Z',
    notification_attempted_at: '2026-08-13T02:45:01Z',
  }
}

function identity() {
  return { seriesKind: 'actual_dominant' as const, symbol: 'ag', frequency: '15m' as const }
}

function bars(...times: Array<string | BarData>): BarData[] {
  return times.flatMap((value) => typeof value === 'string' ? [{
    time: value,
    trading_day: '2026-08-13',
    open: 100,
    high: 101,
    low: 99,
    close: 100,
    volume: 10,
  }] : [value])
}

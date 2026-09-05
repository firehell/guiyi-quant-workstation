import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, test } from 'node:test'
import { ref } from 'vue'
import { usePersistentAlertMarkers } from '../src/composables/usePersistentAlertMarkers.ts'
import { useProductAlertScope } from '../src/composables/useProductAlertScope.ts'
import type { AlertEvent, BarData } from '../src/types/market.ts'
import {
  alertEventsToMarkers,
  alertMarkersForOverlay,
  markerRuleCodes,
  mergeKlineMarkers,
} from '../src/utils/alertMarkers.ts'
import {
  ALERT_RULE_CODES,
  alertResultLabel,
  alertRuleShortLabel,
} from '../src/utils/alertRules.ts'

describe('HTDY Alert scope', () => {
  test('uses only the product-frequency mutation API', () => {
    const source = readFileSync(new URL('../src/api/alerts.ts', import.meta.url), 'utf-8')
    assert.match(source, /scope\/\$\{symbol\}\/\$\{frequency\}/)
    assert.doesNotMatch(source, /scope\/\$\{symbol\}\x60/)
  })

  test('loads and mutates the exact current frequency pair', async () => {
    const symbol = ref('jm')
    const frequency = ref<'15m'>('15m')
    const calls: unknown[][] = []
    const controller = useProductAlertScope({
      symbol,
      frequency,
      fetchProductAlerts: async () => ({ symbol: 'jm', rules: [rule(false)] }),
      fetchRuntimeStatus: async () => 'healthy',
      setProductFrequencyEnabled: async (...args) => {
        calls.push(args)
        return rule(true)
      },
      notifyError: () => undefined,
    })
    await controller.refresh()
    await controller.toggleHtdyCurrentFrequency(ALERT_RULE_CODES.HTDY, true)
    assert.deepEqual(calls, [[ALERT_RULE_CODES.HTDY, 'jm', '15m', true]])
    assert.equal(controller.alertRules.value[0]?.enabled_for_product, true)
    controller.dispose()
  })

  test('wrong or unknown Rule identity fails closed before mutation', async () => {
    let calls = 0
    const controller = useProductAlertScope({
      symbol: ref('jm'),
      frequency: ref('15m'),
      fetchProductAlerts: async () => ({ symbol: 'jm', rules: [rule(false)] }),
      fetchRuntimeStatus: async () => 'healthy',
      setProductFrequencyEnabled: async () => {
        calls += 1
        return rule(true)
      },
      notifyError: () => undefined,
    })
    await controller.refresh()
    await controller.toggleHtdyCurrentFrequency('future_rule', true)
    assert.equal(calls, 0)
    controller.dispose()
  })
})

describe('two-Rule Alert presentation', () => {
  test('owns the exact SuBing observation labels', () => {
    assert.equal(ALERT_RULE_CODES.SUBING_THS, 'subing_ths_alert_15m_v1')
    assert.equal(alertRuleShortLabel(ALERT_RULE_CODES.SUBING_THS), '苏冰预警')
    assert.equal(alertResultLabel(ALERT_RULE_CODES.SUBING_THS, ['buy']), '多头预警')
    assert.equal(alertResultLabel(ALERT_RULE_CODES.SUBING_THS, ['sell']), '空头预警')
  })
})

describe('persistent Alert markers', () => {
  test('uses both rules only for actual-dominant 15m', () => {
    assert.deepEqual(markerRuleCodes('actual_dominant', '15m'), [
      ALERT_RULE_CODES.HTDY,
      ALERT_RULE_CODES.SUBING_THS,
    ])
    assert.deepEqual(markerRuleCodes('actual_dominant', '5m'), [ALERT_RULE_CODES.HTDY])
    assert.deepEqual(markerRuleCodes('actual_dominant', '1d'), [ALERT_RULE_CODES.HTDY])
    assert.deepEqual(markerRuleCodes('continuous', '15m'), [])
  })

  test('maps first-seen events to observation markers and only exposes them under HTDY', () => {
    const markers = alertEventsToMarkers([event(1, ['buy']), event(2, ['sell'])])
    assert.deepEqual(markers.map((item) => item.label), ['买入观察 · 首次识别', '卖出观察 · 首次识别'])
    assert.deepEqual(markers.map((item) => item.tone), ['up', 'down'])
    assert.deepEqual(alertMarkersForOverlay('none', markers), [])
    assert.deepEqual(alertMarkersForOverlay('htdy', markers), markers)
  })

  test('maps SuBing Event facts to S markers without formula recomputation', () => {
    const markers = alertEventsToMarkers([subingEvent(3, 'buy'), subingEvent(4, 'sell')])
    assert.deepEqual(markers.map((item) => ({
      label: item.label,
      shape: item.shape,
      position: item.position,
      tone: item.tone,
      alertRuleCode: item.alertRuleCode,
    })), [
      {
        label: 'S↑', shape: 'arrowUp', position: 'belowBar', tone: 'up',
        alertRuleCode: ALERT_RULE_CODES.SUBING_THS,
      },
      {
        label: 'S↓', shape: 'arrowDown', position: 'aboveBar', tone: 'down',
        alertRuleCode: ALERT_RULE_CODES.SUBING_THS,
      },
    ])
    assert.match(markers[0]!.tooltip ?? '', /MACD 金叉/)
    assert.match(markers[0]!.tooltip ?? '', /EMA21 上方/)
    assert.match(markers[1]!.tooltip ?? '', /MACD 死叉/)
    assert.match(markers[1]!.tooltip ?? '', /EMA21 下方/)
  })

  test('does not reinterpret malformed SuBing facts as a sell marker', () => {
    const malformed = { ...subingEvent(5, 'buy'), result_codes: ['bad'] } as unknown as AlertEvent
    assert.deepEqual(alertEventsToMarkers([malformed]), [])
  })

  test('keeps SuBing markers visible without an overlay while retaining HTDY visibility', () => {
    const htdy = alertEventsToMarkers([event(1, ['buy'])])
    const subing = alertEventsToMarkers([subingEvent(2, 'buy')])
    assert.deepEqual(alertMarkersForOverlay('none', htdy), [])
    assert.deepEqual(alertMarkersForOverlay('none', subing), subing)
    assert.deepEqual(alertMarkersForOverlay('htdy', [...htdy, ...subing]), [...htdy, ...subing])
  })

  test('keeps current and persistent markers distinct while sorting by time', () => {
    const current = [{
      id: 'current',
      time: '2026-08-15T01:00:00Z',
      label: '买观察',
      tone: 'htdy' as const,
      position: 'belowBar' as const,
      shape: 'arrowUp' as const,
    }]
    const persistent = alertEventsToMarkers([event(1, ['buy'])])
    const merged = mergeKlineMarkers(current, persistent)
    assert.equal(merged.length, 2)
    assert.deepEqual(merged.map((item) => item.id), ['current', persistent[0]!.id])
  })

  test('fetches both 15m rules and clears its timer on dispose', async () => {
    const requests: string[] = []
    let cleared = false
    const controller = usePersistentAlertMarkers({
      fetchEvents: async ({ ruleCode }) => {
        requests.push(ruleCode)
        return { items: [ruleCode === ALERT_RULE_CODES.HTDY ? event(1, ['buy']) : subingEvent(2, 'buy')] }
      },
      scheduleInterval: () => 1,
      clearInterval: () => { cleared = true },
    })
    await controller.sync({
      seriesKind: 'actual_dominant',
      symbol: 'jm',
      frequency: '15m',
    }, bars(), 'replace')
    assert.deepEqual(requests, [ALERT_RULE_CODES.HTDY, ALERT_RULE_CODES.SUBING_THS])
    assert.equal(controller.markers.value.length, 2)
    controller.dispose()
    assert.equal(cleared, true)
  })

  test('HTDY workspace narrows read-only Event requests to HTDY and exposes immutable Event facts', async () => {
    const requests: string[] = []
    const controller = usePersistentAlertMarkers({
      fetchEvents: async ({ ruleCode }) => {
        requests.push(ruleCode)
        return { items: [event(1, ['buy'])] }
      },
      scheduleInterval: () => 1,
      clearInterval: () => undefined,
    }, {
      resolveRuleCodes: () => [ALERT_RULE_CODES.HTDY],
    })
    await controller.sync({ seriesKind: 'actual_dominant', symbol: 'jm', frequency: '15m' }, bars(), 'replace')
    assert.deepEqual(requests, [ALERT_RULE_CODES.HTDY])
    assert.equal(controller.events.value[0]?.rule_code, ALERT_RULE_CODES.HTDY)
    assert.equal(controller.unavailable.value, false)
    controller.dispose()
  })

  test('keeps last immutable Event snapshot while marking an Event refresh unavailable', async () => {
    let reject = false
    const controller = usePersistentAlertMarkers({
      fetchEvents: async () => {
        if (reject) throw new Error('offline')
        return { items: [event(1, ['buy'])] }
      },
      scheduleInterval: () => 1,
      clearInterval: () => undefined,
    }, { resolveRuleCodes: () => [ALERT_RULE_CODES.HTDY] })
    const identity = { seriesKind: 'actual_dominant' as const, symbol: 'jm', frequency: '15m' as const }
    await controller.sync(identity, bars(), 'replace')
    reject = true
    await controller.sync(identity, [{ ...bars()[0]!, time: '2026-08-15T00:00:00Z' }, ...bars()], 'prepend')
    assert.equal(controller.events.value.length, 1)
    assert.equal(controller.unavailable.value, true)
    controller.dispose()
  })

  test('same-identity replacement retains the successful Event snapshot when refresh fails', async () => {
    let reject = false
    const controller = usePersistentAlertMarkers({
      fetchEvents: async () => {
        if (reject) throw new Error('offline')
        return { items: [subingEvent(8, 'buy')] }
      },
      scheduleInterval: () => 1,
      clearInterval: () => undefined,
    }, { resolveRuleCodes: () => [ALERT_RULE_CODES.SUBING_THS] })
    const identity = { seriesKind: 'actual_dominant' as const, symbol: 'jm', frequency: '15m' as const }
    await controller.sync(identity, bars(), 'replace')
    reject = true
    await controller.sync(identity, bars(), 'replace')
    assert.equal(controller.events.value[0]?.id, 8)
    assert.equal(controller.unavailable.value, true)
    controller.dispose()
  })

  test('an Event response with a mismatched requested identity fails closed', async () => {
    const controller = usePersistentAlertMarkers({
      fetchEvents: async () => ({ items: [{ ...subingEvent(9, 'buy'), symbol: 'rb' }] }),
      scheduleInterval: () => 1,
      clearInterval: () => undefined,
    }, { resolveRuleCodes: () => [ALERT_RULE_CODES.SUBING_THS] })
    await controller.sync({ seriesKind: 'actual_dominant', symbol: 'jm', frequency: '15m' }, bars(), 'replace')
    assert.equal(controller.events.value.length, 0)
    assert.equal(controller.unavailable.value, true)
    controller.dispose()
  })

  test('an older same-identity replacement cannot overwrite a newer Event snapshot', async () => {
    const first = deferred<{ items: AlertEvent[] }>()
    const second = deferred<{ items: AlertEvent[] }>()
    let calls = 0
    const controller = usePersistentAlertMarkers({
      fetchEvents: async () => (++calls === 1 ? first.promise : second.promise),
      scheduleInterval: () => 1,
      clearInterval: () => undefined,
    }, { resolveRuleCodes: () => [ALERT_RULE_CODES.SUBING_THS] })
    const identity = { seriesKind: 'actual_dominant' as const, symbol: 'jm', frequency: '15m' as const }
    const older = controller.sync(identity, bars(), 'replace')
    const newer = controller.sync(identity, bars(), 'replace')
    second.resolve({ items: [subingEvent(8, 'sell')] })
    await newer
    first.resolve({ items: [subingEvent(9, 'buy')] })
    await older
    assert.equal(controller.events.value[0]?.id, 8)
    controller.dispose()
  })

  test('an older same-identity failure cannot mark a newer Event snapshot stale', async () => {
    const first = deferred<{ items: AlertEvent[] }>()
    const second = deferred<{ items: AlertEvent[] }>()
    let calls = 0
    const controller = usePersistentAlertMarkers({
      fetchEvents: async () => (++calls === 1 ? first.promise : second.promise),
      scheduleInterval: () => 1,
      clearInterval: () => undefined,
    }, { resolveRuleCodes: () => [ALERT_RULE_CODES.SUBING_THS] })
    const identity = { seriesKind: 'actual_dominant' as const, symbol: 'jm', frequency: '15m' as const }
    const older = controller.sync(identity, bars(), 'replace')
    const newer = controller.sync(identity, bars(), 'replace')
    second.resolve({ items: [subingEvent(8, 'sell')] })
    await newer
    first.reject(new Error('late offline'))
    await older
    assert.equal(controller.events.value[0]?.id, 8)
    assert.equal(controller.unavailable.value, false)
    controller.dispose()
  })

  test('a live bar update cannot cancel the initial persistent Event window', async () => {
    const initial = deferred<{ items: AlertEvent[] }>()
    let calls = 0
    const controller = usePersistentAlertMarkers({
      fetchEvents: async () => {
        calls += 1
        return initial.promise
      },
      scheduleInterval: () => 1,
      clearInterval: () => undefined,
    }, { resolveRuleCodes: () => [ALERT_RULE_CODES.SUBING_THS] })
    const identity = { seriesKind: 'actual_dominant' as const, symbol: 'jm', frequency: '15m' as const }
    const pending = controller.sync(identity, bars(), 'replace')

    await controller.sync(identity, [...bars(), { ...bars()[1]!, time: '2026-08-15T03:00:00Z' }], 'live')
    initial.resolve({ items: [subingEvent(1, 'buy')] })
    await pending

    assert.equal(calls, 1)
    assert.deepEqual(controller.events.value.map((item) => item.id), [1])
    assert.equal(controller.unavailable.value, false)
    controller.dispose()
  })

  test('a live bar update cannot cancel an in-flight prepended Event window', async () => {
    const prepended = deferred<{ items: AlertEvent[] }>()
    let calls = 0
    const controller = usePersistentAlertMarkers({
      fetchEvents: async () => {
        calls += 1
        if (calls === 1) return { items: [subingEvent(1, 'buy')] }
        return prepended.promise
      },
      scheduleInterval: () => 1,
      clearInterval: () => undefined,
    }, { resolveRuleCodes: () => [ALERT_RULE_CODES.SUBING_THS] })
    const identity = { seriesKind: 'actual_dominant' as const, symbol: 'jm', frequency: '15m' as const }
    await controller.sync(identity, bars(), 'replace')
    const prepend = controller.sync(
      identity,
      [{ ...bars()[0]!, time: '2026-08-15T00:00:00Z' }, ...bars()],
      'prepend',
    )

    await controller.sync(identity, [...bars(), { ...bars()[1]!, time: '2026-08-15T03:00:00Z' }], 'live')
    prepended.resolve({ items: [subingEvent(0, 'sell')] })
    await prepend

    assert.equal(calls, 2)
    assert.deepEqual(controller.events.value.map((item) => item.id), [0, 1])
    assert.equal(controller.unavailable.value, false)
    controller.dispose()
  })

  test('a recent refresh merges without canceling an in-flight prepended Event window', async () => {
    const prepended = deferred<{ items: AlertEvent[] }>()
    let refresh: (() => void | Promise<void>) | undefined
    let calls = 0
    const controller = usePersistentAlertMarkers({
      fetchEvents: async () => {
        calls += 1
        if (calls === 1) return { items: [subingEvent(1, 'buy')] }
        if (calls === 2) return prepended.promise
        return { items: [subingEvent(2, 'sell')] }
      },
      scheduleInterval: (callback) => {
        refresh = callback
        return 1
      },
      clearInterval: () => undefined,
    }, { resolveRuleCodes: () => [ALERT_RULE_CODES.SUBING_THS] })
    const identity = { seriesKind: 'actual_dominant' as const, symbol: 'jm', frequency: '15m' as const }
    await controller.sync(identity, bars(), 'replace')
    const prepend = controller.sync(
      identity,
      [{ ...bars()[0]!, time: '2026-08-15T00:00:00Z' }, ...bars()],
      'prepend',
    )

    assert.ok(refresh)
    await refresh()
    prepended.resolve({ items: [subingEvent(0, 'sell')] })
    await prepend

    assert.equal(calls, 3)
    assert.deepEqual(controller.events.value.map((item) => item.id), [0, 1, 2])
    assert.equal(controller.unavailable.value, false)
    controller.dispose()
  })
})

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

function rule(enabled: boolean) {
  return {
    rule_code: ALERT_RULE_CODES.HTDY,
    display_name: '火天大有',
    kind: 'indicator_observation' as const,
    input_frequencies: ['15m'] as const,
    enabled_for_product: enabled,
    enabled_frequencies: enabled ? ['15m'] as const : [],
  }
}

function event(id: number, resultCodes: AlertEvent['result_codes']): AlertEvent {
  return {
    id,
    rule_code: ALERT_RULE_CODES.HTDY,
    symbol: 'jm',
    contract: 'JM2601',
    trading_day: '2026-08-15',
    frequency: '15m',
    bar_end: `2026-08-15T0${id}:00:00Z`,
    result_codes: resultCodes,
    detected_at: `2026-08-15T0${id}:00:01Z`,
    notification_attempted_at: null,
  }
}

function subingEvent(id: number, direction: 'buy' | 'sell'): AlertEvent {
  return {
    id,
    rule_code: 'subing_ths_alert_15m_v1',
    symbol: 'jm',
    contract: 'JM2601',
    trading_day: '2026-08-15',
    frequency: '15m',
    bar_end: `2026-08-15T0${id}:00:00Z`,
    result_codes: [direction],
    detected_at: `2026-08-15T0${id}:00:01Z`,
    notification_attempted_at: null,
  } as AlertEvent
}

function bars(): BarData[] {
  return [1, 2].map((hour) => ({
    time: `2026-08-15T0${hour}:00:00Z`,
    trading_day: '2026-08-15',
    physicalContract: 'JM2601',
    open: 100,
    high: 102,
    low: 99,
    close: 101,
    volume: 10,
  }))
}

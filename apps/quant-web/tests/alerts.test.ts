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
    assert.deepEqual(markers.map((item) => item.label), ['买入观察', '卖出观察'])
    assert.ok(markers.every((item) => item.tone === 'htdy'))
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
        return { items: [event(1, ['buy'])] }
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
    assert.equal(controller.markers.value.length, 1)
    controller.dispose()
    assert.equal(cleared, true)
  })
})

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

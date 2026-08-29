import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { describe, it } from 'node:test'

import { alertRuntimeLabel, isCurrentAlertMutation } from '../src/utils/alertControl.ts'
import { ALERT_RULE_CODES, ALERT_RULE_PRESENTATIONS } from '../src/utils/alertRules.ts'
import {
  alertEventsToMarkers,
  alertMarkersForOverlay,
  isPersistentAlertIdentity,
  markerRuleCodes,
  mergeKlineMarkers,
} from '../src/utils/alertMarkers.ts'
import { usePersistentAlertMarkers } from '../src/composables/usePersistentAlertMarkers.ts'
import { useProductAlertScope } from '../src/composables/useProductAlertScope.ts'
import { ref } from 'vue'
import type { AlertEvent } from '../src/api/alerts.ts'
import { MARKET_FREQUENCIES, type BarData } from '../src/types/market.ts'


const apiSource = read('../src/api/alerts.ts')
const marketTypesSource = read('../src/types/market.ts')
const rulesPath = new URL('../src/components/market/ProductAlertRules.vue', import.meta.url)
const chartSource = read('../src/pages/market/chart.vue')


describe('Product Alert server-side scope', () => {
  it('uses the exact GET and PUT server API contracts without localStorage truth', () => {
    assert.match(apiSource, /`\/api\/alerts\/products\/\$\{symbol\}`/)
    assert.match(apiSource, /`\/api\/alerts\/rules\/\$\{ruleCode\}\/scope\/\$\{symbol\}`/)
    assert.match(
      apiSource,
      /`\/api\/alerts\/rules\/\$\{ruleCode\}\/scope\/\$\{symbol\}\/\$\{frequency\}`/,
    )
    assert.match(apiSource, /\{ enabled \}/)
    assert.doesNotMatch(apiSource, /localStorage|sessionStorage/)
    assert.doesNotMatch(chartSource, /localStorage.*alert|alert.*localStorage/i)
  })

  it('uses the exact V2 current-view endpoints', () => {
    assert.match(
      apiSource,
      /getCurrentStrategyActions\(\)\s*\{\s*return request\.get<never, CurrentStrategyActionsResponse>\('\/api\/alerts\/strategy-actions\/current'\)/,
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
      'enabled_frequencies: MarketFrequency[]',
    ])
    assert.deepEqual(interfaceFields(marketTypesSource, 'HtdyAlertEvent'), [
      "rule_code: 'htdy_original_15m'",
      "result_codes: Array<'buy' | 'sell'>",
      'action_id: null',
      'strategy_action: null',
    ])
    assert.deepEqual(interfaceFields(marketTypesSource, 'SubingStrategyAlertEventCommon'), [
      "rule_code: 'subing_strategy_v1'",
      'trading_day: string',
      "frequency: '15m'",
      'action_id: string',
    ])
    assert.match(marketTypesSource, /result_codes: \['open_long'\][^]*strategy_action: SubingStrategyOpenLongActionPayloadWire/)
    assert.match(marketTypesSource, /result_codes: \['close_short'\][^]*strategy_action: SubingStrategyCloseShortActionPayloadWire/)
    assert.match(marketTypesSource, /reason_codes: \[SubingStrategyLongExitReason, \.\.\.SubingStrategyLongExitReason\[\]\]/)
    assert.match(marketTypesSource, /reason_codes: \[SubingStrategyShortExitReason, \.\.\.SubingStrategyShortExitReason\[\]\]/)
    assert.match(marketTypesSource, /export type AlertEvent = HtdyAlertEvent \| SubingStrategyAlertEvent/)
    assert.match(apiSource, /export type CurrentStrategyActionItem = SubingStrategyAlertEvent & \{/)
    assert.deepEqual(interfaceFields(apiSource, 'CurrentStrategyActionsResponse'), [
      "status: 'ready' | 'unavailable'",
      'trading_day: string | null',
      'items: CurrentStrategyActionItem[]',
    ])
    assert.deepEqual(interfaceFields(apiSource, 'ProductCurrentAlertEventsResponse'), [
      "status: 'ready' | 'unavailable'",
      'trading_day: string | null',
      'items: AlertEvent[]',
    ])
  })

  it('drops V1 rule shape fields in favor of the V2 rule registry contract', () => {
    assert.doesNotMatch(interfaceBody(apiSource, 'ProductAlertRuleState'), /indicator_code|series_kind|frequency:/)
    assert.doesNotMatch(interfaceBody(marketTypesSource, 'HtdyAlertEvent'), /observation_types|notified_at|lower_tf_confirmation/)
    assert.doesNotMatch(interfaceBody(marketTypesSource, 'SubingStrategyAlertEventCommon'), /observation_types|notified_at|lower_tf_confirmation/)
  })

  it('renders only the HTDY current-frequency pair row and shared Runtime status', () => {
    assert.equal(existsSync(rulesPath), true)
    const rulesSource = read('../src/components/market/ProductAlertRules.vue')
    assert.deepEqual(ALERT_RULE_PRESENTATIONS.map((item) => item.ruleCode), [
      ALERT_RULE_CODES.HTDY,
      ALERT_RULE_CODES.SUBING,
    ])
    assert.match(rulesSource, /matchesAlertRuleCode\(rule, ALERT_RULE_CODES\.HTDY\)/)
    assert.doesNotMatch(rulesSource, /\.rule_code\s*[!=]==?/)
    assert.match(rulesSource, /htdyRule\.value\?\.enabled_frequencies\.includes\(props\.frequency\)/)
    assert.match(rulesSource, /`\$\{rule\.display_name\} · \$\{props\.frequency\}`/)
    assert.doesNotMatch(rulesSource, /ALERT_RULE_CODES\.SUBING|enabled_for_product/)
    assert.doesNotMatch(rulesSource, /全周期/)
    assert.equal((rulesSource.match(/Alert Runtime/g) || []).length, 1)
    assert.match(rulesSource, /不可用/)
  })

  it('dispatches every Overlay explicitly without treating generic research as HTDY', () => {
    const sidebarSource = read('../src/components/market/ProductCheckSidebar.vue')
    const observationSource = between(
      sidebarSource,
      'data-testid="product-check-observation"',
      'data-testid="product-check-background"',
    )
    for (const overlay of ['none', 'subing', 'htdy']) {
      assert.match(observationSource, new RegExp(`selectedOverlay === '${overlay}'`))
    }
    assert.doesNotMatch(observationSource, /<template v-else>/)
    assert.match(observationSource, /selectedOverlay === 'htdy'[^]*<ProductAlertRules/)
    assert.doesNotMatch(between(observationSource, "selectedOverlay === 'none'", "selectedOverlay === 'subing'"), /<ProductAlertRules/)
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
      ruleIdentityCurrent: true,
    }), false)
    assert.equal(isCurrentAlertMutation({
      requestGeneration: 3,
      currentGeneration: 3,
      requestedSymbol: 'ag',
      currentSymbol: 'ag',
      ruleIdentityCurrent: true,
    }), true)
  })

  it('toggles the exact rule without changing its neighbor', async () => {
    const symbol = ref('jm')
    const frequency = ref<'15m' | '5m'>('15m')
    const controller = useProductAlertScope({
      symbol,
      frequency,
      fetchProductAlerts: async () => ({ symbol: 'jm', rules: [htdyRule(true), subingRule(false)] }),
      fetchRuntimeStatus: async () => 'ok',
      setProductEnabled: async (ruleCode, requestedSymbol, enabled) => ({
        ...(ruleCode === 'subing_strategy_v1' ? subingRule(enabled) : htdyRule(enabled)),
        symbol: requestedSymbol,
      }),
      setProductFrequencyEnabled: async () => { throw new Error('not used') },
      notifyError: () => undefined,
    })

    await controller.refresh()
    await controller.toggleSubingProduct('subing_strategy_v1', true)

    assert.equal(controller.alertRules.value.find((rule) => rule.rule_code === ALERT_RULE_CODES.SUBING)?.enabled_for_product, true)
    assert.equal(controller.alertRules.value.find((rule) => rule.rule_code === ALERT_RULE_CODES.HTDY)?.enabled_for_product, true)
    controller.dispose()
  })

  it('tracks saving independently for each rule', async () => {
    const symbol = ref('jm')
    const frequency = ref<'15m' | '5m'>('15m')
    let resolveUpdate: ((value: ReturnType<typeof subingRule>) => void) | undefined
    const controller = useProductAlertScope({
      symbol,
      frequency,
      fetchProductAlerts: async () => ({ symbol: 'jm', rules: [htdyRule(false), subingRule(false)] }),
      fetchRuntimeStatus: async () => 'ok',
      setProductEnabled: () => new Promise((resolve) => { resolveUpdate = resolve }),
      setProductFrequencyEnabled: async () => { throw new Error('not used') },
      notifyError: () => undefined,
    })

    await controller.refresh()
    const pending = controller.toggleSubingProduct('subing_strategy_v1', true)
    assert.equal(controller.savingRuleCodes.value.has('subing_strategy_v1'), true)
    assert.equal(controller.savingRuleCodes.value.has('htdy_original_15m'), false)
    resolveUpdate!(subingRule(true))
    await pending
    assert.equal(controller.savingRuleCodes.value.size, 0)
    controller.dispose()
  })

  it('drops a stale rule mutation response after the selected symbol changes', async () => {
    const symbol = ref('ag')
    const frequency = ref<'15m' | '5m'>('15m')
    let resolveUpdate: ((value: ReturnType<typeof htdyRule>) => void) | undefined
    const controller = useProductAlertScope({
      symbol,
      frequency,
      fetchProductAlerts: async (requestedSymbol) => ({ symbol: requestedSymbol, rules: [htdyRule(false), subingRule(false)] }),
      fetchRuntimeStatus: async () => 'ok',
      setProductEnabled: () => new Promise((resolve) => { resolveUpdate = resolve }),
      setProductFrequencyEnabled: () => new Promise((resolve) => { resolveUpdate = resolve }),
      notifyError: () => undefined,
    })

    await controller.refresh()
    const pending = controller.toggleHtdyCurrentFrequency('htdy_original_15m', true)
    symbol.value = 'jm'
    await controller.refresh()
    resolveUpdate!(htdyRule(true))
    await pending
    assert.deepEqual(
      controller.alertRules.value.find((rule) => rule.rule_code === ALERT_RULE_CODES.HTDY)?.enabled_frequencies,
      [],
    )
    controller.dispose()
  })

  it('routes HTDY by captured symbol and frequency while SuBing stays product-scoped', async () => {
    const symbol = ref('jm')
    const frequency = ref<'15m' | '5m'>('15m')
    const productCalls: Array<[string, string, boolean]> = []
    const pairCalls: Array<[string, string, string, boolean]> = []
    const controller = useProductAlertScope({
      symbol,
      frequency,
      fetchProductAlerts: async () => ({ symbol: 'jm', rules: [htdyRule(true), subingRule(false)] }),
      fetchRuntimeStatus: async () => 'ok',
      setProductEnabled: async (ruleCode, requestedSymbol, enabled) => {
        productCalls.push([ruleCode, requestedSymbol, enabled])
        return subingRule(enabled)
      },
      setProductFrequencyEnabled: async (ruleCode, requestedSymbol, requestedFrequency, enabled) => {
        pairCalls.push([ruleCode, requestedSymbol, requestedFrequency, enabled])
        return htdyRule(enabled)
      },
      notifyError: () => undefined,
    })

    await controller.refresh()
    const htdyMutation = controller.toggleHtdyCurrentFrequency(ALERT_RULE_CODES.HTDY, false)
    frequency.value = '5m'
    await htdyMutation
    await controller.toggleSubingProduct(ALERT_RULE_CODES.SUBING, true)

    assert.deepEqual(pairCalls, [[ALERT_RULE_CODES.HTDY, 'jm', '15m', false]])
    assert.deepEqual(productCalls, [[ALERT_RULE_CODES.SUBING, 'jm', true]])
    controller.dispose()
  })

  it('fails closed before mutation when either named entry receives the wrong Rule', async () => {
    const symbol = ref('jm')
    const frequency = ref<'15m' | '5m'>('15m')
    const calls: string[] = []
    const controller = useProductAlertScope({
      symbol,
      frequency,
      fetchProductAlerts: async () => ({ symbol: 'jm', rules: [htdyRule(true), subingRule(false)] }),
      fetchRuntimeStatus: async () => 'ok',
      setProductEnabled: async () => {
        calls.push('product')
        return subingRule(true)
      },
      setProductFrequencyEnabled: async () => {
        calls.push('pair')
        return htdyRule(true)
      },
      notifyError: () => undefined,
    })

    await controller.refresh()
    await controller.toggleSubingProduct(ALERT_RULE_CODES.HTDY, true)
    await controller.toggleSubingProduct('future_rule', true)
    await controller.toggleHtdyCurrentFrequency(ALERT_RULE_CODES.SUBING, true)
    await controller.toggleHtdyCurrentFrequency('future_rule', true)

    assert.deepEqual(calls, [])
    assert.equal(controller.savingRuleCodes.value.size, 0)
    controller.dispose()
  })

  it('serializes HTDY writes by Rule code even when the displayed frequency changes', async () => {
    const symbol = ref('jm')
    const frequency = ref<'15m' | '5m'>('15m')
    const pairCalls: Array<[string, string, string, boolean]> = []
    let resolveUpdate: ((value: ReturnType<typeof htdyRule>) => void) | undefined
    const controller = useProductAlertScope({
      symbol,
      frequency,
      fetchProductAlerts: async () => ({ symbol: 'jm', rules: [htdyRule(false), subingRule(false)] }),
      fetchRuntimeStatus: async () => 'ok',
      setProductEnabled: () => new Promise((resolve) => { resolveUpdate = resolve }),
      setProductFrequencyEnabled: (ruleCode, requestedSymbol, requestedFrequency, enabled) => {
        pairCalls.push([ruleCode, requestedSymbol, requestedFrequency, enabled])
        return new Promise((resolve) => { resolveUpdate = resolve })
      },
      notifyError: () => undefined,
    })

    await controller.refresh()
    const pending = controller.toggleHtdyCurrentFrequency(ALERT_RULE_CODES.HTDY, true)
    frequency.value = '5m'
    await controller.toggleHtdyCurrentFrequency(ALERT_RULE_CODES.HTDY, true)

    assert.deepEqual(pairCalls, [[ALERT_RULE_CODES.HTDY, 'jm', '15m', true]])
    assert.equal(controller.savingRuleCodes.value.has(ALERT_RULE_CODES.HTDY), true)
    resolveUpdate!(htdyRule(true))
    await pending
    assert.equal(controller.savingRuleCodes.value.size, 0)
    controller.dispose()
  })

  it('accepts a same-symbol HTDY response with the full pair set after display frequency changes', async () => {
    const symbol = ref('jm')
    const frequency = ref<'15m' | '5m'>('15m')
    let resolveUpdate: ((value: ReturnType<typeof htdyRule>) => void) | undefined
    const controller = useProductAlertScope({
      symbol,
      frequency,
      fetchProductAlerts: async () => ({ symbol: 'jm', rules: [htdyRule(false), subingRule(false)] }),
      fetchRuntimeStatus: async () => 'ok',
      setProductEnabled: () => new Promise((resolve) => { resolveUpdate = resolve }),
      setProductFrequencyEnabled: () => new Promise((resolve) => { resolveUpdate = resolve }),
      notifyError: () => undefined,
    })

    await controller.refresh()
    const pending = controller.toggleHtdyCurrentFrequency(ALERT_RULE_CODES.HTDY, true)
    frequency.value = '5m'
    resolveUpdate!(htdyRule(true, ['15m']))
    await pending

    assert.deepEqual(
      controller.alertRules.value.find((rule) => rule.rule_code === ALERT_RULE_CODES.HTDY)?.enabled_frequencies,
      ['15m'],
    )
    controller.dispose()
  })

  it('keeps only the latest symbol scope response after page lifecycle extraction', async () => {
    const symbol = ref('ag')
    const frequency = ref<'15m' | '5m'>('15m')
    const resolvers = new Map<string, (value: { symbol: string; rules: never[] }) => void>()
    const controller = useProductAlertScope({
      symbol,
      frequency,
      fetchProductAlerts: (requestedSymbol) => new Promise((resolve) => {
        resolvers.set(requestedSymbol, resolve)
      }),
      fetchRuntimeStatus: async () => 'ok',
      setProductEnabled: async () => { throw new Error('not used') },
      setProductFrequencyEnabled: async () => { throw new Error('not used') },
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

  it('invalidates loaded rules synchronously and blocks all mutations until the new Scope arrives', async () => {
    const productCalls: string[] = []
    const pairCalls: string[] = []
    const controller = useProductAlertScope({
      symbol: ref('ag'),
      frequency: ref('15m'),
      fetchProductAlerts: async () => ({ symbol: 'ag', rules: [htdyRule(true), subingRule(true)] }),
      fetchRuntimeStatus: async () => 'ok',
      setProductEnabled: async (_ruleCode, requestedSymbol) => {
        productCalls.push(requestedSymbol)
        return subingRule(false)
      },
      setProductFrequencyEnabled: async (_ruleCode, requestedSymbol) => {
        pairCalls.push(requestedSymbol)
        return htdyRule(false)
      },
      notifyError: () => undefined,
    })
    await controller.refresh()

    controller.invalidateIdentity()
    const subing = controller.toggleSubingProduct(ALERT_RULE_CODES.SUBING, false)
    const htdy = controller.toggleHtdyCurrentFrequency(ALERT_RULE_CODES.HTDY, false)
    await Promise.all([subing, htdy])

    assert.deepEqual(controller.alertRules.value, [])
    assert.equal(controller.alertLoading.value, true)
    assert.deepEqual(productCalls, [])
    assert.deepEqual(pairCalls, [])
    controller.dispose()
  })

  it('drops an earlier AG Scope response after AG to JM to AG invalidations', async () => {
    const symbol = ref('ag')
    const resolvers: Array<(value: { symbol: string; rules: ReturnType<typeof htdyRule>[] }) => void> = []
    const controller = useProductAlertScope({
      symbol,
      frequency: ref('15m'),
      fetchProductAlerts: () => new Promise((resolve) => { resolvers.push(resolve) }),
      fetchRuntimeStatus: async () => 'ok',
      setProductEnabled: async () => { throw new Error('not used') },
      setProductFrequencyEnabled: async () => { throw new Error('not used') },
      notifyError: () => undefined,
    })

    const oldAg = controller.refresh()
    controller.invalidateIdentity()
    symbol.value = 'jm'
    controller.invalidateIdentity()
    symbol.value = 'ag'
    const finalAg = controller.refresh()
    resolvers[1]({ symbol: 'ag', rules: [htdyRule(true)] })
    await finalAg
    resolvers[0]({ symbol: 'ag', rules: [htdyRule(false)] })
    await oldAg

    assert.deepEqual(controller.alertRules.value[0].enabled_frequencies, ['15m'])
    controller.dispose()
  })

  it('keeps Strategy Events out of the generic persistent marker path', () => {
    const markers = alertEventsToMarkers([
      event(0, ['buy', 'sell'], 'subing_strategy_v1'),
      event(1, ['buy']),
      event(2, ['sell'], 'subing_strategy_v1'),
      event(3, ['buy', 'sell']),
    ])

    assert.deepEqual(markers.map((marker) => [marker.id, marker.label, marker.tone]), [
      ['alert:htdy_original_15m:ag:15m:2026-08-13T02:15:00Z', '买入观察', 'htdy'],
      ['alert:htdy_original_15m:ag:15m:2026-08-13T02:45:00Z', '买入/卖出观察', 'htdy'],
    ])
  })

  it('shows HTDY persistent observation markers only when HTDY overlay is selected', () => {
    const markers = alertEventsToMarkers([
      event(1, ['buy']),
      event(3, ['sell']),
    ])
    assert.equal(markers.length, 2)
    assert.deepEqual(alertMarkersForOverlay('htdy', markers), markers)
    assert.deepEqual(alertMarkersForOverlay('subing', markers), [])
    assert.deepEqual(alertMarkersForOverlay('none', markers), [])
    assert.match(chartSource, /:alert-markers="visibleAlertMarkers"/)
    assert.match(
      chartSource,
      /alertMarkersForOverlay\(\s*selectedOverlay\.value,\s*persistentAlertMarkers\.value,?\s*\)/,
    )
  })

  it('keeps same-rule same-bar HTDY events distinct by frequency', () => {
    const fifteenMinute = event(1, ['buy'])
    const sixtyMinute = { ...fifteenMinute, id: 60, frequency: '60m' as const }

    assert.deepEqual(
      alertEventsToMarkers([fifteenMinute, sixtyMinute]).map((marker) => marker.id),
      [
        'alert:htdy_original_15m:ag:15m:2026-08-13T02:15:00Z',
        'alert:htdy_original_15m:ag:60m:2026-08-13T02:15:00Z',
      ],
    )
  })

  it('renders only HTDY observation tone in the generic path', () => {
    assert.deepEqual(alertEventsToMarkers([
      event(0, ['buy'], 'subing_strategy_v1'),
      event(1, ['sell'], 'subing_strategy_v1'),
      event(2, ['buy'], 'htdy_original_15m'),
    ]).map((marker) => marker.tone), ['htdy'])
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
      tone: 'neutral' as const,
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

  it('uses the exact V2 Rule set for each visible series identity', () => {
    for (const frequency of MARKET_FREQUENCIES) {
      const expected = frequency === '15m'
        ? ['htdy_original_15m', 'subing_strategy_v1']
        : ['htdy_original_15m']
      assert.deepEqual(markerRuleCodes('actual_dominant', frequency), expected)
      assert.equal(isPersistentAlertIdentity('actual_dominant', frequency), true)
      assert.deepEqual(markerRuleCodes('continuous', frequency), [])
      assert.deepEqual(markerRuleCodes('contract', frequency), [])
      assert.equal(isPersistentAlertIdentity('continuous', frequency), false)
      assert.equal(isPersistentAlertIdentity('contract', frequency), false)
    }
  })

  it('fetches only the exact V2 Rules per frequency, dedups, and clears timer off identity', async () => {
    const requests: Array<{ ruleCode: string; start: string; end: string }> = []
    const scheduled: Array<() => void> = []
    const cleared: unknown[] = []
    const controller = usePersistentAlertMarkers({
      fetchEvents: async (params) => {
        requests.push({ ruleCode: params.ruleCode, start: params.start, end: params.end })
        return { items: [event(
          params.ruleCode === 'htdy_original_15m' ? 3 : 2,
          ['buy'],
          params.ruleCode,
        )] }
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
    assert.deepEqual(requests.map((request) => request.ruleCode), [
      'htdy_original_15m',
      'subing_strategy_v1',
    ])
    assert.equal(controller.markers.value.length, 1)

    await controller.sync(
      identity(),
      bars('2026-08-13T02:15:00Z', ...initialBars),
      'prepend',
    )
    assert.equal(requests.length, 4)
    assert.equal(controller.markers.value.length, 1)

    await scheduled.at(-1)!()
    assert.equal(requests.length, 6)
    assert.match(requests.at(-1)!.start, /2026-08-13/)

    await controller.sync({ ...identity(), seriesKind: 'continuous' }, initialBars, 'replace')
    assert.deepEqual(controller.markers.value, [])
    assert.ok(cleared.length >= 1)
    await controller.sync({ ...identity(), seriesKind: 'contract' }, initialBars, 'replace')
    assert.equal(requests.length, 6)
    controller.dispose()

    const fiveMinuteRequests: string[] = []
    const fiveMinute = usePersistentAlertMarkers({
      fetchEvents: async (params) => {
        fiveMinuteRequests.push(params.ruleCode)
        return { items: [{ ...event(1, ['sell'], params.ruleCode), frequency: '5m' }] }
      },
    })
    await fiveMinute.sync({ ...identity(), frequency: '5m' }, initialBars, 'replace')
    assert.deepEqual(fiveMinuteRequests, ['htdy_original_15m'])
    assert.equal(fiveMinute.markers.value.length, 1)
    fiveMinute.dispose()
  })
})

describe('KlineChart SuBing strategy label overlay', () => {
  const klineChartSource = read('../src/components/kline/KlineChart.vue')
  const chartPageSource = read('../src/pages/market/chart.vue')
  const hoverLegendSource = read('../src/components/kline/KlineHoverLegend.vue')

  it('lays out SuBing strategy labels via HTML overlay', () => {
    assert.match(klineChartSource, /layoutSubingStrategyLabels/)
    assert.match(klineChartSource, /isSubingStrategyMarker/)
    assert.match(klineChartSource, /estimateSubingLabelBoxWidth/)
    assert.match(klineChartSource, /data-testid="kline-strategy-labels"/)
    assert.match(klineChartSource, /pointer-events:\s*none/)
    assert.match(klineChartSource, /kline-strategy-label--profit/)
    assert.match(klineChartSource, /kline-strategy-label--loss/)
    assert.match(
      klineChartSource,
      /mergedDisplayMarkers[\s\S]*filter\([\s\S]*isSubingStrategyMarker/,
    )
    assert.match(klineChartSource, /markersForHoverContext/)
    assert.match(
      klineChartSource,
      /onCrosshairMove[\s\S]*markersForHoverContext/,
    )
    assert.match(
      klineChartSource,
      /markersForHoverContext[\s\S]*filter\([\s\S]*!isSubingStrategyMarker/,
    )
  })

  it('styles crosshair time labels dark and keeps volume red-up green-down tokens', () => {
    assert.match(klineChartSource, /labelBackgroundColor:\s*'#1F2937'/)
    assert.match(klineChartSource, /tickMarkFormatter:\s*\(time:\s*Time,\s*tickMarkType:\s*TickMarkType\)/)
    const tokensSource = read('../src/styles/tokens.css')
    const chartThemeSource = read('../src/styles/chartTheme.ts')
    assert.match(tokensSource, /--gy-chart-volume-up:\s*rgba\(220,\s*38,\s*38,\s*0\.5\)/)
    assert.match(tokensSource, /--gy-chart-volume-down:\s*rgba\(22,\s*163,\s*74,\s*0\.5\)/)
    assert.match(chartThemeSource, /volumeUp:\s*'rgba\(220,\s*38,\s*38,\s*0\.5\)'/)
    assert.match(chartThemeSource, /volumeDown:\s*'rgba\(22,\s*163,\s*74,\s*0\.5\)'/)
  })

  it('keeps chart shell inside the viewport flex chain so crosshair time stays visible', () => {
    assert.doesNotMatch(chartPageSource, /flex:\s*0\s+0\s+calc\(100vh\s*-\s*120px\)/)
    assert.match(
      chartPageSource,
      /\.chart-page\s*>\s*:deep\(\.n-spin-container\)[^}]*flex:\s*1\s+1\s+0/,
    )
    assert.match(
      chartPageSource,
      /\.product-workspace__kline\s+:deep\(\.kline-shell\)[^}]*min-height:\s*0/,
    )
    assert.match(hoverLegendSource, /formatChartTimeInShanghai/)
    assert.match(hoverLegendSource, /data-testid="kline-hover-time"/)
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

function event(
  index: number,
  observations: Array<'buy' | 'sell'>,
  ruleCode = 'htdy_original_15m',
): AlertEvent {
  const minute = String(index * 15).padStart(2, '0')
  return {
    id: index,
    rule_code: ruleCode,
    symbol: 'ag',
    contract: 'AG2610',
    trading_day: '2026-08-13',
    frequency: '15m',
    bar_end: `2026-08-13T02:${minute}:00Z`,
    result_codes: observations,
    action_id: null,
    strategy_action: null,
    detected_at: '2026-08-13T02:45:01Z',
    notification_attempted_at: '2026-08-13T02:45:01Z',
  }
}

function htdyRule(enabled: boolean, enabledFrequencies: Array<'15m' | '5m'> = enabled ? ['15m'] : []) {
  return {
    rule_code: 'htdy_original_15m',
    display_name: '火天大有',
    kind: 'indicator_observation' as const,
    input_frequencies: MARKET_FREQUENCIES,
    enabled_for_product: enabledFrequencies.length > 0,
    enabled_frequencies: enabledFrequencies,
  }
}

function subingRule(enabled: boolean) {
  return {
    rule_code: 'subing_strategy_v1',
    display_name: '苏冰策略',
    kind: 'strategy_action' as const,
    input_frequencies: ['1m' as const, '5m' as const, '15m' as const],
    enabled_for_product: enabled,
    enabled_frequencies: [],
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

import assert from 'node:assert/strict'
import test from 'node:test'
import type {
  AlertEvent,
  BarData,
  SubingHistoricalSignalResponse,
} from '../src/types/market.ts'
import { useHistoricalResearchMarkers } from '../src/composables/useHistoricalResearchMarkers.ts'
import {
  historicalResearchEventToMarker,
} from '../src/utils/historicalResearchMarkers.ts'
import {
  alertEventsToMarkers,
  mergeKlineMarkers,
} from '../src/utils/alertMarkers.ts'
import {
  RESEARCH_OVERLAY_DEFINITIONS,
  researchOverlayCapability,
} from '../src/utils/mainIndicators.ts'


const canonicalBars: BarData[] = [
  {
    time: '2026-08-03T01:05:00Z',
    trading_day: '2026-08-03',
    physicalContract: 'JM2609',
    open: 100,
    high: 101,
    low: 99,
    close: 100,
    volume: 10,
  },
  {
    time: '2026-08-03T01:10:00Z',
    trading_day: '2026-08-03',
    physicalContract: 'JM2609',
    open: 100,
    high: 101,
    low: 99,
    close: 100,
    volume: 10,
  },
]

function response(
  symbol: string,
  frequency: '5m' | '15m',
  barEnd: string,
  direction: 'buy' | 'sell' = 'buy',
): SubingHistoricalSignalResponse {
  return {
    request: {
      series_kind: 'actual_dominant',
      symbol,
      frequency,
      since: '2026-08-03',
      through: '2026-08-03',
    },
    events: [{
      event_id: `subing_entry_signal_v1|${symbol}|JM2609|2026-08-03|${barEnd}|${frequency}|${direction}`,
      bar_end: barEnd,
      trading_day: '2026-08-03',
      contract: 'JM2609',
      segment_start_trading_day: '2026-08-03',
      direction,
      trigger_timeframe: frequency,
      lower_tf_confirmation: false,
    }],
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((accept) => { resolve = accept })
  return { promise, resolve }
}

test('research overlay capability registry exposes only the public Overlay surface', () => {
  assert.deepEqual(
    RESEARCH_OVERLAY_DEFINITIONS.map(({ id, label }) => ({ id, label })),
    [
      { id: 'none', label: '无' },
      { id: 'subing', label: '苏冰' },
      { id: 'jdj_strategy', label: '日进斗金参考回放' },
      { id: 'htdy', label: '火天大有' },
    ],
  )
  assert.deepEqual(researchOverlayCapability('subing', 'actual_dominant', '5m'), {
    supported: true,
    definition: RESEARCH_OVERLAY_DEFINITIONS[1],
  })
  assert.equal(researchOverlayCapability('subing', 'continuous', '5m').supported, false)
  assert.equal(researchOverlayCapability('subing', 'actual_dominant', '1m').supported, false)
  assert.equal(researchOverlayCapability('jdj_strategy' as never, 'actual_dominant', '1m').supported, true)
  assert.equal(researchOverlayCapability('jdj_strategy' as never, 'actual_dominant', '5m').supported, false)
  assert.equal(researchOverlayCapability('jdj_strategy' as never, 'continuous', '1m').supported, false)
  assert.equal(RESEARCH_OVERLAY_DEFINITIONS[2].historicalSource, 'jdj_strategy')
  assert.deepEqual(RESEARCH_OVERLAY_DEFINITIONS[2].mainIndicators, [])
})

test('JDJ strategy markers project only reference fills with exact symbols and replay detail', async () => {
  const markerModule = await import('../src/utils/historicalResearchMarkers.ts')
  const mapper = (markerModule as unknown as {
    jdjStrategyActionToMarker?: (action: Record<string, unknown>) => null | {
      time: string
      label: string
      tooltip: string
      position: string
    }
  }).jdjStrategyActionToMarker
  assert.equal(typeof mapper, 'function')

  const action = (kind: string, direction: string, overrides: Record<string, unknown> = {}) => ({
    event_id: `strategy-${kind}-${direction}`,
    episode_id: 'episode-1',
    kind,
    source_event_ids: ['candidate-1', 'candidate-2'],
    primary_setup: 'key_level_breakout',
    supporting_setups: ['trend_follow'],
    direction,
    contract: 'JM2701',
    trading_day: '2026-08-03',
    segment_start_trading_day: '2026-08-01',
    decision_at: '2026-08-03T02:15:00Z',
    effective_bar_end: '2026-08-03T02:16:00Z',
    reference_price: '101.5',
    quantity: 8,
    position_quantity_after: 8,
    stop_price: '99.5',
    target_price: '106',
    reward_risk: '2.25',
    reason: 'ENTRY_FILLED',
    fill_basis: 'limit_touch',
    ...overrides,
  })
  const cases = [
    ['entry', 'long', '▲', 'belowBar'],
    ['entry', 'short', '▼', 'aboveBar'],
    ['add', 'long', '＋', 'belowBar'],
    ['reduce', 'long', '－', 'belowBar'],
    ['exit', 'long', '×', 'belowBar'],
  ] as const

  for (const [kind, direction, label, position] of cases) {
    const marker = mapper!(action(kind, direction))
    assert.ok(marker)
    assert.equal(marker.time, '2026-08-03T02:16:00Z')
    assert.equal(marker.label, label)
    assert.equal(marker.position, position)
    assert.match(marker.tooltip, /参考回放/)
    assert.match(marker.tooltip, /主设置 key_level_breakout/)
    assert.match(marker.tooltip, /辅助设置 trend_follow/)
    assert.match(marker.tooltip, /合约 JM2701/)
    assert.match(marker.tooltip, /决策时间 2026-08-03T02:15:00Z/)
    assert.match(marker.tooltip, /生效时间 2026-08-03T02:16:00Z/)
    assert.match(marker.tooltip, /数量 8/)
    assert.match(marker.tooltip, /止损 99.5/)
    assert.match(marker.tooltip, /目标 106/)
    assert.match(marker.tooltip, /R:R 2.25/)
    assert.match(marker.tooltip, /原因 ENTRY_FILLED/)
  }

  assert.equal(mapper!(action('rejected', 'short', {
    effective_bar_end: null,
    reference_price: null,
    quantity: 0,
  })), null)
  assert.equal(mapper!(action('entry', 'long', { effective_bar_end: null })), null)
  assert.equal(mapper!(action('entry', 'long', { reference_price: null })), null)
})

test('JDJ strategy loader sends the current non-JM replay identity', async () => {
  let capturedRequest: Record<string, unknown> | undefined
  const controller = useHistoricalResearchMarkers({
    fetchSubing: async () => { throw new Error('wrong source') },
    fetchJdjStrategy: async (request: Record<string, unknown>) => {
      capturedRequest = request
      return { request, reference_execution: true, actions: [] }
    },
  } as never)

  await controller.sync({
    overlay: 'jdj_strategy' as const,
    seriesKind: 'actual_dominant' as const,
    symbol: 'rb',
    frequency: '1m' as const,
  }, canonicalBars, {
    start: canonicalBars[0].time,
    end: canonicalBars[1].time,
  }, 'replace')

  assert.ok(capturedRequest)
  assert.equal(capturedRequest.symbol, 'rb')
  assert.equal(capturedRequest.series_kind, 'actual_dominant')
  assert.equal(capturedRequest.frequency, '1m')
  assert.equal(controller.error.value, null)
})

test('JDJ strategy loader rejects an rb request answered with jm identity', async () => {
  const controller = useHistoricalResearchMarkers({
    fetchSubing: async () => { throw new Error('wrong source') },
    fetchJdjStrategy: async (request: Record<string, unknown>) => ({
      request: { ...request, symbol: 'jm' },
      reference_execution: true,
      actions: [],
    }),
  } as never)

  await controller.sync({
    overlay: 'jdj_strategy' as const,
    seriesKind: 'actual_dominant' as const,
    symbol: 'rb',
    frequency: '1m' as const,
  }, canonicalBars, {
    start: canonicalBars[0].time,
    end: canonicalBars[1].time,
  }, 'replace')

  assert.deepEqual(controller.markers.value, [])
  assert.equal(controller.error.value, 'HISTORICAL_RESEARCH_UNAVAILABLE')
})

test('JDJ strategy shared loader clears unsupported identity, reloads, prepends without duplicates, and ignores stale response', async () => {
  const first = deferred<Record<string, unknown>>()
  let calls = 0
  const later = {
    event_id: 'strategy-entry-later', episode_id: 'episode-1', kind: 'entry',
    source_event_ids: ['candidate-1'], primary_setup: 'trend_follow', supporting_setups: [],
    direction: 'long', contract: 'JM2701', trading_day: '2026-08-03',
    segment_start_trading_day: '2026-08-01', decision_at: canonicalBars[0].time,
    effective_bar_end: canonicalBars[1].time, reference_price: '101.5', quantity: 8,
    position_quantity_after: 8, stop_price: '99.5', target_price: '105.5',
    reward_risk: '2', reason: 'ENTRY_FILLED', fill_basis: 'limit_touch',
  }
  const earlierBar = {
    ...canonicalBars[0],
    time: '2026-08-02T01:05:00Z',
    trading_day: '2026-08-02',
  }
  const earlier = {
    ...later,
    event_id: 'strategy-add-earlier', kind: 'add', trading_day: '2026-08-02',
    decision_at: earlierBar.time, effective_bar_end: earlierBar.time, quantity: 2,
    position_quantity_after: 10, reason: 'ADD_FILLED',
  }
  const controller = useHistoricalResearchMarkers({
    fetchSubing: async () => { throw new Error('wrong source') },
    fetchJdjStrategy: async (request: Record<string, unknown>) => {
      calls += 1
      if (calls === 1) return first.promise
      return { request, reference_execution: true, actions: calls === 3 ? [earlier, later] : [later] }
    },
  } as never)
  const identity = {
    overlay: 'jdj_strategy' as never,
    seriesKind: 'actual_dominant' as const,
    symbol: 'jm',
    frequency: '1m' as const,
  }
  const coverage = { start: canonicalBars[0].time, end: canonicalBars[1].time }

  const staleSync = controller.sync(identity, canonicalBars, coverage, 'replace')
  await controller.sync({ ...identity, frequency: '5m' }, canonicalBars, coverage, 'replace')
  assert.deepEqual(controller.markers.value, [])
  assert.equal(researchOverlayCapability('jdj_strategy' as never, 'actual_dominant', '5m').supported, false)
  first.resolve({
    request: { series_kind: 'actual_dominant', symbol: 'jm', frequency: '1m', since: '2026-08-03', through: '2026-08-03' },
    reference_execution: true,
    actions: [later],
  })
  await staleSync
  assert.deepEqual(controller.markers.value, [])

  await controller.sync(identity, canonicalBars, coverage, 'replace')
  assert.deepEqual(controller.markers.value.map((marker) => marker.label), ['▲'])
  await controller.sync(identity, [earlierBar, ...canonicalBars], {
    start: earlierBar.time,
    end: canonicalBars[1].time,
  }, 'prepend')
  assert.deepEqual(controller.markers.value.map((marker) => marker.label), ['＋', '▲'])
  assert.equal(new Set(controller.markers.value.map((marker) => marker.id)).size, 2)

  await controller.sync({ ...identity, frequency: '5m' }, canonicalBars, coverage, 'replace')
  assert.deepEqual(controller.markers.value, [])
  await controller.sync(identity, canonicalBars, coverage, 'replace')
  assert.deepEqual(controller.markers.value.map((marker) => marker.label), ['▲'])
  assert.equal(calls, 4)
})

test('JDJ strategy loader preserves typed profile unavailable without relabeling generic failures', async () => {
  const identity = {
    overlay: 'jdj_strategy' as const,
    seriesKind: 'actual_dominant' as const,
    symbol: 'ag',
    frequency: '1m' as const,
  }
  const coverage = { start: canonicalBars[0].time, end: canonicalBars[1].time }
  const dependencies = (failure: unknown) => ({
    fetchSubing: async () => { throw new Error('wrong source') },
    fetchJdjStrategy: async () => { throw failure },
  })

  const profileUnavailable = useHistoricalResearchMarkers(dependencies({
    response: {
      status: 422,
      data: { detail: { code: 'JDJ_STRATEGY_PROFILE_UNAVAILABLE' } },
    },
  }) as never)
  await profileUnavailable.sync(identity, canonicalBars, coverage, 'replace')
  assert.equal(profileUnavailable.error.value, 'JDJ_STRATEGY_PROFILE_UNAVAILABLE')
  assert.deepEqual(profileUnavailable.markers.value, [])

  const serverFailure = useHistoricalResearchMarkers(dependencies({
    response: { status: 503, data: { detail: 'unavailable' } },
  }) as never)
  await serverFailure.sync(identity, canonicalBars, coverage, 'replace')
  assert.equal(serverFailure.error.value, 'HISTORICAL_RESEARCH_UNAVAILABLE')
  assert.deepEqual(serverFailure.markers.value, [])
})

test('historical loader discards stale response after full overlay identity changes', async () => {
  const first = deferred<SubingHistoricalSignalResponse>()
  const second = deferred<SubingHistoricalSignalResponse>()
  const controller = useHistoricalResearchMarkers({
    fetchSubing: ({ symbol }) => symbol === 'jm' ? first.promise : second.promise,
  })
  const coverage = { start: canonicalBars[0].time, end: canonicalBars[1].time }

  const oldSync = controller.sync(
    { overlay: 'subing', seriesKind: 'actual_dominant', symbol: 'jm', frequency: '5m' },
    canonicalBars,
    coverage,
    'replace',
  )
  const newSync = controller.sync(
    { overlay: 'subing', seriesKind: 'actual_dominant', symbol: 'ag', frequency: '5m' },
    canonicalBars,
    coverage,
    'replace',
  )
  second.resolve(response('ag', '5m', canonicalBars[1].time))
  await newSync
  first.resolve(response('jm', '5m', canonicalBars[0].time))
  await oldSync

  assert.equal(controller.markers.value.length, 1)
  assert.match(controller.markers.value[0].id, /\|ag\|/)
})

test('historical loader clips requests to canonical coverage and ignores live-only mutations', async () => {
  const requests: Array<Record<string, string>> = []
  const controller = useHistoricalResearchMarkers({
    fetchSubing: async (request) => {
      requests.push(request)
      return response(request.symbol, request.frequency, canonicalBars[1].time)
    },
  })
  const liveTail: BarData = {
    ...canonicalBars[1],
    time: '2026-08-04T01:05:00Z',
    trading_day: '2026-08-04',
  }
  const identity = {
    overlay: 'subing' as const,
    seriesKind: 'actual_dominant' as const,
    symbol: 'jm',
    frequency: '5m' as const,
  }

  await controller.sync(
    identity,
    [...canonicalBars, liveTail],
    { start: canonicalBars[0].time, end: canonicalBars[1].time },
    'replace',
  )
  await controller.sync(
    identity,
    [...canonicalBars, liveTail],
    { start: canonicalBars[0].time, end: canonicalBars[1].time },
    'live',
  )

  assert.deepEqual(requests, [{
    series_kind: 'actual_dominant',
    symbol: 'jm',
    frequency: '5m',
    since: '2026-08-03',
    through: '2026-08-03',
  }])
})

test('unsupported identity clears replay markers without requesting or mutating Kline bars', async () => {
  let requests = 0
  const bars = canonicalBars.map((bar) => ({ ...bar }))
  const controller = useHistoricalResearchMarkers({
    fetchSubing: async (request) => {
      requests += 1
      return response(request.symbol, request.frequency, canonicalBars[1].time)
    },
  })
  await controller.sync(
    { overlay: 'subing', seriesKind: 'actual_dominant', symbol: 'jm', frequency: '5m' },
    bars,
    { start: bars[0].time, end: bars[1].time },
    'replace',
  )
  assert.equal(controller.markers.value.length, 1)

  await controller.sync(
    { overlay: 'subing', seriesKind: 'continuous', symbol: 'jm', frequency: '5m' },
    bars,
    { start: bars[0].time, end: bars[1].time },
    'replace',
  )

  assert.equal(requests, 1)
  assert.deepEqual(controller.markers.value, [])
  assert.deepEqual(bars, canonicalBars)
})

test('prepend failure keeps confirmed markers and never mutates Kline bars', async () => {
  let fail = false
  const bars = canonicalBars.map((bar) => ({ ...bar }))
  const controller = useHistoricalResearchMarkers({
    fetchSubing: async (request) => {
      if (fail) throw new Error('offline')
      return response(request.symbol, request.frequency, canonicalBars[1].time)
    },
  })
  const identity = {
    overlay: 'subing' as const,
    seriesKind: 'actual_dominant' as const,
    symbol: 'jm',
    frequency: '5m' as const,
  }
  await controller.sync(
    identity,
    bars,
    { start: bars[0].time, end: bars[1].time },
    'replace',
  )
  const previous = [...controller.markers.value]
  fail = true
  const earlier = {
    ...bars[0],
    time: '2026-08-02T01:05:00Z',
    trading_day: '2026-08-02',
  }

  await controller.sync(
    identity,
    [earlier, ...bars],
    { start: earlier.time, end: bars[1].time },
    'prepend',
  )

  assert.deepEqual(controller.markers.value, previous)
  assert.equal(controller.error.value, 'HISTORICAL_RESEARCH_UNAVAILABLE')
  assert.deepEqual(bars, canonicalBars)
})

test('persisted SuBing AlertEvent overrides replay marker with the same dedupe identity', () => {
  const replay = historicalResearchEventToMarker(
    'jm',
    response('jm', '5m', canonicalBars[1].time).events[0],
  )
  const event: AlertEvent = {
    id: 42,
    rule_code: 'subing_entry_signal_v1',
    symbol: 'jm',
    contract: 'JM2609',
    trading_day: '2026-08-03',
    frequency: '5m',
    bar_end: canonicalBars[1].time,
    result_codes: ['buy'],
    lower_tf_confirmation: false,
    detected_at: canonicalBars[1].time,
    notification_attempted_at: null,
  }
  const persisted = alertEventsToMarkers([event])[0]

  assert.equal(replay.dedupeKey, persisted.dedupeKey)
  const merged = mergeKlineMarkers([persisted], [replay])
  assert.equal(merged.length, 1)
  assert.equal(merged[0].id, persisted.id)
  assert.equal(merged[0].label, '买入信号')
})

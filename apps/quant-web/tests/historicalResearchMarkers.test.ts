import assert from 'node:assert/strict'
import test from 'node:test'
import type {
  BarData,
  SubingStrategyEpisode,
  SubingStrategyHistoricalResponse,
} from '../src/types/market.ts'
import { useHistoricalResearchMarkers } from '../src/composables/useHistoricalResearchMarkers.ts'
import { subingStrategyActionToMarker } from '../src/utils/historicalResearchMarkers.ts'
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

function strategyResponse(
  symbol: string,
  since = '2026-08-03',
  through = '2026-08-03',
  state: 'open' | 'closed' = 'closed',
): SubingStrategyHistoricalResponse {
  const entry = {
    action_id: `subing-action:${symbol}:entry`, episode_id: `subing-episode:${symbol}`,
    strategy_id: 'subing_strategy_v1' as const,
    formula_version: 'subing_strategy_15m_v1' as const,
    kind: 'open_long' as const, symbol, contract: `${symbol.toUpperCase()}2609`,
    trading_day: '2026-08-03', segment_start_trading_day: '2026-08-01',
    opportunity_id: `subing-opportunity:${symbol}`,
    decision_at: '2026-08-03T01:05:00Z', effective_bar_end: '2026-08-03T01:10:00Z',
    reference_price: 100, fill_basis: 'next_bar_open' as const,
    confirmation_source: 'formal_v1' as const, reason_codes: [],
    direction_context_source_day: '2026-07-31',
    direction_context_target_day: '2026-08-03', bound_reference_pivot: null,
  }
  const exit = {
    ...entry,
    action_id: `subing-action:${symbol}:exit`, kind: 'close_long' as const,
    trading_day: '2026-08-03', decision_at: '2026-08-03T01:10:00Z',
    effective_bar_end: '2026-08-03T01:15:00Z', reference_price: 107.97,
    confirmation_source: null,
    reason_codes: ['EMA21_BREACH_LONG', 'MACD_HIGH_DEAD_CROSS'],
    direction_context_source_day: null, direction_context_target_day: null,
  }
  const episode: SubingStrategyEpisode = {
    episode_id: entry.episode_id, direction: 'long', entry_action: entry,
    exit_action: state === 'closed' ? exit : null, state,
    holding_bar_count: state === 'closed' ? 2 : 1,
    reference_change_percent: state === 'closed' ? 7.97 : null,
    current_reference_change_percent: state === 'open' ? 1 : null,
    latest_reference_price: state === 'open' ? 101 : null,
    exit_reason_codes: state === 'closed' ? [...exit.reason_codes] : [],
    structure_exit_available: false,
  }
  return {
    request: {
      series_kind: 'actual_dominant',
      symbol,
      frequency: '15m',
      since,
      through,
    },
    policy: {
      strategy_id: 'subing_strategy_v1', formula_version: 'subing_strategy_15m_v1',
      research_only: true, series_kind: 'actual_dominant', decision_frequency: '15m',
      lifecycle_policy_id: 'subing_lifecycle_v2_research_v1',
      allowed_confirmation_sources: [
        'formal_v1', 'momentum_hold', 'pivot_break_hold', 'pivot_retest_rebreak',
      ],
    },
    resolved_cutoff: '2026-08-03T01:15:00Z', segment_summaries: [],
    actions: state === 'closed' ? [entry, exit] : [entry], episodes: [episode],
    context_unavailable: [], cache_state: 'miss',
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
    assert.match(marker.tooltip, /^日进斗金参考回放 · /)
    assert.doesNotMatch(marker.tooltip, /日进斗金策略/)
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
    fetchSubingStrategy: async () => { throw new Error('wrong source') },
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
    fetchSubingStrategy: async () => { throw new Error('wrong source') },
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
    fetchSubingStrategy: async () => { throw new Error('wrong source') },
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
    fetchSubingStrategy: async () => { throw new Error('wrong source') },
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

test('SuBing Strategy marker anchors effective Bar and shows all close reasons', () => {
  const response = strategyResponse('jm')
  const episodes = new Map(response.episodes.map((episode) => [episode.episode_id, episode]))
  const open = subingStrategyActionToMarker(response.actions[0], episodes)
  const close = subingStrategyActionToMarker(response.actions[1], episodes)

  assert.equal(open.time, '2026-08-03T01:10:00Z')
  assert.equal(open.label, '▲ 建多')
  assert.equal(open.position, 'belowBar')
  assert.equal(open.shape, 'arrowUp')
  assert.equal(close.label, '× 清多')
  assert.equal(close.position, 'aboveBar')
  assert.match(close.tooltip!, /EMA21 跌破/)
  assert.match(close.tooltip!, /MACD 高位死叉/)
  assert.match(close.tooltip!, /参考变动 \+7\.97%/)
  assert.match(close.tooltip!, /模拟动作·非实际成交/)
  assert.match(close.tooltip!, /SuBing Strategy V1 · 15m/)
  assert.match(close.tooltip!, /方向 Context 2026-07-31 → 2026-08-03/)
  assert.match(close.tooltip!, /确认来源 formal_v1/)
  assert.match(close.tooltip!, /Opportunity subing-opportunity:jm/)
  assert.match(close.tooltip!, /结构退出 不可用/)
  assert.match(close.tooltip!, /持有 2 根 15m Bar/)
  assert.match(close.tooltip!, /生效口径 下一根同合约 15m open/)

  const closeShort = subingStrategyActionToMarker(
    { ...response.actions[1], kind: 'close_short' },
    new Map(),
  )
  assert.equal(closeShort.position, 'belowBar')
})

test('SuBing Strategy history requests only actual-dominant 15m', async () => {
  const requests: Array<Record<string, string>> = []
  const controller = useHistoricalResearchMarkers({
    fetchSubingStrategy: async (request) => {
      requests.push(request)
      return strategyResponse(request.symbol, request.since, request.through)
    },
  } as never)
  const coverage = { start: canonicalBars[0].time, end: canonicalBars[1].time }

  await controller.sync(
    { overlay: 'subing', seriesKind: 'actual_dominant', symbol: 'jm', frequency: '5m' },
    canonicalBars, coverage, 'replace',
  )
  assert.deepEqual(requests, [])
  await controller.sync(
    { overlay: 'subing', seriesKind: 'actual_dominant', symbol: 'jm', frequency: '15m' },
    canonicalBars, coverage, 'replace',
  )
  assert.deepEqual(requests, [{
    series_kind: 'actual_dominant', symbol: 'jm', frequency: '15m',
    since: '2026-08-03', through: '2026-08-03',
  }])
})

test('SuBing Strategy discards stale identity and merges prepend actions and Episodes', async () => {
  const stale = deferred<SubingStrategyHistoricalResponse>()
  let calls = 0
  const controller = useHistoricalResearchMarkers({
    fetchSubingStrategy: async (request: Record<string, string>) => {
      calls += 1
      if (calls === 1) return stale.promise
      const result = strategyResponse(request.symbol, request.since, request.through)
      if (calls === 3) {
        result.episodes[0] = strategyResponse(request.symbol, request.since, request.through, 'open').episodes[0]
        result.actions = [result.episodes[0].entry_action]
      }
      return result
    },
  } as never)
  const identity = {
    overlay: 'subing' as const, seriesKind: 'actual_dominant' as const,
    symbol: 'jm', frequency: '15m' as const,
  }
  const coverage = { start: canonicalBars[0].time, end: canonicalBars[1].time }

  const oldSync = controller.sync(identity, canonicalBars, coverage, 'replace')
  await controller.sync({ ...identity, symbol: 'ag' }, canonicalBars, coverage, 'replace')
  stale.resolve(strategyResponse('jm'))
  await oldSync
  assert.match(controller.markers.value[0].id, /ag/)

  await controller.sync(identity, canonicalBars, coverage, 'replace')
  assert.equal(controller.subingStrategyEpisodes.value[0].state, 'open')
  const earlier = { ...canonicalBars[0], time: '2026-08-02T01:05:00Z', trading_day: '2026-08-02' }
  await controller.sync(identity, [earlier, ...canonicalBars], {
    start: earlier.time, end: canonicalBars[1].time,
  }, 'prepend')
  assert.equal(controller.subingStrategyEpisodes.value[0].state, 'closed')
  assert.equal(new Set(controller.markers.value.map((marker) => marker.id)).size, 2)
})

test('complete Episode survives when only its exit Action is in the visible window', async () => {
  const controller = useHistoricalResearchMarkers({
    fetchSubingStrategy: async (request: Record<string, string>) => {
      const result = strategyResponse('jm', request.since, request.through)
      result.actions = [result.episodes[0].exit_action!]
      return result
    },
  } as never)
  await controller.sync(
    { overlay: 'subing', seriesKind: 'actual_dominant', symbol: 'jm', frequency: '15m' },
    canonicalBars, { start: canonicalBars[0].time, end: canonicalBars[1].time }, 'replace',
  )

  assert.deepEqual(controller.markers.value.map((marker) => marker.label), ['× 清多'])
  assert.equal(controller.subingStrategyEpisodes.value[0].entry_action.action_id,
    'subing-action:jm:entry')
})

test('prepend failure preserves Strategy markers, Episodes, and Kline bars', async () => {
  let fail = false
  const bars = canonicalBars.map((bar) => ({ ...bar }))
  const controller = useHistoricalResearchMarkers({
    fetchSubingStrategy: async (request: Record<string, string>) => {
      if (fail) throw new Error('offline')
      return strategyResponse('jm', request.since, request.through)
    },
  } as never)
  const identity = {
    overlay: 'subing' as const, seriesKind: 'actual_dominant' as const,
    symbol: 'jm', frequency: '15m' as const,
  }
  await controller.sync(identity, bars, {
    start: bars[0].time, end: bars[1].time,
  }, 'replace')
  const previousMarkers = [...controller.markers.value]
  const previousEpisodes = [...controller.subingStrategyEpisodes.value]
  fail = true
  const earlier = { ...bars[0], time: '2026-08-02T01:05:00Z', trading_day: '2026-08-02' }
  await controller.sync(identity, [earlier, ...bars], {
    start: earlier.time, end: bars[1].time,
  }, 'prepend')

  assert.deepEqual(controller.markers.value, previousMarkers)
  assert.deepEqual(controller.subingStrategyEpisodes.value, previousEpisodes)
  assert.equal(controller.error.value, 'HISTORICAL_RESEARCH_UNAVAILABLE')
  assert.deepEqual(bars, canonicalBars)
})

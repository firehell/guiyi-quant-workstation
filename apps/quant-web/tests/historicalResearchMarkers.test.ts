import assert from 'node:assert/strict'
import test from 'node:test'
import type { BarData, SubingStrategyEpisode, SubingStrategyHistoricalResponse } from '../src/types/market.ts'
import { useHistoricalResearchMarkers } from '../src/composables/useHistoricalResearchMarkers.ts'
import { subingStrategyActionToMarker } from '../src/utils/historicalResearchMarkers.ts'
import { RESEARCH_OVERLAY_DEFINITIONS, researchOverlayCapability } from '../src/utils/mainIndicators.ts'

const canonicalBars: BarData[] = [
  { time: '2026-08-03T01:05:00Z', trading_day: '2026-08-03', physicalContract: 'JM2609', open: 100, high: 101, low: 99, close: 100, volume: 10 },
  { time: '2026-08-03T01:10:00Z', trading_day: '2026-08-03', physicalContract: 'JM2609', open: 100, high: 101, low: 99, close: 100, volume: 10 },
]

function strategyResponse(
  symbol: string,
  since = '2026-08-03',
  through = '2026-08-03',
): SubingStrategyHistoricalResponse {
  const entry = {
    action_id: `subing-action:${symbol}:entry`, episode_id: `subing-episode:${symbol}`,
    strategy_id: 'subing_strategy_v1' as const, formula_version: 'subing_strategy_15m_v1' as const,
    kind: 'open_long' as const, symbol, contract: `${symbol.toUpperCase()}2609`,
    trading_day: '2026-08-03', segment_start_trading_day: '2026-08-01', opportunity_id: `subing-opportunity:${symbol}`,
    decision_at: '2026-08-03T01:05:00Z', effective_bar_end: '2026-08-03T01:10:00Z', reference_price: 100,
    fill_basis: 'next_bar_open' as const, confirmation_source: 'formal_v1' as const, reason_codes: [],
    direction_context_source_day: '2026-07-31', direction_context_target_day: '2026-08-03', bound_reference_pivot: null,
  }
  const exit = {
    ...entry, action_id: `subing-action:${symbol}:exit`, kind: 'close_long' as const,
    decision_at: '2026-08-03T01:10:00Z', effective_bar_end: '2026-08-03T01:15:00Z', reference_price: 107.97,
    confirmation_source: null, reason_codes: ['EMA21_BREACH_LONG', 'MACD_HIGH_DEAD_CROSS'],
    direction_context_source_day: null, direction_context_target_day: null,
  }
  const episode: SubingStrategyEpisode = {
    episode_id: entry.episode_id, direction: 'long', entry_action: entry, exit_action: exit, state: 'closed',
    holding_bar_count: 2, reference_change_percent: 7.97, current_reference_change_percent: null,
    latest_reference_price: null, exit_reason_codes: [...exit.reason_codes], structure_exit_available: false,
  }
  return {
    request: { series_kind: 'actual_dominant', symbol, frequency: '15m', since, through },
    policy: {
      strategy_id: 'subing_strategy_v1', formula_version: 'subing_strategy_15m_v1', research_only: true,
      series_kind: 'actual_dominant', decision_frequency: '15m', lifecycle_policy_id: 'subing_lifecycle_v2_research_v1',
      allowed_confirmation_sources: ['formal_v1', 'momentum_hold', 'pivot_break_hold', 'pivot_retest_rebreak'],
    },
    resolved_cutoff: '2026-08-03T01:15:00Z', segment_summaries: [], actions: [entry, exit], episodes: [episode],
    context_unavailable: [], cache_state: 'miss',
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((accept) => { resolve = accept })
  return { promise, resolve }
}

test('research Overlay exposes none, SuBing, and HTDY while retaining SuBing capability', () => {
  assert.deepEqual(
    RESEARCH_OVERLAY_DEFINITIONS.map(({ id, label }) => ({ id, label })),
    [{ id: 'none', label: '无' }, { id: 'subing', label: '苏冰' }, { id: 'htdy', label: '火天大有' }],
  )
  assert.deepEqual(researchOverlayCapability('subing', 'actual_dominant', '5m'), {
    supported: true, definition: RESEARCH_OVERLAY_DEFINITIONS[1],
  })
  assert.equal(researchOverlayCapability('subing', 'continuous', '5m').supported, false)
})

test('SuBing Strategy marker anchors effective bars and preserves simulated-action facts', () => {
  const response = strategyResponse('jm')
  const episodes = new Map(response.episodes.map((episode) => [episode.episode_id, episode]))
  const open = subingStrategyActionToMarker(response.actions[0], episodes)
  const close = subingStrategyActionToMarker(response.actions[1], episodes)

  assert.equal(open.time, '2026-08-03T01:10:00Z')
  assert.equal(open.label, '▲ 建多')
  assert.equal(open.position, 'belowBar')
  assert.doesNotMatch(open.tooltip!, /持有/)
  assert.equal(close.label, '× 清多')
  assert.equal(close.position, 'aboveBar')
  assert.match(close.tooltip!, /EMA21 跌破/)
  assert.match(close.tooltip!, /MACD 高位死叉/)
  assert.match(close.tooltip!, /参考变动 \+7\.97%/)
  assert.match(close.tooltip!, /模拟动作·非实际成交/)
  assert.match(close.tooltip!, /方向 Context 2026-07-31 → 2026-08-03/)
  assert.match(close.tooltip!, /确认来源 formal_v1/)
  assert.match(close.tooltip!, /Opportunity subing-opportunity:jm/)
  assert.match(close.tooltip!, /持有 2 根 15m Bar/)
  assert.match(close.tooltip!, /生效口径 下一根同合约 15m open/)

  const closeShort = subingStrategyActionToMarker(
    { ...response.actions[1], kind: 'close_short' },
    new Map(),
  )
  assert.equal(closeShort.position, 'belowBar')
})

test('SuBing Strategy marker keeps entry and terminal fill bases distinct', () => {
  const response = strategyResponse('jm')
  const terminalExit = { ...response.actions[1], fill_basis: 'segment_terminal_close' as const }
  const terminalEpisode = { ...response.episodes[0], exit_action: terminalExit }
  const close = subingStrategyActionToMarker(
    terminalExit,
    new Map([[terminalEpisode.episode_id, terminalEpisode]]),
  )

  assert.match(close.tooltip!, /入场生效口径 下一根同合约 15m open/)
  assert.match(close.tooltip!, /平仓生效口径 旧段末最后一根 15m close/)
})

test('SuBing Strategy history requests only actual-dominant 15m', async () => {
  const requests: Array<Record<string, string>> = []
  const controller = useHistoricalResearchMarkers({
    fetchSubingStrategy: async (request) => {
      requests.push(request)
      return strategyResponse(request.symbol, request.since, request.through)
    },
  })
  const coverage = { start: canonicalBars[0].time, end: canonicalBars[1].time }
  await controller.sync({ overlay: 'subing', seriesKind: 'actual_dominant', symbol: 'jm', frequency: '5m' }, canonicalBars, coverage, 'replace')
  assert.deepEqual(requests, [])
  await controller.sync({ overlay: 'subing', seriesKind: 'actual_dominant', symbol: 'jm', frequency: '15m' }, canonicalBars, coverage, 'replace')
  assert.deepEqual(requests, [{ series_kind: 'actual_dominant', symbol: 'jm', frequency: '15m', since: '2026-08-03', through: '2026-08-03' }])
})

test('complete SuBing Episode survives when only its exit Action is visible', async () => {
  const controller = useHistoricalResearchMarkers({
    fetchSubingStrategy: async (request) => {
      const result = strategyResponse(request.symbol, request.since, request.through)
      result.actions = [result.episodes[0].exit_action!]
      return result
    },
  })
  await controller.sync(
    { overlay: 'subing', seriesKind: 'actual_dominant', symbol: 'jm', frequency: '15m' },
    canonicalBars, { start: canonicalBars[0].time, end: canonicalBars[1].time }, 'replace',
  )

  assert.deepEqual(controller.markers.value.map((marker) => marker.label), ['× 清多'])
  assert.equal(controller.subingStrategyEpisodes.value[0].entry_action.action_id, 'subing-action:jm:entry')
})

test('SuBing Strategy prepend upgrades an open Episode without duplicate markers', async () => {
  let calls = 0
  const controller = useHistoricalResearchMarkers({
    fetchSubingStrategy: async (request) => {
      calls += 1
      const result = strategyResponse(request.symbol, request.since, request.through)
      if (calls === 1) {
        result.episodes[0] = {
          ...result.episodes[0], exit_action: null, state: 'open', holding_bar_count: 1,
          reference_change_percent: null, current_reference_change_percent: 1, latest_reference_price: 101,
          exit_reason_codes: [],
        }
        result.actions = [result.episodes[0].entry_action]
      }
      return result
    },
  })
  const identity = { overlay: 'subing' as const, seriesKind: 'actual_dominant' as const, symbol: 'jm', frequency: '15m' as const }
  await controller.sync(identity, canonicalBars, {
    start: canonicalBars[0].time, end: canonicalBars[1].time,
  }, 'replace')
  const earlier = { ...canonicalBars[0], time: '2026-08-02T01:05:00Z', trading_day: '2026-08-02' }
  await controller.sync(identity, [earlier, ...canonicalBars], {
    start: earlier.time, end: canonicalBars[1].time,
  }, 'prepend')

  assert.equal(controller.subingStrategyEpisodes.value[0].state, 'closed')
  assert.equal(new Set(controller.markers.value.map((marker) => marker.id)).size, 2)
})

test('SuBing Strategy ignores stale responses and preserves markers after a prepend failure', async () => {
  const stale = deferred<SubingStrategyHistoricalResponse>()
  let calls = 0
  let fail = false
  const bars = canonicalBars.map((bar) => ({ ...bar }))
  const controller = useHistoricalResearchMarkers({
    fetchSubingStrategy: async (request) => {
      calls += 1
      if (calls === 1) return stale.promise
      if (fail) throw new Error('offline')
      return strategyResponse(request.symbol, request.since, request.through)
    },
  })
  const identity = { overlay: 'subing' as const, seriesKind: 'actual_dominant' as const, symbol: 'jm', frequency: '15m' as const }
  const coverage = { start: bars[0].time, end: bars[1].time }
  const oldSync = controller.sync(identity, bars, coverage, 'replace')
  await controller.sync({ ...identity, symbol: 'ag' }, bars, coverage, 'replace')
  stale.resolve(strategyResponse('jm'))
  await oldSync
  assert.match(controller.markers.value[0].id, /ag/)

  await controller.sync(identity, bars, coverage, 'replace')
  const previousMarkers = [...controller.markers.value]
  const previousEpisodes = [...controller.subingStrategyEpisodes.value]
  const earlier = { ...bars[0], time: '2026-08-02T01:05:00Z', trading_day: '2026-08-02' }
  fail = true
  await controller.sync(identity, [earlier, ...bars], { start: earlier.time, end: bars[1].time }, 'prepend')
  assert.deepEqual(controller.markers.value, previousMarkers)
  assert.deepEqual(controller.subingStrategyEpisodes.value, previousEpisodes)
  assert.deepEqual(bars, canonicalBars)
  assert.equal(controller.error.value, 'HISTORICAL_RESEARCH_UNAVAILABLE')
})

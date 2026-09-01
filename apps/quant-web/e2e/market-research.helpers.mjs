import { expect } from '@playwright/test'
import {
  cloneSubingLifecycleCase,
  lifecycleChartBars,
  reidentifySubingResponse,
} from '../tests/fixtures/subingLifecycleCases.mjs'

export function bar(index) {
  const barEnd = new Date(Date.UTC(2026, 0, index + 1, 7)).toISOString()
  return {
    bar_end: barEnd, trading_day: barEnd.slice(0, 10), open: 99 + index, high: 102 + index,
    low: 98 + index, close: 100 + index, volume: 1_000 + index, turnover: 10_000 + index,
    open_interest: 2_000 + index,
  }
}

export function research(oiChange = 0.06) {
  return {
    symbol: 'ag', product_name: '白银', sector: 'precious', exchange: 'SHFE',
    series_kind: 'actual_dominant', contract: null, as_of: '2026-08-11', current_dominant: 'AG2601',
    dominant_mapping_date: '2026-08-11', daily_trend: 'up', weekly_trend: 'neutral', position20: 0.85,
    distance_to_20d_high: 0.03, distance_to_20d_low: 0.21, volume_ratio20: 1.42,
    oi_change_1d: oiChange, turnover_change_5d: 0.12, atr14_percentile252: 0.76,
    recent_daily: Array.from({ length: 40 }, (_, index) => ({
      ...bar(index), open_interest: oiChange === null ? null : 2_000 + index,
    })),
  }
}

export function dailyWatchItem(symbol, productName = symbol.toUpperCase()) {
  const trend = {
    bar_end: '2026-08-24T07:00:00Z', trading_day: '2026-08-24', physical_contract: `${symbol.toUpperCase()}2701`,
    current_segment_start_trading_day: '2026-07-20', warmup_start_trading_day: '2026-07-01',
    warmup_bar_count: 30, warmup_segment_count: 2, history_mode: 'rank1_stitched_raw',
    close: '3512.125', ema21: '3478.2468', price_side: 'above',
    slope_5_bps_per_bar: '8.6214', slope_10_bps_per_bar: '5.9173',
  }
  return {
    symbol, product_name: productName, sector: 'black', decision: 'long_watch',
    reason_codes: ['D1_H1_LONG_ALIGNED'], daily: trend, hourly: trend, unavailable_reasons: [],
  }
}

export function dailyWatch({ long_watch = [], short_watch = [], unavailable = [], excluded = 60 } = {}) {
  return {
    projection_version: 'subing_daily_watch_v2',
    formula_version: 'subing_ema21_rank1_stitched_raw_v2',
    history_mode: 'rank1_stitched_raw',
    status: 'ready', expected_target_trading_day: '2026-08-25', latest_target_trading_day: '2026-08-25', error_code: null,
    snapshot: {
      source_trading_day: '2026-08-24', target_trading_day: '2026-08-25', generated_at: '2026-08-24T10:24:13Z',
      counts: { universe: long_watch.length + short_watch.length + unavailable.length + excluded, long_watch: long_watch.length, short_watch: short_watch.length, excluded, unavailable: unavailable.length },
      long_watch, short_watch, unavailable,
    },
  }
}

export function runtimeHealth(overrides = {}) {
  return {
    status: 'ok', generated_at: '2026-08-24T10:15:00+00:00', readonly: true,
    would_start_services: false, would_enqueue_jobs: false, would_send_notifications: false,
    components: {
      db: { status: 'ok', latency_ms: 1.2, error_type: null, error_message: null },
      redis: { status: 'ok', latency_ms: 0.8, error_type: null, error_message: null },
      live_market: {
        status: 'ok', configured_enabled: true, operational_count: 60, subscribed_count: 60,
        last_heartbeat_at: '2026-08-24T10:14:58+00:00', last_bar_at: '2026-08-24T10:14:00+00:00',
        phase_counts: { closed: 60 }, error_type: null, error_message: null,
      },
      alert: {
        status: 'ok', configured_enabled: true,
        notification: { transport: 'pushplus', configured: true, audience_count: 2, would_send: false },
        last_heartbeat_at: '2026-08-24T10:14:57+00:00', enabled_rule_count: 2, scope_product_count: 60,
        processing_state: 'unobserved', notification_state: 'provider_accepted', last_processed_bar_at: null,
        last_processing_success_at: null, last_processing_failure_at: null, processing_error_type: null,
        last_event_at: '2026-08-24T10:00:01+00:00', last_transport_attempt_at: '2026-08-24T10:00:02+00:00',
        last_provider_accepted_at: '2026-08-24T10:00:02+00:00', last_notification_failure_at: null,
        notification_error_type: null, consecutive_notification_failures: 0, error_type: null,
      },
      after_market: {
        status: 'ok', configured_enabled: true, run_state: 'completed', expected_trading_day: '2026-08-24',
        current_run: null,
        last_run: {
          trading_day: '2026-08-24', status: 'passed', attempts: 1,
          started_at: '2026-08-24T10:05:00+00:00', finished_at: '2026-08-24T10:10:00+00:00',
          products: ['jm'], error_code: null,
          failure_notification: { attempted_at: '2026-08-24T10:10:01+00:00', state: 'provider_accepted', error_type: null },
        },
        last_successful_trading_day: '2026-08-24', last_failure: null, error_type: null, error_message: null,
      },
    },
    ...overrides,
  }
}

export async function mockMarketHomepage(
  page,
  dailyWatchResponse = dailyWatch(),
  runtimeResponse = runtimeHealth(),
) {
  await page.route('**/api/runtime/health', (route) => route.fulfill({ json: runtimeResponse }))
  await page.route('**/api/v1/market/research/subing-daily-watch/current', (route) => route.fulfill({ json: dailyWatchResponse }))
}

export function subing(overrides = {}) {
  return { ...cloneSubingLifecycleCase('longSetup'), ...overrides }
}

export function panelEvent(overrides = {}) {
  const event = {
    id: 301,
    rule_code: 'subing_strategy_v1',
    symbol: 'ag',
    contract: 'AG2601',
    trading_day: '2026-01-12',
    frequency: '15m',
    bar_end: '2026-01-12T02:30:00Z',
    result_codes: ['open_long'],
    action_id: 'subing-action:301',
    detected_at: '2026-01-12T02:30:01Z',
    notification_attempted_at: null,
    ...overrides,
  }
  if (event.rule_code !== 'subing_strategy_v1') {
    return { ...event, action_id: null, strategy_action: null }
  }
  const kind = event.result_codes[0]
  const actionId = event.action_id || `subing-action:${event.id}`
  return {
    ...event,
    action_id: actionId,
    strategy_action: {
      schema_version: 1,
      strategy_id: 'subing_strategy_v1',
      formula_version: 'subing_strategy_15m_v1',
      action_id: actionId,
      episode_id: `subing-episode:${event.id}`,
      kind,
      symbol: event.symbol,
      contract: event.contract,
      trading_day: event.trading_day,
      segment_start_trading_day: '2026-01-01',
      opportunity_id: `subing-opportunity:${event.id}`,
      decision_at: event.bar_end,
      effective_open_at: event.bar_end,
      effective_bar_end: event.bar_end,
      reference_price: '101.5',
      fill_basis: 'next_bar_open',
      confirmation_source: 'formal_v1',
      reason_codes: [],
      direction_context_source_day: '2026-01-09',
      direction_context_target_day: '2026-01-12',
      bound_reference_pivot: null,
      entry: null,
      holding_bar_count: null,
      reference_change_percent: null,
    },
  }
}

export function emptySubingStrategyHistory(request) {
  return {
    request,
    policy: {
      strategy_id: 'subing_strategy_v1', formula_version: 'subing_strategy_15m_v1',
      research_only: true, series_kind: 'actual_dominant', decision_frequency: '15m',
      lifecycle_policy_id: 'subing_lifecycle_v2_research_v1',
      allowed_confirmation_sources: [
        'formal_v1', 'momentum_hold', 'pivot_break_hold', 'pivot_retest_rebreak',
      ],
    },
    resolved_cutoff: `${request.through}T07:00:00Z`, segment_summaries: [],
    actions: [], episodes: [], context_unavailable: [], cache_state: 'unavailable',
  }
}

export function subingStrategyCurrent(request, contract = 'AG2601', overrides = {}) {
  return {
    strategy_id: 'subing_strategy_v1', formula_version: 'subing_strategy_15m_v1',
    series_kind: 'actual_dominant', symbol: request.symbol, frequency: '15m', contract,
    segment_start_trading_day: '2026-01-01', source_mode: 'canonical',
    cutoff: '2026-01-12T02:30:00Z', position_state: 'flat', pending_action: null,
    current_episode: null, latest_completed_episode: null,
    direction_context: {
      symbol: request.symbol, target_trading_day: '2026-01-12', source_trading_day: '2026-01-09',
      direction: 'no_new_entry', reason_codes: [], daily_bar_end: null, hourly_bar_end: null,
      physical_contract: contract,
    },
    ...overrides,
  }
}

export function subingStrategyHistory(request, entryTime, exitTime) {
  const decisionBefore = (value) => new Date(Date.parse(value) - 15 * 60 * 1000).toISOString()
  const entry = {
    action_id: 'subing-action:e2e-entry', episode_id: 'subing-episode:e2e',
    strategy_id: 'subing_strategy_v1', formula_version: 'subing_strategy_15m_v1',
    kind: 'open_long', symbol: request.symbol, contract: 'AG2601',
    trading_day: entryTime.slice(0, 10), segment_start_trading_day: entryTime.slice(0, 10),
    opportunity_id: 'subing-opportunity:e2e', decision_at: decisionBefore(entryTime),
    effective_open_at: decisionBefore(entryTime),
    effective_bar_end: entryTime, reference_price: '100.5', fill_basis: 'next_bar_open',
    confirmation_source: 'formal_v1', reason_codes: [],
    direction_context_source_day: entryTime.slice(0, 10),
    direction_context_target_day: entryTime.slice(0, 10), bound_reference_pivot: null,
  }
  const exit = {
    ...entry, action_id: 'subing-action:e2e-exit', kind: 'close_long',
    trading_day: exitTime.slice(0, 10), decision_at: decisionBefore(exitTime),
    effective_open_at: decisionBefore(exitTime),
    effective_bar_end: exitTime, reference_price: '108.50985', confirmation_source: null,
    reason_codes: ['EMA21', 'MACD_HIGH_DEAD_CROSS'],
    direction_context_source_day: null, direction_context_target_day: null,
  }
  return {
    ...emptySubingStrategyHistory(request),
    resolved_cutoff: exitTime,
    segment_summaries: [{
      contract: 'AG2601', start_trading_day: entry.trading_day,
      end_trading_day: exit.trading_day, loaded_through: exit.trading_day,
      bar_count_5m: 3, bar_count_15m: 2, initial_position: 'flat',
      final_position: 'flat', terminal_bar_end: null, pending_action: false,
    }],
    actions: [entry, exit],
    episodes: [{
      episode_id: entry.episode_id, direction: 'long', entry_action: entry,
      exit_action: exit, state: 'closed', holding_bar_count: 20,
      reference_change_percent: '7.97', current_reference_change_percent: null,
      latest_reference_price: null,
      exit_reason_codes: ['EMA21', 'MACD_HIGH_DEAD_CROSS'],
      structure_exit_available: false,
    }],
  }
}

export function subingStrategyPerformance(symbol, episodes = [], exitReasonCounts = null) {
  const stats = (items) => {
    const closed = items.filter((item) => item.state === 'closed')
    if (closed.length === 0) return {
      completed: 0, positive: 0, negative: 0, flat: 0,
      positive_rate_percent: null, mean_reference_change_percent: null,
      median_reference_change_percent: null, best_reference_change_percent: null,
      worst_reference_change_percent: null, mean_holding_15m_bars: null,
    }
    const changes = closed.map((item) => Number(item.reference_change_percent))
    const ordered = [...changes].sort((left, right) => left - right)
    const middle = Math.floor(ordered.length / 2)
    const median = ordered.length % 2
      ? ordered[middle]
      : (ordered[middle - 1] + ordered[middle]) / 2
    const positive = changes.filter((value) => value > 0).length
    return {
      completed: closed.length,
      positive,
      negative: changes.filter((value) => value < 0).length,
      flat: changes.filter((value) => value === 0).length,
      positive_rate_percent: String(positive / closed.length * 100),
      mean_reference_change_percent: String(changes.reduce((sum, value) => sum + value, 0) / closed.length),
      median_reference_change_percent: String(median),
      best_reference_change_percent: String(Math.max(...changes)),
      worst_reference_change_percent: String(Math.min(...changes)),
      mean_holding_15m_bars: String(closed.reduce((sum, item) => sum + item.holding_bar_count, 0) / closed.length),
    }
  }
  const resolvedExitReasonCounts = exitReasonCounts || [...episodes.reduce((counts, episode) => {
    for (const reasonCode of episode.exit_reason_codes) {
      counts.set(reasonCode, (counts.get(reasonCode) || 0) + 1)
    }
    return counts
  }, new Map())].map(([reason_code, count]) => ({ reason_code, count }))
  return {
    strategy_id: 'subing_strategy_v1', formula_version: 'subing_strategy_15m_v1',
    symbol, series_kind: 'actual_dominant', frequency: '15m',
    coverage: {
      since: '2026-01-01', through: '2026-04-30', resolved_cutoff: '2026-04-30T07:00:00Z',
      segment_count: 1, bar_count_15m: 120, context_unavailable_count: 0,
    },
    cache_state: 'hit',
    cache_identity_sha256: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    cache_generated_at: '2026-08-27T06:00:00Z',
    summary: {
      overall: stats(episodes),
      long: stats(episodes.filter((item) => item.direction === 'long')),
      short: stats(episodes.filter((item) => item.direction === 'short')),
      open_episodes: episodes.filter((item) => item.state === 'open').length,
    },
    exit_reason_counts: resolvedExitReasonCounts, episodes,
  }
}

export async function mockWorkspace(page, researchResponse, options = {}) {
  const workspaceSymbol = options.symbol || 'ag'
  const workspaceContract = options.resolvedContract || (workspaceSymbol === 'jm' ? 'JM2701' : 'AG2601')
  const marketRequests = options.marketRequests || []
  const researchRequests = options.researchRequests || []
  const subingRequests = options.subingRequests || []
  const subingStrategyHistoricalRequests = options.subingStrategyHistoricalRequests || []
  const dominantRequests = options.dominantRequests || []
  let dominantResponseIndex = 0
  let subingResponseIndex = 0
  await page.route('**/api/v1/market/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/research/subing-strategy/performance')) {
      const request = Object.fromEntries(url.searchParams)
      const configured = typeof options.subingStrategyPerformanceResponse === 'function'
        ? options.subingStrategyPerformanceResponse(request)
        : options.subingStrategyPerformanceResponse
      return route.fulfill({ json: configured || subingStrategyPerformance(request.symbol) })
    }
    if (url.pathname.endsWith('/research/subing-strategy/current')) {
      const request = Object.fromEntries(url.searchParams)
      const configured = typeof options.subingStrategyCurrentResponse === 'function'
        ? options.subingStrategyCurrentResponse(request)
        : options.subingStrategyCurrentResponse
      return route.fulfill({ json: configured || subingStrategyCurrent(request, workspaceContract) })
    }
    if (url.pathname.endsWith('/research/subing-strategy/history')) {
      const request = Object.fromEntries(url.searchParams)
      subingStrategyHistoricalRequests.push(request)
      const configured = typeof options.subingStrategyHistoricalResponse === 'function'
        ? options.subingStrategyHistoricalResponse(request)
        : options.subingStrategyHistoricalResponse
      return route.fulfill({ json: configured || emptySubingStrategyHistory(request) })
    }
    if (url.pathname.endsWith('/dominants')) {
      dominantRequests.push(Object.fromEntries(url.searchParams))
      if (dominantResponseIndex > 0 && options.dominantsRefreshDelayMs) {
        await new Promise((resolve) => setTimeout(resolve, options.dominantsRefreshDelayMs))
      }
      const responses = options.dominantsResponses || []
      const response = responses[Math.min(dominantResponseIndex, responses.length - 1)]
        || { items: [{
          product: workspaceSymbol,
          product_name: options.productName || (workspaceSymbol === 'jm' ? '焦煤' : '白银'),
          sector: options.sector || (workspaceSymbol === 'jm' ? 'black' : 'precious'),
          exchange: options.exchange || (workspaceSymbol === 'jm' ? 'DCE' : 'SHFE'),
          actual_contract: workspaceContract,
          dominant_mapping_date: '2026-01-12',
        }] }
      dominantResponseIndex += 1
      return route.fulfill({ json: response })
    }
    if (url.pathname.endsWith('/research/product')) {
      researchRequests.push(Object.fromEntries(url.searchParams))
      return route.fulfill(researchResponse)
    }
    if (url.pathname.endsWith('/research/subing')) {
      subingRequests.push(Object.fromEntries(url.searchParams))
      if (options.subingDelayMs) await new Promise((resolve) => setTimeout(resolve, options.subingDelayMs))
      const responses = options.subingResponses || []
      const response = responses[Math.min(subingResponseIndex, responses.length - 1)]
        || options.subingResponse
        || subing()
      subingResponseIndex += 1
      if (response?.__http_status) {
        return route.fulfill({ status: response.__http_status, json: response.json || { detail: 'unavailable' } })
      }
      return route.fulfill({ json: response })
    }
    if (url.pathname.endsWith('/state')) {
      if (options.marketStateDelayMs) {
        await new Promise((resolve) => setTimeout(resolve, options.marketStateDelayMs))
      }
      return route.fulfill({ json: { symbol: workspaceSymbol, series_kind: url.searchParams.get('series_kind'), frequency: url.searchParams.get('frequency'), operational: true, phase: options.live ? 'TRADING' : 'CLOSED', trading_day: '2026-08-11', live_eligible: !!options.live, live_available: !!options.live, live_contract: options.live ? workspaceContract : null, canonical_end: null, after_market: options.afterMarket || {} } })
    }
    if (url.pathname.endsWith('/bars/page')) {
      const request = Object.fromEntries(url.searchParams)
      marketRequests.push(request)
      const paged = options.barsPage?.(request)
      const bars = paged?.bars || options.bars || Array.from({ length: 120 }, (_, index) => bar(index))
      const resolvedContractSegments = options.resolvedContractSegments || (
        request.series_kind === 'actual_dominant' && bars.length > 0
          ? [{
              contract: workspaceContract,
              start_trading_day: bars[0].trading_day,
              end_trading_day: bars.at(-1).trading_day,
            }]
          : []
      )
      return route.fulfill({ json: {
        request: { series_kind: request.series_kind, symbol: workspaceSymbol, contract: request.contract || null, frequency: request.frequency, before: null, limit: 1200 },
        bars,
        canonical_coverage: options.canonicalCoverage || null,
        page: paged?.page || options.pageMeta || { has_more_before: false, next_before: null },
        resolved_contract_segments: resolvedContractSegments,
      } })
    }
    return route.abort()
  })
}

export async function mockAlertMarkerSurface(page, currentItems = [], options = {}) {
  const symbol = options.symbol || 'ag'
  const contract = options.contract || (symbol === 'jm' ? 'JM2701' : 'AG2601')
  await page.route('**/api/runtime/health', (route) => route.fulfill({ json: {
    status: 'ok', components: { alert: { status: 'disabled' } },
  } }))
  await page.route('**/api/alerts/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith(`/products/${symbol}`)) {
      if (options.alertScopeGate) await options.alertScopeGate.promise
      else if (options.alertScopeDelayMs) await new Promise((resolve) => setTimeout(resolve, options.alertScopeDelayMs))
      return route.fulfill({ json: { symbol, rules: options.rules || [] } })
    }
    if (url.pathname.endsWith('/current-events')) {
      if (options.currentEventsDelayMs) await new Promise((resolve) => setTimeout(resolve, options.currentEventsDelayMs))
      return route.fulfill({ json: {
        status: options.currentEventsStatus || 'ready',
        trading_day: options.currentEventsStatus === 'unavailable' ? null : '2026-01-12',
        items: currentItems,
      } })
    }
    if (url.pathname.endsWith('/events')) return route.fulfill({ json: {
      items: options.persistentItems || [],
    } })
    return route.abort()
  })
}

export async function mockProductIdentityWorkspace(page) {
  const calls = { bars: [], research: [], subing: [], performance: [], scope: [], events: [], put: [] }
  const gates = {
    jmBars: deferred(),
    jm15mBars: deferred(),
    jmResearch: deferred(),
    jmSubing: deferred(),
    jmScope: deferred(),
    jmEvents: deferred(),
    jmPerformance: deferred(),
    initialAgResearch: deferred(),
    initialAgSubing: deferred(),
    initialAgScope: deferred(),
    initialAgEvents: deferred(),
    initialAgPerformance: deferred(),
    finalAgResearch: deferred(),
    finalAgSubing: deferred(),
    finalAgScope: deferred(),
    finalAgEvents: deferred(),
    finalAgPerformance: deferred(),
  }
  const agRequestCounts = { research: 0, subing: 0, performance: 0, scope: 0, events: 0 }
  const contracts = { ag: 'AG2601', jm: 'JM2701' }
  const productNames = { ag: '白银', jm: '焦煤' }

  await page.route('**/api/v1/market/**', async (route) => {
    const url = new URL(route.request().url())
    const requestedSymbol = url.searchParams.get('symbol') || 'ag'
    if (url.pathname.endsWith('/dominants')) {
      return route.fulfill({ json: { items: ['ag', 'jm'].map((item) => ({
        product: item,
        product_name: productNames[item],
        sector: item === 'ag' ? 'precious' : 'black',
        exchange: item === 'ag' ? 'SHFE' : 'DCE',
        actual_contract: contracts[item],
        dominant_mapping_date: '2026-01-12',
      })) } })
    }
    if (url.pathname.endsWith('/research/subing-strategy/history')) {
      const request = Object.fromEntries(url.searchParams)
      return route.fulfill({ json: emptySubingStrategyHistory(request) })
    }
    if (url.pathname.endsWith('/research/subing-strategy/performance')) {
      const index = requestedSymbol === 'ag' ? agRequestCounts.performance++ : 0
      calls.performance.push(requestedSymbol)
      await identityFactGate(gates, 'Performance', requestedSymbol, index)
      try {
        return await route.fulfill({ json: subingStrategyPerformance(requestedSymbol) })
      } catch {
        return undefined
      }
    }
    if (url.pathname.endsWith('/research/product')) {
      const index = requestedSymbol === 'ag' ? agRequestCounts.research++ : 0
      calls.research.push(requestedSymbol)
      await identityFactGate(gates, 'Research', requestedSymbol, index)
      return route.fulfill({ json: identityResearch(
        requestedSymbol,
        requestedSymbol === 'jm' ? -0.042 : index === 0 ? 0.061 : 0.092,
      ) })
    }
    if (url.pathname.endsWith('/research/subing')) {
      const index = requestedSymbol === 'ag' ? agRequestCounts.subing++ : 0
      calls.subing.push(requestedSymbol)
      await identityFactGate(gates, 'Subing', requestedSymbol, index)
      return route.fulfill({ json: identitySubing(
        requestedSymbol,
        contracts[requestedSymbol],
        requestedSymbol === 'jm' ? -4.2 : index === 0 ? 6.1 : 9.2,
      ) })
    }
    if (url.pathname.endsWith('/bars/page')) {
      calls.bars.push(requestedSymbol)
      if (requestedSymbol === 'jm') {
        await (url.searchParams.get('frequency') === '15m' ? gates.jm15mBars : gates.jmBars).promise
      }
      const items = Array.from({ length: 120 }, (_, index) => bar(index))
      return route.fulfill({ json: {
        request: {
          series_kind: url.searchParams.get('series_kind'),
          symbol: requestedSymbol,
          contract: null,
          frequency: url.searchParams.get('frequency'),
          before: null,
          limit: 1200,
        },
        bars: items,
        canonical_coverage: null,
        page: { has_more_before: false, next_before: null },
        resolved_contract_segments: [{
          contract: contracts[requestedSymbol],
          start_trading_day: items[0].trading_day,
          end_trading_day: items.at(-1).trading_day,
        }],
      } })
    }
    if (url.pathname.endsWith('/state')) {
      return route.fulfill({ json: {
        symbol: requestedSymbol,
        series_kind: url.searchParams.get('series_kind'),
        frequency: url.searchParams.get('frequency'),
        operational: true,
        phase: 'CLOSED',
        trading_day: '2026-08-11',
        live_eligible: false,
        live_available: false,
        live_contract: null,
        canonical_end: null,
        after_market: {},
      } })
    }
    return route.abort()
  })
  await page.route('**/api/runtime/health', (route) => route.fulfill({ json: {
    status: 'ok', components: { alert: { status: 'disabled' } },
  } }))
  await page.route('**/api/alerts/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (request.method() === 'PUT') {
      calls.put.push(url.pathname)
      return route.fulfill({ status: 500, json: { detail: 'unexpected PUT' } })
    }
    const currentEventsMatch = url.pathname.match(/\/products\/(ag|jm)\/current-events$/)
    if (currentEventsMatch) {
      const requestedSymbol = currentEventsMatch[1]
      const index = requestedSymbol === 'ag' ? agRequestCounts.events++ : 0
      calls.events.push(requestedSymbol)
      await identityFactGate(gates, 'Events', requestedSymbol, index)
      const id = index === 0 ? 401 : requestedSymbol === 'ag' ? 409 : 502
      return route.fulfill({ json: {
        status: 'ready',
        trading_day: '2026-01-12',
        items: [panelEvent({
          id,
          symbol: requestedSymbol,
          contract: contracts[requestedSymbol],
          result_codes: requestedSymbol === 'jm' ? ['open_long'] : ['open_short'],
        })],
      } })
    }
    const scopeMatch = url.pathname.match(/\/products\/(ag|jm)$/)
    if (scopeMatch) {
      const requestedSymbol = scopeMatch[1]
      const index = requestedSymbol === 'ag' ? agRequestCounts.scope++ : 0
      calls.scope.push(requestedSymbol)
      await identityFactGate(gates, 'Scope', requestedSymbol, index)
      const suffix = requestedSymbol === 'jm' ? 'JM' : index === 0 ? 'OLD' : 'FINAL'
      return route.fulfill({ json: { symbol: requestedSymbol, rules: [{
        rule_code: 'subing_strategy_v1',
        display_name: `${requestedSymbol.toUpperCase()} ${suffix} Scope`,
        kind: 'strategy_action',
        input_frequencies: ['5m', '15m'],
        enabled_for_product: true,
        enabled_frequencies: [],
      }] } })
    }
    if (url.pathname.endsWith('/events')) return route.fulfill({ json: { items: [] } })
    return route.abort()
  })

  return { calls, gates }
}

export function identityResearch(symbol, oiChange) {
  return {
    ...research(oiChange),
    symbol,
    product_name: symbol === 'ag' ? '白银' : '焦煤',
    sector: symbol === 'ag' ? 'precious' : 'black',
    exchange: symbol === 'ag' ? 'SHFE' : 'DCE',
    current_dominant: symbol === 'ag' ? 'AG2601' : 'JM2701',
  }
}

export function identitySubing(symbol, contract, slope) {
  const response = reidentifySubingResponse(cloneSubingLifecycleCase('longSetup'), contract)
  response.symbol = symbol
  response.primary.snapshot.slope_5_bps_per_bar = String(slope)
  return response
}

export function identityFactGate(gates, kind, symbol, index) {
  if (symbol === 'jm') return gates[`jm${kind}`].promise
  return gates[index === 0 ? `initialAg${kind}` : `finalAg${kind}`].promise
}

export function deferred() {
  let resolve
  const promise = new Promise((resolver) => { resolve = resolver })
  return { promise, resolve }
}

export async function selectProduct(page, label) {
  await page.getByLabel('品种').click()
  await page.locator('.n-base-select-option').filter({ hasText: label }).click()
}

export function releaseIdentityFacts(gates, prefix) {
  for (const kind of ['Research', 'Subing', 'Performance', 'Scope', 'Events']) gates[`${prefix}${kind}`].resolve()
}

export async function openDataDetails(page) {
  const details = page.getByTestId('product-check-data-details')
  if (!(await details.getAttribute('open'))) await details.locator('summary').click()
  return details
}

export async function openSubingResearchDetails(page) {
  const details = page.getByTestId('subing-research-details')
  if (!(await details.getAttribute('open'))) await details.locator('summary').click()
  return details
}

export async function enableSubingInternalProcess(page) {
  await page.getByRole('button', { name: '图表设置', exact: true }).click()
  await expect(page.getByRole('group', { name: 'EMA' }).getByRole('button')).toHaveText(['EMA10', 'EMA21', 'EMA60'])
  const toggle = page.getByRole('switch', { name: '显示苏冰内部研究过程', exact: true })
  await expect(toggle).toBeVisible()
  if (!(await toggle.isChecked())) await toggle.click()
  await page.keyboard.press('Escape')
  await openSubingResearchDetails(page)
}

export async function enableSubingStrategyPerformance(page) {
  await page.getByRole('button', { name: '图表设置', exact: true }).click()
  const toggle = page.getByRole('switch', { name: '显示全历史策略效果', exact: true })
  await expect(toggle).toBeVisible()
  if (!(await toggle.isChecked())) await toggle.click()
  await page.keyboard.press('Escape')
}

export {
  cloneSubingLifecycleCase,
  lifecycleChartBars,
  reidentifySubingResponse,
}

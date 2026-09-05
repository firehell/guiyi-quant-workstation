export function detailResearch(symbol) {
  const upper = symbol.toUpperCase()
  return {
    symbol,
    product_name: symbol === 'jm' ? '焦煤' : '螺纹钢',
    sector: '黑色',
    exchange: symbol === 'jm' ? 'DCE' : 'SHFE',
    series_kind: 'actual_dominant',
    contract: null,
    as_of: '2026-09-03T02:45:00Z',
    current_dominant: `${upper}2601`,
    dominant_mapping_date: '2026-09-03',
    daily_trend: 'neutral',
    weekly_trend: 'neutral',
    position20: null,
    distance_to_20d_high: null,
    distance_to_20d_low: null,
    volume_ratio20: null,
    oi_change_1d: null,
    turnover_change_5d: null,
    atr14_percentile252: null,
    recent_daily: [],
  }
}

export function detailBar(symbol, index, close = 100 + index) {
  const time = new Date(Date.UTC(2026, 8, 3, 2, 30 + index * 15)).toISOString()
  return {
    bar_end: time,
    trading_day: '2026-09-03',
    open: close - 1,
    high: close + 2,
    low: close - 2,
    close,
    volume: 1_000 + index,
    turnover: 10_000 + index,
    open_interest: 2_000 + index,
    physical_contract: `${symbol.toUpperCase()}2601`,
  }
}

const trendDays = [
  '2026-08-21', '2026-08-24', '2026-08-25', '2026-08-26', '2026-08-27',
  '2026-08-28', '2026-08-31', '2026-09-01', '2026-09-02', '2026-09-03',
]
const trendCloses = [98, 100, 102, 105, 103, 101, 104, 107, 109, 111]

export function trendGenericBars(symbol = 'jm') {
  const upper = symbol.toUpperCase()
  return trendDays.map((tradingDay, index) => {
    const close = trendCloses[index]
    return {
      bar_end: `${tradingDay}T07:00:00.000Z`,
      trading_day: tradingDay,
      open: close - 1,
      high: close + 2,
      low: close - 2,
      close,
      volume: 2_000 + index * 100,
      turnover: 200_000 + index * 10_000,
      open_interest: 3_000 + index * 50,
      physical_contract: index < 4 ? `${upper}2601` : `${upper}2605`,
    }
  })
}

export function assertNewowCupFixtureLifecycle(fixture) {
  const barIndex = new Map(fixture.bars.map((bar, index) => [bar.bar_end, index]))
  const segmentFor = (barEnd) => fixture.bars[barIndex.get(barEnd)]?.segment_id
  const cups = new Map()

  for (const cup of fixture.cup_handles) {
    if (cups.has(cup.candidate_id)) throw new Error(`duplicate Cup candidate ${cup.candidate_id}`)
    cups.set(cup.candidate_id, cup)
  }

  const markersByCandidate = new Map([...cups.keys()].map((candidateId) => [candidateId, []]))
  for (const marker of fixture.cup_markers) {
    const candidateId = marker.trigger_facts?.candidate_id
    if (!markersByCandidate.has(candidateId)) throw new Error(`orphan Cup marker ${marker.marker_id}`)
    markersByCandidate.get(candidateId).push(marker)
  }

  const expectedLifecycle = {
    FORMING: [],
    READY: ['CUP_HANDLE_READY'],
    BREAKOUT: ['CUP_HANDLE_READY', 'CUP_HANDLE_BREAKOUT'],
    WEAKENED: ['CUP_HANDLE_READY', 'CUP_HANDLE_BREAKOUT', 'CUP_HANDLE_WEAKENED'],
    INVALIDATED: ['CUP_HANDLE_READY', 'CUP_HANDLE_BREAKOUT', 'CUP_HANDLE_INVALIDATED'],
    EXPIRED: ['CUP_HANDLE_READY', 'CUP_HANDLE_BREAKOUT', 'CUP_HANDLE_EXPIRED'],
  }

  for (const [candidateId, cup] of cups) {
    const markers = markersByCandidate.get(candidateId)
    const actualTypes = markers.map((marker) => marker.marker_type)
    const expectedTypes = expectedLifecycle[cup.state]
    if (JSON.stringify(actualTypes) !== JSON.stringify(expectedTypes)) {
      throw new Error(`invalid Cup lifecycle ${candidateId}: ${actualTypes.join(' -> ')}`)
    }

    const milestoneIndexes = markers.map((marker) => barIndex.get(marker.bar_end))
    if (milestoneIndexes.some((index) => index === undefined)
      || milestoneIndexes.some((index, markerIndex) => markerIndex > 0 && index <= milestoneIndexes[markerIndex - 1])) {
      throw new Error(`non-increasing Cup lifecycle ${candidateId}`)
    }
    if (markers.some((marker, markerIndex) => (
      JSON.stringify(marker.related_marker_ids) !== JSON.stringify(markers.slice(0, markerIndex).map((item) => item.marker_id))
    ))) throw new Error(`invalid Cup milestone lineage ${candidateId}`)
    if (markers.length > 0 && markers.at(-1).bar_end !== cup.state_changed_at) {
      throw new Error(`Cup state timestamp does not match lifecycle ${candidateId}`)
    }

    const segment = segmentFor(cup.state_changed_at)
    const evidenceTimes = [
      cup.left_rim.pivot_at,
      cup.bottom.pivot_at,
      cup.right_rim.pivot_at,
      cup.handle_start_at,
      cup.handle_extreme?.pivot_at,
      cup.pivot_frozen_at,
      ...markers.map((marker) => marker.bar_end),
    ].filter(Boolean)
    if (!segment || evidenceTimes.some((barEnd) => segmentFor(barEnd) !== segment)) {
      throw new Error(`cross-segment Cup evidence ${candidateId}`)
    }
  }
}

export function newowTrendDetailFixture({ product = 'jm', from = trendDays[0], through = trendDays.at(-1) } = {}) {
  const upper = product.toUpperCase()
  const calculationIdentity = [
    'market_data_service:canonical_v2',
    'main_contract_map:rank1:canonical_v1',
    product,
    'actual_dominant',
    '1d',
    'newow_trend_d1_page_v2',
    'newow_trend_band_page_v2',
    'newow_escape_d123_page_v2',
    'newow_cup_handle_v1',
  ].join('|')
  const genericBars = trendGenericBars(product)
  const segmentA = `${upper}2601:2026-08-21:2026-08-26`
  const segmentB = `${upper}2605:2026-08-27:2026-09-03`
  const bars = genericBars.map((bar, index) => ({
    bar_end: bar.bar_end,
    trading_day: bar.trading_day,
    open: bar.open.toFixed(2),
    high: bar.high.toFixed(2),
    low: bar.low.toFixed(2),
    close: bar.close.toFixed(2),
    volume: bar.volume,
    open_interest: bar.open_interest,
    physical_contract: bar.physical_contract,
    segment_id: index < 4 ? segmentA : segmentB,
    source_identity: calculationIdentity,
  }))
  const marker = (markerId, markerType, index, formulaVersion, candidateId, relatedMarkerIds = []) => ({
    marker_id: markerId,
    marker_type: markerType,
    bar_end: bars[index].bar_end,
    price: formulaVersion === 'newow_trend_band_page_v2'
      ? (trendCloses[index] - 1.1).toFixed(2)
      : formulaVersion === 'newow_escape_d123_page_v2'
        ? bars[index].high
        : bars[index].close,
    label: ({
      CUP_HANDLE_READY: '杯柄就绪',
      CUP_HANDLE_BREAKOUT: '杯柄突破',
      CUP_HANDLE_WEAKENED: '杯柄走弱',
      CUP_HANDLE_INVALIDATED: '杯柄失效',
      CUP_HANDLE_EXPIRED: '杯柄过期',
    })[markerType] ?? markerType,
    color_token: `newow-${markerType.toLowerCase()}`,
    priority: markerType === 'NEWOW_ESCAPE_D1' ? 300 : markerType === 'NEWOW_ESCAPE_D2' ? 200 : 100,
    related_marker_ids: relatedMarkerIds,
    trigger_facts: candidateId === undefined ? { fixture: true } : { candidate_id: candidateId },
    formula_version: formulaVersion,
  })
  const pivot = (index, price, confirmedIndex = index) => ({
    pivot_at: bars[index].bar_end,
    confirmed_at: bars[confirmedIndex].bar_end,
    price: price.toFixed(2),
  })
  const readyCup = (candidateId, state, stateIndex) => ({
    candidate_id: candidateId,
    direction: candidateId === 'cup-e-invalidated' ? 'BEARISH' : 'BULLISH',
    state,
    left_rim: pivot(4, trendCloses[4] + 3),
    bottom: pivot(5, trendCloses[5] - 4),
    right_rim: pivot(6, trendCloses[6] + 2),
    handle_start_at: bars[6].bar_end,
    handle_extreme: pivot(7, trendCloses[7] - 1),
    pivot_price: '104.50',
    pivot_frozen_at: bars[7].bar_end,
    confirmed_at: bars[7].bar_end,
    first_seen_at: bars[7].bar_end,
    state_changed_at: bars[stateIndex].bar_end,
    score: 88,
    score_breakdown: {
      pretrend: 20, cup_geometry: 25, u_shape_purity: 15,
      handle_quality: 15, volume_structure: 13,
    },
    hard_failures: [],
    diagnostics: [`fixture-${state.toLowerCase()}`],
    volume_facts: {
      right_leg_median: 2200, handle_median: 1800, handle_baseline_median: 2100,
      handle_right_ratio: 0.8181818182, handle_baseline_ratio: 0.8571428571,
    },
    formula_version: 'newow_cup_handle_v1',
  })
  const cupLifecycle = (candidateId, terminalType) => {
    const readyId = `${candidateId}-ready`
    const breakoutId = `${candidateId}-breakout`
    const ready = marker(readyId, 'CUP_HANDLE_READY', 7, 'newow_cup_handle_v1', candidateId)
    if (!terminalType) return [ready]
    const breakout = marker(
      breakoutId,
      'CUP_HANDLE_BREAKOUT',
      8,
      'newow_cup_handle_v1',
      candidateId,
      [readyId],
    )
    if (terminalType === 'CUP_HANDLE_BREAKOUT') return [ready, breakout]
    return [
      ready,
      breakout,
      marker(
        `${candidateId}-${terminalType.toLowerCase()}`,
        terminalType,
        9,
        'newow_cup_handle_v1',
        candidateId,
        [readyId, breakoutId],
      ),
    ]
  }

  return {
    meta: {
      strategy_code: 'newow_trend_v1',
      profile_id: 'newow_trend_d1_page_v2',
      frequency: '1d',
      series_kind: 'actual_dominant',
      calculation_identity: calculationIdentity,
      data_revision_identity: 'fixture-revision-2026-09-03',
      request_identity: `${calculationIdentity}:${from}:${through}`,
    },
    instrument: {
      product,
      display_name: product === 'jm' ? '焦煤' : '螺纹钢',
      last_visible_physical_contract: `${upper}2605`,
    },
    bars,
    bar_policy: 'completed_only',
    trend_band: bars.map((bar, index) => {
      const state = index === 2 || index === 3 || index >= 6 ? 'YELLOW' : 'BLUE'
      const stateBefore = index === 0 ? null : (index === 2 || index === 6 ? 'BLUE' : index === 4 ? 'YELLOW' : state)
      const transition = index === 2 || index === 6 ? 'BUILD' : index === 4 ? 'CLEAR' : null
      return {
        bar_end: bar.bar_end,
        b_value: trendCloses[index] - 2.4,
        c_value: trendCloses[index] - 1.1,
        state,
        state_before: stateBefore,
        transition,
      }
    }),
    trend_markers: [
      marker('trend-build-a', 'BUILD', 2, 'newow_trend_band_page_v2'),
      marker('trend-clear-a', 'CLEAR', 4, 'newow_trend_band_page_v2'),
      marker('trend-build-b', 'BUILD', 6, 'newow_trend_band_page_v2'),
    ],
    escape_markers: [
      marker('escape-old-d3', 'NEWOW_ESCAPE_D3', 3, 'newow_escape_d123_page_v2'),
      marker('escape-latest-d1', 'NEWOW_ESCAPE_D1', 9, 'newow_escape_d123_page_v2'),
      marker('escape-latest-d2', 'NEWOW_ESCAPE_D2', 9, 'newow_escape_d123_page_v2'),
      marker('escape-latest-d3', 'NEWOW_ESCAPE_D3', 9, 'newow_escape_d123_page_v2'),
    ],
    cup_markers: [
      ...cupLifecycle('cup-c-ready'),
      ...cupLifecycle('cup-a-breakout', 'CUP_HANDLE_BREAKOUT'),
      ...cupLifecycle('cup-d-weakened', 'CUP_HANDLE_WEAKENED'),
      ...cupLifecycle('cup-e-invalidated', 'CUP_HANDLE_INVALIDATED'),
      ...cupLifecycle('cup-f-expired', 'CUP_HANDLE_EXPIRED'),
    ].sort((left, right) => left.bar_end.localeCompare(right.bar_end)),
    cup_handles: [
      readyCup('cup-a-breakout', 'BREAKOUT', 8),
      {
        candidate_id: 'cup-b-forming', direction: 'BULLISH', state: 'FORMING',
        left_rim: pivot(4, 106), bottom: pivot(5, 97), right_rim: pivot(6, 106),
        handle_start_at: bars[6].bar_end, handle_extreme: null,
        pivot_price: null, pivot_frozen_at: null,
        confirmed_at: bars[6].bar_end, first_seen_at: bars[7].bar_end,
        state_changed_at: bars[7].bar_end, score: 60,
        score_breakdown: { pretrend: 20, cup_geometry: 25, u_shape_purity: 15, handle_quality: 0, volume_structure: 0 },
        hard_failures: [], diagnostics: ['fixture-forming'], volume_facts: {}, formula_version: 'newow_cup_handle_v1',
      },
      readyCup('cup-c-ready', 'READY', 7),
      readyCup('cup-d-weakened', 'WEAKENED', 9),
      readyCup('cup-e-invalidated', 'INVALIDATED', 9),
      readyCup('cup-f-expired', 'EXPIRED', 9),
    ],
    rollover_seams: [{
      trading_day: bars[4].trading_day,
      previous_contract: `${upper}2601`,
      next_contract: `${upper}2605`,
      previous_bar_end: bars[3].bar_end,
      next_bar_end: bars[4].bar_end,
      previous_segment_id: segmentA,
      next_segment_id: segmentB,
    }],
    legend: {
      BUILD: 'trend build', CLEAR: 'trend clear', D1: 'escape D1', D2: 'escape D2', D3: 'escape D3',
    },
    formula_descriptions: {
      trend_band: 'newow_trend_band_page_v2',
      escape: 'newow_escape_d123_page_v2',
      cup_handle: 'newow_cup_handle_v1',
    },
    warnings: [],
  }
}

export async function mockMarketDetail(page, options = {}) {
  const requests = []
  const alertRequests = []
  const runtimeRequests = []
  const newowRequests = []
  const newowCompletedProducts = []
  const delays = options.researchDelayMs || {}
  await page.route('**/api/v1/market/**', async (route) => {
    const url = new URL(route.request().url())
    requests.push(url)
    const symbol = url.searchParams.get('symbol') || options.defaultSymbol || 'jm'
    const upper = symbol.toUpperCase()

    if (url.pathname.endsWith('/newow/trend-detail')) {
      newowRequests.push(url)
      const product = url.searchParams.get('product') || 'jm'
      if (options.newowDelayMs?.[product]) {
        await new Promise((resolve) => setTimeout(resolve, options.newowDelayMs[product]))
      }
      const response = typeof options.newowTrendDetail === 'function'
        ? options.newowTrendDetail({ url, product, count: newowRequests.length })
        : options.newowTrendDetail
      newowCompletedProducts.push(product)
      if (response === 'error' || response === undefined) return route.abort('failed')
      return route.fulfill({ json: response })
    }

    if (url.pathname.endsWith('/dominants')) {
      return route.fulfill({ json: { items: [
        { product: 'jm', product_name: '焦煤', sector: '黑色', exchange: 'DCE', actual_contract: 'JM2601', dominant_mapping_date: '2026-09-03' },
        { product: 'rb', product_name: '螺纹钢', sector: '黑色', exchange: 'SHFE', actual_contract: 'RB2601', dominant_mapping_date: '2026-09-03' },
      ] } })
    }
    if (url.pathname.endsWith('/research/product')) {
      if (delays[symbol]) await new Promise((resolve) => setTimeout(resolve, delays[symbol]))
      return route.fulfill({ json: detailResearch(symbol) })
    }
    if (url.pathname.endsWith('/state')) {
      return route.fulfill({ json: {
        symbol,
        series_kind: url.searchParams.get('series_kind'),
        frequency: url.searchParams.get('frequency'),
        operational: true,
        phase: options.live ? 'TRADING' : 'CLOSED',
        trading_day: '2026-09-03',
        live_eligible: Boolean(options.live),
        live_available: Boolean(options.live),
        live_contract: options.live ? `${upper}2601` : null,
        canonical_end: '2026-09-03T02:45:00Z',
        after_market: { last_successful_trading_day: '2026-09-03' },
      } })
    }
    if (url.pathname.endsWith('/bars/page')) {
      const customPage = options.barsPage?.({ url, symbol })
      const frequency = url.searchParams.get('frequency')
      const seed = symbol === 'jm' ? 100 : 200
      const bars = customPage?.bars ?? (frequency === '1d' || frequency === '1w'
        ? [
            { ...detailBar(symbol, 0, seed), bar_end: '2026-09-02T07:00:00.000Z', trading_day: '2026-09-02' },
            { ...detailBar(symbol, 1, seed + 1), bar_end: '2026-09-03T07:00:00.000Z', trading_day: '2026-09-03' },
          ]
        : [detailBar(symbol, 0, seed), detailBar(symbol, 1, seed + 1)])
      return route.fulfill({ json: {
        request: {
          series_kind: url.searchParams.get('series_kind'),
          symbol,
          contract: url.searchParams.get('contract'),
          frequency,
          before: url.searchParams.get('before'),
          limit: Number(url.searchParams.get('limit')),
        },
        bars,
        canonical_coverage: { start: bars[0].bar_end, end: bars.at(-1).bar_end },
        page: customPage?.page ?? { has_more_before: false, next_before: null },
        resolved_contract_segments: customPage?.resolvedContractSegments ?? (url.searchParams.get('series_kind') === 'actual_dominant'
          ? [{ contract: `${upper}2601`, start_trading_day: bars[0].trading_day, end_trading_day: bars.at(-1).trading_day }]
          : []),
      } })
    }
    return route.abort()
  })
  await page.route('**/api/alerts/**', async (route) => {
    const url = new URL(route.request().url())
    alertRequests.push({ url, method: route.request().method() })
    if (url.pathname.endsWith('/events')) {
      const items = typeof options.alertEvents === 'function' ? options.alertEvents({ url, count: alertRequests.length }) : (options.alertEvents ?? [])
      if (items === 'error') return route.abort('failed')
      return route.fulfill({ json: { items } })
    }
    if (url.pathname.includes('/products/')) {
      const symbol = url.pathname.split('/').at(-1)
      const rules = typeof options.alertRules === 'function' ? options.alertRules({ symbol }) : (options.alertRules ?? [htdyRule()])
      return route.fulfill({ json: { symbol, rules } })
    }
    return route.abort()
  })
  await page.route('**/api/runtime/health', async (route) => {
    runtimeRequests.push(new URL(route.request().url()))
    const subingRuleStatus = typeof options.subingRuntimeRuleStatus === 'function'
      ? options.subingRuntimeRuleStatus({ count: runtimeRequests.length })
      : options.subingRuntimeRuleStatus
    return route.fulfill({ json: {
      status: 'ok', generated_at: '2026-09-03T03:00:00Z', readonly: true, would_start_services: false,
      would_enqueue_jobs: false, would_send_notifications: false, components: { alert: {
        status: options.alertRuntimeStatus ?? 'ok', enabled_rule_count: 0,
        rule_status: {
          htdy_original_15m: { last_evaluated_bar_at: null, last_event_at: null, last_failure_at: null, error_type: null },
          subing_ths_alert_15m_v1: { last_evaluated_bar_at: null, last_event_at: null, last_failure_at: null, error_type: null, ...subingRuleStatus },
        },
      } },
    } })
  })
  requests.alertRequests = alertRequests
  requests.runtimeRequests = runtimeRequests
  requests.newowRequests = newowRequests
  requests.newowCompletedProducts = newowCompletedProducts
  return requests
}

export function htdyEvent(symbol, frequency, barEnd = '2026-09-03T02:45:00.000Z', tradingDay = '2026-09-03', detectedAt = '2026-09-03T02:46:00.000Z') {
  return {
    id: 1, rule_code: 'htdy_original_15m', symbol, contract: `${symbol.toUpperCase()}2601`, trading_day: tradingDay,
    frequency, bar_end: barEnd, result_codes: ['buy'], detected_at: detectedAt, notification_attempted_at: null,
  }
}

function htdyRule() {
  return { rule_code: 'htdy_original_15m', display_name: '火天大有', kind: 'indicator_observation', input_frequencies: ['1m', '5m', '15m', '30m', '60m', '1d', '1w'], enabled_for_product: true, enabled_frequencies: ['15m'] }
}

export function subingRule(enabled = false) {
  return { rule_code: 'subing_ths_alert_15m_v1', display_name: '苏冰预警', kind: 'indicator_observation', input_frequencies: ['15m'], enabled_for_product: enabled, enabled_frequencies: enabled ? ['15m'] : [] }
}

export function subingEvent(symbol, direction = 'buy') {
  return { id: 9, rule_code: 'subing_ths_alert_15m_v1', symbol, contract: `${symbol.toUpperCase()}2601`, trading_day: '2026-09-03', frequency: '15m', bar_end: '2026-09-03T02:45:00.000Z', result_codes: [direction], detected_at: '2026-09-03T02:46:00.000Z', notification_attempted_at: null }
}

export async function installDetailFakeWebSocket(page) {
  await page.addInitScript(() => {
    const sockets = []
    class DetailFakeWebSocket {
      static OPEN = 1
      static CLOSED = 3
      readyState = DetailFakeWebSocket.OPEN
      onopen = null
      onmessage = null
      onclose = null

      constructor(url) {
        this.url = url
        this.closed = false
        sockets.push(this)
        queueMicrotask(() => this.onopen?.())
      }

      close() {
        this.closed = true
        this.readyState = DetailFakeWebSocket.CLOSED
        this.onclose?.()
      }
    }
    window.WebSocket = DetailFakeWebSocket
    window.__marketDetailSockets = sockets
  })
}

export async function navigateClient(page, path) {
  await page.evaluate((nextPath) => {
    return import('/src/app/router.ts').then(({ router }) => router.push(nextPath))
  }, path)
}

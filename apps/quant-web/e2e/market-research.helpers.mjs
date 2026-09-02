export function bar(index) {
  const barEnd = new Date(Date.UTC(2026, 0, index + 1, 7)).toISOString()
  return {
    bar_end: barEnd,
    trading_day: barEnd.slice(0, 10),
    open: 99 + index,
    high: 102 + index,
    low: 98 + index,
    close: 100 + index,
    volume: 1_000 + index,
    turnover: 10_000 + index,
    open_interest: 2_000 + index,
  }
}

export function research(oiChange = 0.06) {
  return {
    symbol: 'ag',
    product_name: '白银',
    sector: 'precious',
    exchange: 'SHFE',
    series_kind: 'actual_dominant',
    contract: null,
    as_of: '2026-08-11',
    current_dominant: 'AG2601',
    dominant_mapping_date: '2026-08-11',
    daily_trend: 'up',
    weekly_trend: 'neutral',
    position20: 0.85,
    distance_to_20d_high: 0.03,
    distance_to_20d_low: 0.21,
    volume_ratio20: 1.42,
    oi_change_1d: oiChange,
    turnover_change_5d: 0.12,
    atr14_percentile252: 0.76,
    recent_daily: Array.from({ length: 40 }, (_, index) => ({
      ...bar(index),
      open_interest: oiChange === null ? null : 2_000 + index,
    })),
  }
}

export function runtimeHealth(overrides = {}) {
  return {
    status: 'ok',
    generated_at: '2026-08-24T10:15:00+00:00',
    readonly: true,
    would_start_services: false,
    would_enqueue_jobs: false,
    would_send_notifications: false,
    components: {
      db: { status: 'ok', latency_ms: 1, error_type: null, error_message: null },
      redis: { status: 'ok', latency_ms: 1, error_type: null, error_message: null },
      live_market: {
        status: 'ok', configured_enabled: true, operational_count: 60, subscribed_count: 60,
        last_heartbeat_at: null, last_bar_at: null, phase_counts: {}, error_type: null, error_message: null,
      },
      alert: {
        status: 'ok', configured_enabled: true,
        notification: { transport: 'pushplus', configured: true, audience_count: 1, would_send: false },
        last_heartbeat_at: null, enabled_rule_count: 1, scope_product_count: 60,
        processing_state: 'unobserved', notification_state: 'unobserved',
        last_processed_bar_at: null, last_processing_success_at: null,
        last_processing_failure_at: null, processing_error_type: null, last_event_at: null,
        last_transport_attempt_at: null, last_provider_accepted_at: null,
        last_notification_failure_at: null, notification_acknowledged_at: null,
        notification_error_type: null, consecutive_notification_failures: 0, error_type: null,
      },
      after_market: {
        status: 'ok', configured_enabled: true, run_state: 'completed',
        expected_trading_day: '2026-08-24', current_run: null, last_run: null,
        last_successful_trading_day: '2026-08-24', last_failure: null,
        error_type: null, error_message: null,
      },
    },
    ...overrides,
  }
}

export async function mockWorkspace(page, researchResponse, options = {}) {
  const workspaceSymbol = options.symbol || 'ag'
  const workspaceContract = options.resolvedContract || 'AG2601'
  const marketRequests = options.marketRequests || []
  await page.route('**/api/v1/market/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/dominants')) {
      return route.fulfill({ json: { items: [{
        product: workspaceSymbol,
        product_name: '白银',
        sector: 'precious',
        exchange: 'SHFE',
        actual_contract: workspaceContract,
        dominant_mapping_date: '2026-01-12',
      }] } })
    }
    if (url.pathname.endsWith('/research/product')) return route.fulfill(researchResponse)
    if (url.pathname.endsWith('/state')) {
      return route.fulfill({ json: {
        symbol: workspaceSymbol,
        series_kind: url.searchParams.get('series_kind'),
        frequency: url.searchParams.get('frequency'),
        operational: true,
        phase: options.live ? 'TRADING' : 'CLOSED',
        trading_day: '2026-08-11',
        live_eligible: Boolean(options.live),
        live_available: Boolean(options.live),
        live_contract: options.live ? workspaceContract : null,
        canonical_end: null,
        after_market: options.afterMarket || {},
      } })
    }
    if (url.pathname.endsWith('/bars/page')) {
      const request = Object.fromEntries(url.searchParams)
      marketRequests.push(request)
      const paged = options.barsPage?.(request)
      const bars = paged?.bars || options.bars || Array.from({ length: 120 }, (_, index) => bar(index))
      return route.fulfill({ json: {
        request: {
          series_kind: request.series_kind,
          symbol: workspaceSymbol,
          contract: request.contract || null,
          frequency: request.frequency,
          before: request.before || null,
          limit: 300,
        },
        bars,
        canonical_coverage: options.canonicalCoverage || null,
        page: paged?.page || { has_more_before: false, next_before: null },
        resolved_contract_segments: request.series_kind === 'actual_dominant' && bars.length ? [{
          contract: workspaceContract,
          start_trading_day: bars[0].trading_day,
          end_trading_day: bars.at(-1).trading_day,
        }] : [],
      } })
    }
    return route.abort()
  })
}

export async function mockAlertMarkerSurface(page, persistentItems = [], options = {}) {
  const symbol = options.symbol || 'ag'
  await page.route('**/api/runtime/health', (route) => route.fulfill({
    json: runtimeHealth(),
  }))
  await page.route('**/api/alerts/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith(`/products/${symbol}`)) {
      return route.fulfill({ json: {
        symbol,
        rules: [{
          rule_code: 'htdy_original_15m',
          display_name: '火天大有',
          kind: 'indicator_observation',
          input_frequencies: ['1m', '5m', '15m', '30m', '60m', '1d', '1w'],
          enabled_for_product: false,
          enabled_frequencies: [],
        }],
      } })
    }
    if (url.pathname.endsWith('/events')) return route.fulfill({ json: { items: persistentItems } })
    return route.abort()
  })
}

export async function openDataDetails(page) {
  const details = page.getByTestId('product-check-data-details')
  if (!(await details.getAttribute('open'))) await details.locator('summary').click()
  return details
}

export const RUNTIME_HEALTH = {
  status: 'ok',
  generated_at: '2026-07-21T12:00:00Z',
  readonly: true,
  would_start_services: false,
  would_enqueue_jobs: false,
  would_send_notifications: false,
  components: {
    db: { status: 'ok', latency_ms: 1.2 },
    redis: { status: 'ok', latency_ms: 0.8 },
    rq: {
      status: 'ok',
      queues: [{ name: 'default', status: 'ok', queued_count: 0, started_count: 0, failed_count: 0, deferred_count: 0, scheduled_count: 0 }],
      worker_count: 1,
      workers: [{ name: 'worker-1', state: 'idle', queues: ['default'] }],
    },
    live_checkpoints: {
      status: 'ok',
      enabled: true,
      stale: false,
      ingest_count: 1,
      aggregation_count: 1,
      status_counts: { ok: 1 },
      recent_ingest: [],
      recent_aggregation: [],
    },
    notification_retry: {
      status: 'ok',
      enabled: true,
      channel: 'enterprise_wechat',
      total_count: 0,
      retry_pending_count: 0,
      due_retry_count: 0,
      failed_count: 0,
      sent_count: 0,
      skipped_count: 0,
      pending_count: 0,
      last_error_type_counts: {},
    },
    scheduler: {
      enabled: true,
      status: 'ok',
      heartbeat_at: '2026-07-21T11:59:00Z',
      heartbeat_age_seconds: 60,
      last_cycle_status: 'ok',
      error_type: null,
    },
    archive: {
      enabled: true,
      status: 'ok',
      latest_task_no: 'archive:jm:JM2609:2026-07-20',
      latest_task_status: 'success',
      latest_contract: 'JM2609',
      latest_finished_at: '2026-07-20T16:00:00Z',
      latest_error_type: null,
      error_type: null,
    },
    after_market_scheduler: {
      enabled: true,
      status: 'degraded',
      last_successful_trading_day: '2026-07-20',
      latest_completed_trading_day: '2026-07-21',
      latest_eligible_trading_day: '2026-07-21',
      archive_lag_trading_days: 1,
      current_task: 'archive:jm:2026-07-21',
      last_error_type: null,
      last_error_at: null,
      retry_count: 2,
      scheduler_heartbeat: {
        status: 'retry_wait',
        health_status: 'ok',
        heartbeat_at: '2026-07-21T12:00:00Z',
        heartbeat_age_seconds: 30,
        lock_status: 'held',
      },
      active_binding_end: '2026-07-20',
      active_binding_ends: [],
      next_retry_at: '2026-07-21T12:05:00Z',
      authorization_hash: 'mock-authorization-hash',
      lock_status: 'held',
      error_type: null,
      error_message: null,
    },
  },
}

const DASHBOARD_SUMMARY = {
  data_status: 'passed',
  risk_status: 'ok',
  strategies: 1,
  v1b_strategies: 1,
  signals_today: 0,
  signals_week: 0,
  backtests: 1,
  backtest_reports: 1,
  backtest_reports_success: 1,
  data_contracts: 1,
  jm_primary_passed_assets: 6,
  live_target_readiness: 'ready',
  live_targets_preview_only: true,
  latest_scan_task: null,
  latest_jm_report: {
    report_id: 14,
    report_no: 'R14',
    strategy_code: 'jm_v1b',
    status: 'completed',
    created_at: '2026-07-01T00:00:00Z',
  },
  generated_at: '2026-07-21T12:00:00Z',
}

const LIVE_TARGETS = {
  provider: 'rqdata',
  target_products: ['jm'],
  trade_date: '2026-07-21',
  readiness_status: 'ready',
  preview_only: true,
  writes_strategy_signal: false,
  writes_signal_event: false,
  sends_notification: false,
  auto_order: false,
  items: [
    {
      product: 'jm',
      continuous_contract: 'jm.MAIN',
      actual_contract: 'JM2609',
      dominant_mapping_date: '2026-07-21',
      readiness_status: 'ready',
      blocked_reasons: [],
      historical_coverage: {},
      live_coverage: {},
    },
  ],
}

const MARKET_LINEAGE = {
  access_mode: 'browser',
  strict_research_ready: false,
  profile_id: null,
  quality_policy: null,
  market_data_file_id: 1,
  market_data_file_ids: [1],
  data_version: 'v1',
  data_versions: ['v1'],
  provider: 'rqdata',
  data_role: 'primary',
  quality_status: 'passed',
  source_interval: '15m',
  source_intervals: ['15m'],
  source_interval_basis: 'native',
  binding_snapshot: null,
  lineage_token: 'mock-lineage',
  source_mode: 'historical',
  view_role: 'actual',
  continuous_contract: 'jm.MAIN',
  actual_contract: 'JM2609',
  asset_evidence: [],
}

const MARKET_DOMINANTS = {
  items: [
    {
      product: 'jm',
      product_name: '焦煤',
      exchange: 'DCE',
      exchange_name: '大商所',
      sector: 'black',
      category: 'futures',
      is_active: true,
      continuous_contract: 'jm.MAIN',
      actual_contract: 'JM2609',
      dominant_mapping_date: '2026-07-21',
      bars_coverage: {
        '5m': { available: true, row_count: 100, quality_status: 'passed' },
        '15m': { available: true, row_count: 100, quality_status: 'passed' },
      },
      quote_ready: true,
      default_period: '15m',
    },
  ],
  default_quote_period: '15m',
}

const WORKBENCH_COVERAGE = {
  instruments: [{ symbol: 'jm', name: '焦煤', exchange: 'DCE' }],
  items: [
    {
      symbol: 'jm',
      contract: 'JM2609',
      period: '15m',
      provider: 'rqdata',
      data_type: 'bars',
      data_role: 'primary',
      quality_status: 'passed',
      profile_id: 'jm-v1',
      view_role: 'actual',
      continuous_contract: 'jm.MAIN',
      actual_contract: 'JM2609',
      start_time: '2026-01-01T09:00:00',
      end_time: '2026-07-21T15:00:00',
      row_count: 100,
      market_data_file_id: 1,
    },
  ],
  default_selection: { symbol: 'jm', contract: 'JM2609', period: '15m' },
}

const BARS_RESPONSE = {
  bars: [
    {
      time: '2026-07-21T14:45:00',
      open: 100,
      high: 101,
      low: 99,
      close: 100.5,
      volume: 10,
      trading_day: '2026-07-21',
    },
  ],
  quality: {
    status: 'passed',
    missing_bars: 0,
    duplicated_bars: 0,
    abnormal_price_count: 0,
    abnormal_volume_count: 0,
    report_count: 0,
  },
  coverage: {
    symbol: 'jm',
    contract: 'JM2609',
    period: '15m',
    provider: 'rqdata',
    row_count: 1,
    quality_status: 'passed',
    data_role: 'primary',
    file_path: null,
  },
  request: {
    symbol: 'jm',
    contract: 'JM2609',
    period: '15m',
    limit: 500,
  },
  lineage: MARKET_LINEAGE,
  strict_research_ready: false,
  message: null,
}

const REPORT_14 = {
  id: 14,
  strategy_code: 'jm_v1b',
  strategy_version: '0.1.0',
  symbol: 'jm',
  contract: 'JM2609',
  period: '15m',
  status: 'completed',
  started_at: '2026-01-01T00:00:00Z',
  created_at: '2026-01-02T00:00:00Z',
  summary: { start_date: '2026-01-01', end_date: '2026-06-01', report_metadata: {} },
}

function fulfillJson(data, status = 200) {
  return async (route) => {
    await route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(data),
    })
  }
}

function pathOf(url) {
  try {
    return new URL(url).pathname
  } catch {
    return url
  }
}

/**
 * 固定 API fixture：阻断写操作，覆盖只读页面打开所需最小响应。
 * 未匹配的 GET 返回空结构，避免 Vite proxy 打到真实后端产生 console error。
 */
function isBackendApi(url) {
  const path = pathOf(url)
  // 只拦截后端 /api/*，绝不能匹配 Vite 模块路径 /src/api/*
  return path === '/api' || path.startsWith('/api/')
}

export async function installMockApi(page) {
  await page.route(isBackendApi, async (route) => {
    const request = route.request()
    const method = request.method().toUpperCase()
    const url = request.url()
    const path = pathOf(url)

    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
      await route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'e2e mock rejects write operations' }),
      })
      return
    }

    if (path.includes('/runtime/health')) {
      await fulfillJson(RUNTIME_HEALTH)(route)
      return
    }
    if (path === '/api/health' || path.endsWith('/api/health')) {
      await fulfillJson({ status: 'ok' })(route)
      return
    }

    if (path.includes('/dashboard/summary')) {
      await fulfillJson(DASHBOARD_SUMMARY)(route)
      return
    }

    if (path.includes('/data/summary')) {
      await fulfillJson({
        source_count: 1,
        exchange_count: 1,
        instrument_count: 1,
        contract_count: 1,
        coverage_count: 1,
        task_count: 0,
        quality_count: 0,
        active_profile_count: 1,
      })(route)
      return
    }

    if (path.includes('/data/instruments')) {
      await fulfillJson([
        { id: 1, symbol: 'jm', name: '焦煤', exchange_code: 'DCE', sector: 'black', category: 'futures', is_active: true },
      ])(route)
      return
    }

    if (path.includes('/data/contracts') || path.includes('/data/profiles') || path.includes('/data/exchanges') || path.includes('/data/sources')) {
      await fulfillJson([])(route)
      return
    }

    if (path.includes('/data/coverage')) {
      const u = new URL(url)
      if (u.searchParams.get('paged') === 'true') {
        await fulfillJson({
          items: [
            {
              id: 1,
              provider: 'rqdata',
              data_type: 'bars',
              instrument_symbol: 'jm',
              contract_code: 'JM2609',
              period: '5m',
              start_time: '2026-01-01T00:00:00',
              end_time: '2026-07-01T00:00:00',
              row_count: 100,
              file_path: null,
              quality_status: 'passed',
              data_version: 'v1',
              data_role: 'primary',
              active_profile_ids: ['jm-v1'],
              binding_status: 'active',
            },
          ],
          total: 1,
          limit: 12,
          offset: 0,
        })(route)
        return
      }
      await fulfillJson([])(route)
      return
    }

    if (path.includes('/data/download-tasks') || path.includes('/data/quality-reports')) {
      await fulfillJson({ items: [], total: 0, limit: 12, offset: 0 })(route)
      return
    }

    if (path.includes('/strategies/registry')) {
      await fulfillJson({
        items: [
          {
            strategy_code: 'jm_v1b',
            name: 'JM V1-B',
            description: 'research',
            strategy_version: '0.1.0',
            product: 'jm',
            periods: ['5m'],
            is_v1b: true,
            capability_classes: ['research_only', 'historical_scan'],
            backtest_endpoints: [],
            scan_endpoint: null,
            spec_doc_path: null,
            spec_doc_exists: false,
          },
        ],
        total: 1,
        v1b_count: 1,
      })(route)
      return
    }

    if (path.includes('/market/dominants')) {
      await fulfillJson(MARKET_DOMINANTS)(route)
      return
    }

    if (path.includes('/market/workbench/coverage') || path.includes('/market/live/coverage')) {
      await fulfillJson(WORKBENCH_COVERAGE)(route)
      return
    }

    if (path.includes('/market/live/targets')) {
      await fulfillJson(LIVE_TARGETS)(route)
      return
    }

    if (path.includes('/market/live/bars') || path.includes('/market/bars')) {
      await fulfillJson(BARS_RESPONSE)(route)
      return
    }

    if (path.includes('/market/indicators')) {
      await fulfillJson({ points: [], series: [], request: {} })(route)
      return
    }

    if (path.includes('/backtests/reports/14/trades')) {
      await fulfillJson({ items: [], total: 0, limit: 50, offset: 0 })(route)
      return
    }

    if (path.includes('/backtests/reports/14/validation-context/observation')) {
      await fulfillJson({
        available: false,
        context: null,
        error_type: 'BACKTEST_VALIDATION_EVIDENCE_INVALID',
        error_message: 'validation evidence is unavailable or invalid',
      })(route)
      return
    }

    if (path.includes('/backtests/reports/14')) {
      await fulfillJson(REPORT_14)(route)
      return
    }

    if (path.includes('/backtests/reports') || path.includes('/backtests/tasks')) {
      await fulfillJson([])(route)
      return
    }

    if (path.includes('/signals/latest') || path.includes('/signals/events')) {
      await fulfillJson([
        {
          id: 1,
          symbol: 'jm',
          product: 'jm',
          contract: 'JM2609',
          continuous_contract: 'jm.MAIN',
          actual_contract: 'JM2609',
          period: '15m',
          interval: '15m',
          status: 'new',
          source_mode: 'jm_v1b_historical_replay',
          score_bucket: 60,
          strength_score: 62,
          bucket_label: '有效',
          signal_price: 1200.5,
          price: 1200.5,
          current_price: 1200.5,
          signal_time: '2026-07-21T14:45:00',
          created_at: '2026-07-21T14:45:00',
          event_type: 'signal_created',
          trigger_price: 1200.5,
          bar_end: '2026-07-21T14:45:00',
          quality_status: { status: 'passed' },
        },
      ])(route)
      return
    }

    if (/\/watchlists\/[^/]+\/items$/.test(path)) {
      await fulfillJson([])(route)
      return
    }
    if (path.includes('/watchlists')) {
      await fulfillJson([{ code: 'black', name: '黑色', item_count: 0 }])(route)
      return
    }

    if (path.includes('/reviews/sources/backtest-trades')) {
      await fulfillJson([])(route)
      return
    }

    if (path.includes('/reviews/tags')) {
      await fulfillJson([])(route)
      return
    }

    if (path.includes('/reviews/stats')) {
      await fulfillJson({
        total_reviews: 0,
        mistake_tags: [],
        rule_effectiveness: [],
        market_phase: [],
        system_compliance: [],
      })(route)
      return
    }

    if (path.includes('/reviews')) {
      await fulfillJson([])(route)
      return
    }

    // 兜底：空对象，防止代理到真实后端
    await fulfillJson({})(route)
  })

  // WebSocket：阻断真实连接，避免 console 噪声
  try {
    await page.routeWebSocket('**/ws**', (ws) => {
      ws.onMessage(() => {
        /* ignore */
      })
    })
  } catch {
    // 旧 Playwright 无 routeWebSocket 时由 console 过滤兜底
  }
}

export const MAIN_ROUTES = [
  '/dashboard',
  '/data',
  '/market',
  '/market/chart',
  '/strategy',
  '/backtest',
  '/backtest/batch',
  '/signal',
  '/runtime',
  '/review',
  '/settings',
]

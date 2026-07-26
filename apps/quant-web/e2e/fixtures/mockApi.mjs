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
  latest_live_signal_event: {
    event_id: 8,
    event_type: 'signal_created',
    source_mode: 'live_realtime_repainting',
    lifecycle_status: 'new',
    symbol: 'jm',
    contract: 'JM2609',
    period: '15m',
    direction: 'long',
    signal_time: '2026-07-27T01:04:00Z',
  },
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
  data_version: 'rqdata_jm_20260721_v2',
  data_versions: ['rqdata_jm_20260721_v2'],
  provider: 'rqdata',
  data_role: 'primary',
  quality_status: 'warning',
  source_interval: '15m',
  source_intervals: ['15m'],
  source_interval_basis: 'native',
  binding_snapshot: null,
  lineage_token: 'mock-lineage',
  source_mode: 'historical',
  view_role: 'actual',
  continuous_contract: 'jm.MAIN',
  actual_contract: 'JM2609',
  asset_evidence: [
    {
      market_data_file_id: 1,
      data_version: 'rqdata_jm_20260721_v2',
      provider: 'rqdata',
      data_role: 'primary',
      quality_status: 'warning',
      checksum: 'mock-checksum-20260721',
      start_time: '2026-01-01T09:00:00',
      end_time: '2026-07-21T15:00:00',
    },
  ],
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

const WORKBENCH_PERIOD = {
  period: '15m',
  provider: 'rqdata',
  data_type: 'bars',
  data_role: 'primary',
  quality_status: 'warning',
  profile_id: 'jm-v1',
  view_role: 'actual',
  continuous_contract: 'jm.MAIN',
  actual_contract: 'JM2609',
  start_time: '2026-01-01T09:00:00',
  end_time: '2026-07-21T15:00:00',
  latest_bar_time: '2026-07-21T15:00:00',
  row_count: 100,
  market_data_file_id: 1,
  data_version: 'rqdata_jm_20260721_v2',
}

const WORKBENCH_COVERAGE = {
  instruments: [
    {
      symbol: 'jm',
      name: '焦煤',
      exchange: 'DCE',
      contracts: [
        {
          contract: 'JM2609',
          name: '焦煤2609',
          exchange: 'DCE',
          provider: 'rqdata',
          status: 'active',
          view_role: 'actual',
          continuous_contract: 'jm.MAIN',
          actual_contract: 'JM2609',
          periods: [WORKBENCH_PERIOD],
        },
      ],
    },
  ],
  items: [
    {
      symbol: 'jm',
      contract: 'JM2609',
      ...WORKBENCH_PERIOD,
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
    status: 'warning',
    missing_bars: 0,
    duplicated_bars: 0,
    abnormal_price_count: 0,
    abnormal_volume_count: 0,
    report_count: 1,
    warning_reasons: ['冲突证据来自 /Volumes/mock-data/jm-15m.parquet'],
    cross_file_conflicts: 20,
    conflict_details: [],
  },
  coverage: {
    symbol: 'jm',
    contract: 'JM2609',
    period: '15m',
    provider: 'rqdata',
    row_count: 1,
    quality_status: 'warning',
    data_role: 'primary',
    profile_id: 'jm-v1',
    data_version: 'rqdata_jm_20260721_v2',
    start_time: '2026-01-01T09:00:00',
    end_time: '2026-07-21T15:00:00',
    latest_bar_time: '2026-07-21T15:00:00',
    market_data_file_id: 1,
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
  message: '浏览模式发现跨文件冲突，仅供观察。',
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

const TRADE_3199 = {
  id: 3199,
  report_id: 14,
  trade_no: 'TRD-3199',
  symbol: 'jm',
  contract: 'JM2609',
  direction: 'long',
  open_time: '2026-05-08T09:15:00',
  close_time: '2026-05-08T10:15:00',
  open_price: 1200,
  close_price: 1212,
  volume: 1,
  net_pnl: 118,
  commission: 2,
  slippage: 0,
  holding_bars: 4,
  entry_reason: 'mock entry',
  exit_reason: 'mock exit',
  raw_payload: { entry_interval: '15m' },
}

const REVIEW_SOURCE_3199 = {
  ...TRADE_3199,
  source_type: 'backtest_trade',
  source_id: 3199,
  trade_id: 3199,
  period: '15m',
  entry_interval: '15m',
  reviewed: true,
  review_id: 9,
}

const REVIEW_9 = {
  id: 9,
  source_type: 'backtest_trade',
  source_id: 3199,
  report_id: 14,
  trade_id: 3199,
  trade_no: 'TRD-3199',
  symbol: 'jm',
  contract: 'JM2609',
  period: '15m',
  entry_interval: '15m',
  direction: 'long',
  open_time: TRADE_3199.open_time,
  close_time: TRADE_3199.close_time,
  open_price: 1200,
  close_price: 1212,
  volume: 1,
  net_pnl: 118,
  mistake_tags: [],
  setup_tags: [],
  rule_tags: [],
  emotion_tags: [],
  screenshot_paths: [],
  ai_status: 'reserved',
  extra: { report_id: 14, trade_id: 3199 },
  source: REVIEW_SOURCE_3199,
}

const HTDY_REVIEW_10 = {
  id: 10,
  source_type: 'signal_event',
  source_id: 8,
  signal_id: 8,
  signal_event_id: 8,
  symbol: 'jm',
  contract: 'JM2609',
  period: '15m',
  entry_interval: '15m',
  direction: 'long',
  open_time: '2026-07-27T09:00:00+08:00',
  close_time: '2026-07-27T09:15:00+08:00',
  open_price: 1234.5,
  close_price: 1234.5,
  volume: 0,
  net_pnl: 0,
  mistake_tags: [],
  setup_tags: [],
  rule_tags: [],
  emotion_tags: [],
  screenshot_paths: [],
  ai_status: 'reserved',
  extra: {
    signal_event_id: 8,
    lineage_status: 'ready',
  },
}

const SIGNAL_EVENT_7 = {
  id: 7,
  event_key: 'signal_created:mock-7',
  event_type: 'signal_created',
  signal_id: 6,
  source_mode: 'live_confirmed',
  strategy_name: 'jm_v1b',
  strategy_version: '0.1.0',
  symbol: 'jm',
  product: 'jm',
  contract: 'JM2609',
  continuous_contract: 'jm.MAIN',
  actual_contract: 'JM2609',
  period: '15m',
  signal_time: '2026-07-21T14:45:00',
  bar_end: '2026-07-21T14:45:00',
  trigger_price: 1200.5,
  direction: 'long',
  signal_status: 'new',
  lifecycle_status: 'new',
  score_bucket: 60,
  data_role: 'primary',
  quality_status: { status: 'passed' },
  payload: {},
  created_at: '2026-07-21T14:45:00',
}

const HTDY_SIGNAL_EVENT_8 = {
  id: 8,
  event_key: 'signal_created:htdy-first-seen:mock-8:created',
  event_type: 'signal_created',
  signal_id: 8,
  source_mode: 'live_realtime_repainting',
  strategy_name: 'htdy_original_realtime_first_seen',
  strategy_version: 'v1.0',
  symbol: 'jm',
  product: 'jm',
  contract: 'JM2609',
  continuous_contract: 'jm.MAIN',
  actual_contract: 'JM2609',
  dominant_mapping_date: '2026-07-27',
  exchange: 'DCE',
  period: '15m',
  signal_time: '2026-07-27T01:04:00Z',
  bar_start: '2026-07-27T09:00:00+08:00',
  bar_end: '2026-07-27T09:15:00+08:00',
  trigger_price: 1234.5,
  direction: 'long',
  signal_status: 'entry_signal',
  lifecycle_status: 'new',
  score_bucket: 0,
  data_role: 'primary',
  quality_status: { status: 'passed', strategy_validity: 'rejected_research_candidate' },
  payload: {
    htdy_first_seen: {
      observation_only: true,
      future_looking: true,
      repainting_accepted: true,
      first_seen_no_retraction: true,
      historical_backtest_allowed: false,
      notification_ready: false,
      not_trading_instruction: true,
      auto_order: false,
    },
    formal_lineage: {
      schema_version: 'signal_review_lineage_v2',
      resolver_name: 'HtDyRealtimeSnapshotResolver',
      resolver_contract_version: 'htdy_realtime_snapshot_v1',
      primary: {
        profile_id: 'live_observation_v1',
        market_data_file_id: 42,
        instrument_symbol: 'jm',
        contract_code: 'JM2609',
        period: '15m',
        data_version: 'rqdata-jm-15m-v1',
        provider: 'rqdata',
        data_role: 'primary',
        quality_status: 'passed',
      },
      contract: {
        actual_contract: 'JM2609',
      },
      bar: {
        bar_start: '2026-07-27T09:00:00+08:00',
        bar_end: '2026-07-27T09:15:00+08:00',
      },
    },
  },
  created_at: '2026-07-27T01:04:00Z',
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

function pagedPayload(url, items) {
  const parsed = new URL(url)
  const limit = Number(parsed.searchParams.get('limit') || items.length || 50)
  const offset = Number(parsed.searchParams.get('offset') || 0)
  return { items: items.slice(offset, offset + limit), total: items.length, limit, offset }
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

    if (path.includes('/market/indicators/macd')) {
      await fulfillJson({
        policy: 'web_macd_legacy_v1',
        indicator_code: 'macd',
        indicator_version: 'mock-v1',
        parameters: {},
        basis: {},
        dif: [],
        dea: [],
        histogram: [],
        source_bar_count: BARS_RESPONSE.bars.length,
        ready_count: 0,
        coverage: BARS_RESPONSE.coverage,
        request: BARS_RESPONSE.request,
        lineage: MARKET_LINEAGE,
        strict_research_ready: false,
        message: null,
      })(route)
      return
    }

    if (path.includes('/market/indicators')) {
      await fulfillJson({
        request: {},
        warmup: {
          requested_display_bar_count: BARS_RESPONSE.bars.length,
          max_warmup_bars: 0,
          read_limit: BARS_RESPONSE.bars.length,
          source_bar_count: BARS_RESPONSE.bars.length,
          display_bar_count: BARS_RESPONSE.bars.length,
        },
        indicators: [],
        lineage: MARKET_LINEAGE,
        strict_research_ready: false,
        message: null,
      })(route)
      return
    }

    if (path.includes('/backtests/reports/14/trades')) {
      await fulfillJson({ items: [TRADE_3199], total: 1, limit: 50, offset: 0 })(route)
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
      await fulfillJson(pagedPayload(url, path.includes('/backtests/reports') ? [REPORT_14] : []))(route)
      return
    }

    if (path.endsWith('/signals/events/7')) {
      await fulfillJson(SIGNAL_EVENT_7)(route)
      return
    }

    if (path.endsWith('/signals/events/8')) {
      await fulfillJson(HTDY_SIGNAL_EVENT_8)(route)
      return
    }

    if (path.includes('/signals/events')) {
      await fulfillJson(pagedPayload(url, [SIGNAL_EVENT_7, HTDY_SIGNAL_EVENT_8]))(route)
      return
    }

    if (path.includes('/signals/latest')) {
      await fulfillJson(pagedPayload(url, [
        {
          id: 6,
          symbol: 'jm',
          product: 'jm',
          contract: 'JM2609',
          continuous_contract: 'jm.MAIN',
          actual_contract: 'JM2609',
          period: '15m',
          interval: '15m',
          status: 'new',
          source_mode: 'live_confirmed',
          score_bucket: 60,
          strength_score: 62,
          bucket_label: '有效',
          signal_price: 1200.5,
          price: 1200.5,
          current_price: 1200.5,
          signal_time: '2026-07-21T14:45:00',
          created_at: '2026-07-21T14:45:00',
          strategy_id: 'jm_v1b',
          strategy_version_id: '0.1.0',
          strategy_name: 'jm_v1b',
          strategy_version: '0.1.0',
          strategy_status: 'observation_only',
          direction: 'long',
          signal_type: 'entry',
          signal_level: 1,
          open_volume: 0,
          margin_required: 0,
          risk_amount: 0,
          account_equity: 100000,
          reasons: [],
          features: {},
          quality_status: { status: 'passed' },
          data_role: 'primary',
          research_only: true,
          research_contract: true,
          alert_status: 'unread',
        },
        {
          id: 8,
          symbol: 'jm',
          product: 'jm',
          contract: 'JM2609',
          continuous_contract: 'jm.MAIN',
          actual_contract: 'JM2609',
          period: '15m',
          interval: '15m',
          status: 'new',
          source_mode: 'live_realtime_repainting',
          score_bucket: 0,
          strength_score: 0,
          bucket_label: '重绘观察',
          signal_price: 1234.5,
          price: 1234.5,
          current_price: 1234.5,
          signal_time: '2026-07-27T01:04:00Z',
          bar_start: '2026-07-27T09:00:00+08:00',
          bar_end: '2026-07-27T09:15:00+08:00',
          created_at: '2026-07-27T01:04:00Z',
          strategy_id: 'htdy_original_realtime_first_seen',
          strategy_code: 'htdy_original_realtime_first_seen',
          strategy_version_id: 'v1.0',
          strategy_name: 'htdy_original_realtime_first_seen',
          strategy_version: 'v1.0',
          strategy_status: 'observation_only',
          direction: 'long',
          signal_type: 'first_seen',
          signal_level: 0,
          open_volume: 0,
          margin_required: 0,
          risk_amount: 0,
          account_equity: 0,
          reasons: ['htdy_original_xma_first_seen'],
          features: {
            source_mode: 'live_realtime_repainting',
            observation_only: true,
            future_looking: true,
            repainting_accepted: true,
            first_seen_no_retraction: true,
            notification_ready: false,
            auto_order: false,
            formal_lineage: HTDY_SIGNAL_EVENT_8.payload.formal_lineage,
          },
          quality_status: { status: 'passed', strategy_validity: 'rejected_research_candidate' },
          data_role: 'primary',
          research_only: true,
          research_contract: true,
          alert_status: 'unread',
        },
      ]))(route)
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
      await fulfillJson(pagedPayload(url, [REVIEW_SOURCE_3199]))(route)
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

    if (path.endsWith('/reviews/9/bars')) {
      await fulfillJson({ lineage: { schema_version: 'review_source_lineage_v1', source_type: 'backtest_trade', source_id: 3199, primary: MARKET_LINEAGE, bar: { bar_start: TRADE_3199.open_time, bar_end: TRADE_3199.close_time } }, bars: BARS_RESPONSE.bars })(route)
      return
    }

    if (path.endsWith('/reviews/10/bars')) {
      await fulfillJson({
        lineage: {
          schema_version: 'review_source_lineage_v1',
          source_type: 'signal_event',
          source_id: 8,
          source_snapshot_schema_version: 'signal_review_lineage_v2',
          resolver_name: 'HtDyRealtimeSnapshotResolver',
          resolver_contract_version: 'htdy_realtime_snapshot_v1',
          primary: HTDY_SIGNAL_EVENT_8.payload.formal_lineage.primary,
          bar: {
            bar_start: HTDY_SIGNAL_EVENT_8.bar_start,
            bar_end: HTDY_SIGNAL_EVENT_8.bar_end,
            confirmation_mode: 'live_realtime_repainting',
          },
        },
        bars: BARS_RESPONSE.bars,
      })(route)
      return
    }

    if (path.endsWith('/reviews/9')) {
      await fulfillJson(REVIEW_9)(route)
      return
    }

    if (path.endsWith('/reviews/10')) {
      await fulfillJson(HTDY_REVIEW_10)(route)
      return
    }

    if (path.includes('/reviews')) {
      const urlObject = new URL(url)
      const sourceType = urlObject.searchParams.get('source_type')
      const sourceId = urlObject.searchParams.get('source_id')
      const rows =
        sourceType === 'signal_event' && sourceId === '7'
          ? []
          : sourceType === 'signal_event' && sourceId === '8'
            ? [HTDY_REVIEW_10]
            : [REVIEW_9]
      await fulfillJson(pagedPayload(url, rows))(route)
      return
    }

    // 兜底：空对象，防止代理到真实后端
    await fulfillJson({})(route)
  })

  // WebSocket：阻断真实连接，避免 console 噪声
  try {
    await page.routeWebSocket(/.*/, (ws) => {
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

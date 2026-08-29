import { expect, test } from '@playwright/test'
import {
  cloneSubingLifecycleCase,
  lifecycleChartBars,
  reidentifySubingResponse,
} from '../tests/fixtures/subingLifecycleCases.mjs'

function bar(index) {
  const barEnd = new Date(Date.UTC(2026, 0, index + 1, 7)).toISOString()
  return {
    bar_end: barEnd, trading_day: barEnd.slice(0, 10), open: 99 + index, high: 102 + index,
    low: 98 + index, close: 100 + index, volume: 1_000 + index, turnover: 10_000 + index,
    open_interest: 2_000 + index,
  }
}

function research(oiChange = 0.06) {
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

function radarItem(overrides = {}) {
  return {
    symbol: 'jm', product_name: '焦煤', sector: 'black', price_change_1d: 0.012,
    price_change_5d: 0.032, volume_ratio20: 1.4, oi_change_1d: 0.021,
    atr14_percentile252: 0.72, position20: 0.84, turnover: 12_000,
    reason_codes: ['ema21_up', 'price_move_up', 'oi_increase'],
    ...overrides,
  }
}

function sectorSummary(sector, median) {
  return {
    sector, total_count: 1, participant_count: 1, up_count: median > 0 ? 1 : 0,
    down_count: median < 0 ? 1 : 0, median_price_change_1d: median,
  }
}

function radar(overrides = {}) {
  return {
    status: 'ready', expected_as_of: '2026-08-15', target_as_of: '2026-08-15', data_as_of: '2026-08-15',
    freshness_state: 'current', freshness_message: '当前完整', active_count: 60, participant_count: 60,
    stale: [], unavailable: [],
    summary: { up_count: 20, down_count: 18, volume_expansion_count: 12, oi_increase_count: 9, high_volatility_count: 7 },
    items: [], sector_summary: [],
    ...overrides,
  }
}

function dailyWatchItem(symbol, productName = symbol.toUpperCase()) {
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

function dailyWatch({ long_watch = [], short_watch = [], unavailable = [], excluded = 60 } = {}) {
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

function runtimeHealth(overrides = {}) {
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

async function mockMarketHomepage(
  page,
  radarResponse = radar(),
  dailyWatchResponse = dailyWatch(),
  runtimeResponse = runtimeHealth(),
) {
  await page.route('**/api/runtime/health', (route) => route.fulfill({ json: runtimeResponse }))
  await page.route('**/api/v1/market/research/radar', (route) => route.fulfill({ json: radarResponse }))
  await page.route('**/api/v1/market/research/subing-daily-watch/current', (route) => route.fulfill({ json: dailyWatchResponse }))
}

test.beforeEach(async ({ page }) => {
  await page.route('**/api/alerts/strategy-actions/current', (route) => route.fulfill({
    json: { status: 'ready', trading_day: '2026-08-25', items: [] },
  }))
})

test('Market homepage shows compact Runtime facts without implying provider delivery', async ({ page }) => {
  await mockMarketHomepage(page)
  await page.goto('/market')

  const strip = page.getByTestId('market-runtime-status')
  await expect(strip).toContainText('整体正常')
  await expect(strip).toContainText('实时正常')
  await expect(strip).toContainText('未获自然验证')
  await expect(strip).toContainText('服务商已接受（不代表送达）')
  await expect(strip).toContainText('已完成')
  await expect(strip).toContainText('2026-08-24 18:14')
  await expect(strip).not.toContainText('综合分')
  await expect(strip).not.toContainText('交易建议')
})

test('Market homepage accessibly distinguishes disabled Alert from missing natural observation', async ({ page }) => {
  const disabledRuntime = runtimeHealth()
  disabledRuntime.components.alert = {
    ...disabledRuntime.components.alert,
    status: 'disabled', configured_enabled: false,
    processing_state: 'unobserved', notification_state: 'unobserved',
    last_heartbeat_at: null, last_processed_bar_at: null,
  }
  await mockMarketHomepage(
    page,
    radar(),
    dailyWatch(),
    disabledRuntime,
  )
  await page.goto('/market')

  const strip = page.getByRole('region', { name: '运行状态' })
  await expect(strip).toContainText('提醒未启用')
  await expect(strip).not.toContainText('未获自然验证')
})

test('Market homepage refreshes Runtime, Strategy Actions and Daily with the bounded visibility policy', async ({ page }) => {
  const counts = { runtime: 0, radar: 0, daily: 0, strategy: 0 }
  await page.route('**/api/runtime/health', (route) => {
    counts.runtime += 1
    return route.fulfill({ json: runtimeHealth() })
  })
  await page.route('**/api/v1/market/research/radar', (route) => {
    counts.radar += 1
    return route.fulfill({ json: radar() })
  })
  await page.route('**/api/v1/market/research/subing-daily-watch/current', (route) => {
    counts.daily += 1
    return route.fulfill({ json: dailyWatch() })
  })
  await page.route('**/api/alerts/strategy-actions/current', (route) => {
    counts.strategy += 1
    return route.fulfill({ json: { status: 'ready', trading_day: '2026-08-25', items: [] } })
  })

  await page.goto('/market')
  await expect.poll(() => ({ ...counts })).toEqual({ runtime: 1, radar: 1, daily: 1, strategy: 1 })

  await page.getByRole('button', { name: '全部刷新' }).click()
  await expect.poll(() => ({ ...counts })).toEqual({ runtime: 2, radar: 2, daily: 2, strategy: 2 })

  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')))
  await expect.poll(() => ({ ...counts })).toEqual({ runtime: 3, radar: 2, daily: 3, strategy: 3 })
})

test('Market homepage marks first Runtime failure unavailable and retains a stale successful snapshot', async ({ page }) => {
  let runtimeAttempt = 0
  await page.route('**/api/runtime/health', (route) => {
    runtimeAttempt += 1
    if (runtimeAttempt === 2) return route.fulfill({ json: runtimeHealth() })
    return route.fulfill({ status: 503 })
  })
  await page.route('**/api/v1/market/research/radar', (route) => route.fulfill({ json: radar() }))
  await page.route('**/api/v1/market/research/subing-daily-watch/current', (route) => route.fulfill({ json: dailyWatch() }))

  await page.goto('/market')
  const strip = page.getByTestId('market-runtime-status')
  await expect(strip).toContainText('运行状态暂不可用')

  await page.getByRole('button', { name: '全部刷新' }).click()
  await expect(strip).toContainText('整体正常')

  await page.getByRole('button', { name: '全部刷新' }).click()
  await expect(strip).toContainText('状态已过期')
  await expect(strip).toContainText('整体正常')
})

test('Market homepage lists every price and open-interest structure without overlapping points', async ({ page }) => {
  const items = [
    radarItem({ symbol: 'rb', product_name: '螺纹钢', price_change_1d: -0.012, oi_change_1d: 0.034 }),
    radarItem({ symbol: 'jm', product_name: '焦煤', price_change_1d: 0.012, oi_change_1d: 0.021 }),
    radarItem({ symbol: 'sf', product_name: '硅铁', price_change_1d: -0.02, oi_change_1d: -0.015 }),
    radarItem({ symbol: 'au', product_name: '黄金', price_change_1d: 0.03, oi_change_1d: -0.01 }),
    radarItem({ symbol: 'a', product_name: '豆一', price_change_1d: 0, oi_change_1d: 0.01 }),
  ]
  await mockWorkspace(page, { json: research() })
  await mockMarketHomepage(page, radar({
    items,
    sector_summary: [sectorSummary('black', 0.01)],
  }))
  await page.goto('/market')
  await page.getByText('展开全市场研究', { exact: true }).click()

  const quadrants = page.getByTestId('market-quadrant-list')
  await expect(quadrants).toBeVisible()
  await expect(quadrants.getByTestId('market-quadrant-down-increase').getByRole('button', { name: '打开 RB 螺纹钢' })).toBeVisible()
  await expect(quadrants.getByTestId('market-quadrant-up-increase').getByRole('button', { name: '打开 JM 焦煤' })).toBeVisible()
  await expect(quadrants.getByTestId('market-quadrant-down-decrease').getByRole('button', { name: '打开 SF 硅铁' })).toBeVisible()
  await expect(quadrants.getByTestId('market-quadrant-up-decrease').getByRole('button', { name: '打开 AU 黄金' })).toBeVisible()
  await expect(quadrants.getByTestId('market-quadrant-neutral').getByRole('button', { name: '打开 A 豆一' })).toBeVisible()
  await expect(quadrants.getByRole('button')).toHaveCount(5)
  await expect(quadrants.locator('.market-scatter__point')).toHaveCount(0)

  await quadrants.getByRole('button', { name: '打开 JM 焦煤' }).click()
  await expect(page).toHaveURL(/\/market\/chart\?symbol=jm/)
})

test('Market homepage shows Radar skeletons while the initial snapshot is pending', async ({ page }) => {
  await page.route('**/api/v1/market/research/radar', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 600))
    await route.fulfill({ json: radar() })
  })
  await page.goto('/market')

  await expect(page.getByTestId('market-radar-skeleton')).toBeVisible()
  await expect(page.getByTestId('subing-daily-watch')).toBeVisible()
  await expect(page.getByTestId('market-radar-skeleton')).toHaveCount(0)
})

test('manual Radar refresh keeps the last snapshot on failure and updates on retry', async ({ page }) => {
  let attempt = 0
  await page.route('**/api/v1/market/research/radar', async (route) => {
    attempt += 1
    if (attempt === 2) return route.fulfill({ status: 503, json: { detail: 'temporarily unavailable' } })
    const asOf = attempt === 1 ? '2026-08-14' : '2026-08-15'
    return route.fulfill({ json: radar({ expected_as_of: asOf, target_as_of: asOf, data_as_of: asOf }) })
  })
  await page.route('**/api/v1/market/research/subing-daily-watch/current', (route) => route.fulfill({ json: dailyWatch() }))
  await page.goto('/market')
  await page.getByText('展开全市场研究', { exact: true }).click()
  const summary = page.locator('.radar-summary')
  await expect(summary).toContainText('当前数据日期 2026-08-14')

  await page.getByRole('button', { name: '全部刷新' }).click()
  await expect(page.getByRole('alert').filter({ hasText: '市场雷达刷新失败' })).toBeVisible()
  await expect(summary).toContainText('当前数据日期 2026-08-14')

  await page.getByRole('button', { name: '全部刷新' }).click()
  await expect(summary).toContainText('当前数据日期 2026-08-15')
  await expect(page.getByRole('alert').filter({ hasText: '市场雷达刷新失败' })).toHaveCount(0)
})

test('sector tabs always show the selected market sector without self-select controls', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('guiyi.market.workspace.preferences.v1', JSON.stringify({
      version: 1, symbol: null, seriesKind: 'actual_dominant', frequency: '15m',
      researchSidebarOpen: true, watchlist: ['a'],
    }))
  })
  await page.route('**/api/v1/market/research/radar', (route) => route.fulfill({ json: radar({
    items: [radarItem(), radarItem({ symbol: 'a', product_name: '豆一', sector: 'agriculture', price_change_1d: -0.004 })],
    sector_summary: [sectorSummary('black', 0.008), sectorSummary('agriculture', -0.004)],
  }) }))
  await page.goto('/market')

  await page.getByText('展开全市场研究', { exact: true }).click()

  const tabs = page.getByRole('tablist', { name: '按板块筛选' }).getByRole('tab')
  await expect(tabs).toHaveText(['黑色系 0.8%', '农产品 -0.4%'])
  await expect(tabs.first()).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('.market-detail tbody tr')).toContainText('JM 焦煤')
  await expect(page.locator('.market-detail thead')).not.toContainText('状态')
  await expect(page.locator('.market-detail thead')).not.toContainText('自选')
  await expect(page.getByRole('button', { name: '自选', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '加入', exact: true })).toHaveCount(0)
  await tabs.nth(1).click()
  await expect(page.locator('.market-detail tbody tr')).toHaveCount(1)
  await expect(page.locator('.market-detail tbody tr')).toContainText('A 豆一')
  await expect(tabs.nth(1).locator('.market-detail__tab-median')).not.toHaveCSS('background-color', 'rgba(0, 0, 0, 0)')
})

test('Market homepage stays inside the three desktop acceptance viewports', async ({ page }) => {
  await mockMarketHomepage(page)
  await page.goto('/market')

  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1280, height: 720 },
    { width: 1024, height: 768 },
  ]) {
    await page.setViewportSize(viewport)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    const box = await page.getByTestId('subing-daily-watch').boundingBox()
    expect(box.x + box.width).toBeLessThanOrEqual(viewport.width)
  }
})

function subing(overrides = {}) {
  return { ...cloneSubingLifecycleCase('longSetup'), ...overrides }
}

function panelEvent(overrides = {}) {
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

function emptySubingStrategyHistory(request) {
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

function subingStrategyCurrent(request, contract = 'AG2601', overrides = {}) {
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

function subingStrategyHistory(request, entryTime, exitTime) {
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

function subingStrategyPerformance(symbol, episodes = [], exitReasonCounts = null) {
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

async function mockWorkspace(page, researchResponse, options = {}) {
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
      const bars = options.bars || Array.from({ length: 120 }, (_, index) => bar(index))
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
        page: options.pageMeta || { has_more_before: false, next_before: null },
        resolved_contract_segments: resolvedContractSegments,
      } })
    }
    return route.abort()
  })
}

async function mockAlertMarkerSurface(page, currentItems = [], options = {}) {
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

async function mockProductIdentityWorkspace(page) {
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

function identityResearch(symbol, oiChange) {
  return {
    ...research(oiChange),
    symbol,
    product_name: symbol === 'ag' ? '白银' : '焦煤',
    sector: symbol === 'ag' ? 'precious' : 'black',
    exchange: symbol === 'ag' ? 'SHFE' : 'DCE',
    current_dominant: symbol === 'ag' ? 'AG2601' : 'JM2701',
  }
}

function identitySubing(symbol, contract, slope) {
  const response = reidentifySubingResponse(cloneSubingLifecycleCase('longSetup'), contract)
  response.symbol = symbol
  response.primary.snapshot.slope_5_bps_per_bar = String(slope)
  return response
}

function identityFactGate(gates, kind, symbol, index) {
  if (symbol === 'jm') return gates[`jm${kind}`].promise
  return gates[index === 0 ? `initialAg${kind}` : `finalAg${kind}`].promise
}

function deferred() {
  let resolve
  const promise = new Promise((resolver) => { resolve = resolver })
  return { promise, resolve }
}

async function selectProduct(page, label) {
  await page.getByLabel('品种').click()
  await page.locator('.n-base-select-option').filter({ hasText: label }).click()
}

function releaseIdentityFacts(gates, prefix) {
  for (const kind of ['Research', 'Subing', 'Performance', 'Scope', 'Events']) gates[`${prefix}${kind}`].resolve()
}

async function openDataDetails(page) {
  const details = page.getByTestId('product-check-data-details')
  if (!(await details.getAttribute('open'))) await details.locator('summary').click()
  return details
}

async function openSubingResearchDetails(page) {
  const details = page.getByTestId('subing-research-details')
  if (!(await details.getAttribute('open'))) await details.locator('summary').click()
  return details
}

async function enableSubingInternalProcess(page) {
  await page.getByRole('button', { name: '图表设置', exact: true }).click()
  await expect(page.getByRole('group', { name: 'EMA' }).getByRole('button')).toHaveText(['EMA10', 'EMA21', 'EMA60'])
  const toggle = page.getByRole('switch', { name: '显示苏冰内部研究过程', exact: true })
  await expect(toggle).toBeVisible()
  if (!(await toggle.isChecked())) await toggle.click()
  await page.keyboard.press('Escape')
  await openSubingResearchDetails(page)
}

async function enableSubingStrategyPerformance(page) {
  await page.getByRole('button', { name: '图表设置', exact: true }).click()
  const toggle = page.getByRole('switch', { name: '显示全历史策略效果', exact: true })
  await expect(toggle).toBeVisible()
  if (!(await toggle.isChecked())) await toggle.click()
  await page.keyboard.press('Escape')
}

test('Product Workspace identity invalidates AG facts before delayed JM Market acceptance', async ({ page }) => {
  const { calls, gates } = await mockProductIdentityWorkspace(page)
  releaseIdentityFacts(gates, 'initialAg')
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect(page.getByTestId('product-check-sidebar')).toContainText('AG OLD Scope')
  await expect(page.getByTestId('product-check-background')).toContainText('6.1%')
  await selectProduct(page, 'JM 焦煤')
  await expect.poll(() => calls.bars.filter((item) => item === 'jm').length).toBe(1)

  expect(calls.research.filter((item) => item === 'jm')).toEqual([])
  expect(calls.subing.filter((item) => item === 'jm')).toEqual([])
  expect(calls.scope.filter((item) => item === 'jm')).toEqual([])
  expect(calls.events.filter((item) => item === 'jm')).toEqual([])
  await expect(page.getByTestId('product-check-sidebar')).toContainText('JM 焦煤')
  await expect(page.getByTestId('product-check-background')).toContainText('正在读取周线 / 日线…')
  await expect(page.getByTestId('product-check-background')).not.toContainText('6.1%')
  await expect(page.getByTestId('subing-current-research')).toContainText('苏冰观察加载中')
  await expect(page.getByTestId('subing-alert-scope')).not.toContainText('AG OLD Scope')
  await expect(page.getByTestId('subing-alert-scope').getByRole('switch')).toHaveClass(/n-switch--disabled/)
  await expect(page.getByTestId('subing-alert-scope').getByRole('switch')).toHaveClass(/n-switch--loading/)
  expect(calls.put).toEqual([])

  gates.jmBars.resolve()
  await expect.poll(() => calls.research.filter((item) => item === 'jm').length).toBe(1)
  await expect.poll(() => calls.subing.filter((item) => item === 'jm').length).toBe(1)
  await expect.poll(() => calls.scope.filter((item) => item === 'jm').length).toBe(1)
  await expect.poll(() => calls.events.filter((item) => item === 'jm').length).toBe(1)
  await expect(page.getByTestId('subing-alert-scope').getByRole('switch')).toHaveClass(/n-switch--disabled/)
  await expect(page.getByTestId('subing-alert-scope').getByRole('switch')).toHaveClass(/n-switch--loading/)

  gates.jmResearch.resolve()
  gates.jmSubing.resolve()
  gates.jmScope.resolve()
  gates.jmEvents.resolve()
  await expect(page.getByTestId('product-check-background')).toContainText('-4.2%')
  await expect(page.locator('.subing-panel__factor').filter({ hasText: 'Primary Factor' })).toContainText('S5 -4.2 bps/bar')
  await expect(page.getByTestId('subing-alert-scope')).toContainText('JM JM Scope')
  await expect(page.getByTestId('subing-alert-scope').getByRole('switch')).not.toHaveClass(/n-switch--disabled/)
  await expect(page.getByTestId('subing-strategy-event')).toContainText('建多')
  expect(calls.put).toEqual([])
})

test('Product Workspace aborts the old full-history performance request on symbol change', async ({ page }) => {
  const failedPerformanceRequests = []
  page.on('requestfailed', (request) => {
    if (request.url().includes('/research/subing-strategy/performance')) {
      failedPerformanceRequests.push(request.url())
    }
  })
  const { calls, gates } = await mockProductIdentityWorkspace(page)
  for (const kind of ['Research', 'Subing', 'Scope', 'Events']) {
    gates[`initialAg${kind}`].resolve()
  }
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')
  await expect.poll(() => calls.performance).toEqual(['ag'])

  await selectProduct(page, 'JM 焦煤')
  gates.jmBars.resolve()
  for (const kind of ['Research', 'Subing', 'Performance', 'Scope', 'Events']) {
    gates[`jm${kind}`].resolve()
  }

  await expect.poll(() => calls.performance).toEqual(['ag', 'jm'])
  await expect(page.getByTestId('subing-strategy-performance')).toHaveCount(0)
  await enableSubingStrategyPerformance(page)
  await expect(page.getByTestId('subing-strategy-performance')).toContainText('JM')
  await expect.poll(() => failedPerformanceRequests.some((url) => url.includes('symbol=ag'))).toBe(true)
})

test('Product Workspace identity replays a frequency change made during delayed symbol Market acceptance', async ({ page }) => {
  const { calls, gates } = await mockProductIdentityWorkspace(page)
  releaseIdentityFacts(gates, 'initialAg')
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')
  await expect(page.getByTestId('product-check-background')).toContainText('6.1%')

  await selectProduct(page, 'JM 焦煤')
  await expect.poll(() => calls.bars.filter((item) => item === 'jm').length).toBe(1)
  await page.getByRole('group', { name: '周期' }).getByRole('button', { name: '15m', exact: true }).click()

  await expect.poll(() => calls.bars.filter((item) => item === 'jm').length).toBe(2)
  expect(calls.research.filter((item) => item === 'jm')).toEqual([])
  expect(calls.scope.filter((item) => item === 'jm')).toEqual([])
  await expect(page.getByTestId('product-check-background')).not.toContainText('6.1%')
  await expect(page.getByTestId('subing-alert-scope').getByRole('switch')).toHaveClass(/n-switch--disabled/)

  gates.jm15mBars.resolve()
  await expect.poll(() => calls.research.filter((item) => item === 'jm').length).toBe(1)
  await expect.poll(() => calls.scope.filter((item) => item === 'jm').length).toBe(1)
  gates.jmResearch.resolve()
  gates.jmSubing.resolve()
  gates.jmScope.resolve()
  gates.jmEvents.resolve()
  await expect(page.getByTestId('product-check-background')).toContainText('-4.2%')
  await expect(page.getByTestId('subing-alert-scope')).toContainText('JM JM Scope')

  gates.jmBars.resolve()
  await page.waitForTimeout(100)
  await expect(page.getByRole('group', { name: '周期' }).getByRole('button', { name: '15m', exact: true })).toHaveClass(/n-button--primary-type/)
  expect(calls.research.filter((item) => item === 'jm')).toHaveLength(1)
  expect(calls.scope.filter((item) => item === 'jm')).toHaveLength(1)
  expect(calls.put).toEqual([])
})

test('Product Workspace identity keeps only the final AG generation across AG to JM to AG', async ({ page }) => {
  const { calls, gates } = await mockProductIdentityWorkspace(page)
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')
  await expect.poll(() => calls.research.filter((item) => item === 'ag').length).toBe(1)
  await expect.poll(() => calls.scope.filter((item) => item === 'ag').length).toBe(1)

  await selectProduct(page, 'JM 焦煤')
  await expect.poll(() => calls.bars.filter((item) => item === 'jm').length).toBe(1)
  await selectProduct(page, 'AG 白银')
  await expect.poll(() => calls.research.filter((item) => item === 'ag').length).toBe(2)
  await expect.poll(() => calls.subing.filter((item) => item === 'ag').length).toBe(2)
  await expect.poll(() => calls.scope.filter((item) => item === 'ag').length).toBe(2)
  await expect.poll(() => calls.events.filter((item) => item === 'ag').length).toBe(2)

  releaseIdentityFacts(gates, 'finalAg')
  await expect(page.getByTestId('product-check-sidebar')).toContainText('AG 白银')
  await expect(page.getByTestId('product-check-background')).toContainText('9.2%')
  await expect(page.locator('.subing-panel__factor').filter({ hasText: 'Primary Factor' })).toContainText('S5 9.2 bps/bar')
  await expect(page.getByTestId('subing-alert-scope')).toContainText('AG FINAL Scope')

  releaseIdentityFacts(gates, 'initialAg')
  gates.jmBars.resolve()
  await expect.poll(() => calls.bars.filter((item) => item === 'jm').length).toBe(1)
  await page.waitForTimeout(100)
  expect(calls.research.filter((item) => item === 'jm')).toEqual([])
  expect(calls.scope.filter((item) => item === 'jm')).toEqual([])
  await expect(page.getByTestId('product-check-background')).toContainText('9.2%')
  await expect(page.getByTestId('subing-alert-scope')).toContainText('AG FINAL Scope')
  await expect(page.getByTestId('subing-alert-scope')).not.toContainText('AG OLD Scope')
  expect(calls.put).toEqual([])
})

test('B1 journey narrows AG on the homepage before opening its verification view', async ({ page }) => {
  const ag = radarItem({ symbol: 'ag', product_name: '白银', sector: 'precious' })
  await mockWorkspace(page, { json: research() })
  await mockAlertMarkerSurface(page)
  await mockMarketHomepage(page, radar({
    items: [ag],
    sector_summary: [sectorSummary('precious', 0.012)],
  }), dailyWatch({
    long_watch: [dailyWatchItem('ag', '白银')],
    excluded: 59,
  }))
  await page.route('**/api/alerts/strategy-actions/current', (route) => route.fulfill({
    json: { status: 'ready', trading_day: '2026-08-25', items: [] },
  }))
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/market')

  await expect(page.getByRole('region', { name: '苏冰', exact: true })).toHaveCount(1)
  await expect(page.getByTestId('subing-daily-watch')).toBeVisible()
  const focus = page.getByTestId('subing-daily-watch')
  await expect(focus).toContainText('AG 白银')
  await expect(page.getByTestId('market-full-research')).not.toHaveAttribute('open')
  await page.getByText('展开全市场研究', { exact: true }).click()
  await expect(page.getByTestId('market-full-research')).toHaveAttribute('open', '')
  await page.getByText('展开全市场研究', { exact: true }).click()
  await focus.getByRole('button', { name: '检查 AG 15m', exact: true }).click()

  await expect(page).toHaveURL(/\/market\/chart\?symbol=ag/)
  expect(Object.fromEntries(new URL(page.url()).searchParams)).toMatchObject({
    symbol: 'ag', series_kind: 'actual_dominant', frequency: '15m',
  })
  await expect(page.getByRole('button', { name: '真实主力', exact: true })).toHaveClass(/n-button--primary-type/)
  await expect(page.getByRole('group', { name: '周期' }).getByRole('button', { name: '15m', exact: true })).toHaveClass(/n-button--primary-type/)
  await expect(page.getByRole('group', { name: 'Overlay' }).getByRole('button', { name: '苏冰', exact: true })).toHaveClass(/n-button--primary-type/)
  await expect(page.getByTestId('product-check-observation')).toBeVisible()
  await expect(page.getByTestId('product-check-background')).toBeVisible()
  await expect(page.getByTestId('product-check-data-details')).not.toHaveAttribute('open')
})

test('exact Daily Watch chart entry is one-shot and leaves saved chart preferences unchanged', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('guiyi.market.chart.preferences.v5', JSON.stringify({
      version: 5,
      selectedOverlay: 'htdy',
      optionalEmaIndicators: [],
      showSubingInternalProcess: false,
      showSubingStrategyPerformance: false,
      period: '5m',
      realtimeFollow: false,
    }))
  })
  await mockWorkspace(page, { json: research() })
  await mockAlertMarkerSurface(page)

  await page.goto('/market/chart?symbol=AG&series_kind=actual_dominant&frequency=15m&overlay=subing&entry=subing-daily-watch')

  const periods = page.getByRole('group', { name: '周期' })
  const overlays = page.getByRole('group', { name: 'Overlay' })
  await expect(periods.getByRole('button', { name: '15m', exact: true })).toHaveClass(/n-button--primary-type/)
  await expect(overlays.getByRole('button', { name: '苏冰', exact: true })).toHaveClass(/n-button--primary-type/)
  await expect(page.getByRole('button', { name: '真实主力', exact: true })).toHaveClass(/n-button--primary-type/)
  await expect(page).toHaveURL(/symbol=ag/)
  expect(Object.fromEntries(new URL(page.url()).searchParams)).toEqual({
    symbol: 'ag',
    series_kind: 'actual_dominant',
    frequency: '15m',
    overlay: 'subing',
    entry: 'subing-daily-watch',
  })
  expect(await page.evaluate(() => JSON.parse(
    window.localStorage.getItem('guiyi.market.chart.preferences.v7'),
  ))).toEqual({
    version: 7,
    selectedOverlay: 'htdy',
    optionalEmaIndicators: [],
    showSubingInternalProcess: false,
    showSubingStrategyPerformance: false,
    period: '5m',
    realtimeFollow: false,
  })

  await overlays.getByRole('button', { name: '无', exact: true }).click()
  await expect(overlays.getByRole('button', { name: '无', exact: true })).toHaveClass(/n-button--primary-type/)
  expect(Object.fromEntries(new URL(page.url()).searchParams)).toEqual({
    symbol: 'ag',
    series_kind: 'actual_dominant',
    frequency: '15m',
  })
  await expect.poll(() => page.evaluate(() => JSON.parse(
    window.localStorage.getItem('guiyi.market.chart.preferences.v7'),
  ).selectedOverlay)).toBe('none')
})

test('strategy action chart entry keeps SuBing overlay and focuses the action', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('guiyi.market.chart.preferences.v7', JSON.stringify({
      version: 7,
      selectedOverlay: 'htdy',
      optionalEmaIndicators: [],
      showSubingInternalProcess: false,
      showSubingStrategyPerformance: false,
      period: '5m',
      realtimeFollow: false,
    }))
  })
  await mockWorkspace(page, { json: research() })
  await mockAlertMarkerSurface(page)

  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m&overlay=subing&entry=subing-strategy-action&action_id=subing-action:test')

  const overlays = page.getByRole('group', { name: 'Overlay' })
  await expect(overlays.getByRole('button', { name: '苏冰', exact: true })).toHaveClass(/n-button--primary-type/)
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-focused-action-id', 'subing-action:test')
  expect(Object.fromEntries(new URL(page.url()).searchParams)).toEqual({
    symbol: 'ag',
    series_kind: 'actual_dominant',
    frequency: '15m',
    overlay: 'subing',
    entry: 'subing-strategy-action',
    action_id: 'subing-action:test',
  })
})

test('normal Market chart URL still loads the saved non-SuBing overlay', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('guiyi.market.chart.preferences.v5', JSON.stringify({
      version: 5,
      selectedOverlay: 'htdy',
      optionalEmaIndicators: [],
      showSubingInternalProcess: false,
      showSubingStrategyPerformance: false,
      period: '5m',
      realtimeFollow: false,
    }))
  })
  await mockWorkspace(page, { json: research() })
  await mockAlertMarkerSurface(page)

  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  const overlays = page.getByRole('group', { name: 'Overlay' })
  await expect(overlays.getByRole('button', { name: '火天大有', exact: true })).toHaveClass(/n-button--primary-type/)
  await expect(overlays.getByRole('button', { name: '苏冰', exact: true })).not.toHaveClass(/n-button--primary-type/)
})

test('SuBing keeps the Market display identity separate from current-dominant research', async ({ page }) => {
  const marketRequests = []
  const researchRequests = []
  const subingRequests = []
  await mockWorkspace(page, { json: research() }, { marketRequests, researchRequests, subingRequests })
  await page.goto('/market/chart?symbol=ag&series_kind=continuous&frequency=5m')

  const overlay = page.getByRole('group', { name: 'Overlay' })
  await expect(overlay.getByRole('button')).toHaveText(['无', '苏冰', '火天大有'])
  await expect(page.getByText('120 bars', { exact: true })).toBeVisible()
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-visible-start-trading-day', '2026-01-01')
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-visible-main-indicators', '')
  await expect(page.getByRole('button', { name: '主连', exact: true })).toBeVisible()
  const toolbar = page.locator('.product-workspace-toolbar')
  const identityRow = toolbar.getByRole('group', { name: '对象与视图' })
  const analysisRow = toolbar.getByRole('group', { name: '研究视角' })
  const actions = toolbar.getByRole('group', { name: '图表操作' })
  const basis = toolbar.locator('.toolbar__subing-basis')
  await expect(basis).toContainText('基准 AG2601')
  await expect(basis).toContainText('ⓘ')
  await expect(basis).toHaveAttribute(
    'title',
    '苏冰始终以当前真实主力 AG2601 计算；主图可独立切换。',
  )
  await expect(analysisRow.getByRole('group', { name: '周期' })).toContainText('1m5m15m30m60mDW')
  await expect(analysisRow.getByRole('group', { name: 'Overlay' }).getByRole('button')).toHaveText(['无', '苏冰', '火天大有'])
  await expect(actions).toContainText('检查图表设置全屏')
  const [identityBox, analysisBox, actionsBox, overlayBox, basisBox] = await Promise.all([
    identityRow.boundingBox(),
    analysisRow.boundingBox(),
    actions.boundingBox(),
    overlay.boundingBox(),
    basis.boundingBox(),
  ])
  expect(identityBox).not.toBeNull()
  expect(analysisBox).not.toBeNull()
  expect(actionsBox).not.toBeNull()
  expect(overlayBox).not.toBeNull()
  expect(basisBox).not.toBeNull()
  expect(analysisBox.y).toBeGreaterThan(identityBox.y)
  expect(Math.abs(actionsBox.y - identityBox.y)).toBeLessThan(2)
  expect(Math.abs(
    basisBox.y + basisBox.height / 2 - (overlayBox.y + overlayBox.height / 2),
  )).toBeLessThan(2)
  expect(basisBox.x).toBeGreaterThan(overlayBox.x)
  expect(marketRequests.some((request) => request.series_kind === 'continuous' && !request.contract)).toBe(true)
  expect(subingRequests).toEqual([{ symbol: 'ag', frequency: '5m' }])
  await expect.poll(() => researchRequests.length).toBe(1)
  expect(researchRequests).toEqual([{ symbol: 'ag', series_kind: 'continuous' }])
  await expect(page).toHaveURL(/series_kind=continuous/)

  const marketRequestCount = marketRequests.length
  await overlay.getByRole('button', { name: '无', exact: true }).click()
  await page.waitForTimeout(100)
  expect(marketRequests).toHaveLength(marketRequestCount)
  expect(researchRequests).toHaveLength(1)
  await expect(page.getByText('120 bars', { exact: true })).toBeVisible()
  await expect(page).toHaveURL(/series_kind=continuous/)
})

test('SuBing Strategy anchors Action times, shows complete records, and keeps internal process opt-in', async ({ page }) => {
  const bars = Array.from({ length: 120 }, (_, index) => bar(index))
  const entryTime = bars[20].bar_end
  const exitTime = bars[100].bar_end
  const strategyRequests = []
  await mockAlertMarkerSurface(page)
  await mockWorkspace(page, { json: research() }, {
    bars,
    canonicalCoverage: { start: bars[0].bar_end, end: bars.at(-1).bar_end },
    subingStrategyHistoricalRequests: strategyRequests,
    subingStrategyHistoricalResponse: (request) => (
      subingStrategyHistory(request, entryTime, exitTime)
    ),
    subingStrategyPerformanceResponse: (request) => {
      const history = subingStrategyHistory(
        { ...request, series_kind: 'actual_dominant', frequency: '15m', since: '2026-01-01', through: '2026-04-30' },
        entryTime,
        exitTime,
      )
      return subingStrategyPerformance(request.symbol, history.episodes)
    },
    subingResponse: cloneSubingLifecycleCase('longSetup'),
  })

  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  const shell = page.getByTestId('kline-shell')
  await expect.poll(() => strategyRequests.length).toBe(1)
  await expect(shell).toHaveAttribute('data-research-marker-count', '2')
  await expect(shell).toHaveAttribute('data-rendered-research-marker-count', '2')
  await expect(shell).toHaveAttribute(
    'data-research-marker-ids',
    'historical:subing-action:e2e-entry,historical:subing-action:e2e-exit',
  )
  await expect(shell).toHaveAttribute('data-research-marker-times', `${entryTime},${exitTime}`)
  await expect(page.getByTestId('subing-strategy-records')).toHaveCount(0)
  await enableSubingStrategyPerformance(page)
  const records = page.getByTestId('subing-strategy-records')
  await expect(records.locator('[data-episode-id="subing-episode:e2e"]')).toHaveCount(1)
  await expect(records).toContainText('建多 → 清多')
  await expect(records).toContainText('参考变动 +7.97%')
  await expect(records).toContainText('历史因果投影 · 模拟动作 · 非实际成交')
  await expect(page.getByTestId('subing-lifecycle-panel')).toHaveCount(0)

  await enableSubingInternalProcess(page)
  await expect(page.getByTestId('subing-lifecycle-panel')).toBeVisible()
  await expect(shell).toHaveAttribute('data-research-marker-count', '3')
  await page.reload()
  await openSubingResearchDetails(page)
  await expect(page.getByTestId('subing-lifecycle-panel')).toBeVisible()
  await expect(page.getByRole('button', { name: '图表设置', exact: true })).toBeVisible()
  await expect(shell).toHaveAttribute('data-research-marker-count', '3')
})

test('SuBing full-history performance expands episodes by twenty and shows exit reasons', async ({ page }) => {
  const history = subingStrategyHistory(
    { symbol: 'ag', since: '2026-01-01', through: '2026-04-30' },
    '2026-01-12T02:15:00Z',
    '2026-01-12T07:00:00Z',
  )
  const base = history.episodes[0]
  const episodes = Array.from({ length: 45 }, (_, index) => {
    const episodeId = `subing-episode:e2e-${index}`
    return {
      ...base,
      episode_id: episodeId,
      entry_action: {
        ...base.entry_action,
        action_id: `subing-action:e2e-entry-${index}`,
        episode_id: episodeId,
      },
      exit_action: {
        ...base.exit_action,
        action_id: `subing-action:e2e-exit-${index}`,
        episode_id: episodeId,
      },
    }
  })
  await mockAlertMarkerSurface(page)
  await mockWorkspace(page, { json: research() }, {
    subingStrategyPerformanceResponse: (request) => subingStrategyPerformance(
      request.symbol,
      episodes,
    ),
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')
  await expect(page.getByTestId('subing-strategy-performance')).toHaveCount(0)
  await enableSubingStrategyPerformance(page)

  const panel = page.getByTestId('subing-strategy-performance')
  await expect(panel.locator('[data-episode-id]')).toHaveCount(20)
  await expect(page.getByTestId('subing-performance-exit-reasons')).toContainText('MACD 高位死叉')
  await page.getByTestId('subing-performance-show-more').click()
  await expect(panel.locator('[data-episode-id]')).toHaveCount(40)
  await page.getByTestId('subing-performance-show-more').click()
  await expect(panel.locator('[data-episode-id]')).toHaveCount(45)
  await expect(page.getByTestId('subing-performance-show-more')).toHaveCount(0)
})

test('SuBing Strategy renders the current open episode from the current endpoint', async ({ page }) => {
  const entry = {
    action_id: 'subing-action:e2e-current-entry', episode_id: 'subing-episode:e2e-current',
    strategy_id: 'subing_strategy_v1', formula_version: 'subing_strategy_15m_v1',
    kind: 'open_long', symbol: 'ag', contract: 'AG2601', trading_day: '2026-01-12',
    segment_start_trading_day: '2026-01-01', opportunity_id: 'subing-opportunity:e2e-current',
    decision_at: '2026-01-12T02:15:00Z', effective_open_at: '2026-01-12T02:15:00Z',
    effective_bar_end: '2026-01-12T02:30:00Z', reference_price: '100.5',
    fill_basis: 'next_bar_open', confirmation_source: 'formal_v1', reason_codes: [],
    direction_context_source_day: '2026-01-09', direction_context_target_day: '2026-01-12',
    bound_reference_pivot: null,
  }
  const currentEpisode = {
    episode_id: entry.episode_id, direction: 'long', entry_action: entry, exit_action: null,
    state: 'open', holding_bar_count: 3, reference_change_percent: null,
    current_reference_change_percent: '2.49', latest_reference_price: '103.0',
    exit_reason_codes: [], structure_exit_available: false,
  }
  await mockAlertMarkerSurface(page)
  await mockWorkspace(page, { json: research() }, {
    subingStrategyCurrentResponse: (request) => subingStrategyCurrent(request, 'AG2601', {
      position_state: 'long', current_episode: currentEpisode,
      direction_context: {
        symbol: 'ag', target_trading_day: '2026-01-12', source_trading_day: '2026-01-09',
        direction: 'long_only', reason_codes: [], daily_bar_end: null, hourly_bar_end: null,
        physical_contract: 'AG2601',
      },
    }),
    subingStrategyPerformanceResponse: (request) => subingStrategyPerformance(
      request.symbol,
      [currentEpisode],
    ),
  })

  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')
  await enableSubingStrategyPerformance(page)

  const records = page.getByTestId('subing-strategy-records')
  const episode = records.locator('[data-episode-id="subing-episode:e2e-current"]')
  await expect(episode).toContainText('建多')
  await expect(episode).toContainText('持仓中')
  await expect(episode).toContainText('100.5')
  await expect(episode).toContainText('3 根 15m Bar')
  await expect(episode).toContainText('当前参考变动 +2.49%')
})

test('SuBing Strategy keeps the canonical marker and exposes an immutable Event fact mismatch', async ({ page }) => {
  const bars = Array.from({ length: 120 }, (_, index) => bar(index))
  const history = subingStrategyHistory(
    { series_kind: 'actual_dominant', symbol: 'ag', frequency: '15m', since: '2026-01-01', through: '2026-04-30' },
    bars[20].bar_end,
    bars[100].bar_end,
  )
  const entry = history.actions[0]
  const currentEvent = {
    id: 220, rule_code: 'subing_strategy_v1', symbol: 'ag', contract: 'AG2601',
    trading_day: entry.trading_day, frequency: '15m', bar_end: entry.decision_at,
    result_codes: ['open_long'], action_id: entry.action_id,
    strategy_action: {
      schema_version: 1, ...entry, reference_price: '999', entry: null,
      holding_bar_count: null, reference_change_percent: null,
    },
    detected_at: entry.decision_at, notification_attempted_at: null,
  }
  await mockAlertMarkerSurface(page, [currentEvent])
  await mockWorkspace(page, { json: research() }, {
    bars,
    canonicalCoverage: { start: bars[0].bar_end, end: bars.at(-1).bar_end },
    subingStrategyHistoricalResponse: history,
  })

  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  const shell = page.getByTestId('kline-shell')
  await expect(shell).toHaveAttribute('data-research-marker-count', '2')
  await expect(shell).toHaveAttribute(
    'data-research-marker-ids',
    'historical:subing-action:e2e-entry,historical:subing-action:e2e-exit',
  )
  const event = page.getByTestId('subing-strategy-event')
  await expect(event).toContainText('建多')
  await expect(event).toContainText('AG2601')
  await expect(event).toContainText('参考价 999')
  await expect(event).toContainText('生效')
  await expect(event).toContainText('STRATEGY_ACTION_FACT_MISMATCH')
  await expect(event).toContainText('图表采用 Canonical Historical 事实')
})


test('shared EMA switches persist across SuBing and HTDY while none hides every overlay', async ({ page }) => {
  await mockWorkspace(page, { json: research() })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  await expect(page.getByRole('button', { name: '图表设置', exact: true })).toBeVisible()
  await expect(page.getByRole('group', { name: 'EMA' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '高级', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '图表设置', exact: true }).click()
  const ema = page.getByRole('group', { name: 'EMA' })
  const ema10 = ema.getByRole('button', { name: 'EMA10', exact: true })
  const ema21 = ema.getByRole('button', { name: 'EMA21', exact: true })
  const ema60 = ema.getByRole('button', { name: 'EMA60', exact: true })
  await expect(ema10).toBeVisible()
  await expect(ema21).toBeVisible()
  await expect(ema60).toBeVisible()
  await expect(page.getByText('指定真实合约', { exact: true })).toBeVisible()
  const kline = page.locator('.product-workspace__kline')
  const overlay = page.getByRole('group', { name: 'Overlay' })

  await expect(ema10).toHaveAttribute('aria-pressed', 'false')
  await expect(ema21).toHaveAttribute('aria-pressed', 'false')
  await expect(ema60).toHaveAttribute('aria-pressed', 'false')
  await expect(kline).toHaveAttribute('data-visible-main-indicators', '')
  await expect(kline).toHaveAttribute('data-subing-ema-ribbon', 'true')
  await ema10.click()
  await ema21.click()
  await ema60.click()
  await expect(kline).toHaveAttribute('data-visible-main-indicators', 'ema_10,ema_21,ema_60')
  await overlay.getByRole('button', { name: '火天大有', exact: true }).click()
  await expect(kline).toHaveAttribute('data-visible-main-indicators', 'ema_10,ema_21,ema_60,htdy')
  await expect(kline).toHaveAttribute('data-subing-ema-ribbon', 'false')
  await overlay.getByRole('button', { name: '无', exact: true }).click()
  await expect(kline).toHaveAttribute('data-visible-main-indicators', '')
  await expect(kline).toHaveAttribute('data-subing-ema-ribbon', 'false')
  await expect(ema10).toHaveAttribute('aria-pressed', 'true')
  await expect(ema21).toHaveAttribute('aria-pressed', 'true')
  await expect(ema60).toHaveAttribute('aria-pressed', 'true')
  await overlay.getByRole('button', { name: '苏冰', exact: true }).click()
  await page.reload()
  await expect(kline).toHaveAttribute('data-visible-main-indicators', 'ema_10,ema_21,ema_60')
  await expect(kline).toHaveAttribute('data-subing-ema-ribbon', 'true')
})

test('SuBing keeps the full Market display history and renders the requested primary Signal', async ({ page }) => {
  await mockWorkspace(page, { json: research() })
  await mockAlertMarkerSurface(page)
  await page.setViewportSize({ width: 1680, height: 1000 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect(page.getByText('120 bars', { exact: true })).toBeVisible()
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-visible-start-trading-day', '2026-01-01')
  await expect(page.getByTestId('subing-strategy-event')).toContainText('当前无可展示的苏冰策略事件记录')
  await expect(page.getByTestId('product-check-background')).toContainText('周线')
  await expect(page.getByTestId('product-check-background')).toContainText('日线')
  await expect(page.getByTestId('product-check-observation')).toContainText('苏冰')
  await expect(page.getByTestId('product-check-observation')).toContainText('5m · 当前不匹配')
  await expect(page.getByTestId('product-check-background')).toContainText('20日位置')
  await expect(page.getByTestId('product-check-data-details')).not.toHaveAttribute('open')
  await expect(page.getByTestId('subing-panel')).toHaveCount(1)
  await expect(page.getByRole('button', { name: '真实主力', exact: true })).toBeVisible()
  await expect(page.locator('.toolbar__subing-basis')).toContainText('基准 AG2601')
  await expect(page.locator('body')).not.toContainText('买入')
  await expect(page.locator('body')).not.toContainText('卖出')
  await expect(page.locator('body')).not.toContainText('formal signal')
  await expect(page.locator('body')).not.toContainText('ZERO_BAND')
})

test('current AlertEvent remains an immutable strategy action event', async ({ page }) => {
  const currentEvent = panelEvent({
    id: 202,
    action_id: 'subing-action:202',
    result_codes: ['open_long'],
    bar_end: '2026-01-12T02:20:00Z',
  })
  await mockWorkspace(page, { json: research() })
  await mockAlertMarkerSurface(page, [currentEvent])
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  const strategyEvent = page.getByTestId('subing-strategy-event')
  await expect(strategyEvent).toContainText('建多')
  await expect(strategyEvent).toContainText('AG2601')
  await expect(strategyEvent).toContainText('参考价 101.5')
  await expect(strategyEvent).toContainText('生效')
  await expect(strategyEvent.getByTestId('subing-confirm-validity')).toContainText('已不是当前仓位')
  await expect(strategyEvent.getByRole('button')).toHaveCount(0)
})

test('current SuBing Strategy Event has no workflow mutation action', async ({ page }) => {
  const currentEvent = panelEvent({
    id: 203,
    action_id: 'subing-action:203',
    result_codes: ['open_short'],
    bar_end: '2026-01-12T02:25:00Z',
  })
  await mockWorkspace(page, { json: research() })
  await mockAlertMarkerSurface(page, [currentEvent])
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  const strategyEvent = page.getByTestId('subing-strategy-event')
  await expect(strategyEvent).toContainText('建空')
  await expect(strategyEvent.getByRole('button')).toHaveCount(0)
})

test('single SuBing panel selects one immutable Event and keeps the remaining backend order', async ({ page }) => {
  const selected = panelEvent()
  const htdy = panelEvent({
    id: 304,
    rule_code: 'htdy_original_15m',
    frequency: '15m',
    bar_end: '2026-01-12T02:25:00Z',
    result_codes: ['buy'],
  })
  const olderBuy = panelEvent({ id: 302, action_id: 'subing-action:302', bar_end: '2026-01-12T02:20:00Z', result_codes: ['open_long'] })
  const oldestSell = panelEvent({ id: 303, action_id: 'subing-action:303', bar_end: '2026-01-12T02:10:00Z', result_codes: ['open_short'] })
  const snapshot = cloneSubingLifecycleCase('dualFormalLong5m')
  snapshot.companion.snapshot.bar_end = '2026-01-12T02:15:00Z'
  await mockWorkspace(page, { json: research() }, {
    subingResponse: snapshot,
  })
  await mockAlertMarkerSurface(page, [selected, htdy, olderBuy, oldestSell], {
    rules: [
      { rule_code: 'htdy_original_15m', display_name: '火天大有', kind: 'indicator_observation', input_frequencies: ['5m', '15m'], enabled_for_product: true, enabled_frequencies: ['5m'] },
      { rule_code: 'subing_strategy_v1', display_name: '苏冰策略', kind: 'strategy_action', input_frequencies: ['5m', '15m'], enabled_for_product: true, enabled_frequencies: [] },
      { rule_code: 'future_rule', display_name: '未来提醒', kind: 'strategy_action', input_frequencies: ['5m'], enabled_for_product: true, enabled_frequencies: [] },
    ],
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  const panel = page.getByTestId('subing-panel')
  const strategyEvent = page.getByTestId('subing-strategy-event')
  await expect(strategyEvent.locator('[data-strategy-event-id="301"]')).toHaveCount(1)
  const historicalRows = strategyEvent.locator('.product-today-alert-events__row')
  await expect(historicalRows).toHaveCount(2)
  expect(await historicalRows.evaluateAll((rows) => rows.map((row) => row.getAttribute('data-event-id'))))
    .toEqual(['302', '303'])
  await expect(strategyEvent.locator('[data-event-id="301"], [data-event-id="304"]')).toHaveCount(0)
  await expect(panel).not.toContainText('火天大有')
  await expect(panel).not.toContainText('未来提醒')
  await expect(panel.getByRole('switch')).toHaveCount(1)

  await openSubingResearchDetails(page)
  await expect(panel.getByText('Resolved Signal', { exact: true })).toBeVisible()
  await expect(panel.getByRole('definition').filter({ hasText: '15m · 买入信号 · 低周期确认' })).toBeVisible()
  await expect(panel.getByText('Primary Signal', { exact: true })).toBeVisible()
  await expect(panel.getByText('5m · 买入信号', { exact: true })).toBeVisible()
  await expect(panel.locator('.subing-panel__factor').filter({ hasText: 'Primary Factor' })).toContainText('5m')
  await expect(panel.locator('.subing-panel__factor').filter({ hasText: 'Companion Factor' })).toContainText('15m')
  await expect(panel.locator('.subing-panel__facts > div').filter({ hasText: 'Primary 确认' })).toContainText('01/12 10:30')
  await expect(panel.locator('.subing-panel__facts > div').filter({ hasText: 'Companion 确认' })).toContainText('01/12 10:15')

  await expect(strategyEvent.getByRole('button')).toHaveCount(0)
})

test('SuBing panel keeps Event and Alert loading independent from a ready snapshot', async ({ page }) => {
  const alertScopeGate = deferred()
  await mockWorkspace(page, { json: research() }, {
    subingResponse: cloneSubingLifecycleCase('dualFormalLong5m'),
  })
  await mockAlertMarkerSurface(page, [], {
    currentEventsDelayMs: 900,
    alertScopeGate,
    rules: [{
      rule_code: 'subing_strategy_v1', display_name: '苏冰策略', kind: 'strategy_action',
      input_frequencies: ['5m', '15m'], enabled_for_product: false, enabled_frequencies: [],
    }],
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  const panel = page.getByTestId('subing-panel')
  const strategyEvent = page.getByTestId('subing-strategy-event')
  const scope = page.getByTestId('subing-alert-scope')
  await openSubingResearchDetails(page)
  await expect(panel.getByText('Resolved Signal', { exact: true })).toBeVisible()
  await expect(strategyEvent).toContainText('正在读取苏冰策略事件')
  await expect(strategyEvent).not.toContainText('当前无可展示的苏冰策略事件记录')
  await expect(scope).toContainText('正在读取苏冰提醒 Scope')
  await expect(scope).not.toContainText('不可用')
  await expect(scope.getByRole('switch')).toHaveCount(1)
  await expect(scope.getByRole('switch')).toHaveClass(/n-switch--disabled/)
  await expect(scope.getByRole('switch')).toHaveClass(/n-switch--loading/)

  await expect(strategyEvent.getByText('当前无可展示的苏冰策略事件记录', { exact: true })).toHaveCount(1)
  await expect(strategyEvent.getByTestId('product-today-alert-events')).toHaveCount(0)
  alertScopeGate.resolve()
  await expect(scope.getByRole('switch')).toBeVisible()
  await expect(scope.getByRole('switch')).not.toHaveClass(/n-switch--disabled/)
})

test('SuBing panel keeps an unavailable Event source distinct from ready empty', async ({ page }) => {
  await mockWorkspace(page, { json: research() })
  await mockAlertMarkerSurface(page, [], { currentEventsStatus: 'unavailable' })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  const strategyEvent = page.getByTestId('subing-strategy-event')
  await expect(strategyEvent).toContainText('苏冰策略事件暂不可用')
  await expect(strategyEvent).not.toContainText('当前无可展示的苏冰策略事件记录')
  await expect(strategyEvent.getByTestId('product-today-alert-events')).toHaveCount(0)
})

test('SuBing panel distinguishes authoritative warm-up without inventing Factor evidence', async ({ page }) => {
  const source = {
    supported: true,
    loading: false,
    error: false,
    snapshot: subing({
      primary: { status: 'insufficient_data', snapshot: null },
      companion: null,
      primary_signal: {
        status: 'insufficient_data', direction: 'none', trigger_timeframe: '5m',
        lower_tf_confirmation: false, resolution: null, conditions: [], error_code: null,
      },
      resolved_signal: null,
    }),
  }
  await mockWorkspace(page, { json: research() }, { subingResponse: source.snapshot })
  await mockAlertMarkerSurface(page)
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  const researchPanel = page.getByTestId('subing-current-research')
  await openSubingResearchDetails(page)
  await expect(researchPanel.getByText('指标 warm-up 中 / 数据不足', { exact: true })).toBeVisible()
  await expect(researchPanel).not.toContainText('苏冰当前周期不可用')
  await expect(researchPanel).not.toContainText('苏冰观察加载中')
  await expect(researchPanel).not.toContainText('苏冰观察暂不可用')

  const primaryConfirmation = researchPanel.locator('.subing-panel__facts > div').filter({ hasText: 'Primary 确认' })
  const primaryFactor = researchPanel.locator('.subing-panel__factor').filter({ hasText: 'Primary Factor' })
  await expect(primaryConfirmation.getByRole('definition')).toHaveText('—')
  await expect(primaryFactor.getByRole('definition')).toHaveText('warm-up 中')
  await expect(primaryConfirmation).not.toContainText(/\d{2}\/\d{2} \d{2}:\d{2}/)
  await expect(primaryFactor).not.toContainText(/EMA|S5|S10|MACD|V\/prev/)
})

test('SuBing lifecycle remains an explicitly research-only funnel beside formal V1 wording', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, {
    subingResponse: cloneSubingLifecycleCase('formalDirectLong'),
  })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  const observation = page.getByTestId('product-check-observation')
  await expect(observation).toContainText('5m · 买入信号')
  await expect(observation).toContainText('Research only')
  await expect(page.getByTestId('subing-lifecycle-panel')).toHaveCount(0)
  await enableSubingInternalProcess(page)
  await openDataDetails(page)
  const lifecycle = page.getByTestId('subing-lifecycle-panel')
  await expect(lifecycle).toContainText('Research only')
  await expect(lifecycle).toContainText('研究确认')
  await expect(lifecycle).toContainText('确认进度')
  await expect(lifecycle).toContainText('已研究确认')
  await expect(lifecycle).not.toContainText('3/3')
  await expect(lifecycle).toContainText('最近状态转换')
  await expect(lifecycle).not.toContainText('买入信号')
  const settings = page.locator('.toolbar__settings')
  if (await settings.isVisible()) await page.getByTestId('kline-shell').click({ position: { x: 400, y: 400 } })
  await expect(settings).not.toBeVisible()
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1280, height: 720 },
    { width: 1024, height: 768 },
  ]) {
    await page.setViewportSize(viewport)
    await expect.poll(() => page.evaluate(() => {
      const column = document.querySelector('.product-workspace__kline')?.getBoundingClientRect()
      const shell = document.querySelector('[data-testid="kline-shell"]')?.getBoundingClientRect()
      return Boolean(column && shell && shell.right <= column.right + 1)
    })).toBe(true)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
})

test('SuBing lifecycle shows a reducer-produced long momentum hold', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, {
    subingResponse: cloneSubingLifecycleCase('longMomentumHold'),
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await enableSubingInternalProcess(page)
  await expect(page.getByTestId('product-check-observation')).toContainText('1/3')
  await expect(page.getByTestId('product-check-observation')).toContainText('当前不匹配')
  await openDataDetails(page)
  await expect(page.getByTestId('subing-lifecycle-panel')).toContainText('1/3')
  await expect(page.locator('.subing-panel__factor').filter({ hasText: 'Primary Factor' })).toContainText('S5 2.0 bps/bar · MACD 金叉')
})

test('retest confirmation renders its own zero then one bar progress', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, {
    bars: lifecycleChartBars,
    subingResponses: [cloneSubingLifecycleCase('pivotRetest0'), cloneSubingLifecycleCase('pivotRetest1')],
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await enableSubingInternalProcess(page)
  await openDataDetails(page)
  const lifecycle = page.getByTestId('subing-lifecycle-panel')
  await expect(lifecycle).toContainText('0/3')
  await expect(lifecycle).toContainText('触发前高')
  await expect(lifecycle).toContainText('110')
  await expect(lifecycle).not.toContainText('绑定前低')
  await expect(page.getByTestId('product-check-observation')).toContainText('0/3')
  const overlay = page.getByRole('group', { name: 'Overlay' })
  await overlay.getByRole('button', { name: '无', exact: true }).click()
  await overlay.getByRole('button', { name: '苏冰', exact: true }).click()
  await expect(lifecycle).toContainText('1/3')
  await expect(lifecycle).toContainText('触发前高')
  await expect(lifecycle).not.toContainText('绑定前低')
  await expect(page.getByTestId('product-check-observation')).toContainText('1/3')
})

test('lifecycle markers keep Alert counts independent and clear stale research snapshots', async ({ page }) => {
  await mockAlertMarkerSurface(page)
  await mockWorkspace(page, { json: research() }, {
    subingDelayMs: 400,
    subingResponses: [cloneSubingLifecycleCase('longSetup'), cloneSubingLifecycleCase('pivotRetestConfirmed'), { __http_status: 503 }],
    bars: lifecycleChartBars,
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  const shell = page.getByTestId('kline-shell')
  await expect(shell).toHaveAttribute('data-research-marker-count', '0')
  await enableSubingInternalProcess(page)
  await openDataDetails(page)
  const setupPanel = page.getByTestId('subing-lifecycle-panel')
  await expect(setupPanel).toBeVisible()
  await expect(setupPanel).toContainText('准备中')
  await expect(setupPanel).toContainText('—')
  await expect(shell).toHaveAttribute('data-alert-marker-count', '0')
  await expect(shell).toHaveAttribute('data-research-marker-count', '1')
  await expect(shell).toHaveAttribute('data-rendered-research-marker-count', '1')

  const overlay = page.getByRole('group', { name: 'Overlay' })
  await overlay.getByRole('button', { name: '无', exact: true }).click()
  await expect(shell).toHaveAttribute('data-alert-marker-count', '0')
  await expect(shell).toHaveAttribute('data-research-marker-count', '0')
  await expect(shell).toHaveAttribute('data-rendered-research-marker-count', '0')
  await overlay.getByRole('button', { name: '苏冰', exact: true }).click()
  await expect(page.getByTestId('subing-lifecycle-panel')).toHaveCount(0)
  await expect(shell).toHaveAttribute('data-research-marker-count', '0')
  await expect(shell).toHaveAttribute('data-rendered-research-marker-count', '0')
  await expect.poll(async () => shell.getAttribute('data-research-marker-count')).toBe('2')
  const confirmedLifecycle = page.getByTestId('subing-lifecycle-panel')
  await openDataDetails(page)
  await expect(confirmedLifecycle).toContainText('触发前高')
  await expect(confirmedLifecycle).toContainText('110')
  await expect(confirmedLifecycle).toContainText('绑定前低')
  await expect(confirmedLifecycle).toContainText('105')
  await expect(shell).toHaveAttribute('data-rendered-research-marker-count', '2')
  await expect(shell).toHaveAttribute('data-alert-marker-count', '0')

  await overlay.getByRole('button', { name: '无', exact: true }).click()
  await overlay.getByRole('button', { name: '苏冰', exact: true }).click()
  await expect(shell).toHaveAttribute('data-research-marker-count', '0')
  await expect(shell).toHaveAttribute('data-rendered-research-marker-count', '0')
  await expect(page.getByText('苏冰观察暂不可用；K 线保留当前展示行情', { exact: true })).toBeVisible()
  await expect(shell).toHaveAttribute('data-rendered-research-marker-count', '0')
  await expect(page.getByTestId('subing-lifecycle-panel')).toHaveCount(0)
})

test('SuBing lifecycle renders risk and closed research stages without trade instructions', async ({ page }) => {
  for (const [caseName, expected] of [['shortExitRiskFirst', '退出风险'], ['oppositeContextClosed', '本轮结束']]) {
    const isRisk = caseName === 'shortExitRiskFirst'
    await mockWorkspace(page, { json: research() }, {
      subingResponse: cloneSubingLifecycleCase(caseName),
    })
    await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')
    await enableSubingInternalProcess(page)
    await openDataDetails(page)
    const lifecycle = page.getByTestId('subing-lifecycle-panel')
    await expect(lifecycle).toContainText(expected)
    await expect(page.locator('.subing-panel__factor').filter({ hasText: 'Primary Factor' })).toContainText(isRisk ? 'S5 -2.0 bps/bar' : 'S5 2.0 bps/bar')
    await expect(lifecycle).not.toContainText(/下单|加仓|平仓指令/)
  }
})

test('SuBing public frequency keeps 1d in Daily Watch and does not request the public Panel', async ({ page }) => {
  const subingRequests = []
  await mockWorkspace(page, { json: research() }, { subingRequests })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=1d')

  await expect(page.getByText('苏冰公开当前观察仅支持 5m / 15m；D1 / 60m 请查看每日观察。', { exact: true })).toBeVisible()
  await expect(page.getByTestId('subing-lifecycle-panel')).toHaveCount(0)
  expect(subingRequests).toEqual([])
})

test('SuBing shows a same-boundary companion-only match without replacing the requested primary', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, {
    subingResponse: cloneSubingLifecycleCase('companionFormalLong5m'),
  })
  await page.setViewportSize({ width: 1680, height: 1000 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect(page.getByTestId('product-check-observation')).toContainText('15m · 买入信号')
  await openSubingResearchDetails(page)
  await expect(page.getByRole('definition').filter({ hasText: '5m · 当前不匹配' })).toBeVisible()
  await expect(page.getByRole('definition').filter({ hasText: '15m · 买入信号' })).toBeVisible()
})

test('SuBing same-boundary dual match keeps 5m primary and resolves one 15m buy signal', async ({ page }) => {
  const alertRequests = []
  await page.route('**/api/v1/alerts/**', async (route) => {
    alertRequests.push(route.request().url())
    return route.abort()
  })
  await mockWorkspace(page, { json: research() }, {
    subingResponse: cloneSubingLifecycleCase('dualFormalLong5m'),
  })
  await page.setViewportSize({ width: 1680, height: 1000 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect(page.getByTestId('product-check-observation')).toContainText('15m · 买入信号 · 低周期确认')
  await openSubingResearchDetails(page)
  await expect(page.getByText('Primary Signal')).toBeVisible()
  await expect(page.getByText('5m · 买入信号', { exact: true })).toBeVisible()
  await expect(page.getByText('Resolved Signal')).toBeVisible()
  await expect(page.getByRole('definition').filter({ hasText: '15m · 买入信号 · 低周期确认' })).toBeVisible()
  await expect(page.locator('body')).not.toContainText('ZERO_BAND')
  await expect(page.locator('body')).not.toContainText('零轴条件')
  expect(alertRequests).toEqual([])
})

test('SuBing same-boundary 15m request keeps 15m as both primary and resolved signal', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, {
    subingResponse: cloneSubingLifecycleCase('dualFormalShort15m'),
  })
  await page.setViewportSize({ width: 1680, height: 1000 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  await expect(page.getByTestId('product-check-observation')).toContainText('15m · 卖出信号 · 低周期确认')
  await openSubingResearchDetails(page)
  await expect(page.getByText('15m · 卖出信号', { exact: true })).toBeVisible()
  await expect(page.getByRole('definition').filter({ hasText: '15m · 卖出信号 · 低周期确认' })).toBeVisible()
})

test('SuBing 15m non-match keeps the requested primary and creates no resolved signal', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, {
    subingResponse: cloneSubingLifecycleCase('noFormalLong15m'),
  })
  await page.setViewportSize({ width: 1680, height: 1000 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  await expect(page.getByTestId('product-check-observation')).toContainText('15m · 当前不匹配')
  await openSubingResearchDetails(page)
  await expect(page.getByRole('definition').filter({ hasText: '15m · 当前不匹配' })).toBeVisible()
  await expect(page.getByText('Resolved Signal')).toHaveCount(0)
})

test('SuBing keeps Market display bars visible while the segment snapshot resolves', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, { subingDelayMs: 700 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect(page.getByText('120 bars', { exact: true })).toBeVisible()
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-visible-start-trading-day', '2026-01-01')
  await expect(page.getByTestId('product-check-observation')).toContainText('苏冰观察加载中')
  await expect(page.getByText('120 bars', { exact: true })).toBeVisible()
})

test('SuBing public frequency keeps unsupported 30m explicit and does not request a snapshot', async ({ page }) => {
  const subingRequests = []
  await mockWorkspace(page, { json: research() }, {
    subingRequests,
    pageMeta: { has_more_before: true, next_before: '2026-08-01T01:00:00Z' },
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=30m')

  await expect(page.getByText('苏冰公开当前观察仅支持 5m / 15m；D1 / 60m 请查看每日观察。', { exact: true })).toBeVisible()
  await expect(page.getByText('120 bars', { exact: true })).toBeVisible()
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-visible-main-indicators', '')
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-subing-ema-ribbon', 'false')
  await openDataDetails(page)
  await expect(page.getByText('可继续向左加载', { exact: true })).toBeVisible()
  expect(subingRequests).toEqual([])

  await page.getByRole('button', { name: '图表设置', exact: true }).click()
  const ema = page.getByRole('group', { name: 'EMA' })
  await ema.getByRole('button', { name: 'EMA10', exact: true }).click()
  await ema.getByRole('button', { name: 'EMA60', exact: true }).click()
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-visible-main-indicators', '')
  expect(subingRequests).toEqual([])
})

test('SuBing refreshes dominant metadata without changing the Market display identity', async ({ page }) => {
  const marketRequests = []
  const subingRequests = []
  const dominantRequests = []
  const ag2602 = reidentifySubingResponse(cloneSubingLifecycleCase('longSetup'), 'AG2602')
  ag2602.dominant_mapping_date = '2026-08-12'
  await mockWorkspace(page, { json: research() }, {
    marketRequests,
    subingRequests,
    dominantRequests,
    dominantsRefreshDelayMs: 700,
    dominantsResponses: [
      { items: [{ product: 'ag', product_name: '白银', sector: 'precious', exchange: 'SHFE', actual_contract: 'AG2601', dominant_mapping_date: '2026-08-11' }] },
      { items: [{ product: 'ag', product_name: '白银', sector: 'precious', exchange: 'SHFE', actual_contract: 'AG2602', dominant_mapping_date: '2026-08-12' }] },
    ],
    subingResponses: [ag2602, ag2602],
  })
  await page.goto('/market/chart?symbol=ag&series_kind=continuous&frequency=5m')

  await expect.poll(() => subingRequests.length).toBe(1)
  await expect(page.getByText('120 bars', { exact: true })).toBeVisible()
  await expect.poll(() => dominantRequests.length).toBe(2)
  await expect.poll(() => subingRequests.length).toBe(2)
  await expect.poll(() => marketRequests.length).toBeGreaterThanOrEqual(2)
  expect(marketRequests.every((request) => request.series_kind === 'continuous' && !request.contract)).toBe(true)
  await expect(page.getByText('120 bars', { exact: true })).toBeVisible()
  await expect(page.locator('.toolbar__subing-basis')).toContainText('基准 AG2602')
  await expect(page).toHaveURL(/series_kind=continuous/)
  expect(dominantRequests).toHaveLength(2)
})

test('SuBing fails closed after one dominant refresh still mismatches the snapshot', async ({ page }) => {
  const subingRequests = []
  const dominantRequests = []
  const mismatched = reidentifySubingResponse(cloneSubingLifecycleCase('longSetup'), 'AG2602')
  mismatched.dominant_mapping_date = '2026-08-12'
  await mockWorkspace(page, { json: research() }, {
    subingRequests,
    dominantRequests,
    subingResponses: [mismatched, mismatched],
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect.poll(() => subingRequests.length).toBe(2)
  await expect(page.getByText('苏冰观察暂不可用；K 线保留当前展示行情', { exact: true })).toBeVisible()
  await expect(page.getByText('120 bars', { exact: true })).toBeVisible()
  await page.waitForTimeout(700)
  expect(subingRequests).toHaveLength(2)
  expect(dominantRequests).toHaveLength(2)
})

test('SuBing performs exactly one delayed refresh for an older companion at the 5m common boundary', async ({ page }) => {
  const subingRequests = []
  const boundarySnapshot = cloneSubingLifecycleCase('olderCompanionAtBoundary')
  await mockWorkspace(page, { json: research() }, {
    subingRequests,
    subingResponse: boundarySnapshot,
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect.poll(() => subingRequests.length).toBe(2)
  await page.waitForTimeout(900)
  expect(subingRequests).toHaveLength(2)
})

test('SuBing refreshes the snapshot after a completed primary Live bar without clipping display history', async ({ page }) => {
  const subingRequests = []
  let marketSocket
  await page.routeWebSocket('**/api/v1/market/ws**', (socket) => {
    marketSocket = socket
  })
  await mockWorkspace(page, { json: research() }, { subingRequests, live: true })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect.poll(() => subingRequests.length).toBe(1)
  await expect.poll(() => !!marketSocket).toBe(true)
  marketSocket.send(JSON.stringify({
    type: 'bar',
    bar: {
      bar_end: '2026-05-01T07:00:00Z', trading_day: '2026-05-01', open: 219,
      high: 222, low: 218, close: 220, volume: 2_000, turnover: 20_000, open_interest: 3_000,
    },
  }))

  await expect.poll(() => subingRequests.length).toBe(2)
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-visible-start-trading-day', '2026-01-01')
})

test('shows one identity-matched research snapshot without crowding desktop Kline', async ({ page }) => {
  await mockWorkspace(page, { json: research() })
  await page.setViewportSize({ width: 1680, height: 1000 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  await expect(page.getByTestId('product-status-strip')).toContainText('Historical')
  await expect(page.getByTestId('product-status-strip')).toContainText('已收盘')
  await expect(page.getByTestId('product-status-strip')).toContainText('数据正常')
  await expect(page.getByText('Price / Volume / OI', { exact: true })).toHaveCount(0)
  await expect(page.getByTestId('product-check-background')).toContainText('日线')
  await expect(page.getByTestId('product-check-background')).toContainText('上行')
  await expect(page.getByTestId('product-check-background')).toContainText('20日位置')
  const details = await openDataDetails(page)
  await expect(details.getByText('Price / Volume / OI')).toBeVisible()
  await expect(page.locator('.product-workspace__sidebar')).toBeVisible()
})

test('status strip surfaces after-market failure instead of a normal-data claim', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, {
    afterMarket: { last_failure: { code: 'UPDATE_FAILED' } },
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  const status = page.getByTestId('product-status-strip')
  await expect(status).toContainText('最近盘后更新失败')
  await expect(status).not.toContainText('数据正常')
})

test('research control toggles the inline sidebar instead of opening a duplicate drawer at 1280px', async ({ page }) => {
  await mockWorkspace(page, { json: research() })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  const sidebar = page.locator('.product-workspace__sidebar')
  const researchControl = page.getByRole('button', { name: '检查', exact: true })
  await expect(sidebar).toBeVisible()
  await researchControl.click()
  await expect(sidebar).toBeHidden()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await researchControl.click()
  await expect(sidebar).toBeVisible()
})

test('Product Workspace stays inside desktop widths and exposes the Check drawer at 1024', async ({ page }) => {
  await mockWorkspace(page, { json: research() })
  await mockAlertMarkerSurface(page)
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1280, height: 720 },
    { width: 1024, height: 768 },
  ]) {
    await page.setViewportSize(viewport)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }

  await page.getByRole('button', { name: '检查', exact: true }).click()
  const drawer = page.getByRole('dialog')
  await expect(drawer).toContainText('检查')
  await expect(drawer.getByTestId('product-check-observation')).toBeVisible()
  await expect(drawer.getByTestId('product-check-data-details')).not.toHaveAttribute('open')
})

test('keeps Kline usable when research is unavailable and does not invent missing OI', async ({ page }) => {
  await mockWorkspace(page, { json: research(null) })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')
  await expect(page.getByText('120 bars')).toBeVisible()
  const details = await openDataDetails(page)
  await expect(details.getByText('OI 暂无可用数据')).toBeVisible()
})

test('research endpoint failure leaves the Kline readable', async ({ page }) => {
  await mockWorkspace(page, { status: 409, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'QUERY_WINDOW_EMPTY' } }) })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')
  await expect(page.getByText('120 bars')).toBeVisible()
  await expect(page.getByTestId('product-check-background')).toContainText('市场背景数据不可用')
})

test('HTDY stays opt-in and uses an in-chart legend without the redundant risk banner', async ({ page }) => {
  await mockWorkspace(page, { json: research() })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  await expect(page.getByText('火天大有原始观察 · 未来引用/重绘风险 · 仅供人工观察', { exact: true })).toHaveCount(0)
  await expect(page.getByTestId('htdy-chart-legend')).toHaveCount(0)
  await page.getByRole('group', { name: 'Overlay' }).getByRole('button', { name: '火天大有', exact: true }).click()
  await expect(page.getByText('火天大有原始观察 · 未来引用/重绘风险 · 仅供人工观察', { exact: true })).toHaveCount(0)
  const legend = page.getByTestId('htdy-chart-legend')
  await expect(legend).toBeVisible()
  await expect(legend.getByText('ZK1 上轨', { exact: true })).toBeVisible()
  await expect(legend.getByText('ZD1 下轨', { exact: true })).toBeVisible()
  await expect(legend.getByText('ZD2 趋势', { exact: true })).toBeVisible()

  const shellBox = await page.getByTestId('kline-shell').boundingBox()
  expect(shellBox).not.toBeNull()
  await page.mouse.move(shellBox.x + 240, shellBox.y + 220)
  const hoverLegend = page.locator('.kline-hover-legend')
  await expect(hoverLegend).toBeVisible()
  const hoverBox = await hoverLegend.boundingBox()
  const legendBox = await legend.boundingBox()
  expect(hoverBox).not.toBeNull()
  expect(legendBox).not.toBeNull()
  expect(legendBox.y).toBeGreaterThanOrEqual(hoverBox.y + hoverBox.height + 4)
})

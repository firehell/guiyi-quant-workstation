import { expect, test } from '@playwright/test'

function radar(freshnessState = 'current') {
  const degraded = freshnessState === 'degraded'
  const pending = freshnessState === 'pending_after_market'
  const items = [
    {
      symbol: 'ag', product_name: '白银', sector: 'precious', price_change_1d: '0.032',
      price_change_5d: '0.061', volume_ratio20: '1.72', oi_change_1d: '0.081',
      atr14_percentile252: '0.83', position20: '0.91', turnover: '9000',
      reason_codes: ['ema21_up', 'price_move_up', 'volume_expansion', 'oi_increase'],
    },
    {
      symbol: 'jm', product_name: '焦煤', sector: 'black', price_change_1d: '-0.021',
      price_change_5d: '-0.034', volume_ratio20: '1.12', oi_change_1d: '-0.06',
      atr14_percentile252: '0.56', position20: '0.24', turnover: '6000',
      reason_codes: ['price_move_down', 'oi_decrease'],
    },
  ]
  return {
    status: degraded ? 'degraded' : 'ready',
    expected_as_of: '2026-08-24', target_as_of: '2026-08-24',
    data_as_of: pending ? '2026-08-23' : '2026-08-24', freshness_state: freshnessState,
    freshness_message: degraded ? '数据异常' : pending ? '盘后更新待完成' : '当前完整',
    active_count: 60, participant_count: degraded ? 59 : 60,
    stale: degraded ? ['jm'] : [], unavailable: [],
    summary: { up_count: 1, down_count: 1, volume_expansion_count: 1, oi_increase_count: 1, high_volatility_count: 1 },
    items,
    sector_summary: [
      { sector: 'precious', total_count: 1, participant_count: 1, up_count: 1, down_count: 0, median_price_change_1d: '0.032' },
      { sector: 'black', total_count: 1, participant_count: degraded ? 0 : 1, up_count: 0, down_count: degraded ? 0 : 1, median_price_change_1d: degraded ? null : '-0.021' },
    ],
  }
}

function dailyWatchTrend(priceSide) {
  const rising = priceSide === 'above'
  return {
    bar_end: '2026-08-24T07:00:00Z', trading_day: '2026-08-24',
    physical_contract: 'RB2610', segment_start_trading_day: '2026-07-20',
    close: rising ? '3512.125' : '3400.5', ema21: '3478.2468', price_side: priceSide,
    slope_5_bps_per_bar: rising ? '8.6214' : '-8.6214',
    slope_10_bps_per_bar: rising ? '5.9173' : '-5.9173',
  }
}

function dailyWatchItem(symbol, decision) {
  const rising = decision === 'long_watch'
  return {
    symbol, product_name: symbol.toUpperCase(), sector: 'black', decision,
    reason_codes: [rising ? 'D1_H1_LONG_ALIGNED' : 'D1_H1_SHORT_ALIGNED'],
    daily: dailyWatchTrend(rising ? 'above' : 'below'),
    hourly: dailyWatchTrend(rising ? 'above' : 'below'), unavailable_reasons: [],
  }
}

function dailyWatch(overrides = {}) {
  const longSymbols = ['rb', 'ag', 'cu', 'al', 'zn', 'au', 'sn']
  const shortSymbols = ['jm', 'i', 'hc', 'ni', 'pb', 'ru', 'bu']
  return {
    status: 'ready', expected_target_trading_day: '2026-08-25',
    latest_target_trading_day: '2026-08-25', error_code: null,
    snapshot: {
      source_trading_day: '2026-08-24', target_trading_day: '2026-08-25', generated_at: '2026-08-24T10:24:13Z',
      counts: { universe: 60, long_watch: 7, short_watch: 7, excluded: 45, unavailable: 1 },
      long_watch: longSymbols.map((symbol) => dailyWatchItem(symbol, 'long_watch')),
      short_watch: shortSymbols.map((symbol) => dailyWatchItem(symbol, 'short_watch')),
      unavailable: [{
        symbol: 'sc', product_name: '原油', sector: 'energy', decision: 'unavailable',
        reason_codes: [], daily: null, hourly: null, unavailable_reasons: ['H1_HISTORY_INSUFFICIENT'],
      }],
    },
    ...overrides,
  }
}

function runtimeHealth() {
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
        processing_state: 'unobserved', notification_state: 'unobserved', last_processed_bar_at: null,
        last_processing_success_at: null, last_processing_failure_at: null, processing_error_type: null,
        last_event_at: null, last_transport_attempt_at: null, last_provider_accepted_at: null,
        last_notification_failure_at: null, notification_error_type: null, consecutive_notification_failures: 0, error_type: null,
      },
      after_market: {
        status: 'ok', configured_enabled: true, run_state: 'completed', expected_trading_day: '2026-08-24',
        current_run: null, last_run: null, last_successful_trading_day: '2026-08-24', last_failure: null,
        error_type: null, error_message: null,
      },
    },
  }
}

async function mockHomepage(page, radarPayload = radar(), dailyPayload = dailyWatch()) {
  await page.route('**/api/alerts/formal-signals/current', (route) => route.fulfill({
    json: { status: 'ready', trading_day: '2026-08-24', items: [] },
  }))
  await page.route('**/api/runtime/health', (route) => route.fulfill({ json: runtimeHealth() }))
  await page.route('**/api/v1/market/research/radar', (route) => route.fulfill({ json: radarPayload }))
  await page.route('**/api/v1/market/research/subing-daily-watch/current', (route) => route.fulfill({ json: dailyPayload }))
}

test('renders Daily Watch instead of Trend Focus, expands each direction independently, and opens exact SuBing entry', async ({ page }) => {
  await mockHomepage(page)
  await page.goto('/market')

  const watch = page.getByTestId('subing-daily-watch')
  await expect(watch).toContainText('苏冰今日观察')
  await expect(page.getByText('Trend Focus', { exact: true })).toHaveCount(0)
  await expect(watch).toContainText('目标交易日 2026-08-25 · 来源交易日 2026-08-24')
  await expect(watch).toContainText('多头观察 7')
  await expect(watch).toContainText('空头观察 7')
  await expect(watch).toContainText('趋势不明确 45')
  await expect(watch).toContainText('数据不可用 1')

  const longGroup = page.getByTestId('subing-daily-watch-group-long')
  const shortGroup = page.getByTestId('subing-daily-watch-group-short')
  await expect(longGroup.getByTestId('subing-daily-watch-card')).toHaveCount(6)
  await expect(shortGroup.getByTestId('subing-daily-watch-card')).toHaveCount(6)
  await longGroup.getByRole('button', { name: '展开剩余 1 个多头观察' }).click()
  await expect(longGroup.getByTestId('subing-daily-watch-card')).toHaveCount(7)
  await expect(shortGroup.getByTestId('subing-daily-watch-card')).toHaveCount(6)
  await shortGroup.getByRole('button', { name: '展开剩余 1 个空头观察' }).click()
  await expect(shortGroup.getByTestId('subing-daily-watch-card')).toHaveCount(7)
  await expect(watch).not.toContainText('3512.125')
  await expect(watch).not.toContainText('3478.2468')

  await longGroup.getByRole('button', { name: '检查 RB 15m' }).click()
  await expect(page).toHaveURL(/\/market\/chart\?/)
  const url = new URL(page.url())
  expect(url.pathname).toBe('/market/chart')
  expect(Object.fromEntries(url.searchParams)).toEqual({
    symbol: 'rb', series_kind: 'actual_dominant', frequency: '15m', overlay: 'subing', entry: 'subing-daily-watch',
  })
})

test('renders ready Daily Watch before a pending Radar request completes', async ({ page }) => {
  let releaseRadar = () => {}
  const radarGate = new Promise((resolve) => { releaseRadar = resolve })
  await page.route('**/api/alerts/formal-signals/current', (route) => route.fulfill({
    json: { status: 'ready', trading_day: '2026-08-24', items: [] },
  }))
  await page.route('**/api/runtime/health', (route) => route.fulfill({ json: runtimeHealth() }))
  await page.route('**/api/v1/market/research/subing-daily-watch/current', (route) => route.fulfill({ json: dailyWatch() }))
  await page.route('**/api/v1/market/research/radar', async (route) => {
    await radarGate
    return route.fulfill({ json: radar() })
  })

  try {
    await page.goto('/market')
    const watch = page.getByTestId('subing-daily-watch')
    await expect(watch).toContainText('苏冰今日观察')
    await expect(watch).toContainText('多头观察 7')
    await expect(watch).toContainText('RB RB')
    await expect(page.getByTestId('market-radar-skeleton')).toBeVisible()
    await expect(page.getByTestId('market-full-research')).toHaveCount(0)
  } finally {
    releaseRadar()
  }

  await expect(page.getByTestId('market-radar-skeleton')).toHaveCount(0)
  await expect(page.getByTestId('market-full-research')).toBeVisible()
  await expect(page.getByTestId('subing-daily-watch')).toContainText('RB RB')
})

test('keeps unavailable items collapsed, explains stable reasons, and never makes them clickable', async ({ page }) => {
  await mockHomepage(page)
  await page.goto('/market')

  const watch = page.getByTestId('subing-daily-watch')
  await expect(watch.getByText('SC 原油', { exact: true })).toHaveCount(0)
  await watch.getByRole('button', { name: '展开 1 个数据不可用品种' }).click()
  const unavailable = page.getByTestId('subing-daily-watch-unavailable')
  await expect(unavailable).toContainText('SC 原油')
  await expect(unavailable).toContainText('影响周期：60m')
  await expect(unavailable).toContainText('原因：60m 历史不足')
  await expect(unavailable.getByRole('button')).toHaveCount(0)
})

test('typed Daily Watch unavailable leaves Runtime, Formal and Radar usable without exposing backend codes', async ({ page }) => {
  await mockHomepage(page, radar(), {
    status: 'unavailable', expected_target_trading_day: '2026-08-25',
    latest_target_trading_day: '2026-08-22', error_code: 'SUBING_DAILY_WATCH_STALE', snapshot: null,
  })
  await page.goto('/market')

  await expect(page.getByTestId('subing-daily-watch')).toContainText('苏冰今日观察暂不可用')
  await expect(page.getByTestId('subing-daily-watch')).not.toContainText('SUBING_DAILY_WATCH_STALE')
  await expect(page.getByTestId('market-runtime-status')).toContainText('整体正常')
  await expect(page.getByTestId('market-formal-signals')).toContainText('当前交易日暂无正式信号')
  await page.getByText('展开全市场研究', { exact: true }).click()
  await expect(page.getByText('市场概览', { exact: true })).toBeVisible()
})

test('latest Daily Watch network failure keeps the prior successful snapshot visibly stale', async ({ page }) => {
  let attempt = 0
  await page.route('**/api/alerts/formal-signals/current', (route) => route.fulfill({ json: { status: 'ready', trading_day: '2026-08-24', items: [] } }))
  await page.route('**/api/runtime/health', (route) => route.fulfill({ json: runtimeHealth() }))
  await page.route('**/api/v1/market/research/radar', (route) => route.fulfill({ json: radar() }))
  await page.route('**/api/v1/market/research/subing-daily-watch/current', (route) => {
    attempt += 1
    return attempt === 1 ? route.fulfill({ json: dailyWatch() }) : route.fulfill({ status: 503 })
  })
  await page.goto('/market')
  await expect(page.getByTestId('subing-daily-watch')).toContainText('RB RB')

  await page.getByRole('button', { name: '全部刷新' }).click()

  await expect.poll(() => attempt).toBe(2)
  await expect(page.getByTestId('subing-daily-watch')).toContainText('状态已过期')
  await expect(page.getByTestId('subing-daily-watch')).toContainText('目标交易日 2026-08-25 · 来源交易日 2026-08-24')
  await expect(page.getByTestId('subing-daily-watch-card')).toHaveCount(12)
  await expect(page.getByTestId('subing-daily-watch')).toContainText('RB RB')
})

test('refreshes Formal, Runtime, Radar and Daily manually, but excludes Radar from visibility refresh', async ({ page }) => {
  const counts = { formal: 0, runtime: 0, radar: 0, daily: 0 }
  await page.route('**/api/alerts/formal-signals/current', (route) => {
    counts.formal += 1
    return route.fulfill({ json: { status: 'ready', trading_day: '2026-08-24', items: [] } })
  })
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

  await page.goto('/market')
  await expect.poll(() => ({ ...counts })).toEqual({ formal: 1, runtime: 1, radar: 1, daily: 1 })
  await page.getByRole('button', { name: '全部刷新' }).click()
  await expect.poll(() => ({ ...counts })).toEqual({ formal: 2, runtime: 2, radar: 2, daily: 2 })
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')))
  await expect.poll(() => ({ ...counts })).toEqual({ formal: 3, runtime: 3, radar: 2, daily: 3 })
})

test('keeps Daily Watch independent from Radar freshness and readable at a narrow viewport', async ({ page }) => {
  await mockHomepage(page, radar('degraded'))
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/market')

  const watch = page.getByTestId('subing-daily-watch')
  await expect(watch).toContainText('RB RB')
  await expect(watch).toContainText('目标交易日')
  await expect(page.getByText('市场雷达数据不完整：stale jm', { exact: true })).toBeVisible()
})

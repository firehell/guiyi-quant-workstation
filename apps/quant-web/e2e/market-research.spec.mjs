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
    down_count: median < 0 ? 1 : 0, median_price_change_1d: median, attention_count: 1,
  }
}

function radar(overrides = {}) {
  return {
    status: 'ready', expected_as_of: '2026-08-15', target_as_of: '2026-08-15', data_as_of: '2026-08-15',
    freshness_state: 'current', freshness_message: '当前完整', active_count: 60, participant_count: 60,
    stale: [], unavailable: [],
    summary: { up_count: 20, down_count: 18, volume_expansion_count: 12, oi_increase_count: 9, high_volatility_count: 7 },
    items: [], attention: [], sector_summary: [],
    ...overrides,
  }
}

function dailyWatchItem(symbol, productName = symbol.toUpperCase()) {
  const trend = {
    bar_end: '2026-08-24T07:00:00Z', trading_day: '2026-08-24', physical_contract: `${symbol.toUpperCase()}2701`,
    segment_start_trading_day: '2026-07-20', close: '3512.125', ema21: '3478.2468', price_side: 'above',
    slope_5_bps_per_bar: '8.6214', slope_10_bps_per_bar: '5.9173',
  }
  return {
    symbol, product_name: productName, sector: 'black', decision: 'long_watch',
    reason_codes: ['D1_H1_LONG_ALIGNED'], daily: trend, hourly: trend, unavailable_reasons: [],
  }
}

function dailyWatch({ long_watch = [], short_watch = [], unavailable = [], excluded = 60 } = {}) {
  return {
    status: 'ready', expected_target_trading_day: '2026-08-25', latest_target_trading_day: '2026-08-25', error_code: null,
    snapshot: {
      source_trading_day: '2026-08-24', target_trading_day: '2026-08-25', generated_at: '2026-08-24T10:24:13Z',
      counts: { universe: long_watch.length + short_watch.length + unavailable.length + excluded, long_watch: long_watch.length, short_watch: short_watch.length, excluded, unavailable: unavailable.length },
      long_watch, short_watch, unavailable,
    },
  }
}

function formalSignal() {
  return {
    id: 17, rule_code: 'subing_entry_signal_v1', display_name: '苏冰', symbol: 'jm', product_name: '焦煤',
    contract: 'JM2609', trading_day: '2026-08-15', frequency: '5m', bar_end: '2026-08-15T02:25:00Z',
    result_codes: ['buy'], lower_tf_confirmation: true, detected_at: '2026-08-15T02:26:00Z', notification_attempted_at: null,
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
  currentFormalResponse,
  radarResponse = radar(),
  dailyWatchResponse = dailyWatch(),
  runtimeResponse = runtimeHealth(),
) {
  await page.route('**/api/alerts/formal-signals/current', (route) => route.fulfill({ json: currentFormalResponse }))
  await page.route('**/api/execution-review/event-states**', (route) => {
    const ids = new URL(route.request().url()).searchParams.getAll('event_ids').map(Number)
    return route.fulfill({ json: { items: ids.map((id) => ({
      event_id: id, state: 'pending_decision', decision_id: null, episode_id: null,
    })) } })
  })
  await page.route('**/api/runtime/health', (route) => route.fulfill({ json: runtimeResponse }))
  await page.route('**/api/v1/market/research/radar', (route) => route.fulfill({ json: radarResponse }))
  await page.route('**/api/v1/market/research/subing-daily-watch/current', (route) => route.fulfill({ json: dailyWatchResponse }))
}

test('Market homepage shows compact Runtime facts without implying provider delivery', async ({ page }) => {
  await mockMarketHomepage(page, { status: 'ready', trading_day: '2026-08-15', items: [] })
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
    { status: 'ready', trading_day: '2026-08-15', items: [] },
    radar(),
    dailyWatch(),
    disabledRuntime,
  )
  await page.goto('/market')

  const strip = page.getByRole('region', { name: '运行状态' })
  await expect(strip).toContainText('提醒未启用')
  await expect(strip).not.toContainText('未获自然验证')
})

test('Market homepage refreshes four sources manually and Formal plus Runtime plus Daily on visibility', async ({ page }) => {
  const counts = { formal: 0, runtime: 0, radar: 0, daily: 0 }
  await page.route('**/api/alerts/formal-signals/current', (route) => {
    counts.formal += 1
    return route.fulfill({ json: { status: 'ready', trading_day: '2026-08-15', items: [] } })
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

test('Market homepage marks first Runtime failure unavailable and retains a stale successful snapshot', async ({ page }) => {
  let runtimeAttempt = 0
  await page.route('**/api/alerts/formal-signals/current', (route) => route.fulfill({
    json: { status: 'ready', trading_day: '2026-08-15', items: [] },
  }))
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

test('Market homepage shows the current formal signals above Radar', async ({ page }) => {
  await mockMarketHomepage(page, {
    status: 'ready',
    trading_day: '2026-08-15',
    items: [
      formalSignal(),
      { ...formalSignal(), id: 18, rule_code: 'htdy_original_15m', display_name: '火天大有' },
    ],
  })
  await page.goto('/market')

  await expect(page.getByRole('region', { name: '苏冰' })).toHaveCount(1)
  const workbench = page.getByTestId('subing-workbench')
  const formal = page.getByTestId('market-formal-signals')
  await expect(formal).toContainText('苏冰')
  await expect(formal).toContainText('JM 焦煤 · 买入信号')
  await expect(formal).toContainText('JM2609')
  await expect(formal).toContainText('5m · 10:25 确认')
  await expect(formal).toContainText('5m 同向确认')
  await expect(formal).toContainText('火天大有')
  await expect(workbench.getByTestId('subing-daily-watch')).toBeVisible()
  expect(await page.locator('[data-testid="market-formal-signals"], [data-testid="subing-daily-watch"]').evaluateAll((nodes) => (
    Boolean(nodes[0]?.compareDocumentPosition(nodes[1]) & Node.DOCUMENT_POSITION_FOLLOWING)
  ))).toBe(true)
})

test('SuBing workbench keeps Formal and Daily Watch failures independent', async ({ page }) => {
  let formalFails = true
  let dailyFails = false
  let dailyResponse = dailyWatch({ long_watch: [dailyWatchItem('ag', '白银')], excluded: 59 })
  await page.route('**/api/alerts/formal-signals/current', (route) => (
    formalFails
      ? route.fulfill({ status: 503 })
      : route.fulfill({ json: { status: 'ready', trading_day: '2026-08-15', items: [formalSignal()] } })
  ))
  await page.route('**/api/runtime/health', (route) => route.fulfill({ json: runtimeHealth() }))
  await page.route('**/api/v1/market/research/radar', (route) => route.fulfill({ json: radar() }))
  await page.route('**/api/v1/market/research/subing-daily-watch/current', (route) => (
    dailyFails ? route.fulfill({ status: 503 }) : route.fulfill({ json: dailyResponse })
  ))
  await page.route('**/api/execution-review/event-states**', (route) => route.fulfill({ json: { items: [] } }))
  await page.goto('/market')

  const workbench = page.getByTestId('subing-workbench')
  await expect(workbench.getByTestId('market-formal-signals')).toContainText('正式信号暂不可用')
  await expect(workbench.getByTestId('subing-daily-watch')).toContainText('AG 白银')

  formalFails = false
  dailyFails = true
  await page.getByRole('button', { name: '全部刷新' }).click()
  await expect(workbench.getByTestId('market-formal-signals')).toContainText('JM 焦煤')
  await expect(workbench.getByTestId('subing-daily-watch')).toContainText('状态已过期')
  await expect(workbench.getByTestId('subing-daily-watch')).toContainText('目标交易日 2026-08-25 · 来源交易日 2026-08-24')
  await expect(workbench.getByTestId('subing-daily-watch')).toContainText('AG 白银')
  await expect(workbench.getByTestId('subing-daily-watch-card')).toHaveCount(1)

  dailyFails = false
  dailyResponse = dailyWatch({ long_watch: [dailyWatchItem('cu', '沪铜')], excluded: 59 })
  await page.getByRole('button', { name: '全部刷新' }).click()
  await expect(workbench.getByTestId('subing-daily-watch').getByText('状态已过期', { exact: true })).toHaveCount(0)
  await expect(workbench.getByTestId('subing-daily-watch')).toContainText('CU 沪铜')
  await expect(workbench.getByTestId('subing-daily-watch')).not.toContainText('AG 白银')
})

test('formal signal cards do not advertise a container-wide click target', async ({ page }) => {
  await mockMarketHomepage(page, { status: 'ready', trading_day: '2026-08-15', items: [formalSignal()] })
  await page.goto('/market')

  const card = page.getByTestId('market-formal-signals').locator('.market-formal-signals__card')
  await card.hover()
  await expect(card).toHaveCSS('transform', 'none')
  await expect(card.getByRole('button', { name: '记录执行' })).toBeVisible()
})

test('same Formal event-id set keeps its Execution Review action while refreshed states are pending', async ({ page }) => {
  let lookupCount = 0
  let releaseReplacementLookup
  const replacementLookup = new Promise((resolve) => { releaseReplacementLookup = resolve })
  await page.route('**/api/alerts/formal-signals/current', (route) => route.fulfill({
    json: { status: 'ready', trading_day: '2026-08-15', items: [formalSignal()] },
  }))
  await page.route('**/api/execution-review/event-states**', async (route) => {
    lookupCount += 1
    if (lookupCount === 2) await replacementLookup
    return route.fulfill({ json: { items: [{ event_id: 17, state: 'pending_decision', decision_id: null, episode_id: null }] } })
  })
  await page.route('**/api/runtime/health', (route) => route.fulfill({ json: runtimeHealth() }))
  await page.route('**/api/v1/market/research/radar', (route) => route.fulfill({ json: radar() }))
  await page.route('**/api/v1/market/research/subing-daily-watch/current', (route) => route.fulfill({ json: dailyWatch() }))
  await page.goto('/market')

  const formal = page.getByTestId('market-formal-signals')
  await expect(formal.getByRole('button', { name: '记录执行' })).toBeVisible()
  await page.getByRole('button', { name: '全部刷新' }).click()
  await expect.poll(() => lookupCount).toBe(2)
  await expect(formal.getByRole('button', { name: '记录执行' })).toBeVisible()
  releaseReplacementLookup()
})

test('Market homepage keeps formal decisions ahead of Radar at a 980-like viewport', async ({ page }) => {
  await page.setViewportSize({ width: 979, height: 900 })
  await mockMarketHomepage(page, {
    status: 'ready',
    trading_day: '2026-08-15',
    items: [formalSignal(), { ...formalSignal(), id: 18, symbol: 'ag', product_name: '白银', contract: 'AG2601' }],
  })
  await page.goto('/market')

  const formal = page.getByTestId('market-formal-signals')
  await expect(formal).toContainText('只显示当前交易日的正式信号')
  await expect(page.getByTestId('subing-daily-watch')).toBeVisible()
  await expect(formal.locator('.market-formal-signals__card')).toHaveCount(2)
  expect(await formal.locator('.market-formal-signals__card').evaluateAll((cards) => cards[1].getBoundingClientRect().top > cards[0].getBoundingClientRect().top)).toBe(true)
  expect(await page.locator('[data-testid="market-formal-signals"], [data-testid="subing-daily-watch"]').evaluateAll((nodes) => (
    Boolean(nodes[0]?.compareDocumentPosition(nodes[1]) & Node.DOCUMENT_POSITION_FOLLOWING)
  ))).toBe(true)
})

test('Market homepage caps formal decisions at two columns on desktop', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await mockMarketHomepage(page, {
    status: 'ready',
    trading_day: '2026-08-15',
    items: [
      formalSignal(),
      { ...formalSignal(), id: 18, symbol: 'ag', product_name: '白银', contract: 'AG2601' },
      { ...formalSignal(), id: 19, symbol: 'au', product_name: '黄金', contract: 'AU2610' },
    ],
  })
  await page.goto('/market')

  const cards = page.getByTestId('market-formal-signals').locator('.market-formal-signals__card')
  await expect(cards).toHaveCount(3)
  const tops = await cards.evaluateAll((nodes) => nodes.map((node) => node.getBoundingClientRect().top))
  expect(Math.abs(tops[0] - tops[1])).toBeLessThan(1)
  expect(tops[2]).toBeGreaterThan(tops[1])
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
  await mockMarketHomepage(page, { status: 'ready', trading_day: '2026-08-15', items: [] }, radar({
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

test('Market homepage keeps lower-timeframe confirmation fixed at 5m for a 15m signal', async ({ page }) => {
  await mockMarketHomepage(page, {
    status: 'ready', trading_day: '2026-08-15', items: [{ ...formalSignal(), frequency: '15m' }],
  })
  await page.goto('/market')

  const formal = page.getByTestId('market-formal-signals')
  await expect(formal).toContainText('买入信号')
  await expect(formal).toContainText('15m')
  await expect(formal).toContainText('5m 同向确认')
  await expect(formal).not.toContainText('15m 同向确认')
})

test('Market homepage distinguishes ready empty formal signals', async ({ page }) => {
  await mockMarketHomepage(page, { status: 'ready', trading_day: '2026-08-15', items: [] })
  await page.goto('/market')

  await expect(page.getByTestId('market-formal-signals')).toContainText('当前交易日暂无正式信号')
})

test('Market homepage keeps Radar visible when formal signals are unavailable', async ({ page }) => {
  await mockMarketHomepage(page, { status: 'unavailable', trading_day: null, items: [] })
  await page.goto('/market')

  const formal = page.getByTestId('market-formal-signals')
  await expect(formal.getByText('暂不可用', { exact: true })).toBeVisible()
  await expect(formal).toContainText('正式信号暂不可用')
  await expect(page.getByTestId('subing-daily-watch')).toBeVisible()
})

test('Market homepage shows Radar skeletons while the initial snapshot is pending', async ({ page }) => {
  await page.route('**/api/alerts/formal-signals/current', (route) => route.fulfill({
    json: { status: 'ready', trading_day: '2026-08-15', items: [] },
  }))
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
  await page.route('**/api/alerts/formal-signals/current', (route) => route.fulfill({
    json: { status: 'ready', trading_day: '2026-08-15', items: [] },
  }))
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
  await page.route('**/api/alerts/formal-signals/current', (route) => route.fulfill({
    json: { status: 'ready', trading_day: '2026-08-15', items: [] },
  }))
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
  await mockMarketHomepage(page, { status: 'ready', trading_day: '2026-08-15', items: [formalSignal()] })
  await page.goto('/market')

  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1280, height: 720 },
    { width: 1024, height: 768 },
  ]) {
    await page.setViewportSize(viewport)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    const box = await page.getByTestId('market-formal-signals').boundingBox()
    expect(box.x + box.width).toBeLessThanOrEqual(viewport.width)
  }
})

function subing(overrides = {}) {
  return { ...cloneSubingLifecycleCase('longSetup'), ...overrides }
}

function panelEvent(overrides = {}) {
  return {
    id: 301,
    rule_code: 'subing_entry_signal_v1',
    symbol: 'ag',
    contract: 'AG2601',
    trading_day: '2026-01-12',
    frequency: '5m',
    bar_end: '2026-01-12T02:30:00Z',
    result_codes: ['sell'],
    lower_tf_confirmation: false,
    detected_at: '2026-01-12T02:30:01Z',
    notification_attempted_at: null,
    ...overrides,
  }
}

async function mockWorkspace(page, researchResponse, options = {}) {
  const workspaceSymbol = options.symbol || 'ag'
  const workspaceContract = options.resolvedContract || (workspaceSymbol === 'jm' ? 'JM2701' : 'AG2601')
  const marketRequests = options.marketRequests || []
  const researchRequests = options.researchRequests || []
  const subingRequests = options.subingRequests || []
  const nHistoricalRequests = options.nHistoricalRequests || []
  const jdjHistoricalRequests = options.jdjHistoricalRequests || []
  const jdjStrategyHistoricalRequests = options.jdjStrategyHistoricalRequests || []
  const dominantRequests = options.dominantRequests || []
  let dominantResponseIndex = 0
  let subingResponseIndex = 0
  await page.route('**/api/v1/market/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/research/n-structure/history')) {
      const request = Object.fromEntries(url.searchParams)
      nHistoricalRequests.push(request)
      return route.fulfill({ json: {
        request,
        events: options.nHistoricalEvents || [{
          event_id: 'n-structure-up-1', observed_at: options.historicalEventTime,
          trading_day: options.historicalEventTime?.slice(0, 10), contract: workspaceContract,
          segment_start_trading_day: options.historicalEventTime?.slice(0, 10), direction: 'up',
        }],
      } })
    }
    if (url.pathname.endsWith('/research/subing/history')) {
      const request = Object.fromEntries(url.searchParams)
      return route.fulfill({ json: { request, events: [] } })
    }
    if (url.pathname.endsWith('/research/jdj/history')) {
      const request = Object.fromEntries(url.searchParams)
      jdjHistoricalRequests.push(request)
      return route.fulfill({ json: {
        request,
        events: options.jdjHistoricalEvents || [{
          event_id: 'jdj-follow-long-1', candidate_id: 'jdj_trend_follow_1m_candidate_v1',
          source_event_kind: 'jdj_trend_follow_triggered', observed_at: options.historicalEventTime,
          trading_day: options.historicalEventTime?.slice(0, 10), contract: workspaceContract,
          segment_start_trading_day: options.historicalEventTime?.slice(0, 10), direction: 'long',
          trigger_level: '219.5',
        }],
      } })
    }
    if (url.pathname.endsWith('/research/jdj-strategy/history')) {
      const request = Object.fromEntries(url.searchParams)
      jdjStrategyHistoricalRequests.push(request)
      if (jdjStrategyHistoricalRequests.length === 1 && options.jdjStrategyFirstDelayMs) {
        await new Promise((resolve) => setTimeout(resolve, options.jdjStrategyFirstDelayMs))
      }
      if (options.jdjStrategyErrorCode) {
        return route.fulfill({
          status: 422,
          json: { detail: { code: options.jdjStrategyErrorCode } },
        })
      }
      if (options.jdjStrategyHttpStatus) {
        return route.fulfill({
          status: options.jdjStrategyHttpStatus,
          json: { detail: 'unavailable' },
        })
      }
      return route.fulfill({ json: {
        request,
        reference_execution: true,
        actions: options.jdjStrategyHistoricalActions || [{
          event_id: 'jdj-strategy-entry-long-1', episode_id: 'jdj-episode-1', kind: 'entry',
          source_event_ids: ['jdj-follow-long-1'], primary_setup: 'trend_follow', supporting_setups: [],
          direction: 'long', contract: workspaceContract, trading_day: options.historicalEventTime?.slice(0, 10),
          segment_start_trading_day: options.historicalEventTime?.slice(0, 10),
          decision_at: options.historicalEventTime, effective_bar_end: options.historicalEventTime,
          reference_price: '219.5', quantity: 8, position_quantity_after: 8,
          stop_price: '217.5', target_price: '224', reward_risk: '2.25',
          reason: 'ENTRY_FILLED', fill_basis: 'limit_touch',
        }, {
          event_id: 'jdj-strategy-rejected-1', episode_id: null, kind: 'rejected',
          source_event_ids: ['jdj-follow-short-2'], primary_setup: 'trend_follow', supporting_setups: [],
          direction: 'short', contract: workspaceContract, trading_day: options.historicalEventTime?.slice(0, 10),
          segment_start_trading_day: options.historicalEventTime?.slice(0, 10),
          decision_at: options.historicalEventTime, effective_bar_end: null,
          reference_price: null, quantity: 0, position_quantity_after: 8,
          stop_price: '221.5', target_price: null, reward_risk: null,
          reason: 'OPEN_EPISODE_EVENT_REJECTED', fill_basis: null,
        }],
      } })
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
  await page.route('**/api/execution-review/event-states**', (route) => route.fulfill({
    json: { items: options.eventStates || [] },
  }))
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
      if (options.alertScopeDelayMs) await new Promise((resolve) => setTimeout(resolve, options.alertScopeDelayMs))
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
    if (url.pathname.endsWith('/events')) return route.fulfill({ json: { items: [{
      id: 101, rule_code: 'subing_entry_signal_v1', symbol, contract,
      trading_day: '2026-01-12', frequency: '5m', bar_end: '2026-01-12T02:20:00Z',
      result_codes: ['buy'], lower_tf_confirmation: false, detected_at: '2026-01-12T02:20:01Z',
      notification_attempted_at: null,
    }] } })
    return route.abort()
  })
}

async function openMoreResearch(page) {
  const more = page.getByTestId('product-check-more')
  if (!(await more.getAttribute('open'))) await more.locator('summary').click()
  return more
}

test('B1 journey narrows AG on the homepage before opening its verification view', async ({ page }) => {
  const ag = radarItem({ symbol: 'ag', product_name: '白银', sector: 'precious' })
  await mockWorkspace(page, { json: research() })
  await mockAlertMarkerSurface(page)
  await mockMarketHomepage(page, {
    status: 'ready', trading_day: '2026-08-15', items: [],
  }, radar({
    items: [ag],
    attention: [ag],
    sector_summary: [sectorSummary('precious', 0.012)],
  }), dailyWatch({
    long_watch: [dailyWatchItem('ag', '白银')],
    excluded: 59,
  }))
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/market')

  await expect(page.getByRole('region', { name: '苏冰' })).toHaveCount(1)
  await expect(page.getByTestId('market-formal-signals')).toBeVisible()
  await expect(page.getByTestId('subing-daily-watch')).toBeVisible()
  expect(await page.locator('[data-testid="market-formal-signals"], [data-testid="subing-daily-watch"]').evaluateAll((nodes) => (
    Boolean(nodes[0]?.compareDocumentPosition(nodes[1]) & Node.DOCUMENT_POSITION_FOLLOWING)
  ))).toBe(true)
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
  await expect(page.getByTestId('product-check-now')).toBeVisible()
  await expect(page.getByTestId('product-check-background')).toBeVisible()
  await expect(page.getByTestId('product-check-observation')).toBeVisible()
  await expect(page.getByTestId('product-check-participation')).toBeVisible()
  await expect(page.getByTestId('product-check-more')).not.toHaveAttribute('open')
})

test('exact Daily Watch chart entry is one-shot and leaves saved chart preferences unchanged', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('guiyi.market.chart.preferences.v3', JSON.stringify({
      version: 3,
      selectedOverlay: 'htdy',
      optionalEmaIndicators: [],
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
  })
  expect(await page.evaluate(() => JSON.parse(
    window.localStorage.getItem('guiyi.market.chart.preferences.v3'),
  ))).toEqual({
    version: 3,
    selectedOverlay: 'htdy',
    optionalEmaIndicators: [],
    period: '5m',
    realtimeFollow: false,
  })

  await overlays.getByRole('button', { name: '无', exact: true }).click()
  await expect(overlays.getByRole('button', { name: '无', exact: true })).toHaveClass(/n-button--primary-type/)
  await expect.poll(() => page.evaluate(() => JSON.parse(
    window.localStorage.getItem('guiyi.market.chart.preferences.v3'),
  ).selectedOverlay)).toBe('none')
})

test('normal Market chart URL still loads the saved non-SuBing overlay', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('guiyi.market.chart.preferences.v3', JSON.stringify({
      version: 3,
      selectedOverlay: 'htdy',
      optionalEmaIndicators: [],
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
  await expect(overlay.getByRole('button')).toHaveText(['无', '苏冰', 'N字', '日进斗金', '日进斗金策略', '火天大有'])
  await expect(page.getByText('120 bars', { exact: true })).toBeVisible()
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-visible-start-trading-day', '2026-01-01')
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-visible-main-indicators', '')
  await expect(page.getByRole('button', { name: '主连', exact: true })).toBeVisible()
  await expect(page.locator('.toolbar__subing-basis')).toHaveText('苏冰计算 AG2601')
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

test('N and JDJ Candidate remain available for AG without implying strategy support', async ({ page }) => {
  const bars = Array.from({ length: 120 }, (_, index) => bar(index))
  const historicalEventTime = bars.at(-1).bar_end
  const nHistoricalRequests = []
  const jdjHistoricalRequests = []
  await mockAlertMarkerSurface(page)
  await mockWorkspace(page, { json: research() }, {
    bars,
    historicalEventTime,
    canonicalCoverage: { start: bars[0].bar_end, end: historicalEventTime },
    nHistoricalRequests,
    jdjHistoricalRequests,
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  const overlay = page.getByRole('group', { name: 'Overlay' })
  const shell = page.getByTestId('kline-shell')
  await expect(page.getByText('120 bars', { exact: true })).toBeVisible()
  await overlay.getByRole('button', { name: 'N字', exact: true }).click()
  await expect.poll(() => nHistoricalRequests.length).toBe(1)
  await expect(shell).toHaveAttribute('data-research-marker-count', '1')
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-visible-main-indicators', '')

  await page.getByRole('group', { name: '周期' }).getByRole('button', { name: '1m', exact: true }).click()
  await expect(shell).toHaveAttribute('data-research-marker-count', '0')
  await overlay.getByRole('button', { name: '日进斗金', exact: true }).click()
  await expect.poll(() => jdjHistoricalRequests.length).toBe(1)
  await expect(shell).toHaveAttribute('data-research-marker-count', '1')
  await expect(shell).toHaveAttribute('data-rendered-research-marker-count', '1')
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-visible-main-indicators', 'ema_20')

  const chartBox = await page.locator('.chart').boundingBox()
  expect(chartBox).not.toBeNull()
  const markerDetail = page.getByTestId('kline-hover-marker')
  for (let x = chartBox.width - 220; x <= chartBox.width - 40; x += 4) {
    await page.mouse.move(chartBox.x + x, chartBox.y + 180)
    if (await markerDetail.count()) break
  }
  await expect(markerDetail).toContainText('jdj_trend_follow_1m_candidate_v1')
  await expect(markerDetail).toContainText(`事件时间 ${historicalEventTime}`)
  await expect(markerDetail).toContainText('触发位 219.5')

  expect(nHistoricalRequests[0]).toMatchObject({ series_kind: 'actual_dominant', symbol: 'ag', frequency: '5m' })
  expect(jdjHistoricalRequests[0]).toMatchObject({ series_kind: 'actual_dominant', symbol: 'ag', frequency: '1m' })
})

test('JDJ Strategy uses current RB identity and clears stale markers across 1m 5m 1m', async ({ page }) => {
  const bars = Array.from({ length: 120 }, (_, index) => bar(index))
  bars[bars.length - 1] = {
    ...bars.at(-1),
    bar_end: '2026-08-20T01:02:00Z',
    trading_day: '2026-08-20',
  }
  const historicalEventTime = bars.at(-1).bar_end
  const marketRequests = []
  const jdjStrategyHistoricalRequests = []
  await mockAlertMarkerSurface(page, [], { symbol: 'rb', contract: 'RB2701' })
  await mockWorkspace(page, { json: {
    ...research(),
    symbol: 'rb', product_name: '螺纹钢', sector: 'black', exchange: 'SHFE', current_dominant: 'RB2701',
  } }, {
    symbol: 'rb',
    productName: '螺纹钢',
    sector: 'black',
    exchange: 'SHFE',
    resolvedContract: 'RB2701',
    bars,
    marketRequests,
    historicalEventTime,
    canonicalCoverage: { start: bars[0].bar_end, end: historicalEventTime },
    jdjStrategyHistoricalRequests,
    jdjStrategyFirstDelayMs: 400,
    jdjStrategyHistoricalActions: [{
      event_id: 'jdj-strategy-rb-entry-1',
      episode_id: 'jdj-rb-episode-1',
      kind: 'entry',
      source_event_ids: ['jdj-rb-follow-long-1'],
      primary_setup: 'trend_follow',
      supporting_setups: [],
      direction: 'long',
      contract: 'RB2701',
      trading_day: '2026-08-20',
      segment_start_trading_day: '2026-08-20',
      decision_at: '2026-08-20T01:01:00Z',
      effective_bar_end: '2026-08-20T01:02:00Z',
      reference_price: '3200',
      quantity: 1,
      position_quantity_after: 1,
      stop_price: '3180',
      target_price: '3240',
      reward_risk: '2',
      reason: 'ENTRY_AUTHORIZED',
      fill_basis: 'limit_touch',
    }],
  })
  await page.goto('/market/chart?symbol=rb&series_kind=actual_dominant&frequency=1m')

  const overlay = page.getByRole('group', { name: 'Overlay' })
  const shell = page.getByTestId('kline-shell')
  await expect(page.getByText('120 bars', { exact: true })).toBeVisible()
  await expect(page.locator('.product-status-strip strong')).toHaveText('RB2701')
  expect(marketRequests[0]).toMatchObject({
    series_kind: 'actual_dominant', symbol: 'rb', frequency: '1m',
  })

  await overlay.getByRole('button', { name: '日进斗金策略', exact: true }).click()
  await expect.poll(() => jdjStrategyHistoricalRequests.length).toBe(1)
  await page.getByRole('group', { name: '周期' }).getByRole('button', { name: '5m', exact: true }).click()
  await expect(shell).toHaveAttribute('data-research-marker-count', '0')
  await expect(page.getByText('当前序列或周期不支持该 Overlay；K 线保持原选择，不自动切换。', { exact: true })).toBeVisible()
  await page.waitForTimeout(450)
  await expect(shell).toHaveAttribute('data-research-marker-count', '0')

  await page.getByRole('group', { name: '周期' }).getByRole('button', { name: '1m', exact: true }).click()
  await expect.poll(() => jdjStrategyHistoricalRequests.length).toBe(2)
  await expect(shell).toHaveAttribute('data-research-marker-count', '1')
  await expect(shell).toHaveAttribute('data-rendered-research-marker-count', '1')
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-visible-main-indicators', '')

  const chartBox = await page.locator('.chart').boundingBox()
  expect(chartBox).not.toBeNull()
  const markerDetail = page.getByTestId('kline-hover-marker')
  for (let x = chartBox.width - 220; x <= chartBox.width - 40; x += 4) {
    await page.mouse.move(chartBox.x + x, chartBox.y + 180)
    if (await markerDetail.count() && (await markerDetail.textContent())?.includes('参考回放')) break
  }
  await expect(markerDetail).toContainText('参考回放')
  await expect(markerDetail).toContainText('主设置 trend_follow')
  await expect(markerDetail).toContainText('合约 RB2701')
  await expect(markerDetail).toContainText('数量 1')
  await expect(markerDetail).toContainText('R:R 2')
  expect(jdjStrategyHistoricalRequests).toEqual([
    { series_kind: 'actual_dominant', symbol: 'rb', frequency: '1m', since: '2026-01-01', through: '2026-08-20' },
    { series_kind: 'actual_dominant', symbol: 'rb', frequency: '1m', since: '2026-01-01', through: '2026-08-20' },
  ])
})

test('JDJ Strategy fails closed for AG profile unavailability', async ({ page }) => {
  const bars = Array.from({ length: 120 }, (_, index) => bar(index))
  const jdjStrategyHistoricalRequests = []
  await mockAlertMarkerSurface(page)
  await mockWorkspace(page, { json: research() }, {
    bars,
    historicalEventTime: bars.at(-1).bar_end,
    canonicalCoverage: { start: bars[0].bar_end, end: bars.at(-1).bar_end },
    jdjStrategyHistoricalRequests,
    jdjStrategyErrorCode: 'JDJ_STRATEGY_PROFILE_UNAVAILABLE',
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=1m')

  const shell = page.getByTestId('kline-shell')
  await expect(page.getByText('120 bars', { exact: true })).toBeVisible()
  await page.getByRole('group', { name: 'Overlay' })
    .getByRole('button', { name: '日进斗金策略', exact: true }).click()

  await expect.poll(() => jdjStrategyHistoricalRequests.length).toBe(1)
  expect(jdjStrategyHistoricalRequests[0]).toMatchObject({
    series_kind: 'actual_dominant', symbol: 'ag', frequency: '1m',
  })
  await expect(shell).toHaveAttribute('data-research-marker-count', '0')
  await expect(shell).toHaveAttribute('data-rendered-research-marker-count', '0')
  await expect(page.getByText('该品种/周期尚未验证；Canonical K 线仍可正常查看。', { exact: true })).toBeVisible()
})

test('JDJ Strategy keeps generic server failures distinct from profile unavailability', async ({ page }) => {
  const bars = Array.from({ length: 120 }, (_, index) => bar(index))
  const jdjStrategyHistoricalRequests = []
  await mockAlertMarkerSurface(page, [], { symbol: 'jm', contract: 'JM2701' })
  await mockWorkspace(page, { json: {
    ...research(),
    symbol: 'jm', product_name: '焦煤', sector: 'black', exchange: 'DCE', current_dominant: 'JM2701',
  } }, {
    symbol: 'jm',
    resolvedContract: 'JM2701',
    bars,
    historicalEventTime: bars.at(-1).bar_end,
    canonicalCoverage: { start: bars[0].bar_end, end: bars.at(-1).bar_end },
    jdjStrategyHistoricalRequests,
    jdjStrategyHttpStatus: 503,
    marketStateDelayMs: 400,
  })
  await page.goto('/market/chart?symbol=jm&series_kind=actual_dominant&frequency=1m')

  await page.getByRole('group', { name: 'Overlay' })
    .getByRole('button', { name: '日进斗金策略', exact: true }).click()

  await expect.poll(() => jdjStrategyHistoricalRequests.length).toBe(1)
  await expect(page.getByText('历史因果重放暂不可用；Canonical K 线仍可正常查看。', { exact: true })).toBeVisible()
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
  const ema60 = ema.getByRole('button', { name: 'EMA60', exact: true })
  await expect(ema10).toBeVisible()
  await expect(ema60).toBeVisible()
  await expect(page.getByText('指定真实合约', { exact: true })).toBeVisible()
  const kline = page.locator('.product-workspace__kline')
  const overlay = page.getByRole('group', { name: 'Overlay' })

  await expect(ema10).toHaveAttribute('aria-pressed', 'false')
  await expect(ema60).toHaveAttribute('aria-pressed', 'false')
  await expect(kline).toHaveAttribute('data-visible-main-indicators', 'ema_21')
  await ema10.click()
  await ema60.click()
  await expect(kline).toHaveAttribute('data-visible-main-indicators', 'ema_10,ema_21,ema_60')
  await overlay.getByRole('button', { name: '火天大有', exact: true }).click()
  await expect(kline).toHaveAttribute('data-visible-main-indicators', 'ema_10,ema_60,htdy')
  await overlay.getByRole('button', { name: '无', exact: true }).click()
  await expect(kline).toHaveAttribute('data-visible-main-indicators', '')
  await expect(ema10).toHaveAttribute('aria-pressed', 'true')
  await expect(ema60).toHaveAttribute('aria-pressed', 'true')
  await overlay.getByRole('button', { name: '苏冰', exact: true }).click()
  await page.reload()
  await expect(kline).toHaveAttribute('data-visible-main-indicators', 'ema_10,ema_21,ema_60')
})

test('SuBing keeps the full Market display history and renders the requested primary Signal', async ({ page }) => {
  await mockWorkspace(page, { json: research() })
  await mockAlertMarkerSurface(page)
  await page.setViewportSize({ width: 1680, height: 1000 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect(page.getByText('120 bars', { exact: true })).toBeVisible()
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-visible-start-trading-day', '2026-01-01')
  await expect(page.getByTestId('subing-formal-event')).toContainText('当前无可展示的苏冰正式事件记录')
  await expect(page.getByTestId('product-check-background')).toContainText('周线')
  await expect(page.getByTestId('product-check-background')).toContainText('日线')
  await expect(page.getByTestId('product-check-observation')).toContainText('苏冰')
  await expect(page.getByTestId('product-check-observation')).toContainText('5m · 当前不匹配')
  await expect(page.getByTestId('product-check-participation')).toContainText('20日位置')
  await expect(page.getByTestId('product-check-more')).not.toHaveAttribute('open')
  await expect(page.getByTestId('subing-panel')).toHaveCount(1)
  await expect(page.getByRole('button', { name: '真实主力', exact: true })).toBeVisible()
  await expect(page.locator('.toolbar__subing-basis')).toHaveText('苏冰计算 AG2601')
  await expect(page.locator('body')).not.toContainText('买入')
  await expect(page.locator('body')).not.toContainText('卖出')
  await expect(page.locator('body')).not.toContainText('formal signal')
  await expect(page.locator('body')).not.toContainText('ZERO_BAND')
})

test('current AlertEvent remains a formal event when no Execution Review state exists', async ({ page }) => {
  const currentEvent = {
    id: 202,
    rule_code: 'subing_entry_signal_v1',
    symbol: 'ag',
    contract: 'AG2601',
    trading_day: '2026-01-12',
    frequency: '5m',
    bar_end: '2026-01-12T02:20:00Z',
    result_codes: ['buy'],
    lower_tf_confirmation: false,
    detected_at: '2026-01-12T02:20:01Z',
    notification_attempted_at: null,
  }
  await mockWorkspace(page, { json: research() })
  await mockAlertMarkerSurface(page, [currentEvent])
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  const formal = page.getByTestId('subing-formal-event')
  await expect(formal).toContainText('苏冰 · 买入信号')
  await expect(formal).toContainText('今日正式提醒记录')
  await expect(formal.getByRole('button')).toHaveCount(0)
  await expect(formal).not.toContainText('研究确认')
})

test('current SuBing Formal Event action remains available in the single product panel', async ({ page }) => {
  const currentEvent = {
    id: 203,
    rule_code: 'subing_entry_signal_v1',
    symbol: 'ag',
    contract: 'AG2601',
    trading_day: '2026-01-12',
    frequency: '5m',
    bar_end: '2026-01-12T02:25:00Z',
    result_codes: ['sell'],
    lower_tf_confirmation: false,
    detected_at: '2026-01-12T02:25:01Z',
    notification_attempted_at: null,
  }
  await mockWorkspace(page, { json: research() }, {
    eventStates: [{ event_id: 203, state: 'pending_decision', decision_id: null, episode_id: null }],
  })
  await mockAlertMarkerSurface(page, [currentEvent])
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  const formal = page.getByTestId('subing-formal-event')
  const action = formal.getByRole('button', { name: '记录执行' })
  await expect(action).toBeVisible()
  await action.click()
  await expect(page).toHaveURL(/\/trade-records\?state=pending_decision&event_id=203/)
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
  const olderBuy = panelEvent({ id: 302, bar_end: '2026-01-12T02:20:00Z', result_codes: ['buy'] })
  const oldestSell = panelEvent({ id: 303, bar_end: '2026-01-12T02:10:00Z' })
  const snapshot = cloneSubingLifecycleCase('dualFormalLong5m')
  snapshot.companion.snapshot.bar_end = '2026-01-12T02:15:00Z'
  await mockWorkspace(page, { json: research() }, {
    subingResponse: snapshot,
    eventStates: [{ event_id: 301, state: 'pending_decision', decision_id: null, episode_id: null }],
  })
  await mockAlertMarkerSurface(page, [selected, htdy, olderBuy, oldestSell], {
    rules: [
      { rule_code: 'htdy_original_15m', display_name: '火天大有', kind: 'indicator_observation', input_frequencies: ['5m', '15m'], enabled_for_product: true, enabled_frequencies: ['5m'] },
      { rule_code: 'subing_entry_signal_v1', display_name: '苏冰入场信号', kind: 'formal_signal', input_frequencies: ['5m', '15m'], enabled_for_product: true, enabled_frequencies: [] },
      { rule_code: 'future_rule', display_name: '未来提醒', kind: 'formal_signal', input_frequencies: ['5m'], enabled_for_product: true, enabled_frequencies: [] },
    ],
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  const panel = page.getByTestId('subing-panel')
  const formal = page.getByTestId('subing-formal-event')
  await expect(formal.locator('[data-formal-event-id="301"]')).toHaveCount(1)
  const historicalRows = formal.locator('.product-today-alert-events__row')
  await expect(historicalRows).toHaveCount(2)
  expect(await historicalRows.evaluateAll((rows) => rows.map((row) => row.getAttribute('data-event-id'))))
    .toEqual(['302', '303'])
  await expect(formal.locator('[data-event-id="301"], [data-event-id="304"]')).toHaveCount(0)
  await expect(panel).not.toContainText('火天大有')
  await expect(panel).not.toContainText('未来提醒')
  await expect(panel.getByRole('switch')).toHaveCount(1)

  await expect(panel.getByText('Resolved Signal', { exact: true })).toBeVisible()
  await expect(panel.getByRole('definition').filter({ hasText: '15m · 买入信号 · 低周期确认' })).toBeVisible()
  await expect(panel.getByText('Primary Signal', { exact: true })).toBeVisible()
  await expect(panel.getByText('5m · 买入信号', { exact: true })).toBeVisible()
  await expect(panel.locator('.subing-panel__factor').filter({ hasText: 'Primary Factor' })).toContainText('5m')
  await expect(panel.locator('.subing-panel__factor').filter({ hasText: 'Companion Factor' })).toContainText('15m')
  await expect(panel.locator('.subing-panel__facts > div').filter({ hasText: 'Primary 确认' })).toContainText('01/12 10:30')
  await expect(panel.locator('.subing-panel__facts > div').filter({ hasText: 'Companion 确认' })).toContainText('01/12 10:15')

  await formal.getByRole('button', { name: '记录执行' }).click()
  await expect(page).toHaveURL(/\/trade-records\?state=pending_decision&event_id=301/)
})

test('SuBing panel keeps Event and Alert loading independent from a ready snapshot', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, {
    subingResponse: cloneSubingLifecycleCase('dualFormalLong5m'),
  })
  await mockAlertMarkerSurface(page, [], {
    currentEventsDelayMs: 900,
    alertScopeDelayMs: 1_500,
    rules: [{
      rule_code: 'subing_entry_signal_v1', display_name: '苏冰入场信号', kind: 'formal_signal',
      input_frequencies: ['5m', '15m'], enabled_for_product: false, enabled_frequencies: [],
    }],
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  const panel = page.getByTestId('subing-panel')
  const formal = page.getByTestId('subing-formal-event')
  const scope = page.getByTestId('subing-alert-scope')
  await expect(panel.getByText('Resolved Signal', { exact: true })).toBeVisible()
  await expect(formal).toContainText('正在读取苏冰正式事件')
  await expect(formal).not.toContainText('当前无可展示的苏冰正式事件记录')
  await expect(scope).toContainText('正在读取苏冰提醒 Scope')
  await expect(scope).not.toContainText('不可用')
  await expect(scope.getByRole('switch')).toHaveCount(0)

  await expect(formal.getByText('当前无可展示的苏冰正式事件记录', { exact: true })).toHaveCount(1)
  await expect(formal.getByTestId('product-today-alert-events')).toHaveCount(0)
  await expect(scope.getByRole('switch')).toBeVisible()
  await expect(scope.getByRole('switch')).toBeEnabled()
})

test('SuBing panel keeps an unavailable Event source distinct from ready empty', async ({ page }) => {
  await mockWorkspace(page, { json: research() })
  await mockAlertMarkerSurface(page, [], { currentEventsStatus: 'unavailable' })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  const formal = page.getByTestId('subing-formal-event')
  await expect(formal).toContainText('苏冰正式事件暂不可用')
  await expect(formal).not.toContainText('当前无可展示的苏冰正式事件记录')
  await expect(formal.getByTestId('product-today-alert-events')).toHaveCount(0)
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
  await expect(page.getByTestId('product-check-now')).not.toContainText('研究确认')
  await openMoreResearch(page)
  const lifecycle = page.getByTestId('subing-lifecycle-panel')
  await expect(lifecycle).toContainText('Research only')
  await expect(lifecycle).toContainText('研究确认')
  await expect(lifecycle).toContainText('确认进度')
  await expect(lifecycle).toContainText('已研究确认')
  await expect(lifecycle).not.toContainText('3/3')
  await expect(lifecycle).toContainText('最近状态转换')
  await expect(lifecycle).not.toContainText('买入信号')
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1280, height: 720 },
    { width: 1024, height: 768 },
  ]) {
    await page.setViewportSize(viewport)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
})

test('SuBing lifecycle shows a reducer-produced long momentum hold', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, {
    subingResponse: cloneSubingLifecycleCase('longMomentumHold'),
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect(page.getByTestId('product-check-observation')).toContainText('1/3')
  await expect(page.getByTestId('product-check-observation')).toContainText('当前不匹配')
  await openMoreResearch(page)
  await expect(page.getByTestId('subing-lifecycle-panel')).toContainText('1/3')
  await expect(page.locator('.subing-panel__factor').filter({ hasText: 'Primary Factor' })).toContainText('S5 2.0 bps/bar · MACD 金叉')
})

test('retest confirmation renders its own zero then one bar progress', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, {
    bars: lifecycleChartBars,
    subingResponses: [cloneSubingLifecycleCase('pivotRetest0'), cloneSubingLifecycleCase('pivotRetest1')],
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await openMoreResearch(page)
  await expect(page.getByTestId('subing-lifecycle-panel')).toContainText('0/3')
  await expect(page.getByTestId('product-check-observation')).toContainText('0/3')
  const overlay = page.getByRole('group', { name: 'Overlay' })
  await overlay.getByRole('button', { name: '无', exact: true }).click()
  await overlay.getByRole('button', { name: '苏冰', exact: true }).click()
  await expect(page.getByTestId('subing-lifecycle-panel')).toContainText('1/3')
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
  await openMoreResearch(page)
  const setupPanel = page.getByTestId('subing-lifecycle-panel')
  await expect(setupPanel).toBeVisible()
  await expect(setupPanel).toContainText('准备中')
  await expect(setupPanel).toContainText('—')
  await expect(shell).toHaveAttribute('data-alert-marker-count', '1')
  await expect(shell).toHaveAttribute('data-research-marker-count', '1')
  await expect(shell).toHaveAttribute('data-rendered-research-marker-count', '1')

  const overlay = page.getByRole('group', { name: 'Overlay' })
  await overlay.getByRole('button', { name: '无', exact: true }).click()
  await expect(shell).toHaveAttribute('data-alert-marker-count', '1')
  await expect(shell).toHaveAttribute('data-research-marker-count', '0')
  await expect(shell).toHaveAttribute('data-rendered-research-marker-count', '0')
  await overlay.getByRole('button', { name: '苏冰', exact: true }).click()
  await expect(page.getByTestId('subing-lifecycle-panel')).toHaveCount(0)
  await expect(shell).toHaveAttribute('data-research-marker-count', '0')
  await expect(shell).toHaveAttribute('data-rendered-research-marker-count', '0')
  await expect.poll(async () => shell.getAttribute('data-research-marker-count')).toBe('2')
  await expect(shell).toHaveAttribute('data-rendered-research-marker-count', '2')
  await expect(shell).toHaveAttribute('data-alert-marker-count', '1')

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
    await openMoreResearch(page)
    const lifecycle = page.getByTestId('subing-lifecycle-panel')
    await expect(lifecycle).toContainText(expected)
    await expect(page.locator('.subing-panel__factor').filter({ hasText: 'Primary Factor' })).toContainText(isRisk ? 'S5 -2.0 bps/bar' : 'S5 2.0 bps/bar')
    await expect(lifecycle).not.toContainText(/下单|加仓|平仓指令/)
  }
})

test('SuBing daily lifecycle unavailability leaves the existing Factor view readable', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, {
    subingResponse: cloneSubingLifecycleCase('dailyUnavailable'),
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=1d')

  await expect(page.getByTestId('product-check-observation')).toContainText('苏冰')
  await openMoreResearch(page)
  await expect(page.getByTestId('subing-lifecycle-panel')).toContainText('SUBING_LIFECYCLE_INTRADAY_ONLY')
  await expect(page.getByText('Primary Factor', { exact: true })).toBeVisible()
})

test('SuBing shows a same-boundary companion-only match without replacing the requested primary', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, {
    subingResponse: cloneSubingLifecycleCase('companionFormalLong5m'),
  })
  await page.setViewportSize({ width: 1680, height: 1000 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect(page.getByTestId('product-check-observation')).toContainText('15m · 买入信号')
  await openMoreResearch(page)
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
  await openMoreResearch(page)
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
  await openMoreResearch(page)
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
  await openMoreResearch(page)
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

test('SuBing keeps unsupported 30m explicit and does not request a snapshot', async ({ page }) => {
  const subingRequests = []
  await mockWorkspace(page, { json: research() }, {
    subingRequests,
    pageMeta: { has_more_before: true, next_before: '2026-08-01T01:00:00Z' },
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=30m')

  await expect(page.getByText('苏冰当前周期不可用，仅支持 5m / 15m / 1d', { exact: true })).toBeVisible()
  await expect(page.getByText('120 bars', { exact: true })).toBeVisible()
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-visible-main-indicators', '')
  await openMoreResearch(page)
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
  await expect(page.locator('.toolbar__subing-basis')).toHaveText('苏冰计算 AG2602')
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
  await expect(page.getByTestId('product-check-participation')).toContainText('20日位置')
  const more = await openMoreResearch(page)
  await expect(more.getByText('Price / Volume / OI')).toBeVisible()
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
  await expect(drawer.getByTestId('product-check-now')).toBeVisible()
  await expect(drawer.getByTestId('product-check-more')).not.toHaveAttribute('open')
})

test('keeps Kline usable when research is unavailable and does not invent missing OI', async ({ page }) => {
  await mockWorkspace(page, { json: research(null) })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')
  await expect(page.getByText('120 bars')).toBeVisible()
  const more = await openMoreResearch(page)
  await expect(more.getByText('OI 暂无可用数据')).toBeVisible()
})

test('research endpoint failure leaves the Kline readable', async ({ page }) => {
  await mockWorkspace(page, { status: 409, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'QUERY_WINDOW_EMPTY' } }) })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')
  await expect(page.getByText('120 bars')).toBeVisible()
  await expect(page.getByTestId('product-check-background')).toContainText('周线 / 日线数据不可用')
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

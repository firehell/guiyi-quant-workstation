import { expect, test } from '@playwright/test'
import {
  bar,
  research,
  radarItem,
  sectorSummary,
  radar,
  dailyWatchItem,
  dailyWatch,
  mockMarketHomepage,
  subing,
  panelEvent,
  subingStrategyCurrent,
  subingStrategyHistory,
  subingStrategyPerformance,
  mockWorkspace,
  mockAlertMarkerSurface,
  deferred,
  openDataDetails,
  openSubingResearchDetails,
  enableSubingInternalProcess,
  enableSubingStrategyPerformance,
  cloneSubingLifecycleCase,
  lifecycleChartBars,
  reidentifySubingResponse,
} from './market-research.helpers.mjs'

test.describe('SuBing current/history', () => {
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
  await expect(page.getByTestId('subing-performance-kpis')).toContainText('累计参考变动')
  await expect(page.getByTestId('subing-performance-exit-reasons')).toHaveCount(0)
  await page.getByTestId('subing-performance-tab-analysis').click()
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
  await expect(shell).toHaveAttribute('data-rendered-research-marker-count', '0')

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
  await expect(shell).toHaveAttribute('data-rendered-research-marker-count', '0')
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
})

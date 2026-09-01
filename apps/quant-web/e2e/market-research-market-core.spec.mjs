import { expect, test } from '@playwright/test'
import { dailyWatch, runtimeHealth, mockMarketHomepage } from './market-research.helpers.mjs'

test.describe('Market dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/alerts/strategy-actions/current', (route) => route.fulfill({
      json: { status: 'ready', trading_day: '2026-08-25', items: [] },
    }))
  })

  test('shows Runtime facts without implying provider delivery', async ({ page }) => {
    await mockMarketHomepage(page)
    await page.goto('/market')

    await expect(page.getByRole('heading', { name: '行情看板' })).toBeVisible()
    const strip = page.getByTestId('market-runtime-status')
    await expect(strip).toContainText('整体正常')
    await expect(strip).toContainText('服务商已接受（不代表送达）')
  })

  test('does not show retired Radar or all-market-research wording when Daily Watch is ready', async ({ page }) => {
    await mockMarketHomepage(page)
    await page.goto('/market')

    await expect(page.getByTestId('subing-daily-watch')).toContainText('今日观察')
    await expect(page.getByTestId('subing-workbench')).not.toContainText('市场雷达')
    await expect(page.getByTestId('subing-workbench')).not.toContainText('全市场研究')
  })

  test('does not show retired Radar or all-market-research wording when Daily Watch is unavailable', async ({ page }) => {
    await mockMarketHomepage(page, {
      status: 'unavailable', expected_target_trading_day: '2026-08-25',
      latest_target_trading_day: '2026-08-22', error_code: 'SUBING_DAILY_WATCH_STALE', snapshot: null,
    })
    await page.goto('/market')

    const watch = page.getByTestId('subing-daily-watch')
    await expect(watch).toContainText('苏冰今日观察暂不可用')
    await expect(watch).not.toContainText('SUBING_DAILY_WATCH_STALE')
    await expect(watch).not.toContainText('市场雷达')
    await expect(watch).not.toContainText('全市场研究')
  })

  test('refreshes only Runtime, Strategy Actions and Daily Watch', async ({ page }) => {
    const counts = { runtime: 0, daily: 0, strategy: 0, radar: 0 }
    page.on('request', (request) => {
      if (request.url().includes('/api/v1/market/research/radar')) counts.radar += 1
    })
    await page.route('**/api/runtime/health', (route) => {
      counts.runtime += 1
      return route.fulfill({ json: runtimeHealth() })
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
    await expect.poll(() => ({ ...counts })).toEqual({ runtime: 1, daily: 1, strategy: 1, radar: 0 })
    await page.getByRole('button', { name: '全部刷新' }).click()
    await expect.poll(() => ({ ...counts })).toEqual({ runtime: 2, daily: 2, strategy: 2, radar: 0 })
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')))
    await expect.poll(() => ({ ...counts })).toEqual({ runtime: 3, daily: 3, strategy: 3, radar: 0 })
  })

  test('retains a successful Runtime snapshot after a refresh failure', async ({ page }) => {
    let runtimeAttempt = 0
    await page.route('**/api/runtime/health', (route) => {
      runtimeAttempt += 1
      return runtimeAttempt === 2
        ? route.fulfill({ json: runtimeHealth() })
        : route.fulfill({ status: 503 })
    })
    await page.route('**/api/v1/market/research/subing-daily-watch/current', (route) => route.fulfill({ json: dailyWatch() }))

    await page.goto('/market')
    const strip = page.getByTestId('market-runtime-status')
    await expect(strip).toContainText('运行状态暂不可用')
    await page.getByRole('button', { name: '全部刷新' }).click()
    await expect(strip).toContainText('整体正常')
    await page.getByRole('button', { name: '全部刷新' }).click()
    await expect(strip).toContainText('状态已过期')
  })

  test('renders and opens a current Strategy Action without Radar data', async ({ page }) => {
    await mockMarketHomepage(page)
    await page.route('**/api/alerts/strategy-actions/current', (route) => route.fulfill({ json: currentStrategyActions() }))
    await page.goto('/market')

    const surface = page.getByTestId('market-strategy-actions')
    await expect(surface).toContainText('JM 焦煤 · 建多')
    await expect(surface).toContainText('JM2609')
    await surface.getByRole('button', { name: '查看 JM 建多' }).click()
    await expect(page).toHaveURL(/\/market\/chart\?symbol=jm/)
    expect(Object.fromEntries(new URL(page.url()).searchParams)).toEqual({
      symbol: 'jm', series_kind: 'actual_dominant', frequency: '15m', overlay: 'subing',
      entry: 'subing-strategy-action', action_id: currentStrategyActions().items[0].action_id,
    })
  })

  test('keeps Strategy Action unavailable, empty, and stale states distinct', async ({ page }) => {
    let attempt = 0
    await mockMarketHomepage(page)
    await page.route('**/api/alerts/strategy-actions/current', (route) => {
      attempt += 1
      if (attempt === 1) return route.fulfill({ json: { status: 'unavailable', trading_day: null, items: [] } })
      if (attempt === 2) return route.fulfill({ json: { status: 'ready', trading_day: '2026-08-25', items: [] } })
      if (attempt === 3) return route.fulfill({ json: currentStrategyActions() })
      return route.fulfill({ status: 503 })
    })
    await page.goto('/market')

    const surface = page.getByTestId('market-strategy-actions')
    await expect(surface).toContainText('苏冰策略事件暂不可用')
    await page.getByRole('button', { name: '全部刷新' }).click()
    await expect(surface).toContainText('当前交易日暂无苏冰策略事件')
    await page.getByRole('button', { name: '全部刷新' }).click()
    await expect(surface).toContainText('JM 焦煤 · 建多')
    await page.getByRole('button', { name: '全部刷新' }).click()
    await expect(surface).toContainText('状态已过期：已保留上一份成功事件')
  })

  test('keeps a Daily Watch snapshot visibly stale after a refresh failure', async ({ page }) => {
    let attempt = 0
    await page.route('**/api/runtime/health', (route) => route.fulfill({ json: runtimeHealth() }))
    await page.route('**/api/v1/market/research/subing-daily-watch/current', (route) => {
      attempt += 1
      if (attempt === 1) return route.fulfill({ json: dailyWatch() })
      return route.fulfill({ status: 503 })
    })
    await page.goto('/market')
    const watch = page.getByTestId('subing-daily-watch')
    await expect(watch).toContainText('目标交易日 2026-08-25 · 来源交易日 2026-08-24')
    await page.getByRole('button', { name: '全部刷新' }).click()
    await expect(watch).toContainText('状态已过期：已保留上一份成功快照')
  })

  test('keeps unavailable Daily Watch items non-clickable', async ({ page }) => {
    await mockMarketHomepage(page)
    await page.goto('/market')
    const watch = page.getByTestId('subing-daily-watch')
    await watch.getByRole('button', { name: '展开 1 个数据不可用品种' }).click()
    const unavailable = page.getByTestId('subing-daily-watch-unavailable')
    await expect(unavailable).toContainText('SC 原油')
    await expect(unavailable).toContainText('影响周期：60m')
    await expect(unavailable).toContainText('原因：60m 历史不足')
    await expect(unavailable.getByRole('button')).toHaveCount(0)
  })

  test('stays within desktop viewports', async ({ page }) => {
    await mockMarketHomepage(page)
    await page.goto('/market')

    for (const viewport of [
      { width: 1440, height: 900 },
      { width: 1280, height: 720 },
      { width: 1024, height: 768 },
    ]) {
      await page.setViewportSize(viewport)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    }
  })
})

function currentStrategyActions() {
  const action = {
    schema_version: 1, strategy_id: 'subing_strategy_v1', formula_version: 'subing_strategy_15m_v1',
    action_id: 'subing-action:test', episode_id: 'subing-episode:test', kind: 'open_long',
    symbol: 'jm', contract: 'JM2609', trading_day: '2026-08-25', segment_start_trading_day: '2026-08-01',
    opportunity_id: 'subing-opportunity:test', decision_at: '2026-08-25T02:30:00Z',
    effective_open_at: '2026-08-25T02:30:00Z', effective_bar_end: '2026-08-25T02:45:00Z',
    reference_price: '100', fill_basis: 'next_bar_open', confirmation_source: 'formal_v1', reason_codes: [],
    direction_context_source_day: '2026-08-24', direction_context_target_day: '2026-08-25',
    bound_reference_pivot: null, entry: null, holding_bar_count: null, reference_change_percent: null,
  }
  return {
    status: 'ready', trading_day: '2026-08-25', items: [{
      id: 1, rule_code: 'subing_strategy_v1', display_name: '苏冰策略', product_name: '焦煤',
      symbol: 'jm', contract: 'JM2609', trading_day: '2026-08-25', frequency: '15m',
      bar_end: '2026-08-25T02:30:00Z', result_codes: ['open_long'], action_id: action.action_id,
      strategy_action: action, detected_at: '2026-08-25T02:30:01Z', notification_attempted_at: null,
    }],
  }
}

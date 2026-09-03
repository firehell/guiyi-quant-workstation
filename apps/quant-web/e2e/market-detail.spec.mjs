import { expect, test } from '@playwright/test'

import { installDetailFakeWebSocket, mockMarketDetail, navigateClient } from './market-detail.helpers.mjs'

const freeJm = '/market/chart?symbol=jm&view=free&series_kind=actual_dominant&frequency=15m'

test('missing view keeps the complete legacy detail page', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto('/market/chart?symbol=jm&series_kind=actual_dominant&frequency=15m')

  await expect(page.getByTestId('product-status-strip')).toBeVisible()
  await expect(page.locator('[data-detail-ready]')).toHaveCount(0)
})

test('Free mounts its generic workspace without the legacy sidebar or strategy markers', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto(freeJm)

  const shell = page.locator('[data-detail-ready="true"]')
  await expect(shell).toBeVisible()
  await expect(shell.getByText('焦煤', { exact: true }).first()).toBeVisible()
  await expect(page.getByTestId('product-check-sidebar')).toHaveCount(0)
  await expect(page.locator('.product-workspace__sidebar')).toHaveCount(0)
  await expect(shell.locator('[data-detail-workspace="free"]')).toBeVisible()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '0')
  await expect(page.getByText('火天大有（原始观察）', { exact: true })).toHaveCount(0)

  const order = await shell.locator('[data-detail-section]').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-detail-section')))
  expect(order.slice(0, 4)).toEqual(['topbar', 'quote', 'view-nav', 'workspace-slot'])
})

test('Free Range warm-up remains explicit and does not create a strategy marker', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto(freeJm)

  await page.getByLabel('箱体识别（Range）').check()
  await expect(page.getByText(/箱体历史预载不足|箱体历史预载失败/)).toBeVisible()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '0')
})

test('Free identity controls keep the selected contract in the URL', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto(freeJm)

  await page.getByLabel('指定合约').fill('JM2605')
  await page.getByRole('button', { name: '指定合约' }).click()
  await expect.poll(() => new URL(page.url()).searchParams.get('series_kind')).toBe('contract')
  expect(new URL(page.url()).searchParams.get('contract')).toBe('JM2605')
})

test('Free clears a contract when the product changes and keeps HTDY preferences untouched', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('guiyi.market.detail.preferences.v1', JSON.stringify({
      version: 1, lastView: 'htdy',
      htdy: { seriesKind: 'continuous', frequency: '30m', optionalEmaIndicators: ['ema_60'], showRangeDetector: true },
      free: { seriesKind: 'actual_dominant', frequency: '15m', optionalEmaIndicators: [], showRangeDetector: false },
    }))
  })
  await mockMarketDetail(page)
  await page.goto('/market/chart?symbol=jm&view=free&series_kind=contract&contract=JM2605&frequency=15m')

  await page.getByLabel('品种代码').fill('rb')
  await page.getByLabel('品种代码').press('Enter')
  await expect.poll(() => new URL(page.url()).searchParams.get('series_kind')).toBe('actual_dominant')
  expect(new URL(page.url()).searchParams.has('contract')).toBe(false)
  await expect(page.getByText('切换品种时，指定合约会清除并回到真实主力。')).toBeVisible()
  await page.getByLabel('箱体识别（Range）').check()
  const preferences = await page.evaluate(() => JSON.parse(localStorage.getItem('guiyi.market.detail.preferences.v1')))
  expect(preferences.htdy).toEqual({ seriesKind: 'continuous', frequency: '30m', optionalEmaIndicators: ['ema_60'], showRangeDetector: true })
})

test('shared quote header exposes the market phase and display source', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto(freeJm)

  const quote = page.locator('[data-detail-section="quote"]')
  await expect(quote.getByText('已收盘', { exact: true })).toBeVisible()
  await expect(quote.getByText('Historical', { exact: true })).toBeVisible()
})

test('invalid identity fails closed and only recovers after an explicit click', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto('/market/chart?symbol=jm&view=free&series_kind=actual_dominant&frequency=2m')

  await expect(page.getByRole('heading', { name: '详情页地址无效' })).toBeVisible()
  expect(new URL(page.url()).searchParams.get('frequency')).toBe('2m')
  await page.getByRole('button', { name: '恢复安全设置' }).click()
  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  expect(new URL(page.url()).searchParams.get('frequency')).toBe('15m')
})

test('Trend, HTDY, and SuBing stay explicitly unavailable and can return to legacy', async ({ page }) => {
  await mockMarketDetail(page)
  for (const path of [
    '/market/chart?symbol=jm&view=trend',
    '/market/chart?symbol=jm&view=htdy&series_kind=actual_dominant&frequency=15m',
    '/market/chart?symbol=jm&view=subing',
  ]) {
    await page.goto(path)
    await expect(page.getByText('当前视角尚未接入统一详情页', { exact: true })).toBeVisible()
    await expect(page.locator('[data-detail-ready="true"]')).toHaveCount(0)
  }

  await page.getByRole('button', { name: '返回旧版详情' }).click()
  await expect(page.getByTestId('product-status-strip')).toBeVisible()
  await expect(page.locator('.route-error-fallback')).toHaveCount(0)
  expect(new URL(page.url()).searchParams.has('view')).toBe(false)
})

test('returning a 30m HTDY event identity to legacy preserves focus and overlay semantics', async ({ page }) => {
  await mockMarketDetail(page)
  const focus = '2026-09-03T02:30:00Z'
  await page.goto(`/market/chart?symbol=jm&view=htdy&series_kind=actual_dominant&frequency=30m&focus_bar_end=${encodeURIComponent(focus)}`)
  await page.evaluate(async () => {
    const { router } = await import('/src/app/router.ts')
    window.__legacyNavigationQuery = null
    router.beforeEach((to) => {
      if (to.path === '/market/chart' && to.query.view === undefined) {
        window.__legacyNavigationQuery = { ...to.query }
      }
    })
  })

  await page.getByRole('button', { name: '返回旧版详情' }).click()
  await expect(page.getByTestId('product-status-strip')).toBeVisible()
  const legacyUrl = new URL(page.url())
  expect(legacyUrl.searchParams.has('view')).toBe(false)
  expect(legacyUrl.searchParams.get('overlay')).toBe('htdy')
  expect(await page.evaluate(() => window.__legacyNavigationQuery.focus_bar_end)).toBe(focus)
})

test('returning a daily HTDY event only consumes focus after locating its trading day', async ({ page }) => {
  await mockMarketDetail(page)
  const focus = '2026-09-03T02:45:00Z'
  await page.goto(`/market/chart?symbol=jm&view=htdy&series_kind=actual_dominant&frequency=1d&focus_bar_end=${encodeURIComponent(focus)}`)

  await page.getByRole('button', { name: '返回旧版详情' }).click()
  await expect(page.getByTestId('product-status-strip')).toBeVisible()
  await expect.poll(() => new URL(page.url()).searchParams.has('focus_bar_end')).toBe(false)
})

test('returning a fixed view to legacy makes its parsed identity explicit', async ({ page }) => {
  await mockMarketDetail(page)
  for (const expected of [
    { path: '/market/chart?symbol=jm&view=trend', frequency: '1d' },
    { path: '/market/chart?symbol=jm&view=subing', frequency: '15m' },
  ]) {
    await page.goto(expected.path)
    await page.evaluate(async () => {
      const { router } = await import('/src/app/router.ts')
      window.__legacyNavigationQuery = null
      router.beforeEach((to) => {
        if (to.path === '/market/chart' && to.query.view === undefined) {
          window.__legacyNavigationQuery = { ...to.query }
        }
      })
    })

    await page.getByRole('button', { name: '返回旧版详情' }).click()
    await expect(page.getByTestId('product-status-strip')).toBeVisible()
    const transferred = await page.evaluate(() => window.__legacyNavigationQuery)
    expect(transferred.series_kind).toBe('actual_dominant')
    expect(transferred.frequency).toBe(expected.frequency)
  }
})

test('a late JM response cannot overwrite a newer RB identity', async ({ page }) => {
  await mockMarketDetail(page, { researchDelayMs: { jm: 400 } })
  await page.goto(freeJm)
  await navigateClient(page, '/market/chart?symbol=rb&view=free&series_kind=actual_dominant&frequency=15m')

  const shell = page.locator('[data-detail-ready="true"]')
  await expect(shell.getByText('螺纹钢', { exact: true }).first()).toBeVisible()
  await expect(shell.getByText('201.00', { exact: true })).toBeVisible()
  await page.waitForTimeout(500)
  await expect(shell.getByText('螺纹钢', { exact: true }).first()).toBeVisible()
  await expect(shell.getByText('201.00', { exact: true })).toBeVisible()
})

test('leaving the Free shell closes its live series resource', async ({ page }) => {
  await installDetailFakeWebSocket(page)
  await mockMarketDetail(page, { live: true })
  await page.goto(freeJm)

  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  await expect.poll(() => page.evaluate(() => (
    window.__marketDetailSockets?.filter((socket) => socket.url.includes('/api/v1/market/ws') && !socket.closed).length ?? 0
  ))).toBeGreaterThan(0)

  await navigateClient(page, '/market/chart?symbol=jm&view=trend')
  await expect(page.getByText('当前视角尚未接入统一详情页', { exact: true })).toBeVisible()
  await expect.poll(() => page.evaluate(() => (
    window.__marketDetailSockets
      ?.filter((socket) => socket.url.includes('/api/v1/market/ws'))
      .every((socket) => socket.closed) ?? false
  ))).toBe(true)
})

test('390px shell keeps keyboard disclosure and does not invent history', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockMarketDetail(page)
  await page.goto(freeJm)

  const disclosure = page.getByRole('button', { name: /更多行情数据/ })
  await disclosure.focus()
  await page.keyboard.press('Enter')
  await expect(disclosure).toHaveAttribute('aria-expanded', 'true')
  await page.keyboard.press('Space')
  await expect(disclosure).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByRole('button', { name: '历史记录' })).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test('mobile history drawer traps focus, closes with Escape, and restores its trigger', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockMarketDetail(page)
  await page.goto(freeJm)
  await page.evaluate(async () => {
    const { createApp, h, ref } = await import('/node_modules/.vite/deps/vue.js')
    const { default: MarketDetailDrawer } = await import('/src/components/market/detail/MarketDetailDrawer.vue')
    const host = document.createElement('div')
    host.id = 'drawer-browser-contract'
    document.body.append(host)
    const open = ref(false)
    const app = createApp({
      setup() {
        return () => h('div', [
          h('button', { id: 'drawer-trigger', onClick: () => { open.value = true } }, '打开历史'),
          h(MarketDetailDrawer, {
            open: open.value,
            title: '历史记录',
            onClose: () => { open.value = false },
          }, { default: () => h('button', { id: 'drawer-action' }, '历史项') }),
        ])
      },
    })
    app.mount(host)
    window.__marketDetailDrawerContractApp = app
  })

  const trigger = page.locator('#drawer-trigger')
  await trigger.click()
  const dialog = page.getByRole('dialog', { name: '历史记录' })
  await expect(dialog).toBeVisible()
  await expect(page.getByRole('button', { name: '关闭' })).toBeFocused()
  await page.locator('#drawer-action').focus()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: '关闭' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()
})

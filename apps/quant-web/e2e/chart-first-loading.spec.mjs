import { expect, test } from '@playwright/test'
import { installNewowProductFixtures, newowRoute, productRequests, assertNoUnexpectedRequests } from './newow-product.helpers.mjs'

for (const width of [1440, 390]) {
  test(`price preview precedes strategy verification; lazy returns ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    const state = await installNewowProductFixtures(page, { deferOnce: 'trend:1d:chart', recordsHistory: true })
    await page.goto(newowRoute())
    const preview = page.getByRole('region', { name: '价格预览', exact: true })
    await expect(preview.locator('canvas').first()).toBeVisible()
    await expect(preview).toContainText('策略确认后显示')
    await expect(page.getByTestId('newow-product-chart-stage')).toHaveCount(0)
    expect(productRequests(state, 'reference')).toHaveLength(0)
    await expect.poll(() => state.deferred.size).toBe(1)
    const chart = productRequests(state, 'chart')[0].url
    expect(chart.searchParams.get('resolve_current')).toBe('true')
    expect(chart.searchParams.has('as_of')).toBe(false)
    expect(state.requests.filter(item => /\/(daily|weekly)-snapshot$/.test(item.url.pathname))).toHaveLength(0)
    await state.deferred.get('trend:1d:chart')()
    await expect(page.getByTestId('newow-product-chart-stage')).toBeVisible()
    await expect(preview).toHaveCount(0)
    await page.getByRole('region', { name: 'Newow 参考与解释', exact: true }).scrollIntoViewIfNeeded()
    await expect.poll(() => productRequests(state, 'reference').length).toBeGreaterThan(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    assertNoUnexpectedRequests(state)
  })
}

test('pending current period retains only prices and never reads dependent strategy sections', async ({ page }) => {
  const state = await installNewowProductFixtures(page, { pendingCurrent: true })
  await page.goto(newowRoute())
  await expect(page.getByRole('region', { name: '价格预览', exact: true }).locator('canvas').first()).toBeVisible()
  await expect(page.getByRole('status').filter({ hasText: '当前周期待更新' }).first()).toBeVisible()
  await expect(page.getByTestId('newow-product-chart-stage')).toHaveCount(0)
  expect(productRequests(state, 'reference')).toHaveLength(0)
  expect(productRequests(state, 'auxiliary')).toHaveLength(0)
  expect(productRequests(state, 'explanation')).toHaveLength(0)
  assertNoUnexpectedRequests(state)
})

test('reload restores disk prices before stalled network and keeps strategy hidden', async ({ page }) => {
  const options = { deferOnce: 'trend:1d:chart' }
  const state = await installNewowProductFixtures(page, options)
  await page.goto(newowRoute())
  await expect(page.getByRole('region', { name: '价格预览', exact: true })).not.toContainText('截止 读取中')
  await expect.poll(() => page.evaluate(async () => {
    const names = await indexedDB.databases()
    const name = names.find(item => item.name.startsWith('guiyi-detail-prices-v1:'))?.name
    if (!name) return 0
    return new Promise(resolve => {
      const open = indexedDB.open(name)
      open.onsuccess = () => { const db = open.result, read = db.transaction('snapshots').objectStore('snapshots').count(); read.onsuccess = () => { resolve(read.result); db.close() } }
    })
  })).toBeGreaterThan(0)
  state.counts.clear(); state.deferred.clear(); options.genericSeries = 'pending'
  await page.addInitScript(() => {
    window.__pricePaint = {}
    new MutationObserver(() => {
      const workspace = document.querySelector('[data-detail-section="workspace-slot"]')
      if (workspace && window.__pricePaint.mount == null) window.__pricePaint.mount = performance.now()
      if (document.querySelector('.newow-product-workspace__price-preview')?.textContent.includes('历史缓存价格预览') && window.__pricePaint.ready == null) window.__pricePaint.ready = performance.now()
    }).observe(document, { childList: true, subtree: true, characterData: true })
  })
  await page.reload({ waitUntil: 'domcontentloaded' })
  const preview = page.getByRole('region', { name: '价格预览', exact: true })
  await expect(preview).toContainText('历史缓存价格预览')
  await expect(preview.locator('canvas').first()).toBeVisible()
  await expect(page.getByTestId('newow-product-chart-stage')).toHaveCount(0)
  const timing = await page.evaluate(() => window.__pricePaint)
  console.log(`cached detail mount-to-price: ${Math.round(timing.ready-timing.mount)}ms`)
  expect(timing.ready-timing.mount).toBeLessThanOrEqual(200)
  assertNoUnexpectedRequests(state)
})

test('strategy switch revokes old strategy while cached prices remain available', async ({ page }) => {
  const state = await installNewowProductFixtures(page, { deferOnce: 'oscillation:1d:chart' })
  await page.goto(newowRoute())
  await expect(page.getByTestId('newow-product-chart-stage')).toBeVisible()
  await page.getByRole('tab', { name: '震荡策略', exact: true }).click()
  await expect(page.getByRole('region', { name: '价格预览', exact: true })).toContainText('策略确认后显示')
  await expect(page.getByTestId('newow-product-chart-stage')).toHaveCount(0)
  await expect.poll(() => state.deferred.has('oscillation:1d:chart')).toBe(true)
  await state.deferred.get('oscillation:1d:chart')()
  await expect(page.getByTestId('newow-product-chart-stage')).toBeVisible()
  assertNoUnexpectedRequests(state)
})

test('manual refresh revalidates one chart and hides old strategy while retaining price preview', async ({ page }) => {
  const options = {}
  const state = await installNewowProductFixtures(page, options)
  await page.goto(newowRoute())
  await expect(page.getByTestId('newow-product-chart-stage')).toBeVisible()
  state.counts.clear(); options.deferOnce = 'trend:1d:chart'
  const before = productRequests(state, 'chart').length
  await page.getByRole('button', { name: '刷新当前数据', exact: true }).click()
  await expect(page.getByRole('region', { name: '价格预览', exact: true })).toContainText('策略确认后显示')
  await expect(page.getByTestId('newow-product-chart-stage')).toHaveCount(0)
  await expect.poll(() => state.deferred.has('trend:1d:chart')).toBe(true)
  expect(productRequests(state, 'chart')).toHaveLength(before + 1)
  await state.deferred.get('trend:1d:chart')()
  await expect(page.getByTestId('newow-product-chart-stage')).toBeVisible()
  expect(productRequests(state, 'chart')).toHaveLength(before + 1)
  assertNoUnexpectedRequests(state)
})

test('API offline including capabilities still restores only cached prices', async ({ page }) => {
  await installNewowProductFixtures(page)
  await page.goto(newowRoute())
  await expect(page.getByTestId('newow-product-chart-stage')).toBeVisible()
  await expect.poll(() => page.evaluate(async () => {
    const names = await indexedDB.databases()
    return names.some(item => item.name.startsWith('guiyi-detail-prices-v1:'))
  })).toBe(true)
  await page.route('**/api/v1/**', route => route.abort('internetdisconnected'))
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('region', { name: '价格预览', exact: true })).toContainText('历史缓存价格预览')
  await expect(page.getByTestId('newow-product-chart-stage')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '重试能力配置', exact: true })).toBeVisible()
})

test('returning from experiment reattaches lazy reference observation to the new region', async ({ page }) => {
  const state = await installNewowProductFixtures(page)
  await page.route('**/api/v1/market/newow/experiments?*', route => route.fulfill({ status: 503, json: { detail: { code: 'NEWOW_DATA_UNAVAILABLE' } } }))
  await page.goto(newowRoute())
  await expect(page.getByTestId('newow-product-chart-stage')).toBeVisible()
  await page.locator('.newow-test-menu > summary').click()
  await page.getByRole('button', { name: '测试', exact: true }).click()
  await expect(page.getByRole('region', { name: '震荡实验策略', exact: true })).toBeVisible()
  await page.getByRole('tab', { name: '震荡策略', exact: true }).click()
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-strategy', 'oscillation')
  await expect(page.getByTestId('newow-product-chart-stage')).toBeVisible()
  await page.getByRole('region', { name: 'Newow 参考与解释', exact: true }).scrollIntoViewIfNeeded()
  await expect.poll(() => productRequests(state, 'reference').filter(item => item.strategy === 'oscillation').length).toBeGreaterThan(0)
  assertNoUnexpectedRequests(state)
})

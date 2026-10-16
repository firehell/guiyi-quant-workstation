import { expect, test } from '@playwright/test'

test.skip(process.env.REAL_DEVELOP !== '1', 'Requires the independently running development API and Web')
test('real JM/RB chart, cache revisit and switch waterfall', async ({ page }) => {
  await page.addInitScript(() => {
    window.__pricePreviewTiming = { mount: null, ready: null }
    new MutationObserver(() => {
      const region = document.querySelector('.newow-product-workspace__price-preview')
      if (region && window.__pricePreviewTiming.mount === null) window.__pricePreviewTiming.mount = performance.now()
      if (region?.textContent.match(/截止 \d{4}-/) && window.__pricePreviewTiming.ready === null) requestAnimationFrame(() => { window.__pricePreviewTiming.ready ??= performance.now() })
    }).observe(document, { childList: true, subtree: true, characterData: true })
  })
  const errors = [], waterfall = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('requestfinished', async request => {
    if (!request.url().includes('/api/v1/market/')) return
    try {
      const response = await request.response()
      waterfall.push({ path: new URL(request.url()).pathname, query: new URL(request.url()).search, status: response?.status(), timing: request.timing(), serverTiming: response?.headers()['server-timing'], sizes: await request.sizes() })
    } catch { /* Navigation may close a response after its completed facts were displayed. */ }
  })
  for (const [symbol, frequency, strategy] of [['jm','1d','oscillation'], ['rb','1d','oscillation'], ['jm','1d','oscillation'], ['jm','60m','oscillation'], ['jm','1d','trend']]) {
    const started = Date.now()
    await page.goto(`/market/chart?view=newow&symbol=${symbol}&strategy=${strategy}&series_kind=actual_dominant&frequency=${frequency}`)
    await expect(page.getByTestId('newow-product-chart-stage')).toBeVisible({ timeout: 20000 })
    console.log(JSON.stringify({ symbol, frequency, strategy, chartVisibleMs: Date.now()-started, preview: await page.evaluate(() => window.__pricePreviewTiming), heap: await page.evaluate(() => performance.memory?.usedJSHeapSize ?? null) }))
  }
  await page.screenshot({ path: '/private/tmp/chart-first-real-desktop.png' })
  console.log(JSON.stringify({ waterfall, errors }))
  expect(errors).toEqual([])
})

test('JM/RB price-entry sample with fresh browser storage', async ({ browser }) => {
  test.setTimeout(120000)
  const samples = []
  for (let index = 0; index < 20; index++) {
    const context = await browser.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, viewport: { width: 1440, height: 900 } })
    const page = await context.newPage(), symbol = index % 2 ? 'rb' : 'jm'
    await page.addInitScript(() => {
      window.__firstPrice = null
      new MutationObserver(() => {
        const preview = document.querySelector('.newow-product-workspace__price-preview')
        if (preview?.textContent.match(/截止 \d{4}-/) && window.__firstPrice == null) requestAnimationFrame(() => { window.__firstPrice ??= performance.now() })
      }).observe(document, { childList: true, subtree: true, characterData: true })
    })
    await page.goto(`/market/chart?view=newow&symbol=${symbol}&strategy=oscillation&series_kind=actual_dominant&frequency=1d`)
    await expect.poll(() => page.evaluate(() => window.__firstPrice), { timeout: 10000 }).not.toBeNull()
    samples.push({ symbol, priceMs: await page.evaluate(() => window.__firstPrice), heap: await page.evaluate(() => performance.memory?.usedJSHeapSize ?? null) })
    await context.close()
  }
  const p95 = samples.map(item => item.priceMs).sort((a, b) => a-b)[18]
  console.log(JSON.stringify({ storageColdSamples: samples, p95, note: 'Fresh browser storage; existing development API, not a server cold-start benchmark' }))
  expect(p95).toBeLessThanOrEqual(2000)
})

test('real manual refresh preserves price preview and revalidates once', async ({ page }) => {
  const requests = []
  page.on('requestfinished', async request => {
    if (!request.url().includes('/api/v1/market/')) return
    try { requests.push({ path: new URL(request.url()).pathname, query: new URL(request.url()).search, timing: request.timing(), sizes: await request.sizes() }) } catch {}
  })
  await page.goto('/market/chart?view=newow&symbol=jm&strategy=oscillation&series_kind=actual_dominant&frequency=1d')
  await expect(page.getByTestId('newow-product-chart-stage')).toBeVisible({ timeout: 20000 })
  requests.length = 0
  const started = Date.now()
  await page.getByRole('button', { name: '刷新当前数据', exact: true }).click()
  await expect(page.getByRole('region', { name: '价格预览', exact: true })).toContainText('策略确认后显示')
  await expect(page.getByTestId('newow-product-chart-stage')).toBeVisible({ timeout: 20000 })
  const charts = requests.filter(item => item.query.includes('resolve_current=true'))
  expect(charts).toHaveLength(1)
  console.log(JSON.stringify({ manualRefreshChartMs: Date.now()-started, waterfall: requests, heap: await page.evaluate(() => performance.memory?.usedJSHeapSize ?? null) }))
})

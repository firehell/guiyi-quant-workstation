import { expect, test } from '@playwright/test'
import { installNewowProductFixtures, newowRoute } from './newow-product.helpers.mjs'

test('all detail strategies retain one native canvas and their period without repeating price pagination', async ({ page }, testInfo) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const fixture = await installNewowProductFixtures(page)
  await page.route('**/api/v1/reference-trading/**', route => route.fulfill({ status: 503, json: { detail: 'Explicit unavailable reference fixture' } }))
  await page.goto(newowRoute())
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready')
  const canvas = page.locator('.tv-lightweight-charts').first()
  await expect(canvas).toBeVisible()
  await canvas.evaluate(element => { window.__detailCanvas = element })
  const pricePages = () => fixture.requests.filter(item => item.url.pathname.endsWith('/bars/page') && item.url.searchParams.get('limit') === '500').length
  const initialPages = pricePages()
  const timings = []
  for (const label of ['震荡策略', '火天大有', '苏冰预警', '自由看盘', '趋势策略', '震荡策略', '趋势策略']) {
    const started = Date.now()
    await page.getByRole('tab', { name: label, exact: true }).click()
    await expect(page.locator('.tv-lightweight-charts').first()).toBeVisible()
    await expect.poll(() => page.evaluate(() => document.querySelector('.tv-lightweight-charts') === window.__detailCanvas)).toBe(true)
    expect(new URL(page.url()).searchParams.get('frequency')).toBe('1d')
    expect(new URL(page.url()).searchParams.get('symbol')).toBe('rb')
    await expect(page.locator('.quote-header')).toBeVisible()
    timings.push({ label, elapsedMs: Date.now() - started })
  }
  expect(pricePages()).toBe(initialPages)
  expect(errors).toEqual([])
  await testInfo.attach('strategy-switch-timings', { body: JSON.stringify(timings), contentType: 'application/json' })
  await page.screenshot({ path: '/private/tmp/guiyi-detail-unified-desktop.png', fullPage: true })
})

test('unsupported analysis keeps the selected one-minute chart without issuing strategy requests', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page)
  await page.goto('/market/chart?symbol=rb&view=free&frequency=1m&series_kind=actual_dominant')
  await expect(page.locator('.tv-lightweight-charts')).toBeVisible()
  await page.locator('.tv-lightweight-charts').evaluate(element => { window.__detailCanvas = element })
  await page.getByRole('tab', { name: '趋势策略', exact: true }).click()
  await expect(page.getByText('当前牛哇周期未开放', { exact: true })).toBeVisible()
  expect(new URL(page.url()).searchParams.get('frequency')).toBe('1m')
  expect(fixture.productRequests).toHaveLength(0)
  expect(await page.evaluate(() => document.querySelector('.tv-lightweight-charts') === window.__detailCanvas)).toBe(true)
  await page.getByRole('tab', { name: '苏冰预警', exact: true }).click()
  await expect(page.getByText('苏冰预警不支持当前周期或指定合约，行情与当前周期已保留。', { exact: true })).toBeVisible()
  expect(new URL(page.url()).searchParams.get('frequency')).toBe('1m')
})

test('native time range and verified history survive a 500 to 300 bar adapter change', async ({ page }) => {
  await installNewowProductFixtures(page)
  await page.goto(newowRoute())
  const result = await page.evaluate(async () => {
    const { createDetailChartSession, detailChartIndex } = await import('/src/utils/detailChartSession.ts')
    const { createChart, CandlestickSeries } = await import('/node_modules/lightweight-charts/dist/lightweight-charts.development.mjs')
    const host = document.createElement('div'); host.style.cssText='width:1000px;height:600px'; document.body.appendChild(host)
    const session = createDetailChartSession({ createChart })
    session.setIdentity('rb:60m')
    const first = session.acquire(host, { width: 1000, height: 600 })
    const bars = Array.from({length:500},(_,index)=>({time:1767225600+index*3600,open:100+index,high:102+index,low:99+index,close:101+index}))
    first.addSeries(CandlestickSeries).setData(bars)
    first.timeScale().setVisibleLogicalRange({from:40,to:100})
    const before = first.timeScale().getVisibleRange()
    const second = session.acquire(host, {width:1000,height:600})
    const candles = second.addSeries(CandlestickSeries); candles.setData(bars.slice(-300))
    const after = second.timeScale().getVisibleRange(), retained=candles.data().length
    candles.setData(bars.slice(-400))
    const afterPrepend = second.timeScale().getVisibleRange()
    const locate = detailChartIndex(second, bars[499].time, 299)
    second.timeScale().setVisibleLogicalRange({ from:locate - 48,to:locate + 8 })
    const focused = second.timeScale().getVisibleRange()
    session.dispose();host.remove()
    return { before, after, afterPrepend, retained, locate, focused, last:bars[499].time }
  })
  expect(result.before).not.toBeNull()
  expect(result.after).toEqual(result.before)
  expect(result.afterPrepend).toEqual(result.before)
  expect(result.retained).toBe(500)
  expect(result.locate).toBe(499)
  expect(result.focused.from).toBeLessThan(result.last)
  expect(result.focused.to).toBe(result.last)
})

test('cached strategy indicators paint within 100ms while current verification remains independent', async ({ page }, testInfo) => {
  await installNewowProductFixtures(page, { onProductRequest: async ({ strategy, section, count }) => {
    if (strategy === 'trend' && section === 'chart' && count === 2) await new Promise(resolve => setTimeout(resolve, 300))
  } })
  await page.goto(newowRoute())
  const workspace = page.locator('[data-detail-workspace="newow"]')
  await expect(workspace).toHaveAttribute('data-chart-state', 'ready')
  await page.getByRole('tab', { name: '震荡策略', exact: true }).click()
  await expect(workspace).toHaveAttribute('data-chart-state', 'ready')
  await page.evaluate(() => {
    window.__cachedPaint = new Promise(resolve => {
      document.addEventListener('click', () => {
        const started = performance.now()
        requestAnimationFrame(() => {
          const stage = document.querySelector('[data-testid="newow-product-chart-stage"]')
          resolve({ ms:performance.now()-started, strategy:stage?.getAttribute('data-strategy'), bands:Number(stage?.getAttribute('data-band-area-count')), current:document.querySelector('[data-detail-workspace="newow"]')?.getAttribute('data-chart-state') })
        })
      }, { capture:true, once:true })
    })
  })
  await page.getByRole('tab', { name:'趋势策略', exact:true }).click()
  const result = await page.evaluate(() => window.__cachedPaint)
  console.log(`cached-indicator-first-frame-ms=${result.ms.toFixed(2)}`)
  expect(result.strategy).toBe('trend'); expect(result.bands).toBeGreaterThan(0)
  expect(result.current).toBe('loading'); expect(result.ms).toBeLessThanOrEqual(100)
  await testInfo.attach('cached-paint', { body:JSON.stringify(result),contentType:'application/json' })
  await expect(workspace).toHaveAttribute('data-chart-state','ready')
})

test('compact and desktop detail layouts preserve readable controls without horizontal overflow', async ({ page }) => {
  await installNewowProductFixtures(page)
  await page.goto(newowRoute())
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state','ready')
  for (const width of [1440,390]) {
    await page.setViewportSize({width,height:1000})
    await expect.poll(() => page.locator('.market-detail-page').evaluate(element => element.scrollWidth-element.clientWidth)).toBeLessThanOrEqual(1)
    await expect(page.getByRole('tab',{name:'趋势策略',exact:true})).toBeVisible()
    await page.screenshot({path:`/private/tmp/guiyi-detail-unified-${width}.png`,fullPage:true})
  }
})

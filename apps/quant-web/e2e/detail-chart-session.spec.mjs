import { expect, test } from '@playwright/test'
import { writeFile } from 'node:fs/promises'
import { assertNoUnexpectedRequests, installNewowProductFixtures, newowRoute } from './newow-product.helpers.mjs'
import { navigateClient } from './market-detail.helpers.mjs'

test('isolated chart soak measures pane and canvas teardown across repeated workspaces', async ({ page }) => {
  const output = process.env.GUIYI_CHART_SOAK_JSON
  test.skip(!output, 'Requires an explicit scratch JSON destination')
  const seconds = Number(process.env.GUIYI_CHART_SOAK_SECONDS ?? 180)
  expect(Number.isInteger(seconds) && seconds > 0).toBe(true)
  test.setTimeout((seconds + 75) * 1000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const fixture = await installNewowProductFixtures(page)
  await page.goto(newowRoute())
  const stage = page.getByTestId('newow-product-chart-stage')
  await expect(stage).toHaveAttribute('data-auxiliary-component', 'zhaoyao_mirror')
  const chartPackage = await stage.getAttribute('data-chart-package')
  const canvas = page.locator('.tv-lightweight-charts')
  const baseCanvas = await canvas.first().elementHandle()
  const library = await (await page.waitForFunction(() => performance.getEntriesByType('resource')
    .find(entry => new URL(entry.name).pathname.endsWith('/lightweight-charts.js'))?.name)).jsonValue()
  await page.evaluate(async (moduleUrl) => {
    const { createChart, CandlestickSeries } = await import(moduleUrl)
    const probe = createChart(document.createElement('div'))
    const chartApi = Object.getPrototypeOf(probe)
    const seriesApi = Object.getPrototypeOf(probe.addSeries(CandlestickSeries))
    const timeApi = Object.getPrototypeOf(probe.timeScale())
    probe.remove()
    const series = new Set(), primitives = new Set(), listeners = new Set()
    function hook(prototype, method, observe) {
      const original = prototype[method]
      prototype[method] = function (...args) {
        const result = original.apply(this, args)
        observe(args, result)
        return result
      }
    }
    hook(chartApi, 'addSeries', (_, result) => series.add(result))
    hook(chartApi, 'removeSeries', ([item]) => series.delete(item))
    hook(seriesApi, 'attachPrimitive', ([item]) => primitives.add(item))
    hook(seriesApi, 'detachPrimitive', ([item]) => primitives.delete(item))
    hook(timeApi, 'subscribeVisibleLogicalRangeChange', ([listener]) => listeners.add(listener))
    hook(timeApi, 'unsubscribeVisibleLogicalRangeChange', ([listener]) => listeners.delete(listener))
    hook(chartApi, 'subscribeCrosshairMove', ([listener]) => listeners.add(listener))
    hook(chartApi, 'unsubscribeCrosshairMove', ([listener]) => listeners.delete(listener))
    window.__chartSoakResources = () => ({ series: series.size, primitives: primitives.size, listeners: listeners.size })
  }, library)
  const resources = () => page.evaluate(() => window.__chartSoakResources())
  const session = await page.context().newCDPSession(page)
  const samples = [], times = []
  async function sample(phase, cycles) {
    await session.send('HeapProfiler.collectGarbage')
    const heap = await session.send('Runtime.getHeapUsage')
    const dom = await session.send('Memory.getDOMCounters')
    const caches = await page.evaluate(async () => {
      const { newowSessionResources } = await import('/src/utils/newowSessionResources.ts')
      const { detailPriceCacheStats } = await import('/src/api/detailPriceCache.ts')
      return { strategy: newowSessionResources.stats(), price: detailPriceCacheStats() }
    })
    for (const cache of Object.values(caches)) {
      expect(cache.entries).toBeLessThanOrEqual(cache.maxEntries)
      expect(cache.bytes).toBeLessThanOrEqual(cache.maxBytes)
    }
    const fixtureSocketUrls = await page.evaluate(() => window.__newowFixtureWebSockets.length)
    samples.push({ phase, cycles, elapsedSeconds: (Date.now() - start) / 1000, heap, dom, caches,
      resources: await resources(), fixtureSocketUrls })
  }
  const start = Date.now()
  let cycles = 0
  const workspaceResources = new Map()
  let nextSample = start + 15_000
  const rows = stage.locator('tr').filter({ has: page.locator('td:nth-child(3)') })
  const selector = stage.getByRole('combobox', { name: '选择附加副图' })
  const macd = stage.locator('[data-auxiliary-pane="macd"]')
  await sample('mounted', cycles)
  while (Date.now() - start < seconds * 1000) {
    const cycleStart = Date.now()
    await stage.getByRole('button', { name: '涨跌动能', exact: true }).click()
    await expect(stage).toHaveAttribute('data-auxiliary-component', 'up_down_energy')
    const baseResources = await resources()
    if (!await selector.isVisible()) await stage.getByText('副图管理', { exact: true }).click()
    await selector.selectOption('macd')
    await stage.getByRole('button', { name: '添加', exact: true }).click()
    await expect(macd).toHaveAttribute('data-auxiliary-status', 'ready')
    await expect(rows).toHaveCount(4)
    expect((await resources()).series).toBe(baseResources.series + 4)
    await stage.getByRole('button', { name: '隐藏MACD副图' }).click()
    await expect(rows).toHaveCount(3)
    await stage.getByRole('button', { name: '显示MACD副图' }).click()
    await expect(rows).toHaveCount(4)
    await stage.getByRole('button', { name: '移除MACD副图' }).click()
    await expect(rows).toHaveCount(3)
    await expect.poll(resources).toEqual(baseResources)
    await stage.getByRole('button', { name: '主力照妖镜', exact: true }).click()
    await expect(stage).toHaveAttribute('data-auxiliary-component', 'zhaoyao_mirror')

    for (const [label, view] of [['震荡策略', 'newow'], ['火天大有', 'htdy'], ['苏冰预警', 'subing'], ['自由看盘', 'free']]) {
      await page.getByRole('tab', { name: label, exact: true }).click()
      await expect(page.locator(`[data-detail-workspace="${view}"]`)).toBeVisible()
      await expect(canvas).toHaveCount(1)
      expect(await baseCanvas.evaluate(node => node === document.querySelector('.tv-lightweight-charts'))).toBe(true)
    }
    const strategy = cycles % 2 === 0 ? 'main_rise' : 'trend'
    await navigateClient(page, newowRoute(strategy))
    await expect(stage).toHaveAttribute('data-auxiliary-state', 'ready')
    await expect(rows).toHaveCount(3)
    if (workspaceResources.has(strategy)) await expect.poll(resources).toEqual(workspaceResources.get(strategy))
    else workspaceResources.set(strategy, await resources())
    cycles++
    times.push(Date.now() - cycleStart)
    if (Date.now() >= nextSample) {
      await sample('cycling', cycles)
      nextSample = Date.now() + 15_000
    }
  }
  expect(cycles).toBeGreaterThan(0)
  await sample('before_unmount', cycles)
  await page.evaluate(() => document.querySelector('#app').__vue_app__.unmount())
  await expect(canvas).toHaveCount(0)
  await expect.poll(resources).toEqual({ series: 0, primitives: 0, listeners: 0 })
  await baseCanvas.dispose()
  await expect.poll(() => page.evaluate(async () => {
    const { newowSessionResources } = await import('/src/utils/newowSessionResources.ts')
    return newowSessionResources.stats().pending
  })).toBe(0)
  await sample('after_unmount', cycles)
  await session.detach()
  expect(errors).toEqual([])
  assertNoUnexpectedRequests(fixture)
  const ordered = times.toSorted((a, b) => a - b)
  const percentiles = [0.5, 0.95, 0.99].map(fraction => ordered[Math.ceil(fraction * ordered.length) - 1])
  await writeFile(output, JSON.stringify({ startedAt: new Date(start).toISOString(), chartPackage,
    elapsedSeconds: (Date.now() - start) / 1000, thresholdSeconds: seconds,
    cycles, cycleTimeP50P95P99Ms: percentiles, samples, productRequests: fixture.productRequests.length, errors }, null, 2) + '\n', { flag: 'wx' })
})

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
  for (const label of ['震荡策略', '火天大有', '苏冰预警', '自由看盘', '传统趋势深链', '震荡策略', '趋势策略']) {
    const started = Date.now()
    if (label === '传统趋势深链') await navigateClient(page, newowRoute())
    else await page.getByRole('tab', { name: label, exact: true }).click()
    await expect(page.locator('.tv-lightweight-charts').first()).toBeVisible()
    await expect.poll(() => page.evaluate(() => document.querySelector('.tv-lightweight-charts') === window.__detailCanvas)).toBe(true)
    expect(new URL(page.url()).searchParams.get('frequency')).toBe('1d')
    expect(new URL(page.url()).searchParams.get('symbol')).toBe('rb')
    await expect(page.locator('.quote-header')).toBeVisible()
    if (['趋势策略', '震荡策略'].includes(label)) {
      const rows = page.getByTestId('newow-product-chart-stage').locator('tr').filter({ has: page.locator('td:nth-child(3)') })
      await expect(rows).toHaveCount(3)
    }
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
  await page.getByRole('tab', { name: '牛哇参考', exact: true }).click()
  await expect(page.getByText('当前周期没有牛哇盘后结果，保留行情底图。', { exact: true })).toBeVisible()
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

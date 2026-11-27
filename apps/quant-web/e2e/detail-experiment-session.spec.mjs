import { expect, test } from '@playwright/test'
import { installNewowProductFixtures, newowRoute } from './newow-product.helpers.mjs'
import { installDetailExperimentSessionFixtures } from './fixtures/detail-experiment-session.mjs'

async function rememberCanvas(page) {
  const native = page.locator('.tv-lightweight-charts').first()
  await expect(native).toBeVisible()
  await native.evaluate(element => { window.__experimentSessionCanvas = element })
}
async function assertCanvasAndInteract(page, errors) {
  const native = page.locator('.tv-lightweight-charts').first()
  await expect(native).toBeVisible()
  await expect.poll(() => page.evaluate(() => document.querySelector('.tv-lightweight-charts') === window.__experimentSessionCanvas && window.__experimentSessionCanvas.isConnected)).toBe(true)
  await native.scrollIntoViewIfNeeded()
  const box = await native.boundingBox()
  expect(box).not.toBeNull()
  await page.mouse.move(box.x + box.width * .6, box.y + box.height * .35)
  await page.mouse.down(); await page.mouse.move(box.x + box.width * .6 - 45,box.y + box.height * .35,{steps:6}); await page.mouse.up()
  await page.mouse.wheel(0,-120)
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  expect(errors).toEqual([])
}
async function chooseTest(page,label) {
  await page.getByLabel('牛哇T策略',{exact:true}).click()
  await page.getByRole('button',{name:label,exact:true}).click()
}

test('repeated T experiment and ordinary switches keep the native canvas through Donchian and range interaction',async({page})=>{
  const errors=[]; page.on('pageerror',error=>errors.push(error.message))
  await installNewowProductFixtures(page)
  const fixture=await installDetailExperimentSessionFixtures(page)
  await page.goto(newowRoute('trend','1d'))
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state','ready')
  await rememberCanvas(page)
  for(const label of ['测试','测试2','测试3','测试4','测试']) {
    await chooseTest(page,label)
    await expect(page.locator('.experiment-panel [data-testid="experiment-summary"]')).toContainText('+1.00 百分点')
    const donchian=page.locator('.experiment-panel').getByRole('button',{name:'唐奇安通道',exact:true})
    await donchian.click(); await expect(donchian).toHaveAttribute('aria-pressed','true')
    await assertCanvasAndInteract(page,errors)
    await donchian.click(); await expect(donchian).toHaveAttribute('aria-pressed','false')
    await page.getByRole('tab',{name:'趋势策略',exact:true}).click()
    await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state','ready')
    await expect(page.locator('.experiment-panel')).toHaveCount(0)
    await assertCanvasAndInteract(page,errors)
    expect(new URL(page.url()).searchParams.get('frequency')).toBe('1d')
  }
  expect(fixture.experiments.map(item=>item.kind)).toEqual(expect.arrayContaining(['osc-test','osc-test2','osc-test3','osc-test4']))
  expect(errors).toEqual([])
})

test('experiment diagnostics report the painted source and isolate volume write failures', async ({ page }) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await installNewowProductFixtures(page)
  await installDetailExperimentSessionFixtures(page, { exactVolumeOwner: kind => kind === 'osc-test', positionedFacts: true,
    invalidIdentity: kind => kind === 'osc-test3' })
  await page.goto(newowRoute('trend', '1d'))
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready')
  await rememberCanvas(page)
  await chooseTest(page, '测试')
  const panel = page.locator('.experiment-panel')
  await expect(panel.getByTestId('experiment-summary')).toContainText('+1.00 百分点')
  const diagnostics = panel.locator('.experiment-chart-controls .chart-layer-diagnostics')
  await diagnostics.getByText('图层诊断', { exact: true }).click()
  const volume = diagnostics.getByText('generic_volume · 就绪', { exact: true })
  await volume.click()
  await expect(volume.locator('..')).toContainText('canonical:rb:RB2605:1d')
  const price = diagnostics.getByText('price · 就绪', { exact: true })
  await price.click()
  await expect(price.locator('..')).toContainText('b'.repeat(64))
  await expect(diagnostics.getByText('newow_oscillation · 就绪', { exact: true })).toBeVisible()
  await expect(diagnostics.getByText('newow_actions · 就绪', { exact: true })).toBeVisible()
  await expect(diagnostics.getByText('newow_display_events · 就绪', { exact: true })).toBeVisible()
  await expect(panel.locator('[data-action-id="experiment-build"]')).toBeVisible()
  const refresh = diagnostics.getByRole('button', { name: '刷新诊断' })
  const display = panel.locator('.newow-display-overlay')
  await expect(display.getByRole('button')).toHaveCount(1)
  await page.evaluate(() => {
    const readContext = HTMLCanvasElement.prototype.getContext
    window.__experimentDisplayFail = true
    HTMLCanvasElement.prototype.getContext = function (kind, ...args) {
      if (window.__experimentDisplayFail && kind === '2d' && this.matches('.experiment-panel .newow-display-overlay canvas')) return null
      return readContext.call(this, kind, ...args)
    }
    window.dispatchEvent(new Event('resize'))
  })
  const displayFailure = diagnostics.getByText('newow_display_events · 渲染错误', { exact: true })
  await expect.poll(async () => { await refresh.click(); return displayFailure.count() }).toBe(1)
  await expect(display.getByRole('button')).toHaveCount(0)
  await displayFailure.click()
  await expect(displayFailure.locator('..')).toContainText('CHART_RENDERER_PAINT_FAILED')
  await page.evaluate(() => { window.__experimentDisplayFail = false; window.dispatchEvent(new Event('resize')) })
  await expect.poll(async () => { await refresh.click(); return diagnostics.getByText('newow_display_events · 就绪', { exact: true }).count() }).toBe(1)
  const native = await (await page.waitForFunction(() => performance.getEntriesByType('resource')
    .find(entry => new URL(entry.name).pathname.endsWith('/lightweight-charts.js'))?.name)).jsonValue()
  await page.evaluate(async moduleUrl => {
    const { createChart, HistogramSeries } = await import(moduleUrl)
    const probe = createChart(document.createElement('div'))
    const prototype = Object.getPrototypeOf(probe.addSeries(HistogramSeries))
    probe.remove()
    const setData = prototype.setData
    const update = prototype.update
    window.__experimentVolumeFail = true
    for (const [name, write] of [['setData', setData], ['update', update]]) {
      prototype[name] = function (...args) {
        if (window.__experimentVolumeFail && this.options().priceScaleId === 'volume') throw Error('experiment volume write failure')
        return write.apply(this, args)
      }
    }
  }, native)
  await chooseTest(page, '测试2')
  await expect(panel.getByTestId('experiment-summary')).toContainText('+1.00 百分点')
  const failure = diagnostics.getByText('generic_volume · 渲染错误', { exact: true })
  await expect.poll(async () => { await refresh.click(); return failure.count() }).toBe(1)
  await failure.click()
  await expect(failure.locator('..')).toContainText('CHART_RENDERER_UPDATE_FAILED')
  await expect(failure.locator('..')).not.toContainText('canonical:rb:RB2605:1d')
  await expect(price).toBeVisible()
  await page.evaluate(() => { window.__experimentVolumeFail = false })
  await chooseTest(page, '测试')
  await expect(panel.getByTestId('experiment-summary')).toContainText('+1.00 百分点')
  await expect.poll(async () => { await refresh.click(); return volume.count() }).toBe(1)
  await chooseTest(page, '测试2')
  await expect(panel.getByTestId('experiment-summary')).toContainText('+1.00 百分点')
  await expect.poll(async () => { await refresh.click(); return diagnostics.getByText('generic_volume · 缺少输入', { exact: true }).count() }).toBe(1)
  await expect(diagnostics.getByText('newow_actions · 缺少输入', { exact: true })).toBeVisible()
  await expect(diagnostics.getByText('newow_display_events · 缺少输入', { exact: true })).toBeVisible()
  const main = panel.locator('.experiment-chart .tv-lightweight-charts')
  await expect(main).toHaveCount(1)
  expect(await main.evaluate(element => element === window.__experimentSessionCanvas)).toBe(true)
  await chooseTest(page, '测试3')
  await expect(panel.getByRole('alert').filter({ has: page.getByRole('button', { name: '重试', exact: true }) })).toBeVisible()
  const invalid = diagnostics.getByText('newow_oscillation · 来源无效', { exact: true })
  await expect.poll(async () => { await refresh.click(); return invalid.count() }).toBe(1)
  await invalid.click()
  await expect(invalid.locator('..')).toContainText('NEWOW_RESPONSE_INVALID')
  expect(errors).toEqual([])
})

test('Test5 reports and toggles the plotted breakout and wick as separate layers', async ({ page }) => {
  await installNewowProductFixtures(page)
  await installDetailExperimentSessionFixtures(page, { breakoutEvents: (bars, frequency) => {
    const version = 'newow_breakout_shapes_detail3449_v1'
    const event = (id, kind, side, occurrence, confirmation) => {
      const bar = confirmation ?? occurrence
      return { event_id: id, display_version: version, formula_version: version, product: 'rb', frequency,
        bar_end: bar.bar_end, known_at: bar.bar_end, occur_bar_end: occurrence.bar_end, confirmed_at: confirmation?.bar_end ?? null,
        physical_contract: bar.physical_contract, segment_id: bar.segment_id, calculation_segment_id: bar.calculation_segment_id,
        kind, side, level: '100', buffer: '2', threshold: '102', volume_ratio: null, volume_ok: true, doubt: false, regime: 'osc',
        occur_high: occurrence.high, occur_low: occurrence.low, confirm_close: confirmation?.close ?? null,
        bar_gap: confirmation ? 1 : null, source_sha256: 'a'.repeat(64), input_sha256: 'b'.repeat(64), executable: false }
    }
    return [event('tested-breakout', 'true_up', 'up', bars[9], bars[10]),
      event('tested-wick', 'wick_lower', 'down', bars[15], null)]
  } })
  await page.goto(newowRoute('oscillation', '1d', '&newow_test=osc-test5'))
  const panel = page.locator('.experiment-panel')
  const overlay = panel.locator('.breakout-overlay')
  await expect(panel.getByTestId('experiment-summary')).toBeVisible()
  const zoomOut = page.getByRole('button', { name: '缩小', exact: true })
  for (let step = 0; step < 14; step++) await zoomOut.click()
  await expect(overlay.getByRole('button').filter({ hasText: '真突破·转撑' })).toBeVisible()
  await expect(overlay.getByRole('button').filter({ hasText: '下影诱空' })).toBeVisible()
  const diagnostics = panel.locator('.experiment-chart-controls .chart-layer-diagnostics')
  await diagnostics.getByText('图层诊断', { exact: true }).click()
  const breakout = diagnostics.getByText('newow_breakouts · 就绪', { exact: true })
  await breakout.click()
  await expect(breakout.locator('..')).toContainText('newow_breakout_shapes_detail3449_v1')
  await expect(diagnostics.getByText('newow_wicks · 就绪', { exact: true })).toBeVisible()
  await panel.getByRole('button', { name: '影线提示', exact: true }).click()
  await expect(overlay.getByRole('button').filter({ hasText: '下影诱空' })).toHaveCount(0)
  await diagnostics.getByRole('button', { name: '刷新诊断' }).click()
  await expect(diagnostics.getByText('newow_wicks · 已隐藏', { exact: true })).toBeVisible()
  await expect(breakout).toBeVisible()
})

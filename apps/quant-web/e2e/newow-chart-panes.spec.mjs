import { expect, test } from '@playwright/test'
import { CHART_MANIFEST } from '@guiyi/quant-chart'
import { NEWOW_AS_OF, NEWOW_STRATEGIES, buildNewowSplitFixtureEnvelopeForTest, installNewowProductFixtures, newowRoute, productRequests, releaseDeferred, assertNoUnexpectedRequests } from './newow-product.helpers.mjs'

for (const strategy of NEWOW_STRATEGIES) for (const frequency of ['1d']) {
  test(`${strategy} ${frequency}: native panes, indicator replacement and action diagnostics`, async ({ page }) => {
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    const fixture = await installNewowProductFixtures(page)
    await page.goto(newowRoute(strategy, frequency))
    const stage = page.getByTestId('newow-product-chart-stage')
    await expect(stage).toHaveAttribute('data-auxiliary-component', 'zhaoyao_mirror')
    await expect(stage).toHaveAttribute('data-auxiliary-state', 'ready')
    // Main price/volume and auxiliary panes share one timeline; separator rows are excluded.
    await expect(stage.locator('tr').filter({ has: page.locator('td:nth-child(3)') })).toHaveCount(3)
    const nativeRows = stage.locator('tr').filter({ has: page.locator('td:nth-child(3)') })
    const paneHeights = await nativeRows.evaluateAll(rows => rows.slice(0, 2).map(row => row.getBoundingClientRect().height))
    expect(paneHeights[0]).toBeGreaterThanOrEqual(280)
    expect(paneHeights[1]).toBeGreaterThanOrEqual(112)
    await expect(stage).toHaveAttribute('data-volume-policy', 'newow')
    await expect(stage).toHaveAttribute('data-volume-bar-count', /^[1-9]\d*$/)
    await expect(stage.locator('.newow-product-chart-stage__volume-label')).toHaveCount(0)
    await expect.poll(async () => {
      const native = await nativeRows.nth(1).boundingBox()
      const controls = await stage.locator('.newow-product-chart-stage__auxiliary-toolbar').boundingBox()
      return Math.abs(native.y - controls.y)
    }).toBeLessThanOrEqual(4)
    expect(productRequests(fixture, 'auxiliary').map(item => item.url.searchParams.get('component'))).toEqual(['zhaoyao_mirror'])
    for (const [label, component] of [['主力照妖镜', 'zhaoyao_mirror'], ['涨跌动能', 'up_down_energy'], ['主力控盘', 'main_force_control'], ['趋势转折', 'trend_reversal']]) {
      const button = page.getByRole('button', { name: label, exact: true })
      await button.click()
      await expect(stage).toHaveAttribute('data-auxiliary-component', component)
      await expect(button).toHaveAttribute('aria-pressed', 'true')
      const count = productRequests(fixture, 'auxiliary').length
      await button.click()
      expect(productRequests(fixture, 'auxiliary')).toHaveLength(count)
      await expect(stage.locator('tr').filter({ has: page.locator('td:nth-child(3)') })).toHaveCount(3)
    }
    expect(productRequests(fixture, 'chart')).toHaveLength(1)
    expect(productRequests(fixture, 'explanation').filter(item => item.url.searchParams.get('decision_v2') === 'true')).toHaveLength(1)
    expect(productRequests(fixture, 'explanation').filter(item => !item.url.searchParams.has('decision_v2'))).toHaveLength(0)
    await stage.getByText('副图管理', { exact: true }).click()
    const diagnostics = stage.locator('.chart-layer-diagnostics')
    await diagnostics.getByText('图层诊断', { exact: true }).click()
    await expect(diagnostics.getByText('newow_actions · 就绪', { exact: true })).toBeVisible()
    const mainIndicator = { trend: 'newow_trend', oscillation: 'newow_oscillation', main_rise: 'newow_main_rise' }[strategy]
    await expect(diagnostics.getByText(`${mainIndicator} · 就绪`, { exact: true }).first()).toBeVisible()
    await expect(diagnostics.getByText('newow_volume · 就绪', { exact: true })).toBeVisible()
    await diagnostics.getByText('图层诊断', { exact: true }).click()

    await stage.getByRole('button', { name: '图表设置', exact: true }).click()
    const settings = page.getByRole('dialog', { name: '图表设置' })
    await settings.getByRole('checkbox', { name: '建仓 / 清仓' }).uncheck()
    await settings.getByRole('button', { name: '完成', exact: true }).click()
    await diagnostics.getByText('图层诊断', { exact: true }).click()
    await expect(diagnostics.getByText('newow_actions · 已隐藏', { exact: true })).toBeVisible()
    await expect(nativeRows).toHaveCount(3)
    expect(productRequests(fixture, 'chart')).toHaveLength(1)
    expect(errors).toEqual([])
    assertNoUnexpectedRequests(fixture)
  })
}

test('weekly deep link remains closed without requesting strategy data', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page)
  await page.goto(newowRoute('trend', '1w'))
  await expect(page.getByText('当前牛哇周期未开放', { exact: true })).toBeVisible()
  await expect(page.getByText(/1w 尚未开放/)).toBeVisible()
  expect(productRequests(fixture, 'chart')).toHaveLength(0)
  expect(productRequests(fixture, 'auxiliary')).toHaveLength(0)
  assertNoUnexpectedRequests(fixture)
})

test('Newow labels the price and volume actually painted before strategy verification', async ({ page }) => {
  const hash = 'f'.repeat(64)
  const fixture = await installNewowProductFixtures(page, { deferOnce: 'trend:1d:chart', genericBarSourceHash: hash })
  await page.goto(newowRoute('trend', '1d'))
  const stage = page.getByTestId('newow-product-chart-stage')
  await expect(stage).toHaveAttribute('data-kline-end', /2026-/)
  await expect(stage).toHaveAttribute('data-volume-bar-count', '2')
  const previewEnd = await stage.getAttribute('data-kline-end')
  await stage.getByText('副图管理', { exact: true }).click()
  const diagnostics = stage.locator('.chart-layer-diagnostics')
  await diagnostics.getByText('图层诊断', { exact: true }).click()
  const rows = diagnostics.locator('.chart-layer-diagnostics__row')
  const price = rows.filter({ has: page.getByText('price · 就绪', { exact: true }) })
  const volume = rows.filter({ has: page.getByText('newow_volume · 就绪', { exact: true }) })
  for (const row of [price, volume]) {
    await row.locator('summary').click()
    await expect(row).toContainText(hash)
    await expect(row).toContainText(previewEnd)
    await expect(row).toContainText('miss')
  }
  await expect(diagnostics.getByText('newow_actions · 就绪', { exact: true })).toHaveCount(0)
  await expect.poll(() => fixture.deferred.has('trend:1d:chart')).toBe(true)
  await releaseDeferred(fixture, 'trend:1d:chart')
  await expect(stage).toHaveAttribute('data-auxiliary-state', 'ready')
  await diagnostics.getByRole('button', { name: '刷新诊断', exact: true }).click()
  await expect(price).not.toContainText(hash)
  await expect(volume).not.toContainText(hash)
  await expect(diagnostics.getByText('newow_actions · 就绪', { exact: true })).toBeVisible()
  assertNoUnexpectedRequests(fixture)
})

test('the dual chart diagnostics keep trend and oscillation action sources separate', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { dualMarket: true })
  await page.goto(newowRoute('trend', '1d', '&newow_mode=dual'))
  const chart = page.getByTestId('newow-product-chart-stage')
  await expect(chart).toHaveAttribute('data-comparison-active', 'true')
  await chart.getByText('副图管理', { exact: true }).click()
  const diagnostics = chart.locator('.chart-layer-diagnostics')
  await diagnostics.getByText('图层诊断', { exact: true }).click()
  await expect(diagnostics.getByText('newow_actions · 就绪', { exact: true })).toHaveCount(2)
  await expect(diagnostics.getByText('newow_dual_background · 就绪', { exact: true })).toBeVisible()
  assertNoUnexpectedRequests(fixture)
})

test('Newow auxiliary readback stops at the last renderable point on selected and added panes', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { onProductRequest: async ({ route, url, section }) => {
    const component = url.searchParams.get('component')
    if (section !== 'auxiliary' || !['up_down_energy', 'main_force_control'].includes(component)) return
    const payload = buildNewowSplitFixtureEnvelopeForTest(url)
    const data = payload.auxiliary.value.segments[0].data
    if (component === 'up_down_energy') {
      data.var4[1] = null
      data.band_entry[0] = 80
    } else {
      data.status[0] = '有庄控盘'
      data.status[1] = 'fixture_missing_status'
    }
    await route.fulfill({ json: payload })
    return 'handled'
  } })
  await page.goto(newowRoute('trend', '1d'))
  const stage = page.getByTestId('newow-product-chart-stage')
  await expect(stage).toHaveAttribute('data-auxiliary-component', 'zhaoyao_mirror')
  const latest = await stage.getAttribute('data-kline-end')
  await expect(stage).toHaveAttribute('data-auxiliary-cutoff', latest)
  await stage.getByRole('button', { name: '涨跌动能', exact: true }).click()
  await expect(stage).toHaveAttribute('data-auxiliary-component', 'up_down_energy')
  const earlier = await stage.getAttribute('data-auxiliary-cutoff')
  expect(Date.parse(earlier)).toBeLessThan(Date.parse(latest))
  await stage.getByText('副图管理', { exact: true }).click()
  await stage.getByRole('combobox', { name: '选择附加副图' }).selectOption('main_force_control')
  await stage.getByRole('button', { name: '添加', exact: true }).click()
  await expect(stage.locator('[data-auxiliary-pane="main_force_control"]')).toHaveAttribute('data-auxiliary-formula', 'newow_main_force_control_page_v1')
  const diagnostics = stage.locator('.chart-layer-diagnostics')
  await diagnostics.getByText('图层诊断', { exact: true }).click()
  for (const component of ['up_down_energy', 'main_force_control']) {
    const row = diagnostics.locator('.chart-layer-diagnostics__row').filter({ hasText: `newow.${component} · 缺少输入` })
    await row.locator('summary').click()
    await expect(row).toContainText(earlier)
    await expect(row).not.toContainText(latest)
  }
  assertNoUnexpectedRequests(fixture)
})

test('a later native canvas frame reports a failed trend band and the chart can retry it', async ({ page }) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => {
    const state = window.guiyiBandPaintProbe = { arm: false, failed: 0, healthy: 0 }
    const fillRect = CanvasRenderingContext2D.prototype.fillRect
    CanvasRenderingContext2D.prototype.fillRect = function (...args) {
      if (['rgba(245,183,38,0.35)', 'rgba(54,90,245,0.35)'].includes(String(this.fillStyle).replaceAll(' ', ''))) {
        if (state.arm) {
          state.arm = false
          state.failed++
          throw new Error('injected later trend band paint')
        }
        state.healthy++
      }
      return fillRect.apply(this, args)
    }
  })
  const fixture = await installNewowProductFixtures(page)
  await page.goto(newowRoute('trend', '1d'))
  const chart = page.getByTestId('newow-product-chart-stage')
  await expect(chart).toHaveAttribute('data-auxiliary-state', 'ready')
  await expect.poll(() => page.evaluate(() => window.guiyiBandPaintProbe.healthy)).toBeGreaterThan(0)
  await page.evaluate(() => { window.guiyiBandPaintProbe.arm = true })
  await page.setViewportSize({ width: 1410, height: 900 })
  await expect.poll(() => page.evaluate(() => window.guiyiBandPaintProbe.failed)).toBe(1)
  await chart.getByText('副图管理', { exact: true }).click()
  const diagnostics = chart.locator('.chart-layer-diagnostics')
  await diagnostics.getByText('图层诊断', { exact: true }).click()
  const failedRow = diagnostics.locator('.chart-layer-diagnostics__row').filter({ hasText: /^newow_trend · 渲染错误/ })
  await failedRow.locator('summary').click()
  await expect(failedRow.getByText('CHART_RENDERER_PAINT_FAILED', { exact: true })).toBeVisible()
  await expect(failedRow.locator('time')).toHaveText(NEWOW_AS_OF)
  await expect(diagnostics.getByText('price · 就绪', { exact: true })).toBeVisible()
  const before = await page.evaluate(() => window.guiyiBandPaintProbe.healthy)
  await chart.getByRole('button', { name: '图表设置', exact: true }).click()
  const settings = page.getByRole('dialog', { name: '图表设置' })
  const structure = settings.getByRole('checkbox', { name: '策略线 / 趋势带', exact: true })
  await structure.uncheck()
  await structure.check()
  await settings.getByRole('button', { name: '完成', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.guiyiBandPaintProbe.healthy)).toBeGreaterThan(before)
  await diagnostics.getByRole('button', { name: '刷新诊断' }).click()
  await expect(diagnostics.getByText('newow_trend · 渲染错误', { exact: true })).toHaveCount(0)
  expect(errors).toEqual([])
  assertNoUnexpectedRequests(fixture)
})

test('explicit additional panes share the primary candle timeline and release their native resources', async ({ page }) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const fixture = await installNewowProductFixtures(page, { onProductRequest: async ({ route, url, section }) => {
    const component = url.searchParams.get('component')
    if (section !== 'auxiliary' || !['main_force_control', 'macd'].includes(component)) return
    const payload = buildNewowSplitFixtureEnvelopeForTest(url)
    const value = payload.auxiliary.value
    const newest = value.segments[0]
    if (component === 'main_force_control') {
      newest.data.status = ['有庄控盘', '有庄控盘']
      newest.data.current_status = '有庄控盘'
    } else {
      const barEnd = new Date(Date.parse(newest.bar_ends[0]) - 86_400_000).toISOString()
      const status = { ...newest.status, status: 'unavailable', reason_code: 'NEWOW_MACD_UNAVAILABLE' }
      const point = { bar_end: barEnd, value: null, ready: false, valid: false, reason: 'NEWOW_MACD_UNAVAILABLE' }
      value.segments.unshift({ physical_contract: newest.physical_contract, segment_id: 'fixture-earlier-macd-owner',
        bar_ends: [barEnd], status, data: { dif: [point], dea: [point], histogram: [point] } })
      payload.auxiliary.status = status
    }
    await route.fulfill({ json: payload })
    return 'handled'
  } })
  await page.goto(newowRoute('trend', '1d'))
  const stage = page.getByTestId('newow-product-chart-stage')
  const nativeRows = stage.locator('tr').filter({ has: page.locator('td:nth-child(3)') })
  await expect(stage).toHaveAttribute('data-auxiliary-component', 'zhaoyao_mirror')
  await expect(nativeRows).toHaveCount(3)
  await expect(stage).toHaveAttribute('data-volume-policy', 'newow')
  await expect(stage).toHaveAttribute('data-volume-bar-count', /^[1-9]\d*$/)
  await stage.getByText('副图管理', { exact: true }).click()
  const selector = stage.getByRole('combobox', { name: '选择附加副图' })
  await selector.selectOption('up_down_energy')
  await stage.getByRole('button', { name: '添加', exact: true }).click()
  const energy = stage.locator('[data-auxiliary-pane="up_down_energy"]')
  await expect(energy).toHaveAttribute('data-auxiliary-status', 'ready')
  await expect(nativeRows).toHaveCount(4)
  await expect(stage).toHaveAttribute('data-auxiliary-component', 'zhaoyao_mirror')
  await expect(stage).toHaveAttribute('data-chart-package', CHART_MANIFEST.version)
  await selector.selectOption('main_force_control')
  await stage.getByRole('button', { name: '添加', exact: true }).click()
  await expect(stage.locator('[data-auxiliary-pane="main_force_control"]')).toHaveAttribute('data-auxiliary-status', 'ready')
  await expect(nativeRows).toHaveCount(5)
  await expect(selector).toHaveCount(0)
  const requests = productRequests(fixture, 'auxiliary').length
  await stage.getByRole('combobox', { name: '涨跌动能副图高度' }).selectOption('160')
  expect(productRequests(fixture, 'auxiliary')).toHaveLength(requests)
  await stage.getByRole('button', { name: '隐藏涨跌动能副图' }).click()
  await expect(nativeRows).toHaveCount(4)
  await expect(energy).toHaveCount(0)
  await expect(stage.getByRole('button', { name: '显示涨跌动能副图' })).toBeVisible()
  await stage.getByRole('button', { name: '显示涨跌动能副图' }).click()
  await expect(energy).toHaveAttribute('data-auxiliary-status', 'ready')
  await expect(nativeRows).toHaveCount(5)
  const control = stage.locator('[data-auxiliary-pane="main_force_control"]')
  await expect.poll(async () => (await energy.boundingBox()).y < (await control.boundingBox()).y).toBe(true)
  await stage.getByRole('button', { name: '移除涨跌动能副图' }).click()
  await expect(nativeRows).toHaveCount(4)
  await stage.getByRole('button', { name: '恢复默认' }).click()
  await expect(nativeRows).toHaveCount(3)
  await expect(stage).toHaveAttribute('data-auxiliary-component', 'zhaoyao_mirror')
  await selector.selectOption('macd')
  await stage.getByRole('button', { name: '添加', exact: true }).click()
  const macd = stage.locator('[data-auxiliary-pane="macd"]')
  await expect(macd).toHaveAttribute('data-auxiliary-status', 'ready')
  await expect(macd).toHaveAttribute('data-auxiliary-formula', 'talib_macd_12_26_9_v1')
  await expect(nativeRows).toHaveCount(4)
  await stage.getByRole('button', { name: '移除MACD副图' }).click()
  await expect(nativeRows).toHaveCount(3)
  await stage.getByText('副图管理', { exact: true }).click()
  for (const [label, component] of [['涨跌动能', 'up_down_energy'], ['主力控盘', 'main_force_control'], ['趋势转折', 'trend_reversal'], ['主力照妖镜', 'zhaoyao_mirror']]) {
    await stage.getByRole('button', { name: label, exact: true }).click()
    await expect(stage).toHaveAttribute('data-auxiliary-component', component)
    await expect(nativeRows).toHaveCount(3)
  }
  expect(productRequests(fixture, 'chart')).toHaveLength(1)
  expect(errors).toEqual([])
  assertNoUnexpectedRequests(fixture)
})

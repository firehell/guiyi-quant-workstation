import { expect, test } from '@playwright/test'
import { performance } from 'node:perf_hooks'
import os from 'node:os'

import {
  NEWOW_AS_OF,
  NEWOW_STRATEGIES,
  assertNoUnexpectedRequests,
  buildNewowFixtureEnvelopeForTest,
  installNewowProductFixtures,
  newowRoute,
  productRequests,
  releaseDeferred,
  unavailable,
  validateNewowFixtureEnvelopeForTest,
  warming,
} from './newow-product.helpers.mjs'

const lineByStrategy = {
  trend: 'B',
  oscillation: 'HHV',
  main_rise: 'MA35',
}

async function showReference(page) {
  if (await page.getByRole('dialog').isVisible()) await page.keyboard.press('Escape')
  await page.locator('.newow-reference').scrollIntoViewIfNeeded()
}

async function resetPageScroll(page) {
  await page.evaluate(() => {
    window.scrollTo(0, 0)
    for (const element of document.querySelectorAll('*')) {
      if (['auto', 'scroll'].includes(getComputedStyle(element).overflowY)) element.scrollTop = 0
    }
  })
}

function expectExactQuery(request, expected) {
  expect(Object.fromEntries([...request.url.searchParams.entries()].sort())).toEqual(Object.fromEntries(Object.entries(expected).sort()))
}

async function selectLatestAction(page, expectedSignalId) {
  const trigger = page.locator('.newow-summary__facts').getByRole('button')
  await expect(trigger).toHaveCount(1)
  await trigger.click()
  await expect(page.getByTestId('newow-product-chart-stage')).toHaveAttribute('data-selected-signal-id', expectedSignalId)
  await expect(page.getByRole('dialog')).toBeVisible()
}

test('main-rise initial clear stays action-only and explains that no entry exists', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { initialClear: true })
  await page.goto(newowRoute('main_rise', '1d'))

  await selectLatestAction(page, 'main_rise-1d-initial-clear-no-entry')
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('历史主动作 清仓（无入场）')
  await expect(page.locator('.newow-summary__facts')).toContainText('清仓（无入场）')
  await expect(dialog).toContainText('初始无入场：未观察到可配对 BUILD，不生成参考交易。')

  await showReference(page)
  await expect(page.getByTestId('newow-reference-summary')).toContainText('暂无已完成参考交易')
  await expect(page.locator('article[data-reference-category]')).toHaveCount(0)
  assertNoUnexpectedRequests(fixture)
})

for (const strategy of NEWOW_STRATEGIES) {
  for (const frequency of ['1d']) {
    test(`${strategy} × ${frequency} owns an independent chart and reference lifecycle`, async ({ page }) => {
      expect(page.viewportSize()).toEqual({ width: 1440, height: 900 })
      const fixture = await installNewowProductFixtures(page)
      await page.goto(newowRoute(strategy, frequency))

      const workspace = page.locator('[data-detail-workspace="newow"]')
      const chart = page.getByTestId('newow-product-chart-stage')
      await expect(workspace).toHaveAttribute('data-strategy', strategy)
      await expect(workspace).toHaveAttribute('data-frequency', frequency)
      await expect(workspace).toHaveAttribute('data-chart-state', 'ready')
      await expect(chart).toHaveAttribute('data-strategy', strategy)
      await expect(chart).toHaveAttribute('data-frequency', frequency)
      await expect(chart.getByText(lineByStrategy[strategy], { exact: true }).first()).toBeVisible()
      const clearId = strategy === 'oscillation' ? `${strategy}-${frequency}-clear-same` : `${strategy}-${frequency}-clear`
      await expect(chart).toHaveAttribute('data-action-ids', `${strategy}-${frequency}-build-closed,${clearId},${strategy}-${frequency}-build-open`)
      expectExactQuery(productRequests(fixture, 'chart')[0], { product: 'rb', strategy, frequency, series_kind: 'actual_dominant', section: 'chart', as_of: NEWOW_AS_OF })
      await expect.poll(() => productRequests(fixture, 'reference').filter(item => !item.url.searchParams.has('history_limit')).length).toBe(1)

      await showReference(page)
      await expect(page.getByTestId('newow-reference-summary')).toContainText('100')
      expectExactQuery(productRequests(fixture, 'reference')[0], { product: 'rb', strategy, frequency, series_kind: 'actual_dominant', section: 'reference', as_of: NEWOW_AS_OF, snapshot_token: `snapshot:${strategy}:${frequency}:fixture-revision-1` })
      await expect.poll(() => productRequests(fixture, 'reference').filter(item => item.url.searchParams.get('history_limit') === '200').length).toBe(1)
      const records = productRequests(fixture, 'reference').find(item => item.url.searchParams.get('history_limit') === '200')
      expectExactQuery(records, { product: 'rb', strategy, frequency, series_kind: 'actual_dominant', section: 'reference', as_of: NEWOW_AS_OF, performance_since: '2026-06-03', performance_through: '2026-09-03', history_limit: '200', snapshot_token: `snapshot:${strategy}:${frequency}:fixture-revision-1` })
      const summaryBefore = await page.getByTestId('newow-reference-summary').innerText()
      await page.getByTestId('newow-load-earlier').click()
      await expect.poll(() => productRequests(fixture, 'chart').length).toBe(2)
      expect(await page.getByTestId('newow-reference-summary').innerText()).toBe(summaryBefore)
      const older = productRequests(fixture, 'chart').at(-1).url.searchParams
      expect(older.get('chart_before')).toBe('chart-page-2')
      expect(older.has('performance_since')).toBe(false)
      expect(older.has('history_before')).toBe(false)
      assertNoUnexpectedRequests(fixture)
    })
  }
}

test('chart failure stays local while other views and the real Decimal quote wire remain available', async ({ browser }) => {
  for (const strategy of NEWOW_STRATEGIES) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
    const page = await context.newPage()
    const fixture = await installNewowProductFixtures(page, { onProductRequest: async ({ route, section }) => {
      if (section !== 'chart') return
      await route.fulfill({ status: 500, json: { detail: { code: 'NEWOW_INTERNAL_ERROR' } } })
      return 'handled'
    } })
    await page.goto(newowRoute(strategy, '1d'))
    await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'unavailable')
    await expect(page.locator('.quote-header__price strong')).toHaveText('106.3')
    await expect(page.locator('.detail-unavailable')).toContainText('NEWOW_API_UNAVAILABLE')
    await expect(page.getByRole('tab', { name: '趋势策略', exact: true })).toBeVisible()
    await expect(page.getByRole('tab', { name: '自由看盘', exact: true })).toBeVisible()
    assertNoUnexpectedRequests(fixture)
    await context.close()
  }
})

test('chart error recovery retries the same as_of while the reference error remains local', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, {
    busy: 'trend:1d:reference',
    genericSeries: 'failed-once',
    onProductRequest: async ({ route, section, count }) => {
      if (section !== 'chart' || count !== 1) return
      await route.fulfill({ status: 500, json: { detail: { code: 'NEWOW_INTERNAL_ERROR' } } })
      return 'handled'
    },
  })
  await page.goto(newowRoute())
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'unavailable')
  await expect(page.locator('.quote-header__price strong')).toHaveText('—')
  await page.getByRole('button', { name: '刷新当前', exact: true }).click()
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready')
  expect(productRequests(fixture, 'chart')).toHaveLength(2)
  expect(productRequests(fixture, 'chart').map(item => item.url.searchParams.get('as_of'))).toEqual([NEWOW_AS_OF, NEWOW_AS_OF])

  await showReference(page)
  await expect(page.locator('.newow-reference')).toContainText('NEWOW_RESOURCE_BUSY')
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready')
  // Refresh-current is an error recovery control, not a permanent ready-page action.
  await expect(page.getByRole('button', { name: '刷新当前', exact: true })).toHaveCount(0)
  await expect(page.locator('.quote-header__price strong')).toHaveText('106.3')
  expect(productRequests(fixture, 'chart')).toHaveLength(2)
  expect(fixture.requests.filter(item => item.url.pathname === '/api/v1/market/bars/page')).toHaveLength(2)
  expect(productRequests(fixture, 'reference').filter(item => !item.url.searchParams.has('history_limit'))).toHaveLength(1)
  expect(productRequests(fixture, 'chart').at(-1).url.searchParams.get('as_of')).toBe(NEWOW_AS_OF)
  assertNoUnexpectedRequests(fixture)
})

test('dense same-Bar hints use the disclosure and exact historical facts while the latest action remains accessible through its summary', async ({ page }) => {
  await page.addInitScript(() => {
    window.__newowPaintedMarkerText = []
    const fillText = CanvasRenderingContext2D.prototype.fillText
    CanvasRenderingContext2D.prototype.fillText = function (text, ...args) {
      if (this.canvas.closest('.newow-product-chart-stage') && /^(D[1-6]|建仓|清仓)(?: .+)?$/.test(text)) window.__newowPaintedMarkerText.push(text)
      return fillText.call(this, text, ...args)
    }
  })
  const payload = buildNewowFixtureEnvelopeForTest('chart', 'oscillation', '1d')
  const value = payload.chart.value
  const owner = value.bars.at(-1)
  value.hints = Array.from({ length: 24 }, (_, index) => ({
    ...value.hints[0], hint_id: `dense-hint-${index}`, kind: `D${index % 6 + 1}`,
    bar_end: owner.bar_end, known_at: NEWOW_AS_OF, sequence: index + 2,
    anchor_price: index === 23 ? '104.123400' : '104.5000',
  }))
  for (const frame of value.frames) frame.hint_ids = frame.bar_end === owner.bar_end ? value.hints.map(hint => hint.hint_id) : []
  validateNewowFixtureEnvelopeForTest(payload, 'chart', 'oscillation', '1d')
  const fixture = await installNewowProductFixtures(page, { onProductRequest: async ({ route, section }) => {
    if (section !== 'chart') return
    await route.fulfill({ json: payload })
    return 'handled'
  } })
  await page.goto(newowRoute('oscillation', '1d'))
  const chart = page.getByTestId('newow-product-chart-stage')
  await expect(chart).toHaveAttribute('data-auxiliary-state', 'ready')
  await expect(chart.locator('[data-action-id="oscillation-1d-build-open"]')).toHaveAttribute('data-reference-price', '104.3000')
  expect(await page.evaluate(() => window.__newowPaintedMarkerText.filter(text => /^D[1-6]$/.test(text)))).toEqual([])
  const entries = chart.locator('[data-hint-id]')
  await expect(entries).toHaveCount(24)
  await expect(entries.first()).not.toBeVisible()
  await chart.locator('.newow-product-chart-stage__legend summary').filter({ hasText: /^过程提示$/ }).click()
  const selected = chart.locator('[data-hint-id="dense-hint-23"]')
  await selected.click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('历史过程提示')
  await expect(dialog).toContainText('D6 低位修复提示 · 104.1234')
  await dialog.getByText('来源与原始事实', { exact: true }).click()
  await expect(dialog).toContainText(`dense-hint-23 · ${owner.bar_end}`)
  await expect(dialog).toContainText(`known_at ${NEWOW_AS_OF} · sequence 25`)
  await expect(dialog).toContainText(`owner ${owner.physical_contract} · ${owner.segment_id}`)
  await expect(dialog).not.toContainText('dense-hint-17')
  await expect(dialog).not.toContainText('当前综合解释')
  expect(productRequests(fixture, 'explanation')).toHaveLength(0)
  await page.keyboard.press('Escape')
  await expect(selected).toBeFocused()
  await chart.locator('.newow-product-chart-stage__legend summary').filter({ hasText: /^过程提示$/ }).click()
  await expect(chart.locator('[data-action-id="oscillation-1d-clear-same"]')).toHaveAttribute('data-reference-price', '109.5163')
  await selectLatestAction(page, 'oscillation-1d-build-open')
  await expect(dialog).toContainText('历史主动作 参考建仓')
  await expect(dialog).toContainText('104.3')
  expect(productRequests(fixture, 'explanation')).toHaveLength(0)
  assertNoUnexpectedRequests(fixture)
})

test('same-Bar CLEAR then BUILD identities and prices remain separate and latest BUILD is selectable', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page)
  await page.goto(newowRoute('oscillation', '1d'))
  const chart = page.getByTestId('newow-product-chart-stage')
  await expect(chart).toHaveAttribute('data-action-ids', /oscillation-1d-clear-same,oscillation-1d-build-open/)
  const clear = chart.locator('[data-action-id="oscillation-1d-clear-same"]')
  const build = chart.locator('[data-action-id="oscillation-1d-build-open"]')
  await expect(clear).toHaveAttribute('data-reference-price', '109.5163')
  await expect(build).toHaveAttribute('data-reference-price', '104.3000')
  expect(await clear.getAttribute('data-reference-time')).toBe(await build.getAttribute('data-reference-time'))
  await selectLatestAction(page, 'oscillation-1d-build-open')
  await expect(page.getByRole('dialog')).toContainText('历史主动作 参考建仓')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).not.toBeVisible()
  await page.mouse.move(0, 0)
  await expect(page).toHaveScreenshot('newow-oscillation-same-bar.png', { animations: 'disabled', caret: 'hide', maxDiffPixels: 500 })
  assertNoUnexpectedRequests(fixture)
})

test('cup dialog renders the accepted cup response and restores the prior auxiliary pane', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page)
  await page.goto(newowRoute())
  await expect(page.getByTestId('newow-product-chart-stage')).toHaveAttribute('data-auxiliary-state', 'ready')
  await page.getByRole('button', { name: '杯柄说明', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('归一杯柄候选')
  await expect(dialog).toContainText('fixture-cup-1')
  await expect(dialog).toContainText('fixture-cup-2')
  expect(productRequests(fixture, 'auxiliary').map(item => item.url.searchParams.get('component'))).toContain('cup_handle')
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
  await expect(page.getByTestId('newow-product-chart-stage')).toHaveAttribute('data-auxiliary-state', 'ready')
  assertNoUnexpectedRequests(fixture)
})

test('main-rise chart has a stable representative viewport', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page)
  await page.goto(newowRoute('main_rise', '1d'))
  await expect(page.getByTestId('newow-product-chart-stage')).toHaveAttribute('data-strategy', 'main_rise')
  await expect(page.getByTestId('newow-product-chart-stage')).toHaveAttribute('data-auxiliary-state', 'ready')
  await page.mouse.move(0, 0)
  await page.getByTestId('newow-product-chart-stage').evaluate((element) => element.scrollIntoView({ block: 'center' }))
  await expect(page).toHaveScreenshot('newow-main-rise-chart.png', { animations: 'disabled', caret: 'hide', maxDiffPixels: 500 })
  assertNoUnexpectedRequests(fixture)
})

test('fixture rejects extra parameters, wrong fixed tokens and inconsistent ReferenceTrade facts', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { noAction: true })
  await page.goto(newowRoute())
  await expect(page.getByTestId('newow-product-chart-stage')).toHaveAttribute('data-action-ids', '')
  await page.evaluate(async () => { try { await fetch('/api/v1/market/newow/strategy-detail?product=rb&strategy=trend&frequency=1d&series_kind=actual_dominant&section=chart&as_of=2026-09-03T08%3A00%3A00.000Z&rogue=1') } catch {} })
  await page.evaluate(async () => { try { await fetch('/api/v1/market/newow/strategy-detail?product=rb&strategy=trend&frequency=1d&series_kind=actual_dominant&section=reference&as_of=2026-09-03T08%3A00%3A00.000Z&snapshot_token=wrong-generation') } catch {} })
  expect(fixture.unexpected).toEqual([expect.stringContaining('unexpected Newow query'), expect.stringContaining('invalid snapshot token')])

  const invalid = structuredClone(buildNewowFixtureEnvelopeForTest('reference', 'trend', '1d'))
  invalid.reference.value.items[0].entry_reference_price = '999.0000'
  expect(() => validateNewowFixtureEnvelopeForTest(invalid, 'reference', 'trend', '1d')).toThrow(/ReferenceTrade\/Action relation drift/)
  for (const locateFrom of ['2025-12-15', '2025-12-31', '2026-01-05', '2026-01-06', '2026-09-03']) {
    const located = buildNewowFixtureEnvelopeForTest('chart', 'trend', '1d', false, locateFrom)
    expect(located.chart.value.chart_from).toBe(locateFrom)
    expect(located.chart.value.chart_through).toBe(locateFrom)
  }
})

test('fixture validator rejects main-line semantic and OHLC contradictions', () => {
  const semantic = structuredClone(buildNewowFixtureEnvelopeForTest('chart', 'main_rise', '1d'))
  const action = semantic.chart.value.actions[0]
  const frame = semantic.chart.value.frames.find((item) => item.bar_end === action.bar_end)
  frame.main_values.ma45 = '999.0000'
  expect(() => validateNewowFixtureEnvelopeForTest(semantic, 'chart', 'main_rise', '1d')).toThrow(/main-line semantic/)

  const ohlc = structuredClone(buildNewowFixtureEnvelopeForTest('chart', 'trend', '1d'))
  ohlc.chart.value.bars[0].low = '999.0000'
  expect(() => validateNewowFixtureEnvelopeForTest(ohlc, 'chart', 'trend', '1d')).toThrow(/OHLC/)
})

test('fixture validator rejects a Reference mark that differs from its completed Bar Close', () => {
  const reference = buildNewowFixtureEnvelopeForTest('reference', 'trend', '1d')
  const markChart = structuredClone(buildNewowFixtureEnvelopeForTest('chart', 'trend', '1d', false, '2026-09-03'))
  markChart.chart.value.bars[0].close = '999.0000'
  expect(() => validateNewowFixtureEnvelopeForTest(reference, 'reference', 'trend', '1d', false, null, { charts: [markChart] })).toThrow(/mark\/Close/)
})

test('fixture validator rejects Bar ownership outside its physical segment window', () => {
  const chart = structuredClone(buildNewowFixtureEnvelopeForTest('chart', 'trend', '1d'))
  chart.chart.value.bars[0].segment_id = 'rb:RB9999:2099-01-01T00:00:00+00:00'
  expect(() => validateNewowFixtureEnvelopeForTest(chart, 'chart', 'trend', '1d')).toThrow(/segment window/)
})

test('strategy controls clear prior selection while hourly stays deferred', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page)
  await page.goto(newowRoute())
  await showReference(page)
  await selectLatestAction(page, 'trend-1d-build-open')
  await page.keyboard.press('Escape')
  const chart = page.getByTestId('newow-product-chart-stage')
  await expect(chart).toHaveAttribute('data-selected-signal-id', 'trend-1d-build-open')
  await expect(chart).toHaveAttribute('data-channel-point-count', '24')
  await page.getByRole('tab', { name: '震荡策略', exact: true }).click()
  await expect(chart).toHaveAttribute('data-strategy', 'oscillation')
  await expect(chart).toHaveAttribute('data-channel-point-count', '24')
  await expect(chart).toHaveAttribute('data-selected-signal-id', '')
  await expect(page.getByRole('button', { name: '1d', exact: true })).toHaveCount(1)
  await expect(page.getByRole('button', { name: '60m', exact: true })).toHaveCount(0)
  await expect.poll(() => productRequests(fixture, 'chart').at(-1)?.url.searchParams.get('strategy')).toBe('oscillation')
  expectExactQuery(productRequests(fixture, 'chart').at(-1), { product: 'rb', strategy: 'oscillation', frequency: '1d', series_kind: 'actual_dominant', section: 'chart', as_of: NEWOW_AS_OF })
  assertNoUnexpectedRequests(fixture)
})

test('six flat choices reuse the chart host, show independent dual tracks and clear them on exit', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { dualMarket: true, onProductRequest: async ({ route, url }) => {
    if (url.searchParams.get('include_fusion') !== 'true') return
    await route.fulfill({ status: 503, json: { detail: { code: 'NEWOW_RESOURCE_BUSY' } } })
    return 'handled'
  } })
  await page.goto(newowRoute('trend', '1d'))
  const tabs = page.getByRole('tablist', { name: '分析选项' }).getByRole('tab')
  await expect(tabs).toHaveCount(6)
  const chart = page.getByTestId('newow-product-chart-stage')
  await expect(chart).toHaveAttribute('data-band-area-count', '24')
  await expect(chart).toHaveAttribute('data-channel-point-count', '24')
  await chart.evaluate(element => { element.dataset.hostSentinel = 'same-host' })
  const quote = await page.locator('.quote-header__price strong').innerText()

  await page.getByRole('tab', { name: '震荡策略', exact: true }).click()
  await expect(chart).toHaveAttribute('data-strategy', 'oscillation')
  await expect(chart).toHaveAttribute('data-host-sentinel', 'same-host')
  await expect(chart).toHaveAttribute('data-band-area-count', '0')
  await expect(chart).toHaveAttribute('data-channel-point-count', '24')
  await expect(page.locator('.quote-header__price strong')).toHaveText(quote)

  await page.getByRole('tab', { name: '双策略', exact: true }).click()
  await expect(chart).toHaveAttribute('data-strategy', 'trend')
  await expect(chart).toHaveAttribute('data-host-sentinel', 'same-host')
  await expect(chart).toHaveAttribute('data-comparison-active', 'true')
  for (const origin of ['trend', 'oscillation']) {
    await expect(chart.locator(`[data-origin-strategy="${origin}"]`).first()).toBeVisible()
  }
  await page.locator('.fusion-panel').scrollIntoViewIfNeeded()
  await expect(page.locator('.fusion-panel [role="alert"]')).toHaveText('融合参考读取失败，请重试。')
  expect(productRequests(fixture, 'reference').filter(item => item.url.searchParams.get('include_fusion') === 'true')).toHaveLength(1)
  expect(productRequests(fixture, 'chart').some(item => item.strategy === 'main_rise')).toBe(false)

  await page.getByRole('tab', { name: '趋势策略', exact: true }).click()
  await expect(chart).toHaveAttribute('data-host-sentinel', 'same-host')
  await expect(chart).toHaveAttribute('data-comparison-active', 'false')
  await expect(chart.locator('[data-origin-strategy]')).toHaveCount(0)
  await expect(page.locator('.fusion-panel')).toHaveCount(0)
  await expect(page.locator('.quote-header__price strong')).toHaveText(quote)
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(tabs).toHaveCount(6)
  expect(await page.getByRole('tablist', { name: '分析选项' }).evaluate(element => element.scrollWidth > element.clientWidth)).toBe(true)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  assertNoUnexpectedRequests(fixture)
})

test('reference pagination exposes OPEN, CLOSED, interrupted and negative rows within the fixed records window without inventing zero metrics', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { recordsHistory: true })
  await page.goto(newowRoute())
  await showReference(page)
  await expect(page.locator('article[data-reference-category="open"]')).toBeVisible()
  await expect(page.locator('article[data-reference-category="closed"]')).toBeVisible()
  await page.getByRole('button', { name: '加载更多参考历史' }).click()
  await expect(page.locator('article[data-reference-category="interrupted"]')).toBeVisible()
  await expect(page.locator('article[data-reference-category="interrupted"] .newow-reference__record-return')).toContainText('-10%')
  await expect(page.locator('article[data-reference-initial="true"]')).toHaveCount(0)
  const openRow = page.locator('article[data-reference-category="open"]')
  await expect(openRow.locator('header')).toContainText('2026-08-03 → 至估值日')
  await expect(openRow).toContainText(/建仓\s*买入\s*106/)
  await expect(openRow).toContainText('104.675')
  const closedRow = page.locator('#reference-trade-trend-1d-closed')
  await expect(closedRow).toContainText(/建仓\s*买入\s*104/)
  await expect(closedRow).toContainText(/清仓\s*卖出\s*109\.3061/)
  const interruptedRow = page.locator('article[data-reference-category="interrupted"]')
  await expect(interruptedRow).toContainText(/建仓\s*买入\s*88/)
  await expect(interruptedRow).toContainText('79.2')
  await expect(interruptedRow).toContainText('中断浮动不计入已完成收益')
  const summaryBeforeViewport = await page.getByTestId('newow-reference-summary').innerText()
  const stage = page.getByTestId('newow-product-chart-stage')
  const pricePane = stage.locator('tr').filter({ has: page.locator('td:nth-child(3)') }).first().locator('td').nth(1)
  await pricePane.evaluate(element => element.addEventListener('mousedown', () => { element.dataset.dragStarted = 'true' }, { once: true }))
  await expect(stage.getByRole('button', { name: '回到最新', exact: true })).toHaveCount(0)
  const referenceScrollY = await page.evaluate(() => window.scrollY)
  await pricePane.scrollIntoViewIfNeeded()
  const paneBox = await pricePane.boundingBox()
  if (paneBox === null) throw new Error('price pane has no bounding box')
  const dragY = paneBox.y + paneBox.height * 0.5
  const dragFromX = paneBox.x + paneBox.width * 0.4
  const dragToX = paneBox.x + paneBox.width * 0.7
  expect(dragY).toBeGreaterThan(0)
  expect(dragY).toBeLessThan(page.viewportSize().height)
  expect(dragFromX).toBeGreaterThan(0)
  expect(dragToX).toBeLessThan(page.viewportSize().width)
  await page.mouse.move(dragFromX, dragY)
  await page.mouse.down()
  await page.mouse.move(dragToX, dragY, { steps: 5 })
  await page.mouse.up()
  await expect(pricePane).toHaveAttribute('data-drag-started', 'true')
  // This control appears only after the native visible-range callback leaves the latest bars.
  await expect(stage.getByRole('button', { name: '回到最新', exact: true })).toBeVisible()
  expect(await page.getByTestId('newow-reference-summary').innerText()).toBe(summaryBeforeViewport)
  await page.evaluate(scrollY => window.scrollTo(0, scrollY), referenceScrollY)
  await page.getByTestId('newow-reference-summary').scrollIntoViewIfNeeded()
  await page.mouse.move(0, 0)
  await expect(page.locator('article[data-reference-category]')).toHaveCount(4)
  await expect(page).toHaveScreenshot('newow-desktop-reference.png', { animations: 'disabled', caret: 'hide', maxDiffPixels: 500 })
  expect(productRequests(fixture, 'reference').at(-1).url.searchParams.get('history_before')).toBe('reference-page-2')
  assertNoUnexpectedRequests(fixture)
})

test('curve selection loads its exact older record inside the fixed records window', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { recordsHistory: true })
  await page.goto(newowRoute())
  await showReference(page)
  const summaryBefore = await page.getByTestId('newow-reference-summary').innerText()
  const chartBefore = productRequests(fixture, 'chart').length
  await page.getByRole('button', { name: /2026-06-30，累计 .*定位参考交易/ }).press('Enter')
  await expect(page.locator('#reference-trade-trend-1d-initial')).toBeInViewport()
  await expect(page.locator('article[data-reference-category]')).toHaveCount(4)
  expect(await page.getByTestId('newow-reference-summary').innerText()).toBe(summaryBefore)
  expect(productRequests(fixture, 'chart')).toHaveLength(chartBefore)
  const records = productRequests(fixture, 'reference').filter(item => item.url.searchParams.has('history_limit'))
  expect(records).toHaveLength(2)
  for (const item of records) {
    expect(item.url.searchParams.get('history_limit')).toBe('200')
    expect(item.url.searchParams.get('performance_since')).toBe('2026-06-03')
    expect(item.url.searchParams.get('performance_through')).toBe('2026-09-03')
  }
  assertNoUnexpectedRequests(fixture)
})

test('default completed W1 window remains current on a weekend', async ({ browser }) => {
  for (const frequency of ['1d']) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
    const page = await context.newPage()
    const fixture = await installNewowProductFixtures(page, { frozenNow: '2026-09-06T03:00:00.000Z' })
    await page.goto(newowRoute('trend', frequency))
    await expect(page.locator('.newow-summary__facts')).toContainText('已读取窗口最近主动作')
    await showReference(page)
    await expect(page.locator('.newow-summary__facts')).toContainText('当前参考交易 未清仓')
    assertNoUnexpectedRequests(fixture)
    await context.close()
  }
})

test('curve window changes leave records, chart and auxiliary windows unchanged', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page)
  await page.goto(newowRoute())
  await showReference(page)
  await expect(page.locator('article[data-reference-category]')).toHaveCount(2)
  const recordsBefore = productRequests(fixture, 'reference').filter(item => item.url.searchParams.has('history_limit')).length
  const chartBefore = productRequests(fixture, 'chart').length
  const auxiliaryBefore = productRequests(fixture, 'auxiliary').length
  await page.getByRole('button', { name: '近3月', exact: true }).click()
  await expect(page.getByRole('button', { name: '近3月', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('article[data-reference-category]')).toHaveCount(2)
  expect(productRequests(fixture, 'reference').filter(item => item.url.searchParams.has('history_limit'))).toHaveLength(recordsBefore)
  expect(productRequests(fixture, 'chart')).toHaveLength(chartBefore)
  expect(productRequests(fixture, 'auxiliary')).toHaveLength(auxiliaryBefore)
  assertNoUnexpectedRequests(fixture)
})

test('generic series failure does not suppress chart-first Newow or its snapshot-bound first-screen sections', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { genericSeries: 'failed' })
  await page.goto('/market/chart?symbol=rb&view=free&frequency=1d&series_kind=actual_dominant')
  await expect.poll(() => fixture.requests.filter((item) => item.url.pathname === '/api/v1/market/bars/page').length).toBe(1)
  await expect.poll(() => fixture.aborted.filter((url) => url.includes('/api/v1/market/bars/page')).length).toBe(1)
  await page.goto(newowRoute('main_rise', '1d'))
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready')
  expect(fixture.requests.filter((item) => item.url.pathname === '/api/v1/market/bars/page')).toHaveLength(2)
  expect(productRequests(fixture, 'chart')).toHaveLength(1)
  await expect.poll(() => productRequests(fixture, 'auxiliary').length).toBe(1)
  await expect.poll(() => productRequests(fixture, 'reference').filter(item => !item.url.searchParams.has('history_limit')).length).toBe(1)
  await expect.poll(() => productRequests(fixture, 'reference').filter(item => item.url.searchParams.get('history_limit') === '200').length).toBe(1)
  expect(productRequests(fixture, 'reference')).toHaveLength(2)
  expect(productRequests(fixture, 'explanation')).toHaveLength(0)
  expect(productRequests(fixture, 'comparator')).toHaveLength(0)
  assertNoUnexpectedRequests(fixture)
})

test('late old chart response cannot overwrite the switched identity', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { deferOnce: 'trend:1d:chart' })
  await page.goto(newowRoute(), { waitUntil: 'domcontentloaded' })
  await expect.poll(() => productRequests(fixture, 'chart').length).toBe(1)
  await page.getByRole('tab', { name: '震荡策略', exact: true }).click()
  const chart = page.getByTestId('newow-product-chart-stage')
  await expect(chart).toHaveAttribute('data-strategy', 'oscillation')
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready')
  await releaseDeferred(fixture, 'trend:1d:chart')
  await expect(chart).toHaveAttribute('data-strategy', 'oscillation')
  await expect(chart).toHaveAttribute('data-action-ids', /oscillation-1d-build-open/)
  assertNoUnexpectedRequests(fixture)
})

test('shared-bar conflict and repeated 409 stay fail-closed and bounded', async ({ browser }) => {
  const revisionContext = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const revisionPage = await revisionContext.newPage()
  const revision = await installNewowProductFixtures(revisionPage, { revision: ({ url, section }) => section === 'chart' && url.searchParams.has('chart_before') ? 'fixture-revision-2' : 'fixture-revision-1' })
  await revisionPage.goto(newowRoute())
  await revisionPage.getByTestId('newow-load-earlier').click()
  await expect.poll(() => productRequests(revision, 'chart').length).toBe(2)
  assertNoUnexpectedRequests(revision)
  await expect(revisionPage.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'input_conflict')
  expect(productRequests(revision, 'chart')).toHaveLength(2)
  await revisionContext.close()

  const sharedContext = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const sharedPage = await sharedContext.newPage()
  const shared = await installNewowProductFixtures(sharedPage, { sharedBarConflict: true })
  await sharedPage.goto(newowRoute())
  await sharedPage.getByTestId('newow-load-earlier').click()
  await expect(sharedPage.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'input_conflict')
  expect(productRequests(shared, 'chart')).toHaveLength(2)
  await sharedContext.close()

  const repeatedContext = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const repeatedPage = await repeatedContext.newPage()
  const repeated = await installNewowProductFixtures(repeatedPage, { conflictAlways: 'trend:1d:chart' })
  await repeatedPage.goto(newowRoute())
  await expect(repeatedPage.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'input_conflict')
  expect(productRequests(repeated, 'chart')).toHaveLength(2)
  await repeatedContext.close()
})

test('daily deep link opens while weekly and hourly remain closed', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page)
  await page.goto(newowRoute('trend', '1d'))
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready')
  expect(productRequests(fixture, 'chart').some(item => item.frequency === '1d')).toBe(true)
  const requestsBefore = productRequests(fixture, 'chart').length
  await page.goto(newowRoute('trend', '60m'))
  await expect(page.getByText('当前牛哇周期未开放', { exact: true })).toBeVisible()
  await expect(page.getByText(/60m 尚未开放/)).toBeVisible()
  expect(productRequests(fixture, 'chart')).toHaveLength(requestsBefore)
  await page.goto(newowRoute('trend', '1w'))
  await expect(page.getByText('当前牛哇周期未开放', { exact: true })).toBeVisible()
  await expect(page.getByText(/1w 尚未开放/)).toBeVisible()
  expect(productRequests(fixture, 'chart')).toHaveLength(requestsBefore)
  await page.getByRole('button', { name: '切换到已开放日线', exact: true }).click()
  await expect(page).toHaveURL(/frequency=1d/)
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready')
  assertNoUnexpectedRequests(fixture)
})

test('isolated weekly candidate opens three W1 strategies and keeps 60m closed', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { weeklyCandidate: true })
  for (const strategy of ['trend', 'oscillation', 'main_rise']) {
    await page.goto(newowRoute(strategy, '1w'))
    await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready')
  }
  await page.goto(newowRoute('trend', '1d'))
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready')
  await page.goto(newowRoute('trend', '1w'))
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready')
  await page.goto(newowRoute('trend', '60m'))
  await expect(page.getByText(/60m 尚未开放/)).toBeVisible()
  assertNoUnexpectedRequests(fixture)
})

test('record cursor conflict preserves accepted records and retries only on explicit request', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { recordsHistory: true, cursorConflictOnce: 'trend:1d:reference' })
  await page.goto(newowRoute())
  await showReference(page)
  const summaryBefore = await page.getByTestId('newow-reference-summary').innerText()
  await page.getByRole('button', { name: '加载更多参考历史' }).click()
  await expect(page.getByText('近三个月操盘记录暂不可用，请重试。')).toBeVisible()
  await expect(page.locator('article[data-reference-category]')).toHaveCount(2)
  expect(productRequests(fixture, 'reference')).toHaveLength(3)
  await page.getByRole('button', { name: '重试记录', exact: true }).click()
  await expect(page.locator('article[data-reference-category]')).toHaveCount(4)
  expect(await page.getByTestId('newow-reference-summary').innerText()).toBe(summaryBefore)
  expect(productRequests(fixture, 'reference')).toHaveLength(4)
  const retry = productRequests(fixture, 'reference').at(-1).url.searchParams
  expect(retry.get('snapshot_token')).toBe('snapshot:trend:1d:fixture-revision-1')
  expect(retry.get('history_before')).toBe('reference-page-2')
  expect(retry.get('history_limit')).toBe('200')
  assertNoUnexpectedRequests(fixture)
})

test('a tokenless chart never requests or exposes an unproven auxiliary', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { tokenlessSections: ['chart'] })
  await page.goto(newowRoute())
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready')
  expect(productRequests(fixture, 'auxiliary')).toHaveLength(0)
  await expect(page.getByTestId('newow-product-chart-stage')).toHaveAttribute('data-auxiliary-component', '')
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-auxiliary-state', 'not_requested')
  await page.getByRole('tab', { name: '震荡策略', exact: true }).click()
  await expect(page.getByTestId('newow-product-chart-stage')).toHaveAttribute('data-strategy', 'oscillation')
  expect(productRequests(fixture, 'auxiliary')).toHaveLength(0)
  assertNoUnexpectedRequests(fixture)
})

test('an auxiliary 409 rebuilds chart proof before its single retry', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { onProductRequest: async ({ route, section, count }) => {
    if (section === 'auxiliary' && count === 1) {
      await route.fulfill({ status: 409, json: { detail: { code: 'NEWOW_SNAPSHOT_GENERATION_CONFLICT' } } })
      return 'handled'
    }
  } })
  await page.goto(newowRoute())
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-auxiliary-state', 'ready')

  const auxiliaryRequests = productRequests(fixture, 'auxiliary')
  expect(auxiliaryRequests).toHaveLength(2)
  for (const { url } of auxiliaryRequests) {
    expect(url.searchParams.get('snapshot_token')).toBeTruthy()
    expect(url.searchParams.get('from')).toBe('2025-01-01')
    expect(url.searchParams.get('through')).toBe('2026-09-03')
  }
  expect(productRequests(fixture, 'chart')).toHaveLength(2)
  assertNoUnexpectedRequests(fixture)
})

test('repeated auxiliary 409 stops after one chart rebuild', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { onProductRequest: async ({ route, section }) => {
    if (section === 'auxiliary') {
      await route.fulfill({ status: 409, json: { detail: { code: 'NEWOW_SNAPSHOT_GENERATION_CONFLICT' } } })
      return 'handled'
    }
  } })
  await page.goto(newowRoute())
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-auxiliary-state', 'input_conflict')

  expect(productRequests(fixture, 'auxiliary')).toHaveLength(2)
  expect(productRequests(fixture, 'chart')).toHaveLength(2)
  for (const { url } of productRequests(fixture, 'auxiliary')) {
    expect(url.searchParams.get('snapshot_token')).toBeTruthy()
  }
  assertNoUnexpectedRequests(fixture)
})

test('switching auxiliary after a prior success clears failed facts and explicit retry recovers', async ({ page }) => {
  let auxiliaryCalls = 0
  const fixture = await installNewowProductFixtures(page, { onProductRequest: async ({ route, section }) => {
    if (section === 'auxiliary' && ++auxiliaryCalls === 2) {
      await route.fulfill({ status: 429, json: { detail: { code: 'NEWOW_RESOURCE_BUSY' } } })
      return 'handled'
    }
  } })
  await page.goto(newowRoute())
  const chart = page.getByTestId('newow-product-chart-stage')
  await expect(chart).toHaveAttribute('data-auxiliary-component', 'macd')
  await page.getByRole('button', { name: '主力控盘', exact: true }).click()
  await expect(chart).toHaveAttribute('data-auxiliary-component', '')
  await expect(page.getByRole('button', { name: '重试指标', exact: true })).toBeVisible()
  expect(productRequests(fixture, 'auxiliary')).toHaveLength(2)
  await page.getByRole('button', { name: '重试指标', exact: true }).click()
  await expect(chart).toHaveAttribute('data-auxiliary-component', 'main_force_control')
  await expect(chart).toHaveAttribute('data-auxiliary-state', 'ready')
  expect(productRequests(fixture, 'auxiliary')).toHaveLength(3)
  expect(productRequests(fixture, 'chart')).toHaveLength(1)
  assertNoUnexpectedRequests(fixture)
})

test('reference rebuild remains bounded without requesting the deferred explanation section', async ({ page }) => {
  let performanceRequests = 0
  const fixture = await installNewowProductFixtures(page, {
    onProductRequest: async ({ route, url, section }) => {
      if (section !== 'reference' || url.searchParams.has('history_limit')) return
      if (++performanceRequests === 2) {
        await route.fulfill({ status: 409, json: { detail: { code: 'NEWOW_SNAPSHOT_GENERATION_CONFLICT' } } })
        return 'handled'
      }
    },
  })
  await page.goto(newowRoute())
  await showReference(page)
  await expect(page.getByTestId('newow-reference-summary')).toBeVisible()
  await page.getByRole('button', { name: '近3月', exact: true }).click()
  await expect.poll(() => performanceRequests).toBe(3)
  const rebuilt = productRequests(fixture, 'reference').filter(item => !item.url.searchParams.has('history_limit')).at(-1)
  expect(rebuilt.url.searchParams.has('snapshot_token')).toBe(false)
  await expect(page.getByTestId('newow-reference-summary')).toBeVisible()
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'not_requested')
  expect(productRequests(fixture, 'explanation')).toHaveLength(0)
  assertNoUnexpectedRequests(fixture)
})

test('a snapshot conflict rebuilds once while busy and identity mismatch fail closed', async ({ page }) => {
  const conflict = await installNewowProductFixtures(page, { conflictOnce: 'trend:1d:reference' })
  await page.goto(newowRoute())
  await showReference(page)
  await expect(page.getByTestId('newow-reference-summary')).toBeVisible()
  const performance = productRequests(conflict, 'reference').filter(item => !item.url.searchParams.has('history_limit'))
  expect(performance).toHaveLength(2)
  await expect.poll(() => productRequests(conflict, 'reference').filter(item => item.url.searchParams.get('history_limit') === '200').length).toBe(1)
  expect(productRequests(conflict, 'reference')).toHaveLength(3)
  expect(performance[0].url.searchParams.get('snapshot_token')).toBeTruthy()
  expect(performance[1].url.searchParams.has('snapshot_token')).toBe(false)
  assertNoUnexpectedRequests(conflict)
})

test('429 is bounded and an identity mismatch clears stale facts', async ({ browser }) => {
  const busyContext = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const busyPage = await busyContext.newPage()
  const busy = await installNewowProductFixtures(busyPage, { busy: 'trend:1d:reference' })
  await busyPage.goto(newowRoute())
  await showReference(busyPage)
  await expect(busyPage.locator('.newow-reference')).toContainText('NEWOW_RESOURCE_BUSY')
  expect(productRequests(busy, 'reference')).toHaveLength(1)
  assertNoUnexpectedRequests(busy)
  await busyContext.close()

  const mismatchContext = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const mismatchPage = await mismatchContext.newPage()
  const mismatch = await installNewowProductFixtures(mismatchPage, { identityMismatch: 'trend:1d:chart' })
  await mismatchPage.goto(newowRoute())
  await expect(mismatchPage.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'input_conflict')
  const unavailable = mismatchPage.locator('.detail-unavailable')
  await expect(unavailable).toContainText('主图事实不可用原因未识别')
  await expect(unavailable.getByText('NEWOW_RESPONSE_INVALID', { exact: true })).not.toBeVisible()
  await unavailable.getByText('技术详情', { exact: true }).click()
  await expect(unavailable.getByText('NEWOW_RESPONSE_INVALID', { exact: true })).toBeVisible()
  expect(productRequests(mismatch, 'chart')).toHaveLength(1)
  assertNoUnexpectedRequests(mismatch)
  await mismatchContext.close()
})

test('zero CLOSED summary renders missing metrics instead of zero percent', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { zeroClosed: true })
  await page.goto(newowRoute())
  await showReference(page)
  const summary = page.getByTestId('newow-reference-summary')
  await expect(summary).toContainText('暂无已完成参考交易；统计指标不是 0%。')
  await expect(summary).not.toContainText('0.00%')
  assertNoUnexpectedRequests(fixture)
})

test('auxiliary cache, applicability and disclosures remain section-local', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page)
  await page.goto(newowRoute('trend', '1d'))
  // Fix the modal's background at a completed read, independent of toolbar scroll timing.
  await showReference(page)
  await expect(page.getByTestId('newow-reference-summary')).toContainText('100')
  await resetPageScroll(page)
  for (const label of ['主力控盘', '涨跌动能', '照妖镜']) {
    await page.getByRole('button', { name: label, exact: true }).click()
    await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-auxiliary-state', 'ready')
  }
  await page.getByRole('button', { name: '照妖镜', exact: true }).click()
  await page.getByRole('button', { name: '指标解读', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('会重绘')
  await expect(page.getByRole('dialog')).toBeInViewport()
  await expect(page).toHaveScreenshot('newow-mirror-repaint-disclosure.png', { animations: 'disabled', caret: 'hide', maxDiffPixels: 500 })
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '主力控盘', exact: true }).click()
  expect(productRequests(fixture, 'auxiliary').filter((item) => item.url.searchParams.get('component') === 'main_force_control')).toHaveLength(1)
  assertNoUnexpectedRequests(fixture)
})

test('auxiliary renders warming, unavailable, and daily cup-handle states', async ({ browser }) => {
  for (const [status, wireStatus, renderState] of [['warming', warming(), 'warming'], ['unavailable', unavailable(), 'error']]) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
    const page = await context.newPage()
    const fixture = await installNewowProductFixtures(page, { auxiliaryState: { main_force_control: wireStatus } })
    await page.goto(newowRoute())
    await page.getByRole('button', { name: '主力控盘', exact: true }).click()
    await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-auxiliary-state', status)
    await expect(page.getByTestId('newow-product-chart-stage')).toHaveAttribute('data-auxiliary-state', renderState)
    assertNoUnexpectedRequests(fixture)
    await context.close()
  }

  const notApplicableContext = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const notApplicablePage = await notApplicableContext.newPage()
  const notApplicable = await installNewowProductFixtures(notApplicablePage)
  await notApplicablePage.goto(newowRoute('trend', '1d'))
  await notApplicablePage.getByRole('button', { name: '杯柄说明', exact: true }).click()
  await expect(notApplicablePage.getByRole('dialog')).toContainText('服务端杯柄事实')
  expect(productRequests(notApplicable, 'auxiliary').map(item => item.url.searchParams.get('component'))).toEqual(['macd', 'cup_handle'])
  assertNoUnexpectedRequests(notApplicable)
  await notApplicableContext.close()
})

test('deferred explanation stays separate from chart, records and optional comparison transport', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page)
  await page.goto(newowRoute('main_rise', '1d'))
  await showReference(page)
  const chart = page.getByTestId('newow-product-chart-stage')
  const actionIdsBefore = await chart.getAttribute('data-action-ids')
  const openBefore = await page.locator('article[data-reference-category="open"]').innerText()
  await page.getByRole('button', { name: '查看依据', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('尚未开放跨周期综合解释')
  await expect(dialog).toContainText('NEWOW_CROSS_FREQUENCY_INPUTS_NOT_OPEN')
  await expect(dialog.getByTestId('newow-explanation-panel')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '页面比较说明', exact: true })).toHaveCount(0)
  await expect(dialog).toBeInViewport()
  await expect(page).toHaveScreenshot('newow-main-rise-explanation-evidence.png', { animations: 'disabled', caret: 'hide', maxDiffPixels: 500 })
  expect(productRequests(fixture, 'explanation')).toHaveLength(0)
  expect(productRequests(fixture, 'comparator')).toHaveLength(0)
  await page.keyboard.press('Escape')
  await showReference(page)
  expect(await page.locator('article[data-reference-category="open"]').innerText()).toBe(openBefore)
  expect(await chart.getAttribute('data-action-ids')).toBe(actionIdsBefore)
  expect(productRequests(fixture, 'reference').filter(item => !item.url.searchParams.has('history_limit'))).toHaveLength(1)
  expect(productRequests(fixture, 'reference').filter(item => item.url.searchParams.get('history_limit') === '200')).toHaveLength(1)
  assertNoUnexpectedRequests(fixture)
})

test('replacement disclosure controls support keyboard focus', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page)
  await page.goto(newowRoute())
  const trigger = page.getByRole('button', { name: '查看依据', exact: true })
  await trigger.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(trigger).toBeFocused()
  assertNoUnexpectedRequests(fixture)
})

test('dense actions retain every identity while visible callouts stay bounded and collision free', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const fixture = await installNewowProductFixtures(page, { denseActions: 100 })
  await page.goto(newowRoute('trend', '1d'))
  const stage = page.getByTestId('newow-product-chart-stage')
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready')
  const ids = (await stage.getAttribute('data-action-ids')).split(',')
  expect(ids).toEqual(Array.from({ length: 100 }, (_, i) => `dense-${i % 2 ? 'clear' : 'build'}-${Math.floor(i / 2)}`))
  const labels = stage.locator('.newow-product-chart-stage__action-label')
  const boxes = await labels.evaluateAll(nodes => nodes.map(node => {
    const r = node.getBoundingClientRect()
    const parent = node.parentElement.getBoundingClientRect()
    return { id: node.dataset.actionId, price: node.dataset.referencePrice, contract: node.dataset.referenceContract,
      x: r.x - parent.x, y: r.y - parent.y, width: r.width, height: r.height, containerWidth: parent.width, containerHeight: parent.height }
  }))
  expect(boxes.length).toBeGreaterThan(0)
  expect(boxes.length).toBeLessThan(ids.length)
  for (const box of boxes) {
    expect(ids).toContain(box.id)
    expect(box.price).toBe('100')
    expect(box.contract).toBe('RB2605')
    expect(box.x).toBeGreaterThanOrEqual(-0.5)
    expect(box.y).toBeGreaterThanOrEqual(-0.5)
    expect(box.x + box.width).toBeLessThanOrEqual(box.containerWidth + 0.5)
    expect(box.y + box.height).toBeLessThanOrEqual(box.containerHeight + 0.5)
  }
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i], b = boxes[j]
    expect(a.x + a.width <= b.x + 0.5 || b.x + b.width <= a.x + 0.5 || a.y + a.height <= b.y + 0.5 || b.y + b.height <= a.y + 0.5).toBe(true)
  }
  await selectLatestAction(page, 'dense-clear-49')
  await expect(page.getByRole('dialog')).toContainText('dense-clear-49')
  expect((await stage.getAttribute('data-action-ids')).split(',')).toEqual(ids)
  assertNoUnexpectedRequests(fixture)
})

test.describe('mobile', () => {
  test.use({ viewport: { width: 390, height: 844 } })
  test('starts at the real mobile viewport with scrollable reference content', async ({ page }) => {
    expect(page.viewportSize()).toEqual({ width: 390, height: 844 })
    const fixture = await installNewowProductFixtures(page)
    await page.goto(newowRoute('oscillation', '1d'))
    await showReference(page)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await expect(page.locator('article[data-reference-category]')).toHaveCount(2)
    await expect(page).toHaveScreenshot('newow-mobile-oscillation-reference.png', { animations: 'disabled', caret: 'hide', maxDiffPixels: 500 })
    assertNoUnexpectedRequests(fixture)
  })
})

test('records raw cold, warm, reuse, rebuild and history-prepend timings without fixed sleeps', async ({ page }, testInfo) => {
  const samples = []
  const fixture = await installNewowProductFixtures(page)
  const start = performance.now()
  await page.goto(newowRoute('trend', '1d'))
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready')
  samples.push({ metric: 'cold_chart_visible_ms', value: performance.now() - start })
  samples.push({ metric: 'cold_chart_request_dispatch_ms', value: productRequests(fixture, 'chart')[0].startedAt - start })
  const beforeReference = performance.now()
  await showReference(page)
  await expect(page.getByTestId('newow-reference-summary')).toBeVisible()
  samples.push({ metric: 'warm_reference_visible_ms', value: performance.now() - beforeReference })
  samples.push({ metric: 'warm_reference_request_dispatch_ms', value: productRequests(fixture, 'reference')[0].startedAt - beforeReference })
  await page.getByRole('button', { name: '查看依据', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('尚未开放跨周期综合解释')
  await page.keyboard.press('Escape')
  const referenceRequestsBeforeReopen = productRequests(fixture, 'reference').length
  const referenceReopen = performance.now()
  await showReference(page)
  await expect(page.getByTestId('newow-reference-summary')).toBeVisible()
  samples.push({ metric: 'already_loaded_reference_reopen_ms', value: performance.now() - referenceReopen })
  samples.push({ metric: 'already_loaded_reference_reopen_request_delta', value: productRequests(fixture, 'reference').length - referenceRequestsBeforeReopen })
  const beforeAux = performance.now()
  await page.getByRole('button', { name: '主力控盘', exact: true }).click()
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-auxiliary-state', 'ready')
  samples.push({ metric: 'cold_auxiliary_visible_ms', value: performance.now() - beforeAux })
  samples.push({ metric: 'cold_auxiliary_request_dispatch_ms', value: productRequests(fixture, 'auxiliary').find(item => item.url.searchParams.get('component') === 'main_force_control').startedAt - beforeAux })
  await page.getByRole('button', { name: '主力控盘', exact: true }).click()
  const reuse = performance.now()
  const auxiliaryRequestsBeforeReuse = productRequests(fixture, 'auxiliary').length
  await page.getByRole('button', { name: '主力控盘', exact: true }).click()
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-auxiliary-state', 'ready')
  samples.push({ metric: 'auxiliary_cache_reuse_visible_ms', value: performance.now() - reuse })
  samples.push({ metric: 'auxiliary_cache_reuse_request_delta', value: productRequests(fixture, 'auxiliary').length - auxiliaryRequestsBeforeReuse })
  const beforeOlder = performance.now()
  await page.getByTestId('newow-load-earlier').click()
  await expect.poll(() => productRequests(fixture, 'chart').length).toBe(2)
  samples.push({ metric: 'history_prepend_ms', value: performance.now() - beforeOlder })
  samples.push({ metric: 'history_request_dispatch_ms', value: productRequests(fixture, 'chart')[1].startedAt - beforeOlder })

  const strategySwitch = performance.now()
  await page.getByRole('tab', { name: '震荡策略', exact: true }).click()
  await expect(page.getByTestId('newow-product-chart-stage')).toHaveAttribute('data-strategy', 'oscillation')
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready')
  samples.push({ metric: 'strategy_switch_visible_ms', value: performance.now() - strategySwitch })
  samples.push({ metric: 'strategy_switch_request_dispatch_ms', value: productRequests(fixture, 'chart').at(-1).startedAt - strategySwitch })
  const rebuildPage = await page.context().newPage()
  const rebuildFixture = await installNewowProductFixtures(rebuildPage, { conflictOnce: 'trend:1d:chart' })
  const rebuildStart = performance.now()
  await rebuildPage.goto(newowRoute())
  await expect(rebuildPage.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready')
  samples.push({ metric: 'snapshot_rebuild_visible_ms', value: performance.now() - rebuildStart })
  samples.push({ metric: 'snapshot_rebuild_request_count', value: productRequests(rebuildFixture, 'chart').length })
  await rebuildPage.close()
  const mobileContext = await page.context().browser().newContext({ viewport: { width: 390, height: 844 } })
  const mobilePage = await mobileContext.newPage()
  const mobileFixture = await installNewowProductFixtures(mobilePage)
  await mobilePage.goto(newowRoute('oscillation', '1d'))
  const mobileInteraction = performance.now()
  await showReference(mobilePage)
  await expect(mobilePage.getByTestId('newow-reference-summary')).toBeVisible()
  samples.push({ metric: 'mobile_390_reference_interaction_ms', value: performance.now() - mobileInteraction })
  samples.push({ metric: 'mobile_390_reference_request_dispatch_ms', value: productRequests(mobileFixture, 'reference')[0].startedAt - mobileInteraction })
  await mobileContext.close()
  const environment = await page.evaluate(() => ({ userAgent: navigator.userAgent, hardwareConcurrency: navigator.hardwareConcurrency, viewport: [innerWidth, innerHeight] }))
  const thresholdMapping = {
    direct: { metric: 'warm_reference_visible_ms', threshold_ms: 5000, source: 'Task21 frozen full-statistics threshold' },
    advisory: ['cold_chart_visible_ms', 'strategy_switch_visible_ms', 'mobile_390_reference_interaction_ms'],
    unmapped: ['already_loaded_reference_reopen_ms', 'auxiliary_cache_reuse_visible_ms', 'history_prepend_ms', 'snapshot_rebuild_visible_ms'],
  }
  await testInfo.attach('newow-performance.json', { body: JSON.stringify({ samples, thresholdMapping, environment: { ...environment, node: process.version, platform: `${os.platform()} ${os.release()}`, cpu: os.cpus()[0]?.model } }, null, 2), contentType: 'application/json' })
  console.log(`NEWOW_PERFORMANCE ${JSON.stringify(samples)}`)
  assertNoUnexpectedRequests(fixture)
})

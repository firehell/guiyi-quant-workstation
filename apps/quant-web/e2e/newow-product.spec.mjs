import { expect, test } from '@playwright/test'
import { performance } from 'node:perf_hooks'
import os from 'node:os'

import {
  NEWOW_AS_OF,
  NEWOW_FREQUENCIES,
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

function expectExactQuery(request, expected) {
  expect(Object.fromEntries([...request.url.searchParams.entries()].sort())).toEqual(Object.fromEntries(Object.entries(expected).sort()))
}

async function clickLastBarMarker(page, expectedSignalId, verticalRatios) {
  const chart = page.getByTestId('newow-product-chart-stage')
  await chart.evaluate((element) => element.scrollIntoView({ block: 'center' }))
  if (await page.getByRole('dialog').isVisible()) await page.keyboard.press('Escape')
  const box = await chart.locator('tr').filter({ has: page.locator('td:nth-child(3)') }).first().boundingBox()
  if (box === null) throw new Error('chart has no bounding box')
  for (const x of [box.x + box.width * 0.476, box.x + box.width * 0.48, box.x + box.width * 0.485, box.x + box.width - 98, box.x + box.width - 94, box.x + box.width - 102]) {
    for (const ratio of verticalRatios) {
      await page.mouse.click(x, box.y + box.height * ratio)
      if (await chart.getAttribute('data-selected-signal-id') === expectedSignalId) return
    }
  }
  throw new Error(`marker ${expectedSignalId} was not clickable`)
}

for (const strategy of NEWOW_STRATEGIES) {
  for (const frequency of NEWOW_FREQUENCIES) {
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
      expect(productRequests(fixture, 'reference')).toHaveLength(0)

      await showReference(page)
      await expect(page.getByTestId('newow-reference-summary')).toContainText('100')
      expectExactQuery(productRequests(fixture, 'reference')[0], { product: 'rb', strategy, frequency, series_kind: 'actual_dominant', section: 'reference', as_of: NEWOW_AS_OF, snapshot_token: `snapshot:${strategy}:${frequency}:fixture-revision-1` })
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

test('same-Bar CLEAR then BUILD actions remain separately locatable', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page)
  await page.goto(newowRoute('oscillation', '1d'))
  const chart = page.getByTestId('newow-product-chart-stage')
  await expect(chart).toHaveAttribute('data-action-ids', /oscillation-1d-clear-same,oscillation-1d-build-open/)
  await clickLastBarMarker(page, 'oscillation-1d-clear-same', [0.30, 0.32, 0.34, 0.36])
  await expect(chart).toHaveAttribute('data-selected-signal-id', 'oscillation-1d-clear-same')
  await expect(page.getByRole('dialog')).toContainText('历史主动作 参考清仓')
  await page.keyboard.press('Escape')
  await clickLastBarMarker(page, 'oscillation-1d-build-open', [0.68, 0.70, 0.72, 0.74, 0.76])
  await expect(chart).toHaveAttribute('data-selected-signal-id', 'oscillation-1d-build-open')
  await expect(page.getByRole('dialog')).toContainText('历史主动作 参考建仓')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).not.toBeVisible()
  await page.mouse.move(0, 0)
  await expect(page).toHaveScreenshot('newow-oscillation-same-bar.png', { animations: 'disabled', caret: 'hide', maxDiffPixels: 500 })
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
  const chart = structuredClone(buildNewowFixtureEnvelopeForTest('chart', 'trend', '1w'))
  chart.chart.value.bars[0].segment_id = 'rb:RB9999:2099-01-01T00:00:00+00:00'
  expect(() => validateNewowFixtureEnvelopeForTest(chart, 'chart', 'trend', '1w')).toThrow(/segment window/)
})

test('strategy and frequency controls clear prior selection and request only the new identity', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page)
  await page.goto(newowRoute())
  await showReference(page)
  await page.getByRole('button', { name: /定位参考记录 trend-1d-open/ }).click()
  const chart = page.getByTestId('newow-product-chart-stage')
  await expect(chart).toHaveAttribute('data-selected-signal-id', 'trend-1d-build-open')
  await page.getByRole('button', { name: '震荡', exact: true }).click()
  await expect(chart).toHaveAttribute('data-strategy', 'oscillation')
  await expect(chart).toHaveAttribute('data-selected-signal-id', '')
  await page.getByRole('button', { name: '60m', exact: true }).click()
  await expect(chart).toHaveAttribute('data-frequency', '60m')
  await expect(chart).toHaveAttribute('data-selected-signal-id', '')
  expectExactQuery(productRequests(fixture, 'chart').at(-1), { product: 'rb', strategy: 'oscillation', frequency: '60m', series_kind: 'actual_dominant', section: 'chart', as_of: NEWOW_AS_OF })
  assertNoUnexpectedRequests(fixture)
})

test('reference pagination exposes OPEN, CLOSED, interrupted, negative and initial rows without inventing zero metrics', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page)
  await page.goto(newowRoute())
  await showReference(page)
  await expect(page.locator('article[data-reference-category="open"]')).toBeVisible()
  await expect(page.locator('article[data-reference-category="closed"]')).toBeVisible()
  await page.getByRole('button', { name: '加载更多参考历史' }).click()
  await expect(page.locator('article[data-reference-category="interrupted"]')).toBeVisible()
  await expect(page.locator('article[data-reference-category="interrupted"] .newow-return-badge')).toHaveText('-10.0000%')
  await expect(page.locator('article[data-reference-initial="true"]')).toBeVisible()
  const openRow = page.locator('article[data-reference-category="open"]')
  await openRow.getByRole('button', { name: /展开参考记录/ }).click()
  await expect(openRow).toContainText('trend-1d-build-open')
  await expect(openRow).toContainText('参考建仓 106.0000')
  await expect(openRow).toContainText('清仓 ID —')
  await expect(openRow).toContainText('104.6750')
  const closedRow = page.locator('article[data-reference-category="closed"][data-reference-initial="false"]')
  await closedRow.getByRole('button', { name: /展开参考记录/ }).click()
  await expect(closedRow).toContainText('trend-1d-build-closed')
  await expect(closedRow).toContainText('参考建仓 104.0000')
  await expect(closedRow).toContainText('trend-1d-clear')
  await expect(closedRow).toContainText('参考清仓 109.3061')
  const interruptedRow = page.locator('article[data-reference-category="interrupted"]')
  await interruptedRow.getByRole('button', { name: /展开参考记录/ }).click()
  await expect(interruptedRow).toContainText('trend-1d-bi')
  await expect(interruptedRow).toContainText('参考建仓 88.0000')
  await expect(interruptedRow).toContainText('79.2000')
  const summaryBeforeViewport = await page.getByTestId('newow-reference-summary').innerText()
  const chartBox = await page.getByTestId('newow-product-chart-stage').locator('.newow-product-chart-stage__chart').boundingBox()
  if (chartBox === null) throw new Error('chart has no bounding box')
  await page.mouse.move(chartBox.x + chartBox.width * 0.7, chartBox.y + chartBox.height * 0.5)
  await page.mouse.down()
  await page.mouse.move(chartBox.x + chartBox.width * 0.5, chartBox.y + chartBox.height * 0.5, { steps: 5 })
  await page.mouse.up()
  expect(await page.getByTestId('newow-reference-summary').innerText()).toBe(summaryBeforeViewport)
  await expect(page).toHaveScreenshot('newow-desktop-reference.png', { animations: 'disabled', caret: 'hide', maxDiffPixels: 500 })
  expect(productRequests(fixture, 'reference').at(-1).url.searchParams.get('history_before')).toBe('reference-page-2')
  assertNoUnexpectedRequests(fixture)
})

test('exact locate loads an unloaded window and never falls back to nearest marker', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page)
  await page.goto(newowRoute())
  await showReference(page)
  await page.getByRole('button', { name: '加载更多参考历史' }).click()
  await expect(page.locator('article[data-reference-category]')).toHaveCount(4)
  const summaryBefore = await page.getByTestId('newow-reference-summary').innerText()
  const rowCountBefore = await page.locator('article[data-reference-category]').count()
  const referenceRequestsBefore = productRequests(fixture, 'reference').length
  await page.getByRole('button', { name: /定位参考记录 trend-1d-interrupted/ }).click()
  await expect(page.getByTestId('newow-product-chart-stage')).toHaveAttribute('data-selected-signal-id', 'trend-1d-bi')
  const locate = productRequests(fixture, 'chart').at(-1).url.searchParams
  expect(locate.get('from')).toBe('2026-01-05')
  expect(locate.has('performance_since')).toBe(false)
  await showReference(page)
  expect(await page.getByTestId('newow-reference-summary').innerText()).toBe(summaryBefore)
  await expect(page.locator('article[data-reference-category]')).toHaveCount(rowCountBefore)
  expect(productRequests(fixture, 'reference')).toHaveLength(referenceRequestsBefore)
  assertNoUnexpectedRequests(fixture)
})

test('absent exact locate stays unavailable without selecting a neighbor or changing performance', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { noAction: true })
  await page.goto(newowRoute())
  await showReference(page)
  const summary = page.getByTestId('newow-reference-summary')
  const summaryBefore = await summary.innerText()
  await page.getByRole('button', { name: '加载更多参考历史' }).click()
  await page.getByRole('button', { name: /定位参考记录 trend-1d-interrupted/ }).click()
  await expect(page.getByText(/无法按精确信号 trend-1d-bi.*没有跳转到邻近日期/)).toBeVisible()
  await expect(page.getByTestId('newow-product-chart-stage')).toHaveAttribute('data-selected-signal-id', '')
  expect(await summary.innerText()).toBe(summaryBefore)
  assertNoUnexpectedRequests(fixture)
})

test('generic series failure does not suppress chart-first Newow or prefetch dependent sections', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { genericSeries: 'failed' })
  await page.goto('/market/chart?symbol=rb&view=free&frequency=1d&series_kind=actual_dominant')
  await expect.poll(() => fixture.requests.filter((item) => item.url.pathname === '/api/v1/market/bars/page').length).toBe(1)
  await expect.poll(() => fixture.aborted.filter((url) => url.includes('/api/v1/market/bars/page')).length).toBe(1)
  await page.goto(newowRoute('main_rise', '1d'))
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready')
  expect(fixture.requests.filter((item) => item.url.pathname === '/api/v1/market/bars/page')).toHaveLength(2)
  expect(productRequests(fixture, 'chart')).toHaveLength(1)
  await expect.poll(() => productRequests(fixture, 'auxiliary').length).toBe(1)
  for (const section of ['reference', 'explanation', 'comparator']) expect(productRequests(fixture, section)).toHaveLength(0)
  assertNoUnexpectedRequests(fixture)
})

test('late old chart response cannot overwrite the switched identity', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { deferOnce: 'trend:1d:chart' })
  await page.goto(newowRoute(), { waitUntil: 'domcontentloaded' })
  await expect.poll(() => productRequests(fixture, 'chart').length).toBe(1)
  await page.getByRole('button', { name: '震荡', exact: true }).click()
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

test('reference cursor generation conflict rebuilds from an unbound first page once', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { cursorConflictOnce: 'trend:1d:reference' })
  await page.goto(newowRoute())
  await showReference(page)
  await page.getByRole('button', { name: '加载更多参考历史' }).click()
  await expect(page.locator('article[data-reference-category="open"]')).toBeVisible()
  await expect.poll(() => productRequests(fixture, 'reference').length).toBe(3)
  expect(productRequests(fixture, 'reference')[2].url.searchParams.has('snapshot_token')).toBe(false)
  expect(productRequests(fixture, 'reference')[2].url.searchParams.has('history_before')).toBe(false)
  assertNoUnexpectedRequests(fixture)
})

test('tokenless in-flight auxiliary is cancelled by identity change', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { tokenlessSections: ['chart'], deferOnce: 'trend:1d:auxiliary' })
  await page.goto(newowRoute())
  await expect.poll(() => productRequests(fixture, 'auxiliary').length).toBe(1)
  expect(productRequests(fixture, 'auxiliary')[0].url.searchParams.has('snapshot_token')).toBe(false)
  await page.getByRole('button', { name: '震荡', exact: true }).click()
  await expect(page.getByTestId('newow-product-chart-stage')).toHaveAttribute('data-strategy', 'oscillation')
  await expect.poll(() => fixture.aborted.some((url) => url.includes('section=auxiliary'))).toBe(true)
  await releaseDeferred(fixture, 'trend:1d:auxiliary')
  assertNoUnexpectedRequests(fixture)
})

test('reference rebuild invalidates loaded and in-flight dependents sharing its token', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, {
    conflictAt: { 'trend:1d:reference': 2 },
    deferOnce: 'trend:1d:explanation',
  })
  await page.goto(newowRoute())
  await showReference(page)
  await expect(page.getByTestId('newow-reference-summary')).toBeVisible()
  await page.getByRole('button', { name: '展开详情', exact: true }).click()
  await expect.poll(() => productRequests(fixture, 'explanation').length).toBe(1)
  await showReference(page)
  await page.getByRole('button', { name: '读取统计窗口' }).click()
  await expect.poll(() => productRequests(fixture, 'reference').length).toBe(3)
  await expect(page.getByTestId('newow-reference-summary')).toBeVisible()
  await expect.poll(() => fixture.aborted.some((url) => url.includes('section=explanation'))).toBe(true)
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'not_requested')
  await releaseDeferred(fixture, 'trend:1d:explanation')
  assertNoUnexpectedRequests(fixture)
})

test('a snapshot conflict rebuilds once while busy and identity mismatch fail closed', async ({ page }) => {
  const conflict = await installNewowProductFixtures(page, { conflictOnce: 'trend:1d:reference' })
  await page.goto(newowRoute())
  await showReference(page)
  await expect(page.getByTestId('newow-reference-summary')).toBeVisible()
  expect(productRequests(conflict, 'reference')).toHaveLength(2)
  expect(productRequests(conflict, 'reference')[0].url.searchParams.get('snapshot_token')).toBeTruthy()
  expect(productRequests(conflict, 'reference')[1].url.searchParams.has('snapshot_token')).toBe(false)
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
  await expect(mismatchPage.locator('.newow-product-workspace__notice')).toContainText('NEWOW_RESPONSE_INVALID')
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
  for (const label of ['主力控盘', '涨跌动能', '照妖镜']) {
    await page.getByRole('button', { name: label, exact: true }).click()
    await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-auxiliary-state', 'ready')
  }
  await page.getByRole('button', { name: '照妖镜', exact: true }).click()
  await page.getByRole('button', { name: '指标解读', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('会重绘')
  await expect(page).toHaveScreenshot('newow-mirror-repaint-disclosure.png', { animations: 'disabled', caret: 'hide', maxDiffPixels: 500 })
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '主力控盘', exact: true }).click()
  expect(productRequests(fixture, 'auxiliary').filter((item) => item.url.searchParams.get('component') === 'main_force_control')).toHaveLength(1)
  assertNoUnexpectedRequests(fixture)
})

test('auxiliary renders warming, unavailable, and non-D1 not-applicable states', async ({ browser }) => {
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
  await notApplicablePage.goto(newowRoute('trend', '60m'))
  await notApplicablePage.getByRole('button', { name: '杯柄说明', exact: true }).click()
  await expect(notApplicablePage.getByRole('dialog')).toContainText('仅适用于 1d')
  expect(productRequests(notApplicable, 'auxiliary').map(item => item.url.searchParams.get('component'))).toEqual(['macd'])
  assertNoUnexpectedRequests(notApplicable)
  await notApplicableContext.close()
})

test('explanation and comparator disclose multi-period facts, evidence gaps and synthetic terminals', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page)
  await page.goto(newowRoute('main_rise', '60m'))
  await showReference(page)
  const chart = page.getByTestId('newow-product-chart-stage')
  const actionIdsBefore = await chart.getAttribute('data-action-ids')
  const openBefore = await page.locator('article[data-reference-category="open"]').innerText()
  const windowBefore = await page.locator('.newow-reference__window input').evaluateAll((inputs) => inputs.map((input) => input.value))
  await page.getByRole('button', { name: '展开详情', exact: true }).click()
  await expect(page.locator('#newow-details').getByTestId('newow-explanation-panel')).toContainText('completed / strict-before')
  await expect(page.locator('#newow-details').getByTestId('newow-explanation-panel')).toContainText('NEWOW_PRIVATE_SCORE_UNPROVEN')
  await expect(page.locator('#newow-details').getByTestId('newow-explanation-panel')).toContainText(`快照 as_of ${NEWOW_AS_OF}`)
  await expect(page.locator('#newow-details').getByTestId('newow-explanation-panel')).toContainText('2026-08-28T07:00:00.000Z')
  await expect(page.locator('#newow-details').getByTestId('newow-explanation-panel')).toContainText('newow_main_rise_ma35_ma45_page_v1')
  await expect(page.locator('#newow-details').getByTestId('newow-explanation-panel')).toContainText('NEWOW_TARGET_SOURCE_UNPROVEN')
  await expect(page.locator('#newow-details').getByTestId('newow-explanation-panel')).toContainText('1w')
  await expect(page.locator('#newow-details').getByTestId('newow-explanation-panel')).toContainText('1d')
  await expect(page.locator('#newow-details').getByTestId('newow-explanation-panel')).toContainText('60m')
  await page.getByRole('button', { name: '页面比较说明', exact: true }).click()
  await expect(page.getByTestId('newow-comparator-panel')).toContainText('理论平仓')
  await page.getByTestId('newow-comparator-panel').scrollIntoViewIfNeeded()
  await expect(page).toHaveScreenshot('newow-main-rise-explanation-evidence.png', { animations: 'disabled', caret: 'hide', maxDiffPixels: 500 })
  expect(productRequests(fixture, 'explanation')).toHaveLength(1)
  expect(productRequests(fixture, 'comparator')).toHaveLength(1)
  expectExactQuery(productRequests(fixture, 'explanation')[0], { product: 'rb', strategy: 'main_rise', frequency: '60m', series_kind: 'actual_dominant', section: 'explanation', as_of: NEWOW_AS_OF, snapshot_token: 'snapshot:main_rise:60m:fixture-revision-1' })
  expectExactQuery(productRequests(fixture, 'comparator')[0], { product: 'rb', strategy: 'main_rise', frequency: '60m', series_kind: 'actual_dominant', section: 'comparator', as_of: NEWOW_AS_OF, snapshot_token: 'snapshot:main_rise:60m:fixture-revision-1' })
  await showReference(page)
  expect(await page.locator('article[data-reference-category="open"]').innerText()).toBe(openBefore)
  expect(await page.locator('.newow-reference__window input').evaluateAll((inputs) => inputs.map((input) => input.value))).toEqual(windowBefore)
  expect(await chart.getAttribute('data-action-ids')).toBe(actionIdsBefore)
  expect(productRequests(fixture, 'reference')).toHaveLength(1)
  assertNoUnexpectedRequests(fixture)
})

test('replacement disclosure controls support keyboard focus', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page)
  await page.goto(newowRoute())
  const trigger = page.getByRole('button', { name: '策略信息', exact: true })
  await trigger.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(trigger).toBeFocused()
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

test('records raw cold, warm, reuse, rebuild and long-history timings without fixed sleeps', async ({ page }, testInfo) => {
  const samples = []
  const fixture = await installNewowProductFixtures(page, { longHistory: 'trend:60m' })
  const start = performance.now()
  await page.goto(newowRoute('trend', '60m'))
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready')
  samples.push({ metric: 'cold_chart_visible_ms', value: performance.now() - start })
  samples.push({ metric: 'cold_chart_request_dispatch_ms', value: productRequests(fixture, 'chart')[0].startedAt - start })
  const beforeReference = performance.now()
  await showReference(page)
  await expect(page.getByTestId('newow-reference-summary')).toBeVisible()
  samples.push({ metric: 'warm_reference_visible_ms', value: performance.now() - beforeReference })
  samples.push({ metric: 'warm_reference_request_dispatch_ms', value: productRequests(fixture, 'reference')[0].startedAt - beforeReference })
  await page.getByRole('button', { name: '展开详情', exact: true }).click()
  await expect(page.locator('#newow-details').getByTestId('newow-explanation-panel')).toContainText('completed / strict-before')
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
  samples.push({ metric: 'long_history_prepend_ms', value: performance.now() - beforeOlder, initial_bars: 480, prepended_bars: 360 })
  samples.push({ metric: 'long_history_request_dispatch_ms', value: productRequests(fixture, 'chart')[1].startedAt - beforeOlder })

  const strategySwitch = performance.now()
  await page.getByRole('button', { name: '震荡', exact: true }).click()
  await expect(page.getByTestId('newow-product-chart-stage')).toHaveAttribute('data-strategy', 'oscillation')
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready')
  samples.push({ metric: 'strategy_switch_visible_ms', value: performance.now() - strategySwitch })
  samples.push({ metric: 'strategy_switch_request_dispatch_ms', value: productRequests(fixture, 'chart').at(-1).startedAt - strategySwitch })
  const frequencySwitch = performance.now()
  await page.getByRole('button', { name: '1d', exact: true }).click()
  await expect(page.getByTestId('newow-product-chart-stage')).toHaveAttribute('data-frequency', '1d')
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready')
  samples.push({ metric: 'frequency_switch_visible_ms', value: performance.now() - frequencySwitch })
  samples.push({ metric: 'frequency_switch_request_dispatch_ms', value: productRequests(fixture, 'chart').at(-1).startedAt - frequencySwitch })

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
    advisory: ['cold_chart_visible_ms', 'strategy_switch_visible_ms', 'frequency_switch_visible_ms', 'mobile_390_reference_interaction_ms'],
    unmapped: ['already_loaded_reference_reopen_ms', 'auxiliary_cache_reuse_visible_ms', 'long_history_prepend_ms', 'snapshot_rebuild_visible_ms'],
  }
  await testInfo.attach('newow-performance.json', { body: JSON.stringify({ samples, thresholdMapping, environment: { ...environment, node: process.version, platform: `${os.platform()} ${os.release()}`, cpu: os.cpus()[0]?.model } }, null, 2), contentType: 'application/json' })
  console.log(`NEWOW_PERFORMANCE ${JSON.stringify(samples)}`)
  assertNoUnexpectedRequests(fixture)
})
